"""Lux Aeterna — tests for the light_manifest schema."""

from __future__ import annotations

import pytest
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


def test_from_dict_missing_fields_are_contextual():
    # Missing required fields must raise a KeyError naming the field + its index
    # path, not a bare KeyError('instrument') (light_manifest is an external
    # contract consumed by mm-terrarium).
    with pytest.raises(KeyError, match=r"instruments\[0\].*instrument"):
        LightManifest.from_dict({"instruments": [{"target": "primary"}]})
    with pytest.raises(KeyError, match=r"lanes\[0\].*source"):
        LightManifest.from_dict({"instruments": [{
            "instrument": "bloom", "target": "primary",
            "lanes": [{"dest": "hue"}]}]})
