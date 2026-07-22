# tests/synth/test_o2bridge.py
"""Lux Aeterna — tests for the O2 bridge: decode, enqueue, attach contract,
and per-binding dispatch isolation."""

from __future__ import annotations

import pytest
from fakes import FakeO2Lite
from luxaeterna.synth.manifest import LightInstrumentDecl, LightLane
from luxaeterna.synth.capability import shroom_capability
from luxaeterna.synth.binding import resolve
from luxaeterna.synth.o2bridge import O2Bridge, decode_midi, dispatch_midi


def test_decode_midi_packing():
    packed = (0x90 << 16) | (60 << 8) | 100
    assert decode_midi(packed) == (0x90, 60, 100)


def test_on_midi_enqueues_packed_int():
    got = []
    bridge = O2Bridge(got.append)
    bridge.on_midi((0x90 << 16) | (60 << 8) | 100)
    assert got == [(0x90 << 16) | (60 << 8) | 100]


def test_attach_matches_real_o2litepy_contract():
    fake = FakeO2Lite()
    got = []
    bridge = O2Bridge(got.append)
    bridge.attach(fake, "/light/midi")
    assert len(fake.handlers) == 1
    fake.deliver("/light/midi", "i", (0xB0 << 16) | (74 << 8) | 64)
    assert got == [(0xB0 << 16) | (74 << 8) | 64]


def test_double_attach_raises():
    fake = FakeO2Lite()
    bridge = O2Bridge(lambda p: None)
    bridge.attach(fake)
    with pytest.raises(RuntimeError):
        bridge.attach(fake)


def test_dispatch_isolates_bad_route():
    class _BoomBinding:
        routes = {"note": (lambda *a: (_ for _ in ()).throw(RuntimeError("bad")))}
        obj = object()

    decl = LightInstrumentDecl("bloom", "primary", {},
                               [LightLane("note", "trigger")])
    good = resolve(decl, shroom_capability("ie3"))
    dispatch_midi([_BoomBinding(), good], 0x90, 60, 127)   # must not raise
    assert good.obj.voices                                  # good binding got the note
