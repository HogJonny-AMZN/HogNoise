"""
HogNoise: the noise parameter families, the gallery's sheets and the viewer's presets, hold together.
Package: tests/test_noise_kernels/test_families
"""

from hog_noise import (
    FAMILIES,
    IMPLEMENTED_FRACTAL_TYPES,
    IMPLEMENTED_NOISE_TYPES,
    NOISE_TYPE_NAMES,
    NoiseParams,
    NumpySampler,
    all_presets,
    enum_name,
)


def test_all_presets_flattens_the_families_in_order_with_their_captions():
    presets = all_presets()
    expected = [(key, caption) for key, _title, builder, _cols in FAMILIES for caption, _p in builder()]
    assert [(family, caption) for family, caption, _p in presets] == expected
    assert len(presets) == len(expected) > 60


def test_every_preset_is_a_valid_record_that_samples():
    for family, caption, params in all_presets():
        assert isinstance(params, NoiseParams), (family, caption)
        assert params.noise_type in IMPLEMENTED_NOISE_TYPES, (family, caption)
        assert params.fractal_type in IMPLEMENTED_FRACTAL_TYPES, (family, caption)
        grid = NumpySampler(params).sample_grid((-4, 0, -4), (8, 1, 8))
        assert grid.shape == (8, 1, 8) and grid.dtype.name == "float32", (family, caption)


def test_every_implemented_noise_type_has_a_preset_captioned_by_its_name():
    captions = {caption for family, caption, _p in all_presets() if family == "types"}
    for nt in IMPLEMENTED_NOISE_TYPES:
        assert enum_name(NOISE_TYPE_NAMES, nt) in captions, nt.name


def test_enum_name_prefers_the_first_spelling_in_the_table():
    assert enum_name({"simplex": 1, "opensimplex2": 1}, 1) == "simplex"
    assert enum_name({"a": 1}, 2) == "2"
