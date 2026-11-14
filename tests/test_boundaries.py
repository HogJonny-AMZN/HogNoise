"""
Framework: tests for tools/boundaries.py (the layer rules of src/, read from the source).
Package: tests/test_boundaries

Every rule has a fixture that breaks exactly that rule and requires the finding, with its file and line, and the fixture
unbroken passes. The last test holds the repository's own ``src/`` to its own ``[layers]``.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import boundaries as b  # noqa: E402
import framework_config as fc  # noqa: E402

# Fixed text, not the repository's own framework.toml: this file is managed, and a project owns that one.
FRAMEWORK = """[framework]
template_version = "0.1.0"

[modules]
core = "on"
journal = "on"
ux = "planned"
python-uv = "on"
tasking = "planned"
hygiene = "on"
graph = "on"
harness-adapters = "on"
specimens = "on"
lanes = "off"
branch-ownership = "off"
devblog = "off"

[harnesses]
enabled = []

[checks]
handoff_max_lines = 150
"""

CLEAN = {
    "src/core/__init__.py": '"""Core."""\n',
    "src/core/tasks.py": (
        "from __future__ import annotations\n\nimport json\nfrom dataclasses import dataclass\n\n"
        "from core import rules\n\n\n@dataclass\nclass Task:\n    name: str\n"
    ),
    "src/core/rules.py": "def ok() -> bool:\n    return True\n",
    "src/app/__init__.py": '"""App."""\n',
    "src/app/service.py": (
        "from core.tasks import Task\n\nimport numpy\n\n\ndef make(name: str) -> Task:\n    return Task(name)\n"
    ),
}


def _repo(tmp_path: Path, files: dict[str, str] | None = None, **extra: str) -> Path:
    for rel, text in {**(CLEAN if files is None else files), **extra}.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
    return tmp_path


def _layers(order=("core", "app"), pure=("core",), unlayered=()) -> fc.LayersConfig:
    return fc.LayersConfig(tuple(order), tuple(pure), tuple(unlayered))


def _scan(root: Path, layers: fc.LayersConfig | None = None) -> list[str]:
    return [str(f) for f in b.scan(root / "src", layers if layers is not None else _layers(), root)]


# ---- the unbroken project passes
def test_a_project_that_keeps_its_layers_has_no_findings(tmp_path: Path) -> None:
    assert _scan(_repo(tmp_path)) == []


def test_a_missing_src_has_nothing_to_hold(tmp_path: Path) -> None:
    assert _scan(tmp_path) == []


# ---- higher-layer
@pytest.mark.parametrize(
    ("source", "line"),
    [
        ("import app\n", 1),
        ("from app import service\n", 1),
        ("from app.service import make\n", 1),
        ("import app.service as s\n", 1),
        ("x = 1\n\n\ndef late():\n    from app import service\n", 5),  # inside a function: counted
        ("try:\n    import app\nexcept ImportError:\n    app = None\n", 2),  # under try
        (
            "from typing import TYPE_CHECKING\n\nif TYPE_CHECKING:\n    from app import service\n",
            4,
        ),  # type-only: counted
    ],
)
def test_a_lower_layer_importing_a_higher_one_is_found_with_its_line(tmp_path: Path, source: str, line: int) -> None:
    root = _repo(tmp_path, **{"src/core/rules.py": source})
    found = _scan(root, _layers(pure=()))
    assert found == [
        f"[higher-layer] src/core/rules.py:{line}: 'core' imports 'app', a higher layer (order: core, app)"
    ]


def test_a_higher_layer_importing_a_lower_one_is_fine(tmp_path: Path) -> None:
    assert _scan(_repo(tmp_path), _layers(pure=())) == []


def test_the_layer_names_and_their_order_come_from_the_table(tmp_path: Path) -> None:
    """Reverse the order and the same import becomes the violation."""
    root = _repo(tmp_path)
    found = _scan(root, _layers(order=("app", "core"), pure=()))
    assert [f.split(":")[0] for f in found] == ["[higher-layer] src/app/service.py"]


# ---- impure
@pytest.mark.parametrize("module", ["numpy", "PySide6", "requests"])
def test_a_pure_layer_importing_a_third_party_package_is_found(tmp_path: Path, module: str) -> None:
    root = _repo(tmp_path, **{"src/core/rules.py": f"import {module}\n"})
    assert _scan(root) == [
        f"[impure] src/core/rules.py:1: pure layer 'core' imports '{module}', which is not the standard library"
    ]


@pytest.mark.parametrize(
    "line",
    [
        "import os",
        "import json",
        "from __future__ import annotations",
        "from typing import Any",
        "import core",
        "from core import tasks",
        "from . import tasks",
        "from .tasks import Task",
    ],
)
def test_a_pure_layer_may_import_the_standard_library_and_itself(tmp_path: Path, line: str) -> None:
    root = _repo(tmp_path, **{"src/core/rules.py": line + "\n"})
    assert not [f for f in _scan(root) if f.startswith("[impure]")]


def test_a_pure_layer_may_not_import_another_layer_even_a_lower_pure_one(tmp_path: Path) -> None:
    files = {"src/base/__init__.py": "", "src/core/__init__.py": "", "src/core/a.py": "import base\n"}
    root = _repo(tmp_path, files)
    found = _scan(root, _layers(order=("base", "core"), pure=("base", "core")))
    assert found == ["[impure] src/core/a.py:1: pure layer 'core' imports 'base', which is not the standard library"]


def test_an_impure_layer_may_use_third_party_packages(tmp_path: Path) -> None:
    assert not [f for f in _scan(_repo(tmp_path)) if "numpy" in f]  # app imports numpy and is not pure


# ---- unlisted and missing
def test_a_package_in_neither_list_is_found_and_listing_it_clears_the_finding(tmp_path: Path) -> None:
    root = _repo(tmp_path, **{"src/extra/__init__.py": "", "src/extra/x.py": "y = 1\n"})
    assert _scan(root) == ["[unlisted] src/extra: is in neither layers.order nor layers.unlayered of framework.toml"]
    assert _scan(root, _layers(unlayered=("extra",))) == []


def test_a_module_file_at_the_top_of_src_is_a_package_too(tmp_path: Path) -> None:
    root = _repo(tmp_path, **{"src/helper.py": "y = 1\n"})
    assert _scan(root) == ["[unlisted] src/helper: is in neither layers.order nor layers.unlayered of framework.toml"]


def test_a_name_in_order_with_no_package_is_found(tmp_path: Path) -> None:
    found = _scan(_repo(tmp_path), _layers(order=("core", "app", "ui")))
    assert found == ["[missing] src: layers.order names 'ui', which is not a package of src/"]


@pytest.mark.parametrize("entry", ["__pycache__/x.py", ".hidden/x.py", "pkg.egg-info/x.py", "__init__.py"])
def test_caches_hidden_entries_and_egg_info_are_not_packages(tmp_path: Path, entry: str) -> None:
    assert _scan(_repo(tmp_path, **{f"src/{entry}": "x = 1\n"})) == []


def test_a_folder_with_no_python_is_not_a_package(tmp_path: Path) -> None:
    assert _scan(_repo(tmp_path, **{"src/assets/logo.txt": "x"})) == []


# ---- cycle
def test_two_modules_importing_each_other_are_a_cycle(tmp_path: Path) -> None:
    root = _repo(tmp_path, **{"src/core/a.py": "from . import b\n", "src/core/b.py": "from . import a\n"})
    found = [f for f in _scan(root) if f.startswith("[cycle]")]
    assert found == ["[cycle] src/core/a.py: modules import each other in a ring: core.a -> core.b -> core.a"]


@pytest.mark.parametrize(
    ("a", "b_"),
    [
        ("import core.b\n", "import core.a\n"),
        ("from core import b\n", "from core import a\n"),
        ("from core.b import x\n", "from core.a import y\n"),
        ("from .b import x\n", "from .a import y\n"),
        ("def f():\n    import core.b\n", "import core.a\n"),  # a late import is still a ring
    ],
)
def test_every_spelling_of_the_ring_is_found(tmp_path: Path, a: str, b_: str) -> None:
    root = _repo(tmp_path, **{"src/core/a.py": a, "src/core/b.py": b_})
    assert any(f.startswith("[cycle]") for f in _scan(root))


def test_a_one_way_import_and_a_self_import_are_not_a_cycle(tmp_path: Path) -> None:
    root = _repo(tmp_path, **{"src/core/a.py": "from . import b\nimport core.a\n", "src/core/b.py": "x = 1\n"})
    assert not [f for f in _scan(root) if f.startswith("[cycle]")]


def test_a_ring_of_three_is_one_finding(tmp_path: Path) -> None:
    files = {"src/core/a.py": "import core.b\n", "src/core/b.py": "import core.c\n", "src/core/c.py": "import core.a\n"}
    found = [f for f in _scan(_repo(tmp_path, **files)) if f.startswith("[cycle]")]
    assert found == ["[cycle] src/core/a.py: modules import each other in a ring: core.a -> core.b -> core.c -> core.a"]


def test_a_long_ring_does_not_run_out_of_stack(tmp_path: Path) -> None:
    """The search is iterative: a ring of thousands of modules is still found, and does not raise RecursionError."""
    count = 1500
    files = {"src/core/__init__.py": ""}
    for i in range(count):
        files[f"src/core/m{i}.py"] = f"import core.m{(i + 1) % count}\n"
    found = [f for f in _scan(_repo(tmp_path, files), _layers(pure=())) if f.startswith("[cycle]")]
    assert len(found) == 1 and found[0].count("->") == count


# ---- outside
@pytest.mark.parametrize(
    "line", ["import tools.check", "from tools import check", "import tests", "from tests.helpers import x"]
)
def test_src_may_not_import_the_tools_or_the_tests(tmp_path: Path, line: str) -> None:
    root = _repo(tmp_path, **{"src/app/service.py": line + "\n"})
    found = _scan(root)
    assert (
        found
        and found[0].startswith("[outside] src/app/service.py:1: imports '")
        and "not part of the product" in found[0]
    )


# ---- relative-escape
def test_a_relative_import_that_climbs_out_of_its_package_is_found(tmp_path: Path) -> None:
    root = _repo(tmp_path, **{"src/core/rules.py": "from .. import app\n"})
    assert _scan(root) == ["[relative-escape] src/core/rules.py:1: .. climbs out of its top-level package"]


def test_a_relative_import_inside_a_subpackage_resolves_against_it(tmp_path: Path) -> None:
    files = {
        "src/core/sub/__init__.py": "",
        "src/core/sub/x.py": "from ..rules import ok\nfrom . import y\n",
        "src/core/sub/y.py": "",
    }
    assert _scan(_repo(tmp_path, **files)) == []


# ---- no-layers
def test_src_with_packages_and_no_layers_table_is_a_finding(tmp_path: Path) -> None:
    found = [str(f) for f in b.scan(_repo(tmp_path) / "src", None, tmp_path)]
    assert found == ["[no-layers] src: has packages and framework.toml has no [layers] table"]


def test_an_empty_src_and_no_layers_table_is_fine(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    assert b.scan(tmp_path / "src", None, tmp_path) == []


# ---- unparsable
def test_a_file_that_does_not_parse_is_a_finding_with_its_line(tmp_path: Path) -> None:
    root = _repo(tmp_path, **{"src/core/rules.py": "x = 1\ndef broken(:\n"})
    (finding,) = [f for f in _scan(root) if f.startswith("[unparsable]")]
    assert finding.startswith("[unparsable] src/core/rules.py:2: cannot be read, so it was not checked: SyntaxError")


def test_a_file_that_is_not_valid_text_is_a_finding_not_a_crash(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / "src/core/rules.py").write_bytes(b"x = '\xff\xfe'\n# coding: ascii\n")
    assert any(f.startswith("[unparsable] src/core/rules.py") for f in _scan(root))


def test_a_source_too_deeply_nested_to_parse_is_a_finding(tmp_path: Path, monkeypatch) -> None:
    """Whether a given input trips the parser's limit depends on the platform; the rule is what happens when it does."""
    root = _repo(tmp_path)
    real = b.ast.parse

    def parse(source, *args, **kwargs):
        if kwargs.get("filename", "").endswith("rules.py"):
            raise RecursionError("depth")
        return real(source, *args, **kwargs)

    monkeypatch.setattr(b.ast, "parse", parse)
    assert any("RecursionError" in f for f in _scan(root))


def test_a_folder_that_cannot_be_listed_is_a_finding(tmp_path: Path, monkeypatch) -> None:
    root = _repo(tmp_path)
    real_walk = os.walk

    def denying(top, onerror=None, **kwargs):
        if onerror is not None and str(top).endswith("core"):
            onerror(PermissionError(13, "Permission denied", str(Path(top) / "locked")))
        yield from real_walk(top, **kwargs)

    monkeypatch.setattr(b.os, "walk", denying)
    found = _scan(root)
    assert any(f.startswith("[unparsable] src/core/locked: cannot be listed, so it was not checked") for f in found)


# ---- order of the report
def test_findings_are_sorted_by_path_then_line(tmp_path: Path) -> None:
    files = {"src/core/z.py": "import app\n", "src/core/a.py": "x = 1\nimport app\nimport app\n"}
    found = _scan(_repo(tmp_path, **files), _layers(pure=()))
    assert [f.split(" ")[1] for f in found] == ["src/core/a.py:2:", "src/core/a.py:3:", "src/core/z.py:1:"]


# ---- the command line: the workspace at --root
WS_LAYERS = 'order = ["acme_tools_core", "acme_tools"]\npure = ["acme_tools_core"]\n'


def _project(tmp_path: Path, layers: str | None = WS_LAYERS) -> Path:
    """A workspace (``_ws``) with a framework.toml; ``layers`` None leaves the table out."""
    _ws(tmp_path)
    table = f"\n[layers]\n{layers}" if layers is not None else ""
    (tmp_path / "framework.toml").write_text(FRAMEWORK + table, encoding="utf-8")
    return tmp_path


def test_main_exit_codes_and_messages(tmp_path: Path, capsys) -> None:
    root = _project(tmp_path)
    assert b.main(["--root", str(root)]) == 0
    assert "boundaries: clean" in capsys.readouterr().out
    (root / CORE / "src/acme_tools_core/rules.py").write_text("import numpy\n", encoding="utf-8")
    assert b.main(["--root", str(root)]) == 1
    out = capsys.readouterr().out
    assert f"[impure] {CORE}/src/acme_tools_core/rules.py:1:" in out and "boundaries: 1 finding(s)" in out
    assert b.main(["--root", str(tmp_path / "nowhere")]) == 2
    assert "is not a directory" in capsys.readouterr().err


def test_main_with_no_members_and_no_src_says_so_and_passes(tmp_path: Path, capsys) -> None:
    (tmp_path / "framework.toml").write_text(FRAMEWORK, encoding="utf-8")
    assert b.main(["--root", str(tmp_path)]) == 0
    assert "no workspace members, nothing to check" in capsys.readouterr().out


def test_main_on_a_repository_with_a_root_src_is_legacy_src(tmp_path: Path, capsys) -> None:
    (tmp_path / "framework.toml").write_text(FRAMEWORK, encoding="utf-8")
    _repo(tmp_path)  # today's tree: src/core, src/app, no workspace
    assert b.main(["--root", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "[legacy-src] src/app:" in out and "[legacy-src] src/core:" in out


def test_main_without_a_layers_table_but_with_members_is_a_finding(tmp_path: Path, capsys) -> None:
    root = _project(tmp_path, layers=None)
    assert b.main(["--root", str(root)]) == 1
    assert "[no-layers]" in capsys.readouterr().out


def test_main_with_an_unusable_configuration_is_exit_2(tmp_path: Path, capsys) -> None:
    assert b.main(["--root", str(tmp_path)]) == 2  # no framework.toml at all
    assert "cannot run" in capsys.readouterr().err
    _project(tmp_path, layers='order = ["core", "core"]\n')
    assert b.main(["--root", str(tmp_path)]) == 2
    assert "layers.order" in capsys.readouterr().err


def test_verbose_is_the_only_thing_that_makes_it_log(tmp_path: Path) -> None:
    root = _project(tmp_path)
    base = [sys.executable, str(ROOT / "tools" / "boundaries.py"), "--root", str(root)]
    quiet = subprocess.run(base, capture_output=True, text=True, check=False)
    loud = subprocess.run([*base, "-v"], capture_output=True, text=True, check=False)
    assert quiet.returncode == loud.returncode == 0
    assert quiet.stderr == "" and "scanned 4 module(s) in 2 package(s) of apps/acme-tools/src" in loud.stderr


def test_a_non_ascii_path_in_a_finding_does_not_crash_a_narrow_stdout(tmp_path: Path) -> None:
    root = _project(tmp_path)
    (root / CORE / "src" / "acme_tools_core" / ("caf" + chr(0xE9) + ".py")).write_text(
        "import numpy\n", encoding="utf-8"
    )
    ran = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "boundaries.py"), "--root", str(root)],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONIOENCODING": "ascii"},
    )
    assert ran.returncode == 1 and "Traceback" not in ran.stderr and "caf" + chr(92) + "xe9.py" in ran.stdout


def test_the_finding_format_has_the_rule_the_place_and_the_reason() -> None:
    assert str(b.Finding("impure", "src/core/a.py", 3, "bad")) == "[impure] src/core/a.py:3: bad"
    assert str(b.Finding("missing", "src", 0, "bad")) == "[missing] src: bad"


# ---- what is and is not read
def test_a_non_python_file_at_the_top_of_src_is_not_a_package(tmp_path: Path) -> None:
    assert _scan(_repo(tmp_path, **{"src/README.md": "# notes\n", "src/data.json": "{}"})) == []


def test_a_cache_folder_inside_a_package_is_not_read(tmp_path: Path) -> None:
    assert _scan(_repo(tmp_path, **{"src/core/__pycache__/stale.py": "import app\n"})) == []


def test_an_init_file_resolves_relative_imports_against_its_own_package(tmp_path: Path) -> None:
    root = _repo(tmp_path, **{"src/core/__init__.py": "from . import rules\nfrom .tasks import Task\n"})
    assert _scan(root) == []


def test_findings_are_in_line_order_within_a_file_not_in_the_order_the_tree_was_walked(tmp_path: Path) -> None:
    """``ast.walk`` meets a nested import after the top-level ones that follow it."""
    source = "def late():\n    import app\n\n\nimport app\n"
    found = _scan(_repo(tmp_path, **{"src/core/rules.py": source}), _layers(pure=()))
    assert [f.split(":")[1] for f in found] == ["2", "5"]


# ---- what the first review found
def test_a_package_with_a_leading_underscore_is_real_code_and_is_held_to_the_rules(tmp_path: Path) -> None:
    files = {"src/_core/x.py": "import app\n", "src/app/y.py": "x = 1\n"}
    found = _scan(_repo(tmp_path, files), _layers(order=("_core", "app"), pure=()))
    assert found == ["[higher-layer] src/_core/x.py:1: '_core' imports 'app', a higher layer (order: _core, app)"]


def test_a_package_with_a_leading_underscore_that_is_not_listed_is_found(tmp_path: Path) -> None:
    found = _scan(_repo(tmp_path, **{"src/_private/x.py": "x = 1\n"}))
    assert found == ["[unlisted] src/_private: is in neither layers.order nor layers.unlayered of framework.toml"]


def test_a_symlinked_folder_is_reported_not_silently_skipped(tmp_path: Path) -> None:
    root = _repo(tmp_path, **{"hidden/z.py": "import app\n"})
    try:
        (root / "src" / "core" / "linked").symlink_to(root / "hidden", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("this account cannot create a symlink")
    found = _scan(root)
    assert found == ["[unparsable] src/core/linked: is a symlinked folder, which is not followed"]


def test_an_unreadable_src_is_a_finding_not_a_traceback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _repo(tmp_path)
    real = Path.iterdir

    def refuse(self: Path):
        if self.name == "src":
            raise PermissionError(13, "Permission denied", str(self))
        return real(self)

    monkeypatch.setattr(Path, "iterdir", refuse)
    found = _scan(root)
    assert len(found) == 1 and found[0].startswith("[unparsable] src: cannot be listed")


def test_a_src_that_is_a_file_is_a_finding(tmp_path: Path) -> None:
    (tmp_path / "src").write_text("not a folder", encoding="utf-8")
    assert _scan(tmp_path) == ["[unparsable] src: is not a folder, so it was not checked"]


def test_a_module_removed_from_a_later_python_is_still_standard_library(tmp_path: Path) -> None:
    """The floor is 3.11, where ``imp`` and ``distutils`` exist; the answer must not depend on the interpreter."""
    root = _repo(tmp_path, **{"src/core/rules.py": "import imp\nimport distutils\nimport telnetlib\n"})
    assert _scan(root) == []


def test_a_package_of_src_that_shares_a_stdlib_name_is_project_code(tmp_path: Path) -> None:
    files = {"src/queue/__init__.py": "", "src/core/rules.py": "import queue\n"}
    found = _scan(_repo(tmp_path, **files), _layers(order=("core", "app", "queue")))
    assert any(f.startswith("[impure] src/core/rules.py:1:") for f in found)


def test_a_ring_is_reported_along_the_imports_that_exist(tmp_path: Path) -> None:
    """a imports c, c imports b, b imports a: sorted order would print a -> b -> c, naming edges that do not exist."""
    files = {"src/core/a.py": "import core.c\n", "src/core/b.py": "import core.a\n", "src/core/c.py": "import core.b\n"}
    found = [f for f in _scan(_repo(tmp_path, **files)) if f.startswith("[cycle]")]
    assert found == ["[cycle] src/core/a.py: modules import each other in a ring: core.a -> core.c -> core.b -> core.a"]


def test_a_ring_with_a_chord_names_a_real_ring_and_says_how_many_modules_are_in_the_group(tmp_path: Path) -> None:
    files = {
        "src/core/a.py": "import core.b\nimport core.c\n",
        "src/core/b.py": "import core.c\n",
        "src/core/c.py": "import core.a\n",
    }
    found = [f for f in _scan(_repo(tmp_path, **files)) if f.startswith("[cycle]")]
    assert found == [
        "[cycle] src/core/a.py: modules import each other in a ring: core.a -> core.c -> core.a"
        " (one ring of 3 modules that depend on each other)"
    ]


def test_importing_a_module_and_a_name_from_the_package_init_keeps_the_edge_to_the_init(tmp_path: Path) -> None:
    files = {
        "src/core/__init__.py": "from core.a import thing\nname = 1\n",
        "src/core/a.py": "from core import b, name\n",
        "src/core/b.py": "x = 1\n",
    }
    found = [f for f in _scan(_repo(tmp_path, files)) if f.startswith("[cycle]")]
    assert found == ["[cycle] src/core/__init__.py: modules import each other in a ring: core -> core.a -> core"]


# ---- the repository's own workspace
def _own_layers() -> fc.LayersConfig | None:
    return fc.load_framework(ROOT / "framework.toml").layers


def test_the_repositorys_own_workspace_keeps_its_own_layers() -> None:
    """The check the rest of this file proves can fail, run on the members that are actually here."""
    found = [str(f) for f in b.scan_workspace(ROOT, _own_layers())]
    assert found == [], "\n".join(found)


def test_the_repositorys_own_layers_catch_the_lowest_package_importing_the_highest(tmp_path: Path) -> None:
    """Prove the live check can fail on this repository's own ``[layers]``: break its rule in a copy and require it."""
    layers = _own_layers()
    members = {p for m in fc.workspace_members(ROOT) for p in m.packages}
    if layers is None or len(layers.order) < 2 or not {layers.order[0], layers.order[-1]} <= members:
        pytest.skip("no two-package [layers] order over the members to break; members with no table fail already")
    copied = tmp_path / "copy"
    shutil.copytree(
        ROOT,
        copied,
        ignore=shutil.ignore_patterns("__pycache__", ".venv", ".git", "logs", "*.egg-info", "Docs", "tools", "tests"),
    )
    lowest, highest = layers.order[0], layers.order[-1]
    owner = next(m for m in fc.workspace_members(copied) if lowest in m.packages)
    probe = copied / owner.path / "src" / lowest / "_probe.py"
    probe.write_text(f"import {highest}\n", encoding="utf-8")
    found = [str(f) for f in b.scan_workspace(copied, layers)]
    want = f"[higher-layer] {owner.path}/src/{lowest}/_probe.py:1: '{lowest}' imports '{highest}', a higher layer"
    assert any(f.startswith(want) for f in found), found


# ---- the workspace: every member's src/, and the rules between members
APP = "apps/acme-tools"
CORE = "packages/python/acme-tools-core"
EXTRA = "packages/python/acme-tools-extra"
REPORT = "apps/acme-report"


AUTHORS = 'authors = [{ name = "Ada Example", email = "ada@example.org" }]\n'


def _manifest(name: str, deps: tuple[str, ...] = (), authors: str = AUTHORS) -> str:
    listed = ", ".join(f'"{d}"' for d in deps)
    return f'[project]\nname = "{name}"\nversion = "0.1.0"\n{authors}dependencies = [{listed}]\n'


def _ws(tmp_path: Path, members: str = '["apps/*", "packages/python/*"]', **files: str) -> Path:
    """A workspace: the app depends on the core, both clean, plus whatever ``files`` adds or replaces."""
    base = {
        "pyproject.toml": f"[tool.uv.workspace]\nmembers = {members}\n",
        f"{APP}/pyproject.toml": _manifest("acme-tools", ("acme-tools-core",)),
        f"{APP}/src/acme_tools/__init__.py": '"""App."""\n',
        f"{APP}/src/acme_tools/cli.py": "from acme_tools_core.tasks import Task\n",
        f"{CORE}/pyproject.toml": _manifest("acme-tools-core"),
        f"{CORE}/src/acme_tools_core/__init__.py": '"""Core."""\n',
        f"{CORE}/src/acme_tools_core/tasks.py": "import json\n\n\nclass Task:\n    pass\n",
    }
    return _repo(tmp_path, {**base, **{k.replace("__", "/"): v for k, v in files.items()}})


def _ws_layers(order=("acme_tools_core", "acme_tools"), pure=("acme_tools_core",), unlayered=()) -> fc.LayersConfig:
    return fc.LayersConfig(tuple(order), tuple(pure), tuple(unlayered))


def _wscan(root: Path, layers: fc.LayersConfig | None = None) -> list[str]:
    return [str(f) for f in b.scan_workspace(root, layers if layers is not None else _ws_layers())]


def _put(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return root


# ---- no-authors: every app and package manifest names its authors (experiments are exempt)
MISSING = (
    "[project] authors is missing or empty: name the people who wrote this member, each with name and email "
    "(Docs/standards/layout.md)"
)


@pytest.mark.parametrize(
    ("authors", "expected"),
    [
        ("", [f"[no-authors] {APP}/pyproject.toml: {MISSING}"]),
        ("authors = []\n", [f"[no-authors] {APP}/pyproject.toml: {MISSING}"]),
        ('authors = "Ada"\n', [f"[no-authors] {APP}/pyproject.toml: {MISSING}"]),
        (
            'authors = [{ name = "Ada", email = "ada@example.org" }, { name = "Bob" }]\n',
            [f"[no-authors] {APP}/pyproject.toml: [project] authors entry 2 has no email"],
        ),
        (
            'authors = [{ email = "ada@example.org" }]\n',
            [f"[no-authors] {APP}/pyproject.toml: [project] authors entry 1 has no name"],
        ),
        (
            'authors = ["Ada", { name = " ", email = "" }]\n',
            [
                f"[no-authors] {APP}/pyproject.toml: [project] authors entry 1 is not a table (name and email)",
                f"[no-authors] {APP}/pyproject.toml: [project] authors entry 2 has no name or email",
            ],
        ),
    ],
    ids=["absent", "empty", "not-a-list", "no-email", "no-name", "neither"],
)
def test_a_member_manifest_without_whole_authors_is_a_finding(tmp_path: Path, authors: str, expected) -> None:
    root = _put(_ws(tmp_path), f"{APP}/pyproject.toml", _manifest("acme-tools", ("acme-tools-core",), authors))
    assert [f for f in _wscan(root) if f.startswith("[no-authors]")] == expected


def test_a_clean_workspace_has_no_authors_finding(tmp_path: Path) -> None:
    assert _wscan(_ws(tmp_path)) == []


def test_a_member_outside_apps_and_packages_needs_no_authors(tmp_path: Path) -> None:
    """The finding is for an app or a package, as the spec and layout.md say; another folder is not held to it."""
    root = _ws(tmp_path, '["apps/*", "packages/python/*", "libs/*"]')
    _put(root, "libs/x/pyproject.toml", _manifest("x", authors=""))
    _put(root, "libs/x/src/x/__init__.py", "")
    layers = _ws_layers(unlayered=("x",))
    assert [f for f in _wscan(root, layers) if f.startswith("[no-authors]")] == []


def test_an_experiment_needs_no_authors(tmp_path: Path) -> None:
    """The owner, 2026-11-06: "experiments should be exempt"."""
    root = _ws(tmp_path, '["apps/*", "packages/python/*", "experiments/*"]')
    _put(root, "experiments/probe/pyproject.toml", _manifest("probe", authors=""))
    _put(root, "experiments/probe/src/probe/__init__.py", "")
    layers = _ws_layers(unlayered=("probe",))
    assert [f for f in _wscan(root, layers) if f.startswith("[no-authors]")] == []


def test_a_workspace_that_keeps_its_rules_has_no_findings(tmp_path: Path) -> None:
    assert _wscan(_ws(tmp_path)) == []


def test_a_package_importing_an_app_is_app_import(tmp_path: Path) -> None:
    root = _put(_ws(tmp_path), f"{CORE}/src/acme_tools_core/tasks.py", "import json\nimport acme_tools\n")
    found = [f for f in _wscan(root, _ws_layers(pure=())) if f.startswith("[app-import]")]
    assert found == [
        f"[app-import] {CORE}/src/acme_tools_core/tasks.py:2: 'acme_tools_core' imports 'acme_tools', an app; "
        "a package never imports an app"
    ]


def test_an_app_importing_a_package_is_not_app_import(tmp_path: Path) -> None:
    assert not [f for f in _wscan(_ws(tmp_path)) if f.startswith("[app-import]")]  # the control: the allowed direction


def test_an_app_importing_another_app_is_app_to_app(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    _put(root, f"{REPORT}/pyproject.toml", _manifest("acme-report", ("acme-tools",)))
    _put(root, f"{REPORT}/src/acme_report/__init__.py", "")
    _put(root, f"{REPORT}/src/acme_report/main.py", "x = 1\n\n\n\nimport acme_tools\n")
    layers = _ws_layers(order=("acme_tools_core", "acme_tools", "acme_report"))
    found = [f for f in _wscan(root, layers) if f.startswith("[app-to-app]")]
    assert found == [
        f"[app-to-app] {REPORT}/src/acme_report/main.py:5: 'acme_report' imports 'acme_tools', another app; "
        "move what they share into a package"
    ]


def test_two_apps_that_each_import_only_packages_are_not_app_to_app(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    _put(root, f"{REPORT}/pyproject.toml", _manifest("acme-report", ("acme-tools-core",)))
    _put(root, f"{REPORT}/src/acme_report/__init__.py", "import acme_tools_core\n")
    layers = _ws_layers(order=("acme_tools_core", "acme_tools", "acme_report"))
    assert _wscan(root, layers) == []


def test_importing_a_member_the_manifest_does_not_declare_is_undeclared(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    _put(root, f"{EXTRA}/pyproject.toml", _manifest("acme-tools-extra"))
    _put(root, f"{EXTRA}/src/acme_tools_extra/__init__.py", "")
    _put(root, f"{APP}/src/acme_tools/store.py", "import json\nimport acme_tools_extra\n")
    layers = _ws_layers(order=("acme_tools_core", "acme_tools_extra", "acme_tools"))
    found = [f for f in _wscan(root, layers) if f.startswith("[undeclared]")]
    assert found == [
        f"[undeclared] {APP}/src/acme_tools/store.py:2: 'acme_tools' imports 'acme_tools_extra', a member its manifest "
        f"does not depend on: add it to {APP}/pyproject.toml"
    ]


def test_importing_a_declared_member_is_not_undeclared(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    _put(root, f"{EXTRA}/pyproject.toml", _manifest("acme-tools-extra"))
    _put(root, f"{EXTRA}/src/acme_tools_extra/__init__.py", "")
    _put(root, f"{APP}/pyproject.toml", _manifest("acme-tools", ("acme-tools-core", "Acme_Tools.Extra>=0.1")))
    _put(root, f"{APP}/src/acme_tools/store.py", "import acme_tools_extra\n")
    layers = _ws_layers(order=("acme_tools_core", "acme_tools_extra", "acme_tools"))
    assert _wscan(root, layers) == []


def test_a_src_no_member_reaches_is_unreached(tmp_path: Path) -> None:
    root = _put(_ws(tmp_path), "apps/acme-web/backend/src/acme_web/__init__.py", "")
    _put(root, "apps/acme-web/backend/pyproject.toml", _manifest("acme-web"))
    found = [f for f in _wscan(root) if f.startswith("[unreached]")]
    assert found == [
        "[unreached] apps/acme-web/backend/src: a src/ no workspace member reaches: add "
        '"apps/acme-web/backend" to [tool.uv.workspace] members'
    ]


def test_a_nested_src_the_members_name_is_reached(tmp_path: Path) -> None:
    root = _ws(tmp_path, members='["apps/*", "packages/python/*", "apps/acme-web/*"]')
    _put(root, "apps/acme-web/backend/src/acme_web/__init__.py", "")
    _put(root, "apps/acme-web/backend/pyproject.toml", _manifest("acme-web"))
    layers = _ws_layers(order=("acme_tools_core", "acme_tools", "acme_web"))
    assert _wscan(root, layers) == []


def test_a_root_src_with_a_package_is_legacy_src(tmp_path: Path) -> None:
    root = _put(_ws(tmp_path), "src/core/__init__.py", "")
    found = [f for f in _wscan(root) if f.startswith("[legacy-src]")]
    assert found == [
        "[legacy-src] src/core: a root src/ with packages; 0.7.0 moves them into apps/ and packages/ "
        '(Docs/standards/updating.md, "0.7.0: the repository layout")'
    ]


def test_an_empty_root_src_is_not_legacy_src(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    (root / "src").mkdir()
    assert _wscan(root) == []


# ---- legacy-root: a root that builds a project, or a package at the root (the flat shape HogShade had)

ROOT_PROJECT = (
    "[legacy-root] pyproject.toml: the root manifest builds a project; the 0.7.0 root is virtual "
    "(Docs/standards/layout.md): remove [project], moving any package it builds into a member "
    '(Docs/standards/updating.md, "0.7.0: the repository layout")'
)


def _root_package(name: str) -> str:
    return (
        f"[legacy-root] {name}: a package at the root; 0.7.0 moves it into a member "
        '(Docs/standards/updating.md, "0.7.0: the repository layout")'
    )


def _legacy_root(root: Path) -> list[str]:
    return [f for f in _wscan(root) if f.startswith("[legacy-root]")]


FLAT_MANIFEST = (
    '[project]\nname = "acme-tools"\nversion = "0.1.0"\n\n'
    '[build-system]\nrequires = ["setuptools>=68"]\nbuild-backend = "setuptools.build_meta"\n\n'
    '[tool.setuptools.packages.find]\ninclude = ["acme_tools*"]\n'
)
WORKSPACE = '\n[tool.uv.workspace]\nmembers = ["apps/*", "packages/python/*"]\n'


def test_a_root_manifest_with_a_project_table_is_legacy_root(tmp_path: Path) -> None:
    root = _put(_ws(tmp_path), "pyproject.toml", FLAT_MANIFEST + WORKSPACE)
    assert _legacy_root(root) == [ROOT_PROJECT]


def test_a_root_project_with_no_members_is_legacy_root(tmp_path: Path) -> None:
    root = _put(tmp_path, "pyproject.toml", FLAT_MANIFEST)
    assert _legacy_root(root) == [ROOT_PROJECT]


def test_a_project_key_that_is_not_a_table_is_still_legacy_root(tmp_path: Path) -> None:
    root = _put(tmp_path, "pyproject.toml", 'project = "acme-tools"\n')
    assert _legacy_root(root) == [ROOT_PROJECT]


def test_a_package_at_the_root_is_legacy_root(tmp_path: Path) -> None:
    root = _put(_ws(tmp_path), "acme_legacy/__init__.py", "")
    assert _legacy_root(root) == [_root_package("acme_legacy")]


@pytest.mark.parametrize(
    "folder", ["apps", "packages", "experiments", "tools", "tests", "scripts", "launchers", "Docs", "src", ".venv"]
)
def test_the_frameworks_own_folders_and_hidden_ones_are_not_legacy_root(tmp_path: Path, folder: str) -> None:
    root = _put(_ws(tmp_path), f"{folder}/__init__.py", "")
    assert _legacy_root(root) == []


def test_a_root_folder_with_no_init_is_not_legacy_root(tmp_path: Path) -> None:
    root = _put(_ws(tmp_path), "content/shader.py", "")
    assert _legacy_root(root) == []


def test_an_init_that_is_a_folder_is_no_package(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    (root / "acme_data" / "__init__.py").mkdir(parents=True)
    assert _legacy_root(root) == []


@pytest.mark.parametrize("name", ["-x", "--output=x", "acme_café"])
def test_a_package_with_a_hostile_name_is_reported_by_its_name(tmp_path: Path, name: str, capsys) -> None:
    root = _put(_ws(tmp_path), f"{name}/__init__.py", "")
    _put(root, "framework.toml", FRAMEWORK)
    assert _legacy_root(root) == [_root_package(name)]
    assert b.main(["--root", str(root)]) == 1
    assert "[legacy-root]" in capsys.readouterr().out


@pytest.mark.parametrize("folder", ["Tests", "TOOLS", "docs"])
def test_the_frameworks_folders_in_another_case_are_not_legacy_root(tmp_path: Path, folder: str) -> None:
    root = _put(_ws(tmp_path), f"{folder}/__init__.py", "")
    assert _legacy_root(root) == []  # "Tests" is "tests" on a filesystem that ignores case; "docs" is "Docs"


def test_a_root_that_cannot_be_listed_is_a_finding(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _ws(tmp_path)
    real = Path.iterdir

    def refuse(self: Path):
        if self == root:
            raise PermissionError(13, "Permission denied", str(self))
        return real(self)

    monkeypatch.setattr(Path, "iterdir", refuse)
    found = [str(f) for f in b._legacy_root(root)]
    assert len(found) == 1, found
    assert found[0].startswith(
        "[unparsable] .: the root cannot be listed, so no package at the root was looked for: [Errno 13]"
    )


def test_a_root_folder_that_cannot_be_read_is_a_finding_not_a_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    root = _put(_ws(tmp_path), "locked/__init__.py", "")
    _put(root, "framework.toml", FRAMEWORK)
    real = Path.stat

    def refuse(self: Path, **kwargs):
        if self == root / "locked" / "__init__.py":
            raise PermissionError(13, "Access is denied", str(self))
        return real(self, **kwargs)

    monkeypatch.setattr(Path, "stat", refuse)
    found = [str(f) for f in b._legacy_root(root)]
    assert len(found) == 1 and found[0].startswith("[unparsable] locked: cannot be read, so it was not checked"), found
    assert b.main(["--root", str(root)]) == 1
    assert "[unparsable] locked" in capsys.readouterr().out


def _loop(link: Path) -> None:
    """``link`` made a symlink to itself, or the test skipped where this account cannot make one."""
    try:
        link.symlink_to(link, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("this account cannot create a symlink")


def test_a_root_folder_that_is_a_symlink_loop_is_a_finding(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    _loop(root / "acme_loop")  # is_dir() says False for a loop and raises nothing: the check must not pass on it
    found = [str(f) for f in b._legacy_root(root)]
    assert len(found) == 1 and found[0].startswith("[unparsable] acme_loop: cannot be read"), found


def test_an_init_that_is_a_symlink_loop_is_a_finding(tmp_path: Path) -> None:
    root = _put(_ws(tmp_path), "acme_tools_flat/core.py", "")
    _loop(root / "acme_tools_flat" / "__init__.py")
    found = [str(f) for f in b._legacy_root(root)]
    assert len(found) == 1 and found[0].startswith("[unparsable] acme_tools_flat: cannot be read"), found


def test_a_dangling_symlink_at_the_root_is_no_package(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    try:
        (root / "gone").symlink_to(root / "nowhere", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("this account cannot create a symlink")
    assert _legacy_root(root) == []


# ---- class A, swept (the scan of #86 to #139, item 6): every read the tool makes tells missing from unreadable
def _refuse_stat(monkeypatch: pytest.MonkeyPatch, target: Path) -> None:
    """``Path.stat`` of ``target`` refused, as an ACL that denies it would; every other path reads as it is."""
    real = Path.stat

    def stat(self: Path, *args: object, **kwargs: object) -> os.stat_result:
        if self == target:
            raise PermissionError(13, "Permission denied", str(self))
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", stat)


def _refuse_listing(monkeypatch: pytest.MonkeyPatch, target: Path) -> None:
    """``os.scandir`` of ``target`` refused, so ``os.walk`` cannot list it; every other folder lists as it is."""
    real = os.scandir

    def scandir(path: object = ".") -> object:
        if Path(os.fspath(path)) == target:
            raise PermissionError(13, "Permission denied", os.fspath(path))
        return real(path)

    monkeypatch.setattr(os, "scandir", scandir)


def _unparsable(found: list[str], where: str) -> list[str]:
    return [f for f in found if f.startswith(f"[unparsable] {where}:")]


@pytest.mark.parametrize("refused", [f"{CORE}/src/acme_hidden", f"{CORE}/src"])
def test_a_member_src_or_entry_that_cannot_be_read_stops_the_run(
    tmp_path: Path, monkeypatch, capsys, refused: str
) -> None:
    """The workspace's own reading (``framework_config``) meets it first and refuses to run: exit 2, never a pass."""
    root = _put(_put(_ws(tmp_path), f"{CORE}/src/acme_hidden/x.py", ""), "framework.toml", FRAMEWORK)
    _refuse_stat(monkeypatch, root / refused)
    assert b.main(["--root", str(root)]) == 2
    assert "Permission denied" in capsys.readouterr().err


def test_a_member_src_entry_that_is_a_symlink_loop_is_a_finding(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    _loop(root / CORE / "src" / "acme_loop")
    assert _unparsable(_wscan(root), f"{CORE}/src/acme_loop"), _wscan(root)


def test_a_symlink_loop_inside_a_package_is_a_finding(tmp_path: Path) -> None:
    """``os.walk`` lists a looping link among the files, not the folders, so the folder rule alone misses it."""
    root = _ws(tmp_path)
    _loop(root / CORE / "src" / "acme_tools_core" / "deep")
    assert _unparsable(_wscan(root), f"{CORE}/src/acme_tools_core/deep"), _wscan(root)


def test_a_root_src_that_cannot_be_read_is_a_finding(tmp_path: Path, monkeypatch) -> None:
    root = _put(_ws(tmp_path), "src/acme_old/__init__.py", "")
    _refuse_stat(monkeypatch, root / "src")
    assert _unparsable(_wscan(root), "src"), _wscan(root)


def test_scan_of_a_src_that_cannot_be_read_is_a_finding(tmp_path: Path, monkeypatch) -> None:
    root = _repo(tmp_path)
    _refuse_stat(monkeypatch, root / "src")
    assert _unparsable(_scan(root), "src"), _scan(root)


def test_scan_of_a_src_that_is_a_symlink_loop_is_a_finding(tmp_path: Path) -> None:
    _loop(tmp_path / "src")
    assert _unparsable(_scan(tmp_path), "src"), _scan(tmp_path)


def test_a_root_manifest_that_cannot_be_read_cannot_run(tmp_path: Path, monkeypatch) -> None:
    root = _put(_ws(tmp_path), "pyproject.toml", FLAT_MANIFEST + WORKSPACE)
    _refuse_stat(monkeypatch, root / "pyproject.toml")
    with pytest.raises(fc.ConfigError, match="pyproject.toml"):
        b._legacy_root(root)


def test_a_folder_under_apps_that_cannot_be_listed_is_a_finding(tmp_path: Path, monkeypatch) -> None:
    root = _put(_ws(tmp_path), "apps/acme-sealed/src/acme_sealed/__init__.py", "")
    _refuse_listing(monkeypatch, root / "apps" / "acme-sealed")
    assert _unparsable(_wscan(root), "apps/acme-sealed"), _wscan(root)


def test_a_folder_whose_kind_cannot_be_read_is_one_finding_not_a_crash(tmp_path: Path, monkeypatch) -> None:
    """Whether an entry is a link is read with ``lstat``, which a folder that can be listed but not searched refuses on
    POSIX: a finding, and not entered (Copilot on #144; ledger P-16)."""
    root = _put(_ws(tmp_path), "apps/acme-sealed/src/acme_sealed/__init__.py", "")
    target = root / "apps" / "acme-sealed"
    real = Path.lstat

    def lstat(self: Path) -> os.stat_result:
        if self == target:
            raise PermissionError(13, "Permission denied", str(self))
        return real(self)

    monkeypatch.setattr(Path, "lstat", lstat)
    findings: list[b.Finding] = []
    list(b._tree(root / "apps", root, findings))
    assert [(f.rule, f.path) for f in findings] == [("unparsable", "apps/acme-sealed")], findings
    assert findings[0].detail.startswith("cannot be read, so it was not checked: [Errno 13]"), findings


def test_a_symlink_loop_under_packages_is_a_finding(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    _loop(root / "packages" / "python" / "acme-loop")
    assert _unparsable(_wscan(root), "packages/python/acme-loop"), _wscan(root)


def test_a_loop_two_walks_meet_is_one_finding(tmp_path: Path) -> None:
    """The member's own walk and the search for unreached src/ folders both pass a loop inside a member: one finding."""
    root = _ws(tmp_path)
    _loop(root / CORE / "src" / "acme_tools_core" / "deep")
    assert len(_unparsable(_wscan(root), f"{CORE}/src/acme_tools_core/deep")) == 1, _wscan(root)


def test_a_linked_folder_under_apps_is_passed_over_by_the_search_for_src(tmp_path: Path) -> None:
    """The search for unreached src/ folders looks for folders, so a link to one that resolves is not a finding."""
    root = _put(_ws(tmp_path), "elsewhere/notes.txt", "x\n")
    try:
        (root / "apps" / "shared").symlink_to(root / "elsewhere", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("this account cannot create a symlink")
    assert _wscan(root) == []


def test_node_modules_and_a_virtual_environment_are_not_searched(tmp_path: Path) -> None:
    """Installed packages are not the repository's code: what cannot be read inside them is not a finding, and a
    src/ with Python inside them is not an unreached member (the deliberate review of the class A sweep)."""
    root = _put(_ws(tmp_path), "apps/web/node_modules/pkg/src/x.py", "")
    _put(root, "apps/tool/venv/pyvenv.cfg", "home = x\n")
    _put(root, "apps/tool/venv/lib/site-packages/dep/src/y.py", "")
    _loop(root / "apps" / "web" / "node_modules" / "loop")
    assert _wscan(root) == []


def test_scan_reports_an_entry_it_cannot_read(tmp_path: Path, monkeypatch) -> None:
    root = _repo(tmp_path)
    entry = next(p for p in sorted((root / "src").iterdir()) if p.is_dir())
    _refuse_stat(monkeypatch, entry)
    assert _unparsable(_scan(root), entry.relative_to(root).as_posix()), _scan(root)


def test_a_junction_loop_inside_a_package_is_one_finding_not_a_walk_round_it(tmp_path: Path) -> None:
    if sys.platform != "win32" or not hasattr(Path, "is_junction"):
        pytest.skip("a junction is a Windows folder link, recognised from Python 3.12")
    import _winapi  # noqa: PLC0415 - Windows only

    root = _ws(tmp_path)
    package = root / CORE / "src" / "acme_tools_core"
    _winapi.CreateJunction(str(package), str(package / "j"))
    found = _wscan(root)
    assert _unparsable(found, f"{CORE}/src/acme_tools_core/j") and not any("/j/j" in f for f in found), found


def test_the_sweep_leaves_a_clean_workspace_and_a_dangling_link_clean(tmp_path: Path) -> None:
    """The negative control: nothing above fires on a workspace it can read, and a dangling link is nothing there."""
    root = _ws(tmp_path)
    assert _wscan(root) == []
    try:
        (root / CORE / "src" / "acme_tools_core" / "gone").symlink_to(root / "nowhere", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("this account cannot create a symlink")
    assert _wscan(root) == []


def test_a_root_manifest_that_is_not_utf8_cannot_run(tmp_path: Path, capsys) -> None:
    _put(tmp_path, "framework.toml", FRAMEWORK)
    (tmp_path / "pyproject.toml").write_bytes(b'[project]\nname = "\xff"\n')
    assert b.main(["--root", str(tmp_path)]) == 2
    assert "cannot run" in capsys.readouterr().err


def test_legacy_root_logs_what_it_read_and_skipped(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    root = _put(_put(_ws(tmp_path), "tests/__init__.py", ""), "acme_legacy/__init__.py", "")
    with caplog.at_level(logging.INFO, logger=b._MODULE_NAME):
        b._legacy_root(root)
    assert "root manifest: virtual" in caplog.text
    assert "skipped tests: the framework's own" in caplog.text
    assert "acme_legacy: a package at the root" in caplog.text


def test_main_fails_the_flat_shape_and_passes_it_once_moved(tmp_path: Path, capsys) -> None:
    flat = tmp_path / "flat"
    _put(flat, "framework.toml", FRAMEWORK)
    _put(flat, "pyproject.toml", FLAT_MANIFEST)
    _put(flat, "acme_tools/__init__.py", '"""Acme tools."""\n')
    _put(flat, "acme_tools/cli.py", "import json\n")
    assert b.main(["--root", str(flat)]) == 1
    out = capsys.readouterr().out
    assert ROOT_PROJECT in out and _root_package("acme_tools") in out

    moved = tmp_path / "moved"  # the layout section's steps: the package in a member, a virtual root
    _put(moved, "framework.toml", FRAMEWORK + '\n[layers]\norder = ["acme_tools"]\n')
    _put(moved, "pyproject.toml", '[tool.uv.workspace]\nmembers = ["packages/python/*"]\n')
    _put(moved, "packages/python/acme-tools/pyproject.toml", _manifest("acme-tools"))
    _put(moved, "packages/python/acme-tools/src/acme_tools/__init__.py", '"""Acme tools."""\n')
    _put(moved, "packages/python/acme-tools/src/acme_tools/cli.py", "import json\n")
    assert b.main(["--root", str(moved)]) == 0, capsys.readouterr().out


def test_todays_rules_hold_across_members(tmp_path: Path) -> None:
    root = _put(_ws(tmp_path), f"{CORE}/src/acme_tools_core/rules.py", "import numpy\n")
    found = _wscan(root, _ws_layers())
    assert found == [
        f"[impure] {CORE}/src/acme_tools_core/rules.py:1: pure layer 'acme_tools_core' imports 'numpy', "
        "which is not the standard library"
    ]
    assert [f for f in _wscan(_ws(tmp_path / "b"), _ws_layers(order=("acme_tools",))) if f.startswith("[unlisted]")]


def test_a_workspace_with_packages_and_no_layers_is_no_layers(tmp_path: Path) -> None:
    found = [str(f) for f in b.scan_workspace(_ws(tmp_path), None)]
    assert found == ["[no-layers] framework.toml: the workspace's members have packages and there is no [layers] table"]


def test_two_members_with_the_same_package_is_duplicate(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    _put(root, "packages/python/other/pyproject.toml", _manifest("other"))
    _put(root, "packages/python/other/src/acme_tools_core/__init__.py", "")
    found = [f for f in _wscan(root) if f.startswith("[duplicate]")]
    assert found == [
        "[duplicate] packages/python/other/src/acme_tools_core: 'acme_tools_core' is also a package of "
        f"{CORE}; one install would hide the other"
    ]


def test_a_namespace_package_and_a_top_level_module_are_held_to_the_member_rules(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    (root / CORE / "src/acme_tools_core/__init__.py").unlink()  # a namespace package now
    _put(root, f"{CORE}/src/acme_tools_core/tasks.py", "import acme_tools\n")
    found = _wscan(root, _ws_layers(pure=()))
    assert any(f.startswith("[app-import]") for f in found), found
    assert any(f.startswith("[undeclared]") for f in found), found


def test_an_app_importing_an_experiment_is_experiment_import(tmp_path: Path) -> None:
    root = _ws(tmp_path, members='["apps/*", "packages/python/*", "experiments/*"]')
    _put(root, "experiments/web/pyproject.toml", _manifest("web"))
    _put(root, "experiments/web/src/web/__init__.py", "")
    _put(root, f"{APP}/pyproject.toml", _manifest("acme-tools", ("acme-tools-core", "web")))
    _put(root, f"{APP}/src/acme_tools/web_bits.py", "import web\n")
    layers = _ws_layers(order=("acme_tools_core", "web", "acme_tools"))
    found = [f for f in _wscan(root, layers) if f.startswith("[experiment-import]")]
    assert found == [
        f"[experiment-import] {APP}/src/acme_tools/web_bits.py:1: 'acme_tools' imports 'web', an experiment; "
        "nothing under apps/ or packages/ depends on one"
    ]


def test_a_member_outside_the_known_roots_gets_no_app_rules(tmp_path: Path) -> None:
    root = _ws(tmp_path, members='["apps/*", "packages/python/*", "libs/*"]')
    _put(root, "libs/l/pyproject.toml", _manifest("l"))
    _put(root, "libs/l/src/l/__init__.py", "")
    _put(root, f"{APP}/pyproject.toml", _manifest("acme-tools", ("acme-tools-core", "l")))
    _put(root, f"{APP}/src/acme_tools/uses_l.py", "import l\n")
    layers = _ws_layers(order=("acme_tools_core", "l", "acme_tools"))
    assert not [f for f in _wscan(root, layers) if f.startswith(("[app-to-app]", "[app-import]"))]


def test_unreached_skips_dot_folders_and_folders_inside_a_member(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    _put(root, f"{APP}/.venv/Lib/site-packages/foo/src/foo/__init__.py", "")
    _put(root, f"{APP}/src/acme_tools/src/__init__.py", "")  # a subpackage called src, inside a member
    assert not [f for f in _wscan(root) if f.startswith("[unreached]")]


def test_main_on_a_malformed_workspace_is_exit_2(tmp_path: Path, capsys) -> None:
    (tmp_path / "framework.toml").write_text(FRAMEWORK, encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text('[tool.uv.workspace]\nmembers = "apps/*"\n', encoding="utf-8")
    assert b.main(["--root", str(tmp_path)]) == 2
    assert "cannot run" in capsys.readouterr().err


def test_undeclared_holds_for_every_package_of_a_member_with_two(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    _put(root, f"{EXTRA}/pyproject.toml", _manifest("acme-tools-extra"))
    _put(root, f"{EXTRA}/src/acme_tools_extra/__init__.py", "")
    _put(root, f"{EXTRA}/src/acme_tools_more/__init__.py", "")  # a second package of the same member
    _put(root, f"{APP}/src/acme_tools/uses.py", "import acme_tools_extra\nimport acme_tools_more\n")
    layers = _ws_layers(order=("acme_tools_core", "acme_tools_extra", "acme_tools_more", "acme_tools"))
    found = [f.split(": ")[0] for f in _wscan(root, layers) if f.startswith("[undeclared]")]
    assert found == [f"[undeclared] {APP}/src/acme_tools/uses.py:1", f"[undeclared] {APP}/src/acme_tools/uses.py:2"]


def test_a_root_src_that_cannot_be_listed_is_a_finding(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _put(_ws(tmp_path), "src/core/__init__.py", "")
    real = Path.iterdir

    def refuse(self: Path):
        if self == root / "src":
            raise PermissionError("denied")
        return real(self)

    monkeypatch.setattr(Path, "iterdir", refuse)
    found = [f for f in _wscan(root) if f.startswith("[unparsable] src")]
    assert found and "cannot be listed" in found[0], found


def test_a_nested_member_left_out_of_the_list_is_unreached_even_under_a_listed_one(tmp_path: Path) -> None:
    root = _ws(tmp_path, members='["apps/*", "packages/python/*"]')
    _put(root, "apps/acme-tools/backend/src/acme_backend/__init__.py", "")  # a part under the listed app, not listed
    found = [f for f in _wscan(root) if f.startswith("[unreached]")]
    assert found == [
        "[unreached] apps/acme-tools/backend/src: a src/ no workspace member reaches: add "
        '"apps/acme-tools/backend" to [tool.uv.workspace] members'
    ]


def test_members_with_no_src_still_hold_layers_order_to_what_exists(tmp_path: Path) -> None:
    root = _repo(
        tmp_path,
        {
            "pyproject.toml": '[tool.uv.workspace]\nmembers = ["apps/*"]\n',
            f"{APP}/pyproject.toml": _manifest("acme-tools"),
        },
    )
    found = [f for f in _wscan(root) if f.startswith("[missing]")]
    assert len(found) == 2 and all("not a package of any workspace member" in f for f in found), found


def test_a_v_run_logs_with_the_tools_prefix(tmp_path: Path) -> None:
    """Every tool logs through log_setup: the time, the level and the module, at INFO with -v (logging in tiers)."""
    from test_log_setup import PROBE_LINE, tool_log_line

    line, level = tool_log_line(
        "boundaries", [a.replace("{empty}", str(tmp_path)) for a in ["-v", "--root", "{empty}"]]
    )
    assert PROBE_LINE.fullmatch(line), line
    assert level == 20
