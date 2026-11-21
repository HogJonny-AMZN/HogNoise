# Harden the GPU fast track: what holds it up, and what does not yet

**Section:** now
**Owner:** @HogJonny-AMZN
**State:** Landed 2026-11-20 in [PR #39](https://github.com/HogJonny-AMZN/HogNoise/pull/39): [the account](../../design/2026-11-20-gpu-fast-track-account.md), Proposed: eight claims hold within the measured range, seven gaps each with a proposed verdict waiting on the owner; the CI proof is not part of it
**Cost:** 1 to 2 d (the account; each gap it finds is sized there)
**Verdict:** Needed: the track was fast by design, so what it rests on is written down before anything is built on it
**Raised:** [the session journal, 2026-11-18](../../journal/2026-11/2026-11-18-HogJonny-AMZN-0147.md)

The owner, 2026-11-18: having fast-tracked [the GPU work](2026-11-01-gpu-fast-track.md), know what shored it up and
that it was done correctly, before the host work. One document: each claim the track makes (the wgpu rung matches the
CPU within its tolerance; the emitted shaders are its WGSL), the evidence behind it with its commit and run, and the
gaps, each with a verdict. Gaps already known: the tolerance is measured at frequency 0.01 out to 4,096 units, and far
coordinates wait on [the large-coordinate stage](2026-11-01-large-coordinate-correctness.md); one discrete GPU (NVIDIA),
no AMD, Intel or Apple hardware; nothing benchmarked; no host has run the emitted shaders; no Metal.

The account decides whether [the CI proof](2026-11-18-emitted-shaders-run-against-the-vectors.md) is part of the
hardening. [The engine trials](2026-11-18-engine-host-trials.md) come after it, and when the core is done.
