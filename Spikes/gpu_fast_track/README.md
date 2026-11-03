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

NVIDIA GeForce RTX 5090. A band holds the points whose larger coordinate magnitude, `max(|x|, |y|)` in world units, lies in
it. Largest absolute difference from the numpy rendering, per band:

| Case | [0, 10) | [10, 100) | [100, 1000) | [1000, 4096) | [4096, 32768) | [32768, 262144) |
| --- | --- | --- | --- | --- | --- | --- |
| one octave, f = 0.01, Vulkan | 1.5e-6 | 2.0e-6 | 5.2e-6 | 2.4e-5 | 2.2e-4 | 1.6e-3 |
| one octave, f = 0.01, DirectX 12 | 1.6e-6 | 2.0e-6 | 5.2e-6 | 2.4e-5 | 2.2e-4 | 1.6e-3 |
| FBm x4, f = 0.01, Vulkan | 1.1e-6 | 1.1e-6 | 6.0e-6 | 2.6e-5 | 2.7e-4 | 1.5e-3 |
| FBm x4, f = 0.05, Vulkan | 1.1e-6 | 3.8e-6 | 3.0e-5 | 1.5e-4 | 9.9e-4 | 8.5e-3 |
| FBm x4, f = 0.05, DirectX 12 | 1.3e-6 | 3.8e-6 | 3.0e-5 | 1.5e-4 | 9.9e-4 | 8.5e-3 |

And pointwise, each point's difference divided by its own `max(1, max(|x|, |y|) * frequency)`, the largest in each band:

| Case | [0, 10) | [10, 100) | [100, 1000) | [1000, 4096) | [4096, 32768) | [32768, 262144) |
| --- | --- | --- | --- | --- | --- | --- |
| one octave, f = 0.01, Vulkan | 1.5e-6 | 2.0e-6 | 1.4e-6 | 6.6e-7 | 7.2e-7 | 6.0e-7 |
| one octave, f = 0.01, DirectX 12 | 1.6e-6 | 2.0e-6 | 1.5e-6 | 6.6e-7 | 7.2e-7 | 6.0e-7 |
| FBm x4, f = 0.05, Vulkan | 1.1e-6 | 9.9e-7 | 8.7e-7 | 8.2e-7 | 7.4e-7 | 7.1e-7 |
| FBm x4, f = 0.05, DirectX 12 | 1.3e-6 | 1.1e-6 | 8.7e-7 | 8.3e-7 | 7.4e-7 | 7.1e-7 |

The full rows (every case on both back ends, p99.9, mean, the fraction exactly equal, the pointwise maximum and the count of
points over the bound) are in `results_vulkan.json` and `results_d3d12.json`. In every band numba and numpy were
bit-identical, as they must be.

A first run (2026-11-01) drew its points by Euclidean radius and compared each band's maximum with the bound at the band's
top, which a point near the band's bottom could violate unseen (Copilot on [PR #8](https://github.com/HogJonny-AMZN/HogNoise/pull/8)). This run draws by the larger
coordinate and checks every point against its own bound.

## What it says

1. **The drift follows the coordinate after the frequency multiply, not the world distance.** A bound of
   `3e-6 * max(1, |coordinate * frequency|)` holds at every point, on both back ends: none of the 1,179,648 points is over
   it, the worst at 2.03e-6 (DirectX 12's one octave in [10, 100), which is why 2e-6 is not the bound). In world terms
   that is about 1e-6 near the origin, a few 1e-5 at the
   vectors' 4,096 units for ordinary frequencies. That is the shape of the tolerance contract for stage 2: stated per feature
   as a multiple of the noise-space coordinate, not one number.
2. **FBm does not compound it.** Four octaves drift about as much as one; the higher octaves' larger coordinates are weighted
   down by the gain.
3. **naga's HLSL (DirectX 12) and SPIR-V (Vulkan) give the same answer** to the printed digits in almost every band. That is
   the stretch goal's premise: one WGSL source, translated, renders the same noise on both back ends.
4. **Far from the origin the GPU needs the roadmap's large-coordinate stage**: at 262,144 units and f = 0.05 the drift reaches
   8.5e-3. A coordinate split (an integer cell and an f32 offset) is the known fix.

**Verdict: go.** The port can proceed at the cost the design gave; the contract is a per-feature multiple of the noise-space
coordinate, measured in stage 2 for every feature.
