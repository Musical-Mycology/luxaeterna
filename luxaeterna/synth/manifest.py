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
