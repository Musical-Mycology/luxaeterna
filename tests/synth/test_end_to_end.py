"""Lux Aeterna — end-to-end integration: manifest -> session -> O2 -> engine -> DMX,
plus a performance smoke test for the per-frame render hot path."""

from __future__ import annotations

import time

import numpy as np
from luxaeterna.synth.capability import SurfaceCapability, Zone, shroom_capability
from luxaeterna.synth.manifest import LightManifest
from luxaeterna.synth.session import build_session
from luxaeterna.synth.engine import LightEngine
from luxaeterna.synth.signal import RenderContext
from luxaeterna.universe import Universe


MANIFEST = {
    "instruments": [{
        "instrument": "bloom", "target": "primary", "params": {},
        "lanes": [{"source": "note", "dest": "trigger"},
                  {"source": "cc:74", "dest": "hue"}],
    }]
}


def test_note_over_o2_lights_the_shroom():
    cap = shroom_capability("ie3")
    bindings, bridge = build_session(LightManifest.from_dict(MANIFEST), cap)
    uni_clock = iter([i * 0.02 for i in range(10)]).__next__
    uni = Universe()
    engine = LightEngine(uni, cap, bindings, clock=uni_clock)

    engine.render_into(uni)
    assert max(uni.get_frame()[:36]) == 0                       # dark before note

    bridge.on_midi((0xB0 << 16) | (74 << 8) | 0)                # CC74=0 -> red
    bridge.on_midi((0x90 << 16) | (60 << 8) | 127)              # note-on
    engine.render_into(uni)
    frame = uni.get_frame()[:36]
    assert max(frame) > 0                                        # lit after note

    # GRB order: byte 0 = green, byte 1 = red. Red hue -> red channel dominant.
    reds = frame[1::3]
    greens = frame[0::3]
    assert max(reds) > max(greens)


def test_perf_1000px_within_frame_budget():
    # perf test measures compositing/render cost only: 1000px * 3 channels
    # = 3000 DMX channels, which exceeds one 512-channel universe, so this
    # renders bindings directly rather than pushing through set_range/Universe.
    cap = SurfaceCapability("array", 1000, "GRB", [Zone("primary", 0, 1000)])
    bindings, _bridge = build_session(LightManifest.from_dict(MANIFEST), cap)
    positions = np.linspace(0, 1, 1000)
    for b in bindings:
        b.routes["note"](60, 1.0)

    t0 = time.perf_counter()
    for f in range(44):
        ctx = RenderContext(f / 44, f, 1 / 44, positions, 1000, 3)
        for b in bindings:
            b.render(ctx)
    elapsed = time.perf_counter() - t0

    assert elapsed / 44 < 0.0227          # avg frame < 22.7 ms (44 Hz budget)
