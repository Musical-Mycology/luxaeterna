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


def test_registry_get_unknown_surface_raises():
    reg = CapabilityRegistry()
    with pytest.raises(KeyError):
        reg.get("nope")


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
