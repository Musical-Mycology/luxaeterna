"""PowerLimiter: keep an LED array inside its supply's current budget."""

from __future__ import annotations

import pytest

from luxaeterna.power import PowerBudget, PowerLimiter

TERRARIUM_PIXELS = 864
TERRARIUM_CHANNELS = TERRARIUM_PIXELS * 4


def white(n_channels: int = TERRARIUM_CHANNELS) -> bytearray:
    return bytearray([255]) * n_channels


def black(n_channels: int = TERRARIUM_CHANNELS) -> bytearray:
    return bytearray(n_channels)


def budget(max_amps: float = 10.0) -> PowerBudget:
    return PowerBudget(max_amps=max_amps)


# --- estimation ---

def test_black_frame_draws_nothing():
    assert PowerLimiter(budget()).estimate_amps(black()) == pytest.approx(0.0)


def test_full_white_array_matches_the_documented_21_6_amps():
    amps = PowerLimiter(budget()).estimate_amps(white())
    assert amps == pytest.approx(21.6, abs=0.05)


def test_half_scale_white_draws_half():
    frame = bytearray([128]) * TERRARIUM_CHANNELS
    amps = PowerLimiter(budget()).estimate_amps(frame)
    assert amps == pytest.approx(21.6 * 128 / 255, abs=0.05)


def test_one_pixel_full_white_draws_one_pixel_worth():
    frame = black()
    frame[0:4] = bytes([255, 255, 255, 255])
    assert PowerLimiter(budget()).estimate_amps(frame) == pytest.approx(
        0.025, abs=1e-4)


# --- scale_for ---

def test_frame_under_budget_is_not_scaled():
    frame = black()
    frame[0:4] = bytes([255, 255, 255, 255])
    assert PowerLimiter(budget()).scale_for(frame) == 1.0


def test_full_white_is_scaled_to_the_budget():
    limiter = PowerLimiter(budget(10.0))
    assert limiter.scale_for(white()) == pytest.approx(10.0 / 21.6, abs=0.001)


def test_black_frame_scale_is_one_not_a_division_by_zero():
    assert PowerLimiter(budget()).scale_for(black()) == 1.0


# --- apply ---

def test_apply_never_exceeds_the_hard_ceiling():
    out = PowerLimiter(budget()).apply(white())
    assert max(out) <= 117


def test_apply_keeps_the_result_inside_budget():
    limiter = PowerLimiter(budget(10.0))
    out = limiter.apply(white())
    assert limiter.estimate_amps(out) <= 10.0


def test_hard_ceiling_alone_holds_even_with_a_huge_budget():
    """Defence in depth: a wrong budget must not let the array exceed the supply."""
    limiter = PowerLimiter(PowerBudget(max_amps=10_000.0))
    out = limiter.apply(white())
    assert max(out) <= 117
    assert limiter.estimate_amps(out) < 10.5


def test_apply_leaves_a_dim_frame_untouched():
    frame = black()
    frame[0:4] = bytes([10, 20, 30, 40])
    out = PowerLimiter(budget()).apply(frame)
    assert out[0:4] == bytearray([10, 20, 30, 40])


def test_apply_does_not_mutate_the_input():
    frame = white()
    PowerLimiter(budget()).apply(frame)
    assert frame == bytearray([255]) * TERRARIUM_CHANNELS


def test_apply_returns_the_same_length():
    assert len(PowerLimiter(budget()).apply(white())) == TERRARIUM_CHANNELS


def test_apply_preserves_relative_colour_within_a_pixel():
    """Values must stay below the hard ceiling, or the ceiling flattens them
    into each other before the adaptive scale ever runs."""
    frame = black()
    frame[0:4] = bytes([100, 80, 60, 0])
    out = PowerLimiter(PowerBudget(max_amps=0.003)).apply(frame)
    assert out[0] > out[1] > out[2] > out[3]


def test_the_hard_ceiling_flattens_channels_above_it():
    """Documents the ceiling's real cost: 255 and 128 both clamp to 117, so
    near-white content loses hue detail. Accepted; the supply rating wins."""
    frame = black()
    frame[0:4] = bytes([255, 128, 64, 0])
    out = PowerLimiter(PowerBudget(max_amps=10.0)).apply(frame)
    assert out[0] == out[1] == 117


# --- budget guards ---

def test_negative_budget_is_rejected():
    with pytest.raises(ValueError):
        PowerBudget(max_amps=-1.0)


def test_zero_budget_is_rejected():
    with pytest.raises(ValueError):
        PowerBudget(max_amps=0.0)


def test_hard_ceiling_out_of_range_is_rejected():
    with pytest.raises(ValueError):
        PowerLimiter(budget(), hard_ceiling=256)


def test_hard_ceiling_of_zero_is_rejected():
    with pytest.raises(ValueError):
        PowerLimiter(budget(), hard_ceiling=0)


def test_the_default_ceiling_alone_keeps_the_array_under_the_supply_rating():
    """117 is chosen so an all-channels-at-ceiling frame stays under the
    LRS-150-12's 12.5 A even if the adaptive stage never runs."""
    limiter = PowerLimiter(budget())
    ceiling_frame = bytearray([limiter.hard_ceiling]) * TERRARIUM_CHANNELS
    assert limiter.estimate_amps(ceiling_frame) < 12.5
