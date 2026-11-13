"""
Framework: the log-format check: no lazy ``%``-formatted log call; the message is an f-string.
Package: tools/check_log_format

The rule (Docs/standards/python.md): log calls use f-strings, because a message you can read in the source is a
message a person can troubleshoot. ``_LOGGER.info("wrote %s", path)`` and ``_LOGGER.info("wrote %s" % path)`` are
findings. The one exception is a measured hot path, marked on the call's first line with a comment
``# lazy-log: <the measurement>`` (it may follow another comment such as ``# noqa``); a bare marker with no measurement
is itself a finding. A tight loop should not log at all (collect, then log once).

What counts as a log call: ``<receiver>.<level>(...)`` where the receiver is a name or attribute that is ``log``,
``logger``, ``logging`` or ends in ``logger`` (any case, leading underscores ignored: ``_LOGGER``, ``self._log``), or a
``logging.getLogger(...)`` call; and ``<receiver>.log(level, message, ...)``. **Known gaps**, pinned by tests so
they are decisions and not surprises: a logger held under another name (``out.info(...)``), a method taken as a
variable (``f = _LOGGER.info``), and a message template held in a variable (``_LOGGER.info(template, x)``) are not
seen.

Every ``*.py`` and ``*.pyw`` under the root is read (a script with only a shebang is not), as Python reads it (a coding
declaration is honoured), except the folders the documents' walk leaves out (``exclude_parts`` of the ``[docs]``
table: spikes, scratch and worktrees), ``.git``, ``.venv``, ``node_modules``, ``__pycache__`` and ``site-packages`` at
any depth, and ``build``, ``dist`` and ``venv`` at the top only. A file that does not parse (too deeply nested
included), or cannot be decoded, is a finding, never a silent pass; so is a directory that cannot be listed, and so is a
scan that found no Python file at all.

Run standalone (exit code 0 clean, 1 findings, 2 the configuration or the arguments are unusable)::

    uv run python tools/check_log_format.py [-v] [root]

``tests/test_check_log_format.py`` runs it on fixtures and on the tree.
"""

from __future__ import annotations

import ast
import io
import logging as _logging
import os
import re
import sys
import tokenize
from dataclasses import dataclass
from pathlib import Path

import framework_config as fc
import log_setup

# -------------------------------------------------------------------------
# module global scope
_MODULE_NAME = "tools.check_log_format"
__version__ = "0.3.1"
__updated__ = "2026-11-07"
_LOGGER = _logging.getLogger(_MODULE_NAME)

#: Directories never scanned, at any depth, whatever the configuration says: other checkouts and installed packages.
ALWAYS_SKIPPED = frozenset({".git", ".venv", "node_modules", "__pycache__", "site-packages"})

#: Directories skipped only at the top of the tree, where they are build output; ``pkg/build/mod.py`` is source.
TOP_LEVEL_SKIPPED = frozenset({"build", "dist", "venv"})

#: The file extensions read.
EXTENSIONS = (".py", ".pyw")

#: The logging methods that take a message first.
LEVELS = frozenset({"debug", "info", "warning", "warn", "error", "exception", "critical", "fatal"})

#: ``Logger.log(level, message, ...)`` takes the message second.
LEVEL_FIRST = "log"

#: A ``%`` conversion in a message, the whole of ``str``'s grammar (``%s``, ``%d``, ``%.2f``, ``%-8.3f``, ``%*d``,
#: ``%.*f``, ``%ld``, ``%o``, ``%u``, ``%a``, ``%(name)s``), or a literal ``%%`` (matched first, so ``%%%s`` is a
#: literal percent followed by a placeholder).
_CONVERSION = re.compile(r"%%|%(?:\([^)]*\))?[#0\- +]*(?:\d+|\*)?(?:\.(?:\d+|\*))?[hlL]?[diouxXeEfFgGcrsa]")

#: The comment that lets a measured hot path keep a lazy call: ``# lazy-log: <the measurement>``, alone or after
#: another comment on the same line.
MARKER = re.compile(r"(?:^|#)\s*lazy-log:\s*(?P<measurement>.*)$")

#: A receiver name that is a logger: ``log``, ``logger``, ``logging``, or ending in ``logger`` or ``_log``, with an
#: optional number (``logger2``, ``app_log``); ``dialog`` and ``blog`` are not.
_LOGGER_NAME = re.compile(r"^_*(log|logger|logging|\w*logger|\w+_log)\d*$", re.IGNORECASE)


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    reason: str

    def __str__(self) -> str:
        return f"[log-format] {self.path}:{self.line}: {self.reason}"


def _imports(tree: ast.AST) -> tuple[frozenset[str], frozenset[str]]:
    """The names this module binds to the ``logging`` module and to ``logging.getLogger`` (``import logging as lg``,
    ``from logging import getLogger as gl``). ``logging`` itself is always a candidate, so a snippet reads as it is."""
    modules, factories = {"logging"}, set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(a.asname or a.name for a in node.names if a.name == "logging")
        elif isinstance(node, ast.ImportFrom) and node.module == "logging":
            factories.update(a.asname or a.name for a in node.names if a.name == "getLogger")
    return frozenset(modules), frozenset(factories)


def _is_logger(
    node: ast.expr, modules: frozenset[str] = frozenset({"logging"}), factories: frozenset[str] = frozenset()
) -> bool:
    """Whether ``node`` (the receiver of a method call) is a logger by its name, or a call of ``logging.getLogger``.

    A call counts only when it provably is the standard library's: ``<module>.getLogger(...)`` where the module name is
    ``logging`` or an alias of it, or ``getLogger(...)`` where the name was imported from ``logging``. A method named
    ``getLogger`` on any other object, and a function of that name defined here, are not."""
    if isinstance(node, ast.Name):
        return bool(_LOGGER_NAME.match(node.id))
    if isinstance(node, ast.Attribute):
        return bool(_LOGGER_NAME.match(node.attr))
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Attribute):
            return func.attr == "getLogger" and isinstance(func.value, ast.Name) and func.value.id in modules
        return isinstance(func, ast.Name) and func.id in factories
    return False


def _has_placeholder(message: str) -> bool:
    return any(m.group(0) != "%%" for m in _CONVERSION.finditer(message))


def _comments(source: str) -> dict[int, str]:
    """The comment on each line that has one, by line number, from the tokenizer (never from string contents)."""
    out: dict[int, str] = {}
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type == tokenize.COMMENT:
                out[tok.start[0]] = tok.string
    except (tokenize.TokenError, IndentationError):
        pass
    return out


def check_source(source: str, path: str = "<source>") -> list[Finding]:
    """The findings in ``source``: a lazy ``%`` log call without the hot-path marker, a marker with no measurement,
    and a source that does not parse (a file that cannot be read must not pass for one that is clean)."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError) as e:  # ValueError: null bytes; the others: depth
        return [
            Finding(
                path,
                getattr(e, "lineno", None) or 1,
                f"does not parse, so its log calls are unchecked: {type(e).__name__}: {e}",
            )
        ]
    comments = _comments(source)
    modules, factories = _imports(tree)
    out: list[Finding] = []
    for line, comment in comments.items():  # a marker with no measurement is a finding wherever it sits
        bare = MARKER.search(comment)
        if bare and not bare.group("measurement").strip():
            out.append(Finding(path, line, "the lazy-log marker needs the measurement after the colon"))
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        attr = node.func.attr
        if (attr not in LEVELS and attr != LEVEL_FIRST) or not _is_logger(node.func.value, modules, factories):
            continue
        args = node.args[1:] if attr == LEVEL_FIRST else node.args
        if not args:
            continue
        first = args[0]
        text = first.value if isinstance(first, ast.Constant) and isinstance(first.value, str) else None
        if text is not None and len(args) > 1 and _has_placeholder(text):
            reason = "a lazy %-format log call with arguments"
        elif isinstance(first, ast.BinOp) and isinstance(first.op, ast.Mod):
            left = first.left
            if not (isinstance(left, ast.Constant) and isinstance(left.value, str)):
                continue  # numeric modulo, or a template we cannot see: not a message
            reason = "a %-operator log message"
        else:
            continue
        marker = MARKER.search(comments.get(node.lineno, ""))
        if marker and marker.group("measurement").strip():
            continue
        if marker:
            continue  # a bare marker was reported above, once, whatever the call
        out.append(Finding(path, node.lineno, f"{reason}: write the message as an f-string"))
    return sorted(out, key=lambda f: (f.line, f.reason))


def _skipped(relative: Path, skip: frozenset[str]) -> bool:
    """Whether the walk never reaches ``relative`` (a path under the root): a skipped folder on the way, or a top-level
    one."""
    parts = relative.parts
    return any(part in skip for part in parts) or bool(parts and parts[0] in TOP_LEVEL_SKIPPED)


def python_files(root: Path, skip: frozenset[str], errors: list[Finding]) -> list[Path]:
    """Every ``*.py`` under ``root`` outside the skipped directories (pruned while walking); a directory that cannot be
    listed is appended to ``errors`` as a finding."""

    def record(error: OSError) -> None:
        where = Path(str(error.filename))
        try:
            where = where.relative_to(root)
        except ValueError:
            pass
        errors.append(Finding(where.as_posix(), 1, f"cannot be listed, so its log calls are unchecked: {error}"))

    found: list[Path] = []
    real_root = root.resolve()
    for current, dirs, files in os.walk(root, onerror=record):
        top = Path(current) == root
        dirs[:] = sorted(d for d in dirs if d not in skip and not (top and d in TOP_LEVEL_SKIPPED))
        # The walk never enters a linked folder (a junction included), and lists a looping link among the files. A
        # loop is source unseen; so is a linked folder whose target is outside the root, which nothing else walks
        # (issue #78), or inside it where the walk skips. A link to a folder the walk reads (a venv's lib64 -> lib) is
        # seen where it points, and a dangling link holds nothing.
        linked: set[str] = set()
        for name in [*dirs, *(f for f in files if not f.endswith(EXTENSIONS))]:
            path = Path(current) / name
            where = path.relative_to(root).as_posix()
            try:
                if not fc.is_link(path):
                    continue
                linked.add(name)
                if fc.path_kind(path) != "dir":
                    continue
                target = path.resolve(strict=True)
            except OSError as e:
                linked.add(name)  # its kind or its target cannot be read: not entered
                errors.append(Finding(where, 1, f"cannot be read, so its log calls are unchecked: {e}"))
                continue
            if not target.is_relative_to(real_root):
                reason = "links to a folder outside the root, which is not followed: its log calls are unchecked"
            elif _skipped(target.relative_to(real_root), skip):
                reason = "links to a folder the walk skips, which is not followed: its log calls are unchecked"
            else:
                continue
            errors.append(Finding(where, 1, reason))
        dirs[:] = [d for d in dirs if d not in linked]
        found += [Path(current) / name for name in sorted(files) if name.endswith(EXTENSIONS)]
    return found


def read_source(path: Path) -> str:
    """The text of a Python file as Python itself reads it: UTF-8 unless a byte-order mark or a coding declaration
    (PEP 263) in the first two lines says otherwise. Raises ``SyntaxError`` (a bad declaration), ``LookupError`` (an
    unknown codec) or ``UnicodeDecodeError``."""
    data = path.read_bytes()
    encoding, _ = tokenize.detect_encoding(io.BytesIO(data).readline)
    return data.decode(encoding)


def check_tree(root: Path, extra_skipped: tuple[str, ...] = ()) -> list[Finding]:
    """Every finding under ``root``, in path order."""
    skip = ALWAYS_SKIPPED | set(extra_skipped)
    out: list[Finding] = []
    paths = python_files(root, frozenset(skip), out)
    if not paths:
        out.append(Finding(".", 1, "no Python file found: a scan of nothing proves nothing"))
    for path in paths:
        rel = path.relative_to(root).as_posix()
        try:
            source = read_source(path)
        except (SyntaxError, LookupError, UnicodeDecodeError) as e:
            out.append(Finding(rel, 1, f"cannot be decoded, so its log calls are unchecked: {e}"))
            continue
        except OSError as e:
            out.append(Finding(rel, 1, f"cannot be read, so its log calls are unchecked: {e}"))
            continue
        out.extend(check_source(source, rel))
    _LOGGER.info(f"read {len(paths)} Python file(s) under {root}, skipping {', '.join(sorted(skip))}")
    return sorted(out, key=lambda f: (f.path, f.line, f.reason))


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # a finding naming a non-ASCII file must not crash the report
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="backslashreplace")
    args = list(sys.argv[1:] if argv is None else argv)
    verbose = "-v" in args
    args = [a for a in args if a != "-v"]
    if len(args) > 1 or any(a.startswith("-") for a in args):
        print("usage: check_log_format.py [-v] [root]", file=sys.stderr)
        return 2
    log_setup.configure(verbose)
    root = Path(args[0]) if args else Path(__file__).resolve().parent.parent
    if not root.is_dir():
        print(f"log-format check: cannot run: {root} is not a directory", file=sys.stderr)
        return 2
    try:
        config_path = root / "framework.toml"
        docs = fc.load_framework(config_path).docs if config_path.exists() else fc.DocsConfig()
    except fc.ConfigError as e:
        print(f"log-format check: cannot run: {e}", file=sys.stderr)
        return 2
    findings = check_tree(root, docs.exclude_parts)
    for finding in findings:
        print(finding)
    if findings:
        print(f"log-format check: {len(findings)} finding(s); see Docs/standards/python.md")
        return 1
    print("log-format check: clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
