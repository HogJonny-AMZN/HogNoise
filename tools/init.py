"""
Framework: the initialiser. `init new` writes a repository from the payload and records what it did.
Package: tools/init

    uv run payload/tools/init.py new --answers answers.json --target ../my-project
    uv run payload/tools/init.py new --target ../my-project --dry-run      # asks for the answers on a terminal

``adopt`` (``init_adopt.py``) brings a repository that predates the template under it: a report by default, ``--apply``
to do it, never overwriting a file the project owns.

``new`` reads the project's values (``answers.json`` in the ``project.json`` schema, or prompts), then writes into the
target, by the class the payload's ``framework-manifest.toml`` gives each file:

- **managed** and **parametrised** files are written verbatim or with the project's values substituted, and their hashes
  go into ``framework.lock``;
- **project-owned** files are seeded once, only if absent, and never overwritten (so ``pyproject.toml`` and ``uv.lock``,
  which a project edits on its first ``uv add``, are seeds);
- a file of a module that is not ``on`` in ``framework.toml`` is skipped, and the record says why.

It writes ``project.json`` and ``framework.lock`` and, if the target has none, a ``framework.toml`` from the payload's.
It is idempotent (a second run over a finished target changes no file), refuses before writing anything when the
answers are invalid, when an unrelated file or a file where a directory belongs is in the way, when a managed file was
edited since the lock, or when the template version moved, and ends by running ``uv sync`` and the target's own gate
(``tools/check.py``) if it has one. Files are written to a temporary name and renamed, and the lock is written last, so
a failure part-way leaves no file truncated and no lock claiming files that are not there; a re-run recovers.

Exit codes: 0 done; 1 refused input (nothing written); 2 the write, ``uv sync`` or the gate failed after writing began.
A real run leaves ``logs/init-<UTC timestamp>.log`` in the target (git-ignored, outside every "no file changes"
assertion), also when it fails; ``--dry-run`` writes no file anywhere and prints the plan instead.

Not here yet: ``--github`` and ``--clear-specimens`` (the design's later increments).
"""

from __future__ import annotations

import argparse
import copy
import dataclasses
import datetime as _dt
import fnmatch
import hashlib
import json
import logging as _logging
import os
import re
import stat
import subprocess
import sys
import tempfile
import tomllib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NamedTuple

import framework_config as fc

# -------------------------------------------------------------------------
# module global scope
_MODULE_NAME = "tools.init"
__version__ = "0.2.0"
__updated__ = "2026-10-10"
_LOGGER = _logging.getLogger(_MODULE_NAME)

SOURCE = Path(__file__).resolve().parents[1]
MANIFEST_NAME = "framework-manifest.toml"
KINDS = ("managed", "parametrised", "project-owned")
ROOT_JUNK = frozenset({".venv", ".git", "logs"})  # skipped at the payload root only
ANYWHERE_JUNK = frozenset({"__pycache__", ".pytest_cache", ".ruff_cache"})
GENERATED = frozenset({"project.json", "framework.lock"})  # written by init, never part of a payload
LINKED_MODULES = (
    "journal",
    "python-uv",
    "graph",
    "harness-adapters",
)  # modules whose files the always-seeded documents link to
EXIT_OK, EXIT_REFUSED, EXIT_FAILED = 0, 1, 2
_TOKEN_RE = re.compile(r"\{\{(\w+)\}\}|your-project-name")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_PATH_TOKENS = frozenset({"today"})  # the only tokens a payload path may carry, and only in its last component
_DAY_GLOB = "[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]"


class ManifestError(Exception):
    """The payload manifest is not valid (a template bug, not a bad input)."""


class RunResult(NamedTuple):
    """What a subprocess did: its exit code and the output it printed."""

    code: int
    output: str = ""


Runner = Callable[[list[str], Path], RunResult]
Say = Callable[[str], None]


@dataclass(frozen=True)
class Rule:
    """One manifest rule: files matching ``pattern`` belong to ``module`` and are of class ``kind``."""

    pattern: str
    module: str
    kind: str


@dataclass
class Action:
    """What the plan does with one path: ``op`` is create, update, unchanged, keep, override, skip, orphan or refuse."""

    path: str
    op: str
    kind: str
    module: str
    note: str = ""


@dataclass
class Plan:
    """The whole decision, made before anything is written: actions, refusals, and the bytes to write."""

    actions: list[Action]
    refusals: list[str]
    contents: dict[str, bytes]  # path to the bytes to write, for create and update
    generated: dict[str, str]  # project.json and framework.lock text
    initialised: str = ""  # the day recorded in the lock (the local date on a first run)
    template: dict[str, bytes] = field(default_factory=dict)  # path to what the template would write, for every file


# -------------------------------------------------------------------------
# the manifest
def load_manifest(path: Path) -> tuple[Rule, ...]:
    """Read and validate a ``framework-manifest.toml``; raises ``ManifestError``."""
    try:
        data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError) as e:
        raise ManifestError(f"{path}: cannot be read: {e}") from e
    if set(data) - {"rule"} or not isinstance(data.get("rule"), list):
        raise ManifestError(f"{path}: must hold only [[rule]] tables")
    rules = []
    for index, item in enumerate(data["rule"]):
        where = f"{path}: rule {index}"
        if not isinstance(item, dict) or set(item) != {"pattern", "module", "kind"}:
            raise ManifestError(f"{where}: needs exactly pattern, module and kind")
        pattern, module, kind = item["pattern"], item["module"], item["kind"]
        if not isinstance(pattern, str) or not pattern or pattern.startswith("/") or "\\" in pattern or ".." in pattern:
            raise ManifestError(f"{where}: pattern must be a relative forward-slash path pattern")
        if module not in fc.MODULES:
            raise ManifestError(f"{where}: unknown module {module!r}")
        if kind not in KINDS:
            raise ManifestError(f"{where}: kind must be one of {', '.join(KINDS)}")
        rules.append(Rule(pattern, module, kind))
    return tuple(rules)


def discover(source: Path) -> list[str]:
    """Every payload file as a sorted relative posix path, without caches, environments and run records."""
    found = []
    for path in source.rglob("*"):
        rel = path.relative_to(source)
        parts = rel.parts
        if not path.is_file() or path.suffix == ".pyc" or rel.as_posix() in GENERATED:
            continue
        if parts[0] in ROOT_JUNK or set(parts) & ANYWHERE_JUNK:
            continue
        found.append(rel.as_posix())
    return sorted(found)


def classify(rules: tuple[Rule, ...], rel: str) -> Rule | None:
    """The first rule whose pattern matches ``rel``, or None."""
    for rule in rules:
        if fnmatch.fnmatchcase(rel, rule.pattern):
            return rule
    return None


def check_manifest(source: Path) -> list[str]:
    """Problems with a payload's manifest: a file no rule describes, and a rule that describes no file."""
    rules = load_manifest(source / MANIFEST_NAME)
    files = discover(source)
    problems = [f"{rel}: no rule in {MANIFEST_NAME} matches it" for rel in files if classify(rules, rel) is None]
    problems += [
        f"rule {rule.pattern!r} matches no file"
        for rule in rules
        if not any(fnmatch.fnmatchcase(rel, rule.pattern) for rel in files)
    ]
    return problems


# -------------------------------------------------------------------------
# content
def _values(project: fc.ProjectConfig, today: str, template_version: str) -> dict[str, str]:
    """The ``{{name}}`` tokens; ``your-project-name`` (the slug) keeps a seeded pyproject.toml runnable as it is.

    ``today`` is the day the repository was initialised (kept in the lock, so a re-run on another day does not seed a
    second dated file); it may appear in a file's content and in a file's path.
    """
    return {
        "name": project.name,
        "slug": project.slug,
        "owner_name": project.owner.name,
        "owner_email": project.owner.email,
        "default_branch": project.default_branch,
        "today": today,
        "template_version": template_version,
    }


def normalised(raw: bytes) -> bytes:
    """Text with LF line endings (git rewrites them), anything that is not UTF-8 text unchanged."""
    try:
        return raw.decode("utf-8").replace("\r\n", "\n").encode("utf-8")
    except UnicodeDecodeError:
        return raw


def unknown_tokens(raw: bytes, values: dict[str, str]) -> list[str]:
    """``{{word}}`` tokens in a template that no project value answers (a typo), found before substitution."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return []
    return sorted({m.group(0) for m in _TOKEN_RE.finditer(text) if m.group(1) and m.group(1) not in values})


def _render_text(text: str, values: dict[str, str]) -> str:
    """Substitute every token in one pass, so a value that looks like a token is never expanded again."""
    return _TOKEN_RE.sub(lambda m: values[m.group(1)] if m.group(1) else values["slug"], text)


def _render(raw: bytes, values: dict[str, str]) -> bytes:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw
    return _render_text(text, values).encode("utf-8")


def _is_day(text: object) -> bool:
    """A real calendar day written YYYY-MM-DD (``2026-13-45`` is not one)."""
    if not isinstance(text, str) or not _DATE_RE.fullmatch(text):
        return False
    try:
        _dt.date.fromisoformat(text)
    except ValueError:
        return False
    return True


def _recovered_day(source: Path, target: Path, rules: tuple[Rule, ...], rendered_modules: set[str]) -> str | None:
    """The earliest day carried by an existing dated seed, for a lock that lost its ``initialised`` field.

    The true first day is still written in the name of the file the first run seeded (``{{today}}`` in its name), so a
    deleted or older lock gets that day back instead of being stamped with today's.
    """
    days: list[str] = []
    for rel in discover(source):
        rule = classify(rules, rel)
        if (
            rule is None
            or rule.kind != "project-owned"
            or rule.module not in rendered_modules
            or "{{today}}" not in rel
        ):
            continue
        directory, _, name = rel.rpartition("/")
        folder = target / directory
        if not folder.is_dir():
            continue
        shape = re.compile(re.escape(name).replace(re.escape("{{today}}"), "([0-9]{4}-[0-9]{2}-[0-9]{2})"))
        for existing in folder.iterdir():
            match = shape.fullmatch(existing.name)
            if match and existing.is_file() and _is_day(match.group(1)):
                days.append(match.group(1))
    return min(days) if days else None


def file_hash(data: bytes) -> str:
    """SHA-256 of content already passed through ``normalised``: the same on every platform and checkout."""
    return hashlib.sha256(data).hexdigest()


def lock_hash(raw: bytes) -> str:
    """The hash ``framework.lock`` records for a file with these bytes: line endings normalised, then SHA-256. The sync
    check calls this, so that it and ``init`` can never disagree about whether a file is as locked."""
    return file_hash(normalised(raw))


# -------------------------------------------------------------------------
# the plan
def read_lock(target: Path) -> tuple[str, dict[str, str], str | None] | None:
    """``(template version, {path: hash}, day initialised)`` from ``target/framework.lock``; ``None`` if there is none.

    :raises fc.ConfigError: the lock exists and cannot be read, or a key is not a normalised relative path.
    """
    path = target / "framework.lock"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))  # a directory here raises OSError: refused, not "absent"
        version, files = data["template_version"], data["files"]
        if not isinstance(version, str) or not isinstance(files, dict):
            raise TypeError("wrong shape")
        for key, value in files.items():
            if not fc.is_relative_path(key):
                raise TypeError(f"the key {key!r} is not a normalised relative path")
            if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
                raise TypeError(f"the entry for {key!r} is not a SHA-256 hex string")
        initialised = data.get("initialised")
        if initialised is not None and not _is_day(initialised):
            raise TypeError("'initialised' is not a real YYYY-MM-DD date")
        return version, dict(files), initialised
    except (OSError, ValueError, KeyError, TypeError, RecursionError) as e:
        message = f"cannot be read ({e}); fix it, or delete it to start the lock afresh"
        raise fc.ConfigError("<file>", message, str(path)) from e


def _placement_problem(target: Path, dest: Path, out: str) -> str | None:
    """Why ``dest`` cannot safely be written, or ``None``: a symlink on its path that leaves the target, or a name the
    target already has with other capitalisation (the same file on a case-insensitive file system)."""
    top = Path(os.path.realpath(target))
    parent = Path(os.path.realpath(dest.parent))
    if parent != top and top not in parent.parents:
        return "a folder on its path is a symlink that leaves the target, so nothing is written through it"
    expected = top.joinpath(*Path(out).parent.parts)
    if str(parent) != str(expected) and str(parent).lower() == str(expected).lower():  # Path == ignores case on Windows
        shown = parent.relative_to(top).as_posix()
        return f"a folder on its path exists as {shown!r}, which differs only in capitalisation"
    if dest.parent.is_dir():
        names = os.listdir(dest.parent)
        clash = [name for name in names if name.lower() == dest.name.lower() and name != dest.name]
        if clash and dest.name not in names:
            return f"the target has {clash[0]!r}, which differs only in capitalisation"
    return None


def _blocked_parent(target: Path, dest: Path) -> Path | None:
    """The first existing parent of ``dest`` inside ``target`` that is not a directory, if any."""
    for parent in dest.parents:
        if parent == target or target not in parent.parents:
            break
        if parent.exists() and not parent.is_dir():
            return parent
    return None


def _decide(
    rule: Rule, rel: str, data: bytes, dest: Path, locked: dict[str, str] | None, overridden: set[str]
) -> tuple[Action, str | None]:
    """The action for one file of an ``on`` module, and a refusal message if it must not be touched."""
    if rule.kind == "project-owned":
        if dest.is_file():
            return Action(rel, "keep", rule.kind, rule.module, "project-owned and present"), None
        return Action(rel, "create", rule.kind, rule.module, "seeded"), None
    if not dest.is_file():
        return Action(rel, "create", rule.kind, rule.module), None
    current = normalised(dest.read_bytes())
    if current == data:
        return Action(rel, "unchanged", rule.kind, rule.module), None
    refuse = Action(rel, "refuse", rule.kind, rule.module)
    if rel in overridden:
        return Action(rel, "override", rule.kind, rule.module, "differs, and framework.toml overrides it"), None
    if locked is None:
        return refuse, f"{rel}: already exists with different content and this target has no framework.lock"
    if rel not in locked:
        return refuse, f"{rel}: exists with different content and is not recorded in framework.lock"
    if file_hash(current) == locked[rel]:
        return Action(rel, "update", rule.kind, rule.module, "the payload changed"), None
    return refuse, f"{rel}: differs from the lock (edited here); edit it in the template or add an override"


#: A board row file's name, as ``check_docs`` reads it: the board is in directory form once one exists.
_ROW_SEED_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}-[a-z0-9]+(?:-[a-z0-9]+)*\.md\Z")


def _has_board(target: Path, docs: fc.DocsConfig) -> bool:
    """The target already has a board, in either form: a page at the board path (hand-kept or rendered) or a row file
    under the board directory. Then the board seeds are not written: a seeded page beside the repository's rows, or
    seeded rows beside its page, would be two trackers."""
    if (target / docs.board).is_file():
        return True
    folder = target / docs.board_dir
    try:
        return folder.is_dir() and any(p.is_file() and _ROW_SEED_RE.fullmatch(p.name) for p in folder.iterdir())
    except OSError:
        return False


def plan_new(
    source: Path,
    target: Path,
    project: fc.ProjectConfig,
    today: str | None = None,
    module_states: dict[str, str] | None = None,
) -> Plan:
    """Decide everything ``init new`` would do, writing nothing. Reads the target; raises ConfigError/ManifestError.

    ``module_states`` sets module states for a target that has no ``framework.toml`` yet (``init adopt --off``); it is
    ignored when the target has one, which decides for itself.

    ``today`` (a real YYYY-MM-DD day, default the local date, which is not the UTC date the run record's name uses)
    matters only on a first run: the lock keeps the day it first used. A dated seed (``{{today}}`` in the last
    component of its path) is also skipped when a file of that shape already exists, so a lost or older lock cannot
    seed a second one.
    """
    if today is not None and not _is_day(today):
        raise fc.ConfigError("today", f"{today!r} is not a real YYYY-MM-DD day")
    refusals: list[str] = []
    rules = load_manifest(source / MANIFEST_NAME)
    template = fc.load_framework(source / "framework.toml")
    if (target / "framework.toml").is_file():
        chosen = fc.load_framework(target / "framework.toml")
    elif module_states:
        chosen = dataclasses.replace(template, modules={**template.modules, **module_states})
    else:
        chosen = template
    lock = read_lock(target)
    if lock is not None and lock[0] != template.template_version:
        refusals.append(
            f"framework.lock is for template {lock[0]} but this payload is {template.template_version}: "
            "updating a repository to a newer template is a later increment (--update)"
        )
    locked = lock[1] if lock else None
    on_modules = {name for name, state in chosen.modules.items() if state == "on"}
    initialised = (
        (lock[2] if lock else None)
        or _recovered_day(source, target, rules, on_modules)
        or today
        or _dt.date.today().isoformat()
    )
    values = _values(project, initialised, template.template_version)
    for module in LINKED_MODULES:  # the entry file and the docs map link to these modules' files
        if chosen.modules[module] != "on" and any(rule.module == module for rule in rules):
            refusals.append(
                f"modules.{module} is {chosen.modules[module]}, but the seeded documents link to its files: set it on "
                "(the documents init writes link to its files, so leave it on)"
            )
    overridden = {o.target for o in chosen.overrides}

    actions: list[Action] = []
    contents: dict[str, bytes] = {}
    rendered: dict[str, bytes] = {}
    lock_files: dict[str, str] = {}
    for rel in discover(source):
        rule = classify(rules, rel)
        if rule is None:
            refusals.append(f"{rel}: no rule in {MANIFEST_NAME} matches it")
            continue
        state = chosen.modules[rule.module]
        if state != "on":
            actions.append(Action(rel, "skip", rule.kind, rule.module, f"module {rule.module} is {state}"))
            continue
        raw = (source / rel).read_bytes()
        out = rel
        directory, _, name = rel.rpartition("/")
        in_path = [m.group(1) for m in _TOKEN_RE.finditer(rel)]
        residue = rel.replace("{{today}}", "")  # anything brace-shaped left is a malformed or disallowed token
        if (
            any(token not in _PATH_TOKENS for token in in_path)
            or "{{" in directory
            or "{{" in residue
            or "}}" in residue
            or rule.kind == "managed"
            and in_path
        ):
            refusals.append(
                f"{rel}: only {{{{today}}}} may appear in a payload path, in the file name only, "
                "and never in a managed file"
            )
            continue
        if rule.kind != "managed":
            bad = unknown_tokens(raw, values)
            if bad:
                known = ", ".join("{{" + key + "}}" for key in values)
                refusals.append(f"{rel}: unknown token {', '.join(sorted(set(bad)))} (known: {known})")
                continue
            out = _render_text(rel, values)
        # defence in depth: unreachable while the token rules above hold, but cheap insurance if they ever loosen
        if not Path(os.path.normpath(target / out)).is_relative_to(target):
            refusals.append(f"{rel}: renders to {out}, which is outside the target")
            continue
        data = normalised(raw) if rule.kind == "managed" else normalised(_render(raw, values))
        dest = target / out
        problem = _placement_problem(target, dest, out)
        if problem is not None:
            refusals.append(f"{out}: {problem}")
            continue
        blocked = _blocked_parent(target, dest)
        if blocked is not None:
            refusals.append(
                f"{out}: {blocked.relative_to(target).as_posix()} exists in the target and is not a directory"
            )
            continue
        if dest.exists() and not dest.is_file():
            refusals.append(f"{out}: exists in the target and is not a file")
            continue
        if os.path.lexists(dest) and not dest.exists():
            refusals.append(f"{out}: is a symlink to nowhere in the target, so it is not replaced")
            continue
        if (
            rule.kind == "project-owned"
            and out.startswith(template.docs.board_dir + "/")  # a board seed: where the payload keeps its rows
            and not dest.is_file()
            and _has_board(target, chosen.docs)  # a board the target has, wherever the target keeps it
        ):
            note = "the repository has a board already (a page or row files), so this board seed is not written"
            actions.append(Action(out, "keep", rule.kind, rule.module, note))
            continue
        if rule.kind == "project-owned" and in_path and not dest.is_file():
            pattern = name.replace("{{today}}", _DAY_GLOB)
            earlier = sorted(q.name for q in dest.parent.glob(pattern) if q.is_file()) if dest.parent.is_dir() else []
            if earlier:
                note = f"an earlier dated file exists ({earlier[0]}), so no second one is seeded"
                actions.append(Action(out, "keep", rule.kind, rule.module, note))
                continue
        rendered[out] = data
        if rule.kind != "project-owned":
            lock_files[out] = file_hash(data)
        try:
            action, refusal = _decide(rule, out, data, dest, locked, overridden)
        except OSError as e:
            refusals.append(f"{out}: cannot be read in the target: {e}")
            continue
        actions.append(action)
        if refusal:
            refusals.append(refusal)
        if action.op in ("create", "update"):
            contents[out] = data
    for rel in sorted(set(locked or {}) - set(lock_files)):
        if (target / rel).is_file():
            note = "was locked; no longer in the payload or its module is not on; left in place"
            actions.append(Action(rel, "orphan", "managed", "-", note))

    generated: dict[str, str] = {}
    for name in sorted(GENERATED):  # a directory where a generated file goes is a collision, found before any write
        if (target / name).exists() and not (target / name).is_file():
            refusals.append(f"{name}: exists in the target and is not a file")
    if (target / "logs").exists() and not (target / "logs").is_dir():
        refusals.append("logs: exists in the target and is not a directory, so the run record cannot be written")
    project_path = target / "project.json"
    if project_path.is_file():
        try:
            same = fc.load_project(project_path) == project
        except fc.ConfigError as e:
            refusals.append(str(e))
            same = True
        if same:
            actions.append(Action("project.json", "unchanged", "generated", "core"))
        else:
            refusals.append("project.json exists and differs from the answers; edit it or give matching answers")
    else:
        actions.append(Action("project.json", "create", "generated", "core"))
        generated["project.json"] = fc.dump_project(project)

    files = dict(sorted(lock_files.items()))
    lock_body = {"template_version": template.template_version, "initialised": initialised, "files": files}
    lock_text = json.dumps(lock_body, indent=2) + "\n"
    lock_path = target / "framework.lock"
    if lock_path.is_file() and normalised(lock_path.read_bytes()).decode("utf-8") == lock_text:
        actions.append(Action("framework.lock", "unchanged", "generated", "core"))
    else:
        actions.append(Action("framework.lock", "update" if lock_path.is_file() else "create", "generated", "core"))
        generated["framework.lock"] = lock_text
    return Plan(actions, refusals, contents, generated, initialised, rendered)


def format_plan(plan: Plan) -> list[str]:
    """The plan as aligned text lines, one per path."""
    width = max((len(a.path) for a in plan.actions), default=0)
    lines = []
    for a in plan.actions:
        note = f"  ({a.note})" if a.note else ""
        lines.append(f"  {a.op:<9} {a.path:<{width}}  [{a.kind}, {a.module}]{note}")
    return lines


# -------------------------------------------------------------------------
# prompts
def _slugify(name: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", name.lower())).strip("-")


_PLACEHOLDER = {
    "name": "x",
    "slug": "x",
    "owner": {"name": "x", "email": "x@x.xx"},
    "default_branch": "main",
    "signoff": True,
    "hygiene": [],
}


def _yes_no(reply: str) -> bool:
    """y/yes/true or n/no/false, in any case; anything else is rejected so a typo cannot switch a policy off."""
    lowered = reply.strip().lower()
    if lowered in ("y", "yes", "true"):
        return True
    if lowered in ("n", "no", "false"):
        return False
    raise ValueError(f"answer y or n, not {reply!r}")


def prompt_answers(ask: Callable[[str], str], say: Say) -> fc.ProjectConfig:
    """Ask for each value, re-asking until ``framework_config`` accepts it; EOF or Ctrl-C propagate to the caller."""
    answers: dict[str, Any] = copy.deepcopy(_PLACEHOLDER)

    def put(field: str, value: Any) -> None:
        if field.startswith("owner."):
            answers["owner"][field.split(".", 1)[1]] = value
        else:
            answers[field] = value

    def ask_field(field: str, prompt: str, default: str = "", convert: Callable[[str], Any] = str) -> None:
        while True:
            reply = ask(f"{prompt}{f' [{default}]' if default else ''}: ").strip() or default
            try:
                put(field, convert(reply))
                fc.parse_project(answers)
                return
            except ValueError as e:
                say(f"  {e}")
            except fc.ConfigError as e:
                if e.field != field and not e.field.startswith(f"{field}["):
                    return  # a different field is wrong (not asked yet); this one is accepted
                say(f"  {e}")

    def identifiers(reply: str) -> list[str]:
        return [part.strip() for part in reply.split(",") if part.strip()]

    ask_field("name", "Project name")
    ask_field("slug", "Slug (lower-case, hyphens)", _slugify(answers["name"]))
    ask_field("owner.name", "Owner name")
    ask_field("owner.email", "Owner email")
    ask_field("default_branch", "Default branch", "main")
    ask_field("signoff", "Require a sign-off on commits (y/n)", "y", _yes_no)
    ask_field("hygiene", "Hygiene identifiers (comma separated, may be empty)", "", identifiers)
    return fc.parse_project(answers)


# -------------------------------------------------------------------------
# running
def _default_runner(argv: list[str], cwd: Path) -> RunResult:
    """Run ``argv`` in ``cwd``, echoing its output as it arrives and returning it for the record."""
    try:
        proc = subprocess.Popen(
            argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace"
        )
    except OSError as e:
        return RunResult(127, f"could not start {argv[0]!r}: {e} (is it installed and on PATH?)")
    chunks = []
    assert proc.stdout is not None
    for line in proc.stdout:
        sys.stdout.write(line)
        chunks.append(line)
    return RunResult(proc.wait(), "".join(chunks))


def quiet_runner(argv: list[str], cwd: Path) -> RunResult:
    """Run ``argv`` in ``cwd`` and return its output without echoing it (for ``git status`` and the like)."""
    try:
        done = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, errors="replace", check=False)
    except OSError as e:
        return RunResult(127, f"could not start {argv[0]!r}: {e} (is it installed and on PATH?)")
    return RunResult(done.returncode, (done.stdout or "") + (done.stderr or ""))


def _publish_new(temp: Path, dest: Path) -> None:
    """Give ``temp`` the name ``dest`` only if nothing has it, in one step: a hard link fails if the name exists (a file
    made since the plan, or a symlink to nowhere), where a check followed by a rename could be too late. Where hard
    links are not available the check is made just before the rename.

    :raises FileExistsError: ``dest`` exists, or is a symlink.
    """
    message = f"{dest} appeared after the plan was made, or is a symlink; it was not replaced"
    try:
        os.link(temp, dest)
    except FileExistsError as e:
        raise FileExistsError(message) from e
    except (OSError, NotImplementedError):
        if os.path.lexists(dest):
            raise FileExistsError(message) from None
        os.replace(temp, dest)


def write_atomic(dest: Path, data: bytes, *, create_only: bool = False) -> None:
    """Write to a temporary name and rename, so a failure never leaves a truncated file.

    An existing file keeps its permissions. With ``create_only`` the write is refused (``FileExistsError``) if ``dest``
    appeared since it was planned (or is a symlink, even to nowhere), so a file made in between is never replaced.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        prefix=dest.name + ".", suffix=".init-tmp", dir=dest.parent
    )  # unique, exclusive
    temp = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
        if create_only:
            _publish_new(temp, dest)
        else:
            if dest.exists():
                os.chmod(temp, stat.S_IMODE(dest.stat().st_mode))
            os.replace(temp, dest)
    finally:
        if temp.exists():
            temp.unlink()


def _record(target: Path, lines: list[str]) -> Path:
    stamp = _dt.datetime.now(_dt.UTC).strftime("%Y%m%dT%H%M%S%fZ")
    path = target / "logs" / f"init-{stamp}.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return path


def _tail(output: str, count: int = 25) -> list[str]:
    return [f"    | {line}" for line in output.splitlines()[-count:]]


def _apply(plan: Plan, target: Path, lines: list[str]) -> None:
    """Write every create and update, the generated files, and the lock last."""
    writes = {**plan.contents, **{k: v.encode("utf-8") for k, v in plan.generated.items() if k != "framework.lock"}}
    for rel, data in writes.items():
        write_atomic(target / rel, data)
        lines.append(f"wrote {rel}")
        _LOGGER.debug(f"wrote {rel} ({len(data)} bytes)")
    if "framework.lock" in plan.generated:
        write_atomic(target / "framework.lock", plan.generated["framework.lock"].encode("utf-8"))
        lines.append("wrote framework.lock")


def _finish(args: argparse.Namespace, target: Path, runner: Runner, lines: list[str]) -> int:
    """``uv sync`` and the target's gate, recording what each said; returns the exit status."""
    if args.no_sync:
        lines.append("uv sync skipped (--no-sync)")
    elif (target / "pyproject.toml").is_file():
        result = runner(["uv", "sync"], target)
        lines.append(f"uv sync exited {result.code}")
        if result.code:
            lines += _tail(result.output)
            lines.append("the gate was not run: uv sync failed")
            return EXIT_FAILED
    else:
        lines.append("uv sync not run: no pyproject.toml in the target")
    if args.no_checks:
        lines.append("the gate was skipped (--no-checks)")
    elif (target / "tools" / "check.py").is_file():
        result = runner(["uv", "run", "python", "tools/check.py"], target)
        lines.append(f"tools/check.py exited {result.code}")
        if result.code:
            lines += _tail(result.output)
            return EXIT_FAILED
    else:
        lines.append("no tools/check.py in the target, so no gate was run")
    return EXIT_OK


def run_new(
    args: argparse.Namespace,
    source: Path,
    runner: Runner,
    say: Say,
    warn: Say,
    ask: Callable[[str], str],
    today: str | None = None,
) -> int:
    """Plan, refuse or apply ``init new``; ``say`` and ``warn`` are stdout and stderr writers, ``ask`` reads a reply."""
    target = Path(args.target).resolve()
    source = Path(source).resolve()
    if target == source:
        warn("refused: a repository cannot be initialised from itself; give a different --target")
        return EXIT_REFUSED
    if target.is_relative_to(source):
        warn("refused: --target is inside the payload; it would become part of the payload")
        return EXIT_REFUSED
    if target.exists() and not target.is_dir():
        warn(f"refused: --target {target} exists and is not a directory")
        return EXIT_REFUSED
    try:
        if args.answers:
            project = fc.load_answers(Path(args.answers))
        elif sys.stdin.isatty():
            project = prompt_answers(ask, say)
        else:
            warn("refused: no --answers file and no terminal to ask on")
            return EXIT_REFUSED
        plan = plan_new(source, target, project, today)
    except fc.ConfigError as e:
        warn(f"refused: {e}")
        return EXIT_REFUSED
    except ManifestError as e:
        warn(f"refused: the payload itself is broken (a template bug): {e}")
        return EXIT_REFUSED
    except (EOFError, KeyboardInterrupt):
        warn("refused: the questions were not answered (input ended or was interrupted); nothing was written")
        return EXIT_REFUSED
    if plan.refusals:
        warn("refused: nothing was written")
        for refusal in plan.refusals:
            warn(f"  {refusal}")
        return EXIT_REFUSED

    started = _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds")
    lines = [f"init new, {started}", f"source {source}", f"target {target}", f"project {project.slug} ({project.name})"]
    lines.append(f"initialised {plan.initialised} (the local date of the first run, kept in framework.lock)")
    lines += ["decisions:", *format_plan(plan)]
    if args.dry_run:
        say(f"init new into {target}: {len(plan.actions)} paths considered")
        for line in format_plan(plan):
            say(line)
        say("dry run: nothing written")
        return EXIT_OK

    status = EXIT_FAILED
    try:
        target.mkdir(parents=True, exist_ok=True)
        _apply(plan, target, lines)
        status = _finish(args, target, runner, lines)
    except OSError as e:
        lines.append(f"FAILED while writing: {e}")
        warn(f"the write failed: {e}; files written so far are listed in the record, and a re-run recovers")
    finally:
        lines.append(f"exit {status}")
        record = None
        if target.exists():
            try:
                record = _record(target, lines)
            except OSError as e:  # never let a record failure replace the real outcome
                warn(f"the run record could not be written: {e}")
    changed = sum(1 for a in plan.actions if a.op in ("create", "update"))
    _LOGGER.info(f"init new: exit {status}, {changed} files planned for {target}; record {record}")
    say(f"init new into {target}: exit {status}; record {record}")
    if status:
        warn("the repository may be incomplete, or uv sync or the gate failed (see the record)")
    return status


def main(
    argv: list[str] | None = None, source: Path = SOURCE, runner: Runner | None = None, today: str | None = None
) -> int:
    """The command line: ``init new``; returns the exit code."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    new = sub.add_parser("new", help="write a repository from the payload")
    new.add_argument("--answers", help="answers.json, in the project.json schema; prompts on a terminal if omitted")
    new.add_argument("--target", required=True, help="the directory to write into (created if missing)")
    new.add_argument("--dry-run", action="store_true", help="print the plan and write nothing")
    new.add_argument("--no-sync", action="store_true", help="do not run uv sync at the end")
    new.add_argument("--no-checks", action="store_true", help="do not run the target's gate at the end")
    adopt = sub.add_parser("adopt", help="bring a repository that predates the template under it (see init_adopt.py)")
    adopt.add_argument("--answers", help="answers.json, in the project.json schema; prompts on a terminal if omitted")
    adopt.add_argument("--target", required=True, help="the existing repository")
    adopt.add_argument(
        "--apply", action="store_true", help="write the adoption (without it: a report, nothing written)"
    )
    adopt.add_argument(
        "--take", action="append", metavar="PATH", help="overwrite this differing file with the template's"
    )
    adopt.add_argument("--take-all", action="store_true", help="overwrite every differing file with the template's")
    adopt.add_argument("--json", action="store_true", help="print the report as JSON (not with --apply)")
    adopt.add_argument("-v", "--verbose", action="store_true", help="list every file, not only the ones that differ")
    adopt.add_argument(
        "--diff", metavar="PATH", help="print how one differing file differs from the template's, and stop"
    )
    adopt.add_argument("--off", action="append", metavar="MODULE", help="leave this module off (repeatable)")
    args = parser.parse_args(argv)
    if args.command == "adopt":
        import init_adopt

        return init_adopt.run_adopt(
            args, source, runner or quiet_runner, print, lambda text: print(text, file=sys.stderr), input, today
        )
    return run_new(
        args, source, runner or _default_runner, print, lambda text: print(text, file=sys.stderr), input, today
    )


if __name__ == "__main__":
    _logging.basicConfig(level=_logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    sys.exit(main())
