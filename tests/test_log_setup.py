"""
Framework: tests of the template's tools' one logging setup, and of each core tool's use of it.
Package: tests/test_log_setup

``log_setup.configure()`` calls ``basicConfig``, which does nothing while pytest's own handler sits on the root logger,
so every case runs in a fresh interpreter. ``tool_log_line`` is shared: the tests of the tools outside core import it,
so each module's file holds its own tool's case.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
#: A line in ``log_setup.FORMAT``: ``2026-11-08 01:02:03,456 WARNING probe.after_main: a warning``.
PROBE_LINE = re.compile(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d{3} WARNING probe\.after_main: a warning")


def _python(code: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-I", "-c", f"import sys; sys.path.insert(0, {str(TOOLS)!r})\n{code}"],
        capture_output=True,
        text=True,
        timeout=120,
    )


def tool_log_line(tool: str, argv: list[str]) -> tuple[str, int]:
    """Run ``tool.main(argv)`` in a fresh interpreter, then log one warning: the warning's stderr line, and the root
    logger's level after ``main``. ``main`` may fail on its input; its logging is set up before it reads any.

    The line checked is this probe's, not one the tool logs: ``basicConfig`` puts one formatter on the root logger for
    every record, so a probe line in ``log_setup.FORMAT`` shows the tool's own lines are in it too, without a fixture
    repository that makes each tool log."""
    run = _python(
        "import logging\n"
        f"import {tool}\n"
        "try:\n"
        f"    {tool}.main({argv!r})\n"
        "except SystemExit:\n"
        "    pass\n"
        "print(logging.getLogger().level)\n"
        "logging.getLogger('probe.after_main').warning('a warning')\n"
    )
    lines = [ln for ln in run.stderr.splitlines() if "a warning" in ln]
    assert lines, f"{tool}: no warning line on stderr\n{run.stderr}"
    return lines[-1], int(run.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize(
    ("calls", "level"),
    [("configure(False)", 30), ("configure(True)", 20), ("configure(True); log_setup.configure(False)", 20)],
)
def test_the_level_is_warning_without_v_and_info_with_it_and_a_second_call_changes_nothing(
    calls: str, level: int
) -> None:
    run = _python(f"import logging, log_setup\nlog_setup.{calls}\nprint(logging.getLogger().level)")
    assert run.returncode == 0, run.stderr
    assert int(run.stdout.strip()) == level


def test_a_line_carries_the_time_the_level_and_the_module() -> None:
    run = _python(
        "import logging, log_setup\nlog_setup.configure(False)\n"
        "logging.getLogger('probe.after_main').warning('a warning')"
    )
    assert PROBE_LINE.fullmatch(run.stderr.strip()), run.stderr


@pytest.mark.parametrize(
    ("tool", "argv"),
    [
        ("check", ["-v", "--list", "--root", "{empty}"]),
        ("check_commit_msg", ["-v", "--root", "{empty}", "{empty}/message"]),
        ("check_docs", ["-v", "{empty}"]),
        ("framework_sync", ["-v", "--check", "--root", "{empty}"]),
        ("install_hooks", ["-v", "--check", "--root", "{empty}"]),
        ("render_board", ["-v", "--print", "--root", "{empty}"]),
    ],
)
def test_each_core_tool_logs_with_the_prefix_at_info_with_v(tool: str, argv: list[str], tmp_path: Path) -> None:
    line, level = tool_log_line(tool, [a.replace("{empty}", str(tmp_path)) for a in argv])
    assert PROBE_LINE.fullmatch(line), line
    assert level == 20
