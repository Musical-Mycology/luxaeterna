"""Lux Aeterna — tests for the field-rate uGens."""

from __future__ import annotations

import numpy as np
from luxaeterna.synth.signal import RenderContext
from luxaeterna.synth.ugens import (Const, SolidColor, Gradient,
                                     PaletteMap, Bloom, Noise)


def ctx(frame=0, n=8, channels=3, time=0.0, dt=1 / 44):
    return RenderContext(time, frame, dt, np.linspace(0, 1, n), n, channels)


def test_solid_color_broadcasts():
    out = SolidColor(Const([1.0, 0.0, 0.5])).render(ctx(n=4))
    assert out.shape == (4, 3)
    assert np.allclose(out[0], [1.0, 0.0, 0.5])
    assert np.allclose(out[3], [1.0, 0.0, 0.5])


def test_gradient_endpoints():
    g = Gradient([(0.0, [0, 0, 0]), (1.0, [1, 1, 1])])
    out = g.render(ctx(n=3))                 # positions 0, 0.5, 1
    assert np.allclose(out[0], [0, 0, 0])
    assert np.allclose(out[1], [0.5, 0.5, 0.5])
    assert np.allclose(out[2], [1, 1, 1])


def test_palette_map_samples():
    pal = np.array([[0, 0, 0], [1, 0, 0]], dtype=float)
    out = PaletteMap(Const(1.0), pal).render(ctx(n=2))
    assert np.allclose(out[0], [1, 0, 0])


def test_bloom_peaks_at_center_and_scales_with_level():
    env = Const(1.0)
    b = Bloom(level=env, color=Const([1, 1, 1]), center=0.5)
    out = b.render(ctx(n=9))                 # center index 4
    assert out[4, 0] >= out[0, 0]            # brighter at centre than edge
    dark = Bloom(level=Const(0.0), color=Const([1, 1, 1]), center=0.5).render(ctx(n=9))
    assert np.allclose(dark, 0.0)            # zero level -> dark


def test_noise_is_bounded():
    out = Noise(Const([1, 1, 1]), scale=3.0, speed=1.0).render(ctx(n=16))
    assert out.shape == (16, 3)
    assert out.min() >= 0.0 and out.max() <= 1.0


def test_bloom_and_noise_pad_narrow_color_to_channels():
    # RGB color (3 values) on an RGBW surface (channels=4) must still yield (n, 4)
    b = Bloom(level=Const(1.0), color=Const([1.0, 0.5, 0.2]), center=0.5)
    assert b.render(ctx(n=5, channels=4)).shape == (5, 4)
    nse = Noise(Const([1.0, 0.5, 0.2]), scale=3.0, speed=1.0)
    assert nse.render(ctx(n=5, channels=4)).shape == (5, 4)
