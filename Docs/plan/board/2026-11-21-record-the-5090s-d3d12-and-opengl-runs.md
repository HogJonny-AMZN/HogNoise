# Record the 5090's D3D12 and OpenGL runs, and say how to choose a back end

**Section:** now
**Owner:** @HogJonny-AMZN
**State:** Started 2026-11-21 on the owner's "proceed": six measurement records at `efb910a` (the 5090 on Vulkan, D3D12 and OpenGL, WARP local and on CI, llvmpipe), the tolerance file derived from them, the README says how to choose a back end; the optional `device (backend)` match is not done
**Cost:** 0.5 d (two measurement records, a re-derivation of the tolerance file, a README paragraph; the optional `device (backend)` match is a test and a few lines more)
**Verdict:** Proposed: Good, very cheap, and first in the account's order. The owner's to confirm
**Raised:** [the account](../../design/2026-11-20-gpu-fast-track-account.md), gap 6, [PR #39](https://github.com/HogJonny-AMZN/HogNoise/pull/39)

On 2026-11-20 the RTX 5090 passed every hog case on D3D12 and on OpenGL, chosen with `WGPU_BACKEND_TYPE` while
`HOG_NOISE_WGPU_ADAPTER` was unset. With the name variable set, the back end is ignored and the first device whose name
matches wins, which for the 5090 is always Vulkan. Neither behaviour is written down.

The work: `WGPU_BACKEND_TYPE=D3D12 hog-noise-measure-gpu run` and the same for OpenGL; records for every adapter at one
commit, then `derive`; the README's *On the GPU* says how to choose a back end. Optionally, match the name variable
against `device (backend)`, so a device and a back end can be named together. Not built now because the account's
verdicts wait on the owner.
