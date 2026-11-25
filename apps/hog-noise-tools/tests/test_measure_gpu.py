"""
HogNoise: the GPU measurement and the rules derived from it (the GPU port's spec, *How a number is fixed*).
Package: apps/hog-noise-tools/tests/test_measure_gpu
"""

import dataclasses
import json
import math
import subprocess

import numpy as np
import pytest

from hog_noise_tools import measure_gpu as m


@pytest.mark.parametrize(
    "x, step",
    [
        (2.03e-6, 5e-6),
        (4e-6, 5e-6),
        (5e-6, 5e-6),
        (5.000000000000001e-06, 5e-6),
        (5.1e-6, 1e-5),
        (1.2e-3, 2e-3),
        (0.0, 1e-7),
    ],
)
def test_step_up_is_the_next_1_2_5_step_with_a_floor(x, step):
    assert m.step_up(x) == step


def test_floor3_rounds_down_without_float_noise():
    assert m.floor3(0.999) == 0.999 and m.floor3(0.99849) == 0.998 and m.floor3(1.0) == 1.0


@pytest.mark.parametrize("x", [0.9999999999999998, 0.9989999999999999, 0.99999, 0.5, 0.123456])
def test_floor3_never_rounds_up(x):
    """
    A bit-exact case's correlation is 0.9999999999999998 from np.corrcoef: rounded up to 1.0 it would be a
    min_correlation the measured adapter itself fails (the Task 14 smoke run, on the RTX 5090).
    """
    assert m.floor3(x) <= x


def stats(feature, output="noise", **over):
    s = {
        "feature": feature,
        "output": output,
        "max_abs": 1e-6,
        "max_normalised": 2.03e-6,
        "p99_normalised": 1e-6,
        "correlation": 0.99999,
        "outside": {key: 0.0 for key in m.CANDIDATE_KEYS},
        "ref_range": 1.9,
    }
    s.update(over)
    return s


def record(adapter, cases):
    return {"adapter": {"device": adapter, "backend_type": "Test"}, "host": "here", "cases": cases}


def test_a_continuous_rule_is_twice_the_worst_over_every_adapter():
    records = [
        record("a", {"hog/fnl/f/scatter_3d": stats("fnl/f")}),
        record("b", {"hog/fnl/f/scatter_3d": stats("fnl/f", max_normalised=3e-6)}),
    ]
    assert m.derive(records) == [
        {"feature": "fnl/f", "kind": "continuous", "bound": {"scale": 1e-5, "coordinate_scaled": True}}
    ]


def test_a_discrete_rule_takes_its_tight_bound_from_the_99th_percentile():
    outside = {key: 0.0 for key in m.CANDIDATE_KEYS}
    outside["5e-06"] = 0.0007
    records = [
        record(
            "a",
            {
                "hog/fns/cellular_natural_cellvalue/scatter_3d": stats(
                    "fns/cellular_natural_cellvalue",
                    max_normalised=0.9,
                    p99_normalised=2e-6,
                    outside=outside,
                    correlation=0.99912,
                )
            },
        )
    ]
    assert m.derive(records) == [
        {
            "feature": "fns/cellular_natural_cellvalue",
            "kind": "discrete",
            "bound": {"scale": 2.0, "coordinate_scaled": False},
            "within": {"scale": 5e-6, "coordinate_scaled": True, "fraction": 0.998},
            "min_correlation": 0.999,
        }
    ]


def test_a_discrete_rule_never_asks_for_a_correlation_above_0_999():
    """
    np.corrcoef of two identical arrays is 1.0 on one run and 0.9999999999999998 on another: CI's llvmpipe leg failed
    a bit-exact cell value against a derived 1.0 (the owner's decision, 2026-11-15: cap at 0.999).
    """
    outside = {key: 0.0 for key in m.CANDIDATE_KEYS}
    records = [
        record(
            "a",
            {
                "hog/fns/cellular_natural_cellvalue/scatter_3d": stats(
                    "fns/cellular_natural_cellvalue", p99_normalised=0.0, outside=outside, correlation=1.0
                )
            },
        )
    ]
    assert m.derive(records)[0]["min_correlation"] == m.MAX_CORRELATION == 0.999


def test_a_feature_with_noise_and_warp_gets_a_rule_for_each_and_the_warp_rule_is_coordinate_scaled():
    """The warp rule follows max_normalised, not max_abs: an absolute bound fails past 4,096 units (the far probe)."""
    records = [
        record(
            "a",
            {
                "hog/fnl/w/scatter_3d": stats("fnl/w"),
                "hog/fnl/w/scatter_3d/warp": stats("fnl/w", output="warp", max_abs=0.3, max_normalised=3e-4),
            },
        )
    ]
    assert m.derive(records) == [
        {
            "feature": "fnl/w",
            "output": "noise",
            "kind": "continuous",
            "bound": {"scale": 5e-6, "coordinate_scaled": True},
        },
        {
            "feature": "fnl/w",
            "output": "warp",
            "kind": "continuous",
            "bound": {"scale": 1e-3, "coordinate_scaled": True},
        },
    ]


def test_a_warp_past_the_largest_bound_is_a_finding():
    with pytest.raises(m.Finding, match="fnl/w warp"):
        m.derive([record("a", {"hog/fnl/w/scatter_3d/warp": stats("fnl/w", output="warp", max_normalised=0.4)})])


def test_a_continuous_feature_that_jumps_is_a_finding_not_a_number():
    with pytest.raises(m.Finding, match="fnl/f"):
        m.derive([record("a", {"hog/fnl/f/scatter_3d": stats("fnl/f", max_normalised=0.4)})])


def test_a_discrete_feature_flipping_more_than_one_percent_is_a_finding():
    outside = {key: 0.02 for key in m.CANDIDATE_KEYS}
    with pytest.raises(m.Finding, match="more than 1%"):
        m.derive([record("a", {"hog/fns/whitenoise_none/scatter_3d": stats("fns/whitenoise_none", outside=outside)})])


@pytest.mark.parametrize("field", ["max_normalised", "p99_normalised", "correlation"])
def test_a_measurement_that_is_not_finite_is_a_finding_not_the_tightest_rule(field):
    """step_up(NaN) is the 1e-7 floor, so a NaN that reached derive would look like a perfect adapter."""
    with pytest.raises(m.Finding, match="not finite"):
        m.derive([record("a", {"hog/fnl/f/scatter_3d": stats("fnl/f", **{field: float("nan")})})])


def test_floor4_rounds_down_to_four_places_and_never_up():
    assert m.floor4(1.0 - 6 / 65536) == 0.9999 and m.floor4(1.0) == 1.0 and m.floor4(0.99969) == 0.9996
    assert m.floor4(0.9999999999999998) == 0.9999


def fresh(**over):
    """A case's fresh-point numbers, as clean as `stats` until ``over`` says otherwise."""
    s = stats("unused", **over)
    return {k: v for k, v in s.items() if k not in ("feature", "output")}


def past(key, fraction):
    """An ``outside`` with ``fraction`` of the points past ``key`` and every tighter step."""
    i = m.CANDIDATE_KEYS.index(key)
    return {k: (fraction if j <= i else 0.0) for j, k in enumerate(m.CANDIDATE_KEYS)}


def test_fresh_points_inside_the_tight_bound_still_leave_1_in_10_000_for_the_next_sample():
    """
    None of these fresh points is past 5e-6, but one sample's worst does not bound the next's: the tight bound is held
    to MAX_FRACTION, under the fixed ceiling, never to every point.
    """
    records = [record("a", {"hog/fnl/f/scatter_3d": stats("fnl/f", fresh=fresh(max_normalised=4e-6))})]
    assert m.derive(records) == [
        {
            "feature": "fnl/f",
            "kind": "continuous",
            "bound": {"scale": m.LARGEST, "coordinate_scaled": True},
            "within": {"scale": 5e-6, "coordinate_scaled": True, "fraction": m.MAX_FRACTION},
        }
    ]


def test_a_fresh_tail_past_the_tight_bound_sets_the_fraction_under_the_ceiling():
    """
    The vectors give 5e-6 (twice 2.03e-6, stepped up). Twenty fresh points of 65,536 are past it, the worst at 1.2e-5:
    the fraction is one minus twice twenty in 65,536, rounded down; the bound stays the ceiling, whatever the worst.
    """
    tail = fresh(max_normalised=1.2e-5, outside=past("5e-06", 20 / 65536))
    records = [
        record("a", {"hog/fnl/f/scatter_3d": stats("fnl/f", fresh=tail)}),
        record("b", {"hog/fnl/f/scatter_3d": stats("fnl/f", fresh=fresh())}),
    ]
    assert m.derive(records) == [
        {
            "feature": "fnl/f",
            "kind": "continuous",
            "bound": {"scale": m.LARGEST, "coordinate_scaled": True},
            "within": {"scale": 5e-6, "coordinate_scaled": True, "fraction": 0.9993},
        }
    ]


def test_a_warp_rule_takes_its_fresh_tail_the_same_way():
    tail = fresh(max_normalised=8e-4, outside=past("5e-04", 2 / 65536))
    records = [
        record("a", {"hog/fnl/w/scatter_3d/warp": stats("fnl/w", output="warp", max_normalised=2e-4, fresh=tail)})
    ]
    assert m.derive(records) == [
        {
            "feature": "fnl/w",
            "kind": "continuous",
            "bound": {"scale": m.LARGEST, "coordinate_scaled": True},
            "within": {"scale": 5e-4, "coordinate_scaled": True, "fraction": 0.9999},
        }
    ]


def test_a_fresh_point_past_the_ceiling_is_a_finding():
    tail = fresh(max_normalised=0.4, outside=past("5e-06", 1 / 65536))
    with pytest.raises(m.Finding, match="fnl/f noise: a fresh point at 0.4 a unit, past the ceiling"):
        m.derive([record("a", {"hog/fnl/f/scatter_3d": stats("fnl/f", fresh=tail)})])


def test_a_fresh_tail_on_more_than_one_percent_of_points_is_a_finding():
    tail = fresh(max_normalised=1e-5, outside=past("5e-06", 0.02))
    with pytest.raises(m.Finding, match="more than 1%"):
        m.derive([record("a", {"hog/fnl/f/scatter_3d": stats("fnl/f", fresh=tail)})])


def test_a_discrete_rule_takes_its_fraction_correlation_and_range_from_both_samples():
    """The tight bound stays the vectors' 99th percentile; how often it is missed is the worse of the two samples."""
    vectors_side = dict(p99_normalised=2e-6, outside=past("5e-06", 0.0007), correlation=0.99912)
    tail = fresh(outside=past("5e-06", 0.0013), correlation=0.9985, ref_range=2.3)
    records = [
        record(
            "a",
            {
                "hog/fns/cellular_natural_cellvalue/scatter_3d": stats(
                    "fns/cellular_natural_cellvalue", **vectors_side, fresh=tail
                )
            },
        )
    ]
    assert m.derive(records) == [
        {
            "feature": "fns/cellular_natural_cellvalue",
            "kind": "discrete",
            "bound": {"scale": 5.0, "coordinate_scaled": False},
            "within": {"scale": 5e-6, "coordinate_scaled": True, "fraction": 0.997},
            "min_correlation": 0.998,
        }
    ]


def test_records_with_and_without_fresh_points_are_a_finding():
    """A rule half from fresh points is no rule: every adapter is measured again."""
    records = [
        record("a", {"hog/fnl/f/scatter_3d": stats("fnl/f", fresh=fresh())}),
        record("b", {"hog/fnl/f/scatter_3d": stats("fnl/f")}),
    ]
    with pytest.raises(m.Finding, match="measure every adapter again"):
        m.derive(records)


def test_the_tables_show_the_fresh_worst_beside_the_vectors_worst_only_when_measured():
    plain = [record("a", {"hog/fnl/f/scatter_3d": stats("fnl/f")})]
    per_case, per_feature = m._tables(plain, m.derive(plain))
    assert "Fresh" not in per_case and "fresh" not in per_feature
    tail = fresh(max_normalised=1.2e-5, outside=past("5e-06", 3 / 65536))
    measured = [record("a", {"hog/fnl/f/scatter_3d": stats("fnl/f", fresh=tail)})]
    per_case, per_feature = m._tables(measured, m.derive(measured))
    assert "| Fresh max / unit | Fresh past tight |" in per_case and "| 1.20e-05 | 0.0000458 |" in per_case
    assert "| fnl/f | 2.03e-06, 1.20e-05 fresh |" in per_feature


@pytest.mark.parametrize("field", ["max_normalised", "correlation"])
def test_a_fresh_measurement_that_is_not_finite_is_a_finding(field):
    with pytest.raises(m.Finding, match="not finite"):
        m.derive([record("a", {"hog/fnl/f/scatter_3d": stats("fnl/f", fresh=fresh(**{field: float("nan")}))})])


TOLERANCE = m.VECTORS / "tolerance" / "wgpu.json"


def test_the_committed_rules_follow_from_the_committed_record():
    """Acceptance 6: every number in the tolerance file recomputes from the record; a hand-edited one fails here."""
    tolerance = json.loads(TOLERANCE.read_text(encoding="utf-8"))
    records = m.read_records(m.VECTORS / tolerance["measured"]["record"])
    assert [m.label(r) for r in records] == tolerance["measured"]["adapters"]
    assert m.derive(records) == tolerance["rules"]
    assert m.measured_range(m.conformance.load(m.VECTORS)) == tolerance["range"]


def test_a_hand_edited_number_is_caught(tmp_path):
    """The instrument can say no: the same comparison, with one rule's scale halved, differs."""
    tolerance = json.loads(TOLERANCE.read_text(encoding="utf-8"))
    records = m.read_records(m.VECTORS / tolerance["measured"]["record"])
    edited = json.loads(json.dumps(tolerance["rules"]))
    edited[0]["bound"]["scale"] /= 2
    assert m.derive(records) != edited


# -------------------------------------------------------------------------
# derive_files and read_records on a copy of vectors/: never the real one (ledger P-2)
REAL_VECTORS = m.VECTORS
#: The record folder the committed tolerance file names, so a new measurement never leaves this pointing at the old one.
RECORD = json.loads(TOLERANCE.read_text(encoding="utf-8"))["measured"]["record"].rstrip("/")


@pytest.fixture(scope="module")
def hog_vectors():
    return m.conformance.load(REAL_VECTORS, sets="hog")


@pytest.fixture
def copy(tmp_path, monkeypatch, hog_vectors):
    """
    A copy of the files `derive_files` writes, under a ``vectors/`` that `m.VECTORS` points at, with the committed hog
    set standing in for its load: returns the copy's root and the bytes of each file before the call.
    """
    root = tmp_path / "vectors"
    for rel in ("tolerance/wgpu.json", "portability-gpu.md", f"{RECORD}/record.md"):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes((REAL_VECTORS / rel).read_bytes())
    monkeypatch.setattr(m, "VECTORS", root)
    monkeypatch.setattr(m.conformance, "load", lambda *a, **k: hog_vectors)
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    return root, before


def _write_records(folder, records):
    folder.mkdir(parents=True, exist_ok=True)
    for i, rec in enumerate(records):
        (folder / f"r{i}.json").write_text(json.dumps(rec), encoding="utf-8")


def _real_records():
    return m.read_records(REAL_VECTORS / RECORD)


def test_derive_files_reproduces_the_committed_files_from_the_committed_record(copy):
    root, before = copy
    for p in (REAL_VECTORS / RECORD).glob("*.json"):
        (root / RECORD / p.name).write_bytes(p.read_bytes())
    m.derive_files(root / RECORD)
    for path, data in before.items():
        assert path.read_bytes().replace(b"\r\n", b"\n") == data.replace(b"\r\n", b"\n"), path
    assert not [p for p in root.rglob("*") if p.name.endswith(".tmp")], "no temporary file is left behind"


def test_an_empty_folder_is_a_finding_and_writes_nothing(copy):
    """A folder with no records once overwrote the tolerance with zero rules before failing on record.md."""
    root, before = copy
    (root / "reports" / "gpu" / "empty").mkdir(parents=True)
    with pytest.raises(m.Finding, match="no measurement records"):
        m.derive_files(root / "reports" / "gpu" / "empty")
    assert {p: p.read_bytes() for p in before} == before


def test_records_holding_different_cases_are_a_finding_and_write_nothing(copy):
    root, before = copy
    a, b = _real_records()[:2]
    del b["cases"][sorted(b["cases"])[0]]
    folder = root / "reports" / "gpu" / "uneven"
    _write_records(folder, [a, b])
    with pytest.raises(m.Finding, match="not the same cases"):
        m.derive_files(folder)
    assert {p: p.read_bytes() for p in before} == before


def test_records_that_are_not_the_hog_set_are_a_finding(copy):
    """A stale record, measured before a hog case was added, would otherwise end in max() of an empty sequence."""
    root, before = copy
    rec = _real_records()[0]
    del rec["cases"][sorted(rec["cases"])[0]]
    folder = root / "reports" / "gpu" / "stale"
    _write_records(folder, [rec])
    with pytest.raises(m.Finding, match="missing 1"):
        m.derive_files(folder)
    assert {p: p.read_bytes() for p in before} == before


@pytest.mark.parametrize(
    "text",
    [
        "{not json",
        "[]",
        '{"adapter": {"device": "d", "backend_type": "b"}, "host": "h", "commit": "abc1234"}',
        '{"adapter": {"device": "d", "backend_type": "b"}, "host": "h", "commit": 7, "cases": {}}',
        '{"adapter": "d", "host": "h", "commit": "abc1234", "cases": {}}',
        '{"adapter": {"device": "d", "backend_type": "b"}, "commit": "abc1234", "cases": {}}',
        '{"adapter": {"device": "d", "backend_type": "b"}, "host": "h", "commit": "abc1234", "cases": []}',
    ],
)
def test_a_malformed_record_is_a_finding_naming_the_file(tmp_path, text):
    (tmp_path / "bad.json").write_text(text, encoding="utf-8")
    with pytest.raises(m.Finding, match=r"bad\.json"):
        m.read_records(tmp_path)


def test_a_well_formed_record_reads(tmp_path):
    """The control for the malformed ones: the same reader says yes."""
    good = {"adapter": {"device": "d", "backend_type": "b"}, "host": "h", "commit": "abc1234", "cases": {}}
    (tmp_path / "good.json").write_text(json.dumps(good), encoding="utf-8")
    assert m.read_records(tmp_path) == [good]


CASE = "hog/fnl/f/scatter_3d"


def a_record(adapter="d", header=None, **over):
    """A record of one case with fresh points, as `run` writes it; ``over`` replaces top-level keys."""
    rec = {
        "adapter": {"device": adapter, "backend_type": "b"},
        "host": "h",
        "commit": "abc1234",
        "fresh": header or {"points": m.FRESH, "seed": m.FRESH_SEED},
        "cases": {CASE: stats("fnl/f", fresh=fresh())},
    }
    rec.update(over)
    return rec


def test_a_well_formed_record_with_fresh_points_reads(tmp_path):
    """The control for the malformed cases below."""
    (tmp_path / "good.json").write_text(json.dumps(a_record()), encoding="utf-8")
    assert m.read_records(tmp_path) == [a_record()]


@pytest.mark.parametrize(
    "mutate, says",
    [
        (lambda s: s.update(fresh="oops"), "fresh: not an object"),
        (lambda s: s.update(fresh=None), "fresh: not an object"),
        (lambda s: s["fresh"].pop("outside"), "fresh: outside"),
        (lambda s: s["fresh"]["outside"].pop("5e-06"), "fresh: outside"),
        (lambda s: s["fresh"].update(max_normalised="x"), "fresh: max_normalised"),
        (lambda s: s.update(fresh={}), "fresh: max_abs"),
        (lambda s: s.pop("max_abs"), "max_abs"),
        (lambda s: s.update(correlation=True), "correlation"),
        (lambda s: s.update(output="both"), "feature 'fnl/f' and output 'both'"),
    ],
)
def test_a_malformed_case_is_a_finding_naming_the_file_and_the_case(tmp_path, mutate, says):
    """
    The review on #58: a record written by hand or by an older tool once reached `derive` and died on a raw KeyError
    or TypeError naming neither file nor case.
    """
    rec = a_record()
    mutate(rec["cases"][CASE])
    (tmp_path / "bad.json").write_text(json.dumps(rec), encoding="utf-8")
    with pytest.raises(m.Finding, match=rf"bad\.json: case {CASE}: {says}"):
        m.read_records(tmp_path)


def test_a_case_with_fresh_points_needs_the_records_fresh_header(tmp_path):
    rec = a_record()
    del rec["fresh"]
    (tmp_path / "bad.json").write_text(json.dumps(rec), encoding="utf-8")
    with pytest.raises(m.Finding, match=r"bad\.json: .*'fresh' header"):
        m.read_records(tmp_path)


def test_records_measured_with_different_fresh_points_are_a_finding(tmp_path):
    """A fraction to four places needs 10,000 points or more, and one rule from two samplings is no rule."""
    records = [a_record("a"), a_record("b", header={"points": 4096, "seed": m.FRESH_SEED})]
    with pytest.raises(m.Finding, match="different fresh points"):
        m.check_cases(records, {CASE}, tmp_path)


@pytest.mark.parametrize("value", ["C:/Temp/x", "../../x", "0d419", "g0d419e9", "0d419e9 x", "a" * 41])
def test_a_pinned_commit_that_is_not_hex_is_refused(monkeypatch, value):
    """The commit becomes a folder name: ``C:/Temp/x`` once gave ``C:/Temp``."""
    monkeypatch.setenv(m.COMMIT_ENV, value)
    with pytest.raises(ValueError, match=m.COMMIT_ENV):
        m._commit()


def test_a_pinned_commit_is_shortened_to_seven(monkeypatch):
    monkeypatch.setenv(m.COMMIT_ENV, "0d419e9ABCDEF0123")
    assert m._commit() == "0d419e9"


def _git(returncode, stdout):
    def run(argv, **kwargs):
        assert argv[0] == "git", argv
        if kwargs.get("check") and returncode:
            raise subprocess.CalledProcessError(returncode, argv, stdout, "fatal: not a git repository")
        return subprocess.CompletedProcess(argv, returncode, stdout, "fatal: not a git repository")

    return run


@pytest.mark.parametrize("returncode, stdout", [(128, ""), (128, "bafde93\n"), (0, ""), (0, "not-a-commit\n")])
def test_a_git_that_fails_or_answers_nothing_raises(monkeypatch, returncode, stdout):
    monkeypatch.delenv(m.COMMIT_ENV, raising=False)
    monkeypatch.setattr(m.subprocess, "run", _git(returncode, stdout))
    with pytest.raises((subprocess.CalledProcessError, ValueError)):
        m._commit()


def test_git_s_answer_is_the_commit(monkeypatch):
    monkeypatch.delenv(m.COMMIT_ENV, raising=False)
    monkeypatch.setattr(m.subprocess, "run", _git(0, "bafde93\n"))
    assert m._commit() == "bafde93"


# -------------------------------------------------------------------------
# Fresh points: the tail the vectors' 4,096 points a case are too few to see (the fresh-sample bounds' row)
GRIDS = ["genasgrid_0.7_1.0_1.3", "genasgrid_1.0_0.5_2.0", "genasgrid_1.0_1.0_1.0"]


def _first(vectors, point_set, output="noise"):
    return next(c for c in vectors.cases if c.set == "hog" and c.point_set == point_set and c.output == output)


def _only(vectors, *cases):
    return dataclasses.replace(vectors, cases=tuple(cases))


def _fakes(offset):
    """``sample``, ``warp`` and ``grid`` renderings giving zeros, and ``offset`` at each call's first point."""

    def sample(params, xs, ys, zs):
        out = np.zeros(len(xs), np.float32)
        out[0] = offset
        return out

    def warp(params, xs, ys, zs):
        out = np.zeros((len(xs), 2 if zs is None else 3), np.float32)
        out[0, 0] = offset
        return out

    def grid(params, start, shape, scales):
        out = np.zeros(tuple(shape), np.float32)
        out.flat[0] = offset
        return out

    return sample, warp, grid


def test_fresh_points_stay_inside_the_reach_and_are_seeded_by_case(hog_vectors):
    reach = m.fresh_reach(hog_vectors)
    assert 4095.0 < reach < 4096.0  # the scatter sets' largest coordinate
    a = m.fresh_points(3, reach, m.fresh_rng("hog/x/a/scatter_3d"))
    assert len(a) == 3 and all(axis.shape == (m.FRESH,) and axis.dtype == np.float32 for axis in a)
    assert max(float(np.abs(axis).max()) for axis in a) <= reach
    again = m.fresh_points(3, reach, m.fresh_rng("hog/x/a/scatter_3d"))
    assert all(np.array_equal(x, y) for x, y in zip(a, again, strict=True))
    assert not np.array_equal(a[0], m.fresh_points(3, reach, m.fresh_rng("hog/x/b/scatter_3d"))[0])


@pytest.mark.parametrize("dims", [2, 3])
def test_fresh_points_cover_the_origin_where_the_bound_is_tightest(dims):
    """
    Within 100 units of the origin the coordinate-scaled bound is at its floor; the first trial drew uniformly over the
    area, put about 1 point in 1,700 there, and missed the Perlin features' tail the probe found there.
    """
    axes = m.fresh_points(dims, 4096.0, m.fresh_rng("hog/x/a/p"))
    near = np.mean(np.max(np.abs(np.stack(axes)), axis=0) < 100.0)
    assert 0.02 < near < 0.03  # 100 / 4,096 of the largest coordinates


def test_fresh_grids_sit_beside_the_cases_own_on_its_lattice(hog_vectors):
    o = hog_vectors.point_sets["genasgrid_1.0_1.0_1.0"].origin
    assert m.fresh_grids(o) == [(64, -64, 1), (192, -64, 1), (320, -64, 1), (448, -64, 1)]
    assert len(m.fresh_grids(o)) * math.prod(o["shape"]) == m.FRESH


def test_the_fresh_numbers_are_the_gpu_against_the_reference_on_fresh_points(hog_vectors):
    """One point a call is off by 1e-3: one point of FRESH for a scatter case, one per tile for a grid case."""
    picked = [
        _first(hog_vectors, "scatter_2d"),
        _first(hog_vectors, "scatter_3d", "warp"),
        _first(hog_vectors, GRIDS[2]),
    ]
    fresh = m.measure_fresh(_only(hog_vectors, *picked), _fakes(0.0), _fakes(1e-3))
    assert list(fresh) == [c.id for c in picked]
    for case, s in zip(picked, fresh.values(), strict=True):
        tiles = len(m.fresh_grids(hog_vectors.point_sets[case.point_set].origin)) if case.point_set in GRIDS else 1
        assert s["max_abs"] == pytest.approx(1e-3) and s["ref_range"] == 0.0
        assert s["outside"]["1e-07"] == tiles / m.FRESH


def test_a_gpu_value_that_is_not_finite_on_fresh_points_is_a_finding(hog_vectors):
    with pytest.raises(m.Finding, match="not finite"):
        m.measure_fresh(_only(hog_vectors, _first(hog_vectors, "scatter_2d")), _fakes(0.0), _fakes(float("nan")))


def test_a_reference_that_is_not_the_hog_set_is_a_finding(hog_vectors):
    """Fresh points are judged against numpy, so numpy must give the hog set's own values first."""
    with pytest.raises(m.Finding, match="does not reproduce"):
        m.check_reference(_only(hog_vectors, _first(hog_vectors, "scatter_2d")), _fakes(0.0))


def test_numpy_reproduces_the_hog_set_on_a_scatter_a_warp_and_a_grid_case(hog_vectors):
    picked = [_first(hog_vectors, "scatter_3d"), _first(hog_vectors, "grid_y0", "warp"), _first(hog_vectors, GRIDS[0])]
    m.check_reference(_only(hog_vectors, *picked), m.reference())
