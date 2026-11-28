# The emitted SPIR-V runs against the vectors in a Vulkan driver, on lavapipe

**Section:** now
**Owner:** @HogJonny-AMZN
**State:** Built in [PR #65](https://github.com/HogJonny-AMZN/HogNoise/pull/65), in review; its landing date is written from the merge (P-31). `noise.spv`, given as bytes to Mesa's lavapipe through Vulkan in a C++ harness written from the shaders README, passes every hog case within `wgpu.json` unmodified in CI's `spirv-vulkan` job (79 passed, 47 skipped; `vulkaninfo`: `llvmpipe (LLVM 21.1.8, 256 bits)`, `PHYSICAL_DEVICE_TYPE_CPU`, Mesa 26.0.8), as it did in the trial's `ubuntu:26.04` container, where four mutants of the harness each failed; the HLSL hosts still pass on WARP. [Its plan](../../superpowers/plans/2026-11-27-the-emitted-spirv-on-lavapipe.md) Accepted 2026-11-27 with L1 to L7 as recommended ([PR #64](https://github.com/HogJonny-AMZN/HogNoise/pull/64))
**Cost:** 1 d (the spec's estimate: a Vulkan back end of (b)'s C++ harness, on Ubuntu with `libvulkan-dev`)
**Verdict:** Good: without it no driver ever reads the SPIR-V a host ships, since wgpu 0.33 has no passthrough. Taken with the spec's decision 1, Accepted 2026-11-22
**Raised:** [the CI proof's spec](../../superpowers/specs/2026-11-22-emitted-shaders-ci-proof.md), decisions 1 and 5, split into rows 2026-11-23 by [its plan](../../superpowers/plans/2026-11-23-emitted-shaders-ci-proof.md) (decision P2)

`noise.spv` given to Mesa's lavapipe through Vulkan by a persistent C++ harness that shares
[(b)](2026-11-23-the-emitted-hlsl-runs-on-warp.md)'s frames and loop. [The first pull request](2026-11-18-emitted-shaders-run-against-the-vectors.md)
runs the same file through wgpu, where naga reads it back into its own IR; this row is the driver consuming the bytes.

**What (b) decided for it** (its plan's B6): (c) shares the HLSL harness's frame format, not its code, since
that harness is D3D and Windows-only. Whether a Vulkan back end joins `hlsl_host.cpp` or is a harness of its own,
built on Linux, is (c)'s plan's decision.

**What (c) built** (its plan's decisions L2 and L3): the frame code turned out D3D-free, so the format and the code
are shared, in `hosts/frames.h` and `hosts.harness`, and the Vulkan back end is a harness of its own, `vulkan_host.cpp`,
built on Linux by g++. Not proven: the barrier before the read back (lavapipe's memory is coherent), hardware Vulkan,
and a Windows Vulkan build (the plan's *Not covered*).
