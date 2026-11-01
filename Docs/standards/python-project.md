# Python: HogNoise's additions

**Status:** Living. Extends [python.md](python.md): these rules add to it and never weaken it.

## The package boundary

`hog_noise` imports the standard library and numpy. numba (`jit`), `pyfastnoiselite` (`reference`) and Pillow (`sheets`) are
optional extras, each imported behind a guard, so the package imports with numpy alone. It never imports a graphics stack
or a sibling project. `tests/test_hog_noise/test_package_boundary.py` enforces it two ways: a static scan of every import,
and a fresh interpreter that refuses the forbidden names. The `[layers]` table in `framework.toml` has one layer,
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
