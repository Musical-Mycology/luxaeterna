"""Lux Aeterna — ThrottledLog: per-key rate-limited logging for hot paths.

The 44 Hz output loop and MIDI dispatch must never emit one log line per
frame/message when something fails persistently. First occurrence per key
logs immediately; afterwards at most one line per ``interval`` seconds,
carrying a count of suppressed occurrences."""

from __future__ import annotations

import time


class ThrottledLog:
    def __init__(self, logger, interval: float = 5.0, clock=time.monotonic) -> None:
        self._logger = logger
        self._interval = interval
        self._clock = clock
        self._last: dict[str, float] = {}
        self._suppressed: dict[str, int] = {}

    def log(self, key: str, level: int, msg: str, *args) -> None:
        now = self._clock()
        last = self._last.get(key)
        if last is None or now - last >= self._interval:
            n = self._suppressed.pop(key, 0)
            if n:
                msg = msg + " (%d similar suppressed)"
                args = args + (n,)
            self._logger.log(level, msg, *args)
            self._last[key] = now
        else:
            self._suppressed[key] = self._suppressed.get(key, 0) + 1
