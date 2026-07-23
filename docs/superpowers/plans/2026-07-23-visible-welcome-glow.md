# Visible Welcome via a `glow` Gesture Instrument — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Bit authors a field-rate `glow` welcome instrument in luxaeterna that renders lit without a note, so a per-role welcome is actually visible for its whole LOADING window.

**Architecture:** Pure vocabulary addition. luxaeterna gains one field-rate instrument (`Fill(SegmentLevel, Const(color))` wrapped as a `LightInstrument`) registered as `glow`; the director, welcome path, manifest schema, and `resolve` are untouched — the existing `Signature(registry.build(name, **params), duration)` welcome path already renders it. `Fill`/`SegmentLevel` are promoted from `status.py` to `ugens.py` first so `glow` can live in `presets.py` without a `presets → status` import. mm-terrarium then re-points TestBit's welcome at `glow` and tightens its smoke test. A separate, independent phase adds a viewing-duration flag to the `harness/led_smoke.py` demo so it can be watched in a browser.

**Tech Stack:** Python 3, numpy, pytest, argparse. Two repos: luxaeterna (renderer, primary) and mm-terrarium (consumer).

**Phases (three PRs):**
- **Phase A — luxaeterna:** the `glow` instrument. Merges to luxaeterna `main`.
- **Phase B — mm-terrarium `main`:** re-point TestBit's welcome at `glow` + tighten the smoke test. **Gated on Phase A merged** to luxaeterna `main`.
- **Phase C — mm-terrarium `main`:** `harness/led_smoke.py` viewing-duration flag. **Independent** — needs only luxaeterna `main` as it already is (its `WebSimBackend`, merged via luxaeterna#6, is present today); no dependency on A or B. Executable at any time, in its own PR.

## Global Constraints

- **luxaeterna test command:** run `/Users/chris/projects/luxaeterna/.venv/bin/pytest` **from the worktree cwd** (`/Users/chris/projects/luxaeterna/.claude/worktrees/kind-austin-6740a1`). The venv lives at the repo root only; `pyproject.toml` sets `pythonpath = ["."]`, so the worktree's own `luxaeterna/` package is imported — no editable install, no per-worktree venv.
- **`glow` param surface:** exactly `hue` (0–1 HSV). Unknown params raise `KeyError` — matching `bloom`'s `_make_bloom` strictness, which preserves luxaeterna's `test_bad_welcome_is_a_resolve_failure_not_an_escape` contract.
- **No changes** to `director.py`, the welcome path, `manifest.py`, or `binding.py`. If a task seems to need one, stop — the design says it doesn't.
- **`Fill`/`SegmentLevel`** are generic field/control primitives; after Task A1 they live in `ugens.py`. `ChannelSweep` stays in `status.py`.
- **Repo sequencing:** Phase A (luxaeterna) must merge before Phase B (mm-terrarium) — mm-terrarium imports luxaeterna as an editable install from `/Users/chris/projects/luxaeterna`, so `glow` is only importable once it lands on that checkout's `main`. Instrument names are **opaque to Control** (`control/role_config.py::_validate_welcome` validates welcome *structure*, not names), so re-pointing the welcome needs no Control-side changes. **Phase C has no such gate** — it uses only `WebSimBackend`/`feed_midi`, already on luxaeterna `main`.
- **mm-terrarium test command (Phases B & C):** the Slice-1 harness landed on `main` (PR mm-terrarium#6, HEAD `de2a6aa`). Run from the mm-terrarium checkout root with its own `.venv`: `.venv/bin/python -m pytest tests -q`. Tests `importorskip("luxaeterna.backends.websim")`, so a checkout without luxaeterna installed skips them rather than failing.

---

# Phase A — luxaeterna (this worktree)

Branch: `claude/heuristic-borg-9ff736`. All Phase A tasks run here.

## Task A1: Promote `Fill` + `SegmentLevel` to `ugens.py`

Pure relocation of two generic primitives out of `status.py`. No behavior change — guarded by the existing `test_status.py` and the full synth suite. `status.py` currently defines both classes and is their only consumer besides `tests/synth/test_status.py` (verified: `grep -rn "Fill\|SegmentLevel" luxaeterna tests` shows no other importers).

**Files:**
- Modify: `luxaeterna/synth/ugens.py` (add both classes)
- Modify: `luxaeterna/synth/status.py` (delete both classes; fix imports)
- Modify: `tests/synth/test_status.py:8-10` (import the two classes from `ugens` instead of `status`)

**Interfaces:**
- Produces: `luxaeterna.synth.ugens.SegmentLevel(points, loop_from=None)` (control-rate `LightUgen`) and `luxaeterna.synth.ugens.Fill(level, color)` (field-rate `LightUgen`) — consumed by Task A2 (`glow`) and by `status.py`'s `sys:*` gestures.

- [ ] **Step 1: Baseline — confirm the suite is green before touching anything**

Run: `/Users/chris/projects/luxaeterna/.venv/bin/pytest tests/synth/test_status.py -q`
Expected: `7 passed`

- [ ] **Step 2: Add `SegmentLevel` to `ugens.py`**

Insert this class immediately **after** the `Envelope` class (i.e. after its `_compute`, before `CCReader`) in `luxaeterna/synth/ugens.py`. It is copied verbatim from `status.py`; `ugens.py` already imports `LightUgen, RenderContext, as_ugen` and `np`.

```python
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
```

- [ ] **Step 3: Add `Fill` to `ugens.py`**

Insert this class immediately **after** the `SolidColor` class in `luxaeterna/synth/ugens.py` (field-rate section). Copied verbatim from `status.py`.

```python
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
```

- [ ] **Step 4: Delete both classes from `status.py` and fix its imports**

In `luxaeterna/synth/status.py`, delete the `SegmentLevel` class (currently lines ~60–81) and the `Fill` class (currently lines ~84–99). Then change the two import lines at the top:

Change:
```python
from .signal import LightUgen, RenderContext, as_ugen
from .ugens import Const, Noise
```
to:
```python
from .signal import LightUgen, RenderContext
from .ugens import Const, Fill, Noise, SegmentLevel
```

(`as_ugen` was used only by the now-moved `Fill`, so it becomes unused in `status.py`. `LightUgen`/`RenderContext` are still used by `ChannelSweep`.)

- [ ] **Step 5: Update the `test_status.py` imports to pull the two classes from `ugens`**

In `tests/synth/test_status.py`, change lines 8–10:

From:
```python
from luxaeterna.synth.status import (ChannelSweep, Fill, GainSignature,
                                     SegmentLevel, Signature, _sig_error)
from luxaeterna.synth.ugens import Const
```
To:
```python
from luxaeterna.synth.status import (ChannelSweep, GainSignature, Signature,
                                     _sig_error)
from luxaeterna.synth.ugens import Const, Fill, SegmentLevel
```

- [ ] **Step 6: Run `test_status.py` — the relocation preserves behavior**

Run: `/Users/chris/projects/luxaeterna/.venv/bin/pytest tests/synth/test_status.py -q`
Expected: `7 passed`

- [ ] **Step 7: Run the full synth suite — nothing else broke**

Run: `/Users/chris/projects/luxaeterna/.venv/bin/pytest tests/synth -q`
Expected: all pass (same count as before the change; no import errors).

- [ ] **Step 8: Commit**

```bash
git add luxaeterna/synth/ugens.py luxaeterna/synth/status.py tests/synth/test_status.py
git commit -m "refactor(synth): promote Fill + SegmentLevel from status.py to ugens.py"
```

---

## Task A2: The `glow` instrument

Add a field-rate `glow` instrument that renders lit every frame without a note. TDD: write `tests/synth/test_presets.py` (the first test file for `presets.py`), watch it fail, implement `_make_glow`, watch it pass.

**Files:**
- Create: `tests/synth/test_presets.py`
- Modify: `luxaeterna/synth/presets.py` (import `Fill`/`SegmentLevel`; add `_make_glow` + register)

**Interfaces:**
- Consumes: `Fill`, `SegmentLevel` from `ugens` (Task A1); `hsv_to_rgb`, `Const`, `LightInstrument`, `registry` already in `presets.py`.
- Produces: registry entry `"glow"` → `_make_glow(**params) -> LightInstrument`. Rendering yields a full-field, `hue`-colored, `(n, channels)` frame. Unknown params raise `KeyError`. Consumed by Task A3 and by Phase B's TestBit welcome.

- [ ] **Step 1: Write the failing tests**

Create `tests/synth/test_presets.py`:

```python
"""Lux Aeterna — tests for the authorable instrument presets (glow)."""

from __future__ import annotations

import numpy as np
import pytest

from luxaeterna.synth import registry
from luxaeterna.synth.instrument import LightInstrument
from luxaeterna.synth.signal import RenderContext


def _ctx(frame=0, n=8, channels=3, dt=0.3):
    # dt > glow's 0.25 s fade-in means the very first rendered frame already
    # holds at full level, so brightness assertions don't depend on frame count.
    return RenderContext(time=frame * dt, frame=frame, dt=dt,
                         positions=np.linspace(0, 1, n), n=n, channels=channels)


def test_glow_builds_as_instrument():
    assert isinstance(registry.build("glow", hue=0.1), LightInstrument)


def test_glow_renders_full_field_lit():
    out = registry.build("glow", hue=0.33).render(_ctx(n=8))
    assert out.shape == (8, 3)
    assert out.max(axis=1).min() > 0.0          # every pixel has a lit channel
    np.testing.assert_allclose(out[0], out[7])  # uniform across the whole zone


def test_glow_hue_sets_color():
    out = registry.build("glow", hue=0.33).render(_ctx(n=4))
    assert out[0, 1] > out[0, 0] and out[0, 1] > out[0, 2]   # hue 0.33 -> green-dominant


def test_glow_defaults_to_hue_zero_and_lights():
    out = registry.build("glow").render(_ctx(n=4))
    assert out.max() > 0.0                       # no params still renders (hue=0 -> red)


def test_glow_rejects_unknown_param():
    with pytest.raises(KeyError):
        registry.build("glow", huue=0.5)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `/Users/chris/projects/luxaeterna/.venv/bin/pytest tests/synth/test_presets.py -q`
Expected: FAIL. The four `build("glow", …)`/render tests fail with `KeyError: "unknown instrument type 'glow'"`. (`test_glow_rejects_unknown_param` may pass incidentally — the registry rejects the unknown *name* with a `KeyError` before `_make_glow` exists; after Step 3 it passes for the right reason: the factory rejects the unknown *param*.)

- [ ] **Step 3: Implement `_make_glow`**

In `luxaeterna/synth/presets.py`, change the ugens import line:

From:
```python
from .ugens import Const, Envelope, Bloom
```
To:
```python
from .ugens import Bloom, Const, Envelope, Fill, SegmentLevel
```

Then add, **after** the existing `registry.register("bloom", _make_bloom)` line at the end of the file:

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

- [ ] **Step 4: Run the tests to verify they pass**

Run: `/Users/chris/projects/luxaeterna/.venv/bin/pytest tests/synth/test_presets.py -q`
Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add luxaeterna/synth/presets.py tests/synth/test_presets.py
git commit -m "feat(synth): add field-rate glow instrument (renders lit without a note)"
```

---

## Task A3: Director-level "welcome renders lit" regression

Lock in — at the director/welcome-path level — that a `glow` welcome produces light during LOADING, where a bare `bloom` welcome is dark. This is the deliberate counterpoint to the existing `test_welcome_replaces_generic_loaded` ("a dark synth is fine — only timing matters"). The red→green step demonstrates the guard bites: point the welcome at `bloom` first (dark, fails), then at `glow` (lit, passes).

**Files:**
- Modify: `tests/synth/test_director.py` (add imports + one test)

**Interfaces:**
- Consumes: `registry` entry `"glow"` (Task A2); `StatusDirector`, `LOADING`, `LightManifest`, `shroom_capability` already imported in the test module.

- [ ] **Step 1: Add the imports**

At the top of `tests/synth/test_director.py`, add (after the existing `from __future__ import annotations`):

```python
import numpy as np

from luxaeterna.synth.signal import RenderContext
```

- [ ] **Step 2: Write the test — first pointed at `bloom` to capture the bug**

Append to `tests/synth/test_director.py`, initially with the welcome instrument set to **`"bloom"`**:

```python
def test_glow_welcome_renders_lit():
    # A welcome must actually light the surface during LOADING. Counterpoint to
    # test_welcome_replaces_generic_loaded: a bare `bloom` welcome is a note-
    # triggered synth with no voice, so it renders dark; a `glow` welcome is a
    # field-rate gesture that renders without a note.
    m = LightManifest.from_dict({
        "instruments": [{"instrument": "bloom", "target": "primary"}],
        "welcome": {"instrument": "bloom", "params": {"hue": 0.33},
                    "duration": 0.5}})
    d = _mk()
    d.swap(m)
    assert d.state == LOADING
    ctx = RenderContext(time=0.0, frame=0, dt=0.05,
                        positions=np.linspace(0, 1, 12), n=12, channels=3)
    out = d._sig_binding.render(ctx)
    assert out.max() > 0.0                       # the welcome pathway is lit
```

- [ ] **Step 3: Run it — the `bloom` welcome fails the lit assertion**

Run: `/Users/chris/projects/luxaeterna/.venv/bin/pytest tests/synth/test_director.py::test_glow_welcome_renders_lit -q`
Expected: FAIL — `assert out.max() > 0.0` fails because the `bloom` welcome renders all zeros (a `LightSynth` with no note-on has no voices).

- [ ] **Step 4: Switch the welcome to `glow`**

In the test just written, change the welcome instrument from `"bloom"` to `"glow"`:

```python
        "welcome": {"instrument": "glow", "params": {"hue": 0.33},
                    "duration": 0.5}})
```

- [ ] **Step 5: Run it — the `glow` welcome is lit**

Run: `/Users/chris/projects/luxaeterna/.venv/bin/pytest tests/synth/test_director.py::test_glow_welcome_renders_lit -q`
Expected: `1 passed`

- [ ] **Step 6: Run the full synth suite**

Run: `/Users/chris/projects/luxaeterna/.venv/bin/pytest tests/synth -q`
Expected: all pass (existing director tests, including `test_welcome_replaces_generic_loaded`, unchanged).

- [ ] **Step 7: Commit**

```bash
git add tests/synth/test_director.py
git commit -m "test(synth): glow welcome renders lit during LOADING (regression guard)"
```

---

**End of Phase A.** At this point luxaeterna has a working, tested `glow` instrument. Close out Phase A as its own PR (see `finishing-a-development-branch`) and merge it before starting Phase B — the mm-terrarium editable install must expose `glow`.

---

# Phase B — mm-terrarium `main` (cross-repo follow-up)

> **Separate execution session in `~/projects/mm-terrarium`, gated on Phase A merged.** The Slice-1 harness — `tests/test_led_smoke.py`, `harness/`, and the `bloom`-welcome `TestBit` — is already on `main` (PR mm-terrarium#6, HEAD `de2a6aa`). Branch off `main` (e.g. `claude/welcome-glow`) and open a PR back to `main`.

**Phase B precondition — verify `glow` is importable before starting:**

1. Ensure the luxaeterna editable checkout reflects the merged Phase A:
   `git -C ~/projects/luxaeterna checkout main && git -C ~/projects/luxaeterna pull`
2. Run (from the mm-terrarium checkout root): `.venv/bin/python -c "from luxaeterna.synth import registry; assert 'glow' in registry._REGISTRY, 'glow not available — merge luxaeterna Phase A first'; print('glow available')"`

Expected: `glow available`. If it asserts, stop — Phase A is not yet merged/installed.

## Task B1: Tighten the smoke-test LOADING assertion (red)

Replace the apologetic dark-welcome workaround in `tests/test_led_smoke.py` §(a) with a real brightness check. With TestBit still on the `bloom` welcome, this **fails** — capturing the bug the same way Task A3 did, but at the full-stack level.

**Files:**
- Modify: `tests/test_led_smoke.py:38-69`

- [ ] **Step 1: Replace the §(a) block**

In `tests/test_led_smoke.py`, replace the entire block from the `# (a) welcome signature plays out …` comment through the `assert loading_frames > 10` line (currently lines 38–69) with:

```python
    # (a) The welcome signature plays out during LOADING and is LIT the whole
    # time (glow is a field-rate gesture that renders without a note), then the
    # session transitions to RUNNING within a bounded window.
    loading_lit = False
    for _ in range(200):
        loop._loop_once()
        if session.state == "loading":
            if max(backend.frames[-1]) > 0:
                loading_lit = True
        elif session.state == "running":
            break
    assert session.state == "running"
    assert loading_lit                           # welcome actually lit the surface
```

- [ ] **Step 2: Run the smoke test — it fails on the dark `bloom` welcome**

Run: `.venv/bin/pytest tests/test_led_smoke.py -q`
Expected: FAIL — `assert loading_lit` fails; the `bloom` welcome renders all-zero frames during LOADING (no note-on ever fires; `LightSession._apply` drops MIDI unless state is RUNNING).

- [ ] **Step 3: Commit the red test**

```bash
git add tests/test_led_smoke.py
git commit -m "test(led-smoke): assert the welcome actually lights the LOADING window"
```

## Task B2: Re-point TestBit's welcome to `glow` (green)

**Files:**
- Modify: `bits/test_bit.py` (welcome light half)

- [ ] **Step 1: Change the welcome light instrument**

In `bits/test_bit.py`, in the `welcome=` block, change the `light` half's instrument from `"bloom"` to `"glow"` (leave `params`/`duration` and the `audio` half untouched):

From:
```python
            welcome={
                "light": {"instrument": "bloom",
                          "params": {"hue": 0.33}, "duration": 1.5},
                "audio": {"instrument": "chime", "duration": 1.5},
            },
```
To:
```python
            welcome={
                "light": {"instrument": "glow",
                          "params": {"hue": 0.33}, "duration": 1.5},
                "audio": {"instrument": "chime", "duration": 1.5},
            },
```

- [ ] **Step 2: Run the smoke test — now green**

Run: `.venv/bin/pytest tests/test_led_smoke.py -q`
Expected: `1 passed` — the `glow` welcome lights the LOADING window.

- [ ] **Step 3: Run the full mm-terrarium suite**

Run: `.venv/bin/pytest -q`
Expected: all pass. The `"bloom"` literals in `tests/test_role_config.py` and `tests/test_console_protocol.py` are independent synthetic role fixtures — Control validates welcome *structure*, not instrument names — so they are unaffected.

- [ ] **Step 4: Commit**

```bash
git add bits/test_bit.py
git commit -m "feat(test-bit): point the welcome at glow so the LOADING window is visible"
```

---

# Phase C — mm-terrarium `main` (independent PR)

> **Separate execution session in `~/projects/mm-terrarium`. No gate on Phase A/B** — this uses only `WebSimBackend`/`feed_midi`, already on luxaeterna `main` (luxaeterna#6). Branch off `main` (e.g. `claude/led-smoke-duration-flag`), open a PR back to `main`. Purely a viewing-ergonomics change to the demo script; no stack behavior changes.

**Precondition — confirm the demo's dependency is importable:**

Run (from the mm-terrarium checkout root): `.venv/bin/python -c "import luxaeterna.backends.websim; print('websim available')"`
Expected: `websim available`. (If it errors, run the editable install from `requirements-dev.txt`.)

## Task C1: `--seconds` / `--hold` viewing-duration flag for the LED-sim demo

`harness/led_smoke.py` is a fixed ~5 s one-shot (TestBit's natural 2 s run + fade), and its web server is a daemon thread that dies when the process exits — so a human can't switch to a browser before it's gone. Add flags to keep it up: `--seconds N` (sweep N s then complete + fade), `--hold` (serve until Ctrl-C), plus `--host`/`--port`. Default (no flag) preserves today's behavior. The one lever: `GameServer` maps a name to a **callable**, so registering `lambda: TestBit(run_duration=…)` sets the Bit's lifetime; `run_duration=float('inf')` never completes. Extract a `build()` helper (mirroring luxaeterna's `build_demo`) so the pure parts are testable without a live server.

**Files:**
- Modify: `harness/led_smoke.py` (add `argparse`; add `build()` + `_run_duration()`; rewrite `main()` to parse flags; update the module docstring)
- Create: `tests/test_led_smoke_cli.py`

**Interfaces:**
- Consumes: `TestBit(run_duration=…)` and `RUN_DURATION_SECONDS` from `bits.test_bit` (`RUN_DURATION_SECONDS = 2.0`, `TestBit.__init__(run_duration=RUN_DURATION_SECONDS)` already exist — no change to `test_bit.py`); `DeviceBridge(capability=None, clock=time.monotonic)`, `WebSimBackend(capability, host, port, serve)`, `GameServer`, `OutputLoop`, `shroom_capability`, `Universe`, `State` — all already imported by `led_smoke.py`.
- Produces: `build(run_duration, host="127.0.0.1", port=8770, serve=True, clock=time.monotonic) -> (loop, session, gs)`; `_run_duration(args) -> float`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_led_smoke_cli.py`:

```python
"""CLI/plumbing tests for the led_smoke demo: the arg->duration mapping and a
headless pipeline build. The live server + real-clock loop in main() is covered
by manual acceptance, not here."""

from __future__ import annotations

import argparse

import pytest

pytest.importorskip("luxaeterna.backends.websim")

from bits.test_bit import RUN_DURATION_SECONDS
from control.state import State
from harness.led_smoke import _run_duration, build


def _args(seconds=None, hold=False):
    return argparse.Namespace(seconds=seconds, hold=hold)


def test_run_duration_hold_is_infinite():
    assert _run_duration(_args(hold=True)) == float("inf")


def test_run_duration_seconds_overrides():
    assert _run_duration(_args(seconds=12.0)) == 12.0


def test_run_duration_default_is_test_bit_natural():
    assert _run_duration(_args()) == RUN_DURATION_SECONDS


def test_build_constructs_headless_pipeline():
    loop, session, gs = build(run_duration=float("inf"), serve=False)
    assert isinstance(gs.state, State)           # a real GameServer wired up
    assert callable(session.render_into)         # luxaeterna session ready to render
    assert loop is not None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_led_smoke_cli.py -q`
Expected: FAIL at import — `ImportError: cannot import name '_run_duration' from 'harness.led_smoke'` (and `build`), because neither exists yet.

- [ ] **Step 3: Implement `build()`, `_run_duration()`, and the flags in `harness/led_smoke.py`**

Replace the module docstring, imports, and `main()` with:

```python
"""python -m harness.led_smoke — drive TestBit through the in-process stack and
watch it on the Web LED simulator.

Requires luxaeterna[websim] installed editable (see requirements-dev.txt):
    python -m pip install -e "/Users/chris/projects/luxaeterna[websim]"

By default the demo runs TestBit's natural ~2 s lifecycle then exits. To watch it
in a browser, keep it up longer:
    python -m harness.led_smoke --hold          # serve until Ctrl-C
    python -m harness.led_smoke --seconds 15    # sweep ~15 s, then complete + fade
    python -m harness.led_smoke --host 0.0.0.0 --port 9000
"""

from __future__ import annotations

import argparse
import time

from bits.test_bit import RUN_DURATION_SECONDS, TestBit
from control.engine import GameServer
from control.state import State
from harness.device_bridge import DeviceBridge
from luxaeterna.backends.websim import WebSimBackend
from luxaeterna.output import OutputLoop
from luxaeterna.synth.capability import shroom_capability
from luxaeterna.universe import Universe

HOST, PORT = "127.0.0.1", 8770


def build(run_duration: float, host: str = HOST, port: int = PORT,
          serve: bool = True, clock=time.monotonic):
    """Construct the demo pipeline WITHOUT starting the loop.

    Returns ``(loop, session, gs)``. ``run_duration`` is threaded into TestBit
    via a factory so the Bit's RUNNING window is caller-controlled
    (``float('inf')`` = never completes). ``serve=False`` gives a record-only
    backend (no websockets, no port) for headless tests."""
    gs = GameServer({"test_bit": lambda: TestBit(run_duration=run_duration)})
    cap = shroom_capability()
    bridge = DeviceBridge(capability=cap, clock=clock)
    gs.on_release = bridge.on_release
    gs.load_bit("test_bit")
    session = bridge.on_grant(gs.join("sim-dev", "TEST_PLAYER_NODE"))
    uni = Universe()
    backend = WebSimBackend(capability=cap, host=host, port=port, serve=serve)
    loop = OutputLoop(uni, backend, on_frame=session.render_into, always_send=True)
    return loop, session, gs


def _run_duration(args) -> float:
    if args.hold:
        return float("inf")
    return RUN_DURATION_SECONDS if args.seconds is None else args.seconds


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Watch TestBit render on the Web LED simulator.")
    ap.add_argument("--seconds", type=float, default=None,
                    help="Keep the Bit RUNNING/sweeping this long before it "
                         "completes + fades (default: TestBit's natural ~2 s).")
    ap.add_argument("--hold", action="store_true",
                    help="Serve until Ctrl-C (never auto-complete).")
    ap.add_argument("--host", default=HOST)
    ap.add_argument("--port", type=int, default=PORT)
    args = ap.parse_args()

    loop, session, gs = build(_run_duration(args), args.host, args.port)
    loop.start()
    print(f"Watch the Shroom at http://{args.host}:{args.port}/  (Ctrl-C to stop)")

    gs.run()
    try:
        while session.state != "running":
            time.sleep(0.02)
        cc = 0
        while gs.state == State.RUNNING:
            session.feed_midi(0xB0, 74, cc)          # cc:74 -> hue
            session.feed_midi(0x90, 60, 100)         # new voice at current hue
            cc = (cc + 8) % 128
            gs.tick(0.15)                            # advances TestBit toward complete
            time.sleep(0.15)
        time.sleep(1.2)                              # let the closing fade + idle play
    except KeyboardInterrupt:
        pass
    finally:
        loop.stop()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the CLI tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_led_smoke_cli.py -q`
Expected: `4 passed`

- [ ] **Step 5: Run the full mm-terrarium suite — the existing regression is untouched**

Run: `.venv/bin/python -m pytest tests -q`
Expected: all pass, 0 skipped. `tests/test_led_smoke.py` builds its pipeline manually (not via `main()`/`build()`), so it is unaffected by this refactor.

- [ ] **Step 6: Manual acceptance (the point of the change)**

Run: `.venv/bin/python -m harness.led_smoke --hold`, open `http://127.0.0.1:8770/`, confirm the ring + stem light and the hue sweeps continuously, then `Ctrl-C` (stops cleanly). Spot-check `--seconds 15` (runs ~15 s then fades) and no-flag (today's ~2 s one-shot). Note: if Phase B has merged, the welcome is now lit (glow) rather than dark — expected, not a regression.

- [ ] **Step 7: Commit**

```bash
git add harness/led_smoke.py tests/test_led_smoke_cli.py
git commit -m "feat(harness): --seconds/--hold viewing-duration flags for led_smoke demo"
```

---

## Self-Review (completed during authoring)

**Spec coverage** — every §-requirement of the glow spec maps to a task:
- §5.1 (promote `Fill`/`SegmentLevel`) → Task A1.
- §5.2 (`glow` instrument: full-field, `hue`, fade-in-hold, reject-unknown-param) → Task A2.
- §5.3 (TestBit welcome → `glow`; tighten smoke test) → Tasks B2, B1.
- §6 testing (`test_presets.py`; director `test_glow_welcome_renders_lit`; `test_status.py` stays green; smoke-test brightness assertion) → A2, A3, A1 step 6–7, B1/B2.
- §7 (alternatives) — no task needed (rejected approaches).
- §8 decisions — enforced by Global Constraints + task scopes.

**Phase C coverage** — the led_smoke handoff's acceptance criteria (§9) map to Task C1: `--hold`/`--seconds`/default → `_run_duration` + tests; `--host`/`--port` → argparse; deterministic mapping test + headless `build()` test → `tests/test_led_smoke_cli.py`; existing regression untouched → C1 step 5; docstring/README → C1 step 3 docstring; PR → C1 process note. `bits/test_bit.py` is **not** modified in Phase C (the `run_duration` param already exists) — so C touches disjoint files from B (`harness/led_smoke.py` + new CLI test vs `bits/test_bit.py` + `tests/test_led_smoke.py`), and the two PRs don't collide.

**Corrections applied** — Phase B was retargeted from the (now-merged) Slice-1 worktree to mm-terrarium `main` (PR mm-terrarium#6, HEAD `de2a6aa`, carries the harness + `bloom` welcome); the current `main` `tests/test_led_smoke.py` still has the `loading_frames > 10` workaround at lines 38–69, so B1's replacement is accurate.

**Placeholder scan** — none; every code step shows complete, paste-ready content.

**Type consistency** — `_make_glow(**params) -> LightInstrument` and the registry name `"glow"` are used identically in A2 (definition), A3 (director welcome), and B2 (TestBit welcome). `Fill(level, color)` / `SegmentLevel(points, loop_from=None)` signatures match their A1 source. `RenderContext(time, frame, dt, positions, n, channels)` matches `signal.py`. For Phase C: `build(run_duration, host, port, serve, clock)` and `_run_duration(args)` are defined and imported with matching names/signatures in C1's implementation and `tests/test_led_smoke_cli.py`; `DeviceBridge(capability, clock)`, `WebSimBackend(capability, host, port, serve)`, and `State` match the current `main` sources verified during authoring.
