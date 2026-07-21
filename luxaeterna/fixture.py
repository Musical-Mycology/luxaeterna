"""Lux Aeterna — fixture profiles and instances mapping logical attributes to DMX channels."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Sequence

from .universe import Universe
from .exceptions import FixtureError


class Attribute(Enum):
    """Logical fixture attributes."""
    INTENSITY = "intensity"
    RED = "red"
    GREEN = "green"
    BLUE = "blue"
    WHITE = "white"
    AMBER = "amber"
    UV = "uv"
    PAN = "pan"
    PAN_FINE = "pan_fine"
    TILT = "tilt"
    TILT_FINE = "tilt_fine"
    GOBO = "gobo"
    STROBE = "strobe"
    ZOOM = "zoom"
    FOCUS = "focus"
    SPEED = "speed"


@dataclass(frozen=True, slots=True)
class ChannelDef:
    """Definition of a single DMX channel within a profile."""
    attribute: Attribute
    default: int = 0
    min_val: int = 0
    max_val: int = 255


@dataclass(frozen=True)
class Profile:
    """Template describing a fixture type's channel layout.

    Channels are ordered by their DMX offset (0 = first channel after
    the fixture's base address).
    """
    name: str
    channels: tuple[ChannelDef, ...]

    @property
    def width(self) -> int:
        """Number of DMX channels this fixture occupies."""
        return len(self.channels)

    def offset_of(self, attr: Attribute) -> int | None:
        """Return the channel offset for *attr*, or None if not present."""
        for i, ch in enumerate(self.channels):
            if ch.attribute == attr:
                return i
        return None


class Fixture:
    """A fixture instance bound to a universe at a base address.

    Provides fast, direct writes into the universe's bytearray.
    """

    __slots__ = ("name", "profile", "base", "_universe", "_offsets")

    def __init__(
        self,
        name: str,
        profile: Profile,
        base_channel: int,
        universe: Universe,
    ) -> None:
        self.name = name
        self.profile = profile
        self.base = base_channel
        self._universe = universe

        # Pre-compute attribute → absolute channel address for O(1) lookups
        self._offsets: dict[Attribute, int] = {}
        for i, ch in enumerate(profile.channels):
            self._offsets[ch.attribute] = base_channel + i

    def set(self, attr: Attribute, value: int) -> None:
        """Set a single attribute value."""
        addr = self._offsets.get(attr)
        if addr is None:
            raise FixtureError(f"{self.name}: no {attr.value} channel")
        self._universe.set(addr, value)

    def get(self, attr: Attribute) -> int:
        """Read a single attribute value."""
        addr = self._offsets.get(attr)
        if addr is None:
            raise FixtureError(f"{self.name}: no {attr.value} channel")
        return self._universe.get(addr)

    def set_rgb(self, r: int, g: int, b: int) -> None:
        """Set RGB in a single lock acquisition (faster than 3x set)."""
        data = bytearray(self.profile.width)
        # Build a partial frame from current state
        start = self.base
        for i in range(self.profile.width):
            data[i] = self._universe.get(start + i)

        r_off = self.profile.offset_of(Attribute.RED)
        g_off = self.profile.offset_of(Attribute.GREEN)
        b_off = self.profile.offset_of(Attribute.BLUE)
        if r_off is None or g_off is None or b_off is None:
            raise FixtureError(f"{self.name}: missing RGB channels")

        data[r_off] = r & 0xFF
        data[g_off] = g & 0xFF
        data[b_off] = b & 0xFF
        self._universe.set_range(start, data)

    def set_all(self, values: dict[Attribute, int]) -> None:
        """Batch-set multiple attributes in one lock acquisition."""
        data = bytearray(self.profile.width)
        start = self.base
        for i in range(self.profile.width):
            data[i] = self._universe.get(start + i)

        for attr, val in values.items():
            off = self.profile.offset_of(attr)
            if off is None:
                raise FixtureError(f"{self.name}: no {attr.value} channel")
            data[off] = val & 0xFF
        self._universe.set_range(start, data)

    def blackout(self) -> None:
        """Zero all channels for this fixture."""
        self._universe.set_range(self.base, bytearray(self.profile.width))

    def apply_defaults(self) -> None:
        """Set all channels to their profile defaults."""
        data = bytearray(ch.default for ch in self.profile.channels)
        self._universe.set_range(self.base, data)

    def __repr__(self) -> str:
        return f"Fixture({self.name!r}, base={self.base})"


# ── Built-in profiles ──────────────────────────────────────────────

RGB = Profile("RGB", (
    ChannelDef(Attribute.RED),
    ChannelDef(Attribute.GREEN),
    ChannelDef(Attribute.BLUE),
))

DIMMED_RGB = Profile("Dimmed RGB", (
    ChannelDef(Attribute.INTENSITY),
    ChannelDef(Attribute.RED),
    ChannelDef(Attribute.GREEN),
    ChannelDef(Attribute.BLUE),
))

RGBW = Profile("RGBW", (
    ChannelDef(Attribute.INTENSITY),
    ChannelDef(Attribute.RED),
    ChannelDef(Attribute.GREEN),
    ChannelDef(Attribute.BLUE),
    ChannelDef(Attribute.WHITE),
))

RGBWA_UV = Profile("RGBWA+UV", (
    ChannelDef(Attribute.INTENSITY),
    ChannelDef(Attribute.RED),
    ChannelDef(Attribute.GREEN),
    ChannelDef(Attribute.BLUE),
    ChannelDef(Attribute.WHITE),
    ChannelDef(Attribute.AMBER),
    ChannelDef(Attribute.UV),
))

MOVING_HEAD = Profile("Moving Head", (
    ChannelDef(Attribute.INTENSITY),
    ChannelDef(Attribute.PAN),
    ChannelDef(Attribute.PAN_FINE),
    ChannelDef(Attribute.TILT),
    ChannelDef(Attribute.TILT_FINE),
    ChannelDef(Attribute.RED),
    ChannelDef(Attribute.GREEN),
    ChannelDef(Attribute.BLUE),
    ChannelDef(Attribute.GOBO),
    ChannelDef(Attribute.STROBE),
    ChannelDef(Attribute.SPEED),
))

SINGLE_CHANNEL = Profile("Single Channel", (
    ChannelDef(Attribute.INTENSITY),
))
