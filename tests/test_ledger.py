"""
Framework: tests for the two ledgers: the framework's (managed) and the project's (seeded, the project's to edit).
Package: tests/test_ledger

They read `Docs/standards/` of the repository they run in: the payload in the template, a made repository elsewhere.
Nothing here may fail because a project appended its own entries; that is what the project ledger is for.
"""

from __future__ import annotations

import re
from pathlib import Path

from pins import pins

ROOT = Path(__file__).resolve().parent.parent
STANDARDS = ROOT / "Docs" / "standards"
FRAMEWORK = STANDARDS / "failure-modes.md"
PROJECT = STANDARDS / "failure-modes-project.md"
LABELS = ("**Trigger:**", "**Do:**", "**Because:**")
END = "## How to add an entry"
BANNED = re.compile(
    r"hogshade|largeworlds|spritejammer|maya|bats\b|claude|gemini|copilot|cursor|codex|anthropic|openai"
    r"|\bgpu\b|shader|wgpu|skinning|draw call|\.archive|python|pytest|pip install",
    re.IGNORECASE,
)


def _heading_re(prefix: str) -> re.Pattern[str]:
    return re.compile(rf"^### {prefix}(\d+) · (.+)$", re.MULTILINE)


def _entries(text: str, prefix: str = "") -> list[tuple[int, str, str]]:
    """Each entry as (number, title, body), in file order, ending where the 'How to add an entry' section begins."""
    body = text.split(END)[0]
    matches = list(_heading_re(prefix).finditer(body))
    return [
        (int(m.group(1)), m.group(2), body[m.end() : matches[i + 1].start() if i + 1 < len(matches) else len(body)])
        for i, m in enumerate(matches)
    ]


def _unfenced(text: str) -> str:
    return re.sub(r"```.*?```", "", text, flags=re.DOTALL)


def _every_entry_heading_parses(text: str, prefix: str) -> list[str]:
    """Headings that look like an entry's but do not match its shape (a wrong separator is not silently skipped)."""
    pattern = _heading_re(prefix)
    return [
        line
        for line in _unfenced(text.split(END)[0]).splitlines()
        if line.startswith("### ") and not pattern.match(line)
    ]


@pins("Docs/standards/failure-modes.md")
def test_the_framework_ledger_entries_are_numbered_in_order_with_unique_titles() -> None:
    text = FRAMEWORK.read_text(encoding="utf-8")
    entries = _entries(text)
    assert [n for n, _, _ in entries] == list(range(1, len(entries) + 1))
    assert len(entries) >= 24
    titles = [title for _, title, _ in entries]
    assert len(set(titles)) == len(titles)
    assert _every_entry_heading_parses(text, "") == []


def _problems(where: str, body: str) -> list[str]:
    """What is wrong with one entry's body: a missing label, or the labels out of order. Empty if it is well formed."""
    missing = [label for label in LABELS if label not in body]
    if missing:
        return [f"{where} has no {', '.join(missing)}"]
    order = [body.index(label) for label in LABELS]
    return [] if order == sorted(order) else [f"{where} has its parts out of order"]


@pins("Docs/standards/failure-modes.md")
def test_every_framework_entry_has_a_trigger_a_do_and_a_because_in_that_order() -> None:
    for number, title, body in _entries(FRAMEWORK.read_text(encoding="utf-8")):
        assert _problems(f"entry {number} ({title})", body) == []


@pins("Docs/standards/failure-modes.md")
def test_github_commands_are_labelled_as_examples_not_prescribed() -> None:
    """The core is not tied to one forge: a `gh` command appears only in an entry that says it is a GitHub example."""
    for number, title, body in _entries(FRAMEWORK.read_text(encoding="utf-8")):
        if "`gh " in body:
            assert "on GitHub" in body, (
                f"entry {number} ({title}) prescribes a gh command without saying it is GitHub's"
            )


@pins("Docs/standards/failure-modes.md")
def test_the_trigger_index_points_only_at_entries_that_exist() -> None:
    text = FRAMEWORK.read_text(encoding="utf-8")
    count = len(_entries(text))
    index = text.split("## The ledger")[0].split("## If you notice...")[1]
    cited = {
        int(n) for row in index.splitlines() if row.startswith("| ") for n in re.findall(r"\b\d+\b", row.split("|")[2])
    }
    assert cited and max(cited) <= count and min(cited) >= 1
    assert cited == set(range(1, count + 1)), (
        f"entries missing from the index: {sorted(set(range(1, count + 1)) - cited)}"
    )


@pins("Docs/standards/failure-modes.md")
def test_the_framework_ledger_names_no_vendor_no_sibling_project_and_no_one_stack() -> None:
    found = BANNED.search(FRAMEWORK.read_text(encoding="utf-8"))
    assert not found, f"the framework ledger names {found.group(0)!r}"


@pins("Docs/standards/failure-modes.md")
def test_the_framework_ledger_says_it_is_managed_and_the_project_one_is_the_projects() -> None:
    framework = FRAMEWORK.read_text(encoding="utf-8")
    project = PROJECT.read_text(encoding="utf-8")
    assert "Managed by the template" in framework and "failure-modes-project.md" in framework
    assert "failure-modes.md" in project and "the project's to edit" in project


def test_the_project_ledger_shows_the_shape_and_whatever_entries_it_has_are_well_formed() -> None:
    """A project may append entries; this must stay green when it does. It checks the format, not the count."""
    project = PROJECT.read_text(encoding="utf-8")
    assert all(label in project for label in LABELS)  # the example in the fence shows the shape
    entries = _entries(_unfenced(project), "P-")
    assert [n for n, _, _ in entries] == list(range(1, len(entries) + 1))
    for number, title, body in entries:
        assert _problems(f"project entry P-{number} ({title})", body) == []
    assert _every_entry_heading_parses(project, "P-") == []


def test_the_entry_parser_sees_a_project_entry_and_a_malformed_heading() -> None:
    sample = (
        "# x\n\n### P-1 · Real\n\n**Trigger:** a\n**Do:** b\n**Because:** c\n\n### P-2 - wrong separator\n\n"
        "## How to add an entry\n\n### P-9 · Not an entry\n"
    )
    assert [n for n, _, _ in _entries(sample, "P-")] == [1]
    assert _every_entry_heading_parses(sample, "P-") == ["### P-2 - wrong separator"]


def test_the_entry_checker_catches_missing_and_misordered_labels() -> None:
    assert _problems("e", "**Trigger:** a\n**Do:** b\n**Because:** c\n") == []
    assert _problems("e", "**Trigger:** a\n**Do:** b\n") == ["e has no **Because:**"]
    assert _problems("e", "**Because:** c\n**Trigger:** a\n**Do:** b\n") == ["e has its parts out of order"]
