"""
Framework: tests for the seeded documents: a repository made from the payload starts with a consistent set of them.
Package: tests/test_seed_documents

These are a stand-in for the docs check until it is ported into the payload (plan task 6): every governed document has
a status line, every relative link resolves with the right case, the journal and ADR indexes list their files, and the
handoff's date has a journal file.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import check_docs as cd  # noqa: E402
import framework_config as fc  # noqa: E402
import init as ini  # noqa: E402
import sync_adapters  # noqa: E402

pytestmark = pytest.mark.skipif(
    (ROOT / "project.json").exists(),
    reason="runs only against the template's payload, not in a repository made from it",
)

TODAY = "2026-10-10"
ANSWERS = {
    "name": "Example Project",
    "slug": "example-project",
    "owner": {"name": "Ada Example", "email": "ada@example.org"},
    "default_branch": "main",
    "signoff": True,
    "hygiene": [],
}
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
STATUS_WORDS = ("Proposed", "Accepted", "Living", "Superseded", "Abandoned")


@pytest.fixture(scope="module")
def made(tmp_path_factory: pytest.TempPathFactory) -> Path:
    base = tmp_path_factory.mktemp("made")
    answers = base / "answers.json"
    answers.write_text(json.dumps(ANSWERS), encoding="utf-8")
    target = base / "proj"
    argv = ["new", "--answers", str(answers), "--target", str(target), "--no-sync", "--no-checks"]
    assert ini.main(argv, source=ROOT, today=TODAY) == 0
    return target


def _markdown(target: Path) -> list[Path]:
    return sorted(p for p in target.rglob("*.md") if ".venv" not in p.parts and "logs" not in p.parts)


def _exists_exact(path: Path, root: Path) -> bool:
    """Case-exact existence: a link that resolves on a case-insensitive disk must resolve on Linux too."""
    current = root
    for part in path.relative_to(root).parts:
        if part not in {child.name for child in current.iterdir()}:
            return False
        current = current / part
    return True


def test_the_seeded_documents_exist_with_today_in_their_paths(made: Path) -> None:
    expected = [
        "AGENTS.md",
        "Docs/README.md",
        "Docs/glossary.md",
        "Docs/plan/board/README.md",
        f"Docs/plan/board/{TODAY}-first-gate.md",
        f"Docs/plan/board/{TODAY}-first-idea.md",
        "Docs/handoffs/CURRENT.md",
        "Docs/journal/README.md",
        f"Docs/journal/{TODAY}-session-01.md",
        "Docs/decisions/README.md",
        "Docs/decisions/ADR-001-adopt-the-framework.md",
        "Docs/standards/failure-modes.md",
        "Docs/standards/failure-modes-project.md",
        "Docs/standards/definition-of-done.md",
        "Docs/standards/workflow.md",
        "Docs/standards/python.md",
        "Docs/standards/testing.md",
        ".github/pull_request_template.md",
        ".agents/skills/local-review/SKILL.md",
        ".agents/skills/local-review/references/rubric.md",
        ".agents/skills/review-and-pr/SKILL.md",
    ]
    for rel in expected:
        assert (made / rel).is_file(), rel


def test_no_token_is_left_unreplaced(made: Path) -> None:
    # a token is {{word}}; Mermaid's hexagon, {{"label"}}, in the generated framework graph is not one
    token = re.compile(r"\{\{\w+\}\}")
    for path in _markdown(made):
        assert not token.search(path.read_text(encoding="utf-8")), path.relative_to(made)
        assert "{{" not in path.name


def test_every_governed_document_has_a_status_in_its_first_twelve_lines(made: Path) -> None:
    for path in _markdown(made):
        rel = path.relative_to(made).as_posix()
        if (
            not rel.startswith("Docs/")
            or re.fullmatch(r"Docs/journal/\d{4}-\d{2}-\d{2}-session-\d{2}\.md", rel)
            or re.fullmatch(r"Docs/plan/board/\d{4}-\d{2}-\d{2}-[a-z0-9-]+\.md", rel)
        ):
            continue  # only Docs/ is governed; a session file and a board row file are governed by their own rules
        head = "\n".join(path.read_text(encoding="utf-8").splitlines()[:12])
        match = re.search(r"\*\*Status:\*\*\s*(\w+)", head)
        assert match, f"{rel}: no **Status:** line in the first 12 lines"
        assert match.group(1) in STATUS_WORDS, f"{rel}: status {match.group(1)!r} is not one of {STATUS_WORDS}"


def test_every_relative_link_resolves_with_the_right_case(made: Path) -> None:
    for path in _markdown(made):
        for target in LINK_RE.findall(path.read_text(encoding="utf-8")):
            if re.match(r"[a-zA-Z][a-zA-Z0-9+.-]*:", target) or target.startswith("#"):
                continue
            # normpath, not resolve(): resolve() corrects the case on Windows and would hide a case-only mistake
            normalised = Path(os.path.normpath(path.parent / target.split("#")[0]))
            if normalised == made / "Docs/plan/BOARD.md":
                continue  # the board page is rendered from the row files and absent on a fresh clone
            assert _exists_exact(normalised, made), f"{path.relative_to(made)}: broken link {target}"


def test_the_indexes_list_what_they_index(made: Path) -> None:
    journal = (made / "Docs/journal/README.md").read_text(encoding="utf-8")
    for session in (made / "Docs/journal").glob("*-session-*.md"):
        assert session.name in journal, session.name
    decisions = (made / "Docs/decisions/README.md").read_text(encoding="utf-8")
    for adr in (made / "Docs/decisions").glob("ADR-*.md"):
        assert adr.name in decisions, adr.name


def test_the_handoff_is_dated_and_the_journal_has_that_day(made: Path) -> None:
    handoff = (made / "Docs/handoffs/CURRENT.md").read_text(encoding="utf-8")
    match = re.search(r"\*\*Last updated:\*\*\s*(\d{4}-\d{2}-\d{2})", handoff)
    assert match and match.group(1) == TODAY
    assert (made / f"Docs/journal/{TODAY}-session-01.md").is_file()


def test_the_board_has_its_five_sections_and_the_first_gate(made: Path, tmp_path: Path) -> None:
    """The seeded board is a directory of row files: the page is rendered, and has the sections and the first gate."""
    copy = tmp_path / "render"
    shutil.copytree(made, copy, ignore=shutil.ignore_patterns(".venv", "logs"))
    assert not (copy / "Docs/plan/BOARD.md").exists()
    tool = str(copy / "tools/render_board.py")
    ran = subprocess.run([sys.executable, tool], cwd=copy, capture_output=True, text=True)
    assert ran.returncode == 0, ran.stdout + ran.stderr
    board = (copy / "Docs/plan/BOARD.md").read_text(encoding="utf-8")
    for section in ("Gates", "Now", "Next", "Blocked", "Icebox"):
        assert re.search(rf"^## {section}\s*$", board, re.MULTILINE), section
    assert "[G1: name the first increment]" in board
    assert [str(f) for f in cd.run(cd.load_context(copy))] == []  # the rendered page is skipped, not read


def test_the_entry_file_states_no_status_and_names_the_owner_identity_rule(made: Path) -> None:
    text = (made / "AGENTS.md").read_text(encoding="utf-8")
    assert "Ada Example <ada@example.org>" in text and "`main`" in text
    assert "**Status:**" not in text  # a pointer, not a summary: no status, counts or phase


def test_the_seeds_stay_neutral_about_vendors_and_the_projects_the_template_came_from(made: Path) -> None:
    banned = re.compile(
        r"hogshade|largeworlds|spritejammer|maya|bats\b|claude|gemini|copilot|cursor|codex|anthropic|openai",
        re.IGNORECASE,
    )
    described = set(sync_adapters.NEUTRAL_EXEMPT)  # where harnesses are described
    for path in _markdown(made):
        if path.relative_to(made).as_posix() in described:
            continue
        found = banned.search(path.read_text(encoding="utf-8"))
        assert not found, f"{path.relative_to(made)} names {found.group(0)!r}"


def test_the_seeds_agree_on_the_journal_cadence_and_the_icebox_columns(made: Path) -> None:
    for path in _markdown(made):
        assert "One file per calendar day" not in path.read_text(encoding="utf-8"), path.relative_to(made)
    rows = (made / "Docs/plan/board/README.md").read_text(encoding="utf-8")
    assert "**Cost:**" in rows and "**Verdict:**" in rows and "**Raised:**" in rows
    agents = " ".join((made / "AGENTS.md").read_text(encoding="utf-8").split())  # the wrapping is not the rule
    assert "cost, a reason and a verdict" in agents and "a link to where it was said" in agents
    idea = (made / f"Docs/plan/board/{TODAY}-first-idea.md").read_text(encoding="utf-8")
    assert "a link to where it was said" in " ".join(idea.split())


def test_the_entry_file_points_at_both_ledgers_and_only_the_frameworks_is_locked(made: Path) -> None:
    agents = (made / "AGENTS.md").read_text(encoding="utf-8")
    assert "Docs/standards/failure-modes.md" in agents and "Docs/standards/failure-modes-project.md" in agents
    assert "failure-modes-project.md" in (made / "Docs/README.md").read_text(encoding="utf-8")
    lock = json.loads((made / "framework.lock").read_text(encoding="utf-8"))
    assert "Docs/standards/failure-modes.md" in lock["files"]  # the framework's ledger is managed: locked
    assert "Docs/standards/failure-modes-project.md" not in lock["files"]  # the project's is not


def test_the_adr_names_the_template_version_and_claims_only_what_exists(made: Path) -> None:
    adr = (made / "Docs/decisions/ADR-001-adopt-the-framework.md").read_text(encoding="utf-8")
    version = fc.load_framework(ROOT / "framework.toml").template_version  # what the payload ships, not a literal
    assert f"version {version}" in adr
    assert "later increment" in adr  # the sync check is not promised as if it existed


def test_the_day_zero_checklist_starts_with_the_first_commit_and_says_what_a_design_is(made: Path) -> None:
    handoff = (made / "Docs/handoffs/CURRENT.md").read_text(encoding="utf-8")
    assert "git init -b main" in handoff and "git commit -s" in handoff and "uv sync" in handoff
    assert "## Terms introduced" in handoff


@pytest.mark.parametrize("module", ["journal", "python-uv", "graph"])
def test_a_repository_made_with_a_linked_module_off_is_refused(tmp_path: Path, module: str) -> None:
    answers = tmp_path / "answers.json"
    answers.write_text(json.dumps(ANSWERS), encoding="utf-8")
    target = tmp_path / "proj"
    target.mkdir()
    text = (ROOT / "framework.toml").read_text(encoding="utf-8").replace(f'{module} = "on"', f'{module} = "off"')
    (target / "framework.toml").write_text(text, encoding="utf-8")
    argv = ["new", "--answers", str(answers), "--target", str(target), "--no-sync", "--no-checks"]
    assert ini.main(argv, source=ROOT, today=TODAY) == 1  # the seeds link to its files; no broken links are made
    assert not (target / "AGENTS.md").exists()


def test_making_the_repository_again_on_another_day_changes_nothing(tmp_path: Path) -> None:
    answers = tmp_path / "answers.json"
    answers.write_text(json.dumps(ANSWERS), encoding="utf-8")
    target = tmp_path / "proj"
    argv = ["new", "--answers", str(answers), "--target", str(target), "--no-sync", "--no-checks"]
    assert ini.main(argv, source=ROOT, today=TODAY) == 0
    first = {
        p.relative_to(target).as_posix(): p.read_bytes()
        for p in target.rglob("*")
        if p.is_file() and "logs" not in p.parts
    }
    assert ini.main(argv, source=ROOT, today="2027-01-01") == 0
    again = {
        p.relative_to(target).as_posix(): p.read_bytes()
        for p in target.rglob("*")
        if p.is_file() and "logs" not in p.parts
    }
    assert again == first


def test_a_made_repository_starts_with_an_empty_project_ledger(made: Path) -> None:
    project = (made / "Docs/standards/failure-modes-project.md").read_text(encoding="utf-8")
    unfenced = re.sub(r"```.*?```", "", project, flags=re.DOTALL)
    assert re.findall(r"^### ", unfenced, re.MULTILINE) == []
    assert "Failure modes: Example Project" in project and "{{" not in project


def test_the_template_the_skills_and_the_standards_are_managed_and_therefore_locked(made: Path) -> None:
    lock = json.loads((made / "framework.lock").read_text(encoding="utf-8"))["files"]
    for rel in (
        ".github/pull_request_template.md",
        ".agents/skills/local-review/SKILL.md",
        ".agents/skills/local-review/references/rubric.md",
        ".agents/skills/review-and-pr/SKILL.md",
        "Docs/standards/definition-of-done.md",
        "Docs/standards/workflow.md",
        "Docs/standards/python.md",
        "Docs/standards/testing.md",
    ):
        assert rel in lock, rel


def test_a_made_repository_ignores_the_rendered_journal_index_and_can_render_it(made: Path, tmp_path: Path) -> None:
    ignored = (made / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "Docs/journal/INDEX.md" in ignored
    makefile = (made / "Makefile").read_text(encoding="utf-8")
    assert "\njournal:\n\tuv run python tools/render_journal_index.py\n" in makefile
    readme = (made / "Docs/journal/README.md").read_text(encoding="utf-8")
    assert "standards/journal.md" in readme and "](INDEX.md)" not in readme  # the page is absent on a fresh clone
    assert (made / "Docs/standards/journal.md").is_file()

    copy = tmp_path / "copy"
    shutil.copytree(made, copy, ignore=shutil.ignore_patterns(".venv", "logs"))
    before = [str(f) for f in cd.run(cd.load_context(copy))]
    ran = subprocess.run(
        [sys.executable, str(copy / "tools/render_journal_index.py")], cwd=copy, capture_output=True, text=True
    )
    assert ran.returncode == 0, ran.stdout + ran.stderr
    assert (copy / "Docs/journal/INDEX.md").is_file()
    assert [str(f) for f in cd.run(cd.load_context(copy))] == before == []


def test_the_standard_is_reached_from_the_map_through_a_managed_file_alone(made: Path, tmp_path: Path) -> None:
    """A repository that keeps its old project-owned README, map and journal README still reaches the standard: the
    managed definition of done links it, and it is linked from the map the definition of done is linked from."""
    copy = tmp_path / "old-seeds"
    shutil.copytree(made, copy, ignore=shutil.ignore_patterns(".venv", "logs"))
    (copy / "Docs/journal/README.md").write_text(
        "# Journal\n\n**Status:** Living.\n\n| Date | Session |\n| --- | --- |\n"
        f"| {TODAY} | [Session 01]({TODAY}-session-01.md) |\n",
        encoding="utf-8",
    )
    readme = (copy / "Docs/README.md").read_text(encoding="utf-8")
    (copy / "Docs/README.md").write_text(
        "\n".join(line for line in readme.splitlines() if "standards/journal.md" not in line) + "\n", encoding="utf-8"
    )
    assert [str(f) for f in cd.run(cd.load_context(copy)) if "orphan" in str(f)] == []
