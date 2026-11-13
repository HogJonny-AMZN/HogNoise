# Testing: HogNoise's additions

**Status:** Living. Extends [testing.md](testing.md): these rules add to it and never weaken it.

## The vectors are the oracle

[`vectors/`](../../vectors/README.md) holds two reference sets as raw float32 and one manifest: `original/`, captured from
the original libraries (`fnl/` from `pyfastnoiselite`, `fns/` from `pyfastnoisesimd`, the domain warp from the C++ harness in
`tools/noise_oracle`), and `hog/`, this package's numpy rendering, which every rendering must match bit for bit. The suite
reads them through `hog_noise.conformance`. An advisory difference past `tight` (or with correlation below 0.99) writes a
comparison sheet under `vectors/reports/` and waits for a human verdict in `accepted.json`; it never fails the build.
**Never loosen a bound or edit a vector to make a test pass.** A kernel change that moves a value fails the hog set until
`uv run python tools/gen_noise_vectors.py` (the hog set) is rerun, and that rerun is a decision the pull request records.
[NOTICE](../../NOTICE) says where each original set came from.

## Generated files are never edited by hand

- `Docs/noise/GALLERY.md` and its sheets come from `uv run python tools/noise_gallery.py`; `tests/test_noise_gallery.py`
  fails when the page falls behind the enums.
- `vectors/manifest.json` and every `.f32` file come from `tools/gen_noise_vectors.py` (`--set hog` anywhere numpy is;
  `--set original` where the bindings are), which recomputes every digest; `load` refuses a hand-edited file.
- `vectors/portability.md` is rewritten by a full-environment test run (numba and `pyfastnoiselite` both
  installed). A partial run skips the writer on purpose, so a numpy-only run cannot replace the full table with a partial one.

## The environments that must pass

Three, because each catches what the others cannot: Python 3.13 with every extra; Python 3.11 with numpy 1.26 (the library
floor); and numpy alone, with no extras, which proves the package stands on its one runtime dependency. A test that names the
best rung it expects computes it from what is installed (`HAVE_NUMBA`, `_have_fastnoiselite()`).
