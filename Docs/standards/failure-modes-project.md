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

## How to add an entry

When the process fails, append the entry in the same pull request as the fix. Mechanise the class when a check can, and
name the check in the entry. If any repository would repeat the failure, propose the entry to the template instead.
