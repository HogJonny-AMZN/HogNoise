# G2: lock the north-star roadmap

**Section:** gate
**Owner:** none
**State:** Closed 2026-11-23 on the owner's "take them" (2026-11-23), recorded in [PR #45](https://github.com/HogJonny-AMZN/HogNoise/pull/45): parity keeps both libraries' algorithms by name; the GPU tolerance is locked as built (a tolerance file per rendering, rules measured per case, never loosened to pass a test); one shader source, WGSL (2026-11-01); the graph serialises to HogNoise's own JSON, a FastNoise2 importer later
**Decider:** @HogJonny-AMZN

[The roadmap](../../design/2026-11-01-north-star-roadmap.md) is Accepted, and its four decisions are the ones in *State*.
The GPU tolerance it locks is the one CI enforces, a tolerance file per rendering with each rule measured per case. The
roadmap had proposed a per-node bound of 1e-5 relative by default, but that was never what got measured, so it was not
locked.

*History, while the gate was open (2026-11-01 to 2026-11-23):* nothing past stage 1, the conformance harness, could be
committed to, with one exception: [the GPU fast track](2026-11-01-gpu-fast-track.md), which the owner locked on its own on
2026-11-01 and which ports today's kernels, not the graph.
