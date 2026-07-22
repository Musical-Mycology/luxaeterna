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
