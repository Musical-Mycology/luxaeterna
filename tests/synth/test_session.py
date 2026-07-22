# tests/synth/test_session.py
"""Tests for the LightSession facade: queue-driven lifecycle + MIDI gating."""

from __future__ import annotations

from luxaeterna.synth.capability import shroom_capability
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
