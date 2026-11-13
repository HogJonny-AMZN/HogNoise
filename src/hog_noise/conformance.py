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
import hashlib
import json
import logging as _logging
from collections.abc import Mapping
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Literal

import numpy as np
from numpy.typing import NDArray

from hog_noise.params import NoiseParams

_MODULE_NAME = "hog_noise.conformance"
__version__ = "0.1.0"
__updated__ = "2026-11-12"
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


def load(vectors: str | Path) -> Vectors:
    """
    Read a vectors folder and verify every file it names against the manifest's digests and sizes.

    :raises ConformanceError: A path that leaves the folder, a file with no digest, a digest or size that does not
        match, an unknown format, output or comparison kind, a case on an unknown point set, or a duplicate case id.
    """
    root = Path(vectors)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("format") != FORMAT:
        raise ConformanceError(f"{root}: manifest format {manifest.get('format')!r}, this reads {FORMAT}")
    digests: Mapping[str, str] = manifest["files"]

    def read(rel: str, count: int) -> NDArray[np.float32]:
        if rel not in digests:
            raise ConformanceError(f"{rel} is named in the manifest but has no digest in files")
        data = _inside(root, rel).read_bytes()
        if hashlib.sha256(data).hexdigest() != digests[rel]:
            raise ConformanceError(f"{rel}: its sha256 does not match the manifest")
        if len(data) != count * 4:
            raise ConformanceError(f"{rel}: {len(data) // 4} float32 values, expected {count}")
        return np.frombuffer(data, dtype=_F32).astype(np.float32)

    point_sets: dict[str, PointSet] = {}
    for name, ps in manifest["point_sets"].items():
        if len(ps["axes"]) != ps["dims"]:
            raise ConformanceError(f"point set {name}: {len(ps['axes'])} axes for {ps['dims']} dims")
        axes = tuple(read(a, ps["count"]) for a in ps["axes"])
        point_sets[name] = PointSet(name, ps["dims"], ps["count"], axes, ps.get("from"))

    cases: list[Case] = []
    for c in manifest["cases"]:
        if c["point_set"] not in point_sets:
            raise ConformanceError(f"{c['id']}: unknown point set {c['point_set']!r}")
        if c["output"] not in ("noise", "warp"):
            raise ConformanceError(f"{c['id']}: unknown output {c['output']!r}")
        if c["compare"]["kind"] not in _COMPARE_KINDS:
            raise ConformanceError(f"{c['id']}: unknown comparison {c['compare']['kind']!r}")
        ps = point_sets[c["point_set"]]
        width = ps.dims if c["output"] == "warp" else 1
        values = read(c["file"], ps.count * width)
        cases.append(
            Case(
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
        )
    ids = [case.id for case in cases]
    if len(set(ids)) != len(ids):
        raise ConformanceError(f"duplicate case ids: {sorted({i for i in ids if ids.count(i) > 1})}")
    _LOGGER.debug(f"loaded {len(cases)} cases on {len(point_sets)} point sets from {root}")
    return Vectors(root, point_sets, tuple(sorted(cases, key=lambda case: case.id)))
