# Tooling: the layers, the stages and the hooks

**Status:** Living. Managed by the template: a repository's copy must match, so do not edit it here; propose a change to the
template. It says where logic lives, what `make check` runs, and what the git hooks enforce.

**This project's additions** go in `tooling-project.md` beside this file, when it has any: an extension adds rules and
never weakens these. To relax or contradict a rule here, override this file in `framework.toml` with a reason that names
the rule.

## The layers, and the one hard rule

| Layer | Holds | Rule |
| --- | --- | --- |
| `tools/*.py` | All logic and all composition: the checks, the check runner, the hook installer | Cross-platform by construction; tested |
| `Makefile` | Dispatch only | **Every recipe is a single `uv` invocation** |
| `.githooks/*` | The git hooks | One `exec uv run python tools/...` line each |

The rule exists because logic in a Makefile has to be written a second time for a machine without make (a wrapper script
"Make-free equivalent of `make install`" is the failure it came from), and a launcher that parses its own arguments has to
be written again in another shell. Keep the Makefile a dispatcher and losing make costs typing, nothing more:

```text
make check    ==    uv run python tools/check.py
```

No conditionals, no loops, no operating-system branching, no `&&`, no pipe (a pipe can swallow a failure, and a gate whose
failure a pipe swallowed passes). `tests/test_tooling.py` parses the Makefile and fails on a recipe that is more than one
`uv` command, on a target missing from `.PHONY` or from `make help`, and on a feature GNU Make 3.81 (the build commonly
found on Windows and macOS) lacks. A project adds its own targets to the Makefile, under the same rule.

## The check runner and its stages

`tools/check.py` runs every check CI runs, in CI's order, and is also the oracle the CI parity test reads
([ci.md](ci.md)). A stage runs only while its module is `on` in `framework.toml`. Every stage runs even after one fails, so
that one run shows every failure; the summary names the stages that failed. The exit code is 0 when every stage passed, 1
when one failed and 2 when the arguments or the configuration are unusable (a run with no stage to run is unusable, never a
pass).

| Stage | Command | Module | Fast | A failure means |
| --- | --- | --- | --- | --- |
| `lint` | `uv run ruff check .` | core | yes | The Python standard is broken |
| `format` | `uv run ruff format --check .` | core | yes | A file is not formatted; fix with `make format` |
| `docs` | `uv run python tools/check_docs.py` | core | yes | Documentation has drifted ([definition-of-done.md](definition-of-done.md) lists each check) |
| `hygiene` | `uv run python tools/check_hygiene.py` | hygiene | yes | An identifier on the project's list is in a tracked file |
| `log-format` | `uv run python tools/check_log_format.py` | python-uv | yes | A log call is not an f-string |
| `graph` | `uv run python tools/render_framework_graph.py --check` | graph | yes | The framework graph is malformed or its page is stale |
| `adapters` | `uv run python tools/sync_adapters.py --check` | harness-adapters | yes | An adapter or skills mirror is not the generated one, an enabled harness has no passing probe, or a managed document names a harness |
| `sync` | `uv run python tools/framework_sync.py --check` | core | yes | A managed file differs from the lock without an override in `framework.toml`, or is missing, or the lock cannot be read |
| `tests` | `uv run pytest -q` | python-uv | no | Behaviour is broken |

The `sync` stage needs `framework.lock`: a repository without one fails it with a `corpus` finding, so the pre-commit hook
refuses commits in a repository that is mid-adoption until the lock exists (`init adopt --apply` writes it). It holds a
repository to its own record; it cannot notice that someone edited a file and regenerated the lock too, and the CI
workflow is the project's own file. Whether the record is the template's is `--upstream`'s question.

A repository that predates the template is brought under it by `init adopt`, not `init new`: [adopting.md](adopting.md).

`uv run python tools/framework_sync.py --upstream` is the other half, and is **not** a stage: it needs the network and `gh`.
It reads the latest `vX.Y.Z` tag of the repository named by `[framework] upstream` in `framework.toml`, and if the lock is
behind it lists the managed files that would change, appear or go, by running the tag's own `init` read-only, in a child
process with a scrubbed environment (**it executes code from the release**: the trust is whoever can push a `vX.Y.Z` tag
to the upstream, and the child is isolated but not a sandbox). The window counts from the day of a published GitHub Release
for the tag when there is one, else from the tagged commit's date, and the report says which. It exits 0
when current or behind for no more than `max_age_days` (default 14, counted from the tag's date), 1 when behind for longer,
and 2 when it could not tell (no `gh`, no tag, no upstream, a download that is not a payload). Run it by hand or from a
scheduled review; it writes nothing.

A test compares this table with the stages the runner has, in both directions and in order: a stage that runs and is not
listed, or listed and not run, fails it.

```text
uv run python tools/check.py            # every stage
uv run python tools/check.py --fast     # the fast stages: what the pre-commit hook runs
uv run python tools/check.py --only docs tests
uv run python tools/check.py --list     # names and commands, runs nothing
```

To add a stage: add it to `ALL_STAGES` in `tools/check.py` with its module, add the step to
`.github/workflows/ci.yml`, and add the row above. The parity test and the table test fail until all three agree.

## The layer rules

`framework.toml` `[layers]` names the packages of `src/` from the lowest layer to the highest, which of them are pure, and
which are deliberately outside the order. `tools/boundaries.py` reads `src/` with `ast` and prints each broken rule as
`[rule] path:line: detail` (exit 0 clean, 1 findings, 2 unusable arguments or configuration); `tests/test_boundaries.py`
runs it, so it is part of the `tests` stage. The rules and the reason for each are in *Layers* in
[python.md](python.md).

## The renderers

Three tools write a page derived from the repository's own files. Each page is git-ignored or checked for being current, so it
cannot drift from its sources:

| Tool | Writes | `make` | The rules |
| --- | --- | --- | --- |
| `tools/render_journal_index.py` | `Docs/journal/INDEX.md`, the journal's browsable index (git-ignored) | `make journal` | [journal.md](journal.md) |
| `tools/render_board.py` | `Docs/plan/BOARD.md`, the board page from its row files (git-ignored) | `make board` | [workflow.md](workflow.md) |
| `tools/render_framework_graph.py` | `Docs/knowledge/ai-first-framework-graph.md`, from the graph's data (committed; the `graph` stage holds it current) | none | this file's check runner |

## The git hooks

Git cannot ship a hook with a repository: a hook runs only if the clone's `core.hooksPath` names the folder that holds it.
The hooks are in `.githooks/`, and **`make hooks` (once per clone) turns them on**; `make hooks-check` says whether they
are. The check runner prints a reminder when it runs in a checkout where they are not. A hook nobody installed enforces
nothing.

| Hook | Runs | Stops the commit when |
| --- | --- | --- |
| `pre-commit` | `tools/check.py --fast` | A fast stage fails. It checks the working tree, not only what is staged, and the tests are not run here (they take longer than a commit should); CI and `make check` run them |
| `commit-msg` | `tools/check_commit_msg.py` | The message carries an AI attribution, or lacks an accepted sign-off (the owner's, or a roster person's own) when the project requires one |

The commit-message rules are the definition of done's *Identity* section:

- **No AI attribution.** A `Co-Authored-By`, `Assisted-by` or `Generated-by` trailer naming an AI tool, or a `Generated with` /
  `Generated by` footer naming one, is rejected, also when the line starts with `#` (git keeps such a line when the message is
  given with `-m`, so a commented-out attribution would ship). The list of names is a floor in `tools/check_commit_msg.py`;
  add a name when a new tool first appears in a trailer. A human co-author is not rejected, except one who shares a tool's
  name: name them in the message body instead.
- **The sign-off.** When `signoff` is true in `project.json`, the message needs a `Signed-off-by: <name> <email>` that is an
  accepted identity: the owner's, exactly as `project.json` gives them, or a roster person's `name` with one of the `emails`
  on their `[[people]]` row in `framework.toml` (the email without regard to case, the name exactly; a person with no address
  cannot sign). `git commit -s` writes it, using git's `user.name` and `user.email`, so those must be one of them; the
  rejection lists every accepted identity. A repository with no `framework.toml` accepts the owner alone; one whose
  `framework.toml` cannot be read or is invalid stops the hook rather than narrowing to the owner silently. A `#` line is no sign-off. A merge message (`Merge branch`,
  `Merge pull request`...) and a `fixup!`, `squash!` or `amend!` message need none of their own.

A hook can be bypassed (`git commit --no-verify`). For the **fast stages** that is why CI runs the same stages: the hook is a
convenience that fails early and CI is the enforcement. **The commit-message rules have no such backstop:** CI does not run
`check_commit_msg.py`, so `--no-verify` bypasses the attribution rule and the sign-off rule alike, and nothing server-side
rechecks them (on GitHub the DCO app checks sign-offs on a pull request; nothing checks attribution). They are local rules.

## Line endings

`.gitattributes` keeps text files LF in the repository and native in the working tree, and forces LF for the Makefile and
the hook files: a hook with a carriage return does not run under `sh`, and a Makefile with one does not parse. A test fails
on either.

## What is deliberately not here

No hook installer that runs by itself (it would change a clone's configuration unasked), no stage for a tool that is
configured and never run, and no logic in the Makefile or a hook, however small.
