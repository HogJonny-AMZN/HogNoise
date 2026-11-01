# Fold tests.yml into the template's ci.yml

**Section:** icebox
**Owner:** none
**State:** Iceboxed
**Cost:** 0.5 d
**Verdict:** Good
**Raised:** [journal](../../journal/2026-10-31-session-01.md)

Two workflows run today: the template's `ci.yml` (the gate on Ubuntu and Windows) and HogNoise's own `tests.yml`, whose
numpy-only leg and Python 3.11 with numpy 1.26 leg the template does not have. One workflow with those legs is simpler to
read and to keep green. Not now: both pass, and the merge is best done once the repository has a forge to run it on.
