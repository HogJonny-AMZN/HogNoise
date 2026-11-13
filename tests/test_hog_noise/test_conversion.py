"""
HogNoise: nothing is lost converting the .npz vectors (acceptance 1 of the harness spec). Removed with the .npz files.
Package: tests/test_hog_noise/test_conversion
"""

from pathlib import Path

import numpy as np
import pytest

from hog_noise import (
    FractalType,
    NoiseParams,
    NoiseType,
    NumpySampler,
    conformance,
    parse_cellular_distance,
    parse_cellular_return,
    parse_domain_warp,
    parse_fractal_type,
    parse_noise_type,
    parse_perturb,
)

ROOT = Path(__file__).resolve().parents[2]
OLD = ROOT / "tests" / "vectors" / "noise"
NEW = ROOT / "vectors"
CLASSIC = ("simplex_none", "simplex_fbm", "simplex_billow", "simplex_rigidmulti")


@pytest.fixture(scope="module")
def vectors():
    return conformance.load(NEW)


def _npz():
    for library in ("fnl", "fns"):
        for path in sorted((OLD / library).glob("*.npz")):
            yield library, path.stem, np.load(path)


def test_every_coordinate_has_an_equal_point_file(vectors):
    old = np.load(OLD / "coords.npz")
    s3, g = vectors.point_sets["scatter_3d"].axes, vectors.point_sets["grid_y0"].axes
    for name, new in (("xs", s3[0]), ("ys", s3[1]), ("zs", s3[2]), ("grid_x", g[0]), ("grid_z", g[2])):
        assert np.array_equal(old[name], new), name
    assert not g[1].any()


def test_every_array_in_every_npz_has_a_case_with_equal_values(vectors):
    by_array = {}
    for case in vectors.cases:
        if case.set != "original":  # hog ids sort first and carry the same source keys
            continue
        by_array.setdefault((case.source["library"], case.source["feature"], case.source.get("array")), case)
    count = 0
    for library, feature, data in _npz():
        for array in data.files:
            if array == "params":
                continue
            case = by_array[(library, feature, array)]
            assert np.array_equal(case.values, data[array]), f"{library}/{feature}/{array}"
            count += 1
    assert count == 66 * 3 + 9 * 3 + 49 * 2 + 2


def _fnl_params(vp: dict) -> NoiseParams:
    """test_kernels._params_from at 0e0957d, unchanged."""
    rotation = {"improve_xy": 1, "improve_xz": 2}.get(vp.get("rotation_3d", ""), 0)
    return NoiseParams(
        seed=vp["seed"],
        frequency=vp["frequency"],
        noise_type=parse_noise_type(vp["noise_type"]),
        fractal_type=parse_fractal_type(vp["fractal_type"]),
        octaves=vp.get("octaves", 1),
        lacunarity=vp.get("lacunarity", 2.0),
        gain=vp.get("gain", 0.5),
        weighted_strength=vp.get("weighted_strength", 0.0),
        ping_pong_strength=vp.get("ping_pong_strength", 2.0),
        rotation_3d=rotation,
        cellular_distance=parse_cellular_distance(vp.get("cellular_distance", "euclideansq")),
        cellular_return=parse_cellular_return(vp.get("cellular_return", "distance")),
        cellular_jitter=vp.get("cellular_jitter", 1.0),
        domain_warp=parse_domain_warp(vp.get("domain_warp", "none")),
        domain_warp_amp=vp.get("domain_warp_amp", 1.0),
    )


def _old_params(library: str, feature: str, vp: dict, variant: str | None) -> NoiseParams | None:
    """The parameters each gating test in test_kernels.py builds today, ported unchanged from 0e0957d."""
    if library == "fnl":
        return _fnl_params(vp)
    if feature in CLASSIC and variant is None:
        return NoiseParams(
            seed=vp["seed"],
            frequency=vp["frequency"],
            noise_type=NoiseType.SIMPLEX_CLASSIC,
            fractal_type=parse_fractal_type(vp["fractal_type"]),
            octaves=vp.get("octaves", 1),
            lacunarity=vp.get("lacunarity", 2.0),
            gain=vp.get("gain", 0.5),
        )
    if feature.endswith("_billow"):
        return NoiseParams(
            seed=12345,
            frequency=0.01,
            noise_type=parse_noise_type(feature.split("_")[0]),
            fractal_type=FractalType.BILLOW,
            octaves=4,
        )
    if feature == "whitenoise_none":
        return NoiseParams(seed=vp["seed"], frequency=vp["frequency"], noise_type=NoiseType.WHITE_NOISE)
    if feature.startswith("cellular_"):
        return NoiseParams(
            seed=vp["seed"],
            frequency=vp["frequency"],
            noise_type=NoiseType.CELLULAR,
            cellular_distance=parse_cellular_distance(vp["cellular_distance"]),
            cellular_return=parse_cellular_return(vp["cellular_return"]),
            cellular_jitter=vp["cellular_jitter"],
            cellular_lookup_frequency=vp.get("lookup_frequency", 0.2),
        )
    if feature.startswith("simplex_fbm_perturb_"):
        return NoiseParams(
            seed=vp["seed"],
            frequency=vp["frequency"],
            noise_type=NoiseType.SIMPLEX_CLASSIC,
            fractal_type=FractalType.FBM,
            octaves=vp["octaves"],
            perturb=parse_perturb(vp["perturb_type"]),
            perturb_amp=vp["perturb_amp"],
            perturb_frequency=vp["perturb_frequency"],
            perturb_octaves=vp["perturb_octaves"],
            perturb_lacunarity=vp["perturb_lacunarity"],
            perturb_gain=vp["perturb_gain"],
            perturb_normalise_length=vp["perturb_normalise_length"],
        )
    if feature.startswith("genasgrid_"):
        return NoiseParams(
            seed=12345, frequency=0.01, noise_type=NoiseType.SIMPLEX_CLASSIC, fractal_type=FractalType.FBM, octaves=4
        )
    return None


def test_the_gating_parameters_sample_exactly_as_todays_tests_build_them(vectors):
    """Same output from the manifest's parameters as from today's test code, on the scatter points. By output, not
    by parameter equality: a field that does not change the output (octaves with no fractal) cannot fail it."""
    xs, ys, zs = vectors.point_sets["scatter_3d"].axes
    checked = 0
    for case in vectors.cases:
        if case.set != "original" or (case.compare["kind"] == "advisory" and case.source["library"] == "fns"):
            continue
        variant = case.id.partition("#")[2] or None
        old = _old_params(case.source["library"], case.source["feature"], case.source["params"], variant)
        assert old is not None, case.id
        ours = NumpySampler(case.params).sample_points(xs, ys, zs, np.empty(len(xs), np.float32))
        theirs = NumpySampler(old).sample_points(xs, ys, zs, np.empty(len(xs), np.float32))
        assert np.array_equal(ours, theirs), case.id
        checked += 1
    assert checked > 225, checked  # every FastNoiseLite case and the FastNoiseSIMD gating ones
