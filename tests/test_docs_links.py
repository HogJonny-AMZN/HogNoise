"""
HogNoise: every relative link in the Markdown documents resolves to a file that exists.
Package: tests/test_docs_links

The documents came from another project and carried ten links to files that were never copied. A link that
goes nowhere in a public README reads as an abandoned project, so this fails on one.
"""

import re
from pathlib import Path
from typing import List

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".venv", ".venv311", ".venv-bare", "build", ".git", ".pytest_cache", ".ruff_cache", "node_modules"}
_FENCE = re.compile(r"```.*?```", re.S)
_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")


def broken_links(markdown: str, folder: Path) -> List[str]:
    """Relative link targets in ``markdown`` that do not exist under ``folder``. URLs and anchors are not checked."""
    broken = []
    for target in _LINK.findall(_FENCE.sub("", markdown)):
        if re.match(r"^(https?:|mailto:|#)", target):
            continue
        if not (folder / target.split("#")[0]).resolve().exists():
            broken.append(target)
    return broken


def _documents() -> List[Path]:
    return sorted(p for p in ROOT.rglob("*.md") if not SKIP_DIRS & set(p.relative_to(ROOT).parts))


@pytest.mark.parametrize("document", _documents(), ids=lambda p: p.relative_to(ROOT).as_posix())
def test_every_relative_link_resolves(document):
    assert broken_links(document.read_text(encoding="utf-8"), document.parent) == []


def test_there_are_documents_to_check():
    assert len(_documents()) >= 8


def test_the_check_flags_a_missing_target(tmp_path: Path):
    """The instrument can produce the other answer."""
    (tmp_path / "real.md").write_text("x", encoding="utf-8")
    text = "[ok](real.md) [gone](missing.md#top) [web](https://example.com) [anchor](#here)\n```\n[code](nope.md)\n```"
    assert broken_links(text, tmp_path) == ["missing.md#top"]
