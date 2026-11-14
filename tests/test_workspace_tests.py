"""
Framework: one test run across workspace members, and why no ``tests/`` folder has an ``__init__.py``.
Package: tests/test_workspace_tests

Two members that each have a ``tests/conftest.py`` and a ``tests/test_same.py`` are collected by one root run with
``--import-mode=importlib``. The control puts an ``__init__.py`` in both test folders: ``tests`` then becomes one
package name in two places, and the second ``conftest.py`` collides with the first, the failure a production
repository met before it removed them (Docs/standards/layout.md).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT_MANIFEST = """[tool.pytest.ini_options]
testpaths = ["apps/*/tests", "packages/*/*/tests"]
addopts = "--import-mode=importlib"
"""


def _workspace(root: Path, with_init: bool) -> Path:
    (root / "pyproject.toml").write_text(ROOT_MANIFEST, encoding="utf-8")
    for member, value in (("apps/one", 1), ("packages/python/two", 2)):
        tests = root / member / "tests"
        tests.mkdir(parents=True)
        (tests / "conftest.py").write_text(
            f"import pytest\n\n\n@pytest.fixture\ndef number() -> int:\n    return {value}\n", encoding="utf-8"
        )
        (tests / "test_same.py").write_text(
            f"def test_the_members_own_fixture(number: int) -> None:\n    assert number == {value}\n", encoding="utf-8"
        )
        if with_init:
            (tests / "__init__.py").write_text("", encoding="utf-8")
    return root


def _pytest(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--rootdir", str(root)],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_one_run_collects_two_members_with_the_same_conftest_and_test_names(tmp_path: Path) -> None:
    run = _pytest(_workspace(tmp_path, with_init=False))
    assert run.returncode == 0, run.stdout + run.stderr
    assert "2 passed" in run.stdout


def test_an_init_in_each_test_folder_makes_the_conftests_collide(tmp_path: Path) -> None:
    run = _pytest(_workspace(tmp_path, with_init=True))
    assert run.returncode != 0, run.stdout + run.stderr
    assert "Plugin already registered" in run.stdout + run.stderr, run.stdout + run.stderr
