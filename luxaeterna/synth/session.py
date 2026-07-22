"""Lux Aeterna — session setup: resolve a manifest against a surface and wire O2 input."""

from __future__ import annotations

from .binding import ActiveBinding, resolve
from .capability import SurfaceCapability
from .manifest import LightManifest
from .o2bridge import O2Bridge


def build_session(manifest: LightManifest,
                  cap: SurfaceCapability) -> tuple[list[ActiveBinding], O2Bridge]:
    """Resolve every instrument declaration against ``cap`` and return the
    active bindings plus an O2 bridge fanning inbound MIDI across them."""
    bindings = [resolve(decl, cap) for decl in manifest.instruments]
    return bindings, O2Bridge(bindings)
