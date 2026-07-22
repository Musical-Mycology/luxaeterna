"""Lux Aeterna — tests for the LightEngine: composite active bindings into a Universe."""

from __future__ import annotations

import numpy as np
import pytest
from luxaeterna.universe import Universe
from luxaeterna.synth.engine import LightEngine, channels_for, to_dmx_bytes, blend_into
from luxaeterna.synth.capability import shroom_capability
from luxaeterna.synth.manifest import LightInstrumentDecl, LightLane
from luxaeterna.synth.binding import resolve, ActiveBinding


def test_channels_and_dmx_byte_order():
    assert channels_for("GRB") == 3
    frame = np.array([[1.0, 0.0, 0.0]])          # pure red, canonical RGB
    out = to_dmx_bytes(frame, "GRB")             # order G,R,B -> 0,255,0
    assert list(out) == [0, 255, 0]


def test_blend_add_and_over():
    surf = np.zeros((2, 3))
    blend_into(surf, slice(0, 2), np.array([[0.5, 0, 0], [0.5, 0, 0]]), "add")
    blend_into(surf, slice(0, 1), np.array([[0.5, 0, 0]]), "add")
    assert surf[0, 0] == 1.0 and surf[1, 0] == 0.5


def test_engine_writes_universe_on_note():
    cap = shroom_capability("ie3")
    binding = resolve(LightInstrumentDecl("bloom", "primary", {},
                                          [LightLane("note", "trigger")]), cap)
    uni = Universe()
    engine = LightEngine(cap)

    engine.render_into(uni, [binding], t=0.0, dt=0.01, frame=0)
    assert max(uni.get_frame()[:36]) == 0
    binding.routes["note"](60, 1.0)
    engine.render_into(uni, [binding], t=0.01, dt=0.01, frame=1)
    assert max(uni.get_frame()[:36]) > 0


def test_engine_isolates_failing_binding_and_reports_it():
    cap = shroom_capability("ie3")
    good = resolve(LightInstrumentDecl("bloom", "primary", {},
                                       [LightLane("note", "trigger")]), cap)
    good.routes["note"](60, 1.0)

    class _Boom:
        def render(self, ctx):
            raise RuntimeError("bad ugen")

    bad = ActiveBinding(obj=_Boom(), zone=cap.zone("ring"), blend="add",
                        routes={})
    uni = Universe()
    engine = LightEngine(cap)
    failed = engine.render_into(uni, [bad, good], t=0.0, dt=0.01, frame=0)
    assert failed == [bad]
    assert max(uni.get_frame()[:36]) > 0        # good binding still rendered


def test_engine_gain_scales_output():
    cap = shroom_capability("ie3")

    def lit_binding():
        b = resolve(LightInstrumentDecl("bloom", "primary", {},
                                        [LightLane("note", "trigger")]), cap)
        b.routes["note"](60, 1.0)
        return b

    uni_full, uni_dim = Universe(), Universe()
    LightEngine(cap).render_into(uni_full, [lit_binding()],
                                 t=0.0, dt=0.01, frame=0)
    LightEngine(cap).render_into(uni_dim, [lit_binding()],
                                 t=0.0, dt=0.01, frame=0, gain=0.25)
    assert 0 < max(uni_dim.get_frame()[:36]) < max(uni_full.get_frame()[:36])


def test_blend_over_replaces_not_adds():
    surf = np.ones((2, 3)) * 0.5
    blend_into(surf, slice(0, 2),
               np.array([[0.2, 0.2, 0.2], [0.3, 0.3, 0.3]]), "over")
    assert surf[0, 0] == 0.2 and surf[1, 0] == 0.3   # replaced, not 0.5 + top


def test_blend_unknown_mode_raises():
    with pytest.raises(ValueError):
        blend_into(np.zeros((1, 3)), slice(0, 1), np.zeros((1, 3)), "screen")
