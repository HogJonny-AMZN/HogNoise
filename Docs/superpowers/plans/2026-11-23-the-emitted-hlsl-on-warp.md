# The CI proof, second pull request: the emitted HLSL on WARP, through D3D11 and D3D12

**Status:** Accepted 2026-11-23 by the owner with its six decisions as recommended ("ok accepted"), to be built after
the warp rules and the fresh-sample bounds, the agreed order. Written from [the spec](../specs/2026-11-22-emitted-shaders-ci-proof.md),
Accepted 2026-11-22, after its first pull request ([PR #49](https://github.com/HogJonny-AMZN/HogNoise/pull/49), merged
as `adf4f30`) fixed the host contract this one follows. The build ticks each step as it lands.
**Board:** [`2026-11-23-the-emitted-hlsl-runs-on-warp`](../../plan/board/2026-11-23-the-emitted-hlsl-runs-on-warp.md)

> **For agentic workers:** REQUIRED SUB-SKILL: use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to carry this out task by task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** the shipped `noise.hlsl`, compiled by FXC (`cs_5_0`) and by DXC (`cs_6_0`), runs on WARP through D3D11 and
D3D12 in CI, bound only as the shaders README says, and passes every hog case within `vectors/tolerance/wgpu.json`,
unmodified. That meets the PyPI release's HLSL condition.

**Architecture:** two hosts, `hlsl-d3d11` and `hlsl-d3d12`, in one module, `hog_noise_tools.hosts.hlsl`, over one
persistent C++ process, `apps/hog-noise-tools/hosts/hlsl/hlsl_host.exe`. Python hashes `noise.hlsl` and the tables
against the manifest (as every host does), compiles the hashed source per entry point with the Windows SDK's own FXC or
DXC (`compile_shaders.find`, the compilers the `shaders` workflow already runs), and sends the tables and the five
programs down the harness's standard input. Each dispatch after that is one request and one reply, so
`conformance.check` stays synchronous (the spec, *What gets built*). The harness reads no file and does only D3D: a
device on the WARP adapter, the README's seven bindings, the dispatch Python computed, the read back. `HostSampler`,
`renderings`, the hash and target checks and every test in `test_hosts.py` are (a)'s, unchanged: the two hosts join
`hosts.HOSTS` and every acceptance test and control runs on them.

**Tech stack:** Python 3.11 to 3.13, numpy; C++17 built by MSVC (`cl`, through `build.bat`, the noise oracle's pattern);
D3D11, D3D12 and DXGI from the Windows SDK; FXC and DXC from the same SDK; pytest through the `pytest` console script
(`uv run pytest`, never `python -m pytest`); `make check` as the gate.

---

## Before you start

- Read the spec end to end, then (a)'s plan, [`2026-11-23-emitted-shaders-ci-proof.md`](2026-11-23-emitted-shaders-ci-proof.md):
  this plan follows its contract and its conventions and does not repeat them.
- Read [the project ledger](../../standards/failure-modes-project.md), above all P-5 and P-7 (a pull request's state,
  checked against a fetched `origin/main`), P-8 (the deliberate review before the pull request leaves draft), P-14 (never
  `python -`; write the script to a file), P-22 (a leg asserts the thing it exists to test) and P-23 (a plan's code is
  trial-run in task order).
- Work in a worktree on a branch from `origin/main`. Commits are signed off (`git commit -s`) with the owner's identity
  and no AI attribution. Write each commit message to a file and pass it with `-F`.
- **Windows only**, for every step that builds or runs the harness: the Windows SDK (10.0.26100 here, for `fxc.exe`,
  `dxc.exe`, `dxil.dll` and the D3D headers) and Visual Studio 2022 or later with the C++ workload. The steps that do not
  build it run anywhere; on another platform the HLSL tests skip, naming why.
- Before every gate run, `uv run ruff format .` and `uv run ruff check --fix .`. Revert `vectors/portability.md` (the
  gate re-stamps its date) before staging, and stage named paths, never `git add -u` or `-A`.
- The commands are written for bash (Git Bash). The harness builds from `cmd`: `cmd //c` in Git Bash.
- Every new Python module ends with an `if __name__ == "__main__":` block.
- **One pull request**, Tasks 1 to 8. It opens as a draft at Task 5, when CI first runs the hosts; it leaves draft after
  Task 8's review.
- **A rule a host fails is a finding for the owner**, never a rule loosened in this pull request
  (`vectors/README.md`, *Tolerance files*). Stop and report it.

## Facts this plan rests on

Read from the code at `e049cc6` (the merge of [PR #50](https://github.com/HogJonny-AMZN/HogNoise/pull/50)), not
assumed:

- **The HLSL's resources.** `noise.hlsl:117-123`: `cbuffer P : register(b0)`, `ByteAddressBuffer` `T`, `XS`, `YS`,
  `ZS` at `t1` to `t4`, `RWByteAddressBuffer OUT : register(u5)`, `cbuffer G : register(b6)`, all in space 0. Each entry
  point is `[numthreads(64, 1, 1)]` and returns when its index is past `NagaBufferLengthRW(OUT) / 4`, which is
  `GetDimensions` on `OUT` (`noise.hlsl:3564-3575`). So the output's view must be exactly the output's size, and on
  D3D12 `u5` must be bound through a descriptor table: a root descriptor is a bare GPU address and has no size.
- **The compilers are already found and already pass.** `compile_shaders.find("fxc" | "dxc")` takes PATH, else the
  newest Windows SDK's `x64` folder (`compile_shaders.py:35`), and the `shaders` workflow's `hlsl` job compiles every
  entry point with `fxc -T cs_5_0` and `dxc -T cs_6_0` on `windows-latest` on every push (`shaders.yml:38-48`).
  `dxil.dll` sits beside the SDK's `dxc.exe`, so DXC's output is signed, which D3D12 requires.
- **The C++ precedent.** `apps/hog-noise-tools/noise_oracle/build.bat` builds a C++ harness with `cl` after finding
  `vcvars64.bat` in the standard Visual Studio folders; its `.exe` is gitignored (`.gitignore:14-15`).
- **The contract (a) fixed.** A host is an object with `name`, `target` and `run(entry, params, axes, n, width, grid)`;
  `hosts.HOSTS` maps each name to what opens it; `test_hosts.py` parametrises every acceptance test and control over
  `hosts.HOSTS`, and `HOG_NOISE_REQUIRE_HOST` and `HOG_NOISE_HOST_TARGET` work by name.
- **WARP's adapter calls itself `Microsoft Basic Render Driver`** (`DXGI_ADAPTER_DESC1.Description`, read by the
  harness below on the RTX 5090 machine, 2026-11-23).
- **This plan's code was run before it was proposed.** Every file below was written from this plan's own text, task by
  task, into a worktree at `e049cc6` on the owner's machine (Windows 11 Pro 10.0.26300, RTX 5090, MSVC 17.14, Windows SDK
  10.0.26100), each task's command run against only the files written so far (P-23), and none of it committed:
  - **Tasks 1 to 3** gave their expectations: no drift; the import error and the two-host message; then the four
    harness tests skipping `not built`, 18 `test_hosts` cases skipping with them, and both compilers' refusals passing.
  - **Task 4:** the harness built at `/W4 /WX`, and the first run passed: with both hosts required and the target
    `Microsoft Basic Render Driver`, 24 passed and 2 skipped (bit for bit, by design). Every hog case on D3D11 and on
    D3D12, within `wgpu.json` unmodified, with both controls failing, the grid matching its points and the dispatch
    past 65,535 workgroups reaching its last points. **The spec's open risk is settled:** D3D11 created every pipeline
    from FXC's `cs_5_0`, and D3D12 from DXC's signed `cs_6_0`. FXC takes about 14 s for each entry point, about 45 s for
    all five at once; DXC about 5 s for all five.
  - **Each mutant failed:** `t2` and `t3` swapped on D3D11, `XS` and `ZS` on D3D12 (each after a real rebuild), and the
    y row of workgroups dropped (both hosts). A harness older than its source skipped, naming `build.bat`.
  - **`make check`, 9 of 9,** after Task 4 and after Task 6, with the harness built, so the HLSL hosts ran inside it.
  - **The trial changed the plan four times.** Task 2's two test files run apart, because a collection error stops the
    run. Task 4's command takes `-k hlsl`: the target applies to every host, and `spirv-naga` and `glsl` opened on the
    5090 and failed it. The harness is never built by the module: built on first use, as the oracle is, it would build
    and run on `tests.yml`'s Windows legs unasked, and `pytest` workers would rebuild a stale one over each other
    (decision B3). And the FXC compiles run at once, which halved the time.
  - **A dead instrument, caught.** The first try at the harness mutants ran the build through a shell script the
    mutation tool's subprocess could not find; exit 127 read as "killed". Rerun through a Python helper, with the
    unmutated build passing first, each mutant failed on its hog case.
  - **Copilot's review of the plan, [PR #51](https://github.com/HogJonny-AMZN/HogNoise/pull/51), changed its code,
    and the trial was run again** from the corrected text, Tasks 1 to 6 in a clean worktree, with the results above.
    `TIMEOUT` had been declared and never applied: a watchdog now ends a harness that does not reply within it. Its
    test uses a stand-in that never answers and fails in seconds; with the watchdog removed, it failed (at 70 s, on the
    wrong message). A harness answering "no device" (status 2) is now a test of its own, a stand-in again; made an error,
    the test failed. Two tests that open a host skip, not fail, when the compiler or the WARP device is missing.
  - **Not run in the trial:** CI (the `windows-latest` image's Visual Studio, WARP there, the `hlsl` job), Task 5's
    target control in CI, and Tasks 7 and 8.

## Files

| File | Responsibility |
| --- | --- |
| Modify `packages/python/hog-noise/src/hog_noise/shaders/README.md` | First: how an HLSL host binds (Task 1); then *What is proven* (Task 6) |
| Modify `.gitignore` | The harness's `.exe` and `.obj` |
| Create `apps/hog-noise-tools/tests/hosts/test_hlsl.py` | The HLSL hosts' own paths: what is a skip, what is an error |
| Modify `apps/hog-noise-tools/tests/hosts/test_shared.py` | The unknown-host message names four hosts |
| Create `apps/hog-noise-tools/src/hog_noise_tools/hosts/hlsl.py` | The two hosts: the hash, the compile, the harness process and its frames |
| Modify `apps/hog-noise-tools/src/hog_noise_tools/hosts/__init__.py` | `HOSTS` gains the two, as `module:function` |
| Create `apps/hog-noise-tools/hosts/hlsl/hlsl_host.cpp` | The harness: D3D11 or D3D12 on WARP, the README's bindings, one dispatch per request |
| Create `apps/hog-noise-tools/hosts/hlsl/build.bat` | MSVC builds it, as `noise_oracle/build.bat` builds the oracle |
| Modify `.github/workflows/hosts.yml` | An `hlsl` job: build the harness, require both hosts on WARP |
| Modify `README.md`, `apps/hog-noise-tools/README.md`, `Docs/standards/testing-project.md` | The claims, and how to build and run the hosts |
| Modify the board rows, `Docs/handoffs/CURRENT.md`; create a journal file | Done includes the documents |

---

### Task 1: the README first

A host is written from the shaders README alone, so what an HLSL host must know goes there before any host is written.
The table already gives the registers; what it does not say is how the output's size bounds the dispatch, which decides
how D3D12 binds `u5`.

**Files:**
- Modify: `packages/python/hog-noise/src/hog_noise/shaders/README.md`
- Modify: `.gitignore`

- [ ] **Step 1: the HLSL paragraph.** In `packages/python/hog-noise/src/hog_noise/shaders/README.md`, replace:

```markdown
**GLSL binds by name.** naga writes no `binding =` qualifier, so a GLSL host binds each block by its name, and the
```

with:

```markdown
**HLSL binds by register,** in space 0, as the table says. The tables and coordinates are `ByteAddressBuffer`s and the
output a `RWByteAddressBuffer`, so their views are raw (`R32_TYPELESS`). The output's size bounds the dispatch: each
invocation compares its point index with `GetDimensions` on `OUT` and returns past the end, so `OUT`'s view covers
exactly the output, `n` points times the entry point's floats per point. On D3D12 that means a descriptor table for
`u5`, not a root descriptor, which is a bare address with no size. A D3D12 constant buffer view is a multiple of 256
bytes, so `Params` (112 bytes) and `Grid` (48) are padded with zeros.

**GLSL binds by name.** naga writes no `binding =` qualifier, so a GLSL host binds each block by its name, and the
```

- [ ] **Step 2: ignore the harness's build.** In `.gitignore`, replace:

```text
apps/hog-noise-tools/noise_oracle/*.obj
```

with:

```text
apps/hog-noise-tools/noise_oracle/*.obj
apps/hog-noise-tools/hosts/hlsl/*.exe
apps/hog-noise-tools/hosts/hlsl/*.obj
```

- [ ] **Step 3: check and commit.**

Run: `uv run python tools/check_docs.py`
Expected: `docs check: ... no drift`.

```bash
git add packages/python/hog-noise/src/hog_noise/shaders/README.md .gitignore
git commit -s -F msg.txt   # "CI proof (b), task 1: the shaders README says how an HLSL host binds"
```

### Task 2: the tests first

The HLSL hosts' own paths, before the module exists. Each case is a skip (no Windows, no harness built, a harness older
than its source, no compiler, no WARP device) or an error (a compiler or the device refusing what it was given, or a
harness that stops replying), and an error is never a skip. Two of the paths need no harness: a stand-in Python script
answers as a harness with no device does, and another never answers, so the timeout is held by a test that fails in
seconds, not one that hangs. The acceptance tests are (a)'s `test_hosts.py`, unchanged: they run on any host in `hosts.HOSTS`.

**Files:**
- Create: `apps/hog-noise-tools/tests/hosts/test_hlsl.py`
- Modify: `apps/hog-noise-tools/tests/hosts/test_shared.py`

- [ ] **Step 1: the tests.** Create `apps/hog-noise-tools/tests/hosts/test_hlsl.py`:

```python
"""
HogNoise tools: the HLSL hosts' own paths, beside test_hosts' acceptance: what is a skip (no Windows, no harness, no
compiler) and what is an error (a compiler or the harness refusing what it was given), which must never be a skip.
Package: apps/hog-noise-tools/tests/hosts/test_hlsl
"""

import os
import sys
import time

import pytest

from hog_noise import shaders
from hog_noise_tools import compile_shaders
from hog_noise_tools.hosts import HostUnavailable, hlsl, verified_tables


def test_off_windows_the_hosts_are_unavailable(monkeypatch):
    monkeypatch.setattr(hlsl.sys, "platform", "linux")
    with pytest.raises(HostUnavailable, match="need Windows"):
        hlsl.harness()


def test_a_harness_never_built_is_unavailable_naming_the_build_script(monkeypatch, tmp_path):
    """Never built here from nothing: tests.yml's Windows legs have MSVC and did not ask for these hosts."""
    monkeypatch.setattr(hlsl.sys, "platform", "win32")
    monkeypatch.setattr(hlsl, "EXE", tmp_path / "hlsl_host.exe")
    with pytest.raises(HostUnavailable, match=r"not built: run .*build\.bat"):
        hlsl.harness()


def test_no_compiler_is_unavailable(monkeypatch):
    monkeypatch.setattr(compile_shaders, "find", lambda name: None)
    with pytest.raises(HostUnavailable, match="fxc is not on PATH"):
        hlsl.compile_entry_points("d3d11", "anything")


def test_a_harness_older_than_its_source_is_unavailable(monkeypatch, tmp_path):
    """A stale harness would run code the source no longer says; it is rebuilt by hand, never by a test worker."""
    exe, source = tmp_path / "hlsl_host.exe", tmp_path / "hlsl_host.cpp"
    exe.write_bytes(b"")
    source.write_text("// newer")
    os.utime(exe, (1_000_000, 1_000_000))
    monkeypatch.setattr(hlsl.sys, "platform", "win32")
    monkeypatch.setattr(hlsl, "EXE", exe)
    monkeypatch.setattr(hlsl, "SOURCE", source)
    with pytest.raises(HostUnavailable, match=r"older than hlsl_host\.cpp: run .*build\.bat"):
        hlsl.harness()


@pytest.mark.parametrize("api", sorted(hlsl.COMPILERS))
def test_a_source_the_compiler_refuses_is_an_error_not_a_skip(api):
    name = hlsl.COMPILERS[api][0]
    if compile_shaders.find(name) is None:
        pytest.skip(f"{name} is not here")
    with pytest.raises(RuntimeError, match=f"{name} refused sample_points_3d"):
        hlsl.compile_entry_points(api, "this is not HLSL")


@pytest.fixture
def built():
    try:
        return hlsl.harness()
    except HostUnavailable as e:
        pytest.skip(f"hlsl: {e}")


@pytest.mark.parametrize("api", sorted(hlsl.COMPILERS))
def test_programs_the_device_refuses_are_an_error_not_a_skip(built, api):
    """
    Bytes that are no compiled shader reach the device and are refused there: a RuntimeError naming the call. With no
    WARP device here the host is unavailable, a skip; HostUnavailable is a RuntimeError too, so it is told apart first.
    """
    garbage = [b"not a compiled shader"] * len(shaders.ENTRY_POINTS)
    try:
        hlsl.Hlsl(api, garbage, verified_tables())
    except HostUnavailable as e:
        pytest.skip(f"hlsl: {e}")
    except RuntimeError as e:
        assert "refused the programs: Create" in str(e), e
    else:
        pytest.fail("the harness accepted bytes that are no compiled shader")


def test_an_unknown_api_is_refused_by_the_harness(built):
    with pytest.raises(RuntimeError, match="unknown --api metal"):
        hlsl.Hlsl("metal", [b""] * len(shaders.ENTRY_POINTS), verified_tables())


def test_the_harness_ends_when_its_input_closes(built):
    """Opening needs DXC and a WARP device as well as the harness: without either, a skip naming which."""
    try:
        host = hlsl.open_d3d12()
    except HostUnavailable as e:
        pytest.skip(f"hlsl: {e}")
    process = host.process
    host.close()
    assert process.returncode == 0


def test_a_harness_that_finds_no_device_is_unavailable_not_an_error(tmp_path):
    """
    No harness needed: a stand-in that answers the init frame as the harness does with no WARP device, status 2.
    That is a skip (HostUnavailable), what the two tests above tell apart from a refusal; any other status is an error.
    """
    stand_in = tmp_path / "no_device.py"
    stand_in.write_text(
        "import struct, sys\n"
        "message = b'no WARP adapter'\n"
        "sys.stdout.buffer.write(struct.pack('<II', 2, len(message)) + message)\n"
        "sys.stdout.buffer.flush()\n"
        "sys.stdin.buffer.read()\n"
    )
    with pytest.raises(HostUnavailable, match="no WARP adapter"):
        hlsl.Hlsl("d3d11", [b""] * len(shaders.ENTRY_POINTS), b"", command=[sys.executable, str(stand_in)])


def test_a_harness_that_never_replies_fails_within_the_timeout(monkeypatch, tmp_path):
    """
    No harness needed: a stand-in that neither reads nor replies for 30 s. Without the watchdog the call waits until the
    stand-in exits and then fails another way, so the message and the time both fail it: a hang in conformance.check
    would stall the gate with no message.
    """
    silent = tmp_path / "silent.py"
    silent.write_text("import time\ntime.sleep(30)\n")
    monkeypatch.setattr(hlsl, "TIMEOUT", 2)
    started = time.monotonic()
    with pytest.raises(RuntimeError, match="did not reply within 2 s, and was ended"):
        hlsl.Hlsl("d3d11", [b""] * len(shaders.ENTRY_POINTS), b"", command=[sys.executable, str(silent)])
    assert time.monotonic() - started < 20
```

- [ ] **Step 2: four known hosts.** In `apps/hog-noise-tools/tests/hosts/test_shared.py`, replace:

```python
    with pytest.raises(ValueError, match="glsl, spirv-naga"):
```

with:

```python
    with pytest.raises(ValueError, match="glsl, hlsl-d3d11, hlsl-d3d12, spirv-naga"):
```

- [ ] **Step 3: run them, and see them fail.**

Run: `uv run pytest apps/hog-noise-tools/tests/hosts/test_hlsl.py -n 0 -q`
Expected: **an error** collecting it, `ImportError: cannot import name 'hlsl' from 'hog_noise_tools.hosts'`. Run the two
files apart: a collection error interrupts the whole run, and the second file's result would not show.

Run: `uv run pytest apps/hog-noise-tools/tests/hosts/test_shared.py -n 0 -q`
Expected: `test_an_unknown_host_is_refused_naming_the_known_ones` **fails**, the message still naming two hosts; the
rest pass.

- [ ] **Step 4: commit.**

```bash
git add apps/hog-noise-tools/tests/hosts/test_hlsl.py apps/hog-noise-tools/tests/hosts/test_shared.py
git commit -s -F msg.txt   # "CI proof (b), task 2: the HLSL hosts' own tests, failing"
```

### Task 3: the module

**Files:**
- Create: `apps/hog-noise-tools/src/hog_noise_tools/hosts/hlsl.py`
- Modify: `apps/hog-noise-tools/src/hog_noise_tools/hosts/__init__.py`

- [ ] **Step 1: the two hosts.** Create `apps/hog-noise-tools/src/hog_noise_tools/hosts/hlsl.py`:

```python
"""
HogNoise tools: the HLSL hosts. ``noise.hlsl``, compiled per entry point by FXC (``cs_5_0``) for D3D11 or DXC
(``cs_6_0``) for D3D12, dispatched on WARP by a persistent C++ harness, ``apps/hog-noise-tools/hosts/hlsl``.
Package: hog_noise_tools.hosts.hlsl

The harness reads no file. This module hashes ``noise.hlsl`` and the tables against the manifest, compiles the hashed
source with the Windows SDK's compilers (``compile_shaders.find``), and sends the tables and the five programs down the
harness's standard input; each dispatch is one request and one reply (the frames are in ``hlsl_host.cpp``). The harness
is built by ``build.bat`` (MSVC), by hand or by CI, never by this module.
"""

from __future__ import annotations

import logging as _logging
import struct
import subprocess
import sys
import tempfile
import threading
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from hog_noise import shaders
from hog_noise_tools import compile_shaders
from hog_noise_tools.hosts import HostUnavailable, verified, verified_tables, workgroups
from hog_noise_tools.repo import APP_ROOT

_MODULE_NAME = "hog_noise_tools.hosts.hlsl"
__version__ = "0.1.0"
__updated__ = "2026-11-23"
_LOGGER = _logging.getLogger(_MODULE_NAME)

HARNESS_DIR = APP_ROOT / "hosts" / "hlsl"
SOURCE = HARNESS_DIR / "hlsl_host.cpp"
EXE = HARNESS_DIR / "hlsl_host.exe"
#: Per API, the SDK compiler and its arguments before ``-E <entry point> -Fo <out> <source>``: compile_shaders' own.
COMPILERS = {"d3d11": ("fxc", ("-nologo", "-T", "cs_5_0")), "d3d12": ("dxc", ("-T", "cs_6_0"))}
#: Seconds the harness may take over one reply; a dispatch past 65,535 workgroups on WARP takes a few.
TIMEOUT = 600
_OK, _ERROR, _UNAVAILABLE = 0, 1, 2


def harness() -> Path:
    """
    The built harness. Never built here: a Windows leg with MSVC that did not ask for the HLSL hosts must not get them,
    and pytest's workers would each rebuild a stale one over an ``.exe`` another is running. CI builds it; by hand,
    ``build.bat``.

    :raises HostUnavailable: Not Windows, not built, or older than its source, naming the build script.
    """
    if sys.platform != "win32":
        raise HostUnavailable("D3D11 and D3D12 need Windows")
    if not EXE.exists():
        raise HostUnavailable(f"the harness is not built: run {HARNESS_DIR / 'build.bat'}")
    if EXE.stat().st_mtime < SOURCE.stat().st_mtime:
        raise HostUnavailable(f"{EXE.name} is older than {SOURCE.name}: run {HARNESS_DIR / 'build.bat'}")
    return EXE


def compile_entry_points(api: str, source: str) -> list[bytes]:
    """
    ``source`` compiled for ``api``, one program per entry point, in ``shaders.ENTRY_POINTS`` order.

    :raises HostUnavailable: The SDK compiler is not here.
    :raises RuntimeError: It refused the source, with its message: a finding, never a skip.
    """
    name, args = COMPILERS[api]
    tool = compile_shaders.find(name)
    if tool is None:
        raise HostUnavailable(f"{name} is not on PATH or in a Windows SDK")
    with tempfile.TemporaryDirectory(prefix="hog-noise-hlsl-") as tmp:
        src = Path(tmp) / shaders.file_name("hlsl")
        src.write_text(source, encoding="utf-8", newline="\n")

        def one(entry: str) -> bytes:
            out = Path(tmp) / f"{entry}.cso"
            cmd = [tool, *args, "-E", entry, "-Fo", str(out), str(src)]
            done = subprocess.run(cmd, capture_output=True, text=True, timeout=compile_shaders.TIMEOUT)
            if done.returncode != 0:
                raise RuntimeError(f"{name} refused {entry}: {(done.stdout + done.stderr).strip()}")
            return out.read_bytes()

        # one process per entry point, at once: FXC takes about 14 s for each (2026-11-23, the RTX 5090 machine)
        with ThreadPoolExecutor(len(shaders.ENTRY_POINTS)) as pool:
            programs = list(pool.map(one, shaders.ENTRY_POINTS))
    _LOGGER.info(f"hlsl: {name} compiled {len(programs)} entry points with {tool}")
    return programs


def _blob(data: bytes) -> bytes:
    return struct.pack("<I", len(data)) + data


class Hlsl:
    """One harness process, on one API."""

    def __init__(
        self, api: str, programs: Sequence[bytes], tables: bytes, command: Sequence[str] | None = None
    ) -> None:
        """
        :param command: What to run in place of the harness: the tests' stand-in for one that never replies.
        :raises HostUnavailable: The harness found no device here.
        :raises RuntimeError: It refused the programs, stopped, or did not reply within `TIMEOUT`.
        """
        self.api, self.name = api, f"hlsl-{api}"
        self._expired = False
        self.process = subprocess.Popen(
            list(command or [str(harness()), "--api", api]),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        named = b"".join(_blob(e.encode()) + _blob(p) for e, p in zip(shaders.ENTRY_POINTS, programs, strict=True))
        status, body = self._exchange(b"HNH1" + _blob(tables) + struct.pack("<I", len(programs)) + named)
        if status != _OK:
            self.process.kill()  # it exits after a failed start anyway; never leave one behind
            self.process.wait()
            if status == _UNAVAILABLE:
                raise HostUnavailable(f"{self.name}: {body.decode()}")
            raise RuntimeError(f"{self.name}: the harness refused the programs: {body.decode()}")
        self.target = body.decode()
        _LOGGER.info(f"{self.name}: {len(programs)} programs on {self.target}")

    def _stopped(self, why: str) -> RuntimeError:
        """The error for a harness that is gone, saying whether the watchdog ended it."""
        if self._expired:
            self.process.wait()
            return RuntimeError(f"{self.name}: the harness did not reply within {TIMEOUT} s, and was ended")
        exit_code = self.process.poll()
        err = self.process.stderr.read().decode(errors="replace").strip() if exit_code is not None else ""
        return RuntimeError(f"{self.name}: the harness {why} (exit {exit_code}) {err}".strip())

    def _read(self, n: int) -> bytes:
        data = self.process.stdout.read(n)
        if len(data) != n:
            raise self._stopped("stopped")
        return data

    def _expire(self) -> None:
        self._expired = True
        self.process.kill()

    def _exchange(self, frame: bytes) -> tuple[int, bytes]:
        """
        One frame out, one reply back, within `TIMEOUT`: past it a watchdog ends the harness, so a harness that stops
        replying fails the call instead of hanging ``conformance.check`` and the gate.
        """
        watchdog = threading.Timer(TIMEOUT, self._expire)
        watchdog.start()
        try:
            try:
                self.process.stdin.write(frame)
                self.process.stdin.flush()
            except OSError as e:
                raise self._stopped("is gone") from e
            status, length = struct.unpack("<II", self._read(8))
            return status, self._read(length)
        finally:
            watchdog.cancel()

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
        gx, gy, _ = workgroups(n)
        head = struct.pack("<5I", shaders.ENTRY_POINTS.index(entry), n, width, gx, gy)
        body = _blob(params) + _blob(grid or b"") + struct.pack("<I", len(axes))
        status, reply = self._exchange(head + body + b"".join(_blob(a.tobytes()) for a in axes))
        if status != _OK:
            raise RuntimeError(f"{self.name} {entry}: {reply.decode(errors='replace')}")
        return np.frombuffer(reply, dtype=np.float32).copy()

    def close(self) -> None:
        """End the harness: its standard input closing is its signal."""
        if self.process.poll() is None:
            self.process.stdin.close()
            self.process.wait(timeout=30)


def _open(api: str) -> Hlsl:
    exe = harness()
    _LOGGER.info(f"hlsl: harness {exe}")
    return Hlsl(api, compile_entry_points(api, verified("hlsl")), verified_tables())


def open_d3d11() -> Hlsl:
    """FXC's ``cs_5_0`` on D3D11, WARP. :raises HostUnavailable: As `harness` and `compile_entry_points`."""
    return _open("d3d11")


def open_d3d12() -> Hlsl:
    """DXC's ``cs_6_0`` on D3D12, WARP. :raises HostUnavailable: As `harness` and `compile_entry_points`."""
    return _open("d3d12")


if __name__ == "__main__":
    _logging.basicConfig(level=_logging.INFO)
    from hog_noise import NoiseParams
    from hog_noise_tools.hosts import HostSampler

    xs = np.linspace(-100, 100, 5, dtype=np.float32)
    for opener in (open_d3d11, open_d3d12):
        host = opener()
        s = HostSampler(NoiseParams(frequency=0.01), host)
        print(host.target, np.round(s.sample_points(xs, xs, np.zeros(5, np.float32), np.empty(5, np.float32)), 5))
        host.close()
```

- [ ] **Step 2: register them.** Two hosts share one module, so a `HOSTS` entry may name its opener. In
  `apps/hog-noise-tools/src/hog_noise_tools/hosts/__init__.py`, replace:

```python
#: The hosts, by name, and the module that opens each (the spec's hosts table).
HOSTS = {"glsl": "hog_noise_tools.hosts.glsl", "spirv-naga": "hog_noise_tools.hosts.spirv_naga"}
```

with:

```python
#: The hosts, by name, and what opens each (the spec's hosts table): a module's ``open_host``, or ``module:function``.
HOSTS = {
    "glsl": "hog_noise_tools.hosts.glsl",
    "hlsl-d3d11": "hog_noise_tools.hosts.hlsl:open_d3d11",
    "hlsl-d3d12": "hog_noise_tools.hosts.hlsl:open_d3d12",
    "spirv-naga": "hog_noise_tools.hosts.spirv_naga",
}
```

and replace:

```python
    return importlib.import_module(HOSTS[name]).open_host()
```

with:

```python
    module, _, function = HOSTS[name].partition(":")
    return getattr(importlib.import_module(module), function or "open_host")()
```

- [ ] **Step 3: run the tests: the harness is not built yet.**

Run: `uv run pytest apps/hog-noise-tools/tests/hosts/test_hlsl.py apps/hog-noise-tools/tests/hosts/test_shared.py -n 0 -q -rs`
Expected on Windows with the SDK: every test passes except the four that need the harness, which skip with `the harness
is not built: run ...build.bat`. Both compiler-refusal tests run and pass: FXC and DXC refuse `this is not HLSL` with
an error, not a skip.

Run: `uv run pytest apps/hog-noise-tools/tests/hosts -n 0 -q -rs -k hlsl`
Expected: every `[hlsl-d3d11]` and `[hlsl-d3d12]` case of `test_hosts.py` skips, naming `build.bat` (18 skipped); `-k
hlsl` also selects `test_hlsl.py`'s eight tests that need no harness, which pass.

- [ ] **Step 4: commit.**

```bash
git add apps/hog-noise-tools/src/hog_noise_tools/hosts/hlsl.py apps/hog-noise-tools/src/hog_noise_tools/hosts/__init__.py
git commit -s -F msg.txt   # "CI proof (b), task 3: the HLSL hosts' module; a missing harness is a skip naming build.bat"
```

### Task 4: the harness

**Files:**
- Create: `apps/hog-noise-tools/hosts/hlsl/hlsl_host.cpp`
- Create: `apps/hog-noise-tools/hosts/hlsl/build.bat`

- [ ] **Step 1: the harness.** Create `apps/hog-noise-tools/hosts/hlsl/hlsl_host.cpp`:

```cpp
// HogNoise tools: the HLSL host harness. noise.hlsl's compiled entry points dispatched through D3D11 (FXC's cs_5_0)
// or D3D12 (DXC's cs_6_0) on WARP, written from hog_noise/shaders/README.md alone.
//
// A persistent process: hog_noise_tools.hosts.hlsl starts it once with --api d3d11|d3d12, sends the tables and the
// five compiled entry points, then one request per dispatch on standard input, and reads each reply on standard output
// before it sends the next. It reads no file: every byte it binds came through Python, which hashed the source and the
// tables against the manifest. The frames are little-endian; a blob is a u32 length and that many bytes.
//
//   init     "HNH1", blob tables, u32 count, count x (blob name, blob bytecode)
//   request  u32 entry, u32 n, u32 width, u32 groups_x, u32 groups_y, blob params, blob grid (empty: none),
//            u32 axes, axes x blob (n float32)
//   reply    u32 status, blob: 0 the output (n * width float32) or the target line after init; 1 an error, its message;
//            2 (init only) no device here, its message
//
// Standard input closing ends the process. Built by build.bat with MSVC; the .exe is gitignored.

#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <d3d11.h>
#include <d3d12.h>
#include <dxgi1_6.h>
#include <fcntl.h>
#include <io.h>
#include <wrl/client.h>

#include <cstdint>
#include <cstdio>
#include <cstring>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

#pragma comment(lib, "d3d11.lib")
#pragma comment(lib, "d3d12.lib")
#pragma comment(lib, "dxgi.lib")

using Microsoft::WRL::ComPtr;
using Bytes = std::vector<uint8_t>;

namespace {

struct Eof {};

// a device or adapter missing: the host is unavailable here, which Python turns into a skip unless it is required
struct Unavailable : std::runtime_error {
    using std::runtime_error::runtime_error;
};

void check(HRESULT hr, const char* what) {
    if (FAILED(hr)) {
        char text[160];
        std::snprintf(text, sizeof text, "%s failed: HRESULT 0x%08lX", what, static_cast<unsigned long>(hr));
        throw std::runtime_error(text);
    }
}

void read_exact(void* into, size_t n, bool eof_ok = false) {
    size_t got = std::fread(into, 1, n, stdin);
    if (got == 0 && eof_ok) throw Eof{};
    if (got != n) throw std::runtime_error("standard input ended inside a frame");
}

uint32_t read_u32(bool eof_ok = false) {
    uint32_t v = 0;
    read_exact(&v, 4, eof_ok);
    return v;
}

Bytes read_blob() {
    Bytes b(read_u32());
    if (!b.empty()) read_exact(b.data(), b.size());
    return b;
}

void reply(uint32_t status, const void* data, size_t n) {
    uint32_t len = static_cast<uint32_t>(n);
    std::fwrite(&status, 4, 1, stdout);
    std::fwrite(&len, 4, 1, stdout);
    if (n) std::fwrite(data, 1, n, stdout);
    std::fflush(stdout);
}

void reply_text(uint32_t status, const std::string& text) { reply(status, text.data(), text.size()); }

std::string utf8(const wchar_t* wide) {
    int n = WideCharToMultiByte(CP_UTF8, 0, wide, -1, nullptr, 0, nullptr, nullptr);
    std::string out(n > 0 ? n - 1 : 0, '\0');
    if (n > 1) WideCharToMultiByte(CP_UTF8, 0, wide, -1, out.data(), n, nullptr, nullptr);
    return out;
}

ComPtr<IDXGIAdapter1> warp_adapter() {
    ComPtr<IDXGIFactory4> factory;
    if (FAILED(CreateDXGIFactory1(IID_PPV_ARGS(&factory)))) throw Unavailable("CreateDXGIFactory1 failed: no DXGI");
    ComPtr<IDXGIAdapter1> adapter;
    if (FAILED(factory->EnumWarpAdapter(IID_PPV_ARGS(&adapter)))) throw Unavailable("no WARP adapter");
    return adapter;
}

std::string describe(IDXGIAdapter1* adapter, const char* api) {
    DXGI_ADAPTER_DESC1 desc{};
    check(adapter->GetDesc1(&desc), "IDXGIAdapter1::GetDesc1");
    return utf8(desc.Description) + " (" + api + ")";
}

// One request's inputs, as the README's bindings: 0 Params, 2-4 the coordinates, 6 Grid.
struct Request {
    uint32_t entry, n, width, gx, gy;
    Bytes params, grid;
    std::vector<Bytes> axes;
};

struct Backend {
    virtual ~Backend() = default;
    virtual void load(const Bytes& tables, const std::vector<Bytes>& programs) = 0;
    virtual std::vector<float> run(const Request& r) = 0;
    std::string target;
};

size_t round_up(size_t n, size_t to) { return (n + to - 1) / to * to; }

// ---------------------------------------------------------------- D3D11

struct D3D11 : Backend {
    ComPtr<ID3D11Device> dev;
    ComPtr<ID3D11DeviceContext> ctx;
    std::vector<ComPtr<ID3D11ComputeShader>> programs;
    ComPtr<ID3D11ShaderResourceView> tables;

    D3D11() {
        auto adapter = warp_adapter();
        D3D_FEATURE_LEVEL want = D3D_FEATURE_LEVEL_11_0;
        if (FAILED(D3D11CreateDevice(adapter.Get(), D3D_DRIVER_TYPE_UNKNOWN, nullptr, 0, &want, 1, D3D11_SDK_VERSION,
                                     &dev, nullptr, &ctx)))
            throw Unavailable("D3D11CreateDevice on WARP failed");
        target = describe(adapter.Get(), "D3D11");
    }

    ComPtr<ID3D11Buffer> buffer(const void* data, size_t bytes, UINT bind, UINT misc) {
        D3D11_BUFFER_DESC d{};
        d.ByteWidth = static_cast<UINT>(bytes);
        d.Usage = D3D11_USAGE_DEFAULT;
        d.BindFlags = bind;
        d.MiscFlags = misc;
        D3D11_SUBRESOURCE_DATA init{data, 0, 0};
        ComPtr<ID3D11Buffer> b;
        check(dev->CreateBuffer(&d, data ? &init : nullptr, &b), "ID3D11Device::CreateBuffer");
        return b;
    }

    // a ByteAddressBuffer: a raw view over the whole buffer
    ComPtr<ID3D11ShaderResourceView> raw_srv(const void* data, size_t bytes) {
        auto b = buffer(data, bytes, D3D11_BIND_SHADER_RESOURCE, D3D11_RESOURCE_MISC_BUFFER_ALLOW_RAW_VIEWS);
        D3D11_SHADER_RESOURCE_VIEW_DESC v{};
        v.Format = DXGI_FORMAT_R32_TYPELESS;
        v.ViewDimension = D3D11_SRV_DIMENSION_BUFFEREX;
        v.BufferEx.NumElements = static_cast<UINT>(bytes / 4);
        v.BufferEx.Flags = D3D11_BUFFEREX_SRV_FLAG_RAW;
        ComPtr<ID3D11ShaderResourceView> srv;
        check(dev->CreateShaderResourceView(b.Get(), &v, &srv), "CreateShaderResourceView");
        return srv;
    }

    // a cbuffer: its size a multiple of 16
    ComPtr<ID3D11Buffer> constants(const Bytes& data) {
        Bytes padded(round_up(std::max<size_t>(data.size(), 16), 16), 0);
        std::memcpy(padded.data(), data.data(), data.size());
        return buffer(padded.data(), padded.size(), D3D11_BIND_CONSTANT_BUFFER, 0);
    }

    void load(const Bytes& t, const std::vector<Bytes>& blobs) override {
        tables = raw_srv(t.data(), t.size());
        for (const auto& blob : blobs) {
            ComPtr<ID3D11ComputeShader> cs;
            check(dev->CreateComputeShader(blob.data(), blob.size(), nullptr, &cs), "CreateComputeShader");
            programs.push_back(cs);
        }
    }

    std::vector<float> run(const Request& r) override {
        const size_t out_bytes = size_t(r.n) * r.width * 4;
        static const float unused_axis = 0.0f;  // the README: a one-float buffer for an unused coordinate
        auto params = constants(r.params);
        auto grid = constants(r.grid.empty() ? Bytes(48, 0) : r.grid);  // and 48 zero bytes for an unused Grid
        ComPtr<ID3D11ShaderResourceView> srvs[4] = {tables};
        for (int i = 0; i < 3; ++i)
            srvs[1 + i] = i < int(r.axes.size()) ? raw_srv(r.axes[i].data(), r.axes[i].size())
                                                 : raw_srv(&unused_axis, 4);
        auto out = buffer(nullptr, out_bytes, D3D11_BIND_UNORDERED_ACCESS, D3D11_RESOURCE_MISC_BUFFER_ALLOW_RAW_VIEWS);
        D3D11_UNORDERED_ACCESS_VIEW_DESC u{};
        u.Format = DXGI_FORMAT_R32_TYPELESS;
        u.ViewDimension = D3D11_UAV_DIMENSION_BUFFER;
        u.Buffer.NumElements = static_cast<UINT>(out_bytes / 4);  // the shader's bound: GetDimensions on OUT
        u.Buffer.Flags = D3D11_BUFFER_UAV_FLAG_RAW;
        ComPtr<ID3D11UnorderedAccessView> uav;
        check(dev->CreateUnorderedAccessView(out.Get(), &u, &uav), "CreateUnorderedAccessView");

        ID3D11Buffer* b0 = params.Get();
        ID3D11Buffer* b6 = grid.Get();
        ID3D11ShaderResourceView* t[4] = {srvs[0].Get(), srvs[1].Get(), srvs[2].Get(), srvs[3].Get()};
        ID3D11UnorderedAccessView* u5 = uav.Get();
        ctx->CSSetShader(programs.at(r.entry).Get(), nullptr, 0);
        ctx->CSSetConstantBuffers(0, 1, &b0);
        ctx->CSSetConstantBuffers(6, 1, &b6);
        ctx->CSSetShaderResources(1, 4, t);
        ctx->CSSetUnorderedAccessViews(5, 1, &u5, nullptr);
        ctx->Dispatch(r.gx, r.gy, 1);
        ID3D11UnorderedAccessView* none = nullptr;
        ctx->CSSetUnorderedAccessViews(5, 1, &none, nullptr);

        D3D11_BUFFER_DESC sd{};
        sd.ByteWidth = static_cast<UINT>(out_bytes);
        sd.Usage = D3D11_USAGE_STAGING;
        sd.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
        ComPtr<ID3D11Buffer> staging;
        check(dev->CreateBuffer(&sd, nullptr, &staging), "CreateBuffer (staging)");
        ctx->CopyResource(staging.Get(), out.Get());
        D3D11_MAPPED_SUBRESOURCE m{};
        check(ctx->Map(staging.Get(), 0, D3D11_MAP_READ, 0, &m), "ID3D11DeviceContext::Map");
        std::vector<float> values(out_bytes / 4);
        std::memcpy(values.data(), m.pData, out_bytes);
        ctx->Unmap(staging.Get(), 0);
        return values;
    }
};

// ---------------------------------------------------------------- D3D12

struct D3D12 : Backend {
    ComPtr<ID3D12Device> dev;
    ComPtr<ID3D12CommandQueue> queue;
    ComPtr<ID3D12CommandAllocator> alloc;
    ComPtr<ID3D12GraphicsCommandList> list;
    ComPtr<ID3D12Fence> fence;
    UINT64 fence_value = 0;
    HANDLE event = nullptr;
    ComPtr<ID3D12RootSignature> root;
    std::vector<ComPtr<ID3D12PipelineState>> programs;
    ComPtr<ID3D12Resource> tables;
    UINT tables_bytes = 0;
    UINT stride = 0;

    D3D12() {
        auto adapter = warp_adapter();
        if (FAILED(D3D12CreateDevice(adapter.Get(), D3D_FEATURE_LEVEL_11_0, IID_PPV_ARGS(&dev))))
            throw Unavailable("D3D12CreateDevice on WARP failed");
        target = describe(adapter.Get(), "D3D12");
        D3D12_COMMAND_QUEUE_DESC q{};
        q.Type = D3D12_COMMAND_LIST_TYPE_DIRECT;
        check(dev->CreateCommandQueue(&q, IID_PPV_ARGS(&queue)), "CreateCommandQueue");
        check(dev->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT, IID_PPV_ARGS(&alloc)),
              "CreateCommandAllocator");
        check(dev->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_DIRECT, alloc.Get(), nullptr, IID_PPV_ARGS(&list)),
              "CreateCommandList");
        check(list->Close(), "ID3D12GraphicsCommandList::Close");
        check(dev->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&fence)), "CreateFence");
        event = CreateEventW(nullptr, FALSE, FALSE, nullptr);
        stride = dev->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
        make_root_signature();
    }

    ~D3D12() override {
        if (event) CloseHandle(event);
    }

    // The README's bindings as one descriptor table, b0, t1-t4, u5, b6, in that order. A table, not root
    // descriptors: the shader bounds every invocation by GetDimensions on OUT, and a root descriptor has no size.
    void make_root_signature() {
        D3D12_DESCRIPTOR_RANGE ranges[4] = {
            {D3D12_DESCRIPTOR_RANGE_TYPE_CBV, 1, 0, 0, D3D12_DESCRIPTOR_RANGE_OFFSET_APPEND},
            {D3D12_DESCRIPTOR_RANGE_TYPE_SRV, 4, 1, 0, D3D12_DESCRIPTOR_RANGE_OFFSET_APPEND},
            {D3D12_DESCRIPTOR_RANGE_TYPE_UAV, 1, 5, 0, D3D12_DESCRIPTOR_RANGE_OFFSET_APPEND},
            {D3D12_DESCRIPTOR_RANGE_TYPE_CBV, 1, 6, 0, D3D12_DESCRIPTOR_RANGE_OFFSET_APPEND},
        };
        D3D12_ROOT_PARAMETER table{};
        table.ParameterType = D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;
        table.DescriptorTable.NumDescriptorRanges = 4;
        table.DescriptorTable.pDescriptorRanges = ranges;
        table.ShaderVisibility = D3D12_SHADER_VISIBILITY_ALL;
        D3D12_ROOT_SIGNATURE_DESC desc{1, &table, 0, nullptr, D3D12_ROOT_SIGNATURE_FLAG_NONE};
        ComPtr<ID3DBlob> blob, error;
        HRESULT hr = D3D12SerializeRootSignature(&desc, D3D_ROOT_SIGNATURE_VERSION_1, &blob, &error);
        if (FAILED(hr) && error) throw std::runtime_error(static_cast<const char*>(error->GetBufferPointer()));
        check(hr, "D3D12SerializeRootSignature");
        check(dev->CreateRootSignature(0, blob->GetBufferPointer(), blob->GetBufferSize(), IID_PPV_ARGS(&root)),
              "CreateRootSignature");
    }

    ComPtr<ID3D12Resource> buffer(D3D12_HEAP_TYPE heap, size_t bytes, D3D12_RESOURCE_FLAGS flags,
                                  D3D12_RESOURCE_STATES state) {
        D3D12_HEAP_PROPERTIES hp{};
        hp.Type = heap;
        D3D12_RESOURCE_DESC d{};
        d.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
        d.Width = bytes;
        d.Height = 1;
        d.DepthOrArraySize = 1;
        d.MipLevels = 1;
        d.SampleDesc.Count = 1;
        d.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
        d.Flags = flags;
        ComPtr<ID3D12Resource> r;
        check(dev->CreateCommittedResource(&hp, D3D12_HEAP_FLAG_NONE, &d, state, nullptr, IID_PPV_ARGS(&r)),
              "CreateCommittedResource");
        return r;
    }

    // an upload-heap buffer holding ``data``, at least ``size`` bytes
    ComPtr<ID3D12Resource> upload(const void* data, size_t n, size_t size) {
        auto r = buffer(D3D12_HEAP_TYPE_UPLOAD, size, D3D12_RESOURCE_FLAG_NONE, D3D12_RESOURCE_STATE_GENERIC_READ);
        void* p = nullptr;
        check(r->Map(0, nullptr, &p), "ID3D12Resource::Map (upload)");
        std::memset(p, 0, size);
        std::memcpy(p, data, n);
        r->Unmap(0, nullptr);
        return r;
    }

    void load(const Bytes& t, const std::vector<Bytes>& blobs) override {
        tables_bytes = static_cast<UINT>(t.size());
        tables = upload(t.data(), t.size(), t.size());
        for (const auto& blob : blobs) {
            D3D12_COMPUTE_PIPELINE_STATE_DESC d{};
            d.pRootSignature = root.Get();
            d.CS = {blob.data(), blob.size()};
            ComPtr<ID3D12PipelineState> pso;
            check(dev->CreateComputePipelineState(&d, IID_PPV_ARGS(&pso)), "CreateComputePipelineState");
            programs.push_back(pso);
        }
    }

    void raw_srv(ID3D12Resource* r, UINT bytes, D3D12_CPU_DESCRIPTOR_HANDLE at) {
        D3D12_SHADER_RESOURCE_VIEW_DESC v{};
        v.Format = DXGI_FORMAT_R32_TYPELESS;
        v.ViewDimension = D3D12_SRV_DIMENSION_BUFFER;
        v.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
        v.Buffer.NumElements = bytes / 4;
        v.Buffer.Flags = D3D12_BUFFER_SRV_FLAG_RAW;
        dev->CreateShaderResourceView(r, &v, at);
    }

    void cbv(ID3D12Resource* r, UINT size, D3D12_CPU_DESCRIPTOR_HANDLE at) {
        D3D12_CONSTANT_BUFFER_VIEW_DESC v{r->GetGPUVirtualAddress(), size};
        dev->CreateConstantBufferView(&v, at);
    }

    void wait() {
        check(queue->Signal(fence.Get(), ++fence_value), "ID3D12CommandQueue::Signal");
        if (fence->GetCompletedValue() < fence_value) {
            check(fence->SetEventOnCompletion(fence_value, event), "SetEventOnCompletion");
            WaitForSingleObject(event, INFINITE);
        }
        check(dev->GetDeviceRemovedReason(), "the D3D12 device (removed)");
    }

    std::vector<float> run(const Request& r) override {
        const size_t out_bytes = size_t(r.n) * r.width * 4;
        static const float unused_axis = 0.0f;  // the README: a one-float buffer for an unused coordinate
        const Bytes grid_bytes = r.grid.empty() ? Bytes(48, 0) : r.grid;  // and 48 zero bytes for an unused Grid
        // a constant buffer view is a multiple of 256 bytes
        auto params = upload(r.params.data(), r.params.size(), round_up(r.params.size(), 256));
        auto grid = upload(grid_bytes.data(), grid_bytes.size(), round_up(grid_bytes.size(), 256));
        std::vector<ComPtr<ID3D12Resource>> axes;
        for (int i = 0; i < 3; ++i)
            axes.push_back(i < int(r.axes.size()) ? upload(r.axes[i].data(), r.axes[i].size(), r.axes[i].size())
                                                  : upload(&unused_axis, 4, 4));
        auto out = buffer(D3D12_HEAP_TYPE_DEFAULT, out_bytes, D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS,
                          D3D12_RESOURCE_STATE_COMMON);
        auto readback = buffer(D3D12_HEAP_TYPE_READBACK, out_bytes, D3D12_RESOURCE_FLAG_NONE,
                               D3D12_RESOURCE_STATE_COPY_DEST);

        D3D12_DESCRIPTOR_HEAP_DESC hd{D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV, 7,
                                      D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE, 0};
        ComPtr<ID3D12DescriptorHeap> heap;
        check(dev->CreateDescriptorHeap(&hd, IID_PPV_ARGS(&heap)), "CreateDescriptorHeap");
        auto slot = [&](int i) {
            D3D12_CPU_DESCRIPTOR_HANDLE h = heap->GetCPUDescriptorHandleForHeapStart();
            h.ptr += SIZE_T(i) * stride;
            return h;
        };
        cbv(params.Get(), static_cast<UINT>(round_up(r.params.size(), 256)), slot(0));
        raw_srv(tables.Get(), tables_bytes, slot(1));
        for (int i = 0; i < 3; ++i)
            raw_srv(axes[i].Get(), static_cast<UINT>(i < int(r.axes.size()) ? r.axes[i].size() : 4), slot(2 + i));
        D3D12_UNORDERED_ACCESS_VIEW_DESC u{};
        u.Format = DXGI_FORMAT_R32_TYPELESS;
        u.ViewDimension = D3D12_UAV_DIMENSION_BUFFER;
        u.Buffer.NumElements = static_cast<UINT>(out_bytes / 4);  // the shader's bound: GetDimensions on OUT
        u.Buffer.Flags = D3D12_BUFFER_UAV_FLAG_RAW;
        dev->CreateUnorderedAccessView(out.Get(), nullptr, &u, slot(5));
        cbv(grid.Get(), static_cast<UINT>(round_up(grid_bytes.size(), 256)), slot(6));

        check(alloc->Reset(), "ID3D12CommandAllocator::Reset");
        check(list->Reset(alloc.Get(), programs.at(r.entry).Get()), "ID3D12GraphicsCommandList::Reset");
        list->SetComputeRootSignature(root.Get());
        ID3D12DescriptorHeap* heaps[] = {heap.Get()};
        list->SetDescriptorHeaps(1, heaps);
        list->SetComputeRootDescriptorTable(0, heap->GetGPUDescriptorHandleForHeapStart());
        D3D12_RESOURCE_BARRIER b{};
        b.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        b.Transition.pResource = out.Get();
        b.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
        b.Transition.StateBefore = D3D12_RESOURCE_STATE_COMMON;
        b.Transition.StateAfter = D3D12_RESOURCE_STATE_UNORDERED_ACCESS;
        list->ResourceBarrier(1, &b);
        list->Dispatch(r.gx, r.gy, 1);
        b.Transition.StateBefore = D3D12_RESOURCE_STATE_UNORDERED_ACCESS;
        b.Transition.StateAfter = D3D12_RESOURCE_STATE_COPY_SOURCE;
        list->ResourceBarrier(1, &b);
        list->CopyBufferRegion(readback.Get(), 0, out.Get(), 0, out_bytes);
        check(list->Close(), "ID3D12GraphicsCommandList::Close");
        ID3D12CommandList* lists[] = {list.Get()};
        queue->ExecuteCommandLists(1, lists);
        wait();

        std::vector<float> values(out_bytes / 4);
        void* p = nullptr;
        D3D12_RANGE whole{0, out_bytes};
        check(readback->Map(0, &whole, &p), "ID3D12Resource::Map (readback)");
        std::memcpy(values.data(), p, out_bytes);
        D3D12_RANGE none{0, 0};
        readback->Unmap(0, &none);
        return values;
    }
};

std::unique_ptr<Backend> open(const std::string& api) {
    if (api == "d3d11") return std::make_unique<D3D11>();
    if (api == "d3d12") return std::make_unique<D3D12>();
    throw std::runtime_error("unknown --api " + api + ": d3d11 or d3d12");
}

}  // namespace

int main(int argc, char** argv) {
    _setmode(_fileno(stdin), _O_BINARY);
    _setmode(_fileno(stdout), _O_BINARY);
    std::string api = argc == 3 && std::string(argv[1]) == "--api" ? argv[2] : "";

    std::unique_ptr<Backend> backend;
    try {
        char magic[4];
        read_exact(magic, 4);
        if (std::memcmp(magic, "HNH1", 4) != 0) throw std::runtime_error("not an HNH1 init frame");
        Bytes tables = read_blob();
        std::vector<Bytes> blobs;
        for (uint32_t i = 0, count = read_u32(); i < count; ++i) {
            Bytes name = read_blob();
            blobs.push_back(read_blob());
        }
        backend = open(api);
        backend->load(tables, blobs);
        reply_text(0, backend->target);
    } catch (const Unavailable& e) {
        reply_text(2, e.what());
        return 2;
    } catch (const std::exception& e) {
        reply_text(1, e.what());
        return 1;
    }

    for (;;) {
        Request r;
        try {
            r.entry = read_u32(true);
        } catch (const Eof&) {
            return 0;
        } catch (const std::exception&) {
            return 1;
        }
        try {
            r.n = read_u32();
            r.width = read_u32();
            r.gx = read_u32();
            r.gy = read_u32();
            r.params = read_blob();
            r.grid = read_blob();
            for (uint32_t i = 0, count = read_u32(); i < count; ++i) r.axes.push_back(read_blob());
            std::vector<float> values = backend->run(r);
            reply(0, values.data(), values.size() * 4);
        } catch (const std::exception& e) {
            reply_text(1, e.what());
        }
    }
}
```

- [ ] **Step 2: its build.** Create `apps/hog-noise-tools/hosts/hlsl/build.bat`:

```bat
@echo off
rem HogNoise tools: build hlsl_host.exe, the HLSL host harness, with MSVC. The exe is gitignored.
rem Probes the standard vcvars64.bat locations for Visual Studio 2026 (folder 18), 2022 and 2019 (any edition, and the
rem Build Tools), as noise_oracle\build.bat does; no vswhere, whose "Program Files (x86)" path breaks a for /f set.
setlocal
set "HERE=%~dp0"
set "VCVARS="
for %%y in (18 2022 2019) do (
    for %%e in (Community Professional Enterprise BuildTools Preview) do (
        if not defined VCVARS if exist "%ProgramFiles%\Microsoft Visual Studio\%%y\%%e\VC\Auxiliary\Build\vcvars64.bat" set "VCVARS=%ProgramFiles%\Microsoft Visual Studio\%%y\%%e\VC\Auxiliary\Build\vcvars64.bat"
        if not defined VCVARS if exist "%ProgramFiles(x86)%\Microsoft Visual Studio\%%y\%%e\VC\Auxiliary\Build\vcvars64.bat" set "VCVARS=%ProgramFiles(x86)%\Microsoft Visual Studio\%%y\%%e\VC\Auxiliary\Build\vcvars64.bat"
    )
)
if not defined VCVARS goto :novs
echo using "%VCVARS%"
call "%VCVARS%" >nul
if errorlevel 1 exit /b 1
pushd "%HERE%"
cl /nologo /O2 /EHsc /std:c++17 /W4 /WX hlsl_host.cpp /Fe:hlsl_host.exe
set "RC=%errorlevel%"
if exist hlsl_host.obj del hlsl_host.obj
popd
exit /b %RC%

:novs
echo no Visual Studio C++ tools found under Program Files; install Visual Studio 2022 with the C++ workload
exit /b 1
```

- [ ] **Step 3: build it.**

Run: `cmd //c apps\\hog-noise-tools\\hosts\\hlsl\\build.bat`
Expected: `using "...vcvars64.bat"`, then `hlsl_host.cpp`, exit 0, and `hlsl_host.exe` beside it. It builds at `/W4 /WX`,
so a warning fails it. (`vcvars64.bat` may print `'vswhere.exe' is not recognized`; the oracle's build prints it too.)
`git status --short` shows the two new files and not the `.exe`.

- [ ] **Step 4: every hog case, on both.**

Run: `HOG_NOISE_REQUIRE_HOST=hlsl-d3d11,hlsl-d3d12 HOG_NOISE_HOST_TARGET="Microsoft Basic Render Driver" uv run pytest apps/hog-noise-tools/tests/hosts -n 0 -q -rs -k hlsl`
(`-k hlsl`: the target applies to every host, and on a machine with wgpu and moderngl `spirv-naga` and `glsl` open on
its own GPU and fail it. CI's `hlsl` job installs neither, so there they skip.)
Expected: 24 passed, 2 skipped. Every `hlsl` case passes: every hog case within `wgpu.json`, the seed-plus-one control, the rule at 0.9 of
its worst, the wrong-target refusal, the power-of-two grid against its points, and the dispatch past 65,535 workgroups,
on each host. The bit-for-bit test skips for both (it is `spirv-naga`'s claim alone). `test_hlsl.py` passes in full.
**A hog case that fails is a finding: stop and report it.**

- [ ] **Step 5: each binding, and the dispatch, mutated once.** Each mutant must fail. Edit, rebuild with step 3's
  command (a stale `.exe` is a skip, so the rebuild is not optional), run, restore, rebuild.
  - D3D11, `t2` and `t3` swapped: in `hlsl_host.cpp`, `{srvs[0].Get(), srvs[1].Get(), srvs[2].Get(), srvs[3].Get()}`
    becomes `{srvs[0].Get(), srvs[2].Get(), srvs[1].Get(), srvs[3].Get()}`. Run step 4's command with `-k "every_hog_case
    and d3d11"`: it **fails**.
  - D3D12, `XS` and `ZS` swapped: after the loop that fills `axes` in `D3D12::run`, add `std::swap(axes[0], axes[2]);`.
    Run with `-k "every_hog_case and d3d12"`: it **fails**.
  - The y row of workgroups dropped: in `hlsl.py`, `gx, gy, _ = workgroups(n)` becomes `gx, gy = workgroups(n)[0], 1`
    (no rebuild). Run with `-k "65535 and hlsl"`: both hosts **fail**.

- [ ] **Step 6: the gate.**

Run: `make check`
Expected: 9 of 9. With the harness built, the HLSL hosts run inside the gate too, each `pytest` worker compiling for
itself.

- [ ] **Step 7: commit.**

```bash
git add apps/hog-noise-tools/hosts/hlsl/hlsl_host.cpp apps/hog-noise-tools/hosts/hlsl/build.bat
git commit -s -F msg.txt   # "CI proof (b), task 4: the C++ harness, D3D11 and D3D12 on WARP"
```

### Task 5: CI, as a draft pull request

**Files:**
- Modify: `.github/workflows/hosts.yml`

- [ ] **Step 1: the `hlsl` job.** In `.github/workflows/hosts.yml`, replace:

```yaml
# The emitted shaders run in a host written from their README, on a software GPU, against the vectors (the CI proof's
# spec). spirv-naga runs on tests.yml's three GPU legs; this file holds the hosts those legs cannot run.
```

with:

```yaml
# The emitted shaders run in a host written from their README, on a software GPU, against the vectors (the CI proof's
# spec). spirv-naga runs on tests.yml's three GPU legs; this file holds the hosts those legs cannot run: the GLSL, and
# the HLSL, whose C++ harness only this file builds, so tests.yml's Windows legs skip it.
```

and append to `.github/workflows/hosts.yml`, after the `glsl` job:

```yaml
  hlsl:
    name: HLSL on WARP (Windows, D3D11 and D3D12)
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-python@v7
        with:
          python-version: "3.13"
      - name: Install
        run: |
          python -m pip install --upgrade pip
          python -m pip install -e "packages/python/hog-noise[dev]"
          python -m pip install --no-deps -e apps/hog-noise-tools
      - name: Build the harness
        # MSVC from the runner's Visual Studio: build.bat finds vcvars64.bat. The only place the harness is built.
        shell: cmd
        run: apps\hog-noise-tools\hosts\hlsl\build.bat
      - name: Test
        env:
          # fails instead of skipping when either host is missing, and unless each runs on WARP, whose adapter is
          # "Microsoft Basic Render Driver"; the line also names the API the host made its device with
          HOG_NOISE_REQUIRE_HOST: hlsl-d3d11,hlsl-d3d12
          HOG_NOISE_HOST_TARGET: Microsoft Basic Render Driver
        # -n 0: one process, so FXC compiles the five entry points once per host, not once per worker; -rA names each
        # test's outcome, so the log shows both hosts passed and not skipped
        run: pytest apps/hog-noise-tools/tests/hosts -rA -n 0
```

- [ ] **Step 2: commit the job.**

Run: `uv run python -I` on a script that parses `.github/workflows/hosts.yml` with PyYAML (`uv run --with pyyaml`) and
prints each job's name and steps. Expected: `glsl` and `hlsl`, the `hlsl` job's steps ending `Build the harness`,
`Test`.

```bash
git add .github/workflows/hosts.yml
git commit -s -F msg.txt   # "CI proof (b), task 5: the hlsl job builds the harness and requires both hosts on WARP"
```

- [ ] **Step 3: open the draft.** Push the branch and open a **draft** pull request against `main`, its body from
  `.github/pull_request_template.md`. Read CI with `gh pr checks <n> --watch`.
  Expected: every leg green. The `hlsl` job's log shows `Microsoft Basic Render Driver (D3D11)` and `(D3D12)` and every
  `[hlsl-d3d11]` and `[hlsl-d3d12]` test PASSED by name; `tests.yml`'s Windows legs show the HLSL hosts skipped, `not built`.

- [ ] **Step 4: the target check, made to fail in CI once (P-22).** A scratch commit sets the job's
  `HOG_NOISE_HOST_TARGET` to `not-warp`; push it, and the `hlsl` job **fails** on `HostTargetError` for both hosts.
  Then a new commit reverting it, never a force-push; read the job green again.

### Task 6: the documents

**Files:**
- Modify: `packages/python/hog-noise/src/hog_noise/shaders/README.md`, `README.md`, `apps/hog-noise-tools/README.md`,
  `Docs/standards/testing-project.md`, `Docs/glossary.md`

- [ ] **Step 1: what is proven.** In `packages/python/hog-noise/src/hog_noise/shaders/README.md`, replace:

```markdown
validates in its own language's tools. Two of them also run, each in a host written from this page alone
```

with:

```markdown
validates in its own language's tools. All three also run, each in a host written from this page alone
```

and replace:

```markdown
| `noise.<entry_point>.comp` | moderngl, OpenGL 4.3 | Mesa llvmpipe through EGL |
```

with:

```markdown
| `noise.<entry_point>.comp` | moderngl, OpenGL 4.3 | Mesa llvmpipe through EGL |
| `noise.hlsl` | FXC `cs_5_0` on D3D11, and DXC `cs_6_0` on D3D12, in a C++ harness | WARP |
```

and replace:

```markdown
Not yet run: `noise.hlsl` (D3D11 and D3D12 on WARP), and `noise.spv` read by a Vulkan driver (lavapipe), each its own
pull request.
```

with:

```markdown
Not yet run: `noise.spv` read by a Vulkan driver (lavapipe), its own pull request; and any of them on hardware outside
CI, where only the RTX 5090 they were written on has run them.
```

- [ ] **Step 2: the top README.** In `README.md`, replace:

```markdown
the SPIR-V through wgpu on WARP, llvmpipe and Metal, the GLSL in OpenGL on llvmpipe. The HLSL compiles and has not run yet.
```

with:

```markdown
the SPIR-V through wgpu on WARP, llvmpipe and Metal, the GLSL in OpenGL on llvmpipe, and the HLSL on WARP through Direct3D 11 (FXC) and Direct3D 12 (DXC).
```

The next sentence went stale when (a), [PR #49](https://github.com/HogJonny-AMZN/HogNoise/pull/49), ran the files; so
also replace:

```markdown
The HLSL, GLSL and SPIR-V files compile, but no host has run them against the vectors yet, and there is no Metal file.
```

with:

```markdown
The HLSL, GLSL and SPIR-V files run against the vectors only on CI's software adapters, and the SPIR-V only through naga, not yet a Vulkan driver; there is no Metal file.
```

- [ ] **Step 3: the app README.** In `apps/hog-noise-tools/README.md`, replace:

```markdown
| `glsl` | the five `noise.<entry_point>.comp` in moderngl | the `hosts` group and an OpenGL 4.3 context |

`uv run --group gpu --group hosts pytest apps/hog-noise-tools/tests/hosts` runs both. A host that is missing skips
```

with:

```markdown
| `glsl` | the five `noise.<entry_point>.comp` in moderngl | the `hosts` group and an OpenGL 4.3 context |
| `hlsl-d3d11`, `hlsl-d3d12` | `noise.hlsl`, compiled by FXC `cs_5_0` or DXC `cs_6_0`, in `hosts/hlsl/hlsl_host.exe` on WARP | Windows, the Windows SDK, and the harness built: `cmd /c apps\hog-noise-tools\hosts\hlsl\build.bat` (Visual Studio's C++ tools) |

`uv run --group gpu --group hosts pytest apps/hog-noise-tools/tests/hosts` runs them all. The harness is never built
by the tests: unbuilt, or older than its source, its hosts skip naming `build.bat`. A host that is missing skips
```

- [ ] **Step 4: the testing standard.** In `Docs/standards/testing-project.md`, replace:

```markdown
- **`HOG_NOISE_HOST_TARGET`** is part of the target line a host must run on: each GPU leg sets its pinned back end, the
  `glsl` job `llvmpipe`. A host on anything else fails before its first dispatch (the project ledger's P-22).
```

with:

```markdown
- **`HOG_NOISE_HOST_TARGET`** is part of the target line a host must run on: each GPU leg sets its pinned back end, the
  `glsl` job `llvmpipe`, the `hlsl` job `Microsoft Basic Render Driver` (WARP). A host on anything else fails before its
  first dispatch (the project ledger's P-22).
- **The `hlsl` job builds the C++ harness** (`apps/hog-noise-tools/hosts/hlsl/build.bat`) and requires
  `hlsl-d3d11,hlsl-d3d12`. Nothing else builds it, so `tests.yml`'s Windows legs skip both hosts: those legs have MSVC
  but did not ask for them. It runs `-n 0`, so FXC compiles the five entry points once per host, not once per worker.
```

- [ ] **Step 5: the glossary's host harness row.** In `Docs/glossary.md`, replace:

```markdown
Built in `hog_noise_tools.hosts` (`spirv-naga`, `glsl`);
```

with:

```markdown
Built in `hog_noise_tools.hosts` (`spirv-naga`, `glsl`, `hlsl-d3d11`, `hlsl-d3d12`);
```

- [ ] **Step 6: check and commit.**

Run: `uv run python tools/check_docs.py`, then `make check`
Expected: no drift; 9 of 9.

```bash
git add packages/python/hog-noise/src/hog_noise/shaders/README.md README.md apps/hog-noise-tools/README.md Docs/standards/testing-project.md Docs/glossary.md
git commit -s -F msg.txt   # "CI proof (b), task 6: the claims move from compiles to runs for the HLSL"
```

### Task 7: the board, the handoff, the journal

- [ ] **Step 1: the row lands.** `Docs/plan/board/2026-11-23-the-emitted-hlsl-runs-on-warp.md`: its state becomes
  Landed, with the date and a link to this pull request, what ran on what, and the numbers from Task 4 and CI; and its
  `**Section:**` becomes `now`, as (a)'s row did. `check_docs` refuses a landed row in any other section but a gate
  (`board-state`).
- [ ] **Step 2: what waited on it.** Three rows name this one in their `**Waits on:**` line: [the buffer-limit
  refusal](../../plan/board/2026-11-21-a-call-past-the-devices-buffer-limit.md), [the engine
  trials](../../plan/board/2026-11-18-engine-host-trials.md) and [lavapipe](../../plan/board/2026-11-23-the-emitted-spirv-runs-on-lavapipe.md).
  `check_docs` refuses a wait on a done row (`waits-on`), so in each, remove this row's link from the `Waits on` line,
  keep every other link there (the engine trials still wait on lavapipe), drop a line left empty, and say in the row's
  prose that the HLSL landed with this pull request. The lavapipe row also says what this plan decided for it
  (decision B6).
- [ ] **Step 3: the handoff and the journal.** `Docs/handoffs/CURRENT.md`, *Last updated*: this pull request, and that
  the PyPI condition's HLSL is met, the release still the owner's go. A journal file for the session.
- [ ] **Step 4: tick this plan's steps** and fill *Built* below with each task's command and result.

```bash
make check
git add <the named files>
git commit -s -F msg.txt   # "CI proof (b), task 7: the row lands; the handoff, the journal"
```

### Task 8: review, then out of draft

- [ ] **Step 1:** run the `local-review` skill on the diff and paste its table into the pull request's *Review*.
- [ ] **Step 2:** fix every finding below 7, or say why not, then re-run the gate.
- [ ] **Step 3:** fill the pull request body from the template: *Decisions* (this plan's and any taken on the way),
  *Verified* (each mutation's result, the target lines, the CI runs), *Not covered* (lavapipe; hardware; speed).
- [ ] **Step 4:** `gh pr ready <n>`, read CI, and assess the automated review when it arrives (the `review-and-pr`
  skill). The owner merges.

## Built

Filled by the build: each task's command, its result, and where the build departed from this plan and why.

## Decisions

Proposed; each is the owner's to take.

| # | Decision | Recommended | Alternative | Why |
| --- | --- | --- | --- | --- |
| B1 | Where the HLSL compiles | In Python, with the Windows SDK's `fxc.exe` and `dxc.exe` (`compile_shaders.find`), at the `shaders` job's profiles; the bytecode goes to the harness down its standard input | In the harness, through `D3DCompile` and `IDxcCompiler3` | The compilers and flags the `shaders` job already proves; the hash check stays in Python, before the compile; a refusal reaches the test with the compiler's own message; the C++ does D3D and nothing else |
| B2 | How the harness builds | `build.bat` and `cl`, `/W4 /WX`, as `noise_oracle/build.bat` builds the oracle | CMake | The repository's precedent and no new tool; one source file needs no build system |
| B3 | Who builds it | CI's `hlsl` job and the developer, by hand. The module never builds it: missing or older than its source, its hosts skip naming `build.bat` | Built on first use, as the oracle is | `tests.yml`'s Windows legs have MSVC and would build it and run the hosts unasked, where the WARP leg's `D3D12` target fails `hlsl-d3d11`; and `pytest -n auto` workers would each rebuild a stale `.exe` over one another is running. Both seen in the trial |
| B4 | The adapter | WARP, always: `IDXGIFactory4::EnumWarpAdapter` | A flag for the hardware adapter too | The spec's target, the same in CI as on the owner's machine. The 5090's D3D12 already runs the shader through `spirv-naga`; hardware D3D11 and D3D12 can be a row of their own if they are wanted |
| B5 | CI jobs | One `hlsl` job for both hosts, `-n 0`, each host required by name and target-checked | One job per host, the spec's words | One harness, one build, one runner; `-n 0` compiles each host's programs once. Each host still fails alone |
| B6 | The lavapipe pull request (c) | It shares this harness's frame format, `HNH1`, not its code: the harness is D3D, Windows-only by nature. Whether a Vulkan back end joins this file or is its own, built on Linux, is (c)'s plan's decision | A Vulkan back end in this file now | (c) is planned when this merges, against code that has run; the frame format is the contract worth keeping |

## Self-review against the spec

- **What gets built:** the two hosts of the spec's table, `hlsl-d3d11` and `hlsl-d3d12`: Tasks 3 and 4. The C++ harness
  is persistent, one process per run, request and reply over standard input and output: Task 4. Written from the README:
  Task 1 puts what it needs there first, and nothing imports `_Gpu`.
- **Each host checks its file's hash before its first dispatch:** `verified("hlsl")` and `verified_tables()` in `_open`.
- **Tests:** every hog case, the seed-plus-one control and the rule at 0.9 of its worst, per host: (a)'s `test_hosts.py`,
  parametrised over `HOSTS`. Skips naming why; `HOG_NOISE_REQUIRE_HOST` makes them failures.
- **Each host asserts its target:** `check_target` through `open_host`; the wrong-target control in `test_hosts.py`; and
  once in CI, Task 5 step 4.
- **CI:** the `hlsl` job in `hosts.yml`: Task 5. **The README's claims:** Task 6.
- **Acceptance:** Task 4 step 4 and CI, `wgpu.json` unmodified. **Open risk, FXC's HLSL on D3D11:** settled by the
  trial: every pipeline was created.

## Terms introduced

None. Checked: *host harness* and *host target* have glossary rows (Task 6 adds the two hosts to the first), and WARP
is in the *GPU adapter* row; the `HNH1` frame is named only inside
`hlsl_host.cpp`, and *descriptor table*, *root descriptor* and *constant buffer view* are D3D12's own terms.
