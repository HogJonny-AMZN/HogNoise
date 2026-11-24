# The emitted HLSL runs against the vectors on WARP, through D3D11 and D3D12

**Section:** next
**Owner:** @HogJonny-AMZN
**State:** Queued 2026-11-23: the CI proof's second pull request, (b). (a), [PR #49](https://github.com/HogJonny-AMZN/HogNoise/pull/49), merged 2026-11-23 (`adf4f30`), so its plan can be written
**Cost:** 1.5 d (the spec's estimate: a C++ harness, FXC `cs_5_0` on D3D11 and DXC `cs_6_0` on D3D12, both on WARP)
**Verdict:** Needed before PyPI: the release's condition names HLSL, and today it only compiles. Taken with the spec, Accepted 2026-11-22
**Raised:** [the CI proof's spec](../../superpowers/specs/2026-11-22-emitted-shaders-ci-proof.md), decision 5, split into rows 2026-11-23 by [its plan](../../superpowers/plans/2026-11-23-emitted-shaders-ci-proof.md) (decision P2)

`noise.hlsl` run by a host written from [the shaders README](../../../packages/python/hog-noise/src/hog_noise/shaders/README.md)
alone: a persistent C++ process in `apps/hog-noise-tools/hosts/`, one dispatch per request on its standard input and
output, so `conformance.check` stays synchronous (the spec, *What gets built*). It is driven through the
`hog_noise_tools.hosts` contract (a) builds, so its plan follows (a)'s `HostSampler.run` rather than guessing at it.

The spec's open risk is here: whether naga's HLSL uses anything D3D11 rejects when the pipeline is created, not when it
compiles. The Vulkan back end of the same harness is [(c)](2026-11-23-the-emitted-spirv-runs-on-lavapipe.md).
