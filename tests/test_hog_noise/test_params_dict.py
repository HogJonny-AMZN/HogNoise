"""
HogNoise: NoiseParams to and from a plain dict, the form the vectors' manifest stores.
Package: tests/test_hog_noise/test_params_dict
"""

import json

import pytest

from hog_noise import CellularReturn, FractalType, NoiseParams, NoiseType, PerturbType


def test_to_dict_names_every_field_with_enums_as_member_names():
    d = NoiseParams(noise_type=NoiseType.PERLIN, fractal_type=FractalType.FBM, octaves=4).to_dict()
    assert d["noise_type"] == "PERLIN" and d["fractal_type"] == "FBM" and d["octaves"] == 4
    assert d["cellular_return"] == "DISTANCE" and type(d["frequency"]) is float and type(d["seed"]) is int
    assert set(d) == set(NoiseParams.__dataclass_fields__)
    json.dumps(d)  # plain JSON, no enum objects


def test_from_dict_round_trips_and_fills_defaults():
    p = NoiseParams(
        seed=7,
        frequency=0.02,
        noise_type=NoiseType.CELLULAR,
        cellular_return=CellularReturn.NOISE_LOOKUP,
        perturb=PerturbType.GRADIENT,
    )
    assert NoiseParams.from_dict(p.to_dict()) == p
    assert NoiseParams.from_dict({"seed": 7}) == NoiseParams(seed=7)


def test_from_dict_rejects_an_unknown_key_and_an_unknown_member_name():
    with pytest.raises(ValueError, match="colour"):
        NoiseParams.from_dict({"colour": "red"})
    with pytest.raises(ValueError, match="NOISE_OF_THE_SPHERES"):
        NoiseParams.from_dict({"noise_type": "NOISE_OF_THE_SPHERES"})
    with pytest.raises(ValueError, match="noise_type"):
        NoiseParams.from_dict({"noise_type": 2})  # a number is not a member name
