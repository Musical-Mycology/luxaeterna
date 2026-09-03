"""Lux Aeterna — tests for the control-rate uGens."""

from __future__ import annotations

import numpy as np
import pytest
from luxaeterna.synth.signal import RenderContext
from luxaeterna.synth.ugens import Const, Smooth, LFO, Envelope, CCReader, NoteTrigger


def ctx(frame, time=0.0, dt=1 / 44, n=4, channels=3):
    return RenderContext(time, frame, dt, np.linspace(0, 1, n), n, channels)


def test_const_set_target():
    c = Const(0.2)
    assert float(c.render(ctx(0))) == 0.2
    c.set_target(0.8)
    assert float(c.render(ctx(1))) == 0.8


def test_smooth_glides_toward_target():
    s = Smooth(Const(0.0), tau=0.1)
    assert float(s.render(ctx(0))) == 0.0
    s.set_target(1.0)
    v1 = float(s.render(ctx(1, time=1 / 44)))
    v2 = float(s.render(ctx(2, time=2 / 44)))
    assert 0.0 < v1 < v2 < 1.0            # monotonic approach, not yet arrived


def test_lfo_sine_range_and_phase():
    lfo = LFO("sine", hz=1.0)
    lo = float(lfo.render(ctx(0, time=0.0)))       # sin(0) -> 0.5
    hi = float(lfo.render(ctx(1, time=0.25)))      # sin(pi/2) -> 1.0
    assert abs(lo - 0.5) < 1e-6
    assert abs(hi - 1.0) < 1e-6


def test_envelope_attacks_then_finishes_after_release():
    e = Envelope(attack=0.1, decay=0.0, sustain=1.0, release=0.1)
    e.gate_on()
    assert float(e.render(ctx(0, dt=0.05))) > 0.0
    _ = e.render(ctx(1, dt=0.1))                   # reach sustain ~1.0
    e.gate_off()
    e.render(ctx(2, dt=0.05))
    e.render(ctx(3, dt=0.1))                       # release elapsed
    assert e.done


def test_ccreader_holds_latest():
    cc = CCReader()
    cc.set_target(0.6)
    assert float(cc.render(ctx(0))) == 0.6


def test_note_trigger_is_one_shot():
    t = NoteTrigger()
    t.fire(pitch=60, vel=0.9)
    assert float(t.render(ctx(0))) == 0.9
    assert float(t.render(ctx(1))) == 0.0


def test_gate_on_resets_level_for_reuse():
    # A reused Envelope must retrigger from silence: gate_on() resets _level to 0
    # so attack always ramps from 0 (no retrigger click). Only observable on the
    # internal level because _compute overwrites it on the next frame.
    e = Envelope(attack=0.1, decay=0.0, sustain=0.6, release=0.2)
    e.gate_on()
    e.render(ctx(0, dt=0.2))                        # attack completes -> decay(0) -> sustain
    assert float(e.render(ctx(1, dt=0.01))) > 0.5   # sitting at sustain ~0.6
    e.gate_on()                                      # retrigger while still lit
    assert e._level == 0.0


def test_lfo_tri_saw_square_shapes():
    tri = LFO("tri", hz=1.0)
    assert abs(float(tri.render(ctx(0, time=0.0))) - 0.0) < 1e-6   # p=0   -> 0
    assert abs(float(tri.render(ctx(1, time=0.5))) - 1.0) < 1e-6   # p=0.5 -> peak
    saw = LFO("saw", hz=1.0)
    assert abs(float(saw.render(ctx(2, time=0.0))) - 0.0) < 1e-6
    assert abs(float(saw.render(ctx(3, time=0.25))) - 0.25) < 1e-6  # ramps with phase
    sq = LFO("square", hz=1.0)
    assert float(sq.render(ctx(4, time=0.0))) == 1.0               # first half high
    assert float(sq.render(ctx(5, time=0.75))) == 0.0             # second half low


def test_lfo_unknown_shape_raises():
    with pytest.raises(ValueError):
        LFO("wobble", hz=1.0).render(ctx(0))


def test_smooth_tracks_non_const_source():
    src = CCReader(0.0)
    s = Smooth(src, tau=0.05)
    assert float(s.render(ctx(0))) == 0.0
    s.set_target(0.9)                                 # no-op: source isn't a Const
    assert float(s.render(ctx(1, time=1 / 44))) == 0.0   # source still 0 -> stays 0
    src.set_target(1.0)                               # drive the live source directly
    v1 = float(s.render(ctx(2, time=2 / 44)))
    v2 = float(s.render(ctx(3, time=3 / 44)))
    assert 0.0 < v1 < v2 < 1.0                        # glides toward the source


def test_huecolor_maps_hue_to_rgb():
    from luxaeterna.synth.ugens import HueColor, Const
    red = HueColor(Const(0.0)).render(ctx(0))       # hue 0 -> red
    assert red.shape == (3,)
    assert red[0] > red[1] and red[0] > red[2]
    green = HueColor(Const(0.33)).render(ctx(1))    # hue 0.33 -> green
    assert green[1] > green[0] and green[1] > green[2]


def test_huecolor_tracks_changing_hue():
    # Recomputes each frame from its live input, so a Smooth-ed / cc-driven hue
    # is reflected — not cached from construction.
    from luxaeterna.synth.ugens import HueColor, Const
    src = Const(0.0)
    hc = HueColor(src)
    assert hc.render(ctx(0))[0] > hc.render(ctx(0))[1]   # red (byte0 > byte1)
    src.set_target(0.33)
    g = hc.render(ctx(1))                                 # now green
    assert g[1] > g[0] and g[1] > g[2]


def _run(ugen, times, dt=1 / 44):
    return [float(ugen.render(ctx(f, time=t, dt=dt))) for f, t in enumerate(times)]


def test_dt_integrators_ignore_absolute_time():
    # Since the session hands ugens the raw clock reading as t (large, and
    # never starting at zero), anything with a local origin must build it
    # from dt alone. Same dt sequence at t near zero and at t = 1e6 must
    # produce byte-identical output for every dt-integrating control ugen.
    n = 30
    near = [f / 44 for f in range(n)]
    far = [1e6 + f / 44 for f in range(n)]

    def fresh():
        s = Smooth(Const(0.0), tau=0.1)
        e = Envelope(attack=0.1, decay=0.1, sustain=0.5, release=0.2)
        e.gate_on()
        return s, e

    s1, e1 = fresh()
    s1.set_target(1.0)
    s2, e2 = fresh()
    s2.set_target(1.0)
    assert _run(s1, near) == _run(s2, far)
    assert _run(e1, near) == _run(e2, far)


def test_time_readers_depend_only_on_absolute_time():
    # LFO reads ctx.time and nothing else: two instances agree at the same
    # t regardless of what either rendered before. This is the continuity
    # property at the ugen level.
    a = LFO("sine", hz=0.25)
    b = LFO("sine", hz=0.25)
    for f, t in enumerate([0.0, 0.5, 1.0]):
        a.render(ctx(f, time=t))
    va = float(a.render(ctx(3, time=1e6 + 0.3)))
    vb = float(b.render(ctx(0, time=1e6 + 0.3)))
    assert va == vb
