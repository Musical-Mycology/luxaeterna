"""Lux Aeterna — signal core: the LightUgen base and per-frame render context."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class RenderContext:
    """Everything a uGen needs to compute one frame.

    ``positions`` is normalized 0..1 across the *bound zone* (length ``n``);
    ``channels`` is the surface's colour width (3 = RGB, 4 = RGBW).
    """
    time: float
    frame: int
    dt: float
    positions: np.ndarray
    n: int
    channels: int


class LightUgen:
    """Base unit generator. Subclasses implement ``_compute``.

    ``render`` memoizes on ``ctx.frame`` so a node pulled by several consumers
    computes once per frame (the analog of Arco's ``run(block_count)`` trick).
    """

    rate: str = "control"  # "control" (per-frame scalar) | "field" (per-pixel array)

    def __init__(self) -> None:
        self._cache_frame: int = -1
        self._cache_val: np.ndarray | None = None

    def render(self, ctx: RenderContext) -> np.ndarray:
        if ctx.frame != self._cache_frame or self._cache_val is None:
            self._cache_val = self._compute(ctx)
            self._cache_frame = ctx.frame
        return self._cache_val

    def _compute(self, ctx: RenderContext) -> np.ndarray:
        raise NotImplementedError


class _Literal(LightUgen):
    """Wraps a constant scalar/array as a control-rate uGen."""

    rate = "control"

    def __init__(self, value) -> None:
        super().__init__()
        self._value = np.asarray(value, dtype=float)

    def _compute(self, ctx: RenderContext) -> np.ndarray:
        return self._value


def as_ugen(x) -> LightUgen:
    """Return ``x`` if it is a LightUgen, else wrap it in a ``_Literal``."""
    return x if isinstance(x, LightUgen) else _Literal(x)
