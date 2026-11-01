"""
Framework: render the board page from the row files of a board in directory form.
Package: tools/render_board

    uv run python tools/render_board.py            # the same as --write: render the board page from <board_dir>
    uv run python tools/render_board.py --print    # the same text on standard output; writes nothing

``make board`` runs the first form; the command is the interface and the target is a convenience.

A board in directory form keeps one file per row under ``board_dir`` (``Docs/plan/board/``), named
``YYYY-MM-DD-<slug>.md``, each with a title and the header lines its section needs (``check_docs`` holds the rules). The
page is the configured board path (``Docs/plan/BOARD.md``): a section per board heading in the fixed order Gates, Now,
Next, Blocked, Icebox, each a table of the section's rows (open rows first, newest first by the file's day and then its
slug; done rows after them, struck through; ``None.`` when there are none), then ``## By owner``, each login's open rows
of every section but the Icebox. It is **derived and not committed** (git-ignored, and the docs check skips exactly that
path once row files exist), so a pull request that adds a row never edits the page and the page cannot drift.

Every inline markdown link in a rendered field is rebased from the row file's directory to the page's, so a link that
resolves from a row resolves from the page; a reference-style link in a field does not resolve on the page (its
definition lives in the body, which is not rendered), so a field writes inline links. The roster is not read here: the
docs check holds a row's logins to it, and the page renders whatever the rows say.

Exit codes: 0 written; 1 a row file failed the header rules (the page is still written, and the row is listed under
``## Unreadable rows``); 2 something could not be read or written (the configuration, the board directory, a row file,
the page), or the board is not in directory form (no row file under ``board_dir``: the board is hand-kept and there is
nothing to render). ``--root PATH`` points it at another repository (the default is the one this file is in); ``-v``
logs what it read, decided and wrote to standard error.
"""

from __future__ import annotations

import argparse
import logging as _logging
import os
import posixpath
import re
import sys
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import check_docs as cd
import framework_config as fc

_MODULE_NAME = "tools.render_board"
__version__ = "0.1.0"
__updated__ = "2026-10-29"
_LOGGER = _logging.getLogger(_MODULE_NAME)

ROOT = Path(__file__).resolve().parents[1]
HEADER = cd.BOARD_HEADER
#: An inline markdown link: the text, the destination (bare, or in angle brackets, which may hold spaces), and anything
#: after a space inside the parentheses (a title).
_LINK_RE = re.compile(r"\[([^\]]*)\]\((?:<([^>\n]*)>|([^)\s]+))((?:\s[^)]*)?)\)")


class BoardError(Exception):
    """Something the tool could not read or write, or a board that is hand-kept; ``main`` reports it and exits 2."""


@dataclass(frozen=True)
class Rendered:
    """A row read for the page: the parsed row and the problems the rules found with it."""

    row: cd.Row
    problems: tuple[str, ...]

    @property
    def sort_key(self) -> tuple[str, str]:
        return (self.row.day, self.row.slug)


# -------------------------------------------------------------------------
# reading the rows
def _configuration(base: Path) -> fc.DocsConfig:
    path = base / "framework.toml"
    if not path.exists():
        _LOGGER.info(f"no framework.toml under {base}: the default board paths apply")
        return fc.DocsConfig()
    try:
        config = fc.load_framework(path)
    except fc.ConfigError as e:
        raise BoardError(f"cannot read {path}: {e}") from e
    docs = config.docs
    if docs.board_sections != fc.DocsConfig().board_sections:
        _LOGGER.info(
            "board_sections is set in framework.toml; it applies to a hand-kept board only and is ignored here"
        )
    _LOGGER.info(f"read {path}: board directory {docs.board_dir}, page {docs.board}")
    return docs


def read_rows(base: Path, docs: fc.DocsConfig) -> list[Rendered]:
    """Every row file under the board directory, parsed, with the problems the rules found; a file that is not a row
    file is left alone (the docs check's finding), and a row file that cannot be read stops the run."""
    directory = base / docs.board_dir
    try:
        names = sorted(entry.name for entry in directory.iterdir())
    except OSError as e:
        raise BoardError(f"cannot list the board directory {directory}: {type(e).__name__}: {e}") from e
    rows: list[Rendered] = []
    for name in names:
        if cd.row_file_name(name) is None:
            continue
        try:
            text = (directory / name).read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError) as e:
            raise BoardError(f"cannot read {directory / name}: {type(e).__name__}: {e}") from e
        rel = posixpath.join(docs.board_dir, name)
        row = cd.parse_row(rel, text)
        rows.append(Rendered(row, tuple(cd.row_problems(row, set()))))
    _LOGGER.info(f"read {len(names)} entries in {directory}: {len(rows)} row file(s)")
    if not rows:
        raise BoardError(f"no row file under {docs.board_dir}: the board is hand-kept, and there is nothing to render")
    return rows


# -------------------------------------------------------------------------
# the page
def _plain(text: str) -> str:
    """``text`` with every control, format and line- or paragraph-separator character turned into a space, so a field
    cannot split a table row or reorder the text around it."""
    return "".join(" " if unicodedata.category(char) in ("Cc", "Cf", "Zl", "Zp") else char for char in text)


def _cell(text: str) -> str:
    """A field as a table cell: plain, pipes escaped, the markdown it carries (links, emphasis) kept."""
    return _plain(text).replace("|", "\\|").strip()


def rebase_links(text: str, from_dir: str, to_dir: str) -> str:
    """``text`` with every relative link destination rewritten from ``from_dir`` to ``to_dir`` (repository-relative
    POSIX directories). A URL, a fragment-only link and a root-relative link are left as they are."""

    def rewrite(match: re.Match[str]) -> str:
        label, bracketed, bare, rest = match.group(1), match.group(2), match.group(3), match.group(4)
        target = bracketed if bracketed is not None else bare
        if target.startswith(("#", "/")) or re.match(r"^(?://|[A-Za-z][A-Za-z0-9+.-]+:)", target):
            return match.group(0)
        path, sep, fragment = target.partition("#")
        absolute = posixpath.normpath(posixpath.join(from_dir, path)) if path else ""
        moved = posixpath.relpath(absolute, to_dir) if absolute else ""
        destination = f"<{moved}{sep}{fragment}>" if bracketed is not None else f"{moved}{sep}{fragment}"
        return f"[{label}]({destination}{rest})"

    return _LINK_RE.sub(rewrite, text)


def _title_link(rendered: Rendered, page_dir: str) -> str:
    row = rendered.row
    target = posixpath.relpath(row.rel, page_dir)
    return f"[{_cell(row.title) or row.slug}]({target})"


def _owner(row: cd.Row) -> str:
    return _cell(row.owner) if row.owner else "none"


def _section_rows(rows: list[Rendered], section: str) -> list[Rendered]:
    members = [r for r in rows if not r.problems and r.row.section == section]
    open_rows = sorted((r for r in members if not r.row.done), key=lambda r: r.sort_key, reverse=True)
    done_rows = sorted((r for r in members if r.row.done), key=lambda r: r.sort_key, reverse=True)
    return open_rows + done_rows


def render(rows: list[Rendered], docs: fc.DocsConfig) -> str:
    """The page text for ``rows``: the sections in order, then the view by owner, then the unreadable rows."""
    board_dir, page_dir = docs.board_dir, posixpath.dirname(docs.board)

    def rebase(text: str) -> str:
        return rebase_links(_cell(text), board_dir, page_dir)

    lines = [
        HEADER,
        "",
        "# The board",
        "",
        f"Rendered from the row files under `{board_dir}/` by `tools/render_board.py` (`make board`); not committed.",
        "A row is one file there: change the row, not this page. Open rows first, newest first; done rows struck.",
    ]
    for section in cd.BOARD_SECTIONS:
        lines += ["", cd.BOARD_HEADINGS[section], ""]
        members = _section_rows(rows, section)
        if not members:
            lines.append("None.")
            continue
        if section == "gate":
            lines += ["| Gate | Decider | State |", "| --- | --- | --- |"]
        elif section == "icebox":
            lines += ["| Idea | Owner | Cost | Verdict | State |", "| --- | --- | --- | --- | --- |"]
        else:
            lines += ["| Row | Owner | State |", "| --- | --- | --- |"]
        for r in members:
            row = r.row
            title = _title_link(r, page_dir)
            if row.done:
                title = f"~~{title}~~"
            state = rebase(row.state)
            if section == "gate":
                decider = _cell(row.lines.get("Decider", "")) or "the owner"
                lines.append(f"| {title} | {decider} | {state} |")
            elif section == "icebox":
                cost = rebase(row.lines.get("Cost", ""))
                verdict = rebase(row.lines.get("Verdict", ""))
                lines.append(f"| {title} | {_owner(row)} | {cost} | {verdict} | {state} |")
            else:
                lines.append(f"| {title} | {_owner(row)} | {state} |")
    lines += ["", "## By owner", ""]
    owners: dict[str, list[tuple[str, Rendered]]] = {}
    for r in rows:
        row = r.row
        if r.problems or row.done or row.section == "icebox" or not row.owner.startswith("@"):
            continue
        owners.setdefault(row.owner.lower(), []).append((row.section, r))
    if not owners:
        lines.append("None.")
    for login in sorted(owners):
        shown = max((r for _, r in owners[login]), key=lambda r: r.sort_key).row.owner  # the newest row's spelling
        lines += [f"### {_cell(shown)}", ""]
        ordered = sorted(owners[login], key=lambda pair: (cd.BOARD_SECTIONS.index(pair[0]), pair[1].sort_key))
        for section, r in ordered:
            lines.append(f"- {cd.BOARD_HEADINGS[section][3:]}: {_title_link(r, page_dir)}: {rebase(r.row.state)}")
        lines.append("")
    unreadable = [r for r in rows if r.problems]
    if unreadable:
        lines += ["## Unreadable rows", ""]
        for r in sorted(unreadable, key=lambda r: r.row.rel):
            target = posixpath.relpath(r.row.rel, page_dir)
            lines.append(f"- [{posixpath.basename(r.row.rel)}]({target}): {'; '.join(_cell(p) for p in r.problems)}")
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def _is_rendered(page: Path) -> bool:
    """The page carries the generated header, so it is a rendered page and may be replaced; a page that cannot be read
    is not one either."""
    try:
        return page.read_text(encoding="utf-8-sig").split("\n", 1)[0].strip() == HEADER
    except (OSError, UnicodeDecodeError):
        return False


def write_page(page: Path, text: str) -> None:
    temporary: Path | None = None
    try:  # written beside the page and moved over it, so a failed write cannot leave half a page
        page.parent.mkdir(parents=True, exist_ok=True)  # the page's folder need not exist yet (a configured path)
        handle, name = tempfile.mkstemp(dir=page.parent, prefix=page.name + ".", suffix=".tmp")
        temporary = Path(name)
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
        temporary.chmod(0o644)
        os.replace(temporary, page)
    except OSError as e:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise BoardError(f"cannot write {page}: {type(e).__name__}: {e}") from e


def _emit(text: str) -> None:
    """Write ``text`` to standard output as UTF-8 bytes with the newlines it has, so ``--print`` is byte for byte what
    ``--write`` puts in the file, whatever the console's codec or newline translation."""
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is None:
        sys.stdout.write(text)
        return
    sys.stdout.flush()
    buffer.write(text.encode("utf-8"))
    buffer.flush()


# -------------------------------------------------------------------------
def main(argv: list[str] | None = None, root: Path | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true", help="render the page (the default)")
    mode.add_argument("--print", action="store_true", dest="show", help="print the page text; write nothing")
    parser.add_argument("--root", type=Path, default=None, help="the repository to read (default: this one)")
    parser.add_argument("-v", "--verbose", action="store_true", help="log what was read, decided and written")
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):  # rows may hold non-ASCII text; reporting them must not crash
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="backslashreplace")
    if args.verbose:
        _logging.basicConfig(level=_logging.INFO, format="%(message)s", stream=sys.stderr)
    base = args.root if args.root is not None else (root if root is not None else ROOT)
    if not base.is_dir():
        print(f"board: cannot run: {base} is not a directory", file=sys.stderr)
        return 2
    try:
        docs = _configuration(base)
        rows = read_rows(base, docs)
        text = render(rows, docs)
        unreadable = [r for r in rows if r.problems]
        findings = sys.stderr if args.show else sys.stdout  # --print's standard output is the page and nothing else
        for r in unreadable:
            for problem in r.problems:
                print(f"[board] {r.row.rel}: {problem}", file=findings)
        if args.show:
            _emit(text)
        else:
            page = base / docs.board
            if page.is_file() and not _is_rendered(page):
                raise BoardError(
                    f"{docs.board} exists and is not a rendered page (no generated header): a hand-kept board beside "
                    "row files is two trackers, and rendering over it would lose it; convert or delete it first"
                )
            write_page(page, text)
            _LOGGER.info(f"wrote {docs.board}: {len(rows)} row(s), {len(unreadable)} unreadable")
            print(f"board: wrote {docs.board} ({len(rows)} rows)")
        return 1 if unreadable else 0
    except BoardError as e:
        print(f"board: cannot run: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
