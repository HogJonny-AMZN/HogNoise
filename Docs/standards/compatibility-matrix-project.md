# Compatibility matrix: HogNoise's additions, the DCC hosts

**Status:** Living. Extends [compatibility-matrix.md](compatibility-matrix.md), which names the coding harnesses; this
file adds the other compatibility HogNoise owes, the DCC hosts it is imported into. It adds rules and never weakens the
base.

## The rule

**HogNoise imports inside every supported DCC host on that host's own Python and numpy.** It cannot replace them. The
owner, 2026-11-25: *"we will need to be able to have a HogNoise that is importable to the DCC packages that we are going
to support, their versions of Python. and their versions of NumPy, etc"*.

- **The declared requirements admit every supported host's own Python and numpy, and their floors are the oldest
  host's:** Python 3.11 and numpy 1.26, Maya 2026's. A floor moves only when the owner drops the host that sets it.
  Raising numpy's to 2.x was tried once and was the wrong direction (the owner, 2026-11-25).
  - **numpy is never capped or excluded:** a newer host brings a newer numpy (Blender 5.2's 2.3.4), and HogNoise cannot
    choose it.
  - **Python's cap, `<3.14`, is the newest Python CI tests,** not a host limit. It rises when CI tests the next Python,
    which numba's support gates; a host on a newer Python is a reason to raise it.
  - `packages/python/hog-noise/tests/test_dcc_host_floors.py` checks each host's exact Python and numpy against the
    whole requirement, not its first clause, and the floors and numpy's openness. It refuses a narrowed requirement by
    naming what it drops.
- **The lock is HogNoise's own environment, not a host's.** Dependabot moves `uv.lock` only
  (`versioning-strategy: lockfile-only` in `.github/dependabot.yml`), because it rewrote a declared floor twice before
  ([PR #28](https://github.com/HogJonny-AMZN/HogNoise/pull/28), [PR #47](https://github.com/HogJonny-AMZN/HogNoise/pull/47),
  `uv-build`'s). HogNoise does not lock to the shared table that its consumers lock to: it supports a range (LargeWorlds'
  table, its rule 3).
- **The core imports on numpy alone.** numba and wgpu are extras a host may lack; every noise has a numpy base, and CI's
  numpy-only leg proves it.
- **Installing into a host never upgrades the host's numpy:** `<host python> -m pip install --no-deps hog-noise`, or the
  wheel on the host's script path. HogNoise is one pure-Python wheel (`py3-none-any`), so one file serves every host.
- **Each supported host's Python and numpy is a CI point** in `.github/workflows/tests.yml`. One point covers the hosts
  that share it.

## The hosts

The versions are LargeWorlds' [shared dependency table](https://github.com/HogJonny-AMZN/LargeWorlds/blob/main/Docs/knowledge/shared-dependency-versions.md),
*Host versions*, which owns them; they are not copied here. What HogNoise does about each, from the owner's list
(2026-11-25), *"what's running currently in the HogShade BATS is the current focus and we aren't looking back"*:

| Host | Supported | CI point | Inside the host |
| --- | --- | --- | --- |
| Maya 2026 | Yes, the floor | `3.11 + numpy 1.26 (floor: Maya 2026, Houdini 21, Unreal 5.8)` | Not yet (BATS worker exists) |
| Houdini 21 | Yes, whatever is installed | The same point as Maya: its files say Python 3.11 and numpy 1.26.4 | Not yet (no BATS worker) |
| Unreal 5.8 | Yes, covered through HogHydra (*"it supports USD and MaterialX"*) | The same point, if its numpy (an Experimental plugin) is the path; HogHydra settles whether Unreal takes the Python import or the emitted shaders | Not yet |
| Blender 5.2 | Yes, the floor set now | `3.13 + numpy 2.3 (Blender 5.2)` | Not yet (BATS worker exists) |
| Marmoset Toolbag 4 | Not now: Python 3.9.4 and no numpy, read inside the host. The owner: *"If I have to update to marmoset toolbag 5 I will, not a current high priority to solve for"* | None | — |
| Substance | Not started; one significant version back from the latest, when it is | None | — |
| 3ds Max | No | None | — |

A host's import inside the host itself, through HogShade's BATS, is [a row of its own](../plan/board/2026-11-25-hognoise-imported-inside-each-dcc-host.md);
until it lands, a CI point stands for its host.

## Terms introduced

- **DCC host:** an application HogNoise is imported into, on its own Python and numpy: Maya, Houdini, Unreal, Blender.
  Not a **Host harness**, which runs an emitted shader.
