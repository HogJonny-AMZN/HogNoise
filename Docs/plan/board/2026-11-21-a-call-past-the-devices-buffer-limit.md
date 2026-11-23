# A call past the device's buffer limit: see what happens, and refuse it clearly

**Section:** next
**Owner:** @HogJonny-AMZN
**State:** Queued 2026-11-23: before PyPI, after the CI proof's HLSL pull request
**Cost:** 0.5 d (one test past the limit on WARP; a refusal before dispatch if wgpu's own error is unclear)
**Verdict:** Minor, but done before PyPI: the first public caller past the limit should get a clear refusal, not wgpu's. Taken by the owner's "take them" (2026-11-23)
**Raised:** [the account](../../design/2026-11-20-gpu-fast-track-account.md), gap 7, [PR #39](https://github.com/HogJonny-AMZN/HogNoise/pull/39)

`hog_noise.gpu` takes the adapter's own limits (2 GiB per storage binding on the RTX 5090, about 536 million float32
values per axis) and does not chunk. A call past the limit has never been tried, and the software adapters' limits are
not recorded. Not built now because the account's verdicts wait on the owner.
