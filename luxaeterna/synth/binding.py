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
