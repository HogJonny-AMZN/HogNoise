"""
HogNoise: the GPU measurement and the rules derived from it (the GPU port's spec, *How a number is fixed*).
Package: apps/hog-noise-tools/tests/test_measure_gpu
"""

import json
import subprocess

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
