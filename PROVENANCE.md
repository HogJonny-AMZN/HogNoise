# Provenance

**Status:** Living

HogNoise began as a one-way, filtered copy of the noise stack in the LargeWorlds repository
(private). This file records exactly what was copied and when, so anyone can see where the two
copies diverge.

| Field | Value |
| --- | --- |
| Source repository | `HogJonny-AMZN/LargeWorlds`, branch `main` |
| Source commit | `bc8ebd2048af0a14a00627b12168315674e5798a` (merge of PR #98) |
| Snapshot made | 2026-10-11 |
| Method | `git clone` of `main` into a new directory, then `git filter-repo --path ...` on that clone; the source repository was not modified |
| Commits kept | 113 of 1,021 (only commits touching the paths below) |

## Paths kept (original locations, unchanged in this commit)

- `Build/ArtTools/hog-py-packages/large_worlds/signals/noise_kernels/`: the kernels
- `Build/ArtTools/hog-py-packages/large_worlds/backends.py`: the ladder this package will carry its own small version of
- `tests/test_noise_kernels/`, `tests/test_backends.py`, `tests/test_noise_gallery.py`, `tests/_tools_path.py`
- `tests/vectors/noise/`: the oracle vectors and comparison reports
- `tools/noise_oracle/`, `tools/gen_noise_vectors.py`, `tools/noise_gallery.py`
- `Docs/noise/`, ADR-007, ADR-008, ADR-009, `Docs/PYTHON_UPGRADE_AND_FASTNOISE.md`, `Docs/DETAILED_FASTNOISE_PERF.md`

## Stage 2: stand-alone (2026-10-11, branch `stage2/stand-alone`)

Done in this repository only; the source repository was not touched.

| Change | Detail |
| --- | --- |
| Layout | `src/hog_noise/` (the eight kernel modules plus `backends.py`, moved with `git mv`), `tests/test_hog_noise/`, `tools/`, `Docs/` |
| Names | `large_worlds.signals.noise_kernels` is `hog_noise`; `large_worlds.backends` is `hog_noise.backends`. Docstring headers read `HogNoise:` |
| Ladder | `hog_noise.backends`, the ladder copied from the source (ADR-009), capability-agnostic. The override variable is `HOG_NOISE_BACKEND_<CAPABILITY>` (`HOG_NOISE_BACKEND_NOISE`), not `LARGE_WORLDS_<CAPABILITY>_BACKEND` |
| Dropped | The `legacy_numpy` rung and `LegacyNumpySampler`: they wrapped LargeWorlds' pre-port `noise_signal.py`, which is not here. The test that covered it is replaced by one that proves naming it raises and never falls through |
| Fixed on the way | `test_ladder_picks_the_best_available...` assumed `pyfastnoiselite` was installed; with only numpy it failed. It now computes the best available rung. `test_write_portability_table` rewrote the committed `portability.md` from whatever a run measured, so a numpy-only run replaced the full table with a partial one in the working tree; it now writes only when numba and the binding were both compared |
| Added | `pyproject.toml` (runtime dependency: numpy; extras `jit`, `reference`, `sheets`, `test`, `dev`), `.gitignore`, `.github/workflows/tests.yml`, `tests/test_hog_noise/test_package_boundary.py` (static import scan plus a fresh interpreter that refuses the sibling packages) |
| Unchanged | The kernels' algorithms, the oracle vectors, the committed gallery images. `portability.md` regenerated: only its date line moved, every row is identical |

Measured on this commit, each in its own virtualenv:

| Environment | Result |
| --- | --- |
| Python 3.13, numpy 2.5, numba, `pyfastnoiselite`, Pillow | 246 passed, 3 skipped |
| Python 3.11, numpy 1.26 (the floor), same extras | 246 passed, 3 skipped |
| Python 3.13, numpy only | 176 passed, 73 skipped (the skips are the comparisons that need a second rung, and the table writer) |

The 3 skips in every row are the sunset check with no sunset declared. At stage 2 the CI workflow had not run, as there was no remote; it first ran on 2026-11-01, on publishing, and passed.

## Stage 3: publish-ready, still private (2026-10-11, branch `stage3/publish-ready`)

| Change | Detail |
| --- | --- |
| Licence | `LICENSE` (MIT, "Copyright (c) 2026 HogJonny"), `NOTICE` carrying the FastNoiseLite and FastNoiseSIMD licences verbatim as published upstream, and the source of the comparison vectors. `pyproject.toml` declares `license = "MIT"` and ships both files in the wheel (checked by building one) |
| Verified upstream facts | `pyfastnoisesimd`: BSD-3-Clause, last upload 2021-03-31, newest wheel cp39. `pyfastnoiselite`: MIT classifier, 0.0.7 uploaded 2025-12-07. Both from PyPI metadata fetched 2026-10-11 |
| Documents | `README.md` (a field report, with a status table that separates shipped from wanted), `AGENTS.md`, `CLAUDE.md` (a pointer), `llms.txt`, `Docs/README.md`, `Docs/standards/failure-modes.md` (three entries from real events) |
| Carried documents | `Docs/PYTHON_UPGRADE_AND_FASTNOISE.md` is marked Historical with section 4 named as the part that applies; ten links to files that were never copied lost their link; the sentence naming the source project's CI credential was removed. The ADRs are unedited |
| Checks added | `tests/test_docs_links.py`: every relative link in every Markdown file resolves, shown to fail on a broken one |
| Sweep | The tree and every commit, for credentials, private-project names, personal and employer identities. No credential values. The name of a CI secret is in two commits (`PYTHON_UPGRADE_AND_FASTNOISE.md`) and is removed from the tip. `pyproject.toml` lists the name only; the source project's address was not copied |
| History | Decided 2026-11-01: a fresh public history (see *The public history starts here*); the filtered history stays private |

## The public history starts here (2026-11-01)

The owner chose a fresh history for the public repository: it begins at one commit carrying the stage 3 tree exactly
(`stage3/publish-ready`, `c4a2394`). The filtered history behind it (the 113 commits kept from the source, then the stage 1
to 3 commits) stays in the private working copy and is not published: its messages cite the source project's pull requests
and board vocabulary, and its metadata carries two author names. The stage sections above remain the record of what was
done; their commit hashes refer to that private history.

## Adopting the template (2026-11-01)

The repository runs on `ai-first-template` 0.4.0 with no overrides ([ADR-001](Docs/decisions/ADR-001-adopt-the-framework.md)).
HogNoise's hand-written `AGENTS.md` and three-entry ledger took the template's versions; their content moved to the
template's extension files and to `Docs/standards/failure-modes-project.md` (P-1 to P-3). `tests/test_docs_links.py` was
removed because the template's docs check covers relative links. The code was brought to the template's lint rules.

## What this is not yet

Not on PyPI. Stage 4 is done: published 2026-11-01 at [https://github.com/HogJonny-AMZN/HogNoise](https://github.com/HogJonny-AMZN/HogNoise), with only the fresh history pushed.
