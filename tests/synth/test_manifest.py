"""Lux Aeterna — tests for the light_manifest schema."""

from __future__ import annotations

from luxaeterna.synth.manifest import LightManifest, LightInstrumentDecl, LightLane


def test_from_dict_round_trips_a_bloom_lane():
    m = LightManifest.from_dict({
        "instruments": [{
            "instrument": "bloom",
            "target": "primary",
            "params": {"hue": 0.3},
            "lanes": [
                {"source": "note", "dest": "trigger"},
                {"source": "cc:74", "dest": "hue", "curve": "exp"},
            ],
        }]
    })
    assert isinstance(m, LightManifest)
    decl = m.instruments[0]
    assert isinstance(decl, LightInstrumentDecl)
    assert decl.instrument == "bloom" and decl.target == "primary"
    assert decl.params == {"hue": 0.3}
    assert decl.lanes[1] == LightLane("cc:74", "hue", "exp")


def test_v1_dict_still_parses_with_empty_v2_fields():
    m = LightManifest.from_dict({"instruments": [
        {"instrument": "bloom", "target": "primary"}]})
    assert m.bit_name == "" and m.bit_version == "" and m.role == ""
    assert m.welcome is None


def test_v2_fields_and_welcome_parse():
    m = LightManifest.from_dict({
        "bit_name": "chorus", "bit_version": "1.2", "role": "drums",
        "welcome": {"instrument": "bloom", "params": {"hue": 0.1},
                    "duration": 0.8},
        "instruments": []})
    assert m.bit_name == "chorus" and m.role == "drums"
    assert m.welcome.instrument == "bloom"
    assert m.welcome.params == {"hue": 0.1}
    assert m.welcome.duration == 0.8


def test_welcome_duration_defaults():
    m = LightManifest.from_dict({
        "welcome": {"instrument": "bloom"}, "instruments": []})
    assert m.welcome.duration == 1.5 and m.welcome.params == {}
