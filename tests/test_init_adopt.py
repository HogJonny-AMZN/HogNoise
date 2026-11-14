"""
Framework: tests for tools/init_adopt.py (``init adopt``: bring a repository that predates the template under it).
Package: tests/test_init_adopt

The payload is a small synthetic one with a file of every class and module state; the target is a repository that
predates it, with a file in each state ``adopt`` reports. ``git`` is a fake runner except in one test, so these run
anywhere. The promise under test: **nothing the project owns is lost**, a dry run writes nothing, and the lock and the
overrides that ``--apply`` leaves make the sync check pass on the day of adoption with the debt listed.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import boundaries as bd  # noqa: E402
import framework_config as fc  # noqa: E402
import framework_sync as fs  # noqa: E402
import init as ini  # noqa: E402
import init_adopt as ad  # noqa: E402

ANSWERS = {
    "name": "Old Project",
    "slug": "old-project",
    "owner": {"name": "Ada Example", "email": "ada@example.org"},
    "default_branch": "main",
    "signoff": True,
    "hygiene": [],
}
MANIFEST = """
[[rule]]
pattern = "tools/*.py"
module = "core"
kind = "managed"

[[rule]]
pattern = "AGENTS.md"
module = "core"
kind = "parametrised"

[[rule]]
pattern = "Docs/glossary.md"
module = "core"
kind = "managed"

[[rule]]
pattern = "pyproject.toml"
module = "python-uv"
kind = "project-owned"

[[rule]]
pattern = "README.md"
module = "core"
kind = "project-owned"

[[rule]]
pattern = "framework.toml"
module = "core"
kind = "project-owned"

[[rule]]
pattern = "framework-manifest.toml"
module = "core"
kind = "managed"

[[rule]]
pattern = "lanes/*"
module = "lanes"
kind = "managed"

[[rule]]
pattern = "specimens/*"
module = "specimens"
kind = "managed"
"""
VERSION = "0.1.0"
PAYLOAD_FILES = {
    "tools/same.py": "print('same')\n",
    "tools/local.py": "print('the template version')\n",
    "tools/new.py": "print('new in the template')\n",
    "AGENTS.md": "# {{name}} by {{owner_name}}\n",
    "Docs/glossary.md": "# Glossary\n\nthe template's terms\n",
    "pyproject.toml": '[project]\nname = "your-project-name"\n',
    "README.md": "# {{name}}\n",
    "lanes/lane.md": "an off module's file\n",
    "specimens/a.md": "a mock the project does not want\n",
}
TARGET_FILES = {
    "tools/same.py": "print('same')\n",
    "tools/local.py": "print('the project edited this')\n# a second line\n",
    "AGENTS.md": "# Old Project by Ada Example\n",
    "Docs/glossary.md": "# Glossary\n\nthe project's own terms\n",
    "README.md": "# The project's own readme\n",
    "src/product.py": "print('product')\n",
}


def _framework_text() -> str:
    modules = {name: "planned" for name in fc.MODULES}
    modules.update({"core": "on", "python-uv": "on", "specimens": "on", "lanes": "off"})
    data = {
        "framework": {"template_version": VERSION},
        "modules": modules,
        "harnesses": {"enabled": []},
        "checks": {"handoff_max_lines": 150},
        "layers": {"order": ["core", "app"], "pure": ["core"]},
        "overrides": [],
    }
    return fc.dump_framework(fc.parse_framework(data))


def _write(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))


@pytest.fixture
def source(tmp_path: Path) -> Path:
    src = tmp_path / "payload"
    _write(src, {"framework-manifest.toml": MANIFEST, "framework.toml": _framework_text(), **PAYLOAD_FILES})
    return src


@pytest.fixture
def target(tmp_path: Path) -> Path:
    root = tmp_path / "old-project"
    _write(root, TARGET_FILES)
    return root


@pytest.fixture
def answers(tmp_path: Path) -> Path:
    path = tmp_path / "answers.json"
    path.write_text(json.dumps(ANSWERS), encoding="utf-8")
    return path


class GitRunner:
    """Answers the git commands ``adopt`` asks; records every call.

    ``code`` non-zero makes the target not a git working tree; ``status`` is the porcelain text; ``toplevel`` is what
    ``rev-parse --show-toplevel`` says (default: the target itself); ``ignored`` are what ``check-ignore`` reports."""

    def __init__(
        self,
        status: str = "",
        code: int = 0,
        toplevel: str | None = None,
        ignored: tuple[str, ...] = (),
        ignore_code: int | None = None,
    ) -> None:
        self.status, self.code, self.toplevel, self.ignored = status, code, toplevel, ignored
        self.ignore_code = ignore_code  # a check-ignore exit code to force (128: git could not say)
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str], cwd: Path) -> ini.RunResult:
        self.calls.append(argv)
        if "rev-parse" in argv:
            if self.code:
                return ini.RunResult(128, "fatal: not a git repository")
            return ini.RunResult(0, self.toplevel or str(cwd.resolve()))
        if "status" in argv:
            return ini.RunResult(0, self.status)
        if "check-ignore" in argv:
            if self.ignore_code is not None:
                return ini.RunResult(self.ignore_code, "fatal: cannot check")
            hit = [p for p in argv[argv.index("--") + 1 :] if p in self.ignored]
            return ini.RunResult(0 if hit else 1, "\n".join(hit))
        raise AssertionError(f"unexpected git call: {argv}")


def _snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def _adopt(source: Path, target: Path, answers: Path, *extra: str, runner=None, capsys=None) -> tuple[int, str, str]:
    code = ini.main(
        ["adopt", "--answers", str(answers), "--target", str(target), *extra],
        source=source,
        runner=runner or GitRunner(),
        today="2026-10-16",
    )
    if capsys is None:
        return code, "", ""
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _states(out: str) -> dict[str, str]:
    """``{path: state}`` from a ``-v`` report's lines."""
    found = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] in ad.STATES and ("/" in parts[1] or "." in parts[1]):
            found[parts[1].rstrip(":")] = parts[0]
    return found


def _symlink(link: Path, to: Path) -> None:
    try:
        link.symlink_to(to, target_is_directory=to.is_dir())
    except (OSError, NotImplementedError):
        pytest.skip("this account cannot create a symlink")


# ---- the dry run
def test_a_dry_run_reports_each_file_in_its_state_and_writes_nothing(
    source: Path, target: Path, answers: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    before = _snapshot(target)
    code, out, _ = _adopt(source, target, answers, "-v", capsys=capsys)
    assert code == 0
    assert _snapshot(target) == before
    assert _states(out) == {
        "tools/same.py": "identical",
        "AGENTS.md": "identical",  # the rendered text equals the project's
        "tools/local.py": "differs",
        "Docs/glossary.md": "differs",
        "tools/new.py": "missing",
        "framework-manifest.toml": "missing",
        "README.md": "seed-present",
        "pyproject.toml": "seed-absent",
        "framework.toml": "seed-absent",
        "lanes/lane.md": "skipped",
        "specimens/a.md": "missing",
    }
    assert "src/product.py" not in out  # the project's own files are not listed
    assert "dry run: nothing written" in out


def test_the_report_starts_with_the_counts_then_the_differing_files_largest_first(
    source: Path, target: Path, answers: Path, capsys
) -> None:
    _, out, _ = _adopt(source, target, answers, capsys=capsys)
    lines = out.splitlines()
    assert lines[1] == "2 identical, 2 differ, 3 missing, 1 seed-present, 2 seed-absent, 1 skipped, 0 blocked"
    assert lines[2].startswith("--apply would record 2 override(s)")
    differing = [line for line in lines if line.startswith("differs")]
    assert [line.split()[1] for line in differing] == ["tools/local.py", "Docs/glossary.md"]  # +1 -2 before +1 -1


def test_without_dash_v_the_rest_is_counted_per_folder_and_with_it_every_file_is_listed(
    source: Path, target: Path, answers: Path, capsys
) -> None:
    _, out, _ = _adopt(source, target, answers, capsys=capsys)
    assert "missing" in out and "tools/new.py" not in out
    assert "tools/ 1" in out
    _, verbose, _ = _adopt(source, target, answers, "-v", capsys=capsys)
    assert "tools/new.py" in verbose


def test_a_differing_file_says_how_many_lines_differ_in_each_direction(
    source: Path, target: Path, answers: Path, capsys
) -> None:
    _, out, _ = _adopt(source, target, answers, capsys=capsys)
    line = next(line for line in out.splitlines() if line.startswith("differs") and "tools/local.py" in line)
    assert line.endswith("(+1 -2)")


def test_diff_shows_how_one_file_differs_and_refuses_one_that_does_not(
    source: Path, target: Path, answers: Path, capsys
) -> None:
    code, out, _ = _adopt(source, target, answers, "--diff", "tools/local.py", capsys=capsys)
    assert code == 0
    assert "-print('the project edited this')" in out
    assert "+print('the template version')" in out
    assert "(this repository)" in out and "(the template)" in out
    code, _, err = _adopt(source, target, answers, "--diff", "tools/same.py", capsys=capsys)
    assert code == 1
    assert "does not differ" in err


def test_a_file_where_a_directory_belongs_is_blocked_in_the_text_and_in_the_json_alike(
    source: Path, target: Path, answers: Path, capsys
) -> None:
    (target / "tools/new.py").mkdir()
    code, out, _ = _adopt(source, target, answers, capsys=capsys)
    assert code == 1
    assert "1 blocked" in out
    assert any(line.startswith("blocked") and "tools/new.py" in line for line in out.splitlines())
    _, out, _ = _adopt(source, target, answers, "--json", capsys=capsys)
    data = json.loads(out)
    assert data["counts"]["blocked"] == 1
    assert [e["path"] for e in data["entries"] if e["state"] == "blocked"] == ["tools/new.py"]


def test_a_refusal_without_a_file_to_name_is_still_a_blocked_entry(
    source: Path, target: Path, answers: Path, capsys
) -> None:
    _write(
        source, {"tools/odd.py": "print('{{nope}}')\n"}
    )  # a managed file is not rendered, so use a parametrised path
    _write(source, {"AGENTS.md": "# {{name}} {{bogus}}\n"})
    code, out, _ = _adopt(source, target, answers, "--json", capsys=capsys)
    assert code == 1
    data = json.loads(out)
    assert data["counts"]["blocked"] >= 1
    assert any("unknown token" in e["detail"] for e in data["entries"] if e["state"] == "blocked")


def test_a_target_that_already_has_a_framework_toml_or_a_lock_is_refused_with_the_remedy(
    source: Path, target: Path, answers: Path, capsys
) -> None:
    for name in ("framework.toml", "framework.lock"):
        _write(target, {name: "x"})
        code, _, err = _adopt(source, target, answers, capsys=capsys)
        assert code == 1
        assert f"already has a {name}" in err
        assert "init new" in err and "git stash -u" in err
        (target / name).unlink()


def test_the_target_must_be_an_existing_folder_apart_from_the_payload(
    source: Path, answers: Path, tmp_path: Path, capsys
) -> None:
    code, _, err = _adopt(source, tmp_path / "nowhere", answers, capsys=capsys)
    assert code == 1
    assert "is not a folder" in err
    assert _adopt(source, source / "inside", answers, capsys=capsys)[0] == 1
    assert _adopt(source, source, answers, capsys=capsys)[0] == 1
    code, _, err = _adopt(source, source.parent, answers, capsys=capsys)
    assert code == 1
    assert "different folders" in err


def test_json_output_is_a_document_with_every_entry_and_integer_line_counts(
    source: Path, target: Path, answers: Path, capsys
) -> None:
    code, out, _ = _adopt(source, target, answers, "--json", capsys=capsys)
    assert code == 0
    data = json.loads(out)
    by_path = {e["path"]: e for e in data["entries"]}
    assert by_path["tools/same.py"]["state"] == "identical"
    assert (by_path["tools/local.py"]["added"], by_path["tools/local.py"]["removed"]) == (1, 2)
    assert by_path["tools/new.py"]["state"] == "missing"
    assert by_path["README.md"]["state"] == "seed-present"
    assert data["counts"]["differs"] == 2


def test_no_answers_and_no_terminal_is_a_refusal(source: Path, target: Path, capsys) -> None:
    code = ini.main(["adopt", "--target", str(target)], source=source, runner=GitRunner())
    err = capsys.readouterr().err
    assert code == 1
    assert "no --answers file" in err


def test_the_json_flag_is_for_the_report_not_for_apply(source: Path, target: Path, answers: Path, capsys) -> None:
    code, _, err = _adopt(source, target, answers, "--apply", "--json", capsys=capsys)
    assert code == 1
    assert "--json is for the report" in err


# ---- what the planner must refuse because it is not the project's to touch
def test_a_stale_lock_makes_adopt_refuse_and_the_projects_file_is_not_replaced(
    source: Path, target: Path, answers: Path, capsys
) -> None:
    """With a lock that matches ``tools/local.py``, ``plan_new`` would update it: adopt must never get there."""
    template = PAYLOAD_FILES["tools/local.py"].encode()
    (target / "tools/local.py").write_bytes(template)
    lock = {
        "template_version": VERSION,
        "initialised": "2026-10-01",
        "files": {"tools/local.py": ini.lock_hash(template)},
    }
    _write(target, {"framework.lock": json.dumps(lock)})
    before = _snapshot(target)
    code, _, err = _adopt(source, target, answers, "--apply", capsys=capsys)
    assert code == 1
    assert "already has a framework.lock" in err
    assert _snapshot(target) == before


def test_a_symlinked_folder_that_leaves_the_target_blocks_everything_written_through_it(
    source: Path, target: Path, answers: Path, tmp_path: Path, capsys
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("not the project's", encoding="utf-8")
    shutil.rmtree(target / "tools")
    _symlink(target / "tools", outside)
    code, out, _ = _adopt(source, target, answers, "--apply", capsys=capsys)
    assert code == 1
    assert "symlink that leaves the target" in out
    assert sorted(p.name for p in outside.iterdir()) == ["keep.txt"]  # nothing was written through the link
    assert not (target / "framework.lock").exists()


def test_take_never_writes_through_a_symlinked_folder(
    source: Path, target: Path, answers: Path, tmp_path: Path, capsys
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "local.py").write_text("outside", encoding="utf-8")
    shutil.rmtree(target / "tools")
    _symlink(target / "tools", outside)
    code, _, _ = _adopt(source, target, answers, "--apply", "--take", "tools/local.py", capsys=capsys)
    assert code == 1
    assert (outside / "local.py").read_text(encoding="utf-8") == "outside"


def _case_insensitive(folder: Path) -> bool:
    probe = folder / "CaseProbe.txt"
    probe.write_text("x", encoding="utf-8")
    try:
        return (folder / "caseprobe.txt").exists()
    finally:
        probe.unlink()


def test_a_name_that_differs_only_in_capitalisation_is_blocked_not_written_beside(
    source: Path, target: Path, answers: Path, tmp_path: Path, capsys
) -> None:
    if not _case_insensitive(tmp_path):
        pytest.skip("this file system is case-sensitive: the two names are two files")
    shutil.rmtree(target / "Docs")
    (target / "docs").mkdir()
    (target / "docs/glossary.md").write_text("the project's", encoding="utf-8")
    code, out, _ = _adopt(source, target, answers, capsys=capsys)
    assert code == 1
    assert "differs only in capitalisation" in out


def test_an_existing_file_keeps_its_permissions_when_the_template_s_is_taken(
    source: Path, target: Path, answers: Path
) -> None:
    if os.name == "nt":
        pytest.skip("POSIX permission bits")
    (target / "tools/local.py").chmod(0o755)
    _adopt(source, target, answers, "--apply", "--take", "tools/local.py")
    assert (target / "tools/local.py").stat().st_mode & 0o777 == 0o755


# ---- --apply: what it refuses
def test_apply_refuses_a_target_that_is_not_a_git_working_tree(
    source: Path, target: Path, answers: Path, capsys
) -> None:
    before = _snapshot(target)
    code, _, err = _adopt(source, target, answers, "--apply", runner=GitRunner(code=128), capsys=capsys)
    assert code == 1
    assert "not a git working tree" in err
    assert _snapshot(target) == before


def test_apply_refuses_a_target_that_is_inside_a_larger_repository(
    source: Path, target: Path, answers: Path, capsys
) -> None:
    code, _, err = _adopt(
        source, target, answers, "--apply", runner=GitRunner(toplevel=str(target.parent)), capsys=capsys
    )
    assert code == 1
    assert "inside a larger git repository" in err


def test_apply_refuses_a_dirty_working_tree_so_the_adoption_is_one_diff(
    source: Path, target: Path, answers: Path, capsys
) -> None:
    before = _snapshot(target)
    code, _, err = _adopt(
        source, target, answers, "--apply", runner=GitRunner(status=" M tools/local.py\n"), capsys=capsys
    )
    assert code == 1
    assert "uncommitted changes" in err
    assert _snapshot(target) == before


def test_the_git_status_call_cannot_run_a_command_or_take_a_lock(source: Path, target: Path, answers: Path) -> None:
    runner = GitRunner()
    _adopt(source, target, answers, "--apply", runner=runner)
    status = next(call for call in runner.calls if "status" in call)
    assert "--no-optional-locks" in status
    assert "core.fsmonitor=" in status


def test_apply_refuses_when_the_gitignore_would_hide_what_it_writes(
    source: Path, target: Path, answers: Path, capsys
) -> None:
    before = _snapshot(target)
    runner = GitRunner(ignored=("framework.lock", "tools/new.py"))
    code, _, err = _adopt(source, target, answers, "--apply", runner=runner, capsys=capsys)
    assert code == 1
    assert ".gitignore" in err
    assert _snapshot(target) == before


def test_a_dry_run_warns_about_ignored_paths_without_failing(source: Path, target: Path, answers: Path, capsys) -> None:
    code, out, _ = _adopt(source, target, answers, runner=GitRunner(ignored=("framework.lock",)), capsys=capsys)
    assert code == 0
    assert "the target's .gitignore would hide these from a commit: framework.lock" in out


def test_apply_refuses_when_something_is_blocked_and_writes_nothing(
    source: Path, target: Path, answers: Path, capsys
) -> None:
    (target / "tools/new.py").mkdir()
    before = _snapshot(target)
    code, _, _ = _adopt(source, target, answers, "--apply", capsys=capsys)
    assert code == 1
    assert _snapshot(target) == before


def test_take_must_name_a_differing_file_even_in_a_dry_run(source: Path, target: Path, answers: Path, capsys) -> None:
    for bad in ("tools/same.py", "tools/nonexistent.py", "../outside.py", "README.md"):
        for extra in (("--apply",), ()):
            before = _snapshot(target)
            code, _, err = _adopt(source, target, answers, *extra, "--take", bad, capsys=capsys)
            assert code == 1, (bad, extra)
            assert "--take" in err
            assert _snapshot(target) == before


# ---- --apply: what it does
def test_adopt_with_a_login_in_its_answers_seeds_no_roster(source: Path, target: Path, tmp_path: Path) -> None:
    answers = tmp_path / "answers-login.json"
    answers.write_text(json.dumps({**ANSWERS, "owner": {**ANSWERS["owner"], "login": "ada"}}), encoding="utf-8")
    code, _, _ = _adopt(source, target, answers, "--apply")
    assert code == 0
    assert "[[people]]" not in (target / "framework.toml").read_text(encoding="utf-8")


def test_apply_adds_what_is_missing_and_never_touches_what_the_project_owns(
    source: Path, target: Path, answers: Path
) -> None:
    before = _snapshot(target)
    code, _, _ = _adopt(source, target, answers, "--apply")
    assert code == 0
    after = _snapshot(target)
    assert after["tools/new.py"] == b"print('new in the template')\n"  # added
    assert after["pyproject.toml"] == b"[project]\nname = " + b'"old-project"\n'  # a seed, since absent
    assert after["tools/local.py"] == before["tools/local.py"]  # a differing file is left as it is
    assert after["Docs/glossary.md"] == before["Docs/glossary.md"]
    assert after["README.md"] == before["README.md"]  # a present seed is never touched
    assert after["src/product.py"] == before["src/product.py"]
    assert "lanes/lane.md" not in after  # a module that is off leaves nothing
    assert {"project.json", "framework.toml", "framework.lock"} <= set(after)


def test_apply_records_an_override_with_a_reason_for_each_differing_file(
    source: Path, target: Path, answers: Path
) -> None:
    _adopt(source, target, answers, "--apply")
    config = fc.load_framework(target / "framework.toml")
    assert {o.target: o.reason for o in config.overrides} == {
        "Docs/glossary.md": f"adopted: differs from template {VERSION}; reconcile",
        "tools/local.py": f"adopted: differs from template {VERSION}; reconcile",
    }


def test_apply_locks_the_templates_hash_for_every_managed_file_including_the_overridden_ones(
    source: Path, target: Path, answers: Path
) -> None:
    _adopt(source, target, answers, "--apply")
    lock = json.loads((target / "framework.lock").read_text(encoding="utf-8"))
    assert lock["template_version"] == VERSION
    assert lock["files"]["tools/local.py"] == ini.lock_hash(PAYLOAD_FILES["tools/local.py"].encode())
    assert lock["files"]["tools/same.py"] == ini.lock_hash(PAYLOAD_FILES["tools/same.py"].encode())
    assert "README.md" not in lock["files"] and "pyproject.toml" not in lock["files"]  # seeds are not locked


def test_the_sync_check_passes_on_the_day_of_adoption_and_lists_the_debt(
    source: Path, target: Path, answers: Path
) -> None:
    _adopt(source, target, answers, "--apply")
    result = fs.report(target)
    assert result.findings == []
    assert sorted(path for path, _ in result.honoured) == ["Docs/glossary.md", "tools/local.py"]


def test_take_overwrites_the_named_file_with_the_templates_and_records_no_override_for_it(
    source: Path, target: Path, answers: Path
) -> None:
    _adopt(source, target, answers, "--apply", "--take", "tools/local.py")
    assert (target / "tools/local.py").read_bytes() == PAYLOAD_FILES["tools/local.py"].encode()
    assert (target / "Docs/glossary.md").read_text(encoding="utf-8").endswith("the project's own terms\n")
    assert [o.target for o in fc.load_framework(target / "framework.toml").overrides] == ["Docs/glossary.md"]
    assert fs.report(target).findings == []


def test_take_all_overwrites_every_differing_file_and_leaves_no_override(
    source: Path, target: Path, answers: Path
) -> None:
    _adopt(source, target, answers, "--apply", "--take-all")
    assert (target / "Docs/glossary.md").read_text(encoding="utf-8") == PAYLOAD_FILES["Docs/glossary.md"]
    assert fc.load_framework(target / "framework.toml").overrides == ()
    assert fs.report(target).honoured == []


def test_apply_commits_nothing_and_asks_git_only_to_look(source: Path, target: Path, answers: Path) -> None:
    runner = GitRunner()
    _adopt(source, target, answers, "--apply", runner=runner)
    assert runner.calls
    assert {
        next(word for word in call if word in ("rev-parse", "status", "check-ignore")) for call in runner.calls
    } == {
        "rev-parse",
        "status",
        "check-ignore",
    }


def test_the_apply_prints_what_to_do_next_and_the_overrides_to_reconcile(
    source: Path, target: Path, answers: Path, capsys
) -> None:
    code, out, _ = _adopt(source, target, answers, "--apply", capsys=capsys)
    assert code == 0
    assert "2 override(s) recorded" in out
    assert "reconcile" in out
    assert "nothing was committed" in out


def test_apply_leaves_a_log_of_every_write_take_and_override(
    source: Path, target: Path, answers: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level("INFO", logger="tools.init_adopt"):
        _adopt(source, target, answers, "--apply", "--take", "tools/local.py")
    messages = [r.getMessage() for r in caplog.records]
    assert any(m.startswith("wrote tools/new.py (") for m in messages)
    assert any(m.startswith("took the template's tools/local.py (") for m in messages)
    assert any(m.startswith("override recorded: Docs/glossary.md: adopted: differs") for m in messages)


def test_init_new_over_an_adopted_repository_changes_nothing(source: Path, target: Path, answers: Path) -> None:
    """The overrides and the lock ``adopt`` leaves are exactly what the idempotent ``init new`` accepts."""
    _adopt(source, target, answers, "--apply")
    before = _snapshot(target)
    code = ini.main(
        ["new", "--answers", str(answers), "--target", str(target), "--no-sync", "--no-checks"],
        source=source,
        today="2026-10-16",
    )
    assert code == 0
    assert {k: v for k, v in _snapshot(target).items() if not k.startswith("logs/")} == before


def test_a_second_adopt_is_refused_because_the_repository_is_now_adopted(
    source: Path, target: Path, answers: Path, capsys
) -> None:
    _adopt(source, target, answers, "--apply")
    capsys.readouterr()
    code, _, err = _adopt(source, target, answers, "--apply", capsys=capsys)
    assert code == 1
    assert "already has a framework.toml" in err


# ---- the order of the writes, and what a failure leaves
class Writes:
    """Records the order of ``write_atomic`` calls, failing at the ``fail_at``-th (1-based) if asked."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, fail_at: int | None = None) -> None:
        self.real, self.fail_at, self.paths = ini.write_atomic, fail_at, []
        monkeypatch.setattr(ini, "write_atomic", self)

    def __call__(self, dest: Path, data: bytes, **kwargs) -> None:
        self.paths.append(dest.name)
        if self.fail_at == len(self.paths):
            raise OSError(28, "No space left on device")
        self.real(dest, data, **kwargs)


def test_the_lock_is_written_last_and_framework_toml_just_before_it(
    source: Path, target: Path, answers: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    writes = Writes(monkeypatch)
    _adopt(source, target, answers, "--apply")
    assert writes.paths[-2:] == ["framework.toml", "framework.lock"]
    assert writes.paths.index("project.json") < writes.paths.index("framework.toml")


def test_a_failure_at_any_write_leaves_no_lock_and_says_how_to_recover(
    source: Path, target: Path, answers: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    before = _snapshot(target)
    total = len(Writes(monkeypatch).paths) or 0
    monkeypatch.undo()
    probe = Writes(monkeypatch)
    _adopt(source, target, answers, "--apply")
    count = len(probe.paths)
    monkeypatch.undo()
    shutil.rmtree(target)
    _write(target, TARGET_FILES)
    assert total == 0 and count >= 6
    for fail_at in (1, count // 2, count - 1, count):
        Writes(monkeypatch, fail_at)
        code, _, err = _adopt(source, target, answers, "--apply", capsys=capsys)
        monkeypatch.undo()
        assert code == 2, fail_at
        assert "No space left" in err
        assert "git stash -u" in err
        assert not (target / "framework.lock").exists()
        shutil.rmtree(target)  # what git stash -u / git clean does
        _write(target, TARGET_FILES)
    assert _snapshot(target) == before
    assert _adopt(source, target, answers, "--apply")[0] == 0  # after the restore a re-run is clean


def test_a_file_that_appears_after_the_plan_was_made_is_not_replaced(
    source: Path, target: Path, answers: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    real = ad._git_problem

    def appears(runner, folder):
        (folder / "tools").mkdir(exist_ok=True)
        (folder / "tools/new.py").write_text("made while the git check was running", encoding="utf-8")
        return real(runner, folder)

    monkeypatch.setattr(ad, "_git_problem", appears)
    code, _, err = _adopt(source, target, answers, "--apply", capsys=capsys)
    assert code == 2
    assert "appeared after the plan was made" in err
    assert (target / "tools/new.py").read_text(encoding="utf-8") == "made while the git check was running"
    assert not (target / "framework.lock").exists()


def test_a_framework_toml_that_cannot_be_dumped_is_exit_2_not_a_traceback(
    source: Path, target: Path, answers: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    def broken(config):
        raise fc.ConfigError("layers.order", "must not be empty")

    monkeypatch.setattr(fc, "dump_framework", broken)
    code, _, err = _adopt(source, target, answers, "--apply", capsys=capsys)
    assert code == 2
    assert "invalid" in err
    assert not (target / "framework.lock").exists()


def test_the_sync_check_is_run_on_the_result_and_its_findings_fail_the_adoption(
    source: Path, target: Path, answers: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    real = fs.report
    calls: list[Path] = []

    def spy(root: Path):
        calls.append(root)
        return real(root)

    monkeypatch.setattr(fs, "report", spy)
    code, out, _ = _adopt(source, target, answers, "--apply", capsys=capsys)
    assert code == 0
    assert calls == [target.resolve()]
    assert "sync check on the result: clean" in out

    def broken(root: Path):
        return fs.Report([fs.Finding("edited", "tools/x.py", "differs from the lock")], [])

    other = target.parent / "second"
    _write(other, TARGET_FILES)
    monkeypatch.setattr(fs, "report", broken)
    code, out, err = _adopt(source, other, answers, "--apply", capsys=capsys)
    assert code == 2
    assert "[edited] tools/x.py" in err
    assert "sync check on the result: 1 finding(s)" in out


def test_a_sync_check_that_cannot_run_is_exit_2_not_a_traceback(
    source: Path, target: Path, answers: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    def boom(root: Path):
        raise fc.ConfigError("<file>", "cannot be read")

    monkeypatch.setattr(fs, "report", boom)
    code, _, err = _adopt(source, target, answers, "--apply", capsys=capsys)
    assert code == 2
    assert "could not run" in err


# ---- --off
def test_off_leaves_a_module_out_of_the_report_and_out_of_the_files_written(
    source: Path, target: Path, answers: Path, capsys
) -> None:
    _, out, _ = _adopt(source, target, answers, "-v", "--off", "specimens", capsys=capsys)
    assert _states(out)["specimens/a.md"] == "skipped"
    assert "off: specimens" in out
    code, _, _ = _adopt(source, target, answers, "--apply", "--off", "specimens")
    assert code == 0
    assert (target / "specimens").exists() is False
    assert fc.load_framework(target / "framework.toml").modules["specimens"] == "off"
    assert fs.report(target).findings == []


def test_init_new_over_an_adopted_repository_with_a_module_off_changes_nothing(
    source: Path, target: Path, answers: Path
) -> None:
    assert _adopt(source, target, answers, "--apply", "--off", "specimens")[0] == 0
    before = _snapshot(target)
    code = ini.main(
        ["new", "--answers", str(answers), "--target", str(target), "--no-sync", "--no-checks"],
        source=source,
        today="2026-10-16",
    )
    assert code == 0
    assert {k: v for k, v in _snapshot(target).items() if not k.startswith("logs/")} == before


def test_a_root_src_is_reported_as_layout_debt_naming_the_guide(
    source: Path, target: Path, answers: Path, capsys
) -> None:
    _write(target, {"src/zeta/__init__.py": "", "src/alpha/__init__.py": ""})
    code, out, _ = _adopt(source, target, answers, capsys=capsys)
    assert code == 0
    debt = [line for line in out.splitlines() if line.startswith("layout debt")]
    assert len(debt) == 1 and "src/ has 3 packages (alpha, product, zeta)" in debt[0]
    assert "legacy-src" in out and '"0.7.0: the repository layout"' in out
    assert out.index("layout debt") < out.index("dry run: nothing written")


def test_the_json_report_carries_the_layout_debt(source: Path, target: Path, answers: Path, capsys) -> None:
    code, out, _ = _adopt(source, target, answers, "--json", capsys=capsys)
    assert code == 0 and json.loads(out)["layout_debt"] == ["product"]


VIRTUAL_ROOT = "[tool.uv.workspace]\nmembers = []\n"  # a 0.7.0 root: it builds nothing, so legacy-root has no say


def test_turning_specimens_off_writes_no_layers_from_a_root_src(
    source: Path, target: Path, answers: Path, capsys
) -> None:
    _write(target, {"src/zeta/__init__.py": "", "src/alpha/__init__.py": "", "src/zeta/x.py": "import alpha\n"})
    _write(target, {"pyproject.toml": VIRTUAL_ROOT})  # so legacy-src alone is in question, not the stand-in seed
    code, out, _ = _adopt(source, target, answers, "--apply", "--off", "specimens", capsys=capsys)
    assert code == 0
    assert fc.load_framework(target / "framework.toml").layers is None
    assert "src/ is layout debt, so no [layers] was written from it" in out
    found = [str(f) for f in bd.scan_workspace(target, None)]
    assert found and all(f.startswith("[legacy-src] src/") for f in found), found  # the gate says what to move


def test_turning_specimens_off_writes_layers_from_the_targets_members(
    source: Path, target: Path, answers: Path, capsys
) -> None:
    shutil.rmtree(target / "src")
    _write(
        target,
        {
            "pyproject.toml": '[tool.uv.workspace]\nmembers = ["apps/*", "packages/python/*"]\n',
            "apps/tool/pyproject.toml": (
                '[project]\nname = "tool"\nauthors = [{ name = "Ada", email = "ada@example.org" }]\n'
                'dependencies = ["lib"]\n'
            ),
            "apps/tool/src/tool/__init__.py": "import lib\n",
            "packages/python/lib/pyproject.toml": (
                '[project]\nname = "lib"\nauthors = [{ name = "Ada", email = "ada@example.org" }]\n'
            ),
            "packages/python/lib/src/lib/__init__.py": "",
        },
    )
    code, out, _ = _adopt(source, target, answers, "--apply", "--off", "specimens", "--take-all", capsys=capsys)
    assert code == 0, out
    layers = fc.load_framework(target / "framework.toml").layers
    assert layers is not None and layers.order == ("lib", "tool")
    assert "from the packages of the workspace's members (lib, tool) in alphabetical order, a placeholder" in out
    assert bd.scan_workspace(target, layers) == []


def test_turning_specimens_off_with_no_src_writes_no_layers_table(
    source: Path, target: Path, answers: Path, capsys
) -> None:
    shutil.rmtree(target / "src")
    _write(target, {"pyproject.toml": VIRTUAL_ROOT})  # the stand-in seed builds a project; the real seed is virtual
    code, out, _ = _adopt(source, target, answers, "--apply", "--off", "specimens", capsys=capsys)
    assert code == 0
    assert fc.load_framework(target / "framework.toml").layers is None
    assert "no [layers] table was written" in out
    assert bd.scan_workspace(target, None) == []


def test_with_specimens_on_the_seeded_layers_are_kept(source: Path, target: Path, answers: Path) -> None:
    _adopt(source, target, answers, "--apply")
    layers = fc.load_framework(target / "framework.toml").layers
    assert layers is not None and layers.order == ("core", "app")


@pytest.mark.parametrize("bad", ["core", "nonsense", "Python-UV", "lanes"])
def test_off_refuses_core_unknown_names_and_modules_that_are_not_on(
    source: Path, target: Path, answers: Path, capsys, bad: str
) -> None:
    before = _snapshot(target)
    code, _, err = _adopt(source, target, answers, "--apply", "--off", bad, capsys=capsys)
    assert code == 1
    assert "--off names" in err
    assert _snapshot(target) == before


# ---- against a real git repository
@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_with_real_git_a_clean_tree_is_adopted_and_a_dirty_one_is_refused(
    source: Path, target: Path, answers: Path, capsys
) -> None:
    def git(*args: str) -> None:
        subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@e.x", *args], cwd=target, check=True, capture_output=True
        )

    git("init", "-q")
    git("add", "-A")
    git("commit", "-qm", "the project before the template")
    (target / "scratch.txt").write_text("uncommitted", encoding="utf-8")
    code, _, err = _adopt(source, target, answers, "--apply", runner=ini.quiet_runner, capsys=capsys)
    assert code == 1
    assert "uncommitted changes" in err
    (target / "scratch.txt").unlink()
    code, _, _ = _adopt(source, target, answers, "--apply", runner=ini.quiet_runner, capsys=capsys)
    assert code == 0
    assert fs.report(target).findings == []


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_with_real_git_a_gitignore_that_hides_the_lock_is_caught_and_a_subfolder_is_refused(
    source: Path, target: Path, answers: Path, capsys
) -> None:
    def git(*args: str) -> None:
        subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@e.x", *args], cwd=target, check=True, capture_output=True
        )

    (target / ".gitignore").write_text("*.lock\n.claude/\n", encoding="utf-8")
    git("init", "-q")
    git("add", "-A")
    git("commit", "-qm", "before")
    code, _, err = _adopt(source, target, answers, "--apply", runner=ini.quiet_runner, capsys=capsys)
    assert code == 1
    assert ".gitignore" in err
    sub = target / "sub"
    sub.mkdir()
    _write(sub, {"a.txt": "x"})
    git("add", "-A")
    git("commit", "-qm", "sub")
    code, _, err = _adopt(source, sub, answers, "--apply", runner=ini.quiet_runner, capsys=capsys)
    assert code == 1
    assert "inside a larger git repository" in err


# ---- survivors of the hardened mutation table
def test_a_file_whose_name_differs_only_in_capitalisation_is_blocked_too(
    source: Path, target: Path, answers: Path, tmp_path: Path, capsys
) -> None:
    if not _case_insensitive(tmp_path):
        pytest.skip("this file system is case-sensitive: the two names are two files")
    (target / "tools/local.py").unlink()
    (target / "tools/Local.py").write_text("the project's", encoding="utf-8")
    code, out, _ = _adopt(source, target, answers, capsys=capsys)
    assert code == 1
    assert "'Local.py', which differs only in capitalisation" in out


def test_a_refusal_that_names_no_file_is_a_blocked_entry_with_no_path(
    source: Path, target: Path, answers: Path, capsys
) -> None:
    """A module the seeded documents link to cannot be off; the refusal is about a setting, not a file."""
    code, out, _ = _adopt(source, target, answers, "--off", "python-uv", "--json", capsys=capsys)
    assert code == 1
    blocked = [e for e in json.loads(out)["entries"] if e["state"] == "blocked"]
    assert [e["path"] for e in blocked] == ["-"]
    assert "python-uv" in blocked[0]["detail"]


def test_a_file_too_large_to_diff_is_said_so_and_counted_as_neither_added_nor_removed(
    source: Path, target: Path, answers: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.setattr(ad, "DIFF_LIMIT", 10)
    _, out, _ = _adopt(source, target, answers, "--json", capsys=capsys)
    entry = next(e for e in json.loads(out)["entries"] if e["path"] == "tools/local.py")
    assert (entry["detail"], entry["added"], entry["removed"]) == ("large file", None, None)


def test_a_plan_action_adopt_cannot_classify_is_an_error_not_a_quiet_blocked_entry(
    source: Path, target: Path, answers: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = ini.plan_new

    def with_update(*args, **kwargs):
        plan = real(*args, **kwargs)
        plan.actions.append(ini.Action("tools/odd.py", "update", "managed", "core"))
        return plan

    monkeypatch.setattr(ini, "plan_new", with_update)
    project = fc.load_answers(target.parent / "answers.json")
    with pytest.raises(RuntimeError, match="cannot classify the plan's action 'update' for tools/odd.py"):
        ad.plan_adopt(source, target, project, "2026-10-16")


# ---- Copilot's review of the pull request
@pytest.mark.parametrize(
    ("old", "new", "counts"),
    [
        (b"a\n---\nb\n", b"a\n++\nb\n", (1, 1)),  # a Markdown rule replaced: its '---' is content, not a header
        (b"a\n+++\nb\n", b"a\nb\n", (0, 1)),
        (b"a\nb\n", b"a\n---\n+++\nb\n", (2, 0)),
        (b"same\n", b"same\n", (0, 0)),
    ],
)
def test_the_line_counts_include_lines_that_look_like_diff_headers(
    old: bytes, new: bytes, counts: tuple[int, int]
) -> None:
    added, removed, _ = ad._diff_counts(old, new)
    assert (added, removed) == counts


def test_a_managed_symlink_whose_target_matches_the_template_is_a_difference_and_the_apply_passes_the_check(
    source: Path, target: Path, answers: Path, capsys
) -> None:
    (target / "tools/same.py").unlink()
    (target / "elsewhere.py").write_bytes(PAYLOAD_FILES["tools/same.py"].encode())
    _symlink(target / "tools/same.py", target / "elsewhere.py")
    _, out, _ = _adopt(source, target, answers, "--json", capsys=capsys)
    entry = next(e for e in json.loads(out)["entries"] if e["path"] == "tools/same.py")
    assert (entry["state"], entry["detail"]) == ("differs", "a symlink")
    code, _, _ = _adopt(source, target, answers, "--apply")
    assert code == 0
    assert "tools/same.py" in [o.target for o in fc.load_framework(target / "framework.toml").overrides]
    assert fs.report(target).findings == []
    assert (target / "tools/same.py").is_symlink()  # preserved, with an override


def test_take_replaces_a_symlink_with_the_templates_file_and_leaves_what_it_pointed_at(
    source: Path, target: Path, answers: Path
) -> None:
    (target / "tools/same.py").unlink()
    (target / "elsewhere.py").write_bytes(PAYLOAD_FILES["tools/same.py"].encode())
    _symlink(target / "tools/same.py", target / "elsewhere.py")
    code, _, _ = _adopt(source, target, answers, "--apply", "--take", "tools/same.py")
    assert code == 0
    assert not (target / "tools/same.py").is_symlink()
    assert (target / "tools/same.py").read_bytes() == PAYLOAD_FILES["tools/same.py"].encode()
    assert (target / "elsewhere.py").read_bytes() == PAYLOAD_FILES["tools/same.py"].encode()
    assert fs.report(target).findings == []


def test_git_status_is_asked_for_untracked_files_and_submodules_whatever_the_users_settings(
    source: Path, target: Path, answers: Path
) -> None:
    runner = GitRunner()
    _adopt(source, target, answers, "--apply", runner=runner)
    status = next(call for call in runner.calls if "status" in call)
    assert "--untracked-files=all" in status
    assert "--ignore-submodules=none" in status


def test_check_ignore_is_asked_without_no_index_so_a_tracked_file_that_matches_a_rule_is_not_a_reason_to_refuse(
    source: Path, target: Path, answers: Path
) -> None:
    runner = GitRunner()
    _adopt(source, target, answers, "--apply", runner=runner)
    call = next(call for call in runner.calls if "check-ignore" in call)
    assert "--no-index" not in call


@pytest.mark.parametrize("code", [128, 2, 129])
def test_a_check_ignore_that_fails_refuses_the_apply_and_a_dry_run_carries_on(
    source: Path, target: Path, answers: Path, capsys, code: int
) -> None:
    before = _snapshot(target)
    result, _, err = _adopt(source, target, answers, "--apply", runner=GitRunner(ignore_code=code), capsys=capsys)
    assert result == 1
    assert "could not be checked" in err and "git check-ignore failed" in err
    assert _snapshot(target) == before
    assert _adopt(source, target, answers, runner=GitRunner(ignore_code=code))[0] == 0


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_with_real_git_untracked_work_is_seen_even_when_hidden_and_a_tracked_ignored_file_can_be_taken(
    source: Path, target: Path, answers: Path, capsys
) -> None:
    def git(*args: str) -> None:
        subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@e.x", *args], cwd=target, check=True, capture_output=True
        )

    (target / ".gitignore").write_text("tools/local.py\n", encoding="utf-8")  # a broad rule over a tracked file
    git("init", "-q")
    git("add", "-A")
    git("add", "-f", "tools/local.py")
    git("commit", "-qm", "before")
    git("config", "status.showUntrackedFiles", "no")
    (target / "scratch.txt").write_text("someone's work", encoding="utf-8")
    code, _, err = _adopt(source, target, answers, "--apply", runner=ini.quiet_runner, capsys=capsys)
    assert code == 1
    assert "uncommitted changes" in err
    (target / "scratch.txt").unlink()
    extra = ("--apply", "--take", "tools/local.py")
    code, _, err = _adopt(source, target, answers, *extra, runner=ini.quiet_runner, capsys=capsys)
    assert code == 0, err
    assert (target / "tools/local.py").read_bytes() == PAYLOAD_FILES["tools/local.py"].encode()


# ---- the seed ADR-001 and a repository that has its own ADR number 1
DECISIONS_MANIFEST = (
    MANIFEST
    + """
[[rule]]
pattern = "Docs/decisions/*"
module = "core"
kind = "project-owned"
"""
)
SEED_ADR = "Docs/decisions/ADR-001-adopt-the-framework.md"
SEED_INDEX = "Docs/decisions/README.md"
INDEX_ROW = "| [ADR-001](ADR-001-adopt-the-framework.md) | Adopt the framework | Accepted |\n"


@pytest.fixture
def decisions_source(tmp_path: Path) -> Path:
    """A payload that seeds the decisions index and ADR-001, as the real one does."""
    src = tmp_path / "payload-decisions"
    files = {
        **PAYLOAD_FILES,
        SEED_ADR: "# ADR-001\n\n**Status:** Accepted.\n",
        SEED_INDEX: "# Decisions\n\n| ADR | Decision | Status |\n| --- | --- | --- |\n" + INDEX_ROW,
    }
    _write(src, {"framework-manifest.toml": DECISIONS_MANIFEST, "framework.toml": _framework_text(), **files})
    return src


def test_a_repository_with_no_adrs_is_seeded_adr_001_and_its_index_row(
    decisions_source: Path, target: Path, answers: Path, capsys
) -> None:
    code, out, _ = _adopt(decisions_source, target, answers, "--apply", "-v", capsys=capsys)
    assert code == 0
    assert (target / SEED_ADR).is_file()
    assert INDEX_ROW in (target / SEED_INDEX).read_text(encoding="utf-8")
    assert _states(out)[SEED_ADR] == "seed-absent"


@pytest.mark.parametrize("own", ["Docs/decisions/ADR-001-something-else.md", "Docs/decisions/adr-1-x.md"])
def test_a_repository_with_its_own_adr_number_1_is_not_seeded_a_second_one(
    decisions_source: Path, target: Path, answers: Path, capsys, own: str
) -> None:
    """The seed is reported seed-present with the note, the seeded index has no row for it, and the target's ADR is
    untouched: two files with one id would fail adr-duplicate at the first gate."""
    _write(target, {own: "# The project's first decision\n\n**Status:** Accepted.\n"})
    code, out, _ = _adopt(decisions_source, target, answers, "--apply", "-v", capsys=capsys)
    assert code == 0, out
    assert not (target / SEED_ADR).exists()
    assert (target / own).read_text(encoding="utf-8").startswith("# The project's first decision")
    index = (target / SEED_INDEX).read_text(encoding="utf-8")
    assert INDEX_ROW not in index and index.startswith("# Decisions")
    assert _states(out)[SEED_ADR] == "seed-present"
    assert "has its own ADR number 1" in out and own in out and "dated ADR" in out


def test_a_repository_with_its_own_index_and_adr_number_1_keeps_both(
    decisions_source: Path, target: Path, answers: Path, capsys
) -> None:
    mine = "# My decisions\n\n| ADR | Decision |\n| --- | --- |\n| [1](ADR-001-mine.md) | Mine |\n"
    _write(target, {"Docs/decisions/ADR-001-mine.md": "# Mine\n", SEED_INDEX: mine})
    code, out, _ = _adopt(decisions_source, target, answers, "--apply", "-v", capsys=capsys)
    assert code == 0, out
    assert (target / SEED_INDEX).read_text(encoding="utf-8") == mine
    assert not (target / SEED_ADR).exists()
    states = _states(out)
    assert states[SEED_ADR] == "seed-present" and states[SEED_INDEX] == "seed-present"


def test_a_dry_run_reports_the_withheld_seed_and_writes_nothing(
    decisions_source: Path, target: Path, answers: Path, capsys
) -> None:
    _write(target, {"Docs/decisions/ADR-001-mine.md": "# Mine\n"})
    before = _snapshot(target)
    code, out, _ = _adopt(decisions_source, target, answers, "-v", capsys=capsys)
    assert code == 0 and _snapshot(target) == before
    assert _states(out)[SEED_ADR] == "seed-present" and "has its own ADR number 1" in out


def test_an_adr_number_1_below_the_decisions_directory_counts_too(
    decisions_source: Path, target: Path, answers: Path, capsys
) -> None:
    _write(target, {"Docs/decisions/old/ADR-001-mine.md": "# Mine\n"})
    _, out, _ = _adopt(decisions_source, target, answers, "-v", capsys=capsys)
    assert _states(out)[SEED_ADR] == "seed-present"


def test_an_adr_with_another_number_does_not_withhold_the_seed(
    decisions_source: Path, target: Path, answers: Path, capsys
) -> None:
    _write(target, {"Docs/decisions/ADR-002-mine.md": "# Mine\n"})
    _, out, _ = _adopt(decisions_source, target, answers, "-v", capsys=capsys)
    assert _states(out)[SEED_ADR] == "seed-absent"


JOURNAL_SEED = "Docs/journal/{{today}}-session-01.md"
JOURNAL_MANIFEST = (
    DECISIONS_MANIFEST
    + """
[[rule]]
pattern = "Docs/journal/*"
module = "core"
kind = "project-owned"
"""
)


@pytest.fixture
def journal_source(tmp_path: Path) -> Path:
    """The decisions payload plus the journal seed, which links the seed ADR as the real one does."""
    src = tmp_path / "payload-journal"
    files = {
        **PAYLOAD_FILES,
        SEED_ADR: "# ADR-001\n\n**Status:** Accepted.\n",
        SEED_INDEX: "# Decisions\n\n| ADR | Decision | Status |\n| --- | --- | --- |\n" + INDEX_ROW,
        JOURNAL_SEED: "# Session 01\n\nDay 0. See [ADR-001](../decisions/ADR-001-adopt-the-framework.md).\n",
    }
    _write(src, {"framework-manifest.toml": JOURNAL_MANIFEST, "framework.toml": _framework_text(), **files})
    return src


def test_a_seed_that_links_the_withheld_adr_links_the_decisions_index_instead(
    journal_source: Path, target: Path, answers: Path, capsys
) -> None:
    """The journal seed would otherwise carry a dangling link and fail the links check at the first gate."""
    _write(target, {"Docs/decisions/ADR-001-mine.md": "# Mine\n"})
    code, out, _ = _adopt(journal_source, target, answers, "--apply", "-v", capsys=capsys)
    assert code == 0, out
    journal = (target / "Docs/journal/2026-10-16-session-01.md").read_text(encoding="utf-8")
    assert "[ADR-001](../decisions/README.md)" in journal and "adopt-the-framework" not in journal
    assert "Docs/journal/2026-10-16-session-01.md" in out and "links the decisions index" in out


MANAGED_NAMING_THE_SEED = "tools/names_the_seed.py"
MANAGED_TEXT = 'ADR_SEED = "Docs/decisions/ADR-001-adopt-the-framework.md"  # as tools/init_adopt.py names it\n'


def test_a_managed_file_that_names_the_withheld_adr_keeps_its_bytes(
    journal_source: Path, target: Path, answers: Path, capsys
) -> None:
    """The rewrite once reached managed files (the real payload's own tools/init_adopt.py among them), whose lock
    hashes still describe the template's bytes, so the adopted repository failed its first sync check. Only a
    project-owned seed is rewritten; a managed file arrives as the template ships it."""
    _write(journal_source, {MANAGED_NAMING_THE_SEED: MANAGED_TEXT})
    _write(target, {"Docs/decisions/ADR-001-mine.md": "# Mine\n"})
    code, out, _ = _adopt(journal_source, target, answers, "--apply", "-v", capsys=capsys)
    assert code == 0, out
    assert (target / MANAGED_NAMING_THE_SEED).read_text(encoding="utf-8") == MANAGED_TEXT
    assert f"{MANAGED_NAMING_THE_SEED} links the decisions index" not in out  # no note claims it was relinked
    assert "sync check on the result: clean" in out  # the lock's hash still describes the managed file's bytes
    journal = (target / "Docs/journal/2026-10-16-session-01.md").read_text(encoding="utf-8")
    assert "[ADR-001](../decisions/README.md)" in journal  # the project-owned seed is still relinked


def test_a_journal_the_target_already_has_is_not_rewritten(
    journal_source: Path, target: Path, answers: Path, capsys
) -> None:
    mine = "# My session\n\nSee [ADR-001](../decisions/ADR-001-adopt-the-framework.md), which is mine.\n"
    _write(target, {"Docs/decisions/ADR-001-mine.md": "# Mine\n", "Docs/journal/2026-10-16-session-01.md": mine})
    code, _, _ = _adopt(journal_source, target, answers, "--apply")
    assert code == 0
    assert (target / "Docs/journal/2026-10-16-session-01.md").read_text(encoding="utf-8") == mine


def test_a_seed_adr_differing_only_in_case_from_the_targets_own_does_not_block_adoption(
    decisions_source: Path, target: Path, answers: Path, capsys
) -> None:
    """On a case-insensitive disk the seed's name clashes with the target's file and plan_new refuses the placement;
    that one refusal is dropped with the seed, because the file is the repository's own ADR number 1. On a
    case-sensitive disk the two names are two files and the ordinary withholding applies; either way the adoption
    goes ahead and the target's file is untouched."""
    own = "Docs/decisions/adr-001-adopt-the-framework.md"
    _write(target, {own: "# The project's own\n"})
    code, out, _ = _adopt(decisions_source, target, answers, "--apply", "-v", capsys=capsys)
    assert code == 0, out
    assert (target / own).read_text(encoding="utf-8") == "# The project's own\n"
    assert _states(out).get(SEED_ADR) == "seed-present" and "has its own ADR number 1" in out
    assert "blocked" not in _states(out).values()


def test_another_case_only_clash_is_still_a_refusal(
    decisions_source: Path, target: Path, answers: Path, capsys
) -> None:
    """Dropping the seed's refusal must not mask a different placement problem."""
    if not _case_insensitive(target):
        pytest.skip("a case-only clash needs a case-insensitive disk")
    _write(target, {"Docs/decisions/ADR-001-mine.md": "# Mine\n", "tools/New.py": "print(1)\n"})  # payload: new.py
    code, out, _ = _adopt(decisions_source, target, answers, "--apply", "-v", capsys=capsys)
    assert code == 1 and "capitalisation" in out


@pytest.mark.parametrize("apply", [False, True], ids=["dry-run", "apply"])
def test_an_unreadable_src_is_a_refusal_naming_the_folder_not_a_traceback(
    source: Path, target: Path, answers: Path, monkeypatch, capsys, apply: bool
) -> None:
    """The layout-debt scan lists ``src/`` on every run: a folder it cannot list is a refusal, and nothing is written
    (#209; ledger P-16)."""
    real = Path.iterdir
    denied = target / "src"

    def iterdir(self: Path):  # noqa: ANN202 - Path.iterdir's own shape
        if self == denied:
            raise PermissionError(13, "Permission denied", str(self))
        return real(self)

    monkeypatch.setattr(Path, "iterdir", iterdir)
    before = _snapshot(target)
    code, _, err = _adopt(source, target, answers, *(["--apply"] if apply else []), capsys=capsys)
    assert code == ini.EXIT_REFUSED and "refused:" in err and "src" in err, err
    assert _snapshot(target) == before


def test_a_package_under_src_that_cannot_be_searched_is_a_refusal(
    source: Path, target: Path, answers: Path, monkeypatch, capsys
) -> None:
    """Denied where the listing really fails, ``os.scandir``: ``Path.rglob`` swallows that error, and the scan would go
    on with a package left out (Copilot on #214)."""
    _write(target, {"src/zeta/inner/__init__.py": ""})
    real = os.scandir
    denied = target / "src" / "zeta" / "inner"

    def scandir(path="."):  # noqa: ANN001, ANN202 - os.scandir's own shape
        if Path(path) == denied:
            raise PermissionError(13, "Permission denied", str(path))
        return real(path)

    monkeypatch.setattr(os, "scandir", scandir)
    before = _snapshot(target)
    code, _, err = _adopt(source, target, answers, capsys=capsys)
    assert code == ini.EXIT_REFUSED and "inner" in err, err
    assert _snapshot(target) == before
