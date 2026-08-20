# SurfaceCapability Zone Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a `SurfaceCapability` whose zones do not account for its
`pixel_count` fail loudly at construction, so every consumer benefits instead
of each one mis-handling it silently.

**Architecture:** Four rules enforced in `SurfaceCapability.__post_init__`,
delegating to three module-private helpers in the same file. Because the
dataclass validates itself, every construction path is covered at once: the
`shroom_capability()` factory, `CapabilityRegistry.load_config`, direct
construction in tests, and mm-terrarium's `harness/room_surface.py` adapters.
`CapabilityRegistry.load_config` additionally gains located field errors and
all-or-nothing registration.

**Tech Stack:** Python 3, `dataclasses`, pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-19-surface-capability-zone-validation-design.md`

## Global Constraints

- Every command in this plan runs on **MYCOLOGICAL**.
- Repo is `/Users/chris/projects/luxaeterna`, branch
  `claude/websim-linear-surface-layout`. Run pytest through `.venv/bin/python`,
  never a bare `python3`.
- Errors are plain `ValueError`. Do not add a new exception type and do not
  import from `luxaeterna/exceptions.py`. `luxaeterna/synth/` has never used
  that tree; it is the I/O layer's.
- **No existing test in either repo may be modified.** Both suites must stay
  green after every task. Baselines: luxaeterna **225 passed**, mm-terrarium
  **1057 passed, 1 skipped**. mm-terrarium has luxaeterna editable-installed
  from this working tree, so its suite exercises these changes directly. An
  existing test that needs changing means a rule is wrong, not the test.
- Do not touch `luxaeterna/backends/websim.py`. The
  `claude/websim-linear-surface-layout` constraint that `pos()`'s ring and
  stem branches stay byte for byte still holds, and the fallback line stays as
  defence against a hand-crafted websocket client.
- Do not touch mm-terrarium. Its `RoomProfile` stays as it is; the deliberate
  strictness divergence is recorded in spec section 6.
- `docs/deployment.md` has unrelated uncommitted changes on this branch. Leave
  them alone and never `git add -A` or `git commit -a`.
- Zone name constants: `_WHOLE_SURFACE = "primary"` and
  `_SHROOM_ZONES = ("ring", "stem")`, defined once at module level in Task 1
  and reused.

---

## File Structure

| File | Responsibility | Task |
| --- | --- | --- |
| `luxaeterna/synth/capability.py` | All four rules plus the registry change. 58 lines today, about 125 after. No split warranted. | 1, 2, 3 |
| `tests/synth/test_capability.py` | All new tests appended. Its existing three tests and its import block are unchanged. | 1, 2, 3 |

`tests/synth/test_capability.py` already imports everything needed:

```python
import pytest
from luxaeterna.synth.capability import (Zone, SurfaceCapability,
                                         CapabilityRegistry, shroom_capability)
```

Add no imports to it in any task.

### Deviation from the spec, deliberate

Spec section 2.2 sketched two helpers (`_check_bounds`, `_check_coverage`).
This plan uses three, splitting rule 4 out as `_check_shroom_geometry`. A
function named `_check_coverage` that also enforced Shroom geometry would be
misnamed, and rule 4 is the rule most likely to be questioned later, so it
deserves its own name and docstring. Behavior is identical to the spec.

---

### Task 1: Rules 1 and 2, bounds and `primary`

Every zone lies inside the surface, zone names are unique, and a declared
`primary` means the whole surface. This is the task that stops the silent
`LightEngine` failure from spec section 1.2.

**Files:**
- Modify: `luxaeterna/synth/capability.py:1-28` (imports, new constants, new
  `__post_init__`, `zone()` uses the constant) and append helpers after the
  `SurfaceCapability` class
- Test: `tests/synth/test_capability.py` (append)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces, relied on by Tasks 2 and 3:
  - `_WHOLE_SURFACE: str = "primary"` module constant
  - `SurfaceCapability.__post_init__(self) -> None`, which calls its checks in
    a fixed order that later tasks extend
  - `_check_bounds(cap: SurfaceCapability) -> None`, raising `ValueError`

- [ ] **Step 1: Write the failing tests**

Append to `tests/synth/test_capability.py`:

```python
def test_shroom_capability_is_still_legal():
    """The canonical surface is the standing regression guard: ring(0,8) plus
    stem(8,4) tiles 12 px and primary spans it, so it satisfies every rule.
    This test passes before the validation lands and must keep passing after."""
    cap = shroom_capability()
    assert cap.pixel_count == 12
    assert [z.name for z in cap.zones] == ["ring", "stem", "primary"]


def test_a_non_positive_pixel_count_is_rejected():
    with pytest.raises(ValueError, match="pixel_count must be positive"):
        SurfaceCapability("x", 0, "GRB", [])


def test_a_zone_with_a_non_positive_count_is_rejected():
    with pytest.raises(ValueError, match="positive count"):
        SurfaceCapability("x", 12, "GRB", [Zone("ring", 0, 0)])


def test_a_zone_starting_before_the_surface_is_rejected():
    with pytest.raises(ValueError, match="before the surface"):
        SurfaceCapability("x", 12, "GRB", [Zone("ring", -1, 4)])


def test_a_zone_running_past_the_end_is_rejected():
    """Unvalidated this reaches LightEngine.render_into, whose slice comes up
    short so the blend raises a numpy broadcast error, which the per-binding
    `except Exception` swallows into `failed`. The instrument then renders
    nothing, forever, and looks like a broken instrument rather than a wrong
    declaration."""
    with pytest.raises(ValueError, match="past the surface's 12 px"):
        SurfaceCapability("x", 12, "GRB", [Zone("ring", 8, 8)])


def test_duplicate_zone_names_are_rejected():
    with pytest.raises(ValueError, match="duplicate zone names"):
        SurfaceCapability("x", 12, "GRB",
                          [Zone("ring", 0, 6), Zone("ring", 6, 6)])


def test_a_primary_that_is_not_the_whole_surface_is_rejected():
    """`primary` is the one name zone() synthesizes, so a primary meaning
    anything but the whole surface is a lie about this module's vocabulary."""
    with pytest.raises(ValueError, match="must span the whole surface"):
        SurfaceCapability("x", 12, "GRB", [Zone("primary", 0, 8)])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/chris/projects/luxaeterna && .venv/bin/python -m pytest tests/synth/test_capability.py -v`

Expected: `test_shroom_capability_is_still_legal` PASSES (it is a
characterization test, not a red test). The other six FAIL with
`Failed: DID NOT RAISE <class 'ValueError'>`.

- [ ] **Step 3: Add the constants and `__post_init__`**

In `luxaeterna/synth/capability.py`, after the `from dataclasses import
dataclass` line and before `class Zone`, add:

```python
_WHOLE_SURFACE = "primary"
```

Then give `SurfaceCapability` a `__post_init__` and make `zone()` use the
constant. The class becomes:

```python
@dataclass
class SurfaceCapability:
    surface_id: str
    pixel_count: int
    color_order: str
    zones: list[Zone]

    def __post_init__(self) -> None:
        _check_bounds(self)

    def zone(self, name: str) -> Zone:
        for z in self.zones:
            if z.name == name:
                return z
        if name == _WHOLE_SURFACE:
            return Zone(_WHOLE_SURFACE, 0, self.pixel_count)
        raise KeyError(f"surface {self.surface_id!r} has no zone {name!r}")
```

- [ ] **Step 4: Add `_check_bounds`**

Insert immediately after the `SurfaceCapability` class and before
`class CapabilityRegistry`:

```python
def _check_bounds(cap: SurfaceCapability) -> None:
    """Rules 1 and 2: every zone lies inside the surface, zone names are
    unique, and `primary` means the whole surface.

    Per-zone checks run in declaration order and report the first zone that
    fails, so the message points at what the author wrote."""
    if cap.pixel_count <= 0:
        raise ValueError(f"surface {cap.surface_id!r}: pixel_count must be "
                         f"positive, got {cap.pixel_count}")
    for z in cap.zones:
        if z.count <= 0:
            raise ValueError(f"surface {cap.surface_id!r}: zone {z.name!r} "
                             f"must have a positive count, got {z.count}")
        if z.start < 0:
            raise ValueError(f"surface {cap.surface_id!r}: zone {z.name!r} "
                             f"starts at {z.start}, before the surface")
        if z.start + z.count > cap.pixel_count:
            raise ValueError(f"surface {cap.surface_id!r}: zone {z.name!r} runs "
                             f"to pixel {z.start + z.count}, past the surface's "
                             f"{cap.pixel_count} px")
    names = [z.name for z in cap.zones]
    duplicates = sorted({n for n in names if names.count(n) > 1})
    if duplicates:
        raise ValueError(f"surface {cap.surface_id!r}: duplicate zone names: "
                         f"{duplicates}")
    primary = next((z for z in cap.zones if z.name == _WHOLE_SURFACE), None)
    if primary is not None and (primary.start,
                                primary.count) != (0, cap.pixel_count):
        raise ValueError(f"surface {cap.surface_id!r}: zone {_WHOLE_SURFACE!r} "
                         f"must span the whole surface (0, {cap.pixel_count}), "
                         f"got ({primary.start}, {primary.count})")
```

`_check_bounds` is defined after the class it annotates, which is fine:
`from __future__ import annotations` is already at the top of the file, and
the name is resolved at call time.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd /Users/chris/projects/luxaeterna && .venv/bin/python -m pytest tests/synth/test_capability.py -v`

Expected: all PASS, 10 tests (3 existing plus 7 new).

- [ ] **Step 6: Run both full suites**

Run: `cd /Users/chris/projects/luxaeterna && .venv/bin/python -m pytest tests -q`

Expected: `232 passed` (225 baseline plus 7 new).

Run: `cd /Users/chris/projects/mm-terrarium && .venv/bin/python -m pytest tests -q`

Expected: `1057 passed, 1 skipped`, unchanged. If anything fails here, stop:
it means a real capability violates rule 1 or 2, which contradicts the spec's
measured section 1.3 table and needs investigating, not working around.

- [ ] **Step 7: Commit**

```bash
cd /Users/chris/projects/luxaeterna && git add luxaeterna/synth/capability.py tests/synth/test_capability.py && git commit -m "feat(capability): reject zones that do not fit their surface

A SurfaceCapability declared a pixel count and a zone list and nothing
checked that the two agreed. A zone running past the end reached
LightEngine.render_into, whose short slice made the blend raise a numpy
broadcast error that the per-binding guard swallowed into \`failed\`, so
the instrument rendered nothing forever and looked broken rather than
mis-declared.

__post_init__ now enforces bounds (positive pixel_count, positive zone
counts, no zone before or past the surface, unique names) and that a
declared \`primary\` spans the whole surface, since primary is the one
name zone() synthesizes."
```

---

### Task 2: Rules 3 and 4, coverage and Shroom geometry

The rules that close the traced websim failure. Rule 3 catches the reviewer's
capability; rule 4 catches the shape rule 3 misses.

**Files:**
- Modify: `luxaeterna/synth/capability.py` (extend `__post_init__`, add two
  helpers plus one shared function)
- Test: `tests/synth/test_capability.py` (append)

**Interfaces:**
- Consumes from Task 1: `_WHOLE_SURFACE`, `SurfaceCapability.__post_init__`,
  `_check_bounds`.
- Produces, relied on by nothing later, but load-bearing for the rules:
  - `_SHROOM_ZONES: tuple[str, str] = ("ring", "stem")` module constant
  - `_first_tiling_fault(zones: list[Zone], pixel_count: int)` returning
    `("overlap", (str, str))`, `("gap", int)`, or `None`
  - `_check_coverage(cap: SurfaceCapability) -> None`
  - `_check_shroom_geometry(cap: SurfaceCapability) -> None`

- [ ] **Step 1: Write the failing tests**

Append to `tests/synth/test_capability.py`:

```python
def test_a_ring_that_does_not_cover_the_surface_is_rejected():
    """The traced case. A ring covering 8 of 20 px sends its tail pixels to
    websim's pos() fallback, which places them at x=328 to 496 on a 320 px
    canvas: the same truncation claude/websim-linear-surface-layout existed to
    fix, on the one path that branch could not touch. Caught by rule 3, since
    a ring alone does not tile 20 px."""
    with pytest.raises(ValueError, match="gap at pixel 8"):
        SurfaceCapability("x", 20, "GRB",
                          [Zone("ring", 0, 8), Zone("primary", 0, 20)])


def test_ring_and_stem_must_account_for_every_pixel_even_when_zones_tile():
    """The case rule 3 alone misses, and the reason rule 4 exists. These zones
    tile [0, 20) perfectly and pass every coverage check, and pixels 12 to 19
    still take websim's ring/stem fallback and still land off-canvas."""
    with pytest.raises(ValueError, match="ring/stem geometry leaves pixel 12"):
        SurfaceCapability("x", 20, "GRB",
                          [Zone("ring", 0, 8), Zone("stem", 8, 4),
                           Zone("tip", 12, 8), Zone("primary", 0, 20)])


def test_a_gap_between_zones_is_rejected():
    with pytest.raises(ValueError, match="gap at pixel 4"):
        SurfaceCapability("x", 12, "GRB", [Zone("a", 0, 4), Zone("b", 8, 4)])


def test_overlapping_zones_are_rejected():
    with pytest.raises(ValueError, match="zones overlap: 'a' and 'b'"):
        SurfaceCapability("x", 12, "GRB", [Zone("a", 0, 8), Zone("b", 4, 8)])


def test_a_capability_with_no_zones_is_legal():
    """Naming no zones at all is a complete declaration. Naming some but not
    all is the ambiguous middle rule 3 refuses."""
    cap = SurfaceCapability("x", 12, "GRB", [])
    assert cap.zone("primary") == Zone("primary", 0, 12)


def test_primary_alone_is_legal():
    """The shape harness/room_surface.py's to_capability() produces for a
    profile declaring no zones, and the one tests/synth/test_end_to_end.py has
    always used for its 1000 px array."""
    cap = SurfaceCapability("array", 1000, "GRB", [Zone("primary", 0, 1000)])
    assert cap.zone("primary").count == 1000


def test_primary_may_overlap_real_zones():
    """primary spans the whole surface by design, so it is exempt from the gap
    and overlap checks. Twelve of the thirteen capabilities either repo
    constructs have this shape, shroom_capability() included, and a blanket
    no-overlap rule would fail on the canonical surface itself."""
    cap = SurfaceCapability("x", 12, "GRB",
                            [Zone("ring", 0, 8), Zone("stem", 8, 4),
                             Zone("primary", 0, 12)])
    assert cap.zone("ring") == Zone("ring", 0, 8)


def test_zones_may_tile_out_of_declaration_order():
    """mm-terrarium's `odd` profile shape, RoomZone("b", 10, 20) declared
    before RoomZone("a", 0, 10). The coverage check sorts by start first, and
    declaration order is preserved on the way out."""
    cap = SurfaceCapability("odd", 30, "GRB",
                            [Zone("b", 10, 20), Zone("a", 0, 10),
                             Zone("primary", 0, 30)])
    assert [z.name for z in cap.zones] == ["b", "a", "primary"]
```

- [ ] **Step 2: Run the tests to verify the right ones fail**

Run: `cd /Users/chris/projects/luxaeterna && .venv/bin/python -m pytest tests/synth/test_capability.py -v`

Expected: the four `pytest.raises` tests FAIL with
`Failed: DID NOT RAISE <class 'ValueError'>`. The four positive tests
(`no_zones`, `primary_alone`, `primary_may_overlap`, `out_of_declaration_order`)
already PASS, since Task 1 permits all four shapes. They are there to pin that
rules 3 and 4 do not break them.

- [ ] **Step 3: Add the Shroom constant**

In `luxaeterna/synth/capability.py`, directly under `_WHOLE_SURFACE`:

```python
_SHROOM_ZONES = ("ring", "stem")
```

- [ ] **Step 4: Extend `__post_init__`**

Replace `SurfaceCapability.__post_init__`'s body:

```python
    def __post_init__(self) -> None:
        # Order is load-bearing. _check_coverage assumes every zone is
        # already inside the surface, and _check_shroom_geometry assumes the
        # non-`primary` zones already tile it.
        _check_bounds(self)
        _check_coverage(self)
        _check_shroom_geometry(self)
```

- [ ] **Step 5: Add the three coverage functions**

Insert after `_check_bounds` and before `class CapabilityRegistry`:

```python
def _first_tiling_fault(zones: list[Zone],
                        pixel_count: int) -> tuple[str, object] | None:
    """The first place `zones` fails to tile [0, pixel_count) exactly, as
    ("overlap", (name, name)) or ("gap", pixel), else None.

    Sorted by start before walking, so the answer is in position order and a
    caller's message does not depend on the order zones were declared in.
    Assumes _check_bounds has run, so no zone reaches past pixel_count and the
    cursor can only fall short of it, never overshoot."""
    cursor = 0
    previous = None
    for z in sorted(zones, key=lambda zone: (zone.start, zone.count)):
        if z.start < cursor:
            return "overlap", (previous.name, z.name)
        if z.start > cursor:
            return "gap", cursor
        cursor, previous = z.start + z.count, z
    if cursor != pixel_count:
        return "gap", cursor
    return None


def _check_coverage(cap: SurfaceCapability) -> None:
    """Rule 3: the non-`primary` zones either name nothing or name everything.

    `primary` is excluded from both the gap and the overlap check because it
    is an alias for the whole surface rather than a region of it, and it
    overlaps every real zone by design: shroom_capability() declares it that
    way, and both of mm-terrarium's adapters append it that way."""
    others = [z for z in cap.zones if z.name != _WHOLE_SURFACE]
    if not others:
        return
    fault = _first_tiling_fault(others, cap.pixel_count)
    if fault is None:
        return
    kind, detail = fault
    if kind == "overlap":
        raise ValueError(f"surface {cap.surface_id!r}: zones overlap: "
                         f"{detail[0]!r} and {detail[1]!r}")
    raise ValueError(f"surface {cap.surface_id!r}: zones do not tile its "
                     f"{cap.pixel_count} px: gap at pixel {detail}")


def _check_shroom_geometry(cap: SurfaceCapability) -> None:
    """Rule 4: a surface claiming Shroom geometry must be fully described by
    it.

    `ring` and `stem` are this module's canonical Shroom vocabulary, defined
    by shroom_capability() below, and the only zone names in the codebase with
    a non-linear physical meaning. A consumer laying out a ring and a stem has
    no defined position for a pixel in neither, which is exactly why
    backends/websim.py's pos() falls back to a fixed 24 px pitch and draws
    such a pixel off-canvas.

    Rule 3 does not give this. A ring, a stem and a third zone can tile the
    surface perfectly and still leave pixels the ring/stem layout cannot
    place."""
    shroom = [z for z in cap.zones if z.name in _SHROOM_ZONES]
    if not shroom or sum(z.count for z in shroom) == cap.pixel_count:
        return
    # _check_coverage has already established that the non-`primary` zones
    # tile the surface, so the shortfall is exactly the zones that are neither
    # Shroom nor `primary`, and the earliest of those is the first pixel this
    # geometry does not reach.
    unaccounted = min(z.start for z in cap.zones
                      if z.name not in _SHROOM_ZONES
                      and z.name != _WHOLE_SURFACE)
    raise ValueError(f"surface {cap.surface_id!r}: ring/stem geometry leaves "
                     f"pixel {unaccounted} unaccounted; a surface declaring a "
                     f"ring or a stem must describe every pixel with them")
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd /Users/chris/projects/luxaeterna && .venv/bin/python -m pytest tests/synth/test_capability.py -v`

Expected: all PASS, 18 tests (3 existing, 7 from Task 1, 8 new).

- [ ] **Step 7: Run both full suites**

Run: `cd /Users/chris/projects/luxaeterna && .venv/bin/python -m pytest tests -q`

Expected: `240 passed` (232 after Task 1 plus 8 new).

Run: `cd /Users/chris/projects/mm-terrarium && .venv/bin/python -m pytest tests -q`

Expected: `1057 passed, 1 skipped`, unchanged. This is the load-bearing check
for this task: every Room profile and fixture capability mm-terrarium builds
goes through rules 3 and 4 here.

- [ ] **Step 8: Commit**

```bash
cd /Users/chris/projects/luxaeterna && git add luxaeterna/synth/capability.py tests/synth/test_capability.py && git commit -m "feat(capability): require zones to account for the whole surface

Rule 3: the non-\`primary\` zones must either name nothing or tile
[0, pixel_count) exactly. \`primary\` is exempt from the gap and overlap
checks because it spans the whole surface by design, in twelve of the
thirteen capabilities either repo constructs.

Rule 4: if a ring or a stem is declared, those zones must account for
every pixel. Coverage alone does not give this. A ring, a stem and a
third zone can tile perfectly and still leave pixels that websim's
pos() has no position for, which is the fallback
claude/websim-linear-surface-layout could not reach.

Both traced cases are now rejected at construction: a ring covering 8
of 20 px by rule 3, and ring+stem+tip on 20 px by rule 4."
```

---

### Task 3: `load_config` locates its errors and loads atomically

**Files:**
- Modify: `luxaeterna/synth/capability.py` (import `_require`, rewrite
  `CapabilityRegistry.load_config`)
- Test: `tests/synth/test_capability.py` (append)

**Interfaces:**
- Consumes from Tasks 1 and 2: `SurfaceCapability.__post_init__` and all four
  rules, which `load_config` gets for free by constructing the dataclass.
- Consumes from `luxaeterna/synth/manifest.py`:
  `_require(mapping: dict, key: str, where: str)`, which returns
  `mapping[key]` or raises `KeyError(f"{where}: missing required field
  {key!r}")`.
- Produces: nothing later depends on this.

- [ ] **Step 1: Write the failing tests**

Append to `tests/synth/test_capability.py`:

```python
def test_load_config_names_the_surface_and_the_missing_field():
    """A capability config is the same kind of external, hand-authored
    contract light_manifest is, so it gets the same located errors rather than
    a bare KeyError with no indication of which surface."""
    reg = CapabilityRegistry()
    with pytest.raises(KeyError, match=r"surfaces\[1\].*pixel_count"):
        reg.load_config({"surfaces": [
            {"surface_id": "a", "pixel_count": 12, "color_order": "GRB",
             "zones": []},
            {"surface_id": "b", "color_order": "GRB", "zones": []}]})


def test_load_config_names_the_zone_index_for_a_missing_zone_field():
    reg = CapabilityRegistry()
    with pytest.raises(KeyError, match=r"surfaces\[0\] zones\[0\].*count"):
        reg.load_config({"surfaces": [
            {"surface_id": "a", "pixel_count": 12, "color_order": "GRB",
             "zones": [{"name": "ring", "start": 0}]}]})


def test_load_config_registers_nothing_when_any_surface_is_invalid():
    """Half a registry is worse than none: the caller has no way to tell which
    surfaces made it in."""
    reg = CapabilityRegistry()
    with pytest.raises(ValueError, match="past the surface's 12 px"):
        reg.load_config({"surfaces": [
            {"surface_id": "good", "pixel_count": 12, "color_order": "GRB",
             "zones": []},
            {"surface_id": "bad", "pixel_count": 12, "color_order": "GRB",
             "zones": [{"name": "ring", "start": 8, "count": 8}]}]})
    with pytest.raises(KeyError, match="unknown surface"):
        reg.get("good")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/chris/projects/luxaeterna && .venv/bin/python -m pytest tests/synth/test_capability.py -v`

Expected, three distinct failures:
- `..._names_the_surface_and_the_missing_field`: FAIL. A `KeyError` is raised,
  but its message is the bare `'pixel_count'`, so the `match` fails.
- `..._names_the_zone_index_for_a_missing_zone_field`: FAIL, same reason with
  the bare `'count'`.
- `..._registers_nothing_when_any_surface_is_invalid`: FAIL. The `ValueError`
  is raised as expected, then `reg.get("good")` returns the already-registered
  surface instead of raising, so the second `pytest.raises` reports
  `DID NOT RAISE`.

- [ ] **Step 3: Import `_require`**

In `luxaeterna/synth/capability.py`, under `from dataclasses import dataclass`
and above the constants:

```python
from .manifest import _require
```

`manifest.py` imports only `__future__` and `dataclasses`, so this cannot
cycle. It is a private name crossing sibling modules deliberately: sharing the
helper is what keeps the two external-contract error formats from drifting
apart in wording.

- [ ] **Step 4: Rewrite `load_config`**

Replace `CapabilityRegistry.load_config` entirely:

```python
    def load_config(self, config: dict) -> None:
        """Register every surface in `config`, or none of them.

        Built in full before anything is registered: a config whose fourth
        surface was invalid used to leave the first three registered and the
        caller holding a half-loaded registry with no way to tell which.
        Field errors are located the way light_manifest's already are, since a
        capability config is the same kind of external, hand-authored
        contract (see manifest._require). Zone validity is checked by
        SurfaceCapability itself."""
        loaded = []
        for idx, s in enumerate(config.get("surfaces", [])):
            where = f"capability config surfaces[{idx}]"
            loaded.append(SurfaceCapability(
                surface_id=_require(s, "surface_id", where),
                pixel_count=_require(s, "pixel_count", where),
                color_order=_require(s, "color_order", where),
                zones=[Zone(_require(z, "name", f"{where} zones[{zi}]"),
                            _require(z, "start", f"{where} zones[{zi}]"),
                            _require(z, "count", f"{where} zones[{zi}]"))
                       for zi, z in enumerate(s.get("zones", []))],
            ))
        for cap in loaded:
            self.register(cap)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd /Users/chris/projects/luxaeterna && .venv/bin/python -m pytest tests/synth/test_capability.py -v`

Expected: all PASS, 21 tests. Confirm the pre-existing
`test_registry_register_get_and_config_merge` is still among the passes: it
loads a 300 px surface whose only zone is `primary(0, 300)`, which satisfies
every rule.

- [ ] **Step 6: Run both full suites**

Run: `cd /Users/chris/projects/luxaeterna && .venv/bin/python -m pytest tests -q`

Expected: `243 passed` (240 after Task 2 plus 3 new).

Run: `cd /Users/chris/projects/mm-terrarium && .venv/bin/python -m pytest tests -q`

Expected: `1057 passed, 1 skipped`, unchanged. mm-terrarium never calls
`load_config`, so this run is confirming the new `manifest` import did not
disturb anything.

- [ ] **Step 7: Commit**

```bash
cd /Users/chris/projects/luxaeterna && git add luxaeterna/synth/capability.py tests/synth/test_capability.py && git commit -m "feat(capability): locate load_config errors and load atomically

A typo in a capability config surfaced as a bare KeyError naming the
field and not the surface. load_config now reuses manifest._require, so
a config file gets the same located errors light_manifest already does:
\"capability config surfaces[2]: missing required field 'pixel_count'\".

It also builds every surface before registering any. A config whose
fourth surface was invalid used to leave the first three registered and
the caller holding a half-loaded registry with no way to tell which."
```

---

## Verification after the final task

- [ ] **Confirm the traced failure is unreachable, end to end**

Run:

```bash
cd /Users/chris/projects/luxaeterna && .venv/bin/python -c "
from luxaeterna.synth.capability import SurfaceCapability, Zone
for name, zones in [
    ('reviewer traced case', [Zone('ring', 0, 8), Zone('primary', 0, 20)]),
    ('rule 4 only', [Zone('ring', 0, 8), Zone('stem', 8, 4),
                     Zone('tip', 12, 8), Zone('primary', 0, 20)]),
]:
    try:
        SurfaceCapability('x', 20, 'GRB', zones)
        print('NOT CAUGHT:', name)
    except ValueError as exc:
        print('caught  :', name, '->', exc)
"
```

Expected, both lines starting `caught  :`:

```
caught  : reviewer traced case -> surface 'x': zones do not tile its 20 px: gap at pixel 8
caught  : rule 4 only -> surface 'x': ring/stem geometry leaves pixel 12 unaccounted; a surface declaring a ring or a stem must describe every pixel with them
```

- [ ] **Confirm every real capability in both repos still constructs**

Run:

```bash
cd /Users/chris/projects/mm-terrarium && .venv/bin/python -c "
from harness.room_surface import to_capability, to_fixture_capability
from control.room_profile import room_profile
from control.rooms import RoomType
from luxaeterna.synth.capability import shroom_capability
print('shroom  :', shroom_capability().surface_id)
for rt in (RoomType.TEST, RoomType.DEMO):
    p = room_profile(rt)
    print('whole   :', to_capability(p).surface_id)
    for f in p.fixtures:
        print('fixture :', to_fixture_capability(p, f.name).surface_id)
"
```

Expected, no exception:

```
shroom  : ie0
whole   : room_test
fixture : room_test_main
fixture : room_test_accent
whole   : room_demo
fixture : room_demo_array
```

This covers `room_demo_array`, which is reachable in production from
`harness/o2_shroom.py` and `harness/room_simulator.py` but which no test in
either suite constructs.

- [ ] **Confirm the working tree is clean apart from the known exception**

Run: `cd /Users/chris/projects/luxaeterna && git status --short`

Expected: exactly one line, `M docs/deployment.md`, the pre-existing unrelated
change this plan must not touch.

---

## Success criteria

Mapped from spec section 8.

1. A capability whose non-`primary` zones leave a gap, overlap each other, or
   run past `pixel_count` raises `ValueError` at construction, naming the
   surface and the offending zone. Tasks 1 and 2.
2. A capability declaring a ring or a stem that does not account for every
   pixel raises `ValueError` at construction, including when its other zones
   make it tile. Task 2.
3. `CapabilityRegistry.load_config` raises a located error for a missing field
   and registers nothing when any surface is invalid. Task 3.
4. `shroom_capability()` and all twelve other capabilities in spec section
   1.3's table still construct. Verified by both suites at every task, plus
   the two post-task scripts above.
5. luxaeterna `243 passed` and mm-terrarium `1057 passed, 1 skipped`, with no
   existing test modified in either repo.
