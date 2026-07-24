# Aurora — Breathing Hue-Gliding Ambient Glow — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a continuously-rendering `aurora` instrument to luxaeterna — a full-field glow that breathes gently and whose hue glides smoothly under `cc` control — and adopt it as TestBit's running visual so the LED demo stops flashing.

**Architecture:** A vocabulary addition. luxaeterna gains one small control uGen (`HueColor`, hue→RGB per frame) and one instrument (`aurora` = `Fill(breathe, HueColor(Smooth(hue)))`), with `hue` exposed as a cc-drivable `Param`. The director/welcome-path/manifest/`resolve` are unchanged — `resolve()`'s existing cc-lane wiring already drives a param. mm-terrarium then points TestBit's running instrument at `aurora` (cc:74→hue lane, no note lane) and feeds the demo a smooth cc ramp.

**Tech Stack:** Python 3, numpy, colorsys, pytest.

## Global Constraints

- **luxaeterna test command:** run `/Users/chris/projects/luxaeterna/.venv/bin/pytest` **from the worktree cwd** (`/Users/chris/projects/luxaeterna/.claude/worktrees/kind-austin-6740a1`). Venv at repo root only; `pyproject.toml` sets `pythonpath = ["."]`; no editable install.
- **`aurora` param surface:** exactly `hue` (0–1 HSV), cc-drivable. Unknown build params raise `KeyError` — matching `_make_bloom`/`_make_glow` strictness (preserves the `test_bad_welcome_is_a_resolve_failure_not_an_escape` contract).
- **Tunable constants (not manifest params):** breathe = `SegmentLevel([(0.0, 0.55), (3.0, 1.0), (6.0, 0.55)], loop_from=0.0)`; `HUE_GLIDE_TAU = 0.4`.
- **NO changes** to `director.py`, the welcome path, `manifest.py`, or `binding.py`.
- **Do NOT modify `bloom` or `glow`.** `aurora` is a distinct instrument; the other two keep their exact current behavior.
- **`hsv_to_rgb` is promoted to `ugens.py`** (one copy); `presets.py` imports it from there.
- **mm-terrarium (Phases B):** run from the mm-terrarium checkout root with `.venv/bin/python -m pytest tests -q`; the full suite must be all-passing with **0 skipped**. luxaeterna imports resolve from the main checkout only when cwd is the mm-terrarium root (a luxaeterna cwd shadows the package). Phase A must merge to luxaeterna `main` before Phase B (editable install).
- **Accepted trade:** switching TestBit's running visual to note-less `aurora` means the *terrarium* smoke test no longer exercises the note-on path (`feed_midi`→`dispatch_midi`→`LightSynth.noteon`); that path stays covered by luxaeterna's own suite.

---

# Phase A — luxaeterna (this worktree)

Branch: `claude/aurora-smooth-glow` (already created off the merged `main`). All Phase A tasks run here.

## Task A1: Promote `hsv_to_rgb` to `ugens.py` + add the `HueColor` uGen

`HueColor` (a uGen) needs `hsv_to_rgb`, which currently lives in `presets.py`. Move the function to `ugens.py` (one copy; `presets.py` imports it — verified `hsv_to_rgb` has no importer outside `presets.py`), then add `HueColor`.

**Files:**
- Modify: `luxaeterna/synth/ugens.py` (add `import colorsys`, the `hsv_to_rgb` function, and the `HueColor` class)
- Modify: `luxaeterna/synth/presets.py` (drop the local `hsv_to_rgb` + now-unused `import colorsys`; import `hsv_to_rgb` from `.ugens`)
- Test: `tests/synth/test_control_ugens.py`

**Interfaces:**
- Produces: `luxaeterna.synth.ugens.hsv_to_rgb(h, s, v) -> np.ndarray` and `luxaeterna.synth.ugens.HueColor(hue)` (control-rate `LightUgen`; `hue` may be a scalar or a uGen; `render` returns a `(3,)` fully-saturated RGB array). Consumed by Task A2.

- [ ] **Step 1: Write the failing tests**

Append to `tests/synth/test_control_ugens.py` (the module's `ctx(frame, time, dt, n, channels)` helper already exists at the top):

```python
def test_huecolor_maps_hue_to_rgb():
    from luxaeterna.synth.ugens import HueColor, Const
    red = HueColor(Const(0.0)).render(ctx(0))       # hue 0 -> red
    assert red.shape == (3,)
    assert red[0] > red[1] and red[0] > red[2]
    green = HueColor(Const(0.33)).render(ctx(1))    # hue 0.33 -> green
    assert green[1] > green[0] and green[1] > green[2]


def test_huecolor_tracks_changing_hue():
    # Recomputes each frame from its live input, so a Smooth-ed / cc-driven hue
    # is reflected — not cached from construction.
    from luxaeterna.synth.ugens import HueColor, Const
    src = Const(0.0)
    hc = HueColor(src)
    assert hc.render(ctx(0))[0] > hc.render(ctx(0))[1]   # red (byte0 > byte1)
    src.set_target(0.33)
    g = hc.render(ctx(1))                                 # now green
    assert g[1] > g[0] and g[1] > g[2]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `/Users/chris/projects/luxaeterna/.venv/bin/pytest tests/synth/test_control_ugens.py -q`
Expected: FAIL — `ImportError: cannot import name 'HueColor' from 'luxaeterna.synth.ugens'`.

- [ ] **Step 3: Move `hsv_to_rgb` into `ugens.py` and add `HueColor`**

In `luxaeterna/synth/ugens.py`, add `import colorsys` to the imports at the top (below `import math`). Then add this function and class near the other field/colour helpers (e.g. immediately after the `Const` class):

```python
def hsv_to_rgb(h: float, s: float, v: float) -> np.ndarray:
    return np.asarray(colorsys.hsv_to_rgb(h % 1.0, s, v), dtype=float)


class HueColor(LightUgen):
    """Live hue (0–1) -> fully-saturated RGB, recomputed each frame. Lets a
    colour follow a control input (e.g. a Smooth-ed cc lane) instead of being
    frozen into a Const at construction."""

    rate = "control"

    def __init__(self, hue) -> None:
        super().__init__()
        self._hue = as_ugen(hue)

    def _compute(self, ctx: RenderContext) -> np.ndarray:
        return hsv_to_rgb(float(np.asarray(self._hue.render(ctx))), 1.0, 1.0)
```

- [ ] **Step 4: Update `presets.py` to import `hsv_to_rgb` from `ugens`**

In `luxaeterna/synth/presets.py`:
1. Delete the module-level `import colorsys` line and the local `def hsv_to_rgb(...)` definition (currently lines ~5 and ~14–15) — `colorsys` is used only by that function.
2. Add `hsv_to_rgb` to the ugens import. Change:
   ```python
   from .ugens import Const, Envelope, Bloom, Fill, SegmentLevel
   ```
   to:
   ```python
   from .ugens import Const, Envelope, Bloom, Fill, SegmentLevel, hsv_to_rgb
   ```
   (`bloom`/`glow` keep calling `hsv_to_rgb(...)` unchanged — it now resolves to the imported one.)

- [ ] **Step 5: Run the tests to verify they pass**

Run: `/Users/chris/projects/luxaeterna/.venv/bin/pytest tests/synth/test_control_ugens.py -q`
Expected: PASS (all, including the two new tests).

- [ ] **Step 6: Run the full synth suite — `bloom`/`glow` still resolve `hsv_to_rgb`**

Run: `/Users/chris/projects/luxaeterna/.venv/bin/pytest tests/synth -q`
Expected: all pass (the `hsv_to_rgb` relocation didn't break `bloom`/`glow`/`presets`).

- [ ] **Step 7: Commit**

```bash
git add luxaeterna/synth/ugens.py luxaeterna/synth/presets.py tests/synth/test_control_ugens.py
git commit -m "feat(synth): add HueColor uGen; promote hsv_to_rgb to ugens.py"
```

---

## Task A2: The `aurora` instrument

Add a full-field breathing glow whose hue is a cc-drivable, `Smooth`-glided `Param`. TDD via `test_presets.py` (behaviour) and `test_binding.py` (the cc-lane contract).

**Files:**
- Modify: `luxaeterna/synth/presets.py` (import `Smooth`/`HueColor` from `.ugens` and `Param` from `.instrument`; add `_make_aurora` + register)
- Modify: `tests/synth/test_presets.py` (aurora behaviour tests)
- Modify: `tests/synth/test_binding.py` (aurora cc:74→hue lane resolves + drives hue)

**Interfaces:**
- Consumes: `HueColor`, `hsv_to_rgb` (Task A1); `Smooth`, `SegmentLevel`, `Fill`, `Const` (`ugens`); `Param`, `LightInstrument` (`instrument`).
- Produces: registry entry `"aurora"` → `_make_aurora(**params) -> LightInstrument`. Renders full-field, breathes, hue glides. `param_names() == {"hue"}`; a `cc` lane may target `hue`. Consumed by Phase B's TestBit manifest.

- [ ] **Step 1: Write the failing behaviour tests**

Append to `tests/synth/test_presets.py` (its `_ctx(frame, n, channels, dt)` helper and `registry`/`np`/`pytest` imports already exist). Also add `import colorsys` at the top of the file:

```python
def _out_hue(pixel):
    return colorsys.rgb_to_hsv(float(pixel[0]), float(pixel[1]), float(pixel[2]))[0]


def test_aurora_renders_full_field_lit():
    out = registry.build("aurora", hue=0.33).render(_ctx(n=8, dt=0.3))
    assert out.shape == (8, 3)
    assert out.max(axis=1).min() > 0.0            # every pixel lit
    np.testing.assert_allclose(out[0], out[7])    # uniform across the zone


def test_aurora_breathes_and_never_dark():
    a = registry.build("aurora", hue=0.0)
    brights = [a.render(_ctx(frame=f, n=4, dt=0.5)).max() for f in range(14)]  # ~0.5–7 s
    assert max(brights) - min(brights) > 0.1      # brightness oscillates (breathe)
    assert min(brights) > 0.0                     # never fully dark


def test_aurora_hue_glides_toward_target_not_snap():
    a = registry.build("aurora", hue=0.0)
    a.render(_ctx(frame=0, n=4, dt=0.1))          # settle at hue 0 (red)
    a.set("hue", 0.33)                            # green target
    h1 = _out_hue(a.render(_ctx(frame=1, n=4, dt=0.1))[0])
    last = None
    for f in range(2, 40):
        last = a.render(_ctx(frame=f, n=4, dt=0.1))
    hN = _out_hue(last[0])
    assert 0.0 < h1 < 0.33                        # started gliding, did not snap
    assert abs(hN - 0.33) < 0.02                  # converged near the target


def test_aurora_param_names_and_rejects_unknown():
    a = registry.build("aurora", hue=0.1)
    assert a.param_names() == {"hue"}             # so a cc lane can target it
    with pytest.raises(KeyError):
        registry.build("aurora", huue=0.5)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `/Users/chris/projects/luxaeterna/.venv/bin/pytest tests/synth/test_presets.py -q`
Expected: FAIL — the `build("aurora", …)` tests raise `KeyError: "unknown instrument type 'aurora'"` (aurora isn't registered yet).

- [ ] **Step 3: Implement `_make_aurora`**

In `luxaeterna/synth/presets.py`, extend the imports:
- ugens line → `from .ugens import Const, Envelope, Bloom, Fill, SegmentLevel, Smooth, HueColor, hsv_to_rgb`
- instrument line → `from .instrument import LightInstrument, LightSynth, Param`

Then add, after the `glow` registration at the end of the file:

```python
_AURORA_PARAMS = frozenset({"hue"})

_AURORA_BREATHE = [(0.0, 0.55), (3.0, 1.0), (6.0, 0.55)]   # ~6 s cycle, never dark
_AURORA_HUE_GLIDE_TAU = 0.4                                # seconds


def _make_aurora(**params) -> LightInstrument:
    unknown = set(params) - _AURORA_PARAMS
    if unknown:                    # reject typo'd manifest params, don't discard them
        raise KeyError(f"unknown aurora param(s) {sorted(unknown)} "
                       f"(known: {sorted(_AURORA_PARAMS)})")
    hue = Smooth(Const(float(params.get("hue", 0.0))), _AURORA_HUE_GLIDE_TAU)
    level = SegmentLevel(_AURORA_BREATHE, loop_from=0.0)
    out = Fill(level, HueColor(hue))
    return LightInstrument(out, {"hue": Param("hue", hue)})


registry.register("aurora", _make_aurora)
```

- [ ] **Step 4: Run the behaviour tests to verify they pass**

Run: `/Users/chris/projects/luxaeterna/.venv/bin/pytest tests/synth/test_presets.py -q`
Expected: PASS (all, including the four new aurora tests).

- [ ] **Step 5: Write the failing binding test**

Append to `tests/synth/test_binding.py` (its imports of `LightInstrumentDecl`, `LightLane`, `resolve`, `shroom_capability`, `RenderContext`, `np` already exist):

```python
def test_resolve_aurora_cc_hue_lane_drives_glide():
    # aurora exposes a "hue" param, so a cc:74 -> hue lane resolves and its route
    # drives the colour (the contract the whole smooth-glow design leans on).
    decl = LightInstrumentDecl(
        instrument="aurora", target="primary", params={},
        lanes=[LightLane("cc:74", "hue")])
    binding = resolve(decl, shroom_capability("ie3"))   # must NOT raise
    assert "cc:74" in binding.routes
    binding.routes["cc:74"](0.33)                       # drive hue toward green
    out = None
    for f in range(40):
        out = binding.render(RenderContext(0.0, f, 0.1, np.linspace(0, 1, 12), 12, 3))
    assert out[0, 1] > out[0, 0] and out[0, 1] > out[0, 2]   # glided to green-dominant
```

- [ ] **Step 6: Run the binding test to verify it passes**

Run: `/Users/chris/projects/luxaeterna/.venv/bin/pytest tests/synth/test_binding.py::test_resolve_aurora_cc_hue_lane_drives_glide -q`
Expected: PASS (aurora already registered in Step 3; this guards the lane contract).

- [ ] **Step 7: Run the full synth suite**

Run: `/Users/chris/projects/luxaeterna/.venv/bin/pytest tests/synth -q`
Expected: all pass (existing `bloom`/`glow`/director/status tests unchanged).

- [ ] **Step 8: Commit**

```bash
git add luxaeterna/synth/presets.py tests/synth/test_presets.py tests/synth/test_binding.py
git commit -m "feat(synth): add aurora — breathing, hue-gliding ambient glow instrument"
```

---

**End of Phase A.** luxaeterna now has `aurora`. Close out Phase A as its own PR (see `finishing-a-development-branch`) and merge it to luxaeterna `main` before starting Phase B — the mm-terrarium editable install must expose `aurora`.

---

# Phase B — mm-terrarium `main` (cross-repo follow-up)

> **Separate execution session in `~/projects/mm-terrarium`, gated on Phase A merged.** Branch off `main` (e.g. `claude/aurora-running-visual`), open a PR back to `main`.

**Phase B precondition — verify `aurora` is importable before starting:**

1. `git -C ~/projects/luxaeterna checkout main && git -C ~/projects/luxaeterna pull`
2. From the mm-terrarium checkout root: `.venv/bin/python -c "from luxaeterna.synth import registry; assert 'aurora' in registry._REGISTRY, 'aurora not available — merge luxaeterna Phase A first'; print('aurora available')"`

Expected: `aurora available`. If it asserts, stop.

## Task B1: TestBit running visual → `aurora`, and the full-stack regression

Combined red→green task with ONE commit: rewrite the smoke test's mid-section to assert the aurora behaviour (RED, because the running instrument is still note-triggered `bloom`), then re-point TestBit's running instrument to `aurora` and update the manifest-pinning unit test (GREEN).

**Files:**
- Modify: `tests/test_led_smoke.py` (§(b)/§(c) rewrite + docstring)
- Modify: `bits/test_bit.py` (running instrument `bloom`+note+cc → `aurora`+cc)
- Modify: `tests/test_test_bit.py` (the `player.light_manifest` expected literal)

- [ ] **Step 1: Rewrite the smoke test's §(b)/§(c)**

In `tests/test_led_smoke.py`, replace the block from the `# (b) dark before any note` comment through the `lit = max(frame)` line (currently lines 52–63) with:

```python
    # (b) aurora renders LIT during RUNNING with NO note-on — a field-rate gesture,
    #     unlike the old note-triggered bloom (dark until a note). Its authored
    #     hue 0.33 is green (GRB byte order: byte0=green, byte1=red).
    loop._loop_once()
    frame = backend.frames[-1]
    assert max(frame) > 0                              # lit without any note fed
    assert max(frame[0::3]) > max(frame[1::3])         # green-dominant (hue 0.33)

    # (c) cc:74 drives the hue and it GLIDES (Smooth), not a snap. Drive toward red
    #     (cc 0); one frame later it is still green-dominant (mid-glide), and after
    #     ~1.4 s it has become red-dominant. Brightness varies across the window
    #     (the breathe). max(frame) == the breathe level (hsv value is always 1.0).
    session.feed_midi(0xB0, 74, 0)                     # target hue 0 (red)
    loop._loop_once()
    mid = backend.frames[-1]
    assert max(mid[0::3]) > max(mid[1::3])             # still green-dominant -> glided, not snapped
    maxes = []
    for _ in range(60):
        loop._loop_once()
        maxes.append(max(backend.frames[-1]))
    settled = backend.frames[-1]
    assert max(settled[1::3]) > max(settled[0::3])     # now red-dominant -> cc glided the hue
    assert max(maxes) - min(maxes) > 0.02              # brightness breathes over the window
    lit = max(maxes)                                    # a lit running frame for the fade check
```

Also update the module docstring line 4 from
`Asserts welcome -> dark-when-running -> note lights + hue routing -> fade."""`
to
`Asserts welcome -> lit-without-a-note -> cc-driven hue glide + breathe -> fade."""`

- [ ] **Step 2: Run the smoke test — it FAILS on the still-`bloom` running visual**

Run (from the mm-terrarium checkout root): `.venv/bin/python -m pytest tests/test_led_smoke.py -q`
Expected: FAIL — §(b) `assert max(frame) > 0` fails: TestBit's running instrument is still `bloom`, which renders dark with no note-on. This is the RED state.

- [ ] **Step 3: Re-point TestBit's running instrument to `aurora`**

In `bits/test_bit.py`, replace the `instruments` list in `light_manifest` (the running instrument) so it is `aurora` with only a `cc:74 → hue` lane (drop the `note` lane; keep `params`/`target`). Change:

```python
            light_manifest={
                "instruments": [
                    {"instrument": "bloom", "target": "primary",
                     "params": {"hue": 0.33},
                     "lanes": [{"source": "note", "dest": "trigger"},
                               {"source": "cc:74", "dest": "hue"}]},
                ],
            },
```
to:
```python
            light_manifest={
                "instruments": [
                    {"instrument": "aurora", "target": "primary",
                     "params": {"hue": 0.33},
                     "lanes": [{"source": "cc:74", "dest": "hue"}]},
                ],
            },
```
Leave the `welcome=` block (glow) untouched.

- [ ] **Step 4: Update the manifest-pinning unit test**

In `tests/test_test_bit.py`, update the `player.light_manifest` expected literal to match Step 3 (drop the note lane; `bloom`→`aurora`). Change:

```python
    assert player.light_manifest == {
        "instruments": [
            {"instrument": "bloom", "target": "primary",
             "params": {"hue": 0.33},
             "lanes": [{"source": "note", "dest": "trigger"},
                       {"source": "cc:74", "dest": "hue"}]},
        ],
    }
```
to:
```python
    assert player.light_manifest == {
        "instruments": [
            {"instrument": "aurora", "target": "primary",
             "params": {"hue": 0.33},
             "lanes": [{"source": "cc:74", "dest": "hue"}]},
        ],
    }
```
(The `player.welcome ==` assertion just below stays `glow`, unchanged.)

- [ ] **Step 5: Run the smoke test + the bit test — now GREEN**

Run: `.venv/bin/python -m pytest tests/test_led_smoke.py tests/test_test_bit.py -q`
Expected: PASS — aurora renders lit without a note, glides hue under cc:74, breathes; the pinned manifest matches.

- [ ] **Step 6: Run the full mm-terrarium suite**

Run: `.venv/bin/python -m pytest tests -q`
Expected: all pass, **0 skipped**. (The `"bloom"` literals in `tests/test_role_config.py` / `tests/test_console_protocol.py` are independent synthetic fixtures — Control validates welcome/manifest *structure*, not names — so they are unaffected.)

- [ ] **Step 7: Commit**

```bash
git add tests/test_led_smoke.py bits/test_bit.py tests/test_test_bit.py
git commit -m "feat(led): aurora running visual — lit without notes, cc-glided hue, breathing"
```

## Task B2: `led_smoke.py` demo loop → smooth cc ramp, no note-ons

The demo's RUNNING loop machine-guns note-ons (the strobe) and steps `cc` coarsely. With `aurora` (no note lane) the note-ons are dead; replace the loop with a smooth `cc:74` ping-pong ramp so the hue drifts and `aurora` glides between steps.

**Files:**
- Modify: `harness/led_smoke.py` (the `while gs.state == State.RUNNING:` loop in `main()`)

- [ ] **Step 1: Replace the RUNNING sweep loop**

In `harness/led_smoke.py`, replace the sweep block inside `main()` — from `cc = 0` through `time.sleep(0.15)` (the body of the `while gs.state == State.RUNNING:` loop, currently):

```python
        cc = 0
        while gs.state == State.RUNNING:
            session.feed_midi(0xB0, 74, cc)          # cc:74 -> hue
            session.feed_midi(0x90, 60, 100)         # new voice at current hue
            cc = (cc + 8) % 128
            gs.tick(0.15)                            # advances TestBit toward complete
            time.sleep(0.15)
```
with (no note-ons; a fine ping-pong cc ramp that aurora's Smooth glides between):

```python
        cc, step = 0, 2
        while gs.state == State.RUNNING:
            session.feed_midi(0xB0, 74, cc)          # cc:74 -> hue; aurora glides between steps
            cc += step
            if cc >= 127 or cc <= 0:                 # ping-pong (no wrap discontinuity)
                cc = max(0, min(127, cc))
                step = -step
            gs.tick(0.15)                            # advances TestBit toward complete
            time.sleep(0.15)
```

- [ ] **Step 2: Confirm the module still imports (no `main()` unit test exists)**

Run: `.venv/bin/python -c "import harness.led_smoke; print('ok')"`
Expected: `ok` (run from the mm-terrarium checkout root).

- [ ] **Step 3: Run the full suite — nothing regressed**

Run: `.venv/bin/python -m pytest tests -q`
Expected: all pass, 0 skipped. (`tests/test_led_smoke.py` builds its own pipeline and drives cc directly; it does not call `main()`, so this demo-loop change does not affect it.)

- [ ] **Step 4: Manual acceptance (deferred to a human)**

`.venv/bin/python -m harness.led_smoke --seconds 300`, open `http://127.0.0.1:8770/`: the welcome is a brief green glow, then the running visual is a **smooth breathing glow whose colour drifts** with no flashing. (This step is a human eyeball check; it is not automated.)

- [ ] **Step 5: Commit**

```bash
git add harness/led_smoke.py
git commit -m "feat(harness): smooth cc ramp for the aurora demo (drop the note-on strobe)"
```

---

## Self-Review (completed during authoring)

**Spec coverage** — every §-requirement maps to a task:
- §5.1 (promote `hsv_to_rgb`) → A1. §5.2 (`HueColor` uGen) → A1. §5.3 (`aurora` instrument: full-field, breathe, cc-drivable glided hue, reject-unknown) → A2.
- §5.4 (TestBit running → aurora+cc lane; test_test_bit; led_smoke smooth ramp; smoke-test rewrite) → B1, B2.
- §6 testing (`HueColor` tests; aurora full-field/breathe/glide/param tests; binding cc-lane test; smoke-test cc-glide+breathe) → A1 Step 1, A2 Steps 1/5, B1 Step 1.
- §7 (alternatives), §8 (decisions) — enforced by Global Constraints + task scopes; §8's "no bloom/glow changes" is a Global Constraint and no task touches them.

**Placeholder scan** — none; every code step shows complete, paste-ready content.

**Type consistency** — `HueColor(hue)` / `hsv_to_rgb(h, s, v)` defined in A1 are consumed with matching signatures in A2's `_make_aurora`. `_make_aurora(**params) -> LightInstrument` and the registry name `"aurora"` are used identically in A2 (definition), the A2 binding test, and B1 (TestBit manifest + pinned test). `Smooth(source, tau)`, `SegmentLevel(points, loop_from=)`, `Fill(level, color)`, `Param(name, ugen)`, `LightInstrument(output, params)`, `RenderContext(time, frame, dt, positions, n, channels)` all match the current sources verified during authoring. GRB byte order (`frame[0::3]`=green, `frame[1::3]`=red) in the smoke test matches the existing §(c) convention; the luxaeterna-side tests use natural RGB (uGen output order), consistent with `test_field_ugens.py`.
