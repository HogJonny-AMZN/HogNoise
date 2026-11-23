# The emitted shaders run against the vectors, headless in CI: the host harness, SPIR-V through naga, and GLSL

**Section:** now
**Owner:** @HogJonny-AMZN
**State:** Landed 2026-11-23 in [PR #49](https://github.com/HogJonny-AMZN/HogNoise/pull/49): `noise.spv` runs through wgpu's SPIR-V front end on WARP, llvmpipe (Vulkan and OpenGL) and Metal, and the five GLSL files in moderngl on llvmpipe through EGL, each host written from the shaders README alone, every hog case within `vectors/tolerance/wgpu.json` unmodified. Bit for bit with the rung on D3D12, Vulkan and OpenGL; on Metal `sample_points_3d` differs by up to 3.58e-7. Built from [its plan](../../superpowers/plans/2026-11-23-emitted-shaders-ci-proof.md), Accepted 2026-11-23 with its five decisions as recommended. Started 2026-11-22 on the owner's "your best recommendations": [the spec](../../superpowers/specs/2026-11-22-emitted-shaders-ci-proof.md) Accepted 2026-11-22 with its five decisions as recommended. Narrowed 2026-11-23 to the spec's first pull request, (a): [its plan](../../superpowers/plans/2026-11-23-emitted-shaders-ci-proof.md) Accepted 2026-11-23 with its five decisions as recommended, nine tasks; the build started 2026-11-23
**Cost:** 1 to 1.5 d (the shared harness and `spirv-naga` 0.5 d, GLSL 0.5 to 1 d; the spec's split of its 3 to 5 d)
**Verdict:** Good: the cheapest step from "compiles" to "proven", and what every host trial waits on
**Raised:** [the session journal, 2026-11-18](../../journal/2026-11/2026-11-18-HogJonny-AMZN-0147.md)

Decided again 2026-11-20, when the hardening landed: [the account](../../design/2026-11-20-gpu-fast-track-account.md)
makes this its gap 4, its own work rather than part of the hardening, and recommends it before the PyPI release. On
that day the RTX 5090 ran naga's HLSL, GLSL and SPIR-V translations of the shader through wgpu and passed every hog case,
which lowers the risk of the HLSL and GLSL legs. Those were not the shipped files.

The [emitted shaders](../../../packages/python/hog-noise/src/hog_noise/shaders/README.md) compile in each language's
own tools and match their WGSL, and nothing more: no host has run them. The spec runs each one on a software GPU CI
already has, bound by the manifest, and holds the output to the committed vectors within `vectors/tolerance/wgpu.json`,
the tolerance the wgpu rung is held to. It does so in three pull requests (its decision 5), and since 2026-11-23 each is
a row, so a row waiting on one of them waits on exactly that one (the plan's decision P2):

- **This row, (a):** the shared host harness (`hog_noise_tools.hosts`); `noise.spv` through wgpu's SPIR-V front end on
  the three existing GPU legs; the GLSL in moderngl on llvmpipe.
- **(b)** [the HLSL on WARP](2026-11-23-the-emitted-hlsl-runs-on-warp.md): D3D11 and D3D12, a small C++ harness. It
  meets the PyPI condition.
- **(c)** [the SPIR-V on lavapipe](2026-11-23-the-emitted-spirv-runs-on-lavapipe.md): a Vulkan driver consumes the
  shipped bytes.

A failure here is a finding about naga's translation or the manifest, before any engine sees the files, so it goes before
[the engine trials](2026-11-18-engine-host-trials.md).
