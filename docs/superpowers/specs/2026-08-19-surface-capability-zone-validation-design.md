# SurfaceCapability zone validation

**Status:** Approved, not yet implemented.
**Repo:** luxaeterna. One file, `luxaeterna/synth/capability.py`, plus its
test module.
**Driven by:** a whole-branch review of `claude/websim-linear-surface-layout`,
which found that the fallback that branch existed to fix is still reachable
and still buggy for a whole class of capability the branch could not touch.
See section 1.

A `SurfaceCapability` declares a surface's pixel count and its named zones,
and nothing anywhere checks that the two agree. A zone may start before the
surface, run past its end, duplicate another zone's name, or leave pixels
unaccounted for, and the object constructs happily. Every consumer then
deals with the consequences on its own, badly and silently.

---

## 1. Findings from the code

### 1.1 The traced failure: websim's `pos()` fallback is still reachable

`luxaeterna/backends/websim.py`'s served page resolves a pixel's screen
position in `pos(i)`, which has three branches: `ring`, `stem`, and a
fallback. `linear` is set at capability-handshake time:

```js
linear=!cap.zones.some(z=>z.name==='ring'||z.name==='stem');
```

Branch `claude/websim-linear-surface-layout` fixed the fallback for surfaces
declaring neither, which now fit the canvas in one row. The old fixed 24 px
pitch survives for the case where `linear` is false:

```js
return [40+i*24,380];
```

That line is reached whenever a capability declares a ring or a stem which
does not fully partition `pixel_count`. A whole-branch reviewer verified it
computationally: a capability with a ring covering 8 of 20 pixels and no stem
puts its tail pixels off-canvas, max x = 496 on a 320 px canvas, reproducing
the exact truncation class the branch existed to fix.

Nothing live triggers it today. The only ring/stem declaration in either repo
is `shroom_capability()`, which exactly partitions 8 + 4 = 12. It was
deliberately left alone because that branch carried a hard constraint that
`pos()`'s ring and stem branches must not change byte for byte.

### 1.2 An overrunning zone fails silently and permanently

This one has nothing to do with the browser and is arguably worse.
`LightEngine.render_into` slices the surface with the zone it is handed:

```python
sl = slice(b.zone.start, b.zone.start + b.zone.count)
blend_into(surface, sl, top, b.blend)
```

A zone running past `pixel_count` produces a short numpy slice, so
`surface[sl] + top` raises a broadcast `ValueError`. The per-binding
`except Exception` one loop above catches it and appends the binding to
`failed`, which is the quarantine path for a misbehaving instrument. The
result is that a mis-declared zone renders nothing, forever, and surfaces
as an instrument that looks broken rather than as a declaration that is
wrong. Nothing raises, nothing logs the real cause.

### 1.3 What is actually declared today, measured

`SurfaceCapability.__init__` was instrumented and both suites run
(`luxaeterna` 225 passed, `mm-terrarium` 1057 passed 1 skipped), which
produced twelve distinct capabilities. `to_fixture_capability(DEMO, "array")`
is the thirteenth: it is reachable in production (`harness/o2_shroom.py` and
`harness/room_simulator.py` both call it) but no test constructs it, so it
was enumerated by calling it directly. The full set:

| surface | px | non-`primary` zones | tiles exactly |
| --- | --- | --- | --- |
| `ie0`, `ie3` (`shroom_capability`) | 12 | ring(0,8) stem(8,4) | yes |
| `ie3` (test, no `primary`) | 12 | ring(0,8) stem(8,4) | yes |
| `array` | 300, 1000 | none | n/a |
| `bare` | 12 | none | n/a |
| `custom` | 24 | only.all(0,24) | yes |
| `odd` | 30 | only.b(10,20) only.a(0,10) | yes, unsorted |
| `room_test` | 90 | 5 zones | yes |
| `room_test_main` | 60 | left/center/right | yes |
| `room_test_accent` | 30 | low/high | yes |
| `room_demo`, `room_demo_array` | 864 | left/center/right | yes |

Two facts fall straight out of that table.

**`primary` overlaps everything, by construction.** Twelve of the thirteen
declare a `primary` zone spanning the whole surface alongside real zones.
`shroom_capability()` does it, and both of mm-terrarium's adapters
(`harness/room_surface.py`'s `to_capability()` and `to_fixture_capability()`)
append it deliberately, with a comment explaining why: the renderer needs it
to resolve an untargeted instrument, and the Console must not draw it. A
blanket no-overlap rule is therefore a non-starter.

**Every real surface already tiles.** Not one existing capability has a gap
in its non-`primary` zones. The strict rule below costs nothing today.

### 1.4 A coverage rule alone does not close the websim hole

Worth stating plainly, because it is the non-obvious part. The `pos()`
fallback fires when a ring or stem is declared and pixel `i` is in neither.
A capability declaring `ring(0,8) stem(8,4) tip(12,8) primary(0,20)` on a
20 px surface tiles `[0, 20)` perfectly and passes any coverage rule. Pixels
12 to 19 still take the fallback and still land at x = 328 to 496 on the
320 px canvas.

Coverage catches the specific capability the reviewer traced, because a ring
alone does not tile 20 px. It does not catch the general shape. Closing the
path for real needs a rule about ring and stem specifically, which is rule 4
in section 2.

### 1.5 mm-terrarium already decided the opposite on gaps

`control/room_profile.py`'s `RoomProfile.__post_init__` validates the same
data one layer up, and its authors considered coverage and rejected it:

```python
# Overlap and overrun are real configuration bugs; declaration
# order and full coverage are not requirements -- a fixture may
# leave pixels undeclared, ...
```

with a test named for it,
`tests/test_room_profile.py::test_zones_need_not_be_declared_in_position_order_or_tile_gaplessly`.
That test constructs a sparse profile and never adapts it to a capability, so
nothing breaks. But the divergence is real and is accepted deliberately here,
see section 6.

---

## 2. The rules

All four are enforced in `SurfaceCapability.__post_init__`, so every
construction path is covered by one rule set: the `shroom_capability()`
factory, `CapabilityRegistry.load_config`, direct construction in tests, and
mm-terrarium's two adapters.

Let `others` be the zones not named `primary`, and `shroom` the zones named
`ring` or `stem`.

**Rule 1, bounds.** `pixel_count` must be positive. Every zone must have
`count > 0`, `start >= 0`, and `start + count <= pixel_count`. Zone names
must be unique.

**Rule 2, `primary` is the whole surface.** If a zone named `primary` is
declared it must be exactly `(0, pixel_count)`. `primary` is the one name
`SurfaceCapability.zone()` synthesizes when absent, so a `primary` meaning
anything else is a lie about this module's own vocabulary.

**Rule 3, coverage.** `others` must be empty, or tile `[0, pixel_count)`
exactly: no gaps, no overlaps among themselves, nothing past the end.
`primary` is excluded from both the gap and the overlap check, because it is
an alias for the whole surface rather than a region of it. Declaration order
does not matter; the check sorts by start first.

**Rule 4, Shroom geometry.** If `shroom` is non-empty, those zones must tile
`[0, pixel_count)` exactly.

Rule 4 is implied by rule 3 whenever ring and stem are the only named zones,
which is every real surface today. It bites in exactly one case: a ring/stem
surface carrying a third named zone, which is the case section 1.4 shows rule
3 misses.

Rule 4 is stated in this module's own terms, not the browser's. `ring` and
`stem` are the canonical Shroom geometry vocabulary, defined by
`shroom_capability()` in this file and appearing nowhere else in either repo
as ordinary zone names. They are also the only zone names in the codebase
with a non-linear physical meaning: everything else is a contiguous run on a
line. A surface that says "these 8 pixels are arranged in a circle" and
leaves 12 unaccounted for is genuinely under-described, and no consumer
laying out a ring and a stem has a defined position for a pixel in neither.

`shroom_capability()` itself is unchanged and stays legal under all four.

### 2.1 Why `ValueError`

`luxaeterna/synth/` never imports the `LuxAeternaError` tree. That tree is
the I/O layer: `backends/`, `universe.py`, `pixelspan.py`, `universeset.py`,
`fixture.py`. Every bad-declaration raise inside `synth/` today is a plain
`ValueError` or `KeyError` (`binding.py:21,48`, `engine.py:30`,
`manifest.py:30`, `presets.py`, `registry.py:14`). mm-terrarium's peer
validation in `RoomProfile.__post_init__` also raises `ValueError`. Using
`ValueError` keeps one idiom across both repos and adds no API surface.

### 2.2 Shape of the implementation

`__post_init__` delegates to small module-private helpers rather than
carrying one long block, so each rule is readable and independently
testable:

```python
def __post_init__(self) -> None:
    _check_bounds(self)      # rules 1 and 2
    _check_coverage(self)    # rules 3 and 4
```

The file is 58 lines today. It stays under about 120 with validation, so no
split is warranted.

---

## 3. `CapabilityRegistry.load_config`

Three changes, all about failing loudly and locatably.

**Located field errors.** `load_config` currently does `s["surface_id"]` and
friends, so a typo in a config file surfaces as a bare `KeyError:
'surface_id'` with no indication of which surface. It reuses `manifest.py`'s
`_require` helper, giving byte-identical message shape to the light-manifest
contract's:

```
capability config surfaces[2]: missing required field 'pixel_count'
capability config surfaces[2] zones[0]: missing required field 'count'
```

This is a cross-module import of a private helper (`from .manifest import
_require`). `manifest.py` imports nothing from the package, so there is no
cycle. The alternative considered was a local `try/except KeyError` wrapper
producing the same message; sharing the helper was preferred so the two
external-declaration contracts cannot drift apart in wording. Flagged here
so it can be vetoed at review.

**Atomic registration.** Today `load_config` registers each surface as it
goes, so a config whose fourth surface is invalid leaves the first three
registered and the caller holding a half-loaded registry. It builds the whole
list first, then registers. A bad config now registers nothing.

**Rules 1 to 4 come for free**, since `load_config` constructs
`SurfaceCapability` objects.

---

## 4. Error messages

Located on the surface first, then the zone, matching the existing style in
this module (`surface {self.surface_id!r} has no zone {name!r}`):

```
surface 'x': pixel_count must be positive, got 0
surface 'x': duplicate zone names: ['ring']
surface 'x': zone 'ring' must have a positive count, got 0
surface 'x': zone 'ring' starts at -1, before the surface
surface 'room_demo': zone 'left' runs to pixel 900, past the surface's 864 px
surface 'ie0': zone 'primary' must span the whole surface (0, 12), got (0, 8)
surface 'x': zones do not tile its 20 px: gap at pixel 8
surface 'x': zones overlap: 'a' and 'b'
surface 'x': ring/stem geometry leaves pixel 12 unaccounted; a surface
  declaring a ring or a stem must describe every pixel with them
```

Each message names the surface, the offending zone where there is one, and
the number that is wrong. A Bit author or a Room profile author reading it
should not need to open this file.

Messages are deterministic for a given declaration: the coverage check sorts
by start before walking, so the gap and overlap messages always report the
first failure in position order rather than in declaration order. Rule 1's
per-zone checks run in declaration order and report the first zone that
fails. Rules run in the order given in section 2, so a capability breaking
more than one rule reports the most basic breakage first.

---

## 5. Testing

Appended to `tests/synth/test_capability.py`. Two carry the actual argument
and must not be dropped:

1. **The traced case.** `ring(0,8)` plus `primary(0,20)` on 20 px is
   rejected. This is the reviewer's capability from section 1.1, whose tail
   lands at x = 496 on a 320 px canvas.
2. **The rule-4-only case.** `ring(0,8) stem(8,4) tip(12,8) primary(0,20)`
   on 20 px is rejected by rule 4 despite tiling `[0, 20)` perfectly. This
   is the test that distinguishes rule 4 from rule 3; without it the guard is
   only partial and the distinction is untested.

The rest:

3. `shroom_capability()` constructs, as a standing regression guard that the
   canonical surface stays legal.
4. A zone running past the end is rejected, with a comment naming the
   silent-`LightEngine` failure from section 1.2.
5. A zone with `count == 0` is rejected; a zone with `start < 0` is rejected.
6. `pixel_count <= 0` is rejected.
7. Duplicate zone names are rejected.
8. `primary` declared with the wrong span is rejected.
9. `primary` alongside real zones is accepted. This is the overlap exemption
   and the shape twelve of the thirteen real capabilities have.
10. A capability with no zones at all is accepted, and `zone("primary")`
    still synthesizes.
11. Zones that tile but are declared out of position order are accepted.
    This is mm-terrarium's `odd` profile from the section 1.3 table.
12. A gap in the non-`primary` zones is rejected.
13. An overlap between two non-`primary` zones is rejected.
14. `load_config` raises a located error naming the surface index and the
    missing field.
15. `load_config` registers nothing when any surface in the config is
    invalid.

The existing three tests in the module are unchanged. Test 11 in particular
is not new coverage of new behavior; it pins that the sort-before-checking
decision in rule 3 actually holds, since an unsorted profile is a shape
mm-terrarium ships.

### 5.1 Verification

Both suites, because mm-terrarium has luxaeterna editable-installed straight
from this working tree (`luxaeterna from:
/Users/chris/projects/luxaeterna/luxaeterna/__init__.py`), so its 1057 tests
exercise whatever branch this repo is on.

**RUN ON: MYCOLOGICAL**

```bash
cd /Users/chris/projects/luxaeterna && .venv/bin/python -m pytest tests -q
```

**RUN ON: MYCOLOGICAL**

```bash
cd /Users/chris/projects/mm-terrarium && .venv/bin/python -m pytest tests -q
```

Baselines to beat: luxaeterna 225 passed, mm-terrarium 1057 passed 1 skipped.
Both must stay green with zero changes to any existing test in either repo.
Any existing test needing a change means a rule is wrong, not that the test
is.

---

## 6. What explicitly does not change

**`pos()` is not touched.** The `claude/websim-linear-surface-layout`
constraint that its ring and stem branches stay byte for byte holds. The
fallback line stays too, as defence against a hand-crafted websocket client:
`capability_message` ships zones to the browser, and validation upstream
constrains what this repo constructs, not what an arbitrary client sends.

**mm-terrarium's `RoomProfile` is not tightened.** luxaeterna ends up
stricter than its own caller. A sparse-zone `RoomProfile` passes
mm-terrarium's validation (section 1.5) and then fails in
`harness/room_surface.py`'s adapter. Nothing today constructs one that gets
adapted, and the error names the surface, but this is a deliberate divergence
rather than an accident, and the next person to declare a Room profile with
partial zone coverage will meet it at boot. Tightening `RoomProfile` to match
is a separate change in a separate repo and is not in scope here.

**No type checking on config values.** `{"pixel_count": "300"}` raises a
`TypeError` from the comparison in rule 1 rather than a located message.
Loud, but ugly. Out of scope.

**No `color_order` validation.** An unknown letter still fails later in
`engine.py`'s `to_dmx_bytes`. Unrelated to zones.

**Mutation after construction still bypasses everything.**
`SurfaceCapability` is a plain dataclass, not frozen, and `zones` is a
mutable list, so `cap.zones.append(...)` is unchecked. Nothing in either repo
mutates a capability after construction (verified by grep). Freezing it is a
larger behavioral change than this work justifies.

---

## 7. Non-goals

- Making `Zone` self-validating. A `Zone` cannot see `pixel_count`, so it
  could only check `count > 0` and `start >= 0`, splitting the rules across
  two classes. All four rules live in one place, matching how `RoomProfile`
  validates its `RoomZone`s rather than `RoomZone` validating itself.
- A new exception type. See section 2.1.
- Any new JavaScript test. The page's behavior is unchanged, and asserting
  the fallback is unreachable from the browser would be testing a guarantee
  that now lives upstream in Python.

---

## 8. Success criteria

1. A capability whose non-`primary` zones leave a gap, overlap each other, or
   run past `pixel_count` raises `ValueError` at construction, naming the
   surface and the offending zone.
2. A capability declaring a ring or a stem that does not account for every
   pixel raises `ValueError` at construction, including when its other zones
   make it tile.
3. `CapabilityRegistry.load_config` raises a located error for a missing
   field and registers nothing when any surface is invalid.
4. `shroom_capability()` and all twelve other capabilities in the section 1.3
   table still construct.
5. luxaeterna 225 passed and mm-terrarium 1057 passed 1 skipped, both with no
   existing test modified, plus the new tests from section 5.
