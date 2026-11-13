# Python coding standards

**Status:** Living. Managed by the template (the `python-uv` module): a repository's copy must match, so do not edit it
here; propose a change to the template. The rules are the core all three source repositories agree on, except *The
tool-root pattern*, which comes from one repository's production use and is marked so; anything about a particular
domain (a GUI toolkit, a GPU, a game loop, a DCC) belongs in this file's extension, not here.
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

_MODULE_NAME = "package.module"  # the import path; under the tool-root logger if the App takes the pattern
__version__ = "0.1.0"
__updated__ = "2026-01-01"
_LOGGER = _logging.getLogger(_MODULE_NAME)
```

- `from __future__ import annotations` in every module, with `X | None` and `list[...]` in signatures; never
  `typing.Optional`, `List` or `Dict`.
- `Package:` and `_MODULE_NAME` are the module's import path (`acme_tools.store`), not its folder: in a workspace member
  the folder starts `apps/` or `packages/`, and the import path starts with the member's package.
- `_LOGGER` from `_MODULE_NAME`, never `__name__`. A module that never logs still declares it (the convention is uniform).
  In an App that takes *The tool-root pattern* (below), a module with user-facing output also declares `_TOOL_LOGGER`,
  the same instance under a second name. Neither configures a handler. Logging is configured only from an entry point's
  `main()`: through `tools/log_setup.py` in the template's tools, through `configure_logging()` in an App that takes
  the pattern.
- `__version__` before `__updated__`. `__author__` (the people on the roster who wrote the module) may follow them; it is
  optional, and git history stays the record of who changed what.

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
- **JSON Lines for a log or event stream that code reads back or several writers append to:** one object per line,
  appended, so a merge is a union of lines. Two other kinds of log are plain text. Logging to stderr uses the format
  *Errors and logging* gives (timestamp, level, module). A run record, a file beside what one run wrote that a person
  reads afterwards, is a plain report: what the run was given, then what it did, one line each, with no per-line
  prefix (`init`'s `logs/init-<timestamp>.log`).
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

### The tool-root pattern

From one repository's production use, not the three-repository core: most Apps never need it.

1. **One `_LOGGER` per module is the rule**, from `_MODULE_NAME`, for every module, as the header says.
2. **When an App takes the pattern.** An App with a second audience for its logs (a log console shown to users) or an
   embedding host whose root logger it does not own (a DCC application) takes the tool-root pattern. It says so in its
   design or spec, with the reason. No key in `framework.toml` declares it and no check reads it.
3. **The tool-root logger** is `_TOOL_ROOT_LOGGER`, named for the App's top-level import package (`your_project_name`).
   - It lives only in the App's entry point module, beside `configure_logging()`.
   - Because `_MODULE_NAME` is the import path, every module of the App is under it with no second naming rule.
   - `_TOOL_LOGGER` is the same logger as `_LOGGER` under a second name, for a module that writes to users; which name a
     call site uses documents intent only. The names are kept from the pattern's first version.
   - *App root* stays the word for the folder `apps/<app>/`.
4. **`configure_logging()`** is called from `main()`, never at import, and a GUI's base window calls the same function.
   Within one launch, a repeat call returns the same log file and leaves one set of handlers. The reference is
   [examples/tool_root_logging.py](examples/tool_root_logging.py), beside this file: copy it and change its constants.
5. **What it configures:**
   - **the tool-root logger**, with `propagate=False`, at `DEBUG`;
   - **a console handler** at `INFO` (`DEBUG` with `-v`), one line per record: a traceback goes to the file only, and
     a line break in a message shows as its escape (`\n`), while the file gets the message as written;
   - **a file handler** at `DEBUG`, writing this launch's log file. A *launch* is one start of the App; its file is
     named for the launch's UTC time. The App's own launch files (`<stamp>.log`) are pruned to the newest 15, as best
     effort: a file another instance holds open, or an entry that is not a file, stays and is a warning. Windows
     refuses to delete an open file; Linux and macOS do not, so there each launch holds a shared lock on the files it
     writes, and pruning keeps a file it cannot lock (a file system without locks is a warning, not a failed start).
     Only a holder that takes the lock is protected there: an instance of an older copy of the App, or another
     program with the file open (a `tail -f`, an editor), takes none, so bring every copy level before relying on
     it. A file another instance pruned between its opening and its lock is opened again. Any other `*.log` in the
     folder is never touched. The folder is `%LOCALAPPDATA%\<app>\logs` (Windows),
     `~/Library/Logs/<app>` (macOS), or `$XDG_STATE_HOME/<app>/logs`, else `~/.local/state/<app>/logs` (Linux). A
     variable that is unset, empty or relative is not used;
   - **each shared library's root**, configured once per process, by the first App to configure it. It writes its own
     files (`<library>-<stamp>.log`, also pruned to 15, counted apart from the App's), and shows on the console at
     `WARNING` and above.
6. **The line format**, exactly `"%(asctime)s [%(levelname)s][%(name)s] >> %(message)s ::(%(filename)s:%(lineno)d)"`.
7. **The third-party cap.** Exactly one App in a process passes `owns_process=True`: the one that started it.
   - **It caps:** each listed namespace the project does not own is set to `WARNING`. Python's root logger gets a
     console handler at `WARNING`, so a capped vendor warning is formatted. Its marker is the same in every App, so a
     second App that also claims the process replaces it rather than doubling it.
   - **`<PROJECT>_LOG_THIRDPARTY_DEBUG=1` lifts it:** each listed vendor namespace goes to `DEBUG` with a handler writing
     this launch's file. The file then holds whatever the SDK logs at `DEBUG`, request bodies and any credentials in
     them included, for as long as the file is kept. Vendor `INFO` stays off the console, and a namespace that is not
     listed is not captured.
   - **Any other value** logs a warning, with the value shown as ASCII.
   - **Inside a host** (`owns_process=False`) the App sets no level and keeps no handler on a namespace it does not own.
     It removes only its own handlers, by its own marker, never another App's: the owner's console handler on Python's
     root stays. A cap it set in an earlier call is undone, back to the level the vendor had before the first cap,
     unless the host has changed that level since; either way the App no longer claims the cap, so a later call never
     takes the host's own level for it. A set variable is a warning: the cap applies only when the App owns
     the process.
   - A vendor's child logger that sets its own level is outside the cap.
8. **Where a record outside the tool-root logger goes** depends on the handlers of its own namespace and of Python's
   root: a shared library's file, a host's handlers, or the root's console handler. Where none accepts it, `INFO` and
   `DEBUG` are dropped, and `WARNING` and above reach Python's last-resort handler unformatted.
9. **The logging self-check**: `configure_logging()` logs once, at `DEBUG`, the level, the `propagate` flag and the
   handlers of Python's root, the tool-root logger and each shared library's root.

### What a log is for

A log is the record of a run that a person reads afterwards and an agent searches when the run failed and nobody watched it.
A declared logger that never logs satisfies the header rule and nothing else. So every unit of work logs:

- **What it is about to do, with its inputs named**, at `INFO`.
- **What it produced and where**, at `INFO`: every artifact written with its path, every file replaced, with sizes or counts.
- **Anything it decided on the caller's behalf**: a default taken, a migration applied, a fallback, an item skipped. `INFO`
  when the result is still what was asked for, `WARNING` when it is not.
- **Per-item detail** at `DEBUG`: off by default, there when a failure needs it.
- Failures with the context first: what was being done, to which input, then the exception.

Entry points configure logging once, from `main()`, with a timestamp, the level and the module: the template's tools
through `tools/log_setup.py`, an App that takes the tool-root pattern through its `configure_logging()`. Library modules
never configure it.

## Structure

- A tool's logic lives in a function the tests can call; `main(argv)` parses and dispatches.
- No mutable default arguments; no module-level mutable state (constants are fine).
- No logging in a tight loop.
- Where a smoke run makes sense, a module keeps an `if __name__ == "__main__":` block; they are a development workflow, not
  dead code, and are not removed during refactoring.

## Layers

The product's code lives in workspace members, each with its own `src/` ([layout.md](layout.md): the tree, the names,
the rules between members). `framework.toml` says how their import packages stack:

```toml
[layers]
order = ["acme_tools_core", "acme_tools"]   # lowest layer first
pure = ["acme_tools_core"]                  # imports the standard library and itself, nothing else
unlayered = []                              # packages deliberately outside the order
```

A layer may import itself and the layers before it in `order`, never one after: the core importing the app is a bug the
day it is written. A pure layer imports only the standard library and itself, so it stays usable with no install. A
package of a member's `src/` that is in neither `order` nor `unlayered` is a finding, and so is a name in `order` that no
member has, so the table cannot drift from the code. Modules of one package may not import each other in a ring. A
member may not import `tools` or `tests`.

The rule is held by `tests/test_boundaries.py` through `tools/boundaries.py`, which reads the source with `ast` and never
imports it, together with the rules between members (`app-import`, `app-to-app`, `experiment-import`, `undeclared`,
`duplicate`, `unreached`, `legacy-src`). Adding a package is its member's folder, its manifest, the root manifest's members list where a glob does
not reach it, and its place in `order`. A workspace with packages and no `[layers]` table fails the test; the decision is
the project's, and leaving the table out is not a way round it. A late or `TYPE_CHECKING` import counts like any other: a
layer rule that ignores them is not a rule.

## Tests

Each member's `tests/` mirrors its `src/`, and the framework's `tests/` holds the tests of `tools/` ([layout.md](layout.md),
*Tests across members*). See [testing.md](testing.md). Test files keep the docstring header (the project and the package
path) but need not carry the metadata block.

## Hygiene

Before every push the gate is clean (`make check`). Commit identity is the rule in
[definition-of-done.md](definition-of-done.md). Nothing copied from a tree you do not own; dependencies whose licences the
project can accept. The project's own list of identifiers that must not appear in any file is the hygiene check in the
[definition of done](definition-of-done.md#the-hygiene-check), which is the standard for it.
