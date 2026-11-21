# The wgpu rung on a macOS runner: Metal, if the runner offers a device

**Section:** now
**Owner:** @HogJonny-AMZN
**State:** In flight, on the owner's "proceed on your best recommendations" (2026-11-21): a macOS leg in `tests.yml`
**Cost:** 0.5 d (to find out; a leg in `tests.yml` with `HOG_NOISE_REQUIRE_GPU=1`)
**Verdict:** Proposed: Worth a try, cheap; whether GitHub's macOS runners give wgpu a Metal adapter is untried. The owner's to confirm
**Raised:** [the account](../../design/2026-11-20-gpu-fast-track-account.md), gap 3, [PR #39](https://github.com/HogJonny-AMZN/HogNoise/pull/39)

Metal has never run HogNoise's shader. wgpu would run the WGSL on Metal directly, so a macOS leg is the cheapest way to
learn whether Apple's GPUs stay within the tolerance. If the runner finds an adapter, its measurement record joins the
others; if not, the leg is dropped and the reason recorded. Metal as a shipped file stays out: naga's command line
writes placeholder bindings.
