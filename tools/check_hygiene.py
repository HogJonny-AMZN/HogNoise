"""
Framework: the hygiene check: none of the project's retired or private identifiers in any file outside the allowlist.
Package: tools/check_hygiene

A project lists identifiers it must not leak or revive (a former codename, an employer's name, a checkout path) in
``project.json`` (``hygiene``). The identifiers live in that one file, so that every other document can say "run the
hygiene check" without repeating them, which would make the check flag the document. This check reads every file git
tracks or would add (``git ls-files --cached --others --exclude-standard``) and reports each line, and each file name,
that contains one, unless the file is allowed. Without git, or when git cannot list the files, it walks the tree
(skipping ``.git``, ``.venv``, ``node_modules``, ``__pycache__`` and ``logs``) and says so as a warning: a different set
of files is being checked, and a reader must be told.

What counts as a match, and what does not:

- An identifier is a literal. Both sides are Unicode-normalised (NFKC) and case-folded, so ``Straße`` finds ``STRASSE``
  and a full-width spelling finds the plain one; whitespace inside an identifier matches any run of whitespace,
  including a line break, so a name wrapped across two lines is found. It is a substring match: a leak is a leak
  wherever it sits.
- A file is searched as UTF-8, and also as Latin-1 when it is not valid UTF-8, and also as UTF-16 and UTF-32 (either
  byte order) when it holds a NUL byte, because a file written by a Windows shell is UTF-16 and a binary file may hold
  a path. **Other encodings (Shift-JIS and the like) are not searched**: a project whose identifier is written in one
  lists the files in ``[[hygiene_allow]]`` or does not rely on this check for them.
- A symbolic link is not followed: its own name and its target text are checked. A submodule's files are not scanned
  (git stores only its commit); that is logged as a warning.
- Lines are split on line feeds and carriage returns only, so a line number agrees with an editor's.
- The report gives the file and line, never the line itself, and an allowlist reason that names an identifier is
  not shown either: the check must not copy the leak into a CI log. (A file *name* that holds one is shown; it is
  the only way to point at it.)

``project.json`` is always allowed (it holds the identifiers). Any other exception is a ``[[hygiene_allow]]`` table in
``framework.toml``, a file or a directory with everything below it and **a reason**. The allowlist only shrinks: an
entry whose path carries no identifier any more is a finding that says to remove it. A file larger than
``MAX_BYTES`` or one that cannot be read is a finding (it was not checked), unless it is allowed. **A file git
stores through LFS (``filter=lfs`` in ``.gitattributes``) is a binary asset: its content is not read, whatever its size,
and its name still is.** Where git cannot say which files are LFS, none is skipped.

No identifiers configured is a valid state (the module is on, the list empty): the check says so and passes. A non-empty
list over zero files is a finding, because a scan of nothing proves nothing.

Run standalone (exit code 0 clean, 1 findings, 2 the configuration or the arguments are unusable)::

    uv run python tools/check_hygiene.py [-v] [root]

``tests/test_check_hygiene.py`` runs it on fixtures and shows each rule can fail.
"""

from __future__ import annotations

import logging as _logging
import os
import re
import subprocess
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import framework_config as fc

# -------------------------------------------------------------------------
# module global scope
_MODULE_NAME = "tools.check_hygiene"
__version__ = "0.3.0"
__updated__ = "2026-10-12"
_LOGGER = _logging.getLogger(_MODULE_NAME)

#: Always allowed: the file that holds the identifiers.
ALWAYS_ALLOWED = ("project.json",)
#: A file larger than this is a finding rather than a silent skip.
MAX_BYTES = 5_000_000
#: Directories the no-git walk skips: other checkouts, caches and the run records of the initialiser.
WALK_SKIP = frozenset({".git", ".venv", "node_modules", "__pycache__", "logs"})
#: Encodings a file with a NUL byte is also searched as (a Windows shell writes UTF-16; a binary may hold a path).
WIDE_ENCODINGS = ("utf-16-le", "utf-16-be", "utf-32-le", "utf-32-be")


@dataclass(frozen=True)
class Finding:
    """One place an identifier was found, or one file the check could not vouch for."""

    path: str
    line: int  # 0 for a finding about the whole file or its name
    detail: str

    def __str__(self) -> str:
        where = f"{self.path}:{self.line}" if self.line else self.path
        return f"[hygiene] {where}: {self.detail}"


def _normal(text: str) -> str:
    """``text`` as the matcher compares it: NFKC-normalised and case-folded."""
    return unicodedata.normalize("NFKC", text).casefold()


def build_pattern(identifiers: tuple[str, ...]) -> re.Pattern[str]:
    """One pattern for all identifiers, applied to ``_normal`` text: each identifier a literal, its words joined by
    ``\\s+`` so that a different run of whitespace, or a line break, between them still matches."""
    parts = [r"\s+".join(re.escape(word) for word in _normal(i).split()) for i in identifiers]
    return re.compile("|".join(part for part in parts if part))


def candidate_paths(root: Path) -> tuple[list[str], str]:
    """The files to scan as sorted relative POSIX paths, and where the list came from (``git`` or ``walk``).

    When git is missing or fails, the walk is used and a warning says why; "this is not a git repository" is the
    expected case of a tree before ``git init`` and is only information.
    """
    reason = ""
    try:
        proc = subprocess.run(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=root,
            capture_output=True,
            check=False,
        )
    except OSError as e:
        proc = None
        reason = f"git could not be run ({type(e).__name__}: {e})"
    if proc is not None and proc.returncode == 0:
        names = [_path_text(n) for n in proc.stdout.split(b"\0") if n]
        return sorted(set(names)), "git"
    if proc is not None:
        reason = proc.stderr.decode("utf-8", errors="replace").strip() or f"git exited {proc.returncode}"
    log = _LOGGER.info if "not a git repository" in reason else _LOGGER.warning
    log(f"{reason}; scanning every file under {root} instead, except {', '.join(sorted(WALK_SKIP))}")
    found: list[str] = []
    for current, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in WALK_SKIP)
        found += [(Path(current) / name).relative_to(root).as_posix() for name in files]
    return sorted(found), "walk"


def lfs_paths(root: Path, paths: list[str]) -> set[str]:
    """The paths among ``paths`` that git stores through LFS (the ``filter`` attribute is ``lfs``): textures, meshes and
    other binaries that are too large to read and are not text. Empty when git cannot say (no git, an error): nothing is
    skipped on a guess, so the large files are findings as before. Their *names* are still checked."""
    if not paths:
        return set()
    try:
        proc = subprocess.run(
            ["git", "check-attr", "-z", "--stdin", "filter"],
            cwd=root,
            input=b"\0".join(os.fsencode(p) for p in paths) + b"\0",
            capture_output=True,
            check=False,
        )
    except OSError:
        return set()
    if proc.returncode != 0:
        return set()
    fields = proc.stdout.split(b"\0")  # path, attribute, value, ...
    return {_path_text(fields[i]) for i in range(0, len(fields) - 2, 3) if fields[i + 2] == b"lfs"}


def _path_text(raw: bytes) -> str:
    """A path git printed, as the file system names it: a name that is not valid UTF-8 keeps its bytes (as surrogate
    escapes) instead of being replaced, so ``root / name`` still finds the file and an identifier in the name still
    matches."""
    try:
        return os.fsdecode(raw)
    except UnicodeDecodeError:  # Windows decodes names strictly; keep the bytes the same way
        return raw.decode("utf-8", errors="surrogateescape")


def _allowed_by(path: str, allowed: tuple[str, ...]) -> str | None:
    """The allowlist entry that covers ``path`` (the entry itself, or a directory above it), if any."""
    return next((a for a in allowed if path == a or path.startswith(a + "/")), None)


def _views(data: bytes) -> list[tuple[str, str]]:
    """The texts one file is searched as: (encoding label, text). See the module docstring for which and why."""
    views = [("utf-8", data.decode("utf-8", errors="replace"))]
    try:
        data.decode("utf-8")
        valid = True
    except UnicodeDecodeError:
        valid = False
    if b"\0" in data:
        views += [(encoding, data.decode(encoding, errors="ignore")) for encoding in WIDE_ENCODINGS]
    if not valid or b"\0" in data:
        views.append(("latin-1", data.decode("latin-1")))
    return views


def match_lines(pattern: re.Pattern[str], text: str) -> list[int]:
    """The 1-based numbers of the lines of ``text`` that hold a match, split on line feeds and carriage returns only."""
    flat = text.replace("\r\n", "\n").replace("\r", "\n")
    normalised = _normal(flat)
    lines: list[int] = []
    number, last = 1, 0
    for match in pattern.finditer(normalised):
        number += normalised.count("\n", last, match.start())
        last = match.start()
        if not lines or lines[-1] != number:
            lines.append(number)
    return lines


def scan(
    root: Path, identifiers: tuple[str, ...], allow: tuple[fc.HygieneAllow, ...]
) -> tuple[list[Finding], list[str]]:
    """Every finding under ``root`` for ``identifiers``, and the allowlisted paths that carried one (for the report)."""
    if not identifiers:
        return [], []
    pattern = build_pattern(identifiers)
    allowed = (*ALWAYS_ALLOWED, *(a.path for a in allow))
    paths, source = candidate_paths(root)
    lfs = lfs_paths(root, paths) if source == "git" else set()
    _LOGGER.info(
        f"scanning {len(paths)} file(s) under {root} (list from {source}) for {len(identifiers)} identifier(s)"
    )
    findings: list[Finding] = []
    used: set[str] = set()
    for rel in paths:
        entry = _allowed_by(rel, allowed)
        full = root / rel
        carried = bool(pattern.search(_normal(rel)))
        if carried and entry is None:
            findings.append(Finding(rel, 0, "the file name contains an identifier"))
        if full.is_symlink():  # not followed: git stores the link text, and a target outside the root is not ours
            if pattern.search(_normal(os.readlink(full))):
                carried = True
                if entry is None:
                    findings.append(Finding(rel, 0, "the link target contains an identifier"))
        elif full.is_dir():
            _LOGGER.warning(f"{rel} is a submodule or a directory entry: its files are not scanned")
        elif rel in lfs:
            # an LFS binary: content not read (see lfs_paths), so an entry for it is not stale; the name was checked
            carried = True
        elif full.is_file():
            carried = _scan_file(full, rel, pattern, entry, findings) or carried
        if carried and entry is not None:
            used.add(entry)
    for entry in allowed:
        if entry not in ALWAYS_ALLOWED and entry not in used:
            findings.append(Finding(entry, 0, "is in hygiene_allow but carries no identifier; remove it from the list"))
    if lfs:
        _LOGGER.info(f"{len(lfs)} LFS-tracked file(s) were not read for content (their names were checked)")
    if not paths:
        findings.append(Finding(".", 0, "no files to scan: a scan of nothing proves nothing"))
    return findings, sorted(used)


def _scan_file(full: Path, rel: str, pattern: re.Pattern[str], entry: str | None, findings: list[Finding]) -> bool:
    """Search one file in every view and append the findings; whether it carries an identifier or cannot be shown not
    to (too large, unreadable)."""
    try:
        if full.stat().st_size > MAX_BYTES:
            if entry is None:
                findings.append(Finding(rel, 0, f"not scanned: larger than {MAX_BYTES:,} bytes"))
            return True
        data = full.read_bytes()
    except OSError as e:
        if entry is None:
            findings.append(Finding(rel, 0, f"not scanned: {type(e).__name__}: {e}"))
        return True
    carried = False
    for label, text in _views(data):
        for number in match_lines(pattern, text):
            carried = True
            if entry is None:
                suffix = "" if label == "utf-8" else f" (read as {label})"
                findings.append(Finding(rel, number, f"holds an identifier{suffix}; the line is not shown"))
    return carried


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # a finding naming a non-ASCII file must not crash the report
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="backslashreplace")
    args = list(sys.argv[1:] if argv is None else argv)
    verbose = "-v" in args
    args = [a for a in args if a != "-v"]
    if len(args) > 1 or any(a.startswith("-") for a in args):
        print("usage: check_hygiene.py [-v] [root]", file=sys.stderr)
        return 2
    _logging.basicConfig(level=_logging.INFO if verbose else _logging.WARNING, format="%(message)s", stream=sys.stderr)
    root = Path(args[0]) if args else Path(__file__).resolve().parent.parent
    if not root.is_dir():
        print(f"hygiene check: cannot run: {root} is not a directory", file=sys.stderr)
        return 2
    try:
        project = fc.load_project(root / "project.json")
        allow = fc.load_framework(root / "framework.toml").hygiene_allow if (root / "framework.toml").exists() else ()
    except fc.ConfigError as e:
        print(f"hygiene check: cannot run: {e}", file=sys.stderr)
        return 2
    findings, used = scan(root, project.hygiene, allow)
    reasons = {a.path: a.reason for a in allow}
    for finding in sorted(findings, key=lambda f: (f.path, f.line, f.detail)):
        print(finding)
    pattern = build_pattern(project.hygiene) if project.hygiene else None
    for entry in used:
        reason = reasons.get(entry, "holds the identifiers")
        if pattern is not None and pattern.search(_normal(reason)):
            reason = "(the reason names an identifier, so it is not shown; see framework.toml)"
        print(f"[allowed] {entry}: {reason}")
    if findings:
        print(f"hygiene check: {len(findings)} finding(s)")
        return 1
    if not project.hygiene:
        print("hygiene check: no identifiers configured (project.json: hygiene is empty); nothing to check")
    else:
        count = len(project.hygiene)
        print(f"hygiene check: clean ({count} identifier(s), {len(used)} allowlisted path(s) carrying one)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
