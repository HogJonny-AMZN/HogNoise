"""
Framework: tests for tools/framework_sync.py (the sync check: is every managed file as the lock says).
Package: tests/test_framework_sync

Each rule has a fixture repository that breaks exactly that rule and requires the finding with its path, and the fixture
unbroken has none. The lock is built with ``init.lock_hash``, the function ``init`` writes it with, so the check and the
initialiser cannot disagree about what "as locked" means.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import framework_config as fc  # noqa: E402
import framework_sync as fs  # noqa: E402
import init as ini  # noqa: E402

FILES = {
    "AGENTS.md": "# Entry\n",
    "tools/one.py": "print('one')\n",
    "Docs/standards/python.md": "# Python\n",
}


def _framework(version: str = "0.1.0", overrides: tuple[tuple[str, str], ...] = ()) -> str:
    modules = {name: "planned" for name in fc.MODULES}
    modules.update({"core": "on", "python-uv": "on", "lanes": "off"})
    data = {
        "framework": {"template_version": version},
        "modules": modules,
        "harnesses": {"enabled": []},
        "checks": {"handoff_max_lines": 150},
        "overrides": [{"target": t, "reason": r} for t, r in overrides],
    }
    return fc.dump_framework(fc.parse_framework(data))


def _repo(
    tmp_path: Path,
    files: dict[str, str] | None = None,
    *,
    overrides: tuple[tuple[str, str], ...] = (),
    lock_version: str = "0.1.0",
    toml_version: str = "0.1.0",
) -> Path:
    """A repository whose lock describes ``files`` exactly as they are written."""
    written = FILES if files is None else files
    for rel, text in written.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
    lock = {
        "template_version": lock_version,
        "initialised": "2026-10-15",
        "files": {rel: ini.lock_hash(text.encode("utf-8")) for rel, text in written.items()},
    }
    (tmp_path / "framework.lock").write_text(json.dumps(lock), encoding="utf-8")
    (tmp_path / "framework.toml").write_text(_framework(toml_version, overrides), encoding="utf-8")
    return tmp_path


def _check(root: Path) -> list[str]:
    return [str(f) for f in fs.check(root)]


# ---- a repository as locked passes
def test_a_repository_whose_files_are_as_locked_has_no_findings(tmp_path: Path) -> None:
    assert _check(_repo(tmp_path)) == []


def test_line_endings_alone_are_not_an_edit(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / "AGENTS.md").write_bytes(b"# Entry\r\n")
    assert _check(root) == []


# ---- edited
def test_an_edited_managed_file_is_found_with_its_path(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / "tools/one.py").write_text("print('changed')\n", encoding="utf-8")
    assert _check(root) == [
        "[edited] tools/one.py: differs from the lock; fix it in the template "
        "(or list it under [[overrides]] with a reason)"
    ]


def test_a_locked_path_that_is_now_a_directory_is_an_edit(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / "tools/one.py").unlink()
    (root / "tools/one.py").mkdir()
    assert _check(root) == ["[edited] tools/one.py: is not a file"]


def test_an_unreadable_locked_file_is_a_finding_not_a_crash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _repo(tmp_path)
    real = Path.read_bytes

    def refuse(self: Path) -> bytes:
        if self.name == "one.py":
            raise PermissionError(13, "denied")
        return real(self)

    monkeypatch.setattr(Path, "read_bytes", refuse)
    found = _check(root)
    assert len(found) == 1
    assert found[0].startswith("[unreadable] tools/one.py: cannot be read")


# ---- missing
def test_a_locked_file_that_is_gone_is_missing(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / "Docs/standards/python.md").unlink()
    assert _check(root) == [
        "[missing] Docs/standards/python.md: is in the lock and not on disk; restore it, "
        "or list it under [[overrides]] with a reason"
    ]


# ---- overrides
def test_an_override_with_a_reason_accepts_an_edit_and_a_deletion(tmp_path: Path) -> None:
    overrides = (("tools/one.py", "pinned to a fork"), ("AGENTS.md", "this project writes its own"))
    root = _repo(tmp_path, overrides=overrides)
    (root / "tools/one.py").write_text("print('mine')\n", encoding="utf-8")
    (root / "AGENTS.md").unlink()
    assert _check(root) == []


def test_an_override_for_a_file_that_equals_the_lock_is_stale(tmp_path: Path) -> None:
    root = _repo(tmp_path, overrides=(("tools/one.py", "was different once"),))
    assert _check(root) == [
        "[override-stale] tools/one.py: the file equals the lock, so the override can be removed "
        "(reason was: was different once)"
    ]


def test_an_override_for_a_setting_is_left_alone(tmp_path: Path) -> None:
    """An override can also name a setting (``handoff_max_lines``); the config loader owns that rule."""
    root = _repo(tmp_path, overrides=(("handoff_max_lines", "a long handoff"),))
    assert _check(root) == []


# ---- the lock itself
def test_no_lock_is_a_corpus_finding_never_a_pass(tmp_path: Path) -> None:
    (tmp_path / "framework.toml").write_text(_framework(), encoding="utf-8")
    assert _check(tmp_path) == [
        "[corpus] framework.lock: there is no lock, so there is nothing to compare with (run init new)"
    ]


def test_an_empty_lock_is_a_corpus_finding(tmp_path: Path) -> None:
    root = _repo(tmp_path, files={})
    assert _check(root) == ["[corpus] framework.lock: the lock lists no files, so nothing was checked"]


def test_an_unreadable_lock_is_a_lock_finding(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / "framework.lock").write_text("{broken", encoding="utf-8")
    found = _check(root)
    assert len(found) == 1
    assert found[0].startswith("[lock] framework.lock: cannot be read")


def test_a_lock_and_framework_toml_that_disagree_on_the_template_version_are_found(tmp_path: Path) -> None:
    root = _repo(tmp_path, lock_version="0.1.0", toml_version="0.2.0")
    assert _check(root) == [
        "[lock] framework.lock: locked at template 0.1.0 and framework.toml says 0.2.0; "
        "run init (or --update) to bring them together"
    ]


def test_findings_are_sorted_by_path_then_rule(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / "tools/one.py").write_text("x\n", encoding="utf-8")
    (root / "AGENTS.md").unlink()
    (root / "Docs/standards/python.md").write_text("x\n", encoding="utf-8")
    assert [f.split(":")[0] for f in _check(root)] == [
        "[missing] AGENTS.md",
        "[edited] Docs/standards/python.md",
        "[edited] tools/one.py",
    ]


# ---- the command line
def test_the_command_line_exits_zero_clean_one_on_findings_and_two_when_it_cannot_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _repo(tmp_path)
    assert fs.main(["--check", "--root", str(root)]) == 0
    assert "sync check: clean" in capsys.readouterr().out
    (root / "tools/one.py").write_text("x\n", encoding="utf-8")
    assert fs.main(["--check", "--root", str(root)]) == 1
    out = capsys.readouterr().out
    assert "[edited] tools/one.py" in out and "1 finding(s)" in out
    assert fs.main(["--check", "--root", str(tmp_path / "nowhere")]) == 2
    assert "not a directory" in capsys.readouterr().out
    (root / "framework.toml").write_text("not = [valid", encoding="utf-8")
    assert fs.main(["--check", "--root", str(root)]) == 2
    assert "cannot run" in capsys.readouterr().out


def test_the_command_line_requires_a_mode(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as caught:
        fs.main([])
    assert caught.value.code == 2
    capsys.readouterr()


def test_the_script_runs_standalone(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "framework_sync.py"), "--check", "--root", str(root)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "sync check: clean" in result.stdout


# ---- this repository
@pytest.mark.skipif(
    not (ROOT / "framework.lock").exists(), reason="the payload has no lock; a repository made from it does"
)
def test_this_repositorys_own_managed_files_are_as_locked() -> None:
    assert _check(ROOT) == []


# ---- survivors of the first mutation table
def test_the_lock_finding_sorts_among_the_file_findings_by_path(tmp_path: Path) -> None:
    root = _repo(tmp_path, lock_version="0.1.0", toml_version="0.2.0")
    (root / "tools/one.py").write_text("x\n", encoding="utf-8")
    (root / "AGENTS.md").write_text("x\n", encoding="utf-8")
    assert [f.split(":")[0] for f in _check(root)] == [
        "[edited] AGENTS.md",
        "[lock] framework.lock",
        "[edited] tools/one.py",
    ]


def test_a_locked_symlink_to_nowhere_is_an_edit_not_a_missing_file(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / "tools/one.py").unlink()
    try:
        (root / "tools/one.py").symlink_to(root / "nowhere")
    except (OSError, NotImplementedError):
        pytest.skip("this account cannot create a symlink")
    assert _check(root) == ["[edited] tools/one.py: is a symlink, and init writes a regular file"]


# ---- what the first review found
def _write_lock(root: Path, files: dict[str, str]) -> None:
    lock = {"template_version": "0.1.0", "initialised": "2026-10-15", "files": files}
    (root / "framework.lock").write_text(json.dumps(lock), encoding="utf-8")


@pytest.mark.parametrize(
    "key",
    ["../outside.md", "/etc/passwd", "a\\b.md", "a//b.md", ".", "", "a/./b.md", "C:/x.md", "line\nbreak.md", "dir/"],
    ids=[
        "parent",
        "absolute",
        "backslash",
        "double-slash",
        "dot",
        "empty",
        "dot-segment",
        "drive",
        "newline",
        "trailing",
    ],
)
def test_a_lock_key_that_is_not_a_normalised_relative_path_is_a_lock_finding(tmp_path: Path, key: str) -> None:
    root = _repo(tmp_path)
    _write_lock(root, {key: ini.lock_hash(b"x"), "AGENTS.md": ini.lock_hash(b"# Entry\n")})
    found = _check(root)
    assert len(found) == 1
    assert found[0].startswith("[lock] framework.lock:")
    assert "not a normalised relative path" in found[0]


def test_a_managed_file_replaced_by_a_symlink_to_identical_content_is_an_edit(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / "elsewhere.py").write_text("print('one')\n", encoding="utf-8")
    (root / "tools/one.py").unlink()
    try:
        (root / "tools/one.py").symlink_to(root / "elsewhere.py")
    except (OSError, NotImplementedError):
        pytest.skip("this account cannot create a symlink")
    assert _check(root) == ["[edited] tools/one.py: is a symlink, and init writes a regular file"]


def test_a_locked_file_reached_through_a_symlinked_folder_that_leaves_the_repository_is_an_edit(tmp_path: Path) -> None:
    root = _repo(tmp_path / "repo", files={"AGENTS.md": "# Entry\n", "Docs/a.md": "# A\n"})
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "a.md").write_text("# A\n", encoding="utf-8")
    (root / "Docs/a.md").unlink()
    (root / "Docs").rmdir()
    try:
        (root / "Docs").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("this account cannot create a symlink")
    assert _check(root) == ["[edited] Docs/a.md: resolves outside the repository"]


def test_an_override_accepts_a_symlink_on_purpose(tmp_path: Path) -> None:
    root = _repo(tmp_path, overrides=(("tools/one.py", "linked to the shared copy"),))
    (root / "elsewhere.py").write_text("print('one')\n", encoding="utf-8")
    (root / "tools/one.py").unlink()
    try:
        (root / "tools/one.py").symlink_to(root / "elsewhere.py")
    except (OSError, NotImplementedError):
        pytest.skip("this account cannot create a symlink")
    assert _check(root) == []


def test_an_override_in_force_is_reported_with_its_reason_though_the_check_passes(tmp_path: Path) -> None:
    root = _repo(tmp_path, overrides=(("tools/one.py", "pinned to a fork"),))
    (root / "tools/one.py").write_text("print('mine')\n", encoding="utf-8")
    result = fs.report(root)
    assert result.findings == []
    assert result.honoured == [("tools/one.py", "pinned to a fork")]


def test_the_command_line_lists_the_overrides_in_force_and_still_exits_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _repo(tmp_path, overrides=(("tools/one.py", "pinned to a fork"),))
    (root / "tools/one.py").write_text("print('mine')\n", encoding="utf-8")
    assert fs.main(["--check", "--root", str(root)]) == 0
    out = capsys.readouterr().out
    assert "override in force: tools/one.py: pinned to a fork" in out
    assert "sync check: clean (1 override in force)" in out


def test_an_override_that_names_no_locked_file_and_no_setting_is_unknown(tmp_path: Path) -> None:
    root = _repo(tmp_path, overrides=(("tools/typo.py", "meant tools/one.py"), ("framework.lock", "no")))
    assert _check(root) == [
        "[override-unknown] framework.lock: names no locked file and no setting; fix the name or remove it",
        "[override-unknown] tools/typo.py: names no locked file and no setting; fix the name or remove it",
    ]


def test_a_directory_that_cannot_be_read_is_unreadable_not_missing_and_an_override_does_not_hide_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _repo(tmp_path, overrides=(("tools/one.py", "pinned"),))
    real = fs.os.lstat

    def denied(path, *args, **kwargs):
        if str(path).endswith("one.py"):
            raise PermissionError(13, "denied")
        return real(path, *args, **kwargs)

    monkeypatch.setattr(fs.os, "lstat", denied)
    found = _check(root)
    assert len(found) == 1
    assert found[0].startswith("[unreadable] tools/one.py: cannot be read, so it was not checked")


def test_a_lock_nested_deeply_enough_to_overflow_the_parser_is_a_lock_finding_not_a_traceback(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / "framework.lock").write_text("[" * 200000, encoding="utf-8")
    found = _check(root)
    assert len(found) == 1
    assert found[0].startswith("[lock] framework.lock: cannot be read")


def test_a_folder_that_cannot_be_resolved_is_unreadable_and_the_other_files_are_still_checked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Before Python 3.13 a symlink loop makes ``Path.resolve`` raise ``RuntimeError``; the check must not abort."""
    root = _repo(tmp_path, overrides=(("tools/one.py", "pinned"),))
    (root / "AGENTS.md").write_text("changed\n", encoding="utf-8")
    real = Path.resolve

    def loop(self: Path, *args, **kwargs):
        if self.name == "tools":
            raise RuntimeError("Symlink loop from " + str(self))
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", loop)
    found = _check(root)
    assert [f.split(":")[0] for f in found] == [
        "[edited] AGENTS.md",
        "[unreadable] tools/one.py",
    ]  # an override does not hide it
    assert "cannot be resolved" in found[1]


def test_a_real_symlink_loop_is_a_finding_not_a_traceback(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / "tools/one.py").unlink()
    (root / "tools").rmdir()
    try:
        (root / "tools").symlink_to("tools", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("this account cannot create a symlink")
    found = _check(root)
    assert any(f.startswith("[") and "tools/one.py" in f for f in found)
    assert not any("AGENTS.md" in f for f in found)
