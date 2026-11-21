# A call past the device's buffer limit: see what happens, and refuse it clearly

**Section:** icebox
**Owner:** none
**State:** Iceboxed
**Cost:** 0.5 d (one test past the limit on WARP; a refusal before dispatch if wgpu's own error is unclear)
**Verdict:** Proposed: Minor; the likely result is wgpu's validation error, not a wrong answer, but nobody has seen it. The owner's to confirm
**Raised:** [the account](../../design/2026-11-20-gpu-fast-track-account.md), gap 7, [PR #39](https://github.com/HogJonny-AMZN/HogNoise/pull/39)

`hog_noise.gpu` takes the adapter's own limits (2 GiB per storage binding on the RTX 5090, about 536 million float32
values per axis) and does not chunk. A call past the limit has never been tried, and the software adapters' limits are
not recorded. Not built now because the account's verdicts wait on the owner.
