"""
HogNoise: NoiseParams to and from a plain dict, the form the vectors' manifest stores.
Package: packages/python/hog-noise/tests/test_params_dict
"""

import json

import pytest
from hog_noise_repo import VECTORS as VECTORS_ROOT

from hog_noise import CellularReturn, FractalType, NoiseParams, NoiseType, PerturbType, conformance


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


def test_every_case_in_the_vectors_round_trips():
    """Acceptance 7, on the committed manifest."""
    vectors = conformance.load(VECTORS_ROOT)
    assert len(vectors.cases) > 600
    for case in vectors.cases:
        assert NoiseParams.from_dict(case.params.to_dict()) == case.params, case.id


@pytest.mark.parametrize(
    "record",
    [
        {"octaves": 3.9},  # would truncate to 3
        {"seed": "12"},  # a string is not a number
        {"frequency": True},  # a bool is not a number
        {"seed": None},
        {"octaves": True},
    ],
)
def test_from_dict_refuses_a_value_of_the_wrong_type_naming_the_field(record):
    """Review on #16: a manifest for other languages is read as written, not converted."""
    (field,) = record
    with pytest.raises(ValueError, match=field):
        NoiseParams.from_dict(record)


def test_from_dict_takes_an_integer_for_a_float_field():
    assert NoiseParams.from_dict({"frequency": 1}).frequency == 1.0
