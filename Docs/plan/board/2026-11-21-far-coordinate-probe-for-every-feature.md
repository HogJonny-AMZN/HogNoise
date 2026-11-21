# A far-coordinate probe for every feature, to size the large-coordinate stage

**Section:** icebox
**Owner:** none
**State:** Iceboxed
**Cost:** 0.5 d (a probe script and a table; the fix is the large-coordinate row's own cost)
**Verdict:** Proposed: Needed before the GPU is used for a large world; measure before fixing. The owner's to confirm
**Raised:** [the account](../../design/2026-11-20-gpu-fast-track-account.md), gap 1, [PR #39](https://github.com/HogJonny-AMZN/HogNoise/pull/39)

The tolerance is measured at frequency 0.01 out to 4,096 units. The stage 1 spike showed the coordinate-scaled bound
holding to 262,144 units for OpenSimplex2 alone. This probe runs every hog feature on the 5090 in the spike's coordinate
bands against the numpy rendering and says which features stay within their rule far out and which do not: the
discrete ones (cellular `cellvalue`, the grids) and the warps, whose output rules are absolute, are the likely first to
break. Its table sizes [the large-coordinate stage](2026-11-01-large-coordinate-correctness.md). Not built now because
the account's verdicts wait on the owner.
