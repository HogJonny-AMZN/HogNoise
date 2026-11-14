# Workflow: from conversation to merge

**Status:** Living. Managed by the template: a repository's copy must match, so do not edit it here; propose a change to the
template.
**Read with:** [definition-of-done.md](definition-of-done.md) · [failure-modes.md](failure-modes.md) ·
[../README.md](../README.md) · [../journal/README.md](../journal/README.md)

**This project's additions** go in `workflow-project.md` beside this file, when it has any: an extension adds rules and
never weakens these. To relax or contradict a rule here, override this file in `framework.toml` with a reason that names
the rule.

**The order is: roadmap, then align in conversation and lock a design, then (for anything a person will touch) a UX mock
pass, then one spec, one plan and one test-driven build per increment, reviewed, closed out, merged by a person on the roster.** The
design is a hand-written lock of what was discussed and decided; the spec and the plan follow from it.

## The stages

| # | Stage | Produces | Lives in | Gate |
| --- | --- | --- | --- | --- |
| 0 | **Roadmap** (optional until there are several tracks) | Tracks, phases, order, what waits on a person | `Docs/ROADMAP.md` | Amended as decisions land |
| 1 | **Converse and lock a design** | Intent, acceptance criteria, decomposition, decisions locked, open questions | `Docs/design/<date>-<topic>.md` | **A person on the roster locks it**: its status moves from `Proposed` to `Accepted` |
| 1a | **UX mock pass**, only for something a person will touch (an app, a screen, a panel, an editor, a CLI) | A mock reviewed on its own: layout, interaction, states | Beside the design, under `Docs/design/` | A person on the roster accepts the mock before the widget or screen is built |
| 2 | **Spec** | One increment's exact deliverable, interfaces, acceptance gate, out of scope | `Docs/superpowers/specs/` | Accepted by a person on the roster |
| 3 | **Plan** | Ordered tasks with checkboxes, each small enough to verify | `Docs/superpowers/plans/` | Accepted by a person on the roster |
| 4 | **Build** | Code and tests, test-first | A branch `type/<slug>` (a worktree is optional) | `make check` green on CI |
| 5 | **Review** | The automated review on every push; the deliberate review on a significant increment | The pull request | Findings fixed or declined with a reason |
| 6 | **Close out** | Plan task ticked with its verification, spec amended, journal, handoff, board | Per [definition-of-done.md](definition-of-done.md) | The docs check green |
| 7 | **Merge** | The increment on the default branch | The forge | **A person on the roster merges and deletes the branch** (their own work included; with more than one person on the roster, ask another for a review first) |

A plan task is ticked when its verification ran, never when its code was written. A phase is done when the spec's acceptance
gate passed and the roadmap, README and affected design were updated.

A **spike** branches off at stage 1 or 2 when a question has to be answered by running something: the question and the
result that would stop the work are stated first, the code is frozen under `Spikes/` and excluded from lint, the result is
written up in the spike's README, and nothing in production imports it. A **roadmap** is the order of tracks and phases; the
**board** is the status of each.

A board yes is not a lock. A row with a cost and a verdict is permission to open the conversation, not the design.

## Who owns what

A program of several increments has several records, and each owns one thing. Duplicating between them is how they drift.

| Record | Owns | Does not own |
| --- | --- | --- |
| **Roadmap** | The tracks, the phases, the gates | Any increment's design |
| **Design** | **Why**: goal, options, what is decided and why | Status, or an increment's detailed design |
| **Spec** | **What one increment builds** and how it is verified | The program; it links up to its design |
| **Plan** | The ordered tasks and their verification notes | Rationale beyond a line |
| **Board** | **Status**: gates, now, next, blocked, Icebox | Rationale beyond a line |
| **ADR** | One structural decision, its consequences and when to revisit it | The narrative that led to it |
| **Journal** | **The narrative**: what happened, which beliefs changed | Current truth |
| **Handoff** | **The snapshot** a new session needs: project truth in the shared `CURRENT.md`, each person's session truth in their own `people/<login>.md` | History |
| **Glossary** | The words | Their use in a document |
| **Ledger** | How the process has failed, as triggers | The work |

## Standing rules at every stage

- **A mentioned feature is not a work order.** Search the board first (the row files under `Docs/plan/board/`, or the
  rendered page), so two people do not start one idea. It goes on the board's Icebox with a cost (a number and its unit, or `unsized: <reason>` when no one can size it yet), a reason it
  is not built now and a verdict, and the idea links to where it was said (the journal entry, design, spec or pull request;
  a pull request or issue as its full URL), unless a person on the roster says build it or it blocks work in flight. Ask "pull it forward now?" before building an Icebox row.
  Pulling it forward moves its row file to *Now* (the board README, *Moving a row*); it never writes a second row. A
  row whose decision waits on other work says so in a `Waits on` line that links that row.
- **A row's id is its file name, and every artifact names it.** The id is the row file's name without `.md`
  (`YYYY-MM-DD-<slug>`, the **UTC** day it was written, as a journal file's time is UTC); once the row is on the
  default branch its file is never renamed or deleted, though its title may change (`row-kept`). Every design, spec
  and plan names its row in a `**Board:**` header line, ``**Board:** [`<id>`](<the row file>)``, or
  `**Board:** none (reason)`; an ADR, a journal entry and a pull request may (`row-ref`). The board page lists each
  row's artifacts. When you mention a row, give its id beside its title.
- **The board holds this repository's work.** An idea whose change is in another repository (its layout, its retrofit, a
  standard only it and its siblings use) goes on that repository's board, wherever it was said. A row here may name another
  repository as the evidence for a change to this one, and links to that repository's row when this one waits on it.
- **Two-way doors are decided and recorded in the pull request's *Decisions* table; one-way doors are asked.** The autonomy
  protocol is in [definition-of-done.md](definition-of-done.md).
- **Never stop a process you did not start.**
- **Work lands through a pull request a person merges.** An agent never merges. Who merges and who decides is in
  [definition-of-done.md](definition-of-done.md#who-merges-and-who-decides).
- **A new word gets its glossary row first**, and every design, spec and plan carries a *Terms introduced* section.
- **A spec lists, for every framework file it adds or changes (one `framework-manifest.toml` classifies), its module,
  its kind (managed, parametrised, project-owned) and who owns it.** In the template that is every payload file; in a
  project, the managed and parametrised files and any seed it changes. A project's own files are in no manifest, so
  the spec lists them by path alone. A file the spec does not list is not in scope. (A spec assumed one module for
  every file, ignored a derived page the docs check walks, and assumed a project-owned file reaches clones.)
- **A script or a patch that contains backslashes or quotes is written to a file and the file run**, never carried through a
  shell heredoc. (Framework 3 and 4 hold the cause; the rule is where the work starts. It recurred in at least seven pull
  requests.)
- **The ledgers are read before work starts** and appended to, in the same pull request, when the process fails.
