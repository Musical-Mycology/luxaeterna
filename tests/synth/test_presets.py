"""Lux Aeterna — tests for the authorable instrument presets (glow)."""

from __future__ import annotations

import colorsys

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


def _out_hue(pixel):
    return colorsys.rgb_to_hsv(float(pixel[0]), float(pixel[1]), float(pixel[2]))[0]


def test_aurora_renders_full_field_lit():
    out = registry.build("aurora", hue=0.33).render(_ctx(n=8, dt=0.3))
    assert out.shape == (8, 3)
    assert out.max(axis=1).min() > 0.0            # every pixel lit
    np.testing.assert_allclose(out[0], out[7])    # uniform across the zone


def test_aurora_breathes_and_never_dark():
    a = registry.build("aurora", hue=0.0)
    brights = [a.render(_ctx(frame=f, n=4, dt=0.5)).max() for f in range(14)]  # ~0.5–7 s
    assert max(brights) - min(brights) > 0.1      # brightness oscillates (breathe)
    assert min(brights) > 0.0                     # never fully dark


def test_aurora_hue_glides_toward_target_not_snap():
    a = registry.build("aurora", hue=0.0)
    a.render(_ctx(frame=0, n=4, dt=0.1))          # settle at hue 0 (red)
    a.set("hue", 0.33)                            # green target
    h1 = _out_hue(a.render(_ctx(frame=1, n=4, dt=0.1))[0])
    last = None
    for f in range(2, 40):
        last = a.render(_ctx(frame=f, n=4, dt=0.1))
    hN = _out_hue(last[0])
    assert 0.0 < h1 < 0.33                        # started gliding, did not snap
    assert abs(hN - 0.33) < 0.02                  # converged near the target


def test_aurora_param_names_and_rejects_unknown():
    a = registry.build("aurora", hue=0.1)
    assert a.param_names() == {"hue"}             # so a cc lane can target it
    with pytest.raises(KeyError):
        registry.build("aurora", huue=0.5)


def test_aurora_without_level_param_still_self_breathes():
    a = registry.build("aurora", hue=0.0)
    assert a.param_names() == {"hue"}             # level is NOT exposed
    brights = [a.render(_ctx(frame=f, n=4, dt=0.5)).max() for f in range(14)]
    assert max(brights) - min(brights) > 0.1      # unchanged: still breathes
    assert min(brights) > 0.0                     # unchanged: never dark


def test_aurora_with_level_param_is_externally_driven_not_breathing():
    a = registry.build("aurora", hue=0.0, level=1.0)
    assert a.param_names() == {"hue", "level"}    # so a cc lane can target it
    brights = [a.render(_ctx(frame=f, n=4, dt=0.5)).max() for f in range(14)]
    assert max(brights) - min(brights) < 0.02     # held steady, breath is gone


def test_aurora_level_glides_toward_target_not_snap():
    a = registry.build("aurora", hue=0.0, level=1.0)
    a.render(_ctx(frame=0, n=4, dt=0.1))          # settle at full
    a.set("level", 0.2)
    b1 = a.render(_ctx(frame=1, n=4, dt=0.1)).max()
    last = None
    for f in range(2, 60):
        last = a.render(_ctx(frame=f, n=4, dt=0.1))
    bN = last.max()
    assert 0.2 < b1 < 1.0                         # started gliding, did not snap
    assert abs(bN - 0.2) < 0.02                   # converged near the target
