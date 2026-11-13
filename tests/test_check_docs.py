"""
Framework: tests for tools/check_docs.py (the unified docs check).
Package: tests/test_check_docs

Acceptance 4: every check can fail. Each test below starts from a small corpus that passes every check, breaks exactly
one rule, and requires the finding under that rule's name and nothing else; the same corpus unbroken passes. A check
that was only ever shown passing has not been shown to work (ledger entry 6).
"""

from __future__ import annotations

import dataclasses
import json
import posixpath
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import check_docs as cd  # noqa: E402
import framework_config as fc  # noqa: E402
import init as ini  # noqa: E402
from pins import pins  # noqa: E402

TODAY = "2026-10-11"

FRAMEWORK_TOML = """\
[framework]
template_version = "0.1.0"

[modules]
core = "on"
journal = "{journal}"
ux = "planned"
python-uv = "on"
tasking = "planned"
hygiene = "planned"
graph = "planned"
harness-adapters = "planned"
specimens = "planned"
lanes = "off"
branch-ownership = "off"
devblog = "off"

[harnesses]
enabled = []

[checks]
handoff_max_lines = {limit}
{extra}
"""


def _doc(status: str = "Living", body: str = "Text.\n") -> str:
    return f"# Title\n\n**Status:** {status}. A document.\n\n{body}"


def base_files() -> dict[str, str]:
    """A corpus every check passes: each document is linked from another, each index lists its files."""
    return {
        "README.md": "# Project\n\nSee [the docs](Docs/README.md).\n",
        "Docs/README.md": _doc(
            body=(
                "[handoff](handoffs/CURRENT.md) [board](plan/BOARD.md) [journal](journal/README.md)"
                " [decisions](decisions/README.md) [spec](standards/one.md)\n"
            ),
        ),
        "Docs/handoffs/CURRENT.md": f"# Handoff\n\n**Status:** Living.\n**Last updated:** {TODAY}: day 0.\n\nState.\n",
        "Docs/journal/README.md": _doc(body=f"| {TODAY} | [Session 01]({TODAY}-session-01.md) | start |\n"),
        f"Docs/journal/{TODAY}-session-01.md": "# Session 01\n\nWork.\n",
        "Docs/decisions/README.md": "# Decisions\n\n| ADR | Title |\n| --- | --- |\n| [1](ADR-001-first.md) | One |\n",
        "Docs/decisions/ADR-001-first.md": _doc("Accepted"),
        "Docs/plan/BOARD.md": _doc(
            body=(
                "## Gates\n\nNone.\n\n## Now\n\n| Row | State |\n| --- | --- |\n"
                "| ~~**Done thing**~~ | Merged as #12 |\n| Open thing | Started |\n\n"
                "## Next\n\nNone.\n\n## Blocked\n\nNone.\n\n## Icebox\n\nNone.\n"
            )
        ),
        "Docs/standards/one.md": _doc("Accepted"),
    }


def write_repo(tmp: Path, files: dict[str, str], *, framework: str | None = None) -> Path:
    for rel, text in files.items():
        path = tmp / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    if framework is not None:
        (tmp / "framework.toml").write_text(framework, encoding="utf-8", newline="\n")
    return tmp


def toml(*, journal: str = "on", limit: int = 150, extra: str = "") -> str:
    return FRAMEWORK_TOML.format(journal=journal, limit=limit, extra=extra)


def findings_of(root: Path) -> list[cd.Finding]:
    return cd.run(cd.load_context(root))


def broken(tmp: Path, expected: str, mutate, *, also: tuple[str, ...] = ()) -> list[cd.Finding]:
    """The base corpus, changed by ``mutate(files)``; the findings must come from ``expected`` (plus ``also``, for a
    break that is two rules at once, such as an index row linking a file that does not exist) and nothing else.
    Returns only the findings of ``expected``."""
    files = base_files()
    mutate(files)
    found = findings_of(write_repo(tmp, files))
    assert found, f"no finding at all; the {expected} check did not fire"
    assert {f.check for f in found} == {expected, *also}, [str(f) for f in found]
    return [f for f in found if f.check == expected]


def test_the_base_corpus_passes_every_check(tmp_path: Path) -> None:
    assert findings_of(write_repo(tmp_path, base_files())) == []


def test_every_check_fires_on_one_corpus_and_emits_only_its_own_name(tmp_path: Path) -> None:
    """One corpus broken once per rule: each registered function must find something, under its registered name only.
    A check that never fires, or reports under another check's name, fails here."""
    files = base_files()
    files["Docs/handoffs/CURRENT.md"] = "# H\n\n**Status:** Living.\n**Last updated:** 2026-10-12: x\n" + "line\n" * 200
    files["Docs/README.md"] += "[gone](nowhere.md)\n"  # links
    files["Docs/fenced.md"] = _doc(body="```\nnever closed\n")  # fences
    files["Docs/handoffs/CURRENT.md"] += f"a backspace{chr(8)}\n"  # control-char
    files["Docs/standards/one.md"] = _doc("Draft")  # status
    files["Docs/twice.md"] = _doc() + "\n" * 20 + "**Status:** Living.\n"  # single-status
    files["Docs/journal/2026-10-11-session-02.md"] = "# S2\n"  # journal-index (unindexed)
    files["Docs/decisions/ADR-002-second.md"] = _doc("Accepted")  # adr-index (unindexed)
    files["Docs/decisions/ADR-1-dup.md"] = _doc("Accepted")  # adr-duplicate (one id with ADR-001)
    files["Docs/decisions/README.md"] += "| [1b](ADR-1-dup.md) | Dup |\n"
    files["Docs/plan/BOARD.md"] = (
        files["Docs/plan/BOARD.md"].replace("## Blocked", "## Stuck").replace("Merged as #12", "no number")
    )  # board and landed-rows
    for name in ("fenced.md", "twice.md"):
        files["Docs/README.md"] += f"[{name}]({name})\n"
    files["Docs/glossary.md"] = GLOSSARY + "| ~~one~~ and ~~two~~ | both | Two in one row. |\n"  # glossary-row
    files["Docs/README.md"] += "[glossary](glossary.md)\n"
    files["Docs/notes.md"] = _doc(body="We still say oldword.\n")  # vocabulary
    files["Docs/README.md"] += "[notes](notes.md)\n"
    files["Docs/superpowers/specs/s.md"] = spec("No terms section.\n")  # terms
    files["Docs/README.md"] += "[s](superpowers/specs/s.md)\n"
    files["Docs/lonely.md"] = _doc()  # orphan
    files["Docs/standards/zzz-project.md"] = _doc()  # extension-base (no zzz.md beside it)
    files["Docs/decisions/ADR-003-third.md"] = _doc(
        "Accepted", "**Superseded by:** [x](ADR-004-fourth.md)\n"
    )  # adr-refs
    files["Docs/decisions/ADR-004-fourth.md"] = _doc("Accepted")
    files["Docs/decisions/README.md"] += "| [3](ADR-003-third.md) | T |\n| [4](ADR-004-fourth.md) | F |\n"
    files["Docs/README.md"] += "[the first ADR](decisions/ADR-001-first.md) (Proposed)\n"  # status-copy
    files["Docs/sub/AGENTS.md"] = _doc()  # nested-instructions
    files["Docs/README.md"] += "[sub](sub/AGENTS.md)\n"
    files["Docs/journal/2026-10/2026-10-11-zed-0930.md"] = GOOD_SESSION  # journal-author (zed is not on the roster)
    write_repo(tmp_path, files, framework=toml(extra=ROSTER))
    (tmp_path / "Docs" / "bad.md").write_bytes(b"\xff\xfe not utf-8")  # corpus
    ctx = cd.load_context(tmp_path)
    # The checks that read row files see nothing on a hand-kept board, so they get a directory-form board of their own
    rows = directory_board()
    rows[f"{BOARD_DIR}/2026-10-08-landed-in-next.md"] = _row("next", "L", "@ada", "Landed as #74")  # board-state
    rows[f"{BOARD_DIR}/2026-10-09-waiting.md"] = _row(
        "icebox", "W", "none", "Iceboxed", ICEBOX_LINES + "**Waits on:** [Done thing](2026-09-30-done-thing.md)\n"
    )  # waits-on
    with_design(rows, None)  # row-ref
    directory_ctx = cd.load_context(write_repo(tmp_path / "directory", rows))
    directory_ctx = dataclasses.replace(directory_ctx, base_rows=frozenset({"2026-10-01-gone"}))  # row-kept
    assert list(cd.CHECKS) == list(dict.fromkeys(cd.CHECKS))
    for name, check in cd.CHECKS.items():
        found = check(directory_ctx if name in ("board-state", "waits-on", "row-ref", "row-kept") else ctx)
        assert found, f"{name} found nothing on a corpus broken for it"
        assert {f.check for f in found} == {name}, [str(f) for f in found]


# --------------------------------------------------------------------------- corpus
def test_an_empty_corpus_is_a_finding_not_a_pass(tmp_path: Path) -> None:
    found = findings_of(tmp_path)
    assert [f.check for f in found].count("corpus") == 1 and "vacuously" in found[0].detail


def test_a_file_that_cannot_be_decoded_is_a_finding(tmp_path: Path) -> None:
    write_repo(tmp_path, base_files())
    (tmp_path / "Docs" / "bad.md").write_bytes(b"# Title\n\n**Status:** Living\n\n\xff\xfe broken bytes\n")
    found = findings_of(tmp_path)
    assert [f.location for f in found if f.check == "corpus"] == ["Docs/bad.md"]


def test_an_excluded_directory_is_pruned_not_scanned(tmp_path: Path) -> None:
    files = base_files()
    files[".venv/lib/pkg/README.md"] = "[gone](missing.md)\n"
    files["Spikes/one/NOTES.md"] = "[gone](missing.md)\n"
    assert findings_of(write_repo(tmp_path, files)) == []


def test_the_exclusions_come_from_the_docs_table(tmp_path: Path) -> None:
    files = base_files()
    files["vendor/README.md"] = "[gone](missing.md)\n"
    root = write_repo(tmp_path, files, framework=toml(extra='[docs]\nexclude_parts = [".git", "vendor"]\n'))
    assert findings_of(root) == []
    (root / "framework.toml").write_text(toml(), encoding="utf-8")
    assert [f.check for f in findings_of(root)] == ["links"]


# --------------------------------------------------------------------------- links
def test_a_broken_link_is_found(tmp_path: Path) -> None:
    found = broken(tmp_path, "links", lambda f: f.update({"Docs/README.md": f["Docs/README.md"] + "[x](nowhere.md)\n"}))
    assert "nowhere.md" in found[0].detail and found[0].location == "Docs/README.md"


def test_a_link_with_the_wrong_case_is_found_even_on_a_case_insensitive_disk(tmp_path: Path) -> None:
    files = base_files()
    files["Docs/Thing.md"] = _doc()
    files["Docs/README.md"] += "[a](Docs/thing.md) [b](thing.md)\n"
    found = findings_of(write_repo(tmp_path, files))
    assert sorted(f.check for f in found) == ["links", "links", "orphan"], [str(f) for f in found]
    assert sorted(f.detail for f in found if f.check == "links") == [
        "broken link -> Docs/thing.md",
        "broken link -> thing.md",
    ]  # and nothing links to Thing.md, which is how a wrong-case link also strands its target
    files["Docs/README.md"] = files["Docs/README.md"].replace("[a](Docs/thing.md) [b](thing.md)", "[a](Thing.md)")
    assert findings_of(write_repo(tmp_path / "exact", files)) == []  # the control: the exact spelling resolves


def test_a_link_may_not_climb_above_the_root(tmp_path: Path) -> None:
    outside = tmp_path / "outside.md"
    outside.write_text("beside the checkout\n", encoding="utf-8")
    root = tmp_path / "repo"
    files = base_files()
    files["Docs/README.md"] += "[up](../../outside.md)\n"
    write_repo(root, files)
    found = [f for f in findings_of(root) if f.check == "links"]
    assert len(found) == 1 and "outside.md" in found[0].detail


def test_a_reference_style_link_is_checked(tmp_path: Path) -> None:
    broken(tmp_path, "links", lambda f: f.update({"Docs/README.md": f["Docs/README.md"] + "[ref]: gone.md\n"}))


def test_a_percent_escaped_link_to_a_file_with_a_space_resolves(tmp_path: Path) -> None:
    files = base_files()
    files["Docs/My Doc.md"] = _doc()
    files["Docs/README.md"] += '[ok](My%20Doc.md) [angle](<My Doc.md> "title")\n'
    assert findings_of(write_repo(tmp_path, files)) == []


def test_links_in_fences_urls_and_fragments_are_not_paths(tmp_path: Path) -> None:
    files = base_files()
    files["Docs/README.md"] += (
        "[web](https://example.org/x.md) [mail](mailto:a@b.c) [frag](#section) [here](README.md#top)\n"
        "```\n[inside](nowhere.md)\n```\n"
    )
    assert findings_of(write_repo(tmp_path, files)) == []


# --------------------------------------------------------------------------- control-char
# The characters are built with chr(), so this file stays clean (#128).
@pytest.mark.parametrize("code", [0x08, 0x00, 0x0B, 0x0C, 0x1B, 0x1F, 0x7F])
def test_a_control_character_is_a_finding_naming_the_file_the_line_and_the_code_point(
    tmp_path: Path, code: int
) -> None:
    def mutate(files: dict[str, str]) -> None:
        files["Docs/standards/one.md"] += f"A clean line.\nA word{chr(code)}with a control in it.\n"

    found = broken(tmp_path, "control-char", mutate)
    assert [(f.location, f"U+{code:04X}" in f.detail) for f in found] == [("Docs/standards/one.md:7", True)]


def test_each_control_character_is_its_own_finding(tmp_path: Path) -> None:
    def mutate(files: dict[str, str]) -> None:
        files["Docs/README.md"] += f"two{chr(8)}{chr(8)} here\n```\nin code{chr(0x7F)} too\n```\n"

    found = broken(tmp_path, "control-char", mutate)
    assert [f.detail.split(" ")[0] for f in found] == ["U+0008", "U+0008", "U+007F"]


# C1 controls, the bidirectional embeddings, overrides and isolates, the zero-width space, and a byte-order mark
# after the start of a file (#159)
@pytest.mark.parametrize("code", [0x80, 0x85, 0x9F, 0x202A, 0x202D, 0x202E, 0x2066, 0x2069, 0x200B, 0xFEFF])
def test_an_invisible_character_beyond_c0_is_a_finding_naming_its_code_point(tmp_path: Path, code: int) -> None:
    def mutate(files: dict[str, str]) -> None:
        files["Docs/standards/one.md"] += f"A clean line.\nA word{chr(code)}with it inside.\n"

    found = broken(tmp_path, "control-char", mutate)
    assert [(f.location, f.detail.split(" ")[0]) for f in found] == [("Docs/standards/one.md:7", f"U+{code:04X}")]


# The line and paragraph separators: an editor shows nothing, str.splitlines() breaks the line there, and an agent's
# file tools wrote one where a backslash escape was meant (2026-11-09)
@pytest.mark.parametrize("code", [0x2028, 0x2029])
def test_a_line_or_paragraph_separator_is_a_finding_that_says_it_breaks_a_line(tmp_path: Path, code: int) -> None:
    def mutate(files: dict[str, str]) -> None:
        files["Docs/standards/one.md"] += f"A clean line.\nThe escape `{chr(code)}` written as the character.\n"

    found = broken(tmp_path, "control-char", mutate)
    assert [(f.location, f.detail.split(" ")[0]) for f in found] == [("Docs/standards/one.md:7", f"U+{code:04X}")]
    assert "separator" in found[0].detail and "breaks the line" in found[0].detail


def test_a_bidirectional_override_says_the_text_can_display_other_than_it_reads(tmp_path: Path) -> None:
    def mutate(files: dict[str, str]) -> None:
        files["Docs/standards/one.md"] += f"Never {chr(0x202E)}egrem{chr(0x202C)} without asking.\n"

    found = broken(tmp_path, "control-char", mutate)
    assert sorted(f.detail.split(" ")[0] for f in found) == ["U+202C", "U+202E"]
    assert all("displays other than it reads" in f.detail for f in found)


def test_joiners_marks_and_a_leading_byte_order_mark_are_not_findings(tmp_path: Path) -> None:
    """U+200C and U+200D join scripts and emoji, U+200E and U+200F mark direction in right-to-left text, and U+2060
    joins words: each has a use in prose. A byte-order mark that starts a file is read as the encoding's, not text."""
    files = base_files()
    files["Docs/standards/one.md"] += (
        f"zwnj{chr(0x200C)}zwj{chr(0x200D)}lrm{chr(0x200E)}rlm{chr(0x200F)}wj{chr(0x2060)} "
        f"and a family {chr(0x1F468)}{chr(0x200D)}{chr(0x1F469)}\n"
    )
    root = write_repo(tmp_path, files)
    readme = root / "Docs" / "README.md"
    readme.write_bytes(b"\xef\xbb\xbf" + readme.read_bytes())
    assert findings_of(root) == []


def test_a_tab_a_crlf_file_and_text_beyond_ascii_are_not_control_characters(tmp_path: Path) -> None:
    files = base_files()
    files["Docs/standards/one.md"] += f"a{chr(9)}tab, an é, a ½ and a — dash, a non-breaking{chr(0xA0)}space\n"
    root = write_repo(tmp_path, files)
    crlf = _doc().replace("\n", "\r\n").encode("utf-8")
    (root / "Docs" / "crlf.md").write_bytes(crlf + b"lone\rcarriage return\r\n")
    (root / "Docs" / "README.md").write_text(files["Docs/README.md"] + "[crlf](crlf.md)\n", encoding="utf-8")
    assert findings_of(root) == []


def test_an_unreadable_file_is_the_corpus_finding_not_a_control_character_pass(tmp_path: Path) -> None:
    """A file that cannot be decoded is never read for control characters: the corpus check reports it instead."""
    write_repo(tmp_path, base_files())
    (tmp_path / "Docs" / "bad.md").write_bytes(b"# T\n\n\xff\x08\n")
    assert {f.check for f in findings_of(tmp_path)} == {"corpus"}


# --------------------------------------------------------------------------- fences
def test_an_unclosed_fence_is_found_and_the_rest_of_the_file_stays_checked(tmp_path: Path) -> None:
    files = base_files()
    files["Docs/README.md"] += "```\ncode that never ends\n[after](gone.md)\n"
    found = findings_of(write_repo(tmp_path, files))
    assert {f.check for f in found} == {"fences", "links"}
    assert any("never closes" in f.detail for f in found if f.check == "fences")


def test_a_longer_fence_can_contain_a_shorter_one(tmp_path: Path) -> None:
    files = base_files()
    files["Docs/README.md"] += "````\n```\n[inside](gone.md)\n```\n````\n"
    assert findings_of(write_repo(tmp_path, files)) == []


# --------------------------------------------------------------------------- status
@pytest.mark.parametrize("word", cd.STATUS_WORDS)
def test_every_word_of_the_closed_set_is_accepted(tmp_path: Path, word: str) -> None:
    files = base_files()
    files["Docs/standards/one.md"] = _doc(word + (" by [the new one](two.md)" if word == "Superseded" else ""))
    files["Docs/standards/two.md"] = _doc("Accepted")
    files["Docs/README.md"] += "[two](standards/two.md)\n"
    assert findings_of(write_repo(tmp_path, files)) == []


@pytest.mark.parametrize("word", ["Draft", "Adopted", "Done", "Active", "living", "Final"])
def test_a_free_form_status_word_is_a_finding(tmp_path: Path, word: str) -> None:
    found = broken(tmp_path, "status", lambda f: f.update({"Docs/standards/one.md": _doc(word)}))
    assert found[0].location == "Docs/standards/one.md" and word in found[0].detail


def test_a_missing_status_is_a_finding(tmp_path: Path) -> None:
    broken(tmp_path, "status", lambda f: f.update({"Docs/standards/one.md": "# Title\n\nNo status here.\n"}))


def test_a_status_after_the_twelfth_line_is_not_in_the_window(tmp_path: Path) -> None:
    late = "# Title\n" + "\n" * 12 + "**Status:** Living.\n"
    found = broken(tmp_path, "status", lambda f: f.update({"Docs/standards/one.md": late}))
    assert "first 12 lines" in found[0].detail
    ok = "# Title\n" + "\n" * 9 + "**Status:** Living.\n"  # line 11
    files = base_files()
    files["Docs/standards/one.md"] = ok
    assert findings_of(write_repo(tmp_path / "ok", files)) == []


def test_a_status_inside_a_fence_does_not_count(tmp_path: Path) -> None:
    quoted = "# Title\n\n```\n**Status:** Living.\n```\n"
    broken(tmp_path, "status", lambda f: f.update({"Docs/standards/one.md": quoted}))


def test_superseded_must_say_by_what(tmp_path: Path) -> None:
    found = broken(tmp_path, "status", lambda f: f.update({"Docs/standards/one.md": _doc("Superseded")}))
    assert "by what" in found[0].detail
    files = base_files()
    files["Docs/standards/one.md"] = "# T\n\n**Status:** Superseded by\n"
    assert [f.check for f in findings_of(write_repo(tmp_path / "bare", files))] == ["status"]


def test_session_files_and_exempt_files_need_no_status(tmp_path: Path) -> None:
    files = base_files()
    files["Docs/other/NOTES.md"] = "# Notes\n"  # governed, no status: the control for the exemptions below
    found = findings_of(write_repo(tmp_path, files))
    assert {f.location for f in found} == {"Docs/other/NOTES.md"}  # the one governed file without a status
    assert {f.check for f in found} == {"status", "orphan"}
    # the session file and the decisions index in base_files() carry no status and are not findings


def test_a_document_outside_the_governed_directories_needs_no_status(tmp_path: Path) -> None:
    files = base_files()
    files["notes/loose.md"] = "# Loose\n"
    assert findings_of(write_repo(tmp_path, files)) == []


# --------------------------------------------------------------------------- single-status
def test_two_document_statuses_in_one_file_are_a_finding(tmp_path: Path) -> None:
    doubled = _doc("Superseded by [two](two.md)") + "\n" * 20 + "**Status:** Living.\n"
    files = base_files()
    files["Docs/standards/one.md"] = doubled
    files["Docs/standards/two.md"] = _doc("Accepted")
    files["Docs/README.md"] += "[two](standards/two.md)\n"
    found = findings_of(write_repo(tmp_path, files))
    assert [f.check for f in found] == ["single-status"] and "2 times" in found[0].detail


def test_a_per_section_status_in_other_words_is_not_a_second_document_status(tmp_path: Path) -> None:
    sectioned = _doc("Living", "## A\n\n**Status:** Deferred.\n\n## B\n\n**Status:** Keep and update.\n")
    files = base_files()
    files["Docs/standards/one.md"] = sectioned
    assert findings_of(write_repo(tmp_path, files)) == []


# --------------------------------------------------------------------------- journal
def test_a_session_file_with_no_row_is_a_finding(tmp_path: Path) -> None:
    found = broken(tmp_path, "journal-index", lambda f: f.update({"Docs/journal/2026-10-11-session-02.md": "# S2\n"}))
    assert "session-02" in found[0].detail


def test_an_index_row_for_a_session_that_does_not_exist_is_found(tmp_path: Path) -> None:
    def ghost(f: dict[str, str]) -> None:
        f["Docs/journal/README.md"] += "| 2026-10-12 | [Session 01](2026-10-12-session-01.md) | gone |\n"

    found = broken(tmp_path, "journal-index", ghost, also=("links",))
    assert "2026-10-12-session-01.md, which does not exist" in found[0].detail


def test_a_handoff_dated_after_the_newest_session_file_is_a_finding(tmp_path: Path) -> None:
    def later(f: dict[str, str]) -> None:
        f["Docs/handoffs/CURRENT.md"] = f["Docs/handoffs/CURRENT.md"].replace(TODAY, "2026-10-12")

    found = broken(tmp_path, "journal-day", later)
    assert "2026-10-12" in found[0].detail and "new day" in found[0].detail


def test_a_handoff_dated_the_same_day_or_before_the_newest_session_passes(tmp_path: Path) -> None:
    files = base_files()
    files["Docs/handoffs/CURRENT.md"] = files["Docs/handoffs/CURRENT.md"].replace(TODAY, "2026-10-09")
    assert findings_of(write_repo(tmp_path, files)) == []


def test_a_dated_handoff_with_no_session_file_at_all_is_a_finding(tmp_path: Path) -> None:
    def none(f: dict[str, str]) -> None:
        del f[f"Docs/journal/{TODAY}-session-01.md"]
        f["Docs/journal/README.md"] = _doc()

    found = broken(tmp_path, "journal-day", none)
    assert "no journal session file" in found[0].detail


def test_the_journal_checks_stand_down_when_the_journal_module_is_off(tmp_path: Path) -> None:
    files = base_files()
    del files[f"Docs/journal/{TODAY}-session-01.md"]
    files["Docs/journal/README.md"] = _doc()
    write_repo(tmp_path, files, framework=toml(journal="off"))
    assert findings_of(tmp_path) == []
    (tmp_path / "framework.toml").write_text(toml(journal="on"), encoding="utf-8")
    assert {f.check for f in findings_of(tmp_path)} == {"journal-day"}


# --------------------------------------------------------------------------- adr-index
def test_an_adr_with_no_index_row_is_a_finding(tmp_path: Path) -> None:
    found = broken(
        tmp_path,
        "adr-index",
        lambda f: f.update({"Docs/decisions/ADR-002-second.md": _doc("Accepted")}),
        also=("orphan",),
    )
    assert "ADR-002-second.md" in found[0].detail


def test_an_index_row_for_a_missing_adr_is_found_and_a_fragment_does_not_hide_a_row(tmp_path: Path) -> None:
    def ghost(f: dict[str, str]) -> None:
        f["Docs/decisions/README.md"] += "| [3](ADR-003-ghost.md) | Ghost |\n"

    assert "ADR-003-ghost.md, which does not exist" in broken(tmp_path, "adr-index", ghost, also=("links",))[0].detail
    files = base_files()
    files["Docs/decisions/README.md"] = files["Docs/decisions/README.md"].replace(
        "(ADR-001-first.md)", "(ADR-001-first.md#why)"
    )
    assert findings_of(write_repo(tmp_path / "frag", files)) == []


def test_a_missing_decisions_index_is_a_finding_when_adrs_exist(tmp_path: Path) -> None:
    def drop(f: dict[str, str]) -> None:
        del f["Docs/decisions/README.md"]
        f["Docs/README.md"] = f["Docs/README.md"].replace(" [decisions](decisions/README.md)", "")

    found = broken(tmp_path, "adr-index", drop, also=("orphan",))  # the ADR lost the index that linked it
    assert "missing" in found[0].detail


# --------------------------------------------------------------------------- board
def test_a_missing_board_section_is_a_finding(tmp_path: Path) -> None:
    found = broken(
        tmp_path,
        "board",
        lambda f: f.update({"Docs/plan/BOARD.md": f["Docs/plan/BOARD.md"].replace("## Blocked", "## Stuck")}),
    )
    assert "## Blocked" in found[0].detail


def test_a_section_name_in_prose_is_not_a_section(tmp_path: Path) -> None:
    def prose_only(f: dict[str, str]) -> None:
        f["Docs/plan/BOARD.md"] = f["Docs/plan/BOARD.md"].replace("## Icebox\n", "Where the ## Icebox lives.\n")

    assert "## Icebox" in broken(tmp_path, "board", prose_only)[0].detail


def test_a_missing_board_is_a_finding(tmp_path: Path) -> None:
    def drop(f: dict[str, str]) -> None:
        del f["Docs/plan/BOARD.md"]
        f["Docs/README.md"] = f["Docs/README.md"].replace(" [board](plan/BOARD.md)", "")

    assert "missing" in broken(tmp_path, "board", drop)[0].detail


def test_the_board_sections_come_from_the_docs_table(tmp_path: Path) -> None:
    files = base_files()
    files["Docs/plan/BOARD.md"] = _doc(body="## Gates\n\nNone.\n")
    root = write_repo(tmp_path, files, framework=toml(extra='[docs]\nboard_sections = ["## Gates"]\n'))
    assert findings_of(root) == []


# --------------------------------------------------------------------------- landed-rows
def test_a_struck_row_with_no_pull_request_is_a_finding(tmp_path: Path) -> None:
    def struck(f: dict[str, str]) -> None:
        f["Docs/plan/BOARD.md"] = f["Docs/plan/BOARD.md"].replace(
            "| Open thing | Started |", "| ~~**Landed thing**~~ | PR number to follow on push |"
        )

    found = broken(tmp_path, "landed-rows", struck)
    board_line = base_files()["Docs/plan/BOARD.md"].splitlines().index("| Open thing | Started |") + 1
    assert "Landed thing" in found[0].detail
    assert found[0].location == f"Docs/plan/BOARD.md:{board_line}"  # the finding points at the row's own line


@pytest.mark.parametrize("ref", ["Merged as #12", "[#12](https://github.com/o/r/pull/12)", "https://x/pull/7"])
def test_a_struck_row_naming_its_pull_request_passes_in_either_spelling(tmp_path: Path, ref: str) -> None:
    files = base_files()
    files["Docs/plan/BOARD.md"] = files["Docs/plan/BOARD.md"].replace("Merged as #12", ref)
    assert findings_of(write_repo(tmp_path, files)) == []


def test_a_row_that_is_not_struck_needs_no_pull_request(tmp_path: Path) -> None:
    files = base_files()  # "Open thing | Started" is in the base board
    assert findings_of(write_repo(tmp_path, files)) == []


# --------------------------------------------------------------------------- handoff
def test_the_limit_is_exact_a_file_of_that_many_lines_passes_and_one_more_fails(tmp_path: Path) -> None:
    head = f"# Handoff\n\n**Status:** Living.\n**Last updated:** {TODAY}: x.\n"
    files = base_files()
    files["Docs/handoffs/CURRENT.md"] = head + "line\n" * (150 - 4)  # exactly 150 lines
    assert len(files["Docs/handoffs/CURRENT.md"].splitlines()) == 150
    assert findings_of(write_repo(tmp_path / "at", files)) == []
    files["Docs/handoffs/CURRENT.md"] += "one more\n"
    found = findings_of(write_repo(tmp_path / "over", files))
    assert [f.check for f in found] == ["handoff"]
    assert "151 lines" in found[0].detail and "limit is 150" in found[0].detail


def test_the_limit_is_read_from_framework_toml(tmp_path: Path) -> None:
    files = base_files()
    files["Docs/handoffs/CURRENT.md"] += "line\n" * 30
    root = write_repo(tmp_path, files, framework=toml(limit=20))
    # a limit other than the default needs an override with a reason, so the loader refuses this file first
    with pytest.raises(fc.ConfigError):
        cd.load_context(root)
    reason = '[[overrides]]\ntarget = "handoff_max_lines"\nreason = "a long-running project"\n'
    (root / "framework.toml").write_text(toml(limit=20, extra=reason), encoding="utf-8")
    found = findings_of(root)
    assert [f.check for f in found] == ["handoff"] and "limit is 20" in found[0].detail
    (root / "framework.toml").write_text(toml(limit=60, extra=reason), encoding="utf-8")
    assert findings_of(root) == []


def test_crlf_line_endings_count_the_same(tmp_path: Path) -> None:
    files = base_files()
    write_repo(tmp_path, files)
    path = tmp_path / "Docs/handoffs/CURRENT.md"
    path.write_bytes(path.read_text(encoding="utf-8").replace("\n", "\r\n").encode("utf-8"))
    assert findings_of(tmp_path) == []


def test_a_handoff_without_a_date_or_with_an_impossible_one_is_a_finding(tmp_path: Path) -> None:
    undated = broken(
        tmp_path / "a", "handoff", lambda f: f.update({"Docs/handoffs/CURRENT.md": "# H\n\n**Status:** Living.\n"})
    )
    assert "Last updated" in undated[0].detail
    impossible = broken(
        tmp_path / "b",
        "handoff",
        lambda f: f.update(
            {"Docs/handoffs/CURRENT.md": "# H\n\n**Status:** Living.\n**Last updated:** 2026-13-45: x\n"}
        ),
    )
    assert "not a real day" in impossible[0].detail


def test_a_missing_handoff_is_a_finding(tmp_path: Path) -> None:
    def drop(f: dict[str, str]) -> None:
        del f["Docs/handoffs/CURRENT.md"]
        f["Docs/README.md"] = f["Docs/README.md"].replace("[handoff](handoffs/CURRENT.md) ", "")

    assert "missing" in broken(tmp_path, "handoff", drop)[0].detail


# --------------------------------------------------------------------------- the command line
def test_main_exits_0_clean_1_on_findings_and_2_on_a_bad_configuration(tmp_path: Path, capsys) -> None:
    write_repo(tmp_path, base_files())
    assert cd.main([str(tmp_path)]) == 0
    assert "no drift" in capsys.readouterr().out
    (tmp_path / "Docs/README.md").write_text(_doc(body="[x](nowhere.md)\n"), encoding="utf-8")
    assert cd.main([str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "[links] Docs/README.md" in out and "finding(s)" in out
    (tmp_path / "framework.toml").write_text("this is not toml = = =", encoding="utf-8")
    assert cd.main([str(tmp_path)]) == 2
    assert "cannot run" in capsys.readouterr().err
    assert cd.main(["a", "b"]) == 2


# --------------------------------------------------------------------------- a repository made from the payload
ANSWERS = {
    "name": "Example Project",
    "slug": "example-project",
    "owner": {"name": "Ada Example", "email": "ada@example.org"},
    "default_branch": "main",
    "signoff": True,
    "hygiene": [],
}


@pytest.mark.skipif(
    (ROOT / "project.json").exists(),
    reason="runs only against the template's payload, not in a repository made from it",
)
def test_the_docs_check_is_clean_on_a_repository_made_from_the_payload(tmp_path: Path) -> None:
    """Plan task 5's moved verification: the seed passes the checker that enforces it."""
    answers = tmp_path / "answers.json"
    answers.write_text(json.dumps(ANSWERS), encoding="utf-8")
    target = tmp_path / "proj"
    argv = ["new", "--answers", str(answers), "--target", str(target), "--no-sync", "--no-checks"]
    assert ini.main(argv, source=ROOT, today=TODAY) == 0
    ctx = cd.load_context(target)
    assert len(ctx.files) > 10  # a made repository has documents; an empty scan would pass vacuously
    assert [str(f) for f in cd.run(ctx)] == []
    assert cd.main([str(target)]) == 0
    extension = target / "Docs/standards/python-project.md"
    extension.write_text(_doc(body="Our rules.\n"), encoding="utf-8")  # nothing links it
    assert cd.main([str(target)]) == 0
    extension.rename(target / "Docs/standards/pythn-project.md")
    found = cd.run(cd.load_context(target))
    assert [(f.check, f.location) for f in found] == [
        ("orphan", "Docs/standards/pythn-project.md"),
        ("extension-base", "Docs/standards/pythn-project.md"),
    ]


# --------------------------------------------------------------------------- the definition of done names the checks
def documented_check_names() -> tuple[set[str], set[str]]:
    """The backticked names in the first column of the definition of done's table of docs checks: those documented as
    implemented, and those on a row marked *Planned*."""
    text = (ROOT / "Docs/standards/definition-of-done.md").read_text(encoding="utf-8")
    section = text.split("### What the docs check catches", 1)[1].split("\n## ", 1)[0]
    implemented: set[str] = set()
    planned: set[str] = set()
    for line in section.splitlines():
        if line.startswith("| `"):
            names = re.findall(r"`([a-z-]+)`", line.split("|")[1])
            (planned if line.split("|")[2].lstrip().startswith("**Planned") else implemented).update(names)
    return implemented, planned


@pins("Docs/standards/definition-of-done.md")
def test_the_definition_of_done_lists_exactly_the_checks_the_checker_runs() -> None:
    implemented, planned = documented_check_names()
    assert implemented, "the table was not found; the parser or the document changed"
    assert set(cd.CHECKS) == implemented, (
        f"run but not documented: {sorted(set(cd.CHECKS) - implemented)}; "
        f"documented as implemented but not run: {sorted(implemented - set(cd.CHECKS))}"
    )
    assert not planned & set(cd.CHECKS), f"run, but still marked Planned: {sorted(planned & set(cd.CHECKS))}"


# --------------------------------------------------------------------------- what is and is not a link (review round 1)
def _readme_with(tmp: Path, extra: str, **more: str) -> list[cd.Finding]:
    files = base_files()
    files["Docs/README.md"] += extra
    files["Docs/img.svg"] = "<svg/>"  # a target for the image half of a badge
    files.update(more)
    return findings_of(write_repo(tmp, files))


@pytest.mark.parametrize(
    "text",
    [
        "Write `[text](gone.md)` for a link.\n",  # an inline code span
        "Write ``[a](gone.md) with ` inside`` for a link.\n",  # a longer run closes a longer run
        "<!-- [x](gone.md) -->\n",  # an HTML comment
        "<!--\n[x](gone.md)\n-->\n",  # across lines
        "[^1]: See the spec for details.\n",  # a footnote definition is not a reference definition
        "A footnote[^1] here.\n",
        "\\[x\\](gone.md)\n",  # escaped brackets
        "- item\n\n    ```\n    [x](gone.md)\n    ```\n",  # a fence inside a list item, indented four spaces
        "> ```\n> [x](gone.md)\n> ```\n",  # a fence inside a block quote
        "~~~\n[x](gone.md)\n~~~\n",  # a tilde fence
        "```text\n~~~\n[x](gone.md)\n```\n",  # the other fence character inside stays code
        "```not a fence``` but a line that starts with three backticks, then [ok](README.md).\n",
        "[web](//example.com/x) [rooted](/README.md)\n",  # protocol-relative; a leading slash is the root
        "[x](README.md?plain=1)\n",  # a query string is not part of the path
    ],
)
def test_text_that_is_not_a_link_is_not_checked(tmp_path: Path, text: str) -> None:
    assert _readme_with(tmp_path, text) == [], text


@pytest.mark.parametrize(
    ("text", "target"),
    [
        ("[x](a(1).md)\n", "a(1).md"),  # balanced parentheses: the path is a(1).md, which does not exist
        ("[![badge](img.svg)](gone.md)", "gone.md"),  # a badge: the outer link is not hidden by the inner image
        ("[a [b]](gone.md)\n", "gone.md"),
        ("[x](gone.md (title))\n", "gone.md"),
        ("[x](missing.py:42)\n", "missing.py:42"),  # a colon after an extension is not a URL scheme
        (
            "[x](/Docs/nowhere.md)\n",
            "/Docs/nowhere.md",
        ),  # a leading slash means the repository root, not the file's dir
        ("[x](gone.md?plain=1#top)\n", "gone.md"),
        ("[x]: gone.md\n", "gone.md"),
    ],
)
def test_a_broken_link_in_every_shape_documents_use_is_found(tmp_path: Path, text: str, target: str) -> None:
    found = _readme_with(tmp_path, text)
    assert [(f.check, f.detail) for f in found] == [("links", f"broken link -> {target}")], [str(f) for f in found]


def test_a_root_relative_link_does_not_resolve_from_the_documents_own_directory(tmp_path: Path) -> None:
    # Docs/thing.md exists, README.md at the root does not link it: "/thing.md" is the root's thing.md, which is absent.
    found = _readme_with(tmp_path, "[x](/thing.md)\n", **{"Docs/thing.md": _doc()})
    assert [f.detail for f in found if f.check == "links"] == ["broken link -> /thing.md"]


def test_a_link_with_parentheses_in_its_path_resolves_when_the_file_exists(tmp_path: Path) -> None:
    assert _readme_with(tmp_path, "[x](a(1).md) [y](<a(1).md>)\n", **{"Docs/a(1).md": _doc()}) == []


def test_a_backslash_in_a_link_is_not_a_separator(tmp_path: Path) -> None:
    found = _readme_with(tmp_path, "[x](Docs" + chr(92) + "README.md)\n")
    assert [f.check for f in found] == ["links"]


def test_a_hostile_file_does_not_stall_the_check(tmp_path: Path) -> None:
    """The first version used a regular expression that took 21 seconds on 80 KB of ``[a](`` and 7 on ``[a](<``."""
    import time

    hostile = "[a](" * 20000 + "\n" + "[a](<" * 10000 + "\n" + "[" * 40000 + "\n" + "`" * 3000 + "a`" * 3000 + "\n"
    started = time.perf_counter()
    _readme_with(tmp_path, hostile)
    assert time.perf_counter() - started < 30.0


# --------------------------------------------------------------------------- line structure and encodings
def test_a_byte_order_mark_does_not_hide_a_status_on_the_first_line(tmp_path: Path) -> None:
    files = base_files()
    write_repo(tmp_path, files)
    path = tmp_path / "Docs/standards/one.md"
    path.write_bytes("﻿**Status:** Living.\n\n# T\n".encode())
    assert findings_of(tmp_path) == []


def test_the_status_window_is_exactly_twelve_lines(tmp_path: Path) -> None:
    def spec(status_line: int) -> str:
        return "\n".join("**Status:** Living." if n == status_line else "x" for n in range(1, 16)) + "\n"

    for line, ok in ((11, True), (12, True), (13, False)):
        files = base_files()
        files["Docs/standards/one.md"] = spec(line)
        found = findings_of(write_repo(tmp_path / f"at{line}", files))
        assert (found == []) is ok, (line, [str(f) for f in found])


@pytest.mark.parametrize(
    "status_line",
    [
        "> **Status:** Accepted",
        "**Status**: Accepted",
        "  **Status:** Accepted",
        "**Status:** **Accepted**",
        "**Status:** Accepted: because it was",
        "**Status:** Accepted" + chr(0x2014) + "ok",
    ],
)
def test_sound_status_lines_in_other_markdown_shapes_pass(tmp_path: Path, status_line: str) -> None:
    files = base_files()
    files["Docs/standards/one.md"] = f"# T\n\n{status_line}\n"
    assert findings_of(write_repo(tmp_path, files)) == []


@pytest.mark.parametrize("status_line", ["**Status:** accepted", "**Status:**", "**Status:** 2026", "Status: Accepted"])
def test_unsound_status_lines_are_findings(tmp_path: Path, status_line: str) -> None:
    files = base_files()
    files["Docs/standards/one.md"] = f"# T\n\n{status_line}\n"
    assert {f.check for f in findings_of(write_repo(tmp_path, files))} == {"status"}


def test_line_separators_inside_a_line_do_not_count_as_lines(tmp_path: Path) -> None:
    files = base_files()
    head = f"# H\n\n**Status:** Living.\n**Last updated:** {TODAY}: x.\n"
    files["Docs/handoffs/CURRENT.md"] = head + ("a" + chr(0x2028) + "b" + chr(0x0C) + "c\n") * 140  # 144 lines, 3 each
    found = findings_of(write_repo(tmp_path, files))
    # The handoff is within its limit; the separators and form feeds are control characters (#128), two on each line
    assert {f.check for f in found} == {"control-char"}
    assert sorted(f.location for f in found) == sorted(
        f"Docs/handoffs/CURRENT.md:{n}" for n in range(5, 145) for _ in range(2)
    )


def test_a_finding_in_the_board_points_at_the_physical_line_even_after_a_line_separator(tmp_path: Path) -> None:
    files = base_files()
    board = files["Docs/plan/BOARD.md"].replace(
        "| Open thing | Started |", "A" + chr(0x2028) + "B\n| ~~**Late**~~ | none |"
    )
    files["Docs/plan/BOARD.md"] = board
    found = findings_of(write_repo(tmp_path, files))
    line = board.split("\n").index("| ~~**Late**~~ | none |") + 1
    # the separator is a finding of its own, on the line before
    assert [(f.check, f.location) for f in found] == [
        ("control-char", f"Docs/plan/BOARD.md:{line - 1}"),
        (next(f.check for f in found if f.check != "control-char"), f"Docs/plan/BOARD.md:{line}"),
    ]


def test_findings_come_back_sorted_by_location_then_detail(tmp_path: Path) -> None:
    found = _readme_with(
        tmp_path, "[z](zzz.md) [a](aaa.md) [o](other.md)\n", **{"Docs/other.md": _doc(body="[m](mmm.md)\n")}
    )
    assert [(f.location, f.detail) for f in found] == [
        ("Docs/README.md", "broken link -> aaa.md"),
        ("Docs/README.md", "broken link -> zzz.md"),
        ("Docs/other.md", "broken link -> mmm.md"),
    ]


def test_an_unreadable_file_is_one_finding_and_not_several(tmp_path: Path) -> None:
    files = base_files()
    write_repo(tmp_path, files)
    (tmp_path / "Docs" / "handoffs" / "CURRENT.md").write_bytes(b"\xff\xfe**Status:** Living")
    found = findings_of(write_repo(tmp_path, {}))
    assert [(f.check, f.location) for f in found] == [("corpus", "Docs/handoffs/CURRENT.md")]


# --------------------------------------------------------------------------- the pruning is real
def test_an_excluded_directory_is_never_entered(tmp_path: Path, monkeypatch) -> None:
    write_repo(tmp_path, base_files())
    (tmp_path / ".venv" / "lib").mkdir(parents=True)
    (tmp_path / ".venv" / "lib" / "x.md").write_text("x", encoding="utf-8")
    visited: list[str] = []
    real_walk = cd.os.walk

    def spying_walk(top, **kwargs):
        for current, dirs, names in real_walk(top, **kwargs):
            visited.append(Path(current).relative_to(top).as_posix())
            yield current, dirs, names

    monkeypatch.setattr(cd.os, "walk", spying_walk)
    cd.load_context(tmp_path)
    assert visited and not [v for v in visited if v.startswith(".venv")], visited


# --------------------------------------------------------------------------- the index checks
def test_an_index_link_in_any_relative_form_counts(tmp_path: Path) -> None:
    files = base_files()
    files["Docs/journal/README.md"] = _doc(body=f"[s](./{TODAY}-session-01.md)\n")
    assert findings_of(write_repo(tmp_path / "dot", files)) == []
    files["Docs/journal/README.md"] = _doc(body=f"[s](../journal/{TODAY}-session-01.md)\n")
    assert findings_of(write_repo(tmp_path / "up", files)) == []
    files["Docs/journal/README.md"] = _doc(body=f"[s](/Docs/journal/{TODAY}-session-01.md)\n")
    assert findings_of(write_repo(tmp_path / "root", files)) == []


def test_an_index_in_another_directory_resolves_its_rows_against_itself(tmp_path: Path) -> None:
    files = base_files()
    del files["Docs/journal/README.md"]
    files["Docs/journal.md"] = _doc(body=f"[s](journal/{TODAY}-session-01.md)\n")
    files["Docs/README.md"] = files["Docs/README.md"].replace("journal/README.md", "journal.md")
    root = write_repo(tmp_path, files, framework=toml(extra='[docs]\njournal_index = "Docs/journal.md"\n'))
    assert findings_of(root) == []
    (root / "Docs/journal.md").write_text(_doc(body="nothing\n"), encoding="utf-8")
    assert [f.check for f in findings_of(root)] == ["journal-index"]


def test_an_index_at_the_repository_root_still_checks_its_members(tmp_path: Path) -> None:
    files = base_files()
    del files["Docs/decisions/README.md"]
    files["ADRS.md"] = "# ADRs\n\n[one](Docs/decisions/ADR-001-first.md)\n"
    files["Docs/README.md"] = files["Docs/README.md"].replace(" [decisions](decisions/README.md)", "")
    root = write_repo(tmp_path, files, framework=toml(extra='[docs]\nadr_index = "ADRS.md"\n'))
    # the index's directory is the root, so every ADR below the root is a member and ADR-001 is listed
    assert findings_of(root) == []
    (root / "Docs/decisions/ADR-002-two.md").write_text(_doc("Accepted"), encoding="utf-8")
    assert sorted(f.check for f in findings_of(root)) == ["adr-index", "orphan"]


@pytest.mark.parametrize("name", ["ADR-0002-x.md", "adr-003-x.md", "ADR-004.md", "sub/ADR-005-x.md"])
def test_an_adr_named_a_little_differently_still_needs_its_index_row(tmp_path: Path, name: str) -> None:
    found = broken(
        tmp_path, "adr-index", lambda f: f.update({f"Docs/decisions/{name}": _doc("Accepted")}), also=("orphan",)
    )
    assert name.rsplit("/", 1)[-1] in found[0].detail


def test_a_dated_file_in_the_journal_that_is_not_a_session_file_is_a_finding(tmp_path: Path) -> None:
    def misnamed(f: dict[str, str]) -> None:
        f["Docs/journal/2026-10-12-session-1.md"] = "# x\n"

    # it is not a session file by name, so it is also an ordinary governed document with no status
    found = broken(tmp_path, "journal-index", misnamed, also=("status", "orphan"))
    assert "not named YYYY-MM-DD-session-NN.md" in found[0].detail


def test_a_session_file_naming_an_impossible_day_is_a_finding_and_never_the_newest(tmp_path: Path) -> None:
    def impossible(f: dict[str, str]) -> None:
        f["Docs/journal/2026-99-99-session-01.md"] = "# x\n"
        f["Docs/journal/README.md"] += "[x](2026-99-99-session-01.md)\n"
        f["Docs/handoffs/CURRENT.md"] = f["Docs/handoffs/CURRENT.md"].replace(TODAY, "2026-12-01")

    found = broken(tmp_path, "journal-day", impossible, also=("journal-index",))
    assert "2026-12-01" in found[0].detail and "newest journal file is 2026-10-11" in found[0].detail


# --------------------------------------------------------------------------- the board and the handoff
@pytest.mark.parametrize("heading", ["## Gates (owner only)", "## Gates ##", "## Gates "])
def test_a_board_heading_with_trailing_words_or_closing_marks_is_still_that_section(
    tmp_path: Path, heading: str
) -> None:
    files = base_files()
    files["Docs/plan/BOARD.md"] = files["Docs/plan/BOARD.md"].replace("## Gates\n", heading + "\n")
    assert findings_of(write_repo(tmp_path, files)) == []


def test_a_heading_that_only_begins_with_the_section_name_is_not_it(tmp_path: Path) -> None:
    found = broken(
        tmp_path,
        "board",
        lambda f: f.update({"Docs/plan/BOARD.md": f["Docs/plan/BOARD.md"].replace("## Now", "## Nowhere")}),
    )
    assert "## Now" in found[0].detail


@pytest.mark.parametrize(
    "row",
    [
        "| **~~Landed~~** | merged |",  # bold around the strike
        "| _~~Landed~~_ | merged |",
        "~~Landed~~ | merged",  # no leading pipe
        "| ~~Landed~~ | see [d](BOARD.md#2026-10-11) |",  # an anchor is not a pull request
        "| ~~Landed~~ | colour #123456 |",  # nor is a hex colour
        "| ~~Landed~~ | &#123; |",  # nor an entity
    ],
)
def test_a_struck_row_is_found_however_it_is_written_and_whatever_unrelated_number_it_holds(
    tmp_path: Path, row: str
) -> None:
    def add(f: dict[str, str]) -> None:
        f["Docs/plan/BOARD.md"] = f["Docs/plan/BOARD.md"].replace("| Open thing | Started |", row)

    assert broken(tmp_path, "landed-rows", add)


def test_a_struck_line_that_is_not_in_a_table_is_not_a_landed_row(tmp_path: Path) -> None:
    files = base_files()
    files["Docs/plan/BOARD.md"] += "\n~~Struck prose~~ with no table around it and no number.\n"
    assert findings_of(write_repo(tmp_path, files)) == []


def test_only_a_cell_that_starts_with_the_strike_makes_a_row_landed(tmp_path: Path) -> None:
    files = base_files()
    files["Docs/plan/BOARD.md"] = files["Docs/plan/BOARD.md"].replace(
        "| Open thing | Started |", "| old ~~name~~ new | Started |"
    )
    assert findings_of(write_repo(tmp_path, files)) == []


@pytest.mark.parametrize("token", ["2026-10-11T10:00", "tomorrow", "2026-1-5", "20261011"])
def test_a_last_updated_that_is_not_a_plain_day_is_a_finding(tmp_path: Path, token: str) -> None:
    def odd(f: dict[str, str]) -> None:
        f["Docs/handoffs/CURRENT.md"] = f"# H\n\n**Status:** Living.\n**Last updated:** {token}\n"

    assert "not a real day" in broken(tmp_path, "handoff", odd)[0].detail


def test_a_date_on_the_line_after_last_updated_is_not_its_date(tmp_path: Path) -> None:
    def next_line(f: dict[str, str]) -> None:
        f["Docs/handoffs/CURRENT.md"] = f"# H\n\n**Status:** Living.\n**Last updated:**\n{TODAY}\n"

    assert broken(tmp_path, "handoff", next_line)


# --------------------------------------------------------------------------- the command line, again
def test_main_exits_2_for_a_root_that_is_not_a_directory_or_an_unknown_flag(tmp_path: Path, capsys) -> None:
    assert cd.main([str(tmp_path / "nowhere")]) == 2
    assert "not a directory" in capsys.readouterr().err
    write_repo(tmp_path, base_files())
    assert cd.main(["--bogus"]) == 2
    assert "usage" in capsys.readouterr().err


def test_a_verbose_run_leaves_a_record_of_what_it_read_and_decided(tmp_path: Path, caplog) -> None:
    write_repo(tmp_path, base_files(), framework=toml(limit=150))
    with caplog.at_level("INFO", logger="tools.check_docs"):
        assert cd.main(["-v", str(tmp_path)]) == 0
    text = caplog.text
    assert "framework.toml" in text and "handoff limit 150" in text and "markdown file(s)" in text
    assert "check handoff: 0 finding(s)" in text


def test_a_run_without_framework_toml_says_it_took_the_defaults(tmp_path: Path, caplog) -> None:
    write_repo(tmp_path, base_files())
    with caplog.at_level("INFO", logger="tools.check_docs"):
        cd.load_context(tmp_path)
    assert "no framework.toml" in caplog.text and "defaults apply" in caplog.text


def test_an_unreadable_file_is_logged_as_a_warning(tmp_path: Path, caplog) -> None:
    write_repo(tmp_path, base_files())
    (tmp_path / "Docs" / "bad.md").write_bytes(b"\xff\xfe")
    with caplog.at_level("WARNING", logger="tools.check_docs"):
        cd.load_context(tmp_path)
    assert "skipped Docs/bad.md" in caplog.text


# --------------------------------------------------------------------------- what a struck row is not asked for
def _board_with(tmp: Path, gates_row: str, now_row: str) -> list[cd.Finding]:
    files = base_files()
    board = files["Docs/plan/BOARD.md"]
    board = board.replace("## Gates\n\nNone.", f"## Gates\n\n| Gate | State |\n| --- | --- |\n{gates_row}\n")
    board = board.replace("| Open thing | Started |", now_row)
    files["Docs/plan/BOARD.md"] = board
    return findings_of(write_repo(tmp, files))


def test_a_gate_closed_by_decision_is_not_a_landed_row(tmp_path: Path) -> None:
    found = _board_with(
        tmp_path, "| ~~**G1 · the name**~~ | CLOSED 2026-10-01 by the owner |", "| Open thing | Started |"
    )
    assert found == []


def test_a_struck_row_after_the_gates_section_is_asked_for_its_number_again(tmp_path: Path) -> None:
    found = _board_with(tmp_path, "| ~~**G1**~~ | CLOSED |", "| ~~**Landed**~~ | Done |")
    assert [f.check for f in found] == ["landed-rows"] and "Landed" in found[0].detail


def test_a_row_may_say_it_closed_without_a_pull_request(tmp_path: Path) -> None:
    said = "| ~~**Spike**~~ | Closed with no pull request: the question was answered in the journal |"
    assert _board_with(tmp_path / "said", "| G | open |", said) == []
    silent = "| ~~**Spike**~~ | Closed: the question was answered in the journal |"
    assert [f.check for f in _board_with(tmp_path / "silent", "| G | open |", silent)] == ["landed-rows"]


def test_a_row_that_landed_on_a_branch_and_names_no_number_is_the_failure_the_rule_exists_for(tmp_path: Path) -> None:
    branch = "| ~~**Journal per day**~~ | Landed the same evening (`docs/journal-per-day`) |"
    assert [f.check for f in _board_with(tmp_path, "| G | open |", branch)] == ["landed-rows"]


# --------------------------------------------------------------------------- review round 2
def _links_found(tmp: Path, text: str, **more: str) -> list[str]:
    return [f.detail.removeprefix("broken link -> ") for f in _readme_with(tmp, text, **more) if f.check == "links"]


def test_a_code_span_that_mentions_a_comment_marker_hides_nothing_after_it(tmp_path: Path) -> None:
    # a later "-->" would close a comment that was never opened, if the marker inside the code span counted
    text = "`<!--` opens a comment.\n\n[x](gone.md)\n\nand `-->` closes it\n"
    assert _links_found(tmp_path, text) == ["gone.md"]


def test_an_unclosed_comment_marker_is_plain_text(tmp_path: Path) -> None:
    assert _links_found(tmp_path, "Write <!-- in html\n[x](gone.md)\n") == ["gone.md"]


def test_a_link_after_a_multi_line_comment_is_still_found_and_one_inside_is_not(tmp_path: Path) -> None:
    text = "<!--\n[inside](hidden.md)\n-->\n[after](gone.md)\n"
    assert _links_found(tmp_path, text) == ["gone.md"]


def test_a_status_a_heading_and_a_date_inside_a_comment_do_not_count(tmp_path: Path) -> None:
    files = base_files()
    files["Docs/standards/one.md"] = "# T\n\n<!--\n**Status:** Living.\n-->\n"
    files["Docs/plan/BOARD.md"] = files["Docs/plan/BOARD.md"].replace("## Icebox\n", "<!--\n## Icebox\n-->\n")
    files["Docs/handoffs/CURRENT.md"] = "# H\n\n**Status:** Living.\n<!--\n**Last updated:** 2026-10-11\n-->\n"
    found = findings_of(write_repo(tmp_path, files))
    assert sorted(f.check for f in found) == ["board", "handoff", "status"], [str(f) for f in found]


@pytest.mark.parametrize(
    "text",
    [
        "[Note]: this is important\n",
        "[TODO]: fix this later\n",
        "[1]: Smith, J. (2020)\n",
        "    [a]: gone.md\n",
        "[^1]: Note.\n",
    ],
)
def test_prose_that_starts_like_a_reference_definition_is_not_one(tmp_path: Path, text: str) -> None:
    assert _links_found(tmp_path, text) == []


@pytest.mark.parametrize(
    ("text", "target"),
    [('[a]: gone.md "A title"\n', "gone.md"), ("[a]: <b c.md>\n", "b c.md"), ("[a]: gone.md (note)\n", "gone.md")],
)
def test_a_real_reference_definition_with_a_title_is_checked(tmp_path: Path, text: str, target: str) -> None:
    assert _links_found(tmp_path, text) == [target]


def test_link_text_that_wraps_across_lines_is_checked(tmp_path: Path) -> None:
    assert _links_found(tmp_path, "see [a long link\ntext](gone.md)\n") == ["gone.md"]
    assert _links_found(tmp_path / "blank", "text](gone.md)\n") == []  # no bracket was opened in this paragraph
    assert _links_found(tmp_path / "reset", "[open\n\ntext](gone.md)\n") == []  # a blank line ends the paragraph


def test_a_closing_bracket_with_no_opening_one_is_not_a_link(tmp_path: Path) -> None:
    assert _links_found(tmp_path, "just text](gone.md) and more\n") == []


def test_html_href_and_src_attributes_are_checked(tmp_path: Path) -> None:
    text = (
        '<a href="gone.md">x</a> <img src=\'gone.png\'> <a href="https://example.org/x.md">y</a> '
        '`<a href="in-code.md">`\n'
    )
    assert _links_found(tmp_path, text) == ["gone.md", "gone.png"]


def test_a_finding_naming_a_non_ascii_file_is_printed_whatever_the_stream_encoding(tmp_path: Path) -> None:
    import os
    import subprocess

    files = base_files()
    files["Docs/README.md"] += "[x](g" + chr(0xF6) + "n" + chr(0xE8) + ".md)\n"
    write_repo(tmp_path, files)
    env = {**os.environ, "PYTHONIOENCODING": "ascii"}
    result = subprocess.run(
        [sys.executable, cd.__file__, str(tmp_path)], capture_output=True, text=True, env=env, check=False
    )
    assert result.returncode == 1, result.stderr
    assert "finding(s)" in result.stdout and "g" + chr(92) + "xf6n" in result.stdout


def test_a_directory_that_cannot_be_listed_is_a_finding_not_a_silent_skip(tmp_path: Path, monkeypatch) -> None:
    write_repo(tmp_path, base_files())
    real_walk = cd.os.walk

    calls: list[str] = []

    def denying_walk(top, onerror=None, **kwargs):
        calls.append(str(top))
        if len(calls) == 1 and onerror is not None:  # the documents' walk is the first call
            onerror(PermissionError(13, "Permission denied", str(Path(top) / "Docs" / "locked")))
        yield from real_walk(top, **kwargs)

    monkeypatch.setattr(cd.os, "walk", denying_walk)
    found = cd.run(cd.load_context(tmp_path))
    assert [(f.check, f.location) for f in found] == [("corpus", "Docs/locked")]
    assert "PermissionError" in found[0].detail


def test_a_hostile_megabyte_does_not_stall_the_check(tmp_path: Path) -> None:
    import time

    hostile = "[a](<" * 600000 + "\n" + "](" * 200000 + "\n" + "[a](" * 200000 + "\n"
    started = time.perf_counter()
    _readme_with(tmp_path, hostile)
    assert time.perf_counter() - started < 30.0


# --- the exclusions
def test_the_configured_exclusions_add_to_the_ones_nothing_can_remove(tmp_path: Path) -> None:
    files = base_files()
    files[".venv/lib/README.md"] = "[gone](missing.md)\n"
    files["vendor/README.md"] = "[gone](missing.md)\n"
    files["node_modules/pkg/README.md"] = "[gone](missing.md)\n"
    root = write_repo(tmp_path, files, framework=toml(extra='[docs]\nexclude_parts = ["vendor"]\n'))
    assert findings_of(root) == []


# --- sessions, statuses and the governed set
def test_a_session_named_file_below_the_journal_directory_is_an_ordinary_governed_document(tmp_path: Path) -> None:
    found = broken(
        tmp_path,
        "status",
        lambda f: f.update({"Docs/journal/sub/2026-10-12-session-01.md": "# x\n"}),
        also=("orphan",),
    )
    assert found[0].location == "Docs/journal/sub/2026-10-12-session-01.md"


def test_a_directory_whose_name_starts_like_a_governed_one_is_not_governed(tmp_path: Path) -> None:
    files = base_files()
    files["Docs2/x.md"] = "# no status needed\n"
    assert findings_of(write_repo(tmp_path, files)) == []


@pytest.mark.parametrize(
    "status_line", ["**Status:** Accepted-ish", "**Status:** Accepted2026", "**Status:** Living-ish"]
)
def test_a_word_that_merely_begins_with_a_status_word_is_not_that_status(tmp_path: Path, status_line: str) -> None:
    files = base_files()
    files["Docs/standards/one.md"] = f"# T\n\n{status_line}\n"
    assert {f.check for f in findings_of(write_repo(tmp_path, files))} == {"status"}


def test_free_text_after_a_status_word_is_allowed_but_superseded_must_say_by_what_next(tmp_path: Path) -> None:
    files = base_files()
    files["Docs/standards/one.md"] = "# T\n\n**Status:** Living, was Proposed.\n"
    assert findings_of(write_repo(tmp_path / "ok", files)) == []
    for tail in ("Superseded; was written by Bob.", "Superseded standby x"):
        files["Docs/standards/one.md"] = f"# T\n\n**Status:** {tail}\n"
        found = findings_of(write_repo(tmp_path / tail[:12].replace(" ", "_").replace(";", ""), files))
        assert {f.check for f in found} == {"status"}, tail


@pytest.mark.parametrize(
    "line",
    [
        "**Last updated**: 2026-10-11",
        "> **Last updated:** 2026-10-11",
        "**Last updated:** **2026-10-11**",
        "**Last updated:** _2026-10-11_",
    ],
)
def test_last_updated_is_read_in_the_same_shapes_as_status(tmp_path: Path, line: str) -> None:
    files = base_files()
    files["Docs/handoffs/CURRENT.md"] = f"# H\n\n**Status:** Living.\n{line}\n"
    assert findings_of(write_repo(tmp_path, files)) == []


def test_a_status_example_inside_a_fence_is_not_a_second_status(tmp_path: Path) -> None:
    files = base_files()
    files["Docs/standards/one.md"] = _doc("Accepted") + "\n```\n**Status:** Living.\n```\n"
    assert findings_of(write_repo(tmp_path, files)) == []


def test_a_closing_fence_with_text_after_it_does_not_close(tmp_path: Path) -> None:
    text = "```\n[x](gone.md)\n``` trailing text\n[y](gone2.md)\n```\n"
    assert _links_found(tmp_path, text) == []


def test_a_board_heading_inside_a_fence_is_not_a_section(tmp_path: Path) -> None:
    def fenced(f: dict[str, str]) -> None:
        f["Docs/plan/BOARD.md"] = f["Docs/plan/BOARD.md"].replace("## Blocked\n", "```\n## Blocked\n```\n")

    assert "## Blocked" in broken(tmp_path, "board", fenced)[0].detail


def test_a_windows_drive_path_is_a_path_not_a_url_scheme(tmp_path: Path) -> None:
    assert _links_found(tmp_path, "[x](C:/x.md)\n") == ["C:/x.md"]


def test_the_journal_index_stands_down_when_the_journal_module_is_off(tmp_path: Path) -> None:
    files = base_files()
    files["Docs/journal/2026-10-12-session-01.md"] = "# unindexed\n"
    root = write_repo(tmp_path, files, framework=toml(journal="off"))
    assert [f for f in findings_of(root) if f.check == "journal-index"] == []
    (root / "framework.toml").write_text(toml(journal="on"), encoding="utf-8")
    assert [f.check for f in findings_of(root) if f.check == "journal-index"] == ["journal-index"]


def test_an_index_row_may_link_other_existing_files_without_being_a_ghost(tmp_path: Path) -> None:
    files = base_files()
    files["Docs/journal/README.md"] += "[the board](../plan/BOARD.md) [adrs](../decisions/ADR-001-first.md)\n"
    assert findings_of(write_repo(tmp_path, files)) == []


# --- the board's gates
def test_a_struck_row_under_a_sub_heading_of_gates_is_still_in_the_gates(tmp_path: Path) -> None:
    files = base_files()
    files["Docs/plan/BOARD.md"] = files["Docs/plan/BOARD.md"].replace(
        "## Gates\n\nNone.", "## Gates\n\n### Closed\n\n| ~~G1~~ | decided |"
    )
    assert findings_of(write_repo(tmp_path, files)) == []


def test_closed_without_a_pull_request_needs_a_reason_after_the_words(tmp_path: Path) -> None:
    bare = "| ~~**Spike**~~ | no pull request |"
    assert [f.check for f in _board_with(tmp_path, "| G | open |", bare)] == ["landed-rows"]


@pytest.mark.parametrize("row", ["| [~~Linked~~](BOARD.md) | none |", "> | ~~Quoted~~ | none |"])
def test_a_struck_first_cell_is_found_inside_a_link_or_a_block_quote(tmp_path: Path, row: str) -> None:
    assert [f.check for f in _board_with(tmp_path, "| G | open |", row)] == ["landed-rows"]


def test_a_pull_request_written_as_pr_hash_number_counts(tmp_path: Path) -> None:
    assert _board_with(tmp_path, "| G | open |", "| ~~**Done**~~ | landed in PR#12 |") == []


# --------------------------------------------------------------------------- Copilot's review of the pull request
def test_an_escaped_opening_bracket_makes_the_rest_plain_text(tmp_path: Path) -> None:
    assert _links_found(tmp_path, "\\[x](gone.md)\n") == []
    assert _links_found(tmp_path / "close", "\\[x\\](gone.md)\n") == []  # both escaped, the case that already worked
    assert _links_found(tmp_path / "real", "[x](gone.md) and \\[y](also-text.md)\n") == ["gone.md"]


def test_an_escaped_opener_does_not_leave_link_text_open_on_the_next_line(tmp_path: Path) -> None:
    assert _links_found(tmp_path, "an escaped \\[bracket\ntext](gone.md)\n") == []
    assert _links_found(tmp_path / "real", "a real [bracket\ntext](gone.md)\n") == ["gone.md"]  # the control


def test_an_escaped_bracket_does_not_start_a_reference_definition(tmp_path: Path) -> None:
    assert _links_found(tmp_path, "\\[a]: gone.md\n") == []


# --------------------------------------------------------------------------- part 2: glossary, ADRs and the link graph
GLOSSARY = """# Glossary

**Status:** Living.

| Term | Meaning |
| --- | --- |
| **Spec**, **Plan** | One increment's deliverable and its tasks. |
| **Gate** (board) | A decision only the owner can make. |

## Retired terms

| ~~Retired~~ | Use | Why |
| --- | --- | --- |
| ~~oldword~~ | `newword` | Renamed. |
| ~~**Bold Old**~~ | New Thing | Renamed. |
| ~~`ticked`~~ | done | Renamed. |
| ~~preserve alpha~~ | keep alpha | Renamed. |

Prose below the table may name a retired word only beside its replacement: oldword, then newword.
Never write oldword on a line of its own.
"""


def with_glossary(files: dict[str, str], text: str = GLOSSARY) -> dict[str, str]:
    files["Docs/glossary.md"] = text
    files["Docs/README.md"] += "[glossary](glossary.md)\n"
    return files


SPEC_OK = "## Terms introduced\n\nNone.\n"


def spec(body: str = SPEC_OK, status: str = "Accepted") -> str:
    return f"# Spec\n\n**Status:** {status}.\n\n{body}"


def checks_of(tmp: Path, files: dict[str, str], **kw: str) -> list[cd.Finding]:
    return findings_of(write_repo(tmp, files, **kw))


# ---- terms
def test_a_spec_without_a_terms_section_is_a_finding(tmp_path: Path) -> None:
    files = with_glossary(base_files())
    files["Docs/superpowers/specs/s.md"] = spec("No section here.\n")
    files["Docs/README.md"] += "[s](superpowers/specs/s.md)\n"
    found = checks_of(tmp_path, files)
    assert [(f.check, f.location) for f in found] == [("terms", "Docs/superpowers/specs/s.md")]
    assert "no `## Terms introduced` section" in found[0].detail


@pytest.mark.parametrize("body", ["None.", "None", "**None**", "_none_"])
def test_none_in_any_emphasis_satisfies_the_section(tmp_path: Path, body: str) -> None:
    files = with_glossary(base_files())
    files["Docs/superpowers/specs/s.md"] = spec(f"## Terms introduced\n\n{body}\n")
    files["Docs/README.md"] += "[s](superpowers/specs/s.md)\n"
    assert checks_of(tmp_path, files) == []


@pytest.mark.parametrize(
    "body", ["- None", "> None.", "None. This spec uses only existing terms.", "**None** so far", "NONE"]
)
def test_none_followed_by_words_or_inside_a_list_or_quote_still_says_none(tmp_path: Path, body: str) -> None:
    files = with_glossary(base_files())
    files["Docs/superpowers/specs/s.md"] = spec(f"## Terms introduced\n\n{body}\n")
    files["Docs/README.md"] += "[s](superpowers/specs/s.md)\n"
    assert checks_of(tmp_path, files) == []


@pytest.mark.parametrize("body", ["Nothing new here.\n", "Some words but no term.\n", "Nonexistent terms.\n"])
def test_prose_that_does_not_start_with_the_word_none_and_lists_no_term_is_a_finding(tmp_path: Path, body: str) -> None:
    files = with_glossary(base_files())
    files["Docs/superpowers/specs/s.md"] = spec("## Terms introduced\n\n" + body)
    files["Docs/README.md"] += "[s](superpowers/specs/s.md)\n"
    found = checks_of(tmp_path, files)
    assert [f.check for f in found] == ["terms"] and "lists no" in found[0].detail


@pytest.mark.parametrize("item", ["- **Plan:** a thing", "- **`Plan`**", "- **Plan** : a thing", "- ** Plan **"])
def test_a_listed_term_with_a_colon_or_markup_inside_the_bold_is_still_that_term(tmp_path: Path, item: str) -> None:
    files = with_glossary(base_files())
    files["Docs/superpowers/specs/s.md"] = spec(f"## Terms introduced\n\n{item}\n")
    files["Docs/README.md"] += "[s](superpowers/specs/s.md)\n"
    assert checks_of(tmp_path, files) == []


def test_a_glossary_table_inside_a_block_quote_and_one_without_a_leading_pipe_separator_are_read(
    tmp_path: Path,
) -> None:
    quoted = "\n".join("> " + line for line in GLOSSARY.splitlines()) + "\n"
    files = with_glossary(base_files(), quoted)
    files["Docs/superpowers/specs/s.md"] = spec("## Terms introduced\n\n- **Plan**\n")
    files["Docs/README.md"] += "[s](superpowers/specs/s.md)\n"
    assert checks_of(tmp_path / "quoted", files) == []
    bare_separator = GLOSSARY.replace("| --- | --- | --- |", "--- | --- | ---").replace("| --- | --- |", "--- | ---")
    files = with_glossary(base_files(), bare_separator)
    files["Docs/notes.md"] = _doc(body="A Retired item only.\n")
    files["Docs/README.md"] += "[n](notes.md)\n"
    assert checks_of(tmp_path / "bare", files) == []  # the header row is a header, not a retired term "Retired"


def test_an_escaped_pipe_stays_inside_its_cell(tmp_path: Path) -> None:
    files = with_glossary(base_files(), GLOSSARY + "| ~~a\\|b~~ | c\\|d | Pipes. |\n")
    ctx = cd.load_context(write_repo(tmp_path, files))
    assert cd.retired_terms(ctx)["a|b"] == "c|d"


def test_the_section_name_has_to_be_the_whole_heading(tmp_path: Path) -> None:
    files = with_glossary(base_files())
    files["Docs/superpowers/specs/s.md"] = spec("## Terms introducedness\n\nNone.\n")
    files["Docs/superpowers/specs/t.md"] = spec("## terms Introduced\n\nNone.\n")  # any case
    files["Docs/README.md"] += "[s](superpowers/specs/s.md) [t](superpowers/specs/t.md)\n"
    found = checks_of(tmp_path, files)
    assert [(f.check, f.location) for f in found] == [("terms", "Docs/superpowers/specs/s.md")]


def test_a_sub_heading_stays_inside_the_section_and_an_index_is_not_asked(tmp_path: Path) -> None:
    files = with_glossary(base_files())
    files["Docs/superpowers/specs/s.md"] = spec(
        "## Terms introduced\n\n- **Plan**\n\n### Detail\n\n**Unknown** here.\n"
    )
    files["Docs/superpowers/specs/README.md"] = spec("An index of the specs.\n")
    files["Docs/README.md"] += "[s](superpowers/specs/s.md) [i](superpowers/specs/README.md)\n"
    found = checks_of(tmp_path, files)
    assert [(f.check, f.location) for f in found] == [("terms", "Docs/superpowers/specs/s.md")]
    assert "'Unknown'" in found[0].detail


def test_every_term_in_a_row_that_defines_several_is_known_and_case_does_not_matter(tmp_path: Path) -> None:
    """The first version registered only a cell's first bold span: ``Plan`` failed against ``**Spec**, **Plan**``."""
    files = with_glossary(base_files())
    files["Docs/superpowers/specs/s.md"] = spec("## Terms introduced\n\n- **Plan**\n- **spec**\n- **Gate**\n")
    files["Docs/README.md"] += "[s](superpowers/specs/s.md)\n"
    assert checks_of(tmp_path, files) == []


def test_a_term_with_no_glossary_row_is_named_in_the_finding(tmp_path: Path) -> None:
    files = with_glossary(base_files())
    files["Docs/superpowers/specs/s.md"] = spec("## Terms introduced\n\n- **Plan**\n- **Frobnicator**\n")
    files["Docs/README.md"] += "[s](superpowers/specs/s.md)\n"
    found = checks_of(tmp_path, files)
    assert [f.check for f in found] == ["terms"] and "'Frobnicator'" in found[0].detail


def test_a_retired_term_is_not_a_known_term(tmp_path: Path) -> None:
    files = with_glossary(base_files())
    files["Docs/superpowers/specs/s.md"] = spec("## Terms introduced\n\n- **oldword**\n")
    files["Docs/README.md"] += "[s](superpowers/specs/s.md)\n"
    found = checks_of(tmp_path, files)
    # the retired word is unknown to `terms`, and the spec that lists it also uses it without its replacement
    assert sorted(f.check for f in found) == ["terms", "vocabulary"]
    assert "'oldword'" in next(f for f in found if f.check == "terms").detail


def test_without_a_glossary_every_listed_term_is_unknown(tmp_path: Path) -> None:
    files = base_files()
    files["Docs/superpowers/specs/s.md"] = spec("## Terms introduced\n\n- **Plan**\n")
    files["Docs/README.md"] += "[s](superpowers/specs/s.md)\n"
    assert [f.check for f in checks_of(tmp_path, files)] == ["terms"]


def test_the_section_is_a_level_two_heading_ending_at_the_next_one(tmp_path: Path) -> None:
    files = with_glossary(base_files())
    files["Docs/README.md"] += "[s](superpowers/specs/s.md) [t](superpowers/specs/t.md)\n"
    files["Docs/superpowers/specs/s.md"] = spec(
        "## Terms introduced\n\n- **Plan**\n\n## Next\n\n**Unknown** is outside it.\n"
    )
    files["Docs/superpowers/specs/t.md"] = spec("### Terms introduced\n\nNone.\n")  # level three: not the section
    found = checks_of(tmp_path, files)
    assert [(f.check, f.location) for f in found] == [("terms", "Docs/superpowers/specs/t.md")]


def test_a_section_inside_a_fence_is_not_a_section(tmp_path: Path) -> None:
    files = with_glossary(base_files())
    files["Docs/superpowers/specs/s.md"] = spec("```\n## Terms introduced\n\nNone.\n```\n")
    files["Docs/README.md"] += "[s](superpowers/specs/s.md)\n"
    assert [f.check for f in checks_of(tmp_path, files)] == ["terms"]


def test_only_the_configured_directories_need_the_section(tmp_path: Path) -> None:
    files = with_glossary(base_files())
    files["Docs/superpowers/plans/p.md"] = spec("No section.\n")
    files["Docs/design/d.md"] = spec("No section.\n")
    files["Docs/README.md"] += "[p](superpowers/plans/p.md) [d](design/d.md)\n"
    assert sorted(f.location for f in checks_of(tmp_path / "default", files)) == [
        "Docs/design/d.md",
        "Docs/superpowers/plans/p.md",
    ]
    root = write_repo(tmp_path / "narrow", files, framework=toml(extra='[docs]\nterms_dirs = ["Docs/design"]\n'))
    assert [f.location for f in findings_of(root)] == ["Docs/design/d.md"]


def test_the_grandfathered_list_only_shrinks(tmp_path: Path) -> None:
    files = with_glossary(base_files())
    files["Docs/superpowers/specs/old.md"] = spec("No section.\n")
    files["Docs/superpowers/specs/fixed.md"] = spec()
    files["Docs/README.md"] += "[a](superpowers/specs/old.md) [b](superpowers/specs/fixed.md)\n"
    listed = '[docs]\nterms_grandfathered = ["Docs/superpowers/specs/old.md"]\n'
    assert findings_of(write_repo(tmp_path / "ok", files, framework=toml(extra=listed))) == []
    both = '[docs]\nterms_grandfathered = ["Docs/superpowers/specs/old.md", "Docs/superpowers/specs/fixed.md"]\n'
    found = findings_of(write_repo(tmp_path / "earned", files, framework=toml(extra=both)))
    assert [(f.check, f.location) for f in found] == [("terms", "Docs/superpowers/specs/fixed.md")]
    assert "remove it from terms_grandfathered" in found[0].detail
    gone = '[docs]\nterms_grandfathered = ["Docs/superpowers/specs/old.md", "Docs/superpowers/specs/missing.md"]\n'
    found = findings_of(write_repo(tmp_path / "gone", files, framework=toml(extra=gone)))
    assert [(f.check, f.location) for f in found] == [("terms", "Docs/superpowers/specs/missing.md")]


# ---- vocabulary and glossary-row
def vocab(tmp: Path, doc: str, *, pad: bool = True, **more: str) -> list[cd.Finding]:
    """``doc`` below a status line; padded past the 12-line header so the header translation cannot hide a bare use."""
    files = with_glossary(base_files())
    filler = "filler line\n" * 10 if pad else ""
    files["Docs/notes.md"] = f"# N\n\n**Status:** Living.\n\n{filler}{doc}"
    files["Docs/README.md"] += "[n](notes.md)\n"
    files.update(more)
    return checks_of(tmp, files)


def test_a_retired_term_without_its_replacement_on_the_line_is_a_finding(tmp_path: Path) -> None:
    found = vocab(tmp_path, "We still say oldword here.\n")
    assert [(f.check, f.location) for f in found] == [
        ("vocabulary", "Docs/notes.md:15")
    ]  # 4 lines, 10 filler, then the text
    assert "'oldword'" in found[0].detail and "'newword'" in found[0].detail


def test_a_line_that_names_both_is_recording_the_change(tmp_path: Path) -> None:
    assert vocab(tmp_path, "oldword became newword in this release.\n") == []
    assert [f.check for f in vocab(tmp_path / "split", "oldword became\nnewword in this release.\n")] == ["vocabulary"]


@pytest.mark.parametrize(
    ("text", "flagged"),
    [
        ("Oldword at a sentence start.", True),
        ("the OLDWORD constant", True),
        ("oldword.", True),
        ("(oldword)", True),
        ("oldwords are different", False),
        ("a preoldword prefix", False),
        ("the oldword-thing is a different name", False),
        ("the thing-oldword is a different name", False),
        ("Preserve-Alpha on the card", True),
        ("preserve  alpha on the card", True),
        ("preservealpha on the card", False),
        ("`ticked` in code", True),
        ("Bold Old as a heading", True),
    ],
)
def test_the_match_is_the_whole_word_or_phrase_in_any_case(tmp_path: Path, text: str, flagged: bool) -> None:
    assert bool(vocab(tmp_path, text + "\n")) is flagged, text


def test_only_the_journal_the_glossary_and_ended_documents_may_name_a_retired_term_by_default(tmp_path: Path) -> None:
    """The live handoff, an accepted ADR and a spec are not exempt: a new one must use the current word."""
    bare = "oldword everywhere.\n"
    ended = {
        "Docs/journal/2026-10-11-session-01.md": bare,
        "Docs/old.md": _doc("Superseded by [notes](notes.md)", bare),
        "Docs/gone.md": _doc("Abandoned", bare),
    }
    live = {
        "Docs/decisions/ADR-001-first.md": _doc("Accepted", bare),
        "Docs/handoffs/CURRENT.md": f"# H\n\n**Status:** Living.\n**Last updated:** {TODAY}\n\n{bare}",
        "Docs/superpowers/specs/s.md": spec(bare + SPEC_OK),
    }
    linked = "[o](old.md) [g](gone.md) [s](superpowers/specs/s.md)\n"
    found = vocab(tmp_path, "Fine.\n" + linked, **ended, **live)
    assert sorted(f.location.rsplit(":", 1)[0] for f in found if f.check == "vocabulary") == sorted(live)
    assert not [f for f in found if f.check != "vocabulary"], [str(f) for f in found]


def test_a_project_can_add_directories_to_the_exempt_list(tmp_path: Path) -> None:
    files = with_glossary(base_files())
    files["Docs/handoffs/CURRENT.md"] += "\noldword everywhere.\n"
    assert [f.check for f in checks_of(tmp_path / "default", files)] == ["vocabulary"]
    both = '[docs]\nretired_exempt_dirs = ["Docs/journal", "Docs/handoffs"]\n'
    assert checks_of(tmp_path / "extended", files, framework=toml(extra=both)) == []


def test_a_header_line_that_translates_the_term_exempts_that_document_for_that_term_only(tmp_path: Path) -> None:
    head = "> Where this says oldword, read newword.\n\n"
    found = vocab(tmp_path, head + "oldword here. preserve alpha there.\n", pad=False)
    assert [f.check for f in found] == ["vocabulary"] and "preserve alpha" in found[0].detail
    only_old = vocab(tmp_path / "old", "> This mentions oldword.\n\noldword later.\n", pad=False)
    assert [f.check for f in only_old] == ["vocabulary", "vocabulary"]


def test_a_retired_term_in_a_fence_or_a_comment_is_not_a_use(tmp_path: Path) -> None:
    assert vocab(tmp_path, "```\noldword\n```\n<!-- oldword -->\n") == []


def test_the_retired_tables_header_row_is_not_a_term(tmp_path: Path) -> None:
    assert vocab(tmp_path, "A Retired item only.\n") == []


def test_the_replacement_is_read_without_its_markup() -> None:
    ctx = cd.Context(
        Path("."),
        fc.DocsConfig(),
        150,
        {"core": "on"},
        ("Docs/glossary.md",),
        {"Docs/glossary.md": GLOSSARY},
    )
    assert cd.retired_terms(ctx) == {
        "oldword": "newword",
        "Bold Old": "New Thing",
        "ticked": "done",
        "preserve alpha": "keep alpha",
    }
    assert cd.glossary_terms(ctx) == {"spec", "plan", "gate"}


@pytest.mark.parametrize(
    "row",
    [
        "| ~~one~~ and ~~two~~ | both | Two terms in one row. |",
        "| ~~X~~ as the standards | Y | Qualified. |",
        "| ~~empty~~ |  | No replacement. |",
        "| ~~alone~~ |",
        "| ~~dash~~ | — | Nothing to name. |",
        "| ~~prose~~ | RETIRED. Unreal's term; here it is a Material Prime. | The cell explains. |",
        "| ~~long~~ | one two three four five six seven | Too many words for a name. |",
        "| ~~~~ | Y | Empty term. |",
    ],
)
def test_a_retired_row_that_parses_into_no_enforceable_term_is_a_finding(tmp_path: Path, row: str) -> None:
    files = with_glossary(base_files(), GLOSSARY + row + "\n")
    found = checks_of(tmp_path, files)
    assert [(f.check, f.location) for f in found] == [
        ("glossary-row", f"Docs/glossary.md:{GLOSSARY.count(chr(10)) + 1}")
    ]


def test_good_retired_rows_are_not_findings_and_no_glossary_is_silent(tmp_path: Path) -> None:
    assert vocab(tmp_path, "Plain text.\n") == []
    assert checks_of(tmp_path / "none", base_files()) == []


# ---- orphan
def test_a_governed_document_nothing_links_to_is_an_orphan(tmp_path: Path) -> None:
    found = broken(tmp_path, "orphan", lambda f: f.update({"Docs/lonely.md": _doc()}))
    assert found[0].location == "Docs/lonely.md"


def test_one_link_from_any_other_document_is_enough_and_a_self_link_is_not(tmp_path: Path) -> None:
    files = base_files()
    files["Docs/lonely.md"] = _doc(body="[me](lonely.md) [also me](./lonely.md#top)\n")
    assert [f.check for f in checks_of(tmp_path / "self", files)] == ["orphan"]
    files["Docs/other.md"] = _doc(body="[to it](lonely.md)\n")
    files["Docs/README.md"] += "[o](other.md)\n"
    assert checks_of(tmp_path / "linked", files) == []


def test_links_are_resolved_to_paths_so_a_shared_file_name_does_not_hide_an_orphan(tmp_path: Path) -> None:
    files = base_files()
    files["Docs/a/x.md"] = _doc()
    files["Docs/b/x.md"] = _doc()
    files["Docs/README.md"] += "[a](a/x.md)\n"
    found = checks_of(tmp_path, files)
    assert [(f.check, f.location) for f in found] == [("orphan", "Docs/b/x.md")]


def test_a_relative_or_root_absolute_link_from_another_folder_counts(tmp_path: Path) -> None:
    files = base_files()
    files["Docs/deep/x.md"] = _doc()
    files["Docs/deep/y.md"] = _doc()
    files["Docs/plan/extra.md"] = _doc(body="[x](../deep/x.md) [y](/Docs/deep/y.md)\n")
    files["Docs/README.md"] += "[e](plan/extra.md)\n"
    assert checks_of(tmp_path, files) == []


def test_the_map_itself_and_the_configured_entry_points_are_allowed(tmp_path: Path) -> None:
    files = base_files()
    files["Docs/entry.md"] = _doc()
    root = write_repo(
        tmp_path, files, framework=toml(extra='[docs]\norphan_allow = ["Docs/README.md", "Docs/entry.md"]\n')
    )
    assert findings_of(root) == []
    (root / "framework.toml").write_text(toml(), encoding="utf-8")
    assert [f.location for f in findings_of(root)] == ["Docs/entry.md"]


def test_documents_outside_the_governed_directories_and_dated_sessions_are_not_orphans(tmp_path: Path) -> None:
    files = base_files()
    files["notes/loose.md"] = "# Loose\n"
    files["Docs/journal/2026-10-12-session-01.md"] = "# S\n"  # the journal index's business
    found = checks_of(tmp_path, files)
    assert {f.check for f in found} == {"journal-index"}


# ---- adr-refs
def adrs(extra_a: str = "", extra_b: str = "") -> dict[str, str]:
    files = base_files()
    files["Docs/decisions/ADR-002-two.md"] = _doc("Accepted", extra_b + "\n")
    files["Docs/decisions/ADR-001-first.md"] = _doc("Accepted", extra_a + "\n")
    files["Docs/decisions/README.md"] += "| [2](ADR-002-two.md) | Two |\n"
    return files


def test_both_sides_of_a_supersede_relation_pass(tmp_path: Path) -> None:
    files = adrs("**Superseded by:** [ADR-002](ADR-002-two.md)", "**Supersedes:** [ADR-001](ADR-001-first.md)")
    assert checks_of(tmp_path, files) == []


@pytest.mark.parametrize(
    ("forward", "back"),
    [
        ("Superseded by", "Supersedes"),
        ("Supersedes", "Superseded by"),
        ("Extends", "Extended by"),
        ("Extended by", "Extends"),
    ],
)
def test_a_one_sided_relation_is_a_finding_in_every_direction(tmp_path: Path, forward: str, back: str) -> None:
    files = adrs(f"**{forward}:** [ADR-002](ADR-002-two.md)", "")
    found = checks_of(tmp_path / "one", files)
    assert [(f.check, f.location) for f in found] == [("adr-refs", "Docs/decisions/ADR-001-first.md:5")]
    assert f"`{forward}`" in found[0].detail and f"`{back}`" in found[0].detail
    both = adrs(f"**{forward}:** [ADR-002](ADR-002-two.md)", f"**{back}:** [ADR-001](ADR-001-first.md)")
    assert checks_of(tmp_path / "both", both) == []


def test_the_other_side_must_link_back_to_this_adr_and_not_merely_to_one(tmp_path: Path) -> None:
    files = adrs("**Superseded by:** [ADR-002](ADR-002-two.md)", "**Supersedes:** [somewhere else](ADR-003-three.md)")
    files["Docs/decisions/ADR-003-three.md"] = _doc("Accepted", "**Superseded by:** [ADR-002](ADR-002-two.md)\n")
    files["Docs/decisions/README.md"] += "| [3](ADR-003-three.md) | Three |\n"
    found = checks_of(tmp_path, files)
    assert [f.location for f in found] == ["Docs/decisions/ADR-001-first.md:5"]


def test_a_relation_to_a_file_that_is_not_an_adr_belongs_to_the_links_check(tmp_path: Path) -> None:
    """A file that does not exist is the links check's; one that exists but is not an ADR is this check's."""
    files = adrs("**Extends:** [the board](../plan/BOARD.md) [gone](ADR-009-gone.md)", "")
    found = checks_of(tmp_path, files)
    assert {f.check for f in found} == {"links", "adr-refs"}
    refs = [f for f in found if f.check == "adr-refs"]
    assert len(refs) == 1 and "BOARD.md" in refs[0].detail and "not an ADR" in refs[0].detail
    only_board = adrs("**Extends:** [the board](../plan/BOARD.md)", "")
    assert [f.check for f in checks_of(tmp_path / "alone", only_board)] == ["adr-refs"]


def test_a_relation_in_a_block_quote_is_read_and_one_in_a_fence_is_not(tmp_path: Path) -> None:
    quoted = adrs("> **Superseded by:** [ADR-002](ADR-002-two.md)", "")
    assert [f.check for f in checks_of(tmp_path / "q", quoted)] == ["adr-refs"]
    fenced = adrs("```\n**Superseded by:** [ADR-002](ADR-002-two.md)\n```", "")
    assert checks_of(tmp_path / "f", fenced) == []


# ---- nested-instructions
@pytest.mark.parametrize("name", ["CLAUDE.md", "AGENTS.md", "GEMINI.md", "agents.md"])
def test_an_instruction_file_below_the_root_is_a_finding(tmp_path: Path, name: str) -> None:
    def nested(f: dict[str, str]) -> None:
        f[f"Docs/sub/{name}"] = _doc()
        f["Docs/README.md"] += f"[n](sub/{name})\n"

    found = broken(tmp_path, "nested-instructions", nested)
    assert found[0].location == f"Docs/sub/{name}"


def test_the_root_ones_and_the_allowed_ones_are_fine(tmp_path: Path) -> None:
    files = base_files()
    files["AGENTS.md"] = "# Agents\n"
    files["CLAUDE.md"] = "@AGENTS.md\n"
    files["Docs/sub/AGENTS.md"] = _doc()
    files["Docs/README.md"] += "[n](sub/AGENTS.md)\n"
    root = write_repo(tmp_path, files, framework=toml(extra='[docs]\ninstructions_allow = ["Docs/sub/AGENTS.md"]\n'))
    assert findings_of(root) == []
    (root / "framework.toml").write_text(toml(), encoding="utf-8")
    assert [f.location for f in findings_of(root)] == ["Docs/sub/AGENTS.md"]


# ---- the ledger names the checks that hold its classes
HELD = {
    10: {"status", "single-status", "handoff", "journal-day"},
    11: {"corpus", "fences"},
    18: {"journal-index", "journal-day"},
    19: {"nested-instructions"},
    20: {"terms", "glossary-row", "vocabulary"},
    26: {"links"},
    27: {"orphan"},
    32: {"status-copy"},
    34: {"board-state", "waits-on"},
}


def ledger_mechanised() -> dict[int, set[str]]:
    text = (ROOT / "Docs/standards/failure-modes.md").read_text(encoding="utf-8").split("## How to add an entry")[0]
    found: dict[int, set[str]] = {}
    parts = re.split(r"^### (\d+) · ", text, flags=re.MULTILINE)
    for number, body in zip(parts[1::2], parts[2::2], strict=True):
        match = re.search(r"^\*\*Mechanised by:\*\* (.+?)(?:\n\n|\Z)", body, re.MULTILINE | re.DOTALL)
        if match:
            found[int(number)] = set(re.findall(r"`([a-z-]+)`", match.group(1)))
    return found


@pins("Docs/standards/failure-modes.md")
def test_the_ledger_entries_a_docs_check_holds_name_it() -> None:
    assert ledger_mechanised() == HELD


def test_every_check_a_ledger_entry_names_exists() -> None:
    named = set().union(*ledger_mechanised().values())
    assert named <= set(cd.CHECKS), sorted(named - set(cd.CHECKS))


def test_underscores_in_a_replacement_name_survive_the_markup_strip() -> None:
    glossary = (
        "| ~~Retired~~ | Use | Why |\n| --- | --- | --- |\n| ~~old.camera~~ | `hog_rendering.camera` | Moved. |\n"
    )
    ctx = cd.Context(
        Path("."), fc.DocsConfig(), 150, {"core": "on"}, ("Docs/glossary.md",), {"Docs/glossary.md": glossary}
    )
    assert cd.retired_terms(ctx) == {"old.camera": "hog_rendering.camera"}


# --------------------------------------------------------------------------- review of part 2
@pytest.mark.parametrize(
    "row",
    [
        "| ~~Color Stack Window~~ | Color Stack | The replacement is found inside the term. |",
        "| ~~old~~ | old | The same word. |",
        "| ~~old~~ | OLD | The same word in another case. |",
        "| ~~old~~ | **old** | The same word in markup. |",
        "| ~~old~~ | new or fresh | Alternatives. |",
        "| ~~old~~ | x; y | Semicolon. |",
        "| ~~old~~ | x: y | Colon. |",
        "| ~~old~~ | x. y | Full stop. |",
        "| ~~old~~ | one two three four five six seven | Seven words. |",
    ],
)
def test_a_replacement_that_could_never_clear_the_finding_is_refused(tmp_path: Path, row: str) -> None:
    found = checks_of(tmp_path, with_glossary(base_files(), GLOSSARY + row + "\n"))
    assert [f.check for f in found] == ["glossary-row"], row


@pytest.mark.parametrize(
    ("cell", "expected"),
    [
        ("[new](x.md)", "new"),
        ("new.", "new"),
        ("**`new`**", "new"),
        ("hog_rendering.camera", "hog_rendering.camera"),
        ("a  b   c", "a b c"),
    ],
)
def test_a_replacement_is_read_as_the_name_it_shows(cell: str, expected: str) -> None:
    assert cd._retired_row(["~~old~~", cell, "why"]) == ("old", expected)


def test_a_term_retired_twice_is_a_finding_on_the_second_row(tmp_path: Path) -> None:
    files = with_glossary(base_files(), GLOSSARY + "| ~~OLDWORD~~ | other | Again. |\n")
    found = checks_of(tmp_path, files)
    assert [(f.check, f.location) for f in found] == [
        ("glossary-row", f"Docs/glossary.md:{GLOSSARY.count(chr(10)) + 1}")
    ]
    assert "retired twice" in found[0].detail


def test_a_long_run_of_spaces_or_hyphens_in_a_term_does_not_stall_the_check(tmp_path: Path) -> None:
    import time

    glossary = GLOSSARY + "| ~~a" + " " * 40000 + "b~~ | c | Many spaces. |\n| ~~x - - y~~ | z | Hyphens. |\n"
    started = time.perf_counter()
    checks_of(tmp_path, with_glossary(base_files(), glossary))
    # the line starts with the pattern's first word and never ends it: the long gap is scanned and given back
    assert cd._phrase_re("x - - y").search("x" + "-" * 60000 + "\n") is None
    assert cd._phrase_re("x   y").search("x" + " " * 60000 + "\n") is None
    assert time.perf_counter() - started < 30.0


def test_a_retired_table_inside_a_fence_is_not_enforced(tmp_path: Path) -> None:
    fenced = (
        "# G\n\n**Status:** Living.\n\n```\n| ~~Retired~~ | Use | Why |\n| --- | --- | --- |\n"
        "| ~~oldword~~ | newword | x |\n```\n"
    )
    files = with_glossary(base_files(), fenced)
    files["Docs/notes.md"] = _doc(body="We say oldword.\n" * 1)
    files["Docs/README.md"] += "[n](notes.md)\n"
    assert checks_of(tmp_path, files) == []


@pytest.mark.parametrize("cell", ["x; y", "x: y", "x. y"])
def test_each_sentence_mark_alone_makes_a_replacement_unnameable(cell: str) -> None:
    assert cd._retired_row(["~~old~~", cell, "why"]) is None


def test_the_header_window_for_the_ended_status_is_the_first_twelve_lines(tmp_path: Path) -> None:
    late = "# N\n" + "\n" * 12 + "**Status:** Abandoned.\n\noldword here.\n"
    found = vocab(tmp_path, "Fine.\n", **{"Docs/late.md": late})
    assert "vocabulary" in {f.check for f in found if f.location.startswith("Docs/late.md")}


# ---- nested-instructions looks where the documents do not
@pytest.mark.parametrize(
    "where",
    ["Spikes/x/CLAUDE.md", ".temp/GEMINI.md", ".claude/CLAUDE.md", "vendor/AGENTS.md", "Docs/sub/CLAUDE.local.md"],
)
def test_an_instruction_file_is_found_in_folders_the_documents_walk_skips(tmp_path: Path, where: str) -> None:
    files = base_files()
    files[where] = "# not a document\n"
    found = [f for f in checks_of(tmp_path, files) if f.check == "nested-instructions"]
    assert [f.location for f in found] == [where]


@pytest.mark.parametrize(
    "where",
    [
        ".git/x/AGENTS.md",
        ".venv/lib/CLAUDE.md",
        "node_modules/p/AGENTS.md",
        ".worktrees/b/AGENTS.md",
        ".claude/worktrees/b/CLAUDE.md",
    ],
)
def test_other_checkouts_and_installed_packages_are_not_this_repositorys_instruction_files(
    tmp_path: Path, where: str
) -> None:
    files = base_files()
    files[where] = "# a copy\n"
    assert [f for f in checks_of(tmp_path, files) if f.check == "nested-instructions"] == []


def test_the_root_instruction_files_are_never_nested(tmp_path: Path) -> None:
    files = base_files()
    files.update(
        {"AGENTS.md": "# a\n", "CLAUDE.md": "@AGENTS.md\n", "GEMINI.md": "@AGENTS.md\n", "CLAUDE.local.md": "x\n"}
    )
    assert checks_of(tmp_path, files) == []


# ---- orphan is reachability
def test_two_documents_that_link_only_to_each_other_are_still_orphans(tmp_path: Path) -> None:
    files = base_files()
    files["Docs/island/a.md"] = _doc(body="[b](b.md)\n")
    files["Docs/island/b.md"] = _doc(body="[a](a.md)\n")
    found = checks_of(tmp_path, files)
    assert [(f.check, f.location) for f in found] == [("orphan", "Docs/island/a.md"), ("orphan", "Docs/island/b.md")]


def test_a_chain_from_the_map_reaches_every_document_on_it(tmp_path: Path) -> None:
    files = base_files()
    files["Docs/chain/a.md"] = _doc(body="[b](b.md)\n")
    files["Docs/chain/b.md"] = _doc(body="[c](c.md)\n")
    files["Docs/chain/c.md"] = _doc()
    files["Docs/README.md"] += "[a](chain/a.md)\n"
    assert checks_of(tmp_path, files) == []


def test_a_document_outside_the_governed_directories_is_part_of_the_map(tmp_path: Path) -> None:
    files = base_files()
    files["Docs/extra.md"] = _doc()
    files["tools/NOTES.md"] = "# Notes\n\n[extra](../Docs/extra.md)\n"
    assert checks_of(tmp_path, files) == []


def test_a_session_files_links_do_not_wire_a_document_in(tmp_path: Path) -> None:
    files = base_files()
    files["Docs/extra.md"] = _doc()
    files[f"Docs/journal/{TODAY}-session-01.md"] = "# S\n\n[extra](../extra.md)\n"
    assert [f.check for f in checks_of(tmp_path, files)] == ["orphan"]


def test_a_link_to_a_directory_does_not_reach_what_is_inside_it(tmp_path: Path) -> None:
    files = base_files()
    files["Docs/sub/README.md"] = _doc()
    files["Docs/README.md"] += "[dir](sub/)\n"
    assert [(f.check, f.location) for f in checks_of(tmp_path, files)] == [("orphan", "Docs/sub/README.md")]


# ---- adr-refs
def test_a_back_link_of_the_wrong_kind_does_not_count(tmp_path: Path) -> None:
    files = adrs("**Superseded by:** [ADR-002](ADR-002-two.md)", "**Superseded by:** [ADR-001](ADR-001-first.md)")
    found = [f for f in checks_of(tmp_path, files) if f.check == "adr-refs"]
    assert sorted(f.location for f in found) == [
        "Docs/decisions/ADR-001-first.md:5",
        "Docs/decisions/ADR-002-two.md:5",
    ]


def test_several_links_on_one_relation_line_are_each_checked(tmp_path: Path) -> None:
    files = adrs(
        "**Extends:** [two](ADR-002-two.md) [three](ADR-003-three.md)", "**Extended by:** [one](ADR-001-first.md)"
    )
    files["Docs/decisions/ADR-003-three.md"] = _doc("Accepted")
    files["Docs/decisions/README.md"] += "| [3](ADR-003-three.md) | Three |\n"
    found = [f for f in checks_of(tmp_path, files) if f.check == "adr-refs"]
    assert len(found) == 1 and "ADR-003-three.md" in found[0].detail


def test_adrs_in_a_sub_directory_are_checked_too(tmp_path: Path) -> None:
    files = adrs()
    files["Docs/decisions/sub/ADR-005-five.md"] = _doc("Accepted", "**Extends:** [one](../ADR-001-first.md)\n")
    files["Docs/decisions/README.md"] += "| [5](sub/ADR-005-five.md) | Five |\n"
    found = [f for f in checks_of(tmp_path, files) if f.check == "adr-refs"]
    assert [f.location for f in found] == ["Docs/decisions/sub/ADR-005-five.md:5"]


@pytest.mark.parametrize(
    "line",
    [
        "**Superseded by**: [ADR-002](ADR-002-two.md)",
        "**superseded by:** [ADR-002](ADR-002-two.md)",
        "- **Superseded by:** [ADR-002](ADR-002-two.md)",
        "> - **Superseded by:** [ADR-002](ADR-002-two.md)",
        "**Status:** Superseded by [ADR-002](ADR-002-two.md)",
    ],
)
def test_the_relation_line_is_read_in_every_shape_and_the_status_form_counts(tmp_path: Path, line: str) -> None:
    files = adrs(line, "")
    found = [f for f in checks_of(tmp_path, files) if f.check == "adr-refs"]
    assert len(found) == 1 and "`Superseded by`" in found[0].detail, line
    both = adrs(line, "**Supersedes:** [ADR-001](ADR-001-first.md)")
    assert [f for f in checks_of(tmp_path / "both", both) if f.check == "adr-refs"] == []


def test_a_wide_adr_does_not_make_the_check_quadratic(tmp_path: Path) -> None:
    import time

    relations = "\n".join("**Extends:** [two](ADR-002-two.md)" for _ in range(2000))
    files = adrs(relations, "**Extended by:** [one](ADR-001-first.md)\n" + "filler line\n" * 5000)
    started = time.perf_counter()
    assert [f for f in checks_of(tmp_path, files) if f.check == "adr-refs"] == []
    assert time.perf_counter() - started < 30.0


# ---- the other configuration
def test_a_grandfathered_path_that_cannot_shrink_is_a_finding(tmp_path: Path) -> None:
    files = with_glossary(base_files())
    listed = '[docs]\nterms_grandfathered = ["Docs/notes.md"]\n'  # outside terms_dirs: dead
    files["Docs/notes.md"] = _doc()
    files["Docs/README.md"] += "[n](notes.md)\n"
    found = checks_of(tmp_path, files, framework=toml(extra=listed))
    assert [(f.check, f.location) for f in found] == [("terms", "Docs/notes.md")]
    assert "outside terms_dirs" in found[0].detail


def test_an_unreadable_grandfathered_file_is_not_called_missing(tmp_path: Path) -> None:
    files = with_glossary(base_files())
    root = write_repo(tmp_path, files, framework=toml(extra='[docs]\nterms_grandfathered = ["Docs/design/old.md"]\n'))
    (root / "Docs/design").mkdir(parents=True)
    (root / "Docs/design/old.md").write_bytes(b"\xff\xfe")
    found = [f for f in findings_of(root) if f.check == "terms"]
    assert found == []  # the corpus check reports it; terms must not also say it is gone


# ---- the ledger is read as a paragraph
def test_a_mechanised_by_paragraph_is_read_across_its_wrapped_lines() -> None:
    sample = (
        "### 1 · A\n\n**Because:** x\n**Mechanised by:** `links`, and\n`corpus` on the next line.\n\n"
        "### 2 · B\n\nplain\n"
    )
    parts = re.split(r"^### (\d+) · ", sample, flags=re.MULTILINE)
    found = {}
    for number, body in zip(parts[1::2], parts[2::2], strict=True):
        match = re.search(r"^\*\*Mechanised by:\*\* (.+?)(?:\n\n|\Z)", body, re.MULTILINE | re.DOTALL)
        if match:
            found[int(number)] = set(re.findall(r"`([a-z-]+)`", match.group(1)))
    assert found == {1: {"links", "corpus"}}


def test_table_rows_drops_the_separator_and_marks_the_header() -> None:
    rows = cd._table_rows([(1, "| a | b |"), (2, "| --- | :-: |"), (3, "| c | d |"), (4, "e | f")])
    assert rows == [(1, ["a", "b"], True), (3, ["c", "d"], False)]
    bare = cd._table_rows([(1, "| a | b |"), (2, "--- | ---"), (3, "| c | d |")])
    assert [header for _, _, header in bare] == [True, False]


def test_a_retired_cell_longer_than_a_name_is_refused_before_it_is_parsed() -> None:
    assert cd._retired_row(["~~" + "a" * 250 + "~~", "new", "why"]) is None
    assert cd._retired_row(["~~old~~", "n" * 250, "why"]) is None
    assert cd._retired_row(["~~" + "a" * 150 + "~~", "new", "why"]) is not None


# --------------------------------------------------------------------------- Copilot's review of part 2
def test_a_directory_the_instruction_walk_cannot_list_is_a_finding(tmp_path: Path, monkeypatch) -> None:
    write_repo(tmp_path, base_files())
    real_walk = cd.os.walk
    calls: list[str] = []

    def denying_walk(top, onerror=None, **kwargs):
        calls.append(str(top))
        # the documents' walk is the first call and the instruction walk the second: fail only the second, so the
        # finding can only have come from the instruction walk's own error handling
        if len(calls) == 2 and onerror is not None:
            onerror(PermissionError(13, "Permission denied", str(Path(top) / "Spikes" / "locked")))
        yield from real_walk(top, **kwargs)

    monkeypatch.setattr(cd.os, "walk", denying_walk)
    found = cd.run(cd.load_context(tmp_path))
    assert len(calls) == 2
    assert [(f.check, f.location) for f in found if f.check == "corpus"] == [("corpus", "Spikes/locked")]


@pytest.mark.parametrize("span", ["**_Plan_**", "**_Plan_:**", "**`Plan`**", "** Plan **", "**Plan:**"])
def test_underscore_emphasis_and_other_markup_inside_a_bold_term_are_stripped(tmp_path: Path, span: str) -> None:
    files = with_glossary(base_files())
    files["Docs/superpowers/specs/s.md"] = spec(f"## Terms introduced\n\n- {span}\n")
    files["Docs/README.md"] += "[s](superpowers/specs/s.md)\n"
    assert checks_of(tmp_path, files) == []


def test_an_identifier_with_underscores_keeps_them_as_a_term() -> None:
    assert cd._term_text("**__init__**") == "__init__"
    assert cd._term_text("**hog_rendering**") == "hog_rendering"
    assert cd._term_text("**_Plan_**") == "Plan"
    assert cd._term_text("**_a_**") == "a"


@pytest.mark.parametrize(
    "second", ["| ~~Foo-Bar~~ | other | Same term, hyphen. |", "| ~~foo   bar~~ | other | Same term, spaces. |"]
)
def test_a_term_retired_twice_in_another_spelling_is_still_twice(tmp_path: Path, second: str) -> None:
    files = with_glossary(base_files(), GLOSSARY + "| ~~foo bar~~ | one | First. |\n" + second + "\n")
    found = checks_of(tmp_path, files)
    assert [f.check for f in found] == ["glossary-row"] and "retired twice" in found[0].detail


def test_a_terms_section_in_the_middle_of_a_document_is_accepted(tmp_path: Path) -> None:
    """By design: findings sections are appended to a spec after its terms (HogShade's rule: wherever it sits)."""
    files = with_glossary(base_files())
    files["Docs/superpowers/specs/s.md"] = spec("## Terms introduced\n\nNone.\n\n## What the build found\n\nText.\n")
    files["Docs/README.md"] += "[s](superpowers/specs/s.md)\n"
    assert checks_of(tmp_path, files) == []


# --------------------------------------------------------------------------- journal: the two file-name forms
NEW_FORM = "Docs/journal/2026-10/2026-10-11-ada-lovelace-0930.md"


@pytest.mark.parametrize(
    ("name", "form"),
    [
        ("2026-10-11-session-01.md", "old"),
        ("2026-10-11-ada-0930.md", "new"),
        ("2026-10-11-HogJonny-AMZN-2359.md", "new"),
        ("2026-10-11-a-0000.md", "new"),
        ("2026-10-11-session-0101.md", "new"),  # a login that happens to be 'session'
        ("2026-10-11-" + "a" * 39 + "-0930.md", "new"),
        ("2026-10-11-" + "a" * 40 + "-0930.md", None),
        ("2026-10-11-ada-2460.md", None),
        ("2026-10-11-ada-2400.md", None),
        ("2026-10-11-ada-0960.md", None),
        ("2026-10-11-ada-930.md", None),
        ("2026-10-11-ada.md", None),
        ("2026-10-11--ada-0930.md", None),
        ("2026-10-11-ada--b-0930.md", None),
        ("2026-10-11-ada-b--0930.md", None),
        ("2026-10-11-a_b-0930.md", None),
        ("2026-10-11-session-1.md", None),
        ("2026-10-11-ada-0930.txt", None),
        ("notes.md", None),
    ],
)
def test_a_journal_file_name_is_the_old_form_the_new_form_or_neither(name: str, form: str | None) -> None:
    assert cd.journal_file_form(name) == form


def test_a_new_form_session_file_needs_no_row_no_status_and_no_link(tmp_path: Path) -> None:
    files = base_files()
    files[NEW_FORM] = "# Session, 2026-10-11\n\nWork.\n"
    assert findings_of(write_repo(tmp_path, files)) == []


def test_a_row_for_a_new_form_file_that_exists_is_allowed_and_for_one_that_does_not_is_found(tmp_path: Path) -> None:
    files = base_files()
    files[NEW_FORM] = "# Session\n"
    files["Docs/journal/README.md"] += "| 2026-10-11 | [Ada](2026-10/2026-10-11-ada-lovelace-0930.md) | x |\n"
    assert findings_of(write_repo(tmp_path / "ok", files)) == []

    def ghost(f: dict[str, str]) -> None:
        f["Docs/journal/README.md"] += "| 2026-10-11 | [Ada](2026-10-11-ada-lovelace-1030.md) | gone |\n"

    found = broken(tmp_path / "ghost", "journal-index", ghost, also=("links",))
    assert "2026-10-11-ada-lovelace-1030.md, which does not exist" in found[0].detail


def test_the_handoff_day_is_satisfied_by_a_new_form_file(tmp_path: Path) -> None:
    files = base_files()
    files["Docs/handoffs/CURRENT.md"] = files["Docs/handoffs/CURRENT.md"].replace(TODAY, "2026-10-12")
    files["Docs/journal/2026-10/2026-10-12-ada-0900.md"] = "# S\n"
    assert findings_of(write_repo(tmp_path, files)) == []


def test_a_handoff_dated_after_the_newest_new_form_file_is_a_finding(tmp_path: Path) -> None:
    def later(f: dict[str, str]) -> None:
        f["Docs/handoffs/CURRENT.md"] = f["Docs/handoffs/CURRENT.md"].replace(TODAY, "2026-10-13")
        f["Docs/journal/2026-10/2026-10-12-ada-0900.md"] = "# S\n"

    found = broken(tmp_path, "journal-day", later)
    assert "newest journal file is 2026-10-12" in found[0].detail


@pytest.mark.parametrize(
    ("name", "detail"),
    [
        ("2026-10-12-ada-2460.md", "2460 is not a time"),
        ("2026-10-12-ada-0960.md", "0960 is not a time"),
        ("2026-10-12-ada.md", "YYYY-MM-DD-<login>-HHMM.md"),
        ("2026-10-12--ada-0930.md", "YYYY-MM-DD-<login>-HHMM.md"),
        ("2026-10-12-" + "a" * 40 + "-0930.md", "YYYY-MM-DD-<login>-HHMM.md"),
    ],
)
def test_a_dated_file_that_is_neither_form_is_a_finding_naming_both_forms(
    tmp_path: Path, name: str, detail: str
) -> None:
    def misnamed(f: dict[str, str]) -> None:
        f[f"Docs/journal/{name}"] = "# x\n"

    found = broken(tmp_path, "journal-index", misnamed, also=("status", "orphan"))
    assert detail in found[0].detail and "YYYY-MM-DD-session-NN.md" in found[0].detail


def test_a_new_form_file_naming_an_impossible_day_is_a_finding_and_never_the_newest(tmp_path: Path) -> None:
    def impossible(f: dict[str, str]) -> None:
        f["Docs/journal/2026-02/2026-02-30-ada-0930.md"] = "# x\n"
        f["Docs/handoffs/CURRENT.md"] = f["Docs/handoffs/CURRENT.md"].replace(TODAY, "2026-12-01")

    found = broken(tmp_path, "journal-day", impossible, also=("journal-index",))
    assert "newest journal file is 2026-10-11" in found[0].detail


# --------------------------------------------------------------------------- journal-author, and the derived page
ROSTER = (
    '[[people]]\nlogin = "ada"\nname = "Ada"\nrole = "owner"\n\n'
    '[[people]]\nlogin = "Bo-B"\nname = "Bo"\nrole = "contributor"\n'
)
AUTHORED = "Docs/journal/2026-10/2026-10-11-ada-0930.md"
GOOD_SESSION = """\
# Session, 2026-10-11

**Status:** Living (append-only within the session).
**Summary:** Decided the thing.

### A heading
**By:** @ada · **Agent:** Claude Code, Opus
**Said by:** @Bo-B

@bo-b: "a quote"

### A pairing
**By:** @ada, @bo-b · **Agent:** none

Prose.
"""


def author_findings(tmp: Path, session: str | None, *, roster: str = ROSTER, journal: str = "on", name: str = AUTHORED):
    files = base_files()
    if session is not None:
        files[name] = session
    write_repo(tmp, files, framework=toml(journal=journal, extra=roster))
    return [f for f in findings_of(tmp) if f.check == "journal-author"], findings_of(tmp)


def test_a_well_formed_new_form_file_passes_every_check(tmp_path: Path) -> None:
    ours, everything = author_findings(tmp_path, GOOD_SESSION)
    assert ours == [] and everything == []


def test_without_a_roster_journal_author_is_silent_whatever_the_file_says(tmp_path: Path) -> None:
    bad = GOOD_SESSION.replace("@ada, @bo-b", "@nobody").replace("**Summary:** Decided the thing.\n", "")
    ours, everything = author_findings(tmp_path, bad, roster="")
    assert ours == [] and everything == []


def test_with_the_journal_module_off_journal_author_is_silent(tmp_path: Path) -> None:
    ours, _ = author_findings(tmp_path, GOOD_SESSION.replace("@ada, @bo-b", "@nobody"), journal="off")
    assert ours == []


def test_an_old_form_file_is_never_checked_for_authorship(tmp_path: Path) -> None:
    files = base_files()
    files[f"Docs/journal/{TODAY}-session-01.md"] = '# S\n\n### Heading\nNo author at all, @nobody: "x"\n'
    write_repo(tmp_path, files, framework=toml(extra=ROSTER))
    assert [f for f in findings_of(tmp_path) if f.check == "journal-author"] == []


@pytest.mark.parametrize(
    ("session", "name", "detail"),
    [
        (GOOD_SESSION, "Docs/journal/2026-10/2026-10-11-zed-0930.md", "login 'zed' is not on the roster"),
        (GOOD_SESSION.replace("**Summary:** Decided the thing.\n", ""), AUTHORED, "no **Summary:** line"),
        (GOOD_SESSION.replace("Decided the thing.", ""), AUTHORED, "**Summary:** is empty"),
        (GOOD_SESSION.replace("Decided the thing.", "x" * 201), AUTHORED, "longer than 200 characters"),
        (
            GOOD_SESSION.replace("### A heading\n", "### A heading\n\nA line before the By line.\n"),
            AUTHORED,
            "entry 'A heading' has no **By:**",
        ),
        (
            GOOD_SESSION.replace("**By:** @ada · **Agent:** Claude Code, Opus", "**By:** @ada"),
            AUTHORED,
            "entry 'A heading' has no **By:**",
        ),
        (
            GOOD_SESSION.replace("**Agent:** Claude Code, Opus", "**Agent:**"),
            AUTHORED,
            "entry 'A heading' has no **By:**",
        ),
        (GOOD_SESSION.replace("**By:** @ada ·", "**By:** @zed ·"), AUTHORED, "entry 'A heading': '@zed' is not on"),
        (GOOD_SESSION.replace("@ada, @bo-b", "@ada, @zed"), AUTHORED, "entry 'A pairing': '@zed' is not on"),
        (GOOD_SESSION.replace("**Said by:** @Bo-B", "**Said by:** @zed"), AUTHORED, "'@zed' is not on the roster"),
        (GOOD_SESSION.replace('@bo-b: "a quote"', '@zed: "a quote"'), AUTHORED, "'@zed:' tags a quote"),
        (GOOD_SESSION.replace('@bo-b: "a quote"', '- @zed: "a quote"'), AUTHORED, "'@zed:' tags a quote"),
    ],
)
def test_each_journal_author_finding_fires_alone(tmp_path: Path, session: str, name: str, detail: str) -> None:
    files = base_files()
    files[name] = session
    write_repo(tmp_path, files, framework=toml(extra=ROSTER))
    found = findings_of(tmp_path)
    assert {f.check for f in found} == {"journal-author"}, [str(f) for f in found]
    assert any(detail in f.detail for f in found), [str(f) for f in found]


def test_a_login_is_compared_ignoring_case_and_a_file_may_have_no_entries(tmp_path: Path) -> None:
    session = GOOD_SESSION.replace("@bo-b", "@BO-B").replace("**By:** @ada", "**By:** @ADA")
    ours, _ = author_findings(tmp_path / "case", session, name="Docs/journal/2026-10/2026-10-11-ADA-0930.md")
    assert ours == []
    header_only = "# Session\n\n**Status:** Living.\n**Summary:** It crossed midnight.\n**Preceded by:** [x](a.md).\n"
    ours, _ = author_findings(tmp_path / "bare", header_only)
    assert ours == []


def test_a_login_in_a_code_fence_or_an_at_sign_in_prose_is_not_read(tmp_path: Path) -> None:
    session = GOOD_SESSION + "\n```\n### Not an entry\n@zed: nope\n```\n\nSee @types/node: and @param: here.\n"
    ours, _ = author_findings(tmp_path, session)
    assert ours == []


def test_the_derived_index_page_is_not_read_by_the_docs_check(tmp_path: Path) -> None:
    files = base_files()
    files["Docs/journal/INDEX.md"] = "# Journal\n\nno status header, and [gone](missing.md) and nothing links here\n"
    write_repo(tmp_path, files, framework=toml(extra=ROSTER))
    assert findings_of(tmp_path) == []
    assert "Docs/journal/INDEX.md" not in cd.load_context(tmp_path).files


def test_only_that_one_path_is_skipped(tmp_path: Path) -> None:
    files = base_files()
    files["Docs/journal/OTHER.md"] = "# x\n"
    files["Docs/INDEX.md"] = "# x\n"
    write_repo(tmp_path, files)
    checks = {f.check for f in findings_of(tmp_path)}
    assert checks == {"status", "orphan"}


# --------------------------------------------------------------------------- journal-author: from the deliberate review
def _author_problems(session: str) -> list[str]:
    return cd._journal_author_findings(AUTHORED, session, frozenset({"ada", "bo-b"}))


@pytest.mark.parametrize(
    "hostile",
    [
        "### a" + " " * 4000 + "x\n**By:** @ada · **Agent:** x\n",
        "### A\n**By:**" + " " * 4000 + "\n",
        "### A\n**By:** @ada" + " · " * 2000 + "\n",
        "**Summary:**" + " " * 4000 + "\n### A\n**By:** @ada · **Agent:** x\n",
        "### A\n**By:** @ada · **Agent:** x\n**Said by:**" + " @ada" * 3000 + "\n",
    ],
)
def test_a_whitespace_heavy_line_cannot_stall_the_check(hostile: str) -> None:
    import time

    started = time.perf_counter()
    _author_problems("**Summary:** s\n" + hostile)
    assert time.perf_counter() - started < 2.0


def test_the_entry_scan_is_linear_in_the_number_of_entries() -> None:
    import time

    session = "**Summary:** s\n" + "### A\n**By:** @ada · **Agent:** x\n\nProse.\n" * 6000
    started = time.perf_counter()
    assert _author_problems(session) == []
    assert time.perf_counter() - started < 2.0


def test_a_summary_of_exactly_two_hundred_characters_passes_and_two_hundred_and_one_does_not() -> None:
    assert _author_problems("**Summary:** " + "x" * 200 + "\n") == []
    assert any("longer than 200" in p for p in _author_problems("**Summary:** " + "x" * 201 + "\n"))


def test_an_entry_ends_at_a_heading_of_a_higher_level() -> None:
    session = "**Summary:** s\n### One\n\n## A section\n**By:** @ada · **Agent:** x\n"
    assert any("entry 'One' has no **By:**" in p for p in _author_problems(session))


def test_text_after_the_logins_in_a_by_line_is_a_finding() -> None:
    session = "**Summary:** s\n### One\n**By:** @ada and @bo-b · **Agent:** x\n"
    assert any("entry 'One' has no **By:**" in p for p in _author_problems(session))


def test_a_summary_after_the_first_entry_does_not_count() -> None:
    session = "### One\n**By:** @ada · **Agent:** x\n**Summary:** too late\n"
    assert any("no **Summary:** line" in p for p in _author_problems(session))


def test_an_entry_heading_indented_up_to_three_spaces_is_an_entry_and_four_is_code() -> None:
    assert any("entry 'One'" in p for p in _author_problems("**Summary:** s\n   ### One\nNo by line.\n"))
    assert _author_problems("**Summary:** s\n    ### One\nNo by line.\n") == []


def test_the_derived_page_skipped_is_the_one_in_the_configured_journal_directory(tmp_path: Path) -> None:
    files = base_files()
    files["Notes/log/INDEX.md"] = "# no status\n"
    files["Docs/journal/INDEX.md"] = "# no status either\n"
    write_repo(tmp_path, files, framework=toml(extra='[docs]\njournal_dir = "Notes/log"\n'))
    seen = cd.load_context(tmp_path).files
    assert "Notes/log/INDEX.md" not in seen and "Docs/journal/INDEX.md" in seen


@pytest.mark.parametrize(
    "name",
    ["2026-10-11-ada-٠٩٣٠.md", "2026-10-11-ada-0930.md\n", "2026-10-11-session-0١.md"],
)
def test_a_journal_file_name_takes_ascii_digits_and_nothing_after_the_extension(name: str) -> None:
    assert cd.journal_file_form(name) is None


def test_a_tab_after_the_hashes_makes_an_entry_heading_too() -> None:
    assert any("entry 'One'" in p for p in _author_problems("**Summary:** s\n###\tOne\nNo by line.\n"))
    assert _author_problems("**Summary:** s\n###\tOne\n**By:** @ada · **Agent:** x\n") == []


def test_every_login_in_a_long_said_by_line_is_read() -> None:
    session = "**Summary:** s\n### One\n**By:** @ada · **Agent:** x\n**Said by:** @ada," + " " * 1500 + "@zed\n"
    assert any("'@zed' is not on the roster" in p for p in _author_problems(session))


def test_a_quote_tag_after_a_very_long_indent_is_still_read() -> None:
    assert any("'@zed:' tags a quote" in p for p in _author_problems("**Summary:** s\n" + " " * 1500 + "@zed: hi\n"))


def _best_times(run_small: Callable[[], object], run_large: Callable[[], object], runs: int = 5) -> tuple[float, float]:
    """The fastest of ``runs`` timings of each, taken alternately: a shared runner that stalls once (issue #120, a 4x
    input once took 10x on Windows) stalls one sample, and the best of several alternating samples is the work."""
    import time

    best = [float("inf"), float("inf")]
    for _ in range(runs):
        for slot, run in enumerate((run_small, run_large)):
            started = time.perf_counter()
            run()
            best[slot] = min(best[slot], time.perf_counter() - started)
    return best[0], best[1]


def _sessions(entries: int) -> str:
    return "**Summary:** s\n" + "### A\n**By:** @ada · **Agent:** x\n\nProse.\n" * entries


def test_the_entry_scan_grows_in_proportion_to_the_number_of_entries() -> None:
    small_text, large_text = _sessions(4000), _sessions(16000)
    assert _author_problems(small_text) == [] and _author_problems(large_text) == []
    small, large = _best_times(lambda: _author_problems(small_text), lambda: _author_problems(large_text))
    # four times the entries: about four times the time; quadratic growth would be sixteen
    assert large < 8 * small + 0.05, f"{small:.3f}s for 4,000 entries, {large:.3f}s for 16,000"


def test_the_growth_measure_tells_quadratic_from_linear() -> None:
    """The negative control: the same measure and limit fail a scan whose work grows with the square of its input."""

    def quadratic(n: int) -> int:
        return sum(1 for _ in range(n) for _ in range(n))

    small, large = _best_times(lambda: quadratic(1000), lambda: quadratic(4000), runs=3)  # large well over the 0.05s
    assert not large < 8 * small + 0.05, f"{small:.3f}s for 1,000, {large:.3f}s for 4,000: the limit would pass it"


# --------------------------------------------------------------------------- ADR ids and adr-duplicate (dated ADRs)
def _dated_adr_corpus(files: dict[str, str], name: str, *, index: bool = True) -> None:
    """A dated ADR beside ``ADR-001``; indexed unless told not to (an unindexed one is ``adr-index``'s)."""
    files[f"Docs/decisions/{name}"] = _doc("Accepted")
    if index:
        files["Docs/decisions/README.md"] += f"| [{name}]({name}) | Dated |\n"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("ADR-005-x.md", cd.AdrId("number", number=5)),
        ("adr-5-y.md", cd.AdrId("number", number=5)),
        ("ADR-2026-10-29-records-for-a-team.md", cd.AdrId("dated", day="2026-10-29", slug="records-for-a-team")),
        ("ADR-2026-10-29-Mixed-Case.md", cd.AdrId("dated", day="2026-10-29", slug="mixed-case")),
        ("ADR-2026-02-30-x.md", cd.AdrId("dated", day="2026-02-30", slug="x")),  # the day is judged by the check
        ("ADR-2026-10-29.md", cd.AdrId("dated", day="2026-10-29", slug="")),  # dated by shape; no slug is the check's
        ("ADR-2026-10-29-.md", cd.AdrId("dated", day="2026-10-29", slug="")),
        ("notes.md", None),
        ("ADR-.md", None),
    ],
)
def test_an_adr_id_is_read_from_either_name_form(name: str, expected: cd.AdrId | None) -> None:
    assert cd.adr_id(name) == expected


def test_an_adr_id_keeps_the_slug_as_written_and_ignores_it_for_equality() -> None:
    mixed, lower = cd.adr_id("ADR-2026-10-29-Mixed-Case.md"), cd.adr_id("ADR-2026-10-29-mixed-case.md")
    assert mixed == lower and hash(mixed) == hash(lower)
    assert mixed is not None and mixed.raw_slug == "Mixed-Case"
    assert cd.adr_id("ADR-005-x.md") != cd.adr_id("ADR-2026-10-29-x.md")


def test_a_dated_adr_is_indexed_and_related_like_a_numbered_one(tmp_path: Path) -> None:
    files = base_files()
    name = "ADR-2026-10-29-records-for-a-team.md"
    files["Docs/decisions/ADR-001-first.md"] = _doc("Accepted", f"**Extended by:** [new]({name})\n")
    files[f"Docs/decisions/{name}"] = _doc("Accepted", "**Extends:** [one](ADR-001-first.md)\n")
    files["Docs/decisions/README.md"] += f"| [{name}]({name}) | Dated |\n"
    assert findings_of(write_repo(tmp_path, files)) == []


def test_two_numbered_adrs_with_one_number_are_a_finding_on_both(tmp_path: Path) -> None:
    def mutate(files: dict[str, str]) -> None:
        files["Docs/decisions/ADR-1-other.md"] = _doc("Accepted")  # ADR-001 and ADR-1 are one id
        files["Docs/decisions/README.md"] += "| [1b](ADR-1-other.md) | Other |\n"

    found = broken(tmp_path, "adr-duplicate", mutate)
    assert {f.location for f in found} == {"Docs/decisions/ADR-001-first.md", "Docs/decisions/ADR-1-other.md"}
    assert all("ADR number 1" in f.detail and "ADR-001 and ADR-1 are one number" in f.detail for f in found), [
        str(f) for f in found
    ]


def test_two_dated_adrs_with_one_date_and_slug_anywhere_below_the_index_are_a_finding(tmp_path: Path) -> None:
    """The second file sits in a sub-directory: a case-insensitive disk cannot hold two names that differ only in case,
    so the case-only pair is proved on a hand-built corpus in the next test, not on disk."""

    def mutate(files: dict[str, str]) -> None:
        _dated_adr_corpus(files, "ADR-2026-10-29-x.md")
        files["Docs/decisions/old/ADR-2026-10-29-x.md"] = _doc("Accepted")
        files["Docs/decisions/README.md"] += "| [old](old/ADR-2026-10-29-x.md) | Old |\n"

    found = broken(tmp_path, "adr-duplicate", mutate)
    assert len(found) == 2 and all("2026-10-29-x" in f.detail for f in found), [str(f) for f in found]


def test_two_dated_adrs_differing_only_in_case_are_one_id_on_a_hand_built_corpus(tmp_path: Path) -> None:
    """No disk: a Context with both names, which Windows and macOS could not hold side by side."""
    files = ("Docs/decisions/ADR-2026-10-29-X.md", "Docs/decisions/ADR-2026-10-29-x.md", "Docs/decisions/README.md")
    ctx = cd.Context(tmp_path, fc.DocsConfig(), 150, {}, files, {rel: _doc("Accepted") for rel in files})
    found = cd.check_adr_duplicate(ctx)
    duplicates = [f for f in found if "shares" in f.detail]
    assert {f.location for f in duplicates} == set(files[:2]), [str(f) for f in found]
    assert all("without regard to case" in f.detail for f in duplicates)
    assert [f.location for f in found if "is not lowercase" in f.detail] == [files[0]]  # the upper-case slug, too


def test_a_dated_name_with_no_slug_is_a_finding_not_a_numbered_adr(tmp_path: Path) -> None:
    found = broken(tmp_path, "adr-duplicate", lambda files: _dated_adr_corpus(files, "ADR-2026-10-29.md"))
    assert len(found) == 1 and "no slug" in found[0].detail, [str(f) for f in found]


def test_a_dated_adr_whose_day_is_not_real_is_a_finding(tmp_path: Path) -> None:
    found = broken(tmp_path, "adr-duplicate", lambda files: _dated_adr_corpus(files, "ADR-2026-02-30-x.md"))
    assert len(found) == 1 and "2026-02-30" in found[0].detail and "day" in found[0].detail


@pytest.mark.parametrize("name", ["ADR-2026-10-29-Bad_Slug.md", "ADR-2026-10-29-a--b.md", "ADR-2026-10-29-Mixed.md"])
def test_a_dated_adr_whose_slug_breaks_the_rule_is_a_finding(tmp_path: Path, name: str) -> None:
    found = broken(tmp_path, "adr-duplicate", lambda files: _dated_adr_corpus(files, name))
    assert len(found) == 1 and "slug" in found[0].detail, [str(f) for f in found]


def test_a_numbered_adr_is_never_held_to_the_slug_rule(tmp_path: Path) -> None:
    files = base_files()
    files["Docs/decisions/ADR-002-Has_Caps.md"] = _doc("Accepted")
    files["Docs/decisions/README.md"] += "| [2](ADR-002-Has_Caps.md) | Two |\n"
    assert findings_of(write_repo(tmp_path, files)) == []


# --------------------------------------------------------------------------- status-copy
def _with_line(line: str, *, extra: dict[str, str] | None = None, into: str = "Docs/README.md") -> dict[str, str]:
    """The base corpus with ``line`` appended to a document, and any extra files (the targets a line points at)."""
    files = base_files()
    files[into] += line + "\n"
    files.update(extra or {})
    return files


def _copies(tmp: Path, files: dict[str, str]) -> list[cd.Finding]:
    found = findings_of(write_repo(tmp, files))
    assert {f.check for f in found} <= {"status-copy"}, [str(f) for f in found]
    return found


TWO = {"Docs/standards/two.md": _doc("Accepted")}


def test_a_status_after_a_link_that_differs_from_the_documents_own_is_a_finding(tmp_path: Path) -> None:
    found = _copies(tmp_path, _with_line("Next: [the spec](standards/one.md) (Proposed)"))
    assert len(found) == 1 and found[0].check == "status-copy"
    assert found[0].location.startswith("Docs/README.md:")
    assert "says Proposed beside Docs/standards/one.md, whose status is Accepted" in found[0].detail


def test_the_finding_names_the_line_it_is_on(tmp_path: Path) -> None:
    files = _with_line("Next: [the spec](standards/one.md) (Proposed)")
    line = files["Docs/README.md"].split("\n").index("Next: [the spec](standards/one.md) (Proposed)") + 1
    assert [f.location for f in _copies(tmp_path, files)] == [f"Docs/README.md:{line}"]


@pytest.mark.parametrize(
    "line",
    [
        "Next: [the spec](standards/one.md) (Accepted)",
        "Next: [the spec](standards/one.md) (Accepted 2026-10-22)",
        "Next: [the spec](standards/one.md) (was Proposed)",
        "Next: [the spec](standards/one.md) (Proposed then Accepted)",
        "Next: [the spec](standards/one.md) (Accepted, was Proposed)",
        "Next: [the spec](standards/one.md) (Draft)",
        "Next: [the spec](standards/one.md) (accepted)",
        "Next: [the spec](standards/one.md) Proposed",
        "Next: [the spec](standards/one.md) - (Proposed)",
        "Next: [the spec](standards/one.md), the second (Proposed) draft",
        "Next: [the spec](standards/one.md) `(Proposed)`",
        "Next: [the spec](standards/one.md) (Acceptedish)",
    ],
)
def test_a_status_beside_a_link_that_is_not_a_disagreeing_copy_is_not_read(tmp_path: Path, line: str) -> None:
    assert _copies(tmp_path, _with_line(line)) == []


def test_a_date_after_the_word_is_part_of_the_copy(tmp_path: Path) -> None:
    found = _copies(tmp_path, _with_line("Next: [the spec](standards/one.md) (Proposed 2026-10-22)"))
    assert len(found) == 1 and "says Proposed" in found[0].detail


def test_text_after_the_word_is_ignored_unless_it_names_a_second_status(tmp_path: Path) -> None:
    assert len(_copies(tmp_path, _with_line("[a](standards/one.md) (Proposed, the owner's merge accepts it)"))) == 1
    assert _copies(tmp_path, _with_line("[a](standards/one.md) (Proposed, then Living)")) == []


def test_a_fragment_on_the_target_is_not_part_of_the_path(tmp_path: Path) -> None:
    found = _copies(tmp_path, _with_line("[the spec](standards/one.md#top) (Proposed)"))
    assert len(found) == 1 and "Docs/standards/one.md," in found[0].detail


def test_the_line_that_began_this_work_is_a_finding_by_its_text(tmp_path: Path) -> None:
    line = "increment 2 (Proposed): [spec](standards/one.md) and [plan](standards/two.md)"
    found = _copies(tmp_path, _with_line(line, extra=TWO))
    assert len(found) == 1 and "says Proposed beside Docs/standards/one.md" in found[0].detail


def test_a_status_before_a_link_reads_the_first_link_only(tmp_path: Path) -> None:
    first_agrees = "increment (Accepted): [a](standards/one.md) and [b](standards/two.md)"
    second_disagrees = {"Docs/standards/two.md": _doc("Living")}
    assert _copies(tmp_path, _with_line(first_agrees, extra=second_disagrees)) == []


def test_a_status_before_a_link_that_agrees_is_not_a_finding(tmp_path: Path) -> None:
    assert _copies(tmp_path, _with_line("increment (Accepted): [a](standards/one.md)")) == []


def test_a_status_before_a_link_needs_only_whitespace_between(tmp_path: Path) -> None:
    assert _copies(tmp_path, _with_line("increment (Proposed): see [a](standards/one.md)")) == []
    assert len(_copies(tmp_path, _with_line("increment (Proposed):   [a](standards/one.md)"))) == 1


def _index_row(cell: str, *, extra_link: str = "") -> dict[str, str]:
    files = base_files()
    files["Docs/decisions/README.md"] = files["Docs/decisions/README.md"].replace(
        "| [1](ADR-001-first.md) | One |", f"| [1](ADR-001-first.md){extra_link} | One | {cell} |"
    )
    return files


@pytest.mark.parametrize(
    "cell", ["Proposed", "**Proposed**", "_Proposed_", "Proposed 2026-10-22", "**Proposed** 2026-10-22"]
)
def test_a_status_cell_beside_one_governed_link_that_differs_is_a_finding(tmp_path: Path, cell: str) -> None:
    found = _copies(tmp_path, _index_row(cell))
    assert len(found) == 1 and found[0].location.startswith("Docs/decisions/README.md:")
    assert "says Proposed beside Docs/decisions/ADR-001-first.md, whose status is Accepted" in found[0].detail


@pytest.mark.parametrize(
    "cell", ["Accepted", "**Accepted**", "Accepted 2026-10-22", "Proposed in 2026", "Draft", "was Proposed"]
)
def test_a_status_cell_that_agrees_or_is_not_exactly_a_status_is_not_read(tmp_path: Path, cell: str) -> None:
    assert _copies(tmp_path, _index_row(cell)) == []


def test_a_row_with_two_governed_links_is_skipped(tmp_path: Path) -> None:
    files = _index_row("Proposed", extra_link=" and [two](../standards/one.md)")
    assert _copies(tmp_path, files) == []


def test_a_row_with_two_links_to_one_document_is_still_one_link(tmp_path: Path) -> None:
    assert len(_copies(tmp_path, _index_row("Proposed", extra_link=" [again](ADR-001-first.md)"))) == 1


def test_a_status_cell_in_a_row_with_no_governed_link_is_not_read(tmp_path: Path) -> None:
    files = base_files()
    files["Docs/README.md"] += "| [outside](../README.md) | Proposed |\n| plain | Proposed |\n"
    assert _copies(tmp_path, files) == []


@pytest.mark.parametrize(
    "fenced", ["```\n[a](standards/one.md) (Proposed)\n```", "~~~\n| [a](standards/one.md) | Proposed |\n~~~"]
)
def test_a_copy_inside_a_code_fence_is_not_read(tmp_path: Path, fenced: str) -> None:
    assert _copies(tmp_path, _with_line(fenced)) == []


def test_a_target_that_is_not_governed_has_no_status_to_copy(tmp_path: Path) -> None:
    files = _with_line("[readme](../README.md) (Proposed)")
    assert _copies(tmp_path, files) == []


def test_a_link_that_does_not_resolve_is_the_links_check_alone(tmp_path: Path) -> None:
    files = _with_line("[gone](standards/missing.md) (Proposed)")
    assert {f.check for f in findings_of(write_repo(tmp_path, files))} == {"links"}


def test_a_target_with_no_status_is_the_status_check_alone(tmp_path: Path) -> None:
    files = _with_line("[bare](standards/bare.md) (Proposed)", extra={"Docs/standards/bare.md": "# Bare\n\nText.\n"})
    files["Docs/README.md"] += "[bare](standards/bare.md)\n"
    assert {f.check for f in findings_of(write_repo(tmp_path, files))} == {"status"}


def test_every_file_inside_the_journal_directory_is_exempt(tmp_path: Path) -> None:
    files = _with_line("[the spec](../standards/one.md) (Proposed)", into="Docs/journal/README.md")
    assert _copies(tmp_path, files) == []


def test_a_copy_in_a_new_form_session_file_is_exempt_too(tmp_path: Path) -> None:
    session = "# S\n\n[the spec](../../standards/one.md) (Proposed)\n"
    files = base_files()
    files["Docs/journal/2026-10/2026-10-11-ada-0900.md"] = session
    assert _copies(tmp_path, files) == []


def test_a_copy_is_read_wherever_the_document_lives_outside_the_journal(tmp_path: Path) -> None:
    files = _with_line("", extra={"Docs/standards/two.md": _doc("Accepted", "[the spec](one.md) (Proposed)\n")})
    files["Docs/README.md"] += "[two](standards/two.md)\n"
    found = _copies(tmp_path, files)
    assert [f.location.split(":")[0] for f in found] == ["Docs/standards/two.md"]


def test_the_journal_directory_is_the_configured_one(tmp_path: Path) -> None:
    """The same copy fires with the default journal directory and is exempt once the configuration moves the journal."""
    copy = {"Docs/notes/two.md": _doc("Living", "[the spec](../standards/one.md) (Proposed)\n")}
    files = {**base_files(), **copy}
    files["Docs/README.md"] += "[two](notes/two.md)\n"

    def mine(root: Path) -> list[cd.Finding]:
        return [f for f in findings_of(root) if f.check == "status-copy"]

    assert len(mine(write_repo(tmp_path / "default", files))) == 1  # the positive control
    moved = write_repo(tmp_path / "moved", files, framework=toml(extra='[docs]\njournal_dir = "Docs/notes"\n'))
    assert mine(moved) == []


def test_a_per_login_handoff_is_not_read_for_status_copies_but_the_handoff_still_is(tmp_path: Path) -> None:
    """A per-login handoff is that login's view, written by that login alone: a lock by another login must not fail the
    gate on it (#82). The project's handoff, which any session writes, is still read."""
    stale = "[the spec](../../standards/one.md) (Proposed)\n"
    files = base_files()
    _with_ada(files)
    files[f"{PEOPLE}/ada.md"] += stale
    assert [f for f in findings_of(write_repo(tmp_path / "people", files)) if f.check == "status-copy"] == []
    files = base_files()
    files["Docs/handoffs/CURRENT.md"] += "[the spec](../standards/one.md) (Proposed)\n"
    found = [f for f in findings_of(write_repo(tmp_path / "handoff", files)) if f.check == "status-copy"]
    assert [f.location.split(":")[0] for f in found] == ["Docs/handoffs/CURRENT.md"]


def test_the_per_login_handoff_directory_is_the_configured_one(tmp_path: Path) -> None:
    """Moved by the configuration, the old folder is read again and the new one is not."""
    files = base_files()
    files["Docs/people/ada.md"] = _person(body="[the spec](../standards/one.md) (Proposed)\n")
    files["Docs/README.md"] += "[ada](people/ada.md)\n"

    def mine(root: Path) -> list[cd.Finding]:
        return [f for f in findings_of(root) if f.check == "status-copy"]

    assert len(mine(write_repo(tmp_path / "default", files))) == 1  # the positive control
    moved = write_repo(tmp_path / "moved", files, framework=toml(extra='[docs]\nhandoff_people_dir = "Docs/people"\n'))
    assert mine(moved) == []


def _scaling(build) -> tuple[float, float]:
    """Seconds to read ``build(n)`` for n and 4n, each the best of two runs, through the check alone."""
    import time

    def seconds(n: int) -> float:
        files = base_files()
        files["Docs/README.md"] += build(n) + "\n"
        ctx = cd.load_context(write_repo(Path(tempfile.mkdtemp()), files))
        best = float("inf")
        for _ in range(2):
            started = time.perf_counter()
            cd.check_status_copy(ctx)
            best = min(best, time.perf_counter() - started)
        return best

    return seconds(1000), seconds(4000)


@pytest.mark.parametrize(
    "build",
    [
        lambda n: "](" * n,
        lambda n: "](" + " " * (10 * n) + "x",
        lambda n: "(Proposed): [" * n,
        lambda n: "(Proposed " * n,
        lambda n: "[x](standards/one.md) " * n,
        lambda n: "| [x](standards/one.md) |" + " Proposed |" * n,
        lambda n: "| [x](standards/one.md) | Proposed" + " " * (10 * n) + "x |",
        lambda n: "| [x](standards/one.md) | " + "*_ " * (5 * n) + "Proposed" + "*_ " * (5 * n) + "x |",
        lambda n: "[" * n + "a",
        lambda n: "[a" * n,
    ],
    ids=[
        "destinations",
        "spaces-in-a-destination",
        "status-before-brackets",
        "open-statuses",
        "many-links",
        "table-cells",
        "a-padded-status-cell",
        "a-status-cell-padded-with-markup",
        "opening-brackets",
        "unclosed-link-texts",
    ],
)
def test_the_cost_of_a_line_grows_with_its_length_not_with_its_square(build) -> None:
    small, large = _scaling(build)  # four times the input: about four times the time, not sixteen
    assert large < 8 * small + 0.05, f"{small:.3f}s for 1,000, {large:.3f}s for 4,000"


def test_a_copy_beside_each_of_several_links_is_a_finding_for_each(tmp_path: Path) -> None:
    line = "[a](standards/one.md) (Proposed) and [b](standards/two.md) (Draft) and [c](standards/two.md) (Living)"
    assert len(_copies(tmp_path, _with_line(line, extra=TWO))) == 2


@pytest.mark.parametrize(
    "line",
    [
        r"\[the spec](standards/one.md) (Proposed)",
        "the spec](standards/one.md) (Proposed)",
        r"(Proposed): \[the spec](standards/one.md)",
        r"| \[a](standards/one.md) | Proposed |",
        "| a](standards/one.md) | Proposed |",
        r"\[the spec\](standards/one.md) (Proposed)",
    ],
)
def test_text_that_is_not_a_link_has_no_status_to_copy(tmp_path: Path, line: str) -> None:
    """An escaped or missing opening bracket makes the text literal, as ``link_targets`` reads it."""
    assert _copies(tmp_path, _with_line(line)) == []


def test_a_link_text_with_brackets_inside_it_is_still_a_link(tmp_path: Path) -> None:
    assert len(_copies(tmp_path, _with_line("[the [spec] text](standards/one.md) (Proposed)"))) == 1
    assert (
        len(_copies(tmp_path, _with_line(r"[the [spec] text](standards/one.md) (Proposed) and \[x](two.md) (Draft)")))
        == 1
    )


# --------------------------------------------------------------------------- the handoff split: per-login handoffs
PEOPLE = "Docs/handoffs/people"


def _person(day: str = TODAY, body: str = "Mine.\n", status: bool = True) -> str:
    head = "# Ada's handoff\n\n" + ("**Status:** Living.\n" if status else "") + f"**Last updated:** {day}: x.\n\n"
    return head + body


def _with_ada(files: dict[str, str], day: str = TODAY, status: bool = True) -> None:
    """Ada's per-login handoff and a new-form journal file of hers dated TODAY."""
    files[f"{PEOPLE}/ada.md"] = _person(day, status=status)
    files[AUTHORED] = GOOD_SESSION


def test_a_per_login_handoff_with_its_logins_journal_file_passes_with_and_without_a_roster(tmp_path: Path) -> None:
    files = base_files()
    _with_ada(files)
    assert findings_of(write_repo(tmp_path, files)) == []
    assert findings_of(write_repo(tmp_path, files, framework=toml(extra=ROSTER))) == []


def test_a_per_login_handoff_for_a_login_off_the_roster_is_a_finding(tmp_path: Path) -> None:
    files = base_files()
    files[f"{PEOPLE}/zed.md"] = _person()
    files["Docs/journal/2026-10/2026-10-11-zed-0900.md"] = GOOD_SESSION.replace("@ada", "@zed")
    found = findings_of(write_repo(tmp_path, files, framework=toml(extra=ROSTER)))
    assert [f.check for f in found if f.check == "handoff"] == ["handoff"]
    assert "zed" in next(f.detail for f in found if f.check == "handoff") and "roster" in str(found)
    assert {f.check for f in found} <= {"handoff", "journal-author"}  # zed's journal file is journal-author's


def test_a_readme_under_people_is_read_as_the_login_readme_which_the_roster_then_refuses(tmp_path: Path) -> None:
    """``readme`` is a login GitHub permits, so the file is its handoff: off the roster, and with no journal file."""
    files = base_files()
    files[f"{PEOPLE}/README.md"] = _person()
    found = findings_of(write_repo(tmp_path, files, framework=toml(extra=ROSTER)))
    assert {f.check for f in found} == {"handoff", "journal-day"}, [str(f) for f in found]
    assert "roster" in next(f.detail for f in found if f.check == "handoff")


@pytest.mark.parametrize("name", ["notes and more.md", "-dash.md", "two--hyphens.md", "a.b.md", "a" * 40 + ".md"])
def test_a_file_under_people_that_is_not_named_for_a_login_is_a_finding(tmp_path: Path, name: str) -> None:
    found = broken(tmp_path, "handoff", lambda f: f.__setitem__(f"{PEOPLE}/{name}", _person()))
    assert len(found) == 1 and "login" in found[0].detail and found[0].location == f"{PEOPLE}/{name}"


@pytest.mark.parametrize("stem", ["con", "CON", "prn", "aux", "nul", "com1", "lpt9"])
def test_a_per_login_handoff_whose_name_windows_reserves_is_a_finding(tmp_path: Path, stem: str) -> None:
    """On a hand-built corpus, not on disk: Windows may refuse or misread a file named for a device, which is the
    very reason for the rule (the disk version of this test did pass on Windows 11 and on both CI runners)."""
    files = {**base_files(), f"{PEOPLE}/{stem}.md": _person()}
    ctx = cd.Context(tmp_path, fc.DocsConfig(), 150, {"core": "on", "journal": "on"}, tuple(sorted(files)), files)
    found = [f for f in cd.check_handoff(ctx) if f.location == f"{PEOPLE}/{stem}.md"]
    assert len(found) == 1 and "Windows" in found[0].detail, [str(f) for f in found]


def test_a_file_under_people_that_is_not_markdown_is_still_a_finding(tmp_path: Path) -> None:
    """The corpus is markdown, so the directory itself is listed: ``ada.txt`` or ``ada.MD`` is not ``<login>.md``."""
    files = base_files()
    _with_ada(files)
    root = write_repo(tmp_path, files)
    (root / PEOPLE / "ada.txt").write_text("not a handoff\n", encoding="utf-8")
    found = findings_of(root)
    assert [f.check for f in found] == ["handoff"] and found[0].location == f"{PEOPLE}/ada.txt", [str(f) for f in found]


def test_a_per_login_handoff_is_checked_even_when_the_shared_handoff_has_no_usable_date(tmp_path: Path) -> None:
    files = base_files()
    files["Docs/handoffs/CURRENT.md"] = "# Handoff\n\n**Status:** Living.\n\nNo date line.\n"
    files[f"{PEOPLE}/ada.md"] = _person()  # dated, and ada has no journal file
    found = findings_of(write_repo(tmp_path, files))
    assert {(f.check, f.location) for f in found} == {
        ("handoff", "Docs/handoffs/CURRENT.md"),
        ("journal-day", f"{PEOPLE}/ada.md"),
    }, [str(f) for f in found]


def test_a_per_login_handoff_dated_after_its_logins_newest_file_is_a_finding_whoever_else_wrote(
    tmp_path: Path,
) -> None:
    def later(f: dict[str, str]) -> None:
        _with_ada(f, "2026-10-12")
        f["Docs/journal/2026-10/2026-10-12-Bo-B-0900.md"] = GOOD_SESSION.replace("@ada", "@Bo-B")  # someone else, newer

    found = broken(tmp_path, "journal-day", later)
    assert len(found) == 1 and found[0].location == f"{PEOPLE}/ada.md"
    assert "@ada" in found[0].detail and "2026-10-11" in found[0].detail


@pytest.mark.parametrize(("file_login", "journal_login"), [("bo-b", "BO-B"), ("Bo-B", "bo-b"), ("BO-B", "Bo-B")])
def test_a_per_login_handoff_and_its_logins_files_compare_ignoring_case_as_the_roster_does(
    tmp_path: Path, file_login: str, journal_login: str
) -> None:
    files = base_files()
    files[f"{PEOPLE}/{file_login}.md"] = _person()  # the roster says Bo-B
    files[f"Docs/journal/2026-10/2026-10-11-{journal_login}-0900.md"] = GOOD_SESSION.replace("@ada", "@Bo-B")
    assert findings_of(write_repo(tmp_path, files, framework=toml(extra=ROSTER))) == []


def test_a_journal_file_named_for_an_unreal_day_does_not_satisfy_a_per_login_handoff(tmp_path: Path) -> None:
    """``2026-13-01`` sorts above every real day; it is journal-index's finding and must not quietly pass the date."""

    def unreal(f: dict[str, str]) -> None:
        _with_ada(f, "2026-10-12")
        f["Docs/journal/2026-13/2026-13-01-ada-0900.md"] = GOOD_SESSION

    found = broken(tmp_path, "journal-day", unreal, also=("journal-index",))
    assert len(found) == 1 and found[0].location == f"{PEOPLE}/ada.md" and "2026-10-11" in found[0].detail


def test_a_per_login_handoff_whose_login_has_no_journal_file_is_a_finding_even_on_a_first_session(
    tmp_path: Path,
) -> None:
    def alone(f: dict[str, str]) -> None:
        f[f"{PEOPLE}/ada.md"] = _person()

    found = broken(tmp_path, "journal-day", alone)
    assert len(found) == 1 and "@ada" in found[0].detail and "no new-form journal file" in found[0].detail


def test_a_per_login_handoff_is_held_to_the_date_line_and_the_limit_like_the_shared_one(tmp_path: Path) -> None:
    def broken_both(f: dict[str, str]) -> None:
        f[f"{PEOPLE}/ada.md"] = "# Ada\n\n**Status:** Living.\n\n" + "line\n" * 200
        f[AUTHORED] = GOOD_SESSION

    found = broken(tmp_path, "handoff", broken_both)
    details = " ".join(f.detail for f in found)
    assert len(found) == 2 and "Last updated" in details and "limit" in details


def test_a_per_login_handoff_needs_no_incoming_link_but_does_need_a_status(tmp_path: Path) -> None:
    files = base_files()
    _with_ada(files)
    assert findings_of(write_repo(tmp_path, files)) == []  # nothing links it: not an orphan
    found = broken(tmp_path, "status", lambda f: _with_ada(f, status=False))
    assert [f.location for f in found] == [f"{PEOPLE}/ada.md"]


def test_the_people_directory_is_the_configured_one(tmp_path: Path) -> None:
    files = base_files()
    files["Docs/people/ada.md"] = _person()
    files[AUTHORED] = GOOD_SESSION
    files[f"{PEOPLE}/zed.md"] = _person()  # the default place is now an ordinary governed folder: linked, so no orphan
    files["Docs/README.md"] += "[zed](handoffs/people/zed.md)\n"
    extra = ROSTER + '\n[docs]\nhandoff_people_dir = "Docs/people"\n'
    assert findings_of(write_repo(tmp_path, files, framework=toml(extra=extra))) == []


# --------------------------------------------------------------------------- the board as a directory of row files
BOARD_DIR = "Docs/plan/board"


def _row(
    section: str, title: str = "A row", owner: str = "@ada", state: str = "Open", extra: str = "", body: str = ""
) -> str:
    return f"# {title}\n\n**Section:** {section}\n**Owner:** {owner}\n**State:** {state}\n{extra}\n{body}"


ICEBOX_LINES = "**Cost:** 2 d\n**Verdict:** Good\n**Raised:** [said](../../README.md)\n"


def directory_board() -> dict[str, str]:
    """The base corpus with the board in directory form: one row per section, no hand-kept page."""
    files = base_files()
    del files["Docs/plan/BOARD.md"]
    files[f"{BOARD_DIR}/2026-10-01-first-gate.md"] = _row("gate", "G1", "none", "Open", "**Decider:** @ada\n")
    files[f"{BOARD_DIR}/2026-10-02-build-it.md"] = _row("now", "Build it", "@ada", "Started")
    files[f"{BOARD_DIR}/2026-10-03-then-this.md"] = _row("next", "Then this", "@Bo-B", "Queued")
    files[f"{BOARD_DIR}/2026-10-04-stuck.md"] = _row("blocked", "Stuck", "@ada", "Waiting on G1")
    files[f"{BOARD_DIR}/2026-10-05-an-idea.md"] = _row("icebox", "An idea", "none", "Iceboxed", ICEBOX_LINES)
    files[f"{BOARD_DIR}/2026-09-30-done-thing.md"] = _row("now", "Done thing", "@ada", "Landed 2026-10-01 as #12")
    return files


def broken_dir(tmp: Path, expected: str, mutate, *, also: tuple[str, ...] = ()) -> list[cd.Finding]:
    """``broken`` for the directory form: the corpus starts from ``directory_board()``, with no hand-kept page."""
    files = directory_board()
    mutate(files)
    found = findings_of(write_repo(tmp, files))
    assert found, f"no finding at all; the {expected} check did not fire"
    assert {f.check for f in found} == {expected, *also}, [str(f) for f in found]
    return [f for f in found if f.check == expected]


def test_a_board_in_directory_form_passes_with_the_page_absent(tmp_path: Path) -> None:
    assert findings_of(write_repo(tmp_path, directory_board())) == []


def test_a_board_in_directory_form_passes_with_a_roster_naming_its_logins(tmp_path: Path) -> None:
    files = directory_board()
    files[AUTHORED] = GOOD_SESSION  # the handoff's day needs a session file either way
    assert findings_of(write_repo(tmp_path, files, framework=toml(extra=ROSTER))) == []


def test_a_rendered_page_is_skipped_and_a_hand_kept_page_beside_row_files_is_two_trackers(tmp_path: Path) -> None:
    files = directory_board()
    files["Docs/plan/BOARD.md"] = cd.BOARD_HEADER + "\n\n# The board\n\nAnything, even a broken [link](nowhere.md).\n"
    assert findings_of(write_repo(tmp_path, files)) == []
    found = broken_dir(
        tmp_path, "board", lambda f: f.update(directory_board()) or f.__setitem__("Docs/plan/BOARD.md", _doc())
    )
    assert len(found) == 1 and "two trackers" in found[0].detail and found[0].location == "Docs/plan/BOARD.md"


def test_a_link_to_the_board_page_resolves_in_directory_form_whether_or_not_it_is_rendered(tmp_path: Path) -> None:
    files = directory_board()
    files["Docs/notes.md"] = _doc(
        body="See [the board](plan/BOARD.md) and [a row](plan/board/2026-10-02-build-it.md).\n"
    )
    files["Docs/README.md"] += "[notes](notes.md)\n"
    assert findings_of(write_repo(tmp_path, files)) == []
    files["Docs/notes.md"] = _doc(body="See [the board](plan/board.md).\n")  # another spelling is still a broken link
    assert [f.check for f in findings_of(write_repo(tmp_path, files))] == ["links"]


def test_a_hand_kept_board_is_checked_as_before_and_board_sections_applies_to_it_only(tmp_path: Path) -> None:
    assert findings_of(write_repo(tmp_path / "hand", base_files())) == []  # the base corpus is the hand-kept form
    files = directory_board()
    root = write_repo(tmp_path / "rows", files, framework=toml(extra='[docs]\nboard_sections = ["## Gates"]\n'))
    assert findings_of(root) == []  # the sections rule is not applied to row files


@pytest.mark.parametrize(
    ("name", "why"),
    [
        ("notes.md", "not a row file"),
        ("2026-10-07-Build-It.md", "slug"),  # a day no row uses: on a case-insensitive disk it would be one file
        ("2026-10-02-build--it.md", "slug"),
        ("2026-13-02-build-it.md", "day"),
        ("2026-10-02-" + "a" * 61 + ".md", "slug"),
        ("build-it.md", "not a row file"),
    ],
)
def test_a_file_in_the_board_directory_that_is_not_a_row_file_is_a_finding(tmp_path: Path, name: str, why: str) -> None:
    def stray(f: dict[str, str]) -> None:
        f.update(directory_board())
        f[f"{BOARD_DIR}/{name}"] = _row("now")

    found = broken_dir(tmp_path, "board", stray)
    assert len(found) == 1 and found[0].location == f"{BOARD_DIR}/{name}" and why in found[0].detail


@pytest.mark.parametrize("name", ["2026-10-29-extra.md", "README.md", "old"])
def test_a_folder_in_the_board_directory_is_a_finding_whatever_its_name(tmp_path: Path, name: str) -> None:
    """A folder named like a row is not in the corpus, so without this rule it passed in silence and `make board`
    then failed trying to read it as a row."""
    root = write_repo(tmp_path, directory_board())
    (root / BOARD_DIR / name).mkdir()
    found = findings_of(root)
    assert [(f.check, f.location) for f in found] == [("board", f"{BOARD_DIR}/{name}")], [str(f) for f in found]
    assert "folder" in found[0].detail


def test_a_readme_in_the_board_directory_is_allowed(tmp_path: Path) -> None:
    files = directory_board()
    files[f"{BOARD_DIR}/README.md"] = _doc(body="How the rows work.\n")
    files["Docs/README.md"] += "[rows](plan/board/README.md)\n"
    assert findings_of(write_repo(tmp_path, files)) == []


def test_a_non_markdown_file_in_the_board_directory_is_a_finding(tmp_path: Path) -> None:
    root = write_repo(tmp_path, directory_board())
    (root / BOARD_DIR / "rows.csv").write_text("a,b\n", encoding="utf-8")
    found = findings_of(root)
    assert [(f.check, f.location) for f in found] == [("board", f"{BOARD_DIR}/rows.csv")]


@pytest.mark.parametrize(
    ("section", "text", "word"),
    [
        ("now", "# T\n\n**Owner:** @ada\n**State:** Open\n", "Section"),
        ("now", "# T\n\n**Section:** now\n**State:** Open\n", "Owner"),
        ("now", "# T\n\n**Section:** now\n**Owner:** @ada\n", "State"),
        ("now", "# T\n\n**Section:** done\n**Owner:** @ada\n**State:** Open\n", "Section"),
        ("now", "# T\n\n**Section:** now\n**Owner:** none\n**State:** Open\n", "Owner"),
        ("now", "# T\n\n**Section:** now\n**Owner:** @ada\n**State:** Open\n**Decider:** @ada\n", "Decider"),
        (
            "now",
            "# T\n\n**Section:** now\n**Owner:** @ada\n**State:** Open\n**Waits on:** [B](2026-10-02-build-it.md)\n",
            "Waits on",
        ),
        ("now", "# T\n\n**Section:** now\n**Owner:** @ada\n**State:** Open\n**Costs:** 2 d\n", "Costs"),
        ("now", "# T\n\n**Section:** now\n**Owner:** @ada\n**State:** Open\n**State:** Twice\n", "twice"),
        ("now", "**Section:** now\n**Owner:** @ada\n**State:** Open\n", "title"),
        ("gate", "# T\n\n**Section:** gate\n**Owner:** none\n**State:** Open\n**Cost:** 2 d\n", "Cost"),
        ("gate", "# T\n\n**Section:** gate\n**Owner:** none\n**State:** Open\n**Decider:** none\n", "Decider"),
        (
            "icebox",
            "# T\n\n**Section:** icebox\n**Owner:** none\n**State:** Iceboxed\n**Verdict:** Good\n"
            "**Raised:** [x](../../README.md)\n",
            "Cost",
        ),
        (
            "icebox",
            "# T\n\n**Section:** icebox\n**Owner:** none\n**State:** Iceboxed\n**Cost:** 2 d\n"
            "**Raised:** [x](../../README.md)\n",
            "Verdict",
        ),
        (
            "icebox",
            "# T\n\n**Section:** icebox\n**Owner:** none\n**State:** Iceboxed\n**Cost:** 2 d\n**Verdict:** Good\n",
            "Raised",
        ),
        (
            "icebox",
            "# T\n\n**Section:** icebox\n**Owner:** @me\n**State:** Iceboxed\n**Cost:** 2 d\n**Verdict:** Good\n"
            "**Raised:** [x](../../README.md)\n**Owner:** none\n",
            "twice",
        ),
    ],
)
def test_a_row_file_missing_a_required_line_or_carrying_a_wrong_one_is_a_finding(
    tmp_path: Path, section: str, text: str, word: str
) -> None:
    def bad(f: dict[str, str]) -> None:
        f.update(directory_board())
        f[f"{BOARD_DIR}/2026-10-09-bad-row.md"] = text

    found = broken_dir(tmp_path, "board", bad)
    assert len(found) == 1 and word in found[0].detail and found[0].location == f"{BOARD_DIR}/2026-10-09-bad-row.md"


@pytest.mark.parametrize(
    "cost",
    [
        "2 d",
        "½ d",
        "0.5 d",
        "1 to 2 d",
        "2 to 4 d, in parts: a step (0.5 d)",
        "3 to 5 d (a design lock first)",
        "4.5 d: month folders 0.5 d",
        "1 w",
        "3 h",
        "2 days",
        "1 to 2 weeks",
    ],
)
def test_every_cost_form_on_the_board_today_parses(tmp_path: Path, cost: str) -> None:
    files = directory_board()
    files[f"{BOARD_DIR}/2026-10-05-an-idea.md"] = _row(
        "icebox",
        "An idea",
        "none",
        "Iceboxed",
        f"**Cost:** {cost}\n**Verdict:** Good\n**Raised:** [x](../../README.md)\n",
    )
    assert findings_of(write_repo(tmp_path, files)) == []


def _icebox_row(state: str = "Iceboxed", cost: str | None = "2 d") -> str:
    cost_line = "" if cost is None else f"**Cost:** {cost}\n"
    return _row("icebox", "An idea", "none", state, f"{cost_line}**Verdict:** Good\n**Raised:** [x](../../README.md)\n")


@pytest.mark.parametrize("cost", ["unsized: a design first", "unsized: after the command bus (HogShade, 2026-11-03)"])
def test_unsized_with_its_reason_is_a_cost(tmp_path: Path, cost: str) -> None:
    files = directory_board()
    files[f"{BOARD_DIR}/2026-10-05-an-idea.md"] = _icebox_row(cost=cost)
    assert findings_of(write_repo(tmp_path, files)) == []


@pytest.mark.parametrize("cost", ["unsized", "unsized:", "unsized:   ", "Unsized: no", "unsized - later"])
def test_unsized_without_a_reason_or_in_another_form_is_a_finding(tmp_path: Path, cost: str) -> None:
    def bad(f: dict[str, str]) -> None:
        f.update(directory_board())
        f[f"{BOARD_DIR}/2026-10-05-an-idea.md"] = _icebox_row(cost=cost)

    found = broken_dir(tmp_path, "board", bad)
    assert len(found) == 1 and "unsized: <reason>" in found[0].detail


@pytest.mark.parametrize("state", ["Closed: the idea went into another row", "Dropped 2026-11-01: not needed"])
def test_a_done_icebox_row_needs_no_cost(tmp_path: Path, state: str) -> None:
    files = directory_board()
    files[f"{BOARD_DIR}/2026-10-05-an-idea.md"] = _icebox_row(state, cost=None)
    assert findings_of(write_repo(tmp_path, files)) == []


def test_an_open_icebox_row_without_a_cost_is_still_a_finding(tmp_path: Path) -> None:
    def bad(f: dict[str, str]) -> None:
        f.update(directory_board())
        f[f"{BOARD_DIR}/2026-10-05-an-idea.md"] = _icebox_row(cost=None)

    found = broken_dir(tmp_path, "board", bad)
    assert len(found) == 1 and "no `**Cost:**` line" in found[0].detail


def test_a_done_icebox_row_with_a_bad_cost_is_still_a_finding(tmp_path: Path) -> None:
    """A done row may leave its cost out; one it keeps is still read, so a malformed one is not hidden."""

    def bad(f: dict[str, str]) -> None:
        f.update(directory_board())
        f[f"{BOARD_DIR}/2026-10-05-an-idea.md"] = _icebox_row("Closed: elsewhere", cost="soon")

    found = broken_dir(tmp_path, "board", bad)
    assert len(found) == 1 and "Cost" in found[0].detail


@pytest.mark.parametrize("cost", ["soon", "2", "d 2", "two days", "2 d3", ""])
def test_a_cost_without_a_number_and_a_unit_is_a_finding(tmp_path: Path, cost: str) -> None:
    def bad(f: dict[str, str]) -> None:
        f.update(directory_board())
        f[f"{BOARD_DIR}/2026-10-05-an-idea.md"] = _row(
            "icebox",
            "An idea",
            "none",
            "Iceboxed",
            f"**Cost:** {cost}\n**Verdict:** Good\n**Raised:** [x](../../README.md)\n",
        )

    found = broken_dir(tmp_path, "board", bad)
    assert len(found) == 1 and "Cost" in found[0].detail


@pytest.mark.parametrize(
    ("raised", "ok"),
    [
        ("[said](../../README.md)", True),
        ("unrecorded (converted 2026-10-29)", True),
        ("unrecorded", False),
        ("unrecorded (converted 2026-13-01)", False),
        ("the owner said so", False),
    ],
)
def test_raised_is_a_link_or_the_unrecorded_form_with_a_real_day(tmp_path: Path, raised: str, ok: bool) -> None:
    files = directory_board()
    files[f"{BOARD_DIR}/2026-10-05-an-idea.md"] = _row(
        "icebox", "An idea", "none", "Iceboxed", f"**Cost:** 2 d\n**Verdict:** Good\n**Raised:** {raised}\n"
    )
    found = findings_of(write_repo(tmp_path, files))
    assert ([(f.check, "Raised" in f.detail) for f in found] == []) is ok, [str(f) for f in found]


@pytest.mark.parametrize(
    ("state", "finding"),
    [
        ("Landed 2026-10-01 as #12", False),
        ("landed as https://github.com/o/r/pull/12", False),
        ("Landed on branch feat/x", True),
        ("Landed; no pull request: merged by hand on the forge", False),
        ("Closed 2026-10-01 by the owner", False),
        ("Dropped: superseded", False),
    ],
)
def test_a_landed_row_file_names_its_pull_request(tmp_path: Path, state: str, finding: bool) -> None:
    files = directory_board()
    files[f"{BOARD_DIR}/2026-09-30-done-thing.md"] = _row("now", "Done thing", "@ada", state)
    found = findings_of(write_repo(tmp_path, files))
    assert ([f.check for f in found] == ["landed-rows"]) is finding, [str(f) for f in found]


# --------------------------------------------------------------------------- board rows stay true
BAD_ROW = f"{BOARD_DIR}/2026-10-09-bad-row.md"


def _with_row(tmp: Path, section: str, state: str, extra: str = "") -> list[cd.Finding]:
    """The directory board with one more row; its findings."""
    files = directory_board()
    owner = "none" if section in ("gate", "icebox") else "@ada"
    lines = (ICEBOX_LINES if section == "icebox" else "") + extra
    files[BAD_ROW] = _row(section, "The row", owner, state, lines)
    return findings_of(write_repo(tmp, files))


@pytest.mark.parametrize("section", ["now", "next", "blocked"])
def test_a_moved_row_may_keep_its_verdict(tmp_path: Path, section: str) -> None:
    state = "Queued" if section == "next" else "Started"
    assert _with_row(tmp_path, section, state, "**Verdict:** Good\n") == []


@pytest.mark.parametrize("section", ["next", "blocked", "icebox"])
def test_a_waits_on_line_linking_an_open_row_is_allowed(tmp_path: Path, section: str) -> None:
    state = {"next": "Queued", "blocked": "Waiting", "icebox": "Iceboxed"}[section]
    assert _with_row(tmp_path, section, state, "**Waits on:** [Build it](2026-10-02-build-it.md)\n") == []


@pytest.mark.parametrize(("section", "state"), [("now", "Started"), ("gate", "Open")])
def test_a_waits_on_line_is_refused_on_now_and_on_a_gate(tmp_path: Path, section: str, state: str) -> None:
    found = _with_row(tmp_path, section, state, "**Waits on:** [Build it](2026-10-02-build-it.md)\n")
    assert [(f.check, f.location) for f in found] == [("board", BAD_ROW)], [str(f) for f in found]
    assert "Waits on" in found[0].detail


@pytest.mark.parametrize(
    ("section", "state", "words"),
    [
        ("next", "Landed 2026-10-30 as #74", "belongs in now"),
        ("blocked", "landed as #3", "belongs in now"),  # the word is matched whatever its case
        ("icebox", "Landed 2026-10-01 as #12", "belongs in now"),
        ("now", "Queued", "belongs in next"),
        ("icebox", "Pulled forward: see the Now row", "move this row"),
    ],
)
def test_a_row_whose_section_contradicts_its_state_is_a_finding(
    tmp_path: Path, section: str, state: str, words: str
) -> None:
    found = _with_row(tmp_path, section, state)
    assert [(f.check, f.location) for f in found] == [("board-state", BAD_ROW)], [str(f) for f in found]
    assert words in found[0].detail


@pytest.mark.parametrize(
    ("section", "state"),
    [
        ("now", "Landed 2026-10-01 as #12"),
        ("gate", "Closed 2026-10-01 by the owner"),
        ("next", "Dropped: superseded"),
        ("icebox", "Dropped: superseded"),
        ("icebox", "Iceboxed"),
        ("next", "Queued"),
        ("now", "Pulled forward by the owner 2026-11-03; building"),  # moved, so its state may say so
        ("gate", "Landed on a decision"),  # a gate closes in place, by a person's decision
        ("next", "Started; landed in part as #74"),  # only the first word is the state's kind
    ],
)
def test_a_row_whose_section_agrees_with_its_state_is_not(tmp_path: Path, section: str, state: str) -> None:
    assert _with_row(tmp_path, section, state) == []


@pytest.mark.parametrize(
    "state",
    [
        "Pulled forward 2026-11-05; the design locked by #114; Landed 2026-11-05 as #116",  # #117's row, as written
        "Started. Closed 2026-11-01 by the owner",
        "Started, Dropped: superseded",
        "Building: Landed in part as #74",
    ],
)
def test_a_done_word_that_opens_a_later_clause_of_the_state_is_a_finding(tmp_path: Path, state: str) -> None:
    """A row is done only when its state starts with the word: later on, the row still reads as open."""
    found = _with_row(tmp_path, "now", state)
    assert [(f.check, f.location) for f in found] == [("board-state", BAD_ROW)], [str(f) for f in found]
    assert "starts with" in found[0].detail


@pytest.mark.parametrize(
    "state",
    [
        "Started; landed in part as #74",  # lower case: prose, not a state word
        "Second in the sequence, after the row id, which landed",
        "Landed 2026-11-05 as #116; Pulled forward earlier",  # done already: the first word decides
        "Started; the Landed rows are read by waits-on",  # capitalised, but not opening a clause
    ],
)
def test_a_done_word_in_prose_or_after_a_done_state_is_not_a_finding(tmp_path: Path, state: str) -> None:
    assert _with_row(tmp_path, "now", state) == []


@pytest.mark.parametrize(
    ("section", "state", "extra"),
    [
        ("done", "Landed as #3", ""),  # an unknown section: the board check's, not board-state's
        ("now", "Started", "**Waits on:** [Done thing](2026-09-30-done-thing.md)\n"),  # refused on now: not read
    ],
)
def test_a_row_the_board_check_refuses_gets_that_finding_alone(
    tmp_path: Path, section: str, state: str, extra: str
) -> None:
    found = _with_row(tmp_path, section, state, extra)
    assert [(f.check, f.location) for f in found] == [("board", BAD_ROW)], [str(f) for f in found]


def _waiting(tmp: Path, line: str, also: dict[str, str] | None = None) -> list[cd.Finding]:
    files = directory_board()
    files.update(also or {})
    files[BAD_ROW] = _row("icebox", "The row", "none", "Iceboxed", ICEBOX_LINES + line)
    return findings_of(write_repo(tmp, files))


@pytest.mark.parametrize(
    "line",
    [
        "**Waits on:** [Build it](2026-10-02-build-it.md)\n",
        "**Waits on:** [Build it](2026-10-02-build-it.md), [Then this](2026-10-03-then-this.md)\n",
        "**Waits on:** [Build it](./2026-10-02-build-it.md)\n",
        # the link forms the links check reads: an angle destination, a title, a fragment, percent-encoding
        "**Waits on:** [Build it](<2026-10-02-build-it.md>)\n",
        '**Waits on:** [Build it](2026-10-02-build-it.md "the build")\n',
        "**Waits on:** [Build it](2026-10-02-build-it.md#part)\n",
        "**Waits on:** [Build it](2026-10-02-build%2Dit.md)\n",
    ],
)
def test_a_wait_on_open_rows_is_not_a_finding(tmp_path: Path, line: str) -> None:
    assert _waiting(tmp_path, line) == []


@pytest.mark.parametrize(
    ("line", "words"),
    [
        ("**Waits on:** [Done thing](2026-09-30-done-thing.md)\n", "which is done"),
        ("**Waits on:** [Build it](2026-10-02-build-it.md), [Done thing](2026-09-30-done-thing.md)\n", "which is done"),
        ("**Waits on:** [Gone](2026-10-08-gone.md)\n", "nothing the board has"),
        ("**Waits on:** [The README](../../README.md)\n", "nothing the board has"),
        ("**Waits on:** increment 2\n", "nothing the board has"),
        ("**Waits on:** [Done thing](<2026-09-30-done-thing.md>)\n", "which is done"),
        ("**Waits on:** [A pull request](https://github.com/example/proj/pull/1)\n", "a URL is not a row"),
    ],
)
def test_a_wait_on_done_work_or_on_nothing_is_a_finding(tmp_path: Path, line: str, words: str) -> None:
    found = [f for f in _waiting(tmp_path, line) if f.check != "links"]  # a link to no file is a broken link as well
    assert [(f.check, f.location) for f in found] == [("waits-on", BAD_ROW)], [str(f) for f in found]
    assert words in found[0].detail


def _waiting_with_body(tmp: Path, line: str, body: str) -> list[cd.Finding]:
    """A waiting row whose prose carries reference definitions."""
    files = directory_board()
    files[BAD_ROW] = _row("icebox", "The row", "none", "Iceboxed", ICEBOX_LINES + line) + body
    return findings_of(write_repo(tmp, files))


DEFS = "\n[build]: 2026-10-02-build-it.md\n[Done Thing]: 2026-09-30-done-thing.md\n[gone]: 2026-10-08-gone.md\n"


@pytest.mark.parametrize(
    "line",
    [
        "**Waits on:** [Build it][build]\n",  # a full reference
        "**Waits on:** [build][]\n",  # a collapsed reference
        "**Waits on:** [Build it][BUILD]\n",  # a label matches whatever its case
    ],
)
def test_a_reference_style_wait_on_an_open_row_is_not_a_finding(tmp_path: Path, line: str) -> None:
    found = [f for f in _waiting_with_body(tmp_path, line, DEFS) if f.check != "links"]  # [gone] is a broken link
    assert found == [], [str(f) for f in found]


@pytest.mark.parametrize(
    ("line", "words"),
    [
        ("**Waits on:** [Build it](2026-10-02-build-it.md), [Done][done thing]\n", "which is done"),  # mixed forms
        ("**Waits on:** [Done][Done  thing]\n", "which is done"),  # whitespace in a label is collapsed
        ("**Waits on:** [Gone][gone]\n", "nothing the board has"),
        ("**Waits on:** [Nowhere][undefined]\n", "nothing the board has"),  # a label with no definition
    ],
)
def test_a_reference_style_wait_on_done_work_or_on_nothing_is_a_finding(tmp_path: Path, line: str, words: str) -> None:
    found = [f for f in _waiting_with_body(tmp_path, line, DEFS) if f.check != "links"]
    assert [(f.check, f.location) for f in found] == [("waits-on", BAD_ROW)], [str(f) for f in found]
    assert words in found[0].detail


@pytest.mark.parametrize("state", ["Closed 2026-10-01 by the owner", "Dropped: superseded"])
def test_a_wait_on_a_closed_or_dropped_row_is_a_wait_on_done_work(tmp_path: Path, state: str) -> None:
    also = {f"{BOARD_DIR}/2026-10-08-other.md": _row("next", "Other", "@ada", state)}
    found = _waiting(tmp_path, "**Waits on:** [Other](2026-10-08-other.md)\n", also)
    assert [f.check for f in found] == ["waits-on"] and "Other" in found[0].detail, [str(f) for f in found]


def test_an_empty_state_line_is_a_finding(tmp_path: Path) -> None:
    def empty(f: dict[str, str]) -> None:
        f[f"{BOARD_DIR}/2026-10-02-build-it.md"] = "# Build it\n\n**Section:** now\n**Owner:** @ada\n**State:**\n"

    found = broken_dir(tmp_path, "board", empty)
    assert len(found) == 1 and "State` is empty" in found[0].detail


def test_a_board_page_that_cannot_be_read_beside_rows_says_so_rather_than_calling_it_hand_kept(tmp_path: Path) -> None:
    root = write_repo(tmp_path, directory_board())
    (root / "Docs/plan/BOARD.md").write_bytes(b"\xff\xfe not utf-8")
    found = findings_of(root)
    assert [(f.check, f.location) for f in found] == [("board", "Docs/plan/BOARD.md")], [str(f) for f in found]
    assert "could not be read" in found[0].detail and "hand-kept" not in found[0].detail


def test_cost_raised_and_was_owned_by_are_allowed_on_a_now_row(tmp_path: Path) -> None:
    files = directory_board()
    files[f"{BOARD_DIR}/2026-10-02-build-it.md"] = _row(
        "now",
        "Build it",
        "@ada",
        "Started",
        "**Cost:** 1 to 2 d\n**Raised:** [x](../../README.md)\n**Was owned by:** @Bo-B\n",
    )
    files[AUTHORED] = GOOD_SESSION
    assert findings_of(write_repo(tmp_path, files, framework=toml(extra=ROSTER))) == []


def test_a_gate_row_that_closed_is_never_asked_for_a_pull_request(tmp_path: Path) -> None:
    files = directory_board()
    files[f"{BOARD_DIR}/2026-10-01-first-gate.md"] = _row(
        "gate", "G1", "none", "Landed on a decision", "**Decider:** @ada\n"
    )
    assert findings_of(write_repo(tmp_path, files)) == []


@pytest.mark.parametrize("line", ["**Owner:** @zed", "**Decider:** @zed", "**Was owned by:** @ada, @zed"])
def test_a_login_on_a_row_must_be_on_the_roster_when_there_is_one(tmp_path: Path, line: str) -> None:
    files = directory_board()
    files[AUTHORED] = GOOD_SESSION
    section = "gate" if "Decider" in line else "now"
    if line.startswith("**Owner"):
        files[f"{BOARD_DIR}/2026-10-02-build-it.md"] = _row("now", "Build it", "@zed", "Started")
    else:
        files[f"{BOARD_DIR}/2026-10-02-build-it.md"] = _row(
            section, "Build it", "none" if section == "gate" else "@ada", "Started", line + "\n"
        )
    found = findings_of(write_repo(tmp_path / "roster", files, framework=toml(extra=ROSTER)))
    assert [f.check for f in found] == ["board"] and "zed" in found[0].detail and "roster" in found[0].detail
    assert findings_of(write_repo(tmp_path / "none", files)) == []  # without a roster, any login passes


def test_a_row_file_needs_no_status_and_no_incoming_link_but_its_own_links_count(tmp_path: Path) -> None:
    files = directory_board()
    files["Docs/only-from-a-row.md"] = _doc()  # linked from nowhere but a row's body
    files[f"{BOARD_DIR}/2026-10-02-build-it.md"] = _row(
        "now", "Build it", "@ada", "Started", body="See [it](../../only-from-a-row.md).\n"
    )
    assert findings_of(write_repo(tmp_path, files)) == []
    found = broken_dir(
        tmp_path, "orphan", lambda f: f.update(directory_board()) or f.__setitem__("Docs/only-from-a-row.md", _doc())
    )
    assert [f.location for f in found] == ["Docs/only-from-a-row.md"]


def test_the_board_directory_is_the_configured_one(tmp_path: Path) -> None:
    files = directory_board()
    rows = {k.replace(BOARD_DIR, "Docs/rows"): v for k, v in files.items() if k.startswith(BOARD_DIR)}
    files = {k: v for k, v in files.items() if not k.startswith(BOARD_DIR)} | rows
    assert findings_of(write_repo(tmp_path, files, framework=toml(extra='[docs]\nboard_dir = "Docs/rows"\n'))) == []


def test_parse_row_reads_the_title_and_header_and_stops_at_the_body() -> None:
    text = "# A title\n\n**Section:** now\n**Owner:** @ada\n**State:** Open\n\n**Not a header:** prose\n"
    row = cd.parse_row("Docs/plan/board/2026-10-02-build-it.md", text)
    assert row.title == "A title" and row.lines == {"Section": "now", "Owner": "@ada", "State": "Open"}
    assert row.day == "2026-10-02" and row.slug == "build-it" and row.problems == ()
    assert cd.parse_row(
        "Docs/plan/board/2026-10-02-x.md", "# T\n\n**Section:** now\n**State:** Landed as #1\n**Owner:** @a\n"
    ).done


# --------------------------------------------------------------------------- the journal under month folders
MONTHLY = "Docs/journal/2026-10/2026-10-11-ada-0930.md"


@pytest.mark.parametrize(
    ("rel", "word"),
    [
        ("Docs/journal/2026-10-11-ada-0930.md", "lives in its month folder"),  # new form at the top
        ("Docs/journal/2026-11/2026-10-11-ada-0930.md", "filed under 2026-11/"),  # the wrong month
        ("Docs/journal/2026-10/2026-10-11-session-02.md", "old-form"),  # an old-form file in a month folder
        ("Docs/journal/2026-10/notes.md", "only"),  # a stray file in a month folder
    ],
)
def test_a_session_file_out_of_its_place_is_a_journal_index_finding(tmp_path: Path, rel: str, word: str) -> None:
    found = broken(tmp_path, "journal-index", lambda f: f.__setitem__(rel, GOOD_SESSION))
    assert [f.location for f in found] == [rel] and word in found[0].detail, [str(f) for f in found]


def test_a_new_form_file_in_its_month_folder_is_a_session_file_for_every_check(tmp_path: Path) -> None:
    files = base_files()
    files[MONTHLY] = GOOD_SESSION  # no incoming link, no Status line: a session file needs neither
    files["Docs/handoffs/CURRENT.md"] = files["Docs/handoffs/CURRENT.md"].replace(TODAY, "2026-10-11")
    assert findings_of(write_repo(tmp_path, files, framework=toml(extra=ROSTER))) == []
    files["Docs/handoffs/CURRENT.md"] = files["Docs/handoffs/CURRENT.md"].replace("2026-10-11", "2026-10-12")
    found = findings_of(write_repo(tmp_path / "later", files, framework=toml(extra=ROSTER)))
    assert [f.check for f in found] == ["journal-day"] and "2026-10-11" in found[0].detail  # counted by journal-day
    files[MONTHLY] = GOOD_SESSION.replace("@ada", "@zed")
    found = findings_of(write_repo(tmp_path / "zed", files, framework=toml(extra=ROSTER)))
    assert "journal-author" in {f.check for f in found}  # checked by journal-author


def test_a_month_folder_that_is_not_a_month_and_a_folder_inside_one_are_findings(tmp_path: Path) -> None:
    root = write_repo(tmp_path, base_files())
    (root / "Docs/journal/2026-13").mkdir()
    (root / "Docs/journal/2026-10/deeper").mkdir(parents=True)
    (root / "Docs/journal/attic").mkdir()  # not named like a month: left alone
    found = findings_of(root)
    assert sorted(f.location for f in found) == ["Docs/journal/2026-10/deeper", "Docs/journal/2026-13"]
    assert all(f.check == "journal-index" for f in found)


def test_a_new_form_file_two_folders_down_is_an_ordinary_document(tmp_path: Path) -> None:
    files = base_files()
    files["Docs/journal/2026-10/deeper/2026-10-11-ada-0930.md"] = GOOD_SESSION
    found = findings_of(write_repo(tmp_path, files))
    assert {f.check for f in found} >= {"journal-index", "orphan"}  # the folder, and a document nothing links


def test_links_across_a_month_boundary_are_ordinary_relative_links(tmp_path: Path) -> None:
    files = base_files()
    files["Docs/journal/2026-10/2026-10-30-ada-0900.md"] = GOOD_SESSION
    files["Docs/journal/2026-11/2026-11-01-ada-0900.md"] = GOOD_SESSION.replace(
        "**Summary:** Decided the thing.",
        "**Summary:** Decided the thing.\n**Preceded by:** [x](../2026-10/2026-10-30-ada-0900.md) and "
        f"[y](../{TODAY}-session-01.md).",
    )
    files["Docs/handoffs/CURRENT.md"] = files["Docs/handoffs/CURRENT.md"].replace(TODAY, "2026-11-01")
    assert findings_of(write_repo(tmp_path, files)) == []
    files["Docs/journal/2026-11/2026-11-01-ada-0900.md"] = files["Docs/journal/2026-11/2026-11-01-ada-0900.md"].replace(
        "../2026-10/2026-10-30-ada-0900.md", "2026-10-30-ada-0900.md"
    )
    assert [f.check for f in findings_of(write_repo(tmp_path / "broken", files))] == ["links"]


def test_an_unreal_day_at_the_top_is_one_finding_and_a_misplaced_file_is_skipped_by_journal_author(
    tmp_path: Path,
) -> None:
    """Two behaviours the review named: the ladder reports the unreal day before the placement, once; a misplaced
    new-form file is journal-index's alone, not journal-author's as well."""
    found = broken(
        tmp_path / "day", "journal-index", lambda f: f.__setitem__("Docs/journal/2026-02-30-ada-0930.md", "# x\n")
    )
    assert len(found) == 1 and "not a real day" in found[0].detail
    files = base_files()
    files["Docs/journal/2026-10-11-zed-0930.md"] = GOOD_SESSION.replace("@ada", "@zed")  # off the roster, misplaced
    found = findings_of(write_repo(tmp_path / "zed", files, framework=toml(extra=ROSTER)))
    assert [f.check for f in found] == ["journal-index"], [str(f) for f in found]


@pytest.mark.parametrize(
    "rel",
    ["Docs/journal/2026-10-12-ada-0900.md", "Docs/journal/2026-11/2026-10-12-ada-0900.md"],
    ids=["top", "wrong-month"],
)
def test_a_misplaced_new_form_file_does_not_count_for_the_handoffs_day(tmp_path: Path, rel: str) -> None:
    """Out of its place it is journal-index's finding and nothing else's evidence: the handoff dated to it still needs a
    session file where one belongs."""
    files = base_files()
    files[rel] = GOOD_SESSION
    files["Docs/handoffs/CURRENT.md"] = files["Docs/handoffs/CURRENT.md"].replace(TODAY, "2026-10-12")
    found = findings_of(write_repo(tmp_path, files))
    assert sorted(f.check for f in found) == ["journal-day", "journal-index"], [str(f) for f in found]


@pytest.mark.parametrize("name", ["notes.txt", "notes.MD", "image.png"])
def test_a_file_of_any_kind_but_a_session_file_in_a_month_folder_is_a_finding(tmp_path: Path, name: str) -> None:
    """The markdown corpus never sees a `.txt`; the month folder is listed from disk, as the board directory is."""
    files = base_files()
    files[MONTHLY] = GOOD_SESSION
    files["Docs/handoffs/CURRENT.md"] = files["Docs/handoffs/CURRENT.md"].replace(TODAY, "2026-10-11")
    root = write_repo(tmp_path, files)
    (root / "Docs/journal/2026-10" / name).write_text("stray\n", encoding="utf-8")
    found = findings_of(root)
    assert [(f.check, f.location) for f in found] == [("journal-index", f"Docs/journal/2026-10/{name}")], [
        str(f) for f in found
    ]


# --------------------------------------------------------------------------- extension-base: beside its base
def test_an_extension_beside_its_base_passes_and_needs_no_incoming_link(tmp_path: Path) -> None:
    files = base_files()
    files["Docs/standards/one-project.md"] = _doc(body="Our rules.\n")  # nothing links it: reached through one.md
    assert checks_of(tmp_path, files) == []


@pytest.mark.parametrize(
    ("name", "base"),
    [
        ("Docs/standards/two-project.md", "two.md"),  # no base at all
        ("Docs/standards/oen-project.md", "oen.md"),  # misspelled: one.md is beside it, oen.md is not
        ("Docs/plan/one-project.md", "one.md"),  # the base is in another folder
        ("Docs/standards/one-project-project.md", "one-project.md"),  # an extension's name claims the nearest base
        ("Docs/notes/2026-10-29-new-project.md", "2026-10-29-new.md"),  # a slug that happens to end in -project
    ],
)
def test_an_extension_without_its_base_beside_it_is_a_finding_and_still_an_orphan(
    tmp_path: Path, name: str, base: str
) -> None:
    found = broken(tmp_path, "extension-base", lambda f: f.update({name: _doc()}), also=("orphan",))
    assert [(f.location, f.detail.split(",")[0]) for f in found] == [(name, f"extends {base}")]
    assert (
        "rename it so its name does not end in -project" in found[0].detail
    )  # the exit for a slug that is no extension


def test_the_match_is_case_exact_as_the_links_check_is(tmp_path: Path) -> None:
    files = base_files()
    files["Docs/standards/One-project.md"] = _doc()  # claims One.md, which is not one.md
    found = broken(tmp_path, "extension-base", lambda f: f.update(files), also=("orphan",))
    assert found[0].detail.startswith("extends One.md")


def test_the_ledger_pair_passes_and_a_linked_extension_is_still_held_to_its_base(tmp_path: Path) -> None:
    files = base_files()
    files["Docs/standards/failure-modes.md"] = _doc(body="[ours](failure-modes-project.md)\n")
    files["Docs/standards/failure-modes-project.md"] = _doc()
    files["Docs/README.md"] += "[ledger](standards/failure-modes.md)\n"
    assert checks_of(tmp_path / "pair", files) == []
    files["Docs/standards/x-project.md"] = _doc()
    files["Docs/README.md"] += "[x](standards/x-project.md)\n"  # linked, so not an orphan; still without its base
    found = checks_of(tmp_path / "linked", files)
    assert [(f.check, f.location) for f in found] == [("extension-base", "Docs/standards/x-project.md")]


def test_a_base_and_its_extension_that_link_only_each_other_are_both_orphans(tmp_path: Path) -> None:
    files = base_files()
    files["Docs/standards/two.md"] = _doc(body="[ours](two-project.md)\n")  # nothing links two.md
    files["Docs/standards/two-project.md"] = _doc(body="[base](two.md)\n")
    found = checks_of(tmp_path, files)
    assert [(f.check, f.location) for f in found] == [
        ("orphan", "Docs/standards/two-project.md"),
        ("orphan", "Docs/standards/two.md"),
    ]


def test_an_extension_whose_base_cannot_be_read_is_the_corpus_checks_finding_not_this_ones(tmp_path: Path) -> None:
    files = base_files()
    files["Docs/standards/one-project.md"] = _doc()
    root = write_repo(tmp_path, files)
    (root / "Docs/standards/one.md").write_bytes(b"\xff\xfe not utf-8")
    assert [f.check for f in findings_of(root)] == ["corpus"]


def test_a_login_ending_in_project_a_row_file_and_a_journal_file_are_not_extensions(tmp_path: Path) -> None:
    files = directory_board()
    files[f"{PEOPLE}/ada-project.md"] = _person()
    files["Docs/journal/2026-10/2026-10-11-ada-project-0930.md"] = GOOD_SESSION
    files[f"{BOARD_DIR}/2026-10-06-the-project.md"] = _row("next", "The project", "@ada", "Queued")
    roster = ROSTER + '\n[[people]]\nlogin = "ada-project"\nname = "Ada P"\nrole = "owner"\n'
    assert checks_of(tmp_path / "clean", files, framework=toml(extra=roster)) == []
    files["Docs/journal/2026-10/notes-project.md"] = "stray\n"  # the journal's finding, not an extension's
    found = checks_of(tmp_path / "stray", files, framework=toml(extra=roster))
    assert [f.check for f in found] == ["journal-index"]


def test_a_document_outside_the_governed_directories_is_not_held_to_a_base(tmp_path: Path) -> None:
    files = base_files()
    files["notes/loose-project.md"] = "# Loose\n"
    assert checks_of(tmp_path, files) == []


# --------------------------------------------------------------------------- the row id: row-ref and row-kept
ROW_ID = "2026-10-02-build-it"
DESIGN = "Docs/design/d.md"


def _board(*ids: str, prefix: str = "../plan/board/") -> str:
    return "**Board:** " + ", ".join(f"[`{i}`]({prefix}{i}.md)" for i in ids)


def _design(board: str | None, body: str = "") -> str:
    line = f"{board}\n" if board is not None else ""
    return f"# A design\n\n**Status:** Accepted.\n{line}\nDate: 2026-10-11.\n\n{body}## Terms introduced\n\nNone.\n"


def with_design(files: dict[str, str], board: str | None, rel: str = DESIGN, body: str = "") -> dict[str, str]:
    files[rel] = _design(board, body)
    files["Docs/README.md"] += f"[d]({posixpath.relpath(rel, 'Docs')})\n"
    return files


# ---- the shared readers
def test_a_file_header_is_its_lines_before_the_first_level_two_heading_outside_fences() -> None:
    text = "# T\n\n**Status:** Living.\n```\n**Board:** fenced\n```\n**Board:** x\n\n## Body\n\n**Board:** body\n"
    assert [line for _, line in cd.header_lines(text)] == ["# T", "", "**Status:** Living.", "**Board:** x", ""]


def test_an_entry_header_is_its_by_line_to_the_first_blank_line() -> None:
    text = (
        "# Session\n\n**Summary:** s\n\n### One\n**By:** @ada · **Agent:** none\n**Said by:** @ada\n**Board:** a\n\n"
        "Body.\n**Board:** body\n\n### Two\n\n**By:** @ada · **Agent:** none\n\n**Board:** after the blank\n"
    )
    headers = [[line for _, line in header] for header in cd.entry_headers(text)]
    assert headers == [
        ["**By:** @ada · **Agent:** none", "**Said by:** @ada", "**Board:** a"],
        ["**By:** @ada · **Agent:** none"],
    ]


@pytest.mark.parametrize(
    ("value", "links", "problems"),
    [
        ("[`a`](a.md)", [("`a`", "a.md")], []),
        ("[`a`](a.md), [`b`](b.md)", [("`a`", "a.md"), ("`b`", "b.md")], []),
        ("none (the first design, before the board)", [], []),
        ("none", [], ["say which row, or none (reason)"]),
        ("none ()", [], ["say which row, or none (reason)"]),
        ("the build row", [], ["say which row, or none (reason)"]),
    ],
)
def test_a_board_line_is_links_or_none_with_a_reason(value: str, links: list, problems: list) -> None:
    assert cd.board_refs(value) == (links, problems)


# ---- row-ref
def test_a_design_naming_its_row_by_id_passes(tmp_path: Path) -> None:
    assert checks_of(tmp_path, with_design(directory_board(), _board(ROW_ID))) == []


def test_a_design_naming_two_rows_or_none_with_a_reason_passes(tmp_path: Path) -> None:
    files = with_design(directory_board(), _board(ROW_ID, "2026-10-03-then-this"))
    with_design(files, "**Board:** none (before the board)", "Docs/superpowers/plans/p.md")
    assert checks_of(tmp_path, files) == []


def test_a_design_spec_or_plan_with_no_board_line_is_a_finding(tmp_path: Path) -> None:
    for rel in (DESIGN, "Docs/superpowers/specs/s.md", "Docs/superpowers/plans/p.md"):
        found = broken_dir(tmp_path / posixpath.basename(rel), "row-ref", lambda f, r=rel: with_design(f, None, r))
        assert [(f.location, f.detail) for f in found] == [
            (rel, "no `**Board:**` line: name its row, or say none (reason)")
        ]


def _link_from_rows(files: dict[str, str], *ids: str, target: str = "../../design/d.md") -> dict[str, str]:
    for row_id in ids:
        files[f"{BOARD_DIR}/{row_id}.md"] += f"\nLinks: [the design]({target})\n"
    return files


def test_a_missing_board_line_names_the_rows_whose_files_link_the_document(tmp_path: Path) -> None:
    """#150: choosing a row by hand was most of an update's cost; the rows that already link the document are named."""

    def mutate(f: dict[str, str]) -> None:
        with_design(f, None)
        _link_from_rows(f, "2026-10-03-then-this", ROW_ID)
        _link_from_rows(f, "2026-10-04-stuck", target="../../design/d.md#a-section")  # a fragment is the same file

    found = broken_dir(tmp_path, "row-ref", mutate)
    assert [f.detail for f in found] == [
        "no `**Board:**` line: name its row, or say none (reason); rows whose files link it: "
        "`2026-10-02-build-it`, `2026-10-03-then-this`, `2026-10-04-stuck`"
    ]


def test_the_old_board_line_names_the_linking_rows_too(tmp_path: Path) -> None:
    def mutate(f: dict[str, str]) -> None:
        with_design(f, "Board: [the board](../README.md).")
        _link_from_rows(f, ROW_ID)

    found = broken_dir(tmp_path, "row-ref", mutate)
    assert [f.detail for f in found] == [
        f"write the row as **Board:** with its id; rows whose files link it: `{ROW_ID}`"
    ]


def test_a_link_in_a_rows_code_block_or_to_another_file_is_not_a_hint(tmp_path: Path) -> None:
    def mutate(f: dict[str, str]) -> None:
        with_design(f, None)
        f[f"{BOARD_DIR}/{ROW_ID}.md"] += "\n```\n[the design](../../design/d.md)\n```\n"
        _link_from_rows(f, "2026-10-03-then-this", target="../../design/d.md.bak")
        _link_from_rows(f, "2026-10-04-stuck", target="../../design/other/d.md")

    found = broken_dir(tmp_path, "row-ref", mutate, also=("links",))
    assert [f.detail for f in found] == ["no `**Board:**` line: name its row, or say none (reason)"]


def test_an_index_in_those_directories_needs_no_board_line(tmp_path: Path) -> None:
    files = directory_board()
    files["Docs/design/README.md"] = _doc(body="The designs.\n")
    files["Docs/README.md"] += "[designs](design/README.md)\n"
    assert checks_of(tmp_path, files) == []


def test_the_old_plain_board_line_is_a_finding_that_says_how_to_rewrite_it(tmp_path: Path) -> None:
    found = broken_dir(tmp_path, "row-ref", lambda f: with_design(f, "Board: [the board](../README.md)."))
    assert [f.detail for f in found] == ["write the row as **Board:** with its id"]


def test_a_board_link_to_no_row_file_is_a_finding(tmp_path: Path) -> None:
    found = broken_dir(tmp_path, "row-ref", lambda f: with_design(f, _board("2026-10-09-gone")), also=("links",))
    assert [f.detail for f in found] == ["names no row: ../plan/board/2026-10-09-gone.md"]


def test_a_board_link_to_a_file_that_is_not_a_row_is_a_finding(tmp_path: Path) -> None:
    found = broken_dir(tmp_path, "row-ref", lambda f: with_design(f, "**Board:** [`one`](../standards/one.md)"))
    assert [f.detail for f in found] == ["names no row: ../standards/one.md"]


def test_a_board_link_whose_text_is_not_the_id_is_a_finding(tmp_path: Path) -> None:
    for text in ("Build it", ROW_ID, "`2026-10-02-build`"):
        line = f"**Board:** [{text}](../plan/board/{ROW_ID}.md)"
        found = broken_dir(tmp_path / str(len(text)), "row-ref", lambda f, ln=line: with_design(f, ln))
        assert [f.detail for f in found] == [f"link text is not the row's id: `{ROW_ID}`"]


def test_none_without_a_reason_or_a_line_naming_nothing_is_a_finding(tmp_path: Path) -> None:
    for value in ("none", "the build row"):
        found = broken_dir(tmp_path / str(len(value)), "row-ref", lambda f, v=value: with_design(f, f"**Board:** {v}"))
        assert [f.detail for f in found] == ["say which row, or none (reason)"]


def test_two_board_lines_in_one_header_are_a_finding(tmp_path: Path) -> None:
    found = broken_dir(tmp_path, "row-ref", lambda f: with_design(f, _board(ROW_ID) + "\n" + _board(ROW_ID)))
    assert [f.detail for f in found] == ["one `**Board:**` line, several rows separated by commas"]


def test_a_board_line_in_a_body_or_a_fence_is_not_read(tmp_path: Path) -> None:
    body = "## Example\n\n**Board:** none\n\n```\n**Board:** [`x`](nowhere.md)\n```\n\n"
    assert checks_of(tmp_path, with_design(directory_board(), _board(ROW_ID), body=body)) == []


ADR = "Docs/decisions/ADR-001-first.md"


def _adr(board: str) -> str:
    return f"# Title\n\n**Status:** Accepted. A document.\n{board}\n\nText.\n"


def test_an_adr_may_carry_a_board_line_and_it_is_checked(tmp_path: Path) -> None:
    assert checks_of(tmp_path / "absent", directory_board()) == []  # the base corpus's ADR has no line: optional there
    files = directory_board()
    files[ADR] = _adr(_board(ROW_ID))
    assert checks_of(tmp_path / "good", files) == []
    found = broken_dir(tmp_path / "bad", "row-ref", lambda f: f.__setitem__(ADR, _adr("**Board:** none")))
    assert [(f.location, f.detail) for f in found] == [(ADR, "say which row, or none (reason)")]


SESSION = f"Docs/journal/{TODAY}-session-01.md"


def _session(board: str) -> str:
    return f"# Session 01\n\n### Work\n**By:** @ada · **Agent:** none\n{board}\n\nWork.\n"


def test_a_journal_entry_may_carry_a_board_line_in_its_header(tmp_path: Path) -> None:
    files = directory_board()
    files[SESSION] = _session(_board(ROW_ID))
    assert checks_of(tmp_path / "good", files) == []
    found = broken_dir(tmp_path / "bad", "row-ref", lambda f: f.__setitem__(SESSION, _session("**Board:** none")))
    assert [(f.location, f.detail) for f in found] == [(SESSION, "say which row, or none (reason)")]


def test_a_hand_kept_board_has_no_ids_and_row_ref_stands_down(tmp_path: Path) -> None:
    assert checks_of(tmp_path, with_design(base_files(), None)) == []


# ---- the base, and row-kept
class FakeGit:
    """A runner for ``read_base``: ``answers`` maps the git arguments after ``git -C <root>`` to (exit, output)."""

    def __init__(
        self,
        answers: dict[tuple[str, ...], tuple[int, str]],
        *,
        missing: bool = False,
        raises: OSError | None = None,
    ) -> None:
        self.answers, self.missing, self.raises = answers, missing, raises

    def __call__(self, argv: list[str]) -> tuple[int, str, str]:
        if self.missing:
            raise FileNotFoundError("git")
        if self.raises is not None:
            raise self.raises
        assert argv[:2] == ["git", "-C"], argv
        key = tuple(argv[3:])
        if key not in self.answers and key == TOPLEVEL:  # an empty runner is a directory that is no repository
            return 128, "", "fatal: not a git repository (or any of the parent directories): .git"
        code, out = self.answers.get(key, (1, ""))  # anything else unanswered is absent, as a --quiet query is
        return code, out, "" if code == 0 else f"fatal: {' '.join(key)}"


TOPLEVEL = ("rev-parse", "--show-toplevel")


def _work_tree(root: Path, extra: dict[str, tuple[int, str]] | None = None) -> dict[tuple[str, ...], tuple[int, str]]:
    answers = {
        TOPLEVEL: (0, f"{root.resolve().as_posix()}\n"),
        ("rev-parse", "--verify", "--quiet", "HEAD"): (0, "a1\n"),
    }
    for key, value in (extra or {}).items():
        answers[tuple(key.split("|"))] = value
    return answers


LS = f"{BOARD_DIR}/2026-10-02-build-it.md\n{BOARD_DIR}/README.md\n{BOARD_DIR}/2026-10-03-then-this.md\n"
CI_LS = f"ls-tree|--name-only|origin/main|--|{BOARD_DIR}/"


def _ci(workspace: Path) -> dict[str, str]:
    """The environment of a pull request's job on CI whose checkout is ``workspace``."""
    return {"GITHUB_BASE_REF": "main", "GITHUB_WORKSPACE": str(workspace)}


def test_in_ci_the_base_is_origin_and_the_base_ref(tmp_path: Path) -> None:
    base = cd.read_base(tmp_path, BOARD_DIR, _ci(tmp_path), FakeGit(_work_tree(tmp_path, {CI_LS: (0, LS)})))
    assert base.rows == frozenset({"2026-10-02-build-it", "2026-10-03-then-this"})
    assert "origin/main" in base.note


def test_in_ci_a_base_git_cannot_read_stops_the_run_and_says_to_fetch_it(tmp_path: Path) -> None:
    with pytest.raises(cd.BaseError, match="fetch-depth: 0"):
        cd.read_base(tmp_path, BOARD_DIR, _ci(tmp_path), FakeGit(_work_tree(tmp_path)))


def test_locally_the_base_is_the_merge_base_with_the_default_branch(tmp_path: Path) -> None:
    answers = _work_tree(
        tmp_path,
        {
            "symbolic-ref|--quiet|--short|refs/remotes/origin/HEAD": (0, "origin/main\n"),
            "merge-base|HEAD|origin/main": (0, "abc123\n"),
            f"ls-tree|--name-only|abc123|--|{BOARD_DIR}/": (0, LS),
        },
    )
    base = cd.read_base(tmp_path, BOARD_DIR, {}, FakeGit(answers))
    assert base.rows == frozenset({"2026-10-02-build-it", "2026-10-03-then-this"})


def test_locally_with_no_origin_head_the_branch_main_is_the_default(tmp_path: Path) -> None:
    answers = _work_tree(
        tmp_path,
        {
            "rev-parse|--verify|--quiet|main": (0, "def456\n"),
            "merge-base|HEAD|main": (0, "def456\n"),
            f"ls-tree|--name-only|def456|--|{BOARD_DIR}/": (0, ""),
        },
    )
    base = cd.read_base(tmp_path, BOARD_DIR, {"GITHUB_BASE_REF": ""}, FakeGit(answers))  # empty: not a pull request
    assert base.rows == frozenset()  # a base from before the board's directory form has no rows: not an error


@pytest.mark.parametrize("case", ["git missing", "not a work tree", "not the top", "no default branch"])
def test_with_no_base_row_kept_is_skipped_and_says_why(tmp_path: Path, case: str) -> None:
    git, why = {
        "git missing": (FakeGit({}, missing=True), "git could not be run"),
        "not a work tree": (FakeGit({}), "not a git work tree"),
        "not the top": (FakeGit(_work_tree(tmp_path.parent)), "not the top of its work tree"),
        "no default branch": (FakeGit(_work_tree(tmp_path)), "no default branch"),
    }[case]
    base = cd.read_base(tmp_path, BOARD_DIR, {}, git)
    assert base.rows is None and why in base.note


def _kept(tmp: Path, base_rows: frozenset[str] | None) -> list[cd.Finding]:
    ctx = cd.load_context(write_repo(tmp, directory_board()))
    return cd.check_row_kept(dataclasses.replace(ctx, base_rows=base_rows))


def test_a_row_on_the_base_still_in_the_tree_or_a_new_row_passes(tmp_path: Path) -> None:
    assert _kept(tmp_path, frozenset({"2026-10-02-build-it"})) == []
    assert _kept(tmp_path / "none", None) == []


def test_a_row_on_the_base_gone_from_the_tree_is_a_finding(tmp_path: Path) -> None:
    found = _kept(tmp_path, frozenset({"2026-10-02-build-it", "2026-10-01-renamed-since"}))
    assert [(f.check, f.location, f.detail) for f in found] == [
        (
            "row-kept",
            f"{BOARD_DIR}/2026-10-01-renamed-since.md",
            "row `2026-10-01-renamed-since` is on the base and gone: a row id never changes once on main",
        )
    ]


def test_main_prints_the_skip_and_stops_on_a_base_it_cannot_read(tmp_path: Path, capsys) -> None:
    write_repo(tmp_path, directory_board())
    assert cd.main([str(tmp_path)], env={}, git=FakeGit({})) == 0
    assert "row-kept: skipped: " in capsys.readouterr().out
    assert cd.main([str(tmp_path)], env=_ci(tmp_path), git=FakeGit(_work_tree(tmp_path))) == 2
    assert "fetch-depth: 0" in capsys.readouterr().err


def test_main_finds_a_renamed_row_against_the_base(tmp_path: Path, capsys) -> None:
    write_repo(tmp_path, directory_board())
    git = FakeGit(_work_tree(tmp_path, {CI_LS: (0, f"{BOARD_DIR}/2026-10-01-the-old-name.md\n")}))
    assert cd.main([str(tmp_path)], env=_ci(tmp_path), git=git) == 1
    assert "[row-kept] Docs/plan/board/2026-10-01-the-old-name.md" in capsys.readouterr().out


def test_row_artifacts_lists_every_kind_naming_a_row_and_nothing_from_a_body(tmp_path: Path) -> None:
    files = with_design(directory_board(), _board(ROW_ID))
    body = "## B\n\n" + _board("2026-10-03-then-this") + "\n\n"
    with_design(files, _board(ROW_ID, prefix="../../plan/board/"), "Docs/superpowers/specs/s.md", body=body)
    files[ADR] = _adr(_board(ROW_ID))
    files[SESSION] = _session(_board(ROW_ID))
    artifacts = cd.row_artifacts(cd.load_context(write_repo(tmp_path, files)))
    assert artifacts == {ROW_ID: [ADR, DESIGN, SESSION, "Docs/superpowers/specs/s.md"]}


def test_in_ci_a_repository_other_than_the_checkout_is_read_as_a_local_one(tmp_path: Path) -> None:
    """A job that builds a repository inside the runner (the day-0 run) has GITHUB_BASE_REF set too, but no origin."""
    made = tmp_path / "made"
    made.mkdir()
    answers = _work_tree(made, {"rev-parse|--verify|--quiet|main": (0, "a1\n"), "merge-base|HEAD|main": (0, "a1\n")})
    answers[("ls-tree", "--name-only", "a1", "--", f"{BOARD_DIR}/")] = (0, "")
    base = cd.read_base(made, BOARD_DIR, _ci(tmp_path), FakeGit(answers))
    assert base.rows == frozenset() and "merge base with main" in base.note


@pytest.mark.parametrize("case", ["git missing", "not a work tree", "git fails"])
def test_in_ci_any_git_failure_stops_the_run_instead_of_skipping(tmp_path: Path, case: str) -> None:
    git = {
        "git missing": FakeGit({}, missing=True),
        "not a work tree": FakeGit({}),
        "git fails": FakeGit(_work_tree(tmp_path, {CI_LS: (128, "")})),
    }[case]
    with pytest.raises(cd.BaseError):
        cd.read_base(tmp_path, BOARD_DIR, _ci(tmp_path), git)


@pytest.mark.parametrize(
    ("extra", "outcome"),
    [
        ({"rev-parse|--verify|--quiet|HEAD": (1, "")}, "no commit yet"),
        ({"rev-parse|--verify|--quiet|main": (0, "a1\n"), "merge-base|HEAD|main": (1, "")}, "no common ancestor"),
        ({"rev-parse|--verify|--quiet|main": (0, "a1\n"), "merge-base|HEAD|main": (128, "")}, "error"),
        ({"symbolic-ref|--quiet|--short|refs/remotes/origin/HEAD": (128, "")}, "error"),
        ({"rev-parse|--verify|--quiet|main": (0, "a1\n"), "merge-base|HEAD|main": (0, "b2\n")}, "error"),  # ls-tree
    ],
)
def test_locally_an_absent_answer_skips_and_any_other_git_failure_is_an_error(
    tmp_path: Path, extra: dict[str, tuple[int, str]], outcome: str
) -> None:
    git = FakeGit(_work_tree(tmp_path, extra))
    if outcome == "error":
        with pytest.raises(cd.BaseError):
            cd.read_base(tmp_path, BOARD_DIR, {}, git)
    else:
        base = cd.read_base(tmp_path, BOARD_DIR, {}, git)
        assert base.rows is None and outcome in base.note


def test_a_one_page_board_with_no_readable_base_is_skipped_even_in_ci(tmp_path: Path, capsys) -> None:
    """A shallow checkout of a board that was always one page: no `fetch-depth: 0`, and no exit 2."""
    write_repo(tmp_path, base_files())
    assert cd.main([str(tmp_path)], env=_ci(tmp_path), git=FakeGit(_work_tree(tmp_path))) == 0
    assert "row-kept: skipped: the board is one page" in capsys.readouterr().out


def test_a_one_page_board_whose_base_has_rows_is_a_row_kept_finding(tmp_path: Path, capsys) -> None:
    """Deleting every row file must not turn the check off: the base still has them."""
    write_repo(tmp_path, base_files())
    git = FakeGit(_work_tree(tmp_path, {CI_LS: (0, f"{BOARD_DIR}/2026-10-01-the-old-name.md\n")}))
    assert cd.main([str(tmp_path)], env=_ci(tmp_path), git=git) == 1
    assert "[row-kept] Docs/plan/board/2026-10-01-the-old-name.md" in capsys.readouterr().out


@pytest.mark.parametrize("error", [TimeoutError("git did not answer"), PermissionError("denied")])
def test_locally_a_git_that_fails_to_run_other_than_missing_is_an_error(tmp_path: Path, error: OSError) -> None:
    with pytest.raises(cd.BaseError):
        cd.read_base(tmp_path, BOARD_DIR, {}, FakeGit({}, raises=error))


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_with_real_git_a_row_renamed_on_a_branch_is_found(tmp_path: Path, capsys) -> None:
    write_repo(tmp_path, directory_board())

    def git(*args: str) -> None:
        cmd = ["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@example.org", *args]
        subprocess.run(cmd, check=True, capture_output=True)

    git("init", "-q", "-b", "main")
    git("add", "-A")
    git("commit", "-q", "-m", "rows")
    git("checkout", "-q", "-b", "work")
    assert cd.main([str(tmp_path)], env={}) == 0
    assert "row-kept: skipped" not in capsys.readouterr().out
    git("mv", f"{BOARD_DIR}/2026-10-03-then-this.md", f"{BOARD_DIR}/2026-10-03-then-that.md")
    git("commit", "-q", "-m", "rename")
    assert cd.main([str(tmp_path)], env={}) == 1
    assert f"[row-kept] {BOARD_DIR}/2026-10-03-then-this.md" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("value", "links", "problems"),
    [
        ("[`a`](<a b.md>)", [("`a`", "a b.md")], []),
        ('[`a`](a.md "the row")', [("`a`", "a.md")], []),
        ("none (a (nested) reason)", [], []),
    ],
)
def test_a_board_line_reads_angle_destinations_titles_and_nested_reasons(
    value: str, links: list, problems: list
) -> None:
    assert cd.board_refs(value) == (links, problems)


def test_a_setext_heading_ends_a_file_header_and_any_heading_ends_an_entry_header() -> None:
    text = "# T\n\n**Status:** Living.\n\nBody\n----\n\n**Board:** body\n"
    assert [line for _, line in cd.header_lines(text)] == ["# T", "", "**Status:** Living.", ""]
    entry = "# S\n\n### One\n**By:** @ada · **Agent:** none\n## Day two\n**Board:** body\n"
    assert [[line for _, line in h] for h in cd.entry_headers(entry)] == [["**By:** @ada · **Agent:** none"]]
