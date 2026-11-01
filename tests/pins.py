"""
Framework: the marker for a test that pins the framework's own text of a managed document.
Package: tests/pins

A managed document that a repository overrides is the repository's text, and a test that asserts the framework's
wording of it would fail for the right reason in the wrong place. ``pins(*documents)`` skips such a test, with the
reason shown (a skip is never silent), when ``framework.toml`` lists any of those documents as an override, and runs it
otherwise. The sync check already lists every override on each run, so the debt stays visible; reconciling one removes
the skip.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import framework_config as fc  # noqa: E402


def pins(*documents: str, root: Path = ROOT) -> pytest.MarkDecorator:
    """``@pins("Docs/standards/workflow.md")``: skip the test when that document is overridden in ``root``."""
    excused = fc.overridden(root, *documents)
    names = ", ".join(excused)
    return pytest.mark.skipif(
        bool(excused),
        reason=f"{names} overridden in framework.toml: this test pins the framework's text, which the project replaced",
    )


def shipped(root: Path, documents: list[str]) -> list[str]:
    """The documents the framework ships, of ``documents``: in a repository with a lock, only those the lock lists (a
    skill the project added is its own); with no lock (the payload itself), all of them."""
    try:
        listed = set(json.loads((root / "framework.lock").read_text(encoding="utf-8"))["files"])
    except (OSError, ValueError, KeyError, TypeError, RecursionError):  # a lock nested deeply overflows the parser
        return documents
    return [d for d in documents if d in listed]
