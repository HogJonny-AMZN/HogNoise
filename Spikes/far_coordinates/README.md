# Probe: every feature's GPU rule, far from the origin

**Date:** 2026-11-21, at `f2df5e7`. **Serves:** [the account](../../Docs/design/2026-11-20-gpu-fast-track-account.md),
gap 1; [the probe's row](../../Docs/plan/board/2026-11-21-far-coordinate-probe-for-every-feature.md). This is evidence,
not product: nothing in `packages/` changed.

The tolerance file was measured on the vectors' points, at frequency 0.01, out to 4,096 units. `probe.py` takes every
hog case's parameters and output (246 probes: each of the 116 features, noise or warp, 2D or 3D). For each one it
draws 65,536 fresh points in each of four bands of the largest coordinate's magnitude. It renders them with numpy, the
reference the hog set was made with, and with the wgpu rung. Then it judges the GPU by the feature's own rule from
`vectors/tolerance/wgpu.json`, using the conformance check's own function.

```bash
uv run python -I Spikes/far_coordinates/probe.py
WGPU_BACKEND_TYPE=D3D12 uv run python -I Spikes/far_coordinates/probe.py
HOG_NOISE_WGPU_ADAPTER="Microsoft Basic Render Driver" uv run python -I Spikes/far_coordinates/probe.py
```

**The control.** Before its bands, each probe runs on its own case's committed points. There, numpy must reproduce the
hog set bit for bit, and the GPU must pass. On all three adapters, all 242 probes that have scatter points did both;
the other 4 are grid cases. So the reference is the hog set's, and the judging is the conformance check's. The
failures below are measurements, not the probe.

**What this is not.** It compares the GPU with the CPU. Whether the CPU itself is right at 1e5 to 1e7 units, against
float64, is [the large-coordinate row](../../Docs/plan/board/2026-11-01-large-coordinate-correctness.md)'s own question,
and nothing here answers it.

## Measured

Probes that pass their feature's rule, per band, with the worst drift as a multiple of the bound. Each band is
65,536 points per probe, and the seed is fixed.

| Adapter | [0, 4,096) (measured range) | [4,096, 32,768) | [32,768, 262,144) | [262,144, 1,048,576) |
| --- | --- | --- | --- | --- |
| RTX 5090, Vulkan | 234 / 246, 8.54x | 218 / 246, 15.6x | 225 / 246, 46.9x | 226 / 246, 250x |
| RTX 5090, D3D12 | 232 / 246, 8.54x | 219 / 246, 15.6x | 226 / 246, 31.2x | 226 / 246, 219x |
| WARP (D3D12) | 221 / 246, 6.1x | 218 / 246, 15.6x | 225 / 246, 50.8x | 226 / 246, 250x |

The same bands, split into the 228 noise probes (coordinate-scaled rules) and the 18 warp outputs (absolute rules), on
the 5090's Vulkan. "Points past" counts out of 228 x 65,536 = 14,942,208 per band:

| Band | Noise probes failing (points past) | Warp outputs failing | Warps' worst drift | One float32 step at the band's top |
| --- | --- | --- | --- | --- |
| [0, 4,096) | 10 / 228 (15) | 2 / 18 | 0.0122 | 0.000488 |
| [4,096, 32,768) | 10 / 228 (16) | 18 / 18 | 0.0312 | 0.00391 |
| [32,768, 262,144) | 3 / 228 (2) | 18 / 18 | 0.0938 | 0.0312 |
| [262,144, 1,048,576) | 2 / 228 (2) | 18 / 18 | 0.5 | 0.125 |

The other two adapters' bands past 4,096 units are like these; their measured-range rows are below, in *What it says*
item 3. The full rows are in `results_*.json`, one file per adapter.

## What it says

1. **The noise rules hold far out, much better than expected.** Out to 1,048,576 units, about 10,000 in noise
   coordinates at frequency 0.01, 226 of 228 noise probes pass their coordinate-scaled rule, on every adapter. Far out,
   the discrete rules (cellular `cellvalue`, NoiseLookup) pass too, apart from two probes in which one point fell
   outside the tight bound. The account expected the discrete features to break first far out, and that was wrong. The coordinate-scaled shape from stage 1, until
   now measured for OpenSimplex2 alone, holds for every noise feature. For noise outputs the GPU needs **no coordinate
   split** to agree with the CPU at these distances.
2. **The warp outputs fail far out, and the fault is the rule's shape.** All 18 fail past 32,768 units on every adapter,
   and 17 or 18 of the 18 fail between 4,096 and 32,768. The failures grow with distance. A warp's output is a coordinate, and its drift is 3 to 8 float32 steps of the coordinate being
   warped, so it grows as the coordinate does. An absolute bound (5e-4 to 5e-3) cannot hold that far out for any
   float32 shader. A coordinate-scaled rule for the warp outputs would follow the drift, as it already does for the
   noise.
3. **The bounds miss rare points even inside the measured range.** On fresh points in [0, 4,096), by adapter, with
   two kinds of failure kept apart:
   - **past the outer bound**: a point beyond the rule's bound;
   - **outside the tight bound**: a discrete rule's share of points within its tight bound, below what it asks.

   | Adapter | Continuous noise probes failing (of 202) | Points past the outer bound, all 228 noise probes pooled | Discrete probes failing on the tight bound | Warp outputs failing (of 18) |
   | --- | --- | --- | --- | --- |
   | RTX 5090, Vulkan | 10 | 15 of 14,942,208 (1.0 per million) | 0 | 2 |
   | RTX 5090, D3D12 | 9 | 14 (0.94 per million) | 3 | 2 |
   | WARP (D3D12) | 20 | 156 (10.4 per million) | 3 | 2 |

   The worst continuous noise probe is 4.9 times its bound (`fnl/simplex_smooth_fbm`, 3D), and the worst warp output
   8.5 times. The three discrete probes are NoiseLookup in 2D (Euclidean, Manhattan and Natural). On D3D12 alone, 0.11
   to 0.13% of their points fall outside the tight bound, where the rule asks for none; their outer bound and
   correlation hold.

   The rules were derived from the vectors' 4,096 points per case, so a tail rarer than about 1 in 4,096 is never seen.
   The claim "each feature is within its bound" therefore holds on the vectors' points. The per-million figures pool
   every noise probe on one adapter. They are not a rate for any one feature, and not a guarantee for points this
   probe did not draw.

## What it changes

- **[The large-coordinate row](../../Docs/plan/board/2026-11-01-large-coordinate-correctness.md):** the GPU does not
  need a coordinate split for noise at these distances. The warp outputs need a coordinate-scaled rule, not a split.
  The CPU's own correctness far out remains the row's question.
- **Two changes to how the bounds are derived**, both in `hog-noise-measure-gpu derive`. Each changes the tolerance
  file, so each is the owner's decision:
  - **the warp outputs' rule coordinate-scaled**, so it means the same thing at every distance;
  - **bounds derived from a large fresh sample**, as this probe draws, not from the vectors' 4,096 points, so a rare
    tail is seen before it is shipped. The vectors stay as the check.

  Both are on the Icebox, with proposed verdicts.

## After the warp rules (2026-11-24)

The first change above was built: the warp outputs' rules are coordinate-scaled
([the row](../../Docs/plan/board/2026-11-21-warp-output-rules-coordinate-scaled.md)). The probe ran again with them, on
the same three adapters, seed and points, into [after-warp-rules/](after-warp-rules/); `compare.py` prints both runs
side by side:

```bash
uv run python -I Spikes/far_coordinates/probe.py Spikes/far_coordinates/after-warp-rules
uv run python -I Spikes/far_coordinates/compare.py Spikes/far_coordinates Spikes/far_coordinates/after-warp-rules
```

The 18 warp outputs, passing per band, with the worst drift as a multiple of the bound and, after, the points past it
(of 18 x 65,536 per band):

| Adapter | [0, 4,096) | [4,096, 32,768) | [32,768, 262,144) | [262,144, 1,048,576) |
| --- | --- | --- | --- | --- |
| RTX 5090, Vulkan, before | 16, 8.54x | 0, 15.6x | 0, 46.9x | 0, 250x |
| RTX 5090, Vulkan, after | 16, 4.22x, 3 past | 16, 1.26x, 2 past | **18**, 0.602x | **18**, 0.62x |
| RTX 5090, D3D12, before | 16, 8.54x | 1, 15.6x | 0, 31.2x | 0, 219x |
| RTX 5090, D3D12, after | 17, 4.22x, 1 past | 16, 1.26x, 2 past | **18**, 0.684x | **18**, 0.613x |
| WARP (D3D12), before | 16, 6.1x | 0, 15.6x | 0, 50.8x | 0, 250x |
| WARP (D3D12), after | 16, 4.05x, 2 past | 17, 1.22x, 1 past | **18**, 0.644x | **18**, 0.726x |

Far out, every warp output now passes, below its bound by a margin that does not shrink with distance: the bound
follows the drift. Inside 32,768 units, 1 to 3 points per band still fall past the bound of one or two warp outputs.
That is the rare tail of *What it says* item 3, which the noise probes show too, and the second change (bounds from a
large fresh sample) is for it.

The noise probes are as before, with one exception unrelated to the warps: 3D `fns/cellular_manhattan_noiselookup`
in [32,768, 262,144) now passes on all three adapters, with the same values. This probe first ran before the macOS
runner's Metal record joined the tolerance file (`5340a3f`), which moved the NoiseLookup features' fraction within
the tight bound from 1.0 to 0.999.
