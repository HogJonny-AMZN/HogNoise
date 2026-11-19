# The reference vectors

What HogNoise's noise must produce, in a form any language can read: raw float32 files and one JSON manifest. A port of
the noise, in any language or on a GPU, checks itself by sampling each case's parameters at its points and comparing with
the stored values. In Python that is one command:

```bash
python -m hog_noise.conformance vectors --rendering numpy
python -m hog_noise.conformance vectors --rendering numba --reference both --select "*/fns/*"
python -m hog_noise.conformance vectors --rendering wgpu --tolerance vectors/tolerance/wgpu.json
```

It prints a table and exits 0 when no case failed: no `points` or `shape` case past its rule, and no output of the wrong
shape. It exits 1 on a failure and 2 when the rendering or the folder cannot be used. The module is
`hog_noise.conformance`; the format it reads is this page.

## The files

```text
manifest.json             every point set, every case, and a sha256 for every .f32 file
points/                   the coordinates
original/fnl/  fns/       what FastNoiseLite and FastNoiseSIMD produced (see NOTICE for their sources)
hog/fnl/  hog/fns/        what HogNoise's numpy rendering produces; every CPU rendering must match it bit for bit
tolerance/wgpu.json       the GPU rendering's bounds against the hog set (see Tolerance files)
accepted.json             a person's verdict on an advisory mismatch, by feature name
portability.md            how closely each pair of renderings agreed, rewritten by a full test run
portability-gpu.md        the GPU rendering against the hog set, per feature and GPU adapter
reports/                  the comparison sheet behind each verdict
reports/gpu/<commit>/     the measurement records the tolerance file was derived from, one JSON file per GPU adapter
```

Every `.f32` file is raw little-endian IEEE 754 float32 with no header. A noise output holds one value per point. A warp
output holds `dims` values per point, row-major: x, y (and z) for the first point, then the next. Nothing here is edited
by hand: `hog-noise-vectors` writes the files and the manifest, and `hog-noise-measure-gpu` the tolerance file,
`portability-gpu.md` and the GPU records.

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
- **`files`** maps every `.f32` file in the folder, and only those a point set or case uses, to its sha256. Check it
  before reading a file: a reader that skips the check cannot tell an edited coordinate from a failing port.
- **Numbers are read as written.** `dims` and `count` are positive integers; an integer parameter is an integer, never
  `3.9` or `"3"`; a float parameter is a number; `true` and `false` are not numbers.
- Every path is relative to this folder, uses `/`, and stays inside it. Refuse any other.

**A case id** is `<set>/<library>/<feature>/<point set>`, with `/warp` for a warp output and `#<variant>` when two
cases would otherwise share an id: `original/fns/simplex_billow/scatter_3d#shape` is FastNoiseSIMD's Billow compared by
shape, as OpenSimplex2, beside the same file compared point by point as classic Simplex.

## How a case is compared

| `compare.kind` | Passes when |
| --- | --- |
| `points` | at every point, `abs(ours - reference) <= scale`; with `"coordinate_scaled": true`, `<= scale * max(1, max(abs(x), abs(y)[, abs(z)]) * frequency)` at that point's own coordinates. A warp point passes when every component does. Optionally also `min_correlation` (Pearson, at least) and `within` (at least `fraction` of the points within `scale`; with `"coordinate_scaled": true` in `within`, each point within `scale` times its own allowance, as for the bound). |
| `shape` | every check listed holds: `range` [lo, hi] for every value, `mean_within` and `std_within` (the difference from the reference's mean and standard deviation), `std_ratio` [lo, hi] (ours over the reference's), `finite`. |
| `advisory` | never fails. It reports how close it came, flagged *needs review* when the largest difference is above 1e-4 or the correlation below 0.99, with any verdict `accepted.json` holds for its feature. HogNoise's own test suite draws a comparison sheet for a flagged case and waits for a person's verdict, unless that verdict is `accepted`. |

Every `hog` case is `points` at a scale of 0: bit for bit. A rendering that has a tolerance file is judged on the hog
set by that file instead (below). The `original` cases carry the limits the test suite has always used, from 1e-6
(white noise) to 4e-3 (the domain-warp field), or are compared by shape or advisory where the original library's
arithmetic differs from HogNoise's.

A port that does not cover a case yet reports it as unsupported, not failed; `report.complete` says whether anything was.

## Hog-only cases

Most hog cases repeat an original case's parameters, point set and output with HogNoise's own values. A **hog-only
case** has no original behind it: it is generated to cover what the originals do not, and carries `"hog_only": true`
in its `source`. There are 48:

- **46 on `scatter_2d`**, one for every FastNoiseSIMD feature with a `scatter_3d` case. FastNoiseSIMD is 3D only, so its
  originals have no 2D case; these compare HogNoise's 2D path for white noise, classic Simplex, the perturbs, Natural,
  NoiseLookup, Distance2Cave, Billow and RigidMulti (at z = 0).
- **2 on `genasgrid_0.7_1.0_1.3`**, a grid at scales that are not powers of two (start (-64, -64, 1), shape
  (128, 128, 1)), for classic Simplex FBm (`fns/genasgrid_simplex_fbm_scales_0.7_1.0_1.3`) and OpenSimplex2 FBm
  (`fnl/genasgrid_opensimplex2_fbm_scales_0.7_1.0_1.3`). On a grid point set a rendering may compute the coordinates
  itself from `from`, and at these scales its float32 coordinate can differ in the last bit from the file's.

`hog-noise-vectors --set hog` writes them with the rest of the hog set, and they are compared like every hog
case.

## Tolerance files

A rendering that cannot match the hog set bit for bit is judged by a tolerance file, `tolerance/<rendering>.json`, and
not by the manifest's bounds. There is one, `tolerance/wgpu.json`, for the GPU's float32 shader. It applies to the hog
set only; the original cases keep their own rules for every rendering.

```json
{
  "format": 1,
  "rendering": "wgpu",
  "range": {"frequency": [0.01], "noise_coordinate_max": 40.96},
  "measured": {"record": "reports/gpu/0d419e9/", "adapters": ["NVIDIA GeForce RTX 5090 (Vulkan) on local", "..."]},
  "rules": [
    {"feature": "fnl/simplex_fbm", "kind": "continuous", "bound": {"scale": 2e-05, "coordinate_scaled": true}},
    {"feature": "fnl/warp_opensimplex2_none", "output": "noise", "kind": "continuous",
     "bound": {"scale": 5e-06, "coordinate_scaled": true}},
    {"feature": "fnl/warp_opensimplex2_none", "output": "warp", "kind": "continuous",
     "bound": {"scale": 0.001, "coordinate_scaled": false}},
    {"feature": "fns/cellular_natural_cellvalue", "kind": "discrete", "bound": {"scale": 2.0, "coordinate_scaled": false},
     "within": {"scale": 1e-07, "coordinate_scaled": true, "fraction": 1.0}, "min_correlation": 0.999}
  ]
}
```

- **A rule names a feature**, `<library>/<feature>` (the middle of a case id), and judges every case of it: noise and
  warp, every point set. A feature with both outputs may instead have one rule per `output`, `"noise"` or `"warp"`. Two
  rules covering one case, or a rule naming no hog feature, is an error when the file is read; a case no rule covers
  **fails** with "no tolerance rule", so a feature added later cannot pass by default.
- **`continuous`** is a bound and nothing else, for a feature whose output moves smoothly with its input. The noise
  outputs' bounds are coordinate-scaled. The warp outputs' are absolute (`"coordinate_scaled": false`): the reference
  warps the raw coordinates in float64 before the frequency multiply, so their error follows the raw coordinate.
- **`discrete`** is for a feature where float32 can flip a choice and jump the output: cellular CellValue and
  NoiseLookup, white noise, and the `genasgrid` grids, whose points sit on the lattice where classic Simplex and
  OpenSimplex2 break a tie between two corners. Its `bound` is the width of the output's range (it fails only a value far
  off the noise's scale); `within`, coordinate-scaled, holds `fraction` of the points to a tight bound; and
  `min_correlation` holds the shape, never asking for more than 0.999.
- **`range`** is what the numbers were measured over: the frequencies in the hog set and its largest noise-space
  coordinate (`coordinate * frequency`). The file claims nothing outside it.
- **`measured`** names the record the rules were derived from and the adapters in it.

**How a number is set.** `hog-noise-measure-gpu run` samples every hog case on one machine's adapter and writes a JSON
record to `reports/gpu/<commit>/`: per case, the largest difference, the largest over its coordinate-scaled allowance,
the 99th percentile of that, the correlation, and the fraction of points outside each 1, 2 or 5 step from 1e-7 to
1e-2. `hog-noise-measure-gpu derive reports/gpu/<commit>` reads every adapter's record and writes the rules: twice the
worst over every adapter, rounded up to a 1, 2 or 5 step (the 99th percentile, for a discrete rule's `within`, whose
`fraction` is one minus twice the worst fraction outside and whose `min_correlation` is the worst correlation, each
rounded down to three places, the correlation to at most 0.999). A
measurement the rules cannot hold, such as a discrete feature flipping more than 1% of its points, stops the
derivation as a measurement finding for a person, and so does a folder of records that are not all exactly the hog
set's cases; nothing is written then. `wgpu.json` was derived from four records at commit `0d419e9`: an RTX 5090
(Vulkan) and Direct3D 12's WARP on one machine, and WARP and Mesa's llvmpipe (Vulkan) on CI. A test recomputes every
number from that record, so a number edited by hand fails it. A rule is never loosened to make a run pass: an adapter
that fails one is a measurement finding, and loosening it is a person's decision.
