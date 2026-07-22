"""Lux Aeterna — tests for the LightSynth voice pool, registry, and bloom preset."""

from __future__ import annotations

import numpy as np
from luxaeterna.synth.signal import RenderContext
from luxaeterna.synth import registry, presets  # noqa: F401  (import registers presets)


def ctx(frame, dt=1 / 44, n=8, channels=3, time=0.0):
    return RenderContext(time, frame, dt, np.linspace(0, 1, n), n, channels)


def test_noteon_produces_light_then_fades_after_noteoff():
    synth = registry.build("bloom")
    synth.noteon(pitch=60, vel=1.0, note_id=1)
    frame0 = synth.render(ctx(0, dt=0.05))
    assert frame0.max() > 0.0                       # note-on lit something
    synth.noteoff(1)
    for f in range(1, 40):                           # advance well past release
        synth.render(ctx(f, dt=0.05, time=f * 0.05))
    assert synth.render(ctx(40, dt=0.05)).max() == 0.0
    assert len(synth.voices) == 0                    # voice pruned


def test_retrigger_existing_note_does_not_evict_others():
    synth = registry.build("bloom")               # max_voices=8
    for pid in range(8):
        synth.noteon(pid, 1.0, note_id=pid)        # fill pool with ids 0..7
    synth.noteon(3, 1.0, note_id=3)                # retrigger an already-present id
    # retriggering an existing note must not evict anyone (the pool didn't grow)
    assert len(synth.voices) == 8
    assert 0 in synth.voices                        # the true-oldest must NOT be wrongly evicted


def test_hue_set_recolors_new_voice():
    synth = registry.build("bloom")
    synth.set("hue", 1.0 / 3.0)                       # green (default hue is 0.0 = red)
    synth.noteon(60, 1.0, note_id=1)
    green = synth.render(ctx(0, dt=0.01))
    assert green[:, 1].max() > green[:, 0].max()      # more green than red -> .set() took effect
