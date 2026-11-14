"""
Framework: the check runner: every check CI runs, in one command, in CI's order, on every platform.
Package: tools/check

The sequence lives here, in the one language every repository made from the template has, and ``make check`` is a
one-line dispatcher to it (``Docs/standards/tooling.md``). A machine without make loses typing and nothing else.

``stages(root)`` is the stage list, and it is also the CI parity oracle: ``tests/test_tooling.py`` asserts that
``.github/workflows/ci.yml`` runs these same commands in this same order, so local green and CI green cannot drift
apart.
A stage belongs to a module of ``framework.toml`` and is in the list only while that module is ``on``: the hygiene check
runs when ``hygiene`` is on, the log-format check and the tests when ``python-uv`` is, the graph check when ``graph``
is, the process map's check when ``process-map`` is, the adapters check when ``harness-adapters`` is. The sync check
belongs to the core.

Every stage runs even after one fails (a run that stops at the first failure hides the others and turns one
fix-and-rerun
cycle into several); the summary names the stages that failed. A stage that cannot be started at all (``uv`` is missing)
is a failed stage with its reason, not a traceback.

Run standalone (exit code 0 every stage passed, 1 a stage failed, 2 the arguments or the configuration are unusable)::

    uv run python tools/check.py [--fast] [--only NAME ...] [--list] [-v] [--root PATH]

``--fast`` runs only the stages cheap enough for a pre-commit hook (everything but the tests); ``--list`` prints the
stage
names and commands and runs nothing; ``--only`` runs the named stages.
"""

from __future__ import annotations

import argparse
import logging as _logging
import os
import subprocess
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import framework_config as fc
import log_setup

# -------------------------------------------------------------------------
# module global scope
_MODULE_NAME = "tools.check"
__version__ = "0.2.0"
__updated__ = "2026-11-01"
_LOGGER = _logging.getLogger(_MODULE_NAME)

#: The repository root: the parent of the folder this file is in.
ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Stage:
    """One check: a label, the argv to run, why it is here, the module that owns it, and whether it is fast.

    :param name: Short label shown in the progress output, the summary and ``--only``.
    :param argv: The command, as an argv and never a shell string, so that no platform disagrees about quoting.
    :param why: One line saying what a failure of this stage means.
    :param module: The ``framework.toml`` module that must be ``on`` for the stage to run.
    :param fast: Whether a pre-commit hook may run it (the tests are the one stage that is not).
    """

    name: str
    argv: tuple[str, ...]
    why: str
    module: str
    fast: bool = True


#: Every stage the framework knows, in the order they run. CI runs them in this order, as separate steps, so a failure
#: names its stage in the CI log; the cheapest and most informative come first, the tests last.
ALL_STAGES: tuple[Stage, ...] = (
    Stage("lint", ("uv", "run", "ruff", "check", "."), "Coding standards: Docs/standards/python.md", "core"),
    Stage(
        "format",
        ("uv", "run", "ruff", "format", "--check", "."),
        "Formatting, so that diffs stay about content. Fix with: make format",
        "core",
    ),
    Stage(
        "docs",
        ("uv", "run", "python", "tools/check_docs.py"),
        "Documentation drift: the definition of done's 'nothing is drifting', mechanised",
        "core",
    ),
    Stage(
        "hygiene",
        ("uv", "run", "python", "tools/check_hygiene.py"),
        "No identifier on the project's list in any tracked file",
        "hygiene",
    ),
    Stage(
        "log-format",
        ("uv", "run", "python", "tools/check_log_format.py"),
        "Log calls use f-strings: Docs/standards/python.md",
        "python-uv",
    ),
    Stage(
        "graph",
        ("uv", "run", "python", "tools/render_framework_graph.py", "--check"),
        "The framework graph is well formed and its page is current",
        "graph",
    ),
    Stage(
        "process-map",
        ("uv", "run", "python", "tools/render_process_map.py", "--check"),
        "The process map's data is well formed and its page is current",
        "process-map",
    ),
    Stage(
        "adapters",
        ("uv", "run", "python", "tools/sync_adapters.py", "--check"),
        "The harness adapters and skills mirrors are the generated ones, and no enabled harness lacks a passing probe",
        "harness-adapters",
    ),
    Stage(
        "sync",
        ("uv", "run", "python", "tools/framework_sync.py", "--check"),
        "A managed file differs from the lock without an override, or is missing",
        "core",
    ),
    Stage(
        "tests",
        ("uv", "run", "pytest", "-q"),
        "Behaviour. Hardware the runner lacks is skipped with a reason, never silently",
        "python-uv",
        fast=False,
    ),
)


def stages(root: Path = ROOT, *, fast: bool = False) -> tuple[Stage, ...]:
    """The stages that run in ``root``: those whose module is ``on`` in its ``framework.toml``, only the fast ones if
    asked.

    :param root: The repository root.
    :param fast: Keep only the stages a pre-commit hook may run.
    :raises fc.ConfigError: ``framework.toml`` is missing or invalid.
    """
    modules = fc.load_framework(root / "framework.toml").modules
    chosen = tuple(s for s in ALL_STAGES if modules.get(s.module) == "on" and (s.fast or not fast))
    _LOGGER.info(f"stages for {root}: {', '.join(s.name for s in chosen)}{' (fast)' if fast else ''}")
    return chosen


def shell_form(argv: Sequence[str]) -> str:
    """An argv as it would be typed at a shell: an argument with a space is double-quoted, so the echo can be pasted.

    Printing ``-m not gpu`` bare would look like the command that ran and not be.
    """
    return " ".join(f'"{a}"' if " " in a else a for a in argv)


def run_stage(stage: Stage, root: Path) -> tuple[bool, float]:
    """Run one stage with its output going straight through to the console. Returns (passed, seconds)."""
    # flushed, so that the header comes out before the child's output when stdout is a pipe
    print(f"\n=== {stage.name} " + "=" * max(4, 60 - len(stage.name)), flush=True)
    print(f"    {shell_form(stage.argv)}", flush=True)
    started = time.perf_counter()
    try:
        passed = subprocess.run(stage.argv, cwd=root, check=False).returncode == 0
    except OSError as e:  # the command could not be started at all: uv is not installed, say
        print(f"    could not start {stage.argv[0]!r}: {e}", file=sys.stderr)
        passed = False
    elapsed = time.perf_counter() - started
    _LOGGER.info(f"stage {stage.name}: {'passed' if passed else 'FAILED'} in {elapsed:.2f}s")
    return passed, elapsed


def hooks_note(root: Path) -> str:
    """A one-line reminder when this is a git checkout whose hooks are not installed and this is not CI; else empty."""
    if os.environ.get("CI") or not (root / ".git").exists():
        return ""
    import install_hooks

    try:
        installed = install_hooks.status(root) == "installed"
    except install_hooks.HooksError as e:  # a reminder is never worth failing the run for
        _LOGGER.info(f"could not tell whether the hooks are installed: {e}")
        return ""
    return "" if installed else "note: the git hooks are not installed; run: make hooks"


def main(argv: list[str] | None = None) -> int:
    """Run the stages, print a summary, and return 0 when every stage passed, 1 when one failed, 2 when unusable
    (130 when interrupted)."""
    try:
        return _run(argv)
    except KeyboardInterrupt:  # Ctrl-C ends the run with the conventional code, not a traceback
        print("\ncheck: interrupted", file=sys.stderr)
        return 130


def _run(argv: list[str] | None) -> int:
    for stream in (sys.stdout, sys.stderr):  # a stage's name or reason is never worth a crash on a narrow console
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="backslashreplace")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fast", action="store_true", help="only the stages a pre-commit hook may run")
    parser.add_argument("--only", nargs="+", metavar="NAME", help="run only the named stages")
    parser.add_argument("--list", action="store_true", help="print the stage names and commands; run nothing")
    parser.add_argument("--root", type=Path, default=ROOT, help="the repository to check (default: this one)")
    parser.add_argument("-v", "--verbose", action="store_true", help="log what was decided to standard error")
    args = parser.parse_args(argv)
    log_setup.configure(args.verbose)
    root = args.root.resolve()
    if not root.is_dir():
        print(f"check: cannot run: {root} is not a directory", file=sys.stderr)
        return 2
    try:
        chosen = stages(root, fast=args.fast)
    except fc.ConfigError as e:
        print(f"check: cannot run: {e}", file=sys.stderr)
        return 2
    if args.only:
        unknown = sorted(set(args.only) - {s.name for s in chosen})
        if unknown:
            print(
                f"check: cannot run: no such stage here: {', '.join(unknown)} (the stages are "
                f"{', '.join(s.name for s in chosen) or 'none'})",
                file=sys.stderr,
            )
            return 2
        chosen = tuple(s for s in chosen if s.name in args.only)
    if not chosen:  # a gate that runs nothing and passes is the failure the docs check's corpus rule exists for
        print("check: no stage is enabled (framework.toml modules are all off); nothing was checked", file=sys.stderr)
        return 2
    if args.list:
        for stage in chosen:
            print(f"{stage.name}\t{shell_form(stage.argv)}")
        return 0

    print(f"check: {root}")
    results = [(stage, *run_stage(stage, root)) for stage in chosen]
    failed = [stage.name for stage, passed, _ in results if not passed]
    print("\n" + "=" * 68)
    for stage, passed, elapsed in results:
        print(f"  {'PASS' if passed else 'FAIL'}  {stage.name:<11} {elapsed:6.2f}s   {stage.why}")
    total = sum(elapsed for _, _, elapsed in results)
    print("=" * 68)
    note = hooks_note(root)
    if note:
        print(note)
    if failed:
        print(f"FAILED: {', '.join(failed)}   ({total:.2f}s total)")
        return 1
    print(f"All {len(results)} stages passed   ({total:.2f}s total)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
