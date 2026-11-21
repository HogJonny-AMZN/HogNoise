# The warp outputs' GPU rules, coordinate-scaled like the noise rules

**Section:** icebox
**Owner:** none
**State:** Iceboxed
**Cost:** 0.5 d (one branch in `measure_gpu.derive`, its test, a re-derivation from the committed records, `vectors/README.md`'s *Tolerance files*)
**Verdict:** Proposed: Good; an absolute bound on a coordinate cannot hold past a few thousand units for any float32 shader. The owner's to confirm
**Raised:** [the far-coordinate probe](../../../Spikes/far_coordinates/README.md), 2026-11-21

All 18 warp outputs fail their rules past 32,768 units on every adapter measured, and 17 or 18 of them between 4,096 and 32,768, by up to 250 times at a million. Their drift is 3 to 8
float32 steps of the coordinate being warped, so it grows as the coordinate does. Their rules are absolute (5e-4 to
5e-3) because the reference warps the raw coordinates before the frequency multiply (`vectors/README.md`). A rule scaled
by the raw coordinate, not the noise coordinate, would follow the drift at every distance. This changes the tolerance
file, so the owner decides. Not built now because it waits on that decision.
