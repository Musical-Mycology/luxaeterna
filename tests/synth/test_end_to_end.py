"""Lux Aeterna — end-to-end integration: manifest -> session -> O2 -> engine ->
DMX, plus a performance smoke test for the full per-frame hot path (queue
drain + director + engine)."""

from __future__ import annotations

import time

from fakes import FakeO2Lite
from luxaeterna.synth.capability import SurfaceCapability, Zone, shroom_capability
from luxaeterna.synth.manifest import LightManifest
from luxaeterna.synth.session import build_session
from luxaeterna.universe import Universe


MANIFEST = {
    "instruments": [{
        "instrument": "bloom", "target": "primary", "params": {"hue": 1.0 / 3.0},   # green default; CC74=0 must drive it to red
        "lanes": [{"source": "note", "dest": "trigger"},
                  {"source": "cc:74", "dest": "hue"}],
    }]
}


def test_note_over_o2_lights_the_shroom():
    cap = shroom_capability("ie3")
    clk = iter([i * 0.02 for i in range(400)]).__next__
    session = build_session(LightManifest.from_dict(MANIFEST), cap, clock=clk)
    fake = FakeO2Lite()
    session.attach(fake)
    uni = Universe()

    for _ in range(200):                            # ride out sys:loaded (1.5 s)
        session.render_into(uni)
        if session.state == "running":
            break
    assert session.state == "running"
    session.render_into(uni)
    assert max(uni.get_frame()[:36]) == 0           # running, dark before note

    fake.deliver("/light/midi", "i", (0xB0 << 16) | (74 << 8) | 0)   # CC74=0 -> red
    fake.deliver("/light/midi", "i", (0x90 << 16) | (60 << 8) | 127) # note-on
    session.render_into(uni)
    frame = uni.get_frame()[:36]
    assert max(frame) > 0                            # lit after note

    # GRB order: byte 0 = green, byte 1 = red. Red hue -> red channel dominant.
    reds = frame[1::3]
    greens = frame[0::3]
    assert max(reds) > max(greens)


def test_perf_1000px_within_frame_budget():
    # 1000 px * 3 ch = 3000 DMX channels > one universe, so measure the full
    # session hot path against a null transport.
    cap = SurfaceCapability("array", 1000, "GRB", [Zone("primary", 0, 1000)])
    clk = iter([i * (1 / 44) for i in range(500)]).__next__
    session = build_session(LightManifest.from_dict(MANIFEST), cap, clock=clk)

    class _NullUniverse:
        def set_range(self, start, values):
            pass

    uni = _NullUniverse()
    for _ in range(200):
        session.render_into(uni)
        if session.state == "running":
            break
    assert session.state == "running"
    session._bridge.on_midi((0x90 << 16) | (60 << 8) | 127)
    session.render_into(uni)

    t0 = time.perf_counter()
    for _ in range(44):
        session.render_into(uni)
    elapsed = time.perf_counter() - t0
    assert elapsed / 44 < 0.0227          # avg frame < 22.7 ms (44 Hz budget)
