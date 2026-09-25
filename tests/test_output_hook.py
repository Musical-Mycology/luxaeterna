"""Lux Aeterna — tests for the OutputLoop on_frame hook."""

from __future__ import annotations

import pytest

from luxaeterna.universe import Universe
from luxaeterna.output import OutputLoop
from luxaeterna.backends.base import DMXBackend


class FakeBackend(DMXBackend):
    def __init__(self):
        self.frames = []
        self._open = False

    def open(self):
        self._open = True

    def close(self):
        self._open = False

    def send(self, frame, universe_id):
        self.frames.append(bytes(frame))

    @property
    def is_open(self):
        return self._open


def test_on_frame_called_before_send():
    uni = Universe()
    marks = []
    def on_frame(u):
        marks.append("called")
        u.set(0, 200)
    loop = OutputLoop(uni, FakeBackend(), on_frame=on_frame)
    loop._loop_once()                              # single tick helper
    assert marks == ["called"]
    assert uni.get(0) == 200


def test_on_frame_exception_is_routed_to_on_error_and_loop_survives():
    uni = Universe()
    errors = []
    def boom(u):
        raise ValueError("render blew up")
    loop = OutputLoop(uni, FakeBackend(), on_frame=boom, on_error=errors.append)
    loop._loop_once()          # must NOT raise
    loop._loop_once()          # still callable a second time (loop would survive)
    assert len(errors) == 2
    assert isinstance(errors[0], ValueError)


def test_default_error_logging_is_throttled(caplog):
    import logging as _logging
    uni = Universe()

    class _BoomBackend:
        def open(self):
            pass

        def close(self):
            pass

        def send(self, frame, universe_id=0):
            raise RuntimeError("dead backend")

        @property
        def is_open(self):
            return True

    loop = OutputLoop(uni, _BoomBackend(), always_send=True)
    with caplog.at_level(_logging.ERROR, logger="luxaeterna.output"):
        for _ in range(50):
            loop._loop_once()
    assert len(caplog.records) == 1        # first logs; 49 suppressed within 5 s


# --- pacing (see the fuller notes in test_universeset.py) ---

PERIOD = 1.0 / 44.0
OVERSLEEP = 0.004          # macOS sleep slack on a 22.7 ms request


class PacedRun:
    """Fake clock + oversleeping sleep that stops *loop* after *seconds*."""

    def __init__(self, seconds: float) -> None:
        self.now = 1000.0
        self.stop_at = self.now + seconds
        self.loop = None

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        assert seconds > 0
        self.now += seconds + OVERSLEEP
        if self.now >= self.stop_at:
            self.loop._running = False

    def run(self, loop) -> None:
        self.loop = loop
        loop._running = True
        loop._loop()


def test_fps_holds_44_despite_sleep_overshoot():
    run = PacedRun(seconds=3.5)
    loop = OutputLoop(Universe(), FakeBackend(), always_send=True,
                      clock=run.clock, sleep=run.sleep)
    run.run(loop)
    assert loop.fps == pytest.approx(44.0, rel=0.01)


def test_a_stall_resyncs_without_bursting():
    run = PacedRun(seconds=2.0)
    ticks: list[float] = []

    def on_frame(_):
        ticks.append(run.now)
        if len(ticks) == 20:
            run.now += 0.100             # a 100 ms stall mid-tick

    loop = OutputLoop(Universe(), FakeBackend(), on_frame=on_frame,
                      clock=run.clock, sleep=run.sleep)
    run.run(loop)
    intervals = [b - a for a, b in zip(ticks, ticks[1:])]
    assert len(ticks) > 40
    assert min(intervals) >= PERIOD - 0.001    # no back-to-back catch-up ticks
