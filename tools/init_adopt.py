"""
Framework: ``init adopt``: bring a repository that predates the template under it, without losing anything it owns.
Package: tools/init_adopt

    uv run payload/tools/init.py adopt --target ../old-project --answers answers.json              # the report
    uv run payload/tools/init.py adopt --target ../old-project --answers answers.json --apply      # do it

``adopt`` plans the same files ``init new`` would write and sorts the target's version of each into a state:

``identical``      the target already has what the template would write (rendered with the project's values)
``differs``        a managed or parametrised file the target has with other content (with how many lines differ)
``missing``        a managed or parametrised file the target lacks; it would be added
``seed-present``   a project-owned file the target has: never touched
``seed-absent``    a project-owned file the target lacks; it would be seeded
``skipped``        a file of a module that is not ``on``; nothing is written
``blocked``        a file where a directory belongs, a symlinked folder that leaves the target, a name that differs
                   only in capitalisation, an unknown token, no rule: ``--apply`` refuses

The target's own files that the payload has no rule for are not listed: they are the project's. The text report puts
the counts first and the ``differs`` files next, largest first; the rest is counted per folder unless ``-v`` lists
every file. ``--json`` gives every entry; ``--diff PATH`` shows how one file differs.

Without ``--apply`` nothing is written. With it, ``adopt`` adds the missing and seed-absent files, writes
``project.json``, the ``framework.toml`` the payload seeds (the target must not have one: merging two is a person's
work) and ``framework.lock``, and leaves every ``differs`` file exactly as it is, recording an **override** for each
in ``framework.toml`` with the reason ``adopted: differs from template <version>; reconcile``. ``--take PATH``
(repeatable) or ``--take-all`` overwrites a differing file with the template's instead, and records no override. The
lock holds the **template's** hash for every managed and parametrised file, overridden ones included, so
``framework_sync.py --check`` passes on the day of adoption, each override is a visible to-do, and ``init new`` over
the result changes nothing.

``--off MODULE`` (repeatable) leaves a module off in the ``framework.toml`` it writes, so its files are neither added
nor reported as debt. Turning ``specimens`` off also drops the seeded ``[layers]`` table (it names the mock ``src/``):
if the target has a ``src/`` the table is written from the packages found there, in alphabetical order as a
placeholder, and the report says to set the real order.

``--apply`` refuses a target that is not the root of a clean git working tree, so that the adoption is one diff to
review; a target that already has a ``framework.toml`` or a ``framework.lock`` (adopted, made, or half adopted);
anything blocked; and a path the target's ``.gitignore`` would hide from that diff. It commits nothing, and it runs
neither ``uv sync`` nor the target's gate (the project's environment is the project's). It ends by running the sync
check on the result.

If a write fails part-way the lock has not been written; ``git status`` shows what was, ``git stash -u`` (or ``git
clean`` and ``git checkout .``) puts the tree back, and a re-run starts clean.

Exit codes: 0 reported or done; 1 refused (nothing written, or blocked files in a dry run); 2 the write failed, or the
result does not pass the sync check.
"""

from __future__ import annotations

import argparse
import dataclasses
import difflib
import json
import keyword
import logging as _logging
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import check_docs as cd
import framework_config as fc
import init as ini

# -------------------------------------------------------------------------
# module global scope
_MODULE_NAME = "tools.init_adopt"
__version__ = "0.2.0"
__updated__ = "2026-10-16"
_LOGGER = _logging.getLogger(_MODULE_NAME)
#: The ADR the payload seeds, and the index whose seed links it. A repository that already has an ADR number 1 is not
#: seeded a second one (two files with one id fail the ``adr-duplicate`` docs check); a seeded index gets no row for it.
ADR_SEED = "Docs/decisions/ADR-001-adopt-the-framework.md"
ADR_SEED_INDEX = "Docs/decisions/README.md"

STATES = ("identical", "differs", "missing", "seed-present", "seed-absent", "skipped", "blocked")
#: A file bigger than this is not diffed line by line; the report says it is large.
DIFF_LIMIT = 2 * 1024 * 1024
_PACKAGE_RE = re.compile(r"[a-z_][a-z0-9_]*")


class AdoptRefused(Exception):
    """The adoption cannot proceed; the message says why and what to do. Nothing has been written."""


@dataclass(frozen=True)
class Entry:
    """One payload file as the target has it: its state, class and module, and for ``differs`` the lines that differ
    (``added``: lines the template has and the target lacks; ``removed``: the reverse)."""

    path: str
    state: str
    kind: str
    module: str
    detail: str = ""
    added: int | None = None
    removed: int | None = None


@dataclass
class AdoptPlan:
    entries: list[Entry]
    plan: ini.Plan
    version: str  # the template version of the source
    modules_off: tuple[str, ...] = ()  # modules the adoption leaves off (``--off``)
    notes: list[str] = field(default_factory=list)

    @property
    def blocked(self) -> list[Entry]:
        return [e for e in self.entries if e.state == "blocked"]

    def counts(self) -> dict[str, int]:
        return {state: sum(1 for e in self.entries if e.state == state) for state in STATES}

    def differing(self) -> list[str]:
        return sorted(e.path for e in self.entries if e.state == "differs")


def _diff_counts(current: bytes, template: bytes) -> tuple[int | None, int | None, str]:
    """``(added, removed, text)``: lines the template has that the file lacks, the reverse, and a short phrase."""
    if len(current) > DIFF_LIMIT or len(template) > DIFF_LIMIT:
        return None, None, "large file"
    try:
        old, new = current.decode("utf-8").splitlines(), template.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        return None, None, "binary"
    added = removed = 0
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old, new).get_opcodes():
        if tag in ("replace", "delete"):
            removed += i2 - i1
        if tag in ("replace", "insert"):
            added += j2 - j1
    return added, removed, f"+{added} -{removed}"


def _own_adr_number_1(target: Path, decisions: str) -> str | None:
    """The target's own ADR number 1 under ``decisions`` (any slug, any case, anywhere below), as a repository-relative
    path, or ``None``."""
    folder = target / decisions
    if not folder.is_dir():
        return None
    for path in sorted(folder.rglob("*.md")):
        ident = cd.adr_id(path.name)
        if path.is_file() and ident is not None and ident.kind == "number" and ident.number == 1:
            return path.relative_to(target).as_posix()
    return None


def _withhold_adr_seed(plan: ini.Plan, own: str) -> list[str]:
    """Withhold the seed ADR because the repository has its own ADR number 1 (``own``): its ``create`` becomes a
    ``keep`` with the note (or, when the seed's name clashes with ``own`` in capitalisation alone and ``plan_new``
    refused the placement, that one refusal is dropped and a ``keep`` is added); its bytes are not written; a seeded
    index loses its row; every other seeded file that links it links the decisions index instead, so no seeded link
    dangles. Returns the notes, empty when the seed was not going to be written anyway."""
    seed_name = ADR_SEED.rsplit("/", 1)[1]
    note = (
        f"the repository has its own ADR number 1 ({own}); {ADR_SEED} is not seeded: record the adoption in a dated ADR"
    )
    seed = next((a for a in plan.actions if a.path == ADR_SEED and a.op == "create"), None)
    clash = next(
        (r for r in plan.refusals if r.startswith(f"{ADR_SEED}: ") and "differs only in capitalisation" in r), None
    )
    if seed is not None:
        seed.op, seed.note = "keep", note
    elif clash is not None:
        plan.refusals.remove(clash)
        like = next((a for a in plan.actions if a.path == ADR_SEED_INDEX), None)
        kind, module = (like.kind, like.module) if like else ("project-owned", "core")
        plan.actions.append(ini.Action(ADR_SEED, "keep", kind, module, note))
    else:
        return []
    plan.contents.pop(ADR_SEED, None)
    notes = [note]
    if ADR_SEED_INDEX in plan.contents:
        text = plan.contents[ADR_SEED_INDEX].decode("utf-8")
        kept = [line for line in text.splitlines(keepends=True) if seed_name not in line]
        plan.contents[ADR_SEED_INDEX] = "".join(kept).encode("utf-8")
    # Only a project-owned seed is relinked: a managed or parametrised file must arrive as the template ships it,
    # because the lock holds the template's hash of it (this module names the seed in ADR_SEED).
    kinds = {action.path: action.kind for action in plan.actions}
    for path in sorted(plan.contents):
        if path in (ADR_SEED, ADR_SEED_INDEX) or seed_name.encode("utf-8") not in plan.contents[path]:
            continue
        if kinds.get(path) != "project-owned":
            continue
        plan.contents[path] = plan.contents[path].replace(seed_name.encode("utf-8"), b"README.md")
        notes.append(f"{path} links the decisions index where the seed linked {seed_name}")
    for line in notes:
        _LOGGER.info(line)
    return notes


def plan_adopt(
    source: Path,
    target: Path,
    project: fc.ProjectConfig,
    today: str | None = None,
    modules_off: tuple[str, ...] = (),
) -> AdoptPlan:
    """Sort every payload file of the target into a state; writes nothing.

    :raises AdoptRefused: the target already has a ``framework.toml`` or a ``framework.lock``.
    :raises fc.ConfigError: the project values or the target's configuration are invalid.
    :raises ini.ManifestError: the payload itself is broken.
    """
    for name in ("framework.toml", "framework.lock"):
        if (target / name).exists():
            raise AdoptRefused(
                f"{target} already has a {name}, so it is adopted, made, or half adopted. Use init new to bring a made "
                "repository up to date; after a failed adoption restore the tree (git stash -u, or git clean -fd and "
                "git checkout .) and run adopt again"
            )
    plan = ini.plan_new(source, target, project, today, {name: "off" for name in modules_off})
    notes: list[str] = []
    own = _own_adr_number_1(target, ADR_SEED.rsplit("/", 1)[0])
    if own is not None:
        notes += _withhold_adr_seed(plan, own)
    version = fc.load_framework(source / "framework.toml").template_version
    differing = {a.path for a in plan.actions if a.op == "refuse"}  # only a differing file is refused with an action
    entries: list[Entry] = []
    for action in plan.actions:
        if action.kind == "generated":
            continue
        managed = action.kind in ("managed", "parametrised")
        base = (action.path, action.kind, action.module)
        if action.path in differing:
            added, removed, text = _diff_counts((target / action.path).read_bytes(), plan.template[action.path])
            entries.append(Entry(action.path, "differs", action.kind, action.module, text, added, removed))
        elif managed and action.op == "unchanged" and (target / action.path).is_symlink():
            # its content matches, but the sync check calls a symlink an edit: it needs an override or to be taken
            entries.append(Entry(action.path, "differs", action.kind, action.module, "a symlink", 0, 0))
        elif action.op == "unchanged":
            entries.append(Entry(base[0], "identical", *base[1:]))
        elif action.op == "create":
            entries.append(Entry(base[0], "missing" if managed else "seed-absent", *base[1:]))
        elif action.op == "keep":
            entries.append(Entry(base[0], "seed-present", *base[1:], action.note))
        elif action.op == "skip":
            entries.append(Entry(base[0], "skipped", *base[1:], action.note))
        else:  # update, override, orphan: they need a lock or a framework.toml, which were refused above
            raise RuntimeError(f"adopt cannot classify the plan's action {action.op!r} for {action.path}")
    for message in plan.refusals:
        path, _, rest = message.partition(": ")
        if path in differing:
            continue  # the refusal that says "this file differs"
        owner = path if rest and " " not in path else "-"
        entries.append(Entry(owner, "blocked", "-", "-", rest if owner != "-" else message))
        _LOGGER.debug(f"blocked: {message}")
    entries.sort(key=lambda e: (e.path, e.state))
    _LOGGER.info(f"planned the adoption of {target}: {len(entries)} entries, {len(differing)} differ")
    return AdoptPlan(entries, plan, version, modules_off, notes)


def _size(entry: Entry) -> int:
    return (entry.added or 0) + (entry.removed or 0)


def _folder(path: str) -> str:
    return path.split("/", 1)[0] + "/" if "/" in path else "(root)"


def format_report(adopt: AdoptPlan, verbose: bool = False) -> list[str]:
    """The plan as text: the counts, what is blocked, the differing files largest first, and the rest per folder (or
    every file with ``verbose``)."""
    counts = adopt.counts()
    lines = [
        f"{counts['identical']} identical, {counts['differs']} differ, {counts['missing']} missing, "
        f"{counts['seed-present']} seed-present, {counts['seed-absent']} seed-absent, {counts['skipped']} skipped, "
        f"{counts['blocked']} blocked",
        f"--apply would record {counts['differs']} override(s) for the files that differ and leave them as they are",
    ]
    width = max(len(s) for s in STATES)
    for entry in adopt.blocked:
        lines.append(f"{'blocked':<{width}}  {entry.path}: {entry.detail}")
    differing = sorted((e for e in adopt.entries if e.state == "differs"), key=lambda e: (-_size(e), e.path))
    if differing:
        lines.append("differing files, largest first (+ lines the template has, - lines this repository has):")
        lines += [f"{'differs':<{width}}  {e.path}  ({e.detail})" for e in differing]
    for state in ("missing", "seed-absent", "identical", "seed-present", "skipped"):
        group = [e for e in adopt.entries if e.state == state]
        if not group:
            continue
        if verbose:
            lines += [f"{state:<{width}}  {e.path}" for e in group]
        else:
            folders: dict[str, int] = {}
            for entry in group:
                folders[_folder(entry.path)] = folders.get(_folder(entry.path), 0) + 1
            lines.append(
                f"{state:<{width}}  {len(group)}: " + ", ".join(f"{f} {n}" for f, n in sorted(folders.items()))
            )
    lines += [f"note: {note}" for note in adopt.notes]
    return lines


def report_data(adopt: AdoptPlan) -> dict:
    """The plan as a JSON-ready document."""
    return {
        "template_version": adopt.version,
        "modules_off": list(adopt.modules_off),
        "entries": [dataclasses.asdict(e) for e in adopt.entries],
        "counts": adopt.counts(),
        "notes": list(adopt.notes),
    }


def diff_text(adopt: AdoptPlan, target: Path, path: str) -> str:
    """How the target's ``path`` differs from the template's, as a unified diff (the template's side is ``+``).

    :raises AdoptRefused: ``path`` is not a differing file.
    """
    if path not in adopt.differing():
        raise AdoptRefused(
            f"--diff names {path}, which does not differ (differing: {', '.join(adopt.differing()) or 'none'})"
        )
    old = (target / path).read_bytes().decode("utf-8", errors="replace").splitlines(keepends=True)
    new = adopt.plan.template[path].decode("utf-8", errors="replace").splitlines(keepends=True)
    return "".join(difflib.unified_diff(old, new, f"{path} (this repository)", f"{path} (the template)"))


def _src_packages(target: Path) -> list[str]:
    """The top-level packages and modules of the target's ``src/`` that can be named in a ``[layers]`` table."""
    src = target / "src"
    if not src.is_dir():
        return []
    names = set()
    for entry in src.iterdir():
        name = entry.stem if entry.is_file() else entry.name
        if entry.name.startswith(".") or entry.name == "__pycache__" or entry.name.endswith(".egg-info"):
            continue
        if (entry.is_dir() and any(entry.rglob("*.py"))) or (
            entry.is_file() and entry.suffix == ".py" and name != "__init__"
        ):
            names.add(name)
    return sorted(n for n in names if _PACKAGE_RE.fullmatch(n) and not keyword.iskeyword(n))


def apply_adopt(adopt: AdoptPlan, target: Path, take: set[str]) -> list[str]:
    """Write the adoption and return the lines that say what was done.

    Order: the added and seeded files, ``project.json``, ``framework.toml``, and ``framework.lock`` last, so a failure
    part-way leaves no lock claiming files that are not there. A file that appears after the plan was made is not
    replaced.

    :raises OSError: a write failed.
    :raises AdoptRefused: the payload seeds no ``framework.toml``.
    :raises fc.ConfigError: the framework.toml to write is invalid.
    """
    plan = adopt.plan
    writes = dict(plan.contents)
    for path in take:
        writes[path] = plan.template[path]
    left = [p for p in adopt.differing() if p not in take]
    if "framework.toml" not in writes:
        raise AdoptRefused("the payload seeds no framework.toml, so the overrides cannot be recorded")
    seeded = fc.parse_framework_text(writes["framework.toml"].decode("utf-8"))
    seeded = dataclasses.replace(seeded, modules={**seeded.modules, **{name: "off" for name in adopt.modules_off}})
    notes = []
    if "specimens" in adopt.modules_off and seeded.layers is not None:
        packages = _src_packages(target)
        layers = fc.LayersConfig(order=tuple(packages)) if packages else None
        seeded = dataclasses.replace(seeded, layers=layers)
        notes.append(
            f"[layers] was written from the packages of src/ ({', '.join(packages)}) in alphabetical order, "
            "a placeholder: set the real order (Docs/standards/python.md, Layers)"
            if packages
            else "specimens is off and src/ has no packages, so no [layers] table was written"
        )
    reason = f"adopted: differs from template {adopt.version}; reconcile"
    seeded = dataclasses.replace(seeded, overrides=tuple(fc.Override(path, reason) for path in left))
    writes["framework.toml"] = fc.dump_framework(seeded).encode("utf-8")
    generated = {name: text.encode("utf-8") for name, text in plan.generated.items() if name != "framework.lock"}
    ordered = [p for p in sorted(writes) if p != "framework.toml"] + sorted(generated) + ["framework.toml"]
    lines = []
    for path in ordered:
        data = generated[path] if path in generated else writes[path]
        created = path not in take
        ini.write_atomic(target / path, data, create_only=created)
        lines.append(f"wrote {path}")
        verb = "took the template's" if path in take else "wrote"
        _LOGGER.info(f"{verb} {path} ({len(data)} bytes)")
    if "framework.lock" in plan.generated:
        ini.write_atomic(target / "framework.lock", plan.generated["framework.lock"].encode("utf-8"), create_only=True)
        lines.append("wrote framework.lock")
    for path in sorted(take):
        lines.append(f"took the template's {path}")
    for path in left:
        _LOGGER.info(f"override recorded: {path}: {reason}")
    lines.append(
        f"{len(left)} override(s) recorded in framework.toml: reconcile each "
        "(keep it, take the template's, or improve the template)"
    )
    lines += [f"note: {note}" for note in notes]
    return lines


def _git_problem(runner: ini.Runner, target: Path) -> str | None:
    """``None`` if ``target`` is the root of a git working tree with nothing uncommitted, else the reason it is not."""
    top = runner(["git", "rev-parse", "--show-toplevel"], target)
    if top.code != 0:
        return f"{target} is not a git working tree (git said: {top.output.strip()[:200]})"
    if Path(top.output.strip()).resolve() != target.resolve():
        return f"{target} is inside a larger git repository ({top.output.strip()}): adopt the repository's root"
    status = runner(
        [
            "git",
            "--no-optional-locks",
            "-c",
            "core.fsmonitor=",
            "status",
            "--porcelain",
            "--untracked-files=all",
            "--ignore-submodules=none",
        ],
        target,
    )
    if status.code != 0:
        return f"git status failed in {target}: {status.output.strip()[:200]}"
    if status.output.strip():
        return f"{target} has uncommitted changes; commit or stash them so that the adoption is one diff to review"
    return None


def _ignored(runner: ini.Runner, target: Path, paths: list[str]) -> tuple[list[str], str | None]:
    """``(paths, problem)``: the paths among ``paths`` that the target's ``.gitignore`` would hide from a commit (a file
    git already tracks is not hidden), and why git could not say, if it could not. Only exit code 1 means "none"."""
    if not paths:
        return [], None
    result = runner(["git", "check-ignore", "--", *paths], target)
    if result.code == 1:
        return [], None
    if result.code != 0:
        return [], f"git check-ignore failed ({result.code}): {result.output.strip()[:200]}"
    return [line.strip() for line in result.output.splitlines() if line.strip() in paths], None


def _written_paths(adopt: AdoptPlan, take: set[str]) -> list[str]:
    plan = adopt.plan
    return sorted({*plan.contents, *take, *plan.generated, "framework.toml"})


def run_adopt(
    args: argparse.Namespace,
    source: Path,
    runner: ini.Runner,
    say: ini.Say,
    warn: ini.Say,
    ask: Callable[[str], str],
    today: str | None = None,
) -> int:
    """Report or apply ``init adopt``; returns 0, 1 (refused) or 2 (the write failed or the result fails the check)."""
    target = Path(args.target).resolve()
    source = Path(source).resolve()
    if target == source or target.is_relative_to(source) or source.is_relative_to(target):
        warn("refused: --target and the payload must be different folders, neither inside the other")
        return ini.EXIT_REFUSED
    if not target.is_dir():
        warn(
            f"refused: --target {target} is not a folder; adopt is for an existing repository "
            "(use init new for a new one)"
        )
        return ini.EXIT_REFUSED
    if args.json and args.apply:
        warn("refused: --json is for the report; run --apply without it")
        return ini.EXIT_REFUSED
    try:
        template = fc.load_framework(source / "framework.toml")
        unknown = [name for name in (args.off or ()) if template.modules.get(name) != "on" or name == "core"]
        if unknown:
            offable = ", ".join(m for m, state in template.modules.items() if state == "on" and m != "core")
            warn(f"refused: --off names {', '.join(unknown)}, which is not a module that is on (can be off: {offable})")
            return ini.EXIT_REFUSED
        if args.answers:
            project = fc.load_answers(Path(args.answers))
        elif sys.stdin.isatty():
            project = ini.prompt_answers(ask, say)
        else:
            warn("refused: no --answers file and no terminal to ask on")
            return ini.EXIT_REFUSED
        adopt = plan_adopt(source, target, project, today, tuple(dict.fromkeys(args.off or ())))
    except AdoptRefused as e:
        warn(f"refused: {e}")
        return ini.EXIT_REFUSED
    except fc.ConfigError as e:
        warn(f"refused: {e}")
        return ini.EXIT_REFUSED
    except ini.ManifestError as e:
        warn(f"refused: the payload itself is broken (a template bug): {e}")
        return ini.EXIT_REFUSED
    except (EOFError, KeyboardInterrupt):
        warn("refused: the questions were not answered; nothing was written")
        return ini.EXIT_REFUSED

    if args.diff:
        try:
            say(diff_text(adopt, target, args.diff))
        except AdoptRefused as e:
            warn(f"refused: {e}")
            return ini.EXIT_REFUSED
        return ini.EXIT_OK
    take = set(args.take or ())
    differing = set(adopt.differing())
    if args.take_all:
        take = differing
    wrong = sorted(take - differing)
    if wrong:
        warn(
            f"refused: --take names {', '.join(wrong)}, which does not differ from the template "
            f"(differing: {', '.join(sorted(differing)) or 'none'})"
        )
        return ini.EXIT_REFUSED

    hidden, ignore_problem = _ignored(runner, target, _written_paths(adopt, take))
    if hidden:
        adopt.notes.append(f"the target's .gitignore would hide these from a commit: {', '.join(hidden)}")
    if args.json:
        say(json.dumps(report_data(adopt), indent=2))
    else:
        off = f", off: {', '.join(adopt.modules_off)}" if adopt.modules_off else ""
        say(f"init adopt {target} (template {adopt.version}{off})")
        for line in format_report(adopt, args.verbose):
            say(line)
    if not args.apply:
        if not args.json:
            say("dry run: nothing written")
        return ini.EXIT_REFUSED if adopt.blocked else ini.EXIT_OK

    if adopt.blocked:
        warn("refused: nothing was written; resolve the blocked files first")
        return ini.EXIT_REFUSED
    problem = _git_problem(runner, target)
    if problem:
        warn(f"refused: {problem}")
        return ini.EXIT_REFUSED
    if ignore_problem:
        warn(
            "refused: the .gitignore could not be checked, so the whole adoption cannot be promised in one commit: "
            f"{ignore_problem}"
        )
        return ini.EXIT_REFUSED
    if hidden:
        warn("refused: fix the .gitignore (or git add -f after the adoption) so the whole adoption is in one commit")
        return ini.EXIT_REFUSED
    try:
        lines = apply_adopt(adopt, target, take)
    except AdoptRefused as e:
        warn(f"refused: {e}")
        return ini.EXIT_REFUSED
    except fc.ConfigError as e:
        warn(f"the framework.toml to write is invalid, so nothing was locked: {e}")
        return ini.EXIT_FAILED
    except OSError as e:
        warn(
            f"the write failed: {e}. No lock was written. `git status` shows what was; restore the tree "
            "(git stash -u, or git clean -fd and git checkout .) and run adopt again"
        )
        return ini.EXIT_FAILED
    for line in lines:
        say(line)
    import framework_sync as sync

    try:
        result = sync.report(target)
    except (fc.ConfigError, OSError) as e:
        warn(f"the sync check could not run on the result: {e}")
        return ini.EXIT_FAILED
    for finding in result.findings:
        warn(str(finding))
    for path, why in result.honoured:
        say(f"override in force: {path}: {why}")
    say(f"sync check on the result: {'clean' if not result.findings else str(len(result.findings)) + ' finding(s)'}")
    say(
        "nothing was committed: review the diff, then commit it on a branch. "
        "uv sync and the gate are the project's to run."
    )
    _LOGGER.info(f"adopted {target}: {len(lines)} step(s), {len(result.honoured)} override(s)")
    return ini.EXIT_OK if not result.findings else ini.EXIT_FAILED
