# AGENTS.md

The entry point for any AI agent or new contributor. It is tool-neutral and canonical; `CLAUDE.md` only points here.

## What this is

HogNoise (`hog_noise`) is a Python port of the FastNoiseLite and FastNoiseSIMD algorithms, verified against committed
vectors from the originals. The story and the status table are in [README.md](README.md); where the code came from is in
[PROVENANCE.md](PROVENANCE.md). Read the README's "What it is not" before promising anything.

## Run it

```bash
uv venv .venv && uv pip install --python .venv -e ".[dev]"
.venv/Scripts/pytest            # or .venv/bin/pytest
```

Run `pytest` the console script. CI also runs Python 3.11 with numpy 1.26, and numpy alone with no extras; a change that
only passes with numba or `pyfastnoiselite` installed is broken (see [Docs/standards/failure-modes.md](Docs/standards/failure-modes.md)).

## Layout

| Path | What |
| --- | --- |
| `src/hog_noise/` | the package: `params.py` (the record), `scalar.py` (numba-compilable), `vectorized.py` (numpy base), `samplers.py` (the rungs), `backends.py` (the ladder), `families.py`, `compare.py`, `tables.py` |
| `tests/test_hog_noise/` | mirrors the package; `test_package_boundary.py` enforces the import rule |
| `tests/vectors/noise/` | the oracle: committed vectors, `portability.md`, `accepted.json`, `reports/` |
| `tools/` | `gen_noise_vectors.py`, `noise_gallery.py`, `noise_oracle/` (a C++ harness over the vendored FastNoiseLite header) |
| `Docs/` | `noise/GALLERY.md` (generated), ADR-007 to 009 and the carried roadmap (history, see `Docs/README.md`), `standards/` |

## Rules that bite

1. **Imports.** The package imports the standard library and numpy. numba, `pyfastnoiselite` and Pillow are optional extras
   behind guards. It never imports a graphics stack or a sibling project. A test enforces it.
2. **The vectors are the oracle.** A difference past the advisory bar writes a sheet and waits for a human verdict in
   `accepted.json`. Never loosen a tolerance or edit a vector to make a test pass. Once a feature is locked, this
   package's output is the reference.
3. **Two rungs, one answer.** The numba and numpy rungs agree bit for bit; a kernel change keeps its numpy twin and the
   agreement test. numba only where a benchmark says so, with `fastmath` off.
4. **Generated files are never hand-edited.** `Docs/noise/GALLERY.md` comes from `python tools/noise_gallery.py`;
   `tests/vectors/noise/portability.md` is rewritten by a full-environment `pytest` run (it is skipped in a partial one on
   purpose).
5. **Claims.** The README and the status table claim only what the vectors prove. A feature is "shipped" when it has
   vectors; anything else is "wanted". Say where something is unmeasured.
6. **A test is not deleted or skipped to get green.** Fix it, or replace it with one that covers the intent better and say why.
7. **Measure the control.** A measurement is evidence only after the instrument has produced the opposite answer; a
   mutation that changes nothing is a dead mutation.
8. **One new runtime dependency is a decision.** numpy is the only one. Prefer what is already declared.
9. **House style.** `ruff` (line length 120, target py311, no syntax newer than 3.11). f-strings everywhere, including
   log calls. No emoji or non-ASCII in log messages (it breaks Maya). Keep every module's `if __name__ == "__main__":`
   mini-test. Use `pathlib` for paths.

## Definition of done

- The suite passes on the three CI legs, and you ran them (not just the one on your machine).
- `ruff check src tests tools` is clean.
- Docs updated in the same change: README status table, `PROVENANCE.md` if provenance moved, a failure-modes entry if
  process failed.
- A new noun gets its definition where it is introduced.

## Commits

Commits carry the owner's identity only: no `Co-Authored-By` trailer for an AI and no "generated with" footer. The DCO
`Signed-off-by` stays (`git commit -s`).

## When process fails

Append the entry to [Docs/standards/failure-modes.md](Docs/standards/failure-modes.md) in the same change, as a trigger
("when you notice X, do Y") with the evidence. Then mechanise the class if a check can.
