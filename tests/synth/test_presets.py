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


def test_rainbow_builds_as_instrument():
    assert isinstance(registry.build("rainbow", hue=0.0), LightInstrument)


def test_rainbow_varies_hue_across_positions_not_uniform():
    """The whole point: unlike aurora/glow/bloom, adjacent pixels differ."""
    out = registry.build("rainbow", hue=0.0, span=1.0, speed=0.0).render(
        _ctx(n=8, dt=0.1))
    assert out.shape == (8, 3)
    # Compare the first pixel to a middle one, not the literal last pixel:
    # span=1.0 is documented as "one full hue cycle across the whole bound
    # zone", and _ctx's positions are an endpoint-inclusive linspace(0, 1,
    # n), so position 0 and position 1.0 always close the loop back to the
    # same hue -- out[0] and out[-1] tie by construction for ANY n under a
    # full-cycle span, not just here. A middle pixel isn't subject to that
    # wraparound and still proves the point: hue genuinely varies by position.
    first_hue = _out_hue(out[0])
    mid_hue = _out_hue(out[4])
    assert abs(first_hue - mid_hue) > 0.1   # meaningfully different across the field


def test_rainbow_span_zero_is_uniform_like_aurora():
    """span=0 collapses the gradient to a single hue -- a sanity bound on the
    formula, not a real operating mode."""
    out = registry.build("rainbow", hue=0.2, span=0.0, speed=0.0).render(
        _ctx(n=6, dt=0.1))
    np.testing.assert_allclose(out[0], out[5], atol=1e-6)


def test_rainbow_scrolls_over_time():
    """speed != 0 advances the phase, so the SAME pixel's hue at frame N
    differs from frame 0 -- the "scrolling" in scrolling gradient."""
    inst = registry.build("rainbow", hue=0.0, span=1.0, speed=0.5)
    out0 = inst.render(_ctx(frame=0, n=8, dt=0.1))
    out1 = inst.render(_ctx(frame=1, n=8, dt=0.1))
    assert abs(_out_hue(out0[0]) - _out_hue(out1[0])) > 0.01


def test_rainbow_param_names_and_rejects_unknown():
    r = registry.build("rainbow", hue=0.1)
    assert r.param_names() == {"hue"}
    with pytest.raises(KeyError):
        registry.build("rainbow", huue=0.5)


def test_rainbow_with_level_param_is_externally_driven():
    r = registry.build("rainbow", hue=0.0, level=1.0)
    assert r.param_names() == {"hue", "level"}
    brights = [r.render(_ctx(frame=f, n=4, dt=0.5)).max() for f in range(14)]
    assert max(brights) - min(brights) < 0.02   # held steady, no private breathing


def test_rainbow_without_level_still_breathes_like_aurora():
    r = registry.build("rainbow", hue=0.0)
    assert r.param_names() == {"hue"}
    brights = [r.render(_ctx(frame=f, n=4, dt=0.5)).max() for f in range(14)]
    assert max(brights) - min(brights) > 0.1
    assert min(brights) > 0.0


def test_rainbow_hue_glides_toward_target_not_snap():
    r = registry.build("rainbow", hue=0.0, span=0.0, speed=0.0)
    r.render(_ctx(frame=0, n=4, dt=0.1))
    r.set("hue", 0.33)
    h1 = _out_hue(r.render(_ctx(frame=1, n=4, dt=0.1))[0])
    last = None
    for f in range(2, 40):
        last = r.render(_ctx(frame=f, n=4, dt=0.1))
    hN = _out_hue(last[0])
    assert 0.0 < h1 < 0.33
    assert abs(hN - 0.33) < 0.02
