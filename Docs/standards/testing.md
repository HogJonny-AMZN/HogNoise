# Testing standards

**Status:** Living. Managed by the template (the `python-uv` module): a repository's copy must match, so do not edit it
here; propose a change to the template.
**Read with:** [python.md](python.md) · [definition-of-done.md](definition-of-done.md) · [failure-modes.md](failure-modes.md)

**This project's additions** go in `testing-project.md` beside this file, when it has any: an extension adds rules and
never weakens these. To relax or contradict a rule here, override this file in `framework.toml` with a reason that names
the rule.

How tests are invoked, where they live, and the conventions that are load-bearing rather than stylistic.

## Invocation: the `pytest` console script, never `python -m pytest`

```bash
uv run pytest                          # the whole suite
uv run pytest tests/test_x.py -v       # one file
uv run pytest tests/test_x.py::test_y  # one test
uv run pytest -k "parse and not slow"
```

**`python -m pytest` puts the working directory on `sys.path`. The console script does not, and the console script is what CI
runs.** So a root-relative import passes locally and fails on CI, and an import failure at collection takes down the whole
suite, not one file. Run the console script once before pushing anything that imports outside the installed packages.

### Importing a script from `tools/`

`tools/` holds scripts, not an installed package. A test puts `tools/` on `sys.path` from the test file itself, then imports
the script by its bare name:

```python
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import check_docs  # noqa: E402
```

Never `import tools.check_docs`: it resolves only where the working directory makes `tools` an implicit namespace package. The
path insert lives in the test file, not in `conftest.py`, because a conftest runs only under pytest and a module's own
mini-test is run directly.

## Layout

`tests/` mirrors the source tree: `tests/test_<module>.py` for a module, a subdirectory for a package. `tests/` has no
`__init__.py`, and a helper shared by tests goes in a sibling module, not imported through a dotted path from `tests`.

## Conventions that are load-bearing

**Test first.** Write the test, watch it fail for the right reason, then write the code. A test never seen failing has not
shown it can.

**Prove the instrument before trusting a negative.** A probe, grep or mutation that returns "nothing" is not evidence until
the same instrument has produced the other answer: run the unmutated control, print a marker, reintroduce the bug and watch
the test fail. A mutation that kills nothing is usually a dead mutation, not a degenerate test.

**Assert the value, not the shape.** `assert isfinite(out)` passes on zeros. Where a guard has branches, each branch gets its
own value assertion, and swapping the branches must fail the suite.

**Count, do not only check a value.** A value assertion cannot see a duplicate emission, an echo write or a feedback loop.
Count the signals.

**Visit the singular point.** A function with a point where its arithmetic breaks (a division by a length, a normalisation,
the origin) gets that point in its test coordinates by name. Scattered or random coordinates never land there.

**Skip with a reason, never silently.** A test that needs hardware, a service or a large payload skips with a reason when it
is absent; a test that depends on an optional extra says so. A skip is never a way to get green.

**Do not pin a hash of computed floats.** Recompute the value by the formula in the test, with a tolerance across machines.

**The boundary test.** `tests/test_boundaries.py` holds the repository's own `src/` to the `[layers]` table of
`framework.toml` (see *Layers* in [python.md](python.md)), and proves the check can fail by breaking the rule in a copy of
`src/` and requiring the finding. It runs with the rest of the tests. Run the tool alone, with the line of every
finding, by `uv run python tools/boundaries.py`.

## Error paths: three outcomes, never two

**An external call has three outcomes, an error, an absent answer and a present one, and code that merges any two of them has a
bug that only the error path shows.** Each item below is a case a test names; write the test before the code that handles it.

- **Every nonzero exit** of a subprocess is an error, whatever it printed; an exit zero with no answer is its own outcome.
- **A lookup that fails** (a timeout, a server error, access denied) is never "nothing was found"; only a confirmed absence is.
- **An unreadable thing is not a missing one**: a file it cannot open, a directory it cannot list, a path through a cycle.
- **A malformed or partial result is an error**, not a smaller result: a truncated stream, a record that is not an object, an
  inventory that is not a list.
- **A timeout holds with child processes**: the limit applies to the process group, not the first process.
- **Symlinks**: cyclic, dangling, to identical content, and a path through a linked directory.
- **A path leaves the root** (`..`, a drive letter, a device name, an absolute path) and is refused before use.
- **A check, then a use**: a file created between them is not replaced; create without replace, or open exclusively.
- **A guard's negative control**: the test breaks the thing the guard guards, and requires the finding (framework ledger 12).

The first version of a tool passes the cases its author thought of; this list is the cases that review has found after that, in
pull requests 17 to 46 of the template.

## Gates

**The docs gate.** The docs check runs as a stage of the gate; what it catches, and why each check exists, is the table in
[definition-of-done.md](definition-of-done.md).

**CI runs the gate.** The workflow runs the stages of `tools/check.py` in the same order as `make check`, on every leg the
project needs; a test asserts the two agree.

What "done" means for a pull request is in [definition-of-done.md](definition-of-done.md).
