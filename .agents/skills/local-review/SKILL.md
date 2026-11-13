---
name: local-review
description: Review code with fresh eyes, in a context that has not seen the author's reasoning, against this repository's own standards and a ten-metric rubric with a 7/10 baseline. Use when asked to review my changes before a merge or pull request, to review one module in full, or to audit the project's design. Takes an optional mode (diff, module or project) and a target.
---

# Local standards reviewer

**This project's additions** go in `project.md` in this skill's folder, when it has any: an extension adds rules and
never weakens these. To relax or contradict a rule here, override this file in `framework.toml` with a reason that names
the rule.

A deliberate review by a reviewer who has **not seen the author's reasoning**. That is a role, not a tool: it can be a
subagent, a second session, or another model. What matters is that the reviewer starts from the code and the standards and
not from the author's account of them.

It reviews against two inputs:

1. **This repository's standards**, discovered at run time from the files in step 2 (never pasted into this skill, so they
   cannot go stale here).
2. **The rubric** in [`references/rubric.md`](references/rubric.md): ten metrics, 7/10 baseline.

When it runs is process, not preference: `Docs/standards/definition-of-done.md`, "When the deliberate review runs". Its
output goes in the pull request's *Review* section.

## 1. Parse the invocation

`local-review [mode] [target]`

- No arguments, or the first word is not a known mode: **`diff`**.
- **`diff`**: the branch against the default branch, plus working changes. "Review my current work."
- **`module [path]`**: one module in full, with its dependency neighbourhood. If `path` is omitted, use the file the user
  named; if there is none, ask for a target rather than guessing.
- **`project`**: a holistic design and architecture pass across the repository, emphasising boundaries over line-level nits.

## 2. Discover the repository's standards

Load what exists, in this order, and stop once there is enough signal:

1. `AGENTS.md` (the non-negotiable rules)
2. The standards in `Docs/standards/`: the definition of done, the workflow, and the language and testing standards the
   project has
3. `Docs/glossary.md` (the vocabulary) and the ledgers, `failure-modes.md` and `failure-modes-project.md`
4. The linter and formatter configuration, the CI workflow, `framework.toml`
5. The decisions the change might contradict: `Docs/decisions/`

The rubric is constant; the concrete standards come from these files. Where they are silent, apply idiomatic defaults for the
language.

## 3. Gather scope (per mode)

**diff**

- Default branch: the one `AGENTS.md` names; if it does not, `git symbolic-ref refs/remotes/origin/HEAD`, and failing that
  ask the forge (on GitHub, `gh repo view --json defaultBranchRef`).
- `git diff <default>...HEAD`, plus `git diff` and `git diff --cached`.
- Read the changed hunks and the functions they touch, with enough surrounding code to judge them.
- Run the project's gate (`make check`, or `uv run python tools/check.py`) and report its verdict, and its hygiene check
  if it is a separate command. **If the project has no gate yet, say so in the report and do not claim a pass.**

**module [path]**: read the target in full and build its neighbourhood (what it imports, what imports it); read enough of each
neighbour to judge fit.

**project**: map the boundaries (entry points, source directories, module boundaries), sample representative modules across
them, and emphasise architecture, design and maintainability at the system level.

## 4. Start the review

Start **one** reviewer (a subagent, or hand the brief to a second session or another model) and wait for its result before
continuing. Its brief contains:

- The rubric **and** output template from [`references/rubric.md`](references/rubric.md).
- The discovered standards, or their relevant sections, quoted.
- The gathered scope for the mode, including the gate and hygiene results.

**Leave out your own summary of the change and your reasoning for it**: the reviewer judges the code, and a curated account
contaminates exactly the fresh eyes this review exists for.

Instruct it to score every applicable metric 1 to 10, mark inapplicable ones `n/a`, justify every sub-7 score with a
`file:line` anchor and a concrete fix, not inflate scores to be agreeable, **run the code where it can** (a probe beats a
reading), not modify tracked files, and return the filled output template as its final result. **Fill the template's
*Error paths* table** for every function the change has that reads the filesystem, runs a subprocess, calls the network
or parses text it did not write: each case of `testing.md`'s *Error paths* checklist, and the test that covers it or
"missing". A checklist the reviewer is only told to consult is one a reviewer skips (framework 18, 42 and 43).

## 5. Relay, then act on the findings

Print the scored report. The author decides each finding: **fix it, or decline it with a reason**, and for a `diff` review
before a pull request pastes the table into the pull request's *Review* section with each finding marked. When someone else
asked for the review, offer the fixes and apply them only on their word. A defect deferred rather than fixed becomes a tracker
issue named under *Not covered*.
