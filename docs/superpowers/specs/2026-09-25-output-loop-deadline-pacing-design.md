# Output loop deadline pacing

**Date:** 2026-09-25
**Status:** Approved
**Scope:** new `luxaeterna/pacing.py`; `luxaeterna/universeset.py`
(`MultiUniverseOutputLoop._loop`); `luxaeterna/output.py` (`OutputLoop._loop`);
tests

## 1. Problem

Both output loops pace themselves the same way:

```python
elapsed = now - loop_start
sleep_time = interval - elapsed
if sleep_time > 0:
    time.sleep(sleep_time)
```

That repays the tick's work time but not the platform's sleep overshoot. On
macOS `time.sleep(1/44)` returns after ~26.8-27 ms instead of 22.7 ms
(dev-box figure, measured 2026-09-23), so the 44 Hz loop runs ~37 Hz. The
Dec 4 2026 show's Terrarium host is a Mac, and it drives the venue array
through `MultiUniverseOutputLoop`.

mm-terrarium hit the same bug in its own tick loops and fixed it with a
deadline pacer (`harness/tick_pacer.py`, spec
`docs/superpowers/specs/2026-09-25-tick-pacing-design.md`, both on its
`claude/tick-pacing` branch). After the fix, its `render_bench` measured
44.00 fps mean, up from 37.78, on the same Mac.

## 2. Design

### 2.1 `luxaeterna/pacing.py`: `TickPacer`

A local port of mm-terrarium's pacer. luxaeterna does not depend on
mm-terrarium; the class is ~20 lines.

```python
class TickPacer:
    def __init__(self, period: float, *, clock=time.monotonic,
                 sleep=time.sleep) -> None: ...
    def wait(self) -> None: ...
```

- The first `wait()` anchors the schedule: `deadline = clock() + period`.
- Each `wait()` sleeps `deadline - clock()` if positive, then advances
  `deadline += period`. A tick that ran long gets a shorter sleep, and an
  oversleep is repaid on the next tick, so the **mean** rate holds at
  `1 / period` whatever the platform's sleep slack.
- **No burst catch-up.** If `clock()` is more than one period past
  `deadline` on entry, the schedule resyncs: no sleep,
  `deadline = now + period`. A stall is lost time, never a run of
  back-to-back ticks. Lateness of up to one period is repaid.
- `sleep` is only ever called with a positive argument.
- `period <= 0` raises `ValueError`.

### 2.2 The two loops

`MultiUniverseOutputLoop` and `OutputLoop` each gain keyword-only
constructor arguments `clock=time.monotonic` and `sleep=time.sleep`. `_loop`
builds a fresh `TickPacer(self.frame_interval, clock=..., sleep=...)` on
each entry (a restart never inherits a stale deadline), calls
`pacer.wait()` at the end of each tick in place of the fixed remaining
sleep, and drops `loop_start`.

The smoothed `fps` property is unchanged in behavior: it still updates
about once a second as `frames / elapsed`, and still counts only ticks that
sent something. It reads the injected clock, so it can be tested offline.

## 3. Out of scope

- **Per-tick jitter.** Deadline pacing fixes the mean, not the ~4 ms
  per-tick jitter macOS sleep adds. A sleep-short-then-spin finish is a
  possible follow-up if bring-up needs it.
- Other `time.sleep` calls (`serial_enttec` break timing, `websim_demo`)
  are not tick pacing and stay.

## 4. Testing

All offline: a fake clock plus a fake sleep that advances it and oversleeps
by 4 ms.

- `tests/test_pacing.py`:
  - with 4 ms oversleep, N waits span `N * period` within one period;
  - work time is subtracted (a tick that ran 10 ms sleeps ~period - 10 ms);
  - an overrun of more than one period resyncs: no sleep that call, and
    the next wait sleeps a full period (no burst);
  - sleep is never called with a non-positive value;
  - the first wait sleeps one period;
  - a non-positive period raises.
- `tests/test_universeset.py` and `tests/test_output_hook.py`: run `_loop()`
  synchronously (the fake sleep stops the loop after a few seconds of fake
  time):
  - `fps` settles within 1% of 44 despite the 4 ms oversleep (the old
    remaining-sleep loop reads ~37.5);
  - a 100 ms stall inside `on_frame` is followed by no back-to-back ticks:
    every tick-to-tick interval is at least one period, less a tolerance.
- Full suite: `/Users/chris/projects/luxaeterna/.venv/bin/pytest -q`.
