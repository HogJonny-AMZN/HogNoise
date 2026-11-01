# A GPU rung (WGSL compute) and shader emitters from the same parameter record

**Section:** icebox
**Owner:** none
**State:** Iceboxed
**Cost:** 3 to 5 d (a spike first, then per feature)
**Verdict:** Good
**Raised:** [README, Wanted](../../../README.md)

The same `NoiseParams` rendered as WGSL compute for grids (a `noise_grid` capability on the ladder), then as shader source,
each held to the same vectors within a stated tolerance. Not now: the conformance harness comes first, because it is what
proves a GPU rendering.
