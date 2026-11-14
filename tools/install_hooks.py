"""
Framework: install the git hooks: point this clone at ``.githooks/`` and make the hook files executable.
Package: tools/install_hooks

Git has no way to ship a hook with a repository: a hook runs only if the clone's ``core.hooksPath`` names the folder
that
holds it. The hooks are in ``.githooks/`` (``pre-commit`` runs the fast stages of ``tools/check.py``; ``commit-msg``
runs
``tools/check_commit_msg.py``), and this tool is the one step per clone that turns them on. A hook nobody installed
enforces nothing, which is why ``--check`` exists (and why the check runner prints a reminder when they are missing).

Run standalone (exit code 0 installed, 1 ``--check`` found them not installed, 2 this is not a git checkout or git
cannot be run)::

    uv run python tools/install_hooks.py [--check] [-v] [--root PATH]
"""

from __future__ import annotations

import argparse
import logging as _logging
import os
import subprocess
import sys
from pathlib import Path

import log_setup

# -------------------------------------------------------------------------
# module global scope
_MODULE_NAME = "tools.install_hooks"
__version__ = "0.1.0"
__updated__ = "2026-10-13"
_LOGGER = _logging.getLogger(_MODULE_NAME)

ROOT = Path(__file__).resolve().parent.parent

#: The folder the hooks live in, relative to the root, and the hooks the framework ships.
HOOKS_DIR = ".githooks"
HOOKS = ("pre-commit", "commit-msg")


class HooksError(Exception):
    """This is not a git checkout, or git cannot be run."""


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=False)
    except OSError as e:
        raise HooksError(f"cannot run git: {e}") from e


def status(root: Path = ROOT) -> str:
    """Whether the hooks are installed in ``root``.

    :raises HooksError: git cannot be run, or fails for a reason other than the setting not being there.
    :returns: ``installed``; ``not-git`` (no ``.git``); ``not-configured`` (``core.hooksPath`` is not ``.githooks``);
        ``missing-files`` (a hook file is absent); or ``not-executable`` (a hook file lacks the execute bit, POSIX
        only).
    """
    if not (root / ".git").exists():
        return "not-git"
    configured = _git(root, "config", "--local", "--get", "core.hooksPath")
    if configured.returncode not in (0, 1):  # 1 is "the key is not set"; anything else is git failing
        raise HooksError(f"git config failed: {configured.stderr.strip() or configured.returncode}")
    if configured.returncode == 1 or configured.stdout.strip() != HOOKS_DIR:
        return "not-configured"
    files = [root / HOOKS_DIR / name for name in HOOKS]
    if not all(f.is_file() for f in files):
        return "missing-files"
    if os.name != "nt" and not all(os.access(f, os.X_OK) for f in files):
        return "not-executable"
    return "installed"


def install(root: Path = ROOT) -> str:
    """Set ``core.hooksPath`` and make the hook files executable; returns the status afterwards (``installed``).

    :raises HooksError: this is not a git checkout, git cannot be run, a hook file is missing or cannot be made
        executable (in which case the configuration is left as it was).
    """
    if not (root / ".git").exists():
        raise HooksError(f"{root} is not a git checkout (no .git)")
    missing = [name for name in HOOKS if not (root / HOOKS_DIR / name).is_file()]
    if missing:
        raise HooksError(f"{HOOKS_DIR}/ has no {', '.join(missing)}")
    for name in HOOKS:  # first, so that a failure leaves the clone as it was and not pointed at unusable hooks
        path = root / HOOKS_DIR / name
        try:
            path.chmod(path.stat().st_mode | 0o111)
        except OSError as e:  # a read-only checkout, say
            raise HooksError(f"cannot make {path} executable: {e}") from e
    done = _git(root, "config", "--local", "core.hooksPath", HOOKS_DIR)
    if done.returncode != 0:
        raise HooksError(f"git config failed: {done.stderr.strip()}")
    _LOGGER.info(f"core.hooksPath set to {HOOKS_DIR} in {root}; made {', '.join(HOOKS)} executable")
    return status(root)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="report whether the hooks are installed; change nothing")
    parser.add_argument("--root", type=Path, default=ROOT, help="the repository (default: this one)")
    parser.add_argument("-v", "--verbose", action="store_true", help="log what was done to standard error")
    args = parser.parse_args(argv)
    log_setup.configure(args.verbose)
    root = args.root.resolve()
    try:
        if args.check:
            state = status(root)
            if state == "not-git":
                raise HooksError(f"{root} is not a git checkout (no .git)")
            print(f"hooks: {state}")
            return 0 if state == "installed" else 1
        state = install(root)
    except HooksError as e:
        print(f"hooks: cannot run: {e}", file=sys.stderr)
        return 2
    print(f"hooks: {state}")
    return 0 if state == "installed" else 1


if __name__ == "__main__":
    sys.exit(main())
