"""Lux Aeterna — built-in instrument presets, registered by name."""

from __future__ import annotations

from . import registry
from .ugens import Const, Envelope, Bloom, Fill, SegmentLevel, Smooth, HueColor, hsv_to_rgb
from .instrument import LightInstrument, LightSynth, Param


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


_GLOW_PARAMS = frozenset({"hue"})


def _make_glow(**params) -> LightInstrument:
    unknown = set(params) - _GLOW_PARAMS
    if unknown:                    # reject typo'd manifest params, don't discard them
        raise KeyError(f"unknown glow param(s) {sorted(unknown)} "
                       f"(known: {sorted(_GLOW_PARAMS)})")
    color = hsv_to_rgb(float(params.get("hue", 0.0)), 1.0, 1.0)
    level = SegmentLevel([(0.0, 0.0), (0.25, 1.0)])   # fade in over 0.25 s, then hold
    return LightInstrument(Fill(level, Const(color)), {})


registry.register("glow", _make_glow)


_AURORA_PARAMS = frozenset({"hue", "level"})

_AURORA_BREATHE = [(0.0, 0.55), (3.0, 1.0), (6.0, 0.55)]   # ~6 s cycle, never dark
_AURORA_HUE_GLIDE_TAU = 0.4                                # seconds
_AURORA_LEVEL_GLIDE_TAU = 0.15                             # seconds


def _make_aurora(**params) -> LightInstrument:
    unknown = set(params) - _AURORA_PARAMS
    if unknown:                    # reject typo'd manifest params, don't discard them
        raise KeyError(f"unknown aurora param(s) {sorted(unknown)} "
                       f"(known: {sorted(_AURORA_PARAMS)})")
    hue = Smooth(Const(float(params.get("hue", 0.0))), _AURORA_HUE_GLIDE_TAU)
    exposed = {"hue": Param("hue", hue)}
    if "level" in params:
        # Declaring level opts into external drive: the breath moves off this
        # preset's private clock and onto whatever cc lane targets it, so a
        # sound engine reading the same controller swells in step with the
        # light. SegmentLevel has no set_target, which is why these are two
        # graphs rather than one.
        level = Smooth(Const(float(params["level"])), _AURORA_LEVEL_GLIDE_TAU)
        exposed["level"] = Param("level", level)
    else:
        level = SegmentLevel(_AURORA_BREATHE, loop_from=0.0)
    return LightInstrument(Fill(level, HueColor(hue)), exposed)


registry.register("aurora", _make_aurora)
