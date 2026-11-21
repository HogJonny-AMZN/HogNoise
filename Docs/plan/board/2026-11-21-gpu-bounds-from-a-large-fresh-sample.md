# GPU bounds derived from a large fresh sample, not only the vectors' points

**Section:** icebox
**Owner:** none
**State:** Iceboxed
**Cost:** 1 to 2 d (`hog-noise-measure-gpu run` adds fresh points per feature against numpy, the records grow, `derive` reads both; tests; a re-derivation on every adapter)
**Verdict:** Proposed: Needed before the bounds are quoted as holding anywhere in the range; today they hold on the vectors' points. The owner's to confirm
**Raised:** [the far-coordinate probe](../../../Spikes/far_coordinates/README.md), 2026-11-21

On 65,536 fresh points inside the measured range, 12 probes on the RTX 5090 exceed their feature's rule at 1 or 2
points (at most 8.5 times the bound), and on WARP 23 do (156 points of 14.9 million). The rules were derived from the
vectors' 4,096 points per case, so a tail rarer than about 1 in 4,096 is never seen. The reference for fresh points is
numpy, which reproduces the hog set bit for bit, so no new vectors are needed. The vectors stay as the check. The other
choice is to keep the bounds and say they hold on the vectors' points, as the README now does. This changes how the
tolerance file is made, so the owner decides. Not built now because it waits on that decision.
