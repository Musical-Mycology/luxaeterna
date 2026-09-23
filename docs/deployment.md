# Deployment matrix — where the Lux Aeterna renderer runs, and what feeds it

Lux Aeterna is a library, not a service. It runs in one place: the
Control+GameServer process on the Terrarium. Everything that shows light,
whether a Tuneshroom, the Console strip or (later) the venue's WLED
controllers, is a **pixel sink** that gets frames Lux Aeterna has already
rendered. This document records that decision, the other shapes it ruled out,
and what each shape costs in messages.

## Implementation status, verified 2026-09-23

> Traced against `mm-terrarium@e709c7e` and `luxaeterna@a4088f1`.
>
> **Row 1 is the only row that exists, and it is the design.** Row 3 is
> retired, not unbuilt. `MM_HARDWARE_DESIGN.md` §4.4 (revised 2026-08-05) says
> *"Lux Aeterna renders on the Terrarium, not on the device"*. mm-terrarium
> built that: `devicelink/agent.py` owns one `LightSession` per joined device
> and one per Room fixture, renders them on the 44 Hz engine tick, and hands
> each changed frame to that output's `FixtureSink`s
> (`control/fixture_sink.py`). The device wire carries **rendered bytes, not
> MIDI**: `DeviceLinkSink` sends `/<dev>/leds` (36 bytes, 12 LEDs × 3) stamped
> with the cue's O2 time `when`, and the device holds the frame until then.
>
> **o2lite is the only device wire** as of mm-terrarium's 2026-09-08 cutover.
> The earlier bare-websocket JSON path is deleted.
>
> **`O2Bridge.attach()` still has no production caller.** Nothing outside
> mm-terrarium's `tests/` references `O2Bridge`. It is kept for row 2, a
> shape nobody plans to build.
>
> **Nothing in Musical Mycology has driven a physical light over Art-Net yet.**
> `harness/array_smoke.py` is the only `ArtNet` caller, and it is standalone.
> `BootConfig.array_backend` reserves a slot for a WLED host, but no
> `FixtureSink` sends to an Art-Net backend. That sink is the planned bridge
> to the venue array (see *Embedded devices* below).

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

| # | Site | What Lux Aeterna drives | Where the renderer runs | Control-plane input (note/CC, manifest swap, status) | Hops | Status |
|---|---|---|---|---|---|---|
| 1 | **Terrarium** | Every light in the room, through `FixtureSink`s: Tuneshroom LEDs (`/<dev>/leds` over o2lite), the Console strip, and later the venue array (Art-Net → WLED, `MM_HARDWARE_DESIGN.md` §7.1) | **Inside the Control+GameServer process** | **Direct Python calls**: `session.feed_midi(...)`, `.swap(...)`, `.clear()`. `O2Bridge` is **not involved.** | **0** in, **2** out to a device | **Built. This is the design.** |
| 2 | **Terrarium**, if split out | same | Its own process on the same Pi 5 | `O2Bridge.attach()` on `/light/midi`; Control → Arco → luxaeterna | **2** in | Not planned; recorded for its cost |
| 3 | ~~**Tuneshroom**, on-device~~ | ~~12 local LEDs~~ | ~~On the device~~ | ~~`O2Bridge.attach()` on `/light/midi`~~ | ~~2~~ | **Retired 2026-08-05** by `MM_HARDWARE_DESIGN.md` §4.4: the device is a pixel sink |

### Row 1 — the Terrarium, in-process

This is what exists. mm-terrarium's `devicelink/agent.py` builds a session with
`build_session(...)` for each joined device (via `harness/device_bridge.py`)
and for each Room fixture. It drives those sessions with `feed_midi(...)` and
`swap(...)` from Bit cues, the lobby, generators and breath. No o2lite handler
is registered for light. The session's lifecycle methods (`swap`, `clear`,
`error`, `identify`, …) are plain method calls that enqueue events. They are
the in-process control surface, and they are not O2-specific.

`feed_midi()` is a first-class production entry point on this path, not merely a
test seam. It packs and enqueues exactly as a real packet would, so the event is
still gated to `RUNNING` and still drained on the render thread at a frame
boundary — the queue discipline is identical whichever input path is used.

**Do not route this through O2.** Sending `/light/midi` from Control to a
luxaeterna session living in Control's own process would cost 2 hops through
Arco to deliver a message that a method call delivers in zero — and Arco on the
venue box is the same process doing all room synthesis while feeding this
renderer's 44 Hz loop.

The *output* side does cross O2. A rendered frame for a Tuneshroom goes
Control → Arco → device (2 hops), stamped with a presentation time one
`cue_horizon` ahead so it arrives before it is due.

Note that the venue array's *spectral* visualisation (§7.1: "spectral →
Art-Net → WLED via Lux Aeterna") is **not built yet**. When it is, its analysis
data originates in Arco and reaches Control over `/actl` (1 hop), then crosses
into the renderer in-process.

### Row 2 — split out, and why row 3 was retired

`O2Bridge` exists for row 2. The renderer would be in a different process from
Control, so `/light/midi` would be a real wire, `attach()` registers the
handler once on the caller-supplied o2lite client, and each note/CC costs 2
hops: Control → Arco → renderer. The bridge only *enqueues* on the o2lite
receive thread, and decode and dispatch happen at drain time on the render
thread, so a 44 Hz loop is never blocked by the network. There is no plan to
split the Terrarium renderer out. Row 2 is here so the cost of doing it is on
the record.

Row 3 put a renderer on each Tuneshroom. The 2026-08-05 hardware revision
removed it along with local Arco: a Bit runs on the Terrarium, and the
Tuneshroom is an instrument the Terrarium plays *to*. Rendering centrally has
three effects. Every light shares one clock and one manifest, the device
firmware stays simple, and nothing on a device needs Python.

## Embedded devices: a pixel sink, not a port

Lux Aeterna is Python and depends on numpy. It will not run on
a microcontroller, and **it never has to**. Every embedded output is reached by
shipping it rendered bytes over a protocol the device already speaks. The seam
is mm-terrarium's `FixtureSink.send_frame(frame, when)`. A new kind of hardware
is a new sink, and nothing upstream of that seam changes.

| Output | Hardware | What runs on it | Bridge | State |
|---|---|---|---|---|
| Tuneshroom (2H) | Radxa Zero 3W, 12× SK6812 RGBW | o2lite client (C). Shows a frame at `when` | `DeviceLinkSink` → `/<dev>/leds` over o2lite | Wire built. mm-tuneshroom's app implements the timed `/ie<N>/leds` queue. 2H firmware not yet written |
| Tuneshroom (2S) / Testshroom | browser or `harness/o2_shroom.py` | o2lite or o2ws client | same | Built |
| Venue array, Booster | WLED ESP32 (GLEDOPTO class) | Stock WLED firmware, Art-Net input | Lux Aeterna `ArtNet` backend → UDP | Backend built (`harness/array_smoke.py`). **No `FixtureSink` yet** |
| Any other MCU strip | ESP32 or similar | o2lite C client (it supports ESP32 Arduino) or WLED | either of the above | Not needed yet |

What an embedded sink has to do is small: accept a byte frame (3 bytes per
LED, in the fixture's `color_order`), hold it until its `when` on the shared
O2 clock, then latch it to the strip. It needs no effects engine, no manifest
and no MIDI.

**Open: RGBW.** The Tuneshroom's SK6812 parts and the venue array's are
RGBW, but the device wire is 3 channels per LED today (`_DEVICE_CHANNELS =
36` in mm-terrarium). `luxaeterna` can render 4-channel surfaces. mm-terrarium's
`control/room_profile.py` records widening the wire to four channels as a
separate, undecided question.

One timing fact matters in every deployment row above: `render_into` passes
the injected clock's reading straight through as `t`. On a Terrarium that
clock is `o2lite.time_get`, injected by Control into every fixture session,
so a `rainbow` declared on `primary` across two fixtures scrolls as one
gradient even though each fixture has its own session. Instruments that
need a local origin (envelopes, segment levels, the status signatures)
integrate `dt` instead; `t` starts wherever the clock is, which is usually
not zero, and must never be assumed to.

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
