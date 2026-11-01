"""
Framework: tests for the pull request template and the two skills the template ships.
Package: tests/test_skills_and_template

They read the repository they run in (the payload in the template, a made repository elsewhere): the skills are managed
files, so every repository must carry them intact.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from pins import pins, shipped

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / ".github" / "pull_request_template.md"
SKILLS = ROOT / ".agents" / "skills"
DEFINITION_OF_DONE = ROOT / "Docs" / "standards" / "definition-of-done.md"
SECTIONS = ("What changed", "Verified", "Decisions", "Wrong along the way", "Review", "Not covered")
FRONTMATTER_KEYS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
# Words that tie a skill to one tool, one forge's vocabulary without saying so, or one of the repositories it came from.
BANNED = re.compile(
    r"claude|gemini|copilot|cursor|codex|anthropic|openai|hogshade|largeworlds|spritejammer"
    r"|\bIDE\b|editor's focus|/local-review|agent tool|subagent tool|synchronously",
    re.IGNORECASE,
)


def _flat(path: Path) -> str:
    """The file's text with emphasis marks removed and whitespace joined, so a pin survives formatting changes."""
    return " ".join(path.read_text(encoding="utf-8").replace("**", "").replace("*", "").split())


def _frontmatter(text: str) -> dict[str, str]:
    """The leading `---` block as a flat mapping, rejecting what a real YAML loader (a harness) would reject or misread.

    Each line must be `key: value` with a plain single-line value: no colon-space or ` #` inside it (YAML reads them as
    mapping or a comment), and no block scalar (`>` or `|`), quote or continuation line.
    """
    match = re.match(r"---\n(.*?)\n---\n", text, re.DOTALL)
    assert match, "no frontmatter"
    result: dict[str, str] = {}
    for line in match.group(1).splitlines():
        key, separator, value = line.partition(": ")
        assert separator and re.fullmatch(r"[a-z][a-z-]*", key), f"not a `key: value` line: {line!r}"
        assert key not in result, f"{key} twice"
        assert value and value[0] not in ">|\"'[{&*!%@`", f"{key}: a value YAML would not read as plain text"
        assert ": " not in value and " #" not in value, f"{key}: a colon-space or ' #' in a plain value"
        result[key] = value
    return result


def test_the_frontmatter_parser_rejects_what_a_real_yaml_loader_would() -> None:
    good = "---\nname: x-y\ndescription: Use it when asked.\n---\nbody\n"
    assert _frontmatter(good) == {"name": "x-y", "description": "Use it when asked."}
    for bad in (
        "---\nname: x\ndescription: Use this: when asked\n---\n",
        "---\nname: x\ndescription: >\n  folded\n---\n",
        "---\nname: x\ndescription: a # comment\n---\n",
        '---\nname: x\ndescription: "quoted"\n---\n',
        "---\nname: x\n  continued: line\n---\n",
        "---\nname: x\nname: y\n---\n",
        "no frontmatter\n",
    ):
        try:
            _frontmatter(bad)
        except AssertionError:
            continue
        raise AssertionError(f"accepted {bad!r}")


def test_every_skill_is_a_folder_with_a_skill_md_whose_name_is_the_folder() -> None:
    folders = sorted(p for p in SKILLS.iterdir() if p.is_dir())
    assert {p.name for p in folders} >= {"local-review", "review-and-pr"}
    for folder in folders:
        meta = _frontmatter((folder / "SKILL.md").read_text(encoding="utf-8"))
        assert set(meta) <= FRONTMATTER_KEYS and {"name", "description"} <= set(meta), folder.name
        assert meta["name"] == folder.name, folder.name
        assert re.fullmatch(r"[a-z][a-z0-9]*(-[a-z0-9]+)*", meta["name"]) and len(meta["name"]) <= 64
        assert 60 <= len(meta["description"]) <= 1024, f"{folder.name}: description length {len(meta['description'])}"


def _links_that_do_not_resolve(path: Path) -> list[str]:
    broken = []
    for target in re.findall(r"\]\(([^)\s]+)\)", path.read_text(encoding="utf-8")):
        if re.match(r"[a-zA-Z][a-zA-Z0-9+.-]*:", target) or target.startswith("#"):
            continue
        resolved = Path(os.path.normpath(path.parent / target.split("#")[0]))
        current = ROOT
        for part in resolved.relative_to(ROOT).parts:  # case-exact, as a case-sensitive runner will see it
            if part not in {child.name for child in current.iterdir()}:
                broken.append(target)
                break
            current = current / part
    return broken


def test_links_in_the_skills_and_the_template_resolve_with_the_right_case() -> None:
    for path in [*SKILLS.rglob("*.md"), TEMPLATE]:
        assert _links_that_do_not_resolve(path) == [], path.relative_to(ROOT)


def test_the_link_check_sees_a_fragment_and_a_case_mistake(tmp_path: Path) -> None:
    probe = ROOT / ".agents" / "skills" / "local-review" / "_probe.md"
    probe.write_text("[ok](SKILL.md#x) [bad](skill.md#x) [bad2](references/missing.md)\n", encoding="utf-8")
    try:
        assert _links_that_do_not_resolve(probe) == ["skill.md#x", "references/missing.md"]
    finally:
        probe.unlink()


NEUTRAL_DOCUMENTS = shipped(ROOT, sorted(p.relative_to(ROOT).as_posix() for p in [*SKILLS.rglob("*.md"), TEMPLATE]))


@pytest.mark.parametrize(
    "rel", [pytest.param(rel, marks=pins(rel), id=rel) for rel in NEUTRAL_DOCUMENTS]
)  # one case per document: overriding one excuses that one
def test_each_skill_and_the_template_is_neutral_about_tools_and_the_projects_it_came_from(rel: str) -> None:
    found = BANNED.search((ROOT / rel).read_text(encoding="utf-8"))
    assert not found, f"{rel} names {found.group(0)!r}"


def test_only_the_documents_the_lock_lists_are_held_to_the_frameworks_neutrality(tmp_path: Path) -> None:
    documents = [".agents/skills/local-review/SKILL.md", ".agents/skills/maya-check/SKILL.md"]
    assert shipped(tmp_path, documents) == documents  # no lock: the payload itself
    (tmp_path / "framework.lock").write_text(json.dumps({"files": {documents[0]: "x"}}), encoding="utf-8")
    assert shipped(tmp_path, documents) == documents[:1]  # a skill the project added is its own
    (tmp_path / "framework.lock").write_text("not json", encoding="utf-8")
    assert shipped(tmp_path, documents) == documents  # unreadable: nothing is excused
    (tmp_path / "framework.lock").write_text("[" * 200000, encoding="utf-8")
    assert (
        shipped(tmp_path, documents) == documents
    )  # nested deeply enough to overflow the parser: still nothing excused


def test_the_neutrality_guard_can_fail_and_there_are_documents_to_read() -> None:
    assert len(NEUTRAL_DOCUMENTS) >= 4
    for control in ("a Claude subagent", "the IDE focus", "run /local-review", "the Agent tool", "run synchronously"):
        assert BANNED.search(control), control  # the guard can fail


@pins(".agents/skills/local-review/SKILL.md")
def test_the_reviewer_is_a_role_that_has_not_seen_the_authors_reasoning() -> None:
    review = _flat(SKILLS / "local-review" / "SKILL.md")
    assert "has not seen the author's reasoning" in review and "That is a role, not a tool" in review
    assert "Leave out your own summary of the change" in review


@pins(".agents/skills/local-review/references/rubric.md")
def test_the_rubric_has_ten_metrics_a_seven_baseline_hard_findings_and_the_output_template() -> None:
    rubric = (SKILLS / "local-review" / "references" / "rubric.md").read_text(encoding="utf-8")
    table = rubric.split("## Metrics")[1].split("## Baseline")[0]
    metrics = [m for m in re.findall(r"^\| ([A-Z][A-Za-z ]+) \| ", table, re.MULTILINE) if m != "Metric"]
    assert metrics == [
        "Design",
        "Architecture",
        "Readability",
        "Maintainability",
        "Performance",
        "Security",
        "Error handling",
        "Logging",
        "Coding standards",
        "Layering",
    ]
    flat = " ".join(rubric.split())
    assert (
        "7/10 per metric is the bar" in flat and "### Below baseline (< 7)" in rubric and "### Hard findings" in rubric
    )
    assert "Any hard finding makes the verdict `needs work`" in flat and "do not claim a pass" in flat


@pins(".agents/skills/review-and-pr/SKILL.md")
def test_review_and_pr_keeps_the_rules_the_ledger_and_the_definition_of_done_state() -> None:
    skill = _flat(SKILLS / "review-and-pr" / "SKILL.md")
    for phrase in (
        "run unpiped",
        "Stage named paths",
        "a person's identity, never an agent's",
        "an agent never merges",
        "`signoff` true",
        "no attribution line for an AI",
        "read it; do not assume it",
        "--body-file",
        "decide valid or not from the code, not from the comment's confidence",
        "open a tracker issue before the pull request merges",
        "names the commit only after the commit exists",
        "suppressed comments",
        "--paginate",
        "issues/<n>/comments",
        "resolveReviewThread",
        "retarget the stack",
        "say so in the pull request and do not claim a pass",
        "never merge",
    ):
        assert phrase in skill, phrase


@pins(".github/pull_request_template.md")
def test_the_pull_request_template_has_every_section_and_the_checks_the_definition_of_done_names() -> None:
    text = TEMPLATE.read_text(encoding="utf-8")
    for section in (*SECTIONS, "Measured"):
        assert re.search(rf"^## {section}\s*$", text, re.MULTILINE), section
    assert "| Decision | Alternative | Why | Reverse cost |" in text
    assert "**Board:**" in text and "MORE THAN 8" in text
    assert len(re.findall(r"^- \[ \] (.+)$", text, re.MULTILINE)) == 6
    flat = " ".join(text.split())
    for phrase in (
        "`make check` passes locally, **run unpiped**",
        "New terms:",
        "Docs match reality, as the definition of done lists them",
        "there are no more than 8",
        "before the session ends",
        "back to back",
    ):
        assert phrase in flat, phrase


def test_the_template_title_example_names_nothing_of_the_template_repository() -> None:
    title = TEMPLATE.read_text(encoding="utf-8").split("-->")[0]
    assert not re.search(r"\binit\b|framework|lock\b|payload|plan task 4", title, re.IGNORECASE)


REVIEW_TRIGGER = "When the deliberate review runs"


@pins("Docs/standards/definition-of-done.md")
def test_the_review_trigger_has_its_name_in_the_definition_of_done() -> None:
    assert f"## {REVIEW_TRIGGER}" in DEFINITION_OF_DONE.read_text(encoding="utf-8")


@pins(".github/pull_request_template.md")
def test_the_review_trigger_has_its_name_in_the_template() -> None:
    assert REVIEW_TRIGGER in TEMPLATE.read_text(encoding="utf-8")


@pins(".agents/skills/local-review/SKILL.md")
def test_the_review_trigger_has_its_name_in_the_skill() -> None:
    assert REVIEW_TRIGGER in _flat(SKILLS / "local-review" / "SKILL.md")
