# The warp outputs' GPU rules, coordinate-scaled like the noise rules

**Section:** now
**Owner:** @HogJonny-AMZN
**State:** Landed 2026-11-24 in [PR #53](https://github.com/HogJonny-AMZN/HogNoise/pull/53) (`7ad23ff`): option A, the existing `coordinate_scaled` bound (the owner's "go"); the far probe's 18 warp outputs pass past 32,768 units on three adapters
**Cost:** 0.5 d (one branch in `measure_gpu.derive`, its test, a re-derivation from the committed records, `vectors/README.md`'s *Tolerance files*)
**Verdict:** Good; an absolute bound on a coordinate cannot hold past a few thousand units for any float32 shader. Taken by the owner's "take them" (2026-11-23)
**Raised:** [the far-coordinate probe](../../../Spikes/far_coordinates/README.md), 2026-11-21

All 18 warp outputs fail their rules past 32,768 units on every adapter measured, and 17 or 18 of them between 4,096 and 32,768, by up to 250 times at a million. Their drift is 3 to 8
float32 steps of the coordinate being warped, so it grows as the coordinate does. Their rules are absolute (5e-4 to
5e-3) because the reference warps the raw coordinates before the frequency multiply (`vectors/README.md`). A rule scaled
by the raw coordinate, not the noise coordinate, would follow the drift at every distance. This changes the tolerance
file, so the owner decides.

**Built (option A, 2026-11-24).** Two options were put to the owner: A, reuse the existing coordinate-scaled bound,
`scale * max(1, |coordinate| * frequency)`; B, a new bound scaled by the raw coordinate, with a schema change and every
adapter measured again. At one frequency the two differ only by a constant, and every hog warp case is at frequency
0.01, the one the tolerance file's `range` names. So A follows the drift as B would, from the records already
committed. `derive` now takes a warp rule from `max_normalised`, as a noise rule, and the nine warp rules went from
absolute 5e-4 to 5e-3 to coordinate-scaled 5e-5 to 2e-4. The probe, run again with them
([after-warp-rules/](../../../Spikes/far_coordinates/after-warp-rules/)): every warp output passes past 32,768 units on
the 5090's Vulkan and D3D12 and on WARP, at 0.6 to 0.73 of its bound out to 1,048,576. Inside 32,768 units, 1 to 3
points per band (of 18 x 65,536) still fall past the bound of one or two warp outputs, as some noise probes' points do: that is the rare
tail [the fresh-sample bounds](2026-11-21-gpu-bounds-from-a-large-fresh-sample.md) are for. The cost of A: a warp rule
holds at the frequencies `range` names and no others, which is what the file already claims.
