"""Lux Aeterna — surface capability descriptors + registry (self-describe ⊕ config)."""

from __future__ import annotations

from dataclasses import dataclass

_WHOLE_SURFACE = "primary"


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
        _check_bounds(self)

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
