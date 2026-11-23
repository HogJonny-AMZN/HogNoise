# The CI proof, first pull request: the host harness, SPIR-V through naga, and GLSL

**Status:** Accepted 2026-11-23 by the owner with its five decisions as recommended ("I accept your recommendations"). Written from [the spec](../specs/2026-11-22-emitted-shaders-ci-proof.md), Accepted
2026-11-22 with its five decisions as recommended. The build ticks each step as it lands.
**Board:** [`2026-11-18-emitted-shaders-run-against-the-vectors`](../../plan/board/2026-11-18-emitted-shaders-run-against-the-vectors.md)

> **For agentic workers:** REQUIRED SUB-SKILL: use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to carry this out task by task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** the shipped `noise.spv` and the five shipped GLSL files run on a software GPU in CI, bound only as the shaders
README says, and pass every hog case within `vectors/tolerance/wgpu.json`, unmodified.

**Architecture:** a new package `hog_noise_tools.hosts` in the tools app. Its `__init__` holds what every host shares:
`HostSampler` (the five calls every sampler has), `renderings(host)` (the three callables `conformance.check` takes), the
dispatch shape, the check that a file hashes to its manifest entry, and the check that a host runs on the target it was
told to expect. Each host is one module with `open_host()` and a `run(entry, params, axes, n, width, grid)`:
`spirv_naga` gives `noise.spv` to wgpu's SPIR-V front end, and `glsl` runs the five `.comp` files in moderngl. Both are
written from the shaders README, never from `hog_noise.gpu`'s `_Gpu`.

**Tech stack:** Python 3.11 to 3.13, numpy, wgpu 0.33 (the `gpu` group), moderngl 5.13 (a new `hosts` group), Mesa
llvmpipe and EGL on Ubuntu, pytest through the `pytest` console script (`uv run pytest`, never `python -m pytest`),
`make check` as the gate.

---

## Before you start

- Read the spec end to end; it is the contract and this plan is how to meet it. Where they disagree, the spec wins and
  this plan is the bug.
- Read [the project ledger](../../standards/failure-modes-project.md), above all P-5 and P-7 (a pull request's state,
  checked against a fetched `origin/main`), P-8 (the deliberate review before the pull request leaves draft), P-14 (never
  `python -`; write the script to a file) and P-22 (a leg asserts the thing it exists to test).
- Work in a worktree on a branch from `origin/main`, never on the local `main` (private history, never pushed). Commits
  are signed off (`git commit -s`) with the owner's identity and no AI attribution. Write each commit message to a file
  and pass it with `-F`.
- Before every gate run, `uv run ruff format .` and `uv run ruff check --fix .`.
- The full gate's tests re-stamp the date in `vectors/portability.md`. Revert it with `git checkout --
  vectors/portability.md` before staging, and stage named paths, never `git add -u` or `-A`.
- The commands are written for bash (Git Bash).
- Every new module ends with an `if __name__ == "__main__":` block.
- **One pull request**, Tasks 1 to 9. It opens as a draft at Task 1 so CI runs the EGL probe, the spec's first open risk,
  before anything is built on it; it leaves draft after Task 9's review.
- **A rule a host fails is a finding for the owner**, never a rule loosened in this pull request
  (`vectors/README.md`, *Tolerance files*). Stop and report it.

## Facts this plan rests on

Read from the code at `8c27b0a` (the merge of [PR #47](https://github.com/HogJonny-AMZN/HogNoise/pull/47)), not assumed:

- **The seam is public.** `hog_noise.gpu.pack_params` (112 bytes), `pack_grid` (48 bytes), `MAX_OCTAVES` (32) and
  `device()` / `adapter_info()` need no private name (`gpu.py:131`, `:143`, `:123`, `:89`, `:108`). `hog_noise.shaders`
  gives `source`, `path`, `file_name`, `tables`, `manifest`, `sha256` and `ENTRY_POINTS` (`shaders/__init__.py`).
- **The manifest has what a host binds.** `manifest()["files"][name]` holds `sha256` and `text` for every shipped file;
  `manifest()["bindings"][n]` holds `hlsl` (`b0`, `t1` to `t4`, `u5`, `b6`) and `glsl.blocks`, a block name per entry point
  that reads the binding. The names are reused across bindings by entry point: in `sample_grid` the output's block is
  `type_4_block_2Compute`, the name the 3D and 2D entry points give binding 2. A host binds by the manifest, per entry point.
- **The GLSL uniforms are scalars.** `Params` is 27 four-byte scalars and `Grid` nine (`noise.wgsl:36-40`;
  `noise.sample_grid.comp:35-45`), so std140 lays them out as `pack_params` and `pack_grid` pack them.
- **The judge.** `conformance.check(sample, vectors, warp=, grid=, tolerance=)` (`conformance.py:508`) takes callables of
  the shape `conformance.renderings` and `conformance.grid_rendering` return (`conformance.py:669`, `:699`). A sampler
  whose constructor raises `NotImplementedError` makes its cases *unsupported*, not failed.
- **The rung's tests are the pattern.** `packages/python/hog-noise/tests/test_gpu.py` has the seed-plus-one control
  (`test_a_seed_off_by_one_fails`), the rule at 0.9 of its worst (`test_a_rule_at_0_9_of_its_worst_fails`), and the
  power-of-two grid against its points, bit for bit. The host tests repeat them per host.
- **This plan's code was run once before it was proposed.** Every `.py` block below was written to its path from
  this file by a script, at `8c27b0a` on the owner's machine (RTX 5090, wgpu 0.33.0, moderngl 5.13 by `uv run --with`,
  never committed), then deleted. ruff passed it. `uv run --group gpu --with "moderngl>=5.13,<6" pytest
  apps/hog-noise-tools/tests/hosts -n 0 -q` gave 36 passed and 1 skipped: every hog case on `spirv-naga` (the 5090's
  Vulkan) and on `glsl` (its OpenGL), within `wgpu.json` unmodified, both controls on each, the stride and grid tests,
  and the bit-for-bit match with the rung; the skip is the bit-for-bit test's `glsl` parametrisation, by design. The
  first form of the GL-after-wgpu test passed against a mutant with no `with ctx:` (wgpu ran before the context was
  made, the order that does not fail), so it was rewritten to the spec's order: against the same mutant it now fails
  with moderngl's `cannot create program`, and passes on the real host. Not run in the trial: CI, EGL, llvmpipe, WARP,
  Metal, and Task 4 step 3's and Task 5 step 4's first mutation.
- **CI.** `tests.yml`'s three GPU legs install the app with `--no-deps`, pin `WGPU_BACKEND_TYPE`, assert it in the
  *Adapter* step and set `HOG_NOISE_REQUIRE_GPU=1`; `pytest` runs the app's tests there too. The root `pyproject.toml`
  holds the dependency groups (`dev`, `gpu`).

## Files

| File | Responsibility |
| --- | --- |
| Create `apps/hog-noise-tools/src/hog_noise_tools/hosts/__init__.py` | What every host shares: `HostSampler`, `renderings`, `open_host`, `workgroups`, `check_hash`, `verified`, `check_target`, the errors |
| Create `apps/hog-noise-tools/src/hog_noise_tools/hosts/spirv_naga.py` | `noise.spv` through wgpu's SPIR-V front end |
| Create `apps/hog-noise-tools/src/hog_noise_tools/hosts/glsl.py` | The five `.comp` files in moderngl, bound by the manifest's block names |
| Create `apps/hog-noise-tools/tests/hosts/test_shared.py` | The shared code, with no GPU |
| Create `apps/hog-noise-tools/tests/hosts/test_hosts.py` | Every host against the vectors, and its controls |
| Create `.github/workflows/hosts.yml` | One job per host the existing legs cannot run: here, `glsl` |
| Modify `.github/workflows/tests.yml` | `spirv-naga` required on the three GPU legs |
| Modify `pyproject.toml`, `uv.lock` | The `hosts` group: moderngl |
| Modify `packages/python/hog-noise/src/hog_noise/shaders/README.md` | *What is proven*; a GL host beside wgpu makes its context current |
| Modify `README.md`, `apps/hog-noise-tools/README.md`, `Docs/standards/testing-project.md`, `Docs/glossary.md` | The claims and the two variables |
| Modify the board row, `Docs/handoffs/CURRENT.md`; create a journal file | Done includes the documents |

---

### Task 1: the EGL probe in CI, as a draft pull request

The spec's first open risk: whether the hosted Ubuntu runner's Mesa gives moderngl a surfaceless EGL context. Learn it
before building on it.

**Files:**
- Create: `.github/workflows/hosts.yml`
- Modify: `pyproject.toml` (the `hosts` group), `uv.lock`

- [x] **Step 1: add the `hosts` group.** In `pyproject.toml`, under `[dependency-groups]`, after `gpu`:

```toml
# The host harnesses' own libraries (hog_noise_tools.hosts): moderngl for the GLSL host. Never the library's.
hosts = ["moderngl>=5.13,<6"]
```

Run: `uv lock && uv sync --all-groups`
Expected: `uv.lock` gains `moderngl` and `glcontext`; the sync succeeds.

- [x] **Step 2: write the probe workflow.** Create `.github/workflows/hosts.yml`:

```yaml
name: hosts

# The emitted shaders run in a host written from their README, on a software GPU, against the vectors (the CI proof's
# spec). spirv-naga runs on tests.yml's three GPU legs; this file holds the hosts those legs cannot run.
on:
  push:
    branches: [main]
  pull_request:

jobs:
  glsl:
    name: GLSL on llvmpipe (Ubuntu, EGL)
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-python@v7
        with:
          python-version: "3.13"
      - name: Mesa's OpenGL through EGL
        run: sudo apt-get update && sudo apt-get install -y libegl1 libgl1-mesa-dri
      - name: Install
        run: |
          python -m pip install --upgrade pip
          # the gpu extra too: the one job with moderngl and wgpu together, so the GL-after-wgpu test runs somewhere
          python -m pip install -e "packages/python/hog-noise[dev,gpu]" "moderngl>=5.13,<6"
          python -m pip install --no-deps -e apps/hog-noise-tools
      - name: Context
        # the spec's first open risk: a surfaceless OpenGL 4.3 context on the runner, and which renderer it is
        run: python -c "import moderngl; c = moderngl.create_standalone_context(require=430, backend='egl'); print(c.info['GL_RENDERER'], '|', c.info['GL_VERSION'])"
```

- [x] **Step 3: commit, push, open the draft.**

```bash
git add pyproject.toml uv.lock .github/workflows/hosts.yml
git commit -s -F <message file>   # "CI proof (a), task 1: probe an EGL context on the hosted runner"
git push -u origin <branch>
gh pr create --draft --base main --title "The CI proof, first pull request: the host harness, SPIR-V through naga, and GLSL" --body-file <body file>
gh pr checks <n> --watch
```

Expected: the *Context* step prints a renderer containing `llvmpipe` and a version of 4.3 or later.

- [x] **Step 4: if it fails, take the fallback and record which.** If `backend='egl'` finds no display, change the
  *Context* and later *Test* steps to run under `xvfb-run -a` with moderngl's default (X11) back end, add `xvfb` to the
  apt line, and set `HOG_NOISE_GL_BACKEND` to empty in the job (Task 5 reads it). Record in the pull request's
  *Decisions* which one ran and the renderer it printed. If neither gives llvmpipe 4.3, stop: that is a finding for the
  owner, and the GLSL host waits.

### Task 2: the shared code, test first

**Files:**
- Create: `apps/hog-noise-tools/tests/hosts/test_shared.py`
- Create: `apps/hog-noise-tools/src/hog_noise_tools/hosts/__init__.py`

- [x] **Step 1: write the failing tests.** Create `apps/hog-noise-tools/tests/hosts/test_shared.py`:

```python
"""
HogNoise tools: what every host harness shares, with no GPU: the dispatch shape, the file check, the target check and
the sampler's own refusals.
Package: apps/hog-noise-tools/tests/hosts/test_shared
"""

import numpy as np
import pytest

from hog_noise import NoiseParams, gpu, shaders
from hog_noise_tools import hosts


class FakeHost:
    """A host that records each dispatch and returns ``n * width`` ascending floats."""

    name = "fake"
    target = "a fake adapter (none)"

    def __init__(self):
        self.calls = []

    def run(self, entry, params, axes, n, width, grid):
        self.calls.append((entry, params, [a.copy() for a in axes], n, width, grid))
        return np.arange(n * width, dtype=np.float32)


@pytest.mark.parametrize(
    "n, groups", [(1, (1, 1, 1)), (64, (1, 1, 1)), (65, (2, 1, 1)), (65535 * 64 + 1, (65535, 2, 1))]
)
def test_the_dispatch_is_the_readmes(n, groups):
    """The README's *Dispatch*: ceil(n / 64) along x, wrapping into y past 65,535."""
    assert hosts.workgroups(n) == groups


def test_the_binding_kinds_are_the_manifests_registers():
    """b is a uniform, t read-only storage, u read-write storage: the README's table, read from the manifest."""
    kind = {"b": "uniform", "t": "read", "u": "write"}
    found = [kind[b["hlsl"][0]] for b in sorted(shaders.manifest()["bindings"], key=lambda b: b["binding"])]
    assert found == list(hosts.BINDING_KINDS)


def test_every_entry_point_has_a_width():
    assert set(hosts.WIDTH) == set(shaders.ENTRY_POINTS) == set(gpu.ENTRY_POINTS)


def test_a_file_that_is_not_the_manifests_is_refused():
    with pytest.raises(ValueError, match=r"noise\.spv hashes to .*, the manifest says"):
        hosts.check_hash("noise.spv", b"not the shipped bytes")


def test_every_shipped_file_hashes_to_its_manifest_entry():
    """The positive side of the refusal above: each file a host loads passes, so the refusal is not always on."""
    for language in ("spirv", "glsl"):
        for entry in shaders.ENTRY_POINTS if language == "glsl" else (None,):
            assert hosts.verified(language, entry)


def test_a_host_on_another_target_is_refused():
    with pytest.raises(hosts.HostTargetError, match="not on 'llvmpipe'"):
        hosts.check_target("glsl", "NVIDIA GeForce RTX 5090 (OpenGL 4.6)", "llvmpipe")


def test_a_host_on_its_target_passes_ignoring_case():
    hosts.check_target("glsl", "llvmpipe (LLVM 19.1.1, 256 bits) (OpenGL 4.5)", "LLVMpipe")


def test_with_no_target_named_the_host_is_not_checked():
    hosts.check_target("glsl", "anything", None)
    hosts.check_target("glsl", "anything", "")


def test_an_unknown_host_is_refused_naming_the_known_ones():
    with pytest.raises(ValueError, match="glsl, spirv-naga"):
        hosts.open_host("metal")


def test_the_sampler_packs_the_uniforms_and_runs_each_entry_point():
    host = FakeHost()
    params = NoiseParams(frequency=0.02, seed=7)
    s = hosts.HostSampler(params, host)
    xs = np.linspace(-1, 1, 5, dtype=np.float32)
    s.sample_points(xs, xs, xs, np.empty(5, np.float32))
    s.sample_points_2d(xs, xs, np.empty(5, np.float32))
    assert s.warp_points(xs, xs, xs).shape == (5, 3)
    assert s.warp_points_2d(xs, xs).shape == (5, 2)
    assert s.sample_grid((0, 0, 0), (2, 3, 1)).shape == (2, 3, 1)
    entries = [c[0] for c in host.calls]
    assert entries == ["sample_points_3d", "sample_points_2d", "warp_points_3d", "warp_points_2d", "sample_grid"]
    assert all(c[1] == gpu.pack_params(params) for c in host.calls)
    assert host.calls[-1][5] == gpu.pack_grid((0, 0, 0), (2, 3, 1), (1.0, 1.0, 1.0))
    assert [len(c[2]) for c in host.calls] == [3, 2, 3, 2, 0]


@pytest.mark.parametrize(
    "call",
    [
        lambda s, a, b: s.sample_points(a, b, a, np.empty(len(a), np.float32)),
        lambda s, a, b: s.sample_points_2d(a, b, np.empty(len(a), np.float32)),
        lambda s, a, b: s.sample_points(a, a, a, np.empty(len(b), np.float32)),
        lambda s, a, b: s.warp_points(a, b, a),
        lambda s, a, b: s.warp_points_2d(a, b),
    ],
    ids=["sample_points", "sample_points_2d", "out", "warp_points", "warp_points_2d"],
)
def test_a_short_axis_is_refused_before_any_dispatch(call):
    """A shader's robust access would clamp a short axis to its last value and answer, silently."""
    host = FakeHost()
    xs = np.linspace(-10, 10, 100, dtype=np.float32)
    with pytest.raises(ValueError, match="100"):
        call(hosts.HostSampler(NoiseParams(), host), xs, xs[:99])
    assert host.calls == []


def test_more_than_32_octaves_is_not_implemented_before_any_dispatch():
    with pytest.raises(NotImplementedError, match="octaves=33"):
        hosts.HostSampler(NoiseParams(octaves=33), FakeHost())


def test_no_points_dispatch_nothing():
    host = FakeHost()
    empty = np.empty(0, np.float32)
    assert len(hosts.HostSampler(NoiseParams(), host).sample_points(empty, empty, empty, empty)) == 0
    assert host.calls == []


def test_renderings_build_one_sampler_per_parameter_record():
    host = FakeHost()
    sample, warp, grid = hosts.renderings(host)
    xs = np.zeros(3, np.float32)
    p = NoiseParams()
    sample(p, xs, xs, None)
    sample(p, xs, xs, xs)
    warp(p, xs, xs, None)
    grid(p, (0, 0, 0), (1, 1, 1), (1.0, 1.0, 1.0))
    assert [c[0] for c in host.calls] == ["sample_points_2d", "sample_points_3d", "warp_points_2d", "sample_grid"]
```

- [x] **Step 2: run them and see them fail.**

Run: `uv run pytest apps/hog-noise-tools/tests/hosts/test_shared.py -n 0 -q`
Expected: collection fails with `ImportError: cannot import name 'hosts' from 'hog_noise_tools'`.

- [x] **Step 3: write the shared module.** Create `apps/hog-noise-tools/src/hog_noise_tools/hosts/__init__.py`:

```python
"""
HogNoise tools: the host harnesses. Each runs one emitted shader through one graphics API and hands its output to
``conformance.check``; this module holds what they share.
Package: hog_noise_tools.hosts

A host is written from ``hog_noise/shaders/README.md`` alone, never from ``hog_noise.gpu``'s ``_Gpu``, so a wrong
sentence in the README fails the proof (the CI proof's spec, *What gets built*). The constants below are the README's,
restated; ``test_shared`` holds them to the manifest. Each host module has ``open_host()``, which raises
`HostUnavailable` naming what is missing, and a host object with ``name``, ``target`` and ``run``.
"""

from __future__ import annotations

import importlib
import logging as _logging
import math
import os
from collections.abc import Callable, Sequence
from typing import Protocol

import numpy as np
from numpy.typing import NDArray

from hog_noise import NoiseParams, shaders
from hog_noise.gpu import MAX_OCTAVES, pack_grid, pack_params

_MODULE_NAME = "hog_noise_tools.hosts"
__version__ = "0.1.0"
__updated__ = "2026-11-23"
_LOGGER = _logging.getLogger(_MODULE_NAME)

#: A comma-separated list of hosts whose absence fails the tests instead of skipping them (CI's host legs).
REQUIRE_ENV = "HOG_NOISE_REQUIRE_HOST"
#: Part of what the host must run on, its ``target`` line, ignoring case; unset, the target is logged and not asserted.
TARGET_ENV = "HOG_NOISE_HOST_TARGET"
#: The hosts, by name, and the module that opens each (the spec's hosts table).
HOSTS = {"glsl": "hog_noise_tools.hosts.glsl", "spirv-naga": "hog_noise_tools.hosts.spirv_naga"}
#: The README's *The entry points*.
WORKGROUP = 64
MAX_GROUPS = 65535
#: The README's *The bindings*, in binding order: a uniform, read-only storage, or read-write storage.
BINDING_KINDS = ("uniform", "read", "read", "read", "read", "write", "uniform")
#: The README's *Output*: floats per point.
WIDTH = {"sample_points_3d": 1, "sample_points_2d": 1, "sample_grid": 1, "warp_points_3d": 3, "warp_points_2d": 2}

Sample = Callable[[NoiseParams, NDArray, NDArray, "NDArray | None"], NDArray]
Grid = Callable[[NoiseParams, Sequence[int], Sequence[int], Sequence[float]], NDArray]


class HostUnavailable(RuntimeError):
    """The host cannot run here: its library, its driver or its device is missing. The message names which."""


class HostTargetError(RuntimeError):
    """The host runs, but not on the target it was told to expect (the project ledger's P-22)."""


class Host(Protocol):
    """A host harness: what it runs on, and one dispatch."""

    name: str
    target: str

    def run(
        self,
        entry: str,
        params: bytes,
        axes: Sequence[NDArray[np.float32]],
        n: int,
        width: int,
        grid: bytes | None,
    ) -> NDArray[np.float32]: ...


def workgroups(n: int) -> tuple[int, int, int]:
    """The README's *Dispatch* for ``n`` points: along x, wrapping into y past 65,535."""
    groups = math.ceil(n / WORKGROUP)
    if groups <= MAX_GROUPS:
        return (groups, 1, 1)
    return (MAX_GROUPS, math.ceil(groups / MAX_GROUPS), 1)


def check_hash(name: str, data: bytes) -> None:
    """
    Refuse a file that is not the one the manifest records.

    :raises ValueError: Naming the file and both hashes.
    """
    record = shaders.manifest()["files"][name]
    found = shaders.sha256(data, text=record["text"])
    if found != record["sha256"]:
        raise ValueError(f"{name} hashes to {found[:12]}, the manifest says {record['sha256'][:12]}: run make shaders")


def verified(language: str, entry_point: str | None = None) -> str | bytes:
    """The shipped shader, read through ``hog_noise.shaders`` once its bytes hash to its manifest entry."""
    name = shaders.file_name(language, entry_point)
    check_hash(name, shaders.path(language, entry_point).read_bytes())
    return shaders.source(language, entry_point)


def check_target(host: str, found: str, expected: str | None) -> None:
    """
    Refuse a host running on anything but ``expected`` (part of its ``target`` line, ignoring case).

    :raises HostTargetError: Naming both. With ``expected`` empty or None the target is logged, not asserted.
    """
    if not expected:
        _LOGGER.info(f"{host}: runs on {found}; {TARGET_ENV} is unset, so the target is not asserted")
        return
    if expected.lower() not in found.lower():
        raise HostTargetError(f"{host} runs on {found!r}, not on {expected!r} ({TARGET_ENV})")
    _LOGGER.info(f"{host}: runs on {found}, the target {expected!r}")


_OPEN: dict[str, Host] = {}


def open_host(name: str, target: str | None = None) -> Host:
    """
    The host ``name``, opened once per process, after its target is checked.

    :param target: What it must run on; None reads `TARGET_ENV`.
    :raises ValueError: An unknown host, naming the known ones.
    :raises HostUnavailable: Naming what is missing here.
    :raises HostTargetError: When it runs on another target.
    """
    if name not in HOSTS:
        raise ValueError(f"unknown host {name!r}; known: {', '.join(sorted(HOSTS))}")
    if name not in _OPEN:
        _OPEN[name] = importlib.import_module(HOSTS[name]).open_host()
    host = _OPEN[name]
    check_target(name, host.target, os.environ.get(TARGET_ENV) if target is None else target)
    return host


def _lengths(axes: Sequence[NDArray], out: NDArray | None = None) -> int:
    """
    The number of points: every axis's length, and ``out``'s where given, which must all be one.

    :raises ValueError: Naming the lengths, before any dispatch.
    """
    lengths = [len(a) for a in axes]
    if len(set(lengths)) > 1:
        raise ValueError(f"the axes have lengths {lengths}; every axis needs one per point")
    if out is not None and len(out) != lengths[0]:
        raise ValueError(f"out has {len(out)} values for {lengths[0]} points")
    return lengths[0]


class HostSampler:
    """The calls every sampler has, each one dispatch on a host."""

    def __init__(self, params: NoiseParams, host: Host) -> None:
        for field in ("octaves", "perturb_octaves"):
            value = getattr(params, field)
            if value > MAX_OCTAVES:
                raise NotImplementedError(f"{field}={value} is past the emitted shaders' cap of {MAX_OCTAVES}")
        self.params, self.host = params, host
        self._params = pack_params(params)

    def _run(self, entry: str, axes: Sequence[NDArray], n: int, grid: bytes | None = None) -> NDArray[np.float32]:
        if n == 0:
            return np.empty(0, np.float32)
        contiguous = [np.ascontiguousarray(a, dtype=np.float32) for a in axes]
        return self.host.run(entry, self._params, contiguous, n, WIDTH[entry], grid)

    def sample_points(self, xs: NDArray, ys: NDArray, zs: NDArray, out: NDArray[np.float32]) -> NDArray[np.float32]:
        """3D noise at each point into ``out``. :raises ValueError: Axes, or ``out``, of unequal length."""
        out[...] = self._run("sample_points_3d", (xs, ys, zs), _lengths((xs, ys, zs), out))
        return out

    def sample_points_2d(self, xs: NDArray, ys: NDArray, out: NDArray[np.float32]) -> NDArray[np.float32]:
        """2D noise at each point into ``out``. :raises ValueError: Axes, or ``out``, of unequal length."""
        out[...] = self._run("sample_points_2d", (xs, ys), _lengths((xs, ys), out))
        return out

    def sample_grid(
        self, start: Sequence[int], shape: Sequence[int], scales: Sequence[float] = (1.0, 1.0, 1.0)
    ) -> NDArray[np.float32]:
        """The grid, its cells x-major (the README's *Output*), reshaped to ``shape``."""
        shape = tuple(int(n) for n in shape)
        grid = pack_grid(start, shape, scales)
        return self._run("sample_grid", (), math.prod(shape), grid).reshape(shape)

    def warp_points(self, xs: NDArray, ys: NDArray, zs: NDArray) -> NDArray[np.float32]:
        """The warped coordinates, ``(N, 3)``. :raises ValueError: Axes of unequal length."""
        n = _lengths((xs, ys, zs))
        return self._run("warp_points_3d", (xs, ys, zs), n).reshape(n, 3)

    def warp_points_2d(self, xs: NDArray, ys: NDArray) -> NDArray[np.float32]:
        """The warped coordinates, ``(N, 2)``. :raises ValueError: Axes of unequal length."""
        n = _lengths((xs, ys))
        return self._run("warp_points_2d", (xs, ys), n).reshape(n, 2)


def renderings(host: Host) -> tuple[Sample, Sample, Grid]:
    """``sample``, ``warp`` and ``grid`` for ``conformance.check``, one `HostSampler` per distinct parameter record."""
    built: dict[NoiseParams, HostSampler] = {}

    def sampler_for(params: NoiseParams) -> HostSampler:
        if params not in built:
            built[params] = HostSampler(params, host)
        return built[params]

    def sample(params: NoiseParams, xs: NDArray, ys: NDArray, zs: NDArray | None) -> NDArray:
        s, out = sampler_for(params), np.empty(len(xs), np.float32)
        return s.sample_points_2d(xs, ys, out) if zs is None else s.sample_points(xs, ys, zs, out)

    def warp(params: NoiseParams, xs: NDArray, ys: NDArray, zs: NDArray | None) -> NDArray:
        s = sampler_for(params)
        return s.warp_points_2d(xs, ys) if zs is None else s.warp_points(xs, ys, zs)

    def grid(params: NoiseParams, start: Sequence[int], shape: Sequence[int], scales: Sequence[float]) -> NDArray:
        return sampler_for(params).sample_grid(start, shape, scales)

    return sample, warp, grid


if __name__ == "__main__":
    _logging.basicConfig(level=_logging.INFO)
    for host_name in sorted(HOSTS):
        try:
            print(f"{host_name}: {open_host(host_name).target}")
        except (HostUnavailable, HostTargetError) as e:
            print(f"{host_name}: {e}")
```

- [x] **Step 4: run them and see them pass.**

Run: `uv run pytest apps/hog-noise-tools/tests/hosts/test_shared.py -n 0 -q`
Expected: all pass. None needs a host module: `open_host` refuses an unknown name before it imports one.

- [x] **Step 5: prove the hash refusal is an instrument.** In a scratch copy of the check, make `check_hash` compare
  `found[:0]` with `record["sha256"][:0]` (always equal); `test_a_file_that_is_not_the_manifests_is_refused` must fail.
  Restore it. Do the same for `check_target`'s `not in`, made `in`: `test_a_host_on_another_target_is_refused` must fail.
  Write each mutation as a script file (P-14), run it, and record both results for the pull request's *Verified*.

- [x] **Step 6: commit.**

```bash
git add apps/hog-noise-tools/src/hog_noise_tools/hosts/__init__.py apps/hog-noise-tools/tests/hosts/test_shared.py
git commit -s -F <message file>   # "CI proof (a), task 2: the host harness's shared code"
```

### Task 3: the host tests, before any host exists

**Files:**
- Create: `apps/hog-noise-tools/tests/hosts/test_hosts.py`

- [x] **Step 1: write them.** Create `apps/hog-noise-tools/tests/hosts/test_hosts.py`:

```python
"""
HogNoise tools: every host harness against the vectors, judged by the wgpu rung's tolerance file, with its controls.
Each host runs where its library and device exist; it skips with the reason elsewhere, and fails instead of skipping
when HOG_NOISE_REQUIRE_HOST names it (CI's host legs), so a leg that loses its host cannot go green.
Package: apps/hog-noise-tools/tests/hosts/test_hosts
"""

import os

import numpy as np
import pytest

from hog_noise import FractalType, NoiseParams, conformance
from hog_noise.conformance import Bound
from hog_noise_tools import hosts
from hog_noise_tools.repo import VECTORS

REQUIRED = {h.strip() for h in os.environ.get(hosts.REQUIRE_ENV, "").split(",") if h.strip()}
TOLERANCE = VECTORS / "tolerance" / "wgpu.json"


def test_every_required_host_is_known():
    """A misspelt name in HOG_NOISE_REQUIRE_HOST would require nothing, and the leg would go green on skips."""
    assert REQUIRED <= set(hosts.HOSTS), sorted(REQUIRED - set(hosts.HOSTS))


@pytest.fixture(scope="module", params=sorted(hosts.HOSTS))
def host(request):
    """The host, or a skip (a failure when HOG_NOISE_REQUIRE_HOST names it) naming why it is not here."""
    try:
        return hosts.open_host(request.param)
    except hosts.HostUnavailable as e:
        if request.param in REQUIRED:
            pytest.fail(f"{hosts.REQUIRE_ENV} names {request.param}, but {e}")
        pytest.skip(f"{request.param}: {e}")


@pytest.fixture(scope="module")
def judged():
    vectors = conformance.load(VECTORS)
    return vectors, conformance.Tolerance.load(TOLERANCE, vectors)


def test_every_hog_case_passes_within_the_wgpu_tolerance(host, judged):
    """The spec's acceptance: every hog case, every entry point, nothing unsupported, the file unmodified."""
    vectors, tolerance = judged
    sample, warp, grid = hosts.renderings(host)
    report = conformance.check(sample, vectors, warp=warp, grid=grid, tolerance=tolerance)
    print(f"{host.name}: {host.target}")
    assert report.ok and report.complete, report.table()


def test_a_seed_off_by_one_fails(host, judged):
    vectors, tolerance = judged
    sample, _, _ = hosts.renderings(host)

    def off(params, xs, ys, zs):
        return sample(params.replace(seed=params.seed + 1), xs, ys, zs)

    assert not conformance.check(off, vectors, tolerance=tolerance, select="hog/fnl/simplex_fbm/*").ok


def test_a_rule_at_0_9_of_its_worst_fails(host, judged):
    """The rule is tight enough to matter on this host. A host with no drift on the feature cannot show it: say so."""
    vectors, tolerance = judged
    sample, _, _ = hosts.renderings(host)
    feature = "fnl/simplex_fbm"
    unit = Bound(1.0, coordinate_scaled=True)
    worst = 0.0
    for case in (c for c in vectors.cases if c.id.startswith(f"hog/{feature}/")):
        ps = vectors.point_sets[case.point_set]
        ours = sample(case.params, ps.axes[0], ps.axes[1], ps.axes[2] if ps.dims == 3 else None)
        diff = np.abs(np.asarray(ours, np.float64) - case.values.astype(np.float64))
        worst = max(worst, float((diff / unit.per_point(case.params.frequency, ps.axes)).max()))
    assert worst > 0.0, f"{host.name} has no drift on {feature}: choose another feature for this control"
    rules = dict(tolerance.rules)
    rules[(feature, None)] = dict(rules[(feature, None)], bound={"scale": 0.9 * worst, "coordinate_scaled": True})
    tight = conformance.Tolerance(tolerance.rendering, tolerance.range, rules)
    assert not conformance.check(sample, vectors, tolerance=tight, select=f"hog/{feature}/*").ok


def test_a_host_told_another_target_refuses(host):
    """P-22's control: the target check fails when the host is told to expect an adapter it is not on."""
    with pytest.raises(hosts.HostTargetError, match="no adapter is called this"):
        hosts.open_host(host.name, target="no adapter is called this")


def test_a_power_of_two_grid_equals_its_points_bit_for_bit(host):
    """sample_grid computes its coordinates in the shader; at scale 1 they are exact, so grid and points agree."""
    from hog_noise.samplers import grid_points

    s = hosts.HostSampler(NoiseParams(frequency=0.01), host)
    start, shape = (-64, -64, 1), (128, 128, 1)
    xs, ys, zs = grid_points(start, shape)
    points = s.sample_points(xs, ys, zs, np.empty(len(xs), np.float32))
    assert np.array_equal(s.sample_grid(start, shape).ravel(), points)


def test_a_dispatch_past_65535_workgroups_reaches_its_last_points(host, judged):
    """The README's y stride: the last 64 points, alone in the second row of workgroups, are written and right."""
    from hog_noise import NumpySampler

    vectors, tolerance = judged
    case = next(c for c in vectors.cases if c.id.startswith("hog/fnl/value_none/"))
    params, rule = case.params, tolerance.rule_for(case)
    i = np.arange(hosts.MAX_GROUPS * hosts.WORKGROUP + hosts.WORKGROUP)
    xs, ys, zs = (((i % m) - m // 2).astype(np.float32) for m in (4093, 4091, 4099))
    assert hosts.workgroups(len(xs)) == (65535, 2, 1)
    ours = hosts.HostSampler(params, host).sample_points(xs, ys, zs, np.empty(len(xs), np.float32))[-64:]
    tail = tuple(a[-64:] for a in (xs, ys, zs))
    numpy = NumpySampler(params).sample_points(*tail, np.empty(64, np.float32))
    allowed = Bound(**rule["bound"]).per_point(params.frequency, tail)
    diff = np.abs(ours.astype(np.float64) - numpy.astype(np.float64))
    assert rule["rule"] == "continuous" and np.all(diff <= allowed), diff.max()


def test_spirv_naga_is_the_wgpu_rung_bit_for_bit(host):
    """
    The spec's first fact, as a test: naga reads the shipped SPIR-V back into the IR it made the WGSL from, so on one
    device the two agree exactly, for every entry point. A seed off by one does not, so the comparison can fail.
    """
    if host.name != "spirv-naga":
        pytest.skip("the bit-for-bit claim is spirv-naga's alone: another compiler differs by its rounding")
    from hog_noise import gpu

    rng = np.random.default_rng(20261122)
    xs, ys, zs = (rng.uniform(-4096, 4096, 4096).astype(np.float32) for _ in range(3))
    for params in (NoiseParams(frequency=0.01), NoiseParams(frequency=0.01, octaves=4, fractal_type=FractalType.FBM)):
        ours, theirs = hosts.HostSampler(params, host), gpu.GpuSampler(params)
        off = hosts.HostSampler(params.replace(seed=params.seed + 1), host)
        out = lambda: np.empty(len(xs), np.float32)  # noqa: E731
        pairs = [
            (ours.sample_points(xs, ys, zs, out()), theirs.sample_points(xs, ys, zs, out())),
            (ours.sample_points_2d(xs, ys, out()), theirs.sample_points_2d(xs, ys, out())),
            (ours.warp_points(xs, ys, zs), theirs.warp_points(xs, ys, zs)),
            (ours.warp_points_2d(xs, ys), theirs.warp_points_2d(xs, ys)),
            (ours.sample_grid((-8, -8, 0), (16, 16, 1)), theirs.sample_grid((-8, -8, 0), (16, 16, 1))),
        ]
        for a, b in pairs:
            assert np.array_equal(a, b)
        assert not np.array_equal(off.sample_points(xs, ys, zs, out()), pairs[0][1])


def test_a_gl_host_builds_after_wgpu_has_enumerated_its_adapters():
    """
    The spec's third fact, as a test, in its order: a GL context exists, wgpu then enumerates its adapters (its OpenGL
    back end among them, which can leave its own context current), and only then does the GL host build its programs.
    They build and run because the host makes its context current first. A context of its own, not the shared one, so
    the order is this test's and not the fixtures'.
    """
    from hog_noise_tools.hosts import glsl

    try:
        import wgpu
    except ImportError as e:
        if "glsl" in REQUIRED:  # the glsl job installs wgpu for this test alone: losing it must not go green
            pytest.fail(f"{hosts.REQUIRE_ENV} names glsl, and this test needs wgpu beside it: {e}")
        pytest.skip(f"needs wgpu: {e}")
    try:
        ctx = glsl.context()
    except hosts.HostUnavailable as e:
        if "glsl" in REQUIRED:
            pytest.fail(f"{hosts.REQUIRE_ENV} names glsl, but {e}")
        pytest.skip(f"glsl: {e}")
    wgpu.gpu.enumerate_adapters_sync()
    host = glsl.Glsl(ctx)
    xs = np.linspace(-100, 100, 64, dtype=np.float32)
    values = hosts.HostSampler(NoiseParams(frequency=0.01), host).sample_points_2d(xs, xs, np.empty(64, np.float32))
    assert np.isfinite(values).all() and values.std() > 0
```

- [x] **Step 2: run them with no host present.**

Run: `uv run pytest apps/hog-noise-tools/tests/hosts/test_hosts.py -n 0 -q -rs`
Expected: `test_every_required_host_is_known` passes; every test using the `host` fixture **errors** in it with
`ModuleNotFoundError: No module named 'hog_noise_tools.hosts.glsl'` (or `...spirv_naga'`), because `open_host` imports
the module before the host can say what it lacks. `test_a_gl_host_builds_after_wgpu_has_enumerated_its_adapters`
**fails** with the same error, from its own import of `glsl`. That is the failing state Tasks 4 and 5 fix: a missing
module is a bug in this app, never a skip. (Built 2026-11-23: 1 passed, 1 failed, 14 errors, each error and the failure
a `ModuleNotFoundError` for one of the two modules.)

- [x] **Step 3: commit.**

```bash
git add apps/hog-noise-tools/tests/hosts/test_hosts.py
git commit -s -F <message file>   # "CI proof (a), task 3: every host against the vectors, and its controls"
```

### Task 4: `spirv-naga`

**Files:**
- Create: `apps/hog-noise-tools/src/hog_noise_tools/hosts/spirv_naga.py`

- [x] **Step 1: write the host.** Create `apps/hog-noise-tools/src/hog_noise_tools/hosts/spirv_naga.py`:

```python
"""
HogNoise tools: the spirv-naga host. ``noise.spv`` through wgpu's SPIR-V front end, bound as the shaders README says.
Package: hog_noise_tools.hosts.spirv_naga

wgpu 0.33 has no SPIR-V passthrough, so naga reads the shipped bytes back into its own IR and wgpu translates that for
the device (the CI proof's spec, *Facts*): this proves the file is naga-readable and binds as documented, not that a
Vulkan driver consumes it; the spirv-vulkan host does that. The device is ``hog_noise.gpu.device()``, the process's
one, so ``HOG_NOISE_WGPU_ADAPTER`` and ``WGPU_BACKEND_TYPE`` choose it as they choose the rung's.
"""

from __future__ import annotations

import logging as _logging
from collections.abc import Sequence
from typing import Any

import numpy as np
from numpy.typing import NDArray

from hog_noise import shaders
from hog_noise_tools.hosts import BINDING_KINDS, HostUnavailable, verified, workgroups

_MODULE_NAME = "hog_noise_tools.hosts.spirv_naga"
__version__ = "0.1.0"
__updated__ = "2026-11-23"
_LOGGER = _logging.getLogger(_MODULE_NAME)


def open_host() -> SpirvNaga:
    """
    The host on the process's wgpu device.

    :raises HostUnavailable: wgpu missing, or no adapter, with the rung's own message.
    """
    from hog_noise import gpu

    try:
        dev = gpu.device()
    except RuntimeError as e:
        raise HostUnavailable(str(e)) from e
    return SpirvNaga(dev, gpu.adapter_info())


class SpirvNaga:
    """``noise.spv``'s five pipelines on one device, with the buffers that never change."""

    name = "spirv-naga"

    def __init__(self, dev: Any, info: dict[str, object]) -> None:
        import wgpu

        self.wgpu, self.device = wgpu, dev
        self.target = f"{info['device']} ({info['backend_type']})"
        module = dev.create_shader_module(code=verified("spirv"))
        kinds = {
            "uniform": wgpu.BufferBindingType.uniform,
            "read": wgpu.BufferBindingType.read_only_storage,
            "write": wgpu.BufferBindingType.storage,
        }
        layout = dev.create_bind_group_layout(
            entries=[
                {"binding": i, "visibility": wgpu.ShaderStage.COMPUTE, "buffer": {"type": kinds[k]}}
                for i, k in enumerate(BINDING_KINDS)
            ]
        )
        self.layout = layout
        pipeline_layout = dev.create_pipeline_layout(bind_group_layouts=[layout])
        self.pipelines = {
            entry: dev.create_compute_pipeline(layout=pipeline_layout, compute={"module": module, "entry_point": entry})
            for entry in shaders.ENTRY_POINTS
        }
        self.tables = self._buffer(shaders.tables(), wgpu.BufferUsage.STORAGE)
        self.unused = self._buffer(bytes(4), wgpu.BufferUsage.STORAGE)  # the README: a one-float buffer
        self.no_grid = self._buffer(bytes(48), wgpu.BufferUsage.UNIFORM)  # the README: 48 zero bytes
        _LOGGER.info(f"spirv-naga: {len(self.pipelines)} pipelines from noise.spv on {self.target}")

    def _buffer(self, data: bytes, usage: Any) -> Any:
        return self.device.create_buffer_with_data(data=data, usage=usage)

    def run(
        self,
        entry: str,
        params: bytes,
        axes: Sequence[NDArray[np.float32]],
        n: int,
        width: int,
        grid: bytes | None,
    ) -> NDArray[np.float32]:
        """Dispatch ``entry`` over ``n`` points and read back ``n * width`` floats."""
        usage = self.wgpu.BufferUsage
        coords = [self._buffer(a.tobytes(), usage.STORAGE) for a in axes] + [self.unused] * (3 - len(axes))
        out = self.device.create_buffer(size=n * width * 4, usage=usage.STORAGE | usage.COPY_SRC)
        uniform_grid = self._buffer(grid, usage.UNIFORM) if grid is not None else self.no_grid
        buffers = [self._buffer(params, usage.UNIFORM), self.tables, *coords, out, uniform_grid]
        group = self.device.create_bind_group(
            layout=self.layout,
            entries=[
                {"binding": i, "resource": {"buffer": b, "offset": 0, "size": b.size}} for i, b in enumerate(buffers)
            ],
        )
        encoder = self.device.create_command_encoder()
        compute = encoder.begin_compute_pass()
        compute.set_pipeline(self.pipelines[entry])
        compute.set_bind_group(0, group)
        compute.dispatch_workgroups(*workgroups(n))
        compute.end()
        self.device.queue.submit([encoder.finish()])
        return np.frombuffer(self.device.queue.read_buffer(out), dtype=np.float32).copy()


if __name__ == "__main__":
    _logging.basicConfig(level=_logging.INFO)
    from hog_noise import NoiseParams
    from hog_noise_tools.hosts import HostSampler

    host = open_host()
    xs = np.linspace(-100, 100, 5, dtype=np.float32)
    s = HostSampler(NoiseParams(frequency=0.01), host)
    print(host.target, np.round(s.sample_points(xs, xs, np.zeros(5, np.float32), np.empty(5, np.float32)), 5))
```

- [x] **Step 2: run the host's tests on this machine.**

Run: `uv run --group gpu pytest apps/hog-noise-tools/tests/hosts -n 0 -q -rs -k "spirv and not glsl"`
Expected: every `spirv-naga` test passes, `test_spirv_naga_is_the_wgpu_rung_bit_for_bit` included. `and not glsl`
is needed: `-k spirv` alone also selects `test_spirv_naga_is_the_wgpu_rung_bit_for_bit[glsl]`, whose fixture imports
`glsl.py` before Task 5 has written it, and errors. Note the adapter
`test_every_hog_case_passes_within_the_wgpu_tolerance` prints, for the pull request's *Verified*.

- [x] **Step 3: prove the stride test is an instrument.** In a scratch copy, make `workgroups` return
  `(MAX_GROUPS, 1, 1)` past 65,535 groups (no y row). `test_a_dispatch_past_65535_workgroups_reaches_its_last_points`
  must fail on `spirv-naga`; restore it. Record the result.

- [x] **Step 4: run it on a second back end.** `WGPU_BACKEND_TYPE=D3D12 HOG_NOISE_HOST_TARGET=D3D12 uv run --group gpu
  pytest apps/hog-noise-tools/tests/hosts -n 0 -q -k "spirv and not glsl"`, then the same with `Vulkan`. Both pass; record each target
  line.

- [x] **Step 5: commit.**

```bash
git add apps/hog-noise-tools/src/hog_noise_tools/hosts/spirv_naga.py
git commit -s -F <message file>   # "CI proof (a), task 4: the spirv-naga host"
```

### Task 5: `glsl`

**Files:**
- Create: `apps/hog-noise-tools/src/hog_noise_tools/hosts/glsl.py`

- [x] **Step 1: write the host.** Create `apps/hog-noise-tools/src/hog_noise_tools/hosts/glsl.py`:

```python
"""
HogNoise tools: the glsl host. The five ``noise.<entry_point>.comp`` files in moderngl, each block bound by the name
``manifest.json`` records for that entry point.
Package: hog_noise_tools.hosts.glsl

naga writes no ``binding =`` qualifier, so a GLSL host binds by block name, and the names differ per entry point (the
shaders README, *GLSL binds by name*). Every call makes this host's context current first: in a process that has used
wgpu, wgpu's OpenGL back end can leave its own context current, and the next program fails to build (the CI proof's
spec, *Facts*). ``HOG_NOISE_GL_BACKEND`` names moderngl's context back end; unset, it is ``egl`` on Linux (headless CI)
and the platform's default elsewhere.
"""

from __future__ import annotations

import logging as _logging
import os
import sys
from collections.abc import Sequence
from typing import Any

import numpy as np
from numpy.typing import NDArray

from hog_noise import shaders
from hog_noise_tools.hosts import BINDING_KINDS, HostUnavailable, verified, workgroups

_MODULE_NAME = "hog_noise_tools.hosts.glsl"
__version__ = "0.1.0"
__updated__ = "2026-11-23"
_LOGGER = _logging.getLogger(_MODULE_NAME)

BACKEND_ENV = "HOG_NOISE_GL_BACKEND"


def _backend() -> str | None:
    """moderngl's context back end: `BACKEND_ENV`'s value (empty means the default), else egl on Linux."""
    if BACKEND_ENV in os.environ:
        return os.environ[BACKEND_ENV] or None
    return "egl" if sys.platform.startswith("linux") else None


def context() -> Any:
    """
    A standalone OpenGL 4.3 context.

    :raises HostUnavailable: moderngl missing, or no OpenGL 4.3 context here, naming the back end tried.
    """
    try:
        import moderngl
    except ImportError as e:
        raise HostUnavailable("moderngl is not installed: uv sync --group hosts") from e
    backend = _backend()
    try:
        return moderngl.create_standalone_context(require=430, **({"backend": backend} if backend else {}))
    except Exception as e:  # moderngl's Error, or glcontext's own when no driver or display exists
        raise HostUnavailable(
            f"no OpenGL 4.3 context ({backend or 'default'} back end): {type(e).__name__}: {e}"
        ) from e


def open_host() -> Glsl:
    """The host on a context of its own. :raises HostUnavailable: As `context`."""
    return Glsl(context())


class Glsl:
    """One compute program per entry point, each block bound to its binding, and the tables' buffer."""

    name = "glsl"

    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx
        self.target = f"{ctx.info['GL_RENDERER']} (OpenGL {ctx.info['GL_VERSION']})"
        bindings = shaders.manifest()["bindings"]
        #: per entry point, the bindings it reads: those with a block for it
        self.reads: dict[str, list[int]] = {}
        self.programs: dict[str, Any] = {}
        with ctx:
            for entry in shaders.ENTRY_POINTS:
                program = ctx.compute_shader(verified("glsl", entry))
                self.reads[entry] = []
                for b in bindings:
                    block = b["glsl"]["blocks"].get(entry)
                    if block is not None:
                        program[block].binding = b["binding"]
                        self.reads[entry].append(b["binding"])
                self.programs[entry] = program
            self.tables = ctx.buffer(shaders.tables())
        _LOGGER.info(f"glsl: {len(self.programs)} programs on {self.target}")

    def run(
        self,
        entry: str,
        params: bytes,
        axes: Sequence[NDArray[np.float32]],
        n: int,
        width: int,
        grid: bytes | None,
    ) -> NDArray[np.float32]:
        """Dispatch ``entry`` over ``n`` points and read back ``n * width`` floats."""
        ctx = self.ctx
        with ctx:
            made = {0: ctx.buffer(params), 5: ctx.buffer(reserve=n * width * 4)}
            made.update({2 + i: ctx.buffer(a.tobytes()) for i, a in enumerate(axes)})
            if grid is not None:
                made[6] = ctx.buffer(grid)
            buffers = {1: self.tables, **made}
            for binding in self.reads[entry]:
                if BINDING_KINDS[binding] == "uniform":
                    buffers[binding].bind_to_uniform_block(binding)
                else:
                    buffers[binding].bind_to_storage_buffer(binding)
            self.programs[entry].run(*workgroups(n))
            ctx.finish()
            values = np.frombuffer(made[5].read(), dtype=np.float32).copy()
            for buffer in made.values():
                buffer.release()
        return values


if __name__ == "__main__":
    _logging.basicConfig(level=_logging.INFO)
    from hog_noise import NoiseParams
    from hog_noise_tools.hosts import HostSampler

    host = open_host()
    xs = np.linspace(-100, 100, 5, dtype=np.float32)
    s = HostSampler(NoiseParams(frequency=0.01), host)
    print(host.target, np.round(s.sample_points(xs, xs, np.zeros(5, np.float32), np.empty(5, np.float32)), 5))
```

- [x] **Step 2: run the host's tests on this machine.**

Run: `uv run --group hosts pytest apps/hog-noise-tools/tests/hosts -n 0 -q -rs -k glsl`
Expected: every `glsl` test passes on the 5090's OpenGL (the spec measured 7.75e-7 and 1.73e-6 on two entry points;
the tolerance file judges all five). If a rule fails, stop: it is a finding for the owner, reported with the report's
table, and the rule is not touched.

- [x] **Step 3: run both hosts in one process.** `uv run --group gpu --group hosts pytest apps/hog-noise-tools/tests/hosts
  -n 0 -q`. Expected: everything passes, `test_a_gl_host_builds_after_wgpu_has_enumerated_its_adapters` included.

- [x] **Step 4: prove the two instruments.** In scratch copies, one at a time, each restored after:
  - bind binding 2 (x) to binding 3's slot in `run`: `test_every_hog_case_passes_within_the_wgpu_tolerance[glsl]` must
    fail;
  - replace both `with ctx:` in `glsl.py` with `if True:`:
    `test_a_gl_host_builds_after_wgpu_has_enumerated_its_adapters` must fail with `cannot create program`, as it did in
    the plan's trial (*Facts*). On a driver where it passes, the fact does not reproduce: record that, keep the
    `with ctx:`, and say in the pull request that the test proves nothing there and why.

  Record each result for *Verified*.

- [x] **Step 5: commit.**

```bash
git add apps/hog-noise-tools/src/hog_noise_tools/hosts/glsl.py
git commit -s -F <message file>   # "CI proof (a), task 5: the glsl host"
```

### Task 6: CI

**Files:**
- Modify: `.github/workflows/hosts.yml`, `.github/workflows/tests.yml`

- [x] **Step 1: the glsl job runs its tests.** Append to the `glsl` job in `hosts.yml`, after *Context* (keep Task 1's
  fallback if it was taken):

```yaml
      - name: Test
        env:
          # fails instead of skipping when the host is missing, and unless it runs on llvmpipe
          HOG_NOISE_REQUIRE_HOST: glsl
          HOG_NOISE_HOST_TARGET: llvmpipe
        run: pytest apps/hog-noise-tools/tests/hosts
```

- [x] **Step 2: spirv-naga on the three GPU legs.** In `tests.yml`'s *Test* step `env`, add:

```yaml
          # spirv-naga runs where the wgpu rung runs: required on the GPU legs, on the leg's pinned back end
          HOG_NOISE_REQUIRE_HOST: ${{ matrix.gpu && 'spirv-naga' || '' }}
          HOG_NOISE_HOST_TARGET: ${{ matrix.backend }}
```

- [x] **Step 3: commit, push, read CI.**

```bash
git add .github/workflows/hosts.yml .github/workflows/tests.yml
git commit -s -F <message file>   # "CI proof (a), task 6: glsl on llvmpipe, spirv-naga on every GPU leg"
git push
gh pr checks <n> --watch
```

Expected: every leg green. In the logs, the `glsl` job's *Test* prints `glsl: llvmpipe ...`, and each GPU leg prints
`spirv-naga: ... (D3D12)`, `(Vulkan)` or `(Metal)`. A host failing a rule on a software adapter is a finding for the
owner, as in Task 5. The `glsl` job is the only one with moderngl and wgpu together. Read its test list for
`test_a_gl_host_builds_after_wgpu_has_enumerated_its_adapters` passing, not skipped. `spirv-naga` is not required
there: with no Vulkan driver installed it skips or, should wgpu find llvmpipe through OpenGL, runs held to the same
target. Either result is recorded.

- [x] **Step 4: prove each leg requires its host.** On a scratch commit pushed to the draft, set the `glsl` job's
  `HOG_NOISE_HOST_TARGET` to `not-llvmpipe`; that job must fail on `HostTargetError`. Revert it with a new commit, never
  a force-push. Record the run's link.

### Task 7: the documents

**Files:**
- Modify: `packages/python/hog-noise/src/hog_noise/shaders/README.md`, `README.md`, `apps/hog-noise-tools/README.md`,
  `Docs/standards/testing-project.md`, `Docs/glossary.md`

- [x] **Step 1: the shaders README.** Replace *What is proven, and what is not* with:

```markdown
## What is proven, and what is not

Proven on every push: each file is what the pinned naga writes from the current `noise.wgsl`, and each compiles or
validates in its own language's tools. Run by a host written from this page alone, and held to the
[reference vectors](https://github.com/HogJonny-AMZN/HogNoise/tree/main/vectors) within the wgpu rung's tolerance
(`apps/hog-noise-tools`, `hog_noise_tools.hosts`):

| File | Host | Adapter, on every push |
| --- | --- | --- |
| `noise.spv` | wgpu's SPIR-V front end (naga reads it back; no driver consumes it) | WARP (D3D12), llvmpipe (Vulkan), Apple's paravirtual GPU (Metal) |
| `noise.<entry_point>.comp` | moderngl, OpenGL 4.3 | Mesa llvmpipe, through EGL |

Not yet run: `noise.hlsl` (D3D11 and D3D12 on WARP) and `noise.spv` read by a Vulkan driver (lavapipe), each its own
pull request.
```

And add to *GLSL binds by name*: "A GL host in a process that also uses `wgpu` makes its own context current before each
call: wgpu's OpenGL back end can leave its context current, and the next program then fails to build."

- [x] **Step 2: the top README.** In *The same shader in another host*, replace the sentence saying no host has run the
  files with: "`noise.spv` and the GLSL files run on every push, in hosts written from the shaders README alone, and
  pass every hog case within the wgpu rung's tolerance: the SPIR-V through wgpu on WARP, llvmpipe and Metal, the GLSL in
  OpenGL on llvmpipe. The HLSL compiles and has not run yet." (Read the section first and keep its other sentences.)

- [x] **Step 3: the app README** gains a *Hosts* section: what `hog_noise_tools.hosts` is, the two hosts, how to run
  them (`uv run --group gpu --group hosts pytest apps/hog-noise-tools/tests/hosts`), and the three variables
  (`HOG_NOISE_REQUIRE_HOST`, `HOG_NOISE_HOST_TARGET`, `HOG_NOISE_GL_BACKEND`).

- [x] **Step 4: testing-project.md.** Beside `HOG_NOISE_REQUIRE_GPU=1`, add `HOG_NOISE_REQUIRE_HOST` (a comma-separated
  list of hosts whose absence fails) and `HOG_NOISE_HOST_TARGET` (part of the adapter or renderer a host must run on), and
  name `hosts.yml`'s `glsl` job beside the three GPU legs.

- [x] **Step 5: the glossary.** In *Host harness*, replace the sentence `Proposed in [the CI proof's spec](superpowers/specs/2026-11-22-emitted-shaders-ci-proof.md).`
  with `Built in hog_noise_tools.hosts (spirv-naga, glsl); [the CI proof's spec](superpowers/specs/2026-11-22-emitted-shaders-ci-proof.md) lists the rest.`

- [x] **Step 6: run the docs check and commit.**

Run: `uv run python tools/check_docs.py`
Expected: `no drift`.

```bash
git add packages/python/hog-noise/src/hog_noise/shaders/README.md README.md apps/hog-noise-tools/README.md Docs/standards/testing-project.md Docs/glossary.md
git commit -s -F <message file>   # "CI proof (a), task 7: the claims move from compiles to runs"
```

### Task 8: the board, the handoff, the journal

- [x] **Step 1: the row.** `2026-11-18-emitted-shaders-run-against-the-vectors.md`: `State` becomes `Landed in PR #<n>`
  with the hosts and adapters, the plan's link and the date. The `waits-on` check fails once this row is done, so in the
  same commit [the fresh-sample bounds](../../plan/board/2026-11-21-gpu-bounds-from-a-large-fresh-sample.md) decides
  again: remove its link to this row (that wait has landed) and keep its link to the warp rules. [The HLSL row](../../plan/board/2026-11-23-the-emitted-hlsl-runs-on-warp.md)
  waits on this one too: remove its `Waits on` line and leave it on *Next*, ready to be pulled. The Vulkan row waits on
  the HLSL row, not on this one, and is not touched.
- [x] **Step 2: the plan's checkboxes**, each ticked with its verification (P-10: every number from a command).
- [x] **Step 3: the handoff** (*In flight*: the CI proof's first pull request landed; the HLSL plan next) and a new
  journal file for the day.
- [x] **Step 4:** run the gate, `make check`, unpiped, and read its verdict. Then commit and push.

### Task 9: review, then out of draft

- [ ] **Step 1:** run the `local-review` skill on the diff and paste its table into the pull request's *Review*.
- [ ] **Step 2:** fix every finding below 7, or say why not, then re-run the gate.
- [ ] **Step 3:** fill the pull request body from the template: *Decisions* (this plan's and any taken on the way),
  *Verified* (each mutation's result, each target line, the CI run), *Not covered* (HLSL, Vulkan).
- [ ] **Step 4:** `gh pr ready <n>`, read CI, and assess the automated review when it arrives (the `review-and-pr`
  skill). The owner merges.

---

## Built

Built 2026-11-23 in [PR #49](https://github.com/HogJonny-AMZN/HogNoise/pull/49), task by task in the plan's order (P-23). Each number is from the command or run named.

| Task | What ran | Result |
| --- | --- | --- |
| 1 | CI run `45287564746`, the `glsl` job's *Context* step | `llvmpipe (LLVM 21.1.8, 256 bits) \| 4.5 (Core Profile) Mesa 26.0.8-1ubuntu0.3` through EGL; the `xvfb-run` fallback was not needed |
| 2 | `pytest apps/hog-noise-tools/tests/hosts/test_shared.py -n 0` | fails at collection before the module, then 21 passed; the hash mutant and the target mutant each fail their test |
| 3 | `pytest .../test_hosts.py -n 0` with no host module | 1 passed, 1 failed, 14 errors, each a `ModuleNotFoundError`; the step's text now names the one failure |
| 4 | `-k "spirv and not glsl"` on the RTX 5090 | 7 passed on Vulkan and 7 on D3D12 (`WGPU_BACKEND_TYPE`, `HOG_NOISE_HOST_TARGET`); the stride mutant fails |
| 5 | `-k glsl`, then both hosts, on the RTX 5090 (OpenGL 4.3.0 NVIDIA 610.88) | 6 passed, then 36 passed and 1 skipped; x and y swapped at their bindings fails the acceptance test; without `with ctx:` the GL-after-wgpu test fails with `cannot create program` |
| 6 | CI on `e44aae5` | 15 of 15; the target mutant (`not-llvmpipe`, `7d0ccf1`) failed the `glsl` job on `HostTargetError` in run `45291532412`, reverted in `8f3b088` |
| 7 | `tools/check_docs.py` | no drift |
| 8 | `make check`, unpiped, at the board and documents commit | 9 of 9: 3,138 passed, 71 skipped |

**Where the build departed from the plan, and why:**

- **Bit for bit, on Metal.** The first CI run failed `test_spirv_naga_is_the_wgpu_rung_bit_for_bit` on the Metal leg:
  `sample_points_3d` differed in 809 of 4,096 values, by up to 3.58e-7, every other entry point equal, and every hog
  case within the tolerance. The spec measured the claim on Vulkan and D3D12. The test now names each differing entry
  point and its largest difference, and holds the claim on the back ends it was measured on (`BIT_EXACT_BACKENDS`); on
  any other it is a non-strict expected failure, so an exact match shows as XPASS.
- **Bit for bit, on OpenGL.** With wgpu installed beside moderngl, the `glsl` job's wgpu found llvmpipe through its
  OpenGL back end, so `spirv-naga` ran there too: every hog case passed and the test XPASSed. OpenGL joined the
  measured set.
- **The GPU legs do not print the target line.** They run under `-n auto` without `-rA`, so a passing test's output is
  not shown. The target is asserted there by `HOG_NOISE_HOST_TARGET` all the same; the `glsl` job reports every test by
  name (`-rA`).

## Decisions

Taken by the owner 2026-11-23, each as recommended ("I accept your recommendations").

| # | Decision | Recommended | Alternative | Why |
| --- | --- | --- | --- | --- |
| P1 | What this plan covers | The first pull request only, the spec's (a). The HLSL pull request (b) and the Vulkan one (c) each get a plan of their own, written when (a) merges | One plan for all three | (b) and (c) share a C++ harness whose request format follows `HostSampler.run`, which (a) fixes; a plan for it written now would guess at code (a) has not run |
| P2 | The board | The existing row becomes (a); new rows on *Next* for (b), waiting on (a), and (c), waiting on (b). The buffer-limit refusal waits on (b)'s row, the fresh-sample bounds on (a)'s, the engine trials on (b)'s and (c)'s | Three new rows, the existing one kept as an umbrella | A `Waits on` link sees whole rows only (`check_waits_on`); one row per pull request makes each wait exact. Done in this plan's pull request |
| P3 | Where moderngl is declared | A `hosts` group in the root `pyproject.toml`, beside `gpu` | A group in the tools app's own `pyproject.toml`, the spec's words | The root already holds `dev` and `gpu`, and every command here runs from it (`uv run --group gpu`); it is never the library's either way, which is the spec's point |
| P4 | How a host knows its target | `HOG_NOISE_HOST_TARGET`, part of the target line; unset, logged and not asserted | Each host's target hard-coded from the spec's table | Hard-coded, the hosts could not run on the owner's 5090, where the probes were measured; CI sets the variable on every leg, so no leg can go green on another target |
| P5 | The GLSL context | moderngl's EGL back end on Linux, the platform default elsewhere; Task 1 probes it first, with `xvfb-run` as the fallback | xvfb from the start | EGL needs no display server; the probe settles the spec's open risk before anything is built on it |

## Self-review against the spec

- *A host is written from the README*: both hosts import `hog_noise.shaders`, `pack_params`, `pack_grid`, `MAX_OCTAVES`
  and (for `spirv-naga`) `gpu.device()`, all public; neither imports `_Gpu`. Task 4 and 5's code.
- *`HostSampler` and `renderings(host)`*: Task 2.
- *Each host checks the file's hash before its first dispatch*: `verified`, called as each program is built (Tasks 4, 5).
- *Tests: every hog case, the two controls, the skip and `HOG_NOISE_REQUIRE_HOST`*: Task 3.
- *Each host asserts its target, with a mismatched-target control*: `check_target`, `open_host`, Task 3's control,
  Task 6 step 4 in CI.
- *CI: `hosts.yml` per host; `spirv-naga` on the three GPU legs*: Tasks 1 and 6.
- *The README's claims*: Task 7.
- *The spec's facts repeated as tests*: the first is `test_spirv_naga_is_the_wgpu_rung_bit_for_bit`; the second is the
  `glsl` acceptance test; the third is Task 5 step 3.
- *Acceptance: the file unmodified, a failing rule a finding*: *Before you start*, Tasks 5 and 6.
- Not here, by P1: the C++ harness, `hlsl-d3d11`, `hlsl-d3d12`, `spirv-vulkan`.

## Terms introduced

None. *Host harness* is in the glossary already; Task 7 updates its row.
