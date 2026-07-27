# Deployment matrix — where the Lux Aeterna renderer runs, and what feeds it

Lux Aeterna is a library, not a service. It runs wherever its LEDs are, and the
two Musical Mycology sites put it in very different places. The input path — and
therefore the message cost of a note or CC — is different at each. This document
states which is which, because nothing else in the repo does.

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
