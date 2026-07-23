"""feed_midi injects MIDI as if it arrived over o2lite — for device sims/tests
with no live o2lite client. It reaches instruments only while RUNNING."""

from __future__ import annotations

from luxaeterna.synth.capability import shroom_capability
from luxaeterna.synth.manifest import LightManifest
from luxaeterna.synth.session import build_session
from luxaeterna.universe import Universe

MANIFEST = {
    "instruments": [{
        "instrument": "bloom", "target": "primary", "params": {"hue": 1.0 / 3.0},
        "lanes": [{"source": "note", "dest": "trigger"},
                  {"source": "cc:74", "dest": "hue"}],
    }]
}


def _to_running(session, uni):
    for _ in range(200):
        session.render_into(uni)
        if session.state == "running":
            return
    raise AssertionError("session never reached RUNNING")


def test_feed_midi_note_lights_the_instrument_when_running():
    clk = iter([i * (1 / 44) for i in range(400)]).__next__
    session = build_session(LightManifest.from_dict(MANIFEST),
                            shroom_capability(), clock=clk)
    uni = Universe()
    _to_running(session, uni)
    session.render_into(uni)
    assert max(uni.get_frame()[:36]) == 0          # dark before any note

    session.feed_midi(0x90, 60, 100)               # note-on
    session.render_into(uni)
    assert max(uni.get_frame()[:36]) > 0           # lit after feed_midi
