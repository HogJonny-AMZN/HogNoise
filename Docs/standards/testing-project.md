# Testing: HogNoise's additions

**Status:** Living. Extends [testing.md](testing.md): these rules add to it and never weaken it.

## The vectors are the oracle

`tests/vectors/noise/` holds outputs captured from the original libraries (`fnl/` from `pyfastnoiselite`, `fns/` from
`pyfastnoisesimd`, the domain warp from the C++ harness in `tools/noise_oracle`). A difference past the advisory bar writes a
comparison sheet under `tests/vectors/noise/reports/` and waits for a human verdict in `accepted.json`; it never fails the
build. **Never loosen a tolerance or edit a vector to make a test pass.** Once a feature is locked, this package's output is
the reference. [NOTICE](../../NOTICE) says where each set of vectors came from.

## Generated files are never edited by hand

- `Docs/noise/GALLERY.md` and its sheets come from `uv run python tools/noise_gallery.py`; `tests/test_noise_gallery.py`
  fails when the page falls behind the enums.
- `tests/vectors/noise/portability.md` is rewritten by a full-environment test run (numba and `pyfastnoiselite` both
  installed). A partial run skips the writer on purpose, so a numpy-only run cannot replace the full table with a partial one.

## The environments that must pass

Three, because each catches what the others cannot: Python 3.13 with every extra; Python 3.11 with numpy 1.26 (the library
floor); and numpy alone, with no extras, which proves the package stands on its one runtime dependency. A test that names the
best rung it expects computes it from what is installed (`HAVE_NUMBA`, `_have_fastnoiselite()`).
