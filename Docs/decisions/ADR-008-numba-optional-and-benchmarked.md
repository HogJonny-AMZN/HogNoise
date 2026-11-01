# ADR-008: numba is an optional extra, used only where a benchmark says so

**Date**: 2026-09-13
**Status:** Accepted — Decided — implemented in fast-track phase F1 (Docs/PYTHON_UPGRADE_AND_FASTNOISE.md, D3)

## Context

numba gave the noise kernels FastNoiseSIMD's speed without a C extension (ADR-007). It is also a
compiler with a warm-up, a cache directory, a per-Python release lag, and a `fastmath` switch that
can make two machines disagree. SpriteJammer adopted it a year earlier for its horde tick under a
discipline that survived real CI: optional import, a numpy twin for every kernel, agreement tests,
and a recorded lesson about `fastmath` reordering floats until a convergence loop never settled.
This project has one measured use for it, noise, and no appetite for it becoming "the way we write
numpy".

## Decision

- **Optional.** `numba>=0.60` lives in the `jit` extra (`all` includes it). Nothing may *require*
  it: every kernel has a numpy base, and `large_worlds` imports and runs without numba installed.
- **Guarded import.** `scalar.py` does `try: from numba import njit, prange` and, failing that,
  defines a no-op `njit` and `prange = range`, so the same source runs as plain Python. The flag is
  `HAVE_NUMBA`; the ladder (ADR-009) reads it.
- **A twin and an agreement test for every kernel.** The numba kernel and the numpy base of the
  same feature must agree exactly. A kernel without a twin does not merge.
- **A benchmark before a kernel.** A numba kernel is added only with a benchmark on a
  world-loop-sized input showing it earns its place. "It could be faster" is not a reason. The
  first kernel's benchmark is `tests/test_noise_kernels/test_kernels.py::test_bin_sized_batch_meets_the_budget`.
- **`fastmath` is per kernel, off for noise.** Measured free on the reference workstation, and
  cross-CPU determinism of terrain matters more than the last few percent. A later kernel may take
  it with its own measurement.
- **`cache=True` everywhere**, with `NUMBA_CACHE_DIR` set by `activate.ps1` / `activate.cmd` to
  `.venv/numba_cache/` so `.nbi`/`.nbc` files stay out of the source tree.
- **Warm-up at setup, never in a frame.** `World.setup_progressive_generation()` calls
  `noise_kernels.warm_up()`; the setup log reports the cost. Measured: 2.0 to 2.4 s on a cold
  cache, 0.26 s from a warm one.
- **Single points go through a scalar entry.** A `prange` launch costs tens of microseconds; the
  scalar entry costs 0.8 µs. Anything that samples one value at a time uses the latter.
- **`NUMBA_NUM_THREADS` is left to numba** unless a profile shows hybrid-CPU tail frames, in which
  case the loop caps it and records why.

## Consequences

- One more optional dependency with a compile step, and a test category (numba vs numpy
  agreement) that did not exist before.
- The `hog_color` numexpr dispatch already has this shape (`_ne_dispatch.py`); it is a candidate
  for the same ladder the next time it is touched, not now (pre-ADR section 7).
- numba's Python support lags a new CPython by a few months. 0.67 ships cp314 wheels, so the
  3.11 to 3.13 range (D1) is not at risk; note it at the next floor bump.
