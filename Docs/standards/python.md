# Python coding standards

**Status:** Living. Managed by the template (the `python-uv` module): a repository's copy must match, so do not edit it
here; propose a change to the template. The rules are the core all three source repositories agree on; anything about a
particular domain (a GUI toolkit, a GPU, a game loop, a DCC) belongs in this file's extension, not here.
**Read with:** [testing.md](testing.md) · [definition-of-done.md](definition-of-done.md) · [failure-modes.md](failure-modes.md)

**This project's additions** go in `python-project.md` beside this file, when it has any: an extension adds rules and
never weakens these. To relax or contradict a rule here, override this file in `framework.toml` with a reason that names
the rule.

`ruff` is the linter and formatter (`pyproject.toml`: 120 columns, a `py311` target; 3.11 is the floor the code supports,
not a recommendation to stay there). CI runs `ruff check` and `ruff format --check`. The 120 columns are enforced, not
only formatted: `E501` is on, so a long string or a long docstring line fails the check too, because the formatter never
wraps those. Dependencies are managed with `uv`; run everything with `uv run`.

## Module header

Every module starts with a docstring naming the project and the package path, then the metadata, then the logger.

```python
"""
<Project>: one line saying what the module is for.
Package: <dotted/path/of/the/package>

More detail if the one line is not enough: what it reads, what it writes, what it must not import.
"""

from __future__ import annotations

import logging as _logging
from pathlib import Path

_MODULE_NAME = "package.module"  # matches the Package line, with dots
__version__ = "0.1.0"
__updated__ = "2026-01-01"
_LOGGER = _logging.getLogger(_MODULE_NAME)
```

- `from __future__ import annotations` in every module, with `X | None` and `list[...]` in signatures; never
  `typing.Optional`, `List` or `Dict`.
- `_LOGGER` from `_MODULE_NAME`, never `__name__`. A module that never logs still declares it (the convention is uniform),
  but `logging.basicConfig` belongs only in a script's `main`, and only when something logs.
- `__version__` before `__updated__`; no `__author__` field.

## Imports

Absolute only, no wildcards; standard library, third-party, project, alphabetical within each group. ruff's isort enforces
the order.

## Types, docstrings, paths

- Complete type hints on every signature. Where numpy is used, arrays carry their dtype (`NDArray[np.float32]`), never a bare
  `NDArray` when the dtype matters to the caller.
- Docstrings say what a function is for and what it returns; reST fields (`:param:`, `:return:`, `:raises:`) where a
  signature is not self-explanatory. A one-line docstring is fine for a helper.
- `pathlib.Path` for every path. `str()` only at the boundary of an API that needs it, through one helper when the consumer
  is fussy. `os.environ` reads stay `os.environ`; wrap the result in `Path` at once.

## Data and config files

The test for a format is that a person can read and edit it, an agent can read and write it, and the Python standard library
handles it with no dependency.

- **JSON for anything code writes:** records, manifests, sidecars, caches, results. `json` reads and writes it. Write it
  with `indent=2`, a stable key order and a trailing newline, so a diff shows only what changed.
- **JSON Lines for logs and event streams:** one object per line, appended, so a merge is a union of lines.
- **TOML for configuration a person edits and code only reads.** `tomllib` reads it; the standard library cannot write it.
  If code has to change a value, that value belongs in JSON, not in a TOML writer. The one exception is generating a
  person's starting configuration once: `init adopt` writes `framework.toml` through `framework_config`'s own small writer
  (`init new` copies a seed). After that the file is the person's, and no code rewrites a value in it.
- **No YAML.** Reading it needs a third-party package, and its implicit typing surprises people (`no` reads as false,
  `3.10` as 3.1). The only YAML is what an outside tool requires and owns, such as `.github/workflows/*.yml` and
  `.github/dependabot.yml`, and it stays limited to that.

## Errors and logging

- Catch specific exceptions; never a bare `except:`. A broad catch is allowed only where the point of the code is to log
  whatever a foreign system throws and keep going, and the comment says so.
- Validate at the boundary of a layer, raise with context (what was being done, to which input), and re-raise across a layer
  boundary rather than returning an error code.
- A call to the outside world has three outcomes (an error, an absent answer, a present one); see *Error paths* in
  [testing.md](testing.md).
- **f-strings in log calls**, because a message that reads as it will print is one a person can troubleshoot:
  `_LOGGER.info(f"wrote {path.name}: {n} rows")`. The exception is a measured hot path, and even
  there the fix is structural: a tight loop does not log; collect, then log once after it, marked on the call's first line
  with `# lazy-log: <the measurement>`. The log-format check (`tools/check_log_format.py`) fails a lazy `%`-format log call
  without the marker.
- Two-part messages, context then detail: `f"Failed to decode {path}: {e}"`. No emoji or non-ASCII in log text: a log
  is read in consoles and tools whose encoding you do not control, and a character that raises there hides the failure.
- `print()` only for a script's final summary in its own entry point (`main`) and in demo entry points. Library code logs.

### What a log is for

A log is the record of a run that a person reads afterwards and an agent searches when the run failed and nobody watched it.
A declared logger that never logs satisfies the header rule and nothing else. So every unit of work logs:

- **What it is about to do, with its inputs named**, at `INFO`.
- **What it produced and where**, at `INFO`: every artifact written with its path, every file replaced, with sizes or counts.
- **Anything it decided on the caller's behalf**: a default taken, a migration applied, a fallback, an item skipped. `INFO`
  when the result is still what was asked for, `WARNING` when it is not.
- **Per-item detail** at `DEBUG`: off by default, there when a failure needs it.
- Failures with the context first: what was being done, to which input, then the exception.

Entry points configure logging once, to stderr, with a timestamp, the level and the module; library modules never configure
it.

## Structure

- A tool's logic lives in a function the tests can call; `main(argv)` parses and dispatches.
- No mutable default arguments; no module-level mutable state (constants are fine).
- No logging in a tight loop.
- Where a smoke run makes sense, a module keeps an `if __name__ == "__main__":` block; they are a development workflow, not
  dead code, and are not removed during refactoring.

## Layers

`src/` holds the product's packages, and `framework.toml` says how they stack:

```toml
[layers]
order = ["core", "app"]   # lowest layer first
pure = ["core"]           # imports the standard library and itself, nothing else
unlayered = []            # packages deliberately outside the order
```

A layer may import itself and the layers before it in `order`, never one after: `core` importing `app` is a bug the day
it is written. A pure layer imports only the standard library and itself, so it stays usable with no install. A package
of `src/` that is in neither `order` nor `unlayered` is a finding, and so is a name in `order` with no package, so the
table cannot drift from the code. Modules of one package may not import each other in a ring. `src/` may not import
`tools` or `tests`.

The rule is held by `tests/test_boundaries.py` through `tools/boundaries.py`, which reads the source with `ast` and never
imports it. Adding a package is two edits: its folder in `src/`, and its place in `order`. A repository with packages in
`src/` and no `[layers]` table fails the test; the decision is the project's, and leaving the table out is not a way
round it. A late or `TYPE_CHECKING` import counts like any other: a layer rule that ignores them is not a rule.

## Tests

`tests/` mirrors the code. See [testing.md](testing.md). Test files keep the docstring header (the project and the package
path) but need not carry the metadata block.

## Hygiene

Before every push the gate is clean (`make check`). Commit identity is the rule in
[definition-of-done.md](definition-of-done.md). Nothing copied from a tree you do not own; dependencies whose licences the
project can accept. The project's own list of identifiers that must not appear in any file is the hygiene check in the
[definition of done](definition-of-done.md#the-hygiene-check), which is the standard for it.
