"""Lux Aeterna — tests for the Param/LightInstrument instrument layer."""

from __future__ import annotations

import numpy as np
from luxaeterna.synth.signal import RenderContext
from luxaeterna.synth.ugens import Const, SolidColor
from luxaeterna.synth.instrument import Param, LightInstrument, LightSynth


def ctx(frame=0, n=3, channels=3):
    return RenderContext(0.0, frame, 1 / 44, np.linspace(0, 1, n), n, channels)


def test_instrument_set_param_changes_output():
    color = Const([0.0, 0.0, 0.0])
    inst = LightInstrument(SolidColor(color), {"color": Param("color", color)})
    assert np.allclose(inst.render(ctx(0))[0], [0, 0, 0])
    inst.set("color", [1.0, 0.0, 0.0])
    assert np.allclose(inst.render(ctx(1))[0], [1, 0, 0])


def test_all_notes_off_gates_every_voice():
    from luxaeterna.synth.presets import _bloom_voice
    synth = LightSynth(voice_factory=_bloom_voice, max_voices=8)
    synth.noteon(60, 1.0)
    synth.noteon(64, 1.0)
    synth.all_notes_off()
    assert len(synth.voices) == 2                    # not dropped — releasing
    for _inst, env in synth.voices.values():
        assert env._stage == "release"
