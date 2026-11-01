"""
Framework: documentation consistency checks, the mechanised half of the definition of done.
Package: tools/check_docs

Every check exists because a drift happened in one of the repositories the framework was extracted from: a renamed file
left links dangling, a document without a status read as live long after it was not, a journal entry was linked from
nowhere, a gate scanned zero files and passed. One check, one name; the names are the ones the definition of done
lists (``Docs/standards/definition-of-done.md``, "What the docs check catches") and a test compares the two.

Checks, in the order they run:

- **corpus**: at least one markdown file was scanned (every other check passes vacuously over nothing), and every
  file could be read
- **links**: every relative markdown link, inline or reference-style, resolves to a file with that exact spelling (a
  case-insensitive disk says yes where Linux CI says no); code is skipped; a link may not climb above the root
- **fences**: a fenced code block that never closes (without this, the links and status checks go silently vacuous
  for the rest of that file)
- **status**: every document in a governed directory carries ``**Status:**`` in its first 12 lines and its first word
  is one of ``STATUS_WORDS`` (a closed set; ``Draft`` and ``Done`` are findings); a ``Superseded`` one says by what
- **single-status**: a governed document declares its status once, because the check reads only the first 12 lines
  and a second declaration further down would hide
- **status-copy**: a status written beside a link to a governed document (after it, before it, or in a table cell) is
  the one on that document's own ``**Status:**`` line; a copy goes stale when the document moves; the journal is exempt
- **journal-index**, **journal-day**: every ``YYYY-MM-DD-session-NN.md`` at the top of the journal directory is a row
  in the journal index (a ``YYYY-MM-DD-<login>-HHMM.md`` file needs none, and lives in its month folder ``YYYY-MM/``:
  one elsewhere, an old-form file in a month folder, a stray file there, or a month folder that is not a month is a
  finding); the day the handoff was last updated has a journal file of that date
  or later, and the day a per-login handoff was last updated has a new-form journal file of that login
- **journal-author**: with a ``[[people]]`` roster, every new-form session file has a summary and every entry names
  its author, and every login named is on the roster
- **adr-index**: every ``ADR-NNN-*.md`` or ``ADR-YYYY-MM-DD-<slug>.md`` is a row in the decisions index and every
  indexed one exists
- **adr-duplicate**: two ADR files with one ADR id (a number, or a date and slug); a dated name with an unreal day, no
  slug, or a slug that breaks the rule
- **board**: a hand-kept board exists and keeps its sections; a board in directory form (row files under
  ``board_dir``) has a title and the header lines its section needs on every row file, nothing else in the directory,
  and no hand-kept page beside the rows
- **landed-rows**: a struck-through board row, or a row file whose state starts with ``Landed``, names the pull
  request that landed it
- **handoff**: the handoff exists, carries a real ``**Last updated:**`` date and is within ``handoff_max_lines``;
  a per-login handoff (``<handoff_people_dir>/<login>.md``, that person's session truth) is held to the same two rules,
  is named for a login that is on the roster when there is one, and nothing else lives in that directory
- **adr-refs**: ADR relation headers (``Superseded by``/``Supersedes``, ``Extended by``/``Extends``) point both ways
- **glossary-row**, **terms**, **vocabulary**: every row of the glossary's retired table parses into one enforceable
  term; every design, spec and plan carries a *Terms introduced* section whose terms have glossary rows; a retired
  term is used only on a line that names its replacement
- **orphan**: every governed document is linked from another document (an extension beside its base is reached
  through the base, as a session file is through the index)
- **extension-base**: a governed ``<name>-project.md`` has its base ``<name>.md`` beside it; the journal, the board
  and the per-login handoff directories are not read (there a name is a session, a row or a login)
- **nested-instructions**: no instruction file below the repository root (``instructions_allow`` for a deliberate one)

Where the checks look and what they leave alone is the ``[docs]`` table of ``framework.toml`` (see
``framework_config.DocsConfig``); the status words are not configurable, on purpose.

**What counts as a link, and what does not.** Markdown is not regular, so this reads the shapes documents actually use
and says which it skips. Read: inline links and images (the destination may hold balanced parentheses, a ``<...>``
form, a ``?query`` and a ``#fragment``, and is percent-decoded), reference definitions (not footnotes), a leading
``/`` meaning the repository root. Skipped: fenced code (any indentation, in a block quote too), inline code spans and
HTML comments (they may span lines; an unclosed ``<!--`` is plain text), URLs (``scheme:`` of two or more letters,
or ``//``). Also read: ``href=`` and ``src=`` attributes, and a link whose text wraps across the lines of a paragraph.
**Not handled**, each a false positive or negative a person can avoid with a fence, the angle form or a one-line link:
an indented (four-space) code block outside a list, and a heading indented four spaces, which both read as prose; a code
span split across lines; a destination holding ``[`` or ``]`` outside the ``<...>`` form; a destination that wraps.

Run standalone (exit code 0 clean, 1 findings, 2 the configuration or the arguments are unusable)::

    uv run python tools/check_docs.py [-v] [root]

``-v`` logs what the run read and decided (the root, whether ``framework.toml`` was found, the modules in force, the
file count and the findings per check) to standard error. ``tests/test_check_docs.py`` proves each check can fail, on
a fixture broken in exactly its rule.
"""

from __future__ import annotations

import logging as _logging
import os
import posixpath
import re
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date
from functools import cached_property
from pathlib import Path
from urllib.parse import unquote

import framework_config as fc

# -------------------------------------------------------------------------
# module global scope
_MODULE_NAME = "tools.check_docs"
__version__ = "0.4.0"
__updated__ = "2026-10-11"
_LOGGER = _logging.getLogger(_MODULE_NAME)

#: The closed set of document statuses. A reader must be able to tell a decision from a hypothesis and a live document
#: from a stale one, and a free-form word (``Adopted``, ``Draft``, ``Done``) is a third thing nobody can query.
STATUS_WORDS = ("Proposed", "Accepted", "Living", "Superseded", "Abandoned")
STATUS_WINDOW = 12
#: Directories no configuration can put back in the corpus: other checkouts and installed packages.
ALWAYS_EXCLUDED = (".git", ".venv", "node_modules", "__pycache__")
DERIVED_INDEX = "INDEX.md"  # in the journal directory: exactly this path is skipped, and not configurable
#: A destination longer than this is not a link; it also bounds the work done per link-looking run of characters.
_MAX_DESTINATION = 2000

#: A fence opens with three or more backticks or tildes at any indentation (a fence inside a list item is indented).
_FENCE_RE = re.compile(r"^(`{3,}|~{3,})(.*)$")  # applied after the block-quote prefix and indentation are removed
_QUOTE_PREFIX_RE = re.compile(r"^[ \t]*(?:>[ \t]?)*")
#: ``\[`` and ``\]`` are text, not link syntax; blanked (to two spaces) before links are read, wherever they sit.
_ESCAPED_BRACKET_RE = re.compile(r"\\[\[\]]")
#: A reference definition ``[label]: destination "title"``: nothing else may follow the destination, so
#: ``[Note]: this is important`` is prose; ``[^1]: text`` is a footnote, not a link.
_REFDEF_RE = re.compile(
    r"^ {0,3}\[(?!\^)[^\]]{1,999}\]:[ \t]*(<[^>]*>|\S+)(?:[ \t]+(?:\"[^\"]*\"|'[^']*'|\([^)]*\)))?[ \t]*$"
)
#: ``href="..."`` and ``src='...'`` in inline HTML.
_HTML_ATTR_RE = re.compile(r"\b(?:href|src)[ \t]*=[ \t]*(?:\"([^\"]*)\"|'([^']*)')", re.IGNORECASE)
#: ``**Status:** word`` or ``**Status**: word``, optionally in a block quote or indented.
_STATUS_LINE_RE = re.compile(r"^[ \t]*(?:>[ \t]*)*\*\*Status(?::\*\*|\*\*:)[ \t]*(.*)$")
_LAST_UPDATED_RE = re.compile(r"^[ \t]*(?:>[ \t]*)*\*\*Last updated(?::\*\*|\*\*:)[ \t]*(\S*)", re.MULTILINE)
_SESSION_FILE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}-session-[0-9]{2}\.md\Z")  # ASCII digits, no trailing newline
# the new form: a login (1 to 39 letters, digits and single hyphens), then the session's start, HHMM, in UTC
_NEW_SESSION_RE = re.compile(
    rf"[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}-(?P<login>{fc.LOGIN_PATTERN})-(?P<hhmm>[0-9]{{4}})\.md\Z"
)
_DATED_RE = re.compile(r"^([0-9]{4}-[0-9]{2}-[0-9]{2})-")
#: A month folder of the journal, ``YYYY-MM``; whether the month is real is the check's to say.
MONTH_DIR_RE = re.compile(r"[0-9]{4}-[0-9]{2}\Z")
#: An extension's file name: its base's name and ``-project`` (``python-project.md`` extends ``python.md``).
_EXTENSION_RE = re.compile(r"(?P<base>.+)-project\.md\Z")
#: A per-login handoff's file name: a login and ``.md``, nothing else (no README: ``readme`` is a login GitHub permits).
_LOGIN_FILE_RE = re.compile(rf"(?P<login>{fc.LOGIN_PATTERN})\.md\Z")
#: Names Windows reserves as file stems, any case: a checkout there could not hold such a file.
_WINDOWS_RESERVED = frozenset(
    {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
)
_ADR_FILE_RE = re.compile(r"^adr-\d+", re.IGNORECASE)
#: The dated ADR form, ``ADR-YYYY-MM-DD-<slug>.md``: read before the numbered one, which its digits also match.
_ADR_DATED_RE = re.compile(r"^adr-([0-9]{4}-[0-9]{2}-[0-9]{2})(?:-(.*))?\.md\Z", re.IGNORECASE)
_ADR_NUMBER_RE = re.compile(r"^adr-([0-9]+)", re.IGNORECASE)
# A dated ADR's slug: lowercase letters, digits and single hyphens. Both ADR patterns run on a file name, which the
# operating system bounds (255 bytes), not on a line of text; neither can backtrack quadratically (disjoint pieces).
_SLUG_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_URL_RE = re.compile(r"^(?://|[A-Za-z][A-Za-z0-9+-]+:)")  # a scheme has two or more letters and no dot: not "a.md:3"
#: ``/pull/N`` or a bare ``#N`` that is not an anchor, an entity or a colour (the character before is not a word,
#: slash, dot or ampersand; the one after is not a word character or hyphen; at most five digits, so a six-digit hex
#: colour is not one).
_PR_REF_RE = re.compile(r"/pull/\d+|(?<![\w/.#&-])#\d{1,5}(?![\w-])|\bPRs?[ \t]*#\d{1,5}(?![\w-])")
_TERMS_HEADING_RE = re.compile(r"##[ \t]+Terms introduced[ \t]*#*", re.IGNORECASE)  # matched against a whole line
_NONE_RE = re.compile(r"none\b", re.IGNORECASE)  # the section's first words; anything may follow
_BOLD_RE = re.compile(r"\*\*([^*\n]+)\*\*")
#: ``**Superseded by:** [ADR-002](ADR-002-x.md)`` and its three siblings, optionally in a block quote.
_ADR_REF_RE = re.compile(
    r"^[ \t]*(?:>[ \t]*)*(?:[-*+][ \t]+)?\*\*(Superseded by|Supersedes|Extended by|Extends)(?::\*\*|\*\*:)(.*)$",
    re.IGNORECASE,
)
_ADR_INVERSE = {
    "Superseded by": "Supersedes",
    "Supersedes": "Superseded by",
    "Extended by": "Extends",
    "Extends": "Extended by",
}
_ADR_KIND = {kind.lower(): kind for kind in _ADR_INVERSE}  # the header's spelling, any case, to the canonical one
_INSTRUCTION_NAMES = ("CLAUDE.md", "CLAUDE.local.md", "GEMINI.md", "AGENTS.md")
#: A struck row may say it closed without a pull request, and must then give some reason after the words.
_NO_PR_RE = re.compile(r"\bno pull request\b\W*\w", re.IGNORECASE)
#: The board section whose rows close by a person's decision, not by a pull request.
_DECISION_SECTION = "## Gates"
#: The first line of a rendered board page: a page without it beside row files is a hand-kept page, a second tracker.
BOARD_HEADER = "<!-- generated by tools/render_board.py; not committed; do not edit -->"
#: A row file's sections, in the page's order, and the heading each renders under (fixed in directory form).
BOARD_SECTIONS = ("gate", "now", "next", "blocked", "icebox")
BOARD_HEADINGS = {
    "gate": "## Gates",
    "now": "## Now",
    "next": "## Next",
    "blocked": "## Blocked",
    "icebox": "## Icebox",
}
#: ``YYYY-MM-DD-<slug>.md``: the day the row was written and a slug of lowercase letters, digits and single hyphens.
_ROW_FILE_RE = re.compile(r"(?P<day>[0-9]{4}-[0-9]{2}-[0-9]{2})-(?P<slug>[a-z0-9]+(?:-[a-z0-9]+)*)\.md\Z")
ROW_SLUG_MAX = 60
#: ``**Name:** value`` in a row file's header, the colon inside or outside the bold.
_ROW_LINE_RE = re.compile(r"^\*\*(?P<name>[A-Za-z][A-Za-z ]*?)(?::\*\*|\*\*:)[ \t]*(?P<value>.*)$")
ROW_NAMES = ("Section", "Owner", "State", "Decider", "Cost", "Verdict", "Raised", "Was owned by")
#: Which lines each section requires, allows, and refuses.
_ROW_REQUIRED = {
    "gate": ("Section", "Owner", "State"),
    "now": ("Section", "Owner", "State"),
    "next": ("Section", "Owner", "State"),
    "blocked": ("Section", "Owner", "State"),
    "icebox": ("Section", "Owner", "State", "Cost", "Verdict", "Raised"),
}
_ROW_ALLOWED = {
    "gate": ("Decider", "Raised", "Was owned by"),
    "now": ("Cost", "Raised", "Was owned by"),
    "next": ("Cost", "Raised", "Was owned by"),
    "blocked": ("Cost", "Raised", "Was owned by"),
    "icebox": ("Was owned by",),
}
#: A cost: a number or a range (digits, a decimal, ½ ¼ ¾, ``1 to 2``) and a unit, then optionally an explanation.
_COST_RE = re.compile(
    r"^(?:[0-9]+(?:\.[0-9]+)?|[½¼¾])(?:\s+to\s+(?:[0-9]+(?:\.[0-9]+)?|[½¼¾]))?\s+(?:h|d|w|hours?|days?|weeks?)"
    r"(?:\s*[:,(].*)?$"
)
_RAISED_LINK_RE = re.compile(r"^\[[^\]]+\]\([^)]+\)")
_RAISED_UNRECORDED_RE = re.compile(r"^unrecorded \(converted ([0-9]{4}-[0-9]{2}-[0-9]{2})\)$")
_DONE_RE = re.compile(r"^(?:landed|closed|dropped)\b", re.IGNORECASE)
_LOGIN_AT_RE = re.compile(rf"^@(?P<login>{fc.LOGIN_PATTERN})\Z")


@dataclass(frozen=True)
class Finding:
    """One documentation inconsistency."""

    check: str
    location: str
    detail: str

    def __str__(self) -> str:
        return f"[{self.check}] {self.location}: {self.detail}"


@dataclass(frozen=True)
class Context:
    """The corpus a run reads: the root, the ``[docs]`` configuration and every markdown file's text, read once."""

    root: Path
    docs: fc.DocsConfig
    handoff_max_lines: int
    modules: Mapping[str, str]
    files: tuple[str, ...]  # readable files, repository-relative POSIX paths, sorted
    texts: Mapping[str, str]  # path -> text with any byte-order mark removed
    unreadable: Mapping[str, str] = field(default_factory=dict)  # path -> why it could not be read
    instructions: tuple[str, ...] = ()  # instruction files below the root, found by their own walk
    people: tuple[fc.Person, ...] = ()  # the roster: empty means authorship is not checked
    _listings: dict[str, frozenset[str]] = field(default_factory=dict, compare=False, repr=False)

    def text(self, rel: str) -> str:
        return self.texts.get(rel, "")

    def has(self, rel: str) -> bool:
        """The file exists in the corpus, readable or not (an unreadable one is the ``corpus`` check's finding)."""
        return rel in self.texts or rel in self.unreadable

    def module_on(self, name: str) -> bool:
        return self.modules.get(name) == "on"

    @cached_property
    def board_is_directory(self) -> bool:
        """The board is a directory of row files (at least one exists under ``board_dir``): the page is rendered, a
        link to it resolves unrendered, and the row rules apply. Decided once per run from the corpus."""
        return board_in_directory_form(self.files, self.docs)

    def listing(self, directory: Path) -> frozenset[str]:
        """The names in a directory, cached for the run (case-exact link resolution asks the same ones often)."""
        key = str(directory)
        if key not in self._listings:
            try:
                self._listings[key] = frozenset(entry.name for entry in directory.iterdir())
            except OSError:
                self._listings[key] = frozenset()
        return self._listings[key]


# -------------------------------------------------------------------------
# reading the corpus
def _walk_error_recorder(root: Path, errors: dict[str, str] | None) -> Callable[[OSError], None]:
    """The ``onerror`` for ``os.walk``: a directory that cannot be listed goes into ``errors`` (relative path to
    reason), where the ``corpus`` check reports it, instead of being skipped in silence."""

    def record(error: OSError) -> None:
        if errors is not None:
            where = str(error.filename)
            try:
                where = Path(where).relative_to(root).as_posix()
            except ValueError:
                pass
            errors[where] = f"{type(error).__name__}: {error}"

    return record


def markdown_paths(root: Path, exclude_parts: tuple[str, ...], errors: dict[str, str] | None = None) -> list[str]:
    """Every markdown file under ``root`` outside the excluded directories, as sorted relative POSIX paths.

    Excluded directories (the configured names and ``ALWAYS_EXCLUDED``, matched by name at any depth) are pruned while
    walking, not filtered afterwards: a virtual environment or a vendored tree can hold tens of thousands of files and
    the walk would otherwise visit them all. A directory that cannot be listed is recorded in ``errors`` (path to
    reason) instead of being skipped in silence: a scan that quietly missed a folder is the vacuous pass again.
    """
    skip = set(exclude_parts) | set(ALWAYS_EXCLUDED)

    found: list[str] = []
    for current, dirs, names in os.walk(root, onerror=_walk_error_recorder(root, errors)):
        dirs[:] = sorted(d for d in dirs if d not in skip)
        base = Path(current)
        found += [(base / name).relative_to(root).as_posix() for name in names if name.endswith(".md")]
    return sorted(found)


def instruction_paths(root: Path, errors: dict[str, str] | None = None) -> tuple[str, ...]:
    """Every instruction file (``CLAUDE.md`` and its siblings) below the root, as sorted relative POSIX paths.

    This walk is **not** the documents' walk: ``exclude_parts`` keeps frozen spikes and scratch folders out of the
    consistency checks, but a harness started inside one still loads the instruction file there, and a vendored copy is
    the very case this exists for. Only what is not this repository's own content is skipped: ``ALWAYS_EXCLUDED``, a
    ``.worktrees`` folder and ``.claude/worktrees`` (each is another full checkout, root files and all). A
    directory that cannot be listed is recorded in ``errors``, as the documents' walk does: an incomplete scan of
    exactly the folders this exists to cover must not read as clean.
    """
    names = {name.lower() for name in _INSTRUCTION_NAMES}
    skip = set(ALWAYS_EXCLUDED) | {".worktrees"}
    found: list[str] = []
    for current, dirs, files in os.walk(root, onerror=_walk_error_recorder(root, errors)):
        here = Path(current)
        dirs[:] = sorted(d for d in dirs if d not in skip and not (here.name == ".claude" and d == "worktrees"))
        if here != root:
            found += [(here / name).relative_to(root).as_posix() for name in files if name.lower() in names]
    return tuple(sorted(found))


def load_context(root: Path) -> Context:
    """Read ``framework.toml`` under ``root`` (defaults if it has none) and every markdown file.

    Raises ``ConfigError`` when ``framework.toml`` is invalid.
    """
    root = Path(root)
    config_path = root / "framework.toml"
    if config_path.exists():
        config = fc.load_framework(config_path)
        docs, limit, modules, people = config.docs, config.handoff_max_lines, config.modules, config.people
        _LOGGER.info(
            f"read {config_path}: handoff limit {limit}, journal {modules['journal']}, {len(people)} on the roster"
        )
    else:
        docs, limit, modules = fc.DocsConfig(), fc.DEFAULT_HANDOFF_MAX_LINES, {"core": "on", "journal": "on"}
        people = ()
        _LOGGER.info(f"no framework.toml under {root}: the framework's defaults apply (handoff limit {limit})")
    texts: dict[str, str] = {}
    unreadable: dict[str, str] = {}
    derived = posixpath.join(docs.journal_dir, DERIVED_INDEX)  # rendered, git-ignored, never read: it cannot drift
    paths = [rel for rel in markdown_paths(root, docs.exclude_parts, unreadable) if rel != derived]
    if board_in_directory_form(paths, docs):  # then the board page is rendered too, and skipped the same way
        paths = [rel for rel in paths if rel != docs.board]
    instructions = instruction_paths(root, unreadable)
    for where in unreadable:
        _LOGGER.warning(f"skipped {where}: it could not be listed; the corpus check reports it")
    for rel in paths:
        try:
            texts[rel] = (root / rel).read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError) as e:
            unreadable[rel] = f"{type(e).__name__}: {e}"
            _LOGGER.warning(f"skipped {rel}: it could not be read ({type(e).__name__}); the corpus check reports it")
    excluded = ", ".join((*docs.exclude_parts, *ALWAYS_EXCLUDED, derived))
    _LOGGER.info(f"read {len(texts)} markdown file(s) under {root}, excluding {excluded}")
    return Context(root, docs, limit, modules, tuple(texts), texts, unreadable, instructions, people)


# -------------------------------------------------------------------------
# markdown helpers
def split_lines(text: str) -> list[str]:
    """The lines of ``text`` split on ``\\n``, ``\\r\\n`` and ``\\r`` only (``str.splitlines`` also splits on U+2028,
    form feed and others, which a document may legitimately contain and which would inflate a line count)."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def prose_lines(text: str) -> tuple[list[tuple[int, str]], int | None]:
    """The lines of a markdown document outside fenced code blocks, with their 1-based numbers, and the line a fence
    that never closed was opened on (``None`` when every fence closes).

    Line-oriented, as CommonMark reads fences: one opens with three or more backticks or tildes (at any indentation,
    after any block-quote markers; a backtick fence's opening line holds no further backtick, so an inline
    ```code``` span is not a fence) and closes with a fence of the same character at least as long and nothing else on
    the line; a fence of the other character inside stays code. An unclosed fence's lines are kept as prose so every
    check stays live for the rest of the file and ``check_fences`` can report the fence.
    """
    out: list[tuple[int, str]] = []
    held: list[tuple[int, str]] = []
    fence_char, fence_len, opened_at = "", 0, None
    for number, line in enumerate(split_lines(text), start=1):
        quote = _QUOTE_PREFIX_RE.match(line)
        inner = line[quote.end() :] if quote else line
        m = _FENCE_RE.match(inner)
        if not fence_char:
            if m and (m.group(1)[0] == "~" or "`" not in m.group(2)):
                fence_char, fence_len, opened_at = m.group(1)[0], len(m.group(1)), number
                held = []
                continue
            out.append((number, line))
        elif m and m.group(1)[0] == fence_char and len(m.group(1)) >= fence_len and not m.group(2).strip():
            fence_char = ""
        else:
            held.append((number, line))
    if fence_char:
        out.extend(held)
    return _without_comments(out), (opened_at if fence_char else None)


def prose(text: str) -> str:
    """The prose of a markdown document, fenced code and HTML comments removed; see ``prose_lines``."""
    return "\n".join(line for _, line in prose_lines(text)[0])


def _blank_comments(text: str) -> str:
    """``text`` with every HTML comment replaced by spaces (newlines kept, so line structure survives).

    A ``<!--`` inside an inline code span does not open a comment, and one that never closes is plain text: the
    first version let a document that merely mentioned the marker hide everything after it from the link check.
    """
    shadow = "\n".join(_blank_code_spans(line) for line in text.split("\n"))  # same length as text
    parts: list[str] = []
    i = 0
    while True:
        start = shadow.find("<!--", i)
        stop = shadow.find("-->", start + 4) if start >= 0 else -1
        if stop < 0:
            parts.append(text[i:])
            return "".join(parts)
        parts.append(text[i:start])
        parts.append(re.sub(r"[^\n]", " ", text[start : stop + 3]))
        i = stop + 3


def _without_comments(lines: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """``lines`` with HTML comments blanked, keeping the line numbers (a comment may span lines)."""
    if not lines:
        return []
    blanked = _blank_comments("\n".join(line for _, line in lines)).split("\n")
    return [(number, text) for (number, _), text in zip(lines, blanked, strict=True)]


def _blank_code_spans(line: str) -> str:
    """``line`` with inline code spans (a backtick run to the next run of the same length) replaced by spaces.

    Linear: the next run of each length is found in one backwards pass, so a line of many backticks costs no more
    than a line of few.
    """
    runs = [(m.start(), m.end()) for m in re.finditer(r"`+", line)]
    if not runs:
        return line
    following: list[int | None] = [None] * len(runs)
    last_of_length: dict[int, int] = {}
    for index in range(len(runs) - 1, -1, -1):
        length = runs[index][1] - runs[index][0]
        following[index] = last_of_length.get(length)
        last_of_length[length] = index
    chars = list(line)
    index = 0
    while index < len(runs):
        closer = following[index]
        if closer is None:
            index += 1
            continue
        for position in range(runs[index][0], runs[closer][1]):
            chars[position] = " "
        index = closer + 1
    return "".join(chars)


def _destination_at(line: str, start: int) -> str | None:
    """The link destination that starts at ``start`` (just after ``](``), or ``None`` if there is none.

    It ends at whitespace, at a ``[`` or ``]``, or at the ``)`` that balances the opening one; the angle form
    ``<...>`` may hold anything but ``>``. Both stop before the next ``]`` or within ``_MAX_DESTINATION`` characters,
    so the work over a whole line is linear.
    """
    size = len(line)
    while start < size and line[start] in " \t":
        start += 1
    if start < size and line[start] == "<":
        stop = line.find(">", start + 1, start + 2 + _MAX_DESTINATION)  # bounded: linear on a hostile line
        return line[start + 1 : stop] if stop > 0 else None
    depth, stop = 0, start
    while stop < size and stop - start <= _MAX_DESTINATION:
        char = line[stop]
        if char in " \t[]":
            break
        if char == "(":
            depth += 1
        elif char == ")":
            if depth == 0:
                break
            depth -= 1
        stop += 1
    return line[start:stop] if stop > start else None


def _destinations(line: str, open_before: int = 0) -> tuple[list[str], int]:
    """The link destinations on one line, and the number of ``[`` still open at its end.

    A destination is whatever follows a ``](`` whose ``]`` closes a ``[`` that is open: opened earlier on this line,
    or ``open_before`` of them left open on earlier lines of the paragraph (link text that wraps). The brackets are
    matched in order, so a badge (``[![alt](img)](target)``) yields both its image and its target, and
    ``text](x.md)`` with no opener, or an opener the caller blanked as escaped (``\\[``, ``\\]``), yields nothing.
    """
    found: list[str] = []
    depth = open_before
    for bracket in re.finditer(r"[\[\]]", line):
        if bracket.group() == "[":
            depth += 1
            continue
        if depth > 0 and line.startswith("(", bracket.end()):
            destination = _destination_at(line, bracket.end() + 1)
            if destination is not None:
                found.append(destination)
        depth = max(0, depth - 1)
    return found, depth


def link_targets(text: str) -> list[str]:
    """Every link destination in the prose of ``text``, as a path: fragment and query removed, percent-decoded.

    Empty destinations (a bare ``#fragment``) and URLs are not paths and are dropped. See the module docstring for
    what is read and what is skipped.
    """
    raw: list[str] = []
    depth = 0  # brackets left open in this paragraph: link text may wrap across its lines
    for line in prose(text).split("\n"):
        if not line.strip():
            depth = 0
            continue
        code_free = _ESCAPED_BRACKET_RE.sub("  ", _blank_code_spans(line))
        definition = _REFDEF_RE.match(code_free)
        if definition:
            raw.append(definition.group(1).strip("<>"))
        found, depth = _destinations(code_free, depth)
        raw += found
        raw += [m.group(1) or m.group(2) for m in _HTML_ATTR_RE.finditer(code_free)]
    targets: list[str] = []
    for item in raw:
        cleaned = unquote(item.strip().split("#")[0].split("?")[0].strip())
        if cleaned and not _URL_RE.match(cleaned):
            targets.append(cleaned)
    return targets


def _exists_exact(ctx: Context, base: Path, target: str) -> bool:
    """``target``, relative to ``base``, names something with exactly this spelling, inside the root.

    On a case-insensitive file system ``exists()`` says yes to ``docs/`` when the directory is ``Docs/``; CI on Linux
    says no. Each component is checked against its parent's listing. A ``..`` that would leave the root is a broken
    link: what lies beside the checkout differs per machine. A leading ``/`` means the root, as on GitHub.
    """
    if target.startswith("/"):
        base, target = ctx.root, target.lstrip("/")
    current = base
    for part in target.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if current == ctx.root:
                return False
            current = current.parent
            continue
        if part not in ctx.listing(current):
            return False
        current = current / part
    return current.exists()


def _in_dir(rel: str, directory: str) -> bool:
    return rel.startswith(directory.rstrip("/") + "/")


def _in_scope(rel: str, directory: str, recursive: bool) -> bool:
    """``rel`` is in ``directory`` (``""`` is the root), and directly in it unless ``recursive``."""
    if directory == "":
        return recursive or "/" not in rel
    if not rel.startswith(directory + "/"):
        return False
    return recursive or "/" not in rel[len(directory) + 1 :]


def _real_day(text: str) -> date | None:
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _new_form_time(name: str) -> str | None:
    """The ``HHMM`` of a name in the new form's shape, or ``None`` if the name has another shape or a bad login."""
    match = _NEW_SESSION_RE.match(name)
    if match is None or len(match.group("login")) > fc.LOGIN_MAX:
        return None
    return match.group("hhmm")


def _is_time(hhmm: str) -> bool:
    return int(hhmm[:2]) <= 23 and int(hhmm[2:]) <= 59


def journal_file_form(name: str) -> str | None:
    """``"old"`` for ``YYYY-MM-DD-session-NN.md``, ``"new"`` for ``YYYY-MM-DD-<login>-HHMM.md`` with a real time of day,
    else ``None``. The day is not judged here: a name with an impossible day still has a form. The two cannot be
    confused: the old one ends ``-session-`` and two digits, the new one a hyphen and four."""
    if _SESSION_FILE_RE.match(name):
        return "old"
    hhmm = _new_form_time(name)
    return "new" if hhmm is not None and _is_time(hhmm) else None


def _month_folder(rel: str, journal_dir: str) -> str | None:
    """The ``YYYY-MM`` folder ``rel`` sits directly in, when it sits in one of the journal directory; else ``None``."""
    parent = posixpath.dirname(rel)
    if posixpath.dirname(parent) != journal_dir:
        return None
    name = posixpath.basename(parent)
    return name if MONTH_DIR_RE.fullmatch(name) else None


def _real_month(name: str) -> bool:
    """A month folder's name names a month: ``01`` to ``12`` (the shape is the caller's to have matched)."""
    return 1 <= int(name[5:]) <= 12


def _journal_place(rel: str, journal_dir: str) -> str | None:
    """Where a session-shaped file sits: ``"top"`` (directly in the journal directory), ``"month"`` (directly in a
    month folder of it), or ``None`` (anywhere else, or not a session-shaped name)."""
    if journal_file_form(posixpath.basename(rel)) is None:
        return None
    if _in_scope(rel, journal_dir, False):
        return "top"
    return "month" if _month_folder(rel, journal_dir) is not None else None


def _well_placed(rel: str, journal_dir: str) -> bool:
    """A session file where it belongs: an old-form file at the top, a new-form file in its own month folder."""
    place = _journal_place(rel, journal_dir)
    form = journal_file_form(posixpath.basename(rel))
    if place == "top":
        return form == "old"
    if place == "month":
        return form == "new" and _month_folder(rel, journal_dir) == posixpath.basename(rel)[:7]
    return False


def _session_files(ctx: Context) -> list[str]:
    """The session files in their places: old-form files at the top of the journal directory, new-form files in their
    month folders (the day in a name may not be real). A session-shaped file anywhere else is ``journal-index``'s."""
    return [rel for rel in ctx.files if _well_placed(rel, ctx.docs.journal_dir)]


def _is_session_file(rel: str) -> bool:
    return journal_file_form(posixpath.basename(rel)) is not None


def _session_shaped_in_journal(ctx: Context, rel: str) -> bool:
    """A session-shaped file at the top of the journal, or anything directly in a month folder, well placed or not:
    exempt from ``status`` and ``orphan`` either way, so a misplaced or stray file gets ``journal-index``'s one finding,
    not three."""
    journal_dir = ctx.docs.journal_dir
    return (_is_session_file(rel) and _in_scope(rel, journal_dir, False)) or _month_folder(rel, journal_dir) is not None


def _governed(ctx: Context, rel: str) -> bool:
    """A document that must carry a status: inside a governed directory, not exempt, not a dated session file, not a
    board row file (its state is its ``State:`` line)."""
    if rel in ctx.docs.status_exempt or _session_shaped_in_journal(ctx, rel):
        return False
    if _is_row_file(ctx, rel):
        return False
    return any(_in_dir(rel, d) for d in ctx.docs.governed_dirs)


def _status_of(line: str) -> tuple[str, str] | None:
    """The status word on a ``**Status:**`` line and the text after it, or ``None`` if the line is not one.

    The word is the leading run of letters, so ``**Status:** **Accepted**`` and ``Accepted: because...`` read as
    ``Accepted``; it must end at whitespace, punctuation or a dash, so ``Accepted-ish`` and ``Accepted2026`` are
    not ``Accepted``. An empty word means the line gave none.
    """
    match = _STATUS_LINE_RE.match(line)
    if match is None:
        return None
    rest = match.group(1).lstrip("*_ ")
    word = re.match(r"[A-Za-z]+", rest)
    if word is None:
        return (rest.split()[0] if rest.split() else ""), ""
    tail = rest[word.end() :]
    if tail and not re.match(r"[\s.,:;()*_\u2013\u2014]", tail):
        return rest.split()[0], ""
    return word.group(0), tail


# -------------------------------------------------------------------------
# the checks
def check_corpus(ctx: Context) -> list[Finding]:
    """A scan of nothing is a finding, not a pass; so is a file that could not be read."""
    findings = [
        Finding("corpus", rel, f"could not be read ({why}); every check passed vacuously over it")
        for rel, why in sorted(ctx.unreadable.items())
    ]
    if not ctx.files and not ctx.unreadable:
        findings.append(Finding("corpus", ".", "no markdown files found: every other check passed vacuously"))
    return findings


def check_links(ctx: Context) -> list[Finding]:
    """Every relative markdown link resolves to a file with that exact spelling; code is not prose."""
    findings: list[Finding] = []
    # in directory form the board page is rendered and git-ignored: a link to exactly that path resolves unrendered
    derived_board = ctx.docs.board if ctx.board_is_directory else None
    for rel in ctx.files:
        base = (ctx.root / rel).parent
        for target in link_targets(ctx.text(rel)):
            if derived_board is not None and _resolve(rel, target.split("#", 1)[0]) == derived_board:
                continue
            if not _exists_exact(ctx, base, target):
                findings.append(Finding("links", rel, f"broken link -> {target}"))
    return findings


def check_fences(ctx: Context) -> list[Finding]:
    """A fenced code block that never closes hides the rest of its file from every other check."""
    findings: list[Finding] = []
    for rel in ctx.files:
        unclosed = prose_lines(ctx.text(rel))[1]
        if unclosed is not None:
            findings.append(Finding("fences", rel, f"fence opened at line {unclosed} never closes"))
    return findings


def _document_status(ctx: Context, rel: str) -> tuple[str, str] | None:
    """The first ``**Status:**`` line among the first 12 prose lines of ``rel``, as ``_status_of`` reads it."""
    head = [line for number, line in prose_lines(ctx.text(rel))[0] if number <= STATUS_WINDOW]
    return next((s for s in map(_status_of, head) if s), None)


def check_status(ctx: Context) -> list[Finding]:
    """Governed documents declare ``**Status:** <word>`` in the first 12 lines; a Superseded one says by what."""
    findings: list[Finding] = []
    for rel in ctx.files:
        if not _governed(ctx, rel):
            continue
        status = _document_status(ctx, rel)
        if status is None:
            findings.append(Finding("status", rel, f"no `**Status:**` line in the first {STATUS_WINDOW} lines"))
            continue
        word, tail = status
        if word not in STATUS_WORDS:
            findings.append(Finding("status", rel, f"status {word!r} is not one of {'|'.join(STATUS_WORDS)}"))
        elif word == "Superseded" and not re.match(r"[\s.,:;()*_\u2013\u2014-]*by\**\s+\S", tail):
            findings.append(Finding("status", rel, "Superseded, but the line does not say by what"))
    return findings


def check_single_status(ctx: Context) -> list[Finding]:
    """A governed document declares its document status once.

    ``check_status`` reads only the first 12 lines, deliberately: a status must be where a reader lands. The same window
    hides a second one, which is how a document carried ``Superseded`` at line 3 and its old ``Living`` at line 16
    while every check passed. Only a second line using the governed words counts: a plan may carry a ``**Status:**``
    per section describing a category of work, and flagging those would make this check noise.
    """
    findings: list[Finding] = []
    for rel in ctx.files:
        if not _governed(ctx, rel):
            continue
        statuses = [s for _, line in prose_lines(ctx.text(rel))[0] if (s := _status_of(line))]
        governing = [word for word, _ in statuses if word in STATUS_WORDS]
        if len(governing) > 1:
            findings.append(
                Finding(
                    "single-status",
                    rel,
                    f"declares a document status {len(governing)} times ({', '.join(governing)}); a reader cannot "
                    f"tell which governs, and the status check reads only the first {STATUS_WINDOW} lines",
                )
            )
    return findings


_STATUS_ALT = "|".join(STATUS_WORDS)
# An inline link: its text (one level of nested brackets), destination and title. The opening bracket is required, and
# escaped brackets are masked before the match (as ``link_targets`` reads them). Possessive throughout, so that a long
# run of spaces, brackets or padding is read once and not retried at every split.
_LINK = r"""\[(?:[^\[\]]++|\[[^\[\]]*+\])*+\]\(\s*+([^()\s]*+)(?:\s++"[^"]*+")?+\s*+\)"""
_COPY_AFTER_RE = re.compile(_LINK + r"\s*\((" + _STATUS_ALT + r")(?![\w-])([^()]*)\)")
_COPY_BEFORE_RE = re.compile(r"\((" + _STATUS_ALT + r")(?![\w-])([^()]*)\)\s*:\s*" + _LINK)
_STATUS_CELL_RE = re.compile(r"^[\s*_]*+(" + _STATUS_ALT + r")[\s*_]*+(?:\d{4}-\d{2}-\d{2})?+[\s*_]*+$")
_CELL_BAR_RE = re.compile(r"(?<!\\)\|")
_WORD_RE = re.compile(r"[A-Za-z]+")


def _names_a_second_status(rest: str) -> bool:
    """The text in a parenthesis, after its first status word, names another (``then Accepted``, ``was Proposed``)."""
    return any(word in STATUS_WORDS for word in _WORD_RE.findall(rest))


def check_status_copy(ctx: Context) -> list[Finding]:
    """A status written beside a link to a governed document says what that document's own status line says.

    Three forms, nothing looser (a loose reading finds true text and teaches authors to ignore the check): after a link,
    ``[text](target) (Word``; before one, ``(Word): [text](target)`` (the first link only); and a table cell that is
    exactly a status word beside the one governed link of its row. A parenthesis that names a second status
    (``Proposed then Accepted``, ``Accepted, was Proposed``) is a history, not a copy. The target is resolved with its
    fragment removed and read as ``check_status`` reads it; a target that is not governed, does not resolve or has no
    status is another check's finding, not this one's. Every file inside the journal directory is history, not read.

    What is **not** read, because the forms are exact: a title in single quotes, a destination in ``<...>``, a
    reference-style link, a status on the next wrapped line, a status inside bold, and a status beside a link that
    starts a table row without its leading pipe. What it reads that is not a status: text after the word is ignored
    (the cost of that), so ``(Living with it)`` or ``(Proposed changes to X)`` beside a link is a copy to reword.
    """
    findings: list[Finding] = []
    known = set(ctx.files)
    statuses: dict[str, str | None] = {}

    def status_of_target(rel: str, target: str) -> tuple[str, str] | None:
        cleaned = unquote(target.split("#")[0].split("?")[0].strip())
        if not cleaned or _URL_RE.match(cleaned):
            return None
        path = _resolve(rel, cleaned)
        if path not in known or not _governed(ctx, path):
            return None
        if path not in statuses:
            found = _document_status(ctx, path)
            statuses[path] = found[0] if found else None
        word = statuses[path]
        return (path, word) if word in STATUS_WORDS else None  # another word is the status check's finding

    def report(rel: str, number: int, said: str, target: tuple[str, str]) -> None:
        if said != target[1]:
            findings.append(
                Finding(
                    "status-copy", f"{rel}:{number}", f"says {said} beside {target[0]}, whose status is {target[1]}"
                )
            )

    for rel in ctx.files:
        if _in_dir(rel, ctx.docs.journal_dir):
            continue
        for number, raw in prose_lines(ctx.text(rel))[0]:
            line = _ESCAPED_BRACKET_RE.sub("  ", _blank_code_spans(raw))
            for m in _COPY_AFTER_RE.finditer(line):
                found = None if _names_a_second_status(m.group(3)) else status_of_target(rel, m.group(1))
                if found:
                    report(rel, number, m.group(2), found)
            for m in _COPY_BEFORE_RE.finditer(line):
                found = None if _names_a_second_status(m.group(2)) else status_of_target(rel, m.group(3))
                if found:
                    report(rel, number, m.group(1), found)
            if not line.lstrip().startswith("|"):
                continue
            cells = _CELL_BAR_RE.split(line.strip().strip("|"))
            saids = [m for m in map(_STATUS_CELL_RE.match, cells) if m]
            if not saids:
                continue
            # A status cell holds no link, so the row's governed documents are found once, over all of its cells.
            governed = {
                found
                for text in cells
                for target in re.findall(_LINK, text)
                if (found := status_of_target(rel, target))
            }
            if len(governed) == 1:  # the one governed document of the row, however many links name it
                for said in saids:
                    report(rel, number, said.group(1), next(iter(governed)))
    return findings


def _index_links(ctx: Context, index_rel: str) -> set[str]:
    """The repository-relative paths the index links to, each resolved against the index's own directory."""
    return {_resolve(index_rel, target) for target in link_targets(ctx.text(index_rel))}


def _check_index(
    ctx: Context,
    index_rel: str,
    directory: str,
    name_re: re.Pattern[str],
    recursive: bool,
    check: str,
    also_known: Callable[[str], bool] = lambda name: False,
) -> list[Finding]:
    """Every file in ``directory`` matching ``name_re`` is linked from the index, and every linked one exists.

    A row may also name a file that ``also_known`` accepts (a file that needs no row but may have one); it must exist.
    """
    members = {
        rel for rel in ctx.files if _in_scope(rel, directory, recursive) and name_re.match(posixpath.basename(rel))
    }
    if not members:
        return []
    if not ctx.has(index_rel):
        return [Finding(check, index_rel, "missing; every entry needs a row here")]
    linked = _index_links(ctx, index_rel)
    findings = [Finding(check, index_rel, f"no row links {posixpath.basename(m)}") for m in sorted(members - linked)]
    ghosts = {
        path
        for path in linked - members
        if _in_scope(path, directory, recursive)
        and (
            name_re.match(posixpath.basename(path))
            or (also_known(posixpath.basename(path)) and not ctx.has(path))  # a file that needs no row, but exists
        )
    }
    findings += [
        Finding(check, index_rel, f"row links {posixpath.basename(g)}, which does not exist") for g in sorted(ghosts)
    ]
    return findings


@dataclass(frozen=True)
class AdrId:
    """What names an ADR for the duplicate check: a number (``ADR-005`` and ``ADR-5`` are one id), or a day and a slug.
    The slug is lowercased for comparison and carried as written in ``raw_slug``, which the slug rule reads and equality
    ignores. Hashable: one id is one dictionary key."""

    kind: str  # "number" or "dated"
    number: int | None = None
    day: str | None = None
    slug: str | None = None
    raw_slug: str | None = field(default=None, compare=False)

    @property
    def shown(self) -> str:
        return f"ADR number {self.number}" if self.kind == "number" else f"ADR-{self.day}-{self.slug}"


def adr_id(name: str) -> AdrId | None:
    """The ``AdrId`` of a file name, or ``None`` for a name that is not an ADR's. A name is dated by its shape alone
    (``ADR-``, a day, then optionally a hyphen and a slug, ``.md``), read before the numbered form because its digits
    also match that one; the day and the slug are judged by ``adr-duplicate``, not here."""
    dated = _ADR_DATED_RE.match(name)
    if dated:
        raw = dated.group(2) or ""
        return AdrId("dated", day=dated.group(1), slug=raw.lower(), raw_slug=raw)
    numbered = _ADR_NUMBER_RE.match(name)
    if numbered:
        return AdrId("number", number=int(numbered.group(1)))
    return None


def _adr_files(ctx: Context) -> list[str]:
    """Every ADR file under the decisions index's directory, the index itself excluded."""
    index = ctx.docs.adr_index
    directory = posixpath.dirname(index)
    return sorted(
        rel
        for rel in ctx.files
        if rel != index and _in_scope(rel, directory, True) and _ADR_FILE_RE.match(posixpath.basename(rel))
    )


def check_adr_duplicate(ctx: Context) -> list[Finding]:
    """Two ADR files with one ADR id are a finding on each, naming the other: a numbered collision (two branches each
    added ``ADR-005-*.md`` with different slugs) merges cleanly and is found only here. A dated name whose day is not
    real, or whose slug is not lowercase letters, digits and single hyphens, is a finding too: the id would otherwise
    compare equal to nothing and the name would hide a typo."""
    findings: list[Finding] = []
    by_id: dict[AdrId, list[str]] = {}
    for rel in _adr_files(ctx):
        ident = adr_id(posixpath.basename(rel))
        if ident is None:  # _ADR_FILE_RE matched, so the numbered form read it; kept for a future form
            continue
        if ident.kind == "dated":
            if _real_day(ident.day or "") is None:
                findings.append(Finding("adr-duplicate", rel, f"the day {ident.day} in the name is not a real day"))
            if not ident.raw_slug:
                findings.append(
                    Finding("adr-duplicate", rel, "no slug after the day; a dated ADR is ADR-YYYY-MM-DD-<slug>.md")
                )
            elif not _SLUG_RE.fullmatch(ident.raw_slug):
                detail = f"the slug {ident.raw_slug!r} is not lowercase letters, digits and single hyphens"
                findings.append(Finding("adr-duplicate", rel, detail))
        by_id.setdefault(ident, []).append(rel)
    for ident, rels in by_id.items():
        if len(rels) < 2:
            continue
        if ident.kind == "number":
            why = f"ADR-{ident.number:03d} and ADR-{ident.number} are one number"
        else:
            why = "a date and slug compare without regard to case"
        for rel in rels:
            others = ", ".join(posixpath.basename(o) for o in rels if o != rel)
            findings.append(
                Finding("adr-duplicate", rel, f"shares {ident.shown} with {others} ({why}); one id, one ADR")
            )
    return findings


def check_adr_index(ctx: Context) -> list[Finding]:
    """Every ADR file (``ADR-<number>...``, any case, in the index's directory or below) is a row in the decisions
    index, and every indexed ADR exists."""
    index = ctx.docs.adr_index
    return _check_index(ctx, index, posixpath.dirname(index), _ADR_FILE_RE, True, "adr-index")


def check_journal_index(ctx: Context) -> list[Finding]:
    """Every old-form session file (``YYYY-MM-DD-session-NN.md``) is a row in the journal index and every indexed
    session exists; a row may also name a new-form file (``YYYY-MM-DD-<login>-HHMM.md``), which needs none. A file in
    the journal directory that starts with a date but is in neither form, or names a day that does not exist, is a
    finding, because no index row could require it."""
    if not ctx.module_on("journal"):
        return []
    directory = ctx.docs.journal_dir
    findings = _check_index(
        ctx,
        ctx.docs.journal_index,
        directory,
        _SESSION_FILE_RE,
        False,
        "journal-index",
        lambda name: journal_file_form(name) == "new",
    )
    forms = "YYYY-MM-DD-session-NN.md or YYYY-MM-DD-<login>-HHMM.md"
    for rel in ctx.files:
        name = posixpath.basename(rel)
        at_top = _in_scope(rel, directory, False)
        month = _month_folder(rel, directory)
        if (not at_top and month is None) or rel == ctx.docs.journal_index:
            continue
        dated = _DATED_RE.match(name)
        hhmm = _new_form_time(name)
        form = journal_file_form(name)
        if dated and form is None:
            if hhmm is not None:  # the new form's shape with a time of day that does not exist
                findings.append(
                    Finding("journal-index", rel, f"{hhmm} is not a time (00:00 to 23:59 UTC); name it {forms}")
                )
            else:
                findings.append(Finding("journal-index", rel, f"starts with a date but is not named {forms}"))
        elif dated and _real_day(dated.group(1)) is None:
            findings.append(Finding("journal-index", rel, f"{dated.group(1)} is not a real day"))
        elif form == "new" and at_top:
            findings.append(
                Finding(
                    "journal-index", rel, f"a new-form session file lives in its month folder: move it to {name[:7]}/"
                )
            )
        elif form == "new" and month is not None and month != name[:7]:
            findings.append(
                Finding("journal-index", rel, f"filed under {month}/ but dated {name[:10]}: move it to {name[:7]}/")
            )
        elif form == "old" and month is not None:
            findings.append(
                Finding(
                    "journal-index",
                    rel,
                    "an old-form session file stays at the top of the journal directory, never moved",
                )
            )
        elif form is None and month is not None:
            findings.append(
                Finding(
                    "journal-index",
                    rel,
                    "a month folder holds new-form session files only; anything else lives at the top",
                )
            )
    # the folders themselves: a month folder that is not a month, and anything nested below a month folder
    base = ctx.root / directory
    for name in sorted(ctx.listing(base)):
        if not (base / name).is_dir() or not MONTH_DIR_RE.fullmatch(name):
            continue  # a folder not named like a month is not the journal's business
        if not _real_month(name):
            findings.append(
                Finding("journal-index", posixpath.join(directory, name), f"{name} is not a month (01 to 12)")
            )
            continue
        for inner in sorted(ctx.listing(base / name)):
            rel = posixpath.join(directory, name, inner)
            if not (base / name / inner).is_dir() and not ctx.has(rel):  # a file the markdown corpus never sees
                findings.append(
                    Finding(
                        "journal-index",
                        rel,
                        "a month folder holds new-form session files only; nothing else, of any kind",
                    )
                )
                continue
            if (base / name / inner).is_dir():
                findings.append(
                    Finding(
                        "journal-index", posixpath.join(directory, name, inner), "nothing nests below a month folder"
                    )
                )
    return findings


def _last_updated(ctx: Context, rel: str | None = None) -> tuple[str, date | None] | None:
    """A handoff's ``Last updated`` token and its date (``None`` if it is not a real ``YYYY-MM-DD`` day); ``None`` if
    the file has no such line. ``rel`` is the shared handoff unless a per-login one is named."""
    match = _LAST_UPDATED_RE.search(prose(ctx.text(rel or ctx.docs.handoff)))
    if match is None:
        return None
    token = match.group(1).strip("*_.,;:")
    return token, (_real_day(token) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", token) else None)


def _people_files(ctx: Context) -> list[str]:
    """The markdown files directly inside the people directory, sorted: each is meant to be one login's handoff."""
    return sorted(rel for rel in ctx.files if _in_scope(rel, ctx.docs.handoff_people_dir, False))


def _extension_base(ctx: Context, rel: str) -> str | None:
    """The base ``rel``'s name claims, ``<dir>/<name>.md`` for a governed ``<dir>/<name>-project.md``, or ``None`` when
    ``rel`` is not an extension's name: outside the governed directories, or in the journal, the board or the per-login
    handoff directory, where a name is a session, a row or a login (a login may end in ``-project``). The match is
    case-exact, as the ``links`` check is: ``One-project.md`` claims ``One.md``."""
    docs = ctx.docs
    if not any(_in_dir(rel, d) for d in docs.governed_dirs):
        return None
    if any(_in_dir(rel, d) for d in (docs.journal_dir, docs.board_dir, docs.handoff_people_dir)):
        return None
    match = _EXTENSION_RE.fullmatch(posixpath.basename(rel))
    if match is None:
        return None
    return posixpath.join(posixpath.dirname(rel), match.group("base") + ".md")


def check_extension_base(ctx: Context) -> list[Finding]:
    """An extension sits beside the base it is named for.

    A project adds its rules to a managed standard in ``<name>-project.md`` beside ``<name>.md`` (the ledger's
    ``failure-modes-project.md`` is the seeded one). The base's sentence names that file, and nothing else reaches it:
    an extension with no base beside it, because the base's name was misspelled or the file was put in another folder,
    is a document no reader is led to and no release can tell from a stray one. The journal, the board and the per-login
    handoff directories are their own checks' (a login may end in ``-project``). A document that is not an extension and
    whose slug happens to end in ``-project`` is read as one: the detail says to rename it.
    """
    return [
        Finding(
            "extension-base",
            rel,
            f"extends {posixpath.basename(base)}, which is not beside it; name the base exactly, move this file next "
            "to it, or, if this is not an extension, rename it so its name does not end in -project",
        )
        for rel in sorted(ctx.files)
        if (base := _extension_base(ctx, rel)) is not None and not ctx.has(base)
    ]


def _handoff_login(rel: str) -> str | None:
    """The login a per-login handoff is named for, or ``None`` when the name is not a login plus ``.md``."""
    match = _LOGIN_FILE_RE.fullmatch(posixpath.basename(rel))
    if match is None or len(match.group("login")) > fc.LOGIN_MAX:
        return None
    return match.group("login")


def _dated_people_handoffs(ctx: Context) -> list[tuple[str, str, str]]:
    """The per-login handoffs that are readable, named for a login and dated with a real day, as ``(path, login,
    the Last updated token)``. Everything else in the directory is the ``handoff`` check's or the corpus check's
    finding, so ``journal-day`` reads only these."""
    found: list[tuple[str, str, str]] = []
    for rel in _people_files(ctx):
        login = _handoff_login(rel)
        if login is None or rel not in ctx.texts:
            continue
        updated = _last_updated(ctx, rel)
        if updated is not None and updated[1] is not None:
            found.append((rel, login, updated[0]))
    return found


def _session_day_and_login(rel: str) -> tuple[str, str | None] | None:
    """A session file's day and, for a new-form file, its login; ``None`` when the day in the name is not a real day
    (``journal-index`` says so; it must not satisfy a handoff's date by sorting above every real one)."""
    name = posixpath.basename(rel)
    if _real_day(name[:10]) is None:
        return None
    match = _NEW_SESSION_RE.match(name)
    return name[:10], (match.group("login") if match else None)


def check_journal_day(ctx: Context) -> list[Finding]:
    """The day the handoff was last updated has a journal file: the newest session file's date is that date or later,
    and a dated handoff with no session file at all is a finding. A handoff with no usable date is ``handoff``'s."""
    if not ctx.module_on("journal"):
        return []
    findings: list[Finding] = []
    sessions = [found for rel in _session_files(ctx) if (found := _session_day_and_login(rel)) is not None]
    dates = sorted(day for day, _ in sessions)
    updated = _last_updated(ctx) if ctx.docs.handoff in ctx.texts else None
    if updated is None or updated[1] is None:
        pass  # no usable shared date: the handoff check's finding; the per-login files below are dated on their own
    elif not dates:
        findings.append(
            Finding("journal-day", ctx.docs.handoff, f"last updated {updated[0]} but there is no journal session file")
        )
    elif dates[-1] < updated[0]:
        findings.append(
            Finding(
                "journal-day",
                ctx.docs.handoff,
                f"last updated {updated[0]} but the newest journal file is {dates[-1]}; "
                "a new day starts a new session file",
            )
        )
    # a per-login handoff is held to that login's own new-form files: the session that writes it writes its journal file
    for rel, login, own in _dated_people_handoffs(ctx):
        mine = sorted(day for day, author in sessions if author is not None and author.lower() == login.lower())
        if not mine:
            findings.append(
                Finding(
                    "journal-day",
                    rel,
                    f"last updated {own} but @{login} has no new-form journal file; the session that writes a "
                    "handoff writes its journal file",
                )
            )
        elif mine[-1] < own:
            findings.append(
                Finding(
                    "journal-day",
                    rel,
                    f"last updated {own} but @{login}'s newest journal file is {mine[-1]}; a new day starts a new "
                    "session file",
                )
            )
    return findings


# The authorship grammar. A journal file is text from outside the check, so a line is cut with string methods and a
# bounded length, never matched by a pattern that can backtrack on whitespace (a 4,000-space line stalled the gate).
_LINE_MAX = 1000
_BY_PREFIX, _AGENT_PREFIX, _SAID_BY_PREFIX, _SUMMARY_PREFIX = "**By:**", "**Agent:**", "**Said by:**", "**Summary:**"
_BY_LOGINS_RE = re.compile(rf"@{fc.LOGIN_PATTERN}(?:,[ \t]*@{fc.LOGIN_PATTERN})*")
_AT_LOGIN_RE = re.compile(rf"@({fc.LOGIN_PATTERN})")
_QUOTE_TAG_RE = re.compile(
    rf"(?:(?:[-*+]|[0-9]+[.)])[ \t]+)?@({fc.LOGIN_PATTERN}):"
)  # on a line with its indent removed
SUMMARY_MAX = 200


def _entry_title(line: str) -> str | None:
    """The title of a ``###`` entry heading (up to three spaces of indent, as CommonMark allows), else ``None``."""
    bare = line.lstrip(" ")
    if len(line) - len(bare) > 3 or not bare.startswith(("### ", "###\t")):
        return None
    return bare[4:].strip().rstrip("#").strip() or bare[4:].strip()


def _after(prefix: str, line: str) -> str | None:
    """What follows ``prefix`` on ``line`` (stripped), or ``None`` if the line does not start with it."""
    bare = line.strip()
    return bare[len(prefix) :].strip() if bare.startswith(prefix) else None


def _by_line(line: str) -> tuple[str, str] | None:
    """The logins text and the agent text of a ``**By:** @login[, @login] · **Agent:** ...`` line, else ``None``."""
    rest = _after(_BY_PREFIX, line)
    if rest is None or len(rest) > _LINE_MAX:
        return None
    by, dot, tail = rest.partition("\u00b7")
    agent = _after(_AGENT_PREFIX, tail)
    if not dot or agent is None or not agent or not _BY_LOGINS_RE.fullmatch(by.strip()):
        return None
    return by.strip(), agent


def session_summary(text: str) -> str | None:
    """The text of the ``**Summary:**`` line in a session file's header (before its first ``###`` entry, outside code
    fences), stripped; ``None`` if there is no such line. It may be empty or longer than ``SUMMARY_MAX``: the caller
    judges that. The index renderer and ``journal-author`` both read it here, so they cannot disagree."""
    for _, line in prose_lines(text)[0]:
        if _entry_title(line) is not None:
            return None
        found = _after(_SUMMARY_PREFIX, line)
        if found is not None:
            return found
    return None


def _journal_author_findings(rel: str, text: str, roster: frozenset[str]) -> list[str]:
    """What is wrong with the authorship of one new-form session file, as detail strings (none: it is sound)."""
    problems: list[str] = []
    login = _NEW_SESSION_RE.match(posixpath.basename(rel))
    if login is not None and login.group("login").lower() not in roster:
        problems.append(f"name's login '{login.group('login')}' is not on the roster")
    lines = [line for _, line in prose_lines(text)[0]]
    first_entry = next((i for i, line in enumerate(lines) if _entry_title(line) is not None), len(lines))
    summary = session_summary(text)
    if summary is None:
        problems.append("no **Summary:** line before the first entry")
    elif not summary:
        problems.append("**Summary:** is empty")
    elif len(summary) > SUMMARY_MAX:
        problems.append(f"**Summary:** is longer than {SUMMARY_MAX} characters")
    for position in range(first_entry, len(lines)):
        title = _entry_title(lines[position])
        if title is None:
            continue
        first_two: list[str] = []  # the entry's first two non-blank lines: the By line and an optional Said by line
        for after in range(position + 1, len(lines)):  # by index: a slice would copy the rest of the file per entry
            line = lines[after]
            if _entry_title(line) is not None:
                break
            if line.strip():  # a higher-level heading is a non-blank line too, so it is never mistaken for a By line
                first_two.append(line)
                if len(first_two) == 2:
                    break
        by = _by_line(first_two[0]) if first_two else None
        if by is None:
            problems.append(f"entry '{title}' has no **By:** @login · **Agent:** ... line as its first line")
            continue
        named = _AT_LOGIN_RE.findall(by[0])
        said = _after(_SAID_BY_PREFIX, first_two[1]) if len(first_two) > 1 else None
        if said is not None:
            named += _AT_LOGIN_RE.findall(
                said
            )  # the whole value: the login pattern is linear, a cut would hide a login
        problems += [f"entry '{title}': '@{n}' is not on the roster" for n in named if n.lower() not in roster]
    for line in lines:
        tag = _QUOTE_TAG_RE.match(line.lstrip(" \t"))
        if tag is not None and tag.group(1).lower() not in roster:
            problems.append(f"'@{tag.group(1)}:' tags a quote with a login not on the roster")
    return problems


def check_journal_author(ctx: Context) -> list[Finding]:
    """Every entry of a new-form session file names its author, and every login it names is on the roster.

    Silent unless the journal module is on and the configuration has a ``[[people]]`` roster: a repository that has
    none pays nothing. Reads new-form files only (``YYYY-MM-DD-<login>-HHMM.md``); the old form's author is the owner.
    ``Agent:`` is never read beyond being present: an agent is a tool, not a person.
    """
    if not ctx.module_on("journal") or not ctx.people:
        return []
    roster = frozenset(person.login.lower() for person in ctx.people)
    findings: list[Finding] = []
    for rel in _session_files(ctx):
        if journal_file_form(posixpath.basename(rel)) != "new":
            continue
        findings += [Finding("journal-author", rel, d) for d in _journal_author_findings(rel, ctx.text(rel), roster)]
    return findings


def _heading_matches(line: str, name: str) -> bool:
    """``line`` is the heading ``name``, allowing closing ``#`` marks and trailing words (``## Gates (owner)``)."""
    heading = line.strip().rstrip("#").rstrip()
    if heading == name:
        return True
    return heading.startswith(name) and not heading[len(name)].isalnum()


def row_file_name(name: str) -> tuple[str, str] | None:
    """``(day, slug)`` of a row file's name, or ``None`` when the name has another shape; the day and the slug's length
    are judged by the ``board`` check, not here."""
    match = _ROW_FILE_RE.fullmatch(name)
    return (match.group("day"), match.group("slug")) if match else None


@dataclass(frozen=True)
class Row:
    """One board row file as read: its title, its header lines, and what was wrong with its shape."""

    rel: str
    day: str
    slug: str
    title: str
    lines: dict[str, str]
    problems: tuple[str, ...] = ()

    @property
    def section(self) -> str:
        return self.lines.get("Section", "").strip().lower()

    @property
    def owner(self) -> str:
        return self.lines.get("Owner", "").strip()

    @property
    def state(self) -> str:
        return self.lines.get("State", "").strip()

    @property
    def done(self) -> bool:
        return _DONE_RE.match(self.state) is not None


def parse_row(rel: str, text: str) -> Row:
    """Read a row file: the title is the first ``# `` heading, the header the run of ``**Name:** value`` lines directly
    after it (blank lines before the first allowed; the first blank line after it ends the header), and the body is
    the rest. A missing title, an unknown name and a name given twice are problems the ``board`` check reports; the
    rules per section are ``row_problems``'s."""
    name = posixpath.basename(rel)
    day, slug = row_file_name(name) or ("", "")
    lines = [line for _, line in prose_lines(text)[0]]
    title, problems, header = "", [], {}
    start = next((i for i, line in enumerate(lines) if line.startswith("# ")), None)
    if start is None:
        problems.append("no title: the first line is `# <the row>`")
        start = -1
    else:
        title = lines[start][2:].strip()
    for line in lines[start + 1 :]:
        if not line.strip():
            if header:
                break  # a blank line after the header ends it; the body follows
            continue
        match = _ROW_LINE_RE.match(line.strip())
        if match is None:
            break
        key = " ".join(match.group("name").split())
        canonical = next((n for n in ROW_NAMES if n.lower() == key.lower()), None)
        if canonical is None:
            problems.append(
                f"unknown header line `{key}` (one of {', '.join(ROW_NAMES)}); a typo would drop a required line"
            )
        elif canonical in header:
            problems.append(f"`{canonical}` is given twice")
        else:
            header[canonical] = match.group("value").strip()
    return Row(rel, day, slug, title, header, tuple(problems))


def _login_problem(value: str, what: str, logins: set[str], *, none_allowed: bool) -> str | None:
    """Why ``value`` is not an acceptable ``@login`` (or ``none``) for ``what``, or ``None``."""
    if value == "none":
        return None if none_allowed else f"`{what}` must be a login (@login), not none"
    match = _LOGIN_AT_RE.match(value)
    if match is None or len(match.group("login")) > fc.LOGIN_MAX:
        return f"`{what}` is {value!r}, not @login" + ("" if not none_allowed else " or none")
    if logins and match.group("login").lower() not in logins:
        return f"`{what}` names @{match.group('login')}, who is not on the roster ([[people]] in framework.toml)"
    return None


def row_problems(row: Row, logins: set[str]) -> list[str]:
    """Everything wrong with a row file's name and header under the rules of its section."""
    problems = list(row.problems)
    if not row.day:
        problems.append(
            "not a row file: the name is `YYYY-MM-DD-<slug>.md` (a real day; the slug lowercase letters, digits and "
            "single hyphens)"
        )
    else:
        if _real_day(row.day) is None:
            problems.append(f"the day {row.day} in the name is not a real day")
        if len(row.slug) > ROW_SLUG_MAX:
            problems.append(f"the slug is {len(row.slug)} characters; the limit is {ROW_SLUG_MAX}")
    section = row.section
    if "Section" not in row.lines:
        problems.append("no `**Section:**` line (gate, now, next, blocked or icebox)")
        return problems
    if section not in BOARD_SECTIONS:
        problems.append(f"`Section` is {row.lines['Section']!r}, not one of {', '.join(BOARD_SECTIONS)}")
        return problems
    for name in _ROW_REQUIRED[section]:
        if name not in row.lines:
            article = "an" if section[0] in "aeiou" else "a"
            problems.append(f"no `**{name}:**` line, which {article} {section} row needs")
    for name in row.lines:
        if name not in _ROW_REQUIRED[section] and name not in _ROW_ALLOWED[section]:
            problems.append(f"`{name}` is not allowed on a {section} row")
    if "Owner" in row.lines:
        found = _login_problem(row.owner, "Owner", logins, none_allowed=section in ("gate", "icebox"))
        if found:
            problems.append(found)
    if "Decider" in row.lines and section == "gate":
        found = _login_problem(row.lines["Decider"].strip(), "Decider", logins, none_allowed=False)
        if found:
            problems.append(found)
    if "Was owned by" in row.lines:
        for part in [p.strip() for p in row.lines["Was owned by"].split(",") if p.strip()]:
            found = _login_problem(part, "Was owned by", logins, none_allowed=False)
            if found:
                problems.append(found)
    if "Cost" in row.lines and not _COST_RE.match(row.lines["Cost"].strip()):
        problems.append(
            f"`Cost` is {row.lines['Cost']!r}; it needs a number or a range and a unit (`2 d`, `½ d`, `1 to 2 w`), "
            "then optionally an explanation"
        )
    if "Raised" in row.lines:
        raised = row.lines["Raised"].strip()
        unrecorded = _RAISED_UNRECORDED_RE.match(raised)
        if unrecorded:
            if _real_day(unrecorded.group(1)) is None:
                problems.append(f"`Raised` says converted on {unrecorded.group(1)}, which is not a real day")
        elif not _RAISED_LINK_RE.match(raised):
            problems.append(
                "`Raised` is not a markdown link to where the idea was said (or `unrecorded (converted YYYY-MM-DD)` "
                "on a converted row)"
            )
    if "State" in row.lines and not row.state:
        problems.append("`State` is empty")
    return problems


def _board_entries(ctx: Context) -> list[str]:
    """Everything in the board directory, listed from disk (the corpus is markdown, so a stray file of any kind is
    seen), as repository-relative paths, with the readable markdown files of the corpus added."""
    directory = ctx.docs.board_dir
    listed = {posixpath.join(directory, name) for name in ctx.listing(ctx.root / directory)}
    return sorted(listed | {rel for rel in ctx.files if _in_scope(rel, directory, False)})


def row_files(ctx: Context) -> list[str]:
    """The row files of the corpus: readable markdown files directly in the board directory whose name is a row's."""
    return [
        rel
        for rel in ctx.files
        if _in_scope(rel, ctx.docs.board_dir, False) and row_file_name(posixpath.basename(rel)) is not None
    ]


def board_in_directory_form(files: tuple[str, ...] | list[str], docs: fc.DocsConfig) -> bool:
    """The board is a directory of row files when at least one row file exists; it is the hand-kept page otherwise."""
    return any(
        _in_scope(rel, docs.board_dir, False) and row_file_name(posixpath.basename(rel)) is not None for rel in files
    )


def _is_row_file(ctx: Context, rel: str) -> bool:
    """A file the ``board`` check owns once the board is a directory: any markdown file directly in the board
    directory but its README. A row file's status is its ``State:`` line and the rendered page reaches it; a stray
    file there is the board check's one finding, not a status and an orphan finding as well."""
    if not _in_scope(rel, ctx.docs.board_dir, False) or posixpath.basename(rel) == "README.md":
        return False
    return ctx.board_is_directory


def _check_row_files(ctx: Context) -> list[Finding]:
    """The directory form: every entry is a row file or the README, every row file has what its section needs, and
    no hand-kept page sits beside the rows."""
    findings: list[Finding] = []
    logins = {person.login.lower() for person in ctx.people}
    for rel in _board_entries(ctx):
        name = posixpath.basename(rel)
        if (ctx.root / rel).is_dir():  # a folder, whatever its name: the corpus never sees it, the renderer would
            findings.append(
                Finding(
                    "board", rel, "a folder in the board directory; nothing lives there but row files and README.md"
                )
            )
            continue
        if name == "README.md":
            continue
        if row_file_name(name) is None:
            detail = (
                "not a row file (`YYYY-MM-DD-<slug>.md`: a real day; the slug lowercase letters, digits and single "
                "hyphens)"
            )
            if name.lower().endswith(".md") and row_file_name(name.lower()) is not None:
                detail = "not a row file: the slug is lowercase letters, digits and single hyphens"
            findings.append(
                Finding(
                    "board", rel, detail + "; nothing else, file or folder, lives in the board directory but README.md"
                )
            )
            continue
        if rel not in ctx.texts:
            continue  # unreadable: the corpus check's finding
        row = parse_row(rel, ctx.text(rel))
        findings += [Finding("board", rel, problem) for problem in row_problems(row, logins)]
    page = ctx.root / ctx.docs.board
    if page.is_file():
        try:
            first = page.read_text(encoding="utf-8-sig").split("\n", 1)[0].strip()
        except (OSError, UnicodeDecodeError) as e:
            detail = (
                f"the board page beside row files could not be read ({type(e).__name__}); the page is rendered by "
                "`make board` and git-ignored once the board is a directory: delete this one and render it again"
            )
            findings.append(Finding("board", ctx.docs.board, detail))
        else:
            if first != BOARD_HEADER:
                findings.append(
                    Finding(
                        "board",
                        ctx.docs.board,
                        "a hand-kept board page beside row files is two trackers: the page is rendered by `make board` "
                        "and git-ignored once the board is a directory; delete the page or the rows",
                    )
                )
    return findings


def check_board(ctx: Context) -> list[Finding]:
    """A hand-kept board exists and keeps every section a reader looks for: a missing section is a tracker degrading. A
    board in directory form is held to the row-file rules instead (``_check_row_files``)."""
    if ctx.board_is_directory:
        return _check_row_files(ctx)
    if not ctx.has(ctx.docs.board):
        return [Finding("board", ctx.docs.board, "missing; the tracker lives here")]
    lines = [line for _, line in prose_lines(ctx.text(ctx.docs.board))[0]]
    return [
        Finding("board", ctx.docs.board, f"no {name!r} section")
        for name in ctx.docs.board_sections
        if not any(_heading_matches(line, name) for line in lines)
    ]


def check_landed_rows(ctx: Context) -> list[Finding]:
    """A struck-through board row names the pull request that landed it.

    A landed row keeps its number and is struck through, never deleted, because the number is what survives: the branch
    is deleted on merge, so a row naming only a branch points at nothing a month later. The number does not exist until
    the push, so a row is written with a placeholder and nothing comes back to fill it in; a check that goes red is the
    only thing that does. Either spelling counts: a ``/pull/N`` link or a bare ``#N``.

    A row is a table row whose first cell starts with ``~~`` (bold or italic markers around it are ignored). Two things
    are not landed rows and are not asked for a number: a row in the **Gates** section (a gate closes by a person's
    decision, not by a pull request), and a row that says it closed without one (the words ``no pull request`` and
    some reason after them). Run against HogShade's real board, the rule found seven struck rows: two were closed gates,
    four closed without a pull request, and one said it landed "on branch X" and named no number, which is the failure
    the rule exists for.

    **It cannot tell a reference from the one that landed the row**: a row citing an issue (``closes issue #12``) as
    evidence passes while its own number is missing. It narrows what a reviewer reads; it does not replace reading a
    landed row.
    """
    if ctx.board_is_directory:
        findings: list[Finding] = []
        for rel in row_files(ctx):
            if rel not in ctx.texts:
                continue
            row = parse_row(rel, ctx.text(rel))
            if row.section == "gate" or not row.state.lower().startswith("landed"):
                continue
            if _PR_REF_RE.search(row.state) or _NO_PR_RE.search(row.state):
                continue
            findings.append(
                Finding(
                    "landed-rows",
                    rel,
                    f'landed row "{row.title[:60]}" names no pull request; a landed row keeps its number (#N or a '
                    "/pull/N link) because the branch is deleted on merge",
                )
            )
        return findings
    if ctx.docs.board not in ctx.texts:
        return []
    findings: list[Finding] = []
    in_gates, gates_level = False, 0
    for number, line in prose_lines(ctx.text(ctx.docs.board))[0]:
        heading = re.match(r"(#{1,6})\s", line)
        if heading and _heading_matches(line, _DECISION_SECTION):
            in_gates, gates_level = True, len(heading.group(1))
        elif heading and in_gates and len(heading.group(1)) <= gates_level:
            in_gates = False  # a deeper heading (### Closed) stays inside the Gates section
        row = re.sub(r"^[ \t]*(?:>[ \t]*)*", "", line)  # a row inside a block quote is still a row
        if "|" not in row:
            continue
        first = re.sub(r"[*_]", "", row.strip().strip("|").split("|")[0]).strip().lstrip("[").strip()
        if not first.startswith("~~") or in_gates or _PR_REF_RE.search(line) or _NO_PR_RE.search(line):
            continue
        findings.append(
            Finding(
                "landed-rows",
                f"{ctx.docs.board}:{number}",
                f'landed row "{re.sub(r"[~`]", "", first)[:60]}" names no pull request; a struck row keeps its number '
                "(#N or a /pull/N link) because the branch is deleted on merge",
            )
        )
    return findings


def _handoff_rules(ctx: Context, rel: str) -> list[Finding]:
    """The two rules every handoff is held to: a real ``Last updated`` day, and the line limit."""
    findings: list[Finding] = []
    updated = _last_updated(ctx, rel)
    if updated is None:
        findings.append(
            Finding("handoff", rel, "no `**Last updated:** YYYY-MM-DD` line; the journal-day check needs it")
        )
    elif updated[1] is None:
        findings.append(Finding("handoff", rel, f"`Last updated` {updated[0]!r} is not a real day (YYYY-MM-DD)"))
    count = len(split_lines(ctx.text(rel)))
    if count > ctx.handoff_max_lines:
        findings.append(
            Finding(
                "handoff",
                rel,
                f"{count} lines; the limit is {ctx.handoff_max_lines} (`handoff_max_lines` in framework.toml). "
                "A handoff past its limit has become a log: history is the journal and git; cut it",
            )
        )
    return findings


def check_handoff(ctx: Context) -> list[Finding]:
    """The shared handoff exists, is dated with a real day, and has not grown into a log (``handoff_max_lines``). Each
    file in the people directory is one login's handoff: named for a login and nothing else (no README), not a name
    Windows reserves, on the roster when there is one, and held to the same two rules as the shared file."""
    rel = ctx.docs.handoff
    if not ctx.has(rel):
        return [Finding("handoff", rel, "missing; a new session reads this first")]
    findings: list[Finding] = []
    if rel in ctx.texts:  # unreadable: the corpus check reports it
        findings += _handoff_rules(ctx, rel)
    logins = {person.login.lower() for person in ctx.people}
    directory = ctx.docs.handoff_people_dir
    # the corpus is markdown, so the directory itself is listed too: ada.txt or a folder is "something else" as well
    listed = {posixpath.join(directory, name) for name in ctx.listing(ctx.root / directory)}
    for person_rel in sorted(listed | set(_people_files(ctx))):
        login = _handoff_login(person_rel)
        if login is None:
            findings.append(
                Finding(
                    "handoff",
                    person_rel,
                    f"not named for a login ({directory}/<login>.md: 1 to {fc.LOGIN_MAX} letters, "
                    "digits or single hyphens); nothing else lives there, not a README",
                )
            )
            continue
        if login.lower() in _WINDOWS_RESERVED:
            findings.append(
                Finding(
                    "handoff", person_rel, f"{login!r} is a name Windows reserves; a checkout there could not hold it"
                )
            )
        if logins and login.lower() not in logins:
            findings.append(
                Finding("handoff", person_rel, f"@{login} is not on the roster ([[people]] in framework.toml)")
            )
        if person_rel in ctx.texts:
            findings += _handoff_rules(ctx, person_rel)
    return findings


# -------------------------------------------------------------------------
# the checks that read the glossary, the ADR headers and the link graph
def _is_separator(text: str) -> bool:
    """A table's ``| --- | --- |`` row (the leading pipe is optional, as in GitHub's tables)."""
    return set(text) <= set("|-: \t") and "-" in text


def _table_rows(lines: list[tuple[int, str]]) -> list[tuple[int, list[str], bool]]:
    """The data rows of the markdown tables in ``lines`` as (line number, cells, is a header row).

    A row starts with a pipe (inside a block quote too); a header row is the one above a separator row, which is
    dropped. Cells are stripped and an escaped pipe (a backslash then a pipe) stays inside its cell.
    """
    rows: list[tuple[int, list[str], bool]] = []
    for index, (number, line) in enumerate(lines):
        text = line.strip().lstrip(">").strip()
        if not text.startswith("|") or _is_separator(text):
            continue
        following = lines[index + 1][1].strip().lstrip(">").strip() if index + 1 < len(lines) else ""
        header = "|" in following and _is_separator(following)
        cells = [cell.strip().replace("\\|", "|") for cell in re.split(r"(?<!\\)\|", text.strip("|"))]
        rows.append((number, cells, header))
    return rows


def _term_text(span: str) -> str:
    """A bold span as a term: no markup inside, no trailing colon (``**Plan:**`` names ``Plan``)."""
    text = re.sub(r"[*`]", "", span).strip().rstrip(":").strip()
    emphasised = re.fullmatch(r"_([^_]|[^_].*[^_])_", text)  # _Plan_, but not an identifier such as __init__
    return emphasised.group(1).strip() if emphasised else text


def _glossary_rows(ctx: Context) -> list[tuple[int, list[str], bool]]:
    if ctx.docs.glossary not in ctx.texts:
        return []
    return _table_rows(prose_lines(ctx.text(ctx.docs.glossary))[0])


def glossary_terms(ctx: Context) -> set[str]:
    """The glossary's current terms, lowercase: every bold span in the first cell of a row that is not retired.

    A row may define several (``**Spec**, **Plan**``); the first version of this check registered only the first span,
    so a document naming ``Plan`` failed against a row that held it.
    """
    terms: set[str] = set()
    for _, cells, header in _glossary_rows(ctx):
        if header or not cells or cells[0].lstrip("*_` ").startswith("~~"):
            continue
        terms.update(_term_text(m.group(1)).lower() for m in _BOLD_RE.finditer(cells[0]))
    return terms


def _plain(cell: str) -> str:
    """A table cell without markup: links reduced to their text, emphasis and code marks and a final stop gone."""
    cell = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", cell)
    return (
        " ".join(re.sub(r"[*`]", "", cell).split()).rstrip(".,").strip()
    )  # not "_": it is part of hog_rendering.camera


def _retired_row(cells: list[str]) -> tuple[str, str] | None:
    """(retired term, replacement) from a retired-table row ``| ~~term~~ | replacement | why |``, or ``None`` if the
    row does not parse into exactly one *enforceable* term.

    A replacement is a **name**: short, with no sentence in it (no ``;`` or ``:``, no full stop followed by a space, no
    "or", at most six words). A cell that explains ("RETIRED. Unreal's term; here it is ...") or offers alternatives can
    never be matched on a line, so every use of the retired term would be a finding nobody could clear; the explanation
    belongs in the *Why* column and each alternative in a row of its own. A replacement that appears inside the retired
    term (``Color Stack Window`` replaced by ``Color Stack``) is found on every line that has the term, so the row
    would enforce nothing: also not enforceable. Found by running this on real glossaries.
    """
    if len(cells) < 2 or len(cells[0]) > 200 or len(cells[1]) > 200:
        return None
    match = re.fullmatch(r"~~\s*(?:\*\*|`)?([^~]+?)(?:\*\*|`)?\s*~~", cells[0])
    old = " ".join(match.group(1).split()) if match else ""
    new = _plain(cells[1])
    nameable = bool(re.search(r"\w", new)) and len(new.split()) <= 6 and not re.search(r"[;:]|\.\s|\bor\b", new, re.I)
    if not (old and re.search(r"\w", old) and nameable) or _phrase_re(new).search(old):
        return None
    return old, new


def retired_terms(ctx: Context) -> dict[str, str]:
    """The retired vocabulary, read from the glossary so there is one list and not two: retired term to replacement."""
    found: dict[str, str] = {}
    for _, cells, header in _glossary_rows(ctx):
        if header or not cells or not cells[0].lstrip("*_` ").startswith("~~"):
            continue
        parsed = _retired_row(cells)
        if parsed:
            found[parsed[0]] = parsed[1]
    return found


def _term_key(term: str) -> str:
    """A retired term as the vocabulary check matches it: any case, a run of spaces or hyphens being one gap."""
    return " ".join(word for word in re.split(r"[\s-]+", term.lower()) if word)


def check_glossary_row(ctx: Context) -> list[Finding]:
    """Every row of the glossary's retired table parses into one enforceable term and a replacement, once.

    A row the parser cannot read is a term nobody enforces and nobody can tell is unenforced, which is worse than not
    listing it. So the table is machine-valid by construction: one retired spelling per row, unqualified, with a
    replacement that is a name not found inside the term, and no term twice (the later row would silently replace
    the earlier). A rule that cannot take that shape belongs in prose below the table, where it reads as a human
    instruction and not as an apparently checked one.
    """
    findings: list[Finding] = []
    seen: set[str] = set()
    for number, cells, header in _glossary_rows(ctx):
        if header or not cells or not cells[0].lstrip("*_` ").startswith("~~"):
            continue
        where = f"{ctx.docs.glossary}:{number}"
        parsed = _retired_row(cells)
        if parsed is None:
            findings.append(
                Finding(
                    "glossary-row",
                    where,
                    "retired-table row does not parse into one enforceable term and a replacement that is a short "
                    "name not found inside the term (`| ~~term~~ | name | why |`), so nothing enforces it; give it its "
                    "own row, or state the rule in prose below the table",
                )
            )
        elif _term_key(parsed[0]) in seen:
            findings.append(Finding("glossary-row", where, f"{parsed[0]!r} is retired twice; keep one row"))
        else:
            seen.add(_term_key(parsed[0]))
    return findings


def _terms_section(lines: list[tuple[int, str]]) -> list[str] | None:
    """The lines of the ``## Terms introduced`` section (to the next level one or two heading), or ``None``.

    A deeper heading (``### Detail``) stays inside the section; a setext heading (a line underlined with ``---``) is
    not read as one.
    """
    start = next((i for i, (_, line) in enumerate(lines) if _TERMS_HEADING_RE.fullmatch(line.strip())), None)
    if start is None:
        return None
    body: list[str] = []
    for _, line in lines[start + 1 :]:
        if re.match(r"#{1,2}\s", line):
            break
        body.append(line)
    return body


def _terms_problems(section: list[str], known: set[str]) -> list[str]:
    """What is wrong with a *Terms introduced* section: nothing listed and not ``None``, or a term with no row.

    ``None`` is the section's first words, in any list or quote marker and emphasis, followed by anything (``None.
    This uses only existing terms.``). A term is a bold span, with markup and a trailing colon stripped.
    """
    first = next((line for line in section if line.strip()), "")
    first = re.sub(r"[*_`]", "", re.sub(r"^[>\s]*(?:[-*+]\s+)?", "", first)).strip()
    if _NONE_RE.match(first):
        return []
    terms = [_term_text(m.group(1)) for m in _BOLD_RE.finditer("\n".join(section))]
    if not terms:
        return ["`Terms introduced` lists no `**Term**` and does not say None"]
    return [
        f"term {term!r} has no row in the glossary; add it before using it"
        for term in terms
        if term.lower() not in known
    ]


def check_terms(ctx: Context) -> list[Finding]:
    """A design, spec or plan carries a ``## Terms introduced`` section: ``None``, or each term in bold with a row.

    The word is added to the glossary in the same change, before the document or code that uses it: a word whose
    meaning only its author holds is retrieved by nobody else. **It holds only the terms an author lists**; a new name
    in code with no entry here is judgment. An index (``README.md``) in those directories introduces nothing and is
    not asked. The documents that predate the rule are listed in ``terms_grandfathered`` and **that list only
    shrinks**: a listed file that is gone, outside ``terms_dirs`` or now has a sound section is a finding that says to
    remove it.
    """
    known = glossary_terms(ctx)
    findings: list[Finding] = []
    grandfathered = set(ctx.docs.terms_grandfathered)
    for path in sorted(grandfathered):
        if not any(_in_dir(path, d) for d in ctx.docs.terms_dirs):
            findings.append(Finding("terms", path, "is in terms_grandfathered but outside terms_dirs; remove it"))
        elif not ctx.has(path):
            findings.append(
                Finding("terms", path, "is in terms_grandfathered but not in the corpus; remove it from the list")
            )
    for rel in ctx.files:
        if not any(_in_dir(rel, d) for d in ctx.docs.terms_dirs) or posixpath.basename(rel).lower() == "readme.md":
            continue
        section = _terms_section(prose_lines(ctx.text(rel))[0])
        problems = ["no `## Terms introduced` section: list the glossary terms this introduces, or say None"]
        if section is not None:
            problems = _terms_problems(section, known)
        if rel in grandfathered:
            if not problems:
                findings.append(Finding("terms", rel, "now has a sound section; remove it from terms_grandfathered"))
            continue
        findings += [Finding("terms", rel, problem) for problem in problems]
    return findings


def _phrase_re(term: str) -> re.Pattern[str]:
    """``term`` as a whole word or phrase: not inside a longer word or hyphenated name. Each gap between its words
    matches one run of spaces or hyphens (so ``Preserve Alpha`` also finds ``preserve-alpha``); a gap is built once,
    however many spaces or hyphens the glossary wrote, so the pattern cannot backtrack on a long run."""
    words = [word for word in re.split(r"[\s-]+", term.strip()) if word]
    return re.compile(r"(?<![\w-])" + r"[\s-]+".join(re.escape(word) for word in words) + r"(?![\w-])", re.IGNORECASE)


def check_vocabulary(ctx: Context) -> list[Finding]:
    """A retired term appears only on a line that also names its replacement.

    The rule is deliberately this and not "never": the documents whose job is to record what changed (the ledger, an
    ADR's outcome, the glossary's own table) must be able to name the old thing, and each of them names the new one on
    the same line because that is what a migration note is. So the allowances are few: ``retired_exempt_dirs`` (by
    default only the append-only journal; a project can add more, and each one is a place the check does not look), a
    document that is ``Superseded`` or ``Abandoned`` (its subject is the retired thing), and, for one term, a
    document whose header (first 12 lines) translates it on a single line naming both.

    **Its limit**: the match is per line, so a sentence wrapped between a retired term and its replacement reads as a
    bare use; reflowing the sentence fixes it. The replacement cell of the glossary row is matched as written, so it
    must be the name to use.
    """
    terms = retired_terms(ctx)
    if not terms:
        return []
    patterns = {old: (_phrase_re(old), _phrase_re(new)) for old, new in terms.items()}
    findings: list[Finding] = []
    for rel in ctx.files:
        if rel == ctx.docs.glossary or any(_in_dir(rel, d) for d in ctx.docs.retired_exempt_dirs):
            continue
        lines = prose_lines(ctx.text(rel))[0]
        header = [line for number, line in lines if number <= STATUS_WINDOW]
        status = next((s for s in map(_status_of, header) if s), None)
        if status and status[0] in ("Superseded", "Abandoned"):
            continue
        for old, (old_re, new_re) in patterns.items():
            if any(old_re.search(line) and new_re.search(line) for line in header):
                continue
            for number, line in lines:
                if old_re.search(line) and not new_re.search(line):
                    findings.append(
                        Finding(
                            "vocabulary",
                            f"{rel}:{number}",
                            f"uses retired {old!r} without naming {terms[old]!r}; say {terms[old]!r}, or name both "
                            "if the line records the change (glossary, retired terms)",
                        )
                    )
    return findings


def _resolve(rel: str, target: str) -> str:
    """The repository-relative path ``target`` names from the document ``rel`` (a leading ``/`` is the root)."""
    joined = target.lstrip("/") if target.startswith("/") else posixpath.join(posixpath.dirname(rel), target)
    return posixpath.normpath(joined)


def check_orphan(ctx: Context) -> list[Finding]:
    """Every document in a governed directory can be reached by links from the map.

    A document written and never wired in is invisible to the agents the corpus exists to serve. The map is every file
    outside the governed directories (the root README, the entry file) and the ``orphan_allow`` entry points; a
    document is reached if some chain of links leads to it from there, so two documents that link only to each other
    are still orphans. Links are resolved to paths (against the linking document's directory), not matched by file
    name, so two files with one name in different folders are told apart. Dated session files are the journal index's
    business (``journal-index``) and carry no weight here. An extension beside its base (``python-project.md`` beside
    ``python.md``) is reached through the base, whose sentence names it, as an implicit edge from the base: a base
    nothing links is still an orphan, and so is its extension, even if the two link each other. One without its base
    is ``extension-base``'s finding and an orphan both; one whose base is unreadable is ``corpus``'s alone. A link to a
    directory does not reach what is inside it: link the file.
    """
    graph = {rel: {_resolve(rel, target) for target in link_targets(ctx.text(rel))} for rel in ctx.files}
    unreadable_base: set[str] = set()
    for rel in ctx.files:
        base = _extension_base(ctx, rel)
        if base in graph:
            graph[base].add(rel)  # the base's sentence names its extension: an edge no link carries
        elif base is not None and base in ctx.unreadable:
            unreadable_base.add(rel)

    def is_session(rel: str) -> bool:
        return _session_shaped_in_journal(ctx, rel)

    people = set(_people_files(ctx))  # a per-login handoff is reached by its name, as a session file is
    documents = {
        rel
        for rel in ctx.files
        if any(_in_dir(rel, d) for d in ctx.docs.governed_dirs)
        and not is_session(rel)
        and rel not in people
        and not _is_row_file(ctx, rel)  # a row file is reached by the rendered page; its own links still count
        and rel not in unreadable_base  # the corpus check's finding, not a second one here
    }
    reached = {rel for rel in ctx.files if rel not in documents} | set(ctx.docs.orphan_allow)
    queue = list(reached)
    while queue:
        node = queue.pop()
        if is_session(node):
            continue  # a journal entry is reached through its index, but its own links wire nothing in
        for path in graph.get(node, ()):
            if path not in reached and path in graph:
                reached.add(path)
                queue.append(path)
    return [
        Finding(
            "orphan",
            rel,
            "no chain of links leads to it from the map (a file outside governed_dirs, or an orphan_allow entry "
            "point); link it from the map that fits, or from an index the map links",
        )
        for rel in sorted(documents - reached)
    ]


def _declared(ctx: Context, rel: str) -> list[tuple[int, str, str]]:
    """The relationship headers of one ADR: (line number, kind, the ADR path linked), in file order.

    A header is ``**Superseded by:** [ADR-002](ADR-002-x.md)`` (or ``**Superseded by**:``, any case, in a list item or a
    block quote), with the link on the same line. The status line ``**Status:** Superseded by [ADR-002](...)`` is the
    same relation and counts as ``Superseded by``.
    """
    found: list[tuple[int, str, str]] = []
    for number, line in prose_lines(ctx.text(rel))[0]:
        match = _ADR_REF_RE.match(line)
        if match:
            kind, rest = _ADR_KIND[match.group(1).lower()], match.group(2)
        else:
            status = _status_of(line)
            if not status or status[0] != "Superseded":
                continue
            kind, rest = "Superseded by", status[1]
        found += [(number, kind, _resolve(rel, target)) for target in link_targets(rest)]
    return found


def check_adr_refs(ctx: Context) -> list[Finding]:
    """ADR relationship headers point both ways, in every direction.

    ``Superseded by`` needs a ``Supersedes`` in the target that links back, and the reverse; ``Extends`` and
    ``Extended by`` likewise. One side alone leaves a reader who arrives at the other document unaware of the relation,
    and the first version of this check (in the repository it came from) covered only three of the four directions.
    The target must link back to **this** ADR with the **inverse** kind, not merely carry some line of that kind or link
    here with the same one. A link to a file that is not an ADR in the corpus is the ``links`` check's finding. The
    header format is documented in ``Docs/standards/definition-of-done.md``.
    """
    adrs = set(_adr_files(ctx))
    declared = {rel: _declared(ctx, rel) for rel in sorted(adrs)}  # once per ADR, not once per relation line
    findings: list[Finding] = []
    for rel, relations in declared.items():
        for number, kind, target in relations:
            if target not in adrs:
                if target in ctx.files:  # a missing file is the links check's finding
                    findings.append(
                        Finding(
                            "adr-refs",
                            f"{rel}:{number}",
                            f"declares `{kind}` {posixpath.basename(target)}, which is not an ADR; an ADR "
                            "relation links ADRs, and any other link belongs in the text",
                        )
                    )
                continue
            back = _ADR_INVERSE[kind]
            if not any(k == back and linked == rel for _, k, linked in declared[target]):
                findings.append(
                    Finding(
                        "adr-refs",
                        f"{rel}:{number}",
                        f"declares `{kind}` {posixpath.basename(target)}, but {target} has no `{back}` line "
                        "linking back",
                    )
                )
    return findings


def check_nested_instructions(ctx: Context) -> list[Finding]:
    """Only the repository root may hold an instruction file (``CLAUDE.md``, ``CLAUDE.local.md``, ``GEMINI.md``,
    ``AGENTS.md``).

    Some harnesses load a nested one automatically as instructions: a vendored copy once injected another project's
    conventions into a repository, noticed by accident, which is why it is a check. It looks everywhere the documents
    walk does not (see ``instruction_paths``): a scratch folder or a spike is exactly where a stray one sits. A project
    that wants scoped instructions lists the file in ``instructions_allow`` and records the decision in an ADR.
    """
    allowed = set(ctx.docs.instructions_allow)
    return [
        Finding(
            "nested-instructions",
            rel,
            f"{posixpath.basename(rel)} below the root is loaded as instructions by some harnesses; rename it, or list "
            "it in instructions_allow with an ADR that says why",
        )
        for rel in ctx.instructions
        if rel not in allowed
    ]


Check = Callable[[Context], list[Finding]]

#: Check name -> function, in the order they run. A function emits findings under exactly its own name.
CHECKS: dict[str, Check] = {
    "corpus": check_corpus,
    "links": check_links,
    "fences": check_fences,
    "status": check_status,
    "single-status": check_single_status,
    "status-copy": check_status_copy,
    "journal-index": check_journal_index,
    "journal-day": check_journal_day,
    "journal-author": check_journal_author,
    "adr-index": check_adr_index,
    "adr-duplicate": check_adr_duplicate,
    "adr-refs": check_adr_refs,
    "board": check_board,
    "landed-rows": check_landed_rows,
    "handoff": check_handoff,
    "glossary-row": check_glossary_row,
    "terms": check_terms,
    "vocabulary": check_vocabulary,
    "orphan": check_orphan,
    "extension-base": check_extension_base,
    "nested-instructions": check_nested_instructions,
}


def run(ctx: Context, checks: Mapping[str, Check] = CHECKS) -> list[Finding]:
    """Run every check over ``ctx``; findings come back in check order, sorted by location within a check."""
    findings: list[Finding] = []
    for name, check in checks.items():
        found = sorted(check(ctx), key=lambda f: (f.location, f.detail))
        _LOGGER.info(f"check {name}: {len(found)} finding(s) over {len(ctx.files)} file(s)")
        findings.extend(found)
    return findings


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # a finding naming a non-ASCII file must not crash the report
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="backslashreplace")
    args = list(sys.argv[1:] if argv is None else argv)
    verbose = "-v" in args
    args = [a for a in args if a != "-v"]
    if len(args) > 1 or any(a.startswith("-") for a in args):
        print("usage: check_docs.py [-v] [root]", file=sys.stderr)
        return 2
    if verbose:
        _logging.basicConfig(level=_logging.INFO, format="%(message)s", stream=sys.stderr)
    root = Path(args[0]) if args else Path(__file__).resolve().parent.parent
    if not root.is_dir():
        print(f"docs check: cannot run: {root} is not a directory", file=sys.stderr)
        return 2
    try:
        ctx = load_context(root)
    except fc.ConfigError as e:
        print(f"docs check: cannot run: {e}", file=sys.stderr)
        return 2
    findings = run(ctx)
    for finding in findings:
        print(finding)
    if findings:
        print(f"docs check: {len(ctx.files)} files, {len(findings)} finding(s)")
        return 1
    print(f"docs check: {len(ctx.files)} files, no drift")
    return 0


if __name__ == "__main__":
    sys.exit(main())
