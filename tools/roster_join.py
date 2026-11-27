"""
Framework: a newcomer adds their own row to the roster in one step.
Package: tools/roster_join

The ``commit-msg`` hook rejects a sign-off the roster (``[[people]]`` in ``framework.toml``) does not hold, and names
this tool. It writes the row the hook needs: the identity ``git commit -s`` writes (``git var GIT_COMMITTER_IDENT``,
so ``GIT_COMMITTER_NAME`` and ``GIT_COMMITTER_EMAIL`` count as git counts them) under the person's GitHub login
(``--login``, or else ``gh api user`` asked of the host of this repository's ``origin``). Nothing else is written: no
``git add``, no commit, nothing to the forge. The pull request that carries the row is how a person on the roster
accepts the newcomer. The spec is ``Docs/superpowers/specs/roster-join.md`` in the template.

What it does with the identity and the login:

* a row with that login holds this name and address: says so, exit 0;
* the identity is ``project.json``'s owner and no row has that login: exit 1 (the owner writes their own row);
* a row with that login and this name: its ``emails`` gains the address;
* a row with that login and another name, or the address on another login's row: exit 1, naming which;
* no row with that login: a new ``contributor`` row after the last ``[[people]]`` table.

The new text is written to a temporary file beside ``framework.toml``, loaded, and checked with
``check_commit_msg.check_message`` (a sign-off required whatever ``project.json`` says); only a candidate that passes
replaces it, and only if ``framework.toml`` is still byte for byte what was read when compared just before the
replace. That catches an edit made before the comparison. **A known limit**, pinned by a test: nothing holds the file
between the comparison and the replace, so a second join that replaces it inside that gap is overwritten, and both
exit 0 (#279). Run one join at a time in a checkout. Run standalone (exit code 0 written or already there, 1 refused by
the roster's rules, 2 an input is unusable or the write failed)::

    uv run python tools/roster_join.py [--login=LOGIN] [-v] [--root PATH]
"""

from __future__ import annotations

import argparse
import logging as _logging
import os
import re
import stat
import subprocess
import sys
import tempfile
import unicodedata
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlsplit

import check_commit_msg as ccm
import framework_config as fc
import framework_sync as fsync
import log_setup

# -------------------------------------------------------------------------
# module global scope
_MODULE_NAME = "tools.roster_join"
__version__ = "0.1.1"
__updated__ = "2026-11-22"
_LOGGER = _logging.getLogger(_MODULE_NAME)

ROOT = Path(__file__).resolve().parent.parent
#: Seconds ``git`` or ``gh`` may take before it counts as not answering.
TIMEOUT = 30
#: A ``[[people]]`` table header, bare or quoted (``[["people"]]``), allowing spaces inside the brackets and a
#: comment after. A key spelled with escapes is not matched, and the join refuses it rather than guess.
_PEOPLE_RE = re.compile(r"""\s*\[\[\s*(?:people|"people"|'people')\s*\]\]\s*(#.*)?""")
#: Any table header: a line whose first non-blank character is ``[``.
_HEADER_RE = re.compile(r"\s*\[")
#: One line with its own ending (``\n`` or ``\r\n``), or a last line without one.
_LINE_RE = re.compile(r"[^\n]*\n|[^\n]+\Z")
#: A TOML string on a line, removed before looking for a ``#`` comment.
_STRING_RE = re.compile(r'"(?:[^"\\]|\\.)*"|\'[^\']*\'')
#: An scp-like git remote, ``[user@]host:path``.
_SCP_RE = re.compile(r"(?:[^@/\s]+@)?([^:/\s]+):")
_LOGIN_HINT = "pass --login=<your login>"

Runner = Callable[..., "subprocess.CompletedProcess[str]"]


class Stop(Exception):
    """The run ends here: ``code`` is the exit code and ``message`` what the person is told."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(code, message)
        self.code = code
        self.message = message


# -------------------------------------------------------------------------
# the inputs
def _call(run: Runner, argv: list[str], env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """``argv`` run with no input, a timeout and UTF-8 output, as ``check_commit_msg._git`` runs git."""
    _LOGGER.info(f"running {' '.join(argv)}")
    return run(
        argv,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdin=subprocess.DEVNULL,
        timeout=TIMEOUT,
        check=False,
        **({"env": env} if env is not None else {}),
    )


def _git(run: Runner, root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """git under ``root``; ``Stop`` (exit 2) when git cannot be run or does not answer in time."""
    try:
        return _call(run, ["git", "-C", str(root), *args])
    except (OSError, subprocess.TimeoutExpired) as e:
        raise Stop(2, f"cannot run git: {e}") from e


def identity(run: Runner, root: Path) -> tuple[str, str]:
    """The ``(name, email)`` ``git commit -s`` signs with here, parsed as ``framework_sync._signoff`` parses it.

    :raises Stop: git cannot run, or has no identity to give.
    """
    done = _git(run, root, "var", "GIT_COMMITTER_IDENT")
    match = fsync._IDENT_RE.fullmatch(done.stdout.strip()) if done.returncode == 0 else None
    if match is None:
        _LOGGER.info(f"git var GIT_COMMITTER_IDENT: exit {done.returncode}, {done.stdout.strip()!r}")
        raise Stop(
            2,
            'git has no name and email for you here: set them with git config user.name "Your Name" and '
            "git config user.email you@example.com, then run this again",
        )
    return match.group(1).strip(), match.group(2).strip()


def origin_host(run: Runner, root: Path) -> str | None:
    """The host of this repository's ``origin`` remote, or ``None`` when there is none or it names no host."""
    done = _git(run, root, "remote", "get-url", "origin")
    url = done.stdout.strip() if done.returncode == 0 else ""
    host: str | None = None
    if "://" in url:
        try:
            host = urlsplit(url).hostname
        except ValueError:
            host = None
    elif url:
        scp = _SCP_RE.match(url)
        host = scp.group(1) if scp else None
    if host is None or not fc._HOST_RE.fullmatch(host):
        _LOGGER.info(f"origin {url!r} names no host")
        return None
    return host.lower()


def is_login(value: str) -> bool:
    """A GitHub login by the roster's rule (``framework_config.LOGIN_PATTERN`` and ``LOGIN_MAX``)."""
    return len(value) <= fc.LOGIN_MAX and re.fullmatch(fc.LOGIN_PATTERN, value) is not None


def gh_login(run: Runner, root: Path) -> str:
    """The login ``gh`` is signed in as on ``origin``'s host.

    :raises Stop: no ``origin`` host, or ``gh`` missing, failing, slow or giving anything but one login.
    """
    host = origin_host(run, root)
    if host is None:
        raise Stop(2, f"this repository has no origin remote naming a host to ask gh about: {_LOGIN_HINT}")
    # --hostname always, github.com too: it outranks GH_HOST, which may name another host
    argv = ["gh", "api", "user", "--jq", ".login", "--hostname", host]
    try:
        done = _call(run, argv, env={**os.environ, "GH_PROMPT_DISABLED": "1"})
    except (OSError, subprocess.TimeoutExpired) as e:
        raise Stop(2, f"cannot ask gh for your login on {host} ({e}): {_LOGIN_HINT}") from e
    lines = done.stdout.splitlines()
    if done.returncode != 0 or len(lines) != 1 or not is_login(lines[0].strip()):
        _LOGGER.info(f"gh api user: exit {done.returncode}, {done.stdout!r}")
        raise Stop(2, f"gh gave no login for {host} (is it installed and signed in?): {_LOGIN_HINT}")
    return lines[0].strip()


def _check_identity(name: str, email: str) -> None:
    """``Stop`` (exit 2) unless the roster's rules and a ``Signed-off-by:`` line can both carry the identity."""
    if (
        not name
        or len(name.splitlines()) != 1
        or any(unicodedata.category(c)[0] == "C" or unicodedata.category(c) in ("Zl", "Zp") for c in name)
        or any(c in "<>" for c in name)
    ):
        raise Stop(
            2,
            f"git names you {name!r}, which a Signed-off-by line cannot carry (one line, no control characters, "
            'no < or >): set it with git config user.name "Your Name"',
        )
    if not fc._EMAIL_RE.fullmatch(email):
        raise Stop(
            2, f"the roster cannot hold the address {email!r}: set one with git config user.email you@example.com"
        )


# -------------------------------------------------------------------------
# the text
def _body(line: str) -> str:
    return line.rstrip("\r\n")


def _blank_or_comment(line: str) -> bool:
    body = _body(line).strip()
    return not body or body.startswith("#")


def _has_comment(line: str) -> bool:
    return "#" in _STRING_RE.sub("", _body(line))


def _row(person: fc.Person, newline: str) -> str:
    """``person``'s table as ``framework_config.dump_person`` writes it, in the file's line ending."""
    return newline.join(fc.dump_person(person).rstrip("\n").split("\n")) + newline  # not splitlines: see dump_framework


def _next_header(lines: list[str], after: int) -> int | None:
    return next((j for j in range(after + 1, len(lines)) if _HEADER_RE.match(lines[j])), None)


def with_new_row(lines: list[str], person: fc.Person, newline: str) -> str:
    """The text with ``person``'s row after the last ``[[people]]`` table, one blank line before it: before the next
    table, above the blank and comment lines that lead into it, or at the end of the file."""
    last = max(i for i, line in enumerate(lines) if _PEOPLE_RE.fullmatch(_body(line)))
    header = _next_header(lines, last)
    row = _row(person, newline)
    if header is None:
        text = "".join(lines)
        if not text.endswith("\n"):
            text += newline
        return text + ("" if not lines[-1].strip() else newline) + row
    at = header
    while at - 1 > last and _blank_or_comment(lines[at - 1]):
        at -= 1
    after = "" if not lines[at].strip() else newline
    return "".join(lines[:at]) + newline + row + after + "".join(lines[at:])


def with_row_replaced(lines: list[str], index: int, person: fc.Person, newline: str) -> tuple[str, bool]:
    """The text with the ``index``-th ``[[people]]`` table replaced by ``person``'s, and whether a comment inside the
    old table was dropped. The table runs from its header to its last line before the blank and comment lines that
    lead into the next header."""
    headers = [i for i, line in enumerate(lines) if _PEOPLE_RE.fullmatch(_body(line))]
    start = headers[index]
    end = _next_header(lines, start)
    stop = len(lines) if end is None else end
    while stop - 1 > start and _blank_or_comment(lines[stop - 1]):
        stop -= 1
    dropped = any(_has_comment(line) for line in lines[start:stop])
    last = lines[stop - 1]
    row = _row(person, newline)[: -len(newline)] + last[len(_body(last)) :]
    return "".join(lines[:start]) + row + "".join(lines[stop:]), dropped


# -------------------------------------------------------------------------
# the write
def _write_checked(path: Path, raw: bytes, text: str, project: fc.ProjectConfig, name: str, email: str) -> None:
    """Replace ``path`` with ``text`` only if it loads, the hook accepts ``name <email>`` against it, and ``path``
    still holds ``raw`` when compared just before the replace; ``Stop`` (exit 2) otherwise, with ``path`` untouched and
    no temporary file left. The comparison is not a lock: a replace by another join between it and ours is lost (#279).
    """
    try:
        fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    except OSError as e:
        raise Stop(2, f"cannot write beside framework.toml, so nothing was written: {e}") from e
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(text.encode("utf-8"))
        os.chmod(temporary, stat.S_IMODE(path.stat().st_mode))  # mkstemp makes it 0600; keep the file's own
        try:
            people = fc.load_framework(Path(temporary)).people
        except fc.ConfigError as e:
            raise Stop(2, f"the new framework.toml would not load, so nothing was written: {e.message}") from e
        signed = f"x\n\nSigned-off-by: {name} <{email}>\n"
        found = ccm.check_message(signed, replace(project, signoff=True), people)
        if found:
            raise Stop(2, "the new framework.toml would not pass the hook, so nothing was written: " + "; ".join(found))
        if path.read_bytes() != raw:
            raise Stop(2, "framework.toml changed while this ran; run it again")
        os.replace(temporary, path)
        _LOGGER.info(f"replaced {path} ({len(text)} characters)")
    except OSError as e:
        raise Stop(2, f"cannot write framework.toml, so nothing was written: {e}") from e
    finally:
        Path(temporary).unlink(missing_ok=True)


# -------------------------------------------------------------------------
# the run
def _load(root: Path) -> tuple[fc.ProjectConfig, Path, bytes, tuple[fc.Person, ...]]:
    """``project.json``, the ``framework.toml`` path, its raw bytes and its people; ``Stop`` (exit 2) on any of them
    missing, unreadable or invalid, on a link, and on no roster."""
    try:
        project = fc.load_project(root / "project.json")
    except fc.ConfigError as e:
        raise Stop(2, f"cannot read this repository's project.json: {e}") from e
    path = root / "framework.toml"
    try:
        if fc.is_link(path):
            raise Stop(2, f"{path} is a link: add your row by hand to the file it points to")
        if fc.path_kind(path) == "missing":
            raise Stop(2, f"there is no framework.toml under {root}: run this from the repository's root")
        raw = path.read_bytes()  # one read: the roster and the bytes compared before the write are the same file
        config = fc.parse_framework_text(raw.decode("utf-8"))
    except UnicodeDecodeError as e:
        raise Stop(2, f"cannot read this repository's framework.toml: it is not UTF-8 ({e})") from e
    except (fc.ConfigError, OSError) as e:
        raise Stop(2, f"cannot read this repository's framework.toml: {e}") from e
    if not config.people:
        raise Stop(2, "this repository has no roster yet; its owner adds the first row")
    return project, path, raw, config.people


def join(root: Path, login: str | None, run: Runner) -> int:
    """Add the identity git commits with here to the roster under ``login`` (or ``gh``'s); the exit code.

    :raises Stop: an input is unusable, or the roster's rules refuse the row.
    """
    project, path, raw, people = _load(root)
    name, email = identity(run, root)
    if login is None:
        login = gh_login(run, root)
    elif not is_login(login):
        raise Stop(2, f"--login={login} is not a GitHub login (letters, digits and single hyphens, at most 39)")
    _check_identity(name, email)
    _LOGGER.info(f"identity {name} <{email}>, login @{login}, {len(people)} on the roster")

    by_login = next((p for p in people if p.login.casefold() == login.casefold()), None)
    by_email = next((p for p in people if email.casefold() in (e.casefold() for e in p.emails)), None)
    if by_login is not None and by_login.name == name and by_email is by_login:
        print(f"join: {name} <{email}> is already on the roster (@{by_login.login})")
        return 0
    owner = project.owner
    if by_login is None and (name, email.casefold()) == (owner.name, owner.email.casefold()):
        raise Stop(
            1,
            f"{name} <{email}> is this repository's owner (project.json), and the roster has no row for @{login}: "
            'the owner adds their own row by hand, with role = "owner"',
        )
    if by_login is not None and by_login.name != name:
        raise Stop(
            1, f'the roster names @{by_login.login} "{by_login.name}", git names you "{name}": change one so they match'
        )
    if by_email is not None and by_email is not by_login:
        raise Stop(1, f"{email} is already on @{by_email.login}'s row: one address belongs to one person")

    text = raw.decode("utf-8")  # _load decoded these same bytes
    newline = "\r\n" if "\n" in text and text[: text.index("\n")].endswith("\r") else "\n"
    lines = _LINE_RE.findall(text)
    headers = sum(1 for line in lines if _PEOPLE_RE.fullmatch(_body(line)))
    person = (
        fc.Person(login, name, "contributor", (email,))
        if by_login is None
        else replace(by_login, emails=(*by_login.emails, email))
    )
    if headers != len(people):
        raise Stop(
            2,
            "the roster is an inline array; add your row by hand, or rewrite it as [[people]] tables:\n"
            + fc.dump_person(person),
        )
    if by_login is None:
        candidate, dropped = with_new_row(lines, person, newline), False
    else:
        candidate, dropped = with_row_replaced(lines, people.index(by_login), person, newline)
    _write_checked(path, raw, candidate, project, name, email)
    if by_login is None:
        print(f"join: added @{login} ({name} <{email}>, contributor) to framework.toml")
    else:
        print(f"join: added {email} to @{by_login.login}'s row ({name}) in framework.toml")
    if dropped:
        print(f"join: a comment inside @{person.login}'s row was dropped when the row was rewritten")
    # prose, not a command to paste: a shell expands a $ in a path even inside double quotes
    print(f"next: in {root}, run git add framework.toml, then commit again; open your pull request as usual.")
    print("      A person on the roster reviews the row when they merge it.")
    return 0


def main(argv: list[str] | None = None, run: Runner = subprocess.run) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--login", help="your GitHub login, as --login=<login> (default: asked of gh)")
    parser.add_argument("--root", type=Path, default=ROOT, help="the repository whose roster to join")
    parser.add_argument("-v", "--verbose", action="store_true", help="log what was read to standard error")
    args = parser.parse_args(argv)
    log_setup.configure(args.verbose)
    try:
        return join(args.root, args.login, run)
    except Stop as e:
        print(f"join: {e.message}", file=sys.stderr)
        return e.code


if __name__ == "__main__":
    sys.exit(main())
