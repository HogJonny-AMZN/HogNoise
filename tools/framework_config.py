"""
Framework: the schemas and loader for framework.toml, project.json and answers.json.
Package: tools/framework_config

``framework.toml`` says which modules are on, which harnesses are enabled, the handoff line limit, where the docs check
looks (the optional ``[docs]`` table; every key defaults to the framework's own layout), the files the hygiene check
may find an identifier in (``[[hygiene_allow]]``, each with a reason), the layer rules of ``src/`` (the optional
``[layers]`` table) and the overrides.
``project.json`` holds a project's values. ``answers.json`` is the initialiser's input and uses the ``project.json``
schema. Every file is validated on load and every refusal names the field (``ConfigError.field``), so a typo is a
message and never a silently ignored key. The dumpers validate too: this module never writes a file it would refuse.

The rules that are choices, not facts, and why:

- ``checks.handoff_max_lines`` is 20 to 1000 (default 150). The upper bound is the soft length guideline of Copilot's
  instruction-file documentation; the lower keeps the check meaningful. A value other than the default needs an override
  with a reason.
- ``slug`` is lower-case words joined by single hyphens and starts with a letter, so it is a valid package and
  repository name everywhere (a leading digit is refused although PEP 508 allows it).
- ``owner.email`` is ``local@domain.tld`` over ASCII letters, digits and ``._%+-``; no ``<>,;"'`` or spaces, because the
  value is written into a ``Signed-off-by`` trailer and into generated files. ``user@localhost`` is refused.
- ``default_branch`` is a valid git branch name over ``A-Za-z0-9._/-``, because it is written into a CI workflow and
  into hooks.
- All free text is a single line without control characters, and ``name`` and ``owner.name`` also refuse ``<`` and
  ``>``, so a value cannot forge or break a trailer.

The module has no dependency beyond the standard library: TOML is read with ``tomllib`` and written by a small
deterministic emitter, because the schema is fixed and a writer package would be the only new dependency.
"""

from __future__ import annotations

import json
import keyword
import logging as _logging
import re
import sys
import tomllib
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

# -------------------------------------------------------------------------
# module global scope
_MODULE_NAME = "tools.framework_config"
__version__ = "0.5.0"
__updated__ = "2026-10-11"
_LOGGER = _logging.getLogger(_MODULE_NAME)

MODULES = (
    "core",
    "journal",
    "ux",
    "python-uv",
    "tasking",
    "hygiene",
    "graph",
    "harness-adapters",
    "specimens",
    "lanes",
    "branch-ownership",
    "devblog",
)
MODULE_STATES = ("on", "off", "planned")
HARNESSES = ("claude", "gemini", "copilot", "codex", "cursor")
DEFAULT_HANDOFF_MAX_LINES = 150
HANDOFF_LIMIT_RANGE = (20, 1000)
#: How long a repository may stay behind the template's latest release before ``framework_sync.py --upstream`` fails.
DEFAULT_MAX_AGE_DAYS = 14
MAX_AGE_RANGE = (1, 365)
HANDOFF_OVERRIDE_TARGET = "handoff_max_lines"

_SEMVER_RE = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
_UPSTREAM_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
_SLUG_RE = re.compile(r"[a-z][a-z0-9]*(-[a-z0-9]+)*")
_EMAIL_LOCAL = r"[A-Za-z0-9_%+-]+(\.[A-Za-z0-9_%+-]+)*"  # dot-separated; no leading, trailing or doubled dot
_EMAIL_LABEL = r"[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?"  # no leading or trailing hyphen
_EMAIL_RE = re.compile(rf"{_EMAIL_LOCAL}@{_EMAIL_LABEL}(\.{_EMAIL_LABEL})+")
_DRIVE_RE = re.compile(r"[A-Za-z]:")
_BRANCH_CHARS_RE = re.compile(r"[A-Za-z0-9._/-]+")
LOGIN_PATTERN = r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*"  # a GitHub login: no leading, trailing or doubled hyphen
LOGIN_MAX = 39  # and no more characters than this; the docs check builds its own patterns from these two
_LOGIN_RE = re.compile(LOGIN_PATTERN)
PERSON_ROLES = ("owner", "contributor")
_NAME_FORBIDDEN = "<>"
_ROOT = "<root>"
_FILE = "<file>"
_NAME_MAX = 80


class ConfigError(Exception):
    """A configuration file broke its schema; ``field`` is the dotted path of the offending key."""

    def __init__(self, field: str, message: str, source: str | None = None) -> None:
        super().__init__(field, message, source)  # all three, so copy and pickle rebuild it
        self.field = field
        self.message = message
        self.source = source

    def __str__(self) -> str:
        where = f"{self.source}: " if self.source else ""
        return f"{where}field '{self.field}': {self.message}"

    def with_source(self, source: str) -> ConfigError:
        return ConfigError(self.field, self.message, source)


@dataclass(frozen=True)
class Override:
    """A file or setting a project deliberately differs on, with the reason."""

    target: str
    reason: str


@dataclass(frozen=True)
class HygieneAllow:
    """A tracked file or directory that may carry a hygiene identifier, and why."""

    path: str
    reason: str


@dataclass(frozen=True)
class Person:
    """One person on the roster: a GitHub login, a name, a role, and the addresses they commit with."""

    login: str
    name: str
    role: str
    emails: tuple[str, ...] = ()


@dataclass(frozen=True)
class DocsConfig:
    """Where the docs check looks and what it leaves alone; every field defaults to the framework's own layout."""

    # in addition to the directories no configuration can put back (.git, .venv, node_modules, __pycache__)
    exclude_parts: tuple[str, ...] = (".claude", ".worktrees", ".temp", "Spikes")
    governed_dirs: tuple[str, ...] = ("Docs",)
    status_exempt: tuple[str, ...] = ("Docs/decisions/README.md",)
    adr_index: str = "Docs/decisions/README.md"
    journal_index: str = "Docs/journal/README.md"
    journal_dir: str = "Docs/journal"
    handoff: str = "Docs/handoffs/CURRENT.md"
    handoff_people_dir: str = "Docs/handoffs/people"  # one file per login: that person's session truth
    board: str = "Docs/plan/BOARD.md"
    board_dir: str = "Docs/plan/board"  # the row files of a board in directory form; the board path is then rendered
    glossary: str = "Docs/glossary.md"
    board_sections: tuple[str, ...] = ("## Gates", "## Now", "## Next", "## Blocked", "## Icebox")
    # the documents that must end with a Terms introduced section, and those written before the rule (only ever shrinks)
    terms_dirs: tuple[str, ...] = ("Docs/design", "Docs/superpowers/specs", "Docs/superpowers/plans")
    terms_grandfathered: tuple[str, ...] = ()
    # governed documents no other document links to on purpose (the map every other one is reached from)
    orphan_allow: tuple[str, ...] = ("Docs/README.md",)
    # append-only dated records, where a retired term may be named without its replacement; each entry is a place
    # the vocabulary check does not look, so the default is the journal alone
    retired_exempt_dirs: tuple[str, ...] = ("Docs/journal",)
    # instruction files (CLAUDE.md, GEMINI.md, AGENTS.md) allowed below the root, with the reason in the project's ADR
    instructions_allow: tuple[str, ...] = ()


@dataclass(frozen=True)
class LayersConfig:
    """The layer rules of ``src/``: the packages from the lowest layer to the highest (a package may import itself
    and the packages before it), those that are pure (standard library and themselves only), and those deliberately
    outside the order. ``tools/boundaries.py`` enforces it."""

    order: tuple[str, ...]
    pure: tuple[str, ...] = ()
    unlayered: tuple[str, ...] = ()


@dataclass(frozen=True)
class FrameworkConfig:
    template_version: str
    modules: Mapping[str, str]
    harnesses: tuple[str, ...]
    handoff_max_lines: int
    overrides: tuple[Override, ...]
    docs: DocsConfig = DocsConfig()
    hygiene_allow: tuple[HygieneAllow, ...] = ()
    layers: LayersConfig | None = None  # None: no [layers] table, so nothing for the boundary test to hold
    upstream: str | None = None  # owner/repo of the template this repository was made from (``--upstream`` reads it)
    max_age_days: int = DEFAULT_MAX_AGE_DAYS
    people: tuple[Person, ...] = ()  # the [[people]] roster; empty: no roster, so nothing checks authorship


@dataclass(frozen=True)
class Owner:
    name: str
    email: str


@dataclass(frozen=True)
class ProjectConfig:
    name: str
    slug: str
    owner: Owner
    default_branch: str
    signoff: bool
    hygiene: tuple[str, ...]


# -------------------------------------------------------------------------
# validation helpers
def _join(prefix: str, key: str) -> str:
    return f"{prefix}.{key}" if prefix else key


def _has_control(value: str) -> bool:
    return any(unicodedata.category(c).startswith("C") for c in value)


def _is_clean(value: Any) -> bool:
    """A non-blank single line of text without control characters or lone surrogates."""
    if not isinstance(value, str) or not value.strip() or _has_control(value):
        return False
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _text(value: Any, field: str, what: str = "text") -> str:
    if not _is_clean(value):
        raise ConfigError(field, f"must be non-empty single-line {what} without control characters")
    return value.strip()


def _table(data: Any, field: str, allowed: tuple[str, ...], required: tuple[str, ...]) -> dict[str, Any]:
    """``data`` as a table: a dict with only ``allowed`` keys and every ``required`` key present."""
    if not isinstance(data, dict):
        raise ConfigError(field, "must be an object (a table in TOML)")
    prefix = "" if field == _ROOT else field
    for key in data:
        if key not in allowed:
            raise ConfigError(_join(prefix, str(key)), f"unknown key (allowed: {', '.join(allowed)})")
    for key in required:
        if key not in data:
            raise ConfigError(_join(prefix, key), "is required")
    return data


def _is_repository(value: Any) -> bool:
    """``owner/name``: two names of letters, digits, ``_``, ``.`` and ``-``, neither of them only dots."""
    return (
        isinstance(value, str)
        and _UPSTREAM_RE.fullmatch(value) is not None
        and not any(part.strip(".") == "" for part in value.split("/"))
    )


def _is_plain_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def is_relative_path(text: str) -> bool:
    """A normalised relative path with forward slashes: no leading slash, drive, backslash, empty, ``.`` or ``..``
    segment, and no control character. The one rule for an override's target and a lock's keys."""
    return not (
        text.startswith("/")
        or _DRIVE_RE.match(text)
        or "\\" in text
        or any(part in ("", ".", "..") for part in text.split("/"))
        or any(ord(char) < 0x20 or ord(char) == 0x7F for char in text)
    )


def _override_target(value: Any, field: str) -> str:
    target = _text(value, field, "text naming a file or a setting")
    if not is_relative_path(target):
        raise ConfigError(field, "must be a normalised relative path with forward slashes, or a setting name")
    return target


# -------------------------------------------------------------------------
# framework.toml
def _parse_overrides(value: Any) -> tuple[Override, ...]:
    if not isinstance(value, list):
        raise ConfigError("overrides", "must be a list of tables")
    seen: set[str] = set()
    result: list[Override] = []
    for index, item in enumerate(value):
        field = f"overrides[{index}]"
        if not isinstance(item, dict):
            raise ConfigError(field, "must be a table with 'target' and 'reason'")
        _table(item, field, ("target", "reason"), ())
        if "target" not in item:
            raise ConfigError(f"{field}.target", "is required")
        target = _override_target(item["target"], f"{field}.target")
        if target in seen:
            raise ConfigError(f"{field}.target", f"'{target}' is overridden twice")
        seen.add(target)
        if "reason" not in item:
            raise ConfigError(f"{field}.reason", "is required: an override without a reason is a drift")
        result.append(Override(target, _text(item["reason"], f"{field}.reason", "text giving the reason")))
    return tuple(result)


def _parse_hygiene_allow(value: Any) -> tuple[HygieneAllow, ...]:
    """The ``[[hygiene_allow]]`` tables: a path (a file, or a directory with everything below it) and the reason it may
    carry an identifier. A reason is required: an allowlist entry without one is a hole nobody can review."""
    if not isinstance(value, list):
        raise ConfigError("hygiene_allow", "must be a list of tables")
    seen: set[str] = set()
    result: list[HygieneAllow] = []
    for index, item in enumerate(value):
        field = f"hygiene_allow[{index}]"
        if not isinstance(item, dict):
            raise ConfigError(field, "must be a table with 'path' and 'reason'")
        _table(item, field, ("path", "reason"), ("path", "reason"))
        path = _relative_path(item["path"], f"{field}.path")
        if path in seen:
            raise ConfigError(f"{field}.path", f"'{path}' is allowed twice")
        seen.add(path)
        result.append(HygieneAllow(path, _text(item["reason"], f"{field}.reason", "text giving the reason")))
    return tuple(result)


DOCS_PATH_KEYS = (
    "adr_index",
    "journal_index",
    "journal_dir",
    "handoff",
    "handoff_people_dir",
    "board",
    "board_dir",
    "glossary",
)
DOCS_PATH_LIST_KEYS = (
    "governed_dirs",
    "status_exempt",
    "terms_dirs",
    "terms_grandfathered",
    "orphan_allow",
    "retired_exempt_dirs",
    "instructions_allow",
)
DOCS_KEYS = ("exclude_parts", *DOCS_PATH_KEYS, "board_sections", *DOCS_PATH_LIST_KEYS)
_HEADING_RE = re.compile(r"#{1,6} \S.*")
#: A check whose list is empty checks nothing, silently: refused, as a scan of zero files is a finding and not a pass.
DOCS_NONEMPTY = ("governed_dirs", "board_sections", "terms_dirs")


def _relative_path(value: Any, field: str) -> str:
    """A normalised repository-relative path with forward slashes: no drive, no ``..``, no empty part."""
    text = _text(value, field, "a repository-relative path")
    # A leading or trailing slash and a doubled one all produce an empty part, so one test covers them.
    if _DRIVE_RE.match(text) or "\\" in text or any(p in ("", ".", "..") for p in text.split("/")):
        raise ConfigError(field, "must be a normalised path relative to the repository root, with forward slashes")
    return text


def _unique_strings(value: Any, field: str, one: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ConfigError(field, "must be a list")
    items = [one(item, f"{field}[{index}]") for index, item in enumerate(value)]
    for item in items:
        if items.count(item) > 1:
            raise ConfigError(field, f"names '{item}' twice")
    return tuple(items)


def _path_part(value: Any, field: str) -> str:
    text = _text(value, field, "a directory name")
    if "/" in text or "\\" in text or text in (".", ".."):
        raise ConfigError(field, "must be one directory name, not a path")
    return text


def _heading(value: Any, field: str) -> str:
    text = _text(value, field, "a markdown heading")
    if not _HEADING_RE.fullmatch(text):
        raise ConfigError(field, "must be a markdown heading such as '## Gates'")
    return text


def parse_docs(data: Any) -> DocsConfig:
    """Validate the optional ``[docs]`` table; an absent key keeps the framework's default."""
    table = _table(data, "docs", DOCS_KEYS, ())
    values: dict[str, Any] = {}
    for key, value in table.items():
        field = f"docs.{key}"
        if key in DOCS_PATH_KEYS:
            values[key] = _relative_path(value, field)
        elif key == "exclude_parts":
            values[key] = _unique_strings(value, field, _path_part)
        elif key == "board_sections":
            values[key] = _unique_strings(value, field, _heading)
        else:
            values[key] = _unique_strings(value, field, _relative_path)
        if key in DOCS_NONEMPTY and not values[key]:
            raise ConfigError(field, "must name at least one entry: an empty list would switch its checks off")
    return DocsConfig(**values)


LAYERS_KEYS = ("order", "pure", "unlayered")
_PACKAGE_RE = re.compile(r"[a-z_][a-z0-9_]*")


def _package_name(value: Any, field: str) -> str:
    """A top-level package of ``src/``: lower-case ASCII, a valid identifier and not a keyword."""
    text = _text(value, field, "a package name")
    if not _PACKAGE_RE.fullmatch(text) or keyword.iskeyword(text):
        raise ConfigError(
            field, "must be a package name: lower-case letters, digits and underscores, not starting with a digit"
        )
    return text


def parse_layers(data: Any) -> LayersConfig:
    """Validate the optional ``[layers]`` table: ``order`` is required and non-empty; ``pure`` and ``unlayered`` default
    to empty; ``pure`` is a subset of ``order``; ``unlayered`` shares no name with ``order``."""
    table = _table(data, "layers", LAYERS_KEYS, ("order",))
    order = _unique_strings(table["order"], "layers.order", _package_name)
    if not order:
        raise ConfigError("layers.order", "must name at least one package: a layers table with no layers rules nothing")
    pure = _unique_strings(table.get("pure", []), "layers.pure", _package_name)
    unlayered = _unique_strings(table.get("unlayered", []), "layers.unlayered", _package_name)
    outside = [name for name in pure if name not in order]
    if outside:
        raise ConfigError("layers.pure", f"names '{outside[0]}', which is not in layers.order")
    shared = [name for name in unlayered if name in order]
    if shared:
        raise ConfigError("layers.unlayered", f"names '{shared[0]}', which is a layer in layers.order")
    return LayersConfig(order, pure, unlayered)


def _parse_people(value: Any) -> tuple[Person, ...]:
    """The ``[[people]]`` tables: who may be named as an author in the journal. A roster needs its owner."""
    if not isinstance(value, list) or not value:
        raise ConfigError("people", "must be a non-empty list of tables")
    seen: set[str] = set()
    seen_emails: set[str] = set()
    result: list[Person] = []
    for index, item in enumerate(value):
        field = f"people[{index}]"
        if not isinstance(item, dict):
            raise ConfigError(field, "must be a table with 'login', 'name' and 'role'")
        _table(item, field, ("login", "name", "role", "emails"), ("login", "name", "role"))
        login = item["login"]
        if not isinstance(login, str) or len(login) > LOGIN_MAX or not _LOGIN_RE.fullmatch(login):
            raise ConfigError(
                f"{field}.login", f"must be a GitHub login (1 to {LOGIN_MAX} letters, digits or single hyphens)"
            )
        if login.lower() in seen:
            raise ConfigError(f"{field}.login", f"'{login}' is on the roster twice (logins compare ignoring case)")
        seen.add(login.lower())
        name = _text(item["name"], f"{field}.name", "text giving the person's name")
        role = item["role"]
        if not isinstance(role, str) or role not in PERSON_ROLES:
            raise ConfigError(f"{field}.role", f"must be one of {', '.join(PERSON_ROLES)}")
        raw_emails = item.get("emails", [])
        if not isinstance(raw_emails, list):
            raise ConfigError(f"{field}.emails", "must be a list of addresses")
        for position, email in enumerate(raw_emails):
            if not isinstance(email, str) or not _EMAIL_RE.fullmatch(email):
                raise ConfigError(f"{field}.emails[{position}]", "must be an email address")
            if email.lower() in seen_emails:
                raise ConfigError(
                    f"{field}.emails[{position}]", f"'{email}' is on the roster twice (addresses compare ignoring case)"
                )
            seen_emails.add(email.lower())
        result.append(Person(login, name, role, tuple(raw_emails)))
    if not any(person.role == "owner" for person in result):
        raise ConfigError("people", "needs a person whose role is owner: a gate names the owner")
    return tuple(result)


def parse_framework(data: Any) -> FrameworkConfig:
    """Validate the decoded ``framework.toml``; raises ``ConfigError`` naming the first offending field."""
    required = ("framework", "modules", "harnesses", "checks")
    _table(data, _ROOT, (*required, "docs", "hygiene_allow", "overrides", "layers", "people"), required)

    framework = _table(
        data["framework"], "framework", ("template_version", "upstream", "max_age_days"), ("template_version",)
    )
    version = framework["template_version"]
    if not isinstance(version, str) or not _SEMVER_RE.fullmatch(version):
        raise ConfigError("framework.template_version", "must be a version like 1.2.3")
    upstream = framework.get("upstream")
    if "upstream" in framework and not _is_repository(upstream):
        raise ConfigError("framework.upstream", "must be a repository like owner/name")
    max_age = framework.get("max_age_days", DEFAULT_MAX_AGE_DAYS)
    age_low, age_high = MAX_AGE_RANGE
    if not _is_plain_int(max_age) or not age_low <= max_age <= age_high:
        raise ConfigError("framework.max_age_days", f"must be a whole number of days from {age_low} to {age_high}")

    raw_modules = _table(data["modules"], "modules", MODULES, MODULES)
    for name in MODULES:
        state = raw_modules[name]
        if not isinstance(state, str) or state not in MODULE_STATES:
            raise ConfigError(f"modules.{name}", f"must be one of {', '.join(MODULE_STATES)}")
    if raw_modules["core"] != "on":
        raise ConfigError("modules.core", "must be on: the core is not optional")
    modules = MappingProxyType({name: raw_modules[name] for name in MODULES})

    harness_table = _table(data["harnesses"], "harnesses", ("enabled",), ("enabled",))
    enabled = harness_table["enabled"]
    if not isinstance(enabled, list) or not all(isinstance(h, str) for h in enabled):
        raise ConfigError("harnesses.enabled", "must be a list of harness names")
    unknown = [h for h in enabled if h not in HARNESSES]
    if unknown:
        raise ConfigError("harnesses.enabled", f"unknown harness {unknown[0]!r} (known: {', '.join(HARNESSES)})")
    if len(set(enabled)) != len(enabled):
        raise ConfigError("harnesses.enabled", "names a harness twice")
    if enabled and modules["harness-adapters"] != "on":
        raise ConfigError("harnesses.enabled", "harnesses need the harness-adapters module to be on")

    checks = _table(data["checks"], "checks", ("handoff_max_lines",), ("handoff_max_lines",))
    limit = checks["handoff_max_lines"]
    low, high = HANDOFF_LIMIT_RANGE
    if not _is_plain_int(limit) or not low <= limit <= high:
        raise ConfigError("checks.handoff_max_lines", f"must be a whole number from {low} to {high}")

    overrides = _parse_overrides(data.get("overrides", []))
    if limit != DEFAULT_HANDOFF_MAX_LINES and HANDOFF_OVERRIDE_TARGET not in {o.target for o in overrides}:
        raise ConfigError(
            "checks.handoff_max_lines",
            f"differs from the default {DEFAULT_HANDOFF_MAX_LINES}, so an override with target "
            f"'{HANDOFF_OVERRIDE_TARGET}' and a reason is required",
        )
    docs = parse_docs(data["docs"]) if "docs" in data else DocsConfig()
    hygiene_allow = _parse_hygiene_allow(data.get("hygiene_allow", []))
    layers = parse_layers(data["layers"]) if "layers" in data else None
    people = _parse_people(data["people"]) if "people" in data else ()
    return FrameworkConfig(
        version, modules, tuple(enabled), limit, overrides, docs, hygiene_allow, layers, upstream, max_age, people
    )


def parse_framework_text(text: str) -> FrameworkConfig:
    try:
        decoded = tomllib.loads(text)
    except (tomllib.TOMLDecodeError, RecursionError) as e:
        raise ConfigError(_FILE, f"is not valid TOML: {type(e).__name__}: {e}") from e
    return parse_framework(decoded)


_TOML_ESCAPES = {'"': '\\"', "\\": "\\\\", "\b": "\\b", "\t": "\\t", "\n": "\\n", "\f": "\\f", "\r": "\\r"}


def _toml_string(value: str) -> str:
    """A TOML basic string: quotes, backslashes and control characters escaped, everything else literal."""
    out = []
    for char in value:
        if char in _TOML_ESCAPES:
            out.append(_TOML_ESCAPES[char])
        elif ord(char) < 0x20 or ord(char) == 0x7F:
            out.append(f"\\u{ord(char):04X}")
        else:
            out.append(char)
    return '"' + "".join(out) + '"'


def _framework_as_data(config: FrameworkConfig) -> dict[str, Any]:
    data: dict[str, Any] = {
        "framework": {"template_version": config.template_version},
        "modules": dict(config.modules),
        "harnesses": {"enabled": list(config.harnesses)},
        "checks": {"handoff_max_lines": config.handoff_max_lines},
    }
    if config.upstream is not None:
        data["framework"]["upstream"] = config.upstream
    if config.max_age_days != DEFAULT_MAX_AGE_DAYS:
        data["framework"]["max_age_days"] = config.max_age_days
    changed = _docs_changes(config.docs)
    if changed:
        data["docs"] = changed
    if config.layers is not None:
        data["layers"] = {"order": list(config.layers.order)}
        if config.layers.pure:
            data["layers"]["pure"] = list(config.layers.pure)
        if config.layers.unlayered:
            data["layers"]["unlayered"] = list(config.layers.unlayered)
    if config.hygiene_allow:
        data["hygiene_allow"] = [{"path": a.path, "reason": a.reason} for a in config.hygiene_allow]
    if config.overrides:
        data["overrides"] = [{"target": o.target, "reason": o.reason} for o in config.overrides]
    if config.people:
        data["people"] = [
            {"login": p.login, "name": p.name, "role": p.role, **({"emails": list(p.emails)} if p.emails else {})}
            for p in config.people
        ]
    return data


def _docs_changes(docs: DocsConfig) -> dict[str, Any]:
    """The ``[docs]`` keys that differ from the defaults, as TOML-ready values, in schema order."""
    default = DocsConfig()
    changed: dict[str, Any] = {}
    for key in DOCS_KEYS:
        value = getattr(docs, key)
        if value != getattr(default, key):
            changed[key] = list(value) if isinstance(value, tuple) else value
    return changed


def dump_framework(config: FrameworkConfig) -> str:
    """The deterministic TOML text of ``config``; refuses a config that ``parse_framework`` would refuse."""
    config = parse_framework(_framework_as_data(config))
    lines = ["[framework]", f"template_version = {_toml_string(config.template_version)}"]
    if config.upstream is not None:
        lines += [f"upstream = {_toml_string(config.upstream)}"]
    if config.max_age_days != DEFAULT_MAX_AGE_DAYS:
        lines += [f"max_age_days = {config.max_age_days}"]
    lines += ["", "[modules]"]
    lines += [f"{name} = {_toml_string(config.modules[name])}" for name in MODULES]
    enabled = ", ".join(_toml_string(h) for h in config.harnesses)
    lines += ["", "[harnesses]", f"enabled = [{enabled}]", "", "[checks]"]
    lines += [f"handoff_max_lines = {config.handoff_max_lines}"]
    changed = _docs_changes(config.docs)
    if changed:
        lines += ["", "[docs]"]
        for key, value in changed.items():
            shown = (
                "[" + ", ".join(_toml_string(item) for item in value) + "]"
                if isinstance(value, list)
                else _toml_string(value)
            )
            lines += [f"{key} = {shown}"]
    if config.layers is not None:
        lines += ["", "[layers]"]
        for key in LAYERS_KEYS:
            names = getattr(config.layers, key)
            if key == "order" or names:
                lines += [f"{key} = [" + ", ".join(_toml_string(n) for n in names) + "]"]
    for allowed in config.hygiene_allow:
        lines += [
            "",
            "[[hygiene_allow]]",
            f"path = {_toml_string(allowed.path)}",
            f"reason = {_toml_string(allowed.reason)}",
        ]
    for override in config.overrides:
        lines += ["", "[[overrides]]", f"target = {_toml_string(override.target)}"]
        lines += [f"reason = {_toml_string(override.reason)}"]
    for person in config.people:
        lines += ["", "[[people]]", f"login = {_toml_string(person.login)}", f"name = {_toml_string(person.name)}"]
        lines += [f"role = {_toml_string(person.role)}"]
        if person.emails:
            lines += ["emails = [" + ", ".join(_toml_string(e) for e in person.emails) + "]"]
    return "\n".join(lines) + "\n"


# -------------------------------------------------------------------------
# project.json and answers.json
def _branch(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise ConfigError("default_branch", "must be a branch name")
    parts = value.split("/")
    bad = (
        not _BRANCH_CHARS_RE.fullmatch(value)
        or value[0] in "-"
        or value == "HEAD"
        or ".." in value
        or value.endswith(".")
        or any(not part or part.startswith(".") or part.endswith(".lock") for part in parts)
    )
    if bad:
        raise ConfigError(
            "default_branch",
            f"{value!r} is not a safe git branch name (letters, digits and . _ - / only; no empty or dotted parts)",
        )
    return value


class _Object(list):
    """A decoded JSON object kept as its list of ``(key, value)`` pairs, so duplicates and the path survive."""


def _unpack(node: Any, path: str) -> Any:
    """Turn ``_Object`` pairs into dicts, refusing a duplicated key with its full dotted path."""
    if isinstance(node, _Object):
        result: dict[str, Any] = {}
        for key, value in node:
            field = _join(path, str(key))
            if key in result:
                raise ConfigError(field, "appears twice in the file")
            result[key] = _unpack(value, field)
        return result
    if isinstance(node, list):
        return [_unpack(item, f"{path}[{index}]") for index, item in enumerate(node)]
    return node


def parse_project(data: Any) -> ProjectConfig:
    """Validate a decoded ``project.json`` (or ``answers.json``); raises ``ConfigError`` naming the field."""
    keys = ("name", "slug", "owner", "default_branch", "signoff", "hygiene")
    _table(data, _ROOT, keys, keys)

    name = data["name"]
    if not _is_clean(name) or len(name.strip()) > _NAME_MAX or any(c in name for c in _NAME_FORBIDDEN):
        raise ConfigError("name", f"must be single-line text of at most {_NAME_MAX} characters, without < or >")
    slug = data["slug"]
    if not isinstance(slug, str) or not _SLUG_RE.fullmatch(slug):
        raise ConfigError("slug", "must be lower-case words joined by single hyphens, starting with a letter")

    owner = _table(data["owner"], "owner", ("name", "email"), ("name", "email"))
    owner_name = _text(owner["name"], "owner.name")
    if any(c in owner_name for c in _NAME_FORBIDDEN):
        raise ConfigError("owner.name", "must not contain < or >: it is written into a Signed-off-by trailer")
    email = owner["email"]
    if not isinstance(email, str) or not _EMAIL_RE.fullmatch(email):
        raise ConfigError("owner.email", "must look like name@domain.tld over letters, digits and . _ % + -")

    branch = _branch(data["default_branch"])
    if not isinstance(data["signoff"], bool):
        raise ConfigError("signoff", "must be true or false")

    hygiene = data["hygiene"]
    if not isinstance(hygiene, list):
        raise ConfigError("hygiene", "must be a list of identifiers (empty by default)")
    cleaned: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(hygiene):
        identifier = _text(item, f"hygiene[{index}]", "text")
        if identifier.lower() in seen:
            raise ConfigError(f"hygiene[{index}]", f"{identifier!r} is listed twice")
        seen.add(identifier.lower())
        cleaned.append(identifier)

    return ProjectConfig(name.strip(), slug, Owner(owner_name, email), branch, data["signoff"], tuple(cleaned))


def parse_project_text(text: str) -> ProjectConfig:
    try:
        decoded = _unpack(json.loads(text, object_pairs_hook=_Object), "")
    except (json.JSONDecodeError, RecursionError) as e:
        raise ConfigError(_FILE, f"is not valid JSON: {type(e).__name__}: {e}") from e
    return parse_project(decoded)


def dump_project(config: ProjectConfig) -> str:
    """The JSON text of ``config`` in a fixed key order; refuses a config that ``parse_project`` would refuse."""
    data = {
        "name": config.name,
        "slug": config.slug,
        "owner": {"name": config.owner.name, "email": config.owner.email},
        "default_branch": config.default_branch,
        "signoff": config.signoff,
        "hygiene": list(config.hygiene),
    }
    parse_project(data)
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


# -------------------------------------------------------------------------
# files
def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, ValueError) as e:  # ValueError covers a bad encoding and a NUL byte in the path
        raise ConfigError(_FILE, f"cannot be read: {e}", str(path)) from e


def _load(path: Path, parse_text: Any) -> Any:
    path = Path(path)
    try:
        return parse_text(_read(path))
    except ConfigError as e:
        if e.source:
            raise
        raise e.with_source(str(path)) from e.__cause__


def load_framework(path: Path) -> FrameworkConfig:
    config = _load(path, parse_framework_text)
    _LOGGER.debug(f"read {path}: template {config.template_version}, harnesses {list(config.harnesses)}")
    return config


def overridden(root: Path, *paths: str) -> list[str]:
    """Which of ``paths`` the repository at ``root`` lists as an override, in the order given.

    A test that pins the framework's own text of a managed document asks this, so that a repository which kept its own
    version of that document (and said why) is not held to the framework's. A ``framework.toml`` that is missing or
    unreadable answers ``[]``: nothing is excused when the answer is not known."""
    try:
        targets = {o.target for o in load_framework(Path(root) / "framework.toml").overrides}
    except (ConfigError, OSError):
        return []
    return [p for p in paths if p in targets]


def load_project(path: Path) -> ProjectConfig:
    config = _load(path, parse_project_text)
    _LOGGER.debug(f"read {path}: project {config.slug}")
    return config


def load_answers(path: Path) -> ProjectConfig:
    """The initialiser's answers: JSON in the ``project.json`` schema; a refusal names this file and the field."""
    return load_project(path)


def main(argv: list[str] | None = None) -> int:
    """Validate each named file (``*.toml`` as framework.toml, anything else as project.json); 0 if all are valid."""
    status = 0
    for argument in sys.argv[1:] if argv is None else argv:
        target = Path(argument)
        try:
            (load_framework if target.suffix == ".toml" else load_project)(target)
        except ConfigError as e:
            print(e, file=sys.stderr)
            status = 1
        else:
            print(f"{target}: ok")
    return status


if __name__ == "__main__":
    sys.exit(main())
