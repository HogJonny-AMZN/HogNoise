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

## How to add an entry

When the process fails, append the entry in the same pull request as the fix. Mechanise the class when a check can, and
name the check in the entry. If any repository would repeat the failure, propose the entry to the template instead.
