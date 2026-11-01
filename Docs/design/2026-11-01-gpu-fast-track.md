# The GPU fast track: today's noise on wgpu, in WGSL

**Status:** Accepted (HogJonny-AMZN, 2026-11-01: "lock it"). The owner's direction the same day: *"fast track ... current
noise features but also wgpu/wgsl support, stretch other gpu shader languages."* Its four decisions are below.

## Intent

Every noise HogNoise has today runs on the GPU through wgpu, from one WGSL source, within a measured and written-down
tolerance of the CPU, without waiting for the node graph or FastNoise2 parity. The stretch is the same noise as HLSL, GLSL and
Metal, generated from that WGSL rather than written again.

This brings the [north-star roadmap](2026-11-01-north-star-roadmap.md)'s GPU stages forward. They were placed after the node
graph because a graph compiles to one shader; the fast track instead ports the current kernels as one shader that dispatches on
the parameters, exactly as `scalar.py` does on the CPU, and the graph, when it comes, calls the same WGSL functions.

## Decisions (the owner, 2026-11-01)

1. **The GPU is used only when asked for**: `make_sampler(params, backend="wgpu")` or an equivalent explicit call. It is an
   override-only rung, which keeps [ADR-2026-11-01](../decisions/ADR-2026-11-01-the-binding-is-reference-only.md)'s rule that
   an install never changes the numbers.
2. **WGSL is the source; naga makes the rest.** One hand-written WGSL file, ported from HogNoise's own CPU kernels. naga, the
   shader translator inside wgpu, emits HLSL, GLSL, Metal and SPIR-V from it. This replaces the roadmap's Slang proposal.
3. **The first release covers everything HogNoise has**: the FastNoiseLite features and the FastNoiseSIMD-only ones (classic
   Simplex, Billow, RigidMulti, white noise, Natural distance, NoiseLookup, Distance2Cave, gradient perturb), and `sample_grid`
   and `sample_points`.
4. **The tolerance is measured, then fixed**: each feature is measured against the vectors over a stated coordinate range, and
   the bound is written down per feature. A bound is never loosened to make a test pass.

## Facts this rests on

- **The path is proven.** The source project's wgpu spike (2026-09-19) ran a WGSL value noise in a compute pass and read it back
  against a numpy twin with the same `u32` arithmetic: worst difference 4.6e-5 on an amplitude of 60, about 1e-6 relative, on an
  RTX 5090. WGSL's `u32` and `i32` arithmetic wraps, as HogNoise's 32-bit hash emulation does.
- **FastNoiseLite ships official HLSL and GLSL ports** (about 99 KB each, MIT). They are an independent cross-check for the
  FastNoiseLite half; they do not have the FastNoiseSIMD-only features.
- **naga has back ends for WGSL, HLSL, GLSL, Metal and SPIR-V.** Running the WGSL on wgpu's DirectX 12, Vulkan and Metal back ends
  exercises the HLSL, SPIR-V and Metal it produces.
- **CI can run it.** The source project's Windows runner ran wgpu on its software adapter; Ubuntu needs a Vulkan software driver
  or skips with a reason.

## The risk, stated up front

The CPU computes in float64 after the float32 frequency multiply; WGSL has no float64. So the GPU's difference from the CPU grows
with the size of the coordinates, and the spike's 1e-6 was measured on one small tile. The vectors sample out to 4096 units,
where float32 resolves about 5e-4. Some features may need a looser bound than others, or the coordinate split the roadmap's
large-coordinate stage describes. Stage 1 below exists to measure this before the port is sized.

## Stages

| Stage | What | Proves it | Cost |
| --- | --- | --- | --- |
| 1 | **Spike**: OpenSimplex2 with FBm as a WGSL compute pass over a grid and over scattered points, read back against the numpy rendering on the existing vector coordinates | the measured difference per coordinate range: whether one bound holds, or which features need their own | 1 to 2 d |
| 2 | **The WGSL port**: every feature, as one shader dispatching on `NoiseParams` (a uniform), a `wgpu` rung for `sample_grid` and `sample_points`, `wgpu` as a new `gpu` extra | every vector within its feature's bound; a GPU comparison table beside `portability.md`; run on a real adapter and on CI's software adapter | 8 to 12 d |
| 3 | **Stretch: the other languages**: `tools/emit_shaders.py` runs naga to write HLSL, GLSL, Metal and SPIR-V beside the WGSL, shipped with the package | the emitted files compile in CI (a drift test fails when they fall behind the WGSL), and run through wgpu's back ends where the machine has them | 2 to 4 d |

## Not in the fast track

The node graph, FastNoise2's nodes and 4D stay where the roadmap has them. A GPU rendering that is chosen automatically. Making
the GPU match the CPU bit for bit: that is not achievable without float64, and is not asked for.

## Terms introduced

None. *Rendering*, *tolerance contract* and *north star* are already in the glossary.
