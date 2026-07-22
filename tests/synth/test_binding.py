"""Lux Aeterna — tests for the resolver: manifest declaration + capability -> active binding."""

from __future__ import annotations

import numpy as np
from luxaeterna.synth.manifest import LightInstrumentDecl, LightLane
from luxaeterna.synth.capability import shroom_capability
from luxaeterna.synth.binding import resolve, apply_curve
from luxaeterna.synth.signal import RenderContext


def test_apply_curve():
    assert apply_curve("linear", 0.5) == 0.5
    assert apply_curve("exp", 0.5) == 0.25


def test_resolve_binds_zone_and_routes():
    decl = LightInstrumentDecl(
        instrument="bloom", target="ring", params={},
        lanes=[LightLane("note", "trigger"), LightLane("cc:74", "hue")])
    binding = resolve(decl, shroom_capability("ie3"))
    assert binding.zone.name == "ring" and binding.zone.count == 8
    assert "note" in binding.routes and "cc:74" in binding.routes

    # cc route sets shared hue; note route spawns a voice that lights up
    binding.routes["cc:74"](0.0)                       # red
    binding.routes["note"](60, 1.0)
    ctx = RenderContext(0.0, 0, 0.01, np.linspace(0, 1, 8), 8, 3)
    out = binding.render(ctx)
    assert out.max() > 0.0
