# CI: the definition of done, enforced

**Status:** Living. Managed by the template: a repository's copy must match, so do not edit it here; propose a change to the
template. It says what the workflow runs and why it is shaped as it is. The stages themselves are in
[tooling.md](tooling.md).

**This project's additions** go in `ci-project.md` beside this file, when it has any: an extension adds rules and never
weakens these. To relax or contradict a rule here, override this file in `framework.toml` with a reason that names the
rule.

## The shape

`.github/workflows/ci.yml` (GitHub's format, since GitHub requires YAML; everywhere else the framework uses JSON or TOML)
has one job on two legs, `windows-latest` and `ubuntu-latest`, and one step per stage of `tools/check.py`, in its order, so
that a failure names its stage in the log:

```text
checkout, install uv, set up Python, sync dependencies (uv sync --group dev)
then one step per stage, in the order `uv run python tools/check.py --list` prints them (the stage table in tooling.md)
```

**Parity is a test, not a hope.** `tests/test_tooling.py` takes the stages from `tools/check.py` (the same function
`make check` runs), reads the `run:` commands out of the workflow and fails when a stage is not run, is run in another
order, or when the workflow runs a check command the runner does not. A command that is commented out is not a step. Turn a
module on or off in `framework.toml` and the test names the step to add or remove. Without it, local green and CI green mean
different things, which is the failure the first CI run of a project usually finds.

## Why two operating systems

The project may be developed on one system, but a path is case-sensitive on the other. A link or an import with the wrong
case works on a case-insensitive disk and fails on a case-sensitive one, so the docs check would pass on Windows alone and a
dead link would ship. The matrix does not cancel the other leg when one fails (`fail-fast: false`): a failure on one system
only is exactly the signal it exists to produce.

## Rules for a step

- **One command per step, never piped.** A pipe can swallow the exit code of the command before it; the test fails on a `|`.
- **Hardware the runner lacks is skipped with a reason**, never silently and never to get green
  ([testing.md](testing.md)).
- **A failing run is read before the push is called finished** (`gh pr checks --watch` on GitHub): a push is not done until its
  CI run's conclusion has been read.
- **No stage step can fail silently or be skipped.** A stage step with `continue-on-error` or an `if:` stays green while it fails
  or never runs; the parity test fails on one.
- **The token reads the repository and nothing else** (`permissions: contents: read` at the top). A step that needs more
  says so in its own job, scoped to what it uses, and a secret is never echoed.

## Dependency updates

`.github/dependabot.yml` opens a weekly pull request for the dependencies (the `uv` ecosystem, which updates the lock file
with `pyproject.toml`) and for the actions the workflow uses. Each
goes through this CI like any other change, which is the point: a bump that breaks the suite is found by the gate and not by
a user.

## What is deliberately not here

No second workflow that repeats the stages under another name, and no step that runs a command `tools/check.py` does not:
if a check is worth running in CI it is worth running locally, so it is a stage.
