# GPU bounds from a large fresh sample: a tight bound for a measured fraction of points, a ceiling for every point

**Status:** Accepted 2026-11-25: merged by the owner ([PR #56](https://github.com/HogJonny-AMZN/HogNoise/pull/56), `620750a`), then "fix up and then do both", taking D3 to D9 as recommended and the vectors gate's small loosening (D6, D9). Proposed 2026-11-24. The owner chose two tiers and 65,536 fresh points a case ("I agree with your
recommendations"); the first trial showed two tiers with an outer bound from a sample's worst cannot hold, and the owner
took the rate-based form, C2 ("I'll take your best recommendation on those bounds"). Decisions D3 to D9 are
recommendations, all taken. Trial-run twice, task by task, before proposing (*The trials*, below).
**Board:** [`2026-11-21-gpu-bounds-from-a-large-fresh-sample`](../../plan/board/2026-11-21-gpu-bounds-from-a-large-fresh-sample.md)

> **For agentic workers:** REQUIRED SUB-SKILL: use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to carry this out task by task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** every GPU tolerance rule states a claim that holds on fresh points anywhere in the measured range, not only
on the vectors' own 4,096 points a case, without loosening the check the vectors make.

**Architecture:** `hog-noise-measure-gpu run` also renders 65,536 fresh points a hog case with numpy (the reference,
which gives the hog set bit for bit) and with the GPU, drawn over the measured range as the far-coordinate probe draws
them, and records the same numbers for them beside the vectors' own. `derive` keeps every tight number from the
vectors' points. A continuous rule's bound becomes its `within`, held to the fraction the fresh points measured and
never more than 0.9999, under a fixed ceiling, `LARGEST` (1e-2 a coordinate unit, the number past which drift stops
being drift), as its `bound`. A discrete rule takes how often its tight bound is missed, its correlation and its range
from the worse of the two samples. The tolerance format goes to 2, since a continuous rule may now hold a `within`.
Every adapter is measured again, and the far-coordinate probe, with its own seed and its own points, is the acceptance
check.

**Tech stack:** Python 3.11 to 3.13, numpy, wgpu (the `gpu` group); pytest through the `pytest` console script
(`uv run pytest`, never `python -m pytest`); `make check` as the gate.

---

## Before you start

- Read [the row](../../plan/board/2026-11-21-gpu-bounds-from-a-large-fresh-sample.md), [the far-coordinate
  probe](../../../Spikes/far_coordinates/README.md) (its *What it says*, item 3, is the tail this plan measures) and
  `vectors/README.md`, *Tolerance files*.
- Read [the project ledger](../../standards/failure-modes-project.md), above all P-2 (`derive_files` writes to a copy in
  tests, never the real `vectors/`), P-12 (measure, derive, load and check end to end before committing a derived
  number), P-14 (never `python -`), P-23 (a plan's code is trial-run in task order) and P-27 (a fact a change makes
  untrue is searched for as a concept, in several wordings, across every documents folder).
- Work in a worktree on a branch from `origin/main`. Commits are signed off (`git commit -s`) with the owner's identity
  and no AI attribution. Write each commit message to a file and pass it with `-F`.
- `uv sync --group gpu` before any step that runs the GPU (the trial's first run died on a missing `wgpu`, journal
  2026-11-24).
- Before every gate run, `uv run ruff format .` and `uv run ruff check --fix .`. Revert `vectors/portability.md` (the
  gate re-stamps its date) before staging, and stage named paths, never `git add -u` or `-A`.
- The commands are written for bash (Git Bash).
- A code fragment from inside a function is fenced as `text`, at its real indentation: `ruff format` formats a
  `python` fence in markdown and would dedent it.
- **One pull request**, Tasks 1 to 10. It opens as a draft at Task 6, when CI must measure its three adapters; it leaves
  draft after Task 10's review.
- **A rule an adapter fails after the re-derivation is a finding for the owner**, never a number edited to pass. Stop
  and report it.

## Facts this plan rests on

Read from the code at `b008c5f` (the merge of [PR #54](https://github.com/HogJonny-AMZN/HogNoise/pull/54)), not
assumed:

- **The reader refuses a `within` on a continuous rule.** `conformance._points_rule` (`conformance.py:415`) raises "a
  continuous rule has a bound and nothing else" for `within` or `min_correlation` on one, and `Tolerance.load` refuses
  any `format` but `TOLERANCE_FORMAT = 1` (`conformance.py:411`). `_points` (`conformance.py:607`) already judges a
  `within` on any points rule: the fraction of points within the tight bound, against `fraction`.
- **How a rule is derived today.** `measure_gpu.derive` (`measure_gpu.py:141`): a continuous rule (noise, or any warp
  output) is `step_up(2 * worst max_normalised)`; a discrete rule's `within` is `step_up(2 * worst p99_normalised)`,
  its `fraction` `floor3(1 - 2 * worst outside)`, its `bound` `step_up(worst ref_range)`, its `min_correlation` the
  worst correlation, floored, at most 0.999. Over `LARGEST = 1e-2`, or more than 1% of points outside, is a finding.
- **The hog set.** 368 cases at one frequency, 0.01, on six point sets: `scatter_2d` and `scatter_3d` (4,096 points,
  x and z in ±4,096, y in ±256), `grid_y0` (16,384 points, x and z in ±2,048, y = 0) and three `genasgrid_*` grids
  (128 x 128 x 1, through the grid entry point; 4 cases). Counted by `ranges.py` in *The trial*.
- **numpy is the reference.** The hog set was written by numpy; the far probe's control found numpy reproduces every
  scatter case bit for bit, and the trial found the same for every hog case, the grids included.
- **The committed record.** `vectors/tolerance/wgpu.json` names `reports/gpu/5340a3f/`, seven records: four local (the
  5090 on Vulkan, D3D12 and OpenGL; WARP) and three from CI (WARP, llvmpipe, Metal), measured by `tests.yml`'s *Measure
  the wgpu rung* step (`tests.yml:63`) and kept as the `gpu-measurement-<os>` artifacts.
- **The grid coordinates.** `hog_noise.samplers.grid_points` is what `gen_noise_vectors` made the grid point sets with;
  a hand-written meshgrid differs from it by one float32 step at scale 0.7 (found in the trial).

## The trials

Run before proposing, in task order in a throwaway worktree, each task's tests against only the files written so far
(P-23). Every number here came from a command at the trials' commits on `b008c5f`, on this machine (an RTX 5090 on
Vulkan, D3D12 and OpenGL, and WARP). CI's three adapters were not measured: that needs the pull request.

**The first trial disproved the first design.** It drew fresh points uniformly over each case's point set, and made a
continuous rule two-tier only when a fresh point passed its bound, with an outer bound of twice the fresh worst. It
derived cleanly and every hog case passed. Then the far probe, with its own seed and points, still failed 5 (Vulkan),
7 (D3D12) and 20 (WARP) of 246 probes inside 4,096 units, at up to 4.5 times the new bounds. On 2^20 points (`tail.py`):

- **The Perlin failures sit within 100 units of the origin,** where the coordinate-scaled bound is at its floor. A
  uniform draw puts about 1 point in 1,700 there and saw none of them; the probe's draw puts 1 in 40 there.
- **The rest are rare spikes, anywhere:** a few a million at 3 to 13 times the bound
  (`fns/simplex_fbm_perturb_gradient`, the warp outputs, `fnl/warp_opensimplex2_none`'s noise). Over 16 samples of
  65,536, the worst point varied up to 56 times. No sample's worst bounds the next's, at any size or margin CI could
  afford.

So this plan draws fresh points the probe's way (D3), and a continuous rule's claim is a rate under a fixed ceiling
(D1, D5), not a sample's worst.

**The second trial, this plan:**

- **Tasks 1 to 5:** each task's new tests failed before its code and passed after. The cap on the fraction was mutated
  away (`floor4` alone): `test_fresh_points_inside_the_tight_bound_still_leave_1_in_10_000_for_the_next_sample` failed,
  and nothing else did. Task 5's instrument: the two-tier check fails the hog cases at `fraction: 1.0` and passes at
  `0.0`.
- **Measuring (Task 6), local:** `run` on Vulkan 21 s, D3D12 54 s, OpenGL 21 s, WARP 81 s.
- **Deriving (Task 7) from the four records:** 125 rules, no finding (`summary_c2.py`). Of the 110 continuous rules,
  103 hold their tight bound at 0.9999 and seven, all Perlin, at 0.9993 to 0.9996; no tight bound moved. Six discrete
  fractions are lower: the three `noiselookup` features 1.0 to 0.995, `fnl/cellular_manhattan_cellvalue` 1.0 to
  0.999, and the two `genasgrid_*_0.7_1.0_1.3` 0.994 to 0.992 and 0.995 to 0.991. The worst continuous fresh point is
  2e-4 a unit, 50 times under the ceiling; the worst of all, 0.0134, is a Manhattan cell value flipping, which its
  discrete rule's range bound judges (`worst_fresh.py`).
- **Checking:** the GPU suite passes on all four adapters against the derived file (26 passed on each).
- **Acceptance, the far probe on the derived file,** its own seed and points: in [0, 4,096), 246 of 246 probes pass
  on the 5090's Vulkan and D3D12 and on WARP, the worst at 0.02 to 0.04 of its bound (the first design: 5, 7 and 20
  failing, at up to 4.5 times). The control held: 242 probes reproduce the hog set and pass on their own points.
  Outside the range, where the file claims nothing, 245 or 246 pass in every band; the one failure is
  `fns/cellular_natural_cellvalue` in 3D in [4,096, 32,768), one cell flip against a discrete rule that asks for
  every point within its tight bound.

The trials' scripts are not committed; they are in the session's scratchpad, and the ones a step needs are quoted in
it.

## Files

| File | Change |
| --- | --- |
| `packages/python/hog-noise/src/hog_noise/conformance.py` | `TOLERANCE_FORMAT = 2`; a continuous rule may hold a `within` |
| `packages/python/hog-noise/tests/test_conformance.py` | the format and message updates; the two-tier judging test |
| `packages/python/hog-noise/tests/test_gpu.py` | the tight tier's mutation, beside the bound's |
| `apps/hog-noise-tools/src/hog_noise_tools/measure_gpu.py` | fresh points in `run`; `derive` and the tables read them |
| `apps/hog-noise-tools/tests/test_measure_gpu.py` | the fresh points, the control, the derivation, the tables |
| `vectors/tolerance/wgpu.json`, `vectors/portability-gpu.md` | re-derived (Task 1: the format alone; Task 7: the rules) |
| `vectors/reports/gpu/<commit>/` | seven new records and their `record.md` |
| `Spikes/far_coordinates/after-fresh-bounds/`, `Spikes/far_coordinates/README.md` | the probe's re-run |
| `vectors/README.md`, `README.md`, `Docs/glossary.md`, `Docs/standards/testing-project.md`, `apps/hog-noise-tools/README.md` | the claims and the vocabulary |
| `Docs/superpowers/specs/2026-11-14-gpu-port.md`, `Docs/design/2026-11-20-gpu-fast-track-account.md` | dated amendments |
| the row, `Docs/handoffs/CURRENT.md`, the journal | the state |

### Task 1: tolerance format 2, where a continuous rule may hold a `within`

**Files:** Modify `packages/python/hog-noise/src/hog_noise/conformance.py:410-434`,
`packages/python/hog-noise/tests/test_conformance.py`, `vectors/tolerance/wgpu.json`.

- [ ] **Step 1: the tests first.** In `test_conformance.py`, `write_tolerance` writes the format the module reads:

```text
    data = {
        "format": conformance.TOLERANCE_FORMAT,
        "rendering": "test",
```

In `test_a_malformed_tolerance_fails_at_load_naming_the_part`'s parameters, replace the two rows that name the old
format and the old message:

```text
        ([dict(CONTINUOUS, min_correlation=0.9)], {}, "a continuous rule takes no min_correlation"),
```

```text
        ([CONTINUOUS], {"format": 1}, "tolerance format 1"),
```

After `test_a_continuous_rule_judges_its_features_cases_and_names_itself`, add:

```python
def test_a_continuous_rule_with_within_holds_a_fraction_to_its_tight_bound(tmp_path):
    """
    Two tiers (the fresh-sample bounds): every point within the outer bound, and ``fraction`` of them within the tight
    one. One point of four is past the tight bound: a fraction of 0.75 holds it, 0.8 fails, and an outer bound below
    that point fails whatever the fraction.
    """
    root = make_vectors(tmp_path, [a_case("hog/t/f/p3", "h/f.f32")], {"h/f.f32": np.zeros(4, np.float32)})
    v = conformance.load(root)
    ours = _values(np.array([0.0, 5e-4, 0.0, 5e-3], np.float32))

    def rule(fraction, outer=1e-2):
        return {
            "feature": "t/f",
            "kind": "continuous",
            "bound": {"scale": outer, "coordinate_scaled": False},
            "within": {"scale": 1e-3, "coordinate_scaled": False, "fraction": fraction},
        }

    def judge(r):
        return conformance.check(ours, v, tolerance=conformance.Tolerance.load(write_tolerance(root, [r]), v))

    held = judge(rule(0.75))
    assert held.ok and held.results[0].rule == "continuous", held.table()
    above = judge(rule(0.8))
    assert not above.ok and "0.7500 within 0.001, below 0.8" in above.results[0].detail
    past = judge(rule(0.75, outer=4e-3))
    assert not past.ok and "1 of 4 points past the bound" in past.results[0].detail
```

- [ ] **Step 2: run them; three fail.**

Run: `uv run pytest -q packages/python/hog-noise/tests/test_conformance.py -k "tolerance or continuous"`
Expected: `3 failed, 17 passed`: the two parameter rows (the old message; format 1 read without complaint) and the new
test.

- [ ] **Step 3: the code.** In `conformance.py`, replace `TOLERANCE_FORMAT = 1` and the top of `_points_rule`, down to
its `if kind == "discrete":` line, with:

```python
#: The tolerance file format this module reads (the GPU port's spec, *The tolerance*). 2 lets a continuous rule hold a
#: fraction of its points to a tight bound (``within``) under a ceiling, measured on a large fresh sample; 1 had no
#: ``within`` there, and a reader of 1 refuses a 2 by its number rather than by a rule it cannot read.
TOLERANCE_FORMAT = 2
_RULE_KINDS = ("continuous", "discrete")


def _points_rule(rule: Mapping[str, object]) -> dict[str, object]:
    """
    A tolerance rule as the points rule `_points` judges: continuous is a bound, with a ``within`` when a fresh sample
    found a tail past its tight bound; discrete adds within and a correlation. ``rule`` records the kind, which
    `_points` reports.
    """
    kind = rule.get("kind")
    if kind not in _RULE_KINDS:
        raise ConformanceError(f"kind {kind!r}, not one of {_RULE_KINDS}")
    points: dict[str, object] = {"kind": "points", "bound": rule.get("bound"), "rule": kind}
    if kind == "continuous":
        if "min_correlation" in rule:
            raise ConformanceError("a continuous rule takes no min_correlation: a bound and, at most, a within")
        if "within" in rule:
            points["within"] = rule["within"]
    if kind == "discrete":
```

The discrete branch and the rest are unchanged.

- [ ] **Step 4: run them; they pass.** Same command. Expected: `20 passed`.

- [ ] **Step 5: the committed file in format 2.** Every GPU test now refuses `wgpu.json` (format 1). Re-derive it from
its own record with the tool, so the format line is the only change:

```bash
uv run hog-noise-measure-gpu derive vectors/reports/gpu/5340a3f
git diff --stat vectors/
```

Expected: `vectors/tolerance/wgpu.json | 2 +-` and nothing else (`portability-gpu.md` and `record.md` are rewritten
identical; a line-ending warning is not a change).

- [ ] **Step 6: the suite.** `uv run pytest -q`. Expected: no failure (the trial: 3,134 passed before Step 5's file,
with 9 GPU errors and 1 failure on the format, all gone after it).

- [ ] **Step 7: commit.** `git add packages/python/hog-noise/src/hog_noise/conformance.py
packages/python/hog-noise/tests/test_conformance.py vectors/tolerance/wgpu.json`, message "Tolerance format 2: a
continuous rule may hold a within".

### Task 2: `run` measures fresh points against numpy

**Files:** Modify `apps/hog-noise-tools/src/hog_noise_tools/measure_gpu.py` (the imports, the constants after
`MAX_CORRELATION`, `measure` at :90, `run` at :298), `apps/hog-noise-tools/tests/test_measure_gpu.py`.

- [ ] **Step 1: the tests first.** In `test_measure_gpu.py`, the imports become:

```python
import dataclasses
import json
import math
import subprocess

import numpy as np
import pytest

from hog_noise_tools import measure_gpu as m
```

At the end of the file, add:

```python
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
```

- [ ] **Step 2: run them; the new ones fail.**

Run: `uv run pytest -q apps/hog-noise-tools/tests/test_measure_gpu.py`
Expected: the 8 new tests fail on `AttributeError` (no `fresh_reach`, `fresh_points`, `fresh_grids`,
`measure_fresh`, `check_reference`, `reference`); the 49 before them pass.

- [ ] **Step 3: the code.** In `measure_gpu.py`, add `import zlib` after `import sys`, and after
`from hog_noise.conformance import Bound`:

```python
from hog_noise.samplers import grid_points
```

After `MAX_CORRELATION = 0.999`:

```python
#: Fresh points a hog case, drawn over the measured range as the far-coordinate probe draws them and rendered by numpy
#: (the reference, which gives the hog set bit for bit) and by the GPU: 16 times a scatter set, the probe's size, so a
#: tail rarer than the vectors' 1 in 4,096 shows (the fresh-sample bounds' row).
FRESH = 65536
#: A case's fresh points come from (FRESH_SEED, crc32 of its id), so a case added later moves no other case's points.
FRESH_SEED = 20261124
#: The most a continuous rule's tight bound may ask for once fresh points are measured: all but 1 point in 10,000.
#: GPU float32 has rare spikes, a few a million at 3 to 13 times the tight bound, and one sample's worst does not bound
#: the next sample's (the fresh-sample bounds' trial). It lets none of a scatter case's 4,096 points past, 1 of 16,384.
MAX_FRACTION = 0.9999
```

Replace `measure`'s body, below its docstring, and add the functions after it, so that `measure` and the fresh
measurement share one way to render a case and one set of numbers:

```text
    cases: dict[str, dict[str, Any]] = {}
    for case in _hog(vectors):
        ps = vectors.point_sets[case.point_set]
        ours = _render(case, ps, (sample, warp, grid), ps.origin)
        cases[case.id] = {
            "feature": feature_of(case.id),
            "output": case.output,
            **_numbers(case.id, ours, case.values, case.params.frequency, ps.axes),
        }
    return cases


def _hog(vectors: conformance.Vectors) -> list[conformance.Case]:
    return [case for case in vectors.cases if case.set == "hog"]


def _render(
    case: conformance.Case,
    ps: conformance.PointSet,
    rendering: tuple[conformance.Sample, conformance.Sample, conformance.Grid],
    origin: Any = None,
    axes: tuple[np.ndarray, ...] | None = None,
) -> np.ndarray:
    """
    ``case`` rendered by ``rendering`` (sample, warp, grid): through its grid entry point at ``origin`` when it is a
    grid case, else at ``axes`` (its point set's own when None), as the harness checks it.

    :raises Finding: A grid of the wrong shape.
    """
    sample, warp, grid = rendering
    if ps.origin is not None and case.output == "noise":
        o = origin or ps.origin
        values = np.asarray(grid(case.params, tuple(o["start"]), tuple(o["shape"]), tuple(o["scales"])))
        if values.shape != tuple(o["shape"]):  # flattening would hide a grid of the wrong shape
            raise Finding(f"{case.id}: grid shape {values.shape}, expected {tuple(o['shape'])}")
        return values.ravel(order=str(o.get("order", "C")))
    axes = ps.axes if axes is None else axes
    fn = warp if case.output == "warp" else sample
    return np.asarray(fn(case.params, axes[0], axes[1], axes[2] if ps.dims == 3 else None))


def _numbers(
    case_id: str, ours: np.ndarray, ref: np.ndarray, frequency: float, axes: tuple[np.ndarray, ...]
) -> dict[str, Any]:
    """
    The numbers a rule is derived from, for one rendering's values against the reference's at the points ``axes``.

    :raises Finding: Values of the wrong shape, or a value that is not finite.
    """
    ours = np.asarray(ours, np.float32)
    if ours.shape != ref.shape:
        raise Finding(f"{case_id}: shape {ours.shape}, expected {ref.shape}")
    bad = int(np.count_nonzero(~np.isfinite(ours)))
    if bad:  # NaN would make every statistic NaN, and step_up(NaN) the tightest rule there is
        raise Finding(f"{case_id}: the GPU wrote {bad} values that are not finite")
    diff = np.abs(ours.astype(np.float64) - ref.astype(np.float64))
    if diff.ndim == 2:
        diff = diff.max(axis=1)  # a warped point is held to one bound over its components, as the harness does
    normalised = diff / Bound(1.0, coordinate_scaled=True).per_point(frequency, axes)
    return {
        "max_abs": float(diff.max()),
        "max_normalised": float(normalised.max()),
        "p99_normalised": float(np.quantile(normalised, 0.99)),
        "correlation": float(compare.compare_values(ours.ravel(), ref.ravel()).correlation),
        "outside": {key: float(np.mean(normalised > c)) for key, c in zip(CANDIDATE_KEYS, CANDIDATES, strict=True)},
        "ref_range": float(ref.max() - ref.min()),
    }


def fresh_rng(case_id: str) -> np.random.Generator:
    """The generator of ``case_id``'s fresh points: its own stream, whatever other cases there are."""
    return np.random.default_rng([FRESH_SEED, zlib.crc32(case_id.encode("utf-8"))])


def fresh_reach(vectors: conformance.Vectors) -> float:
    """The largest coordinate magnitude of the hog set's scattered points: how far out fresh points are drawn."""
    sets = {c.point_set for c in _hog(vectors) if vectors.point_sets[c.point_set].origin is None}
    return max(float(np.max(np.abs(a))) for name in sets for a in vectors.point_sets[name].axes)


def fresh_points(dims: int, reach: float, rng: np.random.Generator) -> tuple[np.ndarray, ...]:
    """
    `FRESH` points as the far-coordinate probe draws them: the largest coordinate's magnitude uniform in [0, ``reach``),
    signs mixed, on a random axis, the others smaller. Uniform over the area would put about 1 point in 1,700 within
    100 units of the origin, where the coordinate-scaled bound is at its floor and tightest; this puts 1 in 40 there.
    """
    big = rng.uniform(0.0, reach, FRESH) * rng.choice([-1.0, 1.0], FRESH)
    axes = [rng.uniform(-1.0, 1.0, FRESH) * np.abs(big) for _ in range(dims)]
    which = rng.integers(0, dims, FRESH)
    return tuple(np.where(which == d, big, axes[d]).astype(np.float32) for d in range(dims))


def fresh_grids(origin) -> list[tuple[int, ...]]:
    """
    The starts of grids of a grid case's shape and scales, beside its own along x, `FRESH` points in all: the same
    lattice, so a tie the case's grid sits on is sat on again at new places.
    """
    start, shape = list(origin["start"]), list(origin["shape"])
    tiles = max(1, FRESH // math.prod(shape))
    return [(start[0] + k * shape[0], *start[1:]) for k in range(1, tiles + 1)]


def reference() -> tuple[conformance.Sample, conformance.Sample, conformance.Grid]:
    """numpy's sample, warp and grid entry points: the rendering the hog set was made with."""
    return (*conformance.renderings("numpy"), conformance.grid_rendering("numpy"))


def check_reference(
    vectors: conformance.Vectors, ref: tuple[conformance.Sample, conformance.Sample, conformance.Grid]
) -> None:
    """
    ``ref`` gives every hog case's committed values bit for bit on the case's own points: the control that fresh points,
    which have no committed values, are judged against the hog set's reference.

    :raises Finding: A case it does not reproduce.
    """
    for case in _hog(vectors):
        ours = np.asarray(_render(case, vectors.point_sets[case.point_set], ref), np.float32)
        if not np.array_equal(ours, case.values):
            raise Finding(f"{case.id}: the reference does not reproduce the hog set bit for bit")


def measure_fresh(
    vectors: conformance.Vectors,
    ref: tuple[conformance.Sample, conformance.Sample, conformance.Grid],
    ours: tuple[conformance.Sample, conformance.Sample, conformance.Grid],
) -> dict[str, dict[str, Any]]:
    """
    Per hog case, `measure`'s numbers for ``ours`` against ``ref`` on `FRESH` new points: drawn over the measured range
    (`fresh_points`) in the case's dimensions, or for a grid case, grids beside its own (`fresh_grids`).

    :raises Finding: A rendering that wrote a value that is not finite, or an output of the wrong shape.
    """
    reach = fresh_reach(vectors)
    cases: dict[str, dict[str, Any]] = {}
    for case in _hog(vectors):
        ps = vectors.point_sets[case.point_set]
        if ps.origin is not None and case.output == "noise":
            o = ps.origin
            origins = [{**o, "start": list(start)} for start in fresh_grids(o)]
            want = np.concatenate([_render(case, ps, ref, origin) for origin in origins])
            got = np.concatenate([_render(case, ps, ours, origin) for origin in origins])
            parts = [grid_points(g["start"], g["shape"], g["scales"]) for g in origins]  # the generator's own
            axes = tuple(np.concatenate(axis) for axis in zip(*parts, strict=True))
        else:
            axes = fresh_points(ps.dims, reach, fresh_rng(case.id))
            want = _render(case, ps, ref, axes=axes)
            got = _render(case, ps, ours, axes=axes)
        cases[case.id] = _numbers(case.id, got, np.asarray(want, np.float32), case.params.frequency, axes)
    return cases
```

In `run`, replace from `sample, warp = conformance.renderings("wgpu")` to the end of the `data = {...}` literal with:

```text
    ours = (*conformance.renderings("wgpu"), conformance.grid_rendering("wgpu"))
    info = gpu.adapter_info()
    _LOGGER.info(f"run: GPU adapter {info['device']} ({info['backend_type']}, {info['adapter_type']})")
    cases = measure(vectors, *ours)
    ref = reference()
    check_reference(vectors, ref)
    _LOGGER.info(f"run: numpy gives the hog set bit for bit; {FRESH} fresh points a case against it")
    for case_id, numbers in measure_fresh(vectors, ref, ours).items():
        cases[case_id]["fresh"] = numbers
    data = {
        "adapter": info,
        "host": os.environ.get(HOST_ENV, "").strip() or "local",
        "commit": commit,
        "fresh": {"points": FRESH, "seed": FRESH_SEED},
        "cases": cases,
    }
```

- [ ] **Step 4: run them; they pass.** Same command. Expected: `57 passed`.

- [ ] **Step 5: one real run, outside `vectors/`.** It must finish and write a record with a `fresh` block on every
case; the second trial took 21 s on the 5090's Vulkan.

```bash
uv sync --group gpu
uv run hog-noise-measure-gpu run --out "$TMP/fresh-trial"
```

Expected: the log line "numpy gives the hog set bit for bit" and "measured 368 hog cases". Delete the folder after.

- [ ] **Step 6: commit.** `git add` the two files, message "measure-gpu run: 65,536 fresh points a hog case against
numpy, beside the vectors' own".

### Task 3: `derive` reads both samples

**Files:** Modify `measure_gpu.py` (`floor3` at :76, `derive` at :141), `test_measure_gpu.py`.

- [ ] **Step 1: the tests first.** After `test_a_measurement_that_is_not_finite_is_a_finding_not_the_tightest_rule`, add:

```python
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


@pytest.mark.parametrize("field", ["max_normalised", "correlation"])
def test_a_fresh_measurement_that_is_not_finite_is_a_finding(field):
    with pytest.raises(m.Finding, match="not finite"):
        m.derive([record("a", {"hog/fnl/f/scatter_3d": stats("fnl/f", fresh=fresh(**{field: float("nan")}))})])
```

- [ ] **Step 2: run them.** `uv run pytest -q apps/hog-noise-tools/tests/test_measure_gpu.py`. Expected: `10 failed,
57 passed`: every new test, since `derive` ignores the fresh numbers and has no `floor4`. The trial mutated Step 3's
cap away; `test_fresh_points_inside_the_tight_bound_still_leave_1_in_10_000_for_the_next_sample` failed, alone.

- [ ] **Step 3: the code.** After `floor3`, add:

```python
def floor4(x: float) -> float:
    """
    ``x`` rounded down to four places, as `floor3`: a continuous rule's fraction within its tight bound. At three, the
    rarest tail a fresh sample finds (1 point in 65,536) would give 0.999 and let 4 of a case's 4,096 vectors points
    past the tight bound; at four it gives 0.9999, which lets none past, as the bound alone did.
    """
    return float(decimal.Decimal(repr(float(x))).quantize(decimal.Decimal("0.0001"), rounding=decimal.ROUND_FLOOR))
```

Replace `derive` whole with:

```python
def derive(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    The rules, from every adapter's record, by the spec's rules and the plan's decisions.

    A tight number comes from the vectors' points, as before. When the records hold fresh points (`measure_fresh`),
    a continuous rule's bound becomes its ``within``, held to the fraction the fresh points measured and never more than
    `MAX_FRACTION`, under the ceiling `LARGEST` as its bound: a fixed number, since one sample's worst does not bound
    the next's. A discrete rule takes how often its tight bound is missed, its correlation and its range from the worse
    of the two samples.

    :raises Finding: A measurement that is not finite, a continuous feature or a warp past `LARGEST` (on either
        sample), more than 1% of points past a tight bound, or records of which some have fresh points and some not.
    """
    groups: dict[tuple[str, str], list[dict[str, Any]]] = collections.defaultdict(list)
    outputs: dict[str, set[str]] = collections.defaultdict(set)
    for rec in records:
        for s in rec["cases"].values():
            groups[(s["feature"], s["output"])].append(s)
            outputs[s["feature"]].add(s["output"])
    with_fresh = sum("fresh" in s for stats in groups.values() for s in stats)
    if 0 < with_fresh < sum(len(stats) for stats in groups.values()):
        raise Finding("some cases were measured on fresh points and some not: measure every adapter again")
    rules = []
    for (feature, output), stats in sorted(groups.items()):
        fresh = [s["fresh"] for s in stats if "fresh" in s]
        for s in [*stats, *fresh]:  # a record written by hand or by an older tool is held to `measure`'s standard
            numbers = [s[k] for k in ("max_abs", "max_normalised", "p99_normalised", "correlation", "ref_range")]
            if not all(math.isfinite(v) for v in [*numbers, *s["outside"].values()]):
                raise Finding(f"{feature} {output}: a measurement that is not finite")
        rule: dict[str, object] = {"feature": feature}
        if len(outputs[feature]) > 1:
            rule["output"] = output
        if output != "warp" and any(k in feature for k in DISCRETE):
            both = [*stats, *fresh]
            within = step_up(2.0 * max(s["p99_normalised"] for s in stats))
            if within > LARGEST:
                raise Finding(f"{feature}: its 99th percentile is itself a flip, more than 1% of points")
            key = f"{within:.0e}"
            outside = max(s["outside"][key] for s in both)
            if outside > 0.01:
                raise Finding(f"{feature}: {outside:.4f} of points outside {within}, more than 1%")
            rule.update(
                kind="discrete",
                bound={"scale": step_up(max(s["ref_range"] for s in both)), "coordinate_scaled": False},
                within={"scale": within, "coordinate_scaled": True, "fraction": floor3(1.0 - 2.0 * outside)},
                min_correlation=min(MAX_CORRELATION, floor3(min(s["correlation"] for s in both))),
            )
        else:
            # A warp's output is a coordinate, and its drift is a few float32 steps of the coordinate warped, so it
            # grows with the raw coordinate (Spikes/far_coordinates). Coordinate-scaled, the bound grows with it too;
            # it is scaled by raw * frequency, not raw, so it holds at the frequencies the tolerance file's range names.
            scale = step_up(2.0 * max(s["max_normalised"] for s in stats))
            if scale > LARGEST:
                jump = "" if output == "warp" else "; a jump the DISCRETE list does not name"
                raise Finding(f"{feature}{' warp' if output == 'warp' else ''}: {scale} past {LARGEST}{jump}")
            rule.update(kind="continuous", bound={"scale": scale, "coordinate_scaled": True})
            if fresh:
                worst = max(f["max_normalised"] for f in fresh)
                if worst > LARGEST:
                    raise Finding(
                        f"{feature} {output}: a fresh point at {worst:.3g} a unit, past the ceiling {LARGEST}"
                    )
                outside = max(f["outside"][f"{scale:.0e}"] for f in fresh)
                if outside > 0.01:
                    raise Finding(f"{feature} {output}: {outside:.4f} of fresh points past {scale}, more than 1%")
                rule.update(
                    bound={"scale": LARGEST, "coordinate_scaled": True},
                    within={
                        "scale": scale,
                        "coordinate_scaled": True,
                        "fraction": min(MAX_FRACTION, floor4(1.0 - 2.0 * outside)),
                    },
                )
        rules.append(rule)
    return rules
```

The warp branch and the continuous branch were the same arithmetic with different messages; they are one branch now,
and both messages are kept, since the existing tests match them.

- [ ] **Step 4: run them; they pass.** Same command. Expected: `67 passed`, the committed-file tests among them: the
`5340a3f` records have no fresh points, so they derive as before.

- [ ] **Step 5: commit.** Message "measure-gpu derive: a tight bound from the vectors for a measured fraction of points,
a fixed ceiling for every point".

### Task 4: the tables show the fresh worst

**Files:** Modify `measure_gpu.py` (`_tables` at :321), `test_measure_gpu.py`.

- [ ] **Step 1: the test first.** Before `test_a_fresh_measurement_that_is_not_finite_is_a_finding`, add:

```python
def test_the_tables_show_the_fresh_worst_beside_the_vectors_worst_only_when_measured():
    plain = [record("a", {"hog/fnl/f/scatter_3d": stats("fnl/f")})]
    per_case, per_feature = m._tables(plain, m.derive(plain))
    assert "Fresh" not in per_case and "fresh" not in per_feature
    tail = fresh(max_normalised=1.2e-5, outside=past("5e-06", 3 / 65536))
    measured = [record("a", {"hog/fnl/f/scatter_3d": stats("fnl/f", fresh=tail)})]
    per_case, per_feature = m._tables(measured, m.derive(measured))
    assert "| Fresh max / unit | Fresh past tight |" in per_case and "| 1.20e-05 | 0.0000458 |" in per_case
    assert "| fnl/f | 2.03e-06, 1.20e-05 fresh |" in per_feature
```

- [ ] **Step 2: run it; it fails** on the second `assert` (no fresh column). `uv run pytest -q
apps/hog-noise-tools/tests/test_measure_gpu.py -k tables`. Expected: `1 failed`.

- [ ] **Step 3: the code.** In `_tables`, replace from the `tight = {...}` line to the end of the per-case loop with:

```text
    tight = {r["feature"]: f"{r['within']['scale']:.0e}" for r in rules if r["kind"] == "discrete"}
    by_output = {(r["feature"], r.get("output")): r for r in rules}

    def tight_of(s: dict[str, Any]) -> str:  # the bound a case's fresh points are counted past: within, else bound
        rule = by_output.get((s["feature"], s["output"])) or by_output[(s["feature"], None)]
        return f"{(rule.get('within') or rule['bound'])['scale']:.0e}"

    fresh = any("fresh" in s for r in records for s in r["cases"].values())
    lines = ["# The wgpu rung against the hog set, per feature", "", "Written by `hog-noise-measure-gpu derive`.", "",
             "| Feature | " + " | ".join(adapters) + " |", "| --- |" + " --- |" * len(adapters)]  # fmt: skip
    per_case = ["# The measurement, per case", "", "| Case | Adapter | Max abs | Max / unit | p99 / unit | Corr |"
                + (" Fresh max / unit | Fresh past tight |" if fresh else ""),
                "| --- | --- | --- | --- | --- | --- |" + (" --- | --- |" if fresh else "")]  # fmt: skip
    features = sorted({s["feature"] for r in records for s in r["cases"].values()})
    for feature in features:
        cells = []
        for r in records:
            stats = [s for s in r["cases"].values() if s["feature"] == feature]
            worst = max(s["max_normalised"] for s in stats)
            cell = f"{worst:.2e}"
            if fresh:
                cell += f", {max(s['fresh']['max_normalised'] for s in stats):.2e} fresh"
            if feature in tight:
                cell += f", {max(s['outside'][tight[feature]] for s in stats):.4f} flipped"
            cells.append(cell)
        lines.append(f"| {feature} | " + " | ".join(cells) + " |")
    for r, name in zip(records, adapters, strict=True):
        for case_id, s in sorted(r["cases"].items()):
            row = (
                f"| {case_id} | {name} | {s['max_abs']:.2e} | {s['max_normalised']:.2e} | {s['p99_normalised']:.2e} "
                f"| {s['correlation']:.6f} |"
            )
            if fresh:
                f = s["fresh"]
                row += f" {f['max_normalised']:.2e} | {f['outside'][tight_of(s)]:.7f} |"
            per_case.append(row)
```

- [ ] **Step 4: run them; they pass.** `uv run pytest -q apps/hog-noise-tools/tests/test_measure_gpu.py`. Expected: `68
passed`; the committed `5340a3f` tables are unchanged, since they have no fresh points.

- [ ] **Step 5: commit.** Message "measure-gpu derive: the tables show the fresh worst".

### Task 5: the tight tier bites on the GPU

**Files:** Modify `packages/python/hog-noise/tests/test_gpu.py` (`test_a_rule_at_0_9_of_its_worst_fails` at :193).

`test_a_rule_at_0_9_of_its_worst_fails` replaces `fnl/simplex_fbm`'s bound with 0.9 of this adapter's worst and expects
a failure. Nothing shows the same for a `within` on a continuous rule, which is what Task 1 lets the file hold.

- [ ] **Step 1: the test.** At the end of that test, add:

```text
    # the same worst as a continuous rule's within, under its own outer bound: the tight tier bites too
    within = {"scale": 0.9 * worst, "coordinate_scaled": True, "fraction": 1.0}
    rules[(feature, None)] = dict(tolerance.rules[(feature, None)], within=within)
    two_tier = conformance.Tolerance(tolerance.rendering, tolerance.range, rules)
    report = conformance.check(sample, vectors, tolerance=two_tier, select=f"hog/{feature}/*")
    assert not report.ok and all("past the bound" not in r.detail for r in report.results), report.table()
```

- [ ] **Step 2: prove it can give the other answer.** Run it: `HOG_NOISE_REQUIRE_GPU=1 uv run pytest -q
packages/python/hog-noise/tests/test_gpu.py -k 0_9`. Expected: `1 passed`. Change `"fraction": 1.0` to `0.0` and run
again. Expected: `1 failed` on `assert (not True)`: with no fraction asked for, nothing fails. Change it back.

- [ ] **Step 3: commit.** Message "The GPU test's 0.9-of-worst mutation, on a within too".

### Task 6: measure every adapter, as a draft pull request

The seven records must come from one commit: this branch's head after Task 5. CI measures its three on the pull
request; the four local ones are measured here at the same commit.

- [ ] **Step 1: the gate, then push and open a draft.** `make check`, unpiped; push; `gh pr create --draft` with the
template filled (*Not covered* names Tasks 7 to 10 as to come). The commit the records name is the head:
`git rev-parse --short HEAD`, called `<commit>` below.

- [ ] **Step 2: the four local adapters,** into the folder the derivation will read:

```bash
uv sync --group gpu
uv run hog-noise-measure-gpu run
WGPU_BACKEND_TYPE=D3D12 uv run hog-noise-measure-gpu run
WGPU_BACKEND_TYPE=OpenGL uv run hog-noise-measure-gpu run
WGPU_BACKEND_TYPE=D3D12 HOG_NOISE_WGPU_ADAPTER="Microsoft Basic Render Driver" uv run hog-noise-measure-gpu run
ls vectors/reports/gpu/<commit>/
```

Expected: four records. The second trial's times: 21, 54, 21 and 81 s.

- [ ] **Step 3: CI's three.** Wait for the run (`gh pr checks <n> --watch`). Its *Measure the wgpu rung* step runs on
WARP, llvmpipe and Metal, each record naming `<commit>`. Record each GPU leg's time against `b008c5f`'s run (the CI
WARP leg took 7 min 13 s there): the fresh points cost the CI legs about as much as WARP's 113 s here, and that is the
only new cost to every pull request. Then:

```bash
gh run download <run id> -n gpu-measurement-Windows -D "$TMP/ci-windows"
gh run download <run id> -n gpu-measurement-Linux -D "$TMP/ci-linux"
gh run download <run id> -n gpu-measurement-macOS -D "$TMP/ci-macos"
cp "$TMP"/ci-*/*.json vectors/reports/gpu/<commit>/
ls vectors/reports/gpu/<commit>/ | wc -l
```

Expected: `7`. Every record holds a `"fresh"` block and the same `commit`; a record naming another commit means a push
landed between measurements: measure again.

### Task 7: derive, check, and the far probe

- [ ] **Step 1: derive.** `uv run hog-noise-measure-gpu derive vectors/reports/gpu/<commit>`. Expected: "derived 125
rules from 7 adapters", no finding. A finding stops the pull request for the owner.

- [ ] **Step 2: say what moved.** Run `summary_c2.py` (below) on the folder and paste its output into the pull
request. It derives the same records with their fresh numbers removed, so it separates what the fresh sample changed
from what the new records changed. Write it to the session's scratchpad, never into the repository, and run it with
`uv run python -I <path> vectors/reports/gpu/<commit>`:

```python
"""The C2 rules: how many continuous fractions sit below the cap, and what the discrete rules moved to."""

import collections
import copy
import sys
from pathlib import Path

from hog_noise_tools import measure_gpu as m

records = m.read_records(Path(sys.argv[1]))
plain = copy.deepcopy(records)
for r in plain:
    for s in r["cases"].values():
        s.pop("fresh", None)
before = {(r["feature"], r.get("output")): r for r in m.derive(plain)}
after = {(r["feature"], r.get("output")): r for r in m.derive(records)}
cont = [(k, r) for k, r in after.items() if r["kind"] == "continuous"]
fractions = collections.Counter(r["within"]["fraction"] for _, r in cont)
print(f"{len(after)} rules; {len(cont)} continuous, fractions: {sorted(fractions.items(), reverse=True)}")
for k, r in sorted(cont):
    if r["within"]["fraction"] < m.MAX_FRACTION:
        print(f"  below the cap: {k[0]} {k[1] or ''} within {r['within']['scale']:g} at {r['within']['fraction']}")
tight_moved = [k for k, r in cont if r["within"]["scale"] != before[k]["bound"]["scale"]]
print(f"continuous tight bounds that moved from the vectors-only rule: {len(tight_moved)}")
for k, r in sorted(after.items()):
    if r["kind"] == "discrete" and r != before[k]:
        diffs = {f: (before[k][f], r[f]) for f in ("bound", "within", "min_correlation") if before[k][f] != r[f]}
        print(f"  discrete {k[0]}: {diffs}")
kinds = {k: r["kind"] for k, r in after.items()}
worst = {"continuous": 0.0, "discrete": 0.0}
for rec in records:
    for s in rec["cases"].values():
        kind = kinds.get((s["feature"], s["output"])) or kinds[(s["feature"], None)]
        worst[kind] = max(worst[kind], s["fresh"]["max_normalised"])
# the ceiling is a continuous rule's bound; a discrete rule's bound is its reference range, so its worst is not compared
print(f"worst continuous fresh point: {worst['continuous']:.3g} a unit, ceiling {m.LARGEST}")
print(f"worst discrete fresh point: {worst['discrete']:.3g} a unit (a flip, judged by its rule's range bound)")
```

Expected, from the second trial's four local records: 110 continuous rules, about 103 at 0.9999 and the Perlin
features below it; no tight bound moved; about 6 discrete fractions lower; the worst continuous fresh point far under
the ceiling. The three CI records may move any of these. A continuous fraction below 0.998 is more than 1 point in 1,000
past its tight bound: name it in the pull request.

- [ ] **Step 3: check.** The suite on every local adapter, against the derived file:

```bash
uv run pytest -q
for b in Vulkan D3D12 OpenGL; do WGPU_BACKEND_TYPE=$b HOG_NOISE_REQUIRE_GPU=1 uv run pytest -q packages/python/hog-noise/tests/test_gpu.py; done
WGPU_BACKEND_TYPE=D3D12 HOG_NOISE_WGPU_ADAPTER="Microsoft Basic Render Driver" HOG_NOISE_REQUIRE_GPU=1 uv run pytest -q packages/python/hog-noise/tests/test_gpu.py
```

Expected: no failure. CI checks its three after the push in Step 5.

- [ ] **Step 4: the far probe, its own seed and points,** on the three adapters it ran on before, into a new folder:

```bash
uv run python -I Spikes/far_coordinates/probe.py Spikes/far_coordinates/after-fresh-bounds
WGPU_BACKEND_TYPE=D3D12 uv run python -I Spikes/far_coordinates/probe.py Spikes/far_coordinates/after-fresh-bounds
HOG_NOISE_WGPU_ADAPTER="Microsoft Basic Render Driver" WGPU_BACKEND_TYPE=D3D12 uv run python -I Spikes/far_coordinates/probe.py Spikes/far_coordinates/after-fresh-bounds
uv run python -I Spikes/far_coordinates/compare.py Spikes/far_coordinates/after-warp-rules Spikes/far_coordinates/after-fresh-bounds
```

Expected: the control holds (242 probes); in [0, 4,096), every probe passes on all three (the second trial: 246 of
246, at most 0.04 of the bound). A probe failing there is a finding: stop. Write what it found under a new section of
`Spikes/far_coordinates/README.md`, *After the fresh-sample bounds (date)*, as the warp rules' section does.

- [ ] **Step 5: commit and push.** `git add vectors/reports/gpu/<commit> vectors/tolerance/wgpu.json
vectors/portability-gpu.md Spikes/far_coordinates/after-fresh-bounds Spikes/far_coordinates/README.md`, message "The
rules re-derived from seven adapters, with 65,536 fresh points a case". Read CI: every GPU leg passes the new file.

### Task 8: the documents

Search first, as P-27 says, and fix every hit that the change makes untrue. The trial's searches, which found the list
below:

```bash
git grep -n -i -E "bound and nothing else|bound alone|a bound only|vectors' points|vectors. 4,096|tolerance format|\"format\": 1|fresh points|1 in 4,096|rarer than" -- '*.md' ':!Docs/journal/*' ':!vectors/reports/*'
git grep -n -i -E "on the vectors|measured over|twice the worst|tight bound|outer bound|within.{0,30}fraction" -- '*.md' ':!Docs/journal/*' ':!vectors/reports/*'
```

Accepted plans under `Docs/superpowers/plans/` and the journal are records of their time and are not edited.

- [ ] **`vectors/README.md`:** the tolerance example's `"format": 1` (the second one; the first is the manifest's)
becomes 2, and its continuous rule gains a `within` under the ceiling; the **`continuous`** bullet says the bound is
the ceiling and the `within` the vectors' tight bound, met by at least the stated fraction of points (each rule's
own, at most 0.9999); **How a number
is set** says how `run` draws fresh points and how `derive` uses them, why the bound is a fixed ceiling and not a
sample's worst (the first trial), and names the new record folder, its seven adapters and what moved from `5340a3f`.
- [ ] **`README.md`**, *What it claims*: on fresh points anywhere in the range, every point within the ceiling, and at
least each rule's stated fraction within its tight bound: 0.9999 for most continuous rules and lower where it was
measured lower (the second trial: seven Perlin rules at 0.9993 to 0.9996, so up to 7 points in 10,000 past). Quote the
range of fractions from the derived file, never a single limit; the probe's re-run is the evidence.
- [ ] **`Docs/glossary.md`:** the **Tolerance file** row (a continuous rule is a tight bound for a fraction under the
ceiling); the **Measurement record** row (it holds fresh-point numbers too); the **Fresh points**, **Tight bound** and
**Ceiling** rows the plan's pull request added lose "Proposed", "not yet built" and "under the plan".
- [ ] **`Docs/standards/testing-project.md`**, *The judge*: a record holds fresh points, and re-measuring takes under
two minutes on WARP.
- [ ] **`apps/hog-noise-tools/README.md`**, the `hog-noise-measure-gpu` row: `run` measures fresh points too.
- [ ] **`Docs/superpowers/specs/2026-11-14-gpu-port.md`**, *The tolerance* and *How a number is fixed*: a dated
amendment, as the 2026-11-15 ones, naming this plan and the format.
- [ ] **`Docs/design/2026-11-20-gpu-fast-track-account.md`:** line 74's "C2's bounds hold on the vectors' points"
gets a dated amendment, as line 52's has. (That C2 is the account's claim 2, not this plan's option C2.)
- [ ] Run both searches again. Expected: every remaining hit is true, or in a dated record.
- [ ] `make check`; commit, message "The documents: fresh points, a tight bound for a fraction, a ceiling".

### Task 9: the row, the handoff, the journal, the ledger

- [ ] **The row:** State Landed with the pull request linked once merged (P-11: a status a merge changes is fixed on
main in the next pull request); until then, "In review". **The HLSL row**'s *Waits on* the fresh-sample bounds goes.
- [ ] **`Docs/handoffs/CURRENT.md`:** the lead, and the agreed order's next item, the HLSL build.
- [ ] **The journal:** a section for the build; the trials and their numbers are in this plan, so it links here.
- [ ] **The ledger,** `Docs/standards/failure-modes-project.md`: the next P-number, the lesson the first trial taught.
Trigger: a bound is derived from the worst of a sample. Do: before trusting it, measure a second, independent sample
with another seed and the drawing the claim covers, and see whether the first sample's worst bounds it; for a heavy
tail, state a rate, not a worst. Because: this plan's first design derived outer bounds from 65,536 points a case, and
the far probe's own 65,536 failed them at up to 4.5 times. Mechanised: the far probe is the acceptance check (Task 7,
Step 4).
- [ ] **LargeWorlds:** nothing. Its pin and canary cover the numpy rung, and this changes no numpy output; say so in
the pull request's *Not covered*.
- [ ] Commit, message "The fresh-sample bounds: the row, the handoff, the journal, ledger P-<n>".

### Task 10: review, then out of draft

- [ ] Run the `local-review` skill on the branch; paste its table into the pull request's *Review* section and act on
each finding. `make check`, unpiped. Update the body (test counts, what moved). Then `gh pr ready <n>`.

## Built

Built 2026-11-25 in [PR #58](https://github.com/HogJonny-AMZN/HogNoise/pull/58), from the trial's code, file for file.

- **Task 1**, `e309425`: `test_conformance.py` 99 passed; `wgpu.json` re-derived from `5340a3f` changed its format line
  alone; the suite 3,144 passed.
- **Tasks 2 to 4**, `4e756c8`, **one commit, not three**: the three tasks share `measure_gpu.py` and
  `test_measure_gpu.py`, and each was trial-run in its own order before the plan was proposed. `test_measure_gpu.py`
  68 passed.
- **Task 5**, `3e05b2c`: the two-tier mutation passes on the 5090's Vulkan.
- **Task 6:** the four local adapters at `3e05b2c` in 28, 59, 30 and 116 s (Vulkan, D3D12, OpenGL, WARP). CI's three
  came from run 45536974570's artifacts, all naming `3e05b2c`. CI's WARP leg took 6 min 27 s with the fresh points,
  against 7 min 13 s at `b008c5f`'s run without them: no visible cost.
- **Task 7:** 125 rules from seven adapters, no finding. **No tight number moved from `5340a3f`** (a script comparing
  each rule's tight number with the committed file's). 103 of 110 continuous rules at 0.9999, seven Perlin rules at
  0.9993 to 0.9996, as in the trial. Six discrete fractions lower; Metal, which the trial did not measure, takes the
  three `noiselookup` features to 0.993 or 0.994 (the trial's four adapters: 0.995). The worst continuous fresh point
  2e-4 a unit; the worst of all, 0.0134, a cell flip. The suite 3,163 passed; the GPU suite 26 of 26 on each local
  adapter. The far probe: 246 of 246 inside the range on all three, the control held.
- **Task 9:** the ledger's P-28 with Task 8. The handoff's lead, the row's State and the journal waited for
  [PR #57](https://github.com/HogJonny-AMZN/HogNoise/pull/57), which edited all three; the branch was rebased on its
  merge (`9f982ac`), so the commits after `3e05b2c` have new hashes. The records still name `3e05b2c`, the head they
  were measured at: the rebase brought only #57's documents, CI leg and floor test, and the one later source change
  (the review's, below) touches how records are read and how a failure is worded, not what `run` measures.
- **Task 10:** the deliberate review returned *needs work* on one hard finding, a malformed `fresh` block or case
  reaching `derive` as a raw `KeyError` or `TypeError`. Fixed with eleven tests (nine malformed shapes from the
  reviewer's probes, a missing header, mismatched headers), with its other code findings; the table and each answer
  are in the pull request.

## Decisions

| # | Decision | Chosen | Instead of |
| --- | --- | --- | --- |
| D1 | The shape of a continuous rule | A rate under a ceiling (C2, the owner's choice): the vectors' tight bound for the measured fraction of points, at most 0.9999, and the fixed ceiling `LARGEST` for every point | An outer bound from twice a sample's worst (C, disproved by the first trial: the next sample's worst was up to 4.5 times it); keeping the bounds and claiming them on the vectors' points only (A); a bigger sample and margin (B: still a sample's worst) |
| D2 | How many fresh points | 65,536 a case, the probe's size (the owner's choice) | More: 21 to 81 s an adapter now, and CI pays it on every pull request |
| D3 | Where fresh points are drawn | The probe's way: the largest coordinate's magnitude uniform in [0, reach), the others smaller, seeded per case by `crc32(id)`; reach is the scatter sets' largest coordinate | Uniform over each case's point set (the first trial): 1 point in 1,700 within 100 units of the origin, where the bound is tightest, and it missed the Perlin tail there |
| D4 | A grid case's fresh points | Four grids of its shape beside its own along x, on the same lattice, through the grid entry point | Scattered points, which never sit on the lattice ties that make `genasgrid` discrete |
| D5 | The ceiling | `LARGEST`, 1e-2 a coordinate unit: the number past which `derive` already calls drift a finding; a fresh point past it is a finding | A ceiling from a sample's worst, which moves with every measurement; none, which lets any value through on 1 point in 10,000 |
| D6 | The fraction | Four places, capped at 0.9999 for every continuous rule, so the claim leaves room for a spike no sample saw. On a scatter case's 4,096 vectors points 0.9999 still asks for every one; on a `grid_y0` case's 16,384 it lets 1 past the old tight bound, and the Perlin rules' 0.9993 lets 2 of 4,096 and 11 of 16,384 (D9) | Three places: 0.999 lets 4 of 4,096 vectors points past where today none may; no cap: a sample that saw no spike asks for every point, which the next sample fails; a second, all-points check on the committed vectors beside the fraction (a second number in every rule, for a gate the fraction already holds to within 11 points) |
| D7 | A discrete rule | Its tight bound stays the vectors' 99th percentile; its fraction, correlation and range take the worse of both samples | Re-deriving the tight bound from the fresh 99th percentile too, which changes what the bound is, not only how often it is missed |
| D8 | Old records and the format | Format 2; the reader refuses 1. A record without fresh points derives as before; a folder mixing the two is a finding | Reading both formats (no format 1 file exists outside this repository; LargeWorlds reads no tolerance file); filling fresh points in old records (they were measured at another commit) |
| D9 | What C2 gives up | A regression that only adds rare spikes, under the ceiling and on fewer points than a rule's fraction allows, passes. That includes the committed vectors: today every vectors point must meet the tight bound; after this, a `grid_y0` case may have 1 point past it (11 for the Perlin rules) and a Perlin scatter case 2 | Catching it on fresh points, which no sampled bound can promise (the first trial); keeping the vectors gate exact with a separate all-points check (D6) |

## Self-review against the row

- **"`run` adds fresh points per feature against numpy, the records grow, `derive` reads both":** Tasks 2 and 3; per
  case rather than per feature, since a feature's cases differ in point set and output.
- **"tests":** each of Tasks 1 to 5 starts with its failing tests; Task 3's cap and Task 5's check were each mutated
  and failed.
- **"a re-derivation on every adapter":** Tasks 6 and 7, all seven, CI's three through its artifacts.
- **"The vectors stay as the check":** the tight bound is still the vectors', but the gate is not exactly as strict
  as today's. A fraction of 0.9999 lets none of a scatter case's 4,096 points past it, and 1 of a `grid_y0` case's
  16,384. The seven Perlin rules measure 0.9993 to 0.9996, which lets up to 2 of 4,096 and 11 of 16,384 past. That is
  the measured tail, named in the pull request and in D6 and D9; a separate all-points check on the vectors would keep
  the gate exact, and is the owner's call.
- **"it measures the real tail, not a rule loosened to pass":** the fraction is measured; the ceiling is a fixed
  number already in the code; the far probe, with its own points, is the acceptance check (Task 7, Step 4).

## Terms introduced

- **Fresh points:** points a measurement draws new for a hog case, 65,536 by default, over the measured range as the
  far-coordinate probe draws them (a grid case: grids beside its own), rendered by numpy as the reference and by the
  rendering measured; recorded beside the vectors' own numbers in a measurement record.
- **Tight bound:** a rule's `within`: the bound a stated fraction of points must meet. A discrete rule's comes from the
  vectors' 99th percentile, a continuous rule's from the vectors' worst; the fraction comes from the fresh points.
- **Ceiling:** a continuous rule's `bound` once fresh points are measured: `LARGEST`, 1e-2 a coordinate unit, which
  every point must meet; past it is not drift.
