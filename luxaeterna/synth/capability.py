"""Lux Aeterna — surface capability descriptors + registry (self-describe ⊕ config)."""

from __future__ import annotations

from dataclasses import dataclass

from .manifest import _require

_WHOLE_SURFACE = "primary"
_SHROOM_ZONES = ("ring", "stem")


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

    def __post_init__(self) -> None:
        # Order is load-bearing. _check_coverage assumes every zone is
        # already inside the surface, and _check_shroom_geometry assumes the
        # non-`primary` zones already tile it.
        _check_bounds(self)
        _check_coverage(self)
        _check_shroom_geometry(self)

    def zone(self, name: str) -> Zone:
        for z in self.zones:
            if z.name == name:
                return z
        if name == _WHOLE_SURFACE:
            return Zone(_WHOLE_SURFACE, 0, self.pixel_count)
        raise KeyError(f"surface {self.surface_id!r} has no zone {name!r}")


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


def shroom_capability(surface_id: str = "ie0") -> SurfaceCapability:
    """The canonical 12-LED Shroom: 8-LED ring + 4-LED stem, GRB."""
    return SurfaceCapability(
        surface_id=surface_id, pixel_count=12, color_order="GRB",
        zones=[Zone("ring", 0, 8), Zone("stem", 8, 4), Zone("primary", 0, 12)],
    )
