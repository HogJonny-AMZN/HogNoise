# Correctness at very large coordinates

**Section:** icebox
**Owner:** none
**State:** Iceboxed
**Cost:** 2 to 3 d
**Verdict:** Good
**Raised:** [README, Wanted](../../../README.md)

A guaranteed result at 1e5 to 1e7 world units, where float32 hashing falls apart, checked by new vectors far from the origin
against float64. It is what planet-scale worlds need. Not now: no consumer has asked yet.

Sized in part on 2026-11-21 by [the far-coordinate probe](../../../Spikes/far_coordinates/README.md), which compares
the GPU with the CPU out to 1,048,576 units. On the GPU side, the noise rules hold that far without a coordinate split,
and only the warp outputs failed, because their rules were absolute. On 2026-11-24 they became coordinate-scaled
([that row](2026-11-21-warp-output-rules-coordinate-scaled.md)), and every warp output passes past 32,768 units.
What remains here is the CPU's own correctness against float64, which the probe does not measure.
