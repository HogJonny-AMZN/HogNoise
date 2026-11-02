# Glossary

**Status:** Living. Seeded on 2026-10-31 with the framework's own terms; the project adds its own below. One word per
concept: use these exact words, no synonyms. A new concept gets its row here first, in the same change and before the
code or document that uses it. A retired term is struck through in the table at the end and kept, so that it can be
refused as current.

## Domain

| Term | Meaning |
| --- | --- |
| **NoiseParams** | The one parameter record every rendering of a noise reads: type, seed, frequency, fractal, cellular, warp and perturb settings. |
| **Rung** | One implementation of a capability on the ladder: `numba` (compiled kernels), `numpy` (the base), and `fastnoiselite` (the reference binding, chosen only by name). |
| **Ladder** | The ordered rungs for one capability, chosen by `hog_noise.backends.select`: the best available wins, an override-only rung (negative priority) is never chosen automatically, and an explicit override (`HOG_NOISE_BACKEND_<CAPABILITY>`) never falls through. |
| **Oracle vectors** | The outputs captured from the original libraries under `tests/vectors/noise/`, which every rung is compared against. |
| **Portability table** | `tests/vectors/noise/portability.md`: every comparison and how closely it agreed, rewritten by a full-environment test run. |
| **North star** | The end state the [roadmap](design/2026-11-01-north-star-roadmap.md) defines: one self-contained package with FastNoise2 parity, 4D, and every rendering of every noise on CPU and GPU. |
| **Rendering** | One way a noise is computed: numba, numpy, or a shader language (WGSL, HLSL, GLSL, Metal). The renderings of one graph must agree to their tolerance contract. |
| **Tolerance contract** | The stated bound a rendering must meet against the oracle vectors: zero (bit-identical) for the CPU renderings, a per-node bound for the GPU. |
| **Node graph** | A noise as nodes whose inputs are constants or other nodes, as in FastNoise2; planned, not built. |
| **Conformance harness** | The published check any implementation runs against the oracle vectors; planned, not built ([design](design/2026-11-02-conformance-harness.md), Proposed). |
| **Reference set** | One source of expected values in the vectors: *original* (what FastNoiseLite and FastNoiseSIMD produced) or *hog* (HogNoise's numpy rendering). Proposed with the conformance harness. |
| **Case** | One parameter record over one point set, with its expected values and its bound: the unit the conformance harness checks. Proposed. |
| **Bound** | The largest difference one case accepts: a constant, or a multiple of the noise-space coordinate (`scale * max(1, abs(coordinate) * frequency)`). A rendering's tolerance contract is stated as bounds. Proposed. |


## Process

| Term | Meaning |
| --- | --- |
| **Layer** | A package of `src/` with a place in `framework.toml`'s `[layers] order`: it may import itself and the layers before it, never one after. |
| **Layer rule** | The rules the `[layers]` table states: the order, which layers are pure (standard library only), and which packages are deliberately unlayered. |
| **Boundary test** | `tests/test_boundaries.py` with `tools/boundaries.py`: reads `src/` with `ast` and fails, naming file, line and rule, when a layer rule is broken. |
| **Mock project** | `src/` as the template seeds it: a small, neutral, working Python project (a task-list engine) that the checks and the boundary test run against until the project replaces it. |
| **Faux library** | One package of the mock project (`core`, `app`): real, tested code on a toy domain, standing in for a project's own libraries. |
| **Handoff** | `Docs/handoffs/CURRENT.md`, the living snapshot a new session reads first: the state, what is in flight, what the owner said that is written nowhere else. Cut when it grows; history is the journal and git. |
| **Project truth** | What the shared handoff, `Docs/handoffs/CURRENT.md`, holds: where the project is, the open gates, what the owner has said that holds, how to run the gate. It changes when a decision changes, not when a session ends. |
| **Session truth** | What a per-login handoff, `Docs/handoffs/people/<login>.md`, holds: the branch, what is mid-build, what that person's next session picks up. Written only by its login; named for a login on the roster, held to the same rules as the shared file, and dated no later than that login's newest journal file. |
| **Board** | The tracker and the only place status lives: gates, Now, Next, Blocked, Icebox. One file per row under `Docs/plan/board/` (directory form), rendered into `Docs/plan/BOARD.md` by `make board`; or, in a repository that never converted, the hand-kept page itself. |
| **Row file** | One board row as its own file under `Docs/plan/board/`, named `YYYY-MM-DD-<slug>.md`, with header lines for its section, owner and state and, for an Icebox row, cost, verdict and where it was raised. The `board` check holds each to its section's lines. |
| **Decider** | The roster login a gate row names as the person who closes it; anyone on the roster when none is named. Not a hierarchy: a line on a row. |
| **Board page** | `Docs/plan/BOARD.md` when the board is a directory of row files: rendered from them by `make board` (`tools/render_board.py`), git-ignored and never committed, with a section per board heading and a view by owner. In a repository with a hand-kept board the same path is the board itself. |
| **Gate** (board) | A decision a person on the roster makes, numbered G1 upward; nothing downstream of an open one may be committed to. Not the check runner. |
| **Check runner** | `tools/check.py`: runs every check CI runs, in CI's order, and is the oracle the CI parity test reads. `make check` is a one-line dispatcher to it. |
| **Check stage** | One command the check runner runs (`lint`, `docs`, `tests`...), owned by a module of `framework.toml` and run only while that module is on. |
| **Fast stages** | The check stages cheap enough for the pre-commit hook: every stage but the tests. `check.py --fast` runs them. |
| **Adapter** | A generated file that points a harness at `AGENTS.md` and holds nothing else; the compatibility matrix says which harness gets which. `tools/sync_adapters.py` writes it for each enabled harness and `--check` fails on one with text of its own. |
| **Skills mirror** | A copy of `.agents/skills/` (byte for byte; line endings normalised for text files) in the folder a harness reads its skills from, generated and checked by `tools/sync_adapters.py`. |
| **Conformance probe** | The procedure that shows a harness reads `AGENTS.md` and the skills through what the framework generates for it, by planting tokens and asking for them; run by a person, recorded in the compatibility matrix, and required before the harness is enabled. |
| **Null control** | The probe question asked with neither `AGENTS.md` nor the adapter present: the harness must not give the token, or the probe could not have failed. |
| **Compatibility matrix** | `Docs/standards/compatibility-matrix.md`: what each harness reads, where that was learned and when, what is generated for it, and whether its probe passed. With `harness-probes.md`, the only managed documents that name harnesses. |
| **CI parity** | The workflow runs the check runner's stages in the runner's order; a test asserts it, so that local green and CI green mean the same thing. |
| **Icebox** | Where every idea said out loud lands with a cost, a reason it is not built now and a verdict, and the idea links to where it was said; a mentioned feature is not a work order. |
| **Verdict** | The one-line judgement attached to an idea when it is recorded: awesome, good with the value named, or meh with what would fix it. Verdicts order ideas; they never delete them. |
| **Landed row** | A finished board row, struck through and keeping its pull request number; nothing is deleted. |
| **Two-way door** | A decision cheap to reverse, taken and recorded in the pull request's *Decisions* table; the merge is the review, by whoever merges. |
| **One-way door** | A decision a person on the roster makes, never an agent, asked of the person the agent works for: a new ADR, a change to a locked design, anything outward-facing or expensive to reverse. |
| **Autonomy protocol** | Keep going until a human decision is needed: decide a two-way door and log it, stop and ask at a one-way door; more than eight logged decisions in one pull request means split it. |
| **Design** (pre-spec) | A hand-written lock of what was discussed and decided, under `Docs/design/`; a person on the roster accepts it (its status moves to `Accepted`) and the spec follows. |
| **Spec**, **Plan** | One increment's deliverable and its ordered, verifiable tasks. A task is ticked when its verification ran, never when its code was written. |
| **UX mock pass** | The stage between the lock and the spec for anything a person will touch: a mock reviewed and accepted on its own before the widget or screen is built. |
| **Spike** | Throwaway evidence code that answers one question: the question and the result that would stop the work are stated first, the result is written up whatever it is, and the code is frozen and never imported by production code. |
| **Roadmap** | The order of tracks and phases and what waits on the owner; not the tracker (that is the board). |
| **Deliberate review** | The review of a significant increment by an isolated reviewer against the repository's standards and a rubric, put in the pull request's *Review* section; distinct from the automated review every pull request gets. |
| **Backstop** | The limit of eight logged two-way decisions in one pull request: more than that and the pull request is split. |
| **Growth ladder** | The table in the definition of done that says what process is added when, so no tier exists before its trigger. |
| **Increment** | One reviewable unit of work with its own spec, plan, pull request and close-out. |
| **Significant increment** | One that earns the deliberate review: a new module or tool, a contract change, or about 200 or more changed lines outside tests. Not documentation only, a dependency bump, test-only or a small fix. |
| **ADR** | An append-only record of one structural decision with its consequences and when to revisit it; changed only by a superseding ADR. A new one is named `ADR-YYYY-MM-DD-<slug>.md`; the numbered form stays valid. |
| **ADR id** | What names an ADR for the duplicate check: the number of a numbered ADR (`ADR-005`, compared as an integer), or the date and slug of a dated one (`ADR-2026-10-29-records-for-a-team`). Two ADR files with one id fail the `adr-duplicate` check. |
| **Journal** | `Docs/journal/`, the append-only narrative, at least one file per calendar day and one per session: what happened and which beliefs changed. |
| **Ledger** | How the process has failed, as triggers ("when you notice X, do Y") with the evidence for each. Two files: `Docs/standards/failure-modes.md` (the framework's, managed) and `failure-modes-project.md` (the project's, starts empty). Loaded before work starts: retrieval is the enforcement. |
| **Definition of done** | What ends an increment: the checks green and the repository's account of itself still true (docs, board, handoff, journal, ledger). |
| **Status** | The word on a document's `**Status:**` line: `Proposed`, `Accepted`, `Living`, `Superseded` (saying by what) or `Abandoned`. A proposed document is a hypothesis, not a fact. |
| **Terms introduced** | The section every design, spec and plan carries (by convention the last), naming the glossary terms it introduces in bold, or saying None. |
| **Mechanise** | To make a rule held by something stronger than prose: a check that goes red in CI, or a generator with a freshness check. |
| **Framework module** | One switchable group of the template's files, checks and CI steps; `framework.toml` says which are on. |
| **Managed file**, **Parametrised file**, **Project-owned file** | The three classes of file in `framework-manifest.toml`: the template owns it and a copy must match; the template owns the skeleton and the project's values are substituted in; seeded once and then the project's. |
| **Base** | A managed file, the template's bytes, that a project may extend: it says in one sentence where its extension lives. |
| **Extension** | A project-owned file beside its base and named for it (`python-project.md` beside `python.md`; `project.md` inside a skill's folder) that adds the project's rules to that base and never weakens it; relaxing or contradicting a base rule is an override. The docs check holds it to its base (`extension-base`); no release ships or touches one. |
| **Override** | A managed file replaced on purpose where the project contradicts the template: an entry in `framework.toml` naming the file, with a reason that names the rule it contradicts; the sync check does not report that file as edited. Adding to a file is an extension, not an override. A list of overrides is the repository's visible debt to the template. |
| **Framework lock** | `framework.lock`: the template version a repository was made from, the day it was initialised, and the hash of each managed and parametrised file. |
| **Docs check** | `tools/check_docs.py`: the named checks that keep the documents consistent with each other; `Docs/standards/definition-of-done.md` lists them and the failure each catches. Each is shown to fail by a test that breaks exactly its rule. |
| **Governed document** | A document in a governed directory (by default all of `Docs/`), which must carry a status line in its first 12 lines. Two exemptions: a file the `[docs]` table's `status_exempt` lists (by default the decisions index) and a dated journal session file directly in the journal directory. |
| **Docs table** | The optional `[docs]` table of `framework.toml`: where the docs check looks and what it leaves alone. Every key defaults to the framework's own layout; the status words are not configurable. |
| **Finding** | One line the docs check prints for one inconsistency: `[check-name] location: what is wrong`. A run with any finding exits 1. |
| **Session file** | A file in `Docs/journal/` (a new-form one in its month folder) named `YYYY-MM-DD-session-NN.md` (the old form: every one is a row in the journal index) or `YYYY-MM-DD-<login>-HHMM.md` (the new form: the author's GitHub login and the session's start in UTC; it needs no row). One session; a new calendar day starts a new file. It is not a governed document (no status line). |
| **Roster** | The `[[people]]` table in `framework.toml`: each person who may be named in the journal, with a GitHub `login`, a `name`, a `role` (`owner` or `contributor`) and the commit `emails` they use. The `journal-author` check holds an entry's author to it, and the `commit-msg` hook accepts a sign-off from a person on it who has an address. A repository without the table has no roster and is not checked. |
| **Journal entry** | One `###` section of a new-form session file, with `**By:**` (the human author's login), `**Agent:**` (the tool and model, or `none`) and optionally `**Said by:**`; the unit of attribution. Not a seed (a project-owned file) or a ledger entry. |
| **Month folder** | A directory `Docs/journal/YYYY-MM/` that holds the new-form session files whose names start with that month; an old-form file stays at the top of the journal directory. |
| **Journal index** | The journal's list of its session files, in two parts that the word covers together. For the older files (`YYYY-MM-DD-session-NN.md`) it is the table in `Docs/journal/README.md`: every one is a row, and the `journal-index` check and the `journal_index` key of `[docs]` mean it. For the new form (`YYYY-MM-DD-<login>-HHMM.md`) it is `Docs/journal/INDEX.md`, rendered newest first by `make journal` (`tools/render_journal_index.py`) from the files' `**Summary:**` lines into a git-ignored file, so that no pull request edits a row and the page cannot drift. |
| **Status copy** | A status word written beside a link to a governed document, as a copy of that document's own `**Status:**`: a status in parentheses right after a link, one in parentheses and a colon right before it, or a status cell in a table row that links the document. The `status-copy` check (see `standards/definition-of-done.md`) compares it with the document's own word. Not a status copy: `(was Proposed)`, and anything in the journal. Seen in docs maps, indexes and board rows; entry 32 of the framework ledger |
| **Orphan document** | A governed document that no chain of links reaches from the map (every file outside the governed directories, and the `orphan_allow` entry points): written and never wired in, so invisible to the agents it is for. Two documents that link only to each other are still orphans. The docs check's `orphan` finds it; the fix is a link from the map or from an index the map links. |
| **Grandfathered document** | A design, spec or plan written before the *Terms introduced* rule, listed in `terms_grandfathered` so the rule does not fail it. The list only shrinks: a file that earns the section, or is gone, is a finding that says to remove it. |
| **Instruction file** | `AGENTS.md` and the files that point a coding assistant at it: read automatically by the assistant. Only the repository root may hold one unless `instructions_allow` lists it with an ADR that says why. |
| **Header translation** | A line in a document's first 12 lines that names a retired term and its replacement together ("where this says X, read Y"); it exempts that document from the vocabulary check for that term. |
| **ADR relation line** | The bold label `**Superseded by:**`, or one of its three siblings (`Supersedes`, `Extended by`, `Extends`), followed by a link to another ADR; each needs the inverse in the ADR it links, linking back. |
| **Mechanised by line** | The optional last line of a ledger entry, `**Mechanised by:**`, naming the docs check that holds the class. A test compares the names with the checks that exist. |
| **Framework graph** | `Docs/knowledge/ai-first-framework.graph.json`: the framework's concepts as nodes in layers and its relations as typed edges, and the page `ai-first-framework-graph.md` drawn from it by `tools/render_framework_graph.py`. The page is generated from the data and never edited; `--check` fails when the data is malformed or the page is stale. |
| **Graph layer** | One of the named groups the framework graph's nodes fall into (a word like `state` or `decision`), each with a title. The page draws one diagram per layer and an overview of how layers join. |
| **Graph node** | One entry of the framework graph: an `id` in kebab-case, a `kind`, a `layer`, a `label`, a `seen` string and a one-sentence summary. It stands for one concept of the framework, and no two nodes in a layer share a label. |
| **Graph edge** | A directed link between two graph nodes carrying one graph relation. An edge to a node that is not there, to itself, or a repeat of another edge is a finding. |
| **Graph relation** | The verb on a graph edge (`reads`, `links-to`...), declared once in the data with its meaning and drawn as one arrow style. A relation no edge uses is a finding. |
| **Graph kind** | What a graph node is (an artifact, a rule, a check, a ritual...), declared in the data and drawn as one shape. |
| **Seen in** | The `seen` column of the graph page: letters (`H`, `L`, `S`) for the repositories a concept existed in when the framework was drawn. It carries a project's name as a letter so that the text never does. |
| **Hygiene identifier** | A literal string in `project.json`'s `hygiene` list (a former codename, a private name, a checkout path) that must appear in no file outside the allowlist; matched as a substring after Unicode normalisation and case folding, in file contents and file names. |
| **Hygiene allowlist** | The `[[hygiene_allow]]` tables of `framework.toml`: a file or directory that may carry an identifier, and why. `project.json` is always allowed. An entry that carries nothing any more is a finding. |
| **Lazy-log marker** | The comment `# lazy-log: <the measurement>` on a log call's first line, which lets a measured hot path keep a `%`-format call. A marker with no measurement is a finding. |

## Retired terms

A retired term used as current fails the docs check. Add a row when a word is replaced; never delete one.

| ~~Retired~~ | Use | Why |
| --- | --- | --- |
