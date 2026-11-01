# Failure modes

**Status:** Living

How the work has gone wrong, as triggers: when you notice X, do Y. Each has the evidence that proves it. When process
fails again, append the entry in the same change, and mechanise the class when a check can.

## 1. A test names the best rung it expects

**Trigger:** a test asserts which rung, backend or value is "the best" and the answer depends on what is installed.

**Do:** compute the expectation from availability (`HAVE_NUMBA`, `_have_fastnoiselite()`), and run the numpy-only leg.

**Evidence:** the stage 2 numpy-only run failed `test_ladder_picks_the_best_available_and_override_is_honoured`: it
assumed `pyfastnoiselite` was installed. It passed for months on a machine that had it. CI now has a numpy-only leg.

## 2. A test rewrites a committed file from whatever it measured

**Trigger:** a test or tool writes into the tracked tree.

**Do:** run it in the smallest environment and read `git status` afterwards. Write only when the run measured everything
the file claims to describe.

**Evidence:** `test_write_portability_table` replaced `tests/vectors/noise/portability.md` (211 lines) with a partial
table (145 lines) after a numpy-only run, in the working tree, ready to be committed by accident. It now skips unless
numba and the binding were both compared.

## 3. Publishing something that began private

**Trigger:** you are about to make a repository public that was cut from a private one.

**Do:** sweep the tree and every commit, not only the tip, for names of secrets, private projects, and personal or
employer identities, in file contents and in commit metadata. Decide filtered or fresh history with the findings in
front of you, and do not copy package metadata (authors, emails, URLs) from the source without reading it.

**Evidence:** the stage 3 sweep found no credential values, but did find a CI secret's name in two commits and identity
strings in commit metadata, and the source project's `pyproject.toml` carried an address that must not ship.
