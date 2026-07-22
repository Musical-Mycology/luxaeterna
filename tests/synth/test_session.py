# tests/synth/test_session.py
"""Tests for the LightSession facade: queue-driven lifecycle + MIDI gating."""

from __future__ import annotations

import logging
import time

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
    assert elapsed < 1.0 / 44.0, f"frame took {elapsed * 1000:.1f} ms"
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
