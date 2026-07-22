import numpy as np
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
