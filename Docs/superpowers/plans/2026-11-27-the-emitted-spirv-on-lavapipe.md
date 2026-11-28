# The CI proof, third pull request: the emitted SPIR-V in a Vulkan driver, on lavapipe

**Status:** Accepted 2026-11-27, by the merge of [PR #64](https://github.com/HogJonny-AMZN/HogNoise/pull/64)
(`2792a39`, 23:30 UTC), with L1 to L7 as recommended; landed 2026-11-28 in [PR #65](https://github.com/HogJonny-AMZN/HogNoise/pull/65) (`bf18d0a`).
Proposed 2026-11-27, on the owner's "Do it" for (c)'s plan. Written from [the spec](../specs/2026-11-22-emitted-shaders-ci-proof.md),
Accepted 2026-11-22, after its second pull request ([PR #59](https://github.com/HogJonny-AMZN/HogNoise/pull/59),
merged as `3a83792`) built the C++ harness this one shares. Trial-run before it was proposed: its code is the branch
[`trial/spirv-on-lavapipe`](https://github.com/HogJonny-AMZN/HogNoise/tree/trial/spirv-on-lavapipe), one commit per
task (decision L1). The build ticks each step as it lands.
**Board:** [`2026-11-23-the-emitted-spirv-runs-on-lavapipe`](../../plan/board/2026-11-23-the-emitted-spirv-runs-on-lavapipe.md)

> **For agentic workers:** REQUIRED SUB-SKILL: use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to carry this out task by task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** the shipped `noise.spv`, given as bytes to a Vulkan driver, runs on Mesa's lavapipe in CI, bound only as the
shaders README says, and passes every hog case within `vectors/tolerance/wgpu.json`, unmodified. Until now no driver
has consumed those bytes: wgpu 0.33 has no SPIR-V passthrough, so `spirv-naga` has naga read the file back into its own
IR (the spec's decision 1).

**Architecture:** one host, `spirv-vulkan`, in `hog_noise_tools.hosts.vulkan`, over a persistent C++ process,
`apps/hog-noise-tools/hosts/vulkan/vulkan_host`, built on Linux by g++ against the Vulkan loader. It speaks the HLSL
harness's frames, which move out of `hlsl_host.cpp` into a header both harnesses include, `hosts/frames.h`; Python
drives both through one class, `hosts.harness.Harness`, moved out of `hosts.hlsl`. The harness opens the first CPU
device (lavapipe), makes one shader module of `noise.spv` and one compute pipeline per entry point, each naming its
entry in `pName`, and for each request binds the README's seven bindings, dispatches what Python computed, and reads
binding 5 back after a pipeline barrier. `HostSampler`, `renderings`, the hash and target checks and every test in
`test_hosts.py` are (a)'s, unchanged: the host joins `hosts.HOSTS`, and every acceptance test and control runs on it.

**Tech stack:** Python 3.11 to 3.13, numpy; C++17 built by g++ (`build.sh`), Vulkan 1.1 through the loader
(`libvulkan-dev`), Mesa's lavapipe (`mesa-vulkan-drivers`); pytest through the `pytest` console script (`uv run
pytest`, never `python -m pytest`); `make check` as the gate.

---

## Before you start

- Read the spec, then (b)'s plan, [`2026-11-23-the-emitted-hlsl-on-warp.md`](2026-11-23-the-emitted-hlsl-on-warp.md):
  this plan moves part of (b)'s harness and follows its conventions without repeating them.
- Read [the project ledger](../../standards/failure-modes-project.md), above all P-14 (never `python -`), P-22 (a leg
  asserts the thing it exists to test), P-23 (a plan's code is trial-run in task order) and P-27 (a changed fact is
  searched for across `Docs/`).
- Work in a worktree on a branch from `origin/main`. Commits are signed off (`git commit -s`) with the owner's identity
  and no AI attribution.
- **Linux for every step that builds or runs the Vulkan harness:** g++, `libvulkan-dev` and `mesa-vulkan-drivers`. On
  Windows, Docker with Ubuntu 26.04 is enough (the trial's container, below). **Windows for the HLSL harness,** as (b):
  Tasks 1 and 2 change it, and it must still pass on WARP.
- Before every gate run, `uv run ruff format .` and `uv run ruff check --fix .`; revert `vectors/portability.md` if the
  gate re-stamps it; stage named paths only.
- **A rule the host fails is a finding for the owner**, never a rule loosened in this pull request
  (`vectors/README.md`, *Tolerance files*). Stop and report it.

## Facts this plan rests on

Read from the code at `f49ba42` (the merge of [PR #63](https://github.com/HogJonny-AMZN/HogNoise/pull/63)) and measured
on the owner's machine, not assumed:

- **`noise.spv`** is SPIR-V 1.0 with `SPV_KHR_storage_buffer_storage_class`, which is core in Vulkan 1.1, and validates
  with `spirv-val --target-env vulkan1.1`. It has five `OpEntryPoint`s, each `LocalSize 64`. Its bindings are all in
  set 0: 0 and 6 `Uniform`, 1 to 5 `StorageBuffer`, 1 to 4 `NonWritable`. Every entry point returns when its index is
  past `arrayLength` of `OUT`, so `OUT`'s descriptor range must be exactly the output, as on D3D.
- **Lavapipe on CI's image.** `ubuntu-latest` is Ubuntu 26.04 with Mesa 26.0.8-1ubuntu0.3. In a container of the same
  release (`ubuntu:26.04`, 26.04.1 LTS; `libvulkan-dev` 1.4.341, g++ 15.2), `vulkaninfo --summary` gives one device:
  `deviceType` `PHYSICAL_DEVICE_TYPE_CPU`, `deviceName` `llvmpipe (LLVM 21.1.8, 256 bits)`, `apiVersion` 1.4.335,
  `driverInfo` Mesa 26.0.8-1ubuntu0.3. **Lavapipe calls itself llvmpipe,** the name Mesa's OpenGL driver has too (the
  `glsl` job's P-22 note).
- **Ubuntu 26.04's Python is 3.14,** outside `hog-noise`'s `<3.14`; the container used `uv` for a 3.13 environment. CI's
  job installs 3.13 with `setup-python`, as the other host jobs do.
- **What (b) left for (c)** (its decision B6): share the frame format `HNH1`; whether the Vulkan back end joins
  `hlsl_host.cpp` or is its own is this plan's decision (L2, L3).
- **The frames are D3D-free already.** In `hlsl_host.cpp` at `f49ba42`, everything but `check`, `utf8`, `warp_adapter`,
  `describe` and the two D3D back ends (the frames, the refusals, the shapes, `Backend`, `round_up` and `main`'s loop)
  uses only the C++ standard library and `_setmode`. Task 1 moves exactly that, by a script, so the D3D code is
  byte for byte what (b) built.

## Files

| File | Responsibility |
| --- | --- |
| Create `apps/hog-noise-tools/hosts/frames.h` | The frames, their refusals, the entry points' shapes, `Backend`, and `serve(argc, argv, open)`, the loop every harness runs |
| Modify `apps/hog-noise-tools/hosts/hlsl/hlsl_host.cpp` | Includes `frames.h`; keeps D3D11, D3D12 and WARP; its factory is `open_backend` |
| Create `apps/hog-noise-tools/src/hog_noise_tools/hosts/harness.py` | `Harness`, `built` and `blob`, moved from `hosts.hlsl`: the process, the frames, the watchdog, standard error in a file |
| Modify `apps/hog-noise-tools/src/hog_noise_tools/hosts/hlsl.py` | `Hlsl(Harness)`; its harness is stale against `frames.h` too |
| Create `apps/hog-noise-tools/hosts/vulkan/vulkan_host.cpp` | The Vulkan back end: the CPU device, the README's bindings, one dispatch per request |
| Create `apps/hog-noise-tools/hosts/vulkan/build.sh` | g++ builds it, `-Wall -Wextra -Werror`, against `-lvulkan` |
| Create `apps/hog-noise-tools/src/hog_noise_tools/hosts/vulkan.py` | The `spirv-vulkan` host: Linux, built, hashed `noise.spv` once per entry point |
| Modify `apps/hog-noise-tools/src/hog_noise_tools/hosts/__init__.py` | `HOSTS` gains `spirv-vulkan` |
| Create `apps/hog-noise-tools/tests/hosts/test_harness.py`, `test_frames.py`, `test_vulkan.py`; modify `test_hlsl.py` | How Python drives any harness; the frame refusals on both harnesses; the Vulkan host's own paths; the HLSL hosts' own paths |
| Modify `.gitignore`, `.github/workflows/hosts.yml` | The built harness; a `spirv-vulkan` job |
| Modify the shaders README, `README.md`, `apps/hog-noise-tools/README.md`, `Docs/standards/testing-project.md`, `Docs/glossary.md` | The claims, how to build and run the host, the fifth host |
| Modify the board row, `Docs/handoffs/CURRENT.md`, today's journal | Done includes the documents |

---

Each task takes its files from the trial branch's commit for it: `git checkout <commit> -- <paths>`, then the task's
command, then a commit. The code is read and reviewed there, where it ran (decision L1).

### Task 1: the frames move to a header

**Commit:** `9afee74`. **Files:** `apps/hog-noise-tools/hosts/frames.h`, `apps/hog-noise-tools/hosts/hlsl/hlsl_host.cpp`.

- [x] **Step 1:** take the two files from `9afee74`. In the trial, a script cut `frames.h` out of `hlsl_host.cpp` and
  the result was checked: every line `frames.h` holds was removed from `hlsl_host.cpp`, and the D3D code is unchanged.
  The factory is `open_backend`, because a function named `open` was ambiguous with the CRT's (MSVC C2672).
- [x] **Step 2:** rebuild and run the HLSL hosts on WARP:

```bash
cmd //c "apps\hog-noise-tools\hosts\hlsl\build.bat"
HOG_NOISE_REQUIRE_HOST=hlsl-d3d11,hlsl-d3d12 HOG_NOISE_HOST_TARGET="Microsoft Basic Render Driver" \
  uv run pytest apps/hog-noise-tools/tests/hosts -q -n 0
```

Expected: the build passes at `/W4 /WX`, then 77 passed, 17 skipped (the `spirv-naga` and `glsl` cases, without
`wgpu` or `moderngl`).

### Task 2: what Python's harnesses share

**Commit:** `06b5cd8`. **Files:** `hosts/harness.py` (new), `hosts/hlsl.py`, `tests/hosts/test_harness.py` (new),
`tests/hosts/test_hlsl.py`.

- [x] **Step 1:** take the four files from `06b5cd8`. `Harness`, `built` and `blob` move from `hosts.hlsl` to
  `hosts.harness`; `Hlsl` keeps its signature, `(api, programs, tables, command=None)`, and `harness()` checks the
  `.exe` against `hlsl_host.cpp` and `frames.h`. The stand-in tests move to `test_harness.py`. **The frame refusals stay
  in `test_hlsl.py`** until Task 3 moves them, so no commit drops a test.
- [x] **Step 2:** Task 1's command, after a rebuild. Expected: 82 passed, 17 skipped.

### Task 3: the Vulkan host's tests, before its code

**Commit:** `054b9f5`. **Files:** `tests/hosts/test_frames.py` (new), `tests/hosts/test_vulkan.py` (new),
`tests/hosts/test_hlsl.py`.

- [x] **Step 1:** take the three files from `054b9f5`. `test_frames.py` runs the eleven frame refusals on each built
  harness, parametrised `hlsl` (`--api d3d12`) and `vulkan`; `test_hlsl.py` loses them. `test_vulkan.py` covers:
  off Linux, never built, and older than its source or `frames.h` (each unavailable, naming `build.sh`); bytes that are
  not whole SPIR-V words, and a module whose `sample_grid` entry is renamed `sample_gri_` (each an error, never a skip);
  an unknown `--api`; no Vulkan driver (`VK_DRIVER_FILES` and `VK_ICD_FILENAMES` at a missing file: unavailable,
  naming what was found); and the harness ending when its input closes.
- [x] **Step 2:** Task 1's command. Expected: 2 errors during collection, `cannot import name 'vulkan'`.

### Task 4: the harness and the host

**Commit:** `e19526a`. **Files:** `hosts/vulkan/vulkan_host.cpp`, `hosts/vulkan/build.sh`, `hosts/vulkan.py`,
`hosts/__init__.py`, `.gitignore`.

- [x] **Step 1:** take the five files from `e19526a`. What the harness does, by line of `vulkan_host.cpp`: an instance
  at Vulkan 1.1 (77); the first `VK_PHYSICAL_DEVICE_TYPE_CPU` device, else unavailable, naming every device found (94);
  the target line, the device's name and its Vulkan version (104); host-visible, coherent buffers; `OUT`'s range
  exactly `n * width * 4` bytes (230, 256); a barrier from the shader's writes to the host's read (299-300) before the
  read back. Every create-info is zeroed by one helper, `info<T>(sType)`, which g++'s
  `-Wmissing-field-initializers` required.
- [x] **Step 2:** on Linux, build and run with the host required on llvmpipe:

```bash
sh apps/hog-noise-tools/hosts/vulkan/build.sh
HOG_NOISE_REQUIRE_HOST=spirv-vulkan HOG_NOISE_HOST_TARGET=llvmpipe \
  uv run pytest apps/hog-noise-tools/tests/hosts -q -rA -n 0
```

Expected: 79 passed, 47 skipped. Every hog case on `spirv-vulkan` within `wgpu.json` unmodified, both controls
failing as they must, the power-of-two grid equal to its points, the dispatch past 65,535 workgroups reaching its last
points, the wrong-target control refusing, and the eleven `test_frames[vulkan]` cases.

- [x] **Step 3:** on Windows, Task 1's command after a rebuild. Expected: 86 passed, 40 skipped; the Vulkan tests
  skip, naming Linux.
- [x] **Step 4: the mutants.** Each, in `vulkan_host.cpp`, rebuilt and run with Step 2's command, then restored from a
  copy (never `git checkout --`) and rebuilt. Expected: x and y workgroups swapped, 3 failed; one entry name for every
  pipeline, 3 failed; `OUT`'s range one point short, 2 failed; `frames.h` dropped from `vulkan.harness`'s sources (in
  `vulkan.py`), 1 failed.

### Task 5: CI

**Commit:** `4acd583`. **File:** `.github/workflows/hosts.yml`.

- [x] **Step 1:** take it from `4acd583`: a `spirv-vulkan` job on `ubuntu-latest` installs Python 3.13,
  `mesa-vulkan-drivers libvulkan-dev vulkan-tools g++`, prints `vulkaninfo --summary`, builds the harness and runs the
  hosts tests with `HOG_NOISE_REQUIRE_HOST=spirv-vulkan`, `HOG_NOISE_HOST_TARGET=llvmpipe`, `-rA -n 0`.
- [x] **Step 2:** open the pull request as a draft and read the job: `spirv-vulkan` passes by name on every hog case,
  and `vulkaninfo` names the CPU device. Not run in the trial: `hosts.yml` runs on pull requests and on `main` only.
- [x] **Step 3: the target control in CI**, as (b)'s Task 5 step 4: a scratch commit sets
  `HOG_NOISE_HOST_TARGET: not-lavapipe`; the job must fail with `HostTargetError`; revert it.

### Task 6: the documents

**Commit:** `17c730a`. **Files:** the shaders README, `README.md`, `apps/hog-noise-tools/README.md`,
`Docs/standards/testing-project.md`, `Docs/glossary.md`.

- [x] **Step 1:** take them from `17c730a`. The shaders README's *What is proven* gains the Vulkan row and what a Vulkan
  host binds, and its "Not yet run" sentence becomes what is not proven on a hardware GPU. The glossary's *host
  harness* row names all five hosts, which is every host the spec lists.
- [x] **Step 2:** P-27: search `Docs/`, the READMEs and `llms.txt` for the hosts, `lavapipe` and "no driver", and fix
  any claim this makes untrue. Then the gate, bounded:

```bash
timeout 900 make check
```

Expected: 9 of 9. Exit 124 is the hang in *The trial*: report it with which processes are left, never rerun it until
it passes.

### Task 7: the board, the handoff, the journal

- [x] **Step 1:** the row lands: Landed, the date (the merge's, in UTC, P-31), this pull request, what ran on what, and
  the numbers from Task 4 and CI; section `now`.
- [x] **Step 2:** what waited on it: [the engine trials](../../plan/board/2026-11-18-engine-host-trials.md) name this
  row in their `Waits on`; remove it there and say in the row's prose that the SPIR-V ran on lavapipe. [The CI
  proof's own row](../../plan/board/2026-11-18-emitted-shaders-run-against-the-vectors.md) lists (c) as its third pull
  request: say there that it landed, so all three have.
- [x] **Step 3:** the handoff's *Last updated*, and the journal. Tick this plan's steps and fill *Built*.

### Task 8: review, then out of draft

- [x] **Step 1:** the `local-review` skill on the diff; its table in the pull request's *Review*.
- [x] **Step 2:** fix every finding below 7 or say why not; re-run the gate.
- [x] **Step 3:** `gh pr ready`, read CI, assess the automated review. The owner merges.

## Built

In [PR #65](https://github.com/HogJonny-AMZN/HogNoise/pull/65), on the owner's machine (as *The trial*) and in CI, each
task's files taken from its trial commit and its command run again:

| Task | Where | Result |
| --- | --- | --- |
| 1 | Windows, WARP | built at `/W4 /WX`; 77 passed, 17 skipped |
| 2 | Windows, WARP | 82 passed, 17 skipped; collected ids 94 to 99, none lost (`test_a_harness_older_than_its_source_is_unavailable` split into its source and `frames.h` cases) |
| 3 | Windows | 2 collection errors, `cannot import name 'vulkan'` |
| 4, step 3 | Windows, WARP | 86 passed, 40 skipped |
| 4, steps 2 and 4 | the trial's container | not repeated: after the commit, `apps/` and `.gitignore` are the same git trees as `e19526a`'s (`282d148`, `40ddb6e`), so the trial's run and mutants are of this code |
| 5, step 2 | CI, `spirv-vulkan` | 47 s; 79 passed, 47 skipped; `vulkaninfo`: `llvmpipe (LLVM 21.1.8, 256 bits)`, `PHYSICAL_DEVICE_TYPE_CPU`, `apiVersion` 1.4.335, Mesa 26.0.8-1ubuntu0.3; `test_every_hog_case_passes_within_the_wgpu_tolerance[spirv-vulkan]` passed, and the eleven `test_frames` cases |
| 5, step 3 | CI, scratch `00e1096` | told `not-lavapipe`, the job failed: 73 passed, 46 skipped, 7 errors, every `spirv-vulkan` case `HostTargetError: spirv-vulkan runs on 'llvmpipe (LLVM 21.1.8, 256 bits) (Vulkan 1.4.335)'`; reverted, the file restored from a copy |
| 6 | Windows | `timeout 900 make check`: 9 of 9, 3,377 passed, 136 skipped, in 102 s; no hang |
| 8 | Windows, WARP | the review's fixes: `validate` refuses workgroups that are not the README's *Dispatch*, which it had passed with output partly zeros (the review's probe, on main's harness too); seven new `test_frames` cases and two `test_harness` cases; 93 passed, 47 skipped. A mutant taking the workgroup check out failed the three workgroup cases |

The review's Vulkan fixes (a failed instance or device lookup is an error, not absence; `make` releases a partial
buffer) are built and run by CI's `spirv-vulkan` job alone: neither path has a test, since lavapipe does not fail them.

Task 7's row says Built in this pull request, not Landed with a date: P-31 has a record written before the merge name
the pull request and leave the date to the status fix on main.

## The trial

Run 2026-11-26 and 27 on the owner's machine (Windows 11 Pro 10.0.26300, MSVC 17.14, Windows SDK 10.0.26100) and, for
Linux, in a Docker container of `ubuntu:26.04` with the packages in *Facts*. Each task's command ran on its commit
alone: each commit checked out, the HLSL harness rebuilt (a checkout makes it older than its sources, so it skips),
and on Linux the commit's tree exported by `git archive` into the container.

| Task | Commit | Where | Result |
| --- | --- | --- | --- |
| 1 | `9afee74` | Windows, WARP | built at `/W4 /WX`; 77 passed, 17 skipped |
| 2 | `06b5cd8` | Windows, WARP | 82 passed, 17 skipped |
| 3 | `054b9f5` | Windows | 2 collection errors, `cannot import name 'vulkan'` |
| 4 | `e19526a` | Linux, lavapipe | built with `-Werror`; 79 passed, 47 skipped, `spirv-vulkan` required on llvmpipe |
| 4 | `e19526a` | Windows, WARP | 86 passed, 40 skipped |
| 4, mutants | the trial's tree | Linux, lavapipe | x and y swapped: 3 failed; one entry name: 3 failed; `OUT` one point short: 2 failed; `frames.h` not a source: 1 failed; each restored byte for byte |
| 6 | `336da95`, then `17c730a` | Windows | `make check` 9 of 9, 3,377 passed, 136 skipped, the HLSL harness built; `17c730a` adds the glossary row, and its commit hook's eight non-test checks passed |

**What the trial changed:**

- **Task 2 dropped eleven tests for one commit.** The first cut moved the frame refusals out of `test_hlsl.py` in
  Task 2 and into `test_frames.py` in Task 3, so Task 2's commit passed with eleven fewer tests than Task 1's. Found by
  comparing the tests each commit collects (`pytest --collect-only -q`), not by its pass count; the refusals now move
  in Task 3, and Task 2 passes 82, the 71 it had plus those eleven.
- **An unused import,** `struct` in `test_harness.py`, found by the commit hook's lint.
- **The glossary's host row** said the spec "lists the rest"; with the fifth host there is no rest (P-27's search).

**A hang, once in six gate runs.** The first `make check` on the trial's code stopped at 98% of the tests and was
found 16 hours later. Every one of its 24 pytest workers was idle, waiting for work, and the controller was waiting
for an event, so no test was running; two workers still held their cached `hlsl_host.exe` processes, which nothing
closes before a worker exits. The machine did not sleep (no power events in the System log). Five runs of the same
tests after it passed in 96 to 158 s. The cause is not known; it is recorded here and under *Not covered*, and Task 6
runs the gate under `timeout`, so a hang stops in 15 minutes and is reported instead of waited out.

## Decisions

| # | Decision | Recommended | Alternative | Why |
| --- | --- | --- | --- | --- |
| L1 | How the plan carries its code | A pushed trial branch, one commit per task, in task order; each task names its commit, files, command and result. The build takes the commits onto a branch from `main` | The code inline in the plan, as (b)'s 1,500 lines did | The code is reviewed where it ran, and each task's result is reproducible from its commit; a copy in prose drifts from the file it copies, and inline it would be about 1,350 lines of this plan |
| L2 | What the two harnesses share | The frames' code: `frames.h` in C++ and `hosts.harness` in Python, with `test_frames` holding both harnesses to the same refusals | A second copy of the frame code in `vulkan_host.cpp` | (b)'s B6 shared the format and not the code because its harness was D3D; the frame code turned out D3D-free, so one copy means one set of refusals, tested on both |
| L3 | Where the Vulkan back end lives | Its own file, `vulkan_host.cpp`, built on Linux by `build.sh` | A `--api vulkan` back end in `hlsl_host.cpp` | Each file needs only its own platform: MSVC and the Windows SDK, or g++ and the loader. Joined, either build needs both |
| L4 | The device | The first CPU device, always; with none, unavailable, naming each device found | The first device, or a flag for a hardware GPU | The spec's target, the same in CI and locally. The 5090's Vulkan already runs the SPIR-V through `spirv-naga`; a driver on hardware can be a row of its own |
| L5 | The target CI asserts | `llvmpipe`, the device's own name | `lavapipe`, the driver's | The device calls itself `llvmpipe (LLVM ...)`, so `lavapipe` matches nothing. The OpenGL driver's name is the same; the harness opens only Vulkan's CPU device, and its target line ends in its Vulkan version |
| L6 | The driver-refusal test | A valid module whose `sample_grid` entry is renamed: the pipeline names an entry the module lacks, and lavapipe refuses it | Invalid bytes to `vkCreateShaderModule` | A driver without validation layers need not reject invalid SPIR-V: that is undefined behaviour. The renamed entry is also invalid usage in the specification, so the test holds lavapipe alone, measured to refuse it; the harness refuses bytes that are not whole words itself |
| L7 | How the harness builds | `build.sh` and g++, `-Wall -Wextra -Werror`, as `build.bat` builds (b)'s | CMake | (b)'s B2: one source file needs no build system |

## Not covered

- **The barrier is untested.** Lavapipe's memory is coherent, so dropping the barrier before the read back still passed.
  It stays because the specification requires it, and the README says why.
- **Hardware Vulkan.** The harness opens a CPU device alone; the hosts' claims rest on CI's software adapters, as the
  shaders README says.
- **A Windows Vulkan build.** `build.sh` is Linux-only, and on Windows the host skips naming Linux.
- **The one hang in six gate runs** (*The trial*), cause unknown.

## Self-review against the spec

- **What gets built:** the spec's `spirv-vulkan` row, "the same harness, a Vulkan back end": Tasks 1 to 4, the shared
  frames and loop with a back end of its own (L2, L3). Written from the README: nothing imports `_Gpu`.
- **Each host checks its file's hash before its first dispatch:** `verified("spirv")` and `verified_tables()` in
  `vulkan.open_host`.
- **Tests:** every hog case and both controls, through (a)'s `test_hosts.py`; skips name why, and
  `HOG_NOISE_REQUIRE_HOST` makes them failures.
- **Each host asserts its target:** `check_target` through `open_host`; the wrong-target control; once in CI, Task 5
  step 3.
- **CI:** Task 5. **The README's claims:** Task 6. **Acceptance:** Task 4 step 2, and CI, `wgpu.json` unmodified.

## Terms introduced

None. *Host harness* and *host target* have glossary rows (Task 6 adds the fifth host to the first); *lavapipe* and
*llvmpipe* are Mesa's names and appear where they are used; `HNH1` and `frames.h` are named only in the code and in
`apps/hog-noise-tools/README.md`.
