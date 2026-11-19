# The emitted shaders run against the vectors, headless in CI

**Section:** icebox
**Owner:** none
**State:** Iceboxed
**Cost:** 3 to 5 d (about 1 d per language, plus the harness's shared half)
**Verdict:** Good: the cheapest step from "compiles" to "proven", and what every host trial waits on
**Raised:** [the session journal, 2026-11-18](../../journal/2026-11/2026-11-18-HogJonny-AMZN-0147.md)

The [emitted shaders](../../../packages/python/hog-noise/src/hog_noise/shaders/README.md) compile in each language's
own tools and match their WGSL, and nothing more: no host has run them. This row runs each one on a software GPU CI
already has, fills the bindings from the manifest, and holds the output to the committed vectors within
`vectors/tolerance/wgpu.json`, the tolerance the wgpu rung is held to:

- **GLSL 4.30**: moderngl (open source, Python) on llvmpipe, Ubuntu. The cheapest of the three, so the first.
- **SPIR-V**: a small Vulkan compute harness on lavapipe, Ubuntu.
- **HLSL**: a small D3D11 (`cs_5_0`) and D3D12 (`cs_6_0`) harness on WARP, Windows.

A failure here is a finding about naga's translation or the manifest, before any engine sees the files. The engine trials,
[their own row](2026-11-18-engine-host-trials.md), wait on this one.
