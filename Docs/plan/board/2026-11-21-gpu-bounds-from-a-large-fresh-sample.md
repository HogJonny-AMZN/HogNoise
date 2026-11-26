# GPU bounds derived from a large fresh sample, not only the vectors' points

**Section:** now
**Owner:** @HogJonny-AMZN
**State:** Landed 2026-11-25 in [PR #58](https://github.com/HogJonny-AMZN/HogNoise/pull/58), merged as `8e77673`: [its plan](../../superpowers/plans/2026-11-24-gpu-bounds-from-a-fresh-sample.md) Accepted (merged in [PR #56](https://github.com/HogJonny-AMZN/HogNoise/pull/56), `620750a`), built; form C2 on the owner's "I'll take your best recommendation" (a continuous rule's tight bound met by a measured fraction of points, at most 0.9999 and 0.9993 at the lowest in the trial, under a fixed ceiling), trial-run twice; the far probe, the acceptance check, passed 246 of 246 probes inside 4,096 units on three adapters
**Cost:** 2 d (the plan's ten tasks: `run` draws 65,536 fresh points a case, `derive` reads both samples, tolerance format 2, every adapter measured again, the far probe as acceptance)
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

**Planned, 2026-11-24.** The owner chose two tiers and 65,536 points a case, and the plan's first trial disproved two tiers with an outer bound from a sample's worst: the far probe's own points failed it at up to 4.5 times, because a uniform draw missed the Perlin tail near the origin and rare spikes (a few a million, at 3 to 13 times the bound) are not bounded by any sample's worst. On the owner's "I'll take your best recommendation", [the plan](../../superpowers/plans/2026-11-24-gpu-bounds-from-a-fresh-sample.md) takes form C2: fresh points drawn the probe's way, a continuous rule's tight bound held for the measured fraction (at most 0.9999) under the fixed ceiling `LARGEST`. Its second trial passed the probe: 246 of 246 probes inside 4,096 units on three adapters.
