# The wgpu rung on a macOS runner: Metal, if the runner offers a device

**Section:** now
**Owner:** @HogJonny-AMZN
**State:** Landed 2026-11-21 in [PR #42](https://github.com/HogJonny-AMZN/HogNoise/pull/42), on the owner's "proceed on your best recommendations": the runner gives wgpu an "Apple Paravirtual device" on Metal; 365 of 368 hog cases passed, the three NoiseLookup 2D cases flipped 0.02% of points, and on the owner's choice its record joined the tolerance file (seven adapters at `5340a3f`, five fields looser)
**Cost:** 0.5 d (to find out; a leg in `tests.yml` with `HOG_NOISE_REQUIRE_GPU=1`)
**Verdict:** Proposed: Worth a try, cheap; whether GitHub's macOS runners give wgpu a Metal adapter is untried. The owner's to confirm
**Raised:** [the account](../../design/2026-11-20-gpu-fast-track-account.md), gap 3, [PR #39](https://github.com/HogJonny-AMZN/HogNoise/pull/39)

Metal has never run HogNoise's shader. wgpu would run the WGSL on Metal directly, so a macOS leg is the cheapest way to
learn whether Apple's GPUs stay within the tolerance. If the runner finds an adapter, its measurement record joins the
others; if not, the leg is dropped and the reason recorded. Metal as a shipped file stays out: naga's command line
writes placeholder bindings.

The leg runs the library's and the app's tests, not the template's: on macOS the template's adopt test finds a
capitalisation check that relies on `os.path.realpath` reporting stored case, which it does on Windows and not on
macOS ([ai-first-template issue #265](https://github.com/HogJonny-AMZN/ai-first-template/issues/265)). When the
template fixes it, the leg can run the whole suite.
