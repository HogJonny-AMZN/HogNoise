# HogNoise

Procedural noise for Python: the FastNoiseLite and FastNoiseSIMD algorithms in one package, checked against the originals.

**Status:** pre-release, `0.1.0.dev0`. Not on PyPI yet. Python 3.11 to 3.13, numpy 1.26 or newer.

## Why this exists

I wanted all of it, with no restraints. I could build the whole thing, it was only a matter of time, and I didn't want
to spend that time waiting.

I use noise in my own projects, LargeWorlds and SpriteJammer, and I kept running out of what was available. The Python
wrapper for FastNoiseSIMD had its last release on 2021-03-31 and its newest wheel was for Python 3.9. That pinned my
whole project to a Python that could not run the GPU library I was moving to (it needs 3.11). Worse, the wrapper had
been quietly giving me simplex noise where I had asked for cellular, and nothing told me.

I measured three ways out on the same four workloads. For a 4,096-point batch: the `pyfastnoiselite` binding took
0.45 ms, a rebuilt FastNoiseSIMD wheel 0.06 ms, and a numba kernel 0.07 ms. I took the numba kernel: pure Python
source, deterministic, and no wheels for me to build and host forever.

**How it was built:** with AI. It took days to weeks instead of the weeks to months it would have taken me alone. I'm
not a noise researcher, I'm someone who needed it, so I don't ask you to take my word or the AI's. Every feature is
compared against committed vectors from the original libraries, and when a result differs a human reads the comparison
sheet and records a verdict. A mismatch doesn't quietly pass and it doesn't quietly fail.

## What it is

One parameter record, `NoiseParams`, rendered three ways, all selected through a small ladder:

| Rung | What | When |
| --- | --- | --- |
| `numba` | the kernels in `scalar.py`, compiled, parallel over points | numba installed |
| `fastnoiselite` | the `pyfastnoiselite` binding, the reference | `pyfastnoiselite` installed |
| `numpy` | the same algorithms vectorised, exact | always |

The numba and numpy rungs agree bit for bit. Both agree with the binding to float32 rounding. The one runtime
dependency is numpy; everything else is an extra.

```python
import numpy as np
from hog_noise import FractalType, NoiseParams, NoiseType, make_sampler

params = NoiseParams(
    seed=1337, frequency=0.02, noise_type=NoiseType.OPEN_SIMPLEX2, fractal_type=FractalType.FBM, octaves=4
)
sampler, selection = make_sampler(params)
print(selection.describe())  # which rung ran, and why

height = sampler.sample_grid((0, 0, 0), (256, 1, 256))  # (nx, ny, nz): a 256 x 256 heightfield, float32
xs = np.linspace(0, 100, 4096, dtype=np.float32)
out = np.empty(4096, np.float32)
sampler.sample_points(xs, xs, np.zeros_like(xs), out)  # fills out, no allocation per call
```

Force a rung with `HOG_NOISE_BACKEND_NOISE=numpy` (an unavailable rung raises; it never falls through silently).
Install from a checkout for now: `pip install -e ".[jit,reference]"`.

## What it covers

Everything in this table is exercised by the committed vectors.

| Area | Shipped |
| --- | --- |
| Noise types | OpenSimplex2, OpenSimplex2S, classic Simplex (FastNoiseSIMD's, so old seeds reproduce), Perlin, Value, ValueCubic, Cellular, white noise |
| Fractals | FBm, Ridged, PingPong, Billow, RigidMulti, domain-warp progressive and independent, weighted strength |
| Cellular | distance functions Euclidean, EuclideanSq, Manhattan, Hybrid, Natural; nine return types including NoiseLookup and Distance2Cave; jitter |
| Domain warp | OpenSimplex2, OpenSimplex2 reduced, basic grid |
| Gradient perturb | five modes (FastNoiseSIMD's) |
| 3D rotation | the three FastNoiseLite modes |
| Grids | `sample_grid` with axis scales: a 1024 x 1024 field in about 17 ms on the numba rung (author's workstation, 2026-09) |

## What it is not

Say this part out loud, because it decides whether you should use it.

- **Not the fastest noise library.** [FastNoise2](https://github.com/Auburn/FastNoise2) is a C++ SIMD library by the same
  author as FastNoiseLite, with 2D, 3D and 4D noise and a node-graph editor. I never evaluated it. If you need 4D, raw
  C++ speed or a node editor, use it.
- **2D and 3D only.** No 4D, no analytic derivatives, no tileable noise.
- **No GPU rung yet.** The design exists; no code does.
- **Not byte-identical to the originals.** Two deliberate deviations, both visible in the comparison report: arithmetic
  is float64 after the float32 frequency multiply, and integer hashing is emulated at 32 bits with wrap.

## Wanted, not built

Listed so you can tell shipped from planned. None of these is a promise.

| Wanted | How it would be verified |
| --- | --- |
| A GPU rung (WGSL compute) and shader emitters from the same parameter record | the same vectors, within a stated tolerance |
| Correctness guarantees at very large coordinates | new vectors far from the origin, against float64 |
| Analytic derivatives, 4D, tileable noise | finite-difference checks, periodicity checks, FastNoise2 output for 4D |
| A conformance harness other ports can run, and the vectors in a language-neutral format | the existing vectors |
| Published benchmarks against FastNoiseLite C++, `pyfastnoiselite` and FastNoiseSIMD | a reproducible script |

**What lies beyond the edge of the known noise corpus I don't know yet.** That is deliberate. When I find out, it gets
verified by properties (derivatives against finite differences, periodicity, agreement across backends), because no
reference library exists out there.

## How to trust it

- `tests/vectors/noise/` holds the committed vectors: 66 files from FastNoiseLite and 51 from FastNoiseSIMD, plus the
  coordinates they were sampled at.
- `tests/vectors/noise/portability.md` is the comparison table, regenerated by the test suite. Of 208 comparisons,
  75 are bit-identical, 74 are within 1e-6, 55 within 1e-4, and 4 within 1e-2. The largest difference is 2.0e-4, on a
  classic-simplex Billow fold. None is beyond.
- A difference past the advisory bar writes a comparison sheet under `tests/vectors/noise/reports/` and waits for a human
  verdict in `accepted.json`. It never fails the build. Once a feature is locked, this package's output is the reference.
- `Docs/noise/GALLERY.md` renders every noise type, generated from the enums, so a new type cannot be left out.
- Run it yourself: `pip install -e ".[dev]"` then `pytest`. CI also runs it on Python 3.11 with numpy 1.26, and with
  numpy alone and no extras.

## For AI agents and contributors

Start at [AGENTS.md](AGENTS.md). [llms.txt](llms.txt) is the short index. Where the code came from and what was changed
is in [PROVENANCE.md](PROVENANCE.md).

## Licence

MIT, see [LICENSE](LICENSE). This is a port, so [NOTICE](NOTICE) carries the FastNoiseLite and FastNoiseSIMD licences and
says where the comparison vectors came from.
