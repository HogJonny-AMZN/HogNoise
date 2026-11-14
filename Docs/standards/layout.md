# Repository layout

**Status:** Living. Managed by the template (the `core` module): a repository's copy must match, so do not edit it here;
propose a change to the template. Where code lives in a repository made from the template, in any language.
**Read with:** [python.md](python.md) · [testing.md](testing.md) · [tooling.md](tooling.md)

**This project's additions** go in `layout-project.md` beside this file, when it has any: an extension adds rules and never
weakens these. To relax or contradict a rule here, override this file in `framework.toml` with a reason that names the
rule.

## The tree

A repository is a workspace of **members**, and has no root `src/`. A new repository starts in this shape, with one app
and one library, so that adding a unit is an entry in a list and nothing that exists moves:

```text
<repository>/
├── pyproject.toml         the workspace root: the framework's environment, builds nothing
├── tools/  tests/         the framework's scripts and their tests
├── Docs/
├── launchers/             one thin wrapper per entry point
├── apps/<app>/            an app root: one launchable application
└── packages/<language>/<name>/   a package root: one installable library
```

`experiments/` and `packages/js/` appear only when the repository needs them.

## Workspace members

An **app root**, `apps/<app>/`, is one independently launchable application, GUI or command line. A **package root**,
`packages/<language>/<name>/`, is one installable library, grouped by language from the first one. Each is a **workspace
member** and is self-contained:

- its own manifest (`pyproject.toml` for Python): name, version, **authors** (PEP 621's `[project] authors`, each
  with a name and an email; `init new` seeds the owner), dependencies, build backend, entry points;
- its own `src/<package>/`, holding one top-level package named for the member;
- its own `tests/`, mirroring its `src/`, with a `conftest.py` where it needs one and **no `__init__.py`**;
- its assets as package data inside its package (`src/<package>/resources/`), read through `importlib.resources`.

A member that uses another names it in its manifest's dependencies, with the workspace as the source. An app may depend on
packages; a package never depends on an app; an app never depends on another app: what two apps share is a package.

An app with halves in two languages has one member per half, `apps/<app>/<part>/`, each with its own manifest. The
root manifest names the parts in its members list, and in ruff's `src` and pytest's `testpaths`
(`apps/<app>/*/src`, `apps/<app>/*/tests`), which reach one level only: a part they do not name is neither linted
as first-party nor tested.

An **experiment**, `experiments/<name>/`, is live, unproven work that may become a member. Unlike a spike it is
maintained and the gate covers it; nothing under `apps/` or `packages/` imports from it.

## Names

A repository's slug (`acme-tools`) names folders and distributions; an import package uses it normalised, lower case with
hyphens as underscores (`acme_tools`). So the app root is `apps/acme-tools/src/acme_tools/`, and a library is
`packages/python/acme-tools-core/src/acme_tools_core/`. Member names carry the slug, so the packages of several
repositories can be installed in one environment. A module's `Package:` line and `_MODULE_NAME` are its import path
(`acme_tools.store`), never its folder.

## The root manifest

The root `pyproject.toml` has no `[project]` table: it is a virtual workspace root, so it builds nothing, and a plain
`uv sync` installs every member. It is also the environment the framework's `tools/` and `tests/` run in, so the shared
tools and their configuration live there, once:

- `[tool.uv.workspace] members`, the folders of every member (`"apps/*"`, `"packages/python/*"`, and any nested part);
- the `dev` dependency group the gate's tools need;
- ruff, with `src` naming every member's `src/`;
- pytest: `testpaths` naming the framework's `tests` and every member's, `--import-mode=importlib`, and
  `pythonpath = ["tests"]` for the framework's own test helpers.

## Tests across members

One `uv run pytest` at the root runs the framework's tests and every member's. Two members may each have a
`tests/conftest.py` and a test file of the same name: importlib mode imports a test file by its path, and with no
`__init__.py` in any `tests/` there is no package called `tests` in two places, so the second `conftest.py` does not
collide with the first ("Plugin already registered"). `tests/test_workspace_tests.py` holds both: the run that passes, and
the `__init__.py` that breaks it. A member's own manifest may set `testpaths = ["tests"]`, so its tests also run alone from
its folder. If the repository adds mypy, it needs `explicit_package_bases = true` for the same reason.

**A helper imported by bare name.** Importlib mode puts no test folder on `sys.path`, so a test that imports a helper
beside it (`from gpu_harness import run`) fails to find it. The fix the template prefers is the folder's own
`conftest.py` putting that folder on `sys.path`, as the root's `pythonpath = ["tests"]` does for the framework's tests:
one place per folder, run before any test in it, where a test file inserting the path itself (as the framework's tests
do for `tools/`, [testing.md](testing.md)) repeats it in every file that borrows the helper.
That does not isolate the helper: a bare name is cached once in `sys.modules`, so two members with a `gpu_harness.py`
share whichever was imported first, and a test that passes alone fails, or quietly uses the other helper, in the
combined run. So **each bare helper name is unique** across the members and the framework's `tests/`; a colliding one
takes its member's prefix (`acme_tools_gpu_harness`), and its imports with it. A root test that borrows a member's helper
names that member's path the same way.

## Layers between members

`tools/boundaries.py` reads the root manifest's members and checks every member's `src/` with `ast`. Within and among the
packages, `[layers]` in `framework.toml` orders the import packages (*Layers* in [python.md](python.md)), and modules of
one package may not import each other in a ring (`cycle`; a late import counts, one under `if __name__ == "__main__":`
included). Between members the shape is the rule:

| Finding | When |
| --- | --- |
| `app-import` | a package root's module imports an app root's package |
| `app-to-app` | an app root's module imports another app root's package |
| `undeclared` | a member imports another member's package that its manifest does not depend on |
| `experiment-import` | an app or a package imports an experiment's package |
| `duplicate` | two members provide a package of the same name: one install would hide the other |
| `unreached` | a `src/` with Python under `apps/`, `packages/` or `experiments/` that no member reaches |
| `legacy-src` | a root `src/` holds a package: move it into a member ([updating.md](updating.md), "0.7.0: the repository layout") |
| `legacy-root` | the root manifest builds a project (`[project]`: the root is virtual), or a folder at the root other than the framework's own holds a package (a flat layout): move it into a member, as for `legacy-src`. A namespace package (no `__init__.py`) or a lone module at the root is not seen |
| `no-authors` | an app or package manifest has no `[project] authors`, or an entry without a name or an email; an experiment needs none |

## Launchers

`launchers/` holds one wrapper per entry point, for each platform: `<name>.cmd` (`uv run <name> %*`) and `<name>.sh`
(`exec uv run <name> "$@"`, executable). Each passes on every argument it was given, so `launchers/acme-tools.sh --help`
asks the tool for help. The entry point is a script in the member's manifest (`[project.scripts]`). `tools/` is the
framework's in every repository made from the template, so launchers never go there. Windows records no executable
bit: a repository committed from Windows runs `git add --chmod=+x launchers/*.sh` once, or a teammate on Linux or
macOS gets "Permission denied".

## Languages

The shape is the same for every language; each language's standard says what its member holds. Python's is
[python.md](python.md). `packages/js/` is reserved for JavaScript and TypeScript, and is not created until a repository
needs it; their standard is not written yet.
