"""
HogNoise: check any rendering of the noise against the committed reference vectors.
Package: hog_noise/conformance

The vectors are raw little-endian float32 files and one ``manifest.json`` (the format:
Docs/superpowers/specs/2026-11-11-conformance-harness.md). `load` reads them and verifies every file against its digest;
`check` samples each selected case through the caller's ``sample`` (and ``warp``) and compares it by points, by shape,
or advisory. The advisory rule is `compare`'s, called and not restated. Standard library and numpy only.

    python -m hog_noise.conformance vectors --rendering numpy
"""

import dataclasses
import fnmatch
import hashlib
import json
import logging as _logging
from collections.abc import Callable, Mapping
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Literal

import numpy as np
from numpy.typing import NDArray

from hog_noise import compare
from hog_noise.params import NoiseParams

_MODULE_NAME = "hog_noise.conformance"
__version__ = "0.1.0"
__updated__ = "2026-11-13"
_LOGGER = _logging.getLogger(_MODULE_NAME)

#: The manifest format this module reads.
FORMAT = 1
_F32 = np.dtype("<f4")


class ConformanceError(ValueError):
    """The vectors folder does not match its manifest, or the manifest is malformed."""


@dataclasses.dataclass(frozen=True)
class Bound:
    """
    How far a value may be from its reference.

    :param scale: The allowed absolute difference; 0 means bit-identical.
    :param coordinate_scaled: Scale it per point by ``max(1, max(abs(axis)) * frequency)``, for renderings whose error
        grows with the coordinate (float32 on a GPU).
    """

    scale: float
    coordinate_scaled: bool = False

    def __post_init__(self) -> None:
        if not self.scale >= 0.0:
            raise ValueError(f"a bound is not negative: {self.scale}")

    def per_point(self, frequency: float, axes: tuple[NDArray, ...]) -> NDArray[np.float64]:
        """The allowed difference at every point of a point set, given its coordinate arrays."""
        n = len(axes[0])
        if not self.coordinate_scaled:
            return np.full(n, float(self.scale))
        magnitude = np.max(np.abs(np.stack([np.asarray(a, np.float64) for a in axes])), axis=0)
        return float(self.scale) * np.maximum(1.0, magnitude * abs(float(frequency)))


def normalised_difference(diff: NDArray, allowed: NDArray) -> NDArray[np.float64]:
    """``diff / allowed`` per point; where ``allowed`` is 0 it is 0 for an exact match and infinity otherwise."""
    diff = np.asarray(diff, np.float64)
    allowed = np.asarray(allowed, np.float64)
    safe = np.where(allowed > 0.0, allowed, 1.0)
    return np.where(allowed > 0.0, diff / safe, np.where(diff == 0.0, 0.0, np.inf))


@dataclasses.dataclass(frozen=True, eq=False)
class PointSet:
    """Named coordinates every case on it is sampled at: ``axes`` is (x, y) or (x, y, z), float32."""

    name: str
    dims: int
    count: int
    axes: tuple[NDArray[np.float32], ...]
    origin: Mapping[str, object] | None = None  # the manifest's "from": how a grid point set was made


@dataclasses.dataclass(frozen=True, eq=False)
class Case:
    """One reference output: its parameters, where it is sampled, and how it is compared."""

    id: str
    set: str
    source: Mapping[str, object]
    params: NoiseParams
    point_set: str
    output: Literal["noise", "warp"]
    file: str
    compare: Mapping[str, object]
    values: NDArray[np.float32]


@dataclasses.dataclass(frozen=True, eq=False)
class Vectors:
    """A loaded, verified vectors folder."""

    root: Path
    point_sets: Mapping[str, PointSet]
    cases: tuple[Case, ...]

    def case(self, case_id: str) -> Case:
        for case in self.cases:
            if case.id == case_id:
                return case
        raise KeyError(f"no case {case_id!r} in {self.root}")


_COMPARE_KINDS = ("points", "shape", "advisory")


def _inside(root: Path, rel: str) -> Path:
    """
    The file a manifest path names, refused before use if it leaves the folder (Docs/standards/testing.md, *Error
    paths*): absolute, a drive, ``..``, a backslash, or a symlink that resolves outside. The digest cannot vouch for
    it, since the manifest supplies both.
    """
    posix, windows = PurePosixPath(rel), PureWindowsPath(rel)
    if not rel or "\\" in rel or posix.is_absolute() or windows.drive or windows.root or ".." in posix.parts:
        raise ConformanceError(f"{rel!r}: a manifest path is relative, uses '/', and stays inside the folder")
    path = root / rel
    if not path.resolve().is_relative_to(root.resolve()):
        raise ConformanceError(f"{rel}: resolves outside {root.resolve()}")
    return path


def _positive_int(name: str, value: object, what: str) -> int:
    """A positive integer from the manifest; a bool, a string or a float is refused, not converted."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ConformanceError(f"point set {name}: {what} is {value!r}, not a positive integer")
    return value


def load(vectors: str | Path, *, sets: str | tuple[str, ...] | None = None) -> Vectors:
    """
    Read a vectors folder and verify every file it names against the manifest's digests and sizes.

    :param vectors: The folder.
    :param sets: Load only the cases of these reference sets (``"original"`` or ``("original",)``), reading only their
        files; the default is every set. The folder-wide checks (every ``.f32`` file has a digest, every digest names
        a used file) run only when every set is loaded.
    :raises ConformanceError: A missing or malformed manifest, a path that leaves the folder, a file that is missing,
        has no digest, or whose digest or size does not match, a ``.f32`` file the manifest does not list or a digest
        that names no file in use, an unknown format, output or comparison kind, a case on an unknown point set, a
        malformed parameter record, or a duplicate case id. Every message names the part that is wrong.
    """
    root = Path(vectors)
    if isinstance(sets, str):
        sets = (sets,)  # a bare name is one set, never matched as a substring
    try:
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    except OSError as e:
        raise ConformanceError(f"{root / 'manifest.json'}: cannot be read ({e})") from e
    except UnicodeDecodeError as e:
        raise ConformanceError(f"{root / 'manifest.json'}: not UTF-8 ({e})") from e
    except json.JSONDecodeError as e:
        raise ConformanceError(f"{root / 'manifest.json'}: not JSON ({e})") from e
    found = manifest.get("format") if isinstance(manifest, dict) else None
    if found != FORMAT:
        raise ConformanceError(f"{root}: manifest format {found!r}, this reads {FORMAT}")
    for key, kind in (("point_sets", dict), ("cases", list), ("files", dict)):
        if not isinstance(manifest.get(key), kind):
            raise ConformanceError(f"{root}: the manifest's {key!r} is missing or not a JSON {kind.__name__}")
    digests: Mapping[str, str] = manifest["files"]
    used: set[str] = set()

    def read(rel: str, count: int) -> NDArray[np.float32]:
        if not isinstance(rel, str) or rel not in digests:
            raise ConformanceError(f"{rel} is named in the manifest but has no digest in files")
        used.add(rel)
        try:
            data = _inside(root, rel).read_bytes()
        except OSError as e:
            raise ConformanceError(f"{rel}: cannot be read ({e})") from e
        if hashlib.sha256(data).hexdigest() != digests[rel]:
            raise ConformanceError(f"{rel}: its sha256 does not match the manifest")
        if len(data) != count * 4:
            raise ConformanceError(f"{rel}: {len(data) // 4} float32 values, expected {count}")
        return np.frombuffer(data, dtype=_F32).astype(np.float32)

    point_sets: dict[str, PointSet] = {}
    for name, ps in manifest["point_sets"].items():
        if not isinstance(ps, dict) or not isinstance(ps.get("axes"), list):
            raise ConformanceError(f"point set {name}: not an object with an 'axes' list")
        dims, count = _positive_int(name, ps.get("dims"), "dims"), _positive_int(name, ps.get("count"), "count")
        if dims not in (2, 3):
            raise ConformanceError(f"point set {name}: dims is {dims}; a point set is 2 or 3 dimensional")
        if len(ps["axes"]) != dims:
            raise ConformanceError(f"point set {name}: {len(ps['axes'])} axes for {dims} dims")
        axes = tuple(read(a, count) for a in ps["axes"])
        point_sets[name] = PointSet(name, dims, count, axes, ps.get("from"))

    cases: list[Case] = []
    for c in manifest["cases"]:
        case_id = c.get("id", "<no id>") if isinstance(c, dict) else "<not an object>"
        if sets is not None and isinstance(c, dict) and c.get("set") not in sets:
            continue
        try:
            cases.append(_case(c, point_sets, read))
        except ConformanceError as e:
            raise ConformanceError(f"{case_id}: {e}") from e
        except (AttributeError, KeyError, TypeError, ValueError) as e:
            raise ConformanceError(f"{case_id}: malformed ({type(e).__name__}: {e})") from e
    ids = [case.id for case in cases]
    if len(set(ids)) != len(ids):
        raise ConformanceError(f"duplicate case ids: {sorted({i for i in ids if ids.count(i) > 1})}")
    if sets is None:
        unused = sorted(set(digests) - used)
        if unused:
            raise ConformanceError(f"files lists digests no point set or case uses: {unused[:5]}")
        on_disk = {p.relative_to(root).as_posix() for p in root.rglob("*.f32")}
        unlisted = sorted(on_disk - set(digests))
        if unlisted:
            raise ConformanceError(f".f32 files the manifest does not list: {unlisted[:5]}")
    _LOGGER.debug(f"loaded {len(cases)} cases on {len(point_sets)} point sets from {root}")
    return Vectors(root, point_sets, tuple(sorted(cases, key=lambda case: case.id)))


def _number(value: object, what: str, lo: float | None = None, hi: float | None = None) -> float:
    """A JSON number from a comparison rule, within [lo, hi] when given; a bool, a string or NaN is refused."""
    if isinstance(value, bool) or not isinstance(value, int | float) or value != value:
        raise ConformanceError(f"{what} is {value!r}, not a number")
    if (lo is not None and value < lo) or (hi is not None and value > hi):
        raise ConformanceError(f"{what} is {value!r}, outside [{lo}, {hi}]")
    return float(value)


def _check_rule(rule: object) -> None:
    """Every field a comparison kind reads, present and of the right type, so a bad rule fails at load, not in check."""
    if not isinstance(rule, dict) or rule.get("kind") not in _COMPARE_KINDS:
        kind = rule.get("kind") if isinstance(rule, dict) else rule
        raise ConformanceError(f"unknown comparison {kind!r}")
    if rule["kind"] == "points":
        bound = rule.get("bound")
        if not isinstance(bound, dict):
            raise ConformanceError(f"a points rule needs a 'bound' object, not {bound!r}")
        _number(bound.get("scale"), "bound.scale", lo=0.0)
        if not isinstance(bound.get("coordinate_scaled", False), bool):
            raise ConformanceError(f"bound.coordinate_scaled is {bound['coordinate_scaled']!r}, not true or false")
        if "min_correlation" in rule:
            _number(rule["min_correlation"], "min_correlation")
        if "within" in rule:
            within = rule["within"]
            if not isinstance(within, dict):
                raise ConformanceError(f"within is {within!r}, not an object with scale and fraction")
            _number(within.get("scale"), "within.scale", lo=0.0)
            _number(within.get("fraction"), "within.fraction", 0.0, 1.0)
    elif rule["kind"] == "shape":
        for key in ("range", "std_ratio"):
            if key in rule:
                pair = rule[key]
                if not isinstance(pair, list) or len(pair) != 2:
                    raise ConformanceError(f"{key} is {pair!r}, not [lo, hi]")
                _number(pair[0], f"{key}[0]")
                _number(pair[1], f"{key}[1]")
        for key in ("mean_within", "std_within"):
            if key in rule:
                _number(rule[key], key)


def _case(c: Mapping[str, object], point_sets: Mapping[str, PointSet], read: Callable[[str, int], NDArray]) -> Case:
    for key in ("id", "set", "point_set", "output", "file"):
        if not isinstance(c.get(key), str):
            raise ConformanceError(f"its {key!r} is {c.get(key)!r}, not a string")
    if not isinstance(c.get("params"), dict):
        raise ConformanceError(f"its 'params' is {c.get('params')!r}, not an object")
    if not isinstance(c.get("source", {}), dict):
        raise ConformanceError(f"its 'source' is {c['source']!r}, not an object")
    if c["point_set"] not in point_sets:
        raise ConformanceError(f"unknown point set {c['point_set']!r}")
    if c["output"] not in ("noise", "warp"):
        raise ConformanceError(f"unknown output {c['output']!r}")
    _check_rule(c.get("compare"))
    ps = point_sets[c["point_set"]]
    width = ps.dims if c["output"] == "warp" else 1
    values = read(c["file"], ps.count * width)
    return Case(
        id=c["id"],
        set=c["set"],
        source=c.get("source", {}),
        params=NoiseParams.from_dict(c["params"]),
        point_set=c["point_set"],
        output=c["output"],
        file=c["file"],
        compare=c["compare"],
        values=values.reshape(ps.count, width) if width > 1 else values,
    )


#: ``sample(params, xs, ys, zs)``: N float32 values; ``zs`` is None on a 2D point set. ``warp`` returns N x dims.
Sample = Callable[[NoiseParams, NDArray, NDArray, NDArray | None], NDArray]


@dataclasses.dataclass(frozen=True)
class CaseResult:
    """
    One case's outcome. ``status`` is ``pass``, ``fail``, ``unsupported`` or ``skipped``, or for an advisory case its
    match class from `compare.classify`.
    """

    id: str
    kind: str
    status: str
    max_abs: float | None = None
    max_normalised: float | None = None
    detail: str = ""
    correlation: float | None = None
    needs_review: bool | None = None
    verdict: str | None = None


@dataclasses.dataclass(frozen=True)
class Report:
    """Every checked case's outcome, in case-id order."""

    results: tuple[CaseResult, ...]

    @property
    def ok(self) -> bool:
        """
        No case failed: a ``points`` or ``shape`` case past its rule, or any case whose output had the wrong shape.
        Unsupported and skipped cases never fail it, and an advisory case fails it only by a wrong-shaped output.
        """
        return not any(r.status == "fail" for r in self.results)

    @property
    def complete(self) -> bool:
        """Nothing was unsupported or skipped."""
        return not any(r.status in ("unsupported", "skipped") for r in self.results)

    def count(self, status: str) -> int:
        return sum(1 for r in self.results if r.status == status)

    def table(self) -> str:
        """A markdown table, one row per case, under a one-line summary."""

        def num(v: float | None) -> str:
            return "" if v is None else f"{v:.2e}"

        advisory = sum(1 for r in self.results if r.kind == "advisory")
        lines = [
            f"{self.count('pass')} pass, {self.count('fail')} fail, {self.count('unsupported')} unsupported, "
            f"{self.count('skipped')} skipped, {advisory} advisory",
            "",
            "| Case | Kind | Status | Max abs | Max / bound | Note |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for r in self.results:
            note = r.detail
            if r.kind == "advisory" and r.correlation is not None:  # an unsupported or skipped one has no statistics
                note = f"corr {r.correlation:.6f}" + (", needs review" if r.needs_review else "")
                if r.verdict:
                    note += f", {r.verdict}"
            lines.append(f"| {r.id} | {r.kind} | {r.status} | {num(r.max_abs)} | {num(r.max_normalised)} | {note} |")
        return "\n".join(lines) + "\n"


def check(
    sample: Sample,
    vectors: str | Path | Vectors,
    *,
    reference: Literal["hog", "original", "both"] = "hog",
    bound: Bound | None = None,
    warp: Sample | None = None,
    select: str | None = None,
) -> Report:
    """
    Sample every selected case and compare it with its reference.

    :param sample: The rendering's noise entry point.
    :param vectors: A vectors folder, or one already loaded.
    :param reference: Which set to check against.
    :param bound: Replaces the bound of every ``points`` case checked (``min_correlation`` and ``within`` still apply).
    :param warp: The rendering's warp entry point; without it, warp cases are skipped.
    :param select: An `fnmatch` pattern over case ids.
    """
    data = vectors if isinstance(vectors, Vectors) else load(vectors)
    sets = {"hog": ("hog",), "original": ("original",), "both": ("hog", "original")}[reference]
    verdicts = compare.Verdicts(data.root / "accepted.json")
    results = []
    for case in data.cases:
        if case.set not in sets or (select is not None and not fnmatch.fnmatchcase(case.id, select)):
            continue
        results.append(_check_case(case, data.point_sets[case.point_set], sample, warp, bound, verdicts))
    report = Report(tuple(results))
    _LOGGER.info(
        f"checked {len(results)} cases against {reference}: {report.count('fail')} failed, "
        f"{report.count('unsupported')} unsupported, {report.count('skipped')} skipped"
    )
    return report


def _check_case(
    case: Case, ps: PointSet, sample: Sample, warp: Sample | None, bound: Bound | None, verdicts: compare.Verdicts
) -> CaseResult:
    kind = str(case.compare["kind"])
    fn = warp if case.output == "warp" else sample
    if fn is None:
        return CaseResult(case.id, kind, "skipped", detail="no warp entry point")
    zs = ps.axes[2] if ps.dims == 3 else None
    try:
        ours = np.asarray(fn(case.params, ps.axes[0], ps.axes[1], zs), dtype=np.float32)
    except NotImplementedError as e:
        return CaseResult(case.id, kind, "unsupported", detail=str(e))
    if ours.shape != case.values.shape:
        return CaseResult(case.id, kind, "fail", detail=f"shape {ours.shape}, expected {case.values.shape}")
    if kind == "points":
        return _points(case, ps, ours, bound)
    if kind == "shape":
        return _shape(case, ours)
    stats = compare.compare_values(ours, case.values)
    return CaseResult(
        case.id,
        kind,
        stats.match_class,
        stats.max_abs,
        correlation=stats.correlation,
        needs_review=stats.needs_review,
        verdict=verdicts.verdict_for(str(case.source.get("feature", ""))),
    )


def _points(case: Case, ps: PointSet, ours: NDArray[np.float32], bound: Bound | None) -> CaseResult:
    rule = case.compare
    b = bound or Bound(float(rule["bound"]["scale"]), bool(rule["bound"].get("coordinate_scaled", False)))
    diff = np.abs(ours.astype(np.float64) - case.values.astype(np.float64))
    if diff.ndim == 2:
        diff = diff.max(axis=1)  # every component of a warped point is held to that point's bound
    allowed = b.per_point(case.params.frequency, ps.axes)
    failures = []
    past = int(np.count_nonzero(~(diff <= allowed)))  # NaN counts as past
    if past:
        failures.append(f"{past} of {diff.size} points past the bound")
    if "min_correlation" in rule:
        corr = compare.compare_values(ours, case.values).correlation
        if not corr >= float(rule["min_correlation"]):
            failures.append(f"correlation {corr:.6f} below {rule['min_correlation']}")
    if "within" in rule:
        fraction = float(np.mean(diff <= float(rule["within"]["scale"])))
        if not fraction >= float(rule["within"]["fraction"]):
            failures.append(f"{fraction:.4f} within {rule['within']['scale']}, below {rule['within']['fraction']}")
    return CaseResult(
        case.id,
        "points",
        "fail" if failures else "pass",
        float(diff.max()),
        float(normalised_difference(diff, allowed).max()),
        "; ".join(failures),
    )


def _shape(case: Case, ours: NDArray[np.float32]) -> CaseResult:
    rule = case.compare
    a = ours.astype(np.float64)
    r = case.values.astype(np.float64)
    failures = []
    if rule.get("finite") and not np.isfinite(a).all():
        failures.append("not finite")
    if "range" in rule:
        lo, hi = (float(v) for v in rule["range"])
        if not (a.min() >= lo and a.max() <= hi):
            failures.append(f"range [{a.min():.4f}, {a.max():.4f}] outside [{lo}, {hi}]")
    if "mean_within" in rule and not abs(a.mean() - r.mean()) <= float(rule["mean_within"]):
        failures.append(f"mean {a.mean():.4f} vs {r.mean():.4f}")
    if "std_within" in rule and not abs(a.std() - r.std()) <= float(rule["std_within"]):
        failures.append(f"std {a.std():.4f} vs {r.std():.4f}")
    if "std_ratio" in rule:
        lo, hi = (float(v) for v in rule["std_ratio"])
        ratio = a.std() / max(r.std(), 1e-6)
        if not lo <= ratio <= hi:
            failures.append(f"std ratio {ratio:.3f} outside [{lo}, {hi}]")
    return CaseResult(
        case.id, "shape", "fail" if failures else "pass", float(np.abs(a - r).max()), None, "; ".join(failures)
    )


def renderings(name: str) -> tuple[Sample, Sample]:
    """
    ``sample`` and ``warp`` callables for one of this package's renderings, by backend name (numpy, numba,
    fastnoiselite). A rendering without a warp entry point raises `NotImplementedError` from ``warp``. One sampler is
    built per distinct parameter record and reused, so a run over the vectors builds each once.
    """
    from hog_noise.samplers import make_sampler

    built: dict[NoiseParams, object] = {}

    def sampler_for(params: NoiseParams):
        if params not in built:
            built[params] = make_sampler(params, backend=name)[0]
        return built[params]

    def sample(params: NoiseParams, xs: NDArray, ys: NDArray, zs: NDArray | None) -> NDArray:
        sampler = sampler_for(params)
        out = np.empty(len(xs), np.float32)
        return sampler.sample_points_2d(xs, ys, out) if zs is None else sampler.sample_points(xs, ys, zs, out)

    def warp(params: NoiseParams, xs: NDArray, ys: NDArray, zs: NDArray | None) -> NDArray:
        sampler = sampler_for(params)
        method = "warp_points_2d" if zs is None else "warp_points"
        if not hasattr(sampler, method):
            raise NotImplementedError(f"{name} has no {method} entry point")
        return sampler.warp_points_2d(xs, ys) if zs is None else sampler.warp_points(xs, ys, zs)

    return sample, warp


def main(argv: list[str] | None = None) -> int:
    """``python -m hog_noise.conformance vectors --rendering numpy``: prints the table; exits 0 when it is ok."""
    import argparse

    parser = argparse.ArgumentParser(prog="python -m hog_noise.conformance", description=__doc__.split("\n\n")[0])
    parser.add_argument("vectors", type=Path, help="the vectors folder")
    parser.add_argument("--rendering", default="numpy", help="numpy, numba or fastnoiselite")
    parser.add_argument("--reference", choices=("hog", "original", "both"), default="hog")
    parser.add_argument("--select", default=None, help="an fnmatch pattern over case ids")
    parser.add_argument("--bound", type=float, default=None, help="replace every points case's bound")
    parser.add_argument("--coordinate-scaled", action="store_true", help="scale --bound per point")
    args = parser.parse_args(argv)
    if args.coordinate_scaled and args.bound is None:
        parser.error("--coordinate-scaled needs --bound")
    _logging.basicConfig(level=_logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    from hog_noise.backends import BackendUnavailable, registered
    from hog_noise.samplers import CAPABILITY, make_sampler

    names = [backend.name for backend in registered(CAPABILITY)]
    if args.rendering not in names:
        parser.exit(2, f"{parser.prog}: error: unknown --rendering {args.rendering!r}; one of {names}\n")
    try:
        make_sampler(NoiseParams(), backend=args.rendering)  # a rendering not installed here fails now, not mid-run
        vectors = load(args.vectors)
    except (BackendUnavailable, ConformanceError) as e:
        parser.exit(2, f"{parser.prog}: error: {e}\n")
    sample, warp = renderings(args.rendering)
    bound = Bound(args.bound, args.coordinate_scaled) if args.bound is not None else None
    report = check(sample, vectors, reference=args.reference, bound=bound, warp=warp, select=args.select)
    print(report.table())
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
