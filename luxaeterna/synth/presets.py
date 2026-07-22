"""Lux Aeterna — built-in instrument presets, registered by name."""

from __future__ import annotations

import colorsys

import numpy as np

from . import registry
from .ugens import Const, Envelope, Bloom
from .instrument import LightInstrument, LightSynth


def hsv_to_rgb(h: float, s: float, v: float) -> np.ndarray:
    return np.asarray(colorsys.hsv_to_rgb(h % 1.0, s, v), dtype=float)


def _bloom_voice(pitch: int, vel: float, shared: dict):
    hue = float(shared.get("hue", 0.0))
    color = hsv_to_rgb(hue, 1.0, 1.0) * vel
    center = (pitch % 12) / 11.0
    env = Envelope(attack=0.04, decay=0.12, sustain=0.6, release=0.4)
    out = Bloom(level=env, color=Const(color), center=center)
    return LightInstrument(out, {}), env


_BLOOM_PARAMS = frozenset({"hue"})


def _make_bloom(**params) -> LightSynth:
    unknown = set(params) - _BLOOM_PARAMS
    if unknown:                    # reject typo'd manifest params, don't discard them
        raise KeyError(f"unknown bloom param(s) {sorted(unknown)} "
                       f"(known: {sorted(_BLOOM_PARAMS)})")
    return LightSynth(voice_factory=_bloom_voice, max_voices=8,
                      shared={"hue": params.get("hue", 0.0)})


registry.register("bloom", _make_bloom)
