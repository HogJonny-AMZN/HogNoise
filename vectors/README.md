# The reference vectors

What HogNoise's noise must produce, in a form any language can read: raw float32 files and one JSON manifest. A port of
the noise, in any language or on a GPU, checks itself by sampling each case's parameters at its points and comparing with
the stored values. In Python that is one command:

```bash
python -m hog_noise.conformance vectors --rendering numpy
python -m hog_noise.conformance vectors --rendering numba --reference both --select "*/fns/*"
```

It prints a table and exits 0 when no `points` or `shape` case failed. The module is `hog_noise.conformance`; the format
it reads is this page.

## The files

```text
manifest.json             every point set, every case, and a sha256 for every .f32 file
points/                   the coordinates
original/fnl/  fns/       what FastNoiseLite and FastNoiseSIMD produced (see NOTICE for their sources)
hog/fnl/  hog/fns/        what HogNoise's numpy rendering produces; every rendering must match it bit for bit
accepted.json             a person's verdict on an advisory mismatch, by feature name
portability.md            how closely each pair of renderings agreed, rewritten by a full test run
reports/                  the comparison sheet behind each verdict
```

Every `.f32` file is raw little-endian IEEE 754 float32 with no header. A noise output holds one value per point. A warp
output holds `dims` values per point, row-major: x, y (and z) for the first point, then the next. Nothing here is edited
by hand: `tools/gen_noise_vectors.py` writes the files and the manifest.

## The manifest

```json
{
  "format": 1,
  "point_sets": {"scatter_3d": {"dims": 3, "count": 4096, "axes": ["points/scatter_x.f32", "..."]}},
  "cases": [{"id": "...", "set": "original", "params": {"...": "..."}, "point_set": "scatter_3d",
             "output": "noise", "file": "original/fns/simplex_fbm.scatter_3d.f32",
             "compare": {"kind": "points", "bound": {"scale": 0.0002, "coordinate_scaled": false}}}],
  "files": {"points/scatter_x.f32": "<sha256 hex>"}
}
```

- **`point_sets`**: `dims` is 2 or 3, `count` the number of points, `axes` one file per axis in order (x, y or x, y, z). A
  2D point set's second axis is the noise's second coordinate. `grid_y.f32` is a file of zeros, so no axis is a special
  case. A grid point set carries `from` (`start`, `shape`, `scales`, `order`), saying how its coordinates were made; the
  coordinates are in the files all the same.
- **`cases`**, sorted by id. `params` is every field of HogNoise's `NoiseParams` by name, enums as member names
  (`"OPEN_SIMPLEX2"`). `source.params` is the original library's own record, kept for the record and never read.
  `output` is `noise` or `warp`. Two cases may share a `file`.
- **`files`** maps every `.f32` file to its sha256. Check it before reading a file: a reader that skips the check cannot
  tell an edited coordinate from a failing port.
- Every path is relative to this folder, uses `/`, and stays inside it. Refuse any other.

**A case id** is `<set>/<library>/<feature>/<point set>`, with `/warp` for a warp output and `#<variant>` when two
cases would otherwise share an id: `original/fns/simplex_billow/scatter_3d#shape` is FastNoiseSIMD's Billow compared by
shape, as OpenSimplex2, beside the same file compared point by point as classic Simplex.

## How a case is compared

| `compare.kind` | Passes when |
| --- | --- |
| `points` | at every point, `abs(ours - reference) <= scale`; with `"coordinate_scaled": true`, `<= scale * max(1, max(abs(x), abs(y)[, abs(z)]) * frequency)` at that point's own coordinates. A warp point passes when every component does. Optionally also `min_correlation` (Pearson, at least) and `within` (at least `fraction` of the points within `scale`). |
| `shape` | every check listed holds: `range` [lo, hi] for every value, `mean_within` and `std_within` (the difference from the reference's mean and standard deviation), `std_ratio` [lo, hi] (ours over the reference's), `finite`. |
| `advisory` | never fails. It reports how close it came, flagged *needs review* when the largest difference is above 1e-4 or the correlation below 0.99, with any verdict `accepted.json` holds for its feature. HogNoise's own test suite draws a comparison sheet for a flagged case and waits for a person's verdict, unless that verdict is `accepted`. |

Every `hog` case is `points` at a scale of 0: bit for bit. The `original` cases carry the limits the test suite has
always used, from 1e-6 (white noise) to 4e-3 (the domain-warp field), or are compared by shape or advisory where the
original library's arithmetic differs from HogNoise's.

A port that does not cover a case yet reports it as unsupported, not failed; `report.complete` says whether anything was.
