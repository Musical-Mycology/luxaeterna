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
class SignatureDecl:
    """A declarable one-shot light gesture (e.g. a per-role welcome)."""
    instrument: str             # registered instrument name
    params: dict = field(default_factory=dict)
    duration: float = 1.5       # seconds until done


@dataclass
class LightManifest:
    instruments: list[LightInstrumentDecl] = field(default_factory=list)
    bit_name: str = ""          # Bit identity, for telemetry/log context
    bit_version: str = ""
    role: str = ""              # role this manifest was resolved for
    welcome: SignatureDecl | None = None   # plays in LOADING instead of sys:loaded

    @classmethod
    def from_dict(cls, d: dict) -> "LightManifest":
        w = d.get("welcome")
        return cls(
            instruments=[
                LightInstrumentDecl(
                    instrument=i["instrument"],
                    target=i["target"],
                    params=dict(i.get("params", {})),
                    lanes=[LightLane(l["source"], l["dest"], l.get("curve", "linear"))
                           for l in i.get("lanes", [])],
                )
                for i in d.get("instruments", [])
            ],
            bit_name=d.get("bit_name", ""),
            bit_version=d.get("bit_version", ""),
            role=d.get("role", ""),
            welcome=SignatureDecl(w["instrument"], dict(w.get("params", {})),
                                  w.get("duration", 1.5)) if w else None,
        )
