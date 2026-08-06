"""Lux Aeterna — tests for the resolver: manifest declaration + capability -> active binding."""

from __future__ import annotations

import numpy as np
import pytest
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
        def param_names(self):
            return {"alpha", "beta"}
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


def test_resolve_rejects_unknown_cc_lane_dest():
    # A typo'd cc-lane dest must fail loudly at resolve() (session setup) rather
    # than silently degrade to a per-packet log warning once MIDI starts flowing.
    decl = LightInstrumentDecl(
        instrument="bloom", target="ring", params={},
        lanes=[LightLane("note", "trigger"), LightLane("cc:74", "hveu")])
    with pytest.raises(ValueError) as ei:
        resolve(decl, shroom_capability("ie3"))
    msg = str(ei.value)
    assert "hveu" in msg and "bloom" in msg and "cc:74" in msg   # contextual: dest + instrument + lane


def test_resolve_accepts_known_cc_lane_dest():
    # A valid dest ("hue" is a bloom shared param) still resolves cleanly.
    decl = LightInstrumentDecl(
        instrument="bloom", target="ring", params={},
        lanes=[LightLane("cc:74", "hue")])
    binding = resolve(decl, shroom_capability("ie3"))            # must NOT raise
    assert "cc:74" in binding.routes


def test_resolve_does_not_validate_note_lane_dest():
    # note-source lanes map to obj.noteon, not .set — their dest ("trigger" is not
    # a param name) is intentionally ignored and must never be validated.
    decl = LightInstrumentDecl(
        instrument="bloom", target="ring", params={},
        lanes=[LightLane("note", "trigger")])
    binding = resolve(decl, shroom_capability("ie3"))            # must NOT raise
    assert "note" in binding.routes


def test_resolve_validates_cc_dest_for_light_instrument():
    # The known-param check is uniform across instrument types: a LightInstrument
    # advertises self.params, and a bad cc dest is caught the same way as a synth's.
    from luxaeterna.synth import registry
    from luxaeterna.synth.ugens import Const, SolidColor
    from luxaeterna.synth.instrument import Param, LightInstrument

    def _li_factory(**params):
        color = Const([0.0, 0.0, 0.0])
        return LightInstrument(SolidColor(color), {"color": Param("color", color)})

    registry.register("_li", _li_factory)
    decl = LightInstrumentDecl(
        instrument="_li", target="primary", params={},
        lanes=[LightLane("cc:9", "colour")])                    # British-spelling typo of "color"
    with pytest.raises(ValueError) as ei:
        resolve(decl, shroom_capability("ie3"))
    assert "colour" in str(ei.value)


def test_resolve_aurora_cc_hue_lane_drives_glide():
    # aurora exposes a "hue" param, so a cc:74 -> hue lane resolves and its route
    # drives the colour (the contract the whole smooth-glow design leans on).
    decl = LightInstrumentDecl(
        instrument="aurora", target="primary", params={},
        lanes=[LightLane("cc:74", "hue")])
    binding = resolve(decl, shroom_capability("ie3"))   # must NOT raise
    assert "cc:74" in binding.routes
    binding.routes["cc:74"](0.33)                       # drive hue toward green
    out = None
    for f in range(40):
        out = binding.render(RenderContext(0.0, f, 0.1, np.linspace(0, 1, 12), 12, 3))
    assert out[0, 1] > out[0, 0] and out[0, 1] > out[0, 2]   # glided to green-dominant


def test_resolve_aurora_cc_level_lane_drives_brightness():
    decl = LightInstrumentDecl(
        instrument="aurora", target="primary", params={"hue": 0.33, "level": 1.0},
        lanes=[LightLane("cc:11", "level")])
    binding = resolve(decl, shroom_capability("ie3"))       # must NOT raise
    assert "cc:11" in binding.routes
    for f in range(20):                                     # settle at full
        binding.render(RenderContext(0.0, f, 0.1, np.linspace(0, 1, 12), 12, 3))
    binding.routes["cc:11"](0.2)                            # drive the breath down
    out = None
    for f in range(20, 80):
        out = binding.render(RenderContext(0.0, f, 0.1, np.linspace(0, 1, 12), 12, 3))
    assert out.max() < 0.3                                  # followed the lane down


def test_resolve_aurora_level_lane_without_level_param_raises():
    # A manifest that wants the breath driven must declare the param. Without it
    # aurora self-breathes and has nothing to set, so this is a located failure.
    decl = LightInstrumentDecl(
        instrument="aurora", target="primary", params={"hue": 0.33},
        lanes=[LightLane("cc:11", "level")])
    with pytest.raises(ValueError) as ei:
        resolve(decl, shroom_capability("ie3"))
    assert "level" in str(ei.value)
