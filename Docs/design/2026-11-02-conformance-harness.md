# The conformance harness, and the vectors anyone can read

**Status:** Proposed. The owner, 2026-11-02: build it before the GPU port ("do it"), check ports against both reference sets,
and keep the vectors in the repository with `check` taking a path. The rest is proposed here for the owner to lock.

## Intent

Any implementation of HogNoise's noise (the numba and numpy renderings, the coming GPU rung, a port in C# or HLSL) proves itself
the same way: run it on the published coordinates, compare with the published values, and get a table that says, per case,
whether it is within its bound. Today that check is buried in `tests/test_hog_noise/test_kernels.py` and reads `.npz` files
whose parameters are spelled the original libraries' way. After this, it is a module with one call, and the vectors are files
a program in any language can read without numpy.

This is stage 1 of [the north-star roadmap](2026-11-01-north-star-roadmap.md) and comes before stage 2 of
[the GPU fast track](2026-11-01-gpu-fast-track.md), whose "every vector within its feature's bound" becomes a `check` call.

## Decisions

1. **Two reference sets** (owner, 2026-11-02). *original*: what FastNoiseLite and FastNoiseSIMD produced, the existing vectors,
   unchanged. *hog*: what HogNoise's numpy rendering produces on the same coordinates and parameters, new. A port of HogNoise
   checks against *hog* to its own bound (zero for the CPU renderings, the measured multiple of the coordinate for the GPU);
   anyone can check against *original*, with the bounds the comparison table already states.
2. **The vectors stay in the repository; `check` takes the folder** (owner, 2026-11-02). They move from `tests/vectors/noise/`
   to a top-level `vectors/`, so they read as a product, not test data. The wheel stays small. A release asset can carry the
   same folder later without changing the format.
3. **One portable format, and it is the only committed form.** *Proposed.* Raw little-endian `float32` files with no header,
   and one `manifest.json` describing every case. The `.npz` files are converted once and removed, so there are never two
   copies to drift apart. The comparison sheets, `accepted.json` and `portability.md` stay beside them.
4. **Parameters in HogNoise's own names.** *Proposed.* The manifest stores each case's `NoiseParams` with its field names and
   enum member names (`"noise_type": "OPEN_SIMPLEX2"`), not the source libraries' spellings, so a port maps one record, and
   `NoiseParams.from_dict` / `to_dict` round-trip it. The original source and its own spelling stay in the case's `source`.
5. **A case is a parameter record over a named point set, and says what it outputs.** *Proposed.* The shared point sets
   are `scatter_3d` (4,096 points), `scatter_2d` (the same points as (x, z)) and `grid_y0` (128 x 128 at y = 0, in the order
   of today's `grid_x` and `grid_z`). A case may have its own instead: the two FastNoiseSIMD `genasgrid_*` fixtures are
   128 x 128 grids from (-64, -64, 1) at axis scales (1, 1, 1) and (1, 0.5, 2), flattened in `sample_grid`'s C order, and
   are written out as their own point files, so no port reconstructs a grid. The output is `noise` (N values; a warp in
   the parameters is applied inside, the end-to-end path) or `warp` (N x 2 or N x 3 warped coordinates: the nine
   FastNoiseLite warp cases' `warp_2d`, `warp_3d` and `grid_warp_3d`). A port implements
   `sample(params, xs, ys, zs) -> float32 (N,)` (`zs` is `None` for 2D) and, if it has a warp,
   `warp(params, xs, ys, zs) -> float32 (N, dims)`; without one, the warp cases are reported as skipped, never as passed.
   `sample_grid` stays tested in the suite against the same values; the harness does not require a grid entry point.
6. **A bound, stated per case or passed in.** *Proposed.* `Bound(scale, coordinate_scaled=False)`: a value passes when
   `|ours - reference| <= scale`, or, when coordinate-scaled, `<= scale * max(1, max(|x|, |y|, |z|) * frequency)`, checked
   per point, the shape the GPU spike measured. *hog* cases default to `Bound(0)`; *original* cases default to their
   recorded class in the comparison table (exact, float32, tight or loose). A caller passes a `Bound` to override, as the
   GPU rung will.
7. **Each case says how it is compared and whether it decides `report.ok`.** *Proposed.* Today's suite compares the
   originals three ways, and the manifest keeps all three rather than forcing them into one:
   - `points`, pointwise within the case's bound. Every *hog* case, and the *original* cases the suite asserts today
     (classic Simplex, gradient perturb, white noise, the warp field, the `genasgrid` grids). These gate.
   - `shape`, where the hash differs so points cannot match: the four FastNoiseSIMD Billow cases (mean and standard
     deviation each within 0.2 of the reference) and the four Phase C cellular cases (standard-deviation ratio between 0.3
     and 3). The statistic and its limits are stored in the case. These gate.
   - `advisory`, the FastNoiseLite comparisons that today always report and never fail the build: each gets its match
     class in the table, with its `accepted.json` verdict if it has one, and never changes `report.ok`.

## The shape

```text
vectors/
  manifest.json                 every case: id, set, source, dims, params, point set, output, comparison, file, sha256, bound
  points/scatter_x.f32 ...      the shared coordinates (scatter x, y, z; grid x, z), and a case's own (the genasgrid grids)
  original/fnl/<case>.f32       FastNoiseLite's values
  original/fns/<case>.f32       FastNoiseSIMD's values
  hog/<case>.f32                HogNoise's numpy values
  accepted.json  portability.md  reports/
```

```python
from hog_noise import conformance

report = conformance.check(my_sample, "vectors", reference="hog")  # every hog case
report = conformance.check(my_sample, "vectors", reference="hog", bound=conformance.Bound(3e-6, coordinate_scaled=True))
assert report.ok, report.table()  # a markdown table, one row per case
```

`python -m hog_noise.conformance vectors --rendering numpy` runs it on a built-in rendering from the command line.

## How it is checked

- numba and numpy pass every *hog* case at `Bound(0)` and every gating *original* case, on all three CI environments, and
  the advisory cases report the classes `portability.md` records today.
- **Nothing is lost in the conversion**: before the `.npz` files are removed, a test maps every array in every one of
  them (noise, warp output, the `genasgrid` grids and their coordinates) to a case or point file whose values are equal.
- **It fails when it should**: a deliberately broken sampler (the seed off by one; one value nudged by 1e-5) fails, so the
  harness is shown able to say no.
- **Language-neutral, proven**: a test reads `manifest.json` and one case with the standard library only (`json` and `array`),
  no numpy, and gets the same numbers.
- The existing advisory comparisons, sheets and `portability.md` are generated from the new files and come out unchanged.
- `tools/gen_noise_vectors.py --set hog` regenerates *hog*; a test fails if the committed *hog* values differ from the numpy
  rendering, so a kernel change cannot leave them stale.

## Cost

1 to 2 days, as the board row says: the format and conversion, the module, moving the tests onto it, the *hog* set.

## Not in this

The GPU rung itself, a port in another language, 4D, FastNoise2 vectors (roadmap stage 3), and a release asset. Repository
size grows by roughly the *hog* set, about 12 MB uncompressed, which git stores compressed.

## Terms introduced

- **Reference set**: one source of expected values in the vectors: *original* (the C++ libraries) or *hog* (HogNoise's numpy
  rendering).
- **Case**: one parameter record over one point set, with its expected output (noise or warp), how it is compared
  (points, shape or advisory) and its bound.
- **Bound**: the largest difference a case accepts, a constant or a multiple of the noise-space coordinate.
