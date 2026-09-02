"""Tests for the status visual language: Signature wrapper + built-in gestures."""

from __future__ import annotations

import numpy as np
from luxaeterna.synth import registry
from luxaeterna.synth.signal import RenderContext
from luxaeterna.synth.status import (ChannelSweep, GainSignature, Signature,
                                     _sig_error)
from luxaeterna.synth.ugens import Const, Fill, SegmentLevel


def _ctx(f, dt=0.05, n=12, ch=3):
    return RenderContext(time=f * dt, frame=f, dt=dt,
                         positions=np.linspace(0, 1, n), n=n, channels=ch)


def test_segment_level_interpolates():
    lvl = SegmentLevel([(0.0, 0.0), (1.0, 1.0), (2.0, 0.0)])
    v = float(lvl.render(_ctx(0, dt=0.5)))          # local t=0.5
    assert abs(v - 0.5) < 1e-6


def test_segment_level_loops_from_anchor():
    lvl = SegmentLevel([(0.0, 0.0), (1.0, 1.0), (2.0, 0.0)], loop_from=0.0)
    v = None
    for f in range(5):                               # local t reaches 2.5 -> wraps to 0.5
        v = float(lvl.render(_ctx(f, dt=0.5)))
    assert abs(v - 0.5) < 1e-6


def test_fill_scales_color_across_pixels():
    fill = Fill(0.5, Const((1.0, 0.0, 0.0)))
    out = fill.render(_ctx(0))
    assert out.shape == (12, 3)
    np.testing.assert_allclose(out[0], [0.5, 0.0, 0.0])
    np.testing.assert_allclose(out[11], [0.5, 0.0, 0.0])


def test_channel_sweep_walks_channels():
    sweep = ChannelSweep(step=0.5)
    out = sweep.render(_ctx(0, dt=0.1))              # t=0.1 -> channel 0
    assert out[0, 0] == 1.0 and out[0, 1] == 0.0
    for f in range(1, 6):                            # t=0.6 -> channel 1
        out = sweep.render(_ctx(f, dt=0.1))
    assert out[0, 1] == 1.0 and out[0, 0] == 0.0


def test_signature_done_and_neutral_gain():
    sig = Signature(Fill(1.0, Const((0, 1, 0))), duration=1.0)
    sig.advance(0.6)
    assert not sig.done and sig.gain == 1.0
    sig.advance(0.5)
    assert sig.done


def test_gain_signature_ramps_and_never_renders():
    g = GainSignature(0.6)
    assert g.renders is False
    g.advance(0.3)
    assert abs(g.gain - 0.5) < 1e-6
    g.advance(0.4)
    assert g.done and g.gain == 0.0


def test_builtins_registered_and_overridable():
    assert isinstance(registry.build("sys:error"), Signature)
    for name in ("sys:idle", "sys:loaded", "sys:closing", "sys:error",
                 "sys:disconnected", "sys:identify", "sys:selftest"):
        assert isinstance(registry.build(name), Signature)
    try:
        registry.register("sys:error",
                          lambda: Signature(Fill(1.0, Const((0, 0, 1))), 0.1))
        assert registry.build("sys:error").duration == 0.1
    finally:
        registry.register("sys:error", _sig_error)   # restore the built-in


def test_signatures_advance_on_dt_and_render_the_same_at_any_absolute_time():
    # Welcome, loaded, error and the close fade all keep their own elapsed
    # clock from dt. A session whose first t is 1e6 (an O2 clock that has
    # been up for days) must play them exactly as one starting at zero.
    def play(name, offset, frames=40, dt=0.05):
        sig = registry.build(name)
        out = []
        for f in range(frames):
            sig.advance(dt)
            c = RenderContext(time=offset + f * dt, frame=f, dt=dt,
                              positions=np.linspace(0, 1, 12), n=12, channels=3)
            out.append((sig.gain, sig.done,
                        sig.render(c).copy() if sig.renders else None))
        return out

    for name in ("sys:loaded", "sys:error", "sys:closing", "sys:idle",
                 "sys:disconnected", "sys:selftest"):
        near, far = play(name, 0.0), play(name, 1e6)
        for (g1, d1, f1), (g2, d2, f2) in zip(near, far):
            assert (g1, d1) == (g2, d2), name
            if f1 is not None:
                assert np.array_equal(f1, f2), name
