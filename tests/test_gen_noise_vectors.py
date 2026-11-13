"""
HogNoise: the vector writer and the rules that make a captured array a case.
Package: tests/test_gen_noise_vectors
"""

from pathlib import Path

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


def test_the_hog_set_is_one_case_per_distinct_parameters_point_set_and_output(tmp_path):
    record = {"noise_type": "simplex", "fractal_type": "billow", "seed": 12345, "frequency": 0.01, "octaves": 4}
    arrays = {"scatter_3d": np.zeros(4096, np.float32)}
    twin = dict(record, noise_type="perlin")
    captured = [
        ("fns", "simplex_billow", record, arrays),
        ("fns", "perlin_billow", twin, arrays),
        ("fns", "perlin_billow2", twin, arrays),
    ]
    gen.write_originals(tmp_path, captured, coords())
    gen.generate_hog(tmp_path)
    v = conformance.load(tmp_path)
    hog = [c.id for c in v.cases if c.set == "hog"]
    assert hog == [
        "hog/fns/perlin_billow/scatter_3d",  # perlin_billow2 has the same parameters: no second case
        "hog/fns/simplex_billow/scatter_3d",
        "hog/fns/simplex_billow/scatter_3d#shape",
    ]
    sample, warp = conformance.renderings("numpy")
    assert conformance.check(sample, v, warp=warp).ok


def _two_features(tmp_path):
    record = {"noise_type": "perlin", "fractal_type": "fbm", "seed": 1, "frequency": 0.01, "octaves": 3}
    arrays = {"scatter_3d": np.zeros(4096, np.float32)}
    captured = [("fns", "perlin_fbm", record, arrays), ("fns", "value_fbm", dict(record, noise_type="value"), arrays)]
    gen.write_originals(tmp_path, captured, coords())
    gen.generate_hog(tmp_path)
    return captured


def test_a_regeneration_that_fails_part_way_leaves_the_folder_as_it_was(tmp_path, monkeypatch):
    """Review on #16: the hog folder was deleted before anything new was written, so a crash left it unloadable."""
    _two_features(tmp_path)
    before = (tmp_path / "manifest.json").read_bytes()
    sample, warp = conformance.renderings("numpy")
    calls = []

    def flaky(params, xs, ys, zs):
        calls.append(params)
        if len(calls) == 2:
            raise RuntimeError("the kernel fell over")
        return sample(params, xs, ys, zs)

    monkeypatch.setattr(gen.conformance, "renderings", lambda name: (flaky, warp))
    with pytest.raises(RuntimeError):
        gen.generate_hog(tmp_path)
    assert (tmp_path / "manifest.json").read_bytes() == before
    assert len(conformance.load(tmp_path).cases) == 4, "the folder still loads, hog set and all"
    assert not list(tmp_path.parent.glob(f"{tmp_path.name}.hog-*")), "no staging folder left behind"
    monkeypatch.undo()
    assert len(gen.generate_hog(tmp_path)) == 2


def test_a_rerun_regenerates_even_when_the_hog_files_are_gone(tmp_path):
    _two_features(tmp_path)
    for f in (tmp_path / "hog").rglob("*.f32"):
        f.unlink()
    assert len(gen.generate_hog(tmp_path)) == 2
    conformance.load(tmp_path)


def test_new_captures_cannot_move_the_coordinates_kept_cases_were_sampled_on(tmp_path):
    """Review on #16: the FastNoiseSIMD originals rely on the point files never changing under them."""
    captured = _two_features(tmp_path)
    moved = coords()
    moved["xs"] = moved["xs"] + np.float32(1.0)
    with pytest.raises(ValueError, match="scatter_x.f32"):
        gen.write_originals(tmp_path, captured[:1], moved)
    gen.write_originals(tmp_path, captured[:1], coords())  # the same coordinates: fine
    gen.write_originals(tmp_path, captured, moved)  # every original captured again on the new ones: fine


@pytest.mark.parametrize("step", ["move the old aside", "move the new in", "write the manifest"])
def test_a_swap_that_fails_raises_and_leaves_the_folder_loadable(tmp_path, monkeypatch, step):
    """Review on #17: a delete that failed silently (a Windows handle) once reported success over a folder that would
    not load. Each step of the swap now raises, and the old hog set is put back."""
    _two_features(tmp_path)
    before = (tmp_path / "manifest.json").read_bytes()
    real_rename, real_manifest = Path.rename, gen.write_manifest
    renames = []

    def failing_rename(self, target):
        renames.append(self.name)
        if (step == "move the old aside" and len(renames) == 1) or (step == "move the new in" and len(renames) == 2):
            raise PermissionError(f"held open: {self}")
        return real_rename(self, target)

    def failing_manifest(*args, **kwargs):
        raise OSError("disk full")

    # New values that differ from the committed ones, so a half-done swap (new files, old manifest) cannot load
    sample, warp = conformance.renderings("numpy")

    def shifted(params, xs, ys, zs):
        return sample(params, xs, ys, zs) + np.float32(1.0)

    monkeypatch.setattr(gen.conformance, "renderings", lambda name: (shifted, warp))
    monkeypatch.setattr(Path, "rename", failing_rename)
    if step == "write the manifest":
        monkeypatch.setattr(gen, "write_manifest", failing_manifest)
    with pytest.raises(OSError):
        gen.generate_hog(tmp_path)
    monkeypatch.undo()
    assert (tmp_path / "manifest.json").read_bytes() == before
    assert len(conformance.load(tmp_path).cases) == 4, "the old hog set is back and the folder loads"
    assert not list(tmp_path.parent.glob(f"{tmp_path.name}.hog-*")), "nothing left beside the folder"
    assert real_manifest is gen.write_manifest
