# Bounded per-frame event drain

**Date:** 2026-07-22
**Status:** Approved (fast-follow from the session-lifecycle final review)
**Scope:** `luxaeterna/synth/events.py`, `luxaeterna/synth/session.py`, tests

## 1. Problem

`EventQueue.drain()` returns *everything* enqueued since the last frame, and
`LightSession.render_into` applies every returned event before rendering. A
large MIDI burst (broken producer, network replay, hostile peer) therefore
blows the 22.7 ms / 44 Hz frame budget in a single frame, and the queue's
memory is unbounded until the drain happens.

The final session-lifecycle review classified this as a fast-follow with
**MIDI-only bounding**: MIDI events are ephemeral real-time data and may be
dropped; control-plane events (`SwapEvent`, `ClearEvent`, `StatusEvent`)
drive the state machine and must **never** be dropped.

## 2. Design

Split `EventQueue` internally by event class, behind the unchanged `put()` /
`drain()` surface:

- **MIDI lane** — `deque(maxlen=midi_capacity)`, default capacity **256**.
  Overflow drops the *oldest* event (fresh MIDI beats stale MIDI for live
  lighting). Drops are counted exactly under the existing lock.
- **Control lane** — unbounded `deque`. `SwapEvent`, `ClearEvent`, and
  `StatusEvent` are never dropped, structurally.

`put(event)` routes by `isinstance(event, MidiEvent)`; producer call sites
(`O2Bridge`, session lifecycle methods) are unchanged. One lock covers both
lanes.

`drain()` still returns a single list: **MIDI first, control last.** Within
each lane arrival order is exact. Cross-lane order is intentionally relaxed
(events landing in the same 22.7 ms window are effectively concurrent);
putting control last means the control plane has the final word every frame
— e.g. a `ClearEvent` always wins over MIDI drained in the same frame, so a
flood can never re-trigger voices after a clear. MIDI applied around a
transition is already dropped by the director's RUNNING-state gate.

New accessor `take_dropped() -> int` returns and resets the drop count.
`render_into` reads it after the drain and emits a **throttled WARNING** via
the existing `ThrottledLog` (`"midi-overflow"` key) — `events.py` stays a
pure, logger-free structure.

### Capacity rationale

Full-rate DIN MIDI (31.25 kbaud) is ~1,000 msgs/s ≈ 23 msgs per 44 Hz frame.
256 gives >10× headroom for legitimate network bursts while dispatching in
well under 1 ms. Constructor parameter `midi_capacity` (default 256) keeps it
tunable per installation.

## 3. Rejected alternatives

- **Per-frame processed-MIDI cap, remainder carried:** memory stays unbounded
  under sustained flood (this branch exists to fix latency *and* memory
  leaks), and stale MIDI replayed seconds late is worse for lighting than
  dropping it. Control events buried behind the backlog would need O(n)
  scan-ahead every frame to stay timely — reordering anyway.
- **Bound the whole queue:** could drop a `SwapEvent`; violates the
  never-drop-control invariant outright.

## 4. Contract changes

- `EventQueue.drain()` no longer preserves *cross-class* arrival order
  (MIDI now precedes control within one drain). The existing
  `test_fifo_order_and_drain_empties` asserts the old interleaving and is
  updated to per-lane order.
- `EventQueue(midi_capacity=256)` — new optional constructor parameter.
- New method `EventQueue.take_dropped()`.

## 5. Testing

1. **Flood regression (from the review):** enqueue one `SwapEvent` and
   100,000 `MidiEvent`s before a single `render_into`; assert wall time for
   the frame stays under 22.7 ms, the swap reached the state machine (the
   director is no longer in IDLE), and nothing carries into the next drain.
2. **Drop-oldest bounding:** cap+K MIDI puts → drain yields exactly `cap`
   events, the newest K..cap+K in order; `take_dropped()` returns K then 0.
3. **Control never dropped:** control events interleaved throughout a 10k
   flood all survive, in arrival order relative to each other.
4. **Overflow log throttled:** a flood produces one WARNING per throttle
   interval, not one per frame.
5. Existing per-lane FIFO and concurrent-put tests updated/retained.
