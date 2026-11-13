"""
HogNoise: the conformance harness, on small vectors built here and on the committed ones.
Package: tests/test_hog_noise/test_conformance
"""

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from hog_noise import conformance
from hog_noise.conformance import Bound


def make_vectors(root: Path, cases: list[dict], values: dict[str, np.ndarray], *, coords=None) -> Path:
    """A minimal vectors folder: one 3D point set ``p3`` and one 2D ``p2``, and the given cases and value files."""
    xs, ys, zs = coords or (
        np.array([10.0, -1000.0, 0.0, 5.0], np.float32),
        np.array([0.0, 2.0, 300.0, -1.0], np.float32),
        np.array([-3.0, 4.0, 0.5, 2000.0], np.float32),
    )
    files = {"points/x.f32": xs, "points/y.f32": ys, "points/z.f32": zs, **values}
    digests = {}
    for rel, array in files.items():
        data = np.asarray(array, "<f4").tobytes()
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(data)
        digests[rel] = hashlib.sha256(data).hexdigest()
    manifest = {
        "format": 1,
        "point_sets": {
            "p3": {"dims": 3, "count": len(xs), "axes": ["points/x.f32", "points/y.f32", "points/z.f32"]},
            "p2": {"dims": 2, "count": len(xs), "axes": ["points/x.f32", "points/z.f32"]},
        },
        "cases": cases,
        "files": digests,
    }
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return root


def a_case(case_id: str, file: str, *, point_set="p3", output="noise", compare=None, params=None) -> dict:
    return {
        "id": case_id,
        "set": case_id.split("/")[0],
        "source": {"library": "test", "feature": case_id.split("/")[2]},
        "params": params or {"seed": 1, "frequency": 0.01},
        "point_set": point_set,
        "output": output,
        "file": file,
        "compare": compare or {"kind": "points", "bound": {"scale": 0.0, "coordinate_scaled": False}},
    }


def test_a_plain_bound_is_the_same_at_every_point():
    allowed = Bound(1e-3).per_point(0.01, (np.array([0.0, 5000.0], np.float32),))
    assert allowed.tolist() == [1e-3, 1e-3]


def test_a_coordinate_scaled_bound_grows_with_each_points_own_magnitude():
    xs = np.array([10.0, -1000.0, 0.0], np.float32)
    ys = np.array([0.0, 0.0, 300.0], np.float32)
    allowed = Bound(2.0, coordinate_scaled=True).per_point(0.01, (xs, ys))
    assert allowed.tolist() == pytest.approx([2.0, 20.0, 6.0])  # max(1, max|axis| * f) per point


def test_a_negative_bound_is_refused():
    with pytest.raises(ValueError):
        Bound(-1e-6)


def test_the_normalised_difference_at_a_zero_bound_is_zero_or_infinity_never_nan():
    ratio = conformance.normalised_difference(np.array([0.0, 1e-9]), np.array([0.0, 0.0]))
    assert ratio.tolist() == [0.0, float("inf")]
    assert conformance.normalised_difference(np.array([5e-4]), np.array([1e-3])).tolist() == [0.5]


def test_load_reads_point_sets_and_cases(tmp_path):
    root = make_vectors(tmp_path, [a_case("hog/t/f/p3", "hog/f.f32")], {"hog/f.f32": np.arange(4, dtype=np.float32)})
    v = conformance.load(root)
    assert v.point_sets["p2"].dims == 2 and v.point_sets["p3"].axes[2].tolist() == [-3.0, 4.0, 0.5, 2000.0]
    case = v.case("hog/t/f/p3")
    assert case.values.tolist() == [0.0, 1.0, 2.0, 3.0] and case.params.seed == 1


def test_a_coordinate_changed_in_place_fails_load(tmp_path):
    root = make_vectors(tmp_path, [a_case("hog/t/f/p3", "hog/f.f32")], {"hog/f.f32": np.zeros(4, np.float32)})
    data = bytearray((root / "points/x.f32").read_bytes())
    data[0:4] = np.array([11.0], "<f4").tobytes()  # same size, one value changed
    (root / "points/x.f32").write_bytes(bytes(data))
    with pytest.raises(conformance.ConformanceError, match="points/x.f32"):
        conformance.load(root)


def test_a_file_without_a_digest_or_of_the_wrong_size_fails_load(tmp_path):
    root = make_vectors(tmp_path, [a_case("hog/t/f/p3", "hog/f.f32")], {"hog/f.f32": np.zeros(3, np.float32)})
    with pytest.raises(conformance.ConformanceError, match="3 float32 values, expected 4"):
        conformance.load(root)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    del manifest["files"]["hog/f.f32"]
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(conformance.ConformanceError, match="no digest"):
        conformance.load(root)


def test_a_warp_file_holds_count_times_dims_values(tmp_path):
    case = a_case("hog/t/w/p2/warp", "hog/w.f32", point_set="p2", output="warp")
    root = make_vectors(tmp_path, [case], {"hog/w.f32": np.arange(8, dtype=np.float32)})
    assert conformance.load(root).case("hog/t/w/p2/warp").values.shape == (4, 2)


def _name_outside(root: Path, rel: str, outside: Path) -> None:
    """Point the one case at ``rel`` and give it the digest of a real file outside the folder."""
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    manifest["cases"][0]["file"] = rel
    manifest["files"][rel] = hashlib.sha256(outside.read_bytes()).hexdigest()
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


@pytest.mark.parametrize("rel", ["../outside.f32", "/tmp/outside.f32", "C:/outside.f32", r"hog\..\..\outside.f32"])
def test_a_manifest_path_that_leaves_the_folder_is_refused_before_it_is_read(tmp_path, rel):
    """testing.md, Error paths: a path that leaves the root is refused before use. Its digest matching proves
    nothing, since the manifest supplies both."""
    outside = tmp_path / "outside.f32"
    outside.write_bytes(np.zeros(4, "<f4").tobytes())
    root = make_vectors(tmp_path / "v", [a_case("hog/t/f/p3", "hog/f.f32")], {"hog/f.f32": np.zeros(4, np.float32)})
    _name_outside(root, rel, outside)
    with pytest.raises(conformance.ConformanceError, match="inside the folder"):
        conformance.load(root)


def test_a_symlink_out_of_the_folder_is_refused(tmp_path):
    outside = tmp_path / "outside.f32"
    outside.write_bytes(np.zeros(4, "<f4").tobytes())
    root = make_vectors(tmp_path / "v", [a_case("hog/t/f/p3", "hog/f.f32")], {"hog/f.f32": np.zeros(4, np.float32)})
    try:
        (root / "hog" / "link.f32").symlink_to(outside)
    except OSError:
        pytest.skip("this system cannot make a symlink here")
    _name_outside(root, "hog/link.f32", outside)
    with pytest.raises(conformance.ConformanceError, match="resolves outside"):
        conformance.load(root)
