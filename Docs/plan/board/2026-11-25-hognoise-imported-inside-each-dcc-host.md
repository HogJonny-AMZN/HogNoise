# HogNoise imported inside each DCC host, through HogShade's BATS

**Section:** next
**Owner:** @HogJonny-AMZN
**State:** Queued 2026-11-25, with [the DCC hosts](../../standards/compatibility-matrix-project.md); after the fresh-sample bounds and the HLSL build in the agreed order, unless the owner moves it
**Cost:** 1 to 1.5 d (a BATS job module in HogShade that installs the pinned HogNoise wheel with `--no-deps` into a host's Python, imports it, samples a handful of hog cases and compares them with the vectors bit for bit; run on the Maya 2026 and Blender 5.2 workers; a record per host and run)
**Verdict:** Good. CI recreates a host's Python and numpy; only the host shows that HogNoise imports beside what the host itself loads, and that installing it left the host's numpy alone. Worth it before PyPI, since a DCC is where most users will meet it
**Raised:** [the journal, 2026-11-25](../../journal/2026-11/2026-11-25-HogJonny-AMZN-0245.md): the owner, *"we will need to be able to have a HogNoise that is importable to the DCC packages that we are going to support, their versions of Python. and their versions of NumPy, etc"*

BATS (HogShade's Job_Orchestrator) already runs headless Maya 2026 and Blender 5.2 workers. HogHydra's session read each
host's Python and numpy through them (LargeWorlds' [shared table](https://github.com/HogJonny-AMZN/LargeWorlds/blob/main/Docs/knowledge/shared-dependency-versions.md)).
The job runs only where a worker exists: Houdini 21 and Unreal 5.8 have none yet, so a CI point stands for them, and
Unreal's path is HogHydra's to settle (*"it supports USD and MaterialX"*). Marmoset Toolbag 4 is out: Python 3.9.4 with
no numpy, and the owner would move to Toolbag 5 before solving for it.

Not on every pull request: a host run is minutes and needs this machine. Before a release, and when a host's version
changes. The job module lives in HogShade, whose BATS it is; this repository holds the row and reads the record.
