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
