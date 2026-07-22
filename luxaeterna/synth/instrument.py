"""Lux Aeterna — Instrument/Synth layer (client-side composition, mirroring
pyarco's arco_instr.py)."""

from __future__ import annotations

import numpy as np

from .signal import LightUgen, RenderContext


class Param:
    """A named, settable binding backed by a Const/Smooth control uGen."""

    __slots__ = ("name", "ugen")

    def __init__(self, name: str, ugen) -> None:
        self.name = name
        self.ugen = ugen

    def set(self, value) -> None:
        self.ugen.set_target(value)


class LightInstrument:
    """A graph with a designated output field-uGen and named params."""

    def __init__(self, output: LightUgen, params: dict[str, Param]) -> None:
        self.output = output
        self.params = params

    def set(self, name: str, value) -> None:
        if name not in self.params:
            raise KeyError(f"no param {name!r} on instrument")
        self.params[name].set(value)

    def render(self, ctx: RenderContext) -> np.ndarray:
        return self.output.render(ctx)
