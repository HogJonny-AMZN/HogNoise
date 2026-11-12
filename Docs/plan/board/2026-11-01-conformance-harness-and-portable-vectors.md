# A conformance harness other ports can run, and the vectors in a language-neutral format

**Section:** next
**Owner:** @HogJonny-AMZN
**State:** Design Accepted 2026-11-11 (the owner: "lock it"); [spec](../../superpowers/specs/2026-11-11-conformance-harness.md) Proposed 2026-11-11; then the plan, then code
**Cost:** 1 to 2 d
**Raised:** [README, Wanted](../../../README.md)

`hog_noise.conformance.check(callable)` runs any sampler against the committed vectors, and the vectors are also exported as
raw arrays with a JSON manifest, so a port in another language (WGSL, HLSL, C#) can validate itself. It turns the vectors
from this package's test data into the reference anyone can use. Published on 2026-11-01, so publishing no longer comes first; the owner put it before the GPU fast track's port (2026-11-02),
which it will check.

[The design](../../design/2026-11-02-conformance-harness.md): both reference sets (*original* and a new *hog*), the vectors
in a top-level `vectors/` as raw float32 plus one manifest, `check(sample, vectors)` with a per-case bound, and each case
saying what it outputs (noise or warp) and how it is compared (points, shape or advisory).
