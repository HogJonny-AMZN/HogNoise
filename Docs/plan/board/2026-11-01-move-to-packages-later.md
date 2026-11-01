# Move the package to packages/, later

**Section:** icebox
**Owner:** none
**State:** Iceboxed
**Cost:** 0.5 d (the folder move and the paths; the template's side first)
**Verdict:** Good, later
**Raised:** [journal](../../journal/2026-11/2026-11-01-HogJonny-AMZN-0446.md)

The owner, 2026-11-01: "src/ is fine for now packages/ will come later." `packages/` is where the owner's repositories keep
named packages (LargeWorlds already does), but the template reads `src/` by name in its layer rule, its boundary check and
`init adopt`, so moving now would make HogNoise override the template from its first day. Not now: it waits on the template
supporting a configurable package root (`src` by default, `packages` allowed), and then it is a folder move with no override.
