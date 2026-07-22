# LightArco Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn `luxaeterna` from an output buffer into a local per-pixel light-synthesis engine ("LightArco") that resolves a Bit's `light_manifest` against a surface's capabilities and renders note/CC-driven Light Instruments at 44 Hz, proven end-to-end on the 12-LED Shroom.

**Architecture:** A new `luxaeterna/synth/` subpackage mirrors Arco's uGen/Instrument/Synth model in Python. Field-rate uGens output per-pixel numpy arrays; control-rate uGens output per-frame scalars. Instruments compose uGens; a Synth pools note-on voices. A resolver binds an abstract manifest to a concrete instrument + MIDI routing table against a capability descriptor. A `LightEngine` composites active bindings into the existing `Universe` via a new `on_frame` hook on `OutputLoop`; the existing backends transmit unchanged.

**Tech Stack:** Python ≥3.10, numpy (new core dep), pytest, o2lite (bridge only; decode is pure and unit-tested without it).

## Global Constraints

- Python ≥ 3.10 (matches `pyproject.toml`).
- `numpy` is a new **core** runtime dependency; add it to `pyproject.toml` `dependencies`.
- Follow existing `luxaeterna` style: `from __future__ import annotations`, module docstring `"""Lux Aeterna — ..."""`, dataclasses for records, focused files.
- **Internal color representation:** float in `[0.0, 1.0]`, canonical channel index `0=R, 1=G, 2=B, 3=W`. Conversion to `0..255` uint8 and to the surface's `color_order` happens only at the DMX boundary (`engine.py`).
- **MIDI packing (ratified wire format):** one int32 = `(status << 16) | (data1 << 8) | data2`.
- Frame clock is 44 Hz; the engine takes an injectable `clock` callable so tests are deterministic (never call real time in a test assertion path).
- Tests use a fake in-memory backend and synthetic O2 packets — **no hardware, no network**.
- All new code under `luxaeterna/synth/`; the transport layer (`universe.py`, `fixture.py`, `backends/`) is untouched except one additive hook on `output.py`.

---

### Task 1: Signal core (`LightUgen` base + `RenderContext`)

**Files:**
- Create: `luxaeterna/synth/__init__.py`
- Create: `luxaeterna/synth/signal.py`
- Modify: `pyproject.toml` (add `numpy` to `dependencies`)
- Test: `tests/synth/test_signal.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `RenderContext(time: float, frame: int, dt: float, positions: np.ndarray, n: int, channels: int)` (dataclass).
  - `class LightUgen` with attr `rate: str` (`"control"`|`"field"`), method `render(ctx) -> np.ndarray` (frame-memoized), and abstract `_compute(ctx) -> np.ndarray`.
  - `as_ugen(x) -> LightUgen` — returns `x` if a `LightUgen`, else wraps a scalar/array in a `_Literal` control uGen.

- [ ] **Step 1: Add numpy dependency**

Edit `pyproject.toml`, change the `dependencies` line:

```toml
dependencies = ["numpy>=1.24"]
```

- [ ] **Step 2: Write the failing test**

Create `tests/synth/test_signal.py`:

```python
import numpy as np
from luxaeterna.synth.signal import LightUgen, RenderContext, as_ugen


def _ctx(frame=0, n=4, channels=3, time=0.0, dt=1 / 44):
    return RenderContext(time=time, frame=frame, dt=dt,
                         positions=np.linspace(0, 1, n), n=n, channels=channels)


def test_render_is_memoized_per_frame():
    calls = []

    class Counter(LightUgen):
        rate = "control"
        def _compute(self, ctx):
            calls.append(ctx.frame)
            return np.asarray(1.0)

    u = Counter()
    ctx = _ctx(frame=5)
    u.render(ctx)
    u.render(ctx)                      # same frame → cached
    u.render(_ctx(frame=6))            # new frame → recompute
    assert calls == [5, 6]


def test_as_ugen_wraps_scalar():
    u = as_ugen(0.5)
    assert isinstance(u, LightUgen)
    assert float(u.render(_ctx())) == 0.5
    same = as_ugen(u)
    assert same is u
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/synth/test_signal.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'luxaeterna.synth'`

- [ ] **Step 4: Write minimal implementation**

Create `luxaeterna/synth/__init__.py`:

```python
"""Lux Aeterna — synth: the light-synthesis engine (the Arco-analog layer)."""
```

Create `luxaeterna/synth/signal.py`:

```python
"""Lux Aeterna — signal core: the LightUgen base and per-frame render context."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class RenderContext:
    """Everything a uGen needs to compute one frame.

    ``positions`` is normalized 0..1 across the *bound zone* (length ``n``);
    ``channels`` is the surface's colour width (3 = RGB, 4 = RGBW).
    """
    time: float
    frame: int
    dt: float
    positions: np.ndarray
    n: int
    channels: int


class LightUgen:
    """Base unit generator. Subclasses implement ``_compute``.

    ``render`` memoizes on ``ctx.frame`` so a node pulled by several consumers
    computes once per frame (the analog of Arco's ``run(block_count)`` trick).
    """

    rate: str = "control"  # "control" (per-frame scalar) | "field" (per-pixel array)

    def __init__(self) -> None:
        self._cache_frame: int = -1
        self._cache_val: np.ndarray | None = None

    def render(self, ctx: RenderContext) -> np.ndarray:
        if ctx.frame != self._cache_frame or self._cache_val is None:
            self._cache_val = self._compute(ctx)
            self._cache_frame = ctx.frame
        return self._cache_val

    def _compute(self, ctx: RenderContext) -> np.ndarray:
        raise NotImplementedError


class _Literal(LightUgen):
    """Wraps a constant scalar/array as a control-rate uGen."""

    rate = "control"

    def __init__(self, value) -> None:
        super().__init__()
        self._value = np.asarray(value, dtype=float)

    def _compute(self, ctx: RenderContext) -> np.ndarray:
        return self._value


def as_ugen(x) -> LightUgen:
    """Return ``x`` if it is a LightUgen, else wrap it in a ``_Literal``."""
    return x if isinstance(x, LightUgen) else _Literal(x)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/synth/test_signal.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml luxaeterna/synth/__init__.py luxaeterna/synth/signal.py tests/synth/test_signal.py
git commit -m "feat(synth): LightUgen base, RenderContext, numpy dep"
```

---

### Task 2: Control-rate uGens

**Files:**
- Create: `luxaeterna/synth/ugens.py`
- Test: `tests/synth/test_control_ugens.py`

**Interfaces:**
- Consumes: `LightUgen`, `RenderContext`, `as_ugen` (Task 1).
- Produces (all `rate="control"`, `_compute` returns a 0-d or 1-d `np.ndarray`):
  - `Const(value)` — `.set_target(value)` replaces the value.
  - `Smooth(source, tau)` — one-pole glide; `.set_target(value)` retargets its source when the source is a `Const` (else glides toward the source's rendered value).
  - `LFO(shape: str, hz: float, phase: float = 0.0)` — `shape in {"sine","tri","saw","square"}`, output 0..1.
  - `Envelope(attack, decay, sustain, release)` — `.gate_on()`, `.gate_off()`, `.done: bool`, output 0..1.
  - `CCReader(initial=0.0)` — `.set_target(value)` sets the latest CC value (already normalized 0..1).
  - `NoteTrigger()` — `.fire(pitch, vel)`; output = `vel` for the single frame after `fire`, else 0.

- [ ] **Step 1: Write the failing test**

Create `tests/synth/test_control_ugens.py`:

```python
import numpy as np
from luxaeterna.synth.signal import RenderContext
from luxaeterna.synth.ugens import Const, Smooth, LFO, Envelope, CCReader, NoteTrigger


def ctx(frame, time=0.0, dt=1 / 44, n=4, channels=3):
    return RenderContext(time, frame, dt, np.linspace(0, 1, n), n, channels)


def test_const_set_target():
    c = Const(0.2)
    assert float(c.render(ctx(0))) == 0.2
    c.set_target(0.8)
    assert float(c.render(ctx(1))) == 0.8


def test_smooth_glides_toward_target():
    s = Smooth(Const(0.0), tau=0.1)
    assert float(s.render(ctx(0))) == 0.0
    s.set_target(1.0)
    v1 = float(s.render(ctx(1, time=1 / 44)))
    v2 = float(s.render(ctx(2, time=2 / 44)))
    assert 0.0 < v1 < v2 < 1.0            # monotonic approach, not yet arrived


def test_lfo_sine_range_and_phase():
    lfo = LFO("sine", hz=1.0)
    lo = float(lfo.render(ctx(0, time=0.0)))       # sin(0) -> 0.5
    hi = float(lfo.render(ctx(1, time=0.25)))      # sin(pi/2) -> 1.0
    assert abs(lo - 0.5) < 1e-6
    assert abs(hi - 1.0) < 1e-6


def test_envelope_attacks_then_finishes_after_release():
    e = Envelope(attack=0.1, decay=0.0, sustain=1.0, release=0.1)
    e.gate_on()
    assert float(e.render(ctx(0, dt=0.05))) > 0.0
    _ = e.render(ctx(1, dt=0.1))                   # reach sustain ~1.0
    e.gate_off()
    e.render(ctx(2, dt=0.05))
    e.render(ctx(3, dt=0.1))                       # release elapsed
    assert e.done


def test_ccreader_holds_latest():
    cc = CCReader()
    cc.set_target(0.6)
    assert float(cc.render(ctx(0))) == 0.6


def test_note_trigger_is_one_shot():
    t = NoteTrigger()
    t.fire(pitch=60, vel=0.9)
    assert float(t.render(ctx(0))) == 0.9
    assert float(t.render(ctx(1))) == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/synth/test_control_ugens.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'luxaeterna.synth.ugens'`

- [ ] **Step 3: Write minimal implementation**

Create `luxaeterna/synth/ugens.py`:

```python
"""Lux Aeterna — the light-uGen vocabulary (control-rate primitives here;
field-rate primitives appended in a later task)."""

from __future__ import annotations

import math

import numpy as np

from .signal import LightUgen, RenderContext, as_ugen


class Const(LightUgen):
    rate = "control"

    def __init__(self, value) -> None:
        super().__init__()
        self._value = np.asarray(value, dtype=float)

    def set_target(self, value) -> None:
        self._value = np.asarray(value, dtype=float)
        self._cache_frame = -1  # invalidate memo

    def _compute(self, ctx: RenderContext) -> np.ndarray:
        return self._value


class Smooth(LightUgen):
    """One-pole glide toward the source value (Arco's Smoothb analog)."""

    rate = "control"

    def __init__(self, source, tau: float) -> None:
        super().__init__()
        self._source = as_ugen(source)
        self._tau = float(tau)
        self._prev: np.ndarray | None = None

    def set_target(self, value) -> None:
        if isinstance(self._source, Const):
            self._source.set_target(value)

    def _compute(self, ctx: RenderContext) -> np.ndarray:
        target = np.asarray(self._source.render(ctx), dtype=float)
        if self._prev is None:
            self._prev = target
        else:
            alpha = 1.0 if self._tau <= 0 else 1.0 - math.exp(-ctx.dt / self._tau)
            self._prev = self._prev + alpha * (target - self._prev)
        return self._prev


class LFO(LightUgen):
    rate = "control"

    def __init__(self, shape: str, hz: float, phase: float = 0.0) -> None:
        super().__init__()
        self._shape = shape
        self._hz = float(hz)
        self._phase = float(phase)

    def _compute(self, ctx: RenderContext) -> np.ndarray:
        p = (self._hz * ctx.time + self._phase) % 1.0
        if self._shape == "sine":
            v = 0.5 + 0.5 * math.sin(2 * math.pi * p)
        elif self._shape == "tri":
            v = 1.0 - abs(2.0 * p - 1.0)
        elif self._shape == "saw":
            v = p
        elif self._shape == "square":
            v = 1.0 if p < 0.5 else 0.0
        else:
            raise ValueError(f"unknown LFO shape {self._shape!r}")
        return np.asarray(v)


class Envelope(LightUgen):
    """Gated ADSR. ``gate_on`` starts A→D→S; ``gate_off`` starts R; ``done``
    is True once release has fully elapsed."""

    rate = "control"

    def __init__(self, attack: float, decay: float, sustain: float, release: float) -> None:
        super().__init__()
        self._a, self._d, self._s, self._r = map(float, (attack, decay, sustain, release))
        self._stage = "idle"   # idle|attack|decay|sustain|release|done
        self._level = 0.0
        self._t = 0.0          # seconds in current stage

    def gate_on(self) -> None:
        self._stage = "attack"
        self._t = 0.0

    def gate_off(self) -> None:
        if self._stage not in ("idle", "done"):
            self._stage = "release"
            self._t = 0.0
            self._rel_from = self._level

    @property
    def done(self) -> bool:
        return self._stage == "done"

    def _compute(self, ctx: RenderContext) -> np.ndarray:
        self._t += ctx.dt
        if self._stage == "attack":
            self._level = 1.0 if self._a <= 0 else min(1.0, self._t / self._a)
            if self._level >= 1.0:
                self._stage, self._t = "decay", 0.0
        elif self._stage == "decay":
            frac = 1.0 if self._d <= 0 else min(1.0, self._t / self._d)
            self._level = 1.0 + frac * (self._s - 1.0)
            if frac >= 1.0:
                self._stage = "sustain"
        elif self._stage == "sustain":
            self._level = self._s
        elif self._stage == "release":
            frac = 1.0 if self._r <= 0 else min(1.0, self._t / self._r)
            self._level = self._rel_from * (1.0 - frac)
            if frac >= 1.0:
                self._stage, self._level = "done", 0.0
        return np.asarray(self._level)


class CCReader(LightUgen):
    rate = "control"

    def __init__(self, initial: float = 0.0) -> None:
        super().__init__()
        self._value = float(initial)

    def set_target(self, value) -> None:
        self._value = float(value)
        self._cache_frame = -1

    def _compute(self, ctx: RenderContext) -> np.ndarray:
        return np.asarray(self._value)


class NoteTrigger(LightUgen):
    """One-shot: outputs ``vel`` on the frame after ``fire``, then 0."""

    rate = "control"

    def __init__(self) -> None:
        super().__init__()
        self._pending: float | None = None
        self._value = 0.0

    def fire(self, pitch: int, vel: float) -> None:
        self._pending = float(vel)
        self._cache_frame = -1

    def _compute(self, ctx: RenderContext) -> np.ndarray:
        if self._pending is not None:
            self._value, self._pending = self._pending, None
        else:
            self._value = 0.0
        return np.asarray(self._value)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/synth/test_control_ugens.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add luxaeterna/synth/ugens.py tests/synth/test_control_ugens.py
git commit -m "feat(synth): control-rate uGens (Const, Smooth, LFO, Envelope, CCReader, NoteTrigger)"
```

---

### Task 3: Field-rate uGens

**Files:**
- Modify: `luxaeterna/synth/ugens.py` (append)
- Test: `tests/synth/test_field_ugens.py`

**Interfaces:**
- Consumes: Task 1 + Task 2 symbols.
- Produces (all `rate="field"`, `_compute` returns shape `(ctx.n, ctx.channels)` float 0..1):
  - `SolidColor(color)` — `color` is a control uGen/array of length `channels`.
  - `Gradient(stops)` — `stops: list[tuple[float, sequence]]` (position, color); linear interp across `ctx.positions`.
  - `PaletteMap(index, palette)` — `index` control uGen 0..1; `palette` an `(M, channels)` array; uniform output at the sampled colour.
  - `Bloom(level, color, center=0.5)` — `level` control 0..1; `color` control length `channels`; Gaussian bloom around `center` widening with `level`.
  - `Noise(color, scale, speed)` — `color` control; sinusoidal spatial noise modulating brightness.

- [ ] **Step 1: Write the failing test**

Create `tests/synth/test_field_ugens.py`:

```python
import numpy as np
from luxaeterna.synth.signal import RenderContext
from luxaeterna.synth.ugens import (Const, Envelope, SolidColor, Gradient,
                                     PaletteMap, Bloom, Noise)


def ctx(frame=0, n=8, channels=3, time=0.0, dt=1 / 44):
    return RenderContext(time, frame, dt, np.linspace(0, 1, n), n, channels)


def test_solid_color_broadcasts():
    out = SolidColor(Const([1.0, 0.0, 0.5])).render(ctx(n=4))
    assert out.shape == (4, 3)
    assert np.allclose(out[0], [1.0, 0.0, 0.5])
    assert np.allclose(out[3], [1.0, 0.0, 0.5])


def test_gradient_endpoints():
    g = Gradient([(0.0, [0, 0, 0]), (1.0, [1, 1, 1])])
    out = g.render(ctx(n=3))                 # positions 0, 0.5, 1
    assert np.allclose(out[0], [0, 0, 0])
    assert np.allclose(out[1], [0.5, 0.5, 0.5])
    assert np.allclose(out[2], [1, 1, 1])


def test_palette_map_samples():
    pal = np.array([[0, 0, 0], [1, 0, 0]], dtype=float)
    out = PaletteMap(Const(1.0), pal).render(ctx(n=2))
    assert np.allclose(out[0], [1, 0, 0])


def test_bloom_peaks_at_center_and_scales_with_level():
    env = Const(1.0)
    b = Bloom(level=env, color=Const([1, 1, 1]), center=0.5)
    out = b.render(ctx(n=9))                 # center index 4
    assert out[4, 0] >= out[0, 0]            # brighter at centre than edge
    dark = Bloom(level=Const(0.0), color=Const([1, 1, 1]), center=0.5).render(ctx(n=9))
    assert np.allclose(dark, 0.0)            # zero level -> dark


def test_noise_is_bounded():
    out = Noise(Const([1, 1, 1]), scale=3.0, speed=1.0).render(ctx(n=16))
    assert out.shape == (16, 3)
    assert out.min() >= 0.0 and out.max() <= 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/synth/test_field_ugens.py -v`
Expected: FAIL with `ImportError: cannot import name 'SolidColor'`

- [ ] **Step 3: Write minimal implementation**

Append to `luxaeterna/synth/ugens.py`:

```python
def _broadcast_color(color_val: np.ndarray, n: int, channels: int) -> np.ndarray:
    c = np.asarray(color_val, dtype=float).reshape(-1)
    if c.shape[0] < channels:        # pad (e.g. RGB color on RGBW surface)
        c = np.concatenate([c, np.zeros(channels - c.shape[0])])
    return np.tile(c[:channels], (n, 1))


class SolidColor(LightUgen):
    rate = "field"

    def __init__(self, color) -> None:
        super().__init__()
        self._color = as_ugen(color)

    def _compute(self, ctx: RenderContext) -> np.ndarray:
        return _broadcast_color(self._color.render(ctx), ctx.n, ctx.channels)


class Gradient(LightUgen):
    rate = "field"

    def __init__(self, stops) -> None:
        super().__init__()
        self._pos = np.asarray([s[0] for s in stops], dtype=float)
        self._cols = np.asarray([s[1] for s in stops], dtype=float)

    def _compute(self, ctx: RenderContext) -> np.ndarray:
        out = np.empty((ctx.n, ctx.channels))
        for ch in range(ctx.channels):
            col = self._cols[:, ch] if ch < self._cols.shape[1] else np.zeros(len(self._pos))
            out[:, ch] = np.interp(ctx.positions, self._pos, col)
        return out


class PaletteMap(LightUgen):
    rate = "field"

    def __init__(self, index, palette) -> None:
        super().__init__()
        self._index = as_ugen(index)
        self._palette = np.asarray(palette, dtype=float)

    def _compute(self, ctx: RenderContext) -> np.ndarray:
        idx = float(np.asarray(self._index.render(ctx)))
        m = self._palette.shape[0]
        pos = np.clip(idx, 0.0, 1.0) * (m - 1)
        lo, hi = int(np.floor(pos)), min(int(np.ceil(pos)), m - 1)
        frac = pos - lo
        color = self._palette[lo] * (1 - frac) + self._palette[hi] * frac
        return _broadcast_color(color, ctx.n, ctx.channels)


class Bloom(LightUgen):
    """Gaussian bloom around ``center`` that widens and brightens with ``level``."""

    rate = "field"

    def __init__(self, level, color, center: float = 0.5) -> None:
        super().__init__()
        self._level = as_ugen(level)
        self._color = as_ugen(color)
        self._center = float(center)

    def _compute(self, ctx: RenderContext) -> np.ndarray:
        level = float(np.asarray(self._level.render(ctx)))
        color = np.asarray(self._color.render(ctx), dtype=float).reshape(-1)[:ctx.channels]
        width = 0.08 + 0.5 * level
        falloff = np.exp(-((ctx.positions - self._center) / width) ** 2)
        intensity = np.clip(level * falloff, 0.0, 1.0)
        return intensity[:, None] * color[None, :]


class Noise(LightUgen):
    rate = "field"

    def __init__(self, color, scale: float, speed: float) -> None:
        super().__init__()
        self._color = as_ugen(color)
        self._scale = float(scale)
        self._speed = float(speed)

    def _compute(self, ctx: RenderContext) -> np.ndarray:
        phase = ctx.positions * self._scale + ctx.time * self._speed
        intensity = 0.5 + 0.5 * np.sin(2 * np.pi * phase)
        color = np.asarray(self._color.render(ctx), dtype=float).reshape(-1)[:ctx.channels]
        return np.clip(intensity[:, None] * color[None, :], 0.0, 1.0)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/synth/test_field_ugens.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add luxaeterna/synth/ugens.py tests/synth/test_field_ugens.py
git commit -m "feat(synth): field-rate uGens (SolidColor, Gradient, PaletteMap, Bloom, Noise)"
```

---

### Task 4: `Param` + `LightInstrument`

**Files:**
- Create: `luxaeterna/synth/instrument.py`
- Test: `tests/synth/test_instrument.py`

**Interfaces:**
- Consumes: `LightUgen`, `RenderContext`, `Const`, `Smooth`.
- Produces:
  - `Param(name: str, ugen)` — `.set(value)` calls `ugen.set_target(value)`.
  - `LightInstrument(output: LightUgen, params: dict[str, Param])` — `.set(name, value)`, `.render(ctx) -> np.ndarray`.

- [ ] **Step 1: Write the failing test**

Create `tests/synth/test_instrument.py`:

```python
import numpy as np
from luxaeterna.synth.signal import RenderContext
from luxaeterna.synth.ugens import Const, SolidColor
from luxaeterna.synth.instrument import Param, LightInstrument


def ctx(frame=0, n=3, channels=3):
    return RenderContext(0.0, frame, 1 / 44, np.linspace(0, 1, n), n, channels)


def test_instrument_set_param_changes_output():
    color = Const([0.0, 0.0, 0.0])
    inst = LightInstrument(SolidColor(color), {"color": Param("color", color)})
    assert np.allclose(inst.render(ctx(0))[0], [0, 0, 0])
    inst.set("color", [1.0, 0.0, 0.0])
    assert np.allclose(inst.render(ctx(1))[0], [1, 0, 0])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/synth/test_instrument.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'luxaeterna.synth.instrument'`

- [ ] **Step 3: Write minimal implementation**

Create `luxaeterna/synth/instrument.py`:

```python
"""Lux Aeterna — Instrument/Synth layer (client-side composition, mirroring
pyarco's arco_instr.py)."""

from __future__ import annotations

import numpy as np

from .signal import LightUgen, RenderContext


class Param:
    """A named, settable binding backed by a Const/Smooth control uGen."""

    __slots__ = ("name", "ugen")

    def __init__(self, name: str, ugen) -> None:
        self.name = name
        self.ugen = ugen

    def set(self, value) -> None:
        self.ugen.set_target(value)


class LightInstrument:
    """A graph with a designated output field-uGen and named params."""

    def __init__(self, output: LightUgen, params: dict[str, Param]) -> None:
        self.output = output
        self.params = params

    def set(self, name: str, value) -> None:
        if name not in self.params:
            raise KeyError(f"no param {name!r} on instrument")
        self.params[name].set(value)

    def render(self, ctx: RenderContext) -> np.ndarray:
        return self.output.render(ctx)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/synth/test_instrument.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add luxaeterna/synth/instrument.py tests/synth/test_instrument.py
git commit -m "feat(synth): Param and LightInstrument"
```

---

### Task 5: `LightSynth` (voice pool) + registry + `bloom` preset

**Files:**
- Modify: `luxaeterna/synth/instrument.py` (append `LightSynth`)
- Create: `luxaeterna/synth/registry.py`
- Create: `luxaeterna/synth/presets.py`
- Test: `tests/synth/test_synth.py`

**Interfaces:**
- Consumes: Task 2/3/4 symbols.
- Produces:
  - `LightSynth(voice_factory, max_voices=8, shared=None)` — `voice_factory(pitch, vel, shared) -> (LightInstrument, Envelope)`; methods `.noteon(pitch, vel, note_id=None)`, `.noteoff(note_id)`, `.set(name, value)` (writes `shared[name]`), `.render(ctx) -> np.ndarray` (additively composites live voices, prunes finished).
  - `registry.register(name, factory)`, `registry.build(name, **params)`.
  - `presets` registers `"bloom"` → a `LightSynth` of Bloom voices; `.set("hue", 0..1)` recolors future voices; `hsv_to_rgb(h, s, v) -> np.ndarray`.

- [ ] **Step 1: Write the failing test**

Create `tests/synth/test_synth.py`:

```python
import numpy as np
from luxaeterna.synth.signal import RenderContext
from luxaeterna.synth import registry, presets  # noqa: F401  (import registers presets)


def ctx(frame, dt=1 / 44, n=8, channels=3, time=0.0):
    return RenderContext(time, frame, dt, np.linspace(0, 1, n), n, channels)


def test_noteon_produces_light_then_fades_after_noteoff():
    synth = registry.build("bloom")
    synth.noteon(pitch=60, vel=1.0, note_id=1)
    frame0 = synth.render(ctx(0, dt=0.05))
    assert frame0.max() > 0.0                       # note-on lit something
    synth.noteoff(1)
    for f in range(1, 40):                           # advance well past release
        synth.render(ctx(f, dt=0.05, time=f * 0.05))
    assert synth.render(ctx(40, dt=0.05)).max() == 0.0
    assert len(synth.voices) == 0                    # voice pruned


def test_hue_set_recolors_new_voice():
    synth = registry.build("bloom")
    synth.set("hue", 0.0)                             # red
    synth.noteon(60, 1.0, note_id=1)
    red = synth.render(ctx(0, dt=0.01))
    assert red[:, 0].max() > red[:, 1].max()         # more red than green
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/synth/test_synth.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'luxaeterna.synth.registry'`

- [ ] **Step 3: Write minimal implementation**

Append to `luxaeterna/synth/instrument.py`:

```python
class LightSynth:
    """A voice pool: note-on spawns a transient voice instrument, additively
    composited and pruned when its envelope finishes (Arco Synth analog)."""

    def __init__(self, voice_factory, max_voices: int = 8, shared: dict | None = None) -> None:
        self.voice_factory = voice_factory
        self.max_voices = max_voices
        self.shared = shared if shared is not None else {}
        self.voices: dict = {}       # note_id -> (LightInstrument, Envelope)
        self._auto = 0

    def noteon(self, pitch: int, vel: float, note_id=None):
        if note_id is None:
            note_id = ("auto", self._auto)
            self._auto += 1
        if len(self.voices) >= self.max_voices:
            self.voices.pop(next(iter(self.voices)))       # drop oldest
        inst, env = self.voice_factory(pitch, vel, self.shared)
        env.gate_on()
        self.voices[note_id] = (inst, env)
        return note_id

    def noteoff(self, note_id):
        v = self.voices.get(note_id)
        if v is not None:
            v[1].gate_off()

    def set(self, name: str, value) -> None:
        self.shared[name] = value

    def render(self, ctx: RenderContext) -> np.ndarray:
        out = np.zeros((ctx.n, ctx.channels))
        finished = []
        for note_id, (inst, env) in self.voices.items():
            out = out + inst.render(ctx)
            if env.done:
                finished.append(note_id)
        for note_id in finished:
            del self.voices[note_id]
        return np.clip(out, 0.0, 1.0)
```

Create `luxaeterna/synth/registry.py`:

```python
"""Lux Aeterna — instrument-type registry (name -> factory)."""

from __future__ import annotations

_REGISTRY: dict = {}


def register(name: str, factory) -> None:
    _REGISTRY[name] = factory


def build(name: str, **params):
    if name not in _REGISTRY:
        raise KeyError(f"unknown instrument type {name!r}")
    return _REGISTRY[name](**params)
```

Create `luxaeterna/synth/presets.py`:

```python
"""Lux Aeterna — built-in instrument presets, registered by name."""

from __future__ import annotations

import colorsys

import numpy as np

from . import registry
from .ugens import Const, Envelope, Bloom
from .instrument import LightInstrument, LightSynth


def hsv_to_rgb(h: float, s: float, v: float) -> np.ndarray:
    return np.asarray(colorsys.hsv_to_rgb(h % 1.0, s, v), dtype=float)


def _bloom_voice(pitch: int, vel: float, shared: dict):
    hue = float(shared.get("hue", 0.0))
    color = hsv_to_rgb(hue, 1.0, 1.0) * vel
    center = (pitch % 12) / 11.0
    env = Envelope(attack=0.04, decay=0.12, sustain=0.6, release=0.4)
    out = Bloom(level=env, color=Const(color), center=center)
    return LightInstrument(out, {}), env


def _make_bloom(**params) -> LightSynth:
    return LightSynth(voice_factory=_bloom_voice, max_voices=8,
                      shared={"hue": params.get("hue", 0.0)})


registry.register("bloom", _make_bloom)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/synth/test_synth.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add luxaeterna/synth/instrument.py luxaeterna/synth/registry.py luxaeterna/synth/presets.py tests/synth/test_synth.py
git commit -m "feat(synth): LightSynth voice pool, registry, bloom preset"
```

---

### Task 6: `light_manifest` schema

**Files:**
- Create: `luxaeterna/synth/manifest.py`
- Test: `tests/synth/test_manifest.py`

**Interfaces:**
- Consumes: nothing (pure data).
- Produces:
  - `LightLane(source: str, dest: str, curve: str = "linear")`
  - `LightInstrumentDecl(instrument: str, target: str, params: dict = {}, lanes: list[LightLane] = [])`
  - `LightManifest(instruments: list[LightInstrumentDecl])` with `@classmethod from_dict(d) -> LightManifest`.

- [ ] **Step 1: Write the failing test**

Create `tests/synth/test_manifest.py`:

```python
from luxaeterna.synth.manifest import LightManifest, LightInstrumentDecl, LightLane


def test_from_dict_round_trips_a_bloom_lane():
    m = LightManifest.from_dict({
        "instruments": [{
            "instrument": "bloom",
            "target": "primary",
            "params": {"hue": 0.3},
            "lanes": [
                {"source": "note", "dest": "trigger"},
                {"source": "cc:74", "dest": "hue", "curve": "exp"},
            ],
        }]
    })
    assert isinstance(m, LightManifest)
    decl = m.instruments[0]
    assert isinstance(decl, LightInstrumentDecl)
    assert decl.instrument == "bloom" and decl.target == "primary"
    assert decl.params == {"hue": 0.3}
    assert decl.lanes[1] == LightLane("cc:74", "hue", "exp")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/synth/test_manifest.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'luxaeterna.synth.manifest'`

- [ ] **Step 3: Write minimal implementation**

Create `luxaeterna/synth/manifest.py`:

```python
"""Lux Aeterna — the light_manifest contract (what a Bit's Role declares)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class LightLane:
    source: str                 # "note" | "cc:<n>" | "sensor:<name>" (sensor deferred)
    dest: str                   # instrument param / "trigger"
    curve: str = "linear"       # "linear" | "exp"


@dataclass
class LightInstrumentDecl:
    instrument: str             # registered type name, e.g. "bloom"
    target: str                 # abstract zone, e.g. "primary" | "ring" | "stem"
    params: dict = field(default_factory=dict)
    lanes: list[LightLane] = field(default_factory=list)


@dataclass
class LightManifest:
    instruments: list[LightInstrumentDecl] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "LightManifest":
        return cls(instruments=[
            LightInstrumentDecl(
                instrument=i["instrument"],
                target=i["target"],
                params=dict(i.get("params", {})),
                lanes=[LightLane(l["source"], l["dest"], l.get("curve", "linear"))
                       for l in i.get("lanes", [])],
            )
            for i in d.get("instruments", [])
        ])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/synth/test_manifest.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add luxaeterna/synth/manifest.py tests/synth/test_manifest.py
git commit -m "feat(synth): light_manifest schema + from_dict"
```

---

### Task 7: Capability descriptor + registry

**Files:**
- Create: `luxaeterna/synth/capability.py`
- Test: `tests/synth/test_capability.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `Zone(name: str, start: int, count: int)`
  - `SurfaceCapability(surface_id: str, pixel_count: int, color_order: str, zones: list[Zone])` with `.zone(name) -> Zone` (`"primary"` synthesized as whole surface if absent).
  - `CapabilityRegistry` with `.register(cap)`, `.get(surface_id) -> SurfaceCapability`, `.load_config(dict)` (merge fixed-infra surfaces).
  - `shroom_capability(surface_id="ie0") -> SurfaceCapability` — the canonical 12-LED descriptor.

- [ ] **Step 1: Write the failing test**

Create `tests/synth/test_capability.py`:

```python
import pytest
from luxaeterna.synth.capability import (Zone, SurfaceCapability,
                                         CapabilityRegistry, shroom_capability)


def test_zone_lookup_and_primary_default():
    cap = SurfaceCapability("ie3", 12, "GRB",
                            [Zone("ring", 0, 8), Zone("stem", 8, 4)])
    assert cap.zone("ring") == Zone("ring", 0, 8)
    assert cap.zone("primary") == Zone("primary", 0, 12)   # synthesized
    with pytest.raises(KeyError):
        cap.zone("nope")


def test_registry_register_get_and_config_merge():
    reg = CapabilityRegistry()
    reg.register(shroom_capability("ie3"))
    assert reg.get("ie3").pixel_count == 12
    reg.load_config({"surfaces": [
        {"surface_id": "array", "pixel_count": 300, "color_order": "GRB",
         "zones": [{"name": "primary", "start": 0, "count": 300}]}]})
    assert reg.get("array").pixel_count == 300
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/synth/test_capability.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'luxaeterna.synth.capability'`

- [ ] **Step 3: Write minimal implementation**

Create `luxaeterna/synth/capability.py`:

```python
"""Lux Aeterna — surface capability descriptors + registry (self-describe ⊕ config)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Zone:
    name: str
    start: int
    count: int


@dataclass
class SurfaceCapability:
    surface_id: str
    pixel_count: int
    color_order: str
    zones: list[Zone]

    def zone(self, name: str) -> Zone:
        for z in self.zones:
            if z.name == name:
                return z
        if name == "primary":
            return Zone("primary", 0, self.pixel_count)
        raise KeyError(f"surface {self.surface_id!r} has no zone {name!r}")


class CapabilityRegistry:
    def __init__(self) -> None:
        self._surfaces: dict[str, SurfaceCapability] = {}

    def register(self, cap: SurfaceCapability) -> None:
        self._surfaces[cap.surface_id] = cap

    def get(self, surface_id: str) -> SurfaceCapability:
        if surface_id not in self._surfaces:
            raise KeyError(f"unknown surface {surface_id!r}")
        return self._surfaces[surface_id]

    def load_config(self, config: dict) -> None:
        for s in config.get("surfaces", []):
            self.register(SurfaceCapability(
                surface_id=s["surface_id"],
                pixel_count=s["pixel_count"],
                color_order=s["color_order"],
                zones=[Zone(z["name"], z["start"], z["count"]) for z in s.get("zones", [])],
            ))


def shroom_capability(surface_id: str = "ie0") -> SurfaceCapability:
    """The canonical 12-LED Shroom: 8-LED ring + 4-LED stem, GRB."""
    return SurfaceCapability(
        surface_id=surface_id, pixel_count=12, color_order="GRB",
        zones=[Zone("ring", 0, 8), Zone("stem", 8, 4), Zone("primary", 0, 12)],
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/synth/test_capability.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add luxaeterna/synth/capability.py tests/synth/test_capability.py
git commit -m "feat(synth): capability descriptor + registry"
```

---

### Task 8: Resolver / binding

**Files:**
- Create: `luxaeterna/synth/binding.py`
- Test: `tests/synth/test_binding.py`

**Interfaces:**
- Consumes: `LightInstrumentDecl` (Task 6), `SurfaceCapability`/`Zone` (Task 7), `registry.build` (Task 5).
- Produces:
  - `ActiveBinding(obj, zone: Zone, blend: str, routes: dict[str, Callable])` with `.render(ctx)`.
  - `resolve(decl: LightInstrumentDecl, cap: SurfaceCapability) -> ActiveBinding`.
  - `apply_curve(curve: str, value: float) -> float` (`"linear"` → v, `"exp"` → v*v).
  - Route keys: `"note"` → `obj.noteon(pitch, vel)`; `"cc:<n>"` → `lambda value: obj.set(dest, apply_curve(curve, value))`.

- [ ] **Step 1: Write the failing test**

Create `tests/synth/test_binding.py`:

```python
import numpy as np
from luxaeterna.synth.manifest import LightInstrumentDecl, LightLane
from luxaeterna.synth.capability import shroom_capability
from luxaeterna.synth.binding import resolve, apply_curve
from luxaeterna.synth.signal import RenderContext


def test_apply_curve():
    assert apply_curve("linear", 0.5) == 0.5
    assert apply_curve("exp", 0.5) == 0.25


def test_resolve_binds_zone_and_routes():
    decl = LightInstrumentDecl(
        instrument="bloom", target="ring", params={},
        lanes=[LightLane("note", "trigger"), LightLane("cc:74", "hue")])
    binding = resolve(decl, shroom_capability("ie3"))
    assert binding.zone.name == "ring" and binding.zone.count == 8
    assert "note" in binding.routes and "cc:74" in binding.routes

    # cc route sets shared hue; note route spawns a voice that lights up
    binding.routes["cc:74"](0.0)                       # red
    binding.routes["note"](60, 1.0)
    ctx = RenderContext(0.0, 0, 0.01, np.linspace(0, 1, 8), 8, 3)
    out = binding.render(ctx)
    assert out.max() > 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/synth/test_binding.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'luxaeterna.synth.binding'`

- [ ] **Step 3: Write minimal implementation**

Create `luxaeterna/synth/binding.py`:

```python
"""Lux Aeterna — late resolution: manifest declaration + capability -> active binding."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np

from . import registry, presets  # noqa: F401  (import registers built-in presets)
from .capability import SurfaceCapability, Zone
from .manifest import LightInstrumentDecl
from .signal import RenderContext


def apply_curve(curve: str, value: float) -> float:
    if curve == "linear":
        return value
    if curve == "exp":
        return value * value
    raise ValueError(f"unknown curve {curve!r}")


@dataclass
class ActiveBinding:
    obj: object                       # LightInstrument | LightSynth
    zone: Zone
    blend: str
    routes: dict[str, Callable]

    def render(self, ctx: RenderContext) -> np.ndarray:
        return self.obj.render(ctx)


def resolve(decl: LightInstrumentDecl, cap: SurfaceCapability) -> ActiveBinding:
    zone = cap.zone(decl.target)
    obj = registry.build(decl.instrument, **decl.params)
    blend = decl.params.get("blend", "add")

    routes: dict[str, Callable] = {}
    for lane in decl.lanes:
        if lane.source == "note":
            routes["note"] = lambda pitch, vel: obj.noteon(pitch, vel)
        elif lane.source.startswith("cc:"):
            routes[lane.source] = (
                lambda value, dest=lane.dest, curve=lane.curve:
                obj.set(dest, apply_curve(curve, value)))
        # sensor:* sources are deferred (v1)

    return ActiveBinding(obj=obj, zone=zone, blend=blend, routes=routes)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/synth/test_binding.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add luxaeterna/synth/binding.py tests/synth/test_binding.py
git commit -m "feat(synth): resolver binding manifest+capability -> instrument+routes"
```

---

### Task 9: O2 bridge (MIDI decode + dispatch)

**Files:**
- Create: `luxaeterna/synth/o2bridge.py`
- Test: `tests/synth/test_o2bridge.py`

**Interfaces:**
- Consumes: `ActiveBinding` (Task 8).
- Produces:
  - `decode_midi(packed: int) -> tuple[int, int, int]` — `(status, data1, data2)` from `(status<<16)|(d1<<8)|d2`.
  - `dispatch_midi(bindings: list[ActiveBinding], status: int, d1: int, d2: int) -> None` — note-on (`0x90`, vel>0) → each binding's `"note"` route with `(pitch, vel/127)`; note-off (`0x80`, or `0x90` vel 0) → `noteoff` best-effort; CC (`0xB0`) → `"cc:<d1>"` route with `d2/127`.
  - `O2Bridge(bindings)` with `.on_midi(packed: int)` (decodes then dispatches). o2lite subscription is a thin `.attach(o2lite_client, address)` documented but not unit-tested.

- [ ] **Step 1: Write the failing test**

Create `tests/synth/test_o2bridge.py`:

```python
import numpy as np
from luxaeterna.synth.manifest import LightInstrumentDecl, LightLane
from luxaeterna.synth.capability import shroom_capability
from luxaeterna.synth.binding import resolve
from luxaeterna.synth.o2bridge import decode_midi, O2Bridge
from luxaeterna.synth.signal import RenderContext


def test_decode_midi_packing():
    packed = (0x90 << 16) | (60 << 8) | 100
    assert decode_midi(packed) == (0x90, 60, 100)


def test_bridge_note_on_lights_binding():
    decl = LightInstrumentDecl("bloom", "primary", {},
                               [LightLane("note", "trigger"), LightLane("cc:74", "hue")])
    binding = resolve(decl, shroom_capability("ie3"))
    bridge = O2Bridge([binding])

    bridge.on_midi((0xB0 << 16) | (74 << 8) | 0)       # CC74 = 0 -> red hue
    bridge.on_midi((0x90 << 16) | (60 << 8) | 127)     # note-on
    ctx = RenderContext(0.0, 0, 0.01, np.linspace(0, 1, 12), 12, 3)
    assert binding.render(ctx).max() > 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/synth/test_o2bridge.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'luxaeterna.synth.o2bridge'`

- [ ] **Step 3: Write minimal implementation**

Create `luxaeterna/synth/o2bridge.py`:

```python
"""Lux Aeterna — O2 input bridge: decode packed-int32 MIDI and dispatch to bindings.

Wire format (ratified): one int32 = (status << 16) | (data1 << 8) | data2,
since o2lite lacks O2's native 'm' MIDI type.
"""

from __future__ import annotations

from .binding import ActiveBinding


def decode_midi(packed: int) -> tuple[int, int, int]:
    return (packed >> 16) & 0xFF, (packed >> 8) & 0xFF, packed & 0xFF


def dispatch_midi(bindings: list[ActiveBinding], status: int, d1: int, d2: int) -> None:
    kind = status & 0xF0
    if kind == 0x90 and d2 > 0:                       # note-on
        for b in bindings:
            fn = b.routes.get("note")
            if fn is not None:
                fn(d1, d2 / 127.0)
    elif kind == 0x80 or (kind == 0x90 and d2 == 0):  # note-off
        for b in bindings:
            noteoff = getattr(b.obj, "noteoff", None)
            if noteoff is not None:
                noteoff(("auto", d1))                 # best-effort; see Task 11 note
    elif kind == 0xB0:                                # control change
        key = f"cc:{d1}"
        for b in bindings:
            fn = b.routes.get(key)
            if fn is not None:
                fn(d2 / 127.0)


class O2Bridge:
    """Holds the active bindings and turns inbound packed-int32 MIDI into route calls."""

    def __init__(self, bindings: list[ActiveBinding]) -> None:
        self.bindings = bindings

    def on_midi(self, packed: int) -> None:
        status, d1, d2 = decode_midi(packed)
        dispatch_midi(self.bindings, status, d1, d2)

    def attach(self, o2lite_client, address: str = "/light/midi") -> None:
        """Subscribe on_midi to an o2lite address. Thin transport glue; the
        decode/dispatch above is what tests exercise."""
        o2lite_client.method_new(address, "i", True,
                                 lambda ts, addr, types, *args: self.on_midi(args[0]))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/synth/test_o2bridge.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add luxaeterna/synth/o2bridge.py tests/synth/test_o2bridge.py
git commit -m "feat(synth): O2 bridge (packed-int32 MIDI decode + dispatch)"
```

---

### Task 10: `LightEngine` + `OutputLoop` `on_frame` hook

**Files:**
- Create: `luxaeterna/synth/engine.py`
- Modify: `luxaeterna/output.py` (add optional `on_frame` param + call site)
- Test: `tests/synth/test_engine.py`
- Test: `tests/test_output_hook.py`

**Interfaces:**
- Consumes: `ActiveBinding` (Task 8), `SurfaceCapability` (Task 7), `Universe` (`luxaeterna.universe`).
- Produces:
  - `channels_for(color_order: str) -> int` (= `len(color_order)`).
  - `to_dmx_bytes(frame: np.ndarray, color_order: str) -> bytearray` — clip 0..1→0..255, reorder canonical RGBW→`color_order`, flatten.
  - `blend_into(surface: np.ndarray, sl: slice, top: np.ndarray, mode: str)` — `"add"` (clip sum) / `"over"` (replace).
  - `LightEngine(universe, cap: SurfaceCapability, bindings: list[ActiveBinding], clock=time.monotonic)` with `.render_into(universe)`.
- `OutputLoop.__init__` gains `on_frame: Callable[[Universe], None] | None = None`, invoked each tick before the dirty check.

- [ ] **Step 1: Write the failing test**

Create `tests/synth/test_engine.py`:

```python
import numpy as np
from luxaeterna.universe import Universe
from luxaeterna.synth.engine import LightEngine, channels_for, to_dmx_bytes, blend_into
from luxaeterna.synth.capability import shroom_capability
from luxaeterna.synth.manifest import LightInstrumentDecl, LightLane
from luxaeterna.synth.binding import resolve


def test_channels_and_dmx_byte_order():
    assert channels_for("GRB") == 3
    frame = np.array([[1.0, 0.0, 0.0]])          # pure red, canonical RGB
    out = to_dmx_bytes(frame, "GRB")             # order G,R,B -> 0,255,0
    assert list(out) == [0, 255, 0]


def test_blend_add_and_over():
    surf = np.zeros((2, 3))
    blend_into(surf, slice(0, 2), np.array([[0.5, 0, 0], [0.5, 0, 0]]), "add")
    blend_into(surf, slice(0, 1), np.array([[0.5, 0, 0]]), "add")
    assert surf[0, 0] == 1.0 and surf[1, 0] == 0.5


def test_engine_writes_universe_on_note():
    cap = shroom_capability("ie3")
    decl = LightInstrumentDecl("bloom", "primary", {},
                               [LightLane("note", "trigger")])
    binding = resolve(decl, cap)
    uni = Universe()
    clock = iter([0.0, 0.01, 0.02, 0.03]).__next__
    engine = LightEngine(uni, cap, [binding], clock=clock)

    engine.render_into(uni)                       # frame 0 -> dark
    assert max(uni.get_frame()[:36]) == 0
    binding.routes["note"](60, 1.0)
    engine.render_into(uni)                        # frame 1 -> lit
    assert max(uni.get_frame()[:36]) > 0
```

Create `tests/test_output_hook.py`:

```python
from luxaeterna.universe import Universe
from luxaeterna.output import OutputLoop
from luxaeterna.backends.base import DMXBackend


class FakeBackend(DMXBackend):
    def __init__(self):
        self.frames = []
    def open(self): pass
    def close(self): pass
    def send(self, frame, universe_id): self.frames.append(bytes(frame))


def test_on_frame_called_before_send():
    uni = Universe()
    marks = []
    def on_frame(u):
        marks.append("called")
        u.set(0, 200)
    loop = OutputLoop(uni, FakeBackend(), on_frame=on_frame)
    loop._loop_once()                              # single tick helper
    assert marks == ["called"]
    assert uni.get(0) == 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/synth/test_engine.py tests/test_output_hook.py -v`
Expected: FAIL (`No module named 'luxaeterna.synth.engine'`, and `OutputLoop` has no `on_frame` / `_loop_once`)

- [ ] **Step 3: Write minimal implementation**

Create `luxaeterna/synth/engine.py`:

```python
"""Lux Aeterna — the LightEngine: composite active bindings into a Universe each frame."""

from __future__ import annotations

import time

import numpy as np

from .binding import ActiveBinding
from .capability import SurfaceCapability
from .signal import RenderContext

_CANON = {"R": 0, "G": 1, "B": 2, "W": 3}


def channels_for(color_order: str) -> int:
    return len(color_order)


def to_dmx_bytes(frame: np.ndarray, color_order: str) -> bytearray:
    perm = [_CANON[ch] for ch in color_order]
    reordered = frame[:, perm]
    u8 = np.clip(reordered * 255.0, 0, 255).astype(np.uint8)
    return bytearray(u8.reshape(-1).tobytes())


def blend_into(surface: np.ndarray, sl: slice, top: np.ndarray, mode: str) -> None:
    if mode == "add":
        surface[sl] = np.clip(surface[sl] + top, 0.0, 1.0)
    elif mode == "over":
        surface[sl] = top
    else:
        raise ValueError(f"unknown blend mode {mode!r}")


class LightEngine:
    def __init__(self, universe, cap: SurfaceCapability,
                 bindings: list[ActiveBinding], clock=time.monotonic) -> None:
        self.universe = universe
        self.cap = cap
        self.bindings = bindings
        self._clock = clock
        self._channels = channels_for(cap.color_order)
        self._frame = 0
        self._start: float | None = None
        self._last: float | None = None
        self._positions = {b.zone.name: np.linspace(0, 1, b.zone.count)
                           for b in bindings}

    def render_into(self, universe) -> None:
        now = self._clock()
        if self._start is None:
            self._start = now
            self._last = now
        t = now - self._start
        dt = max(now - self._last, 1e-6)
        self._last = now

        surface = np.zeros((self.cap.pixel_count, self._channels))
        for b in self.bindings:
            ctx = RenderContext(time=t, frame=self._frame, dt=dt,
                                positions=self._positions[b.zone.name],
                                n=b.zone.count, channels=self._channels)
            top = b.render(ctx)
            sl = slice(b.zone.start, b.zone.start + b.zone.count)
            blend_into(surface, sl, top, b.blend)

        self._frame += 1
        universe.set_range(0, to_dmx_bytes(surface, self.cap.color_order))
```

Now modify `luxaeterna/output.py`. Add the import and parameter. Change the constructor signature and store the callback:

Add to the `__init__` signature (after `always_send: bool = False,`):

```python
        on_frame: Callable[[Universe], None] | None = None,
```

Add in `__init__` body (with the other assignments):

```python
        self.on_frame = on_frame
```

Extract the loop body into a reusable `_loop_once` and call the hook. Replace the `while self._running:` block in `_loop` with a call, and add the helper:

```python
    def _loop_once(self) -> None:
        """Run a single tick: hook, then conditional send. Used by the loop and tests."""
        if self.on_frame is not None:
            self.on_frame(self.universe)
        if self.always_send or self.universe.dirty:
            try:
                frame = self.universe.get_frame()
                self.backend.send(frame, self.universe.universe_id)
            except Exception as exc:
                if self.on_error:
                    self.on_error(exc)
                else:
                    log.error("Output error on universe %d: %s",
                              self.universe.universe_id, exc)
```

In `_loop`, keep the timing/FPS code but call `self._loop_once()` where the send block was. (The FPS counter increments only when a send happens; move the `frames += 1` into `_loop_once` by returning a bool, or keep FPS approximate — for this task, increment `frames` each tick and leave FPS as ticks/sec.)

Add the `Callable`/`Universe` imports at the top if not present:

```python
from typing import Callable
from .universe import Universe
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/synth/test_engine.py tests/test_output_hook.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Run the full suite (guard the output change)**

Run: `pytest -q`
Expected: PASS (all prior tests still green — the `on_frame=None` default preserves behavior)

- [ ] **Step 6: Commit**

```bash
git add luxaeterna/synth/engine.py luxaeterna/output.py tests/synth/test_engine.py tests/test_output_hook.py
git commit -m "feat(synth): LightEngine + additive on_frame hook on OutputLoop"
```

---

### Task 11: End-to-end integration + performance smoke

**Files:**
- Create: `tests/synth/test_end_to_end.py`
- Create: `luxaeterna/synth/session.py`
- Test: same file (integration).

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `build_session(manifest: LightManifest, cap: SurfaceCapability) -> tuple[list[ActiveBinding], O2Bridge]` — resolves every decl against the capability and wires a bridge over all bindings.
  - This is the single entry point a host (Shroom process) calls at session setup.

**Note on note-off id matching:** v1 `dispatch_midi` note-off uses a best-effort `("auto", pitch)` id. For deterministic control, hosts should pass explicit `note_id`s; the end-to-end test drives note-on then advances envelopes to prune (does not rely on note-off id matching). Tightening note-off→voice identity is listed in the spec's open questions.

- [ ] **Step 1: Write the failing test**

Create `tests/synth/test_end_to_end.py`:

```python
import time
import numpy as np
from luxaeterna.synth.manifest import LightManifest
from luxaeterna.synth.capability import shroom_capability
from luxaeterna.synth.session import build_session
from luxaeterna.synth.engine import LightEngine


MANIFEST = {
    "instruments": [{
        "instrument": "bloom", "target": "primary", "params": {},
        "lanes": [{"source": "note", "dest": "trigger"},
                  {"source": "cc:74", "dest": "hue"}],
    }]
}


def test_note_over_o2_lights_the_shroom():
    cap = shroom_capability("ie3")
    bindings, bridge = build_session(LightManifest.from_dict(MANIFEST), cap)
    uni_clock = iter([i * 0.02 for i in range(10)]).__next__
    from luxaeterna.universe import Universe
    uni = Universe()
    engine = LightEngine(uni, cap, bindings, clock=uni_clock)

    engine.render_into(uni)
    assert max(uni.get_frame()[:36]) == 0                      # dark before note

    bridge.on_midi((0xB0 << 16) | (74 << 8) | 0)               # CC74=0 -> red
    bridge.on_midi((0x90 << 16) | (60 << 8) | 127)             # note-on
    engine.render_into(uni)
    frame = uni.get_frame()[:36]
    assert max(frame) > 0                                       # lit after note

    # GRB order: byte 0 = green, byte 1 = red. Red hue -> red channel dominant.
    reds = frame[1::3]
    greens = frame[0::3]
    assert max(reds) > max(greens)


def test_perf_1000px_within_frame_budget():
    from luxaeterna.synth.capability import SurfaceCapability, Zone
    cap = SurfaceCapability("array", 1000, "GRB", [Zone("primary", 0, 1000)])
    bindings, bridge = build_session(LightManifest.from_dict(MANIFEST), cap)
    from luxaeterna.universe import Universe  # 1000px * 3 = 3000 > 512: use 2 universes in prod
    # perf test measures compositing cost only, not DMX packing bounds
    from luxaeterna.synth.engine import RenderContext  # noqa
    import numpy as np
    positions = np.linspace(0, 1, 1000)
    for b in bindings:
        b.routes["note"](60, 1.0)
    from luxaeterna.synth.signal import RenderContext as RC
    t0 = time.perf_counter()
    for f in range(44):
        ctx = RC(f / 44, f, 1 / 44, positions, 1000, 3)
        for b in bindings:
            b.render(ctx)
    elapsed = time.perf_counter() - t0
    assert elapsed / 44 < 0.0227          # avg frame < 22.7 ms (44 Hz budget)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/synth/test_end_to_end.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'luxaeterna.synth.session'`

- [ ] **Step 3: Write minimal implementation**

Create `luxaeterna/synth/session.py`:

```python
"""Lux Aeterna — session setup: resolve a manifest against a surface and wire O2 input."""

from __future__ import annotations

from .binding import ActiveBinding, resolve
from .capability import SurfaceCapability
from .manifest import LightManifest
from .o2bridge import O2Bridge


def build_session(manifest: LightManifest,
                  cap: SurfaceCapability) -> tuple[list[ActiveBinding], O2Bridge]:
    """Resolve every instrument declaration against ``cap`` and return the
    active bindings plus an O2 bridge fanning inbound MIDI across them."""
    bindings = [resolve(decl, cap) for decl in manifest.instruments]
    return bindings, O2Bridge(bindings)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/synth/test_end_to_end.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Run the whole suite**

Run: `pytest -q`
Expected: PASS (all green)

- [ ] **Step 6: Commit**

```bash
git add luxaeterna/synth/session.py tests/synth/test_end_to_end.py
git commit -m "feat(synth): build_session entry point + end-to-end and perf tests"
```

---

### Task 12: `tests/__init__` hygiene + README pointer

**Files:**
- Create: `tests/__init__.py`, `tests/synth/__init__.py` (if the test runner needs them)
- Modify: `pyproject.toml` (add `[project.optional-dependencies] dev = ["pytest", "numpy>=1.24"]` if not present)
- Test: `pytest -q` clean run.

- [ ] **Step 1: Ensure test packages import cleanly**

Create empty `tests/__init__.py` and `tests/synth/__init__.py` only if `pytest -q` reports import-mode collisions; otherwise skip. Run:

Run: `pytest -q`
Expected: PASS, no collection errors.

- [ ] **Step 2: Add a dev extra (if missing)**

Ensure `pyproject.toml` has:

```toml
[project.optional-dependencies]
serial = ["pyserial>=3.5"]
all = ["pyserial>=3.5"]
dev = ["pytest>=7", "numpy>=1.24"]
```

- [ ] **Step 3: Commit**

```bash
git add tests pyproject.toml
git commit -m "chore(synth): test package hygiene + dev extra"
```

---

## Self-Review

**1. Spec coverage:**

| Spec section | Task(s) |
|--------------|---------|
| §4.1 module layout | 1–11 (one file per module) |
| §5 signal model (field/control, memoization, `RenderContext`) | 1 |
| §6 starter vocabulary | 2 (control), 3 (field) |
| §7 Param / LightInstrument / LightSynth | 4, 5 |
| §8.1 `light_manifest` | 6 |
| §8.2 capability descriptor | 7 |
| §8.3 resolver / binding | 8 |
| §6/§10 MIDI packed int32 decode | 9 |
| §9 render loop + `on_frame` hook | 10 |
| §11 testing (deterministic uGen, resolver, O2 decode, fake-backend e2e, perf smoke) | 1–11, esp. 10–11 |
| §10 numpy core dep | 1 |

No spec requirement is left without a task. Deferred items (§3 non-goals) are intentionally absent.

**2. Placeholder scan:** No "TBD"/"handle edge cases"/"similar to Task N" — every code step carries complete code. The one forward-reference (note-off id matching) is documented explicitly in Task 11's note and maps to a spec open question, not a hidden gap.

**3. Type consistency:** `set_target` is the uniform setter across `Const`/`Smooth`/`CCReader` (used by `Param.set`). `render(ctx) -> np.ndarray` is uniform across uGens, instruments, synths, and `ActiveBinding`. `RenderContext(time, frame, dt, positions, n, channels)` field order is identical everywhere it is constructed (tasks 1,2,3,4,5,8,9,10,11). Route keys `"note"` / `"cc:<n>"` match between `binding.resolve` (Task 8) and `dispatch_midi` (Task 9). `channels_for`/`to_dmx_bytes`/`blend_into` signatures match their call sites in `LightEngine` (Task 10).

## Deferred to later specs (from spec §3)

Terrarium spectral array (Arco `probe`→O2→`SpectrumBand`), multi-surface arbitration, text DSL, on-device sensor→CC, the full `/ie<N>/led "tib" pattern` cue vocabulary, and per-pixel alpha-over blending (v1 ships `add` + opaque `over`).
