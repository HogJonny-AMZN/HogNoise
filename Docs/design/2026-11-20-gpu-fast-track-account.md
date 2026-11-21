# The GPU fast track, accounted for: what holds it up, and what does not yet

**Status:** Proposed. The evidence is as measured. The verdicts on the gaps are recommendations, and each one waits on
the owner.
**Board:** [`2026-11-18-harden-the-gpu-fast-track`](../plan/board/2026-11-18-harden-the-gpu-fast-track.md)

The owner, 2026-11-18: having fast-tracked [the GPU work](2026-11-01-gpu-fast-track.md), "know what shored it up and
that it was done correctly", before the host work. This page takes each claim the track makes, the evidence behind it
with its commit and run, and each gap with a verdict. The new measurements were taken on 2026-11-20 at `4723216`
(`main` after [PR #38](https://github.com/HogJonny-AMZN/HogNoise/pull/38)), on the owner's machine: Windows 11 Pro
10.0.26300, an NVIDIA GeForce RTX 5090 (driver 32.0.16.1088), wgpu 0.33.0.

## The short answer

The track was done correctly inside the range it measured. Every feature runs on wgpu. Each one is held to a measured
bound, and on the feature tested for it (`fnl/simplex_fbm`) the bound is tight enough that an off-by-one seed, or a
rule at 0.9 of the worst drift, fails. CI checks this
on two software adapters on every push. The emitted HLSL, GLSL and SPIR-V are what the pinned naga writes, and each one
compiles in its own language's tools.

What it does not yet hold up is anything outside that range:

- coordinates past 4,096 units;
- any GPU vendor but NVIDIA;
- Apple and Metal;
- speed;
- a host other than wgpu running the shipped files.

None of these gaps is a defect found. Each is a claim that nobody has made yet, and the README already says so. Two
small rough edges did turn up while measuring: the two adapter variables do not combine, and nothing has been tried
past a device's buffer limit (gaps 6 and 7).

## The claims, and what holds them

| # | Claim | Evidence | Holds? |
| --- | --- | --- | --- |
| C1 | Every feature runs on wgpu, and only when asked for | `test_every_feature_builds_a_sampler` and `test_every_pipeline_builds` (all five entry points) in [`test_gpu.py`](../../packages/python/hog-noise/tests/test_gpu.py). `test_the_rung_is_registered_override_only` and `test_an_installed_wgpu_never_changes_the_ladder`. The boundary test holds `import hog_noise` to numpy alone | Yes |
| C2 | Each feature is within a measured bound of the CPU | [`vectors/tolerance/wgpu.json`](../../vectors/tolerance/wgpu.json): 125 rules over 116 features (110 continuous, 15 discrete), derived by `hog-noise-measure-gpu derive` from the worst of the four adapters, by three rules (see *How the bounds are derived*, below). The records it was derived from are in [`reports/gpu/0d419e9/`](../../vectors/reports/gpu/0d419e9/record.md) | Yes, at frequency 0.01 and noise coordinates up to 40.96 (4,096 units): the file's own `range` |
| C3 | The bound is tight enough to mean something | `test_a_seed_off_by_one_fails`, and `test_a_rule_at_0_9_of_its_worst_fails`, which uses the worst drift of the adapter the test is running on. Rerun today as a control on the 5090's D3D12: shifting the seed by one fails all 3 `simplex_fbm` cases. Both tests cover `fnl/simplex_fbm` only | Yes for that feature. The other 115 rules come from the same derivation, but no test tightens them |
| C4 | The measurement describes the shader that ships | Between `0d419e9` (measured) and `4723216`, `noise.wgsl` changed only a comment (`git diff 0d419e9 4723216 -- packages/python/hog-noise/src/hog_noise/wgsl/`). `gpu.py` gained input checks, not arithmetic. CI rejudges all 368 hog cases on every push | Yes |
| C5 | It holds on more than the adapter it was tuned on | Four adapters in the records: the RTX 5090 (Vulkan), WARP twice (D3D12, CI and local) and llvmpipe (Vulkan). On every push, CI's WARP and llvmpipe legs run with `HOG_NOISE_REQUIRE_GPU=1`, so a leg that loses its adapter fails instead of skipping. The last `tests` run was [44861482689](https://github.com/HogJonny-AMZN/HogNoise/actions/runs/44861482689) on `fc9e4eb`: 6 of 6 jobs green, and 13 of 13 checks on that commit across every workflow. **New today:** the 5090 passes all 368 cases on Vulkan, on D3D12 and on OpenGL. D3D12 is naga's HLSL path; the stage 1 spike ran it on the 5090 for one feature, OpenSimplex2, and this is the first run of the whole shader there. OpenGL is naga's GLSL path, and this is its first run | Yes for NVIDIA and two software rasterisers. Nothing else has been tried |
| C6 | The CPU it is judged against is right | The GPU is judged against the hog set, which is the numpy rendering, and numba matches it bit for bit. The CPU is judged against the originals separately ([`portability.md`](../../vectors/portability.md)). Against FastNoiseLite, 132 rows: 8 exact, 74 within 1e-6, 48 within 1e-4, and 2 within 1e-2 (`simplex_pingpong`, accepted by the owner 2026-09-13). Against FastNoiseSIMD, 10 rows: 1 exact, 7 within 1e-4, 2 within 1e-2 | Yes, in two steps: the GPU is never compared with the originals directly, so its distance from them is up to the sum of the two bounds |
| C7 | The emitted shaders are its WGSL | On every push, [`shaders.yml`](../../.github/workflows/shaders.yml) rebuilds them with the pinned naga-cli 29.0.2 and fails on any difference. `test_shaders.py` holds every file to its manifest hash. FXC (`cs_5_0`), DXC (`cs_6_0`), glslang and spirv-val compile or validate every entry point. The shipped files' naga is not the run-time naga. naga-cli 29.0.2 is one patch above the naga 29.0.1 inside wgpu-native. What was measured equivalent is 29.0.2 against naga 30.0.1, on everything a host binds ([stage 3's plan](../superpowers/plans/2026-11-17-emitted-languages.md), *Facts*) | Yes as text, and they compile. Nothing compares the shipped files with what wgpu runs, and no host has run them (gap 4) |
| C8 | Large dispatches reach every point | `test_a_dispatch_past_65535_workgroups_reaches_its_last_points`: 4,194,304 points, with the last 64 checked by the feature's rule. A wrong stride was tried and failed | Yes |

### How the bounds are derived

`hog-noise-measure-gpu derive` (`apps/hog-noise-tools/src/hog_noise_tools/measure_gpu.py`) takes the worst of the
four adapters and applies one of three rules. Each result is rounded up to the next 1, 2 or 5 step, never below 1e-7.

- **The 101 coordinate-scaled continuous rules:** twice the worst drift per unit.
- **The warp outputs:** twice the worst absolute drift, not coordinate-scaled.
- **The 15 discrete rules:** the within-bound is twice the worst p99 per unit. The outer bound is the reference's
  range, not doubled. The fraction is 1 minus twice the share outside it, and the correlation is capped at 0.999.

## The gaps, each with a verdict

| # | Gap | What is known | Verdict (proposed) | What closes it | Cost |
| --- | --- | --- | --- | --- | --- |
| 1 | **Far coordinates**: measured to 4,096 units at one frequency | The stage 1 spike measured OpenSimplex2 alone, 2D, out to 262,144 units on both back ends. The per-point bound `3e-6 * max(1, abs(coordinate * frequency))` held at every one of 1,179,648 points, so for that feature the coordinate-scaled shape extends. Unmeasured: every other feature far out, above all the discrete ones (cellular `cellvalue`, the grids' flipped fraction), where float32's coarse steps move a point across a cell edge. Also unmeasured: the warps, whose output rules are absolute (5e-4 to 5e-3), not coordinate-scaled, so far out they will be the first to break. The grid features already drift the most here, up to 1.26e-3 per unit (`fns/genasgrid_simplex_fbm_scales_1.0_1.0_1.0`) | **Needed** before HogNoise's GPU is used for a large world, which is what its users build. Measure before fixing: a far-band probe over every feature says which features need the coordinate split, and so sizes [the large-coordinate stage](../plan/board/2026-11-01-large-coordinate-correctness.md) | A probe: every hog feature on the 5090 in the spike's bands, out to 262,144 units, against the numpy rendering | 0.5 d for the probe; the fix is that row's 2 to 3 d |
| 2 | **One GPU vendor** | NVIDIA only. On the simplex fractals the 5090 drifts about 4.4 times more than the software adapters (`simplex_pingpong` 2.23e-5 per unit against 5.14e-6; `simplex_fbm` and `simplex_ridged` the same ratio), so real hardware is the worst case, and CI's software legs cannot see a hardware-only drift below the bound. AMD, Intel, Apple and mobile GPUs may differ in fused multiply-add, flushing of denormals and the precision of built-in functions, all of which WGSL leaves open. This machine's integrated Intel GPU is not enabled (wgpu lists none) | **Wanted, not blocking**: the README already says the bound was "measured on four GPU adapters" and names them, so no claim outruns the evidence | `hog-noise-measure-gpu run` on each vendor's hardware, then a re-derivation from all the records | unsized: needs hardware the project does not have |
| 3 | **Apple, Metal** | Never run. Metal is not shipped (naga's command line writes placeholder bindings). wgpu would run the WGSL on Metal directly | **Worth a try, cheap**: GitHub's macOS runners may offer a Metal device to wgpu; that is untried | A macOS leg in `tests.yml` with `HOG_NOISE_REQUIRE_GPU=1`; if it finds an adapter, its record joins the others | 0.5 d to find out |
| 4 | **No host has run the shipped files** | Narrower than it was. Today the 5090 ran naga's HLSL (D3D12), GLSL (OpenGL) and SPIR-V (Vulkan) translations of this WGSL and passed all 368 cases on each. Those are wgpu's own in-memory translations, by naga 29.0.1, not the shipped bytes. What no one has tried is a host binding the shipped files with its own code: the registers, GLSL's block names, the 112-byte `Params` and 48-byte `Grid` uniforms packed outside Python | **Needed before the PyPI release**, whose condition names HLSL. It is its own work, not part of this account: [the CI proof](../plan/board/2026-11-18-emitted-shaders-run-against-the-vectors.md), and today's runs make its HLSL and GLSL legs lower risk | That row | 3 to 5 d (that row) |
| 5 | **Speed** | Not benchmarked. One informal timing, not a benchmark: 33,554,432 2D points of one-octave OpenSimplex2 took 0.28 to 0.43 s on the 5090, upload and readback included (one run each, `4723216`). Nothing compares it with numba | **Needed before any speed claim**, and none is made. The track was fast in schedule, not by measurement | [The benchmarks](../plan/board/2026-11-01-published-benchmarks.md), with the GPU as a column | 1 to 2 d (that row) |
| 6 | **The two adapter variables do not combine** | With `HOG_NOISE_WGPU_ADAPTER` unset, wgpu's `WGPU_BACKEND_TYPE` chooses the back end: D3D12 and OpenGL each passed all 368 cases that way today, through the module's own command. With it set, the first device whose name matches wins, and `WGPU_BACKEND_TYPE` is ignored. The 5090 is offered three times under one name, so that is always Vulkan. Nothing documents either behaviour | **Good, very cheap**: `WGPU_BACKEND_TYPE=D3D12 hog-noise-measure-gpu run` can already record today's two new passes. Only naming a device and a back end together needs code | Say so in the README, and record the 5090's D3D12 and OpenGL runs. Optionally, match the variable against `device (backend)` | 0.5 d with the records and the re-derivation |
| 7 | **Past a device's buffer limit** | The device takes the adapter's limits: 2 GiB per storage binding on the 5090, about 536 million float32 values per axis. The 128 MiB default was suspected and disproved today: 2^25 and 2^25 + 64 points both ran. There is no chunking, and a call past the real limit has never been tried. The software adapters' limits are not recorded | **Minor**: the likely result is wgpu's own validation error, not a wrong answer, but nobody has seen it. A clear refusal naming the limit would be enough | One test past the limit on WARP, and a refusal before dispatch if the error is unclear | 0.5 d |

**Since the account:** gap 6 was closed on 2026-11-21 ([PR #40](https://github.com/HogJonny-AMZN/HogNoise/pull/40)).
Gap 1 was measured the same day by [the far-coordinate probe](../../Spikes/far_coordinates/README.md), with two
corrections to this page:
- far out, the discrete features hold and only the warp outputs fail;
- C2's bounds hold on the vectors' points, while on fresh points in the range about 1 to 10 in a million exceed them.

Nothing in the account changes a bound, the tolerance file or a record. Today's runs are evidence for this page, not
measurement records. Recording them means a new record folder and a re-derivation, which is gap 6's work.

## What this decides

The row asked whether [the CI proof](../plan/board/2026-11-18-emitted-shaders-run-against-the-vectors.md) is part of
the hardening. **The recommendation is no.** The hardening is this account. The CI proof is gap 4's own work, and it is
the one gap that stands between the shipped HLSL and the PyPI condition. [The engine trials](../plan/board/2026-11-18-engine-host-trials.md)
still come after it.

The recommended order, cheapest evidence first:

1. **Gap 6** (0.5 d): record the 5090's D3D12 and OpenGL runs with `WGPU_BACKEND_TYPE`, and say in the README how
   to choose a back end.
2. **Gap 1's probe** (0.5 d): far bands for every feature, which sizes the large-coordinate stage.
3. **Gap 3** (0.5 d): try a macOS leg.
4. **Gap 4**, the CI proof (3 to 5 d), before the PyPI release.
5. **Gap 5**, the benchmarks (1 to 2 d), before any speed claim.
6. **Gaps 2 and 7** when hardware or time allows.

Gaps 1, 3, 6 and 7 are on the Icebox, each with its verdict marked as proposed:
[gap 6's records](../plan/board/2026-11-21-record-the-5090s-d3d12-and-opengl-runs.md),
[gap 1's probe](../plan/board/2026-11-21-far-coordinate-probe-for-every-feature.md),
[gap 3's macOS leg](../plan/board/2026-11-21-the-wgpu-rung-on-a-macos-runner.md) and
[gap 7's buffer limit](../plan/board/2026-11-21-a-call-past-the-devices-buffer-limit.md). Gaps 2, 4 and 5 already had
rows or need hardware.

## How today's numbers were taken

From a worktree of `main` at `4723216`, after `uv sync --all-packages --all-extras --group dev`. The probe scripts were
run with `uv run --no-sync python -I <script>`.

- **The adapters:** `wgpu.gpu.enumerate_adapters_sync()` lists the 5090 on Vulkan, D3D12 and OpenGL, and the Microsoft
  Basic Render Driver on D3D12.
- **The conformance run on Vulkan**, by the module's own command:
  `HOG_NOISE_WGPU_ADAPTER="RTX 5090" python -m hog_noise.conformance vectors --rendering wgpu --tolerance vectors/tolerance/wgpu.json`.
  The result: `368 pass, 0 fail, 0 unsupported, 0 skipped, 0 advisory`. Adding `WGPU_BACKEND_TYPE=D3D12` still logs
  Vulkan: with a name set, the back end is ignored (gap 6).
- **The same command on D3D12 and OpenGL**, with `HOG_NOISE_WGPU_ADAPTER` unset and `WGPU_BACKEND_TYPE=D3D12` or
  `OpenGL`: the log names the 5090 on each, and each gives `368 pass, 0 fail, 0 unsupported, 0 skipped, 0 advisory`.
- **The probe below**, run first and before the reviewer pointed out the route above, gives the same answers. It chooses the adapter by name and back end,
  replaces `gpu._pick_adapter` with that choice, and runs `conformance.check` with the tolerance file, as
  `test_the_rung_passes_every_hog_case_against_its_tolerance` does. Results:
  - Vulkan: 368 cases, ok, complete.
  - D3D12: 368 cases, ok, complete.
  - OpenGL: 368 cases, ok, complete.
  - The control, D3D12 with every seed shifted by one, on `hog/fnl/simplex_fbm/*`: 3 of 3 fail.
- **The buffer limit:** `device.limits` on the 5090 gives `max-storage-buffer-binding-size` 2,147,483,644 and
  `max-buffer-size` 1,099,511,627,776. `sample_points_2d` of 2^25 points ran in 0.43 s, and of 2^25 + 64 in 0.28 s, all
  finite.

The probe, kept here so that the run can be repeated:

```python
import sys

import wgpu

from hog_noise import conformance, gpu

name, backend, vectors_dir = sys.argv[1], sys.argv[2], sys.argv[3]
found = [
    a
    for a in wgpu.gpu.enumerate_adapters_sync()
    if name.lower() in str(a.info.get("device", "")).lower() and a.info.get("backend_type") == backend
]
gpu._pick_adapter = lambda _wgpu: found[0]
vectors = conformance.load(vectors_dir)
tolerance = conformance.Tolerance.load(f"{vectors_dir}/tolerance/wgpu.json", vectors)
sample, warp = conformance.renderings("wgpu")
report = conformance.check(sample, vectors, warp=warp, grid=conformance.grid_rendering("wgpu"), tolerance=tolerance)
print(gpu.adapter_info(), len(report.results), report.ok, report.complete)
```

## Terms introduced

None. *GPU adapter*, *measurement record*, *rendering* and *tolerance contract* are already in the glossary.
