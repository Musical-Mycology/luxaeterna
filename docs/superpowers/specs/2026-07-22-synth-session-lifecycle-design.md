# Lux Aeterna — Session Lifecycle & Status Visual Language

**Status:** Approved in brainstorm, pending spec review
**Date:** 2026-07-22
**Scope:** Bit session lifecycle (create/swap/destroy), corrected o2litepy contract,
a system status visual language, manifest v2 (bit identity + per-role welcome),
and four riding fixes from the 2026-07-22 latency/memory review.

---

## 1. Motivation

A latency/memory-leak review of the v1 LightArco engine (spec:
`2026-07-21-lightarco-engine-design.md`) found that the synth layer has **no
destroy path at all**, and that the real o2litepy API makes this fatal rather
than merely untidy. Verified against the actual source
(`rbdannenberg/o2`, `o2litepy/src/o2lite.py`):

1. **`method_new` takes five required args** `(path, typespec, full, handler,
   info)` — `O2Bridge.attach()` passes four, so it raises `TypeError` on first
   real wiring. The handler convention is `handler(address, types, info)` with
   values pulled via `client.get_int32()` — not the `(ts, addr, types, *args)`
   shape the current lambda assumes.
2. **Handlers accumulate and cannot be removed.** `method_new` appends to a
   plain list; dispatch scans in registration order and returns at the first
   match; there is no `method_free`/unregister anywhere in o2litepy. An
   attach-per-bit pattern therefore (a) pins every retired session's full graph
   (bindings → voices → envelopes → arrays) for the life of the client, and
   (b) keeps routing MIDI to the *first* bit ever attached while later bits'
   handlers sit shadowed behind it.
3. The device model makes this worse: per
   `mm-terrarium/docs/control-gameserver-design.md`, a Shroom joins as an
   o2lite client **once at power-on** and stays up for the whole installation,
   while Bits/roles swap many times mid-session.

The same review found four riding defects, folded into this spec (§8):
a cross-thread race on `LightSynth.voices`, no per-binding exception isolation,
unthrottled 44 Hz error logging, and blocking serial writes.

Finally: a bare fade between bits communicates nothing but "done". The Shroom's
LEDs are the device's only face — this spec gives lifecycle events a small,
consistent **status visual language** (§6) so the room can distinguish
"loading", "loaded successfully", "error", "disconnected", and "alive but idle"
at a glance.

## 2. Design pillars (settled in brainstorm)

1. **Attach once, swap contents.** The o2lite handler is registered exactly
   once per process and closes over the long-lived `LightSession`, never over
   bindings. Bit changes swap the session's *contents*. This works with
   o2litepy's append-only handler table instead of against it; the leak becomes
   structurally impossible rather than a caller obligation.
2. **All graph mutation on the render thread.** Inbound MIDI, swaps, and status
   commands are events in one thread-safe queue, drained at the top of each
   frame. Voices dicts, envelopes, bindings, and signatures are render-thread-
   only — the voices-dict race is eliminated by construction, not by locking.
3. **Facade + director split.** `LightSession` (public API, queue, coordination)
   owns a `StatusDirector` (state machine + signature selection). Bridge decodes
   and enqueues; engine renders what it is handed; director decides; session
   coordinates. Each unit is testable alone.
4. **Signatures are ordinary instruments.** Every status gesture is a
   `LightInstrument` built from the existing uGen vocabulary, registered under
   reserved `sys:*` names, installation-overridable via the registry, created at
   transition time and dropped when done — the same create/destroy discipline
   as voices.
5. **Luxaeterna stays a caller-driven library.** The device app owns the o2lite
   client, its polling loop, and connection monitoring; it informs the session
   via `notify_disconnect()`/`notify_reconnect()`. `attach()` keeps taking the
   client as a parameter.
6. **MIDI is dropped outside RUNNING.** Transitions last ≲1.5 s; the outgoing
   bit must not react and the incoming bit does not exist yet. Buffering across
   a bit boundary would replay stale notes into the wrong instrument.

## 3. Architecture

```
O2 thread:       o2lite poll → handler → get_int32() → session.enqueue(MidiEvent)
caller threads:  session.swap(manifest) / clear() / error() / identify() … → enqueue

render thread (OutputLoop.on_frame → session.render_into):
  1. drain queue in arrival order   (MIDI dispatch, swaps, status — ALL graph
                                     mutation happens here, single-threaded)
  2. director.advance()             (signature done? → state transition)
  3. compose render list + gain     (bit bindings, system signature, overlays)
  4. engine renders list → DMX bytes → universe.set_range
```

The queue is the only structure touched by multiple threads.

### 3.1 Module layout

| File | Responsibility |
|------|----------------|
| `luxaeterna/synth/events.py` (new) | `MidiEvent`, `SwapEvent`, `ClearEvent`, `StatusEvent` + thread-safe queue (enqueue any thread; drain-all on render thread) |
| `luxaeterna/synth/session.py` (rewritten) | `LightSession` facade: public API (§7), owns queue + bridge + director + current bindings. `build_session(manifest, cap)` returns a `LightSession` with the initial swap enqueued (breaking change to the v1 tuple return; no external callers exist) |
| `luxaeterna/synth/director.py` (new) | `StatusDirector`: the state machine (§5), signature lifecycle, render-list + gain composition |
| `luxaeterna/synth/status.py` (new) | Built-in `sys:*` signature factories (§6) + `Signature` wrapper |
| `luxaeterna/synth/o2bridge.py` (changed) | Corrected o2litepy contract (§4); `on_midi` enqueues; pure `decode_midi`/`dispatch_midi` unchanged, called at drain time |
| `luxaeterna/synth/manifest.py` (changed) | Manifest v2: `bit_name`, `bit_version`, `role`, `welcome: SignatureDecl` (§9); `from_dict` back-compatible |
| `luxaeterna/synth/engine.py` (changed) | Renders the binding list handed to it; per-binding isolation + quarantine (§8.1); optional global `gain`; lazy per-zone positions cache |
| `luxaeterna/output.py` (changed) | Throttled default error logging (§8.2) |
| `luxaeterna/backends/serial_enttec.py` (changed) | `write_timeout` (§8.3) |

## 4. Corrected o2litepy contract

Verified against `o2litepy/src/o2lite.py` (commit `6c83cf6`):

```python
# registration — info arg is REQUIRED, no default
client.method_new("/light/midi", "i", True, handler, None)

# dispatch convention — o2litepy calls handler(address, types, info);
# payload values are pulled sequentially from the client per the typespec
def handler(address, types, info):
    session.enqueue(MidiEvent(client.get_int32()))
```

`attach(o2lite_client, address="/light/midi")` performs this registration and
guards against double-attach (second call raises `RuntimeError` — o2litepy has
no removal API, so a second registration would be a permanent leak).

## 5. Session state machine

Six states; all transitions applied at frame boundaries by the director.

```
IDLE ──swap──► LOADING ──done──► RUNNING ──swap/clear──► CLOSING ──done──► IDLE
  ▲               │                  │                       │        (or LOADING
  │            resolve            error()/                   │         if a swap
  │            failure            collapse                   │         is pending)
  │               ▼                  ▼                       │
  └──done──── ERROR ◄────────────────┘                       │
  ▲                                                          │
  └── reconnect ── DISCONNECTED ◄── disconnect (any state) ──┘
```

- **IDLE** — renders `sys:idle` (dim slow breathing, loops forever). The
  "connected, alive, no bit" beacon; distinguishes a waiting device from a dead
  one in a dark room.
- **LOADING** — plays the bit's welcome signature if its manifest declares one,
  **else** `sys:loaded`. The declared welcome *replaces* the generic green (one
  ceremony, not two); the green flash is the universal fallback so every bit
  gets load feedback. Bit bindings are already resolved but not live; the
  signature plays alone on black. Done → RUNNING.
- **RUNNING** — bit bindings render; MIDI dispatches. The only state where MIDI
  reaches instruments; elsewhere it is dropped (debug-throttled).
- **CLOSING** — bit bindings are retained; all voices gated off at entry
  (releases play out); `sys:closing` drives a global gain ramp 1→0 (default
  600 ms). Done → pending manifest if queued, else IDLE. Old-graph retention is
  bounded by the fade; afterwards nothing references it.
- **ERROR** — entered on `session.error()`, manifest resolve failure, or total
  binding collapse (§8.1). Bit dropped immediately; `sys:error` plays
  (rise to red, fall to black). Done → IDLE, or LOADING if a swap is pending.
- **DISCONNECTED** — entered from any state on `notify_disconnect()`; bit
  dropped; `sys:disconnected` loops (red double-blink, then dim red breathing —
  reads as "trying", distinct from terminal error). `notify_reconnect()` →
  LOADING if a swap arrived while disconnected, else IDLE (Control re-sends the
  role/manifest per the gameserver flow).

Cross-cutting rules:

- **Latest-wins swaps.** A swap during CLOSING replaces the pending manifest;
  during LOADING it aborts the never-ran bit and restarts LOADING with the new
  manifest; during ERROR/DISCONNECTED it is held as pending. No swap queue
  deeper than one.
- **Overlays don't change state.** `identify()` renders `sys:identify`
  additively on top of any state for its duration (default 3 s). `selftest()`
  is honored only in IDLE/DISCONNECTED, plays `sys:selftest`, returns to the
  prior state; elsewhere ignored with a throttled log.

## 6. Status visual language

### 6.1 Signature contract

```python
class Signature:
    def render(self, ctx) -> np.ndarray   # (n, channels), like any instrument
    def gain(self) -> float               # 1.0 unless a gain-style signature
    @property
    def done(self) -> bool                # duration-based
```

A `Signature` wraps an instrument built from a registry factory plus a
duration. `sys:closing` is the one gain-style signature: it renders nothing and
produces the 1→0 ramp applied to the retained bit surface. Signatures are
created on the render thread at transition time and dropped when done.

### 6.2 Built-in vocabulary (v1)

| Name | Gesture | Trigger |
|------|---------|---------|
| `sys:idle` | dim slow breathing (loops) | IDLE |
| `sys:loaded` | green flash, then 2 soft green pulses | LOADING (no welcome declared) |
| `sys:closing` | global gain fade 1→0, 600 ms | CLOSING |
| `sys:error` | rise to red, fall to black | ERROR |
| `sys:disconnected` | red double-blink, then dim red breathing (loops) | DISCONNECTED |
| `sys:identify` | distinctive wave overlay, 3 s | `identify()` |
| `sys:selftest` | R→G→B→W channel sweep | `selftest()` |

Reserved names, **not implemented in v1** (need gameserver verbs):
`sys:role-adopted`, `sys:role-denied`, `sys:goodbye`.

All names resolve through the existing instrument registry;
an installation overrides a gesture by re-registering the name.

## 7. Public API

```python
session = LightSession(cap, clock=time.monotonic)

# wiring (once, at device startup)
session.attach(o2lite_client, address="/light/midi")
loop = OutputLoop(universe, backend, always_send=True,
                  on_frame=session.render_into)

# lifecycle (thread-safe: enqueue, applied at next frame boundary)
session.swap(manifest)           # close-fade → welcome → running
session.clear()                  # close-fade → idle
session.error(reason="")         # error signature → idle

# link status (from the device app's connection monitoring)
session.notify_disconnect()
session.notify_reconnect()

# ops
session.identify(duration=3.0)
session.selftest()

# introspection (read-only snapshots)
session.state                    # "idle" | "loading" | "running" | ...
session.bit_name
```

`build_session(manifest, cap)` constructs a session with the initial swap
enqueued.

## 8. Riding fixes

### 8.1 Per-binding exception isolation + quarantine

Each binding renders in its own try/except; one failure skips that binding and
the rest of the surface still updates. A binding failing **44 consecutive
frames (~1 s)** is quarantined — removed from the render list, throttle-logged
with `bit_name`/`role` context. When *all* bit bindings are quarantined the
director escalates to ERROR. The same per-binding isolation applies in
`dispatch_midi` (which now runs at drain time on the render thread), so one bad
route no longer starves later bindings.

### 8.2 Throttled logging

`ThrottledLog` helper (per-key: first occurrence logs immediately, then at most
one line per 5 s carrying a suppressed-count). Applied to: the OutputLoop error
path (today 44 lines/s when a backend dies), quarantine notices, dropped-MIDI
debug lines, ignored-selftest notices. The `on_error` callback path is
unchanged for callers with their own policy.

### 8.3 Serial write timeout

Both ENTTEC backends open pyserial with `write_timeout=0.05` (≈2 frame
periods, constructor-overridable). A timeout surfaces as `BackendError` — the
loop survives, throttle-logged — instead of blocking the render thread
indefinitely under a wedged USB device.

### 8.4 Engine positions cache

`LightEngine._positions` becomes a lazy per-zone-name cache populated on first
render, since the binding list now changes at runtime (fixes the latent
KeyError on swap).

## 9. Manifest v2 — the Bit light-contract

```python
@dataclass
class SignatureDecl:                  # a declarable one-shot light gesture
    instrument: str                   # any registered instrument name
    params: dict = field(default_factory=dict)
    duration: float = 1.5             # seconds until done

@dataclass
class LightManifest:
    instruments: list[LightInstrumentDecl]        # unchanged from v1
    bit_name: str = ""                            # Bit identity (telemetry/logs)
    bit_version: str = ""
    role: str = ""                                # role this was resolved for
    welcome: SignatureDecl | None = None          # plays in LOADING instead of sys:loaded
```

- `from_dict` stays backward-compatible: a v1 dict with only `instruments`
  parses with new fields defaulting empty.
- **Per-role welcomes need no role table here.** Control resolves roles and
  ships a per-role config blob (`/ie<N>/role "sssib" bit role class channel
  config`); each role's blob carries its own `LightManifest` with its own
  `welcome`. `role`/`bit_name` are provenance for logs and error context.
- **Sound + light pairing.** The audio half of a welcome lives in the Bit's
  `ugen_manifest`/cue logic on the Arco side; both halves trigger off the same
  role-adoption message. Alignment within O2 delivery jitter is sufficient for
  a ~1.5 s greeting; no sync protocol.

## 10. Testing strategy (no hardware)

1. **Leak regression (headline).** 100 swap cycles against a fake o2lite
   client, frames driven through each full transition. Assert the client's
   handler list holds exactly one entry throughout, and `weakref`s to every
   retired graph object report collected after the close fade + `gc.collect()`.
2. **o2litepy contract test.** `FakeO2Lite` replicating the verified real API:
   5-required-arg `method_new`, dispatch calling `handler(address, types,
   info)`, sequential `get_int32()`. `attach()` + injected messages must
   deliver MIDI end-to-end. Executable documentation of the real contract.
3. **State machine coverage.** Fake clock + fake universe: every transition in
   §5, latest-wins mid-CLOSING and mid-LOADING, welcome-vs-`sys:loaded`
   selection, MIDI dropped outside RUNNING, disconnect from each state,
   resolve-failure → ERROR, selftest gating, identify overlay.
4. **Threading stress (race regression).** Producer threads hammer noteon/CC/
   swap enqueues while the render thread spins frames — zero exceptions,
   deterministic final state. Would have caught the voices-dict `RuntimeError`.
5. **Signature rendering.** Each built-in `sys:*`: pixel values at key times,
   `done` at declared duration, registry override replaces a built-in.
6. **Riding fixes.** Throwing binding: skipped, quarantined at 44 consecutive
   failures, ERROR escalation when all bit bindings gone. `ThrottledLog`
   first + suppressed-count. Mocked serial write timeout → `BackendError`,
   loop survives.
7. **Compatibility & perf.** v1 manifest dicts parse; e2e test migrates to the
   session API; the 1000 px perf test extends to include queue-drain +
   director-advance in the measured path, still < 22.7 ms/frame.

## 11. Open questions / cross-repo coordination

- **mm-terrarium adoption:** `Role.light_manifest` in `mm-terrarium/control/
  roles.py` should adopt manifest v2 (the placeholder's "schema freezes once a
  real Bit declares lanes" promise coming due), and Control's role-adoption
  flow should ship the per-role welcome blob. Follow-up in that repo.
- **Deferred signatures:** `sys:role-adopted`, `sys:role-denied`, `sys:goodbye`
  await gameserver verbs; names reserved now so the vocabulary is stable.
- **o2litepy dependency:** o2litepy remains caller-supplied (not a declared
  dependency); the contract test pins the API shape we rely on.

## 11.1 Upstream alignment (verified 2026-07-22 against arco@498e4ab)

Synced `rbdannenberg/arco` `origin/main` (commit `498e4ab`, the Serpent→Python
pyarco port, 2026-07-17) and re-verified:

- **arco now vendors o2litepy** (`arco/o2litepy/o2lite.py`) — the copy device
  apps will most likely import. Contract identical to the o2-repo copy this
  spec pins: 5-required-arg `method_new`, `handler(address, types, info)`
  dispatch, append-only handler list, first-match-wins, **no removal API**.
  Attach-once is double-confirmed.
- **pyarco's epoch mechanism** (`doc/pyarco.md`): on Arco reset, all ugen IDs
  are invalidated via an epoch number and `arco_ref()` raises on stale-epoch
  access. This is upstream solving the same problem our swap lifecycle solves —
  stale references from a previous era must never be dereferenced. Ours
  resolves it structurally (whole graph dropped at swap; pure in-process), the
  correct analog since we have no cross-process shadow objects.
- **Arco's reset flow** (`doc/server.md`): `/arco/reset` frees all ugens →
  `/actl/reset` → client re-initializes from scratch — the same
  re-initialize-don't-patch shape as our reconnect → IDLE → Control re-sends
  the manifest.
- **Caution:** o2litepy `print()`s to stdout for every message to an unmatched
  address. Not ours to fix, but a mis-agreed address between Control and the
  device would emit per-message stdout writes on a real-time device — the
  contract test pins `/light/midi` for this reason too.
- pyarco's new `Synth` keeps a `free_notes` recycling pool because audio voice
  creation costs O2 round-trips to build server-side graphs. Light voices are
  cheap in-process objects, so LightSynth's create-per-note remains correct
  (YAGNI on pooling).

## 12. Sources

- Latency/memory review findings — this session, 2026-07-22 (o2litepy API
  verified against `rbdannenberg/o2` `o2litepy/src/o2lite.py`, commit `6c83cf6`).
- Device/bit lifecycle — `mm-terrarium/docs/control-gameserver-design.md`
  (power-on join, `/ie<N>/role` config blob, role switch teardown, packed-int32
  MIDI).
- v1 engine design — `docs/superpowers/specs/2026-07-21-lightarco-engine-design.md`.
