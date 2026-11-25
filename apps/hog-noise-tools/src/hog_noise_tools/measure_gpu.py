"""
HogNoise: measure the wgpu rung against the hog set on this machine's adapter, and derive the tolerance file from every
adapter's measurement (the GPU port's spec, *How a number is fixed*).
Package: hog_noise_tools.measure_gpu

    uv run --group gpu hog-noise-measure-gpu run                  # this adapter -> vectors/reports/gpu/<commit>/
    uv run hog-noise-measure-gpu derive vectors/reports/gpu/<commit>   # every adapter -> the rules and the tables

`run` writes one measurement record (a JSON file) per GPU adapter, so the owner's GPU, WARP and CI's llvmpipe each add
their own (``--out`` elsewhere for a trial). `derive` reads them all and writes `vectors/tolerance/wgpu.json`,
`vectors/portability-gpu.md` and the folder's `record.md`; the folder must be under `vectors/`, which the tolerance file
names. The rules follow from the records alone, so apps/hog-noise-tools/tests/test_measure_gpu.py can recompute every
committed number.
"""

from __future__ import annotations

import argparse
import collections
import decimal
import json
import logging as _logging
import math
import os
import re
import subprocess
import sys
import zlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from hog_noise import compare, conformance
from hog_noise.conformance import Bound
from hog_noise.samplers import grid_points
from hog_noise_tools.repo import REPO_ROOT as ROOT

_MODULE_NAME = "hog_noise_tools.measure_gpu"
__version__ = "0.1.0"
__updated__ = "2026-11-17"
_LOGGER = _logging.getLogger(_MODULE_NAME)

VECTORS = ROOT / "vectors"
#: Every 1, 2 or 5 step from 1e-7 to 1e-2: the tight bounds a discrete rule may take.
CANDIDATES = [float(f"{m}e{e}") for e in range(-7, -2) for m in (1, 2, 5)] + [1e-2]
CANDIDATE_KEYS = [f"{c:.0e}" for c in CANDIDATES]
#: Features whose output jumps where float32 flips a choice (the plan's decision): judged by a discrete rule.
DISCRETE = ("cellvalue", "noiselookup", "whitenoise", "genasgrid")
#: Past this, a doubled worst is no longer drift: the derivation stops and the owner decides.
LARGEST = 1e-2
#: The highest correlation a discrete rule asks for: np.corrcoef of two identical arrays is 1.0 on one run and
#: 0.9999999999999998 on another (the owner's decision, 2026-11-15). Precision is the rule's `within`.
MAX_CORRELATION = 0.999
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


class Finding(Exception):
    """
    A measurement finding: a measurement the rules cannot turn into a number, or a measurement record that cannot be
    read as one. It stops the derivation for the owner's decision, in the pull request (the glossary's **Measurement
    finding**, not the docs check's **Finding**).
    """


def step_up(x: float) -> float:
    """The smallest 1, 2 or 5 step at or above ``x``, and never below the smallest candidate (2.03e-6 -> 5e-6)."""
    if not x > CANDIDATES[0]:
        return CANDIDATES[0]
    exponent = math.floor(math.log10(x))
    for e in (exponent, exponent + 1):
        for m in (1, 2, 5):
            step = float(f"{m}e{e}")
            if step >= x * (1.0 - 1e-9):
                return step
    raise AssertionError(x)  # unreachable: 1e(exponent + 1) is always at or above x


def floor3(x: float) -> float:
    """
    ``x`` rounded down to three decimal places, without float noise turning 0.999 into 0.998, and never up: it rounds
    the shortest decimal that is ``x`` (its ``repr``), so 0.9999999999999998, a bit-exact case's correlation from
    ``np.corrcoef``, gives 0.999 and not a 1.0 the measured adapter itself would fail.
    """
    return float(decimal.Decimal(repr(float(x))).quantize(decimal.Decimal("0.001"), rounding=decimal.ROUND_FLOOR))


def floor4(x: float) -> float:
    """
    ``x`` rounded down to four places, as `floor3`: a continuous rule's fraction within its tight bound. At three, the
    rarest tail a fresh sample finds (1 point in 65,536) would give 0.999 and let 4 of a case's 4,096 vectors points
    past the tight bound; at four it gives 0.9999, which lets none past, as the bound alone did.
    """
    return float(decimal.Decimal(repr(float(x))).quantize(decimal.Decimal("0.0001"), rounding=decimal.ROUND_FLOOR))


def feature_of(case_id: str) -> str:
    """``<library dir>/<feature>``, the middle of a case id, as the harness names a tolerance rule's feature."""
    return "/".join(case_id.split("/")[1:3])


def measure(
    vectors: conformance.Vectors, sample: conformance.Sample, warp: conformance.Sample, grid: conformance.Grid
) -> dict[str, dict[str, Any]]:
    """
    Per hog case, the numbers the rules are derived from.

    :param vectors: The loaded vectors; only the hog set is measured.
    :param sample: The rendering's noise entry point (`conformance.renderings`).
    :param warp: Its warp entry point.
    :param grid: Its grid entry point (`conformance.grid_rendering`): a case on a point set with ``from`` goes through
        it, as the harness checks it.
    :raises Finding: A rendering that wrote a value that is not finite, or an output of the wrong shape.
    """
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
    """The hog set's cases, the only ones the GPU is measured on."""
    return [case for case in vectors.cases if case.set == "hog"]


def _render(
    case: conformance.Case,
    ps: conformance.PointSet,
    rendering: tuple[conformance.Sample, conformance.Sample, conformance.Grid],
    origin: Mapping[str, Any] | None = None,
    axes: tuple[NDArray[np.float32], ...] | None = None,
) -> NDArray:
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
    case_id: str, ours: NDArray, ref: NDArray[np.float32], frequency: float, axes: tuple[NDArray[np.float32], ...]
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


def fresh_points(dims: int, reach: float, rng: np.random.Generator) -> tuple[NDArray[np.float32], ...]:
    """
    `FRESH` points as the far-coordinate probe draws them: the largest coordinate's magnitude uniform in [0, ``reach``),
    signs mixed, on a random axis, the others smaller. Uniform over the area would put about 1 point in 1,700 within
    100 units of the origin, where the coordinate-scaled bound is at its floor and tightest; this puts 1 in 40 there.
    """
    big = rng.uniform(0.0, reach, FRESH) * rng.choice([-1.0, 1.0], FRESH)
    axes = [rng.uniform(-1.0, 1.0, FRESH) * np.abs(big) for _ in range(dims)]
    which = rng.integers(0, dims, FRESH)
    return tuple(np.where(which == d, big, axes[d]).astype(np.float32) for d in range(dims))


def fresh_grids(origin: Mapping[str, Any]) -> list[tuple[int, ...]]:
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
            if scale > LARGEST and output == "warp":
                raise Finding(f"{feature} warp: {scale} past {LARGEST}")
            if scale > LARGEST:
                raise Finding(f"{feature}: {scale} past {LARGEST}; a jump the DISCRETE list does not name")
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


def read_records(folder: Path) -> list[dict[str, Any]]:
    """
    Every GPU adapter's measurement record in ``folder``, by file name; an empty list when it holds none.

    :raises Finding: A file that cannot be read, is not JSON, or is not a record: an object with an ``adapter`` object
        naming its ``device`` and ``backend_type``, a ``host`` and a ``commit`` string, and a ``cases`` object whose
        every case is `measure`'s shape (its fresh points `measure_fresh`'s, under a ``fresh`` header); the message
        names the file and the case.
    """
    records = []
    for path in sorted(folder.glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError) as e:
            raise Finding(f"{path}: cannot be read ({e})") from e
        except json.JSONDecodeError as e:
            raise Finding(f"{path}: not JSON ({e})") from e
        adapter = record.get("adapter") if isinstance(record, dict) else None
        if not (
            isinstance(adapter, dict)
            and all(isinstance(adapter.get(k), str) for k in ("device", "backend_type"))
            and isinstance(record.get("host"), str)
            and isinstance(record.get("commit"), str)
            and isinstance(record.get("cases"), dict)
        ):
            raise Finding(
                f"{path}: not a measurement record (an object with an 'adapter' object naming its device and "
                f"backend_type, a 'host' and a 'commit' string, and a 'cases' object)"
            )
        for case_id, s in record["cases"].items():
            why = _malformed_case(s)
            if why:
                raise Finding(f"{path}: case {case_id}: {why}")
        has_fresh = any("fresh" in s for s in record["cases"].values())
        header = record.get("fresh")
        if has_fresh and not (isinstance(header, dict) and all(_is_count(header.get(k)) for k in ("points", "seed"))):
            raise Finding(f"{path}: its cases have fresh points, but it has no 'fresh' header with points and seed")
        records.append(record)
    return records


#: The numbers of a case's measurement, and of its fresh points' (`_numbers`).
_NUMBERS = ("max_abs", "max_normalised", "p99_normalised", "correlation", "ref_range")


def _is_number(v: object) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool)


def _is_count(v: object) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _malformed_numbers(s: object) -> str | None:
    """Why ``s`` is not `_numbers`' shape, or None: every number a number, ``outside`` one for every candidate."""
    if not isinstance(s, dict):
        return "not an object"
    for key in _NUMBERS:
        if not _is_number(s.get(key)):
            return f"{key} is {s.get(key)!r}, not a number"
    outside = s.get("outside")
    if not isinstance(outside, dict) or not all(_is_number(outside.get(k)) for k in CANDIDATE_KEYS):
        return f"outside is not a number for every candidate bound ({CANDIDATE_KEYS[0]} to {CANDIDATE_KEYS[-1]})"
    return None


def _malformed_case(s: object) -> str | None:
    """Why ``s`` is not a case as `measure` writes it (its fresh points as `measure_fresh` does), or None."""
    why = _malformed_numbers(s)
    if why:
        return why
    if not isinstance(s.get("feature"), str) or s.get("output") not in ("noise", "warp"):
        return f"feature {s.get('feature')!r} and output {s.get('output')!r}, not a name and 'noise' or 'warp'"
    if "fresh" in s:
        why = _malformed_numbers(s["fresh"])
        if why:
            return f"fresh: {why}"
    return None


def check_cases(records: list[dict[str, Any]], hog_ids: set[str], folder: Path) -> None:
    """
    Every record holds the same cases, and they are exactly the hog set's: a rule over part of the set, or a stale
    record measured before a case was added, is not a number to derive.

    :raises Finding: No records, records holding different cases or measured with different fresh points, or cases
        that are not the hog set's.
    """
    if not records:
        raise Finding(f"{folder}: no measurement records (*.json) to derive from")
    first = set(records[0]["cases"])
    for rec in records[1:]:
        if set(rec["cases"]) != first:
            raise Finding(f"{folder}: the records hold not the same cases ({label(records[0])} vs {label(rec)})")
        if rec.get("fresh") != records[0].get("fresh"):
            raise Finding(
                f"{folder}: the records were measured with different fresh points ({label(records[0])}: "
                f"{records[0].get('fresh')}, {label(rec)}: {rec.get('fresh')}); measure every adapter again"
            )
    missing, extra = sorted(hog_ids - first), sorted(first - hog_ids)
    if missing or extra:
        raise Finding(
            f"{folder}: the records are not the hog set's cases: missing {len(missing)} {missing[:3]}, "
            f"{len(extra)} not in it {extra[:3]}"
        )


def measured_range(vectors: conformance.Vectors) -> dict[str, object]:
    """The frequencies and the largest noise-space coordinate of the hog set: what the rules hold over."""
    hog = [c for c in vectors.cases if c.set == "hog"]
    reach = max(
        float(np.max(np.abs(np.stack(vectors.point_sets[c.point_set].axes)))) * abs(c.params.frequency) for c in hog
    )
    return {
        "frequency": sorted({c.params.frequency for c in hog}),
        "noise_coordinate_max": math.ceil(reach * 100) / 100,
    }


#: Set on CI to the pull request's head, since a pull_request run checks out a merge commit nobody else can measure at.
COMMIT_ENV = "HOG_NOISE_MEASURED_COMMIT"
#: Where a measurement was taken (CI sets "ci-windows" or "ci-ubuntu"); two runs of one adapter are kept apart by it.
HOST_ENV = "HOG_NOISE_MEASURE_HOST"


#: A commit as a folder name: 7 to 40 hex digits, nothing that could be a path.
_HEX_COMMIT = re.compile(r"[0-9a-fA-F]{7,40}")


def _commit() -> str:
    """
    The measured commit, shortened to seven: `COMMIT_ENV` when set, else ``git rev-parse --short HEAD``.

    :raises ValueError: A pinned commit, or git's answer, that is not 7 to 40 hex digits (it becomes a folder name).
    :raises subprocess.CalledProcessError: git exited nonzero.
    """
    pinned = os.environ.get(COMMIT_ENV, "").strip()
    if pinned:
        if not _HEX_COMMIT.fullmatch(pinned):
            raise ValueError(f"{COMMIT_ENV} is {pinned!r}, not a commit of 7 to 40 hex digits")
        return pinned[:7].lower()
    answer = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True, cwd=ROOT
    ).stdout.strip()
    if not _HEX_COMMIT.fullmatch(answer):
        raise ValueError(f"git rev-parse --short HEAD answered {answer!r}, not a commit; set {COMMIT_ENV}")
    return answer[:7].lower()


def label(record: dict[str, Any]) -> str:
    """An adapter's record, named: device, back end and where it ran."""
    return f"{record['adapter']['device']} ({record['adapter']['backend_type']}) on {record['host']}"


def _slug(text: str) -> str:
    """``text`` as a file name: lower case, each run of other characters one hyphen."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def run(out: Path) -> Path:
    """Measure every hog case on this machine's GPU adapter and write its record to ``out``; returns the file."""
    from hog_noise import gpu

    commit = _commit()
    _LOGGER.info(f"run: measuring the hog set under {VECTORS} at commit {commit}, writing to {out}")
    vectors = conformance.load(VECTORS)
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
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{_slug(label(data))}.json"
    path.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    _LOGGER.info(f"measured {len(data['cases'])} hog cases on {info['device']} ({info['backend_type']}) -> {path}")
    return path


def _tables(records: list[dict[str, Any]], rules: list[dict[str, Any]]) -> tuple[str, str]:
    """``record.md`` (per case and adapter) and ``portability-gpu.md`` (per feature and adapter)."""
    adapters = [label(r) for r in records]
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
    return "\n".join(per_case) + "\n", "\n".join(lines) + "\n"


def _replace(path: Path, text: str) -> None:
    """Write ``text`` to a temporary file beside ``path``, then put it in place in one step: never half-written."""
    tmp = path.with_name(f"{path.name}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8", newline="\n")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def derive_files(folder: Path) -> list[Path]:
    """
    Derive the rules from every measurement record in ``folder`` (under ``vectors/``) and write the three files;
    returns them. Every text is built before any is written, and each is put in place whole.

    :raises Finding: No records, a malformed one, records that are not all exactly the hog set's cases, or a measurement
        the rules cannot turn into a number. Nothing is written then.
    """
    files = sorted(p.name for p in folder.glob("*.json"))
    _LOGGER.info(f"derive: {len(files)} measurement records in {folder}: {files}")
    records = read_records(folder)
    vectors = conformance.load(VECTORS, sets="hog")
    check_cases(records, {c.id for c in vectors.cases if c.set == "hog"}, folder)
    rules = derive(records)
    tolerance = {
        "format": conformance.TOLERANCE_FORMAT,
        "rendering": "wgpu",
        "range": measured_range(vectors),
        "measured": {
            "record": folder.relative_to(VECTORS).as_posix() + "/",
            "adapters": [label(r) for r in records],
        },
        "rules": rules,
    }
    record_md, portability = _tables(records, rules)
    texts = {
        VECTORS / "tolerance" / "wgpu.json": json.dumps(tolerance, indent=2) + "\n",
        VECTORS / "portability-gpu.md": portability,
        folder / "record.md": record_md,
    }
    (VECTORS / "tolerance").mkdir(parents=True, exist_ok=True)
    for path, text in texts.items():
        _replace(path, text)
    written = list(texts)
    _LOGGER.info(f"derived {len(rules)} rules from {len(records)} adapters: {[str(p) for p in written]}")
    return written


def main(argv: list[str] | None = None) -> int:
    """
    ``run`` (measure this machine's GPU adapter) or ``derive <folder>`` (the rules and tables from every record in it).

    :return: 0, or 1 on a measurement finding, which is logged for the owner.
    """
    parser = argparse.ArgumentParser(prog="hog-noise-measure-gpu", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    run_p = sub.add_parser("run", help="measure this machine's adapter")
    run_p.add_argument("--out", type=Path, default=None, help="default: vectors/reports/gpu/<commit>/")
    derive_p = sub.add_parser("derive", help="derive the rules and tables from every adapter's record in a folder")
    derive_p.add_argument("folder", type=Path)
    args = parser.parse_args(argv)
    _logging.basicConfig(level=_logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    if args.command == "run":
        try:
            run(args.out or VECTORS / "reports" / "gpu" / _commit())
        except Finding as e:
            _LOGGER.error(f"a finding for the owner, not a number: {e}")
            return 1
        return 0
    try:
        derive_files(args.folder.resolve())
    except Finding as e:
        _LOGGER.error(f"a finding for the owner, not a number: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
