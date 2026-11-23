# The emitted SPIR-V runs against the vectors in a Vulkan driver, on lavapipe

**Section:** next
**Owner:** @HogJonny-AMZN
**State:** Queued 2026-11-23: the CI proof's third pull request, (c), after the HLSL; its plan is written when (b) merges
**Cost:** 1 d (the spec's estimate: a Vulkan back end of (b)'s C++ harness, on Ubuntu with `libvulkan-dev`)
**Verdict:** Good: without it no driver ever reads the SPIR-V a host ships, since wgpu 0.33 has no passthrough. Taken with the spec's decision 1, Accepted 2026-11-22
**Raised:** [the CI proof's spec](../../superpowers/specs/2026-11-22-emitted-shaders-ci-proof.md), decisions 1 and 5, split into rows 2026-11-23 by [its plan](../../superpowers/plans/2026-11-23-emitted-shaders-ci-proof.md) (decision P2)
**Waits on:** [the HLSL on WARP](2026-11-23-the-emitted-hlsl-runs-on-warp.md)

`noise.spv` given to Mesa's lavapipe through Vulkan by the same persistent C++ harness as
[(b)](2026-11-23-the-emitted-hlsl-runs-on-warp.md), with a Vulkan back end. [The first pull request](2026-11-18-emitted-shaders-run-against-the-vectors.md)
runs the same file through wgpu, where naga reads it back into its own IR; this row is the driver consuming the bytes.
