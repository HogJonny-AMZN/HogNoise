"""
Framework: the boundary check: the layer rules of every workspace member's ``src/``, read from the source and never
by importing it.
Package: tools/boundaries

The root ``pyproject.toml`` names the workspace's members (``[tool.uv.workspace] members``; see
``Docs/standards/layout.md``).
``framework.toml`` has an optional ``[layers]`` table naming their import packages from the lowest layer to the highest
(``order``), the pure ones (``pure``: the standard library and themselves only) and those deliberately outside the order
(``unlayered``). This tool reads every ``.py`` file under each member's ``src/`` with ``ast`` (importing would run
project code and needs the environment) and reports, as ``[rule] path:line: detail``:

``higher-layer``   a package imports one after it in ``order``
``impure``         a pure package imports anything outside the standard library and itself
``unlisted``       a package of a member is neither in ``order`` nor in ``unlayered``
``missing``        a name in ``order`` is no member's package
``cycle``          modules of one package import each other in a ring
``outside``        a member's module imports from ``tools/`` or ``tests/``, which are not part of the product
``relative-escape`` a relative import that climbs out of its top-level package
``no-layers``      the members have packages and ``framework.toml`` has no ``[layers]`` table
``app-import``     a package root (``packages/``) imports an app root's package (``apps/``)
``app-to-app``     an app root imports another app root's package
``experiment-import`` an app or a package imports an experiment's package (``experiments/``)
``undeclared``     a member imports another member's package that its manifest does not depend on
``duplicate``      two members provide a package of the same name
``unreached``      a ``src/`` with Python under ``apps/``, ``packages/`` or ``experiments/`` that no member reaches
``legacy-src``     a root ``src/`` holds a package: the layout before 0.7.0
``legacy-root``    the root manifest builds a project (``[project]``), or a folder at the root holds a package: the flat
                   layout before 0.7.0
``no-authors``     an app or package manifest has no ``[project] authors``, or an entry without a name or an
                   email (an experiment needs none)
``unparsable``     a file that cannot be read or parsed, a folder that cannot be listed, or a symlink that loops or
                   leads to a folder the walk does not follow (a check that could not see a file must not pass for
                   one that saw it)

**What counts as an import**: every ``import`` and ``from ... import`` statement anywhere in a file, including one
inside a function, under ``try`` or under ``if TYPE_CHECKING:`` (a layer rule that ignores a late import is not a
rule). A relative import is resolved against the file's own package. The standard library is the running
interpreter's list plus the modules removed in 3.12 and 3.13 (the floor is 3.11), and a member's package that shares a
stdlib name is project code. A ``cycle`` is looked for among the modules of one package: two unlayered packages that
import each other are not reported, and an import that only a late or ``TYPE_CHECKING`` import breaks still counts.
**What it cannot see**: ``importlib.import_module`` and ``__import__`` with a computed name, and a module reached
through a path edit; a project that needs those has left what a static check can hold.

Run standalone (exit code 0 clean, 1 findings, 2 the configuration or the arguments are unusable)::

    uv run python tools/boundaries.py [-v] [--root PATH]

``tests/test_boundaries.py`` runs it on fixtures that break each rule and on the repository's own members.
"""

from __future__ import annotations

import argparse
import ast
import logging as _logging
import os
import stat
import sys
import tomllib
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import framework_config as fc
import log_setup

# -------------------------------------------------------------------------
# module global scope
_MODULE_NAME = "tools.boundaries"
__version__ = "0.2.1"
__updated__ = "2026-11-07"
_LOGGER = _logging.getLogger(_MODULE_NAME)

ROOT = Path(__file__).resolve().parent.parent

#: Names a ``src/`` module may not import: the tools and the tests are not part of the product.
NOT_PRODUCT = frozenset({"tools", "tests"})
#: Standard-library modules removed in Python 3.12 and 3.13. The library floor is 3.11, where they still exist, so the
#: answer must not change with the interpreter that runs the check.
_REMOVED_STDLIB = frozenset(
    "aifc asynchat asyncore audioop cgi cgitb chunk crypt distutils imghdr imp lib2to3 mailcap msilib nis nntplib "
    "ossaudiodev pipes smtpd sndhdr spwd sunau telnetlib uu xdrlib".split()
)
_STDLIB = frozenset(sys.stdlib_module_names) | _REMOVED_STDLIB | {"__future__"}
_SKIPPED_DIRS = frozenset({"__pycache__"})
#: Folders at the root that may hold an ``__init__.py`` without being a package left outside the members: the member
#: roots (``apps``, ``packages``, ``experiments``), the framework's own (``tools``, ``tests``, ``scripts``,
#: ``launchers``, ``Docs``; an adopted repository may have a ``tests/__init__.py``), and ``src``, which ``legacy-src``
#: reports.
_FRAMEWORK_DIRS = frozenset(
    {"apps", "packages", "experiments", "tools", "tests", "scripts", "launchers", "docs", "src"}
)  # case-folded: compared with a folder's name case-folded
#: Where a ``legacy-src`` or ``legacy-root`` finding sends the reader.
_MOVE_GUIDE = '(Docs/standards/updating.md, "0.7.0: the repository layout")'


@dataclass(frozen=True)
class Finding:
    """One broken rule: which, where (a path relative to the repository and a 1-based line, 0 for none), and why."""

    rule: str
    path: str
    line: int
    detail: str

    def __str__(self) -> str:
        where = f"{self.path}:{self.line}" if self.line else self.path
        return f"[{self.rule}] {where}: {self.detail}"


@dataclass(frozen=True)
class _Import:
    top: str  # the top-level name imported ("" for a relative import that stays inside the package)
    module: str  # the dotted module it names, resolved ("" when unresolvable)
    line: int
    names: tuple[str, ...] = ()  # what a ``from`` import takes: ``from core import b`` may mean the module core.b


def _unreadable(path: Path, base: Path, error: OSError) -> Finding:
    return Finding(
        "unparsable", path.relative_to(base).as_posix(), 0, f"cannot be read, so it was not checked: {error}"
    )


def _is_environment(folder: Path) -> bool:
    """``node_modules``, or a virtual environment (it holds ``pyvenv.cfg``): installed packages, not the repository's
    code. One that cannot be read is not called one, so the walk enters it and reports what it cannot list."""
    if folder.name == "node_modules":
        return True
    try:
        return fc.path_kind(folder / "pyvenv.cfg") == "file"
    except OSError:
        return False


def _tree(
    top: Path,
    base: Path,
    findings: list[Finding],
    *,
    hidden: bool = True,
    links: bool = True,
    environments: bool = True,
) -> Iterator[tuple[Path, list[str], list[str]]]:
    """``os.walk`` over ``top``, each folder's names sorted and ``_SKIPPED_DIRS`` pruned; hidden folders too unless
    ``hidden``, and ``node_modules`` and virtual environments (a folder holding ``pyvenv.cfg``) unless
    ``environments``. A folder it cannot list, and a link below ``top`` that loops or cannot be read (``os.walk`` lists
    it among the files), is an ``unparsable`` finding: what the walk could not see must not pass. So is a linked folder
    that resolves, which the walk does not enter, unless ``links`` is False: a walk that only looks for folders passes
    those over. A Windows junction is a link here too; ``os.walk`` would otherwise follow it, round a loop if it is one.
    """
    problems: list[OSError] = []
    for dirpath, dirnames, filenames in os.walk(top, onerror=problems.append):
        here = Path(dirpath)
        linked: set[str] = set()
        for name in sorted([*dirnames, *filenames]):
            path = here / name
            if name in _SKIPPED_DIRS or (not hidden and name.startswith(".")):
                continue
            try:
                if not fc.is_link(path):
                    continue
            except OSError as e:  # its kind cannot be read: not entered, and said so
                linked.add(name)
                findings.append(_unreadable(path, base, e))
                continue
            linked.add(name)
            try:
                if fc.path_kind(path) == "dir" and links:
                    findings.append(Finding("unparsable", path.relative_to(base).as_posix(), 0, _NOT_FOLLOWED))
            except OSError as e:  # a loop: there, and nothing can be read through it
                findings.append(_unreadable(path, base, e))
        dirnames[:] = sorted(
            d
            for d in dirnames
            if d not in _SKIPPED_DIRS
            and d not in linked  # never entered, a junction included
            and (hidden or not d.startswith("."))
            and (environments or not _is_environment(here / d))
        )
        yield here, dirnames, sorted(filenames)
    for error in problems:
        where = (
            Path(error.filename).relative_to(base).as_posix() if error.filename else top.relative_to(base).as_posix()
        )
        findings.append(Finding("unparsable", where, 0, f"cannot be listed, so it was not checked: {error}"))


_NOT_FOLLOWED = "is a symlinked folder, which is not followed"


def _walk(src: Path, findings: list[Finding], base: Path) -> dict[str, list[Path]] | None:
    """``{top-level name: [its .py files]}``: a directory is a package, a ``.py`` file at the top is a module.
    ``None`` when ``src`` itself cannot be listed (a finding says so, and no other rule can be judged)."""
    found: dict[str, list[Path]] = {}
    try:
        entries = sorted(src.iterdir())
    except OSError as e:
        findings.append(Finding("unparsable", src.relative_to(base).as_posix(), 0, f"cannot be listed: {e}"))
        return None
    for entry in entries:
        if entry.name.startswith(".") or entry.name in _SKIPPED_DIRS or entry.name.endswith(".egg-info"):
            _LOGGER.info(f"skipped {entry.relative_to(base).as_posix()}: not a package")
            continue
        try:
            kind = fc.path_kind(entry)
        except OSError as e:
            findings.append(_unreadable(entry, base, e))
            continue
        if kind == "dir":  # a symlinked package is read through its link, as os.walk reads the folder it starts at
            files = [here / f for here, _, names in _tree(entry, base, findings) for f in names if f.endswith(".py")]
            if files:
                found[entry.name] = files
        elif entry.suffix == ".py" and entry.stem != "__init__":
            found[entry.stem] = [entry]
    return found


def _module_name(file: Path, src: Path) -> tuple[str, ...]:
    """The dotted module a file is, as parts: ``src/core/a.py`` is ``("core", "a")``; an ``__init__`` is its package."""
    parts = list(file.relative_to(src).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return tuple(parts)


def _imports(
    tree: ast.AST, module: tuple[str, ...], is_package: bool, rel: str, findings: list[Finding]
) -> list[_Import]:
    """Every import in ``tree``, resolved. ``module`` is the file's dotted name; ``is_package``: an ``__init__``."""
    found: list[_Import] = []
    package = module if is_package else module[:-1]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [_Import(a.name.split(".")[0], a.name, node.lineno) for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                name = node.module or ""
                found.append(_Import(name.split(".")[0], name, node.lineno, tuple(a.name for a in node.names)))
                continue
            climb = node.level - 1
            if climb >= len(package):  # climbs out of the top-level package
                findings.append(
                    Finding(
                        "relative-escape", rel, node.lineno, f"{'.' * node.level} climbs out of its top-level package"
                    )
                )
                continue
            base = package[: len(package) - climb]
            named = tuple(node.module.split(".")) if node.module else ()
            found.append(_Import("", ".".join((*base, *named)), node.lineno, tuple(a.name for a in node.names)))
    return found


def _resolve_module(module: str, names: set[str]) -> str:
    """Narrow ``a.b.c`` to the longest prefix that is a module of the scanned packages."""
    parts = module.split(".")
    while parts and ".".join(parts) not in names:
        parts.pop()
    return ".".join(parts)


def _edges(item: _Import, known: set[str]) -> list[str]:
    """The modules an import reaches: ``from core import b`` reaches ``core.b`` when that is a module, else ``core``."""
    submodules = [f"{item.module}.{n}" for n in item.names if f"{item.module}.{n}" in known]
    if submodules and len(submodules) == len(item.names):
        return submodules
    narrowed = _resolve_module(item.module, known)
    return [*submodules, *([narrowed] if narrowed else [])]


def _ring(component: list[str], graph: dict[str, set[str]]) -> list[str]:
    """A real ring through the first module of ``component``: the shortest path back to it along actual imports."""
    start = component[0]
    members = set(component)
    paths = {child: [start, child] for child in sorted(graph[start] & members)}
    queue = list(paths)
    while queue:
        node = queue.pop(0)
        if start in graph[node]:
            return paths[node]
        for child in sorted(graph[node] & members):
            if child not in paths:
                paths[child] = [*paths[node], child]
                queue.append(child)
    return component  # unreachable for a strongly connected component of more than one module


def _cycles(graph: dict[str, set[str]]) -> list[list[str]]:
    """The strongly connected components of more than one module (iterative Tarjan, so depth never limits it)."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    result: list[list[str]] = []
    counter = 0
    for start in sorted(graph):
        if start in index:
            continue
        work = [(start, iter(sorted(graph[start])))]
        index[start] = low[start] = counter
        counter += 1
        stack.append(start)
        on_stack.add(start)
        while work:
            node, children = work[-1]
            advanced = False
            for child in children:
                if child not in graph:
                    continue
                if child not in index:
                    index[child] = low[child] = counter
                    counter += 1
                    stack.append(child)
                    on_stack.add(child)
                    work.append((child, iter(sorted(graph[child]))))
                    advanced = True
                    break
                if child in on_stack:
                    low[node] = min(low[node], index[child])
            if advanced:
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
            if low[node] == index[node]:
                component = []
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    component.append(member)
                    if member == node:
                        break
                if len(component) > 1:
                    result.append(sorted(component))
    return sorted(result)


@dataclass(frozen=True)
class _Owner:
    """The workspace member a package belongs to: its folder, its kind (``app``, ``package`` or ``experiment``, from the
    folder's first part) and the distribution names its manifest depends on."""

    path: str
    kind: str
    dependencies: tuple[str, ...]
    name: str


_KINDS = {"apps": "app", "packages": "package", "experiments": "experiment"}
#: The folders a member lives under: a ``src/`` with Python below one of them must be reached by a member.
MEMBER_ROOTS = tuple(_KINDS)


def scan(src: Path, layers: fc.LayersConfig | None, base: Path | None = None) -> list[Finding]:
    """Every finding for the packages under ``src`` against ``layers``; paths are relative to ``base`` (``src``'s
    parent). A missing ``src/`` has nothing to hold and no findings."""
    base = base or src.parent
    try:
        kind = fc.path_kind(src)
    except OSError as e:
        return [_unreadable(src, base, e)]
    if kind == "missing":
        return []
    if kind != "dir":
        return [Finding("unparsable", src.relative_to(base).as_posix(), 0, "is not a folder, so it was not checked")]
    return _scan_roots([src], layers, base, None)


def _member_rules(
    top: str, target: str, owners: dict[str, _Owner], by_name: dict[str, _Owner], rel: str, line: int
) -> list[Finding]:
    """The rules between members, for one import of ``target`` by package ``top``."""
    mine, theirs = owners.get(top), owners.get(target)
    if mine is None or theirs is None or mine.path == theirs.path:
        return []
    found = []
    if theirs.kind == "experiment" and mine.kind in ("app", "package"):
        found.append(
            Finding(
                "experiment-import",
                rel,
                line,
                f"'{top}' imports '{target}', an experiment; nothing under apps/ or packages/ depends on one",
            )
        )
    if mine.kind == "package" and theirs.kind == "app":
        found.append(
            Finding("app-import", rel, line, f"'{top}' imports '{target}', an app; a package never imports an app")
        )
    elif mine.kind == "app" and theirs.kind == "app":
        found.append(
            Finding(
                "app-to-app", rel, line, f"'{top}' imports '{target}', another app; move what they share into a package"
            )
        )
    if theirs.name not in mine.dependencies and by_name.get(theirs.name) == theirs:  # by value: one per package
        found.append(
            Finding(
                "undeclared",
                rel,
                line,
                f"'{top}' imports '{target}', a member its manifest does not depend on: "
                f"add it to {mine.path}/pyproject.toml",
            )
        )
    return found


def _scan_roots(
    srcs: list[Path], layers: fc.LayersConfig | None, base: Path, owners: dict[str, _Owner] | None
) -> list[Finding]:
    """The rules over the packages of every root in ``srcs``. ``owners`` (package to member) turns on the rules between
    members and words ``missing`` and ``no-layers`` for a workspace."""
    findings: list[Finding] = []
    packages: dict[str, list[Path]] = {}
    roots: dict[str, Path] = {}  # package -> the src/ it is in
    for src in srcs:
        walked = _walk(src, findings, base)
        if walked is None:  # a root it could not list: no rule can be judged against what it did not see
            return sorted(findings, key=lambda f: (f.path, f.line, f.rule))
        for name, files in walked.items():
            if name in roots:
                findings.append(
                    Finding(
                        "duplicate",
                        f"{src.relative_to(base).as_posix()}/{name}",
                        0,
                        f"'{name}' is also a package of {roots[name].parent.relative_to(base).as_posix()}; "
                        "one install would hide the other",
                    )
                )
                continue
            packages[name] = files
            roots[name] = src
    if layers is None:
        if packages:
            if owners is None:
                where, detail = (
                    srcs[0].relative_to(base).as_posix(),
                    "has packages and framework.toml has no [layers] table",
                )
            else:
                where, detail = "framework.toml", "the workspace's members have packages and there is no [layers] table"
            findings.append(Finding("no-layers", where, 0, detail))
        return sorted(findings, key=lambda f: (f.path, f.line, f.rule))
    order = {name: i for i, name in enumerate(layers.order)}
    for name in sorted(packages):
        if name not in order and name not in layers.unlayered:
            findings.append(
                Finding(
                    "unlisted",
                    f"{roots[name].relative_to(base).as_posix()}/{name}",
                    0,
                    "is in neither layers.order nor layers.unlayered of framework.toml",
                )
            )
    for name in layers.order:
        if name not in packages:
            if owners is None:
                where, detail = srcs[0].relative_to(base).as_posix(), "which is not a package of src/"
            else:
                where, detail = "framework.toml", "which is not a package of any workspace member"
            findings.append(Finding("missing", where, 0, f"layers.order names '{name}', {detail}"))
    by_name = {o.name: o for o in (owners or {}).values()}
    modules: dict[tuple[str, ...], Path] = {}
    for name, files in packages.items():
        for file in files:
            modules[_module_name(file, roots[name])] = file
    known = {".".join(m) for m in modules}
    graph: dict[str, set[str]] = {}
    for module, file in sorted(modules.items()):
        rel = file.relative_to(base).as_posix()
        top = module[0] if module else file.stem
        try:
            tree = ast.parse(file.read_bytes(), filename=rel)
        except (SyntaxError, ValueError, RecursionError, MemoryError, OSError) as e:
            line = getattr(e, "lineno", None) or 0
            findings.append(
                Finding("unparsable", rel, line, f"cannot be read, so it was not checked: {type(e).__name__}: {e}")
            )
            continue
        for item in _imports(tree, module, file.name == "__init__.py", rel, findings):
            target = item.top or (item.module.split(".")[0] if item.module else "")
            if target in NOT_PRODUCT:
                findings.append(
                    Finding("outside", rel, item.line, f"imports '{target}', which is not part of the product")
                )
            if target in order and top in order and order[target] > order[top]:
                findings.append(
                    Finding(
                        "higher-layer",
                        rel,
                        item.line,
                        f"'{top}' imports '{target}', a higher layer (order: {', '.join(layers.order)})",
                    )
                )
            if top in layers.pure and target != top and (target not in _STDLIB or target in packages):
                findings.append(
                    Finding(
                        "impure",
                        rel,
                        item.line,
                        f"pure layer '{top}' imports '{target}', which is not the standard library",
                    )
                )
            if owners is not None:
                findings += _member_rules(top, target, owners, by_name, rel, item.line)
            if target == top:
                for edge in _edges(item, known):
                    if edge != ".".join(module):
                        graph.setdefault(".".join(module), set()).add(edge)
        graph.setdefault(".".join(module), set())
    for component in _cycles(graph):
        ring = _ring(component, graph)
        first = modules[tuple(component[0].split("."))].relative_to(base).as_posix()
        more = (
            f" (one ring of {len(component)} modules that depend on each other)" if len(ring) < len(component) else ""
        )
        findings.append(
            Finding("cycle", first, 0, "modules import each other in a ring: " + " -> ".join([*ring, ring[0]]) + more)
        )
    where = ", ".join(s.relative_to(base).as_posix() for s in srcs)
    _LOGGER.info(f"scanned {len(modules)} module(s) in {len(packages)} package(s) of {where}")
    return sorted(findings, key=lambda f: (f.path, f.line, f.rule, f.detail))


def _legacy_src(root: Path) -> list[Finding]:
    """A root ``src/`` holding a package: the layout before 0.7.0, which no workspace member reaches."""
    src = root / "src"
    try:
        if fc.path_kind(src) != "dir":
            return []
    except OSError as e:
        return [_unreadable(src, root, e)]
    findings: list[Finding] = []
    found = _walk(src, findings, root) or {}
    return findings + [
        Finding(
            "legacy-src",
            f"src/{name}",
            0,
            "a root src/ with packages; 0.7.0 moves them into apps/ and packages/ "
            '(Docs/standards/updating.md, "0.7.0: the repository layout")',
        )
        for name in sorted(found)
    ]


def _legacy_root(root: Path) -> list[Finding]:
    """The flat shape before 0.7.0: a root manifest that builds a project, and a package folder at the root.

    The 0.7.0 root is virtual (``layout.md``): its ``pyproject.toml`` has no ``[project]``, in any form, so a
    ``project`` key that is not a table is reported too. A folder at the root holding an ``__init__.py`` file is a
    package that no member reaches, unless it is one of ``_FRAMEWORK_DIRS`` in any case (``Tests`` is ``tests`` on a
    filesystem that ignores case) or hidden. A root, or a folder, that cannot be read is ``unparsable``: a check that
    could not see must not pass.

    **What it cannot see:** a namespace package (a folder of modules with no ``__init__.py``) and a lone module at the
    root are not reported; under a virtual root, a repository holding only those passes.

    :param root: The repository.
    :return: The findings, unsorted.
    """
    findings: list[Finding] = []
    manifest = root / "pyproject.toml"
    try:
        has_manifest = fc.path_kind(manifest) == "file"
    except OSError as e:  # there and unreadable is not "no manifest", which would read as a virtual root
        raise fc.ConfigError("pyproject.toml", f"the root manifest cannot be read: {e}") from e
    if has_manifest:
        try:
            with manifest.open("rb") as handle:
                builds = "project" in tomllib.load(handle)
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as e:
            raise fc.ConfigError("pyproject.toml", f"the root manifest cannot be read: {e}") from e
        _LOGGER.info(f"root manifest: {'builds a project' if builds else 'virtual'}")
        if builds:
            findings.append(
                Finding(
                    "legacy-root",
                    "pyproject.toml",
                    0,
                    "the root manifest builds a project; the 0.7.0 root is virtual (Docs/standards/layout.md): "
                    f"remove [project], moving any package it builds into a member {_MOVE_GUIDE}",
                )
            )
    try:
        entries = sorted(root.iterdir())
    except OSError as e:
        detail = f"the root cannot be listed, so no package at the root was looked for: {e}"
        return [*findings, Finding("unparsable", ".", 0, detail)]
    for entry in entries:
        if entry.name.startswith(".") or entry.name.casefold() in _FRAMEWORK_DIRS:
            _LOGGER.info(f"skipped {entry.name}: the framework's own, or hidden")
            continue
        try:  # stat, not is_dir/is_file, which answer False for a symlink loop and raise nothing
            package = stat.S_ISDIR(entry.stat().st_mode) and stat.S_ISREG((entry / "__init__.py").stat().st_mode)
        except (FileNotFoundError, NotADirectoryError):
            package = False  # a dangling link, or no __init__.py: nothing at the root to report
        except OSError as e:
            findings.append(Finding("unparsable", entry.name, 0, f"cannot be read, so it was not checked: {e}"))
            continue
        if package:
            _LOGGER.info(f"{entry.name}: a package at the root")
            detail = f"a package at the root; 0.7.0 moves it into a member {_MOVE_GUIDE}"
            findings.append(Finding("legacy-root", entry.name, 0, detail))
    return findings


def _unreached(root: Path, members: tuple[fc.Member, ...]) -> list[Finding]:
    """A ``src/`` with Python under ``apps/``, ``packages/`` or ``experiments/`` whose folder is no member."""
    reached = {m.path for m in members}
    findings: list[Finding] = []
    for top in MEMBER_ROOTS:
        try:
            if fc.path_kind(root / top) != "dir":
                continue
        except OSError as e:
            findings.append(_unreadable(root / top, root, e))
            continue
        srcs: list[Path] = []
        with_python: set[Path] = set()
        # hidden folders (an environment) and caches are not code of the repository; a folder it cannot list is a
        # finding, never a src/ silently unseen (rglob would skip it without a word)
        for here, _, names in _tree(root / top, root, findings, hidden=False, links=False, environments=False):
            if here.name == "src":
                srcs.append(here)
            if any(name.endswith(".py") for name in names):
                with_python.add(here)
        for src in sorted(srcs):
            folder = src.parent.relative_to(root).as_posix()
            if folder in reached or any(folder.startswith(f"{member}/src/") for member in reached):
                continue  # a member, or inside a member's own src/: the search for Python below is not needed
            if any(found == src or src in found.parents for found in with_python):
                findings.append(
                    Finding(
                        "unreached",
                        src.relative_to(root).as_posix(),
                        0,
                        f'a src/ no workspace member reaches: add "{folder}" to [tool.uv.workspace] members',
                    )
                )
    return findings


def _no_authors(members: tuple[fc.Member, ...]) -> list[Finding]:
    """An app or package member whose manifest names no authors, or an author without a name or an email. An
    experiment needs none (the owner, 2026-11-06), nor does a member outside ``apps/`` and ``packages/``."""
    findings = []
    for member in members:
        if _KINDS.get(member.path.split("/")[0]) not in ("app", "package"):
            continue
        where = f"{member.path}/pyproject.toml"
        if not member.authors:
            detail = (
                "[project] authors is missing or empty: name the people who wrote this member, each with name and "
                "email (Docs/standards/layout.md)"
            )
            findings.append(Finding("no-authors", where, 0, detail))
        for number, author in enumerate(member.authors, start=1):
            if not author.table:
                findings.append(
                    Finding("no-authors", where, 0, f"[project] authors entry {number} is not a table (name and email)")
                )
                continue
            missing = [field for field, value in (("name", author.name), ("email", author.email)) if value is None]
            if missing:
                detail = f"[project] authors entry {number} has no {' or '.join(missing)}"
                findings.append(Finding("no-authors", where, 0, detail))
    return findings


def scan_workspace(root: Path, layers: fc.LayersConfig | None) -> list[Finding]:
    """Every finding for the repository at ``root``: a leftover root ``src/``, a root manifest that builds a project or
    a package at the root (the flat shape), a member ``src/`` the workspace does not reach, an app or package manifest
    without its authors, and the rules over the ``src/`` of every workspace member, within packages and between
    members."""
    members = fc.workspace_members(root)
    owners = {
        package: _Owner(m.path, _KINDS.get(m.path.split("/")[0], "other"), m.dependencies, m.name)
        for m in members
        for package in m.packages
    }
    findings = _legacy_src(root) + _legacy_root(root) + _unreached(root, members) + _no_authors(members)
    srcs = []
    for member in members:
        src = root / member.path / "src"
        try:
            if fc.path_kind(src) == "dir":
                srcs.append(src)
        except OSError as e:
            findings.append(_unreadable(src, root, e))
    # No members is a repository not yet moved (legacy-src or legacy-root says so); members with no src/ still answer.
    if members:
        findings += _scan_roots(srcs, layers, root, owners)
    # two walks can meet the same unreadable path (a loop inside a member's src/): it is one finding
    return sorted(set(findings), key=lambda f: (f.path, f.line, f.rule, f.detail))


def main(argv: list[str] | None = None) -> int:
    """Check the workspace's members against the repository's ``[layers]``; returns 0 clean, 1 findings, 2 unusable."""
    for stream in (sys.stdout, sys.stderr):  # a finding naming a non-ASCII file must not crash the report
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="backslashreplace")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=ROOT, help="the repository (default: this one)")
    parser.add_argument("-v", "--verbose", action="store_true", help="log what was scanned to standard error")
    args = parser.parse_args(argv)
    log_setup.configure(args.verbose)
    root = args.root.resolve()
    if not root.is_dir():
        print(f"boundaries: cannot run: {root} is not a directory", file=sys.stderr)
        return 2
    try:
        config = fc.load_framework(root / "framework.toml")
    except fc.ConfigError as e:
        print(f"boundaries: cannot run: {e}", file=sys.stderr)
        return 2
    try:
        found = scan_workspace(root, config.layers)
        members = fc.workspace_members(root)
    except fc.ConfigError as e:
        print(f"boundaries: cannot run: {e}", file=sys.stderr)
        return 2
    for finding in found:
        print(finding)
    if found:
        print(f"boundaries: {len(found)} finding(s)")
        return 1
    print("boundaries: clean" if members else "boundaries: no workspace members, nothing to check")
    return 0


if __name__ == "__main__":
    sys.exit(main())
