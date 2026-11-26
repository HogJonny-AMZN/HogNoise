# A call past the device's buffer limit: see what happens, and refuse it clearly

**Section:** next
**Owner:** @HogJonny-AMZN
**State:** Planned 2026-11-25: [its plan](../../superpowers/plans/2026-11-25-a-call-past-the-buffer-limit.md) Proposed, on the owner's "Yes" to refusing a call past the limit before any upload (option A, not chunking or wgpu's error documented); waits on the owner's acceptance. Queued 2026-11-23, before PyPI, next in the agreed order once the HLSL landed ([PR #59](https://github.com/HogJonny-AMZN/HogNoise/pull/59), `3a83792`)
**Cost:** 0.5 d (one test past the limit on WARP; a refusal before dispatch if wgpu's own error is unclear)
**Verdict:** Minor, but done before PyPI: the first public caller past the limit should get a clear refusal, not wgpu's. Taken by the owner's "take them" (2026-11-23)
**Raised:** [the account](../../design/2026-11-20-gpu-fast-track-account.md), gap 7, [PR #39](https://github.com/HogJonny-AMZN/HogNoise/pull/39)

`hog_noise.gpu` takes the adapter's own limits and does not chunk. Probed 2026-11-25 (the plan's *Facts*): the RTX
5090 on Vulkan, D3D12 and OpenGL and WARP each bind at most 2,147,483,644 bytes, 536,870,911 float32 a call. One point
past it, wgpu raises its own validation error, in its terms (a buffer size, a binding number) that differ by back end
and after the axes are uploaded; no wrong answer and no crash, and the device runs on.
