"""Lux Aeterna — tests for the Param/LightInstrument instrument layer."""

from __future__ import annotations

import numpy as np
from luxaeterna.synth.signal import RenderContext
from luxaeterna.synth.ugens import Const, SolidColor
from luxaeterna.synth.instrument import Param, LightInstrument


def ctx(frame=0, n=3, channels=3):
    return RenderContext(0.0, frame, 1 / 44, np.linspace(0, 1, n), n, channels)


def test_instrument_set_param_changes_output():
    color = Const([0.0, 0.0, 0.0])
    inst = LightInstrument(SolidColor(color), {"color": Param("color", color)})
    assert np.allclose(inst.render(ctx(0))[0], [0, 0, 0])
    inst.set("color", [1.0, 0.0, 0.0])
    assert np.allclose(inst.render(ctx(1))[0], [1, 0, 0])
