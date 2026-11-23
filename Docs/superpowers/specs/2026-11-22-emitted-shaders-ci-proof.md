# Spec: the emitted shaders run against the vectors, headless in CI

**Status:** Accepted 2026-11-22, with its five decisions as recommended, on the owner's "Go with your best
recommendations". Written on the owner's "your best recommendations" (2026-11-22) from [the account](../../design/2026-11-20-gpu-fast-track-account.md)'s gap 4, the next in its order.
**Board:** [`2026-11-18-emitted-shaders-run-against-the-vectors`](../../plan/board/2026-11-18-emitted-shaders-run-against-the-vectors.md)

What gets built, exactly enough that a plan is a list of tasks and a reviewer can check the result against this page.
The row says why: the [emitted shaders](../../../packages/python/hog-noise/src/hog_noise/shaders/README.md) compile in
each language's own tools and match their WGSL, and no host has run them. The PyPI release's condition names HLSL.

## Facts this rests on

Measured 2026-11-22 at `01480cd` on the owner's machine (Windows 11 Pro 10.0.26300, RTX 5090, wgpu 0.33.0); the
probes are scratch scripts, described here so the plan's first task can repeat them as tests.

- **The shipped SPIR-V reproduces the WGSL bit for bit, read back through wgpu.** `noise.spv`, given to
  `device.create_shader_module(code=bytes)` and bound exactly as the shaders README documents (seven bindings in group
  0, a 4-byte buffer for an unused coordinate, 48 zero bytes for an unused `Grid`), gave output identical to
  `GpuSampler` for all five entry points: 4,096 random points out to 4,096 units, two parameter records (OpenSimplex2
  alone, and a 4-octave fractal), and a 256-cell grid. On the 5090's Vulkan and D3D12 both. The control, the same
  path with the seed plus one, did not compare identical. This is naga reading the shipped bytes back into its own
  IR, not a Vulkan driver consuming them: wgpu 0.33 has no SPIR-V passthrough (`WGPUNativeFeature_PassthroughShaders`
  is commented out in its `wgpu.h`).
- **The shipped GLSL runs in moderngl, bound by the manifest's block names.** moderngl 5.13.0, a standalone OpenGL 4.3
  context on the 5090 (NVIDIA 610.88), compiled `noise.sample_points_3d.comp` and `noise.sample_points_2d.comp`; each
  block named in `manifest.json`'s `bindings[n].glsl.blocks` was found under that name, given its binding, and
  filled. Against the WGSL on Vulkan, on the same 4,096 points: largest difference 7.75e-7 (3D) and 1.73e-6 (2D), not
  bit-identical, as expected of another compiler; the seed-plus-one control differed. The tolerance file judges this,
  not the probe.
- **wgpu and moderngl in one process.** After `GpuSampler` had built its pipelines, moderngl's next program failed
  ("cannot create program") until its context was made current again (`with ctx:`). wgpu enumerates its OpenGL
  back end, which can leave its own context current. A GL host sharing a process with wgpu has to make its own context
  current; the harness does, and the shaders README will say so.
- **The seam.** The wgpu rung touches the GPU in one place, `_Gpu.run(entry, params, axes, n, width, grid)`
  (`packages/python/hog-noise/src/hog_noise/gpu.py:223`). Everything else a host needs is public and needs no `wgpu`:
  `shaders.source`, `shaders.tables`, `shaders.manifest`, `gpu.pack_params`, `gpu.pack_grid`, `gpu.ENTRY_POINTS`.
  The judge is `conformance.check(sample, vectors, warp=..., grid=..., tolerance=...)` with callables of the shape
  `conformance.renderings` returns (`conformance.py:669`).

## What gets built

**A host is written from the README, not from `gpu.py`.** Each harness is what a host author would write from
[the shaders README](../../../packages/python/hog-noise/src/hog_noise/shaders/README.md) alone: it reads the files
through `hog_noise.shaders`, packs the uniforms with `pack_params` and `pack_grid`, binds by the manifest, and
dispatches as the README's *Dispatch* says. It does not import `_Gpu` or copy its code, so a wrong sentence in the
README fails the proof.

- **`hog_noise_tools.hosts`** (in `apps/hog-noise-tools`, which already holds the emitter): one module per host, each
  exposing `run(entry, params_bytes, axes, n, width, grid_bytes) -> float32 array`, and one shared
  `HostSampler(params, run)` with the calls every sampler has (`sample_points`, `sample_points_2d`, `sample_grid`,
  `warp_points`, `warp_points_2d`), plus `renderings(host)` returning the three callables `conformance.check` takes.
  Each host checks, before its first dispatch, that the file it loaded hashes to the manifest's entry (P-22: the leg
  asserts the thing it exists to test).
- **The hosts:**

  | Host | File | Runs on | How |
  | --- | --- | --- | --- |
  | `spirv-naga` | `noise.spv` | every existing GPU leg (WARP, llvmpipe, Metal) | wgpu's SPIR-V front end; no new dependency |
  | `glsl` | `noise.<entry>.comp` | Ubuntu, Mesa llvmpipe OpenGL through EGL | moderngl |
  | `hlsl-d3d11` | `noise.hlsl`, FXC `cs_5_0` | Windows, WARP | a small C++ harness |
  | `hlsl-d3d12` | `noise.hlsl`, DXC `cs_6_0` | Windows, WARP | the same harness |
  | `spirv-vulkan` | `noise.spv` | Ubuntu, Mesa lavapipe | the same harness, a Vulkan back end |

  The C++ harness (`apps/hog-noise-tools/hosts/`) is a persistent process speaking request and response over its
  standard input and output: Python starts it once per run, and each `run(...)` call writes one dispatch (entry point,
  uniforms, coordinates) and blocks until that dispatch's output comes back. That keeps the synchronous contract
  `conformance.check` needs, since `_check_case` consumes each result before asking for the next case
  (`conformance.py:573-585`), and the negative controls are ordinary requests on the same process. One process per run,
  not per case; a batch file is not used, because the callback cannot return its first result before the batch has run.
- **Tests,** in `apps/hog-noise-tools/tests/`: per host, every hog case against `vectors/tolerance/wgpu.json`; the
  seed-plus-one control and a rule at 0.9 of its worst both fail, as `test_gpu.py` does for the rung. Without the host
  they skip, naming why; `HOG_NOISE_REQUIRE_HOST=<host>` turns the skip into a failure, as `HOG_NOISE_REQUIRE_GPU` does.
- **Each host asserts its target** (P-22): before its first dispatch it reads back the back end and the adapter or
  renderer it got, and fails unless they match its row in the hosts table (D3D11 or D3D12 on WARP; OpenGL on
  llvmpipe; Vulkan on lavapipe; for `spirv-naga`, the leg's pinned back end, as `tests.yml` already asserts). A
  mismatched-target control, the host told to expect another adapter, must fail that check.
- **CI:** a `hosts.yml` workflow, one job per host, each failing unless its host ran (`HOG_NOISE_REQUIRE_HOST`) on the
  target it names, and each printing the adapter it ran on; `spirv-naga` joins the three existing GPU legs in `tests.yml` instead.
- **The README's claims** move from "compiles" to "runs": the shaders README's *What is proven* and the top README's
  GPU section say which host ran which file, on which adapter.

## Acceptance

Every hog case passes on every host it is given, within `vectors/tolerance/wgpu.json`, unmodified. A host that fails a
rule is a finding for the owner, never a rule loosened in the same change (`vectors/README.md`, *Tolerance files*).

## Not in this

- New measurement records or rules. The hosts are judged by the wgpu rung's file; they are not measured into it.
- Engine hosts (Unreal, Unity, Godot, Maya): [the engine trials](../../plan/board/2026-11-18-engine-host-trials.md).
- Metal Shading Language: not shipped (stage 3's decision 1).
- Speed.

## Decisions

Taken by the owner 2026-11-22, each as recommended.

| # | Decision | Recommended | Alternative |
| --- | --- | --- | --- |
| 1 | SPIR-V | Both tiers: `spirv-naga` now (no dependency; measured above on the 5090's Vulkan and D3D12 only, and planned on the three existing GPU legs: WARP, llvmpipe and Metal), and `spirv-vulkan` on lavapipe so a driver consumes the shipped bytes | `spirv-naga` only: cheaper by about 1 d, but no driver ever reads the file a host ships |
| 2 | GLSL host | moderngl on llvmpipe through EGL, a dependency group `hosts` in the tools app, never the library's | PyOpenGL (more code, the same driver); or C++ beside the HLSL harness |
| 3 | HLSL host | A small C++ harness built by MSVC on the Windows runner, D3D11 (FXC `cs_5_0`) and D3D12 (DXC `cs_6_0`), both on WARP | Python over COM with `ctypes` (no compiler, but fragile vtable code); or D3D11 only (half a day less; DXC's output never runs) |
| 4 | The judge | `vectors/tolerance/wgpu.json`, as the row says: the same float32 shader, so the same bound | A tolerance file per host, measured from its own runs: hosts that fail would set their own bounds |
| 5 | Pull requests | Three, cheapest first: (a) the shared harness, `spirv-naga` and `glsl`; (b) HLSL on D3D11 and D3D12, which meets the PyPI condition; (c) `spirv-vulkan` | One pull request for all of it |

## Open risks

- **llvmpipe through EGL on the hosted Ubuntu runner.** Mesa's llvmpipe supports OpenGL 4.5 and compute; whether the
  runner's Mesa gives a surfaceless EGL context to moderngl is not yet read. The plan's first CI task only creates the
  context and prints `GL_RENDERER`.
- **FXC's HLSL on D3D11.** The file compiles in FXC; whether naga's HLSL uses anything D3D11 rejects at pipeline creation
  (rather than compile) is unknown until it runs.
- **lavapipe on the hosted runner.** `mesa-vulkan-drivers` already gives the llvmpipe leg its Vulkan; lavapipe is that
  same driver, so the risk is the C++ harness, not the runner.
- **A C++ toolchain in CI.** MSVC is on `windows-latest`; the Vulkan harness needs the Vulkan headers and loader on
  Ubuntu (`libvulkan-dev`). Both are packages, not builds.

## Cost

3 to 5 d, the row's estimate: the shared harness and `spirv-naga` 0.5 d; GLSL 0.5 to 1 d; HLSL on D3D11 and D3D12
1.5 d; `spirv-vulkan` 1 d. Decision 1's alternative saves about 1 d.

## Terms introduced

- **Host harness**: a program that runs an emitted shader through one graphics API, written from the shaders README
  alone, and hands its output to `conformance.check`. One per row of the hosts table above.
