# Handoff: where HogNoise is right now

**Status:** Living. Rewritten whenever work is interrupted, a decision changes, the state moves, or the owner states a
preference worth carrying forward.

**Last updated:** 2026-11-01: the public history starts at one commit, and the repository adopted `ai-first-template` 0.4.0
with no overrides ([ADR-001](../decisions/ADR-001-adopt-the-framework.md)). Nothing has been pushed; there is no remote.

A new session reads this, then [../plan/BOARD.md](../plan/BOARD.md) (gates first), then the newest file in
[../journal/](../journal/README.md). This file is project truth: where the project is, the gates, what the owner said that
holds. A person's session truth (their branch, what is mid-build, what their next session picks up) is their own
`people/<login>.md` beside it, which nobody else writes.

## What is true now

- **HogNoise** is a Python port of the FastNoiseLite and FastNoiseSIMD algorithms (`src/hog_noise`), rendered three ways from
  one `NoiseParams` and compared against committed vectors from the originals. Its only runtime dependency is numpy.
  [README.md](../../README.md) is the public story; [PROVENANCE.md](../../PROVENANCE.md) is where it came from and what each
  stage changed.
- **Stages done:** 1, the filtered snapshot; 2, standing alone; 3, publish-ready (LICENSE, NOTICE, README) - all 2026-10-11.
  On 2026-11-01 the public history was started fresh at one commit (branch `public/main`); the filtered history behind it
  stays on the private local branches `main`, `stage2/stand-alone` and `stage3/publish-ready` and is never pushed.
- **The template adoption** is on branch `adopt/template-0.4.0`, on top of `public/main`.

## In flight

| Item | State | Waiting on |
| --- | --- | --- |
| The template adoption, branch `adopt/template-0.4.0` | Adopted untouched, then the gate made green | The owner's read; there is no pull request to open until a remote exists |
| Publishing, stage 4 (gate G1 on the board) | Not started | The owner's decisions in G1 |

## What the owner has said that still holds

- **"I don't want to f with LargeWorlds"**: HogNoise is a one-way copy; the source repository is not refactored for it.
- **The README is a field report, not a frontier claim**: "I wanted it all with no restraints", built with AI in days to
  weeks instead of weeks to months, used in LargeWorlds and SpriteJammer, "I'm not a noise researcher" (keep both, 2026-11-01).
  It claims only what the vectors prove.
- **What lies beyond the edge is not known yet**, and stays an open slot, not a roadmap.
- **Hog branding** (2026-10-15): repository `HogNoise`, distribution `hog-noise`, import `hog_noise`.
- **Fresh public history, `src/` layout, the template adopted before publishing** (2026-11-01).
- No publishing, pushing, repository creation or PyPI registration without the owner's explicit go; the owner merges.

## Open, and waiting on a person

- **G1, publishing:** the copyright line in `LICENSE` (now "HogJonny"); the author name on the public commits (now
  `HogJonny-AMZN`); which GitHub account or organisation hosts the repository; registering `hog-noise` on PyPI.
