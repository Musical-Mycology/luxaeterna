"""Tests for ThrottledLog: per-key rate-limited logging."""

from __future__ import annotations

import logging

from luxaeterna.logutil import ThrottledLog


class _Capture:
    def __init__(self):
        self.records = []

    def log(self, level, msg, *args):
        self.records.append((level, msg % args if args else msg))


def test_first_logs_then_suppresses_then_summarizes():
    cap = _Capture()
    t = {"now": 0.0}
    tl = ThrottledLog(cap, interval=5.0, clock=lambda: t["now"])

    tl.log("k", logging.ERROR, "boom %d", 0)
    for i in range(10):
        t["now"] += 0.1
        tl.log("k", logging.ERROR, "boom %d", i)
    assert len(cap.records) == 1                      # only the first got through

    t["now"] += 5.0
    tl.log("k", logging.ERROR, "boom last")
    assert len(cap.records) == 2
    assert "10 similar suppressed" in cap.records[1][1]


def test_keys_are_independent():
    cap = _Capture()
    tl = ThrottledLog(cap, interval=5.0, clock=lambda: 0.0)
    tl.log("a", logging.WARNING, "one")
    tl.log("b", logging.WARNING, "two")
    assert len(cap.records) == 2
