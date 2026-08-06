"""Lux Aeterna — map a logical pixel strip across consecutive DMX universes.

A DMX universe is 512 channels. An RGBW pixel is 4 channels, and 512 / 4 = 128
exactly, so an RGBW pixel never straddles a universe boundary. That property is
what keeps this arithmetic trivial, and it is why ``channels_per_pixel`` must
divide 512 evenly. Three-channel RGB strips do straddle; supporting them is out
of scope by decision.
"""

from __future__ import annotations

from .constants import DMX_CHANNELS
from .exceptions import ChannelError


class PixelSpan:
    """A pixel strip laid out across one or more consecutive universes.

    Parameters
    ----------
    pixel_count : int
        Number of logical pixels in the strip.
    channels_per_pixel : int
        Channels each pixel occupies. Must divide 512 evenly (1, 2, 4, 8, …).
    start_universe : int
        DMX universe id of the first universe in the span.
    """

    __slots__ = ("pixel_count", "channels_per_pixel", "start_universe")

    def __init__(self, pixel_count: int, channels_per_pixel: int = 4,
                 start_universe: int = 0) -> None:
        if pixel_count <= 0:
            raise ChannelError(f"pixel_count must be positive, got {pixel_count}")
        if channels_per_pixel <= 0:
            raise ChannelError(
                f"channels_per_pixel must be positive, got {channels_per_pixel}")
        if DMX_CHANNELS % channels_per_pixel != 0:
            raise ChannelError(
                f"channels_per_pixel {channels_per_pixel} must divide "
                f"{DMX_CHANNELS} evenly; pixels may not straddle universes")
        if start_universe < 0:
            raise ChannelError(f"start_universe must be >= 0, got {start_universe}")

        self.pixel_count = pixel_count
        self.channels_per_pixel = channels_per_pixel
        self.start_universe = start_universe

    @property
    def channel_count(self) -> int:
        return self.pixel_count * self.channels_per_pixel

    @property
    def pixels_per_universe(self) -> int:
        return DMX_CHANNELS // self.channels_per_pixel

    @property
    def universe_count(self) -> int:
        per = self.pixels_per_universe
        return (self.pixel_count + per - 1) // per

    @property
    def universe_ids(self) -> list[int]:
        return [self.start_universe + i for i in range(self.universe_count)]

    def locate(self, pixel_index: int) -> tuple[int, int]:
        """Return ``(universe_id, channel_offset)`` for *pixel_index*."""
        if not (0 <= pixel_index < self.pixel_count):
            raise ChannelError(
                f"Pixel {pixel_index} out of range 0-{self.pixel_count - 1}")
        per = self.pixels_per_universe
        universe_offset, within = divmod(pixel_index, per)
        return (self.start_universe + universe_offset,
                within * self.channels_per_pixel)

    def slice_for(self, universe_id: int) -> tuple[int, int]:
        """Return ``(first_pixel, pixel_count)`` carried by *universe_id*."""
        offset = universe_id - self.start_universe
        if not (0 <= offset < self.universe_count):
            raise ChannelError(
                f"Universe {universe_id} outside span "
                f"{self.start_universe}-"
                f"{self.start_universe + self.universe_count - 1}")
        per = self.pixels_per_universe
        first = offset * per
        return first, min(per, self.pixel_count - first)

    def __repr__(self) -> str:
        return (f"PixelSpan(pixel_count={self.pixel_count}, "
                f"channels_per_pixel={self.channels_per_pixel}, "
                f"start_universe={self.start_universe})")
