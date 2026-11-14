<!--
Title: what is now true -- e.g. "Rate limiter: requests over the limit are refused with a retry hint (plan task 3)".
Branch: type/<slug> (feat, fix, docs, chore). A person on the roster merges and deletes the branch.
Delete any section that has nothing in it.
-->

**Board:** <!-- the row this lands, closes or adds, by its id: [`<row id>`](Docs/plan/board/<row id>.md); "none (reason)" is an answer, an omission is not -->

## What changed

<!-- What is now true that was not. Lead with the result, not the process. Name the plan task. -->

## Verified

<!--
What ran, where, and the artifact it left: `make check` and its verdict, the tests, the pictures or logs. A claim
comes after the evidence exists. Numbers without a command are estimates; quote a number with its commit.
-->

## Measured

<!--
Optional: only if this pull request claims a measurement. Before and after, taken back to back on the same machine, with the
command that produced each. A comparison against an old capture is not a comparison.
-->

## Decisions

<!--
Every two-way-door decision made on this branch: the autonomy protocol's record (Docs/standards/definition-of-done.md).
The merge is the review, by whoever merges, so a decision not listed here was not reviewed. MORE THAN 8 means the pull request is
too big: split it. One-way doors do not belong here; they stop work and get asked. Quotes, with the login, where a person decided.
-->

| Decision | Alternative | Why | Reverse cost |
| --- | --- | --- | --- |
| | | | |

## Wrong along the way

<!-- Beliefs, records or measurements that did not survive. This is the research record, not an apology. -->

## Review

<!--
Significant increments only (Docs/standards/definition-of-done.md, "When the deliberate review runs"). Paste the score
table from the local-review skill, then each finding as fixed, or declined with the reason. The automated review runs on
every push; this is the deliberate one.
-->

## Not covered

<!--
What this does not verify, test or change, said plainly. An open gate is stated, never implied. A defect found here and
not fixed here is a tracker issue opened before this merges (or, for a review that posts after the merge, before the
session ends): name its number.
-->

---

- [ ] `make check` passes locally, **run unpiped** and its verdict read
- [ ] CI green on every leg, read with the forge's checks command, not assumed
- [ ] New terms: every word this coins (a module, type, enum value, level, kind, CLI verb, document type) has its glossary
      row, and each new design, spec or plan ends with a `## Terms introduced` section (or says None)
- [ ] Docs match reality, as the definition of done lists them: the board, the plan task, the spec, the journal, the handoff,
      the ledger if the process failed
- [ ] Review: the deliberate review run and its findings answered above, **or** this increment is not significant under the
      rule, and *Review* says why
- [ ] Error paths: code here that reads the filesystem, runs a subprocess, calls the network or parses text it did
      not write has a test for each case of `Docs/standards/testing.md`'s *Error paths* that applies, or *Verified*
      names the case and why not (the review's *Error paths* table, where it ran)
- [ ] Every two-way-door decision is in *Decisions*, and there are no more than 8
