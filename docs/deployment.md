# Deployment matrix — where the Lux Aeterna renderer runs, and what feeds it

Lux Aeterna is a library, not a service. It runs wherever its LEDs are, and the
two Musical Mycology sites put it in very different places. The input path — and
therefore the message cost of a note or CC — is different at each. This document
states which is which, because nothing else in the repo does.

## Implementation status, verified 2026-08-20

> **The matrix below describes the target architecture. Row 1 is still the only
> row that exists**, but the reason rows 2 and 3 do not is no longer the reason
> the previous revision of this note gave. Traced against `mm-terrarium@c94cdc5`
> and `luxaeterna@97281ee`.
>
> **There is an Arco server process now.** `control/arco_process.py` spawns and
> owns it and `control/boot.py` starts it as the first step of the load
> sequence; shutdown is SIGTERM, because Arco has no message-based quit. There
> is still no `arcoserver/` in mm-terrarium: the binary is Arco's own
> `apps/pytest/server`, spawned on a pty.
>
> **pyarco and o2litepy are imported, always function-scoped.**
> `control/arco_process.py:37`, `harness/arco_synth.py:91-93`,
> `harness/o2_shroom.py:236`, `harness/run_stack.py:478`,
> `harness/terrarium_boot.py:480`. Every one is marked lazy by design.
> `control/audio.py` documents the module-level ban that keeps the offline
> suite green. A previous revision of this note claimed zero such imports; that
> came from a grep anchored at `^` which could not see an indented one.
>
> **The device wire is two paths now, chosen per run.** The default is still
> plain JSON over a bare websocket (`devicelink/server.py:14,33`), with an
> envelope that mirrors o2ws field-for-field without being o2ws. Opt in with
> `--transport o2lite` and `devicelink/o2_transport.py` offers Control's `game`
> service on the real Arco hub instead. That path has been run against a live
> Arco and observed working (2026-08-13).
>
> **That did not advance rows 2 or 3, and the reason is the interesting part.**
> What crosses the device wire is *rendered frames*, not MIDI:
> `devicelink/agent.py:379` ships `universe.get_frame()[:36]` to a Tuneshroom,
> and `:305` ships the Room its `channel_count` slice. luxaeterna renders inside
> Control for every path that exists. Rows 2 and 3 both describe luxaeterna
> running somewhere else and being fed `/light/midi`, and the architecture went
> the other way: render centrally, ship pixels. A real device transport is
> therefore not the missing piece for those rows.
>
> **`O2Bridge.attach()` still has no production caller.** `git grep "attach("`
> over all of mm-terrarium returns nothing; `LightSession.attach()`
> (`synth/session.py:44`) is reached only from `tests/synth/`. `O2Bridge.on_midi()`
> *is* live, as an in-process queue shim. The class is instantiated; its o2lite
> half has never executed. Unchanged since this note was first written, and the
> single clearest signal that rows 2 and 3 are unbuilt.
>
> **A `DMXBackend` is instantiated now, just not on the Tuneshroom path.**
> `WebSimBackend` at `harness/led_smoke.py:65`, `harness/o2_shroom.py:161` and
> `harness/room_simulator.py:91`; `ArtNet` at `harness/array_smoke.py:46`. A
> previous revision claimed the only `ArtNet(` anywhere was the usage example in
> `luxaeterna/__init__.py:12`; that stopped being true when the venue-array
> tooling landed.
>
> **Still true: nothing in Musical Mycology has driven a physical light.**
> `harness/array_smoke.py` is the only Art-Net caller and it is standalone,
> never plugged into `boot()`. The venue array remains simulated.

## The routing rule this follows

From mm-terrarium's `docs/control-gameserver-design.md` § *Message Routing*
(v3, 2026-07-27): the Control+GameServer is an **o2lite client of the Arco
server**, not a full O2 peer — Arco is the only full-O2 process in the room. An
o2lite client's `send()` has no local short-circuit — every message it sends
leaves over its single link to the host. So:

| Path | Hops |
|---|---|
| Control → `/arco` (Control's host *is* Arco) | 1 |
| Arco → `/actl` | 1 |
| Control → a device service (`/ie<N>/*`, `/light/*`) | 2 |
| device → `/game/*` | 2 |

Which yields the rule this document exists to make explicit:

> **An in-process consumer is reached by a Python method call, not by O2.**
> Addressing an o2lite service from inside the process that offers it round-trips
> through Arco and back. O2 addressing is for the process boundary.

## The matrix

| # | Site | What Lux Aeterna drives | Where the renderer runs | Control-plane input (note/CC, manifest swap, status) | Hops |
|---|---|---|---|---|---|
| 1 | **Terrarium (venue)** — *today's shape* | Venue LED array: SK6812 bars + fiber engines, via Art-Net → WLED (`MM_HARDWARE_DESIGN.md` §7.1) | **Inside the Control+GameServer process** — mm-terrarium's `harness/` constructs a `LightSession` in-process | **Direct Python calls**: `session.feed_midi(...)`, `.swap(...)`, `.clear()`. `O2Bridge.attach()` is **not involved at all.** | **0** |
| 2 | **Terrarium (venue)** — *if split out* | same | Its own process on the same Pi 5 | `O2Bridge.attach()` on `/light/midi`; Control → Arco → luxaeterna | **2** |
| 3 | **Tuneshroom (device)** | 12 local LEDs (8-ring + 4-stem, GRB) at 44 Hz | On the device, alongside its o2lite client | `O2Bridge.attach()` on `/light/midi`; Control → Arco → device | **2** |

### Row 1 — the Terrarium, in-process

This is what exists. mm-terrarium's `harness/device_bridge.py` turns a granted
`JoinResult.config` blob into a `LightSession` and calls `build_session(...)`
directly; `harness/led_smoke.py` injects MIDI with `LightSession.feed_midi(...)`.
No o2lite client is constructed and no handler is registered. The session's
lifecycle methods (`swap`, `clear`, `error`, `identify`, …) are already plain
method calls that enqueue events — they are the in-process control surface, and
they are not O2-specific.

`feed_midi()` is a first-class production entry point on this path, not merely a
test seam. It packs and enqueues exactly as a real packet would, so the event is
still gated to `RUNNING` and still drained on the render thread at a frame
boundary — the queue discipline is identical whichever input path is used.

**Do not route this through O2.** Sending `/light/midi` from Control to a
luxaeterna session living in Control's own process would cost 2 hops through
Arco to deliver a message that a method call delivers in zero — and Arco on the
venue box is the same process doing all room synthesis while feeding this
renderer's 44 Hz loop.

Note that the venue array's *spectral* visualisation (§7.1: "spectral →
Art-Net → WLED via Lux Aeterna") is **not built in this repo yet**. When it is,
its analysis data originates in Arco and reaches Control over `/actl` (1 hop),
then crosses into the renderer in-process. This document's matrix covers the
control-plane input that exists today.

### Rows 2 and 3 — the cross-process and on-device cases

`O2Bridge` exists for these. The renderer is in a different process from
Control, so `/light/midi` is a real wire, `attach()` registers the handler once
on the caller-supplied o2lite client, and each note/CC costs 2 hops: Control →
Arco → renderer.

Both rows land against a 44 Hz render loop, which is why the bridge only
*enqueues* on the o2lite receive thread — decode and dispatch happen later, at
drain time on the render thread. That design is unchanged by anything here.

One timing fact matters in every deployment row above: `render_into` passes
the injected clock's reading straight through as `t`. On a Terrarium that
clock is `o2lite.time_get`, injected by Control into every fixture session,
so a `rainbow` declared on `primary` across two fixtures scrolls as one
gradient even though each fixture has its own session. Instruments that
need a local origin (envelopes, segment levels, the status signatures)
integrate `dt` instead; `t` starts wherever the clock is, never at zero.

Row 2 is not today's shape and there is no current plan to split the Terrarium
renderer out. It is in the matrix so the cost of doing so is on the record: it
converts row 1's zero-hop path into a 2-hop one.

## Development environment caveat

**Art-Net is UDP to WLED controllers on the LAN.** A NAT'd VM or a WSL2 host
cannot reach them: its virtual NIC sits on its own subnet, so Art-Net frames
never arrive at the controllers without mirrored networking or manual port
proxying. The same is true of O2's UDP discovery. This matches
`control-gameserver-design.md` § *Host Platform*, which rules WSL2/VM hosts out
for bring-up on exactly these grounds.

**Develop without hardware using `WebSimBackend`.** It is a `DMXBackend` that
records DMX frames and streams them to a self-contained browser canvas — an
on-screen 12-LED Shroom. It needs no LEDs, no controller, and no LAN, so it is
the supported path on a laptop, VM, or WSL2 box:

    pip install luxaeterna[websim]
    python -m luxaeterna.websim_demo

Construct it with `serve=False` for a headless frame recorder in tests.

**Timing and throughput numbers are only meaningful on target hardware.** Frame
rate, render-loop headroom, drain latency, and sustained message rate measured on
a virtualized or laptop host say nothing about the Pi 5 venue box — which is
bare-metal Linux with a mandatory I2S DAC HAT and no virtualization layer in the
venue path. Measure on the target before quoting a number.
