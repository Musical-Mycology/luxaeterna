"""Lux Aeterna — the LightEngine: composite active bindings into a Universe each frame."""

from __future__ import annotations

import numpy as np

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
    """Composites whatever binding list it is handed into DMX bytes.

    Timing (t/dt/frame) is supplied by the caller — the LightSession owns the
    clock, and t is that clock's raw reading (shared across every session on
    the same clock), not seconds since this engine's first frame. Per-binding
    exceptions are swallowed and the offenders returned so the director can
    quarantine repeat failures; one bad binding never costs the rest of the
    surface its frame. Zone positions are cached lazily by zone name because
    the binding list changes at runtime (bit swaps)."""

    def __init__(self, cap: SurfaceCapability) -> None:
        self.cap = cap
        self._channels = channels_for(cap.color_order)
        self._positions: dict[str, np.ndarray] = {}

    def render_into(self, universe, bindings, t: float, dt: float,
                    frame: int, gain: float = 1.0) -> list:
        surface = np.zeros((self.cap.pixel_count, self._channels))
        failed = []
        for b in bindings:
            pos = self._positions.get(b.zone.name)
            if pos is None:
                pos = np.linspace(0, 1, b.zone.count)
                self._positions[b.zone.name] = pos
            ctx = RenderContext(time=t, frame=frame, dt=dt, positions=pos,
                                n=b.zone.count, channels=self._channels)
            try:
                top = b.render(ctx)
            except Exception:
                failed.append(b)
                continue
            sl = slice(b.zone.start, b.zone.start + b.zone.count)
            blend_into(surface, sl, top, b.blend)
        if gain != 1.0:
            surface *= gain
        universe.set_range(0, to_dmx_bytes(surface, self.cap.color_order))
        return failed
