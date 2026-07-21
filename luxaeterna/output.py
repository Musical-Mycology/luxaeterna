"""Lux Aeterna — output loop thread that pushes DMX frames to a backend."""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable

from .backends.base import DMXBackend
from .constants import DMX_REFRESH_HZ
from .universe import Universe

log = logging.getLogger(__name__)


class OutputLoop:
    """Continuously sends the universe's current state to a backend.

    Runs on a daemon thread so it dies automatically if the main
    program exits.  The loop targets *frame_rate* Hz (default 44,
    the DMX512 standard) and skips sending when the universe hasn't
    changed (dirty-flag optimisation).

    Parameters
    ----------
    universe : Universe
        The universe to read frames from.
    backend : DMXBackend
        Where to send frames.
    frame_rate : float
        Target output rate in Hz.
    on_error : callable, optional
        Called with the exception if a send fails.  The loop continues
        regardless.
    always_send : bool
        If True, send every frame even when the universe hasn't changed.
        Useful for backends/fixtures that need continuous refresh.
    """

    def __init__(
        self,
        universe: Universe,
        backend: DMXBackend,
        frame_rate: float = DMX_REFRESH_HZ,
        on_error: Callable[[Exception], None] | None = None,
        always_send: bool = False,
    ) -> None:
        self.universe = universe
        self.backend = backend
        self.frame_interval = 1.0 / frame_rate
        self.on_error = on_error
        self.always_send = always_send

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
            target=self._loop,
            name=f"luxaeterna-output-{self.universe.universe_id}",
            daemon=True,
        )
        self._thread.start()
        log.info("Output loop started for universe %d", self.universe.universe_id)

    def stop(self, timeout: float = 2.0) -> None:
        """Signal the loop to stop and wait for it to finish."""
        if not self._running:
            return
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None
        self.backend.close()
        log.info("Output loop stopped for universe %d", self.universe.universe_id)

    @property
    def running(self) -> bool:
        return self._running

    @property
    def fps(self) -> float:
        """Approximate frames-per-second actually achieved."""
        return self._fps

    def _loop(self) -> None:
        uid = self.universe.universe_id
        interval = self.frame_interval
        frames = 0
        fps_clock = time.monotonic()

        while self._running:
            loop_start = time.monotonic()

            if self.always_send or self.universe.dirty:
                try:
                    frame = self.universe.get_frame()
                    self.backend.send(frame, uid)
                    frames += 1
                except Exception as exc:
                    if self.on_error:
                        self.on_error(exc)
                    else:
                        log.error("Output error on universe %d: %s", uid, exc)

            # FPS tracking (updated once per second)
            now = time.monotonic()
            elapsed_fps = now - fps_clock
            if elapsed_fps >= 1.0:
                self._fps = frames / elapsed_fps
                frames = 0
                fps_clock = now

            # Sleep the remainder of the frame interval
            elapsed = now - loop_start
            sleep_time = interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)
