# Python: HogNoise's additions

**Status:** Living. Extends [python.md](python.md): these rules add to it and never weaken it.

## The package boundary

`hog_noise` imports the standard library and numpy. numba (`fast`), `pyfastnoiselite` (`reference`) and Pillow (`sheets`) are
optional extras, each imported behind a guard, so the package imports with numpy alone. It never imports a graphics stack,
except `wgpu` (`gpu`) in `gpu.py`, behind the override-only `wgpu` rung (the GPU fast track), and never a sibling
project. `gpu.py` imports `wgpu` inside its functions, never at the top, so importing `hog_noise` or using any other
rung never loads it. `packages/python/hog-noise/tests/test_package_boundary.py` enforces it two ways: a static scan of
every import, with `wgpu` allowed in `gpu.py` alone (`MODULE_ALLOWED`), and a fresh interpreter that refuses the
forbidden names, `wgpu` among them, and still imports the package and samples the default ladder. The `[layers]` table in `framework.toml` has one layer,
`hog_noise`; it is not `pure`, because it imports numpy.

**A new runtime dependency is a decision**, not a convenience: numpy is the only one. Prefer what is already declared.

## Two rungs, one answer

The numba kernels in `scalar.py` and the numpy base in `vectorized.py` are one algorithm rendered twice and must agree bit
for bit. A kernel change keeps its numpy twin and the agreement test. numba is used only where a benchmark says it pays,
always with `fastmath` off, because `fastmath` lets the two renderings disagree.

## Where this code runs

The library floor is Python 3.11 with numpy 1.26, because Maya 2026 ships them, so library code uses nothing newer than
3.11 syntax (`target-version = "py311"`). Log messages are ASCII only: emoji and other non-ASCII characters break Maya's
script editor. Paths are `pathlib.Path`, with `str()` only at an API boundary.
