# tests/synth/test_session.py
"""Tests for the LightSession facade: queue-driven lifecycle + MIDI gating."""

from __future__ import annotations

import logging
import time

from luxaeterna.constants import DMX_REFRESH_HZ
from luxaeterna.logutil import ThrottledLog
from luxaeterna.synth import session as session_module
from luxaeterna.synth.capability import shroom_capability
from luxaeterna.synth.events import MidiEvent
from luxaeterna.synth.manifest import LightManifest
from luxaeterna.synth.session import LightSession, build_session
from luxaeterna.universe import Universe

MANIFEST = {
    "bit_name": "e2e", "instruments": [{
        "instrument": "bloom", "target": "primary",
        "lanes": [{"source": "note", "dest": "trigger"},
                  {"source": "cc:74", "dest": "hue"}],
    }]
}

RAINBOW_MANIFEST = {
    "bit_name": "cont", "instruments": [{
        "instrument": "rainbow", "target": "primary",
        # level declared so the breath is externally driven (a constant
        # here) rather than SegmentLevel's local clock, matching how
        # mm-terrarium's TestBit declares the Room rainbow.
        "params": {"hue": 0.0, "level": 1.0, "span": 1.0, "speed": 0.05},
    }],
    "welcome": {"instrument": "glow", "duration": 0.5},
}


def _mk(dt=0.02, steps=600):
    cap = shroom_capability("ie3")
    clk = iter([i * dt for i in range(steps)]).__next__
    return LightSession(cap, clock=clk), Universe()


def _run_until(session, uni, state, limit=400):
    for _ in range(limit):
        session.render_into(uni)
        if session.state == state:
            return
    raise AssertionError(f"never reached {state!r} (at {session.state!r})")


def test_full_lifecycle_idle_loading_running_closing_idle():
    session, uni = _mk()
    assert session.state == "idle"
    session.swap(LightManifest.from_dict(MANIFEST))
    _run_until(session, uni, "running")
    assert session.bit_name == "e2e"
    session.clear()
    session.render_into(uni)
    assert session.state == "closing"
    _run_until(session, uni, "idle")
    assert session.bit_name == ""


def test_midi_dropped_outside_running_dispatched_inside():
    session, uni = _mk()
    session.swap(LightManifest.from_dict(MANIFEST))
    session._bridge.on_midi((0x90 << 16) | (60 << 8) | 127)   # during LOADING
    _run_until(session, uni, "running")
    synth = session._director.bit_bindings[0].obj
    assert not synth.voices                                    # dropped

    session._bridge.on_midi((0x90 << 16) | (60 << 8) | 127)   # while RUNNING
    session.render_into(uni)
    assert synth.voices                                        # dispatched


def test_status_events_route_to_director():
    session, uni = _mk()
    session.notify_disconnect()
    session.render_into(uni)
    assert session.state == "disconnected"
    session.notify_reconnect()
    session.render_into(uni)
    assert session.state == "idle"


def test_build_session_enqueues_initial_swap():
    cap = shroom_capability("ie3")
    clk = iter([i * 0.02 for i in range(600)]).__next__
    session = build_session(LightManifest.from_dict(MANIFEST), cap, clock=clk)
    uni = Universe()
    session.render_into(uni)
    assert session.state == "loading"


def test_midi_capacity_passthrough():
    cap = shroom_capability("ie3")
    clk = iter([i * 0.02 for i in range(10)]).__next__
    session = LightSession(cap, clock=clk, midi_capacity=4)
    for i in range(10):
        session._bridge.on_midi(i)
    assert sum(isinstance(e, MidiEvent) for e in session._queue.drain()) == 4
    assert session._queue.take_dropped() == 6


def test_midi_flood_stays_inside_frame_budget_and_swap_survives():
    # Review regression: 100k-event burst before one frame must neither blow
    # the 44 Hz budget nor drop the queued SwapEvent.
    session, uni = _mk()
    session.swap(LightManifest.from_dict(MANIFEST))
    packed = (0x90 << 16) | (60 << 8) | 127
    for _ in range(100_000):
        session._queue.put(MidiEvent(packed))
    t0 = time.perf_counter()
    session.render_into(uni)
    elapsed = time.perf_counter() - t0
    assert elapsed < 1.0 / DMX_REFRESH_HZ, f"frame took {elapsed * 1000:.1f} ms"
    assert session.state != "idle"           # the SwapEvent was applied
    assert session._queue.drain() == []      # nothing carried to next frame


def test_midi_overflow_warns_throttled(monkeypatch, caplog):
    session, uni = _mk()
    # Fresh throttle: the module-level one is shared process-wide.
    monkeypatch.setattr(session_module, "_throttle",
                        ThrottledLog(session_module.log))
    session.swap(LightManifest.from_dict(MANIFEST))
    packed = (0x90 << 16) | (60 << 8) | 127
    with caplog.at_level(logging.WARNING, logger="luxaeterna.synth.session"):
        for _ in range(1000):
            session._queue.put(MidiEvent(packed))
        session.render_into(uni)             # overflow logged once
        for _ in range(1000):
            session._queue.put(MidiEvent(packed))
        session.render_into(uni)             # second overflow throttled
    overflow = [r for r in caplog.records if "overflow" in r.getMessage()]
    assert len(overflow) == 1
    assert "744" in overflow[0].getMessage()   # 1000 - 256 dropped


def _probe(session):
    """Wrap the engine so each render_into records the (t, dt) the session
    handed it. The engine is the only consumer of t, so this is the seam
    that observes the session's clock contract without a ugen in the way."""
    seen = []
    real = session._engine.render_into

    def spy(universe, bindings, t, dt, frame, gain=1.0):
        seen.append((t, dt))
        return real(universe, bindings, t, dt, frame, gain)

    session._engine.render_into = spy
    return seen


def test_t_is_the_clock_reading_not_elapsed_since_first_render():
    cap = shroom_capability("ie3")
    clk = iter([1000.0, 1000.02, 1000.04]).__next__
    session = LightSession(cap, clock=clk)
    seen = _probe(session)
    uni = Universe()
    for _ in range(3):
        session.render_into(uni)
    assert [t for t, _ in seen] == [1000.0, 1000.02, 1000.04]


def test_two_sessions_first_rendered_at_different_readings_agree_on_t():
    # The property the change exists for: mm-terrarium builds one session
    # per Room fixture, each first rendered at a slightly different instant,
    # and all of them must read the same t for the same clock value.
    cap = shroom_capability("ie3")
    a = LightSession(cap, clock=iter([10.0, 900.0]).__next__)
    b = LightSession(cap, clock=iter([500.0, 900.0]).__next__)
    seen_a, seen_b = _probe(a), _probe(b)
    uni = Universe()
    a.render_into(uni); b.render_into(uni)      # construction skew
    a.render_into(uni); b.render_into(uni)      # the same clock value
    assert seen_a[1][0] == seen_b[1][0] == 900.0


def test_first_frame_dt_is_the_small_constant_and_later_dt_is_the_delta():
    cap = shroom_capability("ie3")
    clk = iter([1000.0, 1000.02, 1000.05]).__next__
    session = LightSession(cap, clock=clk)
    seen = _probe(session)
    uni = Universe()
    for _ in range(3):
        session.render_into(uni)
    dts = [dt for _, dt in seen]
    assert dts[0] == 1e-6
    assert abs(dts[1] - 0.02) < 1e-9
    assert abs(dts[2] - 0.03) < 1e-9


def test_a_stalled_clock_never_yields_a_zero_dt():
    # A frozen or backwards clock (a hub restart resets o2lite time) must
    # not hand ugens dt == 0 or a negative dt: Smooth divides by tau and
    # SegmentLevel integrates dt, so the floor is what keeps them sane.
    cap = shroom_capability("ie3")
    clk = iter([50.0, 50.0, 49.0]).__next__
    session = LightSession(cap, clock=clk)
    seen = _probe(session)
    uni = Universe()
    for _ in range(3):
        session.render_into(uni)
    assert [dt for _, dt in seen] == [1e-6, 1e-6, 1e-6]


def test_full_lifecycle_with_a_large_first_clock_reading():
    # An O2 clock that has been running for a long time before this session
    # was built: welcome (glow) -> running -> close fade -> idle must all
    # complete, because every signature keeps its own dt-integrated clock.
    cap = shroom_capability("ie3")
    clk = iter([1e6 + i * 0.02 for i in range(600)]).__next__
    session = build_session(LightManifest.from_dict(RAINBOW_MANIFEST), cap, clock=clk)
    uni = Universe()
    session.render_into(uni)
    assert session.state == "loading"
    _run_until(session, uni, "running")
    session.clear()
    session.render_into(uni)
    assert session.state == "closing"
    _run_until(session, uni, "idle")


def test_rainbow_frames_agree_across_sessions_at_the_same_clock_value():
    # Two sessions, first rendered 490 s apart (the construction skew two
    # Room fixtures have), both RUNNING, then rendered at the same clock
    # reading: byte-identical frames. Before this slice each session's
    # t started at zero at ITS first frame, so the two rainbows were offset
    # by 490 s of scroll.
    cap = shroom_capability("ie3")

    def running_session(first):
        clk = iter([first + i * 0.02 for i in range(200)] + [5000.0, 5000.02]).__next__
        s = build_session(LightManifest.from_dict(RAINBOW_MANIFEST), cap, clock=clk)
        u = Universe()
        _run_until(s, u, "running")
        return s, u

    a, ua = running_session(10.0)
    b, ub = running_session(500.0)
    # Drain each schedule to its 5000.0 entry so both render at the same
    # clock reading. The session's _last is the previous clock read, which
    # is the cheapest honest way to know which entry was just consumed.
    for s, u in ((a, ua), (b, ub)):
        while s._last != 5000.0:
            s.render_into(u)
    assert ua.get_frame()[:36] == ub.get_frame()[:36]
    assert max(ua.get_frame()[:36]) > 0
    # And it is not a constant frame: one more tick (5000.02) moves the hue.
    a.render_into(ua)
    assert ua.get_frame()[:36] != ub.get_frame()[:36]
