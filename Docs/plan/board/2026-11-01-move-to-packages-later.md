# Move the package to packages/, later

**Section:** now
**Owner:** @HogJonny-AMZN
**State:** Landed 2026-11-13 in [PR #18](https://github.com/HogJonny-AMZN/HogNoise/pull/18), with ai-first-template 0.9.4: its 0.7.0 layout is the template's own, so the move is no override. The library is the workspace member `packages/python/hog-noise/`; the owner, 2026-11-13: "yes we need to adapt to the specified layout".
**Cost:** 0.5 d (the folder move and the paths; the template's side first)
**Verdict:** Good, later
**Raised:** [journal](../../journal/2026-11/2026-11-01-HogJonny-AMZN-0446.md)

The owner, 2026-11-01: "src/ is fine for now packages/ will come later." `packages/` is where the owner's repositories keep
named packages (LargeWorlds already does), but the template reads `src/` by name in its layer rule, its boundary check and
`init adopt`, so moving now would make HogNoise override the template from its first day. Not now: it waits on the template
supporting a configurable package root (`src` by default, `packages` allowed), and then it is a folder move with no override.
