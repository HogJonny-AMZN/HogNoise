# Failure modes: HogNoise

**Status:** Living. Seeded on 2026-10-31. This project's ledger: how the process has gone wrong here, as triggers. It is
the project's to edit and starts without entries. The framework's own lessons are in
[failure-modes.md](failure-modes.md); read both before starting work, because retrieval is the enforcement.

Entries are append-only and numbered `P-1`, `P-2`, ... so a cross-reference to "framework 5" or "project P-1" is
unambiguous. Never rewrite one; add a new entry that supersedes it and say which.

## The shape of an entry

```markdown
### P-1 · A short name for the failure

**Trigger:** What you would notice at the moment it applies.
**Do:** The action it should cause.
**Because:** The pull request or commit that proves it, and what happened.
```

## Entries

Append this project's entries below this line, oldest first.

### P-1 · A test names the best rung it expects

**Trigger:** a test asserts which rung, backend or value is "the best" and the answer depends on what is installed.
**Do:** compute the expectation from availability (`HAVE_NUMBA`, `_have_fastnoiselite()`), and run the numpy-only leg.
**Because:** the stage 2 numpy-only run failed `test_ladder_picks_the_best_available_and_override_is_honoured`: it
assumed `pyfastnoiselite` was installed. It passed for months on a machine that had it. CI now has a numpy-only leg.

### P-2 · A test rewrites a committed file from whatever it measured

**Trigger:** a test or tool writes into the tracked tree.
**Do:** run it in the smallest environment and read `git status` afterwards. Write only when the run measured everything
the file claims to describe.
**Because:** `test_write_portability_table` replaced `tests/vectors/noise/portability.md` (211 lines) with a partial
table (145 lines) after a numpy-only run, in the working tree, ready to be committed by accident. It now skips unless
numba and the binding were both compared.

### P-3 · Publishing something that began private

**Trigger:** you are about to make a repository public that was cut from a private one.
**Do:** sweep the tree and every commit, not only the tip, for names of secrets, private projects, and personal or
employer identities, in file contents and in commit metadata. Decide filtered or fresh history with the findings in
front of you, and do not copy package metadata (authors, emails, URLs) from the source without reading it.
**Because:** the stage 3 sweep found no credential values, but did find a CI secret's name in two commits and identity
strings in commit metadata, and the source project's `pyproject.toml` carried an address that must not ship.

### P-4 · A deny-list in a tracked file publishes what it denies

**Trigger:** you are about to put an identifier the repository must never contain (an employer, a private project, a
secret's name) into a checked-in list, so that a check can refuse it.
**Do:** keep that list out of anything that will be published, or list a pattern that does not spell the identifier out.
Before publishing, read the check's own configuration as part of the sweep.
**Because:** the adoption's answers put an employer's email domain and a private project's CI secret name in
`project.json`'s `hygiene` list, so that the hygiene check would refuse them. The pre-publication sweep found them there: the
only place in the tree either string appeared was the list meant to keep them out. They were removed before anything was
pushed; the sweep of every commit had already shown neither string anywhere else.

### P-5 · A fix pushed to a pull request that has already merged

**Trigger:** you are about to push a review fix, or reply "fixed in <commit>" on a thread, some time after the pull
request was last looked at; or a person says it merged.
**Do:** before pushing, read its state (`gh pr view <n> --json state`); it must be `OPEN`. After a person says it merged,
confirm the branch's last commit is in the default branch (`git merge-base --is-ancestor <commit> origin/main`) before
calling the work landed. A commit that missed the merge goes in a new pull request from the default branch, and the merged
one gets a comment pointing there.
**Because:** [PR #12](https://github.com/HogJonny-AMZN/HogNoise/pull/12) merged at 03:34Z; the commit answering Copilot's
second pass was pushed to its branch at 03:36Z, and four resolved threads said "fixed in 2895e40" about text that was not
on `main`. It was caught only because the "deleted" branch still showed on the remote, and landed in
[PR #13](https://github.com/HogJonny-AMZN/HogNoise/pull/13). Not mechanised: the state check is one command, run by hand.

### P-6 · A spec describes today's code from memory

**Trigger:** a spec, design or reply says what the code does today: a limit, a condition, which arrays are compared,
what a dependency can or cannot do.
**Do:** read the code or the record first, and name the function with its file and line; quote the condition rather
than paraphrase it. Where the new work must keep a behaviour, say it calls the existing function instead of restating
the rule.
**Because:** Copilot's two passes on [PR #12](https://github.com/HogJonny-AMZN/HogNoise/pull/12) found four claims about
existing behaviour that were written from memory and were wrong: FastNoiseSIMD's originals "cannot be regenerated" (ADR-007
records a working source build), FastNoiseLite `grid_3d` "compared" (it is only drawn on a sheet), the advisory rule
without its correlation floor and with `rejected` exempting, and the direct `sample_grid` test dropped against the design.
Each was fixed by reading the cited line. Not mechanised: whether a sentence describes code is not something a check can
see.

### P-7 · Checking a merge against a stale `origin/main` (supersedes P-5's check)

**Trigger:** you are about to run P-5's ancestry check after a person says a pull request merged.
**Do:** `git fetch origin` first, and run the check only if the fetch succeeded:
`git fetch origin && git merge-base --is-ancestor <commit> origin/main`. The rest of P-5 stands.
**Because:** P-5 named `git merge-base --is-ancestor <commit> origin/main` without a fetch. `origin/main` is a local ref that
neither a merge on GitHub nor `gh pr view` updates, so straight after a merge the check can call a merged commit missing
and send it into a new pull request for nothing. Copilot found it on
[PR #13](https://github.com/HogJonny-AMZN/HogNoise/pull/13) two minutes after that pull request merged; the check run for
#13 itself had fetched first, so no harm was done.

### P-8 · The deliberate review starts after the pull request opens

**Trigger:** a significant increment is ready, and you are about to push and open its pull request.
**Do:** run the deliberate review (`local-review`) first, act on its findings, and open the pull request with its table
in *Review*, as `review-and-pr` orders it (step 3 before step 5). If a review is still running when the pull request is
up, say so in the reply to the owner in one line that asks them to hold the merge, not only in an unticked box.
**Because:** [PR #16](https://github.com/HogJonny-AMZN/HogNoise/pull/16) was opened with the independent review and Copilot's still to come; CI went green and the owner
merged within the hour, so the review's findings (an unrecoverable regeneration, untyped manifest errors, silent
parameter conversion) landed as a follow-up instead of before the merge. Not mechanised: nothing stops a merge on green
CI, and the rule is the order of the steps.

### P-9 · A command that writes to the forge, built to try something out

**Trigger:** you are about to run a `gh` command that posts, replies, edits, resolves, creates or closes, and its text,
target or arguments are not yet final: a placeholder body, a guessed id, a dry run of the shape.
**Do:** never run it to see what happens. Check the command's shape without the forge (print it, or write the body to a
file and read it back), and run the writing command once, when posting that exact text to that exact target is the
intent. A wrong post is fixed by editing it, and said so in the reply to the owner.
**Because:** on [PR #18](https://github.com/HogJonny-AMZN/HogNoise/pull/18) a command meant as a placeholder posted a real
reply to a Copilot thread (comment 4566206935, 2026-11-13) that linked the wrong issue: ai-first-template #209 instead of
#208. It was edited to the right link at 2026-11-14 00:56Z. A post is public the moment it lands, and notifications go
out before an edit. Not mechanised: whether a command's text is final is not something a check can see.

### P-10 · A count in a spec that no command produced

**Trigger:** a spec, design or plan states a number about the repository's data: features, cases, files, functions,
callers.
**Do:** produce it with a command or script run on the code and data at the commit the document cites, and keep the
command beside the number or in the pull request's *Verified*. A count derived from another count ("48 features lack X,
so 48 new cases") is re-derived from the data, not the arithmetic.
**Because:** the GPU port's spec ([PR #20](https://github.com/HogJonny-AMZN/HogNoise/pull/20)) said the hog set had 95
features and that it would grow by 50 cases. A script run while writing the plan found 114 features, and found that two of
the 48 FastNoiseSIMD features without a 2D case are grids, so the cases were 48. Both were corrected before the merge.
Copilot also found the spec naming one caller of `renderings()` where there are 13. P-6 covers behaviour; this covers
numbers. Not mechanised.

### P-11 · A status a merge changed, fixed on the feature branch only

**Trigger:** a merge changes a status that living records state (a plan Accepted when its pull request merges, a row
landed), and you are working on a long-running branch.
**Do:** fix the records on the default branch, in the next pull request off it; make the same edit on the long branch
with the same script, so the two agree line for line and merge cleanly. Never leave the default branch saying what the
merge made untrue.
**Because:** [PR #21](https://github.com/HogJonny-AMZN/HogNoise/pull/21) merged the GPU port's plan; the plan's status,
the board row, the map and the handoff were updated to Accepted only on `feat/gpu-port`, so `main` still said Proposed.
[PR #23](https://github.com/HogJonny-AMZN/HogNoise/pull/23)'s new handoff header then said Accepted against its own
*In flight* row, and Copilot found it. Not mechanised: which statuses a merge changes is not something a check can see.

### P-12 · Derived numbers committed before the derivation was run end to end

**Trigger:** a tool turns measurements into numbers that are committed and then judge something (a tolerance, a
threshold, a budget).
**Do:** before committing its output, run the whole chain once, on real measurements, to the end: measure, derive,
load, and check against the adapter or machine that measured. Name that run in the pull request. Unit tests of each
step are not that run.
**Because:** in the GPU port ([PR #22](https://github.com/HogJonny-AMZN/HogNoise/pull/22)) the plan's `floor3` passed
its tests and rounded a correlation of 0.9999999999999998 up to 1.0, so the trial run's rules failed the RTX 5090 that
had measured them; and after the real measurement a rule asked one bit-exact feature for a correlation of exactly 1.0,
which CI's llvmpipe failed with its output identical to the reference (`np.corrcoef` of identical arrays is not always
1.0). The first was caught by a trial run, the second by CI. Not mechanised.

### P-13 · A tool that writes a committed file, given an input that yields nothing

**Trigger:** you write or review a tool that writes into the tracked tree from inputs it reads (records, a folder, a
manifest).
**Do:** refuse an input that yields nothing, and inputs that disagree or are incomplete, before writing anything; build
every output first, then write each atomically (a temporary file and a replace). Its tests include the empty, partial
and malformed inputs, and assert the committed files are byte-identical afterwards.
**Because:** `tools/measure_gpu.py derive`, pointed at a folder with no records, overwrote the committed
`vectors/tolerance/wgpu.json` with zero rules and rewrote `portability-gpu.md` before failing on the third file. No
test covered it; the deliberate review on [PR #22](https://github.com/HogJonny-AMZN/HogNoise/pull/22) probed it. Fixed
with a check of the records against the hog set and atomic writes; P-2 covers a test that writes, this covers a tool.

### P-14 · A rule already written down, broken again: a script run from stdin

**Trigger:** you are about to run Python on a script written into the command itself: a heredoc piped to `python -`,
`uv run python -`, or any interpreter given a lone `-`.
**Do:** write the script to a file (in the scratchpad when it is not part of the repository) and run the file. Its text
is then something a reviewer can read, and nothing waits on stdin.
**Because:** HogShade's ledger has the rule as its P-5, and the agent's memory carried it; in the session that wrote
stage 3's spec ([PR #26](https://github.com/HogJonny-AMZN/HogNoise/pull/26)) a command still began with a bare
`python -`, the heredoc did not reach it, and it waited on stdin until it was stopped. It changed nothing. A rule in
a ledger and in memory had not held, so the class is mechanised: a Claude Code `PreToolUse` hook in the owner's user
settings, on the Bash and PowerShell tools, refuses the command before it runs
(`~/.claude/hooks/refuse_bare_python_stdin.py`, with a `--self-test`; proven on 2026-11-17 by sending it a bare
`python -` through each tool). Its first pattern also refused this entry's own commit, whose message said "the bare
python - rule"; it now matches an interpreter only in command position, and the self-test holds both cases. **Mechanised on the owner's machine only:** the hook is not in this repository, so
another machine, another person or another agent is not covered, and the rule above still applies to them.

### P-15 · P-2 again, by a new way to run only part: tests split across workers

**Trigger:** a change to how the suite runs (parallel workers, a new scheduler, a filter in `addopts`), or a diff in a
generated file that you are about to revert as "only its date".
**Do:** read the diff's size before reverting it: `git diff --stat` on the file, not `git checkout` on reflex. A test
that writes a committed file checks that it measured every row the file holds before it writes, rather than trusting
the environment to be whole.
**Because:** ai-first-template 0.11.0 turned on `-n auto` ([PR #35](https://github.com/HogJonny-AMZN/HogNoise/pull/35)).
pytest-xdist spread `test_kernels.py` over the workers, and `test_write_portability_table`, seeing only its own
worker's rows, replaced `vectors/portability.md` (210 table lines) with 47; its header-only assertion passed. P-2's
guard checked the environment (numba and the binding installed), and that was whole. Every gate run on the branch did
it, and each time the diff was reverted as the usual date stamp, unread; Copilot's review found it. xdist's
`--dist loadgroup` would have kept the module on one worker, but on pytest 9.2.0 and pytest-xdist 3.8.0 it did not
group even a minimal module (measured 2026-11-20). **Mechanised:** the writer now compares what it measured with every
row of the committed table; under xdist it skips with the command that regenerates the table (`-n 0`), and in one
process a missing row fails. `test_a_partial_set_of_rows_is_never_complete` holds the guard.

### P-16 · A plan's own code breaks a rule the ledger already has

**Trigger:** a plan, or its self-review, contains code for a tool that writes a committed file.
**Do:** hold that code to P-13 in the plan's self-review, before any task runs: what it does on an input that yields
nothing, a partial one and a malformed one, and whether it writes before it has built everything. A plan's code is
copied into the build, so a fault in the plan is a fault in the product.
**Because:** stage 3's plan gave the shader emitter code that wrote `manifest.json` with blank binding entries when it
could not read naga's output, which is what P-13 forbids. The plan's self-review passed it; the deliberate review on
[PR #34](https://github.com/HogJonny-AMZN/HogNoise/pull/34) caught it, and `241768c` made the emitter refuse an
incomplete binding table and write nothing. Not mechanised: a plan is prose, and no check reads its code against the
ledger.

### P-17 · A parser of a real language, tested only on the forms the repository happens to contain

**Trigger:** you write or review code that reads a language by hand (a regex or a scanner over WGSL, HLSL, TOML,
markdown) rather than through that language's own parser.
**Do:** test it against the variants the grammar allows that the repository does not use today: whitespace inside
tokens, every comment form (nested ones too where the language nests them), and a form it cannot read, which it
refuses rather than skips. Better, read the language's own tool's output when one exists.
**Because:** the emitter's binding reader handled `@binding(6)` as the WGSL was written, but not `@binding( 6 )`, which
WGSL allows, and it counted declarations inside `/* */` comments. Copilot's review on
[PR #34](https://github.com/HogJonny-AMZN/HogNoise/pull/34) found it, not ours. `f155da5` reads the attribute with
spaces, skips comments as WGSL does, refuses a binding it cannot read, and adds three tests, each seen to fail first.

### P-18 · A claim true of a module, written as if true of importing it

**Trigger:** a document says what something needs or does not need: "standard library only", "no GPU", "no numpy".
**Do:** state it of the thing a user does (`from hog_noise import shaders`), not of one file, and prove it in a fresh
interpreter with the dependency blocked, as the no-wgpu test does. A claim no test has seen fail is not yet a claim.
**Because:** "`hog_noise.shaders` needs only the standard library" held for `shaders/__init__.py`, but importing it
loads the package, which imports numpy. The claim reached five documents before Copilot's review on
[PR #34](https://github.com/HogJonny-AMZN/HogNoise/pull/34) questioned it; `f155da5` corrected the five. The claim
the spec needed (reading a shader needs no wgpu) was already held by a test. The owner's "verify the exact claim"
rule again, recorded because it spread.

### P-19 · A file written by a heredoc, against a rule already written down

**Trigger:** you are about to write or append a file from a shell heredoc (`cat > f <<EOF`, `tee f <<EOF`) or a
PowerShell here-string piped to `Set-Content` or `Out-File`.
**Do:** write it with the Write tool (or edit it with Edit), then run or commit the file.
**Because:** HogShade's ledger has the rule as its P-2, and memory carried it. Still, on 2026-11-19 the journal of
[PR #34](https://github.com/HogJonny-AMZN/HogNoise/pull/34) was appended with a heredoc (the text came out right),
and on 2026-11-20 an empty, pointless heredoc wrote a scratch script. As with P-14, a ledger line had not held, so the
class is mechanised: a Claude Code `PreToolUse` hook in the owner's user settings, on the Bash and PowerShell tools,
refuses the command before it runs (`~/.claude/hooks/refuse_heredoc_file_write.py`, with a `--self-test` of 13
refused and 11 allowed forms; proven on 2026-11-20 by a heredoc into the scratchpad, refused, nothing written). A
heredoc fed to a command (`git commit -F - <<EOF`) is not refused. **Mechanised on the owner's machine only**, as P-14.

### P-20 · A green local gate, when a release changes how pytest runs

**Trigger:** a template release, or your own change, edits pytest's configuration (`addopts`, a plugin, a marker) or
the test dependencies.
**Do:** list every workflow that runs pytest and how each installs its tools (`grep -n pytest .github/workflows/*`),
and check each gets what the new configuration needs. `make check` proves only the environment `make` builds.
**Because:** ai-first-template 0.11.0 put `-n auto` in the root's `addopts` and `pytest-xdist` in the root's `dev`
group, which `make check` installs. `tests.yml` installs the library's extras with pip, so on the first push of
[PR #35](https://github.com/HogJonny-AMZN/HogNoise/pull/35) all six of its legs stopped on
`unrecognized arguments: -n` while the local gate was green. `e26a833` puts `pytest-xdist` in the `test` extra. The
template's guide now says it too ([ai-first-template PR #248](https://github.com/HogJonny-AMZN/ai-first-template/pull/248)).
Not mechanised here beyond CI itself, which caught it.

### P-21 · A number from one run, written as if it held for every run

**Trigger:** you write a figure or a "every", "all", "none" from measurements taken on more than one adapter, back end,
host or run.
**Do:** name the run a number came from beside it ("the 5090 on Vulkan"), say what a pooled figure pools, and check
every general claim against every result file with a script before the text is committed. Reading one file and
remembering the others is not the check.
**Because:** the far-coordinate probe of [PR #41](https://github.com/HogJonny-AMZN/HogNoise/pull/41) ran on three
adapters, and its write-up was drafted from the Vulkan results. A script over all three files caught two claims that
held on Vulkan alone ("all 18 warps fail past 4,096"; "every discrete rule passes"), both fixed before the commit.
Copilot's review then caught two more of the same class the script had not been asked about: a pooled "1 to 10 in a
million" that did not say what it pooled, and in-range counts that were the Vulkan run's, unlabelled. `35b77c5` made
the finding a table per adapter. P-10 asks that a count come from a command; this asks that it also say which run it
counts. Not mechanised: the check is a script per write-up, kept with the evidence.

### P-22 · A leg that proves something exists, named as if it proved the one thing it is for

**Trigger:** you add a CI leg, a test or a probe named for one specific thing (a back end, an adapter, a language, a
shipped file), and its pass condition is that *something* ran.
**Do:** assert the specific thing itself (the back end the device reports, the hash of the file loaded), and see the
assertion fail once on the wrong thing before trusting its pass.
**Because:** [PR #42](https://github.com/HogJonny-AMZN/HogNoise/pull/42)'s "wgpu on Metal" leg required an adapter,
not Metal: `gpu._pick_adapter` takes wgpu's own choice, so a runner image that changed it would have stayed green on
another back end. Copilot's review caught it, and the WARP and llvmpipe legs had the same gap. `a1c355f` pins each
GPU leg's back end with `WGPU_BACKEND_TYPE` and asserts it in the Adapter step; pinned to OpenGL and expecting D3D12,
the check exited 1 locally. Mechanised for the GPU legs by that assertion; the
[CI proof's spec](../superpowers/specs/2026-11-22-emitted-shaders-ci-proof.md) applies it to each host harness, which
checks the loaded file's hash against the manifest.

### P-23 · A plan's code trial-run all at once, when its tasks run one at a time

**Trigger:** you trial-run a plan's code before proposing it (P-12, P-16), and the plan writes that code across several
tasks.
**Do:** run the trial in the plan's order: write only the files a task has written so far, run that task's own
commands, then add the next task's files. A command a task runs is tested against the tree that task sees, not the
finished one.
**Because:** the CI proof's plan ([PR #48](https://github.com/HogJonny-AMZN/HogNoise/pull/48)) was trial-run with
every module written at once, and 36 tests passed. Its Task 4 ran `-k spirv`, which also selects a `glsl`
parametrisation whose fixture imports `glsl.py`, a file Task 5 writes; at Task 4 that command errors. Copilot's review
caught it, and it was reproduced by removing `glsl.py` from the trial copy (7 passed, 1 error) before `3a95f49` fixed
the selection. Not mechanised: the trial is a script that extracts a plan's code, and it could take a task number;
worth doing when a plan's trial is next run.

### P-24 · The repository's state, said from memory

**Trigger:** you are about to tell the owner what is next, what a row or document says, or how an earlier pull request
did something, and you have not read it in this session.
**Do:** read it first: the handoff's order and the board rows for what is next, the file on `origin/main` for what a
document says. Quote what you read, or link it.
**Because:** after [PR #50](https://github.com/HogJonny-AMZN/HogNoise/pull/50) merged, the agent told the owner the HLSL
pull request was next. The handoff's agreed order put the warp rules and the fresh-sample bounds first, and both were
queued. The owner's "word" answered the wrong framing, and [the HLSL plan](../superpowers/plans/2026-11-23-the-emitted-hlsl-on-warp.md)
was written out of order ([PR #51](https://github.com/HogJonny-AMZN/HogNoise/pull/51) says so). The same plan said (a)'s
board row "stayed in next" when it landed. Main had it in `now`, and Copilot's review caught it. Not mechanised: it is
a habit, and the handoff's *Last updated* is where the order is read.

### P-25 · A plan's trial that stops before its documents' tasks

**Trigger:** you trial-run a plan (P-23), and its later tasks edit the board, the handoff or other governed documents.
**Do:** run those tasks too, as far as a scratch copy allows: make the board and document edits they describe, and run
`check_docs` on them. A step `check_docs` refuses is a plan bug, found before the owner reads it.
**Because:** [the HLSL plan](../superpowers/plans/2026-11-23-the-emitted-hlsl-on-warp.md)'s trial ran Tasks 1 to 6 and
stopped. Task 7 kept the landed row in `next` (`board-state` refuses that) and left three rows waiting on a done row
(`waits-on` refuses that). Copilot's review on [PR #51](https://github.com/HogJonny-AMZN/HogNoise/pull/51) found both,
from `check_docs.py`. `94f1e3c` fixed the plan's steps. Not mechanised: the trial's applier applies only code blocks; a
documents task describes its edits in prose.

### P-26 · A constant declared for a guard and never applied

**Trigger:** code you write or review declares a limit, a timeout or a retry count as a module constant.
**Do:** find the line that applies it, and a test that fails when that line is removed. A guard nothing applies is the
absence of the guard, with a comment claiming it.
**Because:** [the HLSL plan](../superpowers/plans/2026-11-23-the-emitted-hlsl-on-warp.md)'s `hlsl.py` declared `TIMEOUT
= 600`, "the harness may take over one reply", and no line used it. A harness that stopped replying would have hung
`conformance.check` and the gate with no message. ruff does not flag an unused module constant. Copilot's review on
[PR #51](https://github.com/HogJonny-AMZN/HogNoise/pull/51) found it. `94f1e3c` applies it through a watchdog, and a test
uses a stand-in that never replies; with the watchdog removed, that test failed. Not mechanised: an unused-constant
check would also flag the public constants other modules read.

### P-27 · A fact a change makes untrue, searched for in one phrasing and one folder

**Trigger:** a change makes something the documents state untrue (a rule's kind, a default, a limit, a name), and you
search for the text to update.
**Do:** search for the concept, not one phrasing of it: its several wordings, each on its own, across every documents
folder (`Docs/` whole, including `superpowers/specs/`, `design/` and the glossary, and each README). Update what states
the present; leave plans and landed rows, which record what was true when they were written, and amend a spec or a
design with a dated note rather than rewriting it.
**Because:** [PR #53](https://github.com/HogJonny-AMZN/HogNoise/pull/53) made the warp outputs' rules coordinate-scaled.
Its search left out `Docs/superpowers/specs/` and matched "absolute" only next to "warp" on one line, so the glossary's
*Tolerance file* row and the GPU port spec still said the warp rules were absolute. Copilot's review found both; the
wider search in `768e00d` also found the GPU fast-track account's line 52. Not mechanised: which sentences state a fact
is a reading, not a pattern.

### P-28 · A bound taken from one sample's worst, trusted without a second sample

**Trigger:** you derive a bound, a tolerance or a limit from the worst value a sample showed, and are about to claim it
holds beyond that sample.
**Do:** before trusting it, draw a second, independent sample (another seed, drawn the way the claim covers, including
where the bound is tightest) and check that the first sample's worst holds there. If the worst moves between samples, the
tail is heavy: state a rate (a fraction within a bound) under a fixed ceiling, not a worst.
**Because:** [the fresh-sample bounds' plan](../superpowers/plans/2026-11-24-gpu-bounds-from-a-fresh-sample.md)'s first
design took each continuous rule's outer bound from twice the worst of 65,536 fresh points. Its trial derived cleanly and
every hog case passed, and the far probe's own 65,536 points then failed the bounds at up to 4.5 times. The uniform draw
had almost never reached the origin, where the bound is tightest; and the GPU's rare spikes, whose worst over 65,536 points
varied 56 times between samples, bound nothing. The trial caught it before anything was committed, and the owner took
the rate-based form ([PR #56](https://github.com/HogJonny-AMZN/HogNoise/pull/56)). Mechanised for the GPU rules: the far
probe, with its own seed and points, is the acceptance check of every re-derivation (the plan's Task 7).

## How to add an entry

When the process fails, append the entry in the same pull request as the fix. Mechanise the class when a check can, and
name the check in the entry. If any repository would repeat the failure, propose the entry to the template instead.
