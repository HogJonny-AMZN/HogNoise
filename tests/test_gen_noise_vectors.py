"""
HogNoise: the vector writer and the rules that make a captured array a case.
Package: tests/test_gen_noise_vectors
"""

import numpy as np
import pytest

import _tools_path  # noqa: F401  (puts tools/ on sys.path)
import gen_noise_vectors as gen
from hog_noise import NoiseType, conformance


def coords():
    rng = np.random.RandomState(1)
    xs, ys, zs = (rng.uniform(-100, 100, 4096).astype(np.float32) for _ in range(3))
    g = np.linspace(-10, 10, 128, dtype=np.float32)
    gx, gz = np.meshgrid(g, g)
    return {"xs": xs, "ys": ys, "zs": zs, "grid_x": gx.ravel(), "grid_z": gz.ravel()}


def test_fns_simplex_is_classic_except_in_the_billow_shape_variant():
    record = {"noise_type": "simplex", "fractal_type": "billow", "seed": 12345, "frequency": 0.01, "octaves": 4}
    assert gen.params_for("fns", "simplex_billow", record).noise_type is NoiseType.SIMPLEX_CLASSIC
    assert gen.params_for("fns", "simplex_billow", record, "shape").noise_type is NoiseType.OPEN_SIMPLEX2
    assert gen.params_for("fnl", "simplex_fbm", dict(record, fractal_type="fbm")).noise_type is NoiseType.OPEN_SIMPLEX2


def test_the_rules_carry_todays_limits():
    assert gen.compare_for("fns", "simplex_fbm", "scatter_3d") == {
        "kind": "points",
        "bound": {"scale": 2e-4, "coordinate_scaled": False},
        "min_correlation": 0.9999,
    }
    assert gen.compare_for("fns", "simplex_fbm", "grid_3d")["bound"]["scale"] == 2e-4
    assert gen.compare_for("fns", "simplex_billow", "scatter_3d", "shape")["kind"] == "shape"
    assert gen.compare_for("fnl", "perlin_fbm", "grid_3d") == {"kind": "advisory"}
    assert gen.compare_for("fnl", "warp_basicgrid_none", "warp_2d")["bound"]["scale"] == 4e-3
    assert gen.compare_for("fns", "perlin_fbm", "scatter_3d") == {"kind": "advisory"}  # read by no test today


def test_simplex_billow_scatter_gives_two_cases_on_one_file():
    record = {"noise_type": "simplex", "fractal_type": "billow", "seed": 12345, "frequency": 0.01, "octaves": 4}
    cases = gen.original_cases("fns", "simplex_billow", record, ["scatter_3d", "grid_3d"])
    ids = [c["id"] for c in cases]
    assert ids == [
        "original/fns/simplex_billow/scatter_3d",
        "original/fns/simplex_billow/scatter_3d#shape",
        "original/fns/simplex_billow/grid_y0",
    ]
    assert cases[0]["file"] == cases[1]["file"] == "original/fns/simplex_billow.scatter_3d.f32"


def test_written_vectors_load(tmp_path):
    record = {"noise_type": "perlin", "fractal_type": "fbm", "seed": 1, "frequency": 0.01, "octaves": 3}
    arrays = {"scatter_3d": np.zeros(4096, np.float32), "grid_3d": np.ones(16384, np.float32)}
    gen.write_originals(tmp_path, [("fns", "perlin_fbm", record, arrays)], coords())
    v = conformance.load(tmp_path)
    assert v.case("original/fns/perlin_fbm/grid_y0").values.max() == 1.0
    assert v.point_sets["grid_y0"].axes[1].tolist() == [0.0] * 16384
    assert v.point_sets["genasgrid_1.0_0.5_2.0"].count == 16384


def test_an_unmapped_record_is_an_error_not_a_skip(tmp_path):
    record = {"noise_type": "noise_of_the_spheres", "fractal_type": "none", "seed": 1, "frequency": 0.01}
    with pytest.raises(ValueError):
        gen.write_originals(tmp_path, [("fns", "x", record, {"scatter_3d": np.zeros(4096, np.float32)})], coords())
