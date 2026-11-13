"""
Framework: the task-runner and CI layering rules, enforced.
Package: tests/test_tooling

Docs/standards/tooling.md defines three layers and one hard rule: ``tools/*.py`` holds all logic and all composition;
the
``Makefile`` dispatches only, so that every recipe is a single ``uv`` invocation; the git hooks are one ``exec`` line.
And
Docs/standards/ci.md adds one more: the CI workflow runs the stages of ``tools/check.py`` in its order, so that local
green
and CI green mean the same thing.

A rule stated in a document decays. These tests are why these will not.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import check  # noqa: E402

MAKEFILE = ROOT / "Makefile"
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
HOOKS = sorted((ROOT / ".githooks").glob("*"))

#: Shell operators that make a recipe more than one command, or let a pipe swallow a failure.
_SHELL_OPERATORS = re.compile(r"&&|\|\||[;|&<>`]|\$[({]")

#: What may not appear in a ``help`` line: sh reads each of these as syntax, not as text to print.
_SH_SYNTAX = re.compile(r"""[;()'"&|<>$`\\*?\[\]{}~#!]""")


# ---- the Makefile
def _makefile_recipes(text: str) -> dict[str, list[str]]:
    """``{target: [recipe lines]}``; recipe lines are tab-indented, and a leading ``@`` (silencing) is removed."""
    recipes: dict[str, list[str]] = {}
    current: str | None = None
    for raw in text.splitlines():
        if raw.startswith("\t"):
            if current is not None:
                recipes[current].append(raw.lstrip("\t").lstrip("@").strip())
            continue
        match = _TARGET_LINE.match(raw)
        if match and not match.group(1).startswith("."):  # .PHONY, .DEFAULT_GOAL: directives, not targets
            current = match.group(1)
            recipes[current] = []
        elif raw.strip():
            current = None
    return recipes


#: A target line: a name (dots allowed, as in ``foo.bar``), a colon that is not ``:=``, and the prerequisites.
_TARGET_LINE = re.compile(r"^([A-Za-z0-9_.\-]+):(?!=)(.*)$")


def _makefile_prerequisites(text: str) -> dict[str, list[str]]:
    """``{target: [prerequisites]}``: what follows the colon of each target line the recipe parser sees."""
    found: dict[str, list[str]] = {}
    for raw in text.splitlines():
        match = _TARGET_LINE.match(raw)
        if match and not match.group(1).startswith("."):
            found[match.group(1)] = match.group(2).split("#")[0].split()
    return found


def test_a_dotted_target_is_a_target_and_its_prerequisite_is_seen() -> None:
    text = "foo.bar: baz\n\tuv run x\n.PHONY: foo.bar\n"
    assert _makefile_recipes(text) == {"foo.bar": ["uv run x"]}
    assert _makefile_prerequisites(text) == {"foo.bar": ["baz"]}


def test_the_recipe_parser_reads_targets_tabs_and_ignores_directives() -> None:
    text = ".PHONY: a b\n.DEFAULT_GOAL := a\n\na:\n\tuv run x\n\nb:\n\t@uv run y\n\tuv run z\nX := 1\n"
    assert _makefile_recipes(text) == {"a": ["uv run x"], "b": ["uv run y", "uv run z"]}


def test_every_makefile_recipe_is_one_uv_command() -> None:
    recipes = _makefile_recipes(MAKEFILE.read_text(encoding="utf-8"))
    assert recipes and "help" in recipes and "check" in recipes
    for target, lines in recipes.items():
        if target == "help":  # echo output, not work
            continue
        assert len(lines) == 1, f"target {target!r} has {len(lines)} recipe lines; composition belongs in tools/"
        assert lines[0].startswith("uv "), f"target {target!r} does not dispatch through uv: {lines[0]!r}"
        assert not _SHELL_OPERATORS.search(lines[0]), f"target {target!r} chains or pipes: {lines[0]!r}"


def test_no_target_has_a_prerequisite() -> None:
    """``check: lint test`` is composition in the Makefile, which the hard rule keeps out (and is not one uv call)."""
    found = {t: p for t, p in _makefile_prerequisites(MAKEFILE.read_text(encoding="utf-8")).items() if p}
    assert found == {}


def test_the_prerequisite_parser_sees_one_and_skips_a_comment() -> None:
    assert _makefile_prerequisites("a: b c\nd:\ne: # nothing\n") == {"a": ["b", "c"], "d": [], "e": []}


def test_the_help_recipe_is_only_echo_with_no_shell_syntax_in_the_text() -> None:
    """``make help`` is the default goal. sh reads ``;`` and an unbalanced quote as syntax, not as text: a help line
    that looked fine failed with ``see: command not found`` for exactly that reason."""
    lines = _makefile_recipes(MAKEFILE.read_text(encoding="utf-8"))["help"]
    assert lines and all(line.startswith("echo ") for line in lines)
    for line in lines:
        assert not _SH_SYNTAX.search(line[len("echo ") :]), f"sh would read syntax in a help line: {line!r}"


@pytest.mark.skipif(shutil.which("sh") is None, reason="needs sh to run a recipe the way make does")
def test_every_help_line_prints_as_written_when_sh_runs_it() -> None:
    for line in _makefile_recipes(MAKEFILE.read_text(encoding="utf-8"))["help"]:
        ran = subprocess.run(["sh", "-c", line], capture_output=True, text=True, check=False)
        assert ran.returncode == 0, (line, ran.stderr)
        assert ran.stdout.split() == line[len("echo ") :].split(), line


def test_the_sh_syntax_pattern_catches_what_broke_make_help() -> None:
    for bad in ("one; see the docs", "CI's order", "the stages (all of them)", "a & b", "$HOME"):
        assert _SH_SYNTAX.search(bad), bad
    assert not _SH_SYNTAX.search("make check - the full gate, every check CI runs in the same order. Run this")


def test_every_target_is_phony_and_documented_in_help() -> None:
    text = MAKEFILE.read_text(encoding="utf-8")
    phony = re.search(r"^\.PHONY:\s*(.+)$", text, re.MULTILINE)
    assert phony, "the Makefile has no .PHONY line"
    recipes = _makefile_recipes(text)
    assert set(phony.group(1).split()) == set(recipes), "the .PHONY line and the targets differ"
    help_text = "\n".join(recipes["help"])
    missing = sorted(t for t in recipes if t != "help" and f"make {t} " not in help_text + " ")
    assert not missing, f"targets missing from `make help`: {missing}"


def test_make_check_is_the_check_runner() -> None:
    assert _makefile_recipes(MAKEFILE.read_text(encoding="utf-8"))["check"] == ["uv run python tools/check.py"]


def test_every_tool_script_a_recipe_runs_exists() -> None:
    for target, lines in _makefile_recipes(MAKEFILE.read_text(encoding="utf-8")).items():
        for token in lines[0].split() if target != "help" else []:
            if token.startswith("tools/"):
                assert (ROOT / token).is_file(), (target, token)


def test_the_makefile_avoids_what_gnu_make_3_81_lacks() -> None:
    code = "\n".join(ln for ln in MAKEFILE.read_text(encoding="utf-8").splitlines() if not ln.startswith("#"))
    assert not re.search(r"^\.ONESHELL|\$\(file |\.RECIPEPREFIX", code, re.MULTILINE)


# ---- the hooks
def test_the_hooks_are_one_exec_line_into_tools() -> None:
    assert [h.name for h in HOOKS] == ["commit-msg", "pre-commit"]
    for hook in HOOKS:
        lines = [ln for ln in hook.read_text(encoding="utf-8").splitlines() if ln.strip()]
        assert lines[0] == "#!/bin/sh", hook.name
        body = [ln for ln in lines if not ln.startswith("#")]
        assert len(body) == 1, f"{hook.name} should hold exactly one command, found {body}"
        assert body[0].startswith("exec uv run python tools/"), f"{hook.name}: {body[0]!r}"
        script = body[0].split()[4]
        assert (ROOT / script).is_file(), f"{hook.name} runs {script}, which is not there"


def test_the_pre_commit_hook_runs_the_fast_stages_and_commit_msg_gets_the_message_file() -> None:
    assert "exec uv run python tools/check.py --fast" in (ROOT / ".githooks/pre-commit").read_text(encoding="utf-8")
    assert 'tools/check_commit_msg.py "$1"' in (ROOT / ".githooks/commit-msg").read_text(encoding="utf-8")


def test_the_hooks_and_the_makefile_keep_lf_line_endings_on_every_system() -> None:
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()
    for path in ("Makefile", ".githooks/pre-commit", ".githooks/commit-msg"):
        assert any(line.split() == [path, "text", "eol=lf"] for line in attributes), f"{path} is not forced to LF"
    for hook in HOOKS:
        assert b"\r" not in hook.read_bytes(), f"{hook.name} has a carriage return"
    assert b"\r" not in MAKEFILE.read_bytes()


# ---- the workflow
def workflow_commands(text: str) -> list[str]:
    """The ``run:`` commands of a workflow, in order. Handles the subset the workflow uses: a one-line ``run: cmd``
    and a ``run: |`` / ``run: >`` block; a commented-out line is not a step, which a plain substring match counts."""
    commands: list[str] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        if line.lstrip().startswith("#"):
            continue
        match = re.match(r"^(\s*)(?:- )?run:\s*(.*?)\s*$", line)
        if not match:
            continue
        indent, value = len(match.group(1)), match.group(2)
        if value in ("|", ">", "|-", ">-"):
            while i < len(lines) and (not lines[i].strip() or len(lines[i]) - len(lines[i].lstrip()) > indent + 1):
                if lines[i].strip() and not lines[i].lstrip().startswith("#"):
                    commands.append(lines[i].strip())
                i += 1
        elif value:
            quoted = len(value) > 1 and value[0] == value[-1] and value[0] in "'\""
            commands.append(value[1:-1] if quoted else value)  # a quoted scalar; a command ending in a quote keeps it
    return commands


def test_the_workflow_command_parser() -> None:
    text = (
        "steps:\n"
        "  - run: uv a\n"
        "  # - run: uv commented\n"
        "  - name: x\n"
        "    run: |\n"
        "      uv b\n"
        "      # uv also commented\n"
        "      uv c\n"
        "    env:\n"
        "      K: v\n"
        "  - run: 'uv d'\n"
        '  - run: uv e --flag "$X"\n'
    )
    assert workflow_commands(text) == ["uv a", "uv b", "uv c", "uv d", 'uv e --flag "$X"']


def _stage_commands() -> list[str]:
    return [check.shell_form(s.argv) for s in check.stages(ROOT)]


def test_the_workflow_runs_every_stage_of_the_check_runner_in_its_order() -> None:
    commands = workflow_commands(WORKFLOW.read_text(encoding="utf-8"))
    stages = _stage_commands()
    assert stages, "the check runner has no stage"
    missing = [s for s in stages if s not in commands]
    assert not missing, f"stages of tools/check.py that the workflow does not run (add a step for each): {missing}"
    positions = [commands.index(s) for s in stages]
    assert positions == sorted(positions), f"the workflow runs the stages in another order than {stages}"


def test_the_workflow_runs_no_gate_command_the_check_runner_does_not() -> None:
    """A step for a module that is off would pass in CI what ``make check`` never runs."""
    commands = workflow_commands(WORKFLOW.read_text(encoding="utf-8"))
    known = {check.shell_form(s.argv) for s in check.ALL_STAGES}
    enabled = set(_stage_commands())
    for command in commands:
        if command in known:
            assert command in enabled, f"the workflow runs {command!r}, which the check runner does not (module off?)"


def workflow_steps(text: str) -> list[str]:
    """The workflow's steps as text, each from its first key (``- name:``, ``- uses:``, ``- run:``) to the next step."""
    steps: list[list[str]] = []
    dash_indent: int | None = None
    for line in text.splitlines():
        if line.lstrip().startswith("#") or not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        if re.match(r"^\s*- (name|uses|run)\s*:", line):
            steps.append([line])
            dash_indent = indent
        elif dash_indent is not None and indent > dash_indent:
            steps[-1].append(line)
        else:
            dash_indent = None  # a line back at job level ends the step list, until the next job's first step
    return ["\n".join(step) for step in steps]


def test_the_step_splitter_keeps_a_steps_keys_together() -> None:
    text = (
        "steps:\n  - name: a\n    if: false\n    run: uv x\n  # - run: gone\n"
        "  - uses: y\n    with:\n      k: v\nnext: 1\n"
    )
    assert workflow_steps(text) == ["  - name: a\n    if: false\n    run: uv x", "  - uses: y\n    with:\n      k: v"]
    # a second job: its own keys (name, if) belong to no step of the first job
    two_jobs = "  a:\n    steps:\n      - run: uv x\n  b:\n    if: false\n    steps:\n      - run: uv y\n"
    assert workflow_steps(two_jobs) == ["      - run: uv x", "      - run: uv y"]


def test_no_stage_step_can_fail_silently_or_be_skipped() -> None:
    """A stage with ``continue-on-error`` or an ``if:`` stays green in CI while it fails or never runs."""
    stages = set(_stage_commands())
    guarded = [
        step
        for step in workflow_steps(WORKFLOW.read_text(encoding="utf-8"))
        if set(workflow_commands(step)) & stages
        and re.search(r"^\s*(?:- )?(?:continue-on-error|if)\s*:", step, flags=re.MULTILINE)
    ]
    assert guarded == [], f"a stage step that can fail silently or be skipped: {guarded}"


def test_the_matrix_lists_both_systems_and_the_job_reads_the_repository_only() -> None:
    text = "\n".join(ln for ln in WORKFLOW.read_text(encoding="utf-8").splitlines() if not ln.lstrip().startswith("#"))
    legs = re.findall(r"^\s*- ((?:windows|ubuntu)-latest)\s*$", text, flags=re.MULTILINE)
    assert sorted(legs) == ["ubuntu-latest", "windows-latest"]
    assert re.search(r"^permissions:\s*\n\s+contents: read\s*$", text, flags=re.MULTILINE)


def test_dependabot_follows_the_package_manager_the_project_uses() -> None:
    if (ROOT / "uv.lock").exists():
        text = (ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
        assert 'package-ecosystem: "uv"' in text and 'package-ecosystem: "pip"' not in text


def test_the_workflow_syncs_before_any_stage_and_never_pipes_a_stage() -> None:
    commands = workflow_commands(WORKFLOW.read_text(encoding="utf-8"))
    stages = _stage_commands()
    assert "uv sync --group dev" in commands
    assert commands.index("uv sync --group dev") < commands.index(stages[0])
    for command in commands:
        assert "|" not in command and "||" not in command, f"a pipe can swallow a failure: {command!r}"


def test_the_workflow_does_not_cancel_the_other_system_when_one_fails() -> None:
    uncommented = "\n".join(
        ln for ln in WORKFLOW.read_text(encoding="utf-8").splitlines() if not ln.lstrip().startswith("#")
    )
    assert re.search(r"^\s+fail-fast: false\s*$", uncommented, flags=re.MULTILINE)


def test_the_check_runner_lists_what_the_workflow_parity_test_compares(tmp_path: Path) -> None:
    ran = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "check.py"), "--list", "--root", str(ROOT)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert ran.returncode == 0, ran.stderr
    listed = [line.split("\t", 1)[1] for line in ran.stdout.splitlines()]
    assert listed == _stage_commands()


@pytest.mark.parametrize(
    "path", ["Makefile", ".githooks/pre-commit", ".githooks/commit-msg", ".github/workflows/ci.yml"]
)
def test_every_file_the_gate_rests_on_exists(path: str) -> None:
    assert (ROOT / path).is_file()


# ---- the standard describes the runner
def test_the_stage_table_in_the_tooling_standard_is_the_check_runners_stage_list() -> None:
    """The table is compared with ``ALL_STAGES`` in both directions, in order, and on every column."""
    rows = []
    for line in (ROOT / "Docs/standards/tooling.md").read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 5 and cells[0].startswith("`") and cells[1].startswith("`uv "):
            rows.append((cells[0].strip("`"), cells[1].strip("`"), cells[2], cells[3]))
    runner = [(s.name, check.shell_form(s.argv), s.module, "yes" if s.fast else "no") for s in check.ALL_STAGES]
    assert rows == runner


# ---- the workflow follows the project's own default branch
@pytest.mark.skipif(
    (ROOT / "project.json").exists(),
    reason="runs only against the template's payload, not in a repository made from it",
)
@pytest.mark.parametrize("branch", ["main", "trunk", "release/1.x"])
def test_the_workflow_runs_on_pushes_to_the_projects_own_default_branch(tmp_path: Path, capsys, branch: str) -> None:
    import json

    import init

    answers = tmp_path / "answers.json"
    answers.write_text(
        json.dumps(
            {
                "name": "Example",
                "slug": "example",
                "owner": {"name": "Ada Example", "email": "ada@example.org"},
                "default_branch": branch,
                "signoff": True,
                "hygiene": [],
            }
        ),
        encoding="utf-8",
    )
    target = tmp_path / "made"
    argv = ["new", "--answers", str(answers), "--target", str(target), "--no-sync", "--no-checks"]
    assert init.main(argv, source=ROOT, today="2026-10-13") == 0
    capsys.readouterr()
    text = (target / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert f"branches: [{branch}]" in text and "{{" not in text.replace("${{", "")


# ---- the commits job: the one CI check that is not a stage (Docs/standards/ci.md)
def _job(text: str, name: str) -> str:
    """The text of one job under ``jobs:``, from its key to the next job's key or the end of the file."""
    lines = text.splitlines()
    key = f"  {name}:"
    assert key in lines, f"no {name!r} job in the workflow"
    body = [key]
    for line in lines[lines.index(key) + 1 :]:
        if line.strip() and len(line) - len(line.lstrip()) <= 2 and not line.lstrip().startswith("#"):
            break  # the next job, or a top-level key
        body.append(line)
    return "\n".join(body)


def test_the_workflow_checks_every_commit_of_a_pull_request() -> None:
    job = _job(WORKFLOW.read_text(encoding="utf-8"), "commits")
    assert "if: github.event_name == 'pull_request'" in job
    assert "fetch-depth: 0" in job  # both ends of the range
    assert "BASE: ${{ github.event.pull_request.base.sha }}" in job
    assert "HEAD: ${{ github.event.pull_request.head.sha }}" in job
    assert "OPENED_BY: ${{ github.event.pull_request.user.login }}" in job  # GitHub's record, not the commit's text
    commands = workflow_commands(job)
    want = 'uv run --no-sync python tools/check_commit_msg.py --range "$BASE..$HEAD" --opened-by "$OPENED_BY"'
    assert want in commands
    assert not [c for c in commands if "${{" in c], "an expression in a run line runs text an author controls"
