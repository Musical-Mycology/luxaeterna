"""TickPacer: deadline pacing that repays sleep slack and never bursts."""

from __future__ import annotations

import pytest

from luxaeterna.pacing import TickPacer

PERIOD = 1.0 / 44.0
OVERSLEEP = 0.004          # macOS dev-box slack on a 22.7 ms request


class FakeTime:
    """A clock whose sleep advances it, oversleeping by a fixed slack."""

    def __init__(self, oversleep: float = 0.0) -> None:
        self.now = 1000.0
        self.oversleep = oversleep
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds + self.oversleep


def make(ft: FakeTime) -> TickPacer:
    return TickPacer(PERIOD, clock=ft.clock, sleep=ft.sleep)


def test_mean_rate_holds_despite_oversleep():
    ft = FakeTime(OVERSLEEP)
    pacer = make(ft)
    start = ft.now
    n = 440
    for _ in range(n):
        pacer.wait()
    assert abs((ft.now - start) - n * PERIOD) < PERIOD


def test_work_time_is_subtracted_from_the_sleep():
    ft = FakeTime()
    pacer = make(ft)
    pacer.wait()
    ft.now += 0.010                    # the tick's work
    pacer.wait()
    assert ft.sleeps[-1] == pytest.approx(PERIOD - 0.010)


def test_first_wait_sleeps_one_period():
    ft = FakeTime()
    make(ft).wait()
    assert ft.sleeps == [pytest.approx(PERIOD)]


def test_a_stall_resyncs_instead_of_bursting():
    ft = FakeTime(OVERSLEEP)
    pacer = make(ft)
    for _ in range(5):
        pacer.wait()
    ft.now += 0.100                    # a stall of more than four periods
    n_before = len(ft.sleeps)
    pacer.wait()
    assert len(ft.sleeps) == n_before  # no sleep on the late call
    pacer.wait()
    # A full period, not a zero-length catch-up tick.
    assert ft.sleeps[-1] == pytest.approx(PERIOD)


def test_lateness_under_one_period_is_repaid():
    ft = FakeTime()
    pacer = make(ft)
    pacer.wait()
    ft.now += PERIOD * 1.5             # late by half a period
    pacer.wait()                       # no sleep: already past the deadline
    pacer.wait()                       # the next deadline is still on schedule
    assert ft.sleeps[-1] == pytest.approx(PERIOD * 0.5)


def test_sleep_is_never_called_with_a_non_positive_value():
    ft = FakeTime(OVERSLEEP)
    pacer = make(ft)
    for i in range(200):
        if i % 7 == 0:
            ft.now += PERIOD * 1.2
        pacer.wait()
    assert ft.sleeps and all(s > 0 for s in ft.sleeps)


@pytest.mark.parametrize("period", [0.0, -1.0])
def test_non_positive_period_raises(period):
    with pytest.raises(ValueError):
        TickPacer(period)
