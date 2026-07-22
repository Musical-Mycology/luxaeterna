"""Lux Aeterna — tests for the O2 bridge: packed-int32 MIDI decode + dispatch."""

from __future__ import annotations

import numpy as np
from luxaeterna.synth.manifest import LightInstrumentDecl, LightLane
from luxaeterna.synth.capability import shroom_capability
from luxaeterna.synth.binding import resolve
from luxaeterna.synth.o2bridge import decode_midi, O2Bridge
from luxaeterna.synth.signal import RenderContext


def test_decode_midi_packing():
    packed = (0x90 << 16) | (60 << 8) | 100
    assert decode_midi(packed) == (0x90, 60, 100)


def test_bridge_note_on_lights_binding():
    decl = LightInstrumentDecl("bloom", "primary", {},
                               [LightLane("note", "trigger"), LightLane("cc:74", "hue")])
    binding = resolve(decl, shroom_capability("ie3"))
    bridge = O2Bridge([binding])

    bridge.on_midi((0xB0 << 16) | (74 << 8) | 0)       # CC74 = 0 -> red hue
    bridge.on_midi((0x90 << 16) | (60 << 8) | 127)     # note-on
    ctx = RenderContext(0.0, 0, 0.01, np.linspace(0, 1, 12), 12, 3)
    assert binding.render(ctx).max() > 0.0


def test_note_off_via_bridge_releases_and_prunes_the_voice():
    decl = LightInstrumentDecl("bloom", "primary", {},
                               [LightLane("note", "trigger")])
    binding = resolve(decl, shroom_capability("ie3"))
    bridge = O2Bridge([binding])

    def _ctx(f):
        return RenderContext(time=f * 0.05, frame=f, dt=0.05,
                             positions=np.linspace(0, 1, 12), n=12, channels=3)

    bridge.on_midi((0x90 << 16) | (60 << 8) | 127)     # note-on pitch 60
    for f in range(5):
        binding.render(_ctx(f))
    assert binding.obj.voices                           # voice sustaining (gate still on)

    bridge.on_midi((0x80 << 16) | (60 << 8) | 0)        # note-off pitch 60
    for f in range(5, 20):
        binding.render(_ctx(f))                         # advance past the 0.4s release
    assert not binding.obj.voices                       # released + pruned -> note-off worked
