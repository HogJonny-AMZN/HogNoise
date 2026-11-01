# ADR-007: Procedural noise is our own kernel port, with `pyfastnoiselite` as the reference

**Date**: 2026-09-13
**Status:** Accepted — Decided — implemented in fast-track phase F1 (Docs/PYTHON_UPGRADE_AND_FASTNOISE.md, D2 and D4)

## Context

`FastNoiseSignal` wrapped `pyfastnoisesimd`, whose newest wheel is cp39 and whose last release was
2021. That single dependency pinned the project to Python 3.9 and therefore blocked `wgpu`
(Python >= 3.11). Three ways out were measured on the same four workloads (a 4 096-point bin, a
65 536-point batch, 512 x 512 and 1024 x 1024 grids, 4 fractal octaves):

| Option | 4 096-point bin | Verdict |
| --- | --- | --- |
| `pyfastnoiselite` binding | 0.45 ms | 7x slower than FastNoiseSIMD, single-threaded, holds the GIL |
| `pyfastnoisesimd` rebuilt from source | 0.06 ms | Works on 3.12 and 3.13 against numpy 2, bit-identical, but we would build and host wheels forever |
| numba kernel, `parallel=True` | 0.05 ms (prototype), 0.07 ms (the port) | Matches FastNoiseSIMD, pure Python source, deterministic, no wheel problem |

The world loop's unit of work is the first row: about 0.8 ms per frame for all signals combined
(ADR-004). `pyfastnoiselite` alone would exceed that.

## Decision

**Noise comes from `large_worlds/signals/noise_kernels/`**, a line-by-line port of the
FastNoiseLite algorithms (MIT) rendered three ways from one parameter record, `NoiseParams`:

- `vectorized.py`, the numpy base: always present, exact, allocates freely.
- `scalar.py`, the same algorithms as plain Python that numba compiles when installed: the world
  loop's rung, `parallel=True` over points, `fastmath=False`, `cache=True`.
- the `pyfastnoiselite` binding, configured from the same `NoiseParams`: the reference the port
  is compared against, and the fallback on a machine without numba.

`FastNoiseSignal` keeps its public API (`noise_type`, `frequency`, `seed`, `set_fractal_parameters`,
`sample`, `sample_area`, `sample_points`) and gains `set_cellular_parameters`, `params`,
`backend_name`, `describe` and `set_backend`. `FASTNOISE_AVAILABLE` is always True because the
base rung always exists. `pyfastnoisesimd` is used once more, on the last Python 3.9 checkout, to
capture the Phase C oracle vectors, then removed in F2.

**Scope of the port** is the union of FastNoiseSIMD and FastNoiseLite over time (pre-ADR 4.2). F1
ships OpenSimplex2 (2D, 3D), Perlin, Value, ValueCubic, Cellular with every distance function and
return type, the FBm, Ridged and PingPong fractals, weighted strength, and the three 3D rotations.
Cellular was Phase B on paper and moved into F1 because the synthetic world's biome layer asks
for it, and the old wrapper had been silently substituting simplex for it.

**Two deliberate deviations from the reference**, both visible in the comparison report rather
than hidden: arithmetic is float64 after the float32 frequency multiply, and integer hashing is
emulated at 32 bits with wrap. Result: the numba kernel and the numpy base agree bit-for-bit on
every machine, and both agree with the binding to float32 rounding (max 1.6e-4 on 4-octave
PingPong, better than 1e-6 on Value and ValueCubic).

**Correctness is compared, not gated.** Every feature is compared against committed vectors from
`pyfastnoiselite` (Phase A and B) and `pyfastnoisesimd` (Phase C). A mismatch beyond the advisory
bar writes a comparison sheet under `tests/vectors/noise/reports/` and marks the test
`needs-review`; a human records the verdict in `tests/vectors/noise/accepted.json`. It never fails
the build. The portability table `tests/vectors/noise/portability.md` is regenerated from the
same comparisons. Once a feature is locked, our own kernel's output is the reference.

## Consequences

- Same seed, different noise from the FastNoiseSIMD era: OpenSimplex2 replaced classic Simplex
  and the hashing changed. Nothing persists generated worlds, so nothing broke. The vectors are
  the record of what noise looked like on either side of the port.
- `populate_test_world`, which samples one point at a time, went from 4.06 s to 1.37 s because
  the single-point entry is a compiled scalar call (0.8 µs), not a batch launch.
- The numpy base is the slowest rung by far on small batches (about 20 ms per 4 096 points cold,
  4.6 ms warm) because every operation allocates; the ladder prefers `pyfastnoiselite` over it, so
  the base only runs where neither numba nor the binding is present, or on request.
- A new class of test: exact agreement between rungs we own. Any change to a kernel must keep
  `scalar.py` and `vectorized.py` in step, and the tests say so immediately.
- `tests/vectors/noise/` holds 108 oracle files (1.5 MB). Phase C vectors cannot be regenerated
  without a `pyfastnoisesimd` build; the generator script is committed beside them.

## Alternatives rejected

- **Keep `pyfastnoisesimd`, host our own wheels.** It works (bit-identical on 3.12 and 3.13) but
  makes a dormant 2021 extension a permanent build responsibility and leaves the feature set
  frozen. Recorded in the pre-ADR as the escape hatch.
- **Use `pyfastnoiselite` as the fast path.** Measured 7 to 18x slower than FastNoiseSIMD, GIL-bound,
  and it cannot be threaded around. Kept as the reference and fallback, where its speed is enough.
