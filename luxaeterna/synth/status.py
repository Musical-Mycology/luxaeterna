"""Lux Aeterna — status visual language: Signature wrapper + built-in sys:*
gestures. Every gesture is an ordinary instrument built from the uGen
vocabulary and registered by name, so installations can reskin any of them by
re-registering. Reserved for future gameserver verbs (names only, no v1
implementation): sys:role-adopted, sys:role-denied, sys:goodbye."""

from __future__ import annotations

import math

import numpy as np

from . import registry
from .signal import LightUgen, RenderContext, as_ugen
from .ugens import Const, Noise


class Signature:
    """A status gesture: an instrument plus a duration clock the director
    advances. ``duration=math.inf`` loops forever (idle/disconnected)."""

    renders = True

    def __init__(self, instrument, duration: float) -> None:
        self.instrument = instrument
        self.duration = float(duration)
        self.elapsed = 0.0

    def advance(self, dt: float) -> None:
        self.elapsed += dt

    @property
    def done(self) -> bool:
        return self.elapsed >= self.duration

    @property
    def gain(self) -> float:
        return 1.0

    def render(self, ctx: RenderContext) -> np.ndarray:
        return self.instrument.render(ctx)


class GainSignature(Signature):
    """Renders nothing; produces the global 1→0 gain ramp (the close fade
    applied over the retained bit surface)."""

    renders = False

    def __init__(self, duration: float) -> None:
        super().__init__(None, duration)

    @property
    def gain(self) -> float:
        if self.duration <= 0:
            return 0.0
        return max(0.0, 1.0 - self.elapsed / self.duration)


class SegmentLevel(LightUgen):
    """Piecewise-linear level over local time (advanced by ctx.dt, memoized
    per frame like Envelope). With ``loop_from`` set, time wraps back there
    after the last point — blink-then-breathe patterns loop forever."""

    rate = "control"

    def __init__(self, points, loop_from: float | None = None) -> None:
        super().__init__()
        self._xs = np.asarray([p[0] for p in points], dtype=float)
        self._ys = np.asarray([p[1] for p in points], dtype=float)
        self._loop_from = loop_from
        self._t = 0.0

    def _compute(self, ctx: RenderContext) -> np.ndarray:
        self._t += ctx.dt
        t = self._t
        end = self._xs[-1]
        if self._loop_from is not None and t > end:
            span = end - self._loop_from
            t = self._loop_from + ((t - self._loop_from) % span)
        return np.asarray(np.interp(t, self._xs, self._ys))


class Fill(LightUgen):
    """level * color across every pixel — SolidColor with a brightness input."""

    rate = "field"

    def __init__(self, level, color) -> None:
        super().__init__()
        self._level = as_ugen(level)
        self._color = as_ugen(color)

    def _compute(self, ctx: RenderContext) -> np.ndarray:
        level = float(np.asarray(self._level.render(ctx)))
        c = np.asarray(self._color.render(ctx), dtype=float).reshape(-1)
        if c.shape[0] < ctx.channels:
            c = np.concatenate([c, np.zeros(ctx.channels - c.shape[0])])
        return np.clip(level * np.tile(c[:ctx.channels], (ctx.n, 1)), 0.0, 1.0)


class ChannelSweep(LightUgen):
    """One full-brightness channel at a time — the R→G→B(→W) wiring self-test
    that instantly exposes color-order mistakes."""

    rate = "field"

    def __init__(self, step: float = 0.5) -> None:
        super().__init__()
        self._step = float(step)
        self._t = 0.0

    def _compute(self, ctx: RenderContext) -> np.ndarray:
        self._t += ctx.dt
        ch = int(self._t / self._step) % ctx.channels
        out = np.zeros((ctx.n, ctx.channels))
        out[:, ch] = 1.0
        return out


WHITE = (1.0, 1.0, 1.0)
GREEN = (0.0, 1.0, 0.0)
RED = (1.0, 0.0, 0.0)
IDLE_TINT = (0.25, 0.25, 0.35)          # dim blue-white


def _sig_idle() -> Signature:
    lvl = SegmentLevel([(0.0, 0.05), (2.0, 0.30), (4.0, 0.05)], loop_from=0.0)
    return Signature(Fill(lvl, Const(IDLE_TINT)), math.inf)


def _sig_loaded() -> Signature:
    pts = [(0.0, 0.0), (0.05, 1.0), (0.30, 0.10), (0.55, 0.55),
           (0.85, 0.05), (1.10, 0.45), (1.50, 0.0)]     # flash + 2 soft pulses
    return Signature(Fill(SegmentLevel(pts), Const(GREEN)), 1.5)


def _sig_closing() -> GainSignature:
    return GainSignature(0.6)


def _sig_error() -> Signature:
    pts = [(0.0, 0.0), (0.45, 1.0), (0.95, 1.0), (1.60, 0.0)]  # rise-hold-fall
    return Signature(Fill(SegmentLevel(pts), Const(RED)), 1.6)


def _sig_disconnected() -> Signature:
    pts = [(0.0, 0.0), (0.10, 1.0), (0.20, 0.0), (0.30, 1.0), (0.40, 0.0),
           (1.00, 0.0), (2.50, 0.25), (4.00, 0.0)]      # double-blink, then breathe
    return Signature(Fill(SegmentLevel(pts, loop_from=1.0), Const(RED)), math.inf)


def _sig_identify() -> Signature:
    return Signature(Noise(Const(WHITE), scale=2.0, speed=3.0), 3.0)


def _sig_selftest() -> Signature:
    return Signature(ChannelSweep(step=0.5), 2.0)


def register_builtin_signatures() -> None:
    registry.register("sys:idle", _sig_idle)
    registry.register("sys:loaded", _sig_loaded)
    registry.register("sys:closing", _sig_closing)
    registry.register("sys:error", _sig_error)
    registry.register("sys:disconnected", _sig_disconnected)
    registry.register("sys:identify", _sig_identify)
    registry.register("sys:selftest", _sig_selftest)


register_builtin_signatures()
