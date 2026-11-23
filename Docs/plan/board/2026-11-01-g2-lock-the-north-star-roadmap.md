# G2: lock the north-star roadmap

**Section:** gate
**Owner:** none
**State:** Closed 2026-11-23 on the owner's "take them" (2026-11-23), recorded in [PR #45](https://github.com/HogJonny-AMZN/HogNoise/pull/45): parity keeps both libraries' algorithms by name; the GPU tolerance is locked as built (a tolerance file per rendering, rules measured per case, never loosened to pass a test); one shader source, WGSL (2026-11-01); the graph serialises to HogNoise's own JSON, a FastNoise2 importer later
**Decider:** @HogJonny-AMZN

[The roadmap](../../design/2026-11-01-north-star-roadmap.md) is Proposed. Locking it means answering its four decisions, one of which (the shader source) was answered on 2026-11-01:
what parity means where FastNoise2 and FastNoiseLite both have an algorithm (proposed: keep both, by name); the GPU tolerance
(proposed: a per-node bound, 1e-5 relative by default, set by measurement); one shader source (decided 2026-11-01: WGSL, with naga for the rest); and the graph's serialised form (proposed: HogNoise's own JSON, with a FastNoise2 importer later). Nothing
past stage 1, the conformance harness, may be committed to until this closes, with one exception: [the GPU fast track](2026-11-01-gpu-fast-track.md), which the owner locked on its own on 2026-11-01 and which ports today's kernels, not the graph, so no open decision here blocks it.
