# The emitted languages: implementation plan

**Status:** Accepted 2026-11-17 by the owner with its five decisions as recommended ("best recommendations"). Written from
[the spec](../specs/2026-11-15-emitted-languages.md), Accepted 2026-11-15 with its six decisions as recommended. The build
ticks each step as it lands.
**Board:** [`2026-11-01-gpu-fast-track`](../../plan/board/2026-11-01-gpu-fast-track.md)

> **For agentic workers:** REQUIRED SUB-SKILL: use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to carry this out task by task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `noise.wgsl` ships beside naga's HLSL, GLSL and SPIR-V of it and the tables a host binds, read through
`hog_noise.shaders`, with CI proving each file compiles in its own language's tools and matches the WGSL it came from.

**Architecture:** HogNoise's own tools move first into an app, `apps/hog-noise-tools/` (the spec's decision 5). There a
new `emit_shaders.py` runs a pinned naga into a temporary folder, writes `manifest.json`, and only then replaces the
files in `hog_noise/shaders/`, each atomically. The package gains `hog_noise.shaders`, standard library only, holding the
accessors and the one hash function the emitter and the drift test share. A new workflow regenerates on every push and
compiles every file.

**Tech stack:** Python 3.11 to 3.13, numpy, naga-cli 29.0.2 (Rust, `cargo install`), FXC and DXC from the Windows SDK,
`glslangValidator` and `spirv-val` from Ubuntu's `glslang-tools` and `spirv-tools`, pytest through the `pytest` console
script (`uv run pytest`, never `python -m pytest`), `uv run python tools/check.py` as the gate.

---

## Before you start

- Read the spec end to end; it is the contract and this plan is how to meet it. Where they disagree, the spec wins and
  this plan is the bug.
- Read [the project ledger](../../standards/failure-modes-project.md), above all P-2 (a test that rewrites a committed
  file), P-5 and P-7 (a pull request's state, checked against a fetched `origin/main`), P-8 (the deliberate review before
  the pull request leaves draft), P-10 (a count no command produced), P-13 (a tool that writes committed files, given an
  input that yields nothing) and P-14 (never `python -`; write the script to a file).
- Work on a branch from `origin/main`, never on the local `main` (private history, never pushed). Commits are signed off
  (`git commit -s`) with the owner's identity and no AI attribution. Write each commit message to a file and pass it with
  `-F`.
- Before every gate run, `uv run ruff format .` and `uv run ruff check --fix .`.
- The full gate's tests re-stamp the date in `vectors/portability.md`. Revert it with `git checkout --
  vectors/portability.md` before staging, and stage named paths, never `git add -u` or `-A`.
- The commands are written for bash (Git Bash).
- Every module keeps its `if __name__ == "__main__":` block, the moved ones included.
- **Two pull requests** (decision P1 below). The first is Tasks 1 to 4, the move, and opens as a draft at Task 1 so CI
  runs the compiler probe; it leaves draft after Task 4. The second, Tasks 5 to 13, branches from `origin/main` after the
  first merges.

## Facts this plan rests on

Read from the code at `09386d0` (the merge of [PR #30](https://github.com/HogJonny-AMZN/HogNoise/pull/30)) and measured
on the owner's Windows machine on 2026-11-17, not assumed:

- **There is no naga-cli 29.0.1.** crates.io lists naga-cli 29.0.0, 29.0.2, 29.0.3 and 29.0.4; every one from 29.0.2 on
  requires `naga ^29.0.1`. `cargo install naga-cli --version 29.0.2 --locked` compiles naga 29.0.2 (its install log:
  `Compiling naga v29.0.2`), one patch above the naga 29.0.1 inside wgpu-native 29.0.1.1.
- **naga 29.0.2 answers the spec's open risk "naga 29 versus 30".** The spec's probes, repeated with it on the same
  `noise.wgsl` (74,489 bytes): every file writes with no error; HLSL 133,502 bytes, Metal 138,174, SPIR-V 113,180, the
  five GLSL files 118,460 to 119,214. The HLSL registers (`b0`, `t1` to `t4`, `u5`, `b6`), the GLSL variable names
  (`_group_0_binding_<n>_cs`), the absent `binding =` qualifiers, the 31 `[[user(fake0)]]` in Metal and the absence of
  padding fields are all as in 30.0.1. Every entry point compiles with `fxc -T cs_5_0` and `dxc -T cs_6_0` (Windows SDK
  10.0.18362). The 432 HLSL lines that differ from 30.0.1 are naga's numbering of temporaries (`_e120` against `_e121`)
  and a `ZeroValuefloat` helper 30 adds; the SPIR-V differs in its bytes. Nothing a host binds differs, so decision 2
  stands, pinned at 29.0.2.
- **GLSL block names differ per entry point.** In naga 29.0.2's GLSL the variable `_group_0_binding_<n>_cs` is the one
  member of its block (`layout(std140) uniform Params_block_0Compute { Params _group_0_binding_0_cs; };`), and an entry
  point that does not use a binding has no block for it. The output's block is `type_4_block_5Compute` in
  `sample_points_3d`, `type_4_block_4Compute` in `sample_points_2d` and `type_4_block_2Compute` in `sample_grid`. So the
  manifest records the blocks per entry point. Read by a trial run of Task 7's `bindings` parser over that output.
- **The tools to move.** `tools/gen_noise_vectors.py` (1,001 lines), `tools/noise_gallery.py` (274) and
  `tools/measure_gpu.py` (423), with `tools/noise_oracle/` (the C++ harness: `FastNoiseLite.h`, `fnl_oracle.cpp`,
  `build.bat`), and their tests `tests/test_gen_noise_vectors.py` (355), `tests/test_noise_gallery.py` (66) and
  `tests/test_measure_gpu.py` (323), which reach them through `tests/_tools_path.py`. `measure_gpu.py` came with the GPU
  port, after the Icebox row counted "three tools and two tests".
- **Each tool finds the repository by counting parents** (`ROOT = Path(__file__).resolve().parent.parent`,
  `gen_noise_vectors.py:62`, `noise_gallery.py:29`; `parents[1]`, `measure_gpu.py:40`). `noise_gallery.py:30` still puts
  a LargeWorlds path on `sys.path` (`Build/ArtTools/hog-py-packages`), which resolves to nothing here. The member's tests
  find it by a marker instead (`packages/python/hog-noise/tests/hog_noise_repo.py`, walking up to `framework.toml`).
- **Who names the tools' paths.** `tests.yml:53` runs `python tools/measure_gpu.py run --out measured`. In living
  documents and code, 33 lines in 14 files, from:
  `git grep -n -e tools/gen_noise_vectors -e tools/noise_gallery -e tools/measure_gpu -e tools/noise_oracle -- ':!Docs/journal' ':!Docs/decisions' ':!Docs/superpowers' | wc -l`.
- **CI.** `ci.yml` runs `uv sync --group dev` and the gate's stages, so a workspace member is installed and tested.
  `tests.yml` installs only the library with pip (`python -m pip install -e "packages/python/hog-noise[...]"`) and runs
  `pytest` from the root, whose `testpaths` already include `apps/*/tests`.
- **The tables** are four float32 arrays in `tables.py` (`GRADIENTS_2D` at line 22, `GRADIENTS_3D` 285, `RAND_VECS_2D`
  548, `RAND_VECS_3D` 1067), concatenated in that order for binding 1 at `gpu.py:203`, 2,048 floats.
- **The member's build backend** is `uv_build`, which ships every file under `src/hog_noise/`; `wgsl/noise.wgsl` is in
  today's wheel that way, so `shaders/` will be too (Task 11 lists the wheel to prove it).
- **This machine** has `cargo` and naga 30.0.1 on `PATH` (`~/.cargo/bin`), `fxc` and `dxc` in the Windows SDK, and no
  `glslangValidator` or `spirv-val`.

## Decisions made in this plan

The spec leaves these to the plan. Each is reversible, and each is recorded here so the build does not re-decide it:

| # | Decision | Chosen | Why |
| --- | --- | --- | --- |
| P1 | How many pull requests | Two: the move (Tasks 1 to 4), then the emitter (5 to 13) | The move touches 14 files of paths and three tools with no behaviour change; reviewed alone, a moved line cannot hide a changed one |
| P2 | The naga pin | naga-cli **29.0.2**, in one file, `apps/hog-noise-tools/naga-version.txt`, read by the emitter and by CI | 29.0.1 does not exist as a CLI; 29.0.2 is the nearest above wgpu's naga and measured equivalent (*Facts*). One file, so the cache key and the refusal cannot disagree |
| P3 | Which naga the emitter runs | `HOG_NOISE_NAGA` if set, else `naga` on `PATH` | The owner's `PATH` has 30.0.1 for other work; a variable lets the pinned build live beside it |
| P4 | Where the binding-1 order lives | A new `tables.binding_table()`, used by `gpu.py`, the emitter and the drift test | One definition of the order the tables file and the rung must agree on |
| P5 | The CI compile step | A script, `compile_shaders.py`, in the app, which finds each compiler and runs it on every file | The logic is testable Python, as `Docs/standards/tooling.md` asks of anything more than one command; the workflow only calls it |

## Files

| File | Task |
| --- | --- |
| `apps/hog-noise-tools/pyproject.toml`, `apps/hog-noise-tools/README.md`, `uv.lock`, `framework.toml` (`[layers]`) | 2 |
| `apps/hog-noise-tools/src/hog_noise_tools/__init__.py`, `repo.py` | 2 |
| `apps/hog-noise-tools/src/hog_noise_tools/{gen_noise_vectors,noise_gallery,measure_gpu}.py` (moved from `tools/`) | 2 |
| `apps/hog-noise-tools/noise_oracle/` (moved from `tools/noise_oracle/`) | 2 |
| `apps/hog-noise-tools/tests/test_{gen_noise_vectors,noise_gallery,measure_gpu}.py` (moved from `tests/`), `test_repo.py` | 2 |
| `launchers/hog-noise-{vectors,gallery,measure-gpu}.{cmd,sh}` | 3 |
| `.github/workflows/tests.yml` | 1, 3 |
| `.github/workflows/shaders.yml` | 1, 10 |
| the 14 files that name the old paths, `Docs/noise/GALLERY.md` and `vectors/portability-gpu.md` among them | 3 |
| the Icebox row `2026-11-13-project-tools-into-an-app.md`, the journal, the handoff | 4, 13 |
| `packages/python/hog-noise/src/hog_noise/tables.py`, `gpu.py` | 5 |
| `packages/python/hog-noise/src/hog_noise/shaders/__init__.py` | 6 |
| `packages/python/hog-noise/tests/test_shaders.py` | 6, 8 |
| `apps/hog-noise-tools/naga-version.txt`, `apps/hog-noise-tools/src/hog_noise_tools/emit_shaders.py`, its test | 7 |
| `.gitattributes`, `packages/python/hog-noise/src/hog_noise/shaders/*` (generated), `Makefile` | 8 |
| `apps/hog-noise-tools/src/hog_noise_tools/compile_shaders.py`, its test | 9 |
| `packages/python/hog-noise/src/hog_noise/shaders/README.md` | 11 |
| `README.md`, `llms.txt`, `Docs/glossary.md`, `Docs/standards/testing-project.md`, `Docs/standards/python-project.md` | 12 |

---

### Task 0: the spec records the naga it now pins (in this plan's pull request)

**Files:** modify `Docs/superpowers/specs/2026-11-15-emitted-languages.md`, `Docs/README.md`.

- [x] **Step 1:** In the spec's *Open risks*, after "naga 29 versus 30.", add: "*Amended 2026-11-17 (plan):* answered.
  There is no naga-cli 29.0.1; 29.0.2 (naga 29.0.2) repeats every fact above that a host binds, and both compilers
  accept its HLSL. The plan's *Facts* hold the numbers; it pins 29.0.2."
- [x] **Step 2:** In `Docs/README.md`, add the spec's row, missing since [PR #26](https://github.com/HogJonny-AMZN/HogNoise/pull/26),
  and this plan's.
- [x] **Step 3:** `uv run python tools/check_docs.py`. Expected: `no drift`. Commit with the plan and its records.

---

### Task 1: a draft pull request whose CI finds the compilers

The spec's first open risk: whether `windows-latest` has `fxc.exe` and `dxc.exe` on a known path, and how long naga takes
to build there. Answered by CI before anything depends on it.

**Files:** create `.github/workflows/shaders.yml`.

- [x] **Step 1:** Write the probe workflow:

```yaml
name: shaders

on:
  push:
    branches: [main]
  pull_request:

jobs:
  probe-windows:
    name: compilers (Windows)
    runs-on: windows-latest
    steps:
      - name: Find FXC and DXC
        shell: pwsh
        run: |
          Get-ChildItem "C:\Program Files (x86)\Windows Kits\10\bin" -Recurse -Include fxc.exe,dxc.exe -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -match '\\x64\\' } | ForEach-Object { $_.FullName }
          Get-Command dxc.exe -ErrorAction SilentlyContinue | ForEach-Object { "on PATH: $($_.Source)" }
  probe-ubuntu:
    name: compilers and naga (Ubuntu)
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - name: Install glslang and SPIR-V tools
        run: sudo apt-get update && sudo apt-get install -y glslang-tools spirv-tools
      - name: Versions
        run: glslangValidator --version && spirv-val --version
      - name: Build naga-cli 29.0.2, timed
        run: time cargo install naga-cli --version 29.0.2 --locked
```

- [x] **Step 2:** Branch `feat/hog-noise-tools-app` from `origin/main`, commit, push, open the pull request as a draft
  titled "HogNoise's own tools move into an app" (its body from `.github/pull_request_template.md`; *Not covered*: the
  move is Tasks 2 to 4).
- [x] **Step 3:** `gh pr checks <n> --watch`, then read each probe's log. Record in the pull request: the SDK folder that
  holds `x64/fxc.exe` and `x64/dxc.exe` (the newest one), the two Ubuntu versions, and the naga build's wall time.
  **If either Windows compiler is missing**, stop and tell the owner; the spec's fallback (DXC from its GitHub release,
  FXC's check dropped) is theirs to accept.

### Task 2: the app, with the three tools, the oracle and their tests

**Files:** see the table, rows for Task 2.

- [x] **Step 1:** Move with history:

```bash
mkdir -p apps/hog-noise-tools/src/hog_noise_tools apps/hog-noise-tools/tests
git mv tools/gen_noise_vectors.py tools/noise_gallery.py tools/measure_gpu.py apps/hog-noise-tools/src/hog_noise_tools/
git mv tools/noise_oracle apps/hog-noise-tools/noise_oracle
git mv tests/test_gen_noise_vectors.py tests/test_noise_gallery.py tests/test_measure_gpu.py apps/hog-noise-tools/tests/
```

- [x] **Step 2:** Write `apps/hog-noise-tools/pyproject.toml`:

```toml
# hog-noise-tools: HogNoise's own tools, an app member (Docs/standards/layout.md): the vector generator, the gallery,
# the GPU measurement and, from stage 3, the shader emitter. Never published.
[project]
name = "hog-noise-tools"
version = "0.1.0"
description = "HogNoise's own tools: reference vectors, the gallery, the GPU measurement, the emitted shaders"
requires-python = ">=3.11,<3.14"
authors = [
    {name = "HogJonny", email = "hogjonny-github@protonmail.com"},
]
dependencies = [
    "hog-noise",
    "numpy>=1.26.0",
]

[project.scripts]
hog-noise-vectors = "hog_noise_tools.gen_noise_vectors:main"
hog-noise-gallery = "hog_noise_tools.noise_gallery:main"
hog-noise-measure-gpu = "hog_noise_tools.measure_gpu:main"

[tool.uv.sources]
hog-noise = { workspace = true }

[build-system]
requires = ["uv_build>=0.13.8,<0.14"]
build-backend = "uv_build"
```

  The email is the one the library's manifest already names (the handoff's open question about it covers both).

- [x] **Step 3:** Write `apps/hog-noise-tools/src/hog_noise_tools/__init__.py` (a docstring naming the app, `_MODULE_NAME
  = "hog_noise_tools"`, `__version__ = "0.1.0"`) and `repo.py`, the marker walk the member's tests already use:

```python
"""
HogNoise tools: where the repository is, found by walking up to its marker, never by counting parents.
Package: hog_noise_tools.repo

The tools read and write the repository's own folders (``vectors/``, ``Docs/noise/``), so they run from a checkout. A
counted ``Path(__file__).parents[N]`` shifts silently when a folder moves, as this app's move would have shown; a
marker does not.
"""

from pathlib import Path

_MODULE_NAME = "hog_noise_tools.repo"
__version__ = "0.1.0"

HERE = Path(__file__).resolve().parent


def above(start: Path, marker: str) -> Path:
    """The nearest folder at or above ``start`` holding the file ``marker``.

    :raises RuntimeError: When none does, naming the marker and the start: the tools run from a checkout.
    """
    found = next((p for p in [start, *start.parents] if (p / marker).is_file()), None)
    if found is None:
        raise RuntimeError(f"no {marker} at or above {start}: run HogNoise's tools from a checkout of the repository")
    return found


REPO_ROOT = above(HERE, "framework.toml")
APP_ROOT = above(HERE, "pyproject.toml")
VECTORS = REPO_ROOT / "vectors"


if __name__ == "__main__":
    print(f"repository {REPO_ROOT}\napp        {APP_ROOT}\nvectors    {VECTORS}")
```

- [x] **Step 4:** In each moved tool, replace the counted root with `from hog_noise_tools.repo import REPO_ROOT as ROOT`
  (keeping the name `ROOT`, so every later use is unchanged), and set its `Package:` line and `_MODULE_NAME` to
  `hog_noise_tools.<module>`. In `noise_gallery.py` delete line 30 (the LargeWorlds `sys.path.insert`) and the
  `# noqa: E402` it forced on the imports after it. In `gen_noise_vectors.py:709`, `ORACLE_DIR = ROOT / "tools" /
  "noise_oracle"` becomes `ORACLE_DIR = APP_ROOT / "noise_oracle"` (import `APP_ROOT` too). Usage lines in the
  docstrings become the console scripts (`hog-noise-vectors --set original --source fnl`, `hog-noise-gallery --check`,
  `uv run --group gpu hog-noise-measure-gpu run`).
- [x] **Step 5:** In each moved test, replace `import _tools_path` and `import <tool>` with
  `from hog_noise_tools import <tool>` (keeping each test's alias: `as gen`, `as m`); `test_noise_gallery.py:13`'s
  `ROOT` becomes `from hog_noise_tools.repo import REPO_ROOT as ROOT`. Each `Package:` line becomes
  `apps/hog-noise-tools/tests/<file>`.
- [x] **Step 6:** Write `apps/hog-noise-tools/tests/test_repo.py`:

```python
"""
HogNoise tools: the repository is found by its marker.
Package: apps/hog-noise-tools/tests/test_repo
"""

import pytest

from hog_noise_tools import repo


def test_the_repository_root_holds_the_marker_and_the_vectors():
    assert (repo.REPO_ROOT / "framework.toml").is_file()
    assert (repo.VECTORS / "manifest.json").is_file()


def test_the_app_root_is_the_app_not_the_repository():
    assert repo.APP_ROOT.name == "hog-noise-tools"


def test_no_marker_says_which_and_where(tmp_path):
    with pytest.raises(RuntimeError, match=r"no framework\.toml at or above"):
        repo.above(tmp_path, "framework.toml")
```

- [x] **Step 7: the layer order.** `framework.toml`'s `[layers]` gains the app's package after the library's,
  `order = ["hog_noise", "hog_noise_tools"]`: the app may import the library, never the reverse. Without it the
  boundary check reports `hog_noise_tools` as `unlisted` (`tools/boundaries.py:449-458`, a package in neither
  `layers.order` nor `layers.unlayered`), and the gate's tests stage fails through
  `tests/test_boundaries.py::test_the_repositorys_own_workspace_keeps_its_own_layers`. Then
  `uv run python tools/boundaries.py`: expected, `boundaries: clean`.
- [x] **Step 8:** `uv sync --group dev`, then `uv run pytest apps/hog-noise-tools -q`. Expected: the moved tests' count
  before the move, plus 3, all passing or skipped with the same reasons as before (compare with
  `uv run pytest tests/test_gen_noise_vectors.py tests/test_noise_gallery.py tests/test_measure_gpu.py -q` run on
  `origin/main` first, and write both counts in the pull request).
- [x] **Step 9:** `uv run hog-noise-gallery --check` and `uv run hog-noise-vectors --help`: the console scripts run, and
  the gallery's committed page is still current. **Commit** ("HogNoise's tools move into an app").

### Task 3: launchers, CI and every path that named the old place

- [x] **Step 1:** For each of the three scripts, `launchers/<name>.cmd` (`@uv run <name> %*`) and `launchers/<name>.sh`
  (`#!/bin/sh` then `exec uv run <name> "$@"`), then `git add --chmod=+x launchers/*.sh` (layout.md, *Launchers*).
- [x] **Step 2:** `tests.yml`: the install line also installs the app, and the measurement uses its script:

```yaml
          python -m pip install -e "packages/python/hog-noise[${{ matrix.extras }}]" -e apps/hog-noise-tools "${{ matrix.numpy }}"
```

```yaml
        run: hog-noise-measure-gpu run --out measured
```

  pip takes the library from the editable install in the same command; the CI run of Task 4 proves it on every leg,
  the floor's numpy 1.26 included.
- [x] **Step 3:** Rerun the `git grep` from *Facts* and change every hit to the new place, except the ledger's entries
  (append-only, they say where things were) and `Docs/PYTHON_UPGRADE_AND_FASTNOISE.md` (a carried record). The
  generated two are regenerated, not edited: `uv run hog-noise-gallery` rewrites `Docs/noise/GALLERY.md` after its
  strings change; for `vectors/portability-gpu.md`, change the string in `measure_gpu.py:321` and the same line in the
  committed file, and `test_measure_gpu.py`'s derivation tests prove the two agree. `NOTICE` and the member's copy
  change together (`test_member_files.py` holds them level).
- [x] **Step 4:** Rerun the `git grep`. Expected: hits only in the ledger and the carried record. **Commit**.

### Task 4: the move's records, the gate, out of draft

- [x] The Icebox row `2026-11-13-project-tools-into-an-app.md` is pulled forward and lands, per the board README's
  *Moving a row*: `Section: now`, `Owner: @HogJonny-AMZN`, `State: Landed <date> in [PR #<n>](...)`: the app, its three
  scripts and launchers, `measure_gpu.py` and the oracle with them.
- [x] The journal: a new entry in the build's session file. The handoff: the GPU row says the move landed and the emitter
  is next.
- [x] `uv run python tools/check.py`, unpiped: every stage passes, the boundary check included (the app imports only
  `hog_noise`, and both packages are in `[layers]` from Task 2, Step 7).
- [ ] The deliberate review (`local-review` skill, `diff`), findings answered in *Review*; then out of draft;
  `gh pr checks <n> --watch` green on every leg, the probe jobs included. The owner merges.

---

The second pull request: after the first merges, `git fetch origin` and branch `feat/emitted-shaders` from `origin/main`.
It opens as a draft at Task 5's first push.

### Task 5: one definition of binding 1's order

**Files:** modify `packages/python/hog-noise/src/hog_noise/tables.py`, `gpu.py`; test in
`packages/python/hog-noise/tests/test_shaders.py` (created here).

- [ ] **Step 1: the failing test.** Create `test_shaders.py` with:

```python
"""
HogNoise: the emitted shaders, their manifest and the tables a host binds.
Package: packages/python/hog-noise/tests/test_shaders
"""

import numpy as np

from hog_noise import tables


def test_the_binding_table_is_the_four_tables_in_order():
    t = tables.binding_table()
    assert t.dtype == np.float32 and t.shape == (2048,)
    parts = [tables.GRADIENTS_2D, tables.GRADIENTS_3D, tables.RAND_VECS_2D, tables.RAND_VECS_3D]
    assert np.array_equal(t, np.concatenate(parts))
```

- [ ] **Step 2:** `uv run pytest packages/python/hog-noise/tests/test_shaders.py -q`. Expected: FAIL,
  `AttributeError: module 'hog_noise.tables' has no attribute 'binding_table'`.
- [ ] **Step 3:** Add to `tables.py`, after `RAND_VECS_3D`:

```python
def binding_table() -> NDArray[np.float32]:
    """The four tables in the order a shader reads them at binding 1: the 2D and 3D gradients, then the 2D and 3D
    random vectors, 2,048 float32. ``gpu.py`` uploads it, and the emitter writes it as ``shaders/tables.f32``."""
    return np.concatenate([GRADIENTS_2D, GRADIENTS_3D, RAND_VECS_2D, RAND_VECS_3D]).astype(np.float32, copy=False)
```

  and in `gpu.py:203` replace the inline `np.concatenate([...])` with `table = tables.binding_table()`.
- [ ] **Step 4:** The new test passes; `uv run --group gpu pytest packages/python/hog-noise/tests/test_gpu.py -q` passes
  as before. **Commit**.

### Task 6: `hog_noise.shaders`, the accessors and the shared hash

**Files:** create `packages/python/hog-noise/src/hog_noise/shaders/__init__.py`; extend `test_shaders.py`.

- [ ] **Step 1: the failing tests.** Append to `test_shaders.py`:

```python
import subprocess
import sys

import pytest

from hog_noise import gpu, shaders


def test_the_entry_points_are_the_rungs():
    assert shaders.ENTRY_POINTS == gpu.ENTRY_POINTS


def test_text_hashes_ignore_line_endings_and_binary_hashes_do_not():
    assert shaders.sha256(b"a\r\nb\n", text=True) == shaders.sha256(b"a\nb\n", text=True)
    assert shaders.sha256(b"a\r\nb\n", text=False) != shaders.sha256(b"a\nb\n", text=False)


@pytest.mark.parametrize("call", [lambda: shaders.path("metal"), lambda: shaders.source("cuda")])
def test_an_unknown_language_names_the_known_ones(call):
    with pytest.raises(ValueError, match=r"wgsl, hlsl, glsl, spirv"):
        call()


def test_glsl_needs_an_entry_point_and_names_them():
    with pytest.raises(ValueError, match=r"sample_points_3d"):
        shaders.path("glsl")
    with pytest.raises(ValueError, match=r"sample_points_3d"):
        shaders.path("glsl", "sample_points_4d")


def test_a_whole_module_language_refuses_an_entry_point():
    with pytest.raises(ValueError, match=r"one file for every entry point"):
        shaders.path("hlsl", "sample_grid")


def test_wgsl_is_the_rungs_source():
    assert shaders.path("wgsl").name == "noise.wgsl"
    assert "@compute" in shaders.source("wgsl")
```

- [ ] **Step 2:** Run them. Expected: FAIL, `ImportError: cannot import name 'shaders'`.
- [ ] **Step 3:** Write `shaders/__init__.py`:

```python
"""
HogNoise: the emitted shaders, naga's HLSL, GLSL and SPIR-V of ``noise.wgsl``, and the tables a host binds.
Package: hog_noise.shaders

Every file here except this module and ``README.md`` is written by ``make shaders`` (the app's ``emit_shaders.py``) and
never edited by hand; ``manifest.json`` records the run. Standard library only: a host reading a shader needs neither
numpy's GPU code nor ``wgpu``. ``sha256`` is the one hash the emitter and the drift test share, so a Windows checkout
(CRLF) and an Ubuntu one (LF) agree.
"""

from __future__ import annotations

import hashlib
import importlib.resources
import json
from pathlib import Path
from typing import Any

_MODULE_NAME = "hog_noise.shaders"
__version__ = "0.1.0"

LANGUAGES = ("wgsl", "hlsl", "glsl", "spirv")
#: The compute entry points of noise.wgsl; ``gpu.ENTRY_POINTS`` holds the same, and a test holds them level.
ENTRY_POINTS = ("sample_points_3d", "sample_points_2d", "sample_grid", "warp_points_3d", "warp_points_2d")
TABLES_FILE = "tables.f32"
TABLES_BYTES = 2048 * 4
MANIFEST_FILE = "manifest.json"
#: The whole-module files; GLSL is one file per entry point, ``noise.<entry_point>.comp``.
_WHOLE = {"hlsl": "noise.hlsl", "spirv": "noise.spv"}


def file_name(language: str, entry_point: str | None = None) -> str:
    """The emitted file's name for ``language`` (and, for GLSL, the entry point).

    :raises ValueError: An unknown language or entry point, naming the known ones; GLSL without an entry point; an
        entry point for a language that is one file for every entry point.
    """
    if language not in LANGUAGES:
        raise ValueError(f"unknown shader language {language!r}; known: {', '.join(LANGUAGES)}")
    if language == "glsl":
        if entry_point not in ENTRY_POINTS:
            raise ValueError(f"GLSL is one file per entry point; pass one of: {', '.join(ENTRY_POINTS)}")
        return f"noise.{entry_point}.comp"
    if entry_point is not None:
        raise ValueError(f"{language} is one file for every entry point; pass no entry_point")
    return "noise.wgsl" if language == "wgsl" else _WHOLE[language]


def path(language: str, entry_point: str | None = None) -> Path:
    """Where the shader is on disk. WGSL is the source, in ``hog_noise/wgsl/``; the rest are here."""
    name = file_name(language, entry_point)
    folder = importlib.resources.files("hog_noise") / ("wgsl" if language == "wgsl" else "shaders")
    return Path(str(folder / name))


def source(language: str, entry_point: str | None = None) -> str | bytes:
    """The shader: text, or bytes for SPIR-V."""
    p = path(language, entry_point)
    return p.read_bytes() if language == "spirv" else p.read_text(encoding="utf-8")


def tables() -> bytes:
    """The 8,192 bytes a host binds at binding 1: the four tables, float32 little-endian (``tables.binding_table``).

    :raises ValueError: When the file is not 8,192 bytes, which the drift test makes impossible on a checkout.
    """
    data = (importlib.resources.files("hog_noise") / "shaders" / TABLES_FILE).read_bytes()
    if len(data) != TABLES_BYTES:
        raise ValueError(f"{TABLES_FILE} is {len(data)} bytes, not {TABLES_BYTES}: run make shaders")
    return data


def manifest() -> dict[str, Any]:
    """The record of the emitter run that wrote these files (the glossary's *Shader manifest*)."""
    return json.loads((importlib.resources.files("hog_noise") / "shaders" / MANIFEST_FILE).read_text(encoding="utf-8"))


def sha256(data: bytes, *, text: bool) -> str:
    """The SHA-256 the manifest records: of a text file's bytes with CRLF made LF, or of a binary file as it is."""
    return hashlib.sha256(data.replace(b"\r\n", b"\n") if text else data).hexdigest()


if __name__ == "__main__":
    for lang in LANGUAGES:
        for ep in ENTRY_POINTS if lang == "glsl" else (None,):
            print(f"{lang:6} {ep or '':18} {path(lang, ep)}")
```

- [ ] **Step 4:** The Step 1 tests pass (the ones reading emitted files wait for Task 8). The package boundary test
  passes: the module imports the standard library only. **Commit**.

### Task 7: the emitter, test first, P-13 from the start

**Files:** create `apps/hog-noise-tools/naga-version.txt` (one line, `29.0.2`),
`apps/hog-noise-tools/src/hog_noise_tools/emit_shaders.py`, `apps/hog-noise-tools/tests/test_emit_shaders.py`; the
app's `[project.scripts]` gains `hog-noise-emit-shaders = "hog_noise_tools.emit_shaders:main"`.

- [ ] **Step 1: the failing tests.** They drive the emitter with a fake naga, a Python script that prints a version and
  writes a file for each output it is asked for, so they need no naga:

```python
"""
HogNoise tools: the shader emitter refuses before it writes, and writes all or nothing (ledger P-13).
Package: apps/hog-noise-tools/tests/test_emit_shaders
"""

import json
import sys

import pytest

from hog_noise import shaders
from hog_noise_tools import emit_shaders as e

FAKE = """
import pathlib, sys
args = sys.argv[1:]
if args == ["--version"]:
    print("{version}")
    sys.exit(0)
out = pathlib.Path(args[-1])
if out.name in {fail!r}:
    sys.exit(3)
out.write_bytes(b"" if out.name in {empty!r} else ("// " + out.name + "\\r\\n").encode())
"""


def fake_naga(tmp_path, version="29.0.2", fail=(), empty=()):
    script = tmp_path / "fake_naga.py"
    script.write_text(FAKE.format(version=version, fail=list(fail), empty=list(empty)), encoding="utf-8")
    return [sys.executable, str(script)]


@pytest.fixture
def dest(tmp_path):
    d = tmp_path / "shaders"
    d.mkdir()
    (d / "README.md").write_text("hand-written", encoding="utf-8")
    (d / "noise.hlsl").write_text("old", encoding="utf-8")
    return d


def snapshot(d):
    return {p.name: p.read_bytes() for p in d.iterdir()}


def test_a_wrong_naga_version_refuses_and_writes_nothing(tmp_path, dest):
    before = snapshot(dest)
    with pytest.raises(
        e.EmitError, match=r"naga 30\.0\.1 .* the pin is 29\.0\.2.*cargo install naga-cli --version 29\.0\.2"
    ):
        e.emit(fake_naga(tmp_path, version="30.0.1"), dest, pin="29.0.2")
    assert snapshot(dest) == before


def test_a_naga_that_prints_no_version_refuses_and_writes_nothing(tmp_path, dest):
    before = snapshot(dest)
    with pytest.raises(e.EmitError, match=r"printed no version.*cargo install naga-cli --version 29\.0\.2"):
        e.emit(fake_naga(tmp_path, version=""), dest, pin="29.0.2")
    assert snapshot(dest) == before


def test_a_naga_failure_on_one_file_leaves_every_file_as_it_was(tmp_path, dest):
    before = snapshot(dest)
    with pytest.raises(e.EmitError, match=r"noise\.sample_grid\.comp"):
        e.emit(fake_naga(tmp_path, fail=["noise.sample_grid.comp"]), dest, pin="29.0.2")
    assert snapshot(dest) == before


def test_an_empty_output_refuses_like_a_failure(tmp_path, dest):
    before = snapshot(dest)
    with pytest.raises(e.EmitError, match=r"noise\.spv.*empty"):
        e.emit(fake_naga(tmp_path, empty=["noise.spv"]), dest, pin="29.0.2")
    assert snapshot(dest) == before


def test_a_run_writes_every_file_lf_with_its_manifest_and_keeps_the_readme(tmp_path, dest):
    e.emit(fake_naga(tmp_path), dest, pin="29.0.2")
    names = {p.name for p in dest.iterdir()}
    expected = {"README.md", "manifest.json", "tables.f32", "noise.hlsl", "noise.spv"}
    expected |= {f"noise.{ep}.comp" for ep in shaders.ENTRY_POINTS}
    assert names == expected
    assert b"\r\n" not in (dest / "noise.hlsl").read_bytes()
    assert (dest / "README.md").read_text(encoding="utf-8") == "hand-written"
    m = json.loads((dest / "manifest.json").read_text(encoding="utf-8"))
    assert m["naga"] == "29.0.2"
    for name, entry in m["files"].items():
        data = (dest / name).read_bytes()
        assert entry["sha256"] == shaders.sha256(data, text=entry["text"]) and entry["bytes"] == len(data)


def test_running_twice_changes_nothing(tmp_path, dest):
    naga = fake_naga(tmp_path)
    e.emit(naga, dest, pin="29.0.2")
    first = snapshot(dest)
    e.emit(naga, dest, pin="29.0.2")
    assert snapshot(dest) == first


def test_a_stale_emitted_file_is_removed(tmp_path, dest):
    (dest / "noise.retired_entry.comp").write_text("old", encoding="utf-8")
    e.emit(fake_naga(tmp_path), dest, pin="29.0.2")
    assert not (dest / "noise.retired_entry.comp").exists()


def test_the_pin_is_one_line_in_one_file():
    assert e.pinned_version() == "29.0.2"
```

- [ ] **Step 2:** `uv run pytest apps/hog-noise-tools/tests/test_emit_shaders.py -q`. Expected: FAIL at import.
- [ ] **Step 3:** Write `emit_shaders.py`:

```python
"""
HogNoise tools: write naga's HLSL, GLSL and SPIR-V of noise.wgsl, the tables and the manifest into hog_noise/shaders/.
Package: hog_noise_tools.emit_shaders

    make shaders                      # == uv run hog-noise-emit-shaders
    HOG_NOISE_NAGA=/path/to/naga make shaders

The naga that writes them is pinned (``apps/hog-noise-tools/naga-version.txt``, the stage 3 spec's decision 2): a
different version is refused before anything runs. Every file is built in a temporary folder beside the destination;
any naga failure or empty output refuses with nothing written (ledger P-13); only then is each file replaced atomically,
and an emitted file the run no longer writes is removed. Text is written LF, and every hash is ``shaders.sha256``.
"""

from __future__ import annotations

import argparse
import json
import logging as _logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from hog_noise import shaders, tables
from hog_noise_tools.repo import APP_ROOT, REPO_ROOT

_MODULE_NAME = "hog_noise_tools.emit_shaders"
__version__ = "0.1.0"
_LOGGER = _logging.getLogger(_MODULE_NAME)

NAGA_ENV = "HOG_NOISE_NAGA"
PIN_FILE = APP_ROOT / "naga-version.txt"
GLSL_PROFILE = "core430"
WGSL = shaders.path("wgsl")
DEST = shaders.path("hlsl").parent
WORKGROUP_SIZE = 64
DISPATCH = "point_index = gid.x + gid.y * 65535 * 64"
#: Names this emitter owns in the destination; anything else there (README.md, __init__.py) is left alone.
_OWNED = re.compile(r"^(noise\.[\w.]+|tables\.f32|manifest\.json)$")


class EmitError(RuntimeError):
    """The emitter refused; nothing was written."""


def pinned_version() -> str:
    """The naga-cli version the shaders are written with."""
    return PIN_FILE.read_text(encoding="utf-8").strip()


def default_naga() -> list[str]:
    """``HOG_NOISE_NAGA`` if set, else ``naga`` on PATH."""
    return [os.environ.get(NAGA_ENV) or "naga"]


def check_naga(naga: Sequence[str], pin: str) -> None:
    """Refuse a naga that is missing or not the pinned version, saying how to install the pinned one."""
    try:
        found = subprocess.run([*naga, "--version"], capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        install = f"cargo install naga-cli --version {pin} --locked"
        raise EmitError(f"cannot run naga ({' '.join(naga)}): {exc}; {install}") from exc
    if not found.split():
        raise EmitError(
            f"{' '.join(naga)} printed no version for --version; cargo install naga-cli --version {pin} --locked"
        )
    if found.split()[-1] != pin:
        raise EmitError(
            f"naga {found} at {' '.join(naga)}, but the pin is {pin}: cargo install naga-cli --version {pin} --locked "
            f"--root <folder>, then set {NAGA_ENV} to its bin/naga"
        )


def jobs() -> list[tuple[str, list[str]]]:
    """Each emitted file and the naga arguments that write it, the output path last."""
    out = [("noise.hlsl", []), ("noise.spv", [])]
    out += [
        (f"noise.{ep}.comp", ["--profile", GLSL_PROFILE, "--entry-point", ep, "--shader-stage", "compute"])
        for ep in shaders.ENTRY_POINTS
    ]
    return out


def bindings(build: Path) -> list[dict[str, Any]]:
    """The binding table per language, read from what was emitted, so a naga rename shows in the manifest's diff."""
    wgsl = WGSL.read_text(encoding="utf-8")
    hlsl = (build / "noise.hlsl").read_text(encoding="utf-8")
    glsl = {ep: (build / f"noise.{ep}.comp").read_text(encoding="utf-8") for ep in shaders.ENTRY_POINTS}
    rows = []
    for group, binding, name in re.findall(r"@group\((\d+)\)\s*@binding\((\d+)\)\s*var(?:<[^>]*>)?\s+(\w+)", wgsl):
        register = re.search(rf"\b{name}\s*:\s*register\(([btu]\d+)\)", hlsl)
        var = f"_group_{group}_binding_{binding}_cs"
        blocks = {}
        for ep, text in glsl.items():
            # naga writes `layout(std140) uniform Params_block_0Compute { Params _group_0_binding_0_cs; };`: the
            # variable is the block's one member, and an entry point that does not use a binding has no block for it.
            found = re.search(rf"(\w+)\s*\{{[^}}]*\b{var}\b", text)
            if found:
                blocks[ep] = found.group(1)
        rows.append({
            "binding": int(binding), "wgsl": name, "hlsl": register.group(1) if register else None,
            "glsl": {"variable": var, "blocks": blocks}, "spirv": {"set": int(group), "binding": int(binding)},
        })  # fmt: skip
    return rows


def build(naga: Sequence[str], pin: str, folder: Path) -> dict[str, Any]:
    """Write every file into ``folder`` and return the manifest; raise ``EmitError`` on any failure or empty file."""
    files: dict[str, Any] = {}
    for name, args in jobs():
        out = folder / name
        cmd = [*naga, *args, str(WGSL), str(out)]
        done = subprocess.run(cmd, capture_output=True, text=True)
        if done.returncode != 0:
            raise EmitError(f"naga failed writing {name} (rc {done.returncode}): {done.stderr.strip()[:400]}")
        if not out.is_file() or out.stat().st_size == 0:
            raise EmitError(f"naga wrote {name} empty or not at all")
        text = not name.endswith(".spv")
        if text:
            out.write_bytes(out.read_bytes().replace(b"\r\n", b"\n"))
        data = out.read_bytes()
        command = " ".join(["naga", *args, "noise.wgsl", name])
        files[name] = {"command": command, "text": text, "sha256": shaders.sha256(data, text=text), "bytes": len(data)}
        _LOGGER.info(f"{name}: {len(data):,} bytes")
    table = tables.binding_table().astype("<f4").tobytes()
    (folder / shaders.TABLES_FILE).write_bytes(table)
    files[shaders.TABLES_FILE] = {
        "command": "hog_noise.tables.binding_table(), float32 little-endian", "text": False,
        "sha256": shaders.sha256(table, text=False), "bytes": len(table),
    }  # fmt: skip
    return {
        "generator": _MODULE_NAME,
        "naga": pin,
        "wgsl": {
            "path": WGSL.relative_to(REPO_ROOT).as_posix(),
            "sha256": shaders.sha256(WGSL.read_bytes(), text=True),
        },
        "glsl_profile": GLSL_PROFILE,
        "workgroup_size": WORKGROUP_SIZE,
        "dispatch": DISPATCH,
        "files": files,
        "bindings": bindings(folder),
    }


def emit(naga: Sequence[str], dest: Path = DEST, pin: str | None = None) -> dict[str, Any]:
    """Check naga, build everything beside ``dest``, then replace ``dest``'s emitted files atomically."""
    pin = pin or pinned_version()
    check_naga(naga, pin)
    folder = Path(tempfile.mkdtemp(prefix=".emit-", dir=dest.parent))
    try:
        manifest = build(naga, pin, folder)
        text = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
        (folder / shaders.MANIFEST_FILE).write_bytes(text.encode("utf-8"))
        written = set(manifest["files"]) | {shaders.MANIFEST_FILE}
        for name in sorted(written):
            os.replace(folder / name, dest / name)
        for stale in (p for p in dest.iterdir() if _OWNED.match(p.name) and p.name not in written):
            stale.unlink()
            _LOGGER.info(f"removed {stale.name}: no longer emitted")
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    _LOGGER.info(f"wrote {len(written)} files to {dest} with naga {pin}")
    return manifest


def main(argv: list[str] | None = None) -> int:
    """Emit the shaders; exit 1 with the reason when the emitter refuses."""
    parser = argparse.ArgumentParser(prog="hog-noise-emit-shaders", description=__doc__.split("\n\n")[0])
    parser.parse_args(argv)
    _logging.basicConfig(level=_logging.INFO, format="%(message)s")
    try:
        emit(default_naga())
    except EmitError as exc:
        print(f"emit-shaders: refused, nothing written: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4:** The tests pass. Then a test of `bindings` on the real emitted files waits for Task 8; there, append to
  `test_shaders.py` a check that the manifest's `bindings` give HLSL `b0, t1, t2, t3, t4, u5, b6` for bindings 0 to 6
  and the GLSL variable `_group_0_binding_<n>_cs` for each, with a block named in every entry point that uses it.
  **Commit**.

### Task 8: the shaders, emitted and committed, and the drift test

**Files:** modify `.gitattributes`, `Makefile`; create `packages/python/hog-noise/src/hog_noise/shaders/*` (generated);
extend `test_shaders.py`.

- [ ] **Step 1:** `.gitattributes`, after the `*.py` block:

```text
# The WGSL and the shaders naga writes from it: LF on every checkout, so a hash is the same everywhere (the stage 3 spec).
*.wgsl    text eol=lf
*.hlsl    text eol=lf
*.comp    text eol=lf
*.spv     binary
```

  then `git add --renormalize .` and `git status`: expected, nothing but `.gitattributes` (the WGSL is already LF in the
  index).
- [ ] **Step 2:** `Makefile`: `shaders` joins `.PHONY`, the help gains
  `@echo   make shaders     - write the HLSL, GLSL, SPIR-V, tables and manifest from noise.wgsl with the pinned naga`,
  and the recipe is `uv run hog-noise-emit-shaders`. `uv run pytest tests/test_tooling.py -q` passes.
- [ ] **Step 3:** Build the pinned naga outside `PATH` and emit:

```bash
cargo install naga-cli --version "$(cat apps/hog-noise-tools/naga-version.txt)" --locked --root "$HOME/.naga-29"
HOG_NOISE_NAGA="$HOME/.naga-29/bin/naga" make shaders
HOG_NOISE_NAGA="$HOME/.naga-29/bin/naga" make shaders && git status --short packages/python/hog-noise/src/hog_noise/shaders
```

  Expected: the first run writes nine files; the second changes nothing (spec acceptance 1).
- [ ] **Step 4: the drift tests.** Append to `test_shaders.py`:

```python
def test_the_manifest_names_the_current_wgsl():
    current = shaders.sha256(shaders.path("wgsl").read_bytes(), text=True)
    assert shaders.manifest()["wgsl"]["sha256"] == current, (
        "noise.wgsl changed since the shaders were emitted: make shaders"
    )


def test_every_emitted_file_matches_its_manifest_entry():
    folder = shaders.path("hlsl").parent
    for name, entry in shaders.manifest()["files"].items():
        data = (folder / name).read_bytes()
        assert shaders.sha256(data, text=entry["text"]) == entry["sha256"], (
            f"{name} differs from its manifest: make shaders"
        )


def test_the_tables_file_is_the_tables_module():
    assert shaders.tables() == tables.binding_table().astype("<f4").tobytes(), "tables.py changed: make shaders"


def test_every_language_and_entry_point_has_its_file():
    for lang in shaders.LANGUAGES:
        for ep in shaders.ENTRY_POINTS if lang == "glsl" else (None,):
            assert shaders.source(lang, ep), (lang, ep)
    assert len(shaders.tables()) == 8192


def test_the_shaders_need_no_wgpu():
    code = "import sys; sys.modules['wgpu'] = None; from hog_noise import shaders; print(len(shaders.source('hlsl')))"
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert int(done.stdout) > 100_000
```

- [ ] **Step 5:** `uv run pytest packages/python/hog-noise/tests/test_shaders.py -q`: all pass.
- [ ] **Step 6: prove the instrument** (spec acceptance 3). Change one byte of `noise.wgsl` (a digit in a comment), run
  the drift tests: expected, `test_the_manifest_names_the_current_wgsl` FAILS with "make shaders". Revert with
  `git checkout -- packages/python/hog-noise/src/hog_noise/wgsl/noise.wgsl`; they pass. Paste both outputs into the pull
  request. Then the same for one float in `tables.py`, failing `test_the_tables_file_is_the_tables_module`; revert.
- [ ] **Step 7:** **Commit** the generated files with the attributes and the Makefile ("The emitted shaders").

### Task 9: the compile script

**Files:** create `apps/hog-noise-tools/src/hog_noise_tools/compile_shaders.py` and its test; the app's scripts gain
`hog-noise-compile-shaders = "hog_noise_tools.compile_shaders:main"`.

- [ ] **Step 1: the failing tests**, with `subprocess.run` and the finder replaced:

```python
"""
HogNoise tools: the compile script runs each language's own compiler on every emitted file.
Package: apps/hog-noise-tools/tests/test_compile_shaders
"""

import subprocess

import pytest

from hog_noise import shaders
from hog_noise_tools import compile_shaders as c


@pytest.fixture
def calls(monkeypatch):
    seen = []

    def run(argv, **kwargs):
        seen.append([str(a) for a in argv])
        return subprocess.CompletedProcess(argv, 0, "version 1\n", "")

    monkeypatch.setattr(c.subprocess, "run", run)
    monkeypatch.setattr(c, "find", lambda name: f"/bin/{name}")
    return seen


def test_hlsl_compiles_every_entry_point_in_both_compilers(calls):
    assert c.main(["hlsl"]) == 0
    for ep in shaders.ENTRY_POINTS:
        assert any(a[0] == "/bin/fxc" and "cs_5_0" in a and ep in a for a in calls)
        assert any(a[0] == "/bin/dxc" and "cs_6_0" in a and ep in a for a in calls)


def test_glsl_validates_every_file_and_spirv_is_validated(calls):
    assert c.main(["glsl", "spirv"]) == 0
    assert sum(a[0] == "/bin/glslangValidator" and a[-1].endswith(".comp") for a in calls) == 5
    assert any(a[0] == "/bin/spirv-val" and a[-1].endswith("noise.spv") for a in calls)


def test_a_missing_compiler_fails_and_names_it(monkeypatch, capsys):
    monkeypatch.setattr(c, "find", lambda name: None)
    assert c.main(["spirv"]) == 2
    assert "spirv-val not found" in capsys.readouterr().err


def test_a_compile_error_fails_with_its_output(monkeypatch, calls, capsys):
    def run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 1, "", "error X3000: syntax error")

    monkeypatch.setattr(c.subprocess, "run", run)
    assert c.main(["hlsl"]) == 1
    assert "X3000" in capsys.readouterr().err
```

- [ ] **Step 2:** Run them. Expected: FAIL at import.
- [ ] **Step 3:** Write `compile_shaders.py`:

```python
"""
HogNoise tools: compile every emitted shader with its own language's compiler, printing each compiler's version.
Package: hog_noise_tools.compile_shaders

    uv run hog-noise-compile-shaders hlsl            # fxc cs_5_0 and dxc cs_6_0, every entry point (Windows)
    uv run hog-noise-compile-shaders glsl spirv      # glslangValidator per file, spirv-val (Ubuntu)

A compiler is found on PATH, or for fxc and dxc in the newest Windows SDK's x64 folder. Exit 0 when every file compiles,
1 when one does not (its output printed), 2 when a compiler is missing.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from hog_noise import shaders

_MODULE_NAME = "hog_noise_tools.compile_shaders"
__version__ = "0.1.0"

SDK_BIN = Path("C:/Program Files (x86)/Windows Kits/10/bin")
NEEDS = {"hlsl": ("fxc", "dxc"), "glsl": ("glslangValidator",), "spirv": ("spirv-val",)}


class MissingCompiler(RuntimeError):
    """A compiler the language needs is not installed."""


def find(name: str) -> str | None:
    """``name`` on PATH, else (fxc, dxc) in the newest Windows SDK's ``x64`` folder."""
    on_path = shutil.which(name)
    if on_path or name not in ("fxc", "dxc") or not SDK_BIN.is_dir():
        return on_path
    found = sorted(SDK_BIN.glob(f"10.*/x64/{name}.exe"))
    return str(found[-1]) if found else None


def commands(language: str, tool: dict[str, str], out: Path) -> list[list[str]]:
    """Every compiler call for ``language``."""
    if language == "hlsl":
        src = str(shaders.path("hlsl"))
        fxc = [[tool["fxc"], "-nologo", "-T", "cs_5_0", "-E", ep, "-Fo", str(out), src] for ep in shaders.ENTRY_POINTS]
        dxc = [[tool["dxc"], "-T", "cs_6_0", "-E", ep, "-Fo", str(out), src] for ep in shaders.ENTRY_POINTS]
        return fxc + dxc
    if language == "glsl":
        return [[tool["glslangValidator"], str(shaders.path("glsl", ep))] for ep in shaders.ENTRY_POINTS]
    return [[tool["spirv-val"], str(shaders.path("spirv"))]]


def main(argv: list[str] | None = None) -> int:
    """Compile the named languages; see the module's docstring for the exit codes."""
    parser = argparse.ArgumentParser(prog="hog-noise-compile-shaders", description=__doc__.split("\n\n")[0])
    parser.add_argument("languages", nargs="+", choices=sorted(NEEDS))
    args = parser.parse_args(argv)
    tool = {}
    for name in (n for lang in args.languages for n in NEEDS[lang]):
        tool[name] = find(name)
        if tool[name] is None:
            print(f"compile-shaders: {name} not found on PATH or in the Windows SDK", file=sys.stderr)
            return 2
        version = subprocess.run([tool[name], "--version"], capture_output=True, text=True)
        print(f"{name}: {tool[name]}: {(version.stdout or version.stderr).strip().splitlines()[:1]}")
    failed = 0
    with tempfile.TemporaryDirectory() as tmp:
        for lang in args.languages:
            for cmd in commands(lang, tool, Path(tmp) / "out.bin"):
                done = subprocess.run(cmd, capture_output=True, text=True)
                ok = done.returncode == 0
                print(f"{'ok  ' if ok else 'FAIL'} {' '.join(Path(a).name if i < 1 else a for i, a in enumerate(cmd))}")
                if not ok:
                    failed += 1
                    print(f"{done.stdout}{done.stderr}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4:** The tests pass. On this machine, `uv run hog-noise-compile-shaders hlsl` (the real fxc and dxc):
  exit 0, ten `ok` lines; paste them into the pull request. `glsl` and `spirv` exit 2 here (not installed) and run in CI.
  **Commit**.

### Task 10: the workflow, the probe made real

**Files:** rewrite `.github/workflows/shaders.yml` (the probe from Task 1 is on `main` by now).

- [ ] **Step 1:** Replace its jobs with three:

```yaml
jobs:
  regenerate:
    # Every push, unconditionally (the spec, amended): a hand edit, or a shader and its hash edited together, fails here.
    name: the shaders are what the pinned naga writes
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - name: The naga pin
        run: echo "NAGA=$(cat apps/hog-noise-tools/naga-version.txt)" >> "$GITHUB_ENV"
      - uses: actions/cache@v4
        id: naga
        with:
          path: ~/.naga
          key: naga-cli-${{ env.NAGA }}-${{ runner.os }}
      - name: Build naga-cli
        if: steps.naga.outputs.cache-hit != 'true'
        run: cargo install naga-cli --version "$NAGA" --locked --root ~/.naga
      - uses: astral-sh/setup-uv@v7
      - run: uv sync --group dev
      - name: Emit
        run: HOG_NOISE_NAGA=~/.naga/bin/naga uv run hog-noise-emit-shaders
      - name: Nothing changed
        run: git diff --exit-code
  hlsl:
    name: HLSL in FXC and DXC (Windows)
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v7
      - uses: astral-sh/setup-uv@v7
      - run: uv sync --group dev
      - run: uv run hog-noise-compile-shaders hlsl
  glsl-spirv:
    name: GLSL in glslang, SPIR-V in spirv-val (Ubuntu)
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - run: sudo apt-get update && sudo apt-get install -y glslang-tools spirv-tools
      - uses: astral-sh/setup-uv@v7
      - run: uv sync --group dev
      - run: uv run hog-noise-compile-shaders glsl spirv
```

  Use the `actions/cache` and `astral-sh/setup-uv` versions `ci.yml` already pins, if they differ from these.
- [ ] **Step 2:** Push; `gh pr checks <n> --watch`; read each job's log: the regeneration job's `git diff` empty, ten HLSL
  `ok` lines, five GLSL and one SPIR-V. **If GLSL fails** on `core430` (glslang reads the `#version 430 core` naga
  writes), stop and bring the error to the owner: decision 4 is theirs.
- [ ] **Step 3: prove the regeneration job can fail.** Push a commit that edits one line of `noise.hlsl` and its hash in
  the manifest together; the `regenerate` job fails on the diff while the drift test passes. Revert in the next commit;
  link both runs in the pull request.

### Task 11: the shipped README and the wheel

- [ ] **Step 1:** Write `packages/python/hog-noise/src/hog_noise/shaders/README.md`: the files and that they are
  generated (`make shaders`, never edited); the binding table per language (from `manifest.json`'s `bindings`, the
  HLSL register, the GLSL variable, the SPIR-V set and binding); the workgroup size and the dispatch rule; how to fill
  the two uniforms (`hog_noise.gpu.pack_params(params)`, `pack_grid(start, shape, scales)`, which need no `wgpu`) and
  binding 1 (`shaders.tables()`, or `tables.f32` from a host with no Python); GLSL binds by naga's names, and Metal is not
  shipped (the spec's decision 1).
- [ ] **Step 2:** `gpu.pack_params` and `gpu.pack_grid` docstrings say they are the documented way a host fills the
  uniforms, linking the README.
- [ ] **Step 3:** `uv build --package hog-noise --out-dir dist-check`, then list the wheel with a script file (P-14, never
  `python -`) that opens it with `zipfile` and prints every name under `hog_noise/shaders/`. Expected: `__init__.py`,
  `README.md` and the nine emitted files. Delete `dist-check/`. **Commit**.

### Task 12: the documents

- [ ] `README.md` and `llms.txt`: the shaders ship (HLSL SM 5.0, GLSL 430, SPIR-V), how to read them
  (`hog_noise.shaders`), what is proven (each compiles, each matches the WGSL it came from) and what is not (no host runs
  them against the vectors yet; Metal is not shipped).
- [ ] `Docs/glossary.md`: **Emitted shader** and **Shader manifest** lose "(spec, Accepted)" for the built module's
  link; no new term (the compile script and the pin file are not concepts).
- [ ] `Docs/standards/testing-project.md`: the drift test, the regeneration job, the compile jobs, `HOG_NOISE_NAGA`,
  and *Generated files* gains `hog_noise/shaders/`.
- [ ] `Docs/standards/python-project.md`, *The package boundary*: `hog_noise.shaders` is standard library only.
- [ ] `uv run python tools/check.py`, unpiped: every stage passes. **Commit** ("Documents: the emitted shaders").

### Task 13: the review, the records, out of draft

- [ ] The board row `2026-11-01-gpu-fast-track.md`: stage 3 landed with the pull request linked; the design's three
  stages done.
- [ ] `Docs/handoffs/CURRENT.md`: the GPU row; the PyPI row's condition ("numpy, WGSL and at least HLSL") now met, so the
  release waits only on the owner's go.
- [ ] The journal: an entry in the build's session file, for a person: what naga wrote, what each compiler said, any
  finding.
- [ ] The deliberate review (`local-review` skill) of the whole diff, findings answered in *Review* (P-8).
- [ ] The pull request body: *Verified* (the test counts, the two emitter runs, the instrument's two failures, the
  compile logs, the wheel listing), *Decisions* (this plan's table and anything the build added), *Not covered*
  (running the files against the vectors; Metal; PyPI).
- [ ] `gh pr checks <n> --watch`: every leg green, the three shader jobs included. Out of draft. The owner merges.

---

## Acceptance, mapped

| Spec acceptance | Where |
| --- | --- |
| 1. `make shaders` writes the files; twice changes nothing | Task 8, Step 3, on the owner's machine; `test_running_twice_changes_nothing` |
| 2. The five checks pass in CI on the head | Task 10, Step 2, and Task 13: the drift and surface tests in every `tests.yml` leg, the regeneration job, the compile jobs, the emitter's tests |
| 3. A one-byte WGSL change fails the drift test | Task 8, Step 6, shown in the pull request |
| 4. `source("hlsl")` without `wgpu` | `test_the_shaders_need_no_wgpu` |

| Spec check | Where |
| --- | --- |
| 1. The drift test | `test_the_manifest_names_the_current_wgsl`, `test_every_emitted_file_matches_its_manifest_entry`, `test_the_tables_file_is_the_tables_module` |
| 2. The surface test | `test_every_language_and_entry_point_has_its_file`, the `ValueError` tests (Task 6) |
| 3. The regeneration job | `shaders.yml` `regenerate`, proven able to fail (Task 10, Step 3) |
| 4. The compile jobs | `shaders.yml` `hlsl` and `glsl-spirv`, through `compile_shaders.py` |
| 5. The emitter's tests | `test_emit_shaders.py`: a wrong version, no version, a naga failure, an empty output, idempotence, stale files |

## Decisions for the owner

| # | Decision | Recommended | Alternative |
| --- | --- | --- | --- |
| P1 | How many pull requests | Two: the move, then the emitter | One, as the GPU port was |
| P2 | The naga pin | naga-cli 29.0.2 (no 29.0.1 CLI exists; measured equivalent) | 29.0.4, the newest 29 |
| P3 | Which naga runs | `HOG_NOISE_NAGA`, else `naga` on PATH | `naga` on PATH only, the owner switching versions |
| P4 | The table order | `tables.binding_table()`, shared | The emitter repeats `gpu.py`'s list |
| P5 | The CI compile step | A tested script in the app | Shell in the workflow |

## Cost

2.5 to 4.5 d, the spec's 2 to 4 d plus the move's 0.5 d.

## Terms introduced

None. The plan uses the spec's: **Emitted shader** and **Shader manifest**. `naga-version.txt` and the compile script are
files, not concepts.
