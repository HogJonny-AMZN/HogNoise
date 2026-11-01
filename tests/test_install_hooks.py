"""
Framework: tests for tools/install_hooks.py (point a clone at .githooks/ and make the hooks executable).
Package: tests/test_install_hooks
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import install_hooks as ih  # noqa: E402


def _git_repo(path: Path, *, hooks: bool = True) -> Path:
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    if hooks:
        (path / ".githooks").mkdir()
        for name in ih.HOOKS:
            (path / ".githooks" / name).write_text("#!/bin/sh\nexit 0\n", encoding="utf-8", newline="\n")
    return path


def _hooks_path(path: Path) -> str:
    done = subprocess.run(
        ["git", "-C", str(path), "config", "--local", "--get", "core.hooksPath"], capture_output=True, text=True
    )
    return done.stdout.strip()


def test_the_hook_files_the_framework_ships_are_the_ones_the_installer_expects() -> None:
    for name in ih.HOOKS:
        assert (ROOT / ih.HOOKS_DIR / name).is_file(), name


def test_status_names_each_way_a_clone_can_be_not_ready(tmp_path: Path) -> None:
    assert ih.status(tmp_path) == "not-git"
    repo = _git_repo(tmp_path / "repo")
    assert ih.status(repo) == "not-configured"
    subprocess.run(["git", "-C", str(repo), "config", "--local", "core.hooksPath", "elsewhere"], check=True)
    assert ih.status(repo) == "not-configured"  # pointed at the wrong folder
    subprocess.run(["git", "-C", str(repo), "config", "--local", "core.hooksPath", ih.HOOKS_DIR], check=True)
    (repo / ".githooks" / "commit-msg").unlink()
    assert ih.status(repo) == "missing-files"


@pytest.mark.skipif(os.name == "nt", reason="Windows has no execute bit to lose")
def test_a_hook_without_the_execute_bit_is_named(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    subprocess.run(["git", "-C", str(repo), "config", "--local", "core.hooksPath", ih.HOOKS_DIR], check=True)
    for name in ih.HOOKS:
        (repo / ".githooks" / name).chmod(0o644)
    assert ih.status(repo) == "not-executable"


def test_install_points_the_clone_at_the_folder_and_reports_installed(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    assert ih.install(repo) == "installed"
    assert _hooks_path(repo) == ".githooks"
    assert ih.status(repo) == "installed"


@pytest.mark.skipif(os.name == "nt", reason="Windows has no execute bit")
def test_install_makes_the_hooks_executable(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    for name in ih.HOOKS:
        (repo / ".githooks" / name).chmod(0o644)
    ih.install(repo)
    assert all(os.access(repo / ".githooks" / name, os.X_OK) for name in ih.HOOKS)


def test_install_twice_changes_nothing_more(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    ih.install(repo)
    config = (repo / ".git" / "config").read_text(encoding="utf-8")
    assert ih.install(repo) == "installed"
    assert (repo / ".git" / "config").read_text(encoding="utf-8") == config


def test_install_refuses_what_it_cannot_install(tmp_path: Path) -> None:
    with pytest.raises(ih.HooksError, match="not a git checkout"):
        ih.install(tmp_path)
    repo = _git_repo(tmp_path / "repo", hooks=False)
    with pytest.raises(ih.HooksError, match="no pre-commit, commit-msg"):
        ih.install(repo)
    assert _hooks_path(repo) == ""  # and it changed nothing


def test_main_exit_codes(tmp_path: Path, capsys) -> None:
    repo = _git_repo(tmp_path / "repo")
    assert ih.main(["--check", "--root", str(repo)]) == 1  # not installed
    assert "hooks: not-configured" in capsys.readouterr().out
    assert _hooks_path(repo) == ""  # --check changed nothing
    assert ih.main(["--root", str(repo)]) == 0
    assert "hooks: installed" in capsys.readouterr().out
    assert ih.main(["--check", "--root", str(repo)]) == 0
    assert ih.main(["--check", "--root", str(tmp_path)]) == 2  # not a git checkout
    assert "not a git checkout" in capsys.readouterr().err
    assert ih.main(["--root", str(tmp_path)]) == 2


def test_git_that_cannot_run_is_reported_not_a_traceback(tmp_path: Path, capsys, monkeypatch) -> None:
    repo = _git_repo(tmp_path)

    def refuse(*args, **kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(ih.subprocess, "run", refuse)
    assert ih.main(["--root", str(repo)]) == 2
    assert "cannot run git" in capsys.readouterr().err
    assert ih.main(["--check", "--root", str(repo)]) == 2  # git failing is not "no .git" and not "not configured"
    assert "cannot run git" in capsys.readouterr().err
    with pytest.raises(ih.HooksError, match="cannot run git"):
        ih.status(repo)


def test_a_git_that_fails_is_an_error_not_a_setup_state(tmp_path: Path, monkeypatch) -> None:
    repo = _git_repo(tmp_path)
    real_run = subprocess.run

    def broken(argv, **kwargs):
        if "--get" in argv:
            return subprocess.CompletedProcess(argv, 128, stdout="", stderr="fatal: bad config file")
        return real_run(argv, **kwargs)

    monkeypatch.setattr(ih.subprocess, "run", broken)
    with pytest.raises(ih.HooksError, match="bad config file"):
        ih.status(repo)


def test_a_setting_that_is_simply_not_set_is_not_configured_not_an_error(tmp_path: Path) -> None:
    assert ih.status(_git_repo(tmp_path)) == "not-configured"


def test_the_runner_reminder_survives_a_git_that_fails(tmp_path: Path, monkeypatch) -> None:
    import check

    repo = _git_repo(tmp_path)

    def refuse(*args, **kwargs):
        raise FileNotFoundError("git")

    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setattr(ih.subprocess, "run", refuse)
    assert check.hooks_note(repo) == ""  # a reminder is never worth failing the run for


def test_a_failed_chmod_leaves_the_clone_unconfigured(tmp_path: Path, monkeypatch) -> None:
    repo = _git_repo(tmp_path)

    def refuse(self, mode):
        raise PermissionError("read-only checkout")

    monkeypatch.setattr(Path, "chmod", refuse)
    with pytest.raises(ih.HooksError):
        ih.install(repo)
    assert _hooks_path(repo) == ""  # not pointed at hooks that cannot run


def test_a_hook_that_cannot_be_made_executable_is_reported_not_a_traceback(tmp_path: Path, capsys, monkeypatch) -> None:
    repo = _git_repo(tmp_path)

    def refuse(self, mode):
        raise PermissionError("read-only checkout")

    monkeypatch.setattr(Path, "chmod", refuse)
    assert ih.main(["--root", str(repo)]) == 2
    err = capsys.readouterr().err
    assert "cannot make" in err and "read-only checkout" in err
