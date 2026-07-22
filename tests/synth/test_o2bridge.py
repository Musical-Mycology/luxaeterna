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
