# AGENTS.md

Tool-neutral entry point for any coding agent in HogNoise. Short on purpose: the knowledge lives in small topic files,
and this is the map. It carries no status, counts or phase; the state is in the handoff and the board.

## Read first

1. [Docs/handoffs/CURRENT.md](Docs/handoffs/CURRENT.md): where the project is (project truth), then your own
   `Docs/handoffs/people/<login>.md` if you have one (session truth: your branch, what you were mid-way through). Then
   [Docs/plan/BOARD.md](Docs/plan/BOARD.md), the tracker (rendered by `make board` from the row files under
   `Docs/plan/board/`, one file per row; read the rows when the page is not there): the gates a person on the roster closes
   (nothing downstream of an open one may be committed to), what is in flight, what is blocked on whom, and the Icebox
   where every idea said out loud lands with a cost.
2. [Docs/README.md](Docs/README.md): the map from a task to the document that governs it. Project-specific pointers go
   there, so this file stays the same in every repository made from the template.
3. [Docs/glossary.md](Docs/glossary.md): the vocabulary. Use these exact words, no synonyms.
4. [Docs/decisions/README.md](Docs/decisions/README.md): the decisions made, as ADRs, before a structural change.
5. The newest file in [Docs/journal/](Docs/journal/README.md) when resuming after a break: the narrative, and what
   changed in what the project believes.
6. The ledgers, before starting work and whenever something goes wrong in the process:
   [Docs/standards/failure-modes.md](Docs/standards/failure-modes.md) (the framework's, as triggers) and
   [Docs/standards/failure-modes-project.md](Docs/standards/failure-modes-project.md) (this project's). Retrieval is the
   enforcement: a ledger nobody loads is a diary.
7. The standards, each with its extension (`X-project.md` beside it) when there is one, before you build or finish anything:
   [Docs/standards/workflow.md](Docs/standards/workflow.md) (the stages from conversation to merge, and which record owns
   what), [Docs/standards/definition-of-done.md](Docs/standards/definition-of-done.md) (what ends an increment, and the
   autonomy protocol), [Docs/standards/python.md](Docs/standards/python.md) and
   [Docs/standards/testing.md](Docs/standards/testing.md) before writing code or tests.

## Non-negotiable rules

- **Claims follow evidence.** Say done, passing or fixed only after the check ran, and say what was not covered.
- **A mentioned feature is not a work order.** It goes on the board's Icebox with a cost, a reason and a verdict, and a link
  to where it was said, in the same session it was said. It is built when a person on the roster says so, when it blocks work in flight, or when it is smaller than the
  conversation about it. Ask "pull it forward now?" in those words before building an Icebox row.
- **The design chain.** Converse and lock a design, then a spec, then a plan, then test-first code; for anything a person
  will touch, a UX mock pass comes after the lock and before the spec. A board yes is not a lock.
- **Two kinds of door.** A two-way door (cheap to reverse) is decided, recorded in the pull request's *Decisions* table,
  and continued past; more than eight in one pull request means split it. A one-way door (expensive to reverse,
  outward-facing, or a person's call) is asked of the person you work for. Anyone on the roster merges, their own work
  included, and the merge is the review; an agent never merges and never decides a one-way door.
- **Use the glossary vocabulary.** A new concept gets its word in the glossary first, in the same change and before the
  code that uses it. A concept with two names is retrieved by neither.
- **Journal continuously**, not retrospectively, under `Docs/journal/`: at least one file per calendar day, one per
  session.
- **Keep the handoff a snapshot, not a log.** Update it when a decision changes, work is interrupted, or a person on the
  roster states a preference worth carrying forward; history belongs in the journal and in git.
- **Commits and pull requests carry a person's identity, never an agent's**: the owner, HogJonny-AMZN <hogjonny-github@protonmail.com>,
  or a person on the roster signing as themselves. No attribution line for an AI. The default branch is `main`.

## Skills and tools

A procedure done twice becomes a plain-markdown skill under `.agents/skills/<name>/SKILL.md`. Follow a matching skill
before improvising. Two ship with the template: [local-review](.agents/skills/local-review/SKILL.md) (a deliberate review by a
reviewer who has not seen the author's reasoning, against the standards and a rubric) and
[review-and-pr](.agents/skills/review-and-pr/SKILL.md) (opening a pull request, and assessing an automated review on one).
The pull request template is `.github/pull_request_template.md`.
