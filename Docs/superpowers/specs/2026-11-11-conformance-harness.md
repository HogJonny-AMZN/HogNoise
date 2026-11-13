# Spec: the conformance harness and the portable vectors

**Status:** Accepted 2026-11-12 (the owner: "accept"). Written 2026-11-11 from
[the design](../../design/2026-11-02-conformance-harness.md), Accepted the same day. The plan:
[2026-11-12-conformance-harness.md](../plans/2026-11-12-conformance-harness.md), which made one correction here: the
module is one file (see *The module*).
**Board:** [`2026-11-01-conformance-harness-and-portable-vectors`](../../plan/board/2026-11-01-conformance-harness-and-portable-vectors.md)

What gets built, exactly enough that the plan is a list of tasks and a reviewer can check the result against this page. The
design says why; this says what. Where the two disagree, the design's decisions hold and this page is the bug.

## Facts this rests on

Read from the code at `cb4e051`, not assumed:

- **The vectors.** `tests/vectors/noise/` holds 117 `.npz` files: 66 FastNoiseLite (`fnl/`) and 51 FastNoiseSIMD (`fns/`),
  plus `coords.npz`. FastNoiseLite files hold `scatter_3d`, `scatter_2d` and `grid_3d`; the nine warp files add `warp_3d`,
  `warp_2d` and `grid_warp_3d`. FastNoiseSIMD files hold `scatter_3d` and `grid_3d`, except the two `genasgrid_*` files,
  which hold only `grid_as_grid`. Each `params` is a JSON string in the source library's spelling. Every coordinate is
  float32.
- **The FastNoiseSIMD set is costly to regenerate.** `pyfastnoisesimd` publishes wheels only up to Python 3.9; a source
  build works on 3.12 and 3.13 and gives bit-identical output ([ADR-007](../../decisions/ADR-007-noise-kernels-port.md)),
  but this repository neither builds nor hosts one. Regenerating means making that build first, so the conversion is
  treated as one-way and checked before anything is removed.
- **How the suite compares the originals today** (`tests/test_hog_noise/test_kernels.py`):

  | Vectors | Parameters as the test builds them | Compared | Limit |
  | --- | --- | --- | --- |
  | FastNoiseLite noise, all 66 (`scatter_3d`, `scatter_2d`) | `_params_from` | advisory, never fails: class and correlation reported to `portability.md`; when either is `needs_review` (`compare.ComparisonStats`: looser than `tight`, or correlation below 0.99) and `Verdicts.is_accepted(feature)` is false, a sheet and xfail. A `rejected` verdict does not exempt | none |
  | FastNoiseLite `grid_3d`, 66 | | not compared: drawn as the reference half of the sheet, only when the scatter needs review | |
  | FastNoiseLite warp field, 9 (`warp_3d`, `warp_2d`) | `_params_from` | by point | max < 4e-3 |
  | FastNoiseLite `grid_warp_3d`, 9 | | not compared | |
  | FastNoiseSIMD classic Simplex, 4 (`scatter_3d`, `grid_3d`) | `SIMPLEX_CLASSIC` | by point | max < 5e-5, 2e-4, 5e-4, 5e-4; correlation > 0.9999 on the scatter |
  | FastNoiseSIMD gradient perturb, 5 (`scatter_3d`) | `SIMPLEX_CLASSIC`, FBm, the perturb fields | by point | max < 1e-3, correlation > 0.9999 |
  | FastNoiseSIMD white noise (`scatter_3d`) | `WHITE_NOISE` | by point | max < 1e-6 |
  | FastNoiseSIMD Billow, 4 (`scatter_3d`) | `parse_noise_type(name)`, seed 12345, f 0.01, Billow, 4 octaves | shape | ours in [-1.05, 1.05]; mean and std each within 0.2 |
  | FastNoiseSIMD Phase C cellular, 4 (`scatter_3d`) | from the record, `CELLULAR` | shape | finite; std ratio ours/theirs in (0.3, 3) |
  | FastNoiseSIMD `genasgrid_*`, 2 | `SIMPLEX_CLASSIC`, FBm, 4 octaves, seed 12345 | by point, own grid | max < 2e-3 and over 98% within 1e-4 |
  | The other 32 FastNoiseSIMD files, and the `grid_3d` of the perturb, white, Billow and cellular files | | not compared | |

  `simplex_billow` appears twice: by point as classic Simplex, and by shape as OpenSimplex2.
- **`NoiseParams` has no `to_dict` or `from_dict`.** The design assumed them; this adds them.
- **The vector paths are named in** the tests, `tools/gen_noise_vectors.py`, `tools/noise_gallery.py`, `README.md`,
  `PROVENANCE.md`, `llms.txt`, `NOTICE`, `Docs/glossary.md`, `Docs/noise/GALLERY.md` and
  `Docs/standards/testing-project.md` (`git grep -n "tests/vectors"`, every file type). The ADRs, the designs, the specs,
  the journal, the planning document and the ledger name them too; those are records and keep the old path.
- **CI** runs the suite on 3.11 with numpy 1.26, 3.13 with the latest numpy, 3.13 with numpy alone (no numba, no binding),
  and 3.13 on Windows.

## The folder

```text
vectors/
  manifest.json
  points/                 scatter_x.f32 scatter_y.f32 scatter_z.f32 grid_x.f32 grid_y.f32 grid_z.f32
                          genasgrid_1.0_1.0_1.0_{x,y,z}.f32  genasgrid_1.0_0.5_2.0_{x,y,z}.f32
  original/fnl/           <feature>.<point set>[.warp].f32
  original/fns/           <feature>.<point set>.f32
  hog/fnl/  hog/fns/      the same names, plus #<variant> where two cases share a file name
  accepted.json  portability.md  reports/
  README.md               the format in one page, for someone with no Python
```

- Every `.f32` file is raw little-endian IEEE float32, no header. A noise file holds N values; a warp file holds N x dims
  values, row-major (x, y[, z] per point). `grid_y.f32` is 16,384 zeros: every point set names a file for every axis, so a
  reader never special-cases a constant.
- `accepted.json`, `portability.md` and `reports/` move unchanged; `accepted.json` stays keyed by feature name.
- No `.npz` file and no `coords.npz` remain in the repository afterwards.

## The manifest

```json
{
  "format": 1,
  "point_sets": {
    "scatter_3d": {"dims": 3, "count": 4096, "axes": ["points/scatter_x.f32", "points/scatter_y.f32", "points/scatter_z.f32"]},
    "scatter_2d": {"dims": 2, "count": 4096, "axes": ["points/scatter_x.f32", "points/scatter_z.f32"]},
    "grid_y0": {"dims": 3, "count": 16384, "axes": ["points/grid_x.f32", "points/grid_y.f32", "points/grid_z.f32"]},
    "genasgrid_1.0_0.5_2.0": {
      "dims": 3,
      "count": 16384,
      "axes": ["..."],
      "from": {"start": [-64, -64, 1], "shape": [128, 128, 1], "scales": [1.0, 0.5, 2.0], "order": "C"}
    }
  },
  "cases": [
    {
      "id": "original/fns/simplex_fbm/scatter_3d",
      "set": "original",
      "source": {"library": "fastnoisesimd", "feature": "simplex_fbm", "params": {"noise_type": "simplex", "...": "..."}},
      "params": {"noise_type": "SIMPLEX_CLASSIC", "fractal_type": "FBM", "seed": 12345, "...": "..."},
      "point_set": "scatter_3d",
      "output": "noise",
      "file": "original/fns/simplex_fbm.scatter_3d.f32",
      "compare": {"kind": "points", "bound": {"scale": 2e-4, "coordinate_scaled": false}, "min_correlation": 0.9999}
    }
  ],
  "files": {
    "points/scatter_x.f32": "<sha256>",
    "original/fns/simplex_fbm.scatter_3d.f32": "<sha256>"
  }
}
```

- **A case id** is `<set>/<library dir>/<feature>/<point set>`, with `/warp` for a warp output and `#<variant>` when two
  cases would otherwise share an id (`original/fns/simplex_billow/scatter_3d#shape`). Ids are unique, and the manifest
  lists cases sorted by id so it diffs cleanly.
- **`params`** is `NoiseParams.to_dict()`, every field present. **`source.params`** is the original record, verbatim, kept
  for the record and never read by the harness.
- **`compare`** is one of:
  - `{"kind": "points", "bound": {"scale": s, "coordinate_scaled": b}}`, optionally with `"min_correlation": c` and
    `"within": {"scale": t, "fraction": f}` (at least fraction `f` of the points within `t`).
  - `{"kind": "shape", ...}` with any of `"range": [lo, hi]`, `"mean_within": m`, `"std_within": s`,
    `"std_ratio": [lo, hi]` and `"finite": true`.
  - `{"kind": "advisory"}`.
- **`files`** maps every `.f32` file in the folder, coordinates and values alike, to its `sha256`. `load` verifies each file
  against it before reading it, and a file a point set or case names that is not in the map is an error, as is a size that
  is not `count` (times `dims` for a warp output) float32 values. So an edited coordinate file, which would change the
  inputs to every case on that point set, is a load error, not a set of comparison results.

## The cases

**original**, converted from the `.npz` files, one case per array, with the parameters and limits from the table above:

| From | Comparison |
| --- | --- |
| FastNoiseLite noise, `scatter_3d` and `scatter_2d` | advisory |
| FastNoiseLite noise, `grid_3d` | advisory, **new**: today it is only drawn on the sheet. Its row is reported and never gates or triggers review, and the sheet still draws it |
| FastNoiseLite `warp_3d`, `warp_2d` | points, `Bound(4e-3)` |
| FastNoiseLite `grid_warp_3d` | points, `Bound(4e-3)` if the conversion measures it within that; otherwise advisory, and the pull request says which |
| FastNoiseSIMD classic Simplex, `scatter_3d` | points, its bound, `min_correlation` 0.9999 |
| FastNoiseSIMD classic Simplex, `grid_3d` | points, its bound |
| FastNoiseSIMD gradient perturb, `scatter_3d` | points, `Bound(1e-3)`, `min_correlation` 0.9999 |
| FastNoiseSIMD white noise, `scatter_3d` | points, `Bound(1e-6)` |
| FastNoiseSIMD Billow, `scatter_3d`, as OpenSimplex2 and the others as the test builds them (`#shape` on `simplex_billow`) | shape: `range` [-1.05, 1.05], `mean_within` 0.2, `std_within` 0.2 |
| FastNoiseSIMD Phase C cellular, `scatter_3d` | shape: `finite`, `std_ratio` [0.3, 3.0] |
| FastNoiseSIMD `genasgrid_*` | points on its own point set, `Bound(2e-3)`, `within` 1e-4 at 0.98 |
| Every other array | advisory |

Today's limits are strict (`<`); a bound is inclusive (`<=`). The difference is a value exactly on the limit, and that is
accepted. Where no test builds the parameters, the record's spelling maps through the `parse_*` functions, with
FastNoiseSIMD's `simplex` as `SIMPLEX_CLASSIC`, as the gallery maps it today. A record that does not map is a conversion
error, never a skipped case.

**hog**: for every distinct (parameters, point set, output) among the original cases, the numpy rendering's output. Every
hog case is `points` at `Bound(0)`. It is generated, never hand-edited.

## Parameters

`NoiseParams.to_dict() -> dict[str, object]`: every field, enums as member names (`"OPEN_SIMPLEX2"`), numbers as Python
`int` and `float`. `NoiseParams.from_dict(d)`: member names back to enums, missing fields take their defaults, an unknown key
or an unknown member name raises `ValueError` naming it. `from_dict(p.to_dict()) == p` for every case's parameters.
*Amended 2026-11-13 ([PR #17](https://github.com/HogJonny-AMZN/HogNoise/pull/17), the review of #16):* values are read as
written, never converted: an integer field takes an `int`, a float field an `int` or `float`, a `bool` is neither, and
anything else is a `ValueError` naming the field.

## The module

`hog_noise.conformance`, standard library and numpy only (the package boundary holds), in the wheel; the vectors are not.
It is one module, `src/hog_noise/conformance.py`, with the command line in its `if __name__ == "__main__":` block, like
`compare.py`: `tests/test_hog_noise/test_package_boundary.py` scans `src/hog_noise/*.py`, not recursively, so a
sub-package would escape the boundary check (found writing the plan).

```python
@dataclass(frozen=True)
class Bound:
    scale: float
    coordinate_scaled: bool = False


def load(vectors: str | Path, *, sets: str | tuple[str, ...] | None = None) -> Vectors: ...


def check(
    sample: Callable[[NoiseParams, NDArray, NDArray, NDArray | None], NDArray],
    vectors: str | Path | Vectors,
    *,
    reference: Literal["hog", "original", "both"] = "hog",
    bound: Bound | None = None,
    warp: Callable[[NoiseParams, NDArray, NDArray, NDArray | None], NDArray] | None = None,
    select: str | None = None,
) -> Report: ...
```

- `sample(params, xs, ys, zs)` gets float32 arrays (`zs` is `None` for a 2D point set) and returns N float32 values.
  `warp` returns N x dims. A callable that raises `NotImplementedError` for a case's parameters marks that case
  **unsupported**: a partial port, such as the GPU rung's first 2D OpenSimplex2, reports what it covers. A warp case with no
  `warp` callable is **skipped**.
- `bound`, when given, replaces the bound of every `points` case checked; `shape` and `advisory` cases are untouched.
- `select` is an `fnmatch` pattern over case ids.
- **A value passes a bound** when `abs(ours - reference) <= scale`, or, coordinate-scaled, when
  `<= scale * max(1, max(abs(x), abs(y)[, abs(z)]) * params.frequency)`, per point, on the input coordinates. For a warp
  output, every component of a point is held to that point's bound.
- **`Report`** has one row per case: id, comparison kind, status (`pass`, `fail`, `unsupported`, `skipped`, or for
  advisory, its match class from `compare.classify`, its correlation, whether `ComparisonStats.needs_review` holds, and any
  `accepted.json` verdict), the largest absolute difference and,
  for points, the largest difference divided by its own bound. A zero bound has no ratio to divide by, so a difference of
  exactly 0 reports 0 and any other difference reports infinity: `Bound(0)` reports 0 on a pass and `inf` on a fail, never
  NaN. `report.ok` is true when no case failed: no `points` or `shape` case past its rule, and no case of any kind whose
  output had the wrong shape (*amended 2026-11-13, PR #17*: an advisory case's wrong-shaped output had passed). An
  advisory case fails it only that way. `report.complete` is true when nothing was unsupported or skipped.
  `report.table()` is a markdown table.
- **`load(sets=...)`** (*added 2026-11-13, PR #17*) reads only the cases of the named reference sets and their files, so
  regenerating the hog set needs only the originals to be sound. The folder-wide checks (every `.f32` file listed in
  `files`, every digest naming a file in use) run when every set is loaded. A malformed manifest, case or rule is a
  `ConformanceError` naming the part, at `load`, never a raw `KeyError` or a traceback later in `check`.

The command line, which exits 0 when `report.ok`, 1 otherwise, and 2 when the rendering is unknown or not installed or
the folder cannot be loaded (*amended 2026-11-13, PR #17*), and prints the table:

```bash
python -m hog_noise.conformance vectors --rendering numpy
python -m hog_noise.conformance vectors --rendering numba --reference both --select "*/fns/*"
python -m hog_noise.conformance vectors --rendering numpy --bound 3e-6 --coordinate-scaled
```

## The tools and the suite

- **`tools/gen_noise_vectors.py`** writes the new format. `--set hog` regenerates the hog files and their manifest entries
  in any environment with numpy. `--set original` keeps today's capture paths (the binding, the C++ oracle,
  `pyfastnoisesimd` from a Python 3.9 wheel or a source build), writing through the same writer. The writer sorts the
  manifest and recomputes every digest in `files`.
- **The one-time conversion** reads the `.npz` files and writes `vectors/`. It is committed, run once, and its check (below)
  runs against the `.npz` files in the same commit. The next commit in the same pull request removes the `.npz` files and
  the conversion code; the pull request records the passing run.
- **`tests/test_hog_noise/test_kernels.py`** reads `vectors/` through `conformance.load`. The reference comparisons become
  `check` calls (numpy, and numba when present, against both sets). The property assertions that are not comparisons with
  a reference stay as they are: the perturb moved the field, white noise is uniform, the warp is a real displacement,
  RigidMulti is not Ridged. The advisory rule is today's, unchanged and not reimplemented: the harness and the test call
  `compare.ComparisonStats.needs_review` (looser than `tight`, or correlation below 0.99) on a feature's `scatter_3d` and
  `scatter_2d` cases, and when either needs review and `compare.Verdicts.is_accepted(feature)` is false (no verdict, or
  `rejected`), the test draws the sheet from the `grid_3d` case and xfails.
- **`portability.md` keeps exactly today's rows**, from the same comparisons that write them now
  (`tests/test_hog_noise/test_kernels.py` lines 122, 151-152, 294, 440 and 513-514): numba against numpy per feature,
  FastNoiseLite `scatter_3d` and `scatter_2d`, white noise, classic Simplex and the gradient perturb. The cases that are
  new as comparisons (FastNoiseLite `grid_3d`, the FastNoiseSIMD arrays no test reads, every hog case) report through
  `Report` only, so acceptance 6 holds.
- **The direct `sample_grid` comparison stays** (the design's decision 5): the two `genasgrid` fixtures are still compared
  with `sample_grid((-64, -64, 1), (128, 128, 1), scales)` at today's limits, reading the reference values from the loaded
  case instead of the `.npz`. The harness's check on the stored points runs as well; it does not replace this, because
  only this one exercises the grid driver.
- **`tools/noise_gallery.py`** reads `vectors/` through `conformance.load`; its own parameter mapping and the
  `simplex_classic` override go, because the manifest's parameters are already HogNoise's.

## Files

Every file the build adds, changes or removes; a file not listed is out of scope. *Module* and *kind* are from
`framework-manifest.toml`. None of these files is in `framework.lock`, so the template never checks or rewrites any of
them. A file the template's payload does not have has no module: the `tools/*.py` and `tests/test_*.py` rules describe the
template's own tools and tests, not a project's. Every file is owned by the project (@HogJonny-AMZN).

| File | Change | Module | Kind |
| --- | --- | --- | --- |
| `src/hog_noise/conformance.py` | add: `Bound`, `load`, `check`, `Report`; the command line | none | project-owned |
| `src/hog_noise/params.py` | change: `NoiseParams.to_dict`, `from_dict` | none | project-owned |
| `src/hog_noise/compare.py` | unchanged; `classify`, `compare_values`, `ComparisonStats`, `Verdicts`, `render_sheet` and `write_portability` are called, not copied | none | project-owned |
| `vectors/manifest.json`, `vectors/points/*.f32`, `vectors/original/**/*.f32`, `vectors/hog/**/*.f32`, `vectors/README.md` | add | none | project-owned |
| `vectors/accepted.json`, `vectors/portability.md`, `vectors/reports/*` | move from `tests/vectors/noise/`, contents unchanged | none | project-owned |
| `tests/vectors/noise/**/*.npz`, `tests/vectors/noise/coords.npz` | remove, in the commit after the conversion | none | project-owned |
| `tools/convert_npz_vectors.py` and its check | add in the conversion commit, remove in the next (temporary) | none | project-owned |
| `tools/gen_noise_vectors.py`, `tools/noise_gallery.py` | change: write and read `vectors/` | none | project-owned |
| `tests/test_hog_noise/test_kernels.py` | change: `check` calls; the advisory rule and the direct `sample_grid` test kept | none | project-owned |
| `tests/test_hog_noise/test_conformance.py`, `test_params_dict.py` | add: acceptance 3 to 7 | none | project-owned |
| `tests/test_gen_noise_vectors.py` | add: the writer and the case rules (added by the plan) | none | project-owned |
| `.gitattributes` | change: `*.f32 binary` | core | project-owned |
| `README.md` | change: the vector path | core | project-owned |
| `Docs/glossary.md`, `Docs/README.md` | change: the vector path; the harness rows to built | core | project-owned |
| `PROVENANCE.md`, `Docs/noise/GALLERY.md`, `Docs/standards/testing-project.md` | change: the vector path | none | project-owned |
| `llms.txt` | change: its link to `portability.md` | none | project-owned |
| `NOTICE` | change: the paths in section 3, where the comparison vectors came from; the attribution text itself unchanged | none | project-owned |
| `Docs/plan/board/2026-11-01-conformance-harness-and-portable-vectors.md`, `Docs/handoffs/CURRENT.md` | change: state | core | project-owned |
| `Docs/journal/2026-11/<the build's session>.md` | add | journal | project-owned |

The names of the new test files and the converter are the plan's to settle; a different name is a plan detail, a file
outside this table is a change to this spec.

## Acceptance

Each line is a test or a recorded run, named in the plan:

1. **Nothing lost.** Before removal, every array in every `.npz` file has a case or point file with equal values, and every
   parameter record maps. Run once, in the conversion commit.
2. **The renderings pass.** numpy and numba pass every hog case at `Bound(0)` and every gating original case, on all four CI
   legs (numba where installed). Passing hog at `Bound(0)` on numpy is also the staleness check: a kernel change that moves
   any value fails until `--set hog` is rerun.
3. **It can say no.** A sampler with the seed off by one fails hog; one value nudged by 1e-5 fails the white-noise original;
   one value moved by one ulp fails hog at `Bound(0)`; a value inside the bound at its band's far edge but outside its own
   point's bound fails a coordinate-scaled bound (the flaw Copilot found in the spike). One coordinate in
   `points/scatter_x.f32`, changed in place without changing the file's size, makes `load` fail. A passing run at
   `Bound(0)` reports a normalised difference of 0, not NaN, and a failing one reports infinity. An advisory case within
   `tight` but with correlation below 0.99 needs review, and a `rejected` verdict still draws the sheet and xfails.
4. **Partial ports report, not fail.** A sampler that raises `NotImplementedError` outside 2D OpenSimplex2 gives
   `report.ok` true and `report.complete` false, with the unsupported cases counted.
5. **Language-neutral.** A test reads `manifest.json` and one case with `json`, `hashlib` and `array` only, and gets the
   same numbers as `load`.
6. **The record holds.** A full-environment run (numba and the binding) rewrites `portability.md` byte for byte as it is,
   apart from its `Generated <date>.` line, which `write_portability` stamps with the day of the run; the check drops that
   one line from both sides and compares the rest exactly.
7. **The parameters round-trip** for every case, and `from_dict` rejects an unknown key and an unknown member name.
8. **The gate passes** (`tools/check.py`, full), and the docs that named the old path name the new one.

## Not in this

The GPU rung, any port in another language, 4D, FastNoise2 vectors, a release asset, and regenerating the FastNoiseSIMD
originals. The roadmap and the GPU fast track own those.

## Open risks

- **hog across numpy versions.** The numpy rendering is bit-identical to numba within one environment; that it is
  bit-identical between numpy 1.26 and the latest, and between Linux and Windows, is assumed, not measured. Acceptance 2
  measures it. If it fails, the hog bound for that leg is recorded as measured, never loosened silently.
- **`grid_warp_3d`** has never been compared. The conversion measures it; the table above says what happens either way.

## Terms introduced

- **Point set**: a named list of coordinates the vectors share, such as `scatter_3d` or a `genasgrid` grid; every case is
  sampled on one.
