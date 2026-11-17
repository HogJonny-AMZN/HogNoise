# Handoff: where HogNoise is right now

**Status:** Living. Rewritten whenever work is interrupted, a decision changes, the state moves, or the owner states a
preference worth carrying forward.

**Last updated:** 2026-11-17: stage 3's plan proposed (the emitted languages), its spec accepted 2026-11-15; the GPU port has landed
([PR #22](https://github.com/HogJonny-AMZN/HogNoise/pull/22), merged 2026-11-15); ai-first-template 0.10.2
([PR #23](https://github.com/HogJonny-AMZN/HogNoise/pull/23)) landed first. Before them, 0.9.4 and its workspace layout
([PR #18](https://github.com/HogJonny-AMZN/HogNoise/pull/18)) and 0.10.1
([PR #19](https://github.com/HogJonny-AMZN/HogNoise/pull/19)) landed; the GPU port's spec is Accepted
([PR #20](https://github.com/HogJonny-AMZN/HogNoise/pull/20)), and so is its plan
([PR #21](https://github.com/HogJonny-AMZN/HogNoise/pull/21)).
Published 2026-11-01 at
[https://github.com/HogJonny-AMZN/HogNoise](https://github.com/HogJonny-AMZN/HogNoise), on `ai-first-template` 0.10.2
(0.4.0 to 0.9.4 in [PR #18](https://github.com/HogJonny-AMZN/HogNoise/pull/18), then 0.10.1 and 0.10.2) with no
overrides
([ADR-001](../decisions/ADR-001-adopt-the-framework.md)). Gate G2, locking the
[north-star roadmap](../design/2026-11-01-north-star-roadmap.md), waits on the owner and blocks neither.

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
| **The GPU fast track** ([design](../design/2026-11-01-gpu-fast-track.md), Accepted 2026-11-01) | Stage 1 done 2026-11-02 ([the spike](../../Spikes/gpu_fast_track/README.md): go, drift within `3e-6 * max(1, abs(coordinate * frequency))`); stage 2, the port: [its spec](../superpowers/specs/2026-11-14-gpu-port.md) Accepted 2026-11-14 with its six decisions as recommended (a `wgpu` rung, one WGSL shader, a tolerance file per rendering, CI on software adapters); [the plan](../superpowers/plans/2026-11-14-gpu-port.md) Accepted 2026-11-14 with its seven decisions; **landed** 2026-11-15 in [PR #22](https://github.com/HogJonny-AMZN/HogNoise/pull/22): every feature on wgpu, all 368 hog cases within the measured tolerance on the RTX 5090, two WARP builds and llvmpipe; the owner's two decisions during the build (grids discrete; a derived correlation at most 0.999) are in its *Decisions*. Stage 3, the emitted languages: [its spec](../superpowers/specs/2026-11-15-emitted-languages.md) Accepted 2026-11-15 with its six decisions as recommended (HLSL, GLSL and SPIR-V by naga, naga-cli 29.0.x; Metal later, since naga's command line writes it with no usable bindings; the tools move to an app first); [the plan](../superpowers/plans/2026-11-17-emitted-languages.md) Proposed 2026-11-17 with five decisions: two pull requests (the move, then the emitter), naga-cli 29.0.2 (no 29.0.1 CLI exists; measured equivalent to 30.0.1 in all a host binds), `HOG_NOISE_NAGA`, a shared `tables.binding_table()`, a tested compile script | The owner, to accept the plan and its five decisions |
| The member's author email ([PR #18](https://github.com/HogJonny-AMZN/HogNoise/pull/18), merged) | The manifest names the address `project.json` already makes public, because the boundary check's `no-authors` requires an email | The owner, to keep or change it |
| The north-star roadmap (gate G2) | Proposed | The owner, to lock its three remaining decisions |
| PyPI release of `hog-noise` | Deferred indefinitely (2026-11-13): not until the core is complete and deployable in numpy, WGSL and at least HLSL | The owner's go, then; needs the owner's PyPI credentials |

## What the owner has said that still holds

- **"I don't want to f with LargeWorlds"**: HogNoise is a one-way copy; the source repository is not refactored for it.
- **The README is a field report, not a frontier claim**: "I wanted it all with no restraints", built with AI in days to
  weeks instead of weeks to months, used in LargeWorlds and SpriteJammer, "I'm not a noise researcher" (keep both, 2026-11-01).
  It claims only what the vectors prove.
- **What lies beyond the edge is not known yet**, and stays an open slot, not a roadmap.
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
  waits on the GPU fast track's stage 2 (WGSL) and stage 3 (HLSL, GLSL by naga), not on a date.
- **The outcome the work is for** (2026-11-13): "the outcome driven value stream is the most modern and every
  language version of fastnoise". A change earns its place by moving toward that: a more modern FastNoise, in more
  of its languages, each checked against the same vectors.
- No publishing, pushing, repository creation or PyPI registration without the owner's explicit go; the owner merges.

## Open, and waiting on a person

- **G2, the roadmap:** its three remaining decisions (see the board row). The GPU fast track does not wait on it.
- **PyPI:** deferred by the owner until the core deploys in numpy, WGSL and at least HLSL; nothing to ask until then.
