# Handoff: where HogNoise is right now

**Status:** Living. Rewritten whenever work is interrupted, a decision changes, the state moves, or the owner states a
preference worth carrying forward.

**Last updated:** 2026-11-28: **the SPIR-V on lavapipe landed** in [PR #65](https://github.com/HogJonny-AMZN/HogNoise/pull/65)
(`bf18d0a`, 00:05 UTC), so **all three of the CI proof's pull requests have landed**. [Its plan](../superpowers/plans/2026-11-27-the-emitted-spirv-on-lavapipe.md)
was Accepted by the owner's merge of [PR #64](https://github.com/HogJonny-AMZN/HogNoise/pull/64) on the 27th. In CI's
new `spirv-vulkan` job, `noise.spv`, given as bytes to Mesa's lavapipe, passes every hog case within `wgpu.json`
unmodified: the first time a driver consumed the shipped SPIR-V. Review found the shared request check, on main since
(b), passing a dispatch that did not cover its points; it now requires the README's. One trial `make check` in six hung,
cause unknown. **The owner: "PyPI isn't a priority yet"** (2026-11-27); what is next is the owner's pick. Before it, 2026-11-25:
**the buffer limit is refused in the caller's terms**
([PR #61](https://github.com/HogJonny-AMZN/HogNoise/pull/61), `f553140`), built from [its plan](../superpowers/plans/2026-11-25-a-call-past-the-buffer-limit.md),
Accepted by the owner's merge of [PR #60](https://github.com/HogJonny-AMZN/HogNoise/pull/60) (`d7abe0c`). A wgpu-rung
call with more points than the device binds in one buffer (2,147,483,644 bytes on every adapter measured) is refused
before any upload, with a `ValueError` naming the method, the most points it takes and the adapter; before, wgpu
refused it in its own terms, after the axes were uploaded. **That was the last of the four the owner set before PyPI;
the release waits on the owner's go and credentials.** Ledger P-30 records the plan's "before any upload" claim, which
its first trial could not test and Copilot's review caught. Before it, the same day: **the HLSL runs**
([PR #59](https://github.com/HogJonny-AMZN/HogNoise/pull/59), `3a83792`). `noise.hlsl`, compiled by FXC `cs_5_0` and DXC
`cs_6_0`, runs on WARP through D3D11 and D3D12 in a C++ harness written from the shaders README, and passes every hog
case within `wgpu.json` unmodified, locally and in CI's new `hlsl` job. That meets the PyPI condition's HLSL; the
release is still the owner's go. Next was [the buffer limit](../plan/board/2026-11-21-a-call-past-the-devices-buffer-limit.md),
then PyPI on the owner's go; [the SPIR-V on lavapipe](../plan/board/2026-11-23-the-emitted-spirv-runs-on-lavapipe.md)
has its plan to write. Before it, the same day: **the fresh-sample bounds landed** ([PR #58](https://github.com/HogJonny-AMZN/HogNoise/pull/58), `8e77673`). Tolerance
format 2: a continuous rule's tight bound, from the vectors, is held for the fraction measured on 65,536 fresh points a
case (at most 0.9999) under a ceiling of 1e-2 a unit; the far probe passes 246 of 246 inside the range on three
adapters; ledger P-28. Its plan merged in [PR #56](https://github.com/HogJonny-AMZN/HogNoise/pull/56) (`620750a`), form C2 on the owner's "I'll take your best
recommendation". And **the DCC hosts** ([the matrix](../standards/compatibility-matrix-project.md),
[PR #57](https://github.com/HogJonny-AMZN/HogNoise/pull/57), `9f982ac`): HogNoise must import in every supported DCC host on that host's own Python and numpy. The
floors stay Maya 2026's (Python 3.11, numpy 1.26), which Houdini 21 and Unreal 5.8 share; Blender 5.2 (3.13, numpy
2.3) has its own CI leg; Marmoset Toolbag 4 (Python 3.9, no numpy) is out until Toolbag 5. Dependabot moves the lock
only, and `test_dcc_host_floors.py` refuses a raised floor or a cap. The import inside each host, through HogShade's
BATS, is [a row](../plan/board/2026-11-25-hognoise-imported-inside-each-dcc-host.md).
Before it, 2026-11-24:
**LargeWorlds takes HogNoise from a pinned commit**
([LargeWorlds PR #134](https://github.com/HogJonny-AMZN/LargeWorlds/pull/134), its ADR-014), with no PyPI release. Its `hognoise`
extra is `b008c5f`, its agreement test holds the 78 shared presets bit for bit, and a weekly canary runs that test
against this `main`. The owner made keeping the two in step the agent's job (*What the owner has said that still holds*). Before it, the same day: [the warp rules](../plan/board/2026-11-21-warp-output-rules-coordinate-scaled.md) landed in [PR #53](https://github.com/HogJonny-AMZN/HogNoise/pull/53) (`7ad23ff`), as option A on the owner's "go": `measure_gpu.derive` takes a warp rule from its coordinate-scaled measurement, as it does a noise rule, and the nine warp rules were derived again from the committed `5340a3f` records (absolute 5e-4 to 5e-3 became coordinate-scaled 5e-5 to 2e-4). Run again with them, [the far-coordinate probe](../../Spikes/far_coordinates/README.md) passes every warp output past 32,768 units on the 5090's Vulkan and D3D12 and on WARP, where none passed before; inside that, a few points in 65,536 remain past, the rare tail [the fresh-sample bounds](../plan/board/2026-11-21-gpu-bounds-from-a-large-fresh-sample.md) are next for, then the HLSL build. Before it, 2026-11-23, late: [the HLSL pull request's plan](../superpowers/plans/2026-11-23-the-emitted-hlsl-on-warp.md) merged ([PR #51](https://github.com/HogJonny-AMZN/HogNoise/pull/51)) and Accepted with its six decisions (B1 to B6) as recommended ("ok accepted"). It was trial-run before it was proposed: every hog case passed on D3D11 and D3D12 on WARP, and the spec's open risk (D3D11 rejecting naga's HLSL at pipeline creation) did not happen. It was written out of the agreed order, because the agent said the HLSL was next, and the owner kept the order: **[the warp rules](../plan/board/2026-11-21-warp-output-rules-coordinate-scaled.md) are next**, then [the fresh-sample bounds](../plan/board/2026-11-21-gpu-bounds-from-a-large-fresh-sample.md), then the HLSL build. Ledger P-24 to P-26 record what that session's checks missed. Before it, the CI proof's first pull request merged, [PR #49](https://github.com/HogJonny-AMZN/HogNoise/pull/49) (`adf4f30`), after Copilot's four findings were fixed (the `glsl` job's wgpu pinned to OpenGL, a buffer-update barrier before the GL read among them): `noise.spv` and the GLSL run in hosts written from the shaders README and pass every hog case within the wgpu tolerance on WARP, llvmpipe and Metal; bit for bit with the rung except on Metal (3.58e-7). Before that, [the CI proof's plan](../superpowers/plans/2026-11-23-emitted-shaders-ci-proof.md) Accepted by the owner with its five decisions as recommended ("I accept your recommendations") and being built, for its first pull request alone (the shared host harness, SPIR-V through naga, GLSL); the HLSL and Vulkan pull requests are rows of their own on *Next*, so the buffer-limit refusal and the engine trials wait on exactly the ones they need. Earlier that day, on the owner's "take them", recorded in [PR #45](https://github.com/HogJonny-AMZN/HogNoise/pull/45): gate G2 closed and [the roadmap](../design/2026-11-01-north-star-roadmap.md) Accepted; the warm-start flake's first step landed (the child's stderr kept); the warp rules, the fresh-sample bounds and the buffer-limit refusal queued on *Next*; PyPI after the CI proof's HLSL pull request and those three. The order: the warp rules, the CI proof's plan and first pull request, the fresh-sample bounds, the HLSL pull request, the buffer limit, then PyPI on the owner's go.
Everything before 2026-11-23 (the CI proof's spec, the MaterialX survey, the macOS leg, the far probe, the account, the
template updates, stage 3) is in [../journal/](../journal/README.md) and `git log`.
Published 2026-11-01 at
[https://github.com/HogJonny-AMZN/HogNoise](https://github.com/HogJonny-AMZN/HogNoise), on `ai-first-template` 0.11.5
(0.4.0 to 0.9.4 in [PR #18](https://github.com/HogJonny-AMZN/HogNoise/pull/18), then 0.10.1, 0.10.2, 0.11.0, 0.11.1 and
0.11.5) with no
overrides
([ADR-001](../decisions/ADR-001-adopt-the-framework.md)). Gate G2 closed 2026-11-23:
the [north-star roadmap](../design/2026-11-01-north-star-roadmap.md) is Accepted.

A new session reads this, then [../plan/BOARD.md](../plan/BOARD.md) (gates first), then the newest file in
[../journal/](../journal/README.md). This file is project truth: where the project is, the gates, what the owner said that
holds. A person's session truth (their branch, what is mid-build, what their next session picks up) is their own
`people/<login>.md` beside it, which nobody else writes.

## What is true now

- **HogNoise** is a Python port of the FastNoiseLite and FastNoiseSIMD algorithms (the workspace member [`packages/python/hog-noise/`](../../packages/python/hog-noise/README.md),
  import `hog_noise`), rendered three ways from
  one `NoiseParams` and compared against committed vectors from the originals. Its only runtime dependency is numpy.
  [README.md](../../README.md) is the public story; [PROVENANCE.md](../../PROVENANCE.md) is where it came from and what each
  stage changed.
- **Stages done:** 1, the filtered snapshot; 2, standing alone; 3, publish-ready (LICENSE, NOTICE, README) - all 2026-10-11.
  On 2026-11-01 the public history was started fresh at one commit (branch `public/main`); the filtered history behind it
  stays on the private local branches `main`, `stage2/stand-alone` and `stage3/publish-ready` and is never pushed.
- **Published** 2026-11-01: `main` on GitHub is the fresh commit, the adoption and the follow-ups. The private history
  branches were never pushed and never will be.

## In flight

| Item | State | Waiting on |
| --- | --- | --- |
| **The GPU fast track** ([design](../design/2026-11-01-gpu-fast-track.md), Accepted 2026-11-01) | Stage 1 done 2026-11-02 ([the spike](../../Spikes/gpu_fast_track/README.md): go, drift within `3e-6 * max(1, abs(coordinate * frequency))`); stage 2, the port: [its spec](../superpowers/specs/2026-11-14-gpu-port.md) Accepted 2026-11-14 with its six decisions as recommended (a `wgpu` rung, one WGSL shader, a tolerance file per rendering, CI on software adapters); [the plan](../superpowers/plans/2026-11-14-gpu-port.md) Accepted 2026-11-14 with its seven decisions; **landed** 2026-11-15 in [PR #22](https://github.com/HogJonny-AMZN/HogNoise/pull/22): every feature on wgpu, all 368 hog cases within the measured tolerance on the RTX 5090, two WARP builds and llvmpipe; the owner's two decisions during the build (grids discrete; a derived correlation at most 0.999) are in its *Decisions*. Stage 3, the emitted languages: [its spec](../superpowers/specs/2026-11-15-emitted-languages.md) Accepted 2026-11-15 with its six decisions as recommended (HLSL, GLSL and SPIR-V by naga, naga-cli 29.0.x; Metal later, since naga's command line writes it with no usable bindings; the tools move to an app first); [the plan](../superpowers/plans/2026-11-17-emitted-languages.md) Accepted 2026-11-17 with its five decisions as recommended: two pull requests (the move, then the emitter), naga-cli 29.0.2 (no 29.0.1 CLI exists; measured equivalent to 30.0.1 in all a host binds), `HOG_NOISE_NAGA`, a shared `tables.binding_table()`, a tested compile script. The move landed in [PR #33](https://github.com/HogJonny-AMZN/HogNoise/pull/33); the emitter in [PR #34](https://github.com/HogJonny-AMZN/HogNoise/pull/34), merged 2026-11-19 as `7dfec85`: HLSL, GLSL 4.30 and SPIR-V in `hog_noise/shaders/`, compiled by FXC, DXC, glslang and spirv-val in CI and regenerated on every push; no host has run them against the vectors yet ([the CI proof](../plan/board/2026-11-18-emitted-shaders-run-against-the-vectors.md) and [the engine trials](../plan/board/2026-11-18-engine-host-trials.md) went on the Icebox 2026-11-18; the CI proof is on Now since 2026-11-22, and only the engine trials remain on the Icebox), and Metal is later. [The hardening](../plan/board/2026-11-18-harden-the-gpu-fast-track.md) was pulled onto *Now* 2026-11-20: [its account](../design/2026-11-20-gpu-fast-track-account.md) finds the claims hold within the measured range (and, new that day, on the 5090's D3D12 and OpenGL back ends too), with seven gaps and a proposed order | The owner: a verdict on each of the account's other gaps. Gap 6, the 5090's D3D12 and OpenGL records, was taken on the owner's "proceed" (2026-11-21); gap 1's [far-coordinate probe](../plan/board/2026-11-21-far-coordinate-probe-for-every-feature.md) followed (2026-11-21), then [gap 3's macOS leg](../plan/board/2026-11-21-the-wgpu-rung-on-a-macos-runner.md) followed (2026-11-21): Metal on the runner's virtual GPU, its record taken on the owner's choice. Gap 4, [the CI proof](../plan/board/2026-11-18-emitted-shaders-run-against-the-vectors.md) (3 to 5 d, before PyPI), was pulled onto *Now* 2026-11-22 on the owner's "your best recommendations": [its spec](../superpowers/specs/2026-11-22-emitted-shaders-ci-proof.md) Accepted 2026-11-22 with its five decisions as recommended, [its plan](../superpowers/plans/2026-11-23-emitted-shaders-ci-proof.md) Accepted 2026-11-23; the first landed in [PR #49](https://github.com/HogJonny-AMZN/HogNoise/pull/49) (SPIR-V through wgpu on WARP, llvmpipe and Metal; GLSL in moderngl on llvmpipe; every hog case within the wgpu tolerance), the second, [the HLSL](../plan/board/2026-11-23-the-emitted-hlsl-runs-on-warp.md) on WARP through D3D11 and D3D12, in [PR #59](https://github.com/HogJonny-AMZN/HogNoise/pull/59); the third, [Vulkan](../plan/board/2026-11-23-the-emitted-spirv-runs-on-lavapipe.md), landed 2026-11-28 in [PR #65](https://github.com/HogJonny-AMZN/HogNoise/pull/65) (`bf18d0a`) from [its plan](../superpowers/plans/2026-11-27-the-emitted-spirv-on-lavapipe.md), Accepted 2026-11-27; the two derivation changes were taken 2026-11-23 and are queued on *Next* |
| [Noise in MaterialX](../plan/board/2026-11-22-noise-in-materialx.md) (2026-11-22) | [The survey](../design/2026-11-22-noise-in-materialx.md), Accepted 2026-11-22, for the two goals (HogNoise presented to MaterialX; MaterialX's own noise respected through the look-dev chain): option C, MaterialX as a third original library first (3 to 5 d, after the CI proof's first pull request; oracle vectors from its GLSL and from its generated OSL through `testshade`), then a `hognoise:` MaterialX library, as source or as standard-node graphs with MaterialX's hash | The CI proof's first pull request; a row on HogShade's board (a HogShade pull request) |
| The member's author email ([PR #18](https://github.com/HogJonny-AMZN/HogNoise/pull/18), merged) | The manifest names the address `project.json` already makes public, because the boundary check's `no-authors` requires an email | The owner, to keep or change it |
| The north-star roadmap (gate G2) | Accepted 2026-11-23, G2 closed, its decisions as recommended | Nothing |
| PyPI release of `hog-noise` | Deferred indefinitely (2026-11-13): not until the core is complete and deployable in numpy, WGSL and at least HLSL. The HLSL condition is met: it runs against the vectors on WARP through D3D11 and D3D12 ([PR #59](https://github.com/HogJonny-AMZN/HogNoise/pull/59)); the buffer-limit refusal, the last of the four set on 2026-11-23, landed in [PR #61](https://github.com/HogJonny-AMZN/HogNoise/pull/61). Not a priority yet (2026-11-27) | The owner's go and PyPI credentials |

## What the owner has said that still holds

- **A contact who works on MaterialX** (2026-11-22): the owner may send them findings later. Sending anything is the
  owner's call; [the survey](../design/2026-11-22-noise-in-materialx.md) says what option A would give them.
- **"I don't want to f with LargeWorlds"**: HogNoise is a one-way copy; the source repository is not refactored for it.
- **The README is a field report, not a frontier claim**: "I wanted it all with no restraints", built with AI in days to
  weeks instead of weeks to months, used in LargeWorlds and SpriteJammer, "I'm not a noise researcher" (keep both, 2026-11-01).
  It claims only what the vectors prove.
- **What lies beyond the edge is not known yet**, and stays an open slot, not a roadmap.
- **HogNoise imports in every supported DCC host, on that host's Python and numpy** (2026-11-25): *"we will need to be
  able to have a HogNoise that is importable to the DCC packages that we are going to support, their versions of
  Python. and their versions of NumPy, etc"*. It supports a range, not the shared table's lock: *"HogNoise is special
  it's the type of project and packages that supports many languages and should probably support multiple python
  versions"* (2026-11-24, relayed by HogHydra). Raising the numpy floor to 2.x was tried once and *"wasn't the right
  direction to head in"*. The hosts: *"maya 2026 is the floor, Blender we can set the floor now, Houdini whatever I have
  installed, unreal 5.8, max I really don't care about, substance tools haven't started yet but I would generally try to
  support one significant version back from whatever the latest is ... what's running currently in the HogShade BATS is
  the current focus and we aren't looking back"*; Unreal through HogHydra (*"it supports USD and MaterialX"*); Toolbag:
  *"If I have to update to marmoset toolbag 5 I will, not a current high priority to solve for"*.
  [The DCC hosts](../standards/compatibility-matrix-project.md) hold the rule.
- **Hog branding** (2026-10-15): repository `HogNoise`, distribution `hog-noise`, import `hog_noise`.
- **Fresh public history, `src/` layout, the template adopted before publishing** (2026-11-01). The layout is
  now the template's (2026-11-13, "yes we need to adapt to the specified layout"): the library is the member
  `packages/python/hog-noise/`, taken with ai-first-template 0.9.4.
- **The GPU fast track first** (2026-11-01): today's noise on wgpu in WGSL, chosen only when asked for, tolerance measured per
  feature; HLSL, GLSL and Metal generated by naga as the stretch.
- **The conformance harness before the GPU port** (2026-11-02, "do it"), so the port is checked the way any port is.
  Its design is locked as written (2026-11-11, "lock it"): both reference sets, the vectors in a top-level `vectors/` as raw
  float32 plus one manifest and nothing else, parameters in HogNoise's names, `sample` (and an optional `warp`) as the
  entry points, a per-point bound, and each case compared by points, shape or advisory. Its spec is accepted
  (2026-11-12, "accept").
- **The GPU port's spec is accepted** (2026-11-14, "first assess the copilot review, otherwise agreed and you can
  proceed"): its six decisions as recommended, a tolerance file per rendering with one rule per feature and output, the
  discrete rule for flips, a 2x margin to a 1-2-5 step, 48 hog-only cases (46 FastNoiseSIMD in 2D, 2 grids), two software-adapter CI legs with `dev`
  excluding `gpu`, and a 32-octave cap on the GPU rung reported as *unsupported*.
- **Two rules decided during the GPU port's build**: grid features are judged by a discrete rule (2026-11-14,
  "Discrete rule": lattice points tie, so a few jump), and a derived correlation is never above 0.999 (2026-11-15,
  "Cap at 0.999": `np.corrcoef` of identical arrays is not always 1.0). Both are in the plan's decisions table.
- **A template update records its machine** (2026-11-15, through the template session): the machine, the OS,
  `git --version`, `uv --version` and the from and to versions go in the update's pull request, so a home-machine
  run can be compared with the work-machine migration test the template's `--update` waits on.
- **PyPI waits until the core is complete** (2026-11-13): "PyPi is indefinitely delayed until I want to go public";
  "I would probably go public when everything is complete and I can deploy the core including Numpy, WGSL and at
  least HLSL, maybe GLSL as well". The repository is already public; this is the package release. So the release
  waits on the GPU fast track's stage 2 (WGSL) and stage 3 (HLSL, GLSL by naga), not on a date. On 2026-11-24: "I don't
  know exactly if/when I want to do a PyPI public release", so no consumer may need one. On 2026-11-27, with the
  four conditions of 2026-11-23 met: "PyPI isn't a priority yet". Do not offer the release as the next step.
- **The agent keeps HogNoise and LargeWorlds in step** (2026-11-24): "it's now your job to help collab, coordinate and
  keep in sync so LargeWorlds doesn't become too stale (and we can have a CI/CD path ongoing between projects)".
  LargeWorlds pins a commit of this `main` through uv's git source at `packages/python/hog-noise`, so moving that folder
  breaks LargeWorlds' lock. A change to a preset or a numpy-rung result fails LargeWorlds' canary within a week; move
  LargeWorlds' pin in the same session that lands such a change. When a HogNoise change lands, say in LargeWorlds' handoff
  what it means there.
- **The outcome the work is for** (2026-11-13): "the outcome driven value stream is the most modern and every
  language version of fastnoise". A change earns its place by moving toward that: a more modern FastNoise, in more
  of its languages, each checked against the same vectors.
- No publishing, pushing, repository creation or PyPI registration without the owner's explicit go; the owner merges.

## Open, and waiting on a person

- **PyPI:** deferred by the owner until the core deploys in numpy, WGSL and at least HLSL. Since
  [PR #34](https://github.com/HogJonny-AMZN/HogNoise/pull/34) merged (2026-11-19), the HLSL ships and compiles; whether
  that is "deployable" before a host has run it against the vectors is the owner's call, and the release waits on their
  go. [The account](../design/2026-11-20-gpu-fast-track-account.md) recommends the CI proof (its gap 4) first. On the owner's "take them" (2026-11-23): after the CI proof's HLSL pull request, the warp rules, the fresh-sample bounds and the buffer-limit refusal; then the owner's go and credentials. All four have landed: [PR #59](https://github.com/HogJonny-AMZN/HogNoise/pull/59), [PR #53](https://github.com/HogJonny-AMZN/HogNoise/pull/53), [PR #58](https://github.com/HogJonny-AMZN/HogNoise/pull/58) and [PR #61](https://github.com/HogJonny-AMZN/HogNoise/pull/61). On 2026-11-27 the owner said "PyPI isn't a priority yet".
- **The account's gaps:** all four of its Icebox rows have been taken. Gaps 6, 1 and 3 went to *Now* on 2026-11-21, and gap 7
  went to *Next* on 2026-11-23. Gap 2 needs hardware the project does not have, and gaps 4 and 5 already had rows
  ([the account](../design/2026-11-20-gpu-fast-track-account.md), *The gaps*).
- **Two changes to how the GPU bounds are derived**, from the far-coordinate probe, each changing the tolerance file, both taken on the owner's "take them" (2026-11-23):
  [the warp outputs coordinate-scaled](../plan/board/2026-11-21-warp-output-rules-coordinate-scaled.md) (0.5 d), landed
  2026-11-24 in [PR #53](https://github.com/HogJonny-AMZN/HogNoise/pull/53), and
  [bounds from a large fresh sample](../plan/board/2026-11-21-gpu-bounds-from-a-large-fresh-sample.md) (1 to 2 d), next on *Next*.
  (`cubic_none`'s looser 5e-7 was accepted by merging [PR #40](https://github.com/HogJonny-AMZN/HogNoise/pull/40).)
