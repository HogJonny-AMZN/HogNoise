# Spike: the GPU fast track, stage 1

**Date:** 2026-11-01. **Serves:** [the GPU fast track](../../Docs/design/2026-11-01-gpu-fast-track.md), stage 1: measure how far an
f32 WGSL rendering drifts from the CPU before the port is sized. Evidence, not product; nothing in `src/` changed.

`noise2.wgsl` is HogNoise's 2D OpenSimplex2 and FBm, ported line for line from `src/hog_noise/scalar.py`, with the integer
hash done on `u32` so it wraps as the CPU's 32-bit emulation does. `spike.py` runs it as a compute pass over 65,536 scattered
points per coordinate band and compares the readback with HogNoise's numpy rendering of the same parameters.

```bash
uv run --with wgpu python Spikes/gpu_fast_track/spike.py
WGPU_BACKEND_TYPE=D3D12 uv run --with wgpu python Spikes/gpu_fast_track/spike.py
```

## Measured

NVIDIA GeForce RTX 5090. Largest absolute difference from the numpy rendering, per band of coordinate magnitude (world units):

| Case | [0, 10) | [10, 100) | [100, 1000) | [1000, 4096) | [4096, 32768) | [32768, 262144) |
| --- | --- | --- | --- | --- | --- | --- |
| one octave, f = 0.01, Vulkan | 1.4e-6 | 1.9e-6 | 3.8e-6 | 1.6e-5 | 1.1e-4 | 9.8e-4 |
| FBm x4, f = 0.01, Vulkan | 1.1e-6 | 1.1e-6 | 5.0e-6 | 1.9e-5 | 1.6e-4 | 1.4e-3 |
| FBm x4, f = 0.05, Vulkan | 9.5e-7 | 2.9e-6 | 3.8e-5 | 1.2e-4 | 1.0e-3 | 6.9e-3 |
| FBm x4, f = 0.05, DirectX 12 | 1.3e-6 | 2.8e-6 | 3.7e-5 | 1.2e-4 | 1.0e-3 | 6.9e-3 |

The full rows (p99.9, mean, the fraction that is exactly equal) are in `results_vulkan.json` and `results_d3d12.json`. In
every band numba and numpy were bit-identical, as they must be.

## What it says

1. **The drift follows the coordinate after the frequency multiply, not the world distance.** A bound of
   `3e-6 * max(1, |coordinate * frequency|)` holds in every cell, on both back ends (a first reading of 2e-6 failed one
   cell, DirectX 12's one octave in [10, 100) at 2.03e-6): about 1e-6 near the origin, a few 1e-5 at the
   vectors' 4,096 units for ordinary frequencies. That is the shape of the tolerance contract for stage 2: stated per feature
   as a multiple of the noise-space coordinate, not one number.
2. **FBm does not compound it.** Four octaves drift about as much as one; the higher octaves' larger coordinates are weighted
   down by the gain.
3. **naga's HLSL (DirectX 12) and SPIR-V (Vulkan) give the same answer** to the printed digits in almost every band. That is
   the stretch goal's premise: one WGSL source, translated, renders the same noise on both back ends.
4. **Far from the origin the GPU needs the roadmap's large-coordinate stage**: at 262,144 units and f = 0.05 the drift reaches
   7e-3. A coordinate split (an integer cell and an f32 offset) is the known fix.

**Verdict: go.** The port can proceed at the cost the design gave; the contract is a per-feature multiple of the noise-space
coordinate, measured in stage 2 for every feature.
