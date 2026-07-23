"""Lux Aeterna — tests for the authorable instrument presets (glow)."""

from __future__ import annotations

import numpy as np
import pytest

from luxaeterna.synth import registry
from luxaeterna.synth.instrument import LightInstrument
from luxaeterna.synth.signal import RenderContext


def _ctx(frame=0, n=8, channels=3, dt=0.3):
    # dt > glow's 0.25 s fade-in means the very first rendered frame already
    # holds at full level, so brightness assertions don't depend on frame count.
    return RenderContext(time=frame * dt, frame=frame, dt=dt,
                         positions=np.linspace(0, 1, n), n=n, channels=channels)


def test_glow_builds_as_instrument():
    assert isinstance(registry.build("glow", hue=0.1), LightInstrument)


def test_glow_renders_full_field_lit():
    out = registry.build("glow", hue=0.33).render(_ctx(n=8))
    assert out.shape == (8, 3)
    assert out.max(axis=1).min() > 0.0          # every pixel has a lit channel
    np.testing.assert_allclose(out[0], out[7])  # uniform across the whole zone


def test_glow_hue_sets_color():
    out = registry.build("glow", hue=0.33).render(_ctx(n=4))
    assert out[0, 1] > out[0, 0] and out[0, 1] > out[0, 2]   # hue 0.33 -> green-dominant


def test_glow_defaults_to_hue_zero_and_lights():
    out = registry.build("glow").render(_ctx(n=4))
    assert out.max() > 0.0                       # no params still renders (hue=0 -> red)


def test_glow_rejects_unknown_param():
    with pytest.raises(KeyError):
        registry.build("glow", huue=0.5)
