"""Lux Aeterna — the light-uGen vocabulary (control-rate primitives, then
field-rate primitives that render a whole zone per frame)."""

from __future__ import annotations

import math

import numpy as np

from .signal import LightUgen, RenderContext, as_ugen


class Const(LightUgen):
    rate = "control"

    def __init__(self, value) -> None:
        super().__init__()
        self._value = np.asarray(value, dtype=float)

    def set_target(self, value) -> None:
        self._value = np.asarray(value, dtype=float)
        self._cache_frame = -1  # invalidate memo

    def _compute(self, ctx: RenderContext) -> np.ndarray:
        return self._value


class Smooth(LightUgen):
    """One-pole glide toward the source value (Arco's Smoothb analog)."""

    rate = "control"

    def __init__(self, source, tau: float) -> None:
        super().__init__()
        self._source = as_ugen(source)
        self._tau = float(tau)
        self._prev: np.ndarray | None = None

    def set_target(self, value) -> None:
        if isinstance(self._source, Const):
            self._source.set_target(value)

    def _compute(self, ctx: RenderContext) -> np.ndarray:
        target = np.asarray(self._source.render(ctx), dtype=float)
        if self._prev is None:
            self._prev = target
        else:
            alpha = 1.0 if self._tau <= 0 else 1.0 - math.exp(-ctx.dt / self._tau)
            self._prev = self._prev + alpha * (target - self._prev)
        return self._prev


class LFO(LightUgen):
    rate = "control"

    def __init__(self, shape: str, hz: float, phase: float = 0.0) -> None:
        super().__init__()
        self._shape = shape
        self._hz = float(hz)
        self._phase = float(phase)

    def _compute(self, ctx: RenderContext) -> np.ndarray:
        p = (self._hz * ctx.time + self._phase) % 1.0
        if self._shape == "sine":
            v = 0.5 + 0.5 * math.sin(2 * math.pi * p)
        elif self._shape == "tri":
            v = 1.0 - abs(2.0 * p - 1.0)
        elif self._shape == "saw":
            v = p
        elif self._shape == "square":
            v = 1.0 if p < 0.5 else 0.0
        else:
            raise ValueError(f"unknown LFO shape {self._shape!r}")
        return np.asarray(v)


class Envelope(LightUgen):
    """Gated ADSR. ``gate_on`` starts A→D→S; ``gate_off`` starts R; ``done``
    is True once release has fully elapsed."""

    rate = "control"

    def __init__(self, attack: float, decay: float, sustain: float, release: float) -> None:
        super().__init__()
        self._a, self._d, self._s, self._r = map(float, (attack, decay, sustain, release))
        self._stage = "idle"   # idle|attack|decay|sustain|release|done
        self._level = 0.0
        self._t = 0.0          # seconds in current stage

    def gate_on(self) -> None:
        self._stage = "attack"
        self._t = 0.0

    def gate_off(self) -> None:
        if self._stage not in ("idle", "done"):
            self._stage = "release"
            self._t = 0.0
            self._rel_from = self._level

    @property
    def done(self) -> bool:
        return self._stage == "done"

    def _compute(self, ctx: RenderContext) -> np.ndarray:
        self._t += ctx.dt
        if self._stage == "attack":
            self._level = 1.0 if self._a <= 0 else min(1.0, self._t / self._a)
            if self._level >= 1.0:
                self._stage, self._t = "decay", 0.0
        elif self._stage == "decay":
            frac = 1.0 if self._d <= 0 else min(1.0, self._t / self._d)
            self._level = 1.0 + frac * (self._s - 1.0)
            if frac >= 1.0:
                self._stage = "sustain"
        elif self._stage == "sustain":
            self._level = self._s
        elif self._stage == "release":
            frac = 1.0 if self._r <= 0 else min(1.0, self._t / self._r)
            self._level = self._rel_from * (1.0 - frac)
            if frac >= 1.0:
                self._stage, self._level = "done", 0.0
        return np.asarray(self._level)


class CCReader(LightUgen):
    rate = "control"

    def __init__(self, initial: float = 0.0) -> None:
        super().__init__()
        self._value = float(initial)

    def set_target(self, value) -> None:
        self._value = float(value)
        self._cache_frame = -1

    def _compute(self, ctx: RenderContext) -> np.ndarray:
        return np.asarray(self._value)


class NoteTrigger(LightUgen):
    """One-shot: outputs ``vel`` on the frame after ``fire``, then 0."""

    rate = "control"

    def __init__(self) -> None:
        super().__init__()
        self._pending: float | None = None
        self._value = 0.0

    def fire(self, pitch: int, vel: float) -> None:
        self._pending = float(vel)
        self._cache_frame = -1

    def _compute(self, ctx: RenderContext) -> np.ndarray:
        if self._pending is not None:
            self._value, self._pending = self._pending, None
        else:
            self._value = 0.0
        return np.asarray(self._value)


def _broadcast_color(color_val: np.ndarray, n: int, channels: int) -> np.ndarray:
    c = np.asarray(color_val, dtype=float).reshape(-1)
    if c.shape[0] < channels:        # pad (e.g. RGB color on RGBW surface)
        c = np.concatenate([c, np.zeros(channels - c.shape[0])])
    return np.tile(c[:channels], (n, 1))


class SolidColor(LightUgen):
    rate = "field"

    def __init__(self, color) -> None:
        super().__init__()
        self._color = as_ugen(color)

    def _compute(self, ctx: RenderContext) -> np.ndarray:
        return _broadcast_color(self._color.render(ctx), ctx.n, ctx.channels)


class Gradient(LightUgen):
    rate = "field"

    def __init__(self, stops) -> None:
        super().__init__()
        self._pos = np.asarray([s[0] for s in stops], dtype=float)
        self._cols = np.asarray([s[1] for s in stops], dtype=float)

    def _compute(self, ctx: RenderContext) -> np.ndarray:
        out = np.empty((ctx.n, ctx.channels))
        for ch in range(ctx.channels):
            col = self._cols[:, ch] if ch < self._cols.shape[1] else np.zeros(len(self._pos))
            out[:, ch] = np.interp(ctx.positions, self._pos, col)
        return out


class PaletteMap(LightUgen):
    rate = "field"

    def __init__(self, index, palette) -> None:
        super().__init__()
        self._index = as_ugen(index)
        self._palette = np.asarray(palette, dtype=float)

    def _compute(self, ctx: RenderContext) -> np.ndarray:
        idx = float(np.asarray(self._index.render(ctx)))
        m = self._palette.shape[0]
        pos = np.clip(idx, 0.0, 1.0) * (m - 1)
        lo, hi = int(np.floor(pos)), min(int(np.ceil(pos)), m - 1)
        frac = pos - lo
        color = self._palette[lo] * (1 - frac) + self._palette[hi] * frac
        return _broadcast_color(color, ctx.n, ctx.channels)


class Bloom(LightUgen):
    """Gaussian bloom around ``center`` that widens and brightens with ``level``."""

    rate = "field"

    def __init__(self, level, color, center: float = 0.5) -> None:
        super().__init__()
        self._level = as_ugen(level)
        self._color = as_ugen(color)
        self._center = float(center)

    def _compute(self, ctx: RenderContext) -> np.ndarray:
        level = float(np.asarray(self._level.render(ctx)))
        color = np.asarray(self._color.render(ctx), dtype=float).reshape(-1)[:ctx.channels]
        width = 0.08 + 0.5 * level
        falloff = np.exp(-((ctx.positions - self._center) / width) ** 2)
        intensity = np.clip(level * falloff, 0.0, 1.0)
        return intensity[:, None] * color[None, :]


class Noise(LightUgen):
    rate = "field"

    def __init__(self, color, scale: float, speed: float) -> None:
        super().__init__()
        self._color = as_ugen(color)
        self._scale = float(scale)
        self._speed = float(speed)

    def _compute(self, ctx: RenderContext) -> np.ndarray:
        phase = ctx.positions * self._scale + ctx.time * self._speed
        intensity = 0.5 + 0.5 * np.sin(2 * np.pi * phase)
        color = np.asarray(self._color.render(ctx), dtype=float).reshape(-1)[:ctx.channels]
        return np.clip(intensity[:, None] * color[None, :], 0.0, 1.0)
