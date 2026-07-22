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


def test_blend_param_not_leaked_to_instrument_factory():
    import numpy as np
    from luxaeterna.synth import registry

    def _strict_factory(**params):
        if "blend" in params:
            raise TypeError("blend leaked into instrument factory")
        class _Obj:
            def set(self, name, value):
                pass
            def render(self, ctx):
                return np.zeros((ctx.n, ctx.channels))
        return _Obj()

    registry.register("_strict", _strict_factory)
    decl = LightInstrumentDecl(instrument="_strict", target="primary",
                               params={"blend": "over"}, lanes=[])
    binding = resolve(decl, shroom_capability("ie3"))   # must NOT raise
    assert binding.blend == "over"


def test_cc_routes_keep_their_own_lane_dest_and_curve():
    # Two cc lanes with different dest+curve must not collapse onto the last lane
    # (regression guard for the default-argument closure capture in resolve()).
    from luxaeterna.synth import registry
    calls = []

    class _Recorder:
        def set(self, name, value):
            calls.append((name, value))
        def render(self, ctx):
            import numpy as np
            return np.zeros((ctx.n, ctx.channels))

    registry.register("_recorder", lambda **params: _Recorder())
    decl = LightInstrumentDecl(
        instrument="_recorder", target="primary", params={},
        lanes=[LightLane("cc:1", "alpha", "linear"),
               LightLane("cc:2", "beta", "exp")])
    binding = resolve(decl, shroom_capability("ie3"))
    binding.routes["cc:1"](0.5)
    binding.routes["cc:2"](0.5)
    assert ("alpha", 0.5) in calls           # linear curve, own dest
    assert ("beta", 0.25) in calls           # exp curve, own dest
