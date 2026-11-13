"""
HogNoise: the conformance harness, on small vectors built here and on the committed ones.
Package: tests/test_hog_noise/test_conformance
"""

import hashlib
import json
import subprocess
import sys
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


def _values(case_values):
    """A sample callable that returns fixed values whatever it is asked."""

    def sample(params, xs, ys, zs):
        return np.asarray(case_values, np.float32)

    return sample


def test_points_pass_and_fail_by_the_bound_and_report_the_ratio(tmp_path):
    ref = np.array([0.1, 0.2, 0.3, 0.4], np.float32)
    bound = {"kind": "points", "bound": {"scale": 1e-3, "coordinate_scaled": False}}
    root = make_vectors(tmp_path, [a_case("original/t/f/p3", "o/f.f32", compare=bound)], {"o/f.f32": ref})
    ok = conformance.check(_values(ref + np.float32(5e-4)), root, reference="original")
    assert ok.ok and ok.results[0].status == "pass" and ok.results[0].max_normalised == pytest.approx(0.5, rel=1e-3)
    bad = conformance.check(_values(ref + np.float32(2e-3)), root, reference="original")
    assert not bad.ok and bad.results[0].status == "fail"


def test_bound_zero_reports_zero_on_a_pass_and_infinity_on_a_fail(tmp_path):
    ref = np.array([0.1, 0.2, 0.3, 0.4], np.float32)
    root = make_vectors(tmp_path, [a_case("hog/t/f/p3", "h/f.f32")], {"h/f.f32": ref})
    assert conformance.check(_values(ref), root).results[0].max_normalised == 0.0
    nudged = ref.copy()
    nudged[2] = np.nextafter(nudged[2], np.float32(1.0))  # one ulp
    result = conformance.check(_values(nudged), root).results[0]
    assert result.status == "fail" and result.max_normalised == float("inf")


def test_a_coordinate_scaled_bound_is_per_point_not_per_band(tmp_path):
    """The spike's flaw: a difference inside the bound at the band's far edge, outside its own point's."""
    ref = np.zeros(4, np.float32)
    ours = np.array([0.05, 0.0, 0.0, 0.0], np.float32)  # at x = 10, where f = 0.01 allows 0.01 * max(1, 0.1)
    root = make_vectors(tmp_path, [a_case("hog/t/f/p3", "h/f.f32")], {"h/f.f32": ref})
    loose = conformance.check(_values(ours), root, bound=Bound(0.01, coordinate_scaled=True))
    assert not loose.ok, "per point, 0.05 > 0.01 at x = 10, though the set's largest point would allow 0.2"


def test_min_correlation_and_within_are_checked_too(tmp_path):
    ref = np.array([0.1, 0.2, 0.3, 0.4], np.float32)
    rule = {
        "kind": "points",
        "bound": {"scale": 1.0, "coordinate_scaled": False},
        "min_correlation": 0.99,
        "within": {"scale": 1e-4, "fraction": 0.75},
    }
    root = make_vectors(tmp_path, [a_case("original/t/f/p3", "o/f.f32", compare=rule)], {"o/f.f32": ref})
    assert conformance.check(_values(ref[::-1]), root, reference="original").results[0].status == "fail"  # corr -1
    two_off = ref + np.array([0, 0, 1e-3, 1e-3], np.float32)
    assert conformance.check(_values(two_off), root, reference="original").results[0].status == "fail"  # 50% within


def test_shape_checks_range_mean_std_ratio_and_finite(tmp_path):
    ref = np.array([-0.5, 0.0, 0.5, 0.25], np.float32)
    rule = {"kind": "shape", "range": [-1.05, 1.05], "mean_within": 0.2, "std_within": 0.2, "finite": True}
    root = make_vectors(tmp_path, [a_case("original/t/f/p3", "o/f.f32", compare=rule)], {"o/f.f32": ref})
    assert conformance.check(_values(ref * 1.1), root, reference="original").ok
    assert not conformance.check(_values(ref * 3), root, reference="original").ok  # out of range
    assert not conformance.check(_values([0, np.nan, 0, 0]), root, reference="original").ok


def test_advisory_never_fails_and_carries_the_review_rule(tmp_path):
    ref = np.linspace(-1, 1, 4).astype(np.float32)
    rule = {"kind": "advisory"}
    root = make_vectors(tmp_path, [a_case("original/t/f/p3", "o/f.f32", compare=rule)], {"o/f.f32": ref})
    report = conformance.check(_values(ref[::-1]), root, reference="original")  # anti-correlated
    result = report.results[0]
    assert report.ok and result.kind == "advisory" and result.needs_review and result.verdict is None
    within_tight = conformance.check(_values(ref), root, reference="original").results[0]
    assert within_tight.status == "exact" and not within_tight.needs_review


def test_a_low_correlation_within_tight_still_needs_review(tmp_path):
    """compare.ComparisonStats.needs_review: correlation below 0.99 is review, even inside `tight`."""
    ref = np.array([1e-5, 0.0, 1e-5, 0.0], np.float32)
    advisory = {"kind": "advisory"}
    root = make_vectors(tmp_path, [a_case("original/t/f/p3", "o/f.f32", compare=advisory)], {"o/f.f32": ref})
    result = conformance.check(_values(ref[::-1]), root, reference="original").results[0]
    assert result.status in ("float32", "tight") and result.needs_review


def test_not_implemented_is_unsupported_and_a_missing_warp_is_skipped(tmp_path):
    cases = [a_case("hog/t/f/p3", "h/f.f32"), a_case("hog/t/w/p2/warp", "h/w.f32", point_set="p2", output="warp")]
    root = make_vectors(tmp_path, cases, {"h/f.f32": np.zeros(4, np.float32), "h/w.f32": np.zeros(8, np.float32)})

    def partial(params, xs, ys, zs):
        raise NotImplementedError("not in this port")

    report = conformance.check(partial, root)
    assert report.ok and not report.complete
    assert sorted(r.status for r in report.results) == ["skipped", "unsupported"]


def test_select_and_reference_choose_the_cases(tmp_path):
    cases = [a_case("hog/t/f/p3", "h/f.f32"), a_case("original/t/f/p3", "o/f.f32")]
    root = make_vectors(tmp_path, cases, {"h/f.f32": np.zeros(4, np.float32), "o/f.f32": np.zeros(4, np.float32)})
    zero = _values(np.zeros(4, np.float32))
    assert [r.id for r in conformance.check(zero, root, reference="both").results] == ["hog/t/f/p3", "original/t/f/p3"]
    assert [r.id for r in conformance.check(zero, root, select="original/*", reference="both").results] == [
        "original/t/f/p3"
    ]
    assert "| hog/t/f/p3 | points | pass |" in conformance.check(zero, root).table()


def test_the_numpy_rendering_samples_2d_and_3d_and_warps(tmp_path):
    from hog_noise import NoiseParams, NumpySampler

    sample, warp = conformance.renderings("numpy")
    p = NoiseParams(seed=3)
    xs = np.array([1.0, 2.0], np.float32)
    zs = np.array([5.0, 6.0], np.float32)
    assert np.array_equal(sample(p, xs, zs, None), NumpySampler(p).sample_points_2d(xs, zs, np.empty(2, np.float32)))
    assert warp(p, xs, zs, None).shape == (2, 2)


def test_the_command_line_exits_one_on_a_failure(tmp_path):
    ref = np.array([9.0, 9.0, 9.0, 9.0], np.float32)  # no noise reaches 9
    root = make_vectors(tmp_path, [a_case("hog/t/f/p3", "h/f.f32")], {"h/f.f32": ref})
    run = subprocess.run(
        [sys.executable, "-m", "hog_noise.conformance", str(root), "--rendering", "numpy"],
        capture_output=True,
        text=True,
    )
    assert run.returncode == 1 and "| hog/t/f/p3 | points | fail |" in run.stdout, run.stderr


# -------------------------------------------------------------------------
# on the committed vectors: acceptance 3, 4 and 5
REAL = Path(__file__).resolve().parents[2] / "vectors"


@pytest.fixture(scope="module")
def real():
    return conformance.load(REAL)


def test_a_seed_off_by_one_fails_hog(real):
    sample, _ = conformance.renderings("numpy")

    def off(params, xs, ys, zs):
        return sample(params.replace(seed=params.seed + 1), xs, ys, zs)

    report = conformance.check(off, real, select="hog/fns/whitenoise_none/*")
    assert len(report.results) == 2 and not report.ok


def test_one_value_nudged_by_1e_5_fails_the_white_noise_original(real):
    sample, _ = conformance.renderings("numpy")

    def nudged(params, xs, ys, zs):
        out = sample(params, xs, ys, zs).copy()
        out[17] += np.float32(1e-5)
        return out

    report = conformance.check(nudged, real, reference="original", select="original/fns/whitenoise_none/scatter_3d")
    assert len(report.results) == 1 and not report.ok


def test_one_ulp_fails_hog_at_bound_zero(real):
    sample, _ = conformance.renderings("numpy")

    def ulp(params, xs, ys, zs):
        out = sample(params, xs, ys, zs).copy()
        out[0] = np.nextafter(out[0], np.float32(np.inf))
        return out

    report = conformance.check(ulp, real, select="hog/fnl/perlin_fbm/scatter_3d")
    assert len(report.results) == 1 and report.results[0].max_normalised == float("inf")


def test_a_partial_port_reports_unsupported_not_failed(real):
    """Acceptance 4: a port of 2D OpenSimplex2 only."""
    from hog_noise import NoiseType

    sample, _ = conformance.renderings("numpy")

    def os2_2d(params, xs, ys, zs):
        if zs is not None or params.noise_type is not NoiseType.OPEN_SIMPLEX2:
            raise NotImplementedError("2D OpenSimplex2 only")
        return sample(params, xs, ys, zs)

    report = conformance.check(os2_2d, real, reference="both")
    assert report.ok and not report.complete and report.count("unsupported") > 0 and report.count("pass") > 0
    table = report.table()  # unsupported advisory rows have no statistics; the table still renders
    assert "| advisory | unsupported |" in table


def test_a_reader_with_no_numpy_gets_the_same_numbers(real):
    """Acceptance 5: json, hashlib and array only."""
    import array

    manifest = json.loads((REAL / "manifest.json").read_text(encoding="utf-8"))
    case = next(c for c in manifest["cases"] if c["id"] == "original/fns/whitenoise_none/scatter_3d")
    raw = (REAL / case["file"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == manifest["files"][case["file"]]
    values = array.array("f")
    values.frombytes(raw)
    if sys.byteorder == "big":
        values.byteswap()
    assert values.tolist() == real.case(case["id"]).values.tolist()


# -------------------------------------------------------------------------
# review on #16: a malformed folder is a ConformanceError naming what is wrong (testing.md, Error paths)
def _manifest(root: Path) -> dict:
    return json.loads((root / "manifest.json").read_text(encoding="utf-8"))


def _rewrite(root: Path, manifest: dict) -> None:
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def _one_case_folder(tmp_path: Path) -> Path:
    return make_vectors(tmp_path, [a_case("hog/t/f/p3", "hog/f.f32")], {"hog/f.f32": np.zeros(4, np.float32)})


def test_a_missing_manifest_or_one_that_is_not_json_is_a_conformance_error(tmp_path):
    with pytest.raises(conformance.ConformanceError, match="manifest.json"):
        conformance.load(tmp_path)
    (tmp_path / "manifest.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(conformance.ConformanceError, match="not JSON"):
        conformance.load(tmp_path)


@pytest.mark.parametrize(
    "break_it, says",
    [
        (lambda m: m.pop("files"), "files"),
        (lambda m: m["point_sets"]["p3"].update(count="4"), "count"),
        (lambda m: m["point_sets"]["p3"].update(dims=True), "dims"),
        (lambda m: m["cases"][0]["compare"].pop("kind"), "hog/t/f/p3"),
        (lambda m: m["cases"][0].update(params={"octaves": 3.9}), "hog/t/f/p3"),
        (lambda m: m["cases"][0].pop("point_set"), "hog/t/f/p3"),
    ],
)
def test_a_malformed_manifest_is_a_conformance_error_naming_the_part(tmp_path, break_it, says):
    root = _one_case_folder(tmp_path)
    manifest = _manifest(root)
    break_it(manifest)
    _rewrite(root, manifest)
    with pytest.raises(conformance.ConformanceError, match=says):
        conformance.load(root)


def test_a_named_file_that_is_missing_is_a_conformance_error(tmp_path):
    root = _one_case_folder(tmp_path)
    (root / "hog" / "f.f32").unlink()
    with pytest.raises(conformance.ConformanceError, match="hog/f.f32"):
        conformance.load(root)


def test_every_f32_file_is_in_the_map_and_every_digest_names_a_used_file(tmp_path):
    """The spec: `files` maps every .f32 file in the folder."""
    root = _one_case_folder(tmp_path)
    (root / "hog" / "stray.f32").write_bytes(np.zeros(4, "<f4").tobytes())
    with pytest.raises(conformance.ConformanceError, match="stray.f32"):
        conformance.load(root)
    (root / "hog" / "stray.f32").unlink()
    manifest = _manifest(root)
    manifest["files"]["hog/unused.f32"] = "0" * 64
    _rewrite(root, manifest)
    with pytest.raises(conformance.ConformanceError, match="unused.f32"):
        conformance.load(root)


def test_load_can_read_one_set_without_the_others_files(tmp_path):
    """What regenerating the hog set needs: the originals, whatever state the hog files are in."""
    cases = [a_case("hog/t/f/p3", "hog/f.f32"), a_case("original/t/f/p3", "o/f.f32")]
    root = make_vectors(tmp_path, cases, {"hog/f.f32": np.zeros(4, np.float32), "o/f.f32": np.ones(4, np.float32)})
    (root / "hog" / "f.f32").unlink()
    with pytest.raises(conformance.ConformanceError):
        conformance.load(root)
    only = conformance.load(root, sets=("original",))
    assert [c.id for c in only.cases] == ["original/t/f/p3"]


def test_a_rejected_verdict_is_reported_and_still_needs_review(tmp_path):
    """Spec acceptance 3: only `accepted` exempts; `rejected` is reported and still needs review."""
    ref = np.linspace(-1, 1, 4).astype(np.float32)
    advisory = {"kind": "advisory"}
    root = make_vectors(tmp_path, [a_case("original/t/f/p3", "o/f.f32", compare=advisory)], {"o/f.f32": ref})
    (root / "accepted.json").write_text(json.dumps({"f": {"verdict": "rejected", "by": "x", "date": "d"}}))
    result = conformance.check(_values(ref[::-1]), root, reference="original").results[0]
    assert result.verdict == "rejected" and result.needs_review
    from hog_noise import compare

    assert not compare.Verdicts(root / "accepted.json").is_accepted("f"), "the suite draws the sheet and xfails"


def test_a_wrong_shaped_output_fails_the_report_whatever_the_kind(tmp_path):
    advisory = {"kind": "advisory"}
    root = make_vectors(tmp_path, [a_case("original/t/f/p3", "o/f.f32", compare=advisory)], {"o/f.f32": np.zeros(4)})
    report = conformance.check(_values(np.zeros(3, np.float32)), root, reference="original")
    assert report.results[0].status == "fail" and not report.ok


@pytest.mark.parametrize("args, says", [(["--rendering", "no_such_rendering"], "no_such_rendering"), ([], "")])
def test_the_command_line_reports_a_bad_rendering_or_folder_and_exits_two(tmp_path, args, says):
    folder = str(_one_case_folder(tmp_path)) if args else str(tmp_path / "missing")
    run = subprocess.run([sys.executable, "-m", "hog_noise.conformance", folder, *args], capture_output=True, text=True)
    assert run.returncode == 2 and "Traceback" not in run.stderr, run.stderr
    assert says in run.stderr


def test_a_rendering_builds_one_sampler_per_distinct_parameters(monkeypatch):
    from hog_noise import NoiseParams, samplers

    built = []
    real = samplers.make_sampler

    def counting(params, backend=None):
        built.append(params)
        return real(params, backend=backend)

    monkeypatch.setattr(samplers, "make_sampler", counting)
    sample, _ = conformance.renderings("numpy")
    xs = np.array([1.0, 2.0], np.float32)
    for _ in range(3):
        sample(NoiseParams(seed=1), xs, xs, xs)
    sample(NoiseParams(seed=2), xs, xs, xs)
    assert len(built) == 2
