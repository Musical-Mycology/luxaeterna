# Visible welcome via a `glow` gesture instrument

Date: 2026-07-23
Status: design approved, pending implementation plan
Primary repo: **luxaeterna** (renderer). Follow-up: **mm-terrarium** (TestBit + smoke test).

## 1. Why this exists

A Bit authors a per-role `welcome` — a luxaeterna `SignatureDecl` — meant to play a
short light gesture during the LOADING window, in place of the built-in `sys:loaded`
flash. TestBit's welcome is `{"instrument": "bloom", "params": {"hue": 0.33}, "duration": 1.5}`.

But `bloom` — luxaeterna's only manifest-authorable instrument — is a `LightSynth`
voice pool (`luxaeterna/synth/presets.py::_make_bloom`). A `LightSynth` renders
**nothing** until `.noteon()` spawns a voice. A `SignatureDecl` has no lanes and never
triggers a note, so a `bloom` welcome renders **dark** for its entire duration.

Net effect: authoring a welcome silently **replaces the visible `sys:loaded` flash with
an invisible one.** luxaeterna's own `tests/synth/test_director.py::test_welcome_replaces_generic_loaded`
documents the surrender ("a dark synth is fine — only timing matters"), as does
mm-terrarium's `tests/test_led_smoke.py` §(a), which had to weaken its LOADING check
from "lit" to merely "LOADING was observed."

### Root cause

The registry has two conventions:

- **Instrument factories** (`bloom` → `LightSynth`): return an object with `.render()`,
  wrapped in a `Signature` by the caller. Renders only after `.noteon()`.
- **Signature factories** (`sys:loaded` → `Signature`): return a ready gesture built
  from field-rate uGens (`Fill(SegmentLevel(...), Const(color))`) that renders every
  frame **with no note required.**

The `sys:*` status gestures already prove the correct shape for a "plays for a fixed
window, no note" visual. Bit authors simply have no such instrument to point a welcome
at — the only authorable instrument is a note-triggered synth, which is a category
error for a lane-less `SignatureDecl`.

## 2. Goal & success criteria

Let a Bit author a welcome that is **actually visible** for its whole LOADING window.

- A new field-rate `glow` instrument renders lit every frame without a note.
- TestBit's welcome points at `glow`; the LOADING window is visibly lit.
- mm-terrarium's smoke test tightens its LOADING assertion back to a real brightness
  check (`max(frame) > 0`).
- The `bad welcome → ERROR` contract is preserved (a typo'd `glow` param still routes
  to ERROR, like `bloom`).

## 3. Non-goals (scope boundary)

- **No change to the director, welcome path, manifest schema, or `resolve`.** The fix is
  a vocabulary addition; the existing `Signature(registry.build(name, **params), duration)`
  path already renders `glow` correctly.
- **No auto-note-on for synth welcomes**, and **no new `note` field on `SignatureDecl`.**
  (Both were weighed and rejected — see §7.)
- **No change to the Bit's *running* instrument.** TestBit still runs `bloom` with its
  `note` + `cc:74` lanes. `glow` is a welcome/ambient gesture with no note or cc lanes.
- `glow` is not intended for note/cc lanes; wiring one is an author error, out of scope.

## 4. Architecture

The change is entirely a **vocabulary** addition to luxaeterna, plus a follow-up
re-point in mm-terrarium. Data flow is unchanged:

```
Role.welcome["light"]  ──(role_config.py copies verbatim)──▶  manifest "welcome" dict
        │
        ▼
LightManifest.from_dict  ──▶  SignatureDecl(instrument="glow", params={"hue":…}, duration=…)
        │
        ▼
director._resolve_and_load:  Signature(registry.build("glow", hue=…), duration)
        │
        ▼
Signature.render → LightInstrument.render → Fill.render → LIT every frame
```

## 5. Component design

### 5.1 Promote `Fill` + `SegmentLevel` to `ugens.py`

`Fill` (a field-rate `level × color` across every pixel) and `SegmentLevel` (a
control-rate piecewise-linear envelope with optional loop) are generic primitives that
currently live in `status.py` only because that is where they were first needed. Move
both class definitions to `luxaeterna/synth/ugens.py`, alongside `SolidColor`, `Bloom`,
and `Envelope`.

- `status.py` imports them instead of defining them:
  `from .ugens import Const, Fill, Noise, SegmentLevel`.
- `ChannelSweep` stays in `status.py` (genuinely selftest-specific).
- `tests/synth/test_status.py`'s import line updates to pull `Fill`/`SegmentLevel` from
  `ugens` (the rest — `ChannelSweep`, `GainSignature`, `Signature`, `_sig_error` — stay
  from `status`).

Pure relocation — no behavior change. Rationale: it lets `glow` live in `presets.py`
without a `presets → status` import, which would be odd layering (`status.py` is the
reserved sys:\* gesture module; `presets.py` is the authorable-instrument module).

### 5.2 The `glow` instrument (`presets.py`)

```python
_GLOW_PARAMS = frozenset({"hue"})

def _make_glow(**params) -> LightInstrument:
    unknown = set(params) - _GLOW_PARAMS
    if unknown:                    # reject typo'd manifest params, don't discard them
        raise KeyError(f"unknown glow param(s) {sorted(unknown)} "
                       f"(known: {sorted(_GLOW_PARAMS)})")
    color = hsv_to_rgb(float(params.get("hue", 0.0)), 1.0, 1.0)
    level = SegmentLevel([(0.0, 0.0), (0.25, 1.0)])   # fade in over 0.25 s, then hold
    return LightInstrument(Fill(level, Const(color)), {})

registry.register("glow", _make_glow)
```

- **Full-field**, colored by `hue` (0–1 HSV, at full saturation/value — the same
  canonical `hue` param `bloom` exposes).
- **Duration-agnostic shape:** `SegmentLevel` rises to 1.0 over 0.25 s; `np.interp`
  clamps beyond the last point, so it **holds at full for any authored `duration`.**
  Visible across the whole LOADING window, then a hard hand-off to RUNNING (the same
  transition every welcome makes; gain stays 1.0). For a very short welcome
  (`duration < 0.25 s`) it is still lit throughout (rising 0 → peak), never dark.
- **Single `hue` param + reject-unknown-param `KeyError`** mirrors `_make_bloom`. This
  preserves the `test_bad_welcome_is_a_resolve_failure_not_an_escape` contract: a typo'd
  glow param is rejected by the factory, surfaces as a resolve failure, and routes to
  ERROR like any other.
- Returns a `LightInstrument` (has `.render()`), matching the instrument-factory
  convention the welcome path expects. No `noteon`/lanes.

### 5.3 mm-terrarium follow-up (after luxaeterna lands)

mm-terrarium installs luxaeterna as an **editable install** from
`/Users/chris/projects/luxaeterna` (`pip install -e "/Users/chris/projects/luxaeterna[websim]"`),
so `glow` is only importable once the luxaeterna change is on the checked-out branch
there. Sequencing: **luxaeterna PR merges first**, then:

- `bits/test_bit.py` — welcome light half `"instrument": "bloom"` → `"glow"` (keep
  `"params": {"hue": 0.33}`, `"duration": 1.5`). The `audio` half (`chime`) is untouched;
  the running `instruments` block (`bloom` + `note`/`cc:74` lanes) is untouched.
- `tests/test_led_smoke.py` §(a) — replace the apologetic dark-welcome workaround
  (`loading_frames > 10`, plus its ~20-line explanatory comment) with a real brightness
  check: at least one LOADING frame has `max(frame) > 0`. Keep the "reaches RUNNING
  within a bounded window" assertion.

## 6. Error handling & testing

**luxaeterna** (all must pass before the mm-terrarium follow-up):

- New `tests/synth/test_presets.py`:
  - `glow` builds via `registry.build("glow", hue=…)` and returns a `LightInstrument`.
  - Rendering one frame produces **non-zero, full-field** output (every pixel lit, not a
    localized bloom).
  - `hue` maps to the expected color (e.g. `hue=0.33` is green-dominant).
  - An unknown param raises `KeyError` (parity with `bloom`).
- New director test `test_glow_welcome_renders_lit` in `tests/synth/test_director.py`:
  swap a manifest whose welcome is `{"instrument": "glow", "duration": …}`, advance one
  `frame()`, render the resulting sig binding through a `RenderContext`, and assert
  `max > 0`. This is the deliberate counterpoint to
  `test_welcome_replaces_generic_loaded` ("a dark synth is fine"): the welcome pathway
  now produces light.
- `tests/synth/test_status.py` stays green after the §5.1 import move (regression guard
  on the relocation).

**mm-terrarium**:

- `tests/test_led_smoke.py` — the tightened §(a) brightness assertion becomes the durable
  regression that a `glow` welcome lights the LOADING window.

## 7. Alternatives considered (and why rejected)

- **(b) Auto-trigger a note-on when the welcome instrument is a `LightSynth`** — the
  director would fire a default `.noteon(pitch, vel)` for synth welcomes. Rejected:
  magic pitch/velocity the author can't control from a lane-less `SignatureDecl`
  (`bloom`'s center *is* `(pitch % 12) / 11`); no note-off, so the envelope sustains then
  hard-cuts; couples the director to instrument internals via an `isinstance` check; and
  it still leaves a plain field-gesture welcome impossible. It papers over the category
  error rather than fixing it.
- **(c) Add an explicit `note` field to `SignatureDecl`** — cleaner than (b) because the
  author opts in, but heavier (wire-schema change) and still forces every welcome to be a
  note-triggered synth. Rejected in favor of the simpler, more general (a).

## 8. Decisions locked (from brainstorm)

- Approach **(a)**: a `glow` gesture instrument that renders without a note.
- `Fill` + `SegmentLevel` **promoted to `ugens.py`** (generic primitives; keeps
  `presets.py` free of a `status` import).
- `glow` visual: **fade-in-then-hold** (`SegmentLevel([(0,0),(0.25,1.0)])`),
  duration-agnostic, full-field, `hue`-colored.
- `glow` param surface: **`hue` only**, with reject-unknown-param strictness matching
  `bloom`.
- **Zero director / welcome-path / manifest / resolve changes.**
- Two repos, sequenced: **luxaeterna first**, mm-terrarium second.
