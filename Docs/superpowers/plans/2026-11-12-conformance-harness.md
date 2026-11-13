# The conformance harness: implementation plan

**Status:** Accepted 2026-11-12 (the owner: "accepted"). Written 2026-11-12 from
[the spec](../specs/2026-11-11-conformance-harness.md), Accepted the same day. The build ticks each step as it lands.

> **For agentic workers:** REQUIRED SUB-SKILL: use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to carry this out task by task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** the committed vectors become raw float32 files and one manifest under a top-level `vectors/`, and
`hog_noise.conformance` checks any rendering against them, with every comparison the suite makes today kept at today's
limits.

**Architecture:** one module, `src/hog_noise/conformance.py` (`Bound`, `load`, `check`, `Report`, the command line),
standard library and numpy only. The writer and the rules that say how each captured array is compared live in
`tools/gen_noise_vectors.py`, so the one-time conversion and any future capture write through the same code. The
suite reads `vectors/` through `conformance.load`, and the reference comparisons become `check` calls.

**Tech stack:** Python 3.11 to 3.13, numpy (1.26 and the latest), numba where installed, pytest through the `pytest`
console script (`uv run pytest`, never `python -m pytest`), `uv run python tools/check.py` as the gate.

---

## Before you start

- Read the spec end to end; it is the contract and this plan is how to meet it. Where they disagree, the spec wins and
  this plan is the bug.
- Read [the project ledger](../../standards/failure-modes-project.md), above all P-2 (a test that rewrites a committed
  file), P-6 (describe today's code from the code) and P-5/P-7 (a pull request's state and its merge).
- Work on a branch from `main`, never on the local `main` (it is private history and never pushed). Commits are signed
  off (`git commit -s`) with the owner's identity and no AI attribution. Write each commit message to a file and pass
  it with `-F`.
- Every module keeps its `if __name__ == "__main__":` block. A script or patch with quotes or backslashes is written to
  a file and run, never `python -` with a heredoc.

## Facts this plan rests on

Read from the code at `0e0957d`:

- `coords.npz` holds `xs`, `ys`, `zs` (4,096 float32 each) and `grid_x`, `grid_z` (16,384 float32 each, a 128 x 128
  `meshgrid` in C order). FastNoiseLite files hold `scatter_3d`, `scatter_2d` (4,096) and `grid_3d` (16,384); the nine
  warp files add `warp_3d` (4,096 x 3), `warp_2d` (4,096 x 2) and `grid_warp_3d` (16,384 x 3). FastNoiseSIMD files hold
  `scatter_3d` and `grid_3d`, and the two `genasgrid_*` files hold only `grid_as_grid` (16,384). Every array is float32.
- Today the 2D samples are taken at `(xs, zs)` (`test_kernels.py:119`) and the `grid_3d` arrays at `(grid_x, 0, grid_z)`
  (`test_kernels.py:162`, `:442`).
- The `genasgrid` grids are `sample_grid((-64, -64, 1), (128, 128, 1), scales)`; `samplers.grid_points` returns the same
  float32 coordinates, flat in C order (`samplers.py:258`).
- `test_package_boundary.py` scans `SRC.glob("*.py")`, which is not recursive. A sub-package would escape the scan, so
  the module is one file, `conformance.py`, not the spec's `conformance/__init__.py` and `__main__.py`. Task 0 changes
  the spec's file table to match.
- The vectors are 12 MB of compressed `.npz` today. Raw float32 does not compress; the originals are about 13 MB raw
  and the hog set about the same again. Task 8 measures and records the size.

## Files

As the spec's *Files* section lists them, with the module as one file and these names settled:

| File | Task |
| --- | --- |
| `src/hog_noise/params.py` | 1 |
| `tests/test_hog_noise/test_params_dict.py` | 1, 9 |
| `src/hog_noise/conformance.py` | 2 to 5 |
| `tests/test_hog_noise/test_conformance.py` | 2 to 5, 9 |
| `tools/gen_noise_vectors.py` | 6, 7 |
| `tests/test_gen_noise_vectors.py` | 6, 7 |
| `.gitattributes` | 8 |
| `tools/convert_npz_vectors.py`, `tests/test_hog_noise/test_conversion.py` (temporary) | 8, removed in 11 |
| `vectors/` | 8, 10 |
| `tests/test_hog_noise/test_kernels.py` | 10 |
| `tools/noise_gallery.py`, `Docs/noise/GALLERY.md` | 12 |
| `README.md`, `PROVENANCE.md`, `llms.txt`, `NOTICE`, `Docs/glossary.md`, `Docs/README.md`, `Docs/standards/testing-project.md`, `vectors/README.md` | 13 |
| the board row, the handoff, the journal | 14 |

`tests/test_gen_noise_vectors.py` is a file the spec's table does not name; Task 0 adds it.

---

### Task 0: the spec matches the plan (in this plan's pull request)

**Files:** modify `Docs/superpowers/specs/2026-11-11-conformance-harness.md`.

- [x] **Step 1:** in *Files*, replace the row `src/hog_noise/conformance/__init__.py, __main__.py` with
  `src/hog_noise/conformance.py`, and add the row `tests/test_gen_noise_vectors.py | add: the writer and the case rules |
  none | project-owned`. In *The module*, say one module, and why (the boundary scan is not recursive).
- [x] **Step 2:** the spec's status line reads Accepted.

---

### Task 1: `NoiseParams.to_dict` and `from_dict`

**Files:** modify `src/hog_noise/params.py`; create `tests/test_hog_noise/test_params_dict.py`.

- [x] **Step 1: write the failing tests**

```python
"""
HogNoise: NoiseParams to and from a plain dict, the form the vectors' manifest stores.
Package: tests/test_hog_noise/test_params_dict
"""

import json

import pytest

from hog_noise import CellularReturn, FractalType, NoiseParams, NoiseType, PerturbType


def test_to_dict_names_every_field_with_enums_as_member_names():
    d = NoiseParams(noise_type=NoiseType.PERLIN, fractal_type=FractalType.FBM, octaves=4).to_dict()
    assert d["noise_type"] == "PERLIN" and d["fractal_type"] == "FBM" and d["octaves"] == 4
    assert d["cellular_return"] == "DISTANCE" and type(d["frequency"]) is float and type(d["seed"]) is int
    assert set(d) == {f for f in NoiseParams.__dataclass_fields__}
    json.dumps(d)  # plain JSON, no enum objects


def test_from_dict_round_trips_and_fills_defaults():
    p = NoiseParams(
        seed=7,
        frequency=0.02,
        noise_type=NoiseType.CELLULAR,
        cellular_return=CellularReturn.NOISE_LOOKUP,
        perturb=PerturbType.GRADIENT,
    )
    assert NoiseParams.from_dict(p.to_dict()) == p
    assert NoiseParams.from_dict({"seed": 7}) == NoiseParams(seed=7)


def test_from_dict_rejects_an_unknown_key_and_an_unknown_member_name():
    with pytest.raises(ValueError, match="colour"):
        NoiseParams.from_dict({"colour": "red"})
    with pytest.raises(ValueError, match="NOISE_OF_THE_SPHERES"):
        NoiseParams.from_dict({"noise_type": "NOISE_OF_THE_SPHERES"})
    with pytest.raises(ValueError, match="noise_type"):
        NoiseParams.from_dict({"noise_type": 2})  # a number is not a member name
```

- [x] **Step 2: run them and see them fail**

Run: `uv run pytest tests/test_hog_noise/test_params_dict.py -q`
Expected: 3 failed, `AttributeError: 'NoiseParams' object has no attribute 'to_dict'` (and `from_dict`).

- [x] **Step 3: implement**, in `params.py`: change `from enum import IntEnum` to `from enum import Enum, IntEnum`,
  add `from collections.abc import Mapping`, and add to `NoiseParams` after `replace`:

```python
def to_dict(self) -> dict[str, object]:
    """Every field, enums as member names, numbers as Python ``int`` and ``float``: the manifest's form."""
    out: dict[str, object] = {}
    for field in dataclasses.fields(self):
        value = getattr(self, field.name)
        if isinstance(value, Enum):
            out[field.name] = value.name
        elif isinstance(field.default, int):
            out[field.name] = int(value)
        else:
            out[field.name] = float(value)
    return out


@classmethod
def from_dict(cls, data: Mapping[str, object]) -> "NoiseParams":
    """
    The inverse of `to_dict`; a missing field takes its default.

    :raises ValueError: An unknown key, or a value that is not a member name of its enum.
    """
    fields = {field.name: field for field in dataclasses.fields(cls)}
    unknown = sorted(set(data) - set(fields))
    if unknown:
        raise ValueError(f"unknown NoiseParams field(s): {unknown}")
    kwargs: dict[str, object] = {}
    for name, value in data.items():
        default = fields[name].default
        if isinstance(default, Enum):
            enum_cls = type(default)
            if not isinstance(value, str) or value not in enum_cls.__members__:
                raise ValueError(f"{name}: {value!r} is not a {enum_cls.__name__} member name")
            kwargs[name] = enum_cls[value]
        elif isinstance(default, int):
            kwargs[name] = int(value)
        else:
            kwargs[name] = float(value)
    return cls(**kwargs)
```

  `isinstance(value, Enum)` is tested before `int` on purpose: these enums are `IntEnum`, so they are also `int`.

- [x] **Step 4: run them and see them pass**

Run: `uv run pytest tests/test_hog_noise/test_params_dict.py -q`
Expected: 3 passed.

- [x] **Step 5: commit** `src/hog_noise/params.py` and the test: "NoiseParams.to_dict and from_dict, the manifest's form".

---

### Task 2: `Bound` and the per-point rule

**Files:** create `src/hog_noise/conformance.py` and `tests/test_hog_noise/test_conformance.py`.

- [x] **Step 1: write the failing tests**

```python
"""
HogNoise: the conformance harness, on small vectors built here and on the committed ones.
Package: tests/test_hog_noise/test_conformance
"""

import numpy as np
import pytest

from hog_noise import conformance
from hog_noise.conformance import Bound


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
```

- [x] **Step 2: run them and see them fail**

Run: `uv run pytest tests/test_hog_noise/test_conformance.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'hog_noise.conformance'`.

- [x] **Step 3: implement** the module's head:

```python
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
```

- [x] **Step 4: run them and see them pass**

Run: `uv run pytest tests/test_hog_noise/test_conformance.py tests/test_hog_noise/test_package_boundary.py -q`
Expected: all passed (the boundary scan now includes `conformance.py`).

- [x] **Step 5: commit**: "conformance: Bound and the per-point rule".

---

### Task 3: `load`, with every file checked against its digest

**Files:** modify `src/hog_noise/conformance.py` and `tests/test_hog_noise/test_conformance.py`.

- [x] **Step 1: write the failing tests.** They build a tiny vectors folder by hand, with `json` and raw bytes, so
  they test the format and not the writer. Imports go at the top of the file, here and in later tasks:

```python
import hashlib
import json
from pathlib import Path


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


@pytest.mark.parametrize("rel", ["../outside.f32", "/tmp/outside.f32", "C:/outside.f32", "hog\\..\\..\\outside.f32"])
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
```

- [x] **Step 2: run them and see them fail**

Run: `uv run pytest tests/test_hog_noise/test_conformance.py -q`
Expected: the 9 new tests fail with `AttributeError: module 'hog_noise.conformance' has no attribute 'load'` (the
symlink test skips instead on a system that cannot make one).

- [x] **Step 3: implement**, after `normalised_difference`:

```python
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
```

- [x] **Step 4: run them and see them pass**

Run: `uv run pytest tests/test_hog_noise/test_conformance.py -q`
Expected: 13 passed (12 and 1 skipped where the system cannot make a symlink).

- [x] **Step 5: commit**: "conformance: load, every file checked against its digest and size, inside the folder".

---

### Task 4: `check` and `Report`

**Files:** modify `src/hog_noise/conformance.py` and `tests/test_hog_noise/test_conformance.py`.

- [x] **Step 1: write the failing tests**

```python
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
    root = make_vectors(
        tmp_path, [a_case("original/t/f/p3", "o/f.f32", compare={"kind": "advisory"})], {"o/f.f32": ref}
    )
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
```

- [x] **Step 2: run them and see them fail**

Run: `uv run pytest tests/test_hog_noise/test_conformance.py -q`
Expected: 9 new tests fail, `AttributeError: module 'hog_noise.conformance' has no attribute 'check'`.

- [x] **Step 3: implement**, after `load`:

```python
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
    results: tuple[CaseResult, ...]

    @property
    def ok(self) -> bool:
        """No ``points`` or ``shape`` case failed. Unsupported, skipped and advisory cases never fail it."""
        return not any(r.status == "fail" for r in self.results if r.kind in ("points", "shape"))

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
```

- [x] **Step 4: run them and see them pass**

Run: `uv run pytest tests/test_hog_noise/test_conformance.py -q`
Expected: 22 passed (or 21 and 1 skipped, as above).

- [x] **Step 5: run the gate's fast stages**: `uv run python tools/check.py --fast`, unpiped. Expected: all 8 stages
  pass (the log-format stage reads the f-strings).

- [x] **Step 6: commit**: "conformance: check and Report, by points, shape or advisory".

---

### Task 5: the renderings and the command line

**Files:** modify `src/hog_noise/conformance.py` and `tests/test_hog_noise/test_conformance.py`.

- [ ] **Step 1: write the failing tests**

```python
import subprocess
import sys


def test_the_numpy_rendering_samples_2d_and_3d_and_warps(tmp_path):
    sample, warp = conformance.renderings("numpy")
    from hog_noise import NoiseParams, NumpySampler

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
```

- [ ] **Step 2: run them and see them fail**

Run: `uv run pytest tests/test_hog_noise/test_conformance.py -q -k "rendering or command"`
Expected: 2 failed (`no attribute 'renderings'`; the subprocess exits non-zero with no table).

- [ ] **Step 3: implement**, at the end of the module:

```python
def renderings(name: str) -> tuple[Sample, Sample]:
    """
    ``sample`` and ``warp`` callables for one of this package's renderings, by backend name (numpy, numba,
    fastnoiselite). A rendering without a warp entry point raises `NotImplementedError` from ``warp``.
    """
    from hog_noise.samplers import make_sampler

    def sample(params: NoiseParams, xs: NDArray, ys: NDArray, zs: NDArray | None) -> NDArray:
        sampler = make_sampler(params, backend=name)[0]
        out = np.empty(len(xs), np.float32)
        return sampler.sample_points_2d(xs, ys, out) if zs is None else sampler.sample_points(xs, ys, zs, out)

    def warp(params: NoiseParams, xs: NDArray, ys: NDArray, zs: NDArray | None) -> NDArray:
        sampler = make_sampler(params, backend=name)[0]
        if not hasattr(sampler, "warp_points"):
            raise NotImplementedError(f"{name} has no warp entry point")
        return sampler.warp_points_2d(xs, ys) if zs is None else sampler.warp_points(xs, ys, zs)

    return sample, warp


def main(argv: list[str] | None = None) -> int:
    """``python -m hog_noise.conformance vectors --rendering numpy``: prints the table, exits 0 when the report is ok."""
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
    _logging.basicConfig(level=_logging.INFO, format="%(levelname)s %(message)s")
    sample, warp = renderings(args.rendering)
    bound = Bound(args.bound, args.coordinate_scaled) if args.bound is not None else None
    report = check(sample, args.vectors, reference=args.reference, bound=bound, warp=warp, select=args.select)
    print(report.table())
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: run them and see them pass**

Run: `uv run pytest tests/test_hog_noise/test_conformance.py -q`
Expected: 24 passed (or 23 and 1 skipped, as above).

- [ ] **Step 5: commit**: "conformance: the renderings and the command line".

---

### Task 6: the writer and the case rules, in the generator

**Files:** modify `tools/gen_noise_vectors.py`; create `tests/test_gen_noise_vectors.py`.

The rules that turn one captured array into one case (its id, file, parameters, comparison) are written once, here,
and used by the one-time conversion and by any future capture.

- [ ] **Step 1: write the failing tests**

```python
"""
HogNoise: the vector writer and the rules that make a captured array a case.
Package: tests/test_gen_noise_vectors
"""

import _tools_path  # noqa: F401  (puts tools/ on sys.path)

import numpy as np
import pytest

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
```

- [ ] **Step 2: run them and see them fail**

Run: `uv run pytest tests/test_gen_noise_vectors.py -q`
Expected: 5 failed, `AttributeError: module 'gen_noise_vectors' has no attribute 'params_for'` and the like.

- [ ] **Step 3: implement**, in `tools/gen_noise_vectors.py`. Add the imports (`hashlib`, `shutil`, and from
  `hog_noise`: `NoiseParams`, `conformance`, the `parse_*` functions, and `grid_points` from `hog_noise.samplers`),
  set `OUT = ROOT / "vectors"`, and add:

```python
# -------------------------------------------------------------------------
# the vectors folder: raw little-endian float32 and one manifest (spec: 2026-11-11-conformance-harness)
POINT_SETS: dict[str, dict[str, object]] = {
    "scatter_3d": {
        "dims": 3,
        "count": N_SCATTER,
        "axes": ["points/scatter_x.f32", "points/scatter_y.f32", "points/scatter_z.f32"],
    },
    "scatter_2d": {"dims": 2, "count": N_SCATTER, "axes": ["points/scatter_x.f32", "points/scatter_z.f32"]},
    "grid_y0": {
        "dims": 3,
        "count": GRID * GRID,
        "axes": ["points/grid_x.f32", "points/grid_y.f32", "points/grid_z.f32"],
    },
}
GENASGRID_SCALES = ((1.0, 1.0, 1.0), (1.0, 0.5, 2.0))
GENASGRID_START, GENASGRID_SHAPE = (-64, -64, 1), (128, 128, 1)
for _scales in GENASGRID_SCALES:
    _name = "genasgrid_" + "_".join(repr(s) for s in _scales)
    POINT_SETS[_name] = {
        "dims": 3,
        "count": 128 * 128,
        "axes": [f"points/{_name}_{axis}.f32" for axis in "xyz"],
        "from": {"start": list(GENASGRID_START), "shape": list(GENASGRID_SHAPE), "scales": list(_scales), "order": "C"},
    }

#: Which point set and output each captured array is on.
ARRAYS = {
    "scatter_3d": ("scatter_3d", "noise"),
    "scatter_2d": ("scatter_2d", "noise"),
    "grid_3d": ("grid_y0", "noise"),
    "warp_3d": ("scatter_3d", "warp"),
    "warp_2d": ("scatter_2d", "warp"),
    "grid_warp_3d": ("grid_y0", "warp"),
}
CLASSIC_SIMPLEX_BOUNDS = {"simplex_none": 5e-5, "simplex_fbm": 2e-4, "simplex_billow": 5e-4, "simplex_rigidmulti": 5e-4}
BILLOW_SHAPE = {"perlin_billow", "value_billow", "cubic_billow", "simplex_billow"}
CELLULAR_SHAPE = {
    "cellular_natural_distance",
    "cellular_natural_cellvalue",
    "cellular_euclidean_noiselookup",
    "cellular_euclidean_distance2cave",
}
#: FastNoiseLite's grid_warp_3d has never been compared. Task 8 measures it and sets this (spec, "The cases").
GRID_WARP_COMPARE: dict[str, object] = {"kind": "advisory"}


def _points(scale: float, **extra: object) -> dict[str, object]:
    return {"kind": "points", "bound": {"scale": scale, "coordinate_scaled": False}, **extra}


def compare_for(library: str, feature: str, array: str, variant: str | None = None) -> dict[str, object]:
    """How a captured array is compared: today's limits from tests/test_hog_noise/test_kernels.py, carried over."""
    if library == "fnl":
        if array in ("warp_3d", "warp_2d"):
            return _points(4e-3)
        if array == "grid_warp_3d":
            return dict(GRID_WARP_COMPARE)
        return {"kind": "advisory"}
    if feature in CLASSIC_SIMPLEX_BOUNDS and variant is None and array in ("scatter_3d", "grid_3d"):
        bound = CLASSIC_SIMPLEX_BOUNDS[feature]
        return _points(bound, min_correlation=0.9999) if array == "scatter_3d" else _points(bound)
    if feature.startswith("simplex_fbm_perturb_") and array == "scatter_3d":
        return _points(1e-3, min_correlation=0.9999)
    if feature == "whitenoise_none" and array == "scatter_3d":
        return _points(1e-6)
    if feature in BILLOW_SHAPE and array == "scatter_3d" and (feature != "simplex_billow" or variant == "shape"):
        return {"kind": "shape", "range": [-1.05, 1.05], "mean_within": 0.2, "std_within": 0.2}
    if feature in CELLULAR_SHAPE and array == "scatter_3d":
        return {"kind": "shape", "finite": True, "std_ratio": [0.3, 3.0]}
    if feature.startswith("genasgrid_"):
        return _points(2e-3, within={"scale": 1e-4, "fraction": 0.98})
    return {"kind": "advisory"}


def params_for(library: str, feature: str, record: dict, variant: str | None = None) -> NoiseParams:
    """
    A capture's record, in its library's spelling, as the parameters the suite samples it with. FastNoiseSIMD's
    ``simplex`` is its classic Simplex, except in the shape comparison of ``simplex_billow``, which is OpenSimplex2.
    """
    noise = record["noise_type"]
    if library == "fns" and noise == "simplex" and variant != "shape":
        noise = "simplex_classic"
    kwargs: dict[str, object] = dict(
        seed=record["seed"],
        frequency=record["frequency"],
        noise_type=parse_noise_type(noise),
        fractal_type=parse_fractal_type(record["fractal_type"]),
        octaves=record.get("octaves", 1),
        lacunarity=record.get("lacunarity", 2.0),
        gain=record.get("gain", 0.5),
        weighted_strength=record.get("weighted_strength", 0.0),
        ping_pong_strength=record.get("ping_pong_strength", 2.0),
        rotation_3d={"improve_xy": 1, "improve_xz": 2}.get(record.get("rotation_3d", ""), 0),
        cellular_distance=parse_cellular_distance(record.get("cellular_distance", "euclideansq")),
        cellular_return=parse_cellular_return(record.get("cellular_return", "distance")),
        cellular_jitter=record.get("cellular_jitter", 1.0),
        cellular_lookup_frequency=record.get("lookup_frequency", 0.2),
        domain_warp=parse_domain_warp(record.get("domain_warp", "none")),
        domain_warp_amp=record.get("domain_warp_amp", 1.0),
    )
    if "perturb_type" in record:
        kwargs.update(
            perturb=parse_perturb(record["perturb_type"]),
            perturb_amp=record["perturb_amp"],
            perturb_frequency=record["perturb_frequency"],
            perturb_octaves=record["perturb_octaves"],
            perturb_lacunarity=record["perturb_lacunarity"],
            perturb_gain=record["perturb_gain"],
            perturb_normalise_length=record["perturb_normalise_length"],
        )
    return NoiseParams(**kwargs)


def _where(feature: str, array: str, record: dict) -> tuple[str, str]:
    if array == "grid_as_grid":
        return "genasgrid_" + "_".join(repr(float(s)) for s in record["axes_scales"]), "noise"
    return ARRAYS[array]


def case_id(set_: str, library: str, feature: str, point_set: str, output: str, variant: str | None = None) -> str:
    return (
        f"{set_}/{library}/{feature}/{point_set}"
        + ("/warp" if output == "warp" else "")
        + (f"#{variant}" if variant else "")
    )


def case_file(set_: str, library: str, feature: str, point_set: str, output: str, variant: str | None = None) -> str:
    return (
        f"{set_}/{library}/{feature}.{point_set}"
        + (".warp" if output == "warp" else "")
        + (f"#{variant}" if variant else "")
        + ".f32"
    )


def original_cases(library: str, feature: str, record: dict, arrays: list[str]) -> list[dict[str, object]]:
    """The manifest entries for one capture's arrays; ``simplex_billow``'s scatter is also a ``#shape`` case."""
    cases = []
    for array in arrays:
        point_set, output = _where(feature, array, record)
        file = case_file("original", library, feature, point_set, output)
        variants = [None, "shape"] if (library, feature, array) == ("fns", "simplex_billow", "scatter_3d") else [None]
        for variant in variants:
            cases.append(
                {
                    "id": case_id("original", library, feature, point_set, output, variant),
                    "set": "original",
                    "source": {"library": library, "feature": feature, "array": array, "params": record},
                    "params": params_for(library, feature, record, variant).to_dict(),
                    "point_set": point_set,
                    "output": output,
                    "file": file,
                    "compare": compare_for(library, feature, array, variant),
                }
            )
    return cases


def write_f32(root: Path, rel: str, values: np.ndarray) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(np.ascontiguousarray(np.asarray(values, dtype="<f4")).tobytes())


def write_manifest(root: Path, point_sets: dict[str, dict[str, object]], cases: list[dict[str, object]]) -> Path:
    """Write the manifest sorted, with every digest recomputed from the files on disk."""
    named = [a for ps in point_sets.values() for a in ps["axes"]] + [c["file"] for c in cases]
    files = {rel: hashlib.sha256((root / rel).read_bytes()).hexdigest() for rel in sorted(set(named))}
    manifest = {
        "format": conformance.FORMAT,
        "point_sets": dict(sorted(point_sets.items())),
        "cases": sorted(cases, key=lambda c: c["id"]),
        "files": files,
    }
    path = root / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    return path


def write_points(root: Path, coords: dict[str, np.ndarray]) -> None:
    write_f32(root, "points/scatter_x.f32", coords["xs"])
    write_f32(root, "points/scatter_y.f32", coords["ys"])
    write_f32(root, "points/scatter_z.f32", coords["zs"])
    write_f32(root, "points/grid_x.f32", coords["grid_x"])
    write_f32(root, "points/grid_y.f32", np.zeros_like(coords["grid_x"]))
    write_f32(root, "points/grid_z.f32", coords["grid_z"])
    for scales in GENASGRID_SCALES:
        name = "genasgrid_" + "_".join(repr(s) for s in scales)
        for axis, values in zip("xyz", grid_points(GENASGRID_START, GENASGRID_SHAPE, scales)):
            write_f32(root, f"points/{name}_{axis}.f32", values)


def write_originals(root: Path, captured: list[tuple[str, str, dict, dict[str, np.ndarray]]], coords) -> Path:
    """
    Write captured arrays as original cases. Cases of features captured again are replaced; every other case in an
    existing manifest is kept. Run ``--set hog`` afterwards.
    """
    existing = []
    if (root / "manifest.json").exists():
        existing = json.loads((root / "manifest.json").read_text(encoding="utf-8"))["cases"]
    write_points(root, coords)
    redone = {(library, feature) for library, feature, _, _ in captured}
    cases = [
        c for c in existing if c["set"] != "original" or (c["source"]["library"], c["source"]["feature"]) not in redone
    ]
    for library, feature, record, arrays in captured:
        for case in original_cases(library, feature, record, sorted(arrays)):
            write_f32(root, case["file"], arrays[case["source"]["array"]])
            cases.append(case)
    return write_manifest(root, POINT_SETS, cases)
```

  Keep lines within the project's 120 columns; `ruff format` will wrap the long dictionary literals.

- [ ] **Step 4: run them and see them pass**

Run: `uv run pytest tests/test_gen_noise_vectors.py -q`
Expected: 5 passed.

- [ ] **Step 5: commit**: "gen_noise_vectors: the writer and the case rules".

---

### Task 7: the hog set, and the capture paths through the writer

**Files:** modify `tools/gen_noise_vectors.py` and `tests/test_gen_noise_vectors.py`.

- [ ] **Step 1: write the failing test**

```python
def test_the_hog_set_is_one_case_per_distinct_parameters_point_set_and_output(tmp_path):
    record = {"noise_type": "simplex", "fractal_type": "billow", "seed": 12345, "frequency": 0.01, "octaves": 4}
    arrays = {"scatter_3d": np.zeros(4096, np.float32)}
    twin = dict(record, noise_type="perlin")
    gen.write_originals(
        tmp_path,
        [
            ("fns", "simplex_billow", record, arrays),
            ("fns", "perlin_billow", twin, arrays),
            ("fns", "perlin_billow2", twin, arrays),
        ],
        coords(),
    )
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
```

- [ ] **Step 2: run it and see it fail**

Run: `uv run pytest tests/test_gen_noise_vectors.py -q -k hog`
Expected: FAIL, `no attribute 'generate_hog'`.

- [ ] **Step 3: implement**:

```python
def generate_hog(root: Path = OUT) -> list[str]:
    """
    The hog set: for every distinct (parameters, point set, output) among the original cases, the numpy rendering's
    output, compared at Bound(0). Rewritten whole; the first original case (by id) of each key names it.
    """
    vectors = conformance.load(root)  # verifies the originals first
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    originals = sorted((c for c in manifest["cases"] if c["set"] == "original"), key=lambda c: c["id"])
    shutil.rmtree(root / "hog", ignore_errors=True)
    sample, warp = conformance.renderings("numpy")
    seen: set[tuple[str, str, str]] = set()
    hog: list[dict[str, object]] = []
    for c in originals:
        key = (json.dumps(c["params"], sort_keys=True), c["point_set"], c["output"])
        if key in seen:
            continue
        seen.add(key)
        library, feature = c["source"]["library"], c["source"]["feature"]
        variant = c["id"].partition("#")[2] or None
        ps = vectors.point_sets[c["point_set"]]
        fn = warp if c["output"] == "warp" else sample
        values = fn(NoiseParams.from_dict(c["params"]), ps.axes[0], ps.axes[1], ps.axes[2] if ps.dims == 3 else None)
        file = case_file("hog", library, feature, c["point_set"], c["output"], variant)
        write_f32(root, file, values)
        hog.append(
            dict(
                c,
                id=case_id("hog", library, feature, c["point_set"], c["output"], variant),
                set="hog",
                file=file,
                compare=_points(0.0),
                source=dict(c["source"], from_case=c["id"]),
            )
        )
    write_manifest(root, manifest["point_sets"], originals + hog)
    _LOGGER.info(f"hog: {len(hog)} cases from {len(originals)} original cases under {root / 'hog'}")
    return [str(c["id"]) for c in hog]
```

  Then route today's capture through the writer. Replace `_write` so it collects instead of saving an `.npz`:

```python
_CAPTURED: list[tuple[str, str, dict, dict[str, np.ndarray]]] = []


def _write(
    source: str, feature: str, params: dict[str, object], values: dict[str, np.ndarray], coords: dict[str, np.ndarray]
) -> Path:
    """Collect one capture; `main` writes them all through `write_originals`."""
    _CAPTURED.append((source, feature, dict(params), {k: np.asarray(v, np.float32) for k, v in values.items()}))
    return OUT / source / f"{feature}"
```

  and change `main`: a `--set` argument (`original` or `hog`, default `hog`), `--source` kept for `original`. For
  `original`, after the capture loop, `write_originals(OUT, _CAPTURED, coords)` and then `generate_hog(OUT)`; for
  `hog`, only `generate_hog(OUT)`. Remove the `np.savez_compressed(VECTORS / "coords.npz", ...)` line and `VECTORS`.
  Update the module docstring: it writes `vectors/` (raw float32 and the manifest), `--set hog` needs only numpy, and
  `--set original` needs the bindings and oracle it always did.

- [ ] **Step 4: run the tests and see them pass**

Run: `uv run pytest tests/test_gen_noise_vectors.py -q`
Expected: 6 passed.

- [ ] **Step 5: commit**: "gen_noise_vectors: the hog set; captures write through the writer".

---

### Task 8: the conversion, with its check (one commit)

**Files:** modify `.gitattributes`; create `tools/convert_npz_vectors.py`, `tests/test_hog_noise/test_conversion.py`,
and `vectors/` (written by the tools).

- [ ] **Step 1:** add `*.f32     binary` under the `*.npz binary` line of `.gitattributes`, before any `.f32` file
  exists, so none is ever committed with text conversion.

- [ ] **Step 2: write the converter**, `tools/convert_npz_vectors.py`:

```python
"""
HogNoise: one-time conversion of tests/vectors/noise/*.npz to vectors/ (raw float32 and the manifest).
Package: tools/convert_npz_vectors

Run once, with its check (tests/test_hog_noise/test_conversion.py), in the commit that adds vectors/. The next commit
removes the .npz files and this script: there will never be .npz vectors to convert again.
"""

import json
import logging as _logging
import sys
from pathlib import Path

import numpy as np

import gen_noise_vectors as gen

_MODULE_NAME = "tools.convert_npz_vectors"
_LOGGER = _logging.getLogger(_MODULE_NAME)
ROOT = Path(__file__).resolve().parent.parent
OLD = ROOT / "tests" / "vectors" / "noise"


def captured(old: Path = OLD) -> list[tuple[str, str, dict, dict[str, np.ndarray]]]:
    out = []
    for library in ("fnl", "fns"):
        for path in sorted((old / library).glob("*.npz")):
            data = np.load(path)
            record = json.loads(str(data["params"]))
            out.append((library, path.stem, record, {k: data[k] for k in data.files if k != "params"}))
    return out


def main() -> int:
    _logging.basicConfig(level=_logging.INFO, format="%(levelname)s %(message)s")
    coords_npz = np.load(OLD / "coords.npz")
    coords = {k: coords_npz[k] for k in coords_npz.files}
    gen.write_originals(gen.OUT, captured(), coords)
    gen.generate_hog(gen.OUT)
    _LOGGER.info(f"converted {OLD} to {gen.OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

  Run it: `uv run python tools/convert_npz_vectors.py` (the script's own folder, `tools/`, is on the path, so
  `gen_noise_vectors` imports). Expected: `INFO converted ...` and `INFO hog: N cases from M original
  cases`. Record N and M for the pull request.

- [ ] **Step 3: measure `grid_warp_3d`** before deciding its comparison (spec, *The cases*):

```python
# scratch/measure_grid_warp.py: written to a file and run, never piped to python -
import numpy as np
from hog_noise import conformance

sample, warp = conformance.renderings("numpy")
report = conformance.check(sample, "vectors", reference="original", warp=warp, select="original/fnl/*/grid_y0/warp")
print(report.table())
```

  Run `uv run python scratch/measure_grid_warp.py` (the scratch directory outside the repository). The advisory rows'
  `Max abs` is the measurement. If every one is at or under 4e-3, set `GRID_WARP_COMPARE = {"kind": "points", "bound": {"scale": 4e-3, "coordinate_scaled": False}}` in
  `gen_noise_vectors.py` (a literal: the constant sits above `_points`, so calling it there is a `NameError` at import) and rerun Step 2; otherwise leave it advisory. Write which, with the largest value, in the
  pull request.

- [ ] **Step 4: write the conversion check**, `tests/test_hog_noise/test_conversion.py`. It is acceptance 1:

```python
"""
HogNoise: nothing is lost converting the .npz vectors (acceptance 1 of the harness spec). Removed with the .npz files.
Package: tests/test_hog_noise/test_conversion
"""

import json
from pathlib import Path

import numpy as np
import pytest

from hog_noise import (
    FractalType,
    NoiseParams,
    NoiseType,
    NumpySampler,
    conformance,
    parse_fractal_type,
    parse_noise_type,
)

ROOT = Path(__file__).resolve().parents[2]
OLD = ROOT / "tests" / "vectors" / "noise"
NEW = ROOT / "vectors"
POINT_SET = {
    "scatter_3d": "scatter_3d",
    "scatter_2d": "scatter_2d",
    "grid_3d": "grid_y0",
    "warp_3d": "scatter_3d",
    "warp_2d": "scatter_2d",
    "grid_warp_3d": "grid_y0",
}


@pytest.fixture(scope="module")
def vectors():
    return conformance.load(NEW)


def _npz():
    for library in ("fnl", "fns"):
        for path in sorted((OLD / library).glob("*.npz")):
            yield library, path.stem, np.load(path)


def test_every_coordinate_has_an_equal_point_file(vectors):
    old = np.load(OLD / "coords.npz")
    s3, g = vectors.point_sets["scatter_3d"].axes, vectors.point_sets["grid_y0"].axes
    for name, new in (("xs", s3[0]), ("ys", s3[1]), ("zs", s3[2]), ("grid_x", g[0]), ("grid_z", g[2])):
        assert np.array_equal(old[name], new), name
    assert not g[1].any()


def test_every_array_in_every_npz_has_a_case_with_equal_values(vectors):
    by_file = {}
    for case in vectors.cases:
        if case.set != "original":  # hog ids sort first and carry the same source keys
            continue
        by_file.setdefault((case.source["library"], case.source["feature"], case.source.get("array")), case)
    count = 0
    for library, feature, data in _npz():
        for array in data.files:
            if array == "params":
                continue
            case = by_file[(library, feature, array)]
            assert case.set == "original"
            assert np.array_equal(case.values, data[array]), f"{library}/{feature}/{array}"
            count += 1
    assert count == 66 * 3 + 9 * 3 + 49 * 2 + 2


def _old_builders():
    """The parameters each gating test builds today, ported unchanged from test_kernels.py at 0e0957d."""

    def fnl(vp):  # test_kernels._params_from
        from hog_noise import parse_cellular_distance, parse_cellular_return, parse_domain_warp

        rotation = {"improve_xy": 1, "improve_xz": 2}.get(vp.get("rotation_3d", ""), 0)
        return NoiseParams(
            seed=vp["seed"],
            frequency=vp["frequency"],
            noise_type=parse_noise_type(vp["noise_type"]),
            fractal_type=parse_fractal_type(vp["fractal_type"]),
            octaves=vp.get("octaves", 1),
            lacunarity=vp.get("lacunarity", 2.0),
            gain=vp.get("gain", 0.5),
            weighted_strength=vp.get("weighted_strength", 0.0),
            ping_pong_strength=vp.get("ping_pong_strength", 2.0),
            rotation_3d=rotation,
            cellular_distance=parse_cellular_distance(vp.get("cellular_distance", "euclideansq")),
            cellular_return=parse_cellular_return(vp.get("cellular_return", "distance")),
            cellular_jitter=vp.get("cellular_jitter", 1.0),
            domain_warp=parse_domain_warp(vp.get("domain_warp", "none")),
            domain_warp_amp=vp.get("domain_warp_amp", 1.0),
        )

    return fnl


def test_the_gating_parameters_sample_exactly_as_todays_tests_build_them(vectors):
    """Same output from the manifest's parameters as from today's test code, on the scatter points."""
    from hog_noise import parse_cellular_distance, parse_cellular_return, parse_perturb

    xs, ys, zs = vectors.point_sets["scatter_3d"].axes
    fnl = _old_builders()

    def old_params(library, feature, vp, variant):
        if library == "fnl":
            return fnl(vp)
        if feature in ("simplex_none", "simplex_fbm", "simplex_billow", "simplex_rigidmulti") and variant is None:
            return NoiseParams(
                seed=vp["seed"],
                frequency=vp["frequency"],
                noise_type=NoiseType.SIMPLEX_CLASSIC,
                fractal_type=parse_fractal_type(vp["fractal_type"]),
                octaves=vp.get("octaves", 1),
                lacunarity=vp.get("lacunarity", 2.0),
                gain=vp.get("gain", 0.5),
            )
        if feature.endswith("_billow"):
            return NoiseParams(
                seed=12345,
                frequency=0.01,
                noise_type=parse_noise_type(feature.split("_")[0]),
                fractal_type=FractalType.BILLOW,
                octaves=4,
            )
        if feature == "whitenoise_none":
            return NoiseParams(seed=vp["seed"], frequency=vp["frequency"], noise_type=NoiseType.WHITE_NOISE)
        if feature.startswith("cellular_"):
            return NoiseParams(
                seed=vp["seed"],
                frequency=vp["frequency"],
                noise_type=NoiseType.CELLULAR,
                cellular_distance=parse_cellular_distance(vp["cellular_distance"]),
                cellular_return=parse_cellular_return(vp["cellular_return"]),
                cellular_jitter=vp["cellular_jitter"],
                cellular_lookup_frequency=vp.get("lookup_frequency", 0.2),
            )
        if feature.startswith("simplex_fbm_perturb_"):
            return NoiseParams(
                seed=vp["seed"],
                frequency=vp["frequency"],
                noise_type=NoiseType.SIMPLEX_CLASSIC,
                fractal_type=FractalType.FBM,
                octaves=vp["octaves"],
                perturb=parse_perturb(vp["perturb_type"]),
                perturb_amp=vp["perturb_amp"],
                perturb_frequency=vp["perturb_frequency"],
                perturb_octaves=vp["perturb_octaves"],
                perturb_lacunarity=vp["perturb_lacunarity"],
                perturb_gain=vp["perturb_gain"],
                perturb_normalise_length=vp["perturb_normalise_length"],
            )
        if feature.startswith("genasgrid_"):
            return NoiseParams(
                seed=12345,
                frequency=0.01,
                noise_type=NoiseType.SIMPLEX_CLASSIC,
                fractal_type=FractalType.FBM,
                octaves=4,
            )
        return None

    checked = 0
    for case in vectors.cases:
        if case.set != "original" or (case.compare["kind"] == "advisory" and case.source["library"] == "fns"):
            continue
        variant = case.id.partition("#")[2] or None
        old = old_params(case.source["library"], case.source["feature"], case.source["params"], variant)
        assert old is not None, case.id
        n = np.empty(len(xs), np.float32)
        assert np.array_equal(
            NumpySampler(case.params).sample_points(xs, ys, zs, n.copy()),
            NumpySampler(old).sample_points(xs, ys, zs, n.copy()),
        ), case.id
        checked += 1
    assert checked > 0
```

  (`ruff format` will reflow it.) Every gating case and every FastNoiseLite case is checked, by output, not by
  parameter equality: a field that does not change the output (octaves under no fractal) cannot fail it.

- [ ] **Step 5: run it, and the instrument once the other way**

Run: `uv run pytest tests/test_hog_noise/test_conversion.py -q`
Expected: 3 passed. Then change one value in one `vectors/original/fns/*.f32` file by hand (and its digest, with
`write_manifest`), run again, see `test_every_array_in_every_npz_has_a_case_with_equal_values` fail, and restore it by
rerunning Step 2. A check that has not failed once is not yet evidence (the golden rule).

- [ ] **Step 6: measure the size**: `du -sh vectors tests/vectors/noise` and `git count-objects -vH` after staging.
  Record both in the pull request; the hog set roughly doubles the vectors, which the design accepted.

- [ ] **Step 7: commit** `.gitattributes`, `tools/gen_noise_vectors.py` (if Step 3 changed it), the converter, the
  check and `vectors/` (manifest, points, original, hog; not yet accepted.json or portability.md): "Convert the .npz
  vectors to vectors/: raw float32 and the manifest, with the nothing-lost check".

---

### Task 9: acceptance 3, 4, 5 and 7 on the committed vectors

**Files:** modify `tests/test_hog_noise/test_conformance.py` and `tests/test_hog_noise/test_params_dict.py`.

- [ ] **Step 1: write the tests**

```python
REAL = Path(__file__).resolve().parents[2] / "vectors"


@pytest.fixture(scope="module")
def real():
    return conformance.load(REAL)


def test_a_seed_off_by_one_fails_hog(real):
    sample, _ = conformance.renderings("numpy")

    def off(params, xs, ys, zs):
        return sample(params.replace(seed=params.seed + 1), xs, ys, zs)

    assert not conformance.check(off, real, select="hog/fns/whitenoise_none/*").ok


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
    import sys

    manifest = json.loads((REAL / "manifest.json").read_text(encoding="utf-8"))
    case = next(c for c in manifest["cases"] if c["id"] == "original/fns/whitenoise_none/scatter_3d")
    raw = (REAL / case["file"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == manifest["files"][case["file"]]
    values = array.array("f")
    values.frombytes(raw)
    if sys.byteorder == "big":
        values.byteswap()
    assert values.tolist() == real.case(case["id"]).values.tolist()
```

  and in `test_params_dict.py` (acceptance 7):

```python
from pathlib import Path

from hog_noise import conformance


def test_every_case_in_the_vectors_round_trips():
    vectors = conformance.load(Path(__file__).resolve().parents[2] / "vectors")
    for case in vectors.cases:
        assert NoiseParams.from_dict(case.params.to_dict()) == case.params, case.id
```

- [ ] **Step 2: run them**: `uv run pytest tests/test_hog_noise/test_conformance.py tests/test_hog_noise/test_params_dict.py -q`.
  Expected: all pass. Each "fails" test passes because the harness said no; that is the instrument shown to work.

- [ ] **Step 3: commit**: "conformance: the acceptance checks on the committed vectors".

---

### Task 10: the suite reads `vectors/`

**Files:** modify `tests/test_hog_noise/test_kernels.py`; move `tests/vectors/noise/accepted.json`,
`portability.md` and `reports/` to `vectors/` with `git mv`.

- [ ] **Step 1: move the record files**: `git mv tests/vectors/noise/accepted.json vectors/accepted.json`, the same
  for `portability.md` and `reports`.

- [ ] **Step 2: replace the head of `test_kernels.py`** (lines 42 to 104 at `0e0957d`): the paths, the fixture, and
  the two helpers. `PHASE_A`, `PHASE_B`, `PORTED` and `_portability_rows` stay as they are.

```python
VECTORS = Path(__file__).resolve().parents[2] / "vectors"
REPORTS = VECTORS / "reports"
ACCEPTED = VECTORS / "accepted.json"
PORTABILITY = VECTORS / "portability.md"
```

```python
@pytest.fixture(scope="module")
def vectors():
    return conformance.load(VECTORS)


@pytest.fixture(scope="module")
def coords(vectors):
    """Today's coordinate names over the point sets, so the property tests below read as they did."""
    xs, ys, zs = vectors.point_sets["scatter_3d"].axes
    grid_x, _, grid_z = vectors.point_sets["grid_y0"].axes
    return {"xs": xs, "ys": ys, "zs": zs, "grid_x": grid_x, "grid_z": grid_z}


def _original(vectors, library: str, feature: str, point_set: str, *, warp: bool = False, variant: str = ""):
    suffix = ("/warp" if warp else "") + (f"#{variant}" if variant else "")
    return vectors.case(f"original/{library}/{feature}/{point_set}{suffix}")
```

  Delete `_params_from` and `_load_vector`, and add `conformance` to the `from hog_noise import (...)` list. Every
  test that used `coords` keeps it; a test that used `_load_vector` takes `vectors` too.

- [ ] **Step 3: rewrite the readers of the old files**, keeping every assertion that is not a reference comparison
  and every portability row exactly as today (spec, *The tools and the suite*):

  - `test_numba_and_numpy_agree_exactly(feature, vectors, coords)`: `params = _original(vectors, "fnl", feature,
    "scatter_3d").params`; the rest unchanged.
  - `test_kernels_against_fastnoiselite_vectors(feature, vectors, coords)`: `c3`, `c2`, `cg` are the feature's
    `scatter_3d`, `scatter_2d` and `grid_y0` cases; `params = c3.params`; `stats_3d = compare.compare_values(ours_3d,
    c3.values)`, `stats_2d` likewise with `c2`; the sheet draws `cg.values.reshape(n, n)`. The two
    `_portability_rows.append` lines, `needs_review` and `Verdicts(ACCEPTED).is_accepted(feature)` stay as they are.
  - `test_domain_warp_field_matches_the_reference(feature, vectors, coords)`: `params` from the `scatter_3d` case;
    `w3 = _original(vectors, "fnl", feature, "scatter_3d", warp=True).values`; the displacement assertion reads `w3`.
    The `err_3d`/`err_2d < 4e-3` line goes (the harness checks it); the exact-between-rungs assertions stay.
  - `test_white_noise_is_exact_between_rungs_and_matches_fastnoisesimd(vectors, coords)`: the case is
    `original/fns/whitenoise_none/scatter_3d`; `params = case.params`; `stats` from `case.values`; the portability
    row, the range and the uniformity assertions stay; `assert stats.max_abs < 1e-6` goes.
  - `test_classic_simplex_matches_fastnoisesimd_by_point(feature, vectors, coords)`: `params` from the case; the
    portability row stays; the `max_abs`/correlation assertion and the grid assertion go.
  - `test_gradient_perturb_matches_fastnoisesimd_by_point(mode, vectors, coords)`: likewise; "the perturb moved the
    field" stays.
  - `test_billow_shape_agrees_with_the_fastnoisesimd_vectors` and `test_cellular_phase_c_spread_agrees_with_fastnoisesimd`
    are deleted: every assertion in them is a comparison with a reference, now the `shape` cases.
  - `test_sample_grid_equals_the_points_it_stands_for_and_the_fastnoisesimd_grids(vectors, coords)`: `ref =
    vectors.case(f"original/fns/{feature}/genasgrid_{s}").values` with `s` the scales joined by `_`
    (`"1.0_1.0_1.0"`, `"1.0_0.5_2.0"`); the `sample_grid` call and `err.max() < 2e-3 and np.mean(err < 1e-4) > 0.98`
    stay exactly as they are (spec: the direct grid test stays).

- [ ] **Step 4: add the harness run**, after the per-feature tests (acceptance 2):

```python
RENDERINGS = ["numpy"] + (["numba"] if HAVE_NUMBA else [])


@pytest.mark.parametrize("rendering", RENDERINGS)
def test_the_renderings_pass_every_gating_case_and_the_hog_set(rendering, vectors):
    """Every hog case at Bound(0) and every gating original, through the harness. Passing hog on numpy is also the
    staleness check: a kernel change that moves a value fails here until `gen_noise_vectors.py --set hog` is rerun."""
    sample, warp = conformance.renderings(rendering)
    report = conformance.check(sample, vectors, reference="both", warp=warp)
    assert report.ok and report.complete, report.table()
```

- [ ] **Step 5: run the suite, unpiped**

Run: `uv run pytest tests/test_hog_noise -q`
Expected: no failures; the advisory xfails as before (one or none, `simplex_pingpong` is accepted). Note the
suite's wall time before (on `main`) and after, for the pull request.

- [ ] **Step 6: acceptance 6, the record holds.** In an environment with numba and `pyfastnoiselite` (the dev extra),
  `test_write_portability_table` rewrites `vectors/portability.md`. Run `git diff -U0 vectors/portability.md`.
  Expected: one changed line, `Generated <today>.`; nothing else. Restore it with `git checkout -- vectors/portability.md`
  (P-2: the committed record is not rewritten by a run).

- [ ] **Step 7: commit**: "Suite: read vectors/ through conformance.load; the reference comparisons are check calls".

---

### Task 11: remove the `.npz` files and the conversion

- [ ] **Step 1:** `git rm -r tests/vectors/noise/fnl tests/vectors/noise/fns tests/vectors/noise/coords.npz
  tools/convert_npz_vectors.py tests/test_hog_noise/test_conversion.py`. Confirm `tests/vectors/` is now empty and
  gone: `git ls-files tests/vectors` prints nothing.
- [ ] **Step 2:** `uv run pytest tests/test_hog_noise -q`. Expected: as Task 10, minus the three conversion tests.
- [ ] **Step 3: commit**: "Remove the .npz vectors and the one-time conversion".

---

### Task 12: the gallery reads `vectors/`

**Files:** modify `tools/noise_gallery.py`; regenerate `Docs/noise/GALLERY.md` and the sheets.

- [ ] **Step 1:** in `tools/noise_gallery.py`: `VECTORS = ROOT / "vectors"`; delete `_params_from_vector` and the
  `parse_*` imports it alone used; `COMPARISONS` becomes `(family, name)` pairs (the third element goes, the manifest's
  parameters already being HogNoise's); `comparison_rows` becomes:

```python
def comparison_rows() -> list[tuple[str, compare.ComparisonStats, np.ndarray, np.ndarray]]:
    """For each listed vector: its caption, the statistics, the oracle's grid and ours."""
    vectors = conformance.load(VECTORS)
    grid_x, grid_y, grid_z = vectors.point_sets["grid_y0"].axes
    n = int(np.sqrt(len(grid_x)))
    rows = []
    for family, name in COMPARISONS:
        case = vectors.case(f"original/{family}/{name}/grid_y0")
        ours = _sampler(case.params).sample_points(grid_x, grid_y, grid_z, np.empty(n * n, np.float32))
        stats = compare.compare_values(ours, case.values)
        rows.append((f"{family}/{name}", stats, case.values.reshape(n, n), ours.reshape(n, n)))
    return rows
```

  and the two page lines name `[portability.md](../../vectors/portability.md)` and `vectors/reports/`. Add
  `conformance` to the `from hog_noise import (...)` list.
- [ ] **Step 2:** `uv run python tools/noise_gallery.py`, then `uv run python tools/noise_gallery.py --check`.
  Expected: `noise gallery: page current`. `git diff --stat Docs/noise` shows `GALLERY.md` (the two path lines, and
  nothing in the numbers: the parameters are the same) and no change to the PNGs. If a PNG or a number changed, stop:
  a mapping differs.
- [ ] **Step 3:** `uv run pytest tests/test_noise_gallery.py -q`. Expected: passed.
- [ ] **Step 4: commit**: "Gallery: read vectors/ through conformance.load".

---

### Task 13: the documents name the new path

- [ ] **Step 1:** find every live reference: `git grep -n "tests/vectors"`. Outside the records (the ADRs, the designs,
  the specs, the plans, the journal, the ledger and `Docs/PYTHON_UPGRADE_AND_FASTNOISE.md`, which keep the old path),
  change each to `vectors/`: `README.md` (the portability link), `PROVENANCE.md`, `llms.txt`, `NOTICE` (section 3's
  paths only: `vectors/original/fnl/` and `vectors/original/fns/`, the attribution text unchanged),
  `Docs/glossary.md` (*Oracle vectors*, *Portability table*), `Docs/standards/testing-project.md`, and the
  `test_kernels.py` docstring at its advisory test.
- [ ] **Step 2:** `Docs/glossary.md`: the *Conformance harness*, *Reference set*, *Case*, *Bound* and *Point set* rows
  say built. `Docs/README.md`: the spec and the plan rows say built.
- [ ] **Step 3: write `vectors/README.md`**, one page for a reader with no Python: what the folder is; the file
  format (raw little-endian IEEE float32, no header; a warp file is N x dims, row-major); the manifest's fields and the
  three comparison kinds with their fields; the case id grammar; "verify each file's sha256 against `files` before
  reading it"; the per-point rule `abs(ours - reference) <= scale`, coordinate-scaled `<= scale * max(1,
  max(abs(x), abs(y)[, abs(z)]) * frequency)`; that `hog` is HogNoise's numpy rendering and `original` the libraries'
  captures; and the command `python -m hog_noise.conformance vectors --rendering numpy`. Every statement in it is
  checked against `conformance.py` as written (P-6).
- [ ] **Step 4:** `git grep -n "tests/vectors"` again: only the records remain. `uv run python tools/check.py`
  (full, unpiped). Expected: every stage passes.
- [ ] **Step 5: commit**: "Docs: the vectors live in vectors/".

---

### Task 14: the record, CI, and the pull request

- [ ] **Step 1:** the board row's State says the harness is built (with the pull request link); the handoff's *In
  flight* row moves the harness to done and the GPU port to next; a journal entry for the build (its session file,
  per `Docs/standards/journal.md`).
- [ ] **Step 2:** push and open the pull request from the template (`.github/pull_request_template.md`), with: the
  case counts (original, hog), the `grid_warp_3d` measurement and decision, the vector size (Task 8 Step 6), the suite
  time before and after, the `portability.md` diff result, and the *Decisions* table (the one-module layout; the case
  rules in the generator; anything decided while building).
- [ ] **Step 3: read CI on every leg** (`gh pr checks <n> --watch`). The open risk the spec names is measured here: the
  hog set at Bound(0) on numpy 1.26, the latest numpy, numpy alone, and Windows. If a leg fails only on hog cases,
  do not loosen anything: report the leg, the cases and the largest difference to the owner (spec, *Open risks*: the
  bound for that leg is recorded as measured, never loosened silently), and wait.
- [ ] **Step 4:** run the review (`local-review` skill) on the diff, since this is a significant increment, and put its
  table in the pull request's *Review* section. Then assess Copilot's review as `review-and-pr` says; before every push,
  `gh pr view <n> --json state` is `OPEN` (P-5).

---

## Self-review against the spec

- *The folder*, *The manifest*: Tasks 6 to 8 (`POINT_SETS`, `case_id`, `case_file`, `write_manifest` with `files`);
  `grid_y.f32` zeros in `write_points`.
- *The cases*: `compare_for` carries every row of the spec's table; `grid_warp_3d` is measured in Task 8 Step 3; the
  32 unread FastNoiseSIMD files fall to the last `advisory`; the hog set in Task 7.
- *Parameters*: Task 1, and acceptance 7 in Task 9.
- *The module*: Tasks 2 to 5, as one file (Task 0).
- *The tools and the suite*: the generator in Tasks 6 and 7; the conversion committed, run with its check and removed
  in Tasks 8 and 11; the suite in Task 10 (the advisory rule called, not restated; `portability.md` keeps today's rows;
  the direct `sample_grid` test kept); the gallery in Task 12.
- *Files*: every row has a task; `tests/test_gen_noise_vectors.py` is added to the spec by Task 0.
- *Acceptance*: 1 in Task 8, 2 in Task 10 Step 4 and Task 14 Step 3, 3 in Tasks 4 and 9, 4 in Tasks 4 and 9, 5 and 7
  in Task 9, 6 in Task 10 Step 6, 8 in Task 13 Step 4.
- *Open risks*: hog across numpy versions and systems, Task 14 Step 3; `grid_warp_3d`, Task 8 Step 3.

## Terms introduced

None. *Point set*, *Case*, *Bound* and *Reference set* are the spec's and already have glossary rows.
