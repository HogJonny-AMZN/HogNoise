# GPU bounds derived from a large fresh sample, not only the vectors' points

**Section:** next
**Owner:** @HogJonny-AMZN
**State:** Queued 2026-11-23: after the warp rules and the CI proof's first pull request, before PyPI
**Cost:** 1 to 2 d (`hog-noise-measure-gpu run` adds fresh points per feature against numpy, the records grow, `derive` reads both; tests; a re-derivation on every adapter)
**Verdict:** Needed before the bounds are quoted as holding anywhere in the range; it measures the real tail, which is the owner's decision, not a rule loosened to pass. Taken by the owner's "take them" (2026-11-23)
**Raised:** [the far-coordinate probe](../../../Spikes/far_coordinates/README.md), 2026-11-21

On 65,536 fresh points per probe inside the measured range, some probes fail their rule on every adapter:

| Adapter | Continuous noise | Discrete, on the tight bound | Warp outputs | Noise points past the outer bound, pooled |
| --- | --- | --- | --- | --- |
| RTX 5090, Vulkan | 10 | 0 | 2 | 15 |
| RTX 5090, D3D12 | 9 | 3 (NoiseLookup 2D) | 2 | 14 |
| WARP | 20 | 3 (NoiseLookup 2D) | 2 | 156 |

The pooled counts are out of 14.9 million. The worst is 4.9 times the bound for the noise and 8.5 times for a warp. The rules were derived from the
vectors' 4,096 points per case, so a tail rarer than about 1 in 4,096 is never seen. The reference for fresh points is
numpy, which reproduces the hog set bit for bit, so no new vectors are needed. The vectors stay as the check. The other
choice is to keep the bounds and say they hold on the vectors' points, as the README now does. This changes how the
tolerance file is made, so the owner decides. Not built now because it waits on that decision.
