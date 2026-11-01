# G2: lock the north-star roadmap

**Section:** gate
**Owner:** none
**State:** Open
**Decider:** @HogJonny-AMZN

[The roadmap](../../design/2026-11-01-north-star-roadmap.md) is Proposed. Locking it means answering its four decisions:
what parity means where FastNoise2 and FastNoiseLite both have an algorithm (proposed: keep both, by name); the GPU tolerance
(proposed: a per-node bound, 1e-5 relative by default, set by measurement); one shader source (proposed: Slang, if its WGSL
runs through wgpu); and the graph's serialised form (proposed: HogNoise's own JSON, with a FastNoise2 importer later). Nothing
past stage 1, the conformance harness, may be committed to until this closes.
