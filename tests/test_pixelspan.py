"""PixelSpan: mapping a logical pixel strip across consecutive DMX universes."""

from __future__ import annotations

import pytest

from luxaeterna.exceptions import ChannelError
from luxaeterna.pixelspan import PixelSpan

TERRARIUM = 864          # 6 m at 144 px/m
SHROOM = 12


def test_terrarium_array_needs_seven_universes():
    span = PixelSpan(TERRARIUM)
    assert span.channel_count == 3456
    assert span.pixels_per_universe == 128
    assert span.universe_count == 7
    assert span.universe_ids == [0, 1, 2, 3, 4, 5, 6]


def test_a_small_span_fits_in_one_universe():
    span = PixelSpan(SHROOM)
    assert span.channel_count == 48
    assert span.universe_count == 1
    assert span.universe_ids == [0]


def test_exact_multiple_does_not_allocate_a_spare_universe():
    span = PixelSpan(256)          # exactly 2 universes
    assert span.universe_count == 2


def test_start_universe_offsets_the_ids():
    span = PixelSpan(TERRARIUM, start_universe=10)
    assert span.universe_ids == [10, 11, 12, 13, 14, 15, 16]


# --- locate ---

def test_locate_first_pixel():
    assert PixelSpan(TERRARIUM).locate(0) == (0, 0)


def test_locate_last_pixel_of_first_universe():
    assert PixelSpan(TERRARIUM).locate(127) == (0, 508)


def test_locate_first_pixel_of_second_universe():
    assert PixelSpan(TERRARIUM).locate(128) == (1, 0)


def test_locate_last_pixel_of_the_array():
    # 863 // 128 == 6, remainder 95, 95 * 4 == 380
    assert PixelSpan(TERRARIUM).locate(863) == (6, 380)


def test_locate_honours_start_universe():
    assert PixelSpan(TERRARIUM, start_universe=10).locate(128) == (11, 0)


def test_locate_rejects_negative_pixel():
    with pytest.raises(ChannelError):
        PixelSpan(TERRARIUM).locate(-1)


def test_locate_rejects_pixel_past_the_end():
    with pytest.raises(ChannelError):
        PixelSpan(TERRARIUM).locate(864)


# --- slice_for ---

def test_slice_for_a_full_universe():
    assert PixelSpan(TERRARIUM).slice_for(0) == (0, 128)


def test_slice_for_the_partial_last_universe():
    # 864 - 6 * 128 == 96 pixels in the final universe
    assert PixelSpan(TERRARIUM).slice_for(6) == (768, 96)


def test_slice_for_honours_start_universe():
    assert PixelSpan(TERRARIUM, start_universe=10).slice_for(16) == (768, 96)


def test_slice_for_rejects_a_universe_outside_the_span():
    with pytest.raises(ChannelError):
        PixelSpan(TERRARIUM).slice_for(7)


# --- construction guards ---

def test_channels_per_pixel_must_divide_a_universe_evenly():
    """RGB (3 ch) straddles universe boundaries; out of scope by decision."""
    with pytest.raises(ChannelError, match="divide"):
        PixelSpan(TERRARIUM, channels_per_pixel=3)


def test_pixel_count_must_be_positive():
    with pytest.raises(ChannelError):
        PixelSpan(0)


def test_start_universe_must_not_be_negative():
    with pytest.raises(ChannelError):
        PixelSpan(TERRARIUM, start_universe=-1)


def test_no_pixel_ever_straddles_a_universe_boundary():
    """The property that keeps the arithmetic trivial. Guard it."""
    span = PixelSpan(TERRARIUM)
    for px in range(TERRARIUM):
        _, offset = span.locate(px)
        assert offset + span.channels_per_pixel <= 512
