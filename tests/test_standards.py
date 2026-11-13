"""
Framework: tests that pin the decisions in the standards and check that the standards agree with the code.
Package: tests/test_standards

The standards are managed files; these tests read them in the payload and in a made repository alike. They are content
tests on purpose: each assertion is a decision the owner made, so changing one is a visible, reviewed act.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import framework_config as fc  # noqa: E402
import init  # noqa: E402
from pins import pins, shipped  # noqa: E402

STANDARDS = ROOT / "Docs" / "standards"
STATUS_WORDS = ("Proposed", "Accepted", "Living", "Superseded", "Abandoned")


def _text(name: str) -> str:
    return " ".join((STANDARDS / name).read_text(encoding="utf-8").split())


@pins("Docs/standards/definition-of-done.md")
def test_the_definition_of_done_holds_the_autonomy_protocol_and_its_backstop() -> None:
    dod = _text("definition-of-done.md")
    for phrase in (
        "Two-way door: decide, record, continue",
        "One-way door: stop and ask",
        "Eight decisions per pull request",
        "a decision not in the table was not reviewed",
        "an agent never merges",
        "Who merges and who decides",
        "A person on the roster merges",
        "helps them decide",
        "With no roster",
    ):
        assert phrase in dod, phrase


@pins("Docs/standards/definition-of-done.md")
def test_the_definition_of_done_states_the_identity_and_scope_rules() -> None:
    dod = _text("definition-of-done.md")
    assert (
        "a person's identity, never an agent's" in dod
        and "a roster person's own" in dod
        and "no attribution trailer or footer for an AI" in dod
    )
    assert "A session memory is not a record" in dod
    assert "say plainly what was left out and why" in dod
    assert "No test is deleted or skipped to get green" in dod


@pins("Docs/standards/definition-of-done.md")
def test_the_definition_of_done_agrees_with_the_code_on_the_handoff_limit() -> None:
    dod = _text("definition-of-done.md")
    assert f"default {fc.DEFAULT_HANDOFF_MAX_LINES}" in dod and "`handoff_max_lines`" in dod


@pytest.mark.skipif(
    (ROOT / "project.json").exists(), reason="reads the seeds as the payload ships them; a made repository owns them"
)
def test_the_status_words_are_the_same_closed_set_in_the_standard_the_glossary_and_the_tests() -> None:
    dod = _text("definition-of-done.md")
    glossary = " ".join((ROOT / "Docs" / "glossary.md").read_text(encoding="utf-8").split())
    for word in STATUS_WORDS:
        assert f"`{word}`" in dod and f"`{word}`" in glossary, word


@pytest.mark.skipif(
    (ROOT / "project.json").exists(), reason="reads the seeds as the payload ships them; a made repository owns them"
)
def test_the_documents_agree_on_the_eight_decision_backstop_and_on_how_a_design_is_locked() -> None:
    texts = {
        name: " ".join(path.read_text(encoding="utf-8").split())
        for name, path in {
            "AGENTS.md": ROOT / "AGENTS.md",
            "glossary": ROOT / "Docs" / "glossary.md",
            "definition of done": STANDARDS / "definition-of-done.md",
        }.items()
    }
    for name, text in texts.items():
        assert "eight" in text.lower(), f"{name} does not state the eight-decision backstop"
    for name, text in {**texts, "workflow": _text("workflow.md")}.items():
        assert "says *Locked*" not in text and "`Exploring`" not in text, f"{name} uses a status word outside the set"
    handoff = (ROOT / "Docs" / "handoffs" / "CURRENT.md").read_text(encoding="utf-8")
    assert "the owner states a preference" in " ".join(handoff.split()), (
        "the handoff header disagrees with the definition of done"
    )


@pins("Docs/standards/workflow.md")
def test_the_workflow_has_every_stage_including_the_ux_mock_pass_and_a_persons_merge() -> None:
    workflow = (STANDARDS / "workflow.md").read_text(encoding="utf-8")
    rows = re.findall(r"^\| (\d+a?) \| \*\*([^*]+)\*\*", workflow, re.MULTILINE)
    assert [number for number, _ in rows] == ["0", "1", "1a", "2", "3", "4", "5", "6", "7"]
    assert any("UX mock pass" in name for _, name in rows)
    flat = " ".join(workflow.split())
    assert "A person on the roster merges and deletes the branch" in flat and "A board yes is not a lock" in flat
    assert "An agent never merges" in flat and "the owner merges" not in flat.lower()
    assert "moves from `Proposed` to `Accepted`" in flat  # a lock uses the closed status vocabulary, no new word


@pins("Docs/standards/workflow.md")
def test_the_workflow_names_what_each_record_owns() -> None:
    workflow = (STANDARDS / "workflow.md").read_text(encoding="utf-8")
    owners = re.findall(r"^\| \*\*([^*]+)\*\* \| ", workflow, re.MULTILINE)
    for record in ("Roadmap", "Design", "Spec", "Plan", "Board", "ADR", "Journal", "Handoff", "Glossary", "Ledger"):
        assert record in owners, record


@pins("Docs/standards/python.md")
def test_the_python_standard_holds_the_picks_of_the_extraction() -> None:
    python = _text("python.md")
    for phrase in (
        "`X | None`",
        "never `typing.Optional`",
        "`E501` is on",
        "f-strings in log calls",
        "`# lazy-log: <the measurement>`",
        "`_LOGGER` from `_MODULE_NAME`, never `__name__`",
        "`__version__` before `__updated__`",
        "`__author__` (the people on the roster who wrote the module) may follow them",
        "`print()` only for a script's final summary",
    ):
        assert phrase in python, phrase


@pins("Docs/standards/testing.md")
def test_the_testing_standard_holds_the_invocation_rule_and_the_load_bearing_conventions() -> None:
    testing = _text("testing.md")
    for phrase in (
        "the `pytest` console script, never `python -m pytest`",
        "Test first",
        "Prove the instrument before trusting a negative.",
        "Assert the value, not the shape.",
        "Do not pin a hash of computed floats.",
        "Skip with a reason, never silently.",
        "Never `import tools.check_docs`",
    ):
        assert phrase in testing, phrase


# ---------------------------------------------------------------------------- what #17 to #46 taught the payload
ERROR_PATH_ITEMS = (
    "Every nonzero exit",
    "A lookup that fails",
    "An unreadable thing is not a missing one",
    "A malformed or partial result is an error",
    "A timeout holds with child processes",
    "Symlinks",
    "A path leaves the root",
    "A check, then a use",
    "A guard's negative control",
)


@pins("Docs/standards/testing.md")
def test_the_testing_standard_holds_the_error_path_checklist_with_its_nine_items() -> None:
    testing = _text("testing.md")
    assert "Error paths: three outcomes, never two" in testing
    assert "an error, an absent answer and a present one" in testing
    assert "pull requests 17 to 46 of the template" in testing
    for item in ERROR_PATH_ITEMS:
        assert item in testing, item


@pins("Docs/standards/python.md")
def test_the_python_standard_points_at_the_error_path_checklist() -> None:
    python = _text("python.md")
    assert "A call to the outside world has three outcomes" in python and "*Error paths*" in python


# ---------------------------------------------------------------------------- logging in tiers (#143)
@pins("Docs/standards/python.md")
def test_the_python_standard_holds_the_tool_root_pattern_as_a_declared_tier() -> None:
    python = _text("python.md")
    assert "### The tool-root pattern" in (STANDARDS / "python.md").read_text(encoding="utf-8")
    assert "The three loggers" not in python
    assert "says so in its design or spec" in python
    assert "examples/tool_root_logging.py" in python
    assert (STANDARDS / "examples" / "tool_root_logging.py").is_file()


@pins("Docs/standards/testing.md")
def test_the_testing_standard_says_how_to_capture_logs_under_a_tool_root_logger() -> None:
    testing = (STANDARDS / "testing.md").read_text(encoding="utf-8")
    assert "## Capturing logs under a tool-root logger" in testing
    assert "def tool_root_caplog(" in testing
    assert "A test never switches `propagate` on" in testing


@pins(".agents/skills/local-review/references/rubric.md")
def test_the_review_rubric_cites_the_error_path_checklist() -> None:
    lines = (ROOT / ".agents/skills/local-review/references/rubric.md").read_text(encoding="utf-8").splitlines()
    row = next(line for line in lines if line.startswith("| Error handling |"))
    assert "checklist in `testing.md`" in row


@pins("Docs/standards/workflow.md")
def test_the_workflow_holds_the_two_standing_rules_the_defect_scan_added() -> None:
    workflow = _text("workflow.md")
    assert "A spec lists, for every framework file it adds or changes" in workflow
    assert "project's own files are in no manifest" in workflow  # #93: the rule is not asked of them
    assert "A script or a patch that contains backslashes or quotes is written to a file and the file run" in workflow


@pins("Docs/standards/tooling.md")
def test_tooling_lists_the_renderers_and_reaches_the_journal_standard() -> None:
    """A repository that overrides definition-of-done.md loses that file's link to journal.md (HogShade's 0.3.0 update);
    tooling.md, which every map links, is a second managed path to it."""
    text = (STANDARDS / "tooling.md").read_text(encoding="utf-8")
    assert "](journal.md)" in text
    assert "tools/render_journal_index.py" in text and "tools/render_board.py" in text


EXTENSION_SENTENCE = (
    "an extension adds rules and never weakens these. To relax or contradict a rule here, override this file in "
    "`framework.toml` with a reason that names the rule."
)


def managed_standards() -> list[str]:
    """The file names of the managed standards, from the manifest: a standard it does not list is not a base."""
    rules = init.load_manifest(ROOT / init.MANIFEST_NAME)
    return sorted(
        rule.pattern.removeprefix("Docs/standards/")
        for rule in rules
        if rule.kind == "managed" and rule.pattern.startswith("Docs/standards/") and "*" not in rule.pattern
    )


BASES = [f"Docs/standards/{name}" for name in managed_standards()]
SHIPPED_SKILLS = shipped(
    ROOT, sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / ".agents" / "skills").glob("*/SKILL.md"))
)


@pytest.mark.skipif(
    (ROOT / "project.json").exists(), reason="the payload's own manifest and standards, not a repository's"
)
def test_every_standard_the_payload_ships_is_in_the_manifest_as_a_base() -> None:
    on_disk = sorted(p.name for p in STANDARDS.glob("*.md") if not p.name.endswith("-project.md"))
    assert on_disk == managed_standards()  # a new standard is a base, and gets its sentence


@pytest.mark.parametrize(
    "rel", [pytest.param(rel, marks=pins(rel), id=rel) for rel in BASES]
)  # one case per base: overriding one excuses that one, and a project's extension beside it is its own
def test_each_managed_standard_names_its_extension_after_its_status_lines(rel: str) -> None:
    name = rel.rpartition("/")[2]
    text = (ROOT / rel).read_text(encoding="utf-8")
    joined = " ".join(text.split())
    own = (
        "[failure-modes-project.md](failure-modes-project.md)"
        if name == "failure-modes.md"
        else f"`{name[:-3]}-project.md`"
    )
    assert f"**This project's additions** go in {own} beside this file" in joined
    assert EXTENSION_SENTENCE in joined
    assert text.index("**Status:**") < text.index("**This project's additions**") < text.index("\n## ")


@pytest.mark.parametrize(
    "rel", [pytest.param(rel, marks=pins(rel), id=rel) for rel in SHIPPED_SKILLS]
)  # one case per skill the lock lists: a skill the project added is its own
def test_each_shipped_skill_names_project_md_in_its_folder_after_its_front_matter(rel: str) -> None:
    text = (ROOT / rel).read_text(encoding="utf-8")
    joined = " ".join(text.split())
    assert "**This project's additions** go in `project.md` in this skill's folder" in joined
    assert EXTENSION_SENTENCE in joined
    front_matter_end = text.index("\n---\n", 3)
    assert front_matter_end < text.index("**This project's additions**") < text.index("\n## ")


def test_the_payload_ships_at_least_the_two_skills() -> None:
    assert len(SHIPPED_SKILLS) >= 2, SHIPPED_SKILLS
