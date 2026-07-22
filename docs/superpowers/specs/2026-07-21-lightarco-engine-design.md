# Lux Aeterna — LightArco Engine (v1 vertical slice)

**Status:** Draft for review
**Date:** 2026-07-21
**Scope:** First spec of the light-synthesis engine. Vertical slice: full pipeline,
one surface (the 12-LED Shroom), driven by real note/CC over O2.

---

## 1. Motivation

Today `luxaeterna` is a pure **output** library: a thread-safe 512-byte `Universe`,
a 44 Hz `OutputLoop` that pushes frames to a backend (Art-Net / sACN / Enttec), and
static `Fixture`/`Profile` addressing. It generates nothing and reacts to nothing —
some external caller must compute every channel value and poke it in.

The Musical Mycology architecture already names the thing that should fill that gap.
Lux Aeterna is defined as *"the real-time lighting renderer — the visual analog of the
Arco audio engine — driving the Terrarium array and the Shroom LEDs in a 44 Hz hot
loop, downstream of a Bit's cue/graph logic"*
(`mm-terrarium/.../2026-07-21-terrarium-console-design.md:238-244`). But the mechanism
does not exist:

- `Role.light_manifest` is an **empty placeholder** (`mm-terrarium/control/roles.py`),
  sibling to `ugen_manifest`, with a comment promising the schema won't change once a
  real Bit declares light lanes.
- There is **no CC→light / note→light mapping** anywhere in code. The rule *"light is
  authored in the same musical timeline as sound"*
  (`mm-documents/mm-shrooms-app/shroom-installations-design.md:349-354`) is stated but
  unimplemented.
- `/game/hello` is a **bare name+version handshake** — there is no LED capability
  negotiation, so a Bit cannot ask "what light systems does this element have?"
- Nothing Faust-shaped or uGen-shaped for light exists in any repo. This is genuinely
  open ground, not a duplication.

This spec designs the engine that closes that gap, starting from a narrow, testable
slice.

## 2. Design pillars (decisions already made)

These six decisions frame the whole design and are treated as settled:

1. **Engine home — in `luxaeterna` (Python).** The light engine mirrors Arco's
   uGen/Instrument/Synth model *in Python*, computing light locally at 44 Hz and
   consuming O2 as **input**, rather than living inside Arco's C++ graph. This honors
   *"drives the 12 LEDs locally"* and the ratified rules *"single writer to `/arco`"*
   and *"the device never touches `/arco`"* (`control-gameserver-design.md:130-132`),
   and needs zero Arco-core changes. luxaeterna becomes the "LightArco."
2. **Signal model — per-pixel spatial field.** A Light Instrument is
   `color = f(pixel position, time, inputs)` evaluated across an element's pixel array
   each frame (the shader / "Faust-over-space" model). A PAR or moving head is the
   1-pixel degenerate case.
3. **Authoring — Python light-uGen graph.** A Light Instrument is composed from
   primitive light-uGens (numpy-vectorized per-pixel nodes), directly mirroring
   `pyarco/python25/arco_instr.py`. A text DSL can layer on later without rework.
4. **Binding — declared lanes, resolved late.** A Bit's `light_manifest` declares
   abstract intent (instrument type + note/CC lane bindings + an abstract target); the
   engine resolves it against live fixture capabilities at session setup, instantiates
   the instrument bound to the real pixel array, and builds the routing table —
   re-resolving on change. This fills `light_manifest` with real meaning and mirrors how
   Control builds the audio graph from the role manifest.
5. **Capability source — hybrid.** Interactive elements self-describe a minimal LED
   descriptor when they register/join (extending `/game/hello`); fixed infrastructure
   comes from a per-installation config. The engine merges both into one capability
   registry keyed by surface.
6. **v1 scope — vertical slice, one surface.** Full pipeline end-to-end but narrow:
   proven on the 12-LED Shroom with real note/CC over O2. Defers the Terrarium spectral
   array, multi-surface arbitration, and any text DSL.

### Two calls resolved during review

- **Subpackage name:** `luxaeterna.synth` — signals "the Arco-analog synthesis layer,"
  distinct from the transport layer (`universe`/`output`/`fixture`/`backends`).
  *(Open to `luxaeterna.light` if preferred.)*
- **`LightSynth` voices in v1:** kept **in** scope. Note-on → transient voice is the
  essence of "MIDI note → light" and is the one piece worth the extra complexity.

## 3. Non-goals (explicitly deferred to later specs)

- Terrarium **spectral array** — Arco's spectral ugens → `probe`/`dnsampleb`-style O2
  emission → a `SpectrumBand` field-uGen. (The Arco decimation precedent —
  `probe`/`vu`/`dnsampleb`, which compute at block rate but emit to an external O2
  address every N blocks — is the intended seam; not built here.)
- **Multi-surface** ownership/arbitration (e.g. two Portable Terrariums vs one Booster).
- **Text DSL** (`.ugen`-style declarative light instruments). The Python graph is the
  substrate; the DSL is future sugar that compiles to it.
- **On-device sensor→CC** mapping (tilt→filter etc.) as an O2 source.
- The full `/ie<N>/led "tib" time pattern args` **cue-pattern vocabulary**. v1 accepts
  note/CC and direct param cues only.

## 4. Architecture

The existing transport layer is **untouched** and becomes the sink. All new code lives
under `luxaeterna/synth/`.

```
   Bit (declares intent)                    Installation config
   light_manifest:                          surfaces: {ring:0-7, stem:8-11, ...}
     instrument: bloom                                │
     lanes: cc:74→hue, note→trigger         ┌─────────┴──────────┐
     target: "primary"                      │ Capability registry │ ← elements self-describe on join
             │                              └─────────┬──────────┘
             ▼                                        │
   ┌───────────────────────────────────────────────────────────┐
   │  binding.resolve()  (session setup)                        │
   │  abstract intent ──resolve→ live instrument bound to real  │
   │                             pixel range + MIDI routing tbl  │
   └───────────────────────────────┬───────────────────────────┘
     O2 in (o2bridge):             ▼
     note/CC (packed int32)  ┌──────────────────┐   44 Hz (engine.tick)
     direct param cues ────► │ Light-uGen graph │ ─────────► Universe ─► backend
                             │ (numpy per-pixel)│           (existing)   (Art-Net/GPIO)
                             │ Instrument/Synth │
                             └──────────────────┘
```

### 4.1 Module layout

| File | Responsibility |
|------|----------------|
| `luxaeterna/synth/signal.py` | `LightUgen` base — `render(ctx) → np.ndarray`; the field-rate vs control-rate model; `RenderContext` |
| `luxaeterna/synth/ugens.py` | Starter vocabulary (§6) |
| `luxaeterna/synth/instrument.py` | `Param`, `LightInstrument`, `LightSynth` — mirrors `arco_instr.py` |
| `luxaeterna/synth/manifest.py` | `LightManifest` / `LightInstrumentDecl` / `LightLane` dataclasses (the `light_manifest` contract) |
| `luxaeterna/synth/capability.py` | `Zone`, `SurfaceCapability`, `CapabilityRegistry` (self-describe ⊕ config) |
| `luxaeterna/synth/binding.py` | `resolve(manifest, capability) → ActiveBinding` (instrument + routing table) |
| `luxaeterna/synth/o2bridge.py` | o2lite client: decode note/CC (packed int32) + cues → param/voice calls |
| `luxaeterna/synth/engine.py` | `LightEngine` — owns the 44 Hz tick: composite graph → `Universe` → backend |
| `luxaeterna/synth/registry.py` | Name → instrument-factory table (so a manifest's `instrument: "bloom"` resolves) |

Reused unchanged: `universe.py`, `output.py` (one small additive hook, §9), `fixture.py`,
`backends/`.

## 5. Signal model — two rates, mirroring Arco's a/b/c

Arco distinguishes `'a'` (audio-rate, `BL`=32 samples/block), `'b'` (block-rate, 1/block),
and `'c'` (const) — see `arco/arco/src/arcotypes.h` and `ugen.h`. The light engine's two
rates are the direct analog, at the DMX frame clock rather than the audio block clock:

- **Field-rate uGens** output a per-pixel array of shape `(N, C)` where `N` = pixel count
  and `C` = channels (3 RGB / 4 RGBW). Analog of `'a'`. Examples: `SolidColor`,
  `Gradient`, `PaletteMap`, `Bloom`, `Noise`.
- **Control-rate uGens** output one scalar (or small tuple) per frame. Analog of `'b'`/`'c'`.
  Examples: `Const`, `Smooth`, `LFO`, `Envelope`, `CCReader`, `NoteTrigger`.

```python
@dataclass
class RenderContext:
    time: float             # seconds since engine start (monotonic)
    frame: int              # frame counter
    dt: float               # seconds since previous frame (~1/44)
    positions: np.ndarray   # shape (N,), normalized pixel position 0..1 along the surface
    n: int                  # pixel count N (== positions.shape[0])

class LightUgen:
    rate: str               # "field" | "control"
    def render(self, ctx: RenderContext) -> np.ndarray: ...
```

**Composition is by wiring, exactly like Arco.** A uGen holds references to its input
uGens and calls their `render(ctx)`; field-rate nodes broadcast control-rate inputs across
pixels (numpy broadcasting is the analog of Arco's stride/broadcast in
`ugen.h:163-189`). Example:

```python
bloom = Bloom(
    trigger = NoteTrigger(),                 # control-rate
    hue     = Smooth(CCReader(74), tau=0.15) # control-rate glide, straight from Smoothb
)                                            # → field-rate (N,3)
```

**Fan-out memoization** (Arco's `run(block_count)` trick, `ugen.h:197-207`): a uGen caches
its output keyed by `ctx.frame`, so a node pulled by two consumers computes once per frame.

**Vectorization is a hard requirement.** At 44 Hz over up to ~1000 px, per-pixel Python
loops cannot hold frame rate. Every field-rate uGen computes with numpy array ops.
`numpy` becomes a core dependency.

## 6. Starter vocabulary (v1)

Minimal but expressive enough to prove the pipeline and author a real Shroom Bit:

**Control-rate**
- `Const(value)` — fixed; analog of Arco `Const` (`arco/src/const.h`).
- `Smooth(input, tau)` — one-pole glide toward the input's latest value; analog of
  `Smoothb` (`arco/src/smoothb.h:53-60`). This is how dynamic params update smoothly.
- `LFO(shape, hz, phase)` — sine/tri/saw/square.
- `Envelope(attack, decay, sustain, release)` — gated by a trigger; drives voice fade.
- `CCReader(cc_number)` — latest value of a MIDI CC lane (0..1 normalized).
- `NoteTrigger()` — fires on note-on; carries pitch/velocity to a voice.

**Field-rate**
- `SolidColor(color)` — uniform fill.
- `Gradient(stops, ...)` — positional gradient across `ctx.positions`.
- `PaletteMap(index, palette)` — map a control value through a named palette (hue ramp,
  fire, etc.).
- `Bloom(trigger, hue, ...)` — a radial/positional bloom that blossoms on trigger and
  fades; the flagship "note-on flash / CC-driven color+bloom" primitive named in
  `shroom-installations-design.md:349-354`.
- `Noise(scale, speed)` — value/perlin-ish spatial noise for organic texture.

Registered by name in `registry.py` so a manifest's `instrument: "bloom"` resolves to a
factory.

## 7. Instrument / Synth / Param — borrowed from `arco_instr.py`

Mirrors the proven Arco client abstraction (which has **no server-side representation** —
`arco/doc/design.md:611-614` — so it is purely a Python composition layer, exactly our case).

- **`Param`** — a named, settable binding backed by a `Const` or `Smooth` control-uGen;
  analog of `Param_descr` (`arco_instr.py:81-130`). `param.set(value)` updates the target.
- **`LightInstrument`** — a graph with a designated **output field-uGen**; exposes named
  `Param`s; `render(ctx)` returns the output node's `(N,C)` array. Analog of
  `class Instrument(Ugen)` borrowing its output ugen's id (`arco_instr.py:165-213`).
- **`LightSynth`** — a voice pool over a `LightInstrument` factory. `noteon(pitch, vel,
  **params)` spawns a transient **voice** instrument (e.g. a `Bloom` with an `Envelope`),
  additively composited over the base; `noteoff`/envelope-completion moves it through a
  `finishing` list and frees it. Direct analog of `class Synth(Instrument)` with
  `notes` / `free_notes` / `finishing_notes` (`arco_instr.py:306-450`).

**Compositing.** Multiple instruments/voices on one surface combine via a blend mode
(`add`, `alpha-over`) into the final `(N,C)` frame. v1 ships `add` (for glowing/bloom
layering) and `alpha-over`.

## 8. The contracts

### 8.1 `light_manifest` schema (fills `Role.light_manifest`)

```python
@dataclass
class LightLane:
    source: str                 # "cc:74" | "note" | "sensor:tilt" (sensor deferred)
    dest:   str                 # instrument param name, e.g. "hue" | "trigger"
    curve:  str = "linear"      # value mapping curve (linear|exp|log); v1: linear + exp

@dataclass
class LightInstrumentDecl:
    instrument: str             # registered type name, e.g. "bloom"
    target:     str             # abstract zone: "primary" | "ring" | "stem"
    params:     dict            # static initial param values
    lanes:      list[LightLane] # note/CC → param bindings

@dataclass
class LightManifest:
    instruments: list[LightInstrumentDecl]
```

Authored per-Role, sibling to `ugen_manifest`. A Bit declares *what* it wants; it never
names pixel indices or fixture wiring — that is resolved late (§8.3).

### 8.2 Capability descriptor

```python
@dataclass
class Zone:
    name:  str                  # "ring" | "stem" | "primary" | installation-named
    start: int                  # first pixel index
    count: int                  # pixel count

@dataclass
class SurfaceCapability:
    surface_id:  str            # e.g. "ie3"
    pixel_count: int
    color_order: str            # "GRB" | "RGB" | "RGBW"
    zones:       list[Zone]     # "primary" defaults to the whole surface
```

- **Interactive elements self-describe** on registration — v1 extends the join with a
  light descriptor. The 12-LED Shroom announces
  `SurfaceCapability("ie3", 12, "GRB", [Zone("ring",0,8), Zone("stem",8,4), Zone("primary",0,12)])`.
- **Fixed infrastructure** is provided by a per-installation config file that the
  `CapabilityRegistry` loads and merges (path/format stubbed but present, so the merge
  seam is exercised even though v1 only drives a Shroom).

### 8.3 Resolver / binding

```python
@dataclass
class ActiveBinding:
    instrument: LightInstrument | LightSynth
    routes: dict[str, Callable]     # "cc:74" → param.set ; "note" → synth.noteon

def resolve(decl: LightInstrumentDecl,
            cap:  SurfaceCapability) -> ActiveBinding: ...
```

At **session setup**: for each `LightInstrumentDecl`, look up `target` in the surface's
zones → get `(start, count)` → instantiate the named instrument bound to that pixel field
→ build `routes` from the lanes. On note/CC arriving over O2, look up `routes` and drive
the param/voice. On capability change (element re-registers), re-resolve.

## 9. Render loop integration

`OutputLoop` gains **one optional additive hook** — the only change to existing code:

```python
OutputLoop(universe, backend, on_frame=engine.render_into)  # on_frame(universe) called
                                                            # each tick BEFORE the frame is read
```

`LightEngine.render_into(universe)`:
1. Allocate the surface frame `(pixel_count, C)`.
2. For **each active binding**, build a `RenderContext` sized to that binding's bound
   **zone** (`n` = zone `count`; `positions` normalized 0..1 across the zone), call
   `binding.render(ctx) → (count, C)`, and blend it into the surface frame at the zone's
   `[start : start+count]` slice using the binding's blend mode. Bindings targeting the
   same/overlapping zones composite in declaration order.
3. Convert the surface frame to the surface's channel order (`color_order`) and
   `universe.set_range(...)`.

So `RenderContext` is **per-binding** (sized to its zone), not per-surface — an instrument
bound to `"ring"` sees `n=8`; one bound to `"primary"` sees `n=12`. The engine owns the
placement of each zone's output into the shared surface frame.

**One clock, no drift**; the existing dirty-flag optimization, FPS tracking, and backends
are reused verbatim. Backwards compatible — `on_frame=None` preserves today's behavior.

## 10. Dependencies

- `numpy` — new **core** dependency (required for per-pixel vectorization).
- `o2lite` (Python) — for the O2 bridge. Confirmed to run on constrained nodes
  (`o2/o2litepy`, `o2/demo/esp32ctrl`), so the transport is proven independent of Arco.
  Wire format for MIDI is **packed int32** (status, data1, data2 in one word) per
  `control-gameserver-design.md:140-141`, since o2lite lacks O2's native `'m'` type.

## 11. Testing strategy (TDD, no hardware)

- **uGen render tests** — deterministic: fixed `RenderContext` + params → expected
  `ndarray` (assert with `np.testing.assert_allclose`).
- **Param / Smooth tests** — glide converges toward target; envelope stages.
- **Resolver tests** — `(manifest, capability)` → correct pixel range + routing table;
  unknown target / unknown instrument raise clear errors.
- **O2 decode tests** — packed int32 → (status, note/cc, value); note-on/off, CC.
- **End-to-end fake-backend test** — a `DMXBackend` that captures frames; feed synthetic
  note/CC through `o2bridge` → `binding` → `engine` → assert emitted frames change as
  expected (note-on blooms; CC shifts hue).
- **Performance smoke** — render a 1000-px graph within the 44 Hz frame budget
  (~22.7 ms), guarding the vectorization requirement.

## 12. Open questions (for the plan / later specs)

- Exact **join-message extension** for element self-description (new O2 verb vs. fields
  on `/game/hello`) — needs coordination with `mm-terrarium`; v1 can stub the transport
  and unit-test the registry directly.
- **Palette catalogue** — which named palettes ship in v1.
- Whether `Smooth` `tau` is per-param authorable in the manifest or fixed per instrument.

## 13. Sources

Design intent and mechanisms this spec is grounded in:

- Lux Aeterna's role & the "visual analog of Arco" framing —
  `mm-terrarium/.../2026-07-21-terrarium-console-design.md:238-244`;
  `mm-documents/mm-shrooms-app/shroom-installations-design.md:101,349-354,514`.
- Ratified rules ("single writer to `/arco`", "device never touches `/arco`", MIDI as
  packed int32) — `mm-terrarium/docs/control-gameserver-design.md:130-132,140-141`.
- `Role.light_manifest` placeholder — `mm-terrarium/control/roles.py`.
- Arco uGen model (base class, block rate, fan-out memoization) —
  `arco/arco/src/ugen.h:71,163-207`, `arco/arco/src/arcotypes.h:7-18`.
- `Const` / `Smoothb` control mechanism — `arco/src/const.h`, `arco/src/smoothb.h:53-60`.
- Instrument / Synth / Param (client-side only) —
  `pyarco/python25/arco_instr.py:81-450`; `arco/doc/design.md:611-614`.
- `.ugen`→Python codegen precedent (for the future DSL) —
  `pyarco/tools/ugen_parser.py`, `pyarco/tools/ugen_codegen.py`.
- Decimated-emit precedent for a future spectral/array path — `arco` `probe`/`vu`/`dnsampleb`.
```
