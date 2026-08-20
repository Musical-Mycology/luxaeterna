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


def test_a_ring_that_does_not_cover_the_surface_is_rejected():
    """The traced case. A ring covering 8 of 20 px sends its tail pixels to
    websim's pos() fallback, which places them at x=328 to 496 on a 320 px
    canvas: the same truncation claude/websim-linear-surface-layout existed to
    fix, on the one path that branch could not touch. Caught by rule 3, since
    a ring alone does not tile 20 px."""
    with pytest.raises(ValueError, match="gap at pixel 8"):
        SurfaceCapability("x", 20, "GRB",
                          [Zone("ring", 0, 8), Zone("primary", 0, 20)])


def test_ring_and_stem_must_account_for_every_pixel_even_when_zones_tile():
    """The case rule 3 alone misses, and the reason rule 4 exists. These zones
    tile [0, 20) perfectly and pass every coverage check, and pixels 12 to 19
    still take websim's ring/stem fallback and still land off-canvas."""
    with pytest.raises(ValueError, match="ring/stem geometry leaves pixel 12"):
        SurfaceCapability("x", 20, "GRB",
                          [Zone("ring", 0, 8), Zone("stem", 8, 4),
                           Zone("tip", 12, 8), Zone("primary", 0, 20)])


def test_a_gap_between_zones_is_rejected():
    with pytest.raises(ValueError, match="gap at pixel 4"):
        SurfaceCapability("x", 12, "GRB", [Zone("a", 0, 4), Zone("b", 8, 4)])


def test_overlapping_zones_are_rejected():
    with pytest.raises(ValueError, match="zones overlap: 'a' and 'b'"):
        SurfaceCapability("x", 12, "GRB", [Zone("a", 0, 8), Zone("b", 4, 8)])


def test_a_capability_with_no_zones_is_legal():
    """Naming no zones at all is a complete declaration. Naming some but not
    all is the ambiguous middle rule 3 refuses."""
    cap = SurfaceCapability("x", 12, "GRB", [])
    assert cap.zone("primary") == Zone("primary", 0, 12)


def test_primary_alone_is_legal():
    """The shape harness/room_surface.py's to_capability() produces for a
    profile declaring no zones, and the one tests/synth/test_end_to_end.py has
    always used for its 1000 px array."""
    cap = SurfaceCapability("array", 1000, "GRB", [Zone("primary", 0, 1000)])
    assert cap.zone("primary").count == 1000


def test_primary_may_overlap_real_zones():
    """primary spans the whole surface by design, so it is exempt from the gap
    and overlap checks. Twelve of the thirteen capabilities either repo
    constructs have this shape, shroom_capability() included, and a blanket
    no-overlap rule would fail on the canonical surface itself."""
    cap = SurfaceCapability("x", 12, "GRB",
                            [Zone("ring", 0, 8), Zone("stem", 8, 4),
                             Zone("primary", 0, 12)])
    assert cap.zone("ring") == Zone("ring", 0, 8)


def test_zones_may_tile_out_of_declaration_order():
    """mm-terrarium's `odd` profile shape, RoomZone("b", 10, 20) declared
    before RoomZone("a", 0, 10). The coverage check sorts by start first, and
    declaration order is preserved on the way out."""
    cap = SurfaceCapability("odd", 30, "GRB",
                            [Zone("b", 10, 20), Zone("a", 0, 10),
                             Zone("primary", 0, 30)])
    assert [z.name for z in cap.zones] == ["b", "a", "primary"]


def test_load_config_names_the_surface_and_the_missing_field():
    """A capability config is the same kind of external, hand-authored
    contract light_manifest is, so it gets the same located errors rather than
    a bare KeyError with no indication of which surface."""
    reg = CapabilityRegistry()
    with pytest.raises(KeyError, match=r"surfaces\[1\].*pixel_count"):
        reg.load_config({"surfaces": [
            {"surface_id": "a", "pixel_count": 12, "color_order": "GRB",
             "zones": []},
            {"surface_id": "b", "color_order": "GRB", "zones": []}]})


def test_load_config_names_the_zone_index_for_a_missing_zone_field():
    reg = CapabilityRegistry()
    with pytest.raises(KeyError, match=r"surfaces\[0\] zones\[0\].*count"):
        reg.load_config({"surfaces": [
            {"surface_id": "a", "pixel_count": 12, "color_order": "GRB",
             "zones": [{"name": "ring", "start": 0}]}]})


def test_load_config_registers_nothing_when_any_surface_is_invalid():
    """Half a registry is worse than none: the caller has no way to tell which
    surfaces made it in."""
    reg = CapabilityRegistry()
    with pytest.raises(ValueError, match="past the surface's 12 px"):
        reg.load_config({"surfaces": [
            {"surface_id": "good", "pixel_count": 12, "color_order": "GRB",
             "zones": []},
            {"surface_id": "bad", "pixel_count": 12, "color_order": "GRB",
             "zones": [{"name": "ring", "start": 8, "count": 8}]}]})
    with pytest.raises(KeyError, match="unknown surface"):
        reg.get("good")
