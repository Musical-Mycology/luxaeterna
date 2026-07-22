"""Tests for the StatusDirector: session state machine + signature lifecycle."""

from __future__ import annotations

from luxaeterna.synth.capability import shroom_capability
from luxaeterna.synth.director import (CLOSING, DISCONNECTED, ERROR, IDLE,
                                       LOADING, QUARANTINE_FRAMES, RUNNING,
                                       SELFTEST, StatusDirector)
from luxaeterna.synth.manifest import LightManifest

MANIFEST = LightManifest.from_dict({
    "bit_name": "testbit", "role": "melody",
    "instruments": [{"instrument": "bloom", "target": "primary",
                     "lanes": [{"source": "note", "dest": "trigger"}]}],
})


def _mk():
    return StatusDirector(shroom_capability("ie3"))


def _run(d, seconds, dt=0.05):
    for _ in range(int(seconds / dt)):
        d.frame(dt)


def test_boots_idle_with_a_signature():
    d = _mk()
    assert d.state == IDLE
    render, gain = d.frame(0.05)
    assert len(render) == 1 and gain == 1.0


def test_swap_from_idle_loads_then_runs():
    d = _mk()
    d.swap(MANIFEST)
    assert d.state == LOADING and d.bit_name == "testbit"
    _run(d, 2.0)                                     # sys:loaded lasts 1.5 s
    assert d.state == RUNNING
    render, _ = d.frame(0.05)
    assert render == d.bit_bindings                  # bit alone on the surface


def test_swap_from_running_fades_then_reloads():
    d = _mk()
    d.swap(MANIFEST)
    _run(d, 2.0)
    d.swap(MANIFEST)
    assert d.state == CLOSING
    render, gain = d.frame(0.05)
    assert render and 0.0 < gain < 1.0               # old bit rendering, fading
    _run(d, 1.0)                                     # 0.6 s fade elapses
    assert d.state in (LOADING, RUNNING)


def test_latest_swap_wins_during_closing():
    d = _mk()
    d.swap(MANIFEST)
    _run(d, 2.0)
    m2 = LightManifest.from_dict({"bit_name": "second", "instruments": [
        {"instrument": "bloom", "target": "primary"}]})
    m3 = LightManifest.from_dict({"bit_name": "third", "instruments": [
        {"instrument": "bloom", "target": "primary"}]})
    d.swap(m2)
    d.swap(m3)
    _run(d, 3.0)
    assert d.bit_name == "third"


def test_welcome_replaces_generic_loaded():
    m = LightManifest.from_dict({
        "instruments": [{"instrument": "bloom", "target": "primary"}],
        "welcome": {"instrument": "bloom", "duration": 0.2}})
    d = _mk()
    d.swap(m)                                        # short welcome (a dark synth
    assert d.state == LOADING                        # is fine — only timing matters)
    _run(d, 0.4)
    assert d.state == RUNNING


def test_resolve_failure_goes_error_then_idle():
    bad = LightManifest.from_dict({
        "instruments": [{"instrument": "no-such-instrument",
                         "target": "primary"}]})
    d = _mk()
    d.swap(bad)
    assert d.state == ERROR
    _run(d, 2.0)                                     # sys:error lasts 1.6 s
    assert d.state == IDLE


def test_clear_fades_to_idle():
    d = _mk()
    d.swap(MANIFEST)
    _run(d, 2.0)
    d.clear()
    assert d.state == CLOSING
    _run(d, 1.0)
    assert d.state == IDLE and not d.bit_bindings


def test_disconnect_drops_bit_and_reconnect_loads_pending():
    d = _mk()
    d.swap(MANIFEST)
    _run(d, 2.0)
    d.disconnect()
    assert d.state == DISCONNECTED and not d.bit_bindings
    d.swap(MANIFEST)                                 # arrives while disconnected
    d.reconnect()
    assert d.state == LOADING


def test_reconnect_without_pending_goes_idle():
    d = _mk()
    d.disconnect()
    d.reconnect()
    assert d.state == IDLE


def test_selftest_gated_by_state_and_restores():
    d = _mk()
    d.selftest()
    assert d.state == SELFTEST
    _run(d, 2.5)                                     # sweep lasts 2.0 s
    assert d.state == IDLE
    d.swap(MANIFEST)
    _run(d, 2.0)
    d.selftest()                                     # ignored while running
    assert d.state == RUNNING


def test_identify_overlays_without_state_change():
    d = _mk()
    d.identify(duration=0.2)
    render, _ = d.frame(0.05)
    assert d.state == IDLE and len(render) == 2      # idle sig + overlay
    _run(d, 0.5)
    render, _ = d.frame(0.05)
    assert len(render) == 1                          # overlay done


def test_quarantine_then_error_escalation():
    d = _mk()
    d.swap(MANIFEST)
    _run(d, 2.0)
    assert d.state == RUNNING
    b = d.bit_bindings[0]
    for _ in range(QUARANTINE_FRAMES):
        d.frame(0.05)
        d.note_failures([b])
    assert not d.bit_bindings
    assert d.state == ERROR
