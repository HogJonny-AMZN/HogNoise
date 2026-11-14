"""
Framework: tests for tools/render_board.py, the board page renderer for a board in directory form.
Package: tests/test_render_board

The page is derived and git-ignored, so the tests prove what it is made of (the five sections in order, open rows before
done ones and newest first, the view by owner, the unreadable rows), that a link resolves from the page as it did from
the row, that a failure never leaves half a page, and that the docs check neither needs the page nor trips on it.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import check_docs as cd  # noqa: E402
import render_board as rb  # noqa: E402

TOOL = ROOT / "tools" / "render_board.py"
BOARD_DIR = "Docs/plan/board"
PAGE = "Docs/plan/BOARD.md"
FRAMEWORK = """\
[framework]
template_version = "0.1.0"

[modules]
core = "on"
journal = "on"
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
handoff_max_lines = 150

{extra}
"""


def row(section: str, title: str, owner: str = "@ada", state: str = "Open", extra: str = "", body: str = "") -> str:
    return f"# {title}\n\n**Section:** {section}\n**Owner:** {owner}\n**State:** {state}\n{extra}\n{body}"


ICEBOX = "**Cost:** 2 d\n**Verdict:** Good\n**Raised:** [said](../../README.md)\n"


def rows() -> dict[str, str]:
    """A board with every section, an owner in two cases, a done row and an Icebox row."""
    return {
        f"{BOARD_DIR}/2026-10-01-first-gate.md": row("gate", "G1", "none", "Open", "**Decider:** @ada\n"),
        f"{BOARD_DIR}/2026-10-02-build-it.md": row(
            "now", "Build it", "@ada", "Started, see [the design](../../design/x.md)"
        ),
        f"{BOARD_DIR}/2026-10-06-newer.md": row("now", "Newer", "@Bo-B", "Open"),
        f"{BOARD_DIR}/2026-10-03-then-this.md": row("next", "Then this", "@bo-b", "Queued"),
        f"{BOARD_DIR}/2026-10-04-stuck.md": row("blocked", "Stuck", "@ada", "Waiting on G1"),
        f"{BOARD_DIR}/2026-10-05-an-idea.md": row("icebox", "An idea", "none", "Iceboxed", ICEBOX),
        f"{BOARD_DIR}/2026-09-30-done-thing.md": row("now", "Done thing", "@ada", "Landed 2026-10-01 as #12"),
    }


def corpus() -> dict[str, str]:
    """A corpus the docs check passes in directory form, with the page absent."""
    return {
        "README.md": "# Project\n\nSee [the docs](Docs/README.md).\n",
        "Docs/README.md": (
            "# Map\n\n**Status:** Living.\n\n[handoff](handoffs/CURRENT.md) [board](plan/BOARD.md) "
            "[journal](journal/README.md) [decisions](decisions/README.md) [design](design/x.md)\n"
        ),
        "Docs/handoffs/CURRENT.md": (
            "# Handoff\n\n**Status:** Living.\n**Last updated:** 2026-10-11: day 0.\n\nState.\n"
        ),
        "Docs/journal/README.md": (
            "# Journal\n\n**Status:** Living.\n\n| 2026-10-11 | [S](2026-10-11-session-01.md) | x |\n"
        ),
        "Docs/journal/2026-10-11-session-01.md": "# Session 01\n\nWork.\n",
        "Docs/decisions/README.md": "# Decisions\n\n| ADR | Title |\n| --- | --- |\n",
        "Docs/design/x.md": (
            "# A design\n\n**Status:** Accepted.\n"
            "**Board:** [`2026-10-02-build-it`](../plan/board/2026-10-02-build-it.md)\n\n"
            "Text.\n\n## Terms introduced\n\nNone.\n"
        ),
        **rows(),
    }


def make_repo(tmp: Path, files: dict[str, str], *, extra: str = "") -> Path:
    for rel, text in {**files, "framework.toml": FRAMEWORK.format(extra=extra)}.items():
        path = tmp / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    return tmp


def render_in(tmp: Path, *args: str) -> tuple[int, str]:
    code = rb.main([*args], root=tmp)
    page = tmp / PAGE
    return code, page.read_text(encoding="utf-8") if page.exists() else ""


# --------------------------------------------------------------------------- the page
def test_the_page_has_the_five_sections_in_order_with_tables_and_none_where_empty(tmp_path: Path) -> None:
    files = corpus()
    del files[f"{BOARD_DIR}/2026-10-03-then-this.md"]
    code, text = render_in(make_repo(tmp_path, files))
    assert code == 0 and text.startswith(cd.BOARD_HEADER + "\n")
    positions = [text.index(h) for h in ("## Gates", "## Now", "## Next", "## Blocked", "## Icebox", "## By owner")]
    assert positions == sorted(positions)
    next_section = text.split("## Next", 1)[1].split("## Blocked", 1)[0]
    assert "None." in next_section and "| Row |" not in next_section
    assert "| G1 | @ada | Open |" not in text and "| [G1](board/2026-10-01-first-gate.md) | @ada | Open |" in text


def test_open_rows_come_first_newest_first_and_done_rows_are_struck_after_them(tmp_path: Path) -> None:
    _, text = render_in(make_repo(tmp_path, corpus()))
    now = text.split("## Now", 1)[1].split("## Next", 1)[0]
    newer, build, done = (now.index(s) for s in ("[Newer]", "[Build it]", "~~[Done thing]"))
    assert newer < build < done
    assert "~~[Done thing](board/2026-09-30-done-thing.md)~~ | @ada | Landed 2026-10-01 as #12" in now


def test_a_done_row_newer_than_every_open_row_still_comes_after_them(tmp_path: Path) -> None:
    files = corpus()
    files[f"{BOARD_DIR}/2026-10-09-landed-late.md"] = row("now", "Landed late", "@ada", "Landed 2026-10-09 as #13")
    _, text = render_in(make_repo(tmp_path, files))
    now = text.split("## Now", 1)[1].split("## Next", 1)[0]
    newer, build, late, done = (now.index(s) for s in ("[Newer]", "[Build it]", "~~[Landed late]", "~~[Done thing]"))
    assert newer < build < late < done  # open rows first, then the done rows, each group newest first


def test_the_icebox_table_carries_cost_and_verdict_and_the_owner_none(tmp_path: Path) -> None:
    _, text = render_in(make_repo(tmp_path, corpus()))
    icebox = text.split("## Icebox", 1)[1].split("## By owner", 1)[0]
    assert "| Idea | Owner | Cost | Verdict | State |" in icebox
    assert "| [An idea](board/2026-10-05-an-idea.md) | none | 2 d | Good | Iceboxed |" in icebox


def test_by_owner_lists_each_logins_open_rows_ignoring_case_without_the_icebox_or_done_rows(tmp_path: Path) -> None:
    _, text = render_in(make_repo(tmp_path, corpus()))
    view = text.split("## By owner", 1)[1]
    assert view.index("### @ada") < view.index("### @Bo-B")
    assert view.count("### @") == 2  # @Bo-B and @bo-b are one owner
    bo = view.split("### @Bo-B", 1)[1]
    assert "Now: [Newer]" in bo and "Next: [Then this]" in bo and bo.index("Now:") < bo.index("Next:")
    assert "Done thing" not in view and "An idea" not in view and "[G1]" not in view  # done, Icebox, gate rows


def test_a_gate_without_a_decider_renders_the_owner_as_its_decider(tmp_path: Path) -> None:
    files = corpus()
    files[f"{BOARD_DIR}/2026-10-01-first-gate.md"] = row("gate", "G1", "none", "Open")
    _, text = render_in(make_repo(tmp_path, files))
    assert "| [G1](board/2026-10-01-first-gate.md) | the owner | Open |" in text


def test_an_icebox_row_with_an_owner_stays_out_of_the_by_owner_view(tmp_path: Path) -> None:
    """The view is each person's work, and an Icebox row is not work: it is excluded by section, not by its owner."""
    files = corpus()
    files[f"{BOARD_DIR}/2026-10-05-an-idea.md"] = row("icebox", "An idea", "@ada", "Iceboxed", ICEBOX)
    _, text = render_in(make_repo(tmp_path, files))
    view = text.split("## By owner", 1)[1]
    assert "An idea" not in view and "An idea" in text.split("## Icebox", 1)[1].split("## By owner", 1)[0]


def test_a_link_in_a_rendered_field_is_rebased_so_it_resolves_from_the_page_too(tmp_path: Path) -> None:
    root = make_repo(tmp_path, corpus())
    _, text = render_in(root)
    assert "[the design](../design/x.md)" in text and "../../design/x.md" not in text
    assert (root / "Docs/plan" / "../design/x.md").resolve() == (root / "Docs/design/x.md").resolve()
    assert rb.rebase_links("[a](https://x.example/p) [b](#here) [c](/root.md)", BOARD_DIR, "Docs/plan") == (
        "[a](https://x.example/p) [b](#here) [c](/root.md)"
    )
    assert rb.rebase_links("[d](../../a.md#frag)", BOARD_DIR, "Docs/plan") == "[d](../a.md#frag)"


def test_a_row_that_fails_the_rules_is_listed_as_unreadable_and_the_run_exits_one(tmp_path: Path, capsys) -> None:
    files = corpus()
    files[f"{BOARD_DIR}/2026-10-07-bad.md"] = "# Bad\n\n**Section:** now\n**State:** Open\n"
    code, text = render_in(make_repo(tmp_path, files))
    assert code == 1 and "## Unreadable rows" in text and "2026-10-07-bad.md" in text and "Owner" in text
    assert "[board] Docs/plan/board/2026-10-07-bad.md" in capsys.readouterr().out
    assert "[Bad]" not in text.split("## Unreadable rows", 1)[0]


def test_the_page_is_the_same_text_every_time(tmp_path: Path) -> None:
    root = make_repo(tmp_path, corpus())
    _, first = render_in(root)
    _, second = render_in(root)
    assert first == second


def test_a_field_with_pipes_and_control_characters_cannot_break_the_table(tmp_path: Path) -> None:
    files = corpus()
    files[f"{BOARD_DIR}/2026-10-06-newer.md"] = row("now", "A | title", "@ada", "Open and | more")
    _, text = render_in(make_repo(tmp_path, files))
    assert "[A \\| title](board/2026-10-06-newer.md) | @ada | Open and \\| more |" in text


def test_print_writes_the_page_text_to_standard_output_and_no_file(tmp_path: Path, capsys) -> None:
    root = make_repo(tmp_path, corpus())
    code = rb.main(["--print"], root=root)
    assert code == 0 and not (root / PAGE).exists()
    assert capsys.readouterr().out.startswith(cd.BOARD_HEADER)


def test_the_board_directory_and_the_page_come_from_the_configuration(tmp_path: Path) -> None:
    files = {k.replace(BOARD_DIR, "Docs/rows"): v for k, v in corpus().items()}
    extra = '[docs]\nboard_dir = "Docs/rows"\nboard = "Docs/plan/VIEW.md"\n'
    root = make_repo(tmp_path, files, extra=extra)
    assert rb.main([], root=root) == 0
    text = (root / "Docs/plan/VIEW.md").read_text(encoding="utf-8")
    assert "[Build it](../rows/2026-10-02-build-it.md)" in text


def test_a_hand_kept_page_beside_rows_is_never_rendered_over(tmp_path: Path, capsys) -> None:
    """The two-trackers condition the docs check rejects: rendering first would destroy the page and its notes."""
    root = make_repo(tmp_path, corpus())
    hand_kept = "# The Board\n\n**Status:** Living.\n\n## Now\n\n| Row | State |\n| --- | --- |\n| Not yet | Open |\n"
    (root / PAGE).write_text(hand_kept, encoding="utf-8")
    assert rb.main([], root=root) == 2
    assert (root / PAGE).read_text(encoding="utf-8") == hand_kept
    assert "two trackers" in capsys.readouterr().err
    assert rb.main(["--print"], root=root) == 0  # printing writes nothing, so it is allowed
    (root / PAGE).write_text(cd.BOARD_HEADER + "\n\nold render\n", encoding="utf-8")
    assert rb.main([], root=root) == 0  # a rendered page is replaced
    assert "old render" not in (root / PAGE).read_text(encoding="utf-8")


def test_an_angle_bracket_destination_is_rebased_with_its_brackets_kept(tmp_path: Path) -> None:
    files = corpus()
    files[f"{BOARD_DIR}/2026-10-06-newer.md"] = row(
        "now", "Newer", "@ada", "See [d](<../../design/x.md>) and [u](<https://x.example/a b>)"
    )
    _, text = render_in(make_repo(tmp_path, files))
    assert "[d](<../design/x.md>)" in text and "[u](<https://x.example/a b>)" in text
    assert rb.rebase_links("[s](<../../a b.md#f> 'title')", BOARD_DIR, "Docs/plan") == "[s](<../a b.md#f> 'title')"


def test_a_hand_kept_board_has_nothing_to_render_and_exits_two(tmp_path: Path, capsys) -> None:
    files = {k: v for k, v in corpus().items() if not k.startswith(BOARD_DIR)}
    files[PAGE] = "# The Board\n\n**Status:** Living.\n\n## Gates\n\nNone.\n"
    (tmp_path / BOARD_DIR).mkdir(parents=True)
    assert rb.main([], root=make_repo(tmp_path, files)) == 2
    assert "hand-kept" in capsys.readouterr().err


def test_a_missing_board_directory_and_a_bad_root_exit_two(tmp_path: Path, capsys) -> None:
    files = {k: v for k, v in corpus().items() if not k.startswith(BOARD_DIR)}
    assert rb.main([], root=make_repo(tmp_path, files)) == 2
    err = capsys.readouterr().err
    # no board directory is the usual hand-kept board: the same message as an empty one, not a traceback's words
    assert "hand-kept" in err and "FileNotFoundError" not in err, err
    assert rb.main([], root=tmp_path / "nowhere") == 2


def test_a_board_directory_that_cannot_be_listed_is_unreadable_not_hand_kept(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    """Missing is hand-kept; a directory that is there and cannot be read is an error that says so (ledger P-16)."""
    repo = make_repo(tmp_path, corpus())
    real_iterdir = Path.iterdir

    def refuse(self: Path):  # noqa: ANN202 - Path.iterdir's own shape
        if self.name == Path(BOARD_DIR).name:
            raise PermissionError(13, "Permission denied", str(self))
        return real_iterdir(self)

    monkeypatch.setattr(Path, "iterdir", refuse)
    assert rb.main([], root=repo) == 2
    err = capsys.readouterr().err
    assert "cannot list the board directory" in err and "PermissionError" in err and "hand-kept" not in err, err


def test_a_board_path_that_is_a_file_is_not_a_hand_kept_board(tmp_path: Path, capsys) -> None:
    files = {k: v for k, v in corpus().items() if not k.startswith(BOARD_DIR)}
    files[BOARD_DIR] = "a file where the board directory goes\n"
    assert rb.main([], root=make_repo(tmp_path, files)) == 2
    err = capsys.readouterr().err
    assert "cannot list the board directory" in err and "hand-kept" not in err, err


def test_a_row_file_that_cannot_be_read_exits_two_and_writes_nothing(tmp_path: Path, capsys) -> None:
    root = make_repo(tmp_path, corpus())
    (root / BOARD_DIR / "2026-10-08-bytes.md").write_bytes(b"\xff\xfe not utf-8")
    assert rb.main([], root=root) == 2 and not (root / PAGE).exists()
    assert "cannot read" in capsys.readouterr().err


def test_a_document_that_cannot_be_read_exits_two_and_writes_no_partial_page(tmp_path: Path, capsys) -> None:
    """The docs check records an undecodable document instead of raising; the page would silently miss its row."""
    root = make_repo(tmp_path, corpus())
    (root / "Docs/design/y.md").write_bytes(b"# Y\n\n\xff\xfe not utf-8\n")
    assert rb.main([], root=root) == 2 and not (root / PAGE).exists()
    err = capsys.readouterr().err
    assert "cannot read Docs/design/y.md" in err, err


def test_a_page_that_cannot_be_written_exits_two_and_leaves_nothing_behind(tmp_path: Path, capsys) -> None:
    root = make_repo(tmp_path, corpus())
    (root / PAGE).mkdir()  # a directory where the page goes
    assert rb.main([], root=root) == 2
    assert "cannot write" in capsys.readouterr().err
    assert [p.name for p in (root / "Docs/plan").iterdir() if p.name.startswith("BOARD.md.")] == []


def test_the_command_line_exits_with_the_same_codes(tmp_path: Path) -> None:
    root = make_repo(tmp_path, corpus())
    done = subprocess.run([sys.executable, str(TOOL), "--root", str(root)], capture_output=True, text=True)
    assert done.returncode == 0 and "board: wrote Docs/plan/BOARD.md" in done.stdout
    bad = subprocess.run([sys.executable, str(TOOL), "--root", str(root / "nowhere")], capture_output=True, text=True)
    assert bad.returncode == 2


# --------------------------------------------------------------------------- the docs check and the page
def test_the_docs_check_passes_with_the_page_absent_rendered_and_hand_edited(tmp_path: Path) -> None:
    root = make_repo(tmp_path, corpus())
    assert cd.run(cd.load_context(root)) == []  # absent: the links to it resolve anyway
    assert rb.main([], root=root) == 0
    assert cd.run(cd.load_context(root)) == []  # rendered: skipped
    page = root / PAGE
    page.write_text(page.read_text(encoding="utf-8") + "\n[broken](nowhere.md)\n", encoding="utf-8")
    assert cd.run(cd.load_context(root)) == []  # hand-edited but still the rendered page: skipped, never read
    page.write_text("# The Board\n\n**Status:** Living.\n\n## Gates\n\nNone.\n", encoding="utf-8")
    found = cd.run(cd.load_context(root))
    assert [f.check for f in found] == ["board"] and "two trackers" in found[0].detail


# --------------------------------------------------------------------------- each row's artifacts
BUILD = "2026-10-02-build-it"


def _board_line(prefix: str) -> str:
    return f"**Board:** [`{BUILD}`]({prefix}plan/board/{BUILD}.md)"


def test_each_row_lists_the_files_that_name_it_one_of_each_kind(tmp_path: Path) -> None:
    files = corpus()
    files["Docs/superpowers/specs/s.md"] = (
        f"# S\n\n**Status:** Accepted.\n{_board_line('../../')}\n\n## Terms introduced\n\nNone.\n"
    )
    files["Docs/superpowers/plans/p.md"] = (
        f"# P\n\n**Status:** Accepted.\n{_board_line('../../')}\n\n## Terms introduced\n\nNone.\n"
    )
    files["Docs/decisions/ADR-001-one.md"] = f"# ADR\n\n**Status:** Accepted.\n{_board_line('../')}\n\nText.\n"
    files["Docs/journal/2026-10-11-session-01.md"] = (
        f"# Session 01\n\n### Work\n**By:** @ada · **Agent:** none\n{_board_line('../')}\n\nWork.\n"
    )
    code, text = render_in(make_repo(tmp_path, files))
    assert code == 0
    section = text.split("## Artifacts", 1)[1]
    assert section.startswith("\n\n### [Build it](board/2026-10-02-build-it.md)\n")
    for rel in (
        "Docs/decisions/ADR-001-one.md",
        "Docs/design/x.md",
        "Docs/journal/2026-10-11-session-01.md",
        "Docs/superpowers/plans/p.md",
        "Docs/superpowers/specs/s.md",
    ):
        assert f"- [`{rel}`](../{Path(rel).relative_to('Docs').as_posix()})" in section, section
    listed = [line for line in section.splitlines() if line.startswith("- ")]
    assert listed == sorted(listed) and len(listed) == 5


def test_an_artifact_link_is_percent_encoded_and_still_resolves(tmp_path: Path, capsys) -> None:
    """A space in a file name breaks the link, and a ``#`` becomes a fragment."""
    files = corpus()
    files["Docs/superpowers/specs/my spec #1.md"] = (
        f"# S\n\n**Status:** Accepted.\n{_board_line('../../')}\n\n## Terms introduced\n\nNone.\n"
    )
    repo = make_repo(tmp_path, files)
    code, text = render_in(repo)
    assert code == 0
    assert "(../superpowers/specs/my%20spec%20%231.md)" in text, text
    capsys.readouterr()
    cd.main([str(repo)], env={}, git=lambda argv: (128, "", "fatal: not a git repository"))
    assert "BOARD.md" not in capsys.readouterr().out


def test_a_board_line_in_a_body_is_not_an_artifact_and_a_row_named_nowhere_is_not_listed(tmp_path: Path) -> None:
    files = corpus()
    files["Docs/design/x.md"] = (
        "# A design\n\n**Status:** Accepted.\n**Board:** none (a test)\n\n## Body\n\n"
        f"{_board_line('../')}\n\n## Terms introduced\n\nNone.\n"
    )
    code, text = render_in(make_repo(tmp_path, files))
    assert code == 0
    assert text.split("## Artifacts", 1)[1].strip().startswith("None.")
    assert "### [Then this]" not in text
