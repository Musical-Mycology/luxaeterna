# Bounded Per-Frame Event Drain Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cap the per-frame MIDI drain (drop-oldest, bounded memory) so an event flood can never blow the 22.7 ms frame budget, while control-plane events are structurally never dropped.

**Architecture:** `EventQueue` splits internally into a bounded MIDI lane (`deque(maxlen=midi_capacity)`, default 256, drop-oldest with exact drop counting) and an unbounded control lane, behind the unchanged `put()`/`drain()` surface. `drain()` returns MIDI first, control last, so control has the final word each frame. `LightSession.render_into` reads `take_dropped()` after the drain and emits a throttled WARNING.

**Tech Stack:** Python (stdlib only: `collections.deque`, `threading`), pytest.

**Spec:** `docs/superpowers/specs/2026-07-22-bounded-event-drain-design.md`

## Global Constraints

- Run tests with the root venv from the worktree cwd: `/Users/chris/projects/luxaeterna/.venv/bin/pytest` (no editable install; `pythonpath=["."]`).
- `events.py` stays a pure, logger-free structure; logging happens in `session.py` via the existing module-level `_throttle` (`ThrottledLog`).
- Default MIDI capacity is exactly **256**; frame budget constant is **1/44 s ≈ 22.7 ms**.
- Never drop `SwapEvent`, `ClearEvent`, or `StatusEvent` under any load.

---

### Task 1: EventQueue MIDI/control lanes

**Files:**
- Modify: `luxaeterna/synth/events.py:37-50` (the `EventQueue` class + module docstring)
- Test: `tests/synth/test_events.py`

**Interfaces:**
- Consumes: existing `MidiEvent`, `SwapEvent`, `ClearEvent`, `StatusEvent` dataclasses (unchanged).
- Produces: `EventQueue(midi_capacity: int = 256)`; `put(event) -> None` (routes by `isinstance(event, MidiEvent)`); `drain() -> list` (MIDI first in arrival order, then control in arrival order); `take_dropped() -> int` (returns and resets the dropped-MIDI count). Task 2 relies on exactly these names.

- [ ] **Step 1: Rewrite the tests to the new contract (failing)**

Replace the whole of `tests/synth/test_events.py` with:

```python
"""Tests for session events: bounded MIDI lane, never-dropped control lane."""

from __future__ import annotations

import threading

from luxaeterna.synth.events import (ClearEvent, EventQueue, MidiEvent,
                                     StatusEvent, SwapEvent)


def test_fifo_within_lanes_and_drain_empties():
    q = EventQueue()
    q.put(MidiEvent(1))
    q.put(ClearEvent())
    q.put(MidiEvent(2))
    items = q.drain()
    # MIDI lane first (arrival order), control lane last.
    assert [type(i) for i in items] == [MidiEvent, MidiEvent, ClearEvent]
    assert items[0].packed == 1 and items[1].packed == 2
    assert q.drain() == []


def test_midi_lane_bounded_drop_oldest():
    q = EventQueue(midi_capacity=8)
    for i in range(20):
        q.put(MidiEvent(i))
    items = q.drain()
    assert [e.packed for e in items] == list(range(12, 20))
    assert q.take_dropped() == 12
    assert q.take_dropped() == 0


def test_control_never_dropped_during_flood():
    q = EventQueue(midi_capacity=4)
    control = [SwapEvent(None), ClearEvent(), StatusEvent("error", "boom")]
    q.put(control[0])
    for i in range(5000):
        q.put(MidiEvent(i))
        if i == 2500:
            q.put(control[1])
    q.put(control[2])
    items = q.drain()
    assert all(a is b for a, b in zip(items[-3:], control))
    assert sum(isinstance(e, MidiEvent) for e in items) == 4


def test_concurrent_puts_all_arrive():
    q = EventQueue(midi_capacity=4000)

    def put_many(base):
        for i in range(1000):
            q.put(MidiEvent(base + i))

    threads = [threading.Thread(target=put_many, args=(k * 1000,))
               for k in range(4)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert len(q.drain()) == 4000
    assert q.take_dropped() == 0
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `/Users/chris/projects/luxaeterna/.venv/bin/pytest tests/synth/test_events.py -v`
Expected: FAIL — `test_fifo_within_lanes_and_drain_empties` (old interleaved order), `test_midi_lane_bounded_drop_oldest` (`TypeError: __init__() got an unexpected keyword argument 'midi_capacity'`), etc.

- [ ] **Step 3: Implement the lane split**

In `luxaeterna/synth/events.py`, replace the `EventQueue` class with:

```python
class EventQueue:
    """put() from any thread; drain() on the render thread once per frame.

    MIDI lands in a bounded lane (drop-oldest at ``midi_capacity``) so a
    burst can never balloon frame time or memory. Control-plane events
    (SwapEvent, ClearEvent, StatusEvent) land in an unbounded lane and are
    never dropped. drain() returns MIDI first, control last — the control
    plane gets the final word within a frame; cross-lane arrival order is
    intentionally not preserved (bounded by one 44 Hz frame)."""

    def __init__(self, midi_capacity: int = 256) -> None:
        self._midi: deque = deque(maxlen=midi_capacity)
        self._control: deque = deque()
        self._dropped = 0
        self._lock = threading.Lock()

    def put(self, event) -> None:
        with self._lock:
            if isinstance(event, MidiEvent):
                if len(self._midi) == self._midi.maxlen:
                    self._dropped += 1
                self._midi.append(event)
            else:
                self._control.append(event)

    def drain(self) -> list:
        with self._lock:
            items = list(self._midi)
            items.extend(self._control)
            self._midi.clear()
            self._control.clear()
        return items

    def take_dropped(self) -> int:
        with self._lock:
            n = self._dropped
            self._dropped = 0
            return n
```

Also update the module docstring's last sentence (line 4-5) to mention the two lanes, e.g.: `"""... the render thread drains once per frame and applies events in arrival order per lane: a bounded MIDI lane (drop-oldest) and an unbounded control lane that never drops."""`

- [ ] **Step 4: Run the events tests — expect all pass**

Run: `/Users/chris/projects/luxaeterna/.venv/bin/pytest tests/synth/test_events.py -v`
Expected: 4 passed.

- [ ] **Step 5: Run the full suite (drain-order change may ripple)**

Run: `/Users/chris/projects/luxaeterna/.venv/bin/pytest`
Expected: all pass (stress/e2e tests assert crash-freedom and lifecycle states, not MIDI retention counts).

- [ ] **Step 6: Commit**

```bash
git add luxaeterna/synth/events.py tests/synth/test_events.py
git commit -m "feat(synth): bound the MIDI event lane (drop-oldest); control lane never drops"
```

---

### Task 2: Session overflow warning + flood regression

**Files:**
- Modify: `luxaeterna/synth/session.py:87-88` (the drain loop in `render_into`)
- Test: `tests/synth/test_session.py` (append)

**Interfaces:**
- Consumes: `EventQueue.take_dropped() -> int` from Task 1; existing `_throttle = ThrottledLog(log)` module global in `session.py`.
- Produces: no new public API — `render_into` behavior only (throttled `WARNING` on the `"midi-overflow"` key).

- [ ] **Step 1: Write the failing tests**

Append to `tests/synth/test_session.py`:

```python
def test_midi_flood_stays_inside_frame_budget_and_swap_survives():
    # Review regression: 100k-event burst before one frame must neither blow
    # the 44 Hz budget nor drop the queued SwapEvent.
    session, uni = _mk()
    session.swap(LightManifest.from_dict(MANIFEST))
    packed = (0x90 << 16) | (60 << 8) | 127
    for _ in range(100_000):
        session._queue.put(MidiEvent(packed))
    t0 = time.perf_counter()
    session.render_into(uni)
    elapsed = time.perf_counter() - t0
    assert elapsed < 1.0 / 44.0, f"frame took {elapsed * 1000:.1f} ms"
    assert session.state != "idle"           # the SwapEvent was applied
    assert session._queue.drain() == []      # nothing carried to next frame


def test_midi_overflow_warns_throttled(monkeypatch, caplog):
    session, uni = _mk()
    # Fresh throttle: the module-level one is shared process-wide.
    monkeypatch.setattr(session_module, "_throttle",
                        ThrottledLog(session_module.log))
    session.swap(LightManifest.from_dict(MANIFEST))
    packed = (0x90 << 16) | (60 << 8) | 127
    with caplog.at_level(logging.WARNING, logger="luxaeterna.synth.session"):
        for _ in range(1000):
            session._queue.put(MidiEvent(packed))
        session.render_into(uni)             # overflow logged once
        for _ in range(1000):
            session._queue.put(MidiEvent(packed))
        session.render_into(uni)             # second overflow throttled
    overflow = [r for r in caplog.records if "overflow" in r.getMessage()]
    assert len(overflow) == 1
    assert "744" in overflow[0].getMessage()   # 1000 - 256 dropped
```

And extend the imports at the top of `tests/synth/test_session.py`:

```python
import logging
import time

from luxaeterna.logutil import ThrottledLog
from luxaeterna.synth import session as session_module
from luxaeterna.synth.events import MidiEvent
```

- [ ] **Step 2: Run tests to verify the overflow test fails**

Run: `/Users/chris/projects/luxaeterna/.venv/bin/pytest tests/synth/test_session.py -v -k "flood or overflow"`
Expected: `test_midi_flood_stays_inside_frame_budget_and_swap_survives` PASSES already (Task 1 bounded the lane — it documents the regression); `test_midi_overflow_warns_throttled` FAILS (no warning emitted yet).

- [ ] **Step 3: Emit the throttled warning after the drain**

In `luxaeterna/synth/session.py` `render_into`, replace:

```python
        for ev in self._queue.drain():
            self._apply(ev)
```

with:

```python
        for ev in self._queue.drain():
            self._apply(ev)
        dropped = self._queue.take_dropped()
        if dropped:
            _throttle.log("midi-overflow", logging.WARNING,
                          "MIDI lane overflow: %d events dropped", dropped)
```

- [ ] **Step 4: Run the session tests — expect all pass**

Run: `/Users/chris/projects/luxaeterna/.venv/bin/pytest tests/synth/test_session.py -v`
Expected: all pass.

- [ ] **Step 5: Run the full suite**

Run: `/Users/chris/projects/luxaeterna/.venv/bin/pytest`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add luxaeterna/synth/session.py tests/synth/test_session.py
git commit -m "feat(synth): throttled overflow warning + 100k-burst frame-budget regression"
```
