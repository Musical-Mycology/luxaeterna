"""Lux Aeterna — a PixelSpan's universes, written and sent as one coherent frame.

``OutputLoop`` drives exactly one ``Universe`` on its own thread. An 864-pixel
array needs seven, and seven independent threads would tear the array: universe 0
of frame N could reach the wire alongside universe 6 of frame N-1.
``MultiUniverseOutputLoop`` sends all of them from one thread per tick instead.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable

from .backends.base import DMXBackend
from .constants import DMX_CHANNELS, DMX_REFRESH_HZ
from .exceptions import ChannelError
from .logutil import ThrottledLog
from .pixelspan import PixelSpan
from .universe import Universe

log = logging.getLogger(__name__)


class UniverseSet:
    """The universes backing one :class:`PixelSpan`."""

    __slots__ = ("span", "universes")

    def __init__(self, span: PixelSpan) -> None:
        self.span = span
        self.universes = [Universe(universe_id=uid) for uid in span.universe_ids]

    def _universe_at(self, universe_id: int) -> Universe:
        return self.universes[universe_id - self.span.start_universe]

    def set_pixels(self, values: bytes | bytearray) -> None:
        """Write the whole strip. *values* must be exactly ``channel_count`` long."""
        expected = self.span.channel_count
        if len(values) != expected:
            raise ChannelError(f"expected {expected} channels, got {len(values)}")
        for index, universe in enumerate(self.universes):
            start = index * DMX_CHANNELS
            chunk = values[start:start + DMX_CHANNELS]
            universe.set_range(0, chunk)
            if len(chunk) < DMX_CHANNELS:
                universe.fill(0, len(chunk), DMX_CHANNELS - len(chunk))

    def fill_pixel(self, pixel_index: int, values: bytes) -> None:
        """Write a single pixel's channels."""
        if len(values) != self.span.channels_per_pixel:
            raise ChannelError(
                f"expected {self.span.channels_per_pixel} channels, "
                f"got {len(values)}")
        universe_id, offset = self.span.locate(pixel_index)
        self._universe_at(universe_id).set_range(offset, values)

    def frames(self) -> list[tuple[int, bytearray]]:
        """Snapshot every universe as ``(universe_id, frame)``."""
        return [(u.universe_id, u.get_frame()) for u in self.universes]

    def reset(self) -> None:
        for universe in self.universes:
            universe.reset()

    def __repr__(self) -> str:
        return f"UniverseSet({self.span!r}, universes={len(self.universes)})"


class MultiUniverseOutputLoop:
    """Send every universe in a :class:`UniverseSet` once per tick, from one thread.

    Parameters mirror :class:`~luxaeterna.output.OutputLoop`, with two
    differences: ``on_frame`` receives the :class:`UniverseSet` rather than a
    single ``Universe``, and ``always_send`` defaults to ``True`` because a
    partially-dirty array must not send a partial frame.
    """

    def __init__(
        self,
        universe_set: UniverseSet,
        backend: DMXBackend,
        frame_rate: float = DMX_REFRESH_HZ,
        on_error: Callable[[Exception], None] | None = None,
        always_send: bool = True,
        on_frame: Callable[[UniverseSet], None] | None = None,
    ) -> None:
        self.universe_set = universe_set
        self.backend = backend
        self.frame_interval = 1.0 / frame_rate
        self.on_error = on_error
        self.always_send = always_send
        self.on_frame = on_frame

        self._throttle = ThrottledLog(log)
        self._running = False
        self._thread: threading.Thread | None = None
        self._fps: float = 0.0

    def start(self) -> None:
        """Open the backend and start the output thread."""
        if self._running:
            return
        self.backend.open()
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, name="luxaeterna-output-multi", daemon=True)
        self._thread.start()
        log.info("Multi-universe output started for %d universes",
                 len(self.universe_set.universes))

    def stop(self, timeout: float = 2.0) -> None:
        """Signal the loop to stop and wait for it to finish."""
        if not self._running:
            return
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None
        self.backend.close()
        log.info("Multi-universe output stopped")

    @property
    def running(self) -> bool:
        return self._running

    @property
    def fps(self) -> float:
        """Approximate full-array frames per second actually achieved."""
        return self._fps

    def _report(self, key: str, message: str, exc: Exception) -> None:
        if self.on_error:
            self.on_error(exc)
        else:
            self._throttle.log(key, logging.ERROR, "%s: %s", message, exc)

    def _loop_once(self) -> int:
        """Run one tick: hook, then sends. Returns the number of universes sent.

        Factored out of ``_loop`` so tests can drive one deterministic tick
        without the background thread, mirroring ``OutputLoop._loop_once``.
        """
        if self.on_frame is not None:
            try:
                self.on_frame(self.universe_set)
            except Exception as exc:
                self._report("on_frame", "on_frame hook error", exc)

        sent = 0
        for universe in self.universe_set.universes:
            # The dirty check MUST precede get_frame(): get_frame() clears the
            # flag, so testing it afterwards would report every universe clean
            # and always_send=False would silently never send anything.
            if not self.always_send and not universe.dirty:
                continue
            frame = universe.get_frame()
            try:
                self.backend.send(frame, universe.universe_id)
                sent += 1
            except Exception as exc:
                self._report(f"send:{universe.universe_id}",
                             f"output error on universe {universe.universe_id}",
                             exc)
        return sent

    def _loop(self) -> None:
        interval = self.frame_interval
        frames = 0
        fps_clock = time.monotonic()

        while self._running:
            loop_start = time.monotonic()

            if self._loop_once():
                frames += 1

            now = time.monotonic()
            elapsed_fps = now - fps_clock
            if elapsed_fps >= 1.0:
                self._fps = frames / elapsed_fps
                frames = 0
                fps_clock = now

            sleep_time = interval - (now - loop_start)
            if sleep_time > 0:
                time.sleep(sleep_time)
