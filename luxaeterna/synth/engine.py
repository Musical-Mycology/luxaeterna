"""Lux Aeterna — the LightEngine: composite active bindings into a Universe each frame."""

from __future__ import annotations

import time

import numpy as np

from .binding import ActiveBinding
from .capability import SurfaceCapability
from .signal import RenderContext

_CANON = {"R": 0, "G": 1, "B": 2, "W": 3}


def channels_for(color_order: str) -> int:
    return len(color_order)


def to_dmx_bytes(frame: np.ndarray, color_order: str) -> bytearray:
    perm = [_CANON[ch] for ch in color_order]
    reordered = frame[:, perm]
    u8 = np.clip(reordered * 255.0, 0, 255).astype(np.uint8)
    return bytearray(u8.reshape(-1).tobytes())


def blend_into(surface: np.ndarray, sl: slice, top: np.ndarray, mode: str) -> None:
    if mode == "add":
        surface[sl] = np.clip(surface[sl] + top, 0.0, 1.0)
    elif mode == "over":
        surface[sl] = top
    else:
        raise ValueError(f"unknown blend mode {mode!r}")


class LightEngine:
    """Renders every active binding into a shared surface, then pushes the
    composited frame into the Universe as DMX bytes.

    ``clock`` is injectable (defaults to ``time.monotonic``) so tests can
    drive deterministic frame timing.
    """

    def __init__(self, universe, cap: SurfaceCapability,
                 bindings: list[ActiveBinding], clock=time.monotonic) -> None:
        self.universe = universe
        self.cap = cap
        self.bindings = bindings
        self._clock = clock
        self._channels = channels_for(cap.color_order)
        self._frame = 0
        self._start: float | None = None
        self._last: float | None = None
        self._positions = {b.zone.name: np.linspace(0, 1, b.zone.count)
                           for b in bindings}

    def render_into(self, universe) -> None:
        now = self._clock()
        if self._start is None:
            self._start = now
            self._last = now
        t = now - self._start
        dt = max(now - self._last, 1e-6)
        self._last = now

        surface = np.zeros((self.cap.pixel_count, self._channels))
        for b in self.bindings:
            ctx = RenderContext(time=t, frame=self._frame, dt=dt,
                                positions=self._positions[b.zone.name],
                                n=b.zone.count, channels=self._channels)
            top = b.render(ctx)
            sl = slice(b.zone.start, b.zone.start + b.zone.count)
            blend_into(surface, sl, top, b.blend)

        self._frame += 1
        universe.set_range(0, to_dmx_bytes(surface, self.cap.color_order))
