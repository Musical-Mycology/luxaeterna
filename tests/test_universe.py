"""Universe: a single DMX buffer, optionally wider than one 512-channel wire universe."""

from __future__ import annotations

import pytest

from luxaeterna.constants import DMX_CHANNELS
from luxaeterna.exceptions import ChannelError
from luxaeterna.universe import Universe


def test_default_construction_is_exactly_512_channels():
    universe = Universe()
    assert len(universe) == DMX_CHANNELS


def test_default_construction_rejects_a_range_past_512():
    universe = Universe()
    with pytest.raises(ChannelError):
        universe.set_range(0, bytes(DMX_CHANNELS + 1))


def test_wide_universe_accepts_a_range_a_default_universe_would_reject():
    universe = Universe(channel_count=2592)
    universe.set_range(0, bytes(2592))   # must not raise
    assert len(universe) == 2592


def test_wide_universe_still_rejects_a_range_past_its_own_bound():
    universe = Universe(channel_count=2592)
    with pytest.raises(ChannelError):
        universe.set_range(0, bytes(2593))


def test_wide_universe_get_frame_returns_its_own_full_width():
    universe = Universe(channel_count=2592)
    universe.set_range(0, bytes([7]) * 2592)
    frame = universe.get_frame()
    assert len(frame) == 2592
    assert frame == bytearray([7]) * 2592


def test_wide_universe_fill_defaults_to_its_own_width():
    universe = Universe(channel_count=2592)
    universe.fill(9)   # no start/count -- must fill the whole 2592, not 512
    frame = universe.get_frame()
    assert len(frame) == 2592
    assert all(b == 9 for b in frame)


def test_wide_universe_reset_reallocates_at_its_own_width():
    universe = Universe(channel_count=2592)
    universe.set_range(0, bytes([5]) * 2592)
    universe.reset()
    frame = universe.get_frame()
    assert len(frame) == 2592
    assert all(b == 0 for b in frame)


def test_wide_universe_set_and_get_a_single_channel_past_512():
    universe = Universe(channel_count=2592)
    universe.set(1000, 42)
    assert universe.get(1000) == 42


def test_wide_universe_rejects_a_single_channel_past_its_own_bound():
    universe = Universe(channel_count=2592)
    with pytest.raises(ChannelError):
        universe.get(2592)
