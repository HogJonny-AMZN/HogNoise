# Handoff: where HogNoise is right now

**Status:** Living. Rewritten whenever work is interrupted, a decision changes, the state moves, or the owner states a
preference worth carrying forward.

**Last updated:** 2026-10-31: day 0. The repository was made from `ai-first-template`; nothing is built.

A new session reads this, then [../plan/BOARD.md](../plan/BOARD.md) (gates first), then the newest file in
[../journal/](../journal/README.md). This file is project truth: where the project is, the gates, what the owner said that
holds. A person's session truth (their branch, what is mid-build, what their next session picks up) is their own
`people/<login>.md` beside it, which nobody else writes.

## Day 0 checklist

- [ ] Make the first commit: `git init -b main`, `git add -A`, then `git commit -s` as HogJonny-AMZN
      (no attribution line for an AI), and run `uv sync`.
- [ ] Have the conversation with HogJonny-AMZN: what is this project for, what does it need to do first? Lock the answer
      in a design under `Docs/design/` (the design chain: lock, spec, plan, test-first code). A design is a file with a
      `**Status:**` line that ends with a `## Terms introduced` section naming the glossary terms it adds, or `None`.
- [ ] Close gate G1 on the board by naming the first increment, and put it under Now: the board is one file per row
      under `Docs/plan/board/` (the README there says the lines), and `make board` renders the page.
- [ ] Replace this checklist with a snapshot of the real state, and keep it a snapshot: history belongs in the journal.
- [ ] Add the project's own rows to [../README.md](../README.md), and its terms to [../glossary.md](../glossary.md).

## In flight

Nothing yet.

## What the owner has said that still holds

Nothing yet. Record here what the owner says that is written nowhere else, so a new session does not lose it.

## Open, and waiting on a person

- G1 on the board: the first increment.
