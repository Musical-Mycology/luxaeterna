# Session Lifecycle & Status Visual Language Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give `luxaeterna.synth` an attach-once session lifecycle (create/swap/destroy for Bits) with a status visual language, eliminating the o2litepy handler leak and the render-thread races found in the 2026-07-22 review.

**Architecture:** A `LightSession` facade owns a thread-safe event queue, the O2 bridge, a six-state `StatusDirector`, and the engine. All graph mutation happens on the render thread at frame boundaries (queue drain). Status gestures are ordinary instruments under reserved `sys:*` registry names. Spec: `docs/superpowers/specs/2026-07-22-synth-session-lifecycle-design.md`.

**Tech Stack:** Python ≥3.10, numpy (only runtime dep), pytest. o2litepy is caller-supplied — its API shape (verified against arco@498e4ab's vendored copy) is pinned by a fake in tests.

## Global Constraints

- Run tests as `/Users/chris/projects/luxaeterna/.venv/bin/pytest` from the worktree cwd (venv lives at the repo root only; `pythonpath=["."]`, no editable install).
- Full suite green at every commit.
- o2litepy contract (do not deviate): `method_new(path, typespec, full, handler, info)` — 5 required args; handlers called `handler(address, types, info)`; payload via `client.get_int32()`; NO handler removal exists.
- Constants: quarantine after 44 consecutive failing frames; close fade 0.6 s; `sys:loaded` 1.5 s; `sys:error` 1.6 s; `identify` default 3.0 s; `ThrottledLog` interval 5.0 s; serial `write_timeout` 0.05 s.
- Perf: 1000 px session render < 22.7 ms/frame average (44 Hz budget).
- Canonical test surface: `shroom_capability(...)` — 12 px GRB, zones ring/stem/primary.
- MIDI wire format: packed int32 `(status << 16) | (data1 << 8) | data2`.

---

### Task 1: ThrottledLog

**Files:**
- Create: `luxaeterna/logutil.py`
- Test: `tests/test_logutil.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `ThrottledLog(logger, interval=5.0, clock=time.monotonic)` with method `log(key: str, level: int, msg: str, *args) -> None`. First call per key logs immediately; subsequent calls within `interval` are suppressed; the next call after `interval` logs with `" (%d similar suppressed)"` appended. Used by Tasks 7, 8, 10.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_logutil.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/chris/projects/luxaeterna/.venv/bin/pytest tests/test_logutil.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'luxaeterna.logutil'`

- [ ] **Step 3: Write the implementation**

```python
# luxaeterna/logutil.py
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `/Users/chris/projects/luxaeterna/.venv/bin/pytest tests/test_logutil.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add luxaeterna/logutil.py tests/test_logutil.py
git commit -m "feat(logutil): ThrottledLog for rate-limited hot-path logging"
```

---

### Task 2: Manifest v2 — bit identity + welcome

**Files:**
- Modify: `luxaeterna/synth/manifest.py`
- Test: `tests/synth/test_manifest.py` (append new tests; do not delete existing ones)

**Interfaces:**
- Consumes: nothing new.
- Produces: `SignatureDecl(instrument: str, params: dict, duration: float = 1.5)`; `LightManifest` gains fields `bit_name: str = ""`, `bit_version: str = ""`, `role: str = ""`, `welcome: SignatureDecl | None = None`. `from_dict` accepts the new keys and stays v1-compatible. Used by Tasks 7, 8.

- [ ] **Step 1: Write the failing tests (append to `tests/synth/test_manifest.py`)**

```python
def test_v1_dict_still_parses_with_empty_v2_fields():
    m = LightManifest.from_dict({"instruments": [
        {"instrument": "bloom", "target": "primary"}]})
    assert m.bit_name == "" and m.bit_version == "" and m.role == ""
    assert m.welcome is None


def test_v2_fields_and_welcome_parse():
    m = LightManifest.from_dict({
        "bit_name": "chorus", "bit_version": "1.2", "role": "drums",
        "welcome": {"instrument": "bloom", "params": {"hue": 0.1},
                    "duration": 0.8},
        "instruments": []})
    assert m.bit_name == "chorus" and m.role == "drums"
    assert m.welcome.instrument == "bloom"
    assert m.welcome.params == {"hue": 0.1}
    assert m.welcome.duration == 0.8


def test_welcome_duration_defaults():
    m = LightManifest.from_dict({
        "welcome": {"instrument": "bloom"}, "instruments": []})
    assert m.welcome.duration == 1.5 and m.welcome.params == {}
```

(Add `SignatureDecl` to the existing import from `luxaeterna.synth.manifest` if a later test needs it; these three only need `LightManifest`.)

- [ ] **Step 2: Run to verify failure**

Run: `/Users/chris/projects/luxaeterna/.venv/bin/pytest tests/synth/test_manifest.py -v`
Expected: new tests FAIL — `LightManifest` has no `bit_name` / `welcome`.

- [ ] **Step 3: Implement in `luxaeterna/synth/manifest.py`**

Add after `LightInstrumentDecl` (keep `LightLane` / `LightInstrumentDecl` unchanged):

```python
@dataclass
class SignatureDecl:
    """A declarable one-shot light gesture (e.g. a per-role welcome)."""
    instrument: str             # registered instrument name
    params: dict = field(default_factory=dict)
    duration: float = 1.5       # seconds until done


@dataclass
class LightManifest:
    instruments: list[LightInstrumentDecl] = field(default_factory=list)
    bit_name: str = ""          # Bit identity, for telemetry/log context
    bit_version: str = ""
    role: str = ""              # role this manifest was resolved for
    welcome: SignatureDecl | None = None   # plays in LOADING instead of sys:loaded

    @classmethod
    def from_dict(cls, d: dict) -> "LightManifest":
        w = d.get("welcome")
        return cls(
            instruments=[
                LightInstrumentDecl(
                    instrument=i["instrument"],
                    target=i["target"],
                    params=dict(i.get("params", {})),
                    lanes=[LightLane(l["source"], l["dest"], l.get("curve", "linear"))
                           for l in i.get("lanes", [])],
                )
                for i in d.get("instruments", [])
            ],
            bit_name=d.get("bit_name", ""),
            bit_version=d.get("bit_version", ""),
            role=d.get("role", ""),
            welcome=SignatureDecl(w["instrument"], dict(w.get("params", {})),
                                  w.get("duration", 1.5)) if w else None,
        )
```

- [ ] **Step 4: Run tests**

Run: `/Users/chris/projects/luxaeterna/.venv/bin/pytest tests/synth/test_manifest.py -v`
Expected: all pass (old + 3 new)

- [ ] **Step 5: Commit**

```bash
git add luxaeterna/synth/manifest.py tests/synth/test_manifest.py
git commit -m "feat(synth): manifest v2 — bit identity, role, welcome SignatureDecl"
```

---

### Task 3: Event types + EventQueue

**Files:**
- Create: `luxaeterna/synth/events.py`
- Test: `tests/synth/test_events.py`

**Interfaces:**
- Consumes: `LightManifest` (Task 2).
- Produces: dataclasses `MidiEvent(packed: int)`, `SwapEvent(manifest)`, `ClearEvent()`, `StatusEvent(kind: str, arg=None)`; `EventQueue` with `put(event)` (any thread) and `drain() -> list` (render thread, FIFO, empties the queue). Used by Task 8.

- [ ] **Step 1: Write the failing test**

```python
# tests/synth/test_events.py
"""Tests for session events: the one structure shared between threads."""

from __future__ import annotations

import threading

from luxaeterna.synth.events import ClearEvent, EventQueue, MidiEvent


def test_fifo_order_and_drain_empties():
    q = EventQueue()
    q.put(MidiEvent(1))
    q.put(ClearEvent())
    q.put(MidiEvent(2))
    items = q.drain()
    assert [type(i) for i in items] == [MidiEvent, ClearEvent, MidiEvent]
    assert items[0].packed == 1 and items[2].packed == 2
    assert q.drain() == []


def test_concurrent_puts_all_arrive():
    q = EventQueue()

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
```

- [ ] **Step 2: Run to verify failure**

Run: `/Users/chris/projects/luxaeterna/.venv/bin/pytest tests/synth/test_events.py -v`
Expected: FAIL — `No module named 'luxaeterna.synth.events'`

- [ ] **Step 3: Implement**

```python
# luxaeterna/synth/events.py
"""Lux Aeterna — session events: the ONLY structure shared between threads.

Producers (the o2lite poll thread, any caller thread) enqueue; the render
thread drains everything once per frame and applies events in arrival order.
Everything downstream of the drain is render-thread-only by construction."""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass

from .manifest import LightManifest


@dataclass
class MidiEvent:
    packed: int                 # (status << 16) | (data1 << 8) | data2


@dataclass
class SwapEvent:
    manifest: LightManifest


@dataclass
class ClearEvent:
    pass


@dataclass
class StatusEvent:
    kind: str                   # "error" | "disconnect" | "reconnect" | "identify" | "selftest"
    arg: object = None


class EventQueue:
    def __init__(self) -> None:
        self._items: deque = deque()
        self._lock = threading.Lock()

    def put(self, event) -> None:
        with self._lock:
            self._items.append(event)

    def drain(self) -> list:
        with self._lock:
            items = list(self._items)
            self._items.clear()
        return items
```

- [ ] **Step 4: Run tests**

Run: `/Users/chris/projects/luxaeterna/.venv/bin/pytest tests/synth/test_events.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add luxaeterna/synth/events.py tests/synth/test_events.py
git commit -m "feat(synth): event types + thread-safe EventQueue"
```

---

### Task 4: Engine rework — caller-supplied timing, isolation, gain, lazy positions

**Files:**
- Modify: `luxaeterna/synth/engine.py`
- Modify: `tests/synth/test_engine.py` (rewrite `test_engine_writes_universe_on_note`, add two tests)
- Modify: `tests/synth/test_end_to_end.py` (adapt both tests to the new engine call; `build_session`/`O2Bridge` are NOT touched in this task)

**Interfaces:**
- Consumes: `SurfaceCapability`, `ActiveBinding` (existing).
- Produces: `LightEngine(cap)` (no universe/bindings/clock in ctor) with `render_into(universe, bindings, t: float, dt: float, frame: int, gain: float = 1.0) -> list` returning the bindings whose `render` raised (exception swallowed, binding skipped). `channels_for`/`to_dmx_bytes`/`blend_into` unchanged. Used by Task 8.

- [ ] **Step 1: Rewrite/extend engine tests**

Replace `test_engine_writes_universe_on_note` in `tests/synth/test_engine.py` and append the two new tests (keep `test_channels_and_dmx_byte_order` and `test_blend_add_and_over` unchanged; add `ActiveBinding` to the imports from `luxaeterna.synth.binding`):

```python
def test_engine_writes_universe_on_note():
    cap = shroom_capability("ie3")
    binding = resolve(LightInstrumentDecl("bloom", "primary", {},
                                          [LightLane("note", "trigger")]), cap)
    uni = Universe()
    engine = LightEngine(cap)

    engine.render_into(uni, [binding], t=0.0, dt=0.01, frame=0)
    assert max(uni.get_frame()[:36]) == 0
    binding.routes["note"](60, 1.0)
    engine.render_into(uni, [binding], t=0.01, dt=0.01, frame=1)
    assert max(uni.get_frame()[:36]) > 0


def test_engine_isolates_failing_binding_and_reports_it():
    cap = shroom_capability("ie3")
    good = resolve(LightInstrumentDecl("bloom", "primary", {},
                                       [LightLane("note", "trigger")]), cap)
    good.routes["note"](60, 1.0)

    class _Boom:
        def render(self, ctx):
            raise RuntimeError("bad ugen")

    bad = ActiveBinding(obj=_Boom(), zone=cap.zone("ring"), blend="add",
                        routes={})
    uni = Universe()
    engine = LightEngine(cap)
    failed = engine.render_into(uni, [bad, good], t=0.0, dt=0.01, frame=0)
    assert failed == [bad]
    assert max(uni.get_frame()[:36]) > 0        # good binding still rendered


def test_engine_gain_scales_output():
    cap = shroom_capability("ie3")

    def lit_binding():
        b = resolve(LightInstrumentDecl("bloom", "primary", {},
                                        [LightLane("note", "trigger")]), cap)
        b.routes["note"](60, 1.0)
        return b

    uni_full, uni_dim = Universe(), Universe()
    LightEngine(cap).render_into(uni_full, [lit_binding()],
                                 t=0.0, dt=0.01, frame=0)
    LightEngine(cap).render_into(uni_dim, [lit_binding()],
                                 t=0.0, dt=0.01, frame=0, gain=0.25)
    assert 0 < max(uni_dim.get_frame()[:36]) < max(uni_full.get_frame()[:36])
```

- [ ] **Step 2: Run to verify failure**

Run: `/Users/chris/projects/luxaeterna/.venv/bin/pytest tests/synth/test_engine.py -v`
Expected: 3 FAIL (new signature doesn't exist), 2 pass.

- [ ] **Step 3: Rewrite `LightEngine` in `luxaeterna/synth/engine.py`**

Keep the module docstring, `_CANON`, `channels_for`, `to_dmx_bytes`, `blend_into` exactly as they are. Remove `import time` (no longer used). Replace the class:

```python
class LightEngine:
    """Composites whatever binding list it is handed into DMX bytes.

    Timing (t/dt/frame) is supplied by the caller — the LightSession owns the
    clock. Per-binding exceptions are swallowed and the offenders returned so
    the director can quarantine repeat failures; one bad binding never costs
    the rest of the surface its frame. Zone positions are cached lazily by
    zone name because the binding list changes at runtime (bit swaps)."""

    def __init__(self, cap: SurfaceCapability) -> None:
        self.cap = cap
        self._channels = channels_for(cap.color_order)
        self._positions: dict[str, np.ndarray] = {}

    def render_into(self, universe, bindings, t: float, dt: float,
                    frame: int, gain: float = 1.0) -> list:
        surface = np.zeros((self.cap.pixel_count, self._channels))
        failed = []
        for b in bindings:
            pos = self._positions.get(b.zone.name)
            if pos is None:
                pos = np.linspace(0, 1, b.zone.count)
                self._positions[b.zone.name] = pos
            ctx = RenderContext(time=t, frame=frame, dt=dt, positions=pos,
                                n=b.zone.count, channels=self._channels)
            try:
                top = b.render(ctx)
            except Exception:
                failed.append(b)
                continue
            sl = slice(b.zone.start, b.zone.start + b.zone.count)
            blend_into(surface, sl, top, b.blend)
        if gain != 1.0:
            surface *= gain
        universe.set_range(0, to_dmx_bytes(surface, self.cap.color_order))
        return failed
```

Also update the imports block: drop `from .binding import ActiveBinding` if now unused, keep `SurfaceCapability` and `RenderContext` imports.

- [ ] **Step 4: Adapt `tests/synth/test_end_to_end.py` to the new engine call**

In `test_note_over_o2_lights_the_shroom`, replace the engine construction and the two render calls (leave the rest — `build_session`, `bridge.on_midi` — untouched; they still use the old bridge until Task 8):

```python
    cap = shroom_capability("ie3")
    bindings, bridge = build_session(LightManifest.from_dict(MANIFEST), cap)
    uni = Universe()
    engine = LightEngine(cap)

    engine.render_into(uni, bindings, t=0.0, dt=0.02, frame=0)
    assert max(uni.get_frame()[:36]) == 0                       # dark before note

    bridge.on_midi((0xB0 << 16) | (74 << 8) | 0)                # CC74=0 -> red
    bridge.on_midi((0x90 << 16) | (60 << 8) | 127)              # note-on
    engine.render_into(uni, bindings, t=0.02, dt=0.02, frame=1)
```

(`test_perf_1000px_within_frame_budget` renders bindings directly and needs no change in this task; delete the now-unused `uni_clock` line.)

- [ ] **Step 5: Run the full suite**

Run: `/Users/chris/projects/luxaeterna/.venv/bin/pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add luxaeterna/synth/engine.py tests/synth/test_engine.py tests/synth/test_end_to_end.py
git commit -m "refactor(synth): engine takes caller timing + binding list; per-binding isolation, gain, lazy positions"
```

---

### Task 5: Status vocabulary — Signature wrapper + built-in sys:* gestures

**Files:**
- Create: `luxaeterna/synth/status.py`
- Test: `tests/synth/test_status.py`

**Interfaces:**
- Consumes: `LightUgen`, `RenderContext`, `as_ugen` (signal.py); `Const`, `Noise` (ugens.py); `registry`.
- Produces: `Signature(instrument, duration)` — attrs `renders=True`, `duration`, `elapsed`; methods `advance(dt)`, `render(ctx)`; properties `done`, `gain` (1.0). `GainSignature(duration)` — `renders=False`, `gain` ramps 1→0. uGens `SegmentLevel(points, loop_from=None)`, `Fill(level, color)`, `ChannelSweep(step=0.5)`. Registry factories under `"sys:idle"`, `"sys:loaded"`, `"sys:closing"`, `"sys:error"`, `"sys:disconnected"`, `"sys:identify"`, `"sys:selftest"` — each returns a **Signature** (unlike instrument factories). Registration happens at import. Used by Task 7.

- [ ] **Step 1: Write the failing tests**

```python
# tests/synth/test_status.py
"""Tests for the status visual language: Signature wrapper + built-in gestures."""

from __future__ import annotations

import numpy as np
from luxaeterna.synth import registry
from luxaeterna.synth.signal import RenderContext
from luxaeterna.synth.status import (ChannelSweep, Fill, GainSignature,
                                     SegmentLevel, Signature, _sig_error)
from luxaeterna.synth.ugens import Const


def _ctx(f, dt=0.05, n=12, ch=3):
    return RenderContext(time=f * dt, frame=f, dt=dt,
                         positions=np.linspace(0, 1, n), n=n, channels=ch)


def test_segment_level_interpolates():
    lvl = SegmentLevel([(0.0, 0.0), (1.0, 1.0), (2.0, 0.0)])
    v = float(lvl.render(_ctx(0, dt=0.5)))          # local t=0.5
    assert abs(v - 0.5) < 1e-6


def test_segment_level_loops_from_anchor():
    lvl = SegmentLevel([(0.0, 0.0), (1.0, 1.0), (2.0, 0.0)], loop_from=0.0)
    v = None
    for f in range(5):                               # local t reaches 2.5 -> wraps to 0.5
        v = float(lvl.render(_ctx(f, dt=0.5)))
    assert abs(v - 0.5) < 1e-6


def test_fill_scales_color_across_pixels():
    fill = Fill(0.5, Const((1.0, 0.0, 0.0)))
    out = fill.render(_ctx(0))
    assert out.shape == (12, 3)
    np.testing.assert_allclose(out[0], [0.5, 0.0, 0.0])
    np.testing.assert_allclose(out[11], [0.5, 0.0, 0.0])


def test_channel_sweep_walks_channels():
    sweep = ChannelSweep(step=0.5)
    out = sweep.render(_ctx(0, dt=0.1))              # t=0.1 -> channel 0
    assert out[0, 0] == 1.0 and out[0, 1] == 0.0
    for f in range(1, 6):                            # t=0.6 -> channel 1
        out = sweep.render(_ctx(f, dt=0.1))
    assert out[0, 1] == 1.0 and out[0, 0] == 0.0


def test_signature_done_and_neutral_gain():
    sig = Signature(Fill(1.0, Const((0, 1, 0))), duration=1.0)
    sig.advance(0.6)
    assert not sig.done and sig.gain == 1.0
    sig.advance(0.5)
    assert sig.done


def test_gain_signature_ramps_and_never_renders():
    g = GainSignature(0.6)
    assert g.renders is False
    g.advance(0.3)
    assert abs(g.gain - 0.5) < 1e-6
    g.advance(0.4)
    assert g.done and g.gain == 0.0


def test_builtins_registered_and_overridable():
    assert isinstance(registry.build("sys:error"), Signature)
    for name in ("sys:idle", "sys:loaded", "sys:closing", "sys:error",
                 "sys:disconnected", "sys:identify", "sys:selftest"):
        assert isinstance(registry.build(name), Signature)
    try:
        registry.register("sys:error",
                          lambda: Signature(Fill(1.0, Const((0, 0, 1))), 0.1))
        assert registry.build("sys:error").duration == 0.1
    finally:
        registry.register("sys:error", _sig_error)   # restore the built-in
```

- [ ] **Step 2: Run to verify failure**

Run: `/Users/chris/projects/luxaeterna/.venv/bin/pytest tests/synth/test_status.py -v`
Expected: FAIL — `No module named 'luxaeterna.synth.status'`

- [ ] **Step 3: Implement**

```python
# luxaeterna/synth/status.py
"""Lux Aeterna — status visual language: Signature wrapper + built-in sys:*
gestures. Every gesture is an ordinary instrument built from the uGen
vocabulary and registered by name, so installations can reskin any of them by
re-registering. Reserved for future gameserver verbs (names only, no v1
implementation): sys:role-adopted, sys:role-denied, sys:goodbye."""

from __future__ import annotations

import math

import numpy as np

from . import registry
from .signal import LightUgen, RenderContext, as_ugen
from .ugens import Const, Noise


class Signature:
    """A status gesture: an instrument plus a duration clock the director
    advances. ``duration=math.inf`` loops forever (idle/disconnected)."""

    renders = True

    def __init__(self, instrument, duration: float) -> None:
        self.instrument = instrument
        self.duration = float(duration)
        self.elapsed = 0.0

    def advance(self, dt: float) -> None:
        self.elapsed += dt

    @property
    def done(self) -> bool:
        return self.elapsed >= self.duration

    @property
    def gain(self) -> float:
        return 1.0

    def render(self, ctx: RenderContext) -> np.ndarray:
        return self.instrument.render(ctx)


class GainSignature(Signature):
    """Renders nothing; produces the global 1→0 gain ramp (the close fade
    applied over the retained bit surface)."""

    renders = False

    def __init__(self, duration: float) -> None:
        super().__init__(None, duration)

    @property
    def gain(self) -> float:
        if self.duration <= 0:
            return 0.0
        return max(0.0, 1.0 - self.elapsed / self.duration)


class SegmentLevel(LightUgen):
    """Piecewise-linear level over local time (advanced by ctx.dt, memoized
    per frame like Envelope). With ``loop_from`` set, time wraps back there
    after the last point — blink-then-breathe patterns loop forever."""

    rate = "control"

    def __init__(self, points, loop_from: float | None = None) -> None:
        super().__init__()
        self._xs = np.asarray([p[0] for p in points], dtype=float)
        self._ys = np.asarray([p[1] for p in points], dtype=float)
        self._loop_from = loop_from
        self._t = 0.0

    def _compute(self, ctx: RenderContext) -> np.ndarray:
        self._t += ctx.dt
        t = self._t
        end = self._xs[-1]
        if self._loop_from is not None and t > end:
            span = end - self._loop_from
            t = self._loop_from + ((t - self._loop_from) % span)
        return np.asarray(np.interp(t, self._xs, self._ys))


class Fill(LightUgen):
    """level * color across every pixel — SolidColor with a brightness input."""

    rate = "field"

    def __init__(self, level, color) -> None:
        super().__init__()
        self._level = as_ugen(level)
        self._color = as_ugen(color)

    def _compute(self, ctx: RenderContext) -> np.ndarray:
        level = float(np.asarray(self._level.render(ctx)))
        c = np.asarray(self._color.render(ctx), dtype=float).reshape(-1)
        if c.shape[0] < ctx.channels:
            c = np.concatenate([c, np.zeros(ctx.channels - c.shape[0])])
        return np.clip(level * np.tile(c[:ctx.channels], (ctx.n, 1)), 0.0, 1.0)


class ChannelSweep(LightUgen):
    """One full-brightness channel at a time — the R→G→B(→W) wiring self-test
    that instantly exposes color-order mistakes."""

    rate = "field"

    def __init__(self, step: float = 0.5) -> None:
        super().__init__()
        self._step = float(step)
        self._t = 0.0

    def _compute(self, ctx: RenderContext) -> np.ndarray:
        self._t += ctx.dt
        ch = int(self._t / self._step) % ctx.channels
        out = np.zeros((ctx.n, ctx.channels))
        out[:, ch] = 1.0
        return out


WHITE = (1.0, 1.0, 1.0)
GREEN = (0.0, 1.0, 0.0)
RED = (1.0, 0.0, 0.0)
IDLE_TINT = (0.25, 0.25, 0.35)          # dim blue-white


def _sig_idle() -> Signature:
    lvl = SegmentLevel([(0.0, 0.05), (2.0, 0.30), (4.0, 0.05)], loop_from=0.0)
    return Signature(Fill(lvl, Const(IDLE_TINT)), math.inf)


def _sig_loaded() -> Signature:
    pts = [(0.0, 0.0), (0.05, 1.0), (0.30, 0.10), (0.55, 0.55),
           (0.85, 0.05), (1.10, 0.45), (1.50, 0.0)]     # flash + 2 soft pulses
    return Signature(Fill(SegmentLevel(pts), Const(GREEN)), 1.5)


def _sig_closing() -> GainSignature:
    return GainSignature(0.6)


def _sig_error() -> Signature:
    pts = [(0.0, 0.0), (0.45, 1.0), (0.95, 1.0), (1.60, 0.0)]  # rise-hold-fall
    return Signature(Fill(SegmentLevel(pts), Const(RED)), 1.6)


def _sig_disconnected() -> Signature:
    pts = [(0.0, 0.0), (0.10, 1.0), (0.20, 0.0), (0.30, 1.0), (0.40, 0.0),
           (1.00, 0.0), (2.50, 0.25), (4.00, 0.0)]      # double-blink, then breathe
    return Signature(Fill(SegmentLevel(pts, loop_from=1.0), Const(RED)), math.inf)


def _sig_identify() -> Signature:
    return Signature(Noise(Const(WHITE), scale=2.0, speed=3.0), 3.0)


def _sig_selftest() -> Signature:
    return Signature(ChannelSweep(step=0.5), 2.0)


def register_builtin_signatures() -> None:
    registry.register("sys:idle", _sig_idle)
    registry.register("sys:loaded", _sig_loaded)
    registry.register("sys:closing", _sig_closing)
    registry.register("sys:error", _sig_error)
    registry.register("sys:disconnected", _sig_disconnected)
    registry.register("sys:identify", _sig_identify)
    registry.register("sys:selftest", _sig_selftest)


register_builtin_signatures()
```

- [ ] **Step 4: Run tests**

Run: `/Users/chris/projects/luxaeterna/.venv/bin/pytest tests/synth/test_status.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add luxaeterna/synth/status.py tests/synth/test_status.py
git commit -m "feat(synth): status visual language — Signature wrapper + built-in sys:* gestures"
```

---

### Task 6: LightSynth.all_notes_off

**Files:**
- Modify: `luxaeterna/synth/instrument.py`
- Test: `tests/synth/test_instrument.py` (append)

**Interfaces:**
- Consumes: existing `LightSynth`.
- Produces: `LightSynth.all_notes_off() -> None` — gates off every active voice so releases play out during the close fade. Used by Task 7 (`_enter_closing`).

- [ ] **Step 1: Append the failing test to `tests/synth/test_instrument.py`**

```python
def test_all_notes_off_gates_every_voice():
    from luxaeterna.synth.presets import _bloom_voice
    synth = LightSynth(voice_factory=_bloom_voice, max_voices=8)
    synth.noteon(60, 1.0)
    synth.noteon(64, 1.0)
    synth.all_notes_off()
    assert len(synth.voices) == 2                    # not dropped — releasing
    for _inst, env in synth.voices.values():
        assert env._stage == "release"
```

- [ ] **Step 2: Run to verify failure**

Run: `/Users/chris/projects/luxaeterna/.venv/bin/pytest tests/synth/test_instrument.py -v`
Expected: new test FAILs — no `all_notes_off`.

- [ ] **Step 3: Implement — add to `LightSynth` after `noteoff`**

```python
    def all_notes_off(self) -> None:
        """Gate off every active voice (releases play out, then prune)."""
        for _inst, env in self.voices.values():
            env.gate_off()
```

- [ ] **Step 4: Run tests**

Run: `/Users/chris/projects/luxaeterna/.venv/bin/pytest tests/synth/test_instrument.py -v`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add luxaeterna/synth/instrument.py tests/synth/test_instrument.py
git commit -m "feat(synth): LightSynth.all_notes_off for close-fade voice release"
```

---

### Task 7: StatusDirector — the state machine

**Files:**
- Create: `luxaeterna/synth/director.py`
- Test: `tests/synth/test_director.py`

**Interfaces:**
- Consumes: `registry.build("sys:*") -> Signature` (Task 5), `Signature` (Task 5), `resolve`/`ActiveBinding` (binding.py), `LightManifest`/`SignatureDecl` (Task 2), `all_notes_off` (Task 6), `ThrottledLog` (Task 1).
- Produces: module constants `IDLE/LOADING/RUNNING/CLOSING/ERROR/DISCONNECTED/SELFTEST` (string values `"idle"` etc.), `QUARANTINE_FRAMES = 44`; `StatusDirector(cap)` with attrs `state`, `bit_bindings`, `bit_name`, `role`, `pending`; event methods `swap(manifest)`, `clear()`, `error(reason="")`, `disconnect()`, `reconnect()`, `identify(duration=3.0)`, `selftest()`; per-frame `frame(dt) -> tuple[list[ActiveBinding], float]` and `note_failures(failed: list) -> None`. Used by Task 8.

- [ ] **Step 1: Write the failing tests**

```python
# tests/synth/test_director.py
"""Tests for the StatusDirector: session state machine + signature lifecycle."""

from __future__ import annotations

from luxaeterna.synth.capability import shroom_capability
from luxaeterna.synth.director import (CLOSING, DISCONNECTED, ERROR, IDLE,
                                       LOADING, QUARANTINE_FRAMES, RUNNING,
                                       SELFTEST, StatusDirector)
from luxaeterna.synth.manifest import LightManifest

MANIFEST = LightManifest.from_dict({
    "bit_name": "testbit", "role": "melody",
    "instruments": [{"instrument": "bloom", "target": "primary",
                     "lanes": [{"source": "note", "dest": "trigger"}]}],
})


def _mk():
    return StatusDirector(shroom_capability("ie3"))


def _run(d, seconds, dt=0.05):
    for _ in range(int(seconds / dt)):
        d.frame(dt)


def test_boots_idle_with_a_signature():
    d = _mk()
    assert d.state == IDLE
    render, gain = d.frame(0.05)
    assert len(render) == 1 and gain == 1.0


def test_swap_from_idle_loads_then_runs():
    d = _mk()
    d.swap(MANIFEST)
    assert d.state == LOADING and d.bit_name == "testbit"
    _run(d, 2.0)                                     # sys:loaded lasts 1.5 s
    assert d.state == RUNNING
    render, _ = d.frame(0.05)
    assert render == d.bit_bindings                  # bit alone on the surface


def test_swap_from_running_fades_then_reloads():
    d = _mk()
    d.swap(MANIFEST)
    _run(d, 2.0)
    d.swap(MANIFEST)
    assert d.state == CLOSING
    render, gain = d.frame(0.05)
    assert render and 0.0 < gain < 1.0               # old bit rendering, fading
    _run(d, 1.0)                                     # 0.6 s fade elapses
    assert d.state in (LOADING, RUNNING)


def test_latest_swap_wins_during_closing():
    d = _mk()
    d.swap(MANIFEST)
    _run(d, 2.0)
    m2 = LightManifest.from_dict({"bit_name": "second", "instruments": [
        {"instrument": "bloom", "target": "primary"}]})
    m3 = LightManifest.from_dict({"bit_name": "third", "instruments": [
        {"instrument": "bloom", "target": "primary"}]})
    d.swap(m2)
    d.swap(m3)
    _run(d, 3.0)
    assert d.bit_name == "third"


def test_welcome_replaces_generic_loaded():
    m = LightManifest.from_dict({
        "instruments": [{"instrument": "bloom", "target": "primary"}],
        "welcome": {"instrument": "bloom", "duration": 0.2}})
    d = _mk()
    d.swap(m)                                        # short welcome (a dark synth
    assert d.state == LOADING                        # is fine — only timing matters)
    _run(d, 0.4)
    assert d.state == RUNNING


def test_resolve_failure_goes_error_then_idle():
    bad = LightManifest.from_dict({
        "instruments": [{"instrument": "no-such-instrument",
                         "target": "primary"}]})
    d = _mk()
    d.swap(bad)
    assert d.state == ERROR
    _run(d, 2.0)                                     # sys:error lasts 1.6 s
    assert d.state == IDLE


def test_clear_fades_to_idle():
    d = _mk()
    d.swap(MANIFEST)
    _run(d, 2.0)
    d.clear()
    assert d.state == CLOSING
    _run(d, 1.0)
    assert d.state == IDLE and not d.bit_bindings


def test_disconnect_drops_bit_and_reconnect_loads_pending():
    d = _mk()
    d.swap(MANIFEST)
    _run(d, 2.0)
    d.disconnect()
    assert d.state == DISCONNECTED and not d.bit_bindings
    d.swap(MANIFEST)                                 # arrives while disconnected
    d.reconnect()
    assert d.state == LOADING


def test_reconnect_without_pending_goes_idle():
    d = _mk()
    d.disconnect()
    d.reconnect()
    assert d.state == IDLE


def test_selftest_gated_by_state_and_restores():
    d = _mk()
    d.selftest()
    assert d.state == SELFTEST
    _run(d, 2.5)                                     # sweep lasts 2.0 s
    assert d.state == IDLE
    d.swap(MANIFEST)
    _run(d, 2.0)
    d.selftest()                                     # ignored while running
    assert d.state == RUNNING


def test_identify_overlays_without_state_change():
    d = _mk()
    d.identify(duration=0.2)
    render, _ = d.frame(0.05)
    assert d.state == IDLE and len(render) == 2      # idle sig + overlay
    _run(d, 0.5)
    render, _ = d.frame(0.05)
    assert len(render) == 1                          # overlay done


def test_quarantine_then_error_escalation():
    d = _mk()
    d.swap(MANIFEST)
    _run(d, 2.0)
    assert d.state == RUNNING
    b = d.bit_bindings[0]
    for _ in range(QUARANTINE_FRAMES):
        d.frame(0.05)
        d.note_failures([b])
    assert not d.bit_bindings
    assert d.state == ERROR
```

- [ ] **Step 2: Run to verify failure**

Run: `/Users/chris/projects/luxaeterna/.venv/bin/pytest tests/synth/test_director.py -v`
Expected: FAIL — `No module named 'luxaeterna.synth.director'`

- [ ] **Step 3: Implement**

```python
# luxaeterna/synth/director.py
"""Lux Aeterna — StatusDirector: the session state machine.

Decides which state the session is in, which status signature is playing, and
what binding list + global gain the engine should render each frame. All
methods run on the render thread (called by LightSession at drain time)."""

from __future__ import annotations

import logging

from ..logutil import ThrottledLog
from . import registry
from .binding import ActiveBinding, resolve
from .capability import SurfaceCapability
from .manifest import LightManifest
from .status import Signature

log = logging.getLogger(__name__)
_throttle = ThrottledLog(log)

IDLE = "idle"
LOADING = "loading"
RUNNING = "running"
CLOSING = "closing"
ERROR = "error"
DISCONNECTED = "disconnected"
SELFTEST = "selftest"

QUARANTINE_FRAMES = 44          # ~1 s of consecutive failures at 44 Hz


class StatusDirector:
    def __init__(self, cap: SurfaceCapability) -> None:
        self.cap = cap
        self.state = IDLE
        self.bit_bindings: list[ActiveBinding] = []
        self.bit_name = ""
        self.role = ""
        self.pending: LightManifest | None = None
        self._signature: Signature | None = None
        self._sig_binding: ActiveBinding | None = None
        self._overlay: Signature | None = None
        self._overlay_binding: ActiveBinding | None = None
        self._prior = IDLE                    # state to restore after SELFTEST
        self._fails: dict[int, int] = {}
        self._enter_idle()

    # -- internals ----------------------------------------------------------

    def _wrap(self, sig: Signature) -> ActiveBinding:
        return ActiveBinding(obj=sig, zone=self.cap.zone("primary"),
                             blend="add", routes={})

    def _set_signature(self, sig: Signature | None) -> None:
        self._signature = sig
        self._sig_binding = self._wrap(sig) if sig is not None and sig.renders else None

    def _drop_bit(self) -> None:
        self.bit_bindings = []
        self._fails = {}
        self.bit_name = ""
        self.role = ""

    def _enter_idle(self) -> None:
        self.state = IDLE
        self._set_signature(registry.build("sys:idle"))

    def _enter_error(self) -> None:
        self._drop_bit()
        self.state = ERROR
        self._set_signature(registry.build("sys:error"))

    def _enter_closing(self) -> None:
        for b in self.bit_bindings:
            stop = getattr(b.obj, "all_notes_off", None)
            if stop is not None:
                stop()
        self.state = CLOSING
        self._set_signature(registry.build("sys:closing"))

    def _resolve_and_load(self, manifest: LightManifest) -> None:
        try:
            bindings = [resolve(d, self.cap) for d in manifest.instruments]
        except Exception as exc:
            log.warning("manifest resolve failed (bit=%r role=%r): %s",
                        manifest.bit_name, manifest.role, exc)
            self._enter_error()
            return
        self.bit_bindings = bindings
        self._fails = {}
        self.bit_name = manifest.bit_name
        self.role = manifest.role
        self.state = LOADING
        w = manifest.welcome
        if w is not None:
            self._set_signature(
                Signature(registry.build(w.instrument, **w.params), w.duration))
        else:
            self._set_signature(registry.build("sys:loaded"))

    # -- event handlers (drain time) ----------------------------------------

    def swap(self, manifest: LightManifest) -> None:
        if self.state == RUNNING:
            self.pending = manifest
            self._enter_closing()
        elif self.state in (IDLE, LOADING):
            self._drop_bit()
            self._resolve_and_load(manifest)
        else:                       # CLOSING/ERROR/DISCONNECTED/SELFTEST: latest wins
            self.pending = manifest

    def clear(self) -> None:
        self.pending = None
        if self.state == RUNNING:
            self._enter_closing()
        elif self.state == LOADING:
            self._drop_bit()
            self._enter_idle()

    def error(self, reason: str = "") -> None:
        if reason:
            log.warning("session error (bit=%r role=%r): %s",
                        self.bit_name, self.role, reason)
        self._enter_error()

    def disconnect(self) -> None:
        self._drop_bit()
        self.state = DISCONNECTED
        self._set_signature(registry.build("sys:disconnected"))

    def reconnect(self) -> None:
        if self.state != DISCONNECTED:
            return
        if self.pending is not None:
            manifest, self.pending = self.pending, None
            self._resolve_and_load(manifest)
        else:
            self._enter_idle()

    def identify(self, duration: float = 3.0) -> None:
        sig = registry.build("sys:identify")
        sig.duration = float(duration)
        self._overlay = sig
        self._overlay_binding = self._wrap(sig)

    def selftest(self) -> None:
        if self.state not in (IDLE, DISCONNECTED):
            _throttle.log("selftest-ignored", logging.INFO,
                          "selftest ignored in state %s", self.state)
            return
        self._prior = self.state
        self.state = SELFTEST
        self._set_signature(registry.build("sys:selftest"))

    # -- per-frame ----------------------------------------------------------

    def frame(self, dt: float) -> tuple[list[ActiveBinding], float]:
        if self._overlay is not None:
            self._overlay.advance(dt)
            if self._overlay.done:
                self._overlay = None
                self._overlay_binding = None
        gain = 1.0
        if self._signature is not None:
            self._signature.advance(dt)
            gain = self._signature.gain
            if self._signature.done:
                self._on_signature_done()
                gain = self._signature.gain if self._signature is not None else 1.0

        render: list[ActiveBinding] = []
        if self.state in (RUNNING, CLOSING):
            render.extend(self.bit_bindings)
        if self._sig_binding is not None:
            render.append(self._sig_binding)
        if self._overlay_binding is not None:
            render.append(self._overlay_binding)
        return render, gain

    def _on_signature_done(self) -> None:
        if self.state == LOADING:
            self.state = RUNNING
            self._set_signature(None)
        elif self.state in (CLOSING, ERROR):
            if self.state == CLOSING:
                self._drop_bit()
            if self.pending is not None:
                manifest, self.pending = self.pending, None
                self._resolve_and_load(manifest)
            else:
                self._enter_idle()
        elif self.state == SELFTEST:
            if self._prior == DISCONNECTED:
                self.state = DISCONNECTED
                self._set_signature(registry.build("sys:disconnected"))
            else:
                self._enter_idle()

    def note_failures(self, failed: list) -> None:
        failed_ids = {id(b) for b in failed}
        for b in list(self.bit_bindings):
            if id(b) in failed_ids:
                n = self._fails.get(id(b), 0) + 1
                self._fails[id(b)] = n
                if n >= QUARANTINE_FRAMES:
                    self.bit_bindings.remove(b)
                    self._fails.pop(id(b), None)
                    _throttle.log(f"quarantine:{id(b)}", logging.ERROR,
                                  "binding quarantined (bit=%r role=%r)",
                                  self.bit_name, self.role)
            else:
                self._fails.pop(id(b), None)
        if self.state == RUNNING and not self.bit_bindings:
            self.error("all bindings quarantined")
```

- [ ] **Step 4: Run tests**

Run: `/Users/chris/projects/luxaeterna/.venv/bin/pytest tests/synth/test_director.py -v`
Expected: 12 passed

- [ ] **Step 5: Commit**

```bash
git add luxaeterna/synth/director.py tests/synth/test_director.py
git commit -m "feat(synth): StatusDirector — session state machine + signature lifecycle"
```

---

### Task 8: O2Bridge rework + LightSession facade + migrations

This is the wiring task: the bridge's constructor change and the session facade must land together to keep the suite green (build_session and the e2e tests consume both).

**Files:**
- Modify: `luxaeterna/synth/o2bridge.py`
- Modify: `luxaeterna/synth/session.py` (full rewrite)
- Modify: `luxaeterna/synth/__init__.py` (exports)
- Create: `tests/synth/fakes.py` (`FakeO2Lite`)
- Modify: `tests/synth/test_o2bridge.py` (rewrite bridge tests; keep decode/dispatch tests)
- Create: `tests/synth/test_session.py`
- Modify: `tests/synth/test_end_to_end.py` (migrate both tests to the session API)

**Interfaces:**
- Consumes: `EventQueue`/events (Task 3), `StatusDirector` + state constants (Task 7), `LightEngine` (Task 4), `ThrottledLog` (Task 1), manifest v2 (Task 2).
- Produces: `O2Bridge(enqueue: Callable[[int], None])` with `on_midi(packed)` and `attach(o2lite_client, address="/light/midi")` (double-attach raises `RuntimeError`); `dispatch_midi` unchanged in signature but per-binding isolated. `LightSession(cap, clock=time.monotonic)` with the full public API from the spec §7; `build_session(manifest, cap, clock=time.monotonic) -> LightSession`. `FakeO2Lite` mirroring the verified o2litepy API. Used by Tasks 9, 10, and callers.

- [ ] **Step 1: Create the fake o2lite client**

```python
# tests/synth/fakes.py
"""FakeO2Lite — mirrors the VERIFIED o2litepy API (rbdannenberg/o2 and the
copy vendored in rbdannenberg/arco@498e4ab):

- method_new(path, typespec, full, handler, info): 5 required args,
  append-only handler list, no removal API.
- dispatch: first match in registration order wins; handler is called
  handler(address, types, info); payload is pulled via get_int32().

If our attach() drifts from the real contract, tests using this fake fail the
way real hardware would."""

from __future__ import annotations


class FakeO2Lite:
    def __init__(self):
        self.handlers = []          # list of (path, typespec, full, handler, info)
        self._msg_int = None

    def method_new(self, path, typespec, full, handler, info):
        self.handlers.append((path, typespec, full, handler, info))

    def get_int32(self):
        v = self._msg_int
        self._msg_int = None
        return v

    def deliver(self, address, typespec, value):
        """Simulate an inbound message: first-match dispatch, real convention."""
        for (path, ts, full, handler, info) in self.handlers:
            if full and path == address and (ts is None or ts == typespec):
                self._msg_int = value
                handler(address, typespec, info)
                return
        # real o2litepy prints and drops unmatched messages
```

- [ ] **Step 2: Rewrite `tests/synth/test_o2bridge.py`**

Keep `test_decode_midi_packing` verbatim. Replace everything else with:

```python
# tests/synth/test_o2bridge.py
"""Lux Aeterna — tests for the O2 bridge: decode, enqueue, attach contract,
and per-binding dispatch isolation."""

from __future__ import annotations

import pytest
from fakes import FakeO2Lite
from luxaeterna.synth.manifest import LightInstrumentDecl, LightLane
from luxaeterna.synth.capability import shroom_capability
from luxaeterna.synth.binding import resolve
from luxaeterna.synth.o2bridge import O2Bridge, decode_midi, dispatch_midi


def test_decode_midi_packing():
    packed = (0x90 << 16) | (60 << 8) | 100
    assert decode_midi(packed) == (0x90, 60, 100)


def test_on_midi_enqueues_packed_int():
    got = []
    bridge = O2Bridge(got.append)
    bridge.on_midi((0x90 << 16) | (60 << 8) | 100)
    assert got == [(0x90 << 16) | (60 << 8) | 100]


def test_attach_matches_real_o2litepy_contract():
    fake = FakeO2Lite()
    got = []
    bridge = O2Bridge(got.append)
    bridge.attach(fake, "/light/midi")
    assert len(fake.handlers) == 1
    fake.deliver("/light/midi", "i", (0xB0 << 16) | (74 << 8) | 64)
    assert got == [(0xB0 << 16) | (74 << 8) | 64]


def test_double_attach_raises():
    fake = FakeO2Lite()
    bridge = O2Bridge(lambda p: None)
    bridge.attach(fake)
    with pytest.raises(RuntimeError):
        bridge.attach(fake)


def test_dispatch_isolates_bad_route():
    class _BoomBinding:
        routes = {"note": (lambda *a: (_ for _ in ()).throw(RuntimeError("bad")))}
        obj = object()

    decl = LightInstrumentDecl("bloom", "primary", {},
                               [LightLane("note", "trigger")])
    good = resolve(decl, shroom_capability("ie3"))
    dispatch_midi([_BoomBinding(), good], 0x90, 60, 127)   # must not raise
    assert good.obj.voices                                  # good binding got the note
```

- [ ] **Step 3: Rewrite `luxaeterna/synth/o2bridge.py`**

```python
"""Lux Aeterna — O2 input bridge: decode packed-int32 MIDI and dispatch to bindings.

Wire format (ratified): one int32 = (status << 16) | (data1 << 8) | data2,
since o2lite lacks O2's native 'm' MIDI type.

o2litepy contract (verified against rbdannenberg/o2 and the copy vendored in
rbdannenberg/arco@498e4ab): ``method_new(path, typespec, full, handler,
info)`` takes five required args, and handlers are called ``handler(address,
types, info)``, pulling payload values via ``client.get_int32()``. There is NO
handler-removal API — registration is permanent for the life of the client,
which is why attach() refuses to run twice."""

from __future__ import annotations

import logging
from typing import Callable

from ..logutil import ThrottledLog

log = logging.getLogger(__name__)
_throttle = ThrottledLog(log)


def decode_midi(packed: int) -> tuple[int, int, int]:
    return (packed >> 16) & 0xFF, (packed >> 8) & 0xFF, packed & 0xFF


def _call(fn, *args, key: str) -> None:
    try:
        fn(*args)
    except Exception as exc:
        _throttle.log(key, logging.WARNING, "binding route error: %s", exc)


def dispatch_midi(bindings, status: int, d1: int, d2: int) -> None:
    kind = status & 0xF0
    if kind == 0x90 and d2 > 0:                       # note-on
        for b in bindings:
            fn = b.routes.get("note")
            if fn is not None:
                _call(fn, d1, d2 / 127.0, key=f"note:{id(b)}")
    elif kind == 0x80 or (kind == 0x90 and d2 == 0):  # note-off
        for b in bindings:
            noteoff = getattr(b.obj, "noteoff", None)
            if noteoff is not None:
                _call(noteoff, d1, key=f"noteoff:{id(b)}")
    elif kind == 0xB0:                                # control change
        key = f"cc:{d1}"
        for b in bindings:
            fn = b.routes.get(key)
            if fn is not None:
                _call(fn, d2 / 127.0, key=f"{key}:{id(b)}")


class O2Bridge:
    """Receives packed-int32 MIDI from o2lite and enqueues it for the render
    thread; decode/dispatch runs later, at drain time."""

    def __init__(self, enqueue: Callable[[int], None]) -> None:
        self._enqueue = enqueue
        self._attached = False

    def on_midi(self, packed) -> None:
        try:
            self._enqueue(int(packed))
        except Exception as exc:
            _throttle.log("midi-enqueue", logging.WARNING,
                          "dropped MIDI packet %r: %s", packed, exc)

    def attach(self, o2lite_client, address: str = "/light/midi") -> None:
        if self._attached:
            raise RuntimeError(
                "O2Bridge.attach() called twice: o2litepy has no handler "
                "removal, so re-attaching would leak the old handler forever")

        def _handler(addr, types, info):
            self.on_midi(o2lite_client.get_int32())

        o2lite_client.method_new(address, "i", True, _handler, None)
        self._attached = True
```

- [ ] **Step 4: Rewrite `luxaeterna/synth/session.py`**

```python
"""Lux Aeterna — LightSession: the attach-once facade.

Owns the event queue, O2 bridge, status director, and engine. The o2lite
handler is registered exactly once per process and closes over this session —
never over bindings — so bit swaps can never leak into o2litepy's append-only
handler table. All graph mutation happens on the render thread at frame
boundaries (queue drain)."""

from __future__ import annotations

import logging
import time

from ..logutil import ThrottledLog
from .capability import SurfaceCapability
from .director import RUNNING, StatusDirector
from .engine import LightEngine
from .events import ClearEvent, EventQueue, MidiEvent, StatusEvent, SwapEvent
from .manifest import LightManifest
from .o2bridge import O2Bridge, decode_midi, dispatch_midi

log = logging.getLogger(__name__)
_throttle = ThrottledLog(log)


class LightSession:
    def __init__(self, cap: SurfaceCapability, clock=time.monotonic) -> None:
        self.cap = cap
        self._clock = clock
        self._queue = EventQueue()
        self._bridge = O2Bridge(lambda packed: self._queue.put(MidiEvent(packed)))
        self._director = StatusDirector(cap)
        self._engine = LightEngine(cap)
        self._frame = 0
        self._start: float | None = None
        self._last: float | None = None

    # -- wiring (once, at device startup) -----------------------------------

    def attach(self, o2lite_client, address: str = "/light/midi") -> None:
        self._bridge.attach(o2lite_client, address)

    # -- lifecycle (thread-safe: applied at the next frame boundary) --------

    def swap(self, manifest: LightManifest) -> None:
        self._queue.put(SwapEvent(manifest))

    def clear(self) -> None:
        self._queue.put(ClearEvent())

    def error(self, reason: str = "") -> None:
        self._queue.put(StatusEvent("error", reason))

    def notify_disconnect(self) -> None:
        self._queue.put(StatusEvent("disconnect"))

    def notify_reconnect(self) -> None:
        self._queue.put(StatusEvent("reconnect"))

    def identify(self, duration: float = 3.0) -> None:
        self._queue.put(StatusEvent("identify", duration))

    def selftest(self) -> None:
        self._queue.put(StatusEvent("selftest"))

    # -- introspection ------------------------------------------------------

    @property
    def state(self) -> str:
        return self._director.state

    @property
    def bit_name(self) -> str:
        return self._director.bit_name

    # -- render thread (wire as OutputLoop's on_frame) ----------------------

    def render_into(self, universe) -> None:
        now = self._clock()
        if self._start is None:
            self._start = now
            self._last = now
        t = now - self._start
        dt = max(now - self._last, 1e-6)
        self._last = now

        for ev in self._queue.drain():
            self._apply(ev)

        bindings, gain = self._director.frame(dt)
        failed = self._engine.render_into(universe, bindings, t, dt,
                                          self._frame, gain)
        self._director.note_failures(failed)
        self._frame += 1

    def _apply(self, ev) -> None:
        if isinstance(ev, MidiEvent):
            if self._director.state == RUNNING:
                status, d1, d2 = decode_midi(ev.packed)
                dispatch_midi(self._director.bit_bindings, status, d1, d2)
            else:
                _throttle.log("midi-dropped", logging.DEBUG,
                              "MIDI dropped in state %s", self._director.state)
        elif isinstance(ev, SwapEvent):
            self._director.swap(ev.manifest)
        elif isinstance(ev, ClearEvent):
            self._director.clear()
        elif isinstance(ev, StatusEvent):
            if ev.kind == "error":
                self._director.error(ev.arg or "")
            elif ev.kind == "disconnect":
                self._director.disconnect()
            elif ev.kind == "reconnect":
                self._director.reconnect()
            elif ev.kind == "identify":
                self._director.identify(ev.arg if ev.arg is not None else 3.0)
            elif ev.kind == "selftest":
                self._director.selftest()


def build_session(manifest: LightManifest, cap: SurfaceCapability,
                  clock=time.monotonic) -> LightSession:
    """Construct a session with the initial bit swap already enqueued."""
    session = LightSession(cap, clock=clock)
    session.swap(manifest)
    return session
```

- [ ] **Step 5: Export the public API — `luxaeterna/synth/__init__.py`**

```python
"""Lux Aeterna — synth: the light-synthesis engine (the Arco-analog layer)."""

from __future__ import annotations

from .session import LightSession, build_session  # noqa: F401
```

- [ ] **Step 6: Write `tests/synth/test_session.py`**

```python
# tests/synth/test_session.py
"""Tests for the LightSession facade: queue-driven lifecycle + MIDI gating."""

from __future__ import annotations

from luxaeterna.synth.capability import shroom_capability
from luxaeterna.synth.manifest import LightManifest
from luxaeterna.synth.session import LightSession, build_session
from luxaeterna.universe import Universe

MANIFEST = {
    "bit_name": "e2e", "instruments": [{
        "instrument": "bloom", "target": "primary",
        "lanes": [{"source": "note", "dest": "trigger"},
                  {"source": "cc:74", "dest": "hue"}],
    }]
}


def _mk(dt=0.02, steps=600):
    cap = shroom_capability("ie3")
    clk = iter([i * dt for i in range(steps)]).__next__
    return LightSession(cap, clock=clk), Universe()


def _run_until(session, uni, state, limit=400):
    for _ in range(limit):
        session.render_into(uni)
        if session.state == state:
            return
    raise AssertionError(f"never reached {state!r} (at {session.state!r})")


def test_full_lifecycle_idle_loading_running_closing_idle():
    session, uni = _mk()
    assert session.state == "idle"
    session.swap(LightManifest.from_dict(MANIFEST))
    _run_until(session, uni, "running")
    assert session.bit_name == "e2e"
    session.clear()
    session.render_into(uni)
    assert session.state == "closing"
    _run_until(session, uni, "idle")
    assert session.bit_name == ""


def test_midi_dropped_outside_running_dispatched_inside():
    session, uni = _mk()
    session.swap(LightManifest.from_dict(MANIFEST))
    session._bridge.on_midi((0x90 << 16) | (60 << 8) | 127)   # during LOADING
    _run_until(session, uni, "running")
    synth = session._director.bit_bindings[0].obj
    assert not synth.voices                                    # dropped

    session._bridge.on_midi((0x90 << 16) | (60 << 8) | 127)   # while RUNNING
    session.render_into(uni)
    assert synth.voices                                        # dispatched


def test_status_events_route_to_director():
    session, uni = _mk()
    session.notify_disconnect()
    session.render_into(uni)
    assert session.state == "disconnected"
    session.notify_reconnect()
    session.render_into(uni)
    assert session.state == "idle"


def test_build_session_enqueues_initial_swap():
    cap = shroom_capability("ie3")
    clk = iter([i * 0.02 for i in range(600)]).__next__
    session = build_session(LightManifest.from_dict(MANIFEST), cap, clock=clk)
    uni = Universe()
    session.render_into(uni)
    assert session.state == "loading"
```

- [ ] **Step 7: Migrate `tests/synth/test_end_to_end.py`**

Full replacement:

```python
"""Lux Aeterna — end-to-end integration: manifest -> session -> O2 -> engine ->
DMX, plus a performance smoke test for the full per-frame hot path (queue
drain + director + engine)."""

from __future__ import annotations

import time

from fakes import FakeO2Lite
from luxaeterna.synth.capability import SurfaceCapability, Zone, shroom_capability
from luxaeterna.synth.manifest import LightManifest
from luxaeterna.synth.session import build_session
from luxaeterna.universe import Universe


MANIFEST = {
    "instruments": [{
        "instrument": "bloom", "target": "primary", "params": {"hue": 1.0 / 3.0},   # green default; CC74=0 must drive it to red
        "lanes": [{"source": "note", "dest": "trigger"},
                  {"source": "cc:74", "dest": "hue"}],
    }]
}


def test_note_over_o2_lights_the_shroom():
    cap = shroom_capability("ie3")
    clk = iter([i * 0.02 for i in range(400)]).__next__
    session = build_session(LightManifest.from_dict(MANIFEST), cap, clock=clk)
    fake = FakeO2Lite()
    session.attach(fake)
    uni = Universe()

    for _ in range(200):                            # ride out sys:loaded (1.5 s)
        session.render_into(uni)
        if session.state == "running":
            break
    assert session.state == "running"
    session.render_into(uni)
    assert max(uni.get_frame()[:36]) == 0           # running, dark before note

    fake.deliver("/light/midi", "i", (0xB0 << 16) | (74 << 8) | 0)   # CC74=0 -> red
    fake.deliver("/light/midi", "i", (0x90 << 16) | (60 << 8) | 127) # note-on
    session.render_into(uni)
    frame = uni.get_frame()[:36]
    assert max(frame) > 0                            # lit after note

    # GRB order: byte 0 = green, byte 1 = red. Red hue -> red channel dominant.
    reds = frame[1::3]
    greens = frame[0::3]
    assert max(reds) > max(greens)


def test_perf_1000px_within_frame_budget():
    # 1000 px * 3 ch = 3000 DMX channels > one universe, so measure the full
    # session hot path against a null transport.
    cap = SurfaceCapability("array", 1000, "GRB", [Zone("primary", 0, 1000)])
    clk = iter([i * (1 / 44) for i in range(500)]).__next__
    session = build_session(LightManifest.from_dict(MANIFEST), cap, clock=clk)

    class _NullUniverse:
        def set_range(self, start, values):
            pass

    uni = _NullUniverse()
    for _ in range(200):
        session.render_into(uni)
        if session.state == "running":
            break
    assert session.state == "running"
    session._bridge.on_midi((0x90 << 16) | (60 << 8) | 127)
    session.render_into(uni)

    t0 = time.perf_counter()
    for _ in range(44):
        session.render_into(uni)
    elapsed = time.perf_counter() - t0
    assert elapsed / 44 < 0.0227          # avg frame < 22.7 ms (44 Hz budget)
```

- [ ] **Step 8: Run the full suite**

Run: `/Users/chris/projects/luxaeterna/.venv/bin/pytest -q`
Expected: all pass (session, bridge, e2e, and every earlier test).

- [ ] **Step 9: Commit**

```bash
git add luxaeterna/synth/o2bridge.py luxaeterna/synth/session.py luxaeterna/synth/__init__.py tests/synth/fakes.py tests/synth/test_o2bridge.py tests/synth/test_session.py tests/synth/test_end_to_end.py
git commit -m "feat(synth): attach-once LightSession facade; corrected o2litepy contract; queue-driven swaps"
```

---

### Task 9: Leak regression + threading stress

**Files:**
- Create: `tests/synth/test_lifecycle_stress.py`

**Interfaces:**
- Consumes: `LightSession` (Task 8), `FakeO2Lite` (Task 8), `shroom_capability`, `LightManifest`.
- Produces: the two headline regression tests. Nothing downstream.

- [ ] **Step 1: Write both tests**

```python
# tests/synth/test_lifecycle_stress.py
"""The review's headline regressions: 100 bit swaps must leave exactly one
o2lite handler and zero retained graphs; concurrent producers must never
crash the render thread (the old voices-dict race)."""

from __future__ import annotations

import gc
import threading
import weakref

from fakes import FakeO2Lite
from luxaeterna.synth.capability import shroom_capability
from luxaeterna.synth.manifest import LightManifest
from luxaeterna.synth.session import LightSession
from luxaeterna.universe import Universe

MANIFEST = {
    "instruments": [{
        "instrument": "bloom", "target": "primary",
        "lanes": [{"source": "note", "dest": "trigger"}],
    }]
}


class _StepClock:
    def __init__(self, dt=0.05):
        self.t = 0.0
        self.dt = dt

    def __call__(self):
        self.t += self.dt
        return self.t


def _drive(session, uni, seconds, dt=0.05):
    for _ in range(int(seconds / dt)):
        session.render_into(uni)


def test_hundred_swaps_leave_one_handler_and_no_garbage():
    session = LightSession(shroom_capability("ie3"), clock=_StepClock())
    fake = FakeO2Lite()
    session.attach(fake)
    uni = Universe()
    refs = []

    for _ in range(100):
        session.swap(LightManifest.from_dict(MANIFEST))
        _drive(session, uni, 3.0)          # close fade + load signature + settle
        assert session.state == "running"
        refs.append(weakref.ref(session._director.bit_bindings[0]))

    assert len(fake.handlers) == 1          # attach-once held across 100 bits

    session.clear()
    _drive(session, uni, 2.0)
    assert session.state == "idle"
    gc.collect()
    assert all(r() is None for r in refs)   # every bit's graph was collected


def test_threaded_producers_never_crash_render():
    session = LightSession(shroom_capability("ie3"), clock=_StepClock(dt=0.01))
    uni = Universe()
    session.swap(LightManifest.from_dict(MANIFEST))
    _drive(session, uni, 3.0, dt=0.01)
    assert session.state == "running"

    stop = threading.Event()

    def hammer_midi():
        i = 0
        while not stop.is_set():
            session._bridge.on_midi((0x90 << 16) | ((60 + i % 12) << 8) | 100)
            session._bridge.on_midi((0x80 << 16) | ((60 + i % 12) << 8) | 0)
            i += 1

    def hammer_swaps():
        while not stop.is_set():
            session.swap(LightManifest.from_dict(MANIFEST))

    threads = [threading.Thread(target=hammer_midi),
               threading.Thread(target=hammer_swaps)]
    for th in threads:
        th.start()
    try:
        for _ in range(500):
            session.render_into(uni)        # a raise here fails the test
    finally:
        stop.set()
        for th in threads:
            th.join(timeout=2)
```

- [ ] **Step 2: Run**

Run: `/Users/chris/projects/luxaeterna/.venv/bin/pytest tests/synth/test_lifecycle_stress.py -v`
Expected: 2 passed. (If the leak test fails, something is retaining retired bindings — check for stray strong references in the director before weakening the test.)

- [ ] **Step 3: Commit**

```bash
git add tests/synth/test_lifecycle_stress.py
git commit -m "test(synth): leak regression (100 swaps, 1 handler, 0 retained) + threaded producer stress"
```

---

### Task 10: OutputLoop throttled logging + serial write_timeout

**Files:**
- Modify: `luxaeterna/output.py`
- Modify: `luxaeterna/backends/serial_enttec.py`
- Test: `tests/test_output_hook.py` (append), Create: `tests/backends/test_serial_enttec.py`

**Interfaces:**
- Consumes: `ThrottledLog` (Task 1).
- Produces: OutputLoop default error logging throttled (the `on_error` callback path is unchanged); both ENTTEC backends accept `write_timeout: float = 0.05` and pass it to `serial.Serial`.

- [ ] **Step 1: Append the failing throttle test to `tests/test_output_hook.py`**

```python
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
```

(Match this file's existing imports — it already imports `Universe` and `OutputLoop`.)

- [ ] **Step 2: Write the failing serial test**

```python
# tests/backends/test_serial_enttec.py
"""ENTTEC backends must open pyserial with a write timeout so a wedged USB
device cannot block the output thread indefinitely."""

from __future__ import annotations

import types

from luxaeterna.backends import serial_enttec


def _fake_serial_module(calls):
    class _FakeSerial:
        def __init__(self, **kwargs):
            calls.update(kwargs)
            self.is_open = True

        def close(self):
            pass

    return types.SimpleNamespace(Serial=_FakeSerial, EIGHTBITS=8,
                                 STOPBITS_TWO=2, PARITY_NONE="N")


def test_enttec_open_sets_write_timeout(monkeypatch):
    calls = {}
    monkeypatch.setattr(serial_enttec, "serial", _fake_serial_module(calls))
    b = serial_enttec.ENTTECOpen("/dev/fake")
    b.open()
    assert calls["write_timeout"] == 0.05


def test_enttec_pro_sets_write_timeout(monkeypatch):
    calls = {}
    monkeypatch.setattr(serial_enttec, "serial", _fake_serial_module(calls))
    b = serial_enttec.ENTTECPro("/dev/fake", write_timeout=0.1)
    b.open()
    assert calls["write_timeout"] == 0.1
```

- [ ] **Step 3: Run to verify failures**

Run: `/Users/chris/projects/luxaeterna/.venv/bin/pytest tests/test_output_hook.py tests/backends/test_serial_enttec.py -v`
Expected: the 3 new tests FAIL.

- [ ] **Step 4: Implement — `luxaeterna/output.py`**

Add `from .logutil import ThrottledLog` to the imports. In `OutputLoop.__init__`, add:

```python
        self._throttle = ThrottledLog(log)
```

In `_loop_once`, replace the two `log.error(...)` calls:

```python
            except Exception as exc:
                if self.on_error:
                    self.on_error(exc)
                else:
                    self._throttle.log(
                        f"on_frame:{self.universe.universe_id}", logging.ERROR,
                        "on_frame hook error on universe %d: %s",
                        self.universe.universe_id, exc)
```

and

```python
            except Exception as exc:
                if self.on_error:
                    self.on_error(exc)
                else:
                    self._throttle.log(
                        f"send:{self.universe.universe_id}", logging.ERROR,
                        "Output error on universe %d: %s",
                        self.universe.universe_id, exc)
```

- [ ] **Step 5: Implement — `luxaeterna/backends/serial_enttec.py`**

Both classes: add the parameter and pass it through.

```python
    def __init__(self, port: str = "/dev/ttyUSB0",
                 write_timeout: float = 0.05) -> None:
        if serial is None:
            raise ImportError("pyserial is required for ENTTEC backends: pip install pyserial")
        self.port = port
        self.write_timeout = write_timeout
        self._serial: serial.Serial | None = None  # type: ignore[name-defined]
```

`ENTTECOpen.open()` gains `write_timeout=self.write_timeout` in the `serial.Serial(...)` kwargs; same for `ENTTECPro.open()`. (pyserial raises `SerialTimeoutException`, an `OSError` subclass, on timeout — the existing `except OSError` in `send()` already converts it to `BackendError`; note this in a comment above the `except OSError` line in both `send` methods:)

```python
        # SerialTimeoutException (write_timeout hit) is an OSError subclass —
        # a wedged device surfaces as BackendError instead of a blocked thread.
```

- [ ] **Step 6: Run the full suite**

Run: `/Users/chris/projects/luxaeterna/.venv/bin/pytest -q`
Expected: all pass (the existing `test_on_frame_exception_is_routed_to_on_error_and_loop_survives` must still pass — the `on_error` path is not throttled).

- [ ] **Step 7: Commit**

```bash
git add luxaeterna/output.py luxaeterna/backends/serial_enttec.py tests/test_output_hook.py tests/backends/test_serial_enttec.py
git commit -m "fix(output): throttle default error logging; serial write_timeout so a wedged device can't stall the render thread"
```

---

## Self-Review Checklist (run after Task 10)

- Full suite green: `/Users/chris/projects/luxaeterna/.venv/bin/pytest -q`
- Spec §4 (o2litepy contract) → Task 8; §5 (state machine) → Task 7; §6 (signatures) → Task 5; §7 (public API) → Task 8; §8.1 (isolation/quarantine) → Tasks 4+7; §8.2 (throttled logging) → Tasks 1, 7, 8, 10; §8.3 (serial) → Task 10; §8.4 (positions cache) → Task 4; §9 (manifest v2) → Task 2; §10.1–10.7 (tests) → Tasks 8, 9, and per-task suites.
- Perf budget holds with the full session path in the loop (Task 8 perf test).
