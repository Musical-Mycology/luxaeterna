"""Lux Aeterna — tests for surface capability descriptors + registry."""

from __future__ import annotations

import pytest
from luxaeterna.synth.capability import (Zone, SurfaceCapability,
                                         CapabilityRegistry, shroom_capability)


def test_zone_lookup_and_primary_default():
    cap = SurfaceCapability("ie3", 12, "GRB",
                            [Zone("ring", 0, 8), Zone("stem", 8, 4)])
    assert cap.zone("ring") == Zone("ring", 0, 8)
    assert cap.zone("primary") == Zone("primary", 0, 12)   # synthesized
    with pytest.raises(KeyError):
        cap.zone("nope")


def test_registry_register_get_and_config_merge():
    reg = CapabilityRegistry()
    reg.register(shroom_capability("ie3"))
    assert reg.get("ie3").pixel_count == 12
    reg.load_config({"surfaces": [
        {"surface_id": "array", "pixel_count": 300, "color_order": "GRB",
         "zones": [{"name": "primary", "start": 0, "count": 300}]}]})
    assert reg.get("array").pixel_count == 300
