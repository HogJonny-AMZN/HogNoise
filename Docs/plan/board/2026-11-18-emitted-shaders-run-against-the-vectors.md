# The emitted shaders run against the vectors, headless in CI

**Section:** now
**Owner:** @HogJonny-AMZN
**State:** Started 2026-11-22 on the owner's "your best recommendations": [the spec](../../superpowers/specs/2026-11-22-emitted-shaders-ci-proof.md) Accepted 2026-11-22 with its five decisions as recommended; the plan is next, then three pull requests; nothing built
**Cost:** 3 to 5 d (about 1 d per language, plus the harness's shared half)
**Verdict:** Good: the cheapest step from "compiles" to "proven", and what every host trial waits on
**Raised:** [the session journal, 2026-11-18](../../journal/2026-11/2026-11-18-HogJonny-AMZN-0147.md)

Decided again 2026-11-20, when the hardening landed: [the account](../../design/2026-11-20-gpu-fast-track-account.md)
makes this its gap 4, its own work rather than part of the hardening, and recommends it before the PyPI release. On
that day the RTX 5090 ran naga's HLSL, GLSL and SPIR-V translations of the shader through wgpu and passed every hog case,
which lowers the risk of the HLSL and GLSL legs. Those were not the shipped files.

The [emitted shaders](../../../packages/python/hog-noise/src/hog_noise/shaders/README.md) compile in each language's
own tools and match their WGSL, and nothing more: no host has run them. This row runs each one on a software GPU CI
already has, fills the bindings from the manifest, and holds the output to the committed vectors within
`vectors/tolerance/wgpu.json`, the tolerance the wgpu rung is held to:

- **GLSL 4.30**: moderngl (open source, Python) on llvmpipe, Ubuntu. The cheapest of the three, so the first.
- **SPIR-V**: a small Vulkan compute harness on lavapipe, Ubuntu.
- **HLSL**: a small D3D11 (`cs_5_0`) and D3D12 (`cs_6_0`) harness on WARP, Windows.

A failure here is a finding about naga's translation or the manifest, before any engine sees the files, so it goes before
[the engine trials](2026-11-18-engine-host-trials.md). The hardening decides whether it is part of the hardening itself.

Two rows wait on one pull request of this row, not on all three. [The fresh-sample bounds](2026-11-21-gpu-bounds-from-a-large-fresh-sample.md)
wait on the first, and [the buffer-limit refusal](2026-11-21-a-call-past-the-devices-buffer-limit.md) waits on the HLSL
one. The `waits-on` check sees only whole rows, so when this row's plan names its pull requests, each of those two gets a
row of its own and both `Waits on` lines are re-pointed to it, in the plan's pull request.
