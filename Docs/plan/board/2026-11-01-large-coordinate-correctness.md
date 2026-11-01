# Correctness at very large coordinates

**Section:** icebox
**Owner:** none
**State:** Iceboxed
**Cost:** 2 to 3 d
**Verdict:** Good
**Raised:** [README, Wanted](../../../README.md)

A guaranteed result at 1e5 to 1e7 world units, where float32 hashing falls apart, checked by new vectors far from the origin
against float64. It is what planet-scale worlds need. Not now: no consumer has asked yet.
