"""
HogNoise: the GPU measurement and the rules derived from it (the GPU port's spec, *How a number is fixed*).
Package: tests/test_measure_gpu
"""

import json

import pytest

import _tools_path  # noqa: F401  (puts tools/ on sys.path)
import measure_gpu as m


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


def test_a_feature_with_noise_and_warp_gets_a_rule_for_each_and_the_warp_rule_is_absolute():
    records = [
        record(
            "a",
            {
                "hog/fnl/w/scatter_3d": stats("fnl/w"),
                "hog/fnl/w/scatter_3d/warp": stats("fnl/w", output="warp", max_abs=3e-4),
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
            "bound": {"scale": 1e-3, "coordinate_scaled": False},
        },
    ]


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
