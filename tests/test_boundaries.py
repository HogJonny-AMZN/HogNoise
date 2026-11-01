"""
Framework: tests for tools/boundaries.py (the layer rules of src/, read from the source).
Package: tests/test_boundaries

Every rule has a fixture that breaks exactly that rule and requires the finding, with its file and line, and the fixture
unbroken passes. The last test holds the repository's own ``src/`` to its own ``[layers]``.
"""

from __future__ import annotations

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


# ---- the command line
def _project(tmp_path: Path, layers: str = 'order = ["core", "app"]\npure = ["core"]\n', **files: str) -> Path:
    (tmp_path / "framework.toml").write_text(FRAMEWORK + f"\n[layers]\n{layers}", encoding="utf-8")
    return _repo(tmp_path, **files)


def test_main_exit_codes_and_messages(tmp_path: Path, capsys) -> None:
    root = _project(tmp_path)
    assert b.main(["--root", str(root)]) == 0
    assert "boundaries: clean" in capsys.readouterr().out
    (root / "src/core/rules.py").write_text("import numpy\n", encoding="utf-8")
    assert b.main(["--root", str(root)]) == 1
    out = capsys.readouterr().out
    assert "[impure] src/core/rules.py:1:" in out and "boundaries: 1 finding(s)" in out
    assert b.main(["--root", str(tmp_path / "nowhere")]) == 2
    assert "is not a directory" in capsys.readouterr().err


def test_main_with_no_src_says_so_and_passes(tmp_path: Path, capsys) -> None:
    (tmp_path / "framework.toml").write_text(FRAMEWORK, encoding="utf-8")
    assert b.main(["--root", str(tmp_path)]) == 0
    assert "no src/, nothing to check" in capsys.readouterr().out


def test_main_without_a_layers_table_but_with_packages_is_a_finding(tmp_path: Path, capsys) -> None:
    (tmp_path / "framework.toml").write_text(FRAMEWORK, encoding="utf-8")
    _repo(tmp_path)
    assert b.main(["--root", str(tmp_path)]) == 1
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
    assert quiet.stderr == "" and "scanned 5 module(s) in 2 package(s) of src" in loud.stderr


def test_a_non_ascii_path_in_a_finding_does_not_crash_a_narrow_stdout(tmp_path: Path) -> None:
    root = _project(tmp_path, **{"src/core/caf" + chr(0xE9) + ".py": "import numpy\n"})
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


# ---- the repository's own src/
def _own_layers() -> fc.LayersConfig | None:
    return fc.load_framework(ROOT / "framework.toml").layers


def test_the_repositorys_own_src_keeps_its_own_layers() -> None:
    """The check the rest of this file proves can fail, run on the code that is actually here."""
    found = [str(f) for f in b.scan(ROOT / "src", _own_layers(), ROOT)]
    assert found == [], "\n".join(found)


def test_the_repositorys_own_layers_catch_the_lowest_package_importing_the_highest(tmp_path: Path) -> None:
    """Prove the live check can fail on this repository's own ``[layers]``: break its rule in a copy and require it."""
    layers = _own_layers()
    if layers is None or len(layers.order) < 2 or not (ROOT / "src" / layers.order[0]).is_dir():
        pytest.skip("no two-package [layers] order to break; packages in src/ with no table already fail (no-layers)")
    shutil.copytree(ROOT / "src", tmp_path / "src", ignore=shutil.ignore_patterns("__pycache__"))
    lowest, highest = layers.order[0], layers.order[-1]
    (tmp_path / "src" / lowest / "_probe.py").write_text(f"import {highest}\n", encoding="utf-8")
    found = [str(f) for f in b.scan(tmp_path / "src", layers, tmp_path)]
    want = f"[higher-layer] src/{lowest}/_probe.py:1: '{lowest}' imports '{highest}', a higher layer"
    assert any(f.startswith(want) for f in found), found
