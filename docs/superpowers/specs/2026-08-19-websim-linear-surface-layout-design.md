# WebSim linear surface layout, and last-frame replay on connect

**Status:** Approved, not yet implemented.
**Repo:** luxaeterna. One file, `luxaeterna/backends/websim.py`.
**Driven by:** three mm-terrarium live-verify checklists that cannot be
performed today. See section 10.

`WebSimBackend` serves a browser canvas that has only ever really rendered
one shape: the canonical 12-LED Shroom, a ring plus a stem. Every Room
surface mm-terrarium has since declared is a linear strip of 30 to 864
pixels, and the page draws at most 12 of them. Separately, a frame sent
before a browser connects is lost, because the backend keeps no record of
what it is currently displaying.

Neither defect is theoretical. Both were measured on 2026-08-19 while
attempting the first of the three checklists below.

---

## 1. Findings from the code

### 1.1 The page draws at most 12 pixels of any linear surface

`PAGE_HTML`'s `pos(i)` resolves a pixel's screen position. It has three
branches: `ring`, `stem`, and a fallback for a surface that declares
neither. Every Room profile declares neither (TEST `main` declares
`left`/`center`/`right`, TEST `accent` declares `low`/`high`, DEMO `array`
declares `left`/`center`/`right`), so every Room takes the fallback:

```js
return [40+i*24,380];
```

A fixed 24 px pitch, on a canvas declared `<canvas id="c" width="320"
height="420">`. Pixel 11 lands at x=304, the last position on the canvas.
Pixel 12 lands at x=328 and is drawn outside it. Everything after that is
drawn progressively further off-canvas and is never visible.

Measured in the live page against mm-terrarium's DEMO profile:

| declared pixels | canvas width | first offscreen index | on-canvas | off-canvas | last x drawn |
|-----|-----|-----|-----|-----|-----|
| 864 | 320 | 12 | 12 | 852 | 20752 |

Confirmed identically on TEST `main` (60 px declared, 12 drawn). The
truncation is a property of the pitch and the canvas width, so it is the
same 12 for every linear surface regardless of size.

### 1.2 The glow radius is fixed, and would smear a dense strip

`draw()` paints each pixel as a radial gradient of radius 20 plus a solid
dot of radius 7, both constants. Those are proportionate at a 24 px pitch.
They are not proportionate at the pitch a fitted 864 px strip needs
(under 1 px at any realistic window width), where a radius-20 glow spans
roughly 40 neighbouring pixels. Fixing section 1.1 alone would therefore
replace an empty canvas with an indistinct wash, and the block boundaries
under test would still not be visible.

There is a cost dimension to the same constant. `draw()` allocates one
`createRadialGradient` and fills two arcs per pixel per frame. At 864
pixels and mm-terrarium's 44 Hz render tick that is about 38,000 gradient
allocations and 76,000 arc fills per second. A stutter there would be read
by an operator as a seam, which is the exact judgement the checklists ask
them to make.

### 1.3 A frame sent before a client connects is lost

`send()` writes to `self._clients` and appends to `self.frames`. `_handle()`
adds the new connection, sends the capability blob, then holds the socket
open. Nothing replays prior state, and no attribute holds "the frame
currently displayed".

For a continuously rendering consumer this is invisible: the next tick
repaints. For a consumer that paints once it is fatal, and the repo has
one. mm-terrarium's `harness/room_simulator.py --identify-blocks` sends a
single static frame at startup and then sleeps until Ctrl-C. It prints its
URL, and a human necessarily reads that URL and opens the browser after the
frame has already been sent. The canvas is black every time.

Verified by A/B on 2026-08-19: the same frame, the same `build()`, the same
backend, resent on a loop instead of once, paints correctly.

### 1.4 Why the existing tests did not catch any of this

`tests/backends/test_websim_serve.py::test_page_is_self_contained_canvas`
is the page's only coverage, and it is a substring grep over `PAGE_HTML`
(`"<canvas" in lower`, `"websocket" in lower`). It cannot observe layout,
and it passes just as happily when 852 of 864 pixels are drawn off-canvas.

mm-terrarium reached the same conclusion the hard way after its Room panel
rebuilt its LED strip roughly four times per painted frame past 843 passing
tests, and wrote the rule down: a grep over source text is not a test of
behavior. This spec adopts that rule here. See section 7.

---

## 2. Goals

1. A linear surface of any declared `pixel_count` is fully visible on the
   canvas at once, with its structure legible.
2. A client that connects after a frame was sent sees that frame.
3. The 12-LED Shroom renders exactly as it does today, to the pixel.

---

## 3. The layout decision: one row, fitted to the viewport

The linear fallback becomes a fitted single row:

```
pitch = (W - 2*M) / n
x     = M + (i + 0.5) * pitch
y     = H / 2
```

where `W`/`H` are the canvas dimensions, `n` is `cap.pixel_count`, and `M`
is a fixed 20 px margin so the end pixels sit clear of the canvas edge.
Recomputed on `resize`.

**One row, not wrapped.** Wrapping a strip into rows (144 per row would map
DEMO's six meter-blocks onto six rows, which is tempting) introduces a
visual break at every row end. Two of the three checklists ask an operator
to confirm there is *no* seam at a boundary. A layout that manufactures
seams cannot answer that question, whatever else it has to recommend it.

**Fitted, not fixed-pitch-with-scroll.** Keeping the 24 px pitch and
growing the canvas to its true width (20,752 px for DEMO) keeps each LED
large, but the operator can then only ever see about 1.5% of the array at a
time. "One gradient across the whole array, no seam" is not a judgement
that survives being made in 65 separate scrolled viewports.

At an 800 px window, DEMO's 864 px gives 0.88 px per LED, so each 144 px
block reads as a band about 127 px wide and the whole array is one glance.
TEST `main`'s 60 px gives about 12.7 px per LED, comfortably fat dots.

### 3.1 Radius scales with pitch

Both radii derive from `pitch` rather than staying constant:

- glow radius: `min(20, pitch * 1.5)`
- dot radius: `max(0.5, min(7, pitch * 0.4))`

At a 24 px pitch these evaluate to 20 and 7, the current constants, so a
sparse surface is unchanged. Below a pitch of about 3 px the radial
gradient is skipped entirely and the pixel is drawn as a `fillRect` of
width `ceil(pitch)`, which is both the legible rendering at that density
and the cheap one.

### 3.2 The canvas resizes only for a linear surface

The `ring` and `stem` branches of `pos()` are hardcoded to absolute
coordinates: the ring is centred at `160,150` with radius 90, the stem runs
down `x=160` from `y=270`. Those constants assume a 320x420 canvas.
Resizing the canvas unconditionally would therefore knock every Shroom off
centre, which is a regression in the one layout that currently works.

So the canvas keeps its declared 320x420 whenever the capability has a
`ring` or `stem` zone, and sizes to the viewport only when it does not.
The branch that selects the layout and the branch that selects the canvas
size are the same condition, evaluated once when the capability arrives.

---

## 4. The replay decision: the backend remembers its last frame

`WebSimBackend` gains `self._last_frame`, assigned in `send()` alongside
the existing `self.frames.append(payload)`. `_handle()` writes it to the
new connection immediately after the capability blob, inside the same
`try` that already guards that write.

This is deliberately placed in the backend rather than in the consumer.
`harness/room_simulator.py --identify-blocks` could resend its static frame
on a loop, and that was the A/B used to prove the defect, but it would
leave the same trap set for the next consumer that paints once, and it
would spend a send every 500 ms forever on a frame that never changes. A
display surface that cannot say what it is currently displaying is the
defect; the one-shot consumer merely exposes it.

**mm-terrarium requires no code change from this.** Its `--identify-blocks`
path becomes correct exactly as written.

`self.frames`, the public headless recorder, is untouched: `_last_frame` is
a separate attribute so that a consumer clearing or reading `frames` cannot
change what a newly connected browser is shown.

### 4.1 Ordering

The capability blob must arrive first, because the page's `onmessage`
ignores a binary frame until `cap` is set (`if(!cap)return;`). Sending the
replay after the capability write, on the same connection, preserves that
ordering by construction.

---

## 5. What explicitly does not change

- `pos()`'s `ring` and `stem` branches, byte for byte.
- The 320x420 canvas for any capability declaring a ring or stem.
- `capability_message()`, the wire shape, and the handshake order.
- `send()`'s existing behavior: the frame slice, the copy, `frames`, the
  `serve=False` record-only path, the dead-client discard.
- Every backend other than websim.

---

## 6. Error handling

- A capability with `pixel_count` of 0 must not divide by zero. `pitch`
  guards with a floor, and `draw()`'s loop does not execute.
- A replay write to a client that dies between the capability write and the
  replay is caught by `_handle()`'s existing `except Exception`, which
  already discards the connection in its `finally`.
- A `resize` that fires before the capability arrives is a no-op: layout
  needs `cap`, and the handler returns early when it is null.
- A surface wide enough that `pitch` rounds to 0 still draws, because
  `fillRect` takes `ceil(pitch)`, a minimum of 1 screen px. Pixels then
  overlap rather than vanish, which degrades legibility honestly instead of
  silently dropping pixels the way the current code does.

---

## 7. Testing

Both levels, because section 1.4 is the reason this defect shipped.

**Python**, extending `tests/backends/test_websim_serve.py`:

1. A client connecting after a `send()` receives the capability blob and
   then that frame, with no further send.
2. A client connecting before any send receives the capability blob only,
   and does not block waiting for a frame that never comes.
3. A second client connecting later receives the same last frame while the
   first client is still attached.

**JavaScript**, a new `tests/js/websim_layout.test.js` evaluated under
Node's `vm` with a canvas stub, wrapped by `tests/backends/test_websim_layout.py`
so it runs in the normal pytest invocation and skips cleanly where node is
absent. The wrapper extracts the `<script>` body from `PAGE_HTML`, so the
served page stays the single source of truth and cannot drift from what is
tested.

4. Every pixel of an 864 px linear capability lands within canvas bounds.
5. Pixel positions across an 864 px surface are strictly increasing and
   evenly spaced.
6. A 12 px `shroom_capability()` produces ring and stem positions identical
   to the current implementation, asserted against literal expected
   coordinates rather than against a re-derivation.
7. Scaled dot radius stays strictly positive at 864 px.
8. A 0 px capability draws nothing and does not throw.

This is the first JS test in luxaeterna. mm-terrarium already runs the same
shape (`tests/js/room_panel_behavior.test.js` under a DOM stub via `vm`,
wrapped by `tests/test_room_panel_behavior.py`); this follows it rather
than inventing a second convention.

---

## 8. Non-goals

- **Any change to mm-terrarium's code.** Section 4. The deep-dive doc sync
  is a separate closeout step, not part of this change.
- **A block-aware or zone-aware canvas.** The page draws pixels. It does
  not draw block boundaries, zone labels, or rulers. `--identify-blocks`
  already answers the block question with color, and the Console's Room
  panel already owns the annotated operator view.
- **Bounding `self.frames`.** It grows unboundedly at roughly 114 KB/s for
  a DEMO surface at 44 Hz, which is about 5 MB across a 45 s run and only
  becomes a question for a long hold. It is pre-existing, it is the
  documented headless recorder API, and changing it here would be an
  unrelated behavior change to every consumer.
- **Touching the ring/stem geometry**, including making the Shroom itself
  responsive. Section 5.

---

## 9. Success criteria

1. An 864 px linear capability renders all 864 pixels within canvas bounds,
   in one row, at one glance.
2. Each of DEMO's six 144 px blocks is visually distinguishable under
   `--identify-blocks`.
3. A browser opened after a one-shot `send()` displays that frame.
4. `shroom_capability()` renders pixel-identically to the current build.
5. The luxaeterna suite passes, including the new JS tests, and skips them
   cleanly with no node present.
6. mm-terrarium's suite (1057 passed, 1 skipped as of 2026-08-19) is
   unchanged, since no mm-terrarium code changes.

---

## 10. Live verification

This change is a prerequisite, not a deliverable in itself. It is done when
the three checklists it unblocks can actually be performed:

- **A.** mm-terrarium `2026-08-17-bit-declared-triggers-and-cue-scripts-design.md`
  section 13.1: fire `play_aurora` from the Console with no device joined,
  confirm the TEST Room's three zones sweep the declared steps at the
  declared offsets, the log reads `ADMIN MANUAL`, and the Room's role name,
  counts and node id are absent from every panel. Needs zones `center`
  (px 20-39) and `right` (px 40-59) to be visible, which today they are not.
- **B.** mm-terrarium `2026-08-18-n-fixture-room-design.md` section 13
  item 10: with both TEST simulator tabs open, fire a rainbow-bearing cue
  and confirm one gradient scrolls continuously across `sim-room-main`
  (60 px) and `sim-room-accent` (30 px) with no seam.
- **C.** mm-terrarium `2026-08-19-demo-room-and-block-profile-design.md`
  section 7: confirm the DEMO Room's rainbow cue sweeps the full 864 px
  with no seam at any of the six meter-block boundaries, and that
  `--identify-blocks` shows six distinct solid colors of exactly 144 px
  each, in declaration order.

C's remaining half, a device joining `TEST_PLAYER_NODE` and completing a
scored round plus an unscored jam join, is unaffected by this change and
is gated behind the separate, upstream headless clock-sync defect
documented in mm-terrarium's deep-dive. It has to be run from an
interactive terminal.
