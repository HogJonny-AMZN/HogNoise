"""
Framework: the boundary check: the layer rules of ``src/``, read from the source and never by importing it.
Package: tools/boundaries

``framework.toml`` has an optional ``[layers]`` table naming the packages of ``src/`` from the lowest layer to the
highest (``order``), the pure ones (``pure``: the standard library and themselves only) and those deliberately outside
the order (``unlayered``). This tool reads every ``.py`` file under ``src/`` with ``ast`` (importing would run project
code and needs the environment) and reports, as ``[rule] path:line: detail``:

``higher-layer``   a package imports one after it in ``order`` (``core`` importing ``app``)
``impure``         a pure package imports anything outside the standard library and itself
``unlisted``       a package of ``src/`` is neither in ``order`` nor in ``unlayered``
``missing``        a name in ``order`` has no package in ``src/``
``cycle``          modules of one package import each other in a ring
``outside``        a ``src/`` module imports from ``tools/`` or ``tests/``, which are not part of the product
``relative-escape`` a relative import that climbs out of its top-level package
``no-layers``      ``src/`` has packages and ``framework.toml`` has no ``[layers]`` table: the decision is the project's
``unparsable``     a file that cannot be read or parsed, or a folder that cannot be listed (a check that could not see
                   a file must not pass for one that saw it)

**What counts as an import**: every ``import`` and ``from ... import`` statement anywhere in a file, including one
inside a function, under ``try`` or under ``if TYPE_CHECKING:`` (a layer rule that ignores a late import is not a
rule). A relative import is resolved against the file's own package. The standard library is the running
interpreter's list plus the modules removed in 3.12 and 3.13 (the floor is 3.11), and a ``src/`` package that shares a
stdlib name is project code. A ``cycle`` is looked for among the modules of one package: two unlayered packages that
import each other are not reported, and an import that only a late or ``TYPE_CHECKING`` import breaks still counts.
**What it cannot see**: ``importlib.import_module`` and ``__import__`` with a computed name, and a module reached
through a path edit; a project that needs those has left what a static check can hold.

Run standalone (exit code 0 clean, 1 findings, 2 the configuration or the arguments are unusable)::

    uv run python tools/boundaries.py [-v] [--root PATH]

``tests/test_boundaries.py`` runs it on fixtures that break each rule and on the repository's own ``src/``.
"""

from __future__ import annotations

import argparse
import ast
import logging as _logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import framework_config as fc

# -------------------------------------------------------------------------
# module global scope
_MODULE_NAME = "tools.boundaries"
__version__ = "0.1.0"
__updated__ = "2026-10-14"
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


def _walk(src: Path, findings: list[Finding], base: Path) -> dict[str, list[Path]] | None:
    """``{top-level name: [its .py files]}``: a directory is a package, a ``.py`` file at the top is a module.
    ``None`` when ``src`` itself cannot be listed (a finding says so, and no other rule can be judged)."""
    problems: list[OSError] = []
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
        if entry.is_dir():
            files = []
            for dirpath, dirnames, filenames in os.walk(entry, onerror=problems.append):
                for d in dirnames:
                    if (Path(dirpath) / d).is_symlink():  # os.walk does not follow it, so its files are unseen
                        where = (Path(dirpath) / d).relative_to(base).as_posix()
                        findings.append(Finding("unparsable", where, 0, "is a symlinked folder, which is not followed"))
                dirnames[:] = sorted(d for d in dirnames if d not in _SKIPPED_DIRS)
                files += [Path(dirpath) / f for f in sorted(filenames) if f.endswith(".py")]
            if files:
                found[entry.name] = files
        elif entry.suffix == ".py" and entry.stem != "__init__":
            found[entry.stem] = [entry]
    for error in problems:
        where = Path(error.filename).relative_to(base).as_posix() if error.filename else src.as_posix()
        findings.append(Finding("unparsable", where, 0, f"cannot be listed, so it was not checked: {error}"))
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


def scan(src: Path, layers: fc.LayersConfig | None, base: Path | None = None) -> list[Finding]:
    """Every finding for the packages under ``src`` against ``layers``; paths are relative to ``base`` (``src``'s
    parent). A missing ``src/`` has nothing to hold and no findings."""
    base = base or src.parent
    findings: list[Finding] = []
    if src.exists() and not src.is_dir():
        return [Finding("unparsable", src.relative_to(base).as_posix(), 0, "is not a folder, so it was not checked")]
    if not src.is_dir():
        return []
    packages = _walk(src, findings, base)
    if packages is None:
        return findings
    if layers is None:
        if packages:
            findings.append(
                Finding(
                    "no-layers",
                    src.relative_to(base).as_posix(),
                    0,
                    "has packages and framework.toml has no [layers] table",
                )
            )
        return sorted(findings, key=lambda f: (f.path, f.line, f.rule))
    order = {name: i for i, name in enumerate(layers.order)}
    src_rel = src.relative_to(base).as_posix()
    for name in sorted(packages):
        if name not in order and name not in layers.unlayered:
            findings.append(
                Finding(
                    "unlisted",
                    f"{src_rel}/{name}",
                    0,
                    "is in neither layers.order nor layers.unlayered of framework.toml",
                )
            )
    for name in layers.order:
        if name not in packages:
            findings.append(
                Finding("missing", src_rel, 0, f"layers.order names '{name}', which is not a package of src/")
            )
    modules: dict[tuple[str, ...], Path] = {}
    for files in packages.values():
        for file in files:
            modules[_module_name(file, src)] = file
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
    _LOGGER.info(f"scanned {len(modules)} module(s) in {len(packages)} package(s) of {src_rel}")
    return sorted(findings, key=lambda f: (f.path, f.line, f.rule, f.detail))


def main(argv: list[str] | None = None) -> int:
    """Check ``src/`` against the repository's ``[layers]``; returns 0 clean, 1 findings, 2 unusable."""
    for stream in (sys.stdout, sys.stderr):  # a finding naming a non-ASCII file must not crash the report
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="backslashreplace")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=ROOT, help="the repository (default: this one)")
    parser.add_argument("-v", "--verbose", action="store_true", help="log what was scanned to standard error")
    args = parser.parse_args(argv)
    _logging.basicConfig(
        level=_logging.INFO if args.verbose else _logging.WARNING, format="%(message)s", stream=sys.stderr
    )
    root = args.root.resolve()
    if not root.is_dir():
        print(f"boundaries: cannot run: {root} is not a directory", file=sys.stderr)
        return 2
    try:
        config = fc.load_framework(root / "framework.toml")
    except fc.ConfigError as e:
        print(f"boundaries: cannot run: {e}", file=sys.stderr)
        return 2
    src = root / "src"
    found = scan(src, config.layers, root)
    for finding in found:
        print(finding)
    if found:
        print(f"boundaries: {len(found)} finding(s)")
        return 1
    print("boundaries: clean" if src.is_dir() else "boundaries: no src/, nothing to check")
    return 0


if __name__ == "__main__":
    sys.exit(main())
