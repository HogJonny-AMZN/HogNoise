# Definition of done, and the autonomy protocol

**Status:** Living. Managed by the template: a repository's copy must match, so do not edit it here; propose a change to the
template. It states what ends an increment and how much to decide alone.

**This project's additions** go in `definition-of-done-project.md` beside this file, when it has any: an extension adds
rules and never weakens these. To relax or contradict a rule here, override this file in `framework.toml` with a reason
that names the rule.

## Principle

**Minimal now, growing with the codebase.** Process that does not catch a real failure is tax. Every rule here exists
because something drifted or broke in one of the repositories this framework was drawn from. The growth ladder at the bottom
says what gets added when; do not add a tier before its trigger.

## DoD: an increment

An increment ends with the docs comprehensively updated so nothing drifts. A checklist item saying "keep the docs
consistent" degrades into a rubber stamp within a month, so as much as possible is mechanised. One command runs every check
that CI runs, in CI's order, except the commit-message job on a pull request ([ci.md](ci.md)):

```bash
make check                      # the same stage list as CI (`tools/check.py --list` prints it; tooling.md explains each)
uv run python tools/check.py    # the same thing without make, for a machine that has none
```

`make check` is a one-line dispatcher over `tools/check.py`, which holds the stage list and logic; a machine without make loses
typing and nothing else. A test asserts that the CI workflow runs the same stages in the same order, so local green and CI
green cannot drift apart. The stages, the git hooks and the Makefile rule are in [tooling.md](tooling.md); the workflow is in
[ci.md](ci.md).

| # | Requirement | Enforced by |
| --- | --- | --- |
| 1 | Tests and lint pass on CI, on every leg. No test is deleted or skipped to get green; a replacement is in the same pull request, named | CI; judgment |
| 1a | Code that reads the filesystem, runs a subprocess, calls the network or parses text it did not write has a test for each case of [testing.md](testing.md)'s *Error paths* that applies to it, or the pull request says which case and why not (the ledger's entries 42 and 43: the checklist existed, and was not applied where the code was written) | The pull request template's checkbox; the deliberate review's *Error paths* table |
| 2 | Hygiene: no identifier on the project's list appears in any tracked file outside the allowlist | The hygiene check, in CI and before every push |
| 3 | Docs match reality: the plan task ticked with its verification, the spec amended if an interface changed, status lines, the project README reflecting the present state (a README that says no code exists after code landed misleads the next reader), the affected topic file, and every new term's glossary row | The docs check (`links`, `status`, `terms`, `vocabulary`); judgment for content |
| 4 | A one-way-door decision has its ADR | Judgment |
| 4a | Every two-way-door decision is in the pull request's *Decisions* table, no more than eight | The pull request template's checkbox; judgment |
| 5 | The journal is appended for this session | The docs check (`journal-index`, `journal-day`), plus judgment on content |
| 6 | The handoff reflects the present state when work was interrupted, a decision changed, the state moved, or **the owner stated a preference, constraint or correction** (it has been the review finding on more than one pull request). A session rewrites its own file, `Docs/handoffs/people/<login>.md` (session truth: the branch, what is mid-build, what the next session picks up), and the shared `CURRENT.md` only when project truth changed (where the project is, the gates, what the owner said that holds) | The docs check (`handoff`, the line limit); judgment |
| 7 | The board is updated when a row lands, a gate closes, or an idea is said out loud; a landed row keeps its pull request number and is struck through (a hand-kept board) or its `State:` starts with `Landed` (a row file), never deleted. A board in directory form is one file per row under `Docs/plan/board/`, rendered by `make board`; search the rows before adding one. A landed row's `Section` is `now`; an idea pulled forward from the Icebox is its row moved, never copied; a wait on other work is a `Waits on` line linking that row. When work lands, every row and handoff it touches is updated, not only the row you came to fix | The docs check (`board`, `landed-rows`, `board-state`, `waits-on`); judgment (the ledger's entry 34) |
| 8 | The failure ledger is appended **in the same pull request** when the process failed | Judgment; the ledger's entry for the class |
| 9 | The automated review is assessed: each finding fixed or refuted with evidence, answered on its thread | The `review-and-pr` skill |
| 10 | A significant increment has had a deliberate review, its findings answered in the pull request's *Review* section | The pull request template's checkbox; the rule below |
| 11 | Landed through a pull request a person merges | Process: an agent never merges |

**A session memory is not a record.** It helps only a session that recalls it, and the next session is a different one. If a
process failure can recur it earns a ledger entry or a check that goes red, here and now.

### What the docs check catches, and why each check exists

| Check | The failure it catches |
| --- | --- |
| `control-char` | An invisible control character is invisible in an editor and on the page, and passes every other check: a C0 code but tab and line feed, DEL, a C1 code, a bidirectional embedding, override or isolate (U+202A to U+202E, U+2066 to U+2069), the line or paragraph separator (U+2028, U+2029), the zero-width space, or a byte-order mark after the start of the file. A C0 code is the trace a shell heredoc leaves when it turns a backslash escape into the character (framework ledger 3); a bidirectional control makes a line display other than it reads, in a file an agent takes as instructions. The joiners, the direction marks and the word joiner are left alone: prose uses them. One finding per character, with its file, line and code point |
| `links` | A renamed file leaves every link to it dangling; a link whose case differs from the file passes on a case-insensitive disk and fails on a case-sensitive CI runner; a link that climbs above the repository root passes on one machine and fails on another |
| `fences` | A code fence that never closes hides the rest of its file from every other check, so each of them would pass vacuously over it |
| `status`, `single-status` | Without a status header a reader cannot tell a decision from a hypothesis or a live document from a stale one; the vocabulary is closed (`Proposed`, `Accepted`, `Living`, `Superseded`, `Abandoned`) and covers specs and plans too; a second status further down is invisible to a check that reads the first twelve lines |
| `status-copy` | A status written beside a link (in parentheses right after it, in parentheses and a colon right before it, or in a table cell of a row that links it) is a copy, and it goes stale when the document it points to moves: eight times in pull requests 21 to 47 it was left behind. It is compared with the target's own `**Status:**`; a parenthesis that names a second status (`Proposed then Accepted`) is history, and the journal and the per-login handoffs (each written by its login alone) are exempt. Link and let the document carry its status |
| `journal-index`, `journal-day` | A session file linked from nowhere is a session that did not happen for the next reader; a handoff dated after the newest journal file means a day that changed the state has no entry. A per-login handoff is held to that login's own new-form files: dated after their newest, or with none at all, is a finding (the session that writes a handoff writes its journal file) |
| `journal-author` | A journal that cannot say who wrote an entry, or names someone the project never listed. Runs only when `framework.toml` has a `[[people]]` roster (a repository without one is not checked): each entry of a `YYYY-MM-DD-<login>-HHMM.md` file starts with `**By:** @login · **Agent:** …`, every login it names (and every `@login:` quote tag) is on the roster, the file name's login is too, and the file has a `**Summary:**` line. An entry is a `###` heading, so a `##` heading in the file is reported: what follows it would escape these checks. `Agent:` is free text and never read beyond being present |
| `adr-index` | An unindexed ADR is invisible to anyone browsing decisions |
| `adr-duplicate` | Two ADRs with one id. A new ADR is named `ADR-YYYY-MM-DD-<slug>.md` (the day it was written; the slug lowercase letters, digits and single hyphens), so two branches never choose one name; the numbered `ADR-NNN-<slug>.md` form stays valid forever and is never renamed. Two branches that each add the next number merge cleanly and collide only here, so the check names both files; a dated name with an unreal day or a slug that breaks the rule is a finding too |
| `board` | A hand-kept board missing a section a reader looks for (Gates, Now, Next, Blocked, Icebox) is a tracker degrading into a list. A board in directory form (row files under `board_dir`, `YYYY-MM-DD-<slug>.md`) has a title and the header lines its section needs on every row: `Section`, `Owner` (a login, or `none` on a gate or an Icebox row) and `State` always; a gate may name a `Decider`; an Icebox row needs a `Cost` (a number or a range and a unit, or `unsized: <reason>` when no one can size it yet; a done one, `Closed` or `Dropped`, may leave it out), a `Verdict` and `Raised` (a link to where the idea was said, or `unrecorded (converted YYYY-MM-DD)` on a converted row); an unknown or repeated line, a login off the roster, anything in the directory but rows and a README, and a hand-kept page beside the rows (two trackers) are findings |
| `landed-rows` | A struck-through board row, or a row file whose `State` starts with `Landed`, that names no pull request points at nothing once the branch is deleted. A closed gate (decided, not landed) and a row that says it closed with no pull request, and why, are exempt (the reason is required: the words alone are not enough) |
| `board-state` | A row file whose `Section` contradicts its `State`: moving work forward edits the state, and nothing made the section follow. A state that starts with `Landed` outside *Now* (a gate excepted: it closes in place), one that starts with `Queued` in *Now*, an Icebox row whose state says `Pulled forward` (a second copy of the row; pulling an idea forward moves its row), and a state that is not done with `Landed`, `Closed` or `Dropped` opening a later clause (the row still reads as open) are findings. On the template's own board two landed rows sat in *Next* and three pulled-forward rows stayed on the Icebox |
| `waits-on` | A row that waits on other work, with nothing to notice when that work lands: five Icebox verdicts on the template's board waited on work that had landed, one for three weeks. A row's `Waits on` line links the rows it waits for; a link to a row that is done (landed, closed or dropped) is a finding (decide the row again), and so is a link that reaches no row file, or a line with no link. A wait written as prose is not read |
| `row-ref` | A design, spec or plan that names no board row, so nothing leads from the idea to its records or back. Each carries a `**Board:**` header line linking its row by id (the row file's name, the link's text in backticks), or `none (reason)`; an ADR or a journal entry may, and is checked when it does. A link that reaches no row, text that is not the id, `none` with no reason, two lines in one header, and the old plain `Board:` line are findings. Only headers are read. A board kept as one page has no ids, and the check stands down |
| `row-kept` | A row renamed or deleted after it reached the default branch: every pull request, commit and document outside the checkout that named it now names nothing, and a rename with its links updated passes every other check. A row file on the base (`origin/<base>` in a pull request on CI, the merge base with the default branch locally) that is gone from the tree is a finding. With no git or no base it is skipped, and the run says why; in CI a base that cannot be read stops the run (fetch the history: `fetch-depth: 0`). A board kept as one page is still compared with a base that has row files, so deleting every row does not turn the check off |
| `handoff` | A handoff past the project's line limit has become a log (the limit is `handoff_max_lines` in `framework.toml`, default 150); one with no real `Last updated` day leaves `journal-day` nothing to compare. The same two rules hold each per-login handoff under `handoff_people_dir`, which is named for a login and nothing else (no README: `readme` is a login), not a name Windows reserves (`CON`, `NUL`, `COM1` and the rest, which a Windows checkout could not hold), and on the roster when there is one |
| `terms` | A design, spec or plan without a *Terms introduced* section, or naming a term with no glossary row: a word whose meaning only its author holds. The documents written before the rule are listed in `terms_grandfathered`, and that list only shrinks: a listed file that is gone or now has a sound section is a finding |
| `vocabulary`, `glossary-row` | A retired term used as if current: two names for one concept means an agent retrieves it by neither. A line may name a retired term only if it also names its replacement (so the ledger and a migration note can record a change). The only places the check does not look are `retired_exempt_dirs` (by default the append-only journal), a `Superseded` or `Abandoned` document, and a document whose header translates the term on one line naming both. A retired-table row must be enforceable: one term, a replacement that is a short name and does not appear inside the term (`Color Stack Window` replaced by `Color Stack` is found on every line that has the term, so it enforces nothing), no term twice; an explanation goes in the *Why* column |
| `corpus` | A check that scanned zero files and passed; a file the check could not read, which it therefore did not check |
| `orphan` | A governed document that no chain of links reaches from the map (every file outside `governed_dirs`, plus the `orphan_allow` entry points, by default `Docs/README.md`): written, never wired in, so invisible to the agents it is for. Two documents that link only to each other are still orphans; a journal entry's own links wire nothing in; a link to a directory does not reach what is inside it. An extension beside its base (`python-project.md` beside `python.md`) is reached through the base, whose sentence names it |
| `extension-base` | An extension with no base beside it: a governed `<name>-project.md` with no `<name>.md` in the same directory, because the base's name was misspelled or the file sits in another folder, so nothing leads a reader to it; a document that is no extension but whose name ends in `-project` is read as one, and is renamed. The journal, the board and the per-login handoff directories are not read (there a name is a session, a row or a login, and a login may end in `-project`) |
| `adr-refs` | A one-sided relation between ADRs. The header is the label in bold (`**Superseded by:**`, or `Supersedes`, `Extended by`, `Extends`; the colon inside or outside the bold, any case, in a list item or a block quote) followed by a link to the other ADR on the same line, and a status line that says `Superseded by` with a link counts as `Superseded by`. Each needs the inverse kind in the target, linking back to this ADR, in every direction |
| `nested-instructions` | An instruction file (the entry file or a harness adapter, by name) below the root, which some harnesses load automatically: a vendored copy once injected another project's conventions. A project that wants scoped instructions lists the file in `instructions_allow` and records why in an ADR |

A test compares this table with the checks the tool runs, in both directions: a check that runs and is not listed, or listed and not run, fails it. A row may be marked *Planned* while its check is being built; the test then requires that it is not run yet.

The docs check also fails a `Superseded` status that does not say by what. Where it looks and what it leaves alone (excluded
directories by name at any depth (on top of `.git`, `.venv`, `node_modules` and `__pycache__`, which nothing puts back), the governed directories, the index paths, the board's sections) is the optional `[docs]` table of
`framework.toml`; the status words are not configurable, on purpose. It exits 0 when clean, 1 on findings and 2 when its
configuration is unusable.

The `[docs]` keys: `exclude_parts`, `governed_dirs`, `status_exempt`, `adr_index`, `journal_index`, `journal_dir`,
`handoff`, `handoff_people_dir` (the per-login handoffs, default `Docs/handoffs/people`), `board`, `board_dir` (the row files of a board in directory form, default `Docs/plan/board`; the `board` path is then the rendered page), `glossary`, `board_sections` (a hand-kept board only), `terms_dirs` (where a *Terms introduced* section is required),
`terms_grandfathered` (the files written before that rule, a list that only shrinks), `orphan_allow` (entry points
nothing links to), `retired_exempt_dirs` and `instructions_allow`. Each defaults to the framework's layout.

### The hygiene check

Requirement 2 is `tools/check_hygiene.py`. The project lists the identifiers it must not leak or revive (a former codename, a
private name, a checkout path) in `project.json`, under `hygiene`; the list is empty by default, and an empty list passes. The
check reads every file git tracks or would add, and every file name, and reports where an identifier is found, never the
line itself, so that the check does not copy the leak into a CI log.

- **What matches.** An identifier is a literal, compared after Unicode normalisation and case folding, as a substring; a
  space in it matches any run of whitespace, including a line break. A file is read as UTF-8, also as Latin-1 when it is not
  valid UTF-8, and also as UTF-16 and UTF-32 when it holds a NUL byte (a Windows shell writes UTF-16; a binary may hold a
  path). **Other encodings are not read.** A symbolic link is not followed, but its name and target text are checked. A
  submodule's files are not read, and a warning says so.
- **Exceptions.** `project.json` is always allowed, since it holds the list. Any other file or directory is a
  `[[hygiene_allow]]` table in `framework.toml` with a path and **a reason**. An entry whose path carries no identifier any
  more is a finding, so the list only shrinks. An entry must not name a file by the identifier itself: the entry is in
  `framework.toml`, which is scanned too, so rename the file instead.
- **When it cannot vouch.** A file too large to read, or one that cannot be read, is a finding unless it is allowed. **A file
  git stores through LFS (`filter=lfs` in `.gitattributes`) is a binary asset: its content is never read, at any size, and its name
  still is; an `[[hygiene_allow]]` entry for one is not reported stale, because its content was not shown free of identifiers.**
  Where git cannot say which files are LFS (no git, an error), none is exempt, so the large ones are findings as before. Without
  git, or when git fails, it walks the tree instead and warns that a different set of files was checked.

## Identity

Commits and pull requests carry **a person's identity, never an agent's**: the owner's, the one in `project.json`, or a
roster person's own (`[[people]]` in `framework.toml`, with one of the addresses on their row): no attribution trailer or
footer for an AI, and agents commit as the git user of the person they work for, never an agent address. This overrides any
tool's default. When the project requires a sign-off (`signoff` in `project.json`), every commit carries a `Signed-off-by` of
one of those identities: commit with `git commit -s`. A repository with no roster accepts the owner's alone. **One
exception, on a pull request only:** a commit authored by `dependabot[bot]`, on a pull request GitHub records as opened by
Dependabot, may carry that bot's own sign-off. CI's `commits` job alone accepts it; the hook does not, and the attribution
rule applies to it as to any commit. Adding a row with an address to the roster is what lets a person commit through the
hook; anyone on the roster may merge that row, so it is where a review is most worth asking for. The hook itself only
matches the message against the roster it loads. The `commit-msg` hook ([tooling.md](tooling.md)) rejects a message that
breaks either rule; `make hooks` installs it. Already-merged commits keep whatever trailers they have; do not rewrite
history.

## Whose work is it

Several sessions and several people may work the repository at once, and **nothing about a pull request identifies its
session**: the author is a person's account, the owner's or a roster person's, and one account may run several sessions.
Before reading or touching a branch, pull request or review you did not
create in this session, ask whose it is. A check can usually prove *not yours* cheaply and can almost never prove *yours*:
being next to a branch is not owning it. When it is not yours, ask the person you work for. A pull request number is not a work order, just
as a mentioned feature is not one. The ledger has the near misses. A repository with more than one person on its roster turns on
the forge's *require branches to be up to date before merging*: it protects every shared file, not only ADRs, and it is a setting,
not a managed file, so nothing checks it.

## Making a change

1. **Minimise the scope of the change.** The smallest change that satisfies the request. Do not modify unrelated code or
   reformat for style unless asked; a reformatted file hides the real diff.
2. **Preserve existing behaviour.** Keep to the established organisation and naming; do not break a public interface
   without saying so and getting agreement.
3. **Handle ambiguity safely.** Where a request is unclear, state the assumption and proceed on the most reasonable
   reading; ask when the decision is genuinely a person's.
4. **Keep it reversible.** Prefer changes that are easy to read and easy to revert.
5. **Log an unscoped idea, do not build it.** A worthwhile improvement outside the task goes on the board with a cost and a
   verdict.
6. **Not without asking:** a global refactor, a new dependency, a change to the core architecture, or renaming an existing
   public identifier.

### Scope

Land the requested scope; do not quietly narrow it, widen it, or substitute something adjacent. If part of it turns out to
be blocked, finish everything else in full and **say plainly what was left out and why**. Scaling the work down is the
call of the person you work for.

## Who merges and who decides

- **A person on the roster merges**, their own work included: the merge is a person's act of trust, and the merge is the
  review, so whoever merges reads the *Decisions* table. With more than one person on the roster, ask another for a review
  first; it is suggested, not required. The forge's *require a pull request before merging* with one approving review is
  recommended for such a repository: a safeguard, not a check of who may merge.
- **A person on the roster decides**: a one-way door, a design's lock, a spec's or plan's acceptance, a gate's close, an
  Icebox row's pull-forward. The agent asks the person it is working for and helps them decide (the options, a
  recommendation and why, the cost to reverse, any precedent in the ADRs, designs or ledgers), then records the answer with
  their login.
- **With no roster**, the owner in `project.json` is the one person, and merges and decides.
- **An agent never merges and never decides a one-way door.**
- **An owner** (a roster role several may hold) tags a release. Adding a person to the roster or giving a role is a merge
  like any other, so it is where a review is most worth asking for.

## The autonomy protocol

> Keep going until you feel there is a real human-in-the-loop review need or decision. If a decision is a two-way door and
> easily changed, just go with an option and log it. If too many of these "didn't review" decisions queue up, stop for
> thorough review.

### Two-way door: decide, record, continue

Cheap to reverse, no data loss, no outward effect, nothing built on top yet: naming, file layout, document structure, which
of several adequate implementations, tooling before anything depends on it, wording, test structure, anything reversible in
under an hour. **Record it in the pull request's *Decisions* table** (the decision, the alternative, why, the cost to
reverse) and keep moving. The merge is the review, so a decision not in the table was not reviewed.

### One-way door: stop and ask

Expensive to reverse, or a person on the roster has already shown they hold an opinion:

- A new ADR, or a change to a locked design
- Anything outward-facing: merging, publishing, creating a repository, posting outside the project's own pull requests
- Deleting or rewriting history: the journal, an ADR, a superseded document
- Stopping a process the agent did not start
- Topics a person on the roster has already corrected
- Anything that invalidates a recorded verification

### The backstop

**Eight decisions per pull request.** More than that and the pull request is too big to review in one sitting: split it.
Eight keeps the table a five-minute read, low enough that a wrong assumption cannot compound far and high enough that the
autonomy is real. A decision reversed in review is changed before merge, and the row says so; a reversal is part
of the record, not an erasure.

## Journaling cadence

Continuous, see [the journal](../journal/README.md) and [its rules](journal.md): appended as work happens, in at least one file per calendar day and one
per session: every meaningful exchange, each step that changed or taught something, and whenever a belief changes.

## When the deliberate review runs

Not on every change, but on **significant** ones: a new module or tool, a change to a contract between components,
roughly 200 or more changed lines outside tests. **Not** documentation-only changes, dependency bumps, test-only changes or
small fixes. The deliberate review is the `local-review` skill: an isolated reviewer (a subagent, a second session or another
model that has not seen the author's reasoning) against the repository's standards and a rubric of design, architecture,
readability, maintainability, performance, security, error handling, logging, coding standards and, where it applies,
layering, each scored out of ten with 7 as the baseline. Put its score table in the pull request's *Review* section with every finding fixed or declined with a reason. The
trigger is the pull request template, not memory. The automated review on the pull request is the automatic one; this is the
deliberate one, and they catch different things.

## A spike's definition of done

A spike is throwaway evidence code that answers one question. State the question and what result would stop the work (a
spike without a stated fail action is not a gate), write the result up in the spike's own README whatever it is (a failed
spike is a result), and freeze the code under `Spikes/`: committed as evidence, never maintained, never imported by
production code, and excluded from lint. It is held to this definition and not to the code one.

## Growth ladder

| Trigger | Add |
| --- | --- |
| The first spike | The spike definition above: a stated question, a written result, frozen code |
| The first code | Tests first, tests passing, lint clean, the deliberate review before merge when the increment is significant |
| The standards pass | These standards, the first ADRs, a status line on every governed document, the ledger |
| A second contributor | Branch protection and required reviews |
| Several sessions at once | Lane-prefixed board ids, the pending-review queue, the branch-ownership tool (the `lanes` and `branch-ownership` modules) |
| A user-facing surface | A UX standard and a smoke gate that launches and drives each app (the `ux` module); the mock pass itself is already a stage in the workflow |
| A second repository on the same framework | The sync check, so an improvement made once reaches all of them |

## What is deliberately not here

A DoD for code that does not exist is ceremony. There are no templates for everything, no formal review gate on
documentation changes, no estimation ritual and no process document about process documents.
