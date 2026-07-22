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


def _require(mapping: dict, key: str, where: str):
    """Fetch a required field, raising a KeyError that names the field and its
    location (``light_manifest`` is an external contract — bare KeyErrors are
    useless to a Bit author debugging a typo)."""
    try:
        return mapping[key]
    except KeyError:
        raise KeyError(f"{where}: missing required field {key!r}") from None


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
        instruments = []
        for idx, i in enumerate(d.get("instruments", [])):
            where = f"light_manifest instruments[{idx}]"
            lanes = []
            for lidx, l in enumerate(i.get("lanes", [])):
                lane_where = f"{where} lanes[{lidx}]"
                lanes.append(LightLane(
                    source=_require(l, "source", lane_where),
                    dest=_require(l, "dest", lane_where),
                    curve=l.get("curve", "linear"),
                ))
            instruments.append(LightInstrumentDecl(
                instrument=_require(i, "instrument", where),
                target=_require(i, "target", where),
                params=dict(i.get("params", {})),
                lanes=lanes,
            ))
        w = d.get("welcome")
        welcome = SignatureDecl(
            instrument=_require(w, "instrument", "light_manifest welcome"),
            params=dict(w.get("params", {})),
            duration=w.get("duration", 1.5),
        ) if w else None
        return cls(
            instruments=instruments,
            bit_name=d.get("bit_name", ""),
            bit_version=d.get("bit_version", ""),
            role=d.get("role", ""),
            welcome=welcome,
        )
