# Aurora — a breathing, hue-gliding ambient glow instrument

Date: 2026-07-23
Status: design approved, pending implementation plan
Primary repo: **luxaeterna** (renderer). Follow-up: **mm-terrarium** (TestBit running visual, demo, smoke test).

## 1. Why this exists

Watching the live LED-sim demo, the RUNNING visual **flashes distractingly** and its
colour changes in visible steps. Two compounding causes, both structural:

1. **The strobe.** `harness/led_smoke.py` fires a fresh note-on every **0.15 s**
   (`feed_midi(0x90, 60, 100)`, ~6.7 Hz). Each spawns a new `bloom` voice whose
   `Envelope(attack=0.04, …)` snaps to full in 40 ms, so the surface pulses ~7×/second.
2. **The stepped colour.** `_bloom_voice` snapshots the hue into a **`Const`** at
   note-on (`color = hsv_to_rgb(hue, 1.0, 1.0) * vel`). A voice's colour is frozen for
   its lifetime, so hue only changes when a *new* voice spawns — and the demo steps
   `cc` by `8/127`, giving ~16 discrete colour jumps.

Critically, **the strobe is load-bearing given bloom's design**: because bloom freezes
colour at note-on, a single held note would never change colour, so the demo *must*
re-trigger to sweep the hue at all. This is not a demo-tuning problem — it is a missing
instrument. luxaeterna has no continuous, note-less instrument whose colour can change
over time.

`glow` (added for the visible welcome) is field-rate and note-less — it never flashes —
but it bakes its hue into a `Const` at construction, so it cannot shift. What's missing
is the running-visual counterpart: **a continuously-rendering ambient glow whose
brightness breathes gently and whose hue glides smoothly under live control.**

## 2. Goal & success criteria

Add a general, reusable instrument — working name **`aurora`** — that renders a smooth
breathing glow with a continuously-glidable hue, and adopt it as TestBit's running visual.

- Renders **continuously at field rate with no note-on** — a strobe is structurally
  impossible.
- Brightness **breathes** slowly (never fully dark), reading as a living organism.
- Hue is **cc-drivable and glided** (`Smooth`), so colour changes are continuous rather
  than stepped, with no re-triggering required.
- The demo's RUNNING loop stops sending note-ons entirely and just ramps `cc:74`.

## 3. Non-goals (scope boundary)

- **No changes** to `director.py`, the welcome path, `manifest.py`, or `binding.py` —
  `resolve()`'s existing cc-lane wiring already covers this instrument (see §4).
- **`bloom` is not modified.** Its note-on hue-snapshot semantics stay exactly as they
  are (other Bits may want per-note frozen colour); it remains a first-class instrument.
- **`glow` is not modified.** It stays the simple, static welcome gesture. Overloading it
  with cc-lanes and a breathe would muddy that role.
- No new spatial motion (drifting gradients / aurora-style travelling colour). `aurora`
  fills its zone uniformly; spatial behaviour is a separate future instrument.
- No audio.

## 4. Architecture

The change is a **vocabulary addition** plus one small uGen. The existing lane machinery
already supports a cc-driven param — no plumbing changes:

```
manifest lane {"source": "cc:74", "dest": "hue"}
        │
        ▼
binding.resolve()  ── checks dest ∈ obj.param_names() ──▶ wires obj.set("hue", value)
        │                                                   (value normalised 0–1 by
        ▼                                                    dispatch_midi's d2/127.0)
LightInstrument.set("hue", v) → Param.set(v) → Smooth.set_target(v)
        │                                        (Smooth delegates to its Const source)
        ▼
Smooth glides toward v each frame ──▶ HueColor(hue) ──▶ hsv_to_rgb ──▶ Fill(level, colour)
                                                                        ▲
                                      looping SegmentLevel (the breathe)─┘
```

Because `dispatch_midi` normalises CC to `d2/127.0`, a `cc:74` lane delivers `0.0–1.0` —
already the hue convention `bloom`/`glow` use.

## 5. Component design

### 5.1 Promote `hsv_to_rgb` to `ugens.py`

`hsv_to_rgb(h, s, v)` currently lives in `presets.py`, but `HueColor` (a uGen) needs it.
Move it to `luxaeterna/synth/ugens.py` and have `presets.py` import it, so there is one
copy. This mirrors the established precedent from the glow work, where `Fill` and
`SegmentLevel` were promoted out of `status.py` into `ugens.py` for exactly this reason.

### 5.2 New control uGen: `HueColor` (`ugens.py`)

```python
class HueColor(LightUgen):
    """Live hue (0–1) -> fully-saturated RGB, recomputed each frame. Lets a colour
    follow a control input (e.g. a Smooth-ed cc lane) instead of being frozen into
    a Const at construction."""

    rate = "control"

    def __init__(self, hue) -> None:
        super().__init__()
        self._hue = as_ugen(hue)

    def _compute(self, ctx: RenderContext) -> np.ndarray:
        return hsv_to_rgb(float(np.asarray(self._hue.render(ctx))), 1.0, 1.0)
```

Outputs a `(3,)` RGB array — exactly what `Fill`'s colour input expects (it reshapes,
pads to `ctx.channels`, and tiles across the zone).

### 5.3 New instrument: `aurora` (`presets.py`)

```python
_AURORA_PARAMS = frozenset({"hue"})

BREATHE_POINTS = [(0.0, 0.55), (3.0, 1.0), (6.0, 0.55)]   # ~6 s cycle, never dark
HUE_GLIDE_TAU = 0.4                                        # seconds


def _make_aurora(**params) -> LightInstrument:
    unknown = set(params) - _AURORA_PARAMS
    if unknown:                    # reject typo'd manifest params, don't discard them
        raise KeyError(f"unknown aurora param(s) {sorted(unknown)} "
                       f"(known: {sorted(_AURORA_PARAMS)})")
    hue = Smooth(Const(float(params.get("hue", 0.0))), HUE_GLIDE_TAU)
    level = SegmentLevel(BREATHE_POINTS, loop_from=0.0)
    out = Fill(level, HueColor(hue))
    return LightInstrument(out, {"hue": Param("hue", hue)})


registry.register("aurora", _make_aurora)
```

- **Breathe:** a *looping* `SegmentLevel` — the same pattern `sys:idle` already uses.
  Brightness oscillates `0.55 → 1.0 → 0.55` over ~6 s and never reaches zero.
- **Hue glide:** `Smooth(Const(hue0), tau=0.4)`. `Param("hue", hue)` exposes it, so
  `set("hue", v)` retargets the `Const` and the `Smooth` glides there over ~0.4 s.
- **Param surface:** exactly `hue`, with a reject-unknown-param `KeyError` — consistent
  with `_make_bloom` and `_make_glow`, and preserving the
  `test_bad_welcome_is_a_resolve_failure_not_an_escape` contract for any manifest that
  declares `aurora`.
- **No note lane.** It renders from the moment it resolves; there is no `noteon` to call.

### 5.4 mm-terrarium follow-up

mm-terrarium consumes luxaeterna as an editable install from
`/Users/chris/projects/luxaeterna`, so `aurora` is only importable once this lands on
luxaeterna `main`. Sequencing: **luxaeterna PR merges first**, then:

- `bits/test_bit.py` — the **running** instrument becomes `aurora` with a single
  `{"source": "cc:74", "dest": "hue"}` lane (the `note` lane and `bloom` are dropped).
  The **welcome stays `glow`**, unchanged.
- `tests/test_test_bit.py` — the `player.light_manifest` expected literal is updated to
  match (it pins TestBit's real declaration; this is the same class of pin that the glow
  work hit).
- `harness/led_smoke.py` — the RUNNING loop stops sending note-ons and feeds a **smooth
  `cc:74` ramp** in small steps; the colour glides and the brightness breathes with no
  flashing.
- `tests/test_led_smoke.py` — the note-driven assertions (note-on → lit + red-dominant →
  hue progression across successive voices) are replaced with cc-driven ones: lit
  *without* any note-on, hue glides toward a new `cc:74` target across frames, and
  brightness varies frame-to-frame (the breathe).

## 6. Error handling & testing

**luxaeterna** (all must pass before the mm-terrarium follow-up):

- `tests/synth/test_field_ugens.py` (or the control-ugen suite) — `HueColor`: hue `0.0`
  → red-dominant, hue `0.33` → green-dominant; it tracks a *changing* hue input across
  frames rather than caching a single value.
- `tests/synth/test_presets.py` — `aurora`:
  - builds via `registry.build("aurora", hue=…)` and returns a `LightInstrument`;
  - renders **full-field** (every pixel lit, uniform across the zone) with **no note-on**;
  - **breathes** — rendered brightness differs across frames spanning the cycle, and
    never hits zero;
  - **glides** — after `set("hue", target)`, the rendered colour moves *toward* the
    target over successive frames rather than snapping in one frame (the defining
    behaviour of this instrument);
  - `param_names() == {"hue"}` (so a `cc` lane resolves), and an unknown build param
    raises `KeyError`.
- `tests/synth/test_binding.py` — a manifest decl of `aurora` with a `cc:74 → hue` lane
  resolves successfully and its route updates the hue (guards the lane contract that the
  whole design leans on).
- Existing suites stay green after the `hsv_to_rgb` move.

**mm-terrarium**: `tests/test_led_smoke.py` becomes the full-stack regression that the
running visual is lit with **zero note-ons**, glides hue under a `cc:74` ramp, and breathes.

**Deliberate coverage trade:** switching TestBit's running visual to a note-less
instrument means the *terrarium* full-stack test no longer exercises the note-on path
(`feed_midi` → `dispatch_midi` → `LightSynth.noteon` → bloom voice). That path remains
covered by luxaeterna's own suite, which owns it; in exchange the terrarium test gains
end-to-end coverage of the cc-lane glide path. Accepted knowingly.

## 7. Alternatives considered (and why rejected)

- **Extend `glow` to take a live hue + breathe.** Rejected: `glow`'s value is being the
  simple, static welcome gesture. Adding cc-lanes and breathing to it conflates two
  different roles (one-shot ceremony vs. continuous ambient) in one instrument.
- **Make `bloom`'s hue live (Smooth) and hold a single sustained voice.** This would fix
  the strobe and the stepping, but keeps bloom's *localized Gaussian blob* shape rather
  than the full-field breathing glow chosen here, and it changes bloom's established
  note-on-snapshot semantics — documented behaviour that other Bits and existing tests
  rely on. Rejected as destabilising a working instrument to get the wrong shape.
- **Tune the demo only** (slower re-trigger, smaller `cc` step, longer bloom attack).
  Rejected as a band-aid: with colour frozen per note, the result stays fundamentally
  stepped and pulsed, and the root cause — no continuous colour-changing instrument —
  remains.

## 8. Decisions locked (from brainstorm)

- Aesthetic: **breathing glow + hue glide** (full-field, not localized, no spatial drift).
- A **new instrument** (`aurora`), leaving `bloom` and `glow` untouched.
- Built from existing primitives (`SegmentLevel` loop, `Smooth`, `Fill`, `Const`,
  `Param`) plus **one** new control uGen, `HueColor`; `hsv_to_rgb` promoted to `ugens.py`.
- Param surface: **`hue` only**, cc-drivable, reject-unknown-param.
- Defaults: breathe `0.55 → 1.0 → 0.55` over ~6 s (`loop_from=0.0`); hue glide
  `tau = 0.4 s`. Tunable constants, not manifest params.
- **Zero** director / welcome-path / manifest / resolve changes.
- Two repos, sequenced: **luxaeterna first**, mm-terrarium second.
- The terrarium smoke test's loss of note-on coverage is an accepted, deliberate trade.
