"""Lux Aeterna — 512-channel DMX universe backed by a bytearray for speed."""

from __future__ import annotations

import threading
from typing import Sequence

from .constants import DMX_CHANNELS, DMX_MAX_VALUE, DMX_MIN_VALUE
from .exceptions import ChannelError


class Universe:
    """A single DMX512 universe (512 channels).

    All channel values are stored in a flat bytearray for minimal
    allocation overhead. A lightweight lock protects concurrent writes
    from the application thread and reads from the output thread.
    """

    __slots__ = ("universe_id", "_data", "_lock", "_dirty")

    def __init__(self, universe_id: int = 0) -> None:
        self.universe_id = universe_id
        self._data = bytearray(DMX_CHANNELS)
        self._lock = threading.Lock()
        self._dirty = True  # Flag for output loop optimisation

    # --- single-channel ops ---

    def set(self, channel: int, value: int) -> None:
        """Set a single channel (0-511) to *value* (0-255)."""
        if not (0 <= channel < DMX_CHANNELS):
            raise ChannelError(f"Channel {channel} out of range 0-{DMX_CHANNELS - 1}")
        with self._lock:
            self._data[channel] = value & 0xFF
            self._dirty = True

    def get(self, channel: int) -> int:
        """Read a single channel value."""
        if not (0 <= channel < DMX_CHANNELS):
            raise ChannelError(f"Channel {channel} out of range 0-{DMX_CHANNELS - 1}")
        return self._data[channel]

    # --- bulk ops (fast path for pixel strips / multi-channel fixtures) ---

    def set_range(self, start: int, values: bytes | bytearray | Sequence[int]) -> None:
        """Set a contiguous range of channels starting at *start*.

        Uses slice assignment on bytearray — significantly faster than
        looping ``set()`` for multi-channel writes.
        """
        end = start + len(values)
        if start < 0 or end > DMX_CHANNELS:
            raise ChannelError(f"Range {start}:{end} exceeds universe bounds")
        with self._lock:
            self._data[start:end] = values
            self._dirty = True

    def fill(self, value: int, start: int = 0, count: int | None = None) -> None:
        """Fill *count* channels starting at *start* with a single *value*."""
        if count is None:
            count = DMX_CHANNELS - start
        end = start + count
        if start < 0 or end > DMX_CHANNELS:
            raise ChannelError(f"Fill range {start}:{end} exceeds universe bounds")
        val = value & 0xFF
        with self._lock:
            for i in range(start, end):
                self._data[i] = val
            self._dirty = True

    # --- frame output ---

    def get_frame(self) -> bytearray:
        """Return a snapshot of the universe for transmission.

        Returns a *copy* so the output backend can work with stable data
        while the application keeps writing.
        """
        with self._lock:
            self._dirty = False
            return bytearray(self._data)

    @property
    def dirty(self) -> bool:
        """True if the universe has been modified since the last get_frame()."""
        return self._dirty

    def reset(self) -> None:
        """Zero all channels."""
        with self._lock:
            self._data = bytearray(DMX_CHANNELS)
            self._dirty = True

    # --- dunder helpers ---

    def __len__(self) -> int:
        return DMX_CHANNELS

    def __getitem__(self, channel: int) -> int:
        return self.get(channel)

    def __setitem__(self, channel: int, value: int) -> None:
        self.set(channel, value)

    def __repr__(self) -> str:
        return f"Universe(id={self.universe_id})"
