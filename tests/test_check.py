"""
Framework: tests for tools/check.py (the check runner: every check CI runs, in one command, in CI's order).
Package: tests/test_check

The stage list follows the modules of framework.toml; every stage runs even after one fails; a stage that cannot be
started
is a failed stage, not a traceback; and ``--list`` is the oracle the CI parity test reads.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import check  # noqa: E402
import framework_config as fc  # noqa: E402

# Fixed text, not the repository's own framework.toml: this file is managed, and a project owns that one.
FRAMEWORK_TOML = """[framework]
template_version = "0.1.0"

[modules]
core = "on"
journal = "on"
ux = "planned"
python-uv = "on"
tasking = "planned"
hygiene = "on"
graph = "on"
harness-adapters = "on"
specimens = "planned"
lanes = "off"
branch-ownership = "off"
devblog = "off"
process-map = "off"

[harnesses]
enabled = []

[checks]
handoff_max_lines = 150
"""
ALL_NAMES = ["lint", "format", "docs", "hygiene", "log-format", "graph", "adapters", "sync", "tests"]


def _repo(tmp_path: Path, **modules: str) -> Path:
    """A directory holding the payload's framework.toml with the given modules set (``python_uv`` is ``python-uv``)."""
    text = FRAMEWORK_TOML
    for module, state in modules.items():
        name = module.replace("_", "-")
        line = next(ln for ln in text.splitlines() if ln.startswith(f"{name} = "))
        text = text.replace(line, f'{name} = "{state}"')
    (tmp_path / "framework.toml").write_text(text, encoding="utf-8")
    return tmp_path


def _fake_run(codes: dict[str, int], calls: list):
    """A stand-in for subprocess.run: the return code is chosen by the stage's name, found from the argv."""

    def run(argv, cwd=None, check=False, **kwargs):
        calls.append((tuple(argv), cwd))
        for name, stage in ((s.name, s) for s in check_module.ALL_STAGES):
            if tuple(argv) == stage.argv:
                return SimpleNamespace(returncode=codes.get(name, 0))
        raise AssertionError(f"an argv that is no stage ran: {argv}")

    return run


check_module = check


# ---- the stage list follows the modules
def test_the_payloads_stages_are_the_documented_ones_in_order(tmp_path: Path) -> None:
    assert [s.name for s in check.stages(_repo(tmp_path))] == ALL_NAMES


@pytest.mark.parametrize(
    ("module", "gone"),
    [
        ("hygiene", ["hygiene"]),
        ("graph", ["graph"]),
        ("harness_adapters", ["adapters"]),
        ("python_uv", ["log-format", "tests"]),
    ],
)
def test_a_module_that_is_off_takes_its_stages_with_it(tmp_path: Path, module: str, gone: list[str]) -> None:
    names = [s.name for s in check.stages(_repo(tmp_path, **{module: "off"}))]
    assert names == [n for n in ALL_NAMES if n not in gone]


def test_the_process_map_stage_runs_only_while_its_module_is_on_and_right_after_the_graph(tmp_path: Path) -> None:
    assert "process-map" not in [s.name for s in check.stages(_repo(tmp_path))]
    names = [s.name for s in check.stages(_repo(tmp_path, process_map="on"))]
    after_graph = ALL_NAMES.index("graph") + 1
    assert names == [*ALL_NAMES[:after_graph], "process-map", *ALL_NAMES[after_graph:]]
    assert next(s for s in check.ALL_STAGES if s.name == "process-map").fast


def test_a_framework_toml_that_does_not_name_the_process_map_runs_without_its_stage(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    text = (root / "framework.toml").read_text(encoding="utf-8")
    (root / "framework.toml").write_text(text.replace('process-map = "off"\n', ""), encoding="utf-8")
    assert "process-map" not in (root / "framework.toml").read_text(encoding="utf-8")
    assert [s.name for s in check.stages(root)] == ALL_NAMES


def test_the_payload_stage_is_the_template_s_own_last_and_never_fast(tmp_path: Path) -> None:
    """The template's root runs the payload's own suite (ledger P-22); a repository made from it never names the
    module, so it reads as off there and the stage list is unchanged."""
    root = _repo(tmp_path)
    assert "payload-suite" not in (root / "framework.toml").read_text(encoding="utf-8")
    assert [s.name for s in check.stages(root)] == ALL_NAMES
    text = (root / "framework.toml").read_text(encoding="utf-8")
    (root / "framework.toml").write_text(text.replace("[harnesses]", 'payload-suite = "on"\n\n[harnesses]'), "utf-8")
    assert [s.name for s in check.stages(root)] == [*ALL_NAMES, "payload"]
    stage = next(s for s in check.ALL_STAGES if s.name == "payload")
    assert stage.module == "payload-suite" and not stage.fast
    assert "payload" not in [s.name for s in check.stages(root, fast=True)]


def test_a_module_that_is_planned_runs_nothing(tmp_path: Path) -> None:
    assert "graph" not in [s.name for s in check.stages(_repo(tmp_path, graph="planned"))]


def test_fast_drops_exactly_the_tests(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    assert [s.name for s in check.stages(root, fast=True)] == [n for n in ALL_NAMES if n != "tests"]
    assert [s.name for s in check.stages(root) if not s.fast] == ["tests"]


def test_every_stage_is_a_uv_run_argv_and_names_a_real_module() -> None:
    for stage in check.ALL_STAGES:
        assert stage.argv[:2] == ("uv", "run"), stage.name
        assert stage.module in fc.MODULES, stage.name
        assert stage.why and stage.name == stage.name.strip()
    assert len({s.name for s in check.ALL_STAGES}) == len(check.ALL_STAGES)


def test_every_script_a_stage_runs_exists() -> None:
    """The payload ships every stage's script; a made repository, only those of the modules it has on."""
    made = (ROOT / "project.json").exists()
    modules = fc.load_framework(ROOT / "framework.toml").modules
    for stage in check.ALL_STAGES:
        if made and modules[stage.module] != "on":
            continue
        for arg in stage.argv:
            if arg.startswith("tools/"):
                assert (ROOT / arg).is_file(), (stage.name, arg)


def test_the_stage_list_is_read_from_the_root_it_is_given(tmp_path: Path) -> None:
    (tmp_path / "framework.toml").write_text("this is not toml = = =", encoding="utf-8")
    with pytest.raises(fc.ConfigError):
        check.stages(tmp_path)


# ---- the command line
def test_list_prints_each_stage_and_its_command_and_runs_nothing(tmp_path: Path, capsys, monkeypatch) -> None:
    monkeypatch.setattr(check.subprocess, "run", lambda *a, **k: pytest.fail("--list ran a command"))
    assert check.main(["--list", "--root", str(_repo(tmp_path))]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert [ln.split("\t")[0] for ln in lines] == ALL_NAMES
    assert lines[0] == "lint\tuv run ruff check ."
    assert lines[-1] == "tests\tuv run pytest -q"


def test_only_runs_the_named_stages_in_the_runners_order(tmp_path: Path, capsys) -> None:
    root = _repo(tmp_path)
    assert check.main(["--list", "--only", "tests", "lint", "--root", str(root)]) == 0
    assert [ln.split("\t")[0] for ln in capsys.readouterr().out.splitlines()] == ["lint", "tests"]


def test_only_a_stage_that_is_not_here_is_unusable_and_names_the_stages(tmp_path: Path, capsys) -> None:
    root = _repo(tmp_path, hygiene="off")
    assert check.main(["--only", "hygiene", "--root", str(root)]) == 2
    err = capsys.readouterr().err
    assert "no such stage here: hygiene" in err and "lint, format, docs" in err


def test_a_missing_or_invalid_framework_toml_is_unusable_not_a_traceback(tmp_path: Path, capsys) -> None:
    assert check.main(["--root", str(tmp_path)]) == 2
    assert "cannot run" in capsys.readouterr().err
    assert check.main(["--root", str(tmp_path / "nowhere")]) == 2
    assert "is not a directory" in capsys.readouterr().err


def test_a_run_with_no_stage_to_run_is_unusable_never_a_pass(tmp_path: Path, capsys, monkeypatch) -> None:
    monkeypatch.setattr(check, "ALL_STAGES", ())
    assert check.main(["--root", str(_repo(tmp_path))]) == 2
    assert "nothing was checked" in capsys.readouterr().err


# ---- running
def test_a_clean_run_runs_every_stage_in_the_root_and_exits_0(tmp_path: Path, capsys, monkeypatch) -> None:
    root = _repo(tmp_path)
    calls: list = []
    monkeypatch.setattr(check.subprocess, "run", _fake_run({}, calls))
    monkeypatch.setenv("CI", "1")
    assert check.main(["--root", str(root)]) == 0
    assert [argv for argv, _ in calls] == [s.argv for s in check.stages(root)]
    assert {str(cwd) for _, cwd in calls} == {str(root.resolve())}
    out = capsys.readouterr().out
    assert f"All {len(ALL_NAMES)} stages passed" in out and out.count("PASS") == len(ALL_NAMES) and "FAIL" not in out


def test_every_stage_runs_after_one_fails_and_the_summary_names_it(tmp_path: Path, capsys, monkeypatch) -> None:
    calls: list = []
    monkeypatch.setattr(check.subprocess, "run", _fake_run({"format": 1, "graph": 3}, calls))
    monkeypatch.setenv("CI", "1")
    assert check.main(["--root", str(_repo(tmp_path))]) == 1
    assert len(calls) == len(ALL_NAMES)  # nothing stopped at the first failure
    out = capsys.readouterr().out
    assert "FAILED: format, graph" in out
    assert out.count("FAIL ") == 2 and out.count("PASS") == len(ALL_NAMES) - 2


def test_a_stage_that_cannot_be_started_is_a_failed_stage_with_its_reason(tmp_path: Path, capsys, monkeypatch) -> None:
    def refuse(argv, **kwargs):
        raise FileNotFoundError("uv")

    monkeypatch.setattr(check.subprocess, "run", refuse)
    monkeypatch.setenv("CI", "1")
    assert check.main(["--root", str(_repo(tmp_path)), "--only", "lint"]) == 1
    captured = capsys.readouterr()
    assert "could not start 'uv'" in captured.err and "FAILED: lint" in captured.out


def test_the_summary_line_gives_each_stages_reason(tmp_path: Path, capsys, monkeypatch) -> None:
    monkeypatch.setattr(check.subprocess, "run", _fake_run({}, []))
    monkeypatch.setenv("CI", "1")
    check.main(["--root", str(_repo(tmp_path)), "--only", "docs"])
    assert next(s.why for s in check.ALL_STAGES if s.name == "docs") in capsys.readouterr().out


def test_verbose_logs_the_decision_and_quiet_does_not(tmp_path: Path) -> None:
    """In a process of its own: logging is configured once per process, so an in-process pair of runs proves nothing."""
    base = [sys.executable, str(ROOT / "tools" / "check.py"), "--list", "--root", str(_repo(tmp_path))]
    quiet = subprocess.run(base, capture_output=True, text=True, check=False)
    loud = subprocess.run([*base, "-v"], capture_output=True, text=True, check=False)
    assert quiet.returncode == loud.returncode == 0
    assert quiet.stderr == "" and "stages for" in loud.stderr


# ---- the argv as typed
@pytest.mark.parametrize(
    ("argv", "typed"),
    [
        (("uv", "run", "ruff", "check", "."), "uv run ruff check ."),
        (("uv", "run", "pytest", "-m", "not gpu and not gui"), 'uv run pytest -m "not gpu and not gui"'),
    ],
)
def test_shell_form_quotes_an_argument_with_a_space(argv: tuple[str, ...], typed: str) -> None:
    assert check.shell_form(argv) == typed


# ---- the hooks reminder
def test_the_reminder_appears_only_in_an_uninstalled_git_checkout_outside_ci(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("CI", raising=False)
    assert check.hooks_note(tmp_path) == ""  # not a git checkout
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    assert "make hooks" in check.hooks_note(tmp_path)
    monkeypatch.setenv("CI", "true")
    assert check.hooks_note(tmp_path) == ""


# ---- review fixes: an empty list, an interrupt, and the order of output on a pipe
def test_list_with_no_stage_is_unusable_like_a_run_with_none(tmp_path: Path, capsys, monkeypatch) -> None:
    monkeypatch.setattr(check, "ALL_STAGES", ())
    assert check.main(["--list", "--root", str(_repo(tmp_path))]) == 2
    assert capsys.readouterr().out == ""


def test_an_interrupt_ends_the_run_with_130_not_a_traceback(tmp_path: Path, capsys, monkeypatch) -> None:
    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(check.subprocess, "run", interrupt)
    monkeypatch.setenv("CI", "1")
    assert check.main(["--root", str(_repo(tmp_path)), "--only", "lint"]) == 130
    assert "interrupted" in capsys.readouterr().err


def test_a_stages_header_is_flushed_before_its_output_can_arrive(tmp_path: Path, monkeypatch) -> None:
    """On a pipe, an unflushed header comes out after the child's output: the log then names the wrong stage."""
    flushed: list[bool] = []

    def record(*args, flush=False, **kwargs):
        if args and str(args[0]).lstrip().startswith(("===", "uv ")):
            flushed.append(flush)

    monkeypatch.setattr(check, "print", record, raising=False)
    monkeypatch.setattr(check.subprocess, "run", _fake_run({}, []))
    check.run_stage(check.ALL_STAGES[0], tmp_path)
    assert flushed == [True, True]
