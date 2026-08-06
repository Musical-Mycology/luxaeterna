"""Lux Aeterna — keep an LED array inside its power supply's current budget.

The Terrarium's 864 SK6812 RGBW pixels draw 21.6 A at full white against a
12.5 A supply, so the array can demand 1.7x what the supply delivers. Two
independent defences are applied, in this order:

1. A **hard ceiling** on every channel value. Unconditional, and sized so that
   even an all-channels-at-ceiling frame stays under the supply rating. A bug in
   the adaptive stage cannot defeat it.
2. An **adaptive scale** that estimates the frame's actual draw and reduces it
   only when it exceeds budget, so ordinary content keeps its full range.

Default ``amps_per_pixel_full`` (0.025 A) is SK6812 RGBW at 12 V, from
MM_HARDWARE_DESIGN.md §6.3 (128 LEDs measured at 38 W).

The ceiling has a real cost: channels above it flatten into each other, so
near-white content loses hue detail. That is accepted -- the supply rating wins.
"""

from __future__ import annotations

from dataclasses import dataclass

# All four channels at 255 on one pixel == amps_per_pixel_full.
_FULL_CHANNEL = 255


@dataclass(frozen=True)
class PowerBudget:
    """The current envelope an array must stay inside."""

    max_amps: float
    amps_per_pixel_full: float = 0.025
    channels_per_pixel: int = 4

    def __post_init__(self) -> None:
        if self.max_amps <= 0:
            raise ValueError(f"max_amps must be positive, got {self.max_amps}")
        if self.amps_per_pixel_full <= 0:
            raise ValueError(
                f"amps_per_pixel_full must be positive, "
                f"got {self.amps_per_pixel_full}")
        if self.channels_per_pixel <= 0:
            raise ValueError(
                f"channels_per_pixel must be positive, "
                f"got {self.channels_per_pixel}")

    @property
    def amps_per_channel_full(self) -> float:
        """Current drawn by one channel at full value."""
        return self.amps_per_pixel_full / self.channels_per_pixel


class PowerLimiter:
    """Apply a hard ceiling and an adaptive scale to a flat channel buffer."""

    __slots__ = ("budget", "hard_ceiling")

    def __init__(self, budget: PowerBudget, hard_ceiling: int = 117) -> None:
        if not (0 < hard_ceiling <= _FULL_CHANNEL):
            raise ValueError(
                f"hard_ceiling must be in 1-{_FULL_CHANNEL}, got {hard_ceiling}")
        self.budget = budget
        self.hard_ceiling = hard_ceiling

    def estimate_amps(self, channels: bytes | bytearray) -> float:
        """Estimated current for *channels*, a flat buffer of 0-255 values."""
        per_channel = self.budget.amps_per_channel_full / _FULL_CHANNEL
        return sum(channels) * per_channel

    def scale_for(self, channels: bytes | bytearray) -> float:
        """Multiplier that brings *channels* inside budget. 1.0 if already inside."""
        amps = self.estimate_amps(channels)
        if amps <= self.budget.max_amps or amps == 0.0:
            return 1.0
        return self.budget.max_amps / amps

    def apply(self, channels: bytes | bytearray) -> bytearray:
        """Return a new buffer, ceiling-clamped then scaled into budget."""
        clamped = bytearray(min(v, self.hard_ceiling) for v in channels)
        scale = self.scale_for(clamped)
        if scale >= 1.0:
            return clamped
        return bytearray(int(v * scale) for v in clamped)

    def __repr__(self) -> str:
        return (f"PowerLimiter(max_amps={self.budget.max_amps}, "
                f"hard_ceiling={self.hard_ceiling})")
