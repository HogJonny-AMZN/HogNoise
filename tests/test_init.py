"""
Framework: tests for tools/init.py (the initialiser: `init new`) and for the payload manifest.
Package: tests/test_init
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import framework_config as fc  # noqa: E402
import init as ini  # noqa: E402

# The checks that read the template's own payload do not apply in a repository made from it (init writes project.json).
IN_A_MADE_REPOSITORY = (ROOT / "project.json").exists()
only_in_the_template = pytest.mark.skipif(
    IN_A_MADE_REPOSITORY, reason="runs only against the template's payload, not in a repository made from it"
)

ANSWERS = {
    "name": "Example Project",
    "slug": "example-project",
    "owner": {"name": "Ada Example", "email": "ada@example.org"},
    "default_branch": "main",
    "signoff": True,
    "hygiene": [],
}

MANIFEST = """
[[rule]]
pattern = "tools/*.py"
module = "core"
kind = "managed"

[[rule]]
pattern = "AGENTS.md"
module = "core"
kind = "parametrised"

[[rule]]
pattern = "pyproject.toml"
module = "python-uv"
kind = "project-owned"

[[rule]]
pattern = "README.md"
module = "core"
kind = "project-owned"

[[rule]]
pattern = "framework.toml"
module = "core"
kind = "project-owned"

[[rule]]
pattern = "framework-manifest.toml"
module = "core"
kind = "managed"

[[rule]]
pattern = "ux/*"
module = "ux"
kind = "managed"

[[rule]]
pattern = "lanes/*"
module = "lanes"
kind = "managed"
"""


def _framework_text(**states: str) -> str:
    modules = {name: "planned" for name in fc.MODULES}
    modules.update({"core": "on", "python-uv": "on", "lanes": "off"})
    modules.update(states)
    data = {
        "framework": {"template_version": "0.1.0"},
        "modules": modules,
        "harnesses": {"enabled": []},
        "checks": {"handoff_max_lines": 150},
        "overrides": [],
    }
    return fc.dump_framework(fc.parse_framework(data))


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


@pytest.fixture
def source(tmp_path: Path) -> Path:
    """A small synthetic payload: one file of every class and module state."""
    src = tmp_path / "payload"
    _write(src, "framework-manifest.toml", MANIFEST)
    _write(src, "framework.toml", _framework_text())
    _write(src, "tools/one.py", "print('managed one')\n")
    _write(src, "tools/two.py", "print('managed two')\n")
    _write(src, "AGENTS.md", "# {{name}}\n\nBy {{owner_name}} <{{owner_email}}>; slug your-project-name.\n")
    _write(src, "pyproject.toml", '[project]\nname = "your-project-name"\n')
    _write(src, "README.md", "# {{name}}\n\nBranch {{default_branch}}, slug {{slug}}.\n")
    _write(src, "ux/mock.md", "planned module file\n")
    _write(src, "lanes/lane.md", "off module file\n")
    return src


@pytest.fixture
def answers(tmp_path: Path) -> Path:
    path = tmp_path / "answers.json"
    path.write_text(json.dumps(ANSWERS), encoding="utf-8")
    return path


def _snapshot(root: Path, skip_logs: bool = True) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    if not root.exists():
        return result
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if path.is_file() and not (skip_logs and rel.startswith("logs/")):
            result[rel] = path.read_bytes()
    return result


def _run(source: Path, target: Path, answers: Path, *extra: str, runner=None) -> int:
    argv = ["new", "--answers", str(answers), "--target", str(target), "--no-sync", "--no-checks", *extra]
    return ini.main(argv, source=source, runner=runner)


class _Runner:
    """A fake subprocess runner: records its calls and answers by a substring of the command."""

    def __init__(self, codes: dict[str, int] | None = None, output: str = "") -> None:
        self.codes = codes or {}
        self.output = output
        self.calls: list[tuple[list[str], Path]] = []

    def __call__(self, argv: list[str], cwd: Path) -> ini.RunResult:
        self.calls.append((argv, cwd))
        for key, code in self.codes.items():
            if key in " ".join(argv):
                return ini.RunResult(code, self.output)
        return ini.RunResult(0, "")


def _last_record(target: Path) -> str:
    return sorted((target / "logs").glob("init-*.log"))[-1].read_text(encoding="utf-8")


# --------------------------------------------------------------------------- the manifest
@only_in_the_template
def test_the_real_payload_manifest_has_no_unregistered_file_and_no_dead_rule() -> None:
    assert ini.check_manifest(ROOT) == []


def test_check_manifest_finds_an_unregistered_file_and_a_dead_rule(source: Path) -> None:
    _write(source, "stray.txt", "nobody registered me\n")
    problems = ini.check_manifest(source)
    assert any("stray.txt" in p and "no rule" in p for p in problems)
    (source / "tools" / "one.py").unlink()
    (source / "tools" / "two.py").unlink()
    assert any("tools/*.py" in p and "matches no file" in p for p in ini.check_manifest(source))


def test_the_manifest_is_validated(tmp_path: Path) -> None:
    head = '[[rule]]\npattern = "x"\nmodule = "core"\nkind = "managed"\n'
    for bad in (
        '[[rule]]\npattern = "x"\nmodule = "core"\nkind = "weird"\n',
        '[[rule]]\npattern = "x"\nmodule = "nope"\nkind = "managed"\n',
        '[[rule]]\nmodule = "core"\nkind = "managed"\n',
        '[[rule]]\npattern = "/abs"\nmodule = "core"\nkind = "managed"\n',
        '[[rule]]\npattern = "../up"\nmodule = "core"\nkind = "managed"\n',
        '[[rule]]\npattern = "a\\\\b"\nmodule = "core"\nkind = "managed"\n',
        '[[rule]]\npattern = ""\nmodule = "core"\nkind = "managed"\n',
        head + "extra = 1\n",
        'stray = 1\n[[rule]]\npattern = "x"\nmodule = "core"\nkind = "managed"\n',
        "not = [valid",
    ):
        path = tmp_path / "m.toml"
        path.write_text(bad, encoding="utf-8")
        with pytest.raises(ini.ManifestError):
            ini.load_manifest(path)
    with pytest.raises(ini.ManifestError):
        ini.load_manifest(tmp_path / "missing.toml")


def test_junk_is_skipped_at_the_root_only_and_caches_anywhere(source: Path) -> None:
    for rel in ("logs/x.log", ".venv/lib.py", ".git/config", "tools/__pycache__/a.pyc", "tools/.ruff_cache/x"):
        _write(source, rel, "junk\n")
    _write(source, "tools/logs/real.py", "a payload directory that happens to be called logs\n")
    found = ini.discover(source)
    assert "tools/logs/real.py" in found
    skipped = ("logs/", ".venv/", ".git/")
    assert not any(p.startswith(skipped) or "__pycache__" in p or ".ruff_cache" in p for p in found)


# --------------------------------------------------------------------------- init new
def test_new_writes_each_class_and_skips_modules_that_are_not_on(source: Path, answers: Path, tmp_path: Path) -> None:
    target = tmp_path / "proj"
    assert _run(source, target, answers) == 0
    snap = _snapshot(target)
    assert set(snap) == {
        "tools/one.py",
        "tools/two.py",
        "AGENTS.md",
        "pyproject.toml",
        "README.md",
        "framework.toml",
        "framework-manifest.toml",
        "project.json",
        "framework.lock",
    }
    assert snap["tools/one.py"] == b"print('managed one')\n"  # managed: verbatim
    assert snap["AGENTS.md"] == b"# Example Project\n\nBy Ada Example <ada@example.org>; slug example-project.\n"
    assert b'name = "example-project"' in snap["pyproject.toml"]  # the runnable token in a seed
    assert snap["README.md"] == b"# Example Project\n\nBranch main, slug example-project.\n"
    assert fc.load_project(target / "project.json").slug == "example-project"
    assert fc.load_framework(target / "framework.toml").modules["python-uv"] == "on"


def test_the_lock_records_the_version_and_a_line_ending_independent_hash(
    source: Path, answers: Path, tmp_path: Path
) -> None:
    (source / "tools" / "one.py").write_bytes(b"print('a')\r\nprint('b')\r\n")  # a CRLF working copy
    target = tmp_path / "proj"
    assert _run(source, target, answers) == 0
    lock = json.loads((target / "framework.lock").read_text(encoding="utf-8"))
    assert lock["template_version"] == "0.1.0"
    assert lock["files"]["tools/one.py"] == hashlib.sha256(b"print('a')\nprint('b')\n").hexdigest()
    assert (target / "tools" / "one.py").read_bytes() == b"print('a')\nprint('b')\n"  # written with LF
    assert set(lock["files"]) == {"tools/one.py", "tools/two.py", "AGENTS.md", "framework-manifest.toml"}


def test_a_crlf_checkout_of_the_target_is_not_a_difference(source: Path, answers: Path, tmp_path: Path) -> None:
    target = tmp_path / "proj"
    assert _run(source, target, answers) == 0
    path = target / "tools" / "one.py"
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))  # autocrlf on a Windows checkout
    assert _run(source, target, answers) == 0


def test_a_second_run_changes_no_tracked_file(source: Path, answers: Path, tmp_path: Path) -> None:
    target = tmp_path / "proj"
    assert _run(source, target, answers) == 0
    first = _snapshot(target)
    assert _run(source, target, answers) == 0
    assert _snapshot(target) == first
    assert len(list((target / "logs").glob("init-*.log"))) == 2  # the record is excluded from the assertion


def test_seeds_the_project_edits_do_not_make_later_runs_refuse(source: Path, answers: Path, tmp_path: Path) -> None:
    target = tmp_path / "proj"
    assert _run(source, target, answers) == 0
    (target / "pyproject.toml").write_text('[project]\nname = "example-project"\ndependencies = ["pytest-cov"]\n')
    (target / "README.md").write_text("rewritten\n")
    assert _run(source, target, answers) == 0  # what `uv add` does on day one
    assert "pytest-cov" in (target / "pyproject.toml").read_text()


def test_dry_run_writes_nothing_and_prints_the_plan(source: Path, answers: Path, tmp_path: Path, capsys) -> None:
    target = tmp_path / "proj"
    assert _run(source, target, answers, "--dry-run") == 0
    assert not target.exists()
    out = capsys.readouterr().out
    assert "tools/one.py" in out and "create" in out
    assert "ux/mock.md" in out and "module ux is planned" in out  # a skipped file is listed with the reason
    assert "dry run" in out.lower()


def test_dry_run_over_a_finished_target_writes_no_record_either(source: Path, answers: Path, tmp_path: Path) -> None:
    target = tmp_path / "proj"
    assert _run(source, target, answers) == 0
    before = _snapshot(target, skip_logs=False)
    assert _run(source, target, answers, "--dry-run") == 0
    assert _snapshot(target, skip_logs=False) == before


def test_a_real_run_leaves_a_record_saying_what_it_decided(source: Path, answers: Path, tmp_path: Path) -> None:
    target = tmp_path / "proj"
    assert _run(source, target, answers) == 0
    text = _last_record(target)
    assert "tools/one.py" in text and "create" in text and "example-project" in text
    assert "ux/mock.md" in text and "planned" in text  # skipped modules are recorded with the reason
    assert "lanes/lane.md" in text and "off" in text
    assert "wrote framework.lock" in text and text.rstrip().endswith("exit 0")


def test_refused_answers_exit_one_naming_the_field_and_write_nothing(source: Path, tmp_path: Path, capsys) -> None:
    path = tmp_path / "answers.json"
    path.write_text(json.dumps(dict(ANSWERS, slug="Not A Slug")), encoding="utf-8")
    target = tmp_path / "proj"
    assert _run(source, target, path) == 1
    assert "slug" in capsys.readouterr().err
    assert not target.exists()


def test_a_missing_answers_file_exits_one(source: Path, tmp_path: Path, capsys) -> None:
    assert _run(source, tmp_path / "proj", tmp_path / "nope.json") == 1
    assert "nope.json" in capsys.readouterr().err


def test_a_collision_with_an_unrelated_file_is_refused_before_any_write(
    source: Path, answers: Path, tmp_path: Path, capsys
) -> None:
    target = tmp_path / "proj"
    _write(target, "tools/one.py", "somebody else's file\n")
    _write(target, "untouched.txt", "keep\n")
    before = _snapshot(target)
    assert _run(source, target, answers) == 1
    assert "tools/one.py" in capsys.readouterr().err
    assert _snapshot(target) == before


def test_a_file_where_a_directory_belongs_is_refused_before_any_write(
    source: Path, answers: Path, tmp_path: Path, capsys
) -> None:
    target = tmp_path / "proj"
    _write(target, "tools", "a file named tools\n")
    before = _snapshot(target)
    assert _run(source, target, answers) == 1
    err = capsys.readouterr().err
    assert "tools" in err and "not a directory" in err
    assert _snapshot(target) == before  # nothing else was written first


def test_project_owned_files_are_never_overwritten(source: Path, answers: Path, tmp_path: Path) -> None:
    target = tmp_path / "proj"
    _write(target, "README.md", "my own readme\n")
    assert _run(source, target, answers) == 0
    assert (target / "README.md").read_text(encoding="utf-8") == "my own readme\n"


def test_a_locally_edited_managed_file_is_refused_unless_overridden(
    source: Path, answers: Path, tmp_path: Path, capsys
) -> None:
    target = tmp_path / "proj"
    assert _run(source, target, answers) == 0
    (target / "tools" / "one.py").write_text("print('edited here')\n", encoding="utf-8")
    assert _run(source, target, answers) == 1
    err = capsys.readouterr().err
    assert "tools/one.py" in err and "differs from the lock" in err
    config = fc.load_framework(target / "framework.toml")
    overridden = fc.FrameworkConfig(
        config.template_version,
        config.modules,
        config.harnesses,
        config.handoff_max_lines,
        (fc.Override("tools/one.py", "pinned to a fork"),),
    )
    (target / "framework.toml").write_text(fc.dump_framework(overridden), encoding="utf-8")
    assert _run(source, target, answers) == 0
    assert (target / "tools" / "one.py").read_text(encoding="utf-8") == "print('edited here')\n"
    (target / "tools" / "one.py").unlink()  # an overridden file that was deleted is recreated, not left missing
    assert _run(source, target, answers) == 0
    assert (target / "tools" / "one.py").read_bytes() == b"print('managed one')\n"


def test_a_changed_payload_file_updates_an_unmodified_managed_file(source: Path, answers: Path, tmp_path: Path) -> None:
    target = tmp_path / "proj"
    assert _run(source, target, answers) == 0
    (source / "tools" / "one.py").write_text("print('v2')\n", encoding="utf-8")
    assert _run(source, target, answers) == 0
    assert (target / "tools" / "one.py").read_text(encoding="utf-8") == "print('v2')\n"
    lock = json.loads((target / "framework.lock").read_text(encoding="utf-8"))
    assert lock["files"]["tools/one.py"] == hashlib.sha256(b"print('v2')\n").hexdigest()


def test_a_different_template_version_is_refused(source: Path, answers: Path, tmp_path: Path, capsys) -> None:
    target = tmp_path / "proj"
    assert _run(source, target, answers) == 0
    (source / "framework.toml").write_text(_framework_text().replace("0.1.0", "0.2.0"), encoding="utf-8")
    assert _run(source, target, answers) == 1
    err = capsys.readouterr().err
    assert "0.2.0" in err and "0.1.0" in err


def test_a_corrupt_lock_is_refused_with_a_remedy(source: Path, answers: Path, tmp_path: Path, capsys) -> None:
    target = tmp_path / "proj"
    for bad in ("{not json", "[]", '{"template_version": 3, "files": {}}', '{"template_version": "0.1.0"}'):
        _write(target, "framework.lock", bad)
        assert _run(source, target, answers) == 1
        err = capsys.readouterr().err
        assert "framework.lock" in err and "delete it" in err


def test_changed_answers_over_an_existing_project_are_refused(
    source: Path, answers: Path, tmp_path: Path, capsys
) -> None:
    target = tmp_path / "proj"
    assert _run(source, target, answers) == 0
    other = tmp_path / "other.json"
    other.write_text(json.dumps(dict(ANSWERS, slug="another-project")), encoding="utf-8")
    assert _run(source, target, other) == 1
    assert "project.json" in capsys.readouterr().err


def test_a_repository_cannot_be_initialised_from_itself_or_into_its_own_payload(
    source: Path, answers: Path, capsys
) -> None:
    assert _run(source, source, answers) == 1
    assert "itself" in capsys.readouterr().err
    assert _run(source, source / "out", answers) == 1
    assert "inside the payload" in capsys.readouterr().err
    assert not (source / "out").exists()


def test_the_payload_may_sit_inside_the_target_for_self_hosting(source: Path, answers: Path, tmp_path: Path) -> None:
    """The template initialises its own root: the payload is a subdirectory of the target."""
    root = tmp_path / "template"
    payload = root / "payload"
    root.mkdir()
    source.rename(payload)
    _write(root, "README.md", "the template's own readme\n")
    assert _run(payload, root, answers) == 0
    assert (root / "README.md").read_text(encoding="utf-8") == "the template's own readme\n"
    assert (root / "tools" / "one.py").exists() and (root / "framework.lock").exists()
    first = _snapshot(root)
    assert _run(payload, root, answers) == 0
    assert _snapshot(root) == first


def test_the_target_must_be_a_directory(source: Path, answers: Path, tmp_path: Path) -> None:
    a_file = tmp_path / "file.txt"
    a_file.write_text("x", encoding="utf-8")
    assert _run(source, a_file, answers) == 1


def test_modules_a_project_turned_on_arrive_and_off_ones_do_not(source: Path, answers: Path, tmp_path: Path) -> None:
    target = tmp_path / "proj"
    _write(target, "framework.toml", _framework_text(ux="on"))  # the project chose ux on before init
    assert _run(source, target, answers) == 0
    assert (target / "ux" / "mock.md").exists() and not (target / "lanes").exists()


def test_a_module_turned_off_after_init_leaves_its_files_and_the_plan_says_so(
    source: Path, answers: Path, tmp_path: Path
) -> None:
    target = tmp_path / "proj"
    _write(target, "framework.toml", _framework_text(ux="on"))
    assert _run(source, target, answers) == 0
    _write(target, "framework.toml", _framework_text(ux="off"))
    assert _run(source, target, answers) == 0
    assert (target / "ux" / "mock.md").exists()
    assert "orphan" in _last_record(target) and "ux/mock.md" in _last_record(target)
    _write(target, "framework.toml", _framework_text(ux="on"))  # and turning it back on is clean again
    assert _run(source, target, answers) == 0


def test_a_module_turned_back_on_over_an_edited_orphan_is_refused_as_unrecorded(
    source: Path, answers: Path, tmp_path: Path, capsys
) -> None:
    target = tmp_path / "proj"
    _write(target, "framework.toml", _framework_text(ux="on"))
    assert _run(source, target, answers) == 0
    _write(target, "framework.toml", _framework_text(ux="off"))
    assert _run(source, target, answers) == 0  # the lock drops ux/mock.md; the file stays
    (target / "ux" / "mock.md").write_text("edited while the module was off\n", encoding="utf-8")
    _write(target, "framework.toml", _framework_text(ux="on"))
    assert _run(source, target, answers) == 1
    assert "not recorded in framework.lock" in capsys.readouterr().err


def test_a_file_removed_from_the_payload_is_reported_not_deleted(source: Path, answers: Path, tmp_path: Path) -> None:
    target = tmp_path / "proj"
    assert _run(source, target, answers) == 0
    (source / "tools" / "two.py").unlink()
    assert _run(source, target, answers) == 0
    assert (target / "tools" / "two.py").exists()
    lock = json.loads((target / "framework.lock").read_text(encoding="utf-8"))
    assert "tools/two.py" not in lock["files"]
    assert "orphan" in _last_record(target)


# --------------------------------------------------------------------------- tokens
def test_a_value_that_looks_like_a_token_is_not_expanded_again(source: Path, tmp_path: Path) -> None:
    tricky = dict(ANSWERS, name="Ex {{slug}} and {{owner_email}}")
    path = tmp_path / "answers.json"
    path.write_text(json.dumps(tricky), encoding="utf-8")
    target = tmp_path / "proj"
    assert _run(source, target, path) == 0
    assert (target / "README.md").read_text(encoding="utf-8").startswith("# Ex {{slug}} and {{owner_email}}\n")
    assert fc.load_project(target / "project.json").name == "Ex {{slug}} and {{owner_email}}"


def test_an_unknown_token_in_a_template_is_refused(source: Path, answers: Path, tmp_path: Path, capsys) -> None:
    _write(source, "README.md", "# {{name}} {{nmae}}\n")
    target = tmp_path / "proj"
    assert _run(source, target, answers) == 1
    assert "{{nmae}}" in capsys.readouterr().err
    assert not target.exists()


def test_backslashes_and_regex_characters_in_values_are_inserted_literally(source: Path, tmp_path: Path) -> None:
    tricky = dict(ANSWERS, name=r"C:\path\1 (a|b)*[x] $1 \g[0]")
    path = tmp_path / "answers.json"
    path.write_text(json.dumps(tricky), encoding="utf-8")
    target = tmp_path / "proj"
    assert _run(source, target, path) == 0
    assert (target / "README.md").read_text(encoding="utf-8").startswith(r"# C:\path\1 (a|b)*[x] $1 \g[0]")


def _with_rule(source: Path, pattern: str) -> None:
    """Register ``pattern`` as a project-owned core file in the synthetic payload's manifest."""
    rule = f'\n[[rule]]\npattern = "{pattern}"\nmodule = "core"\nkind = "project-owned"\n'
    _write(source, "framework-manifest.toml", MANIFEST + rule)


def test_today_is_a_token_in_content_and_in_paths_and_the_lock_keeps_it(
    source: Path, answers: Path, tmp_path: Path
) -> None:
    _write(source, "journal/{{today}}-session-01.md", "# Session 01 - {{today}}\n")
    _with_rule(source, "journal/*")
    target = tmp_path / "proj"
    argv = ["new", "--answers", str(answers), "--target", str(target), "--no-sync", "--no-checks"]
    assert ini.main(argv, source=source, today="2026-10-10") == 0
    seeded = target / "journal" / "2026-10-10-session-01.md"
    assert seeded.read_text(encoding="utf-8") == "# Session 01 - 2026-10-10\n"
    lock = json.loads((target / "framework.lock").read_text(encoding="utf-8"))
    assert lock["initialised"] == "2026-10-10"
    first = _snapshot(target)
    # a re-run on another day neither seeds a second dated file nor changes the lock
    assert ini.main(argv, source=source, today="2026-11-02") == 0
    assert _snapshot(target) == first
    assert not (target / "journal" / "2026-11-02-session-01.md").exists()


def test_the_default_day_is_the_local_date_and_a_bad_recorded_day_is_a_corrupt_lock(
    source: Path, answers: Path, tmp_path: Path, capsys
) -> None:
    target = tmp_path / "proj"
    assert _run(source, target, answers) == 0
    lock = json.loads((target / "framework.lock").read_text(encoding="utf-8"))
    assert lock["initialised"] == ini._dt.date.today().isoformat()
    lock["initialised"] = "yesterday"
    (target / "framework.lock").write_text(json.dumps(lock), encoding="utf-8")
    assert _run(source, target, answers) == 1
    assert "initialised" in capsys.readouterr().err


def test_an_unknown_token_in_a_payload_path_is_refused(source: Path, answers: Path, tmp_path: Path, capsys) -> None:
    _write(source, "notes/{{tdoay}}.md", "x\n")
    _with_rule(source, "notes/*")
    assert _run(source, tmp_path / "proj", answers) == 1
    assert "{{tdoay}}" in capsys.readouterr().err


def test_a_value_token_in_a_payload_path_is_refused_so_a_path_cannot_escape(
    source: Path, answers: Path, tmp_path: Path, capsys
) -> None:
    _write(source, "docs/{{owner_name}}.md", "x\n")
    _with_rule(source, "docs/*")
    tricky = dict(ANSWERS, owner={"name": "..\\..\\escape", "email": "ada@example.org"})
    path = tmp_path / "answers.json"
    path.write_text(json.dumps(tricky), encoding="utf-8")
    assert _run(source, tmp_path / "proj", path) == 1
    assert "only {{today}} may appear in a payload path" in capsys.readouterr().err
    assert not (tmp_path / "escape.md").exists() and not (tmp_path / "proj").exists()


def test_a_token_in_a_managed_files_path_or_in_a_directory_name_is_refused(
    source: Path, answers: Path, tmp_path: Path, capsys
) -> None:
    _write(source, "tools/x-{{today}}.py", "x = 1\n")  # managed by the tools/*.py rule
    assert _run(source, tmp_path / "a", answers) == 1
    assert "never in a managed file" in capsys.readouterr().err
    (source / "tools" / "x-{{today}}.py").unlink()
    _write(source, "{{today}}/note.md", "x\n")
    _with_rule(source, "*/note.md")
    assert _run(source, tmp_path / "b", answers) == 1
    assert "in the file name only" in capsys.readouterr().err


def test_an_impossible_day_is_refused_wherever_it_comes_from(
    source: Path, answers: Path, tmp_path: Path, capsys
) -> None:
    argv = ["new", "--answers", str(answers), "--target", str(tmp_path / "a"), "--no-sync", "--no-checks"]
    assert ini.main(argv, source=source, today="2026-13-45") == 1
    assert "today" in capsys.readouterr().err and not (tmp_path / "a").exists()
    target = tmp_path / "b"
    assert _run(source, target, answers) == 0
    lock = json.loads((target / "framework.lock").read_text(encoding="utf-8"))
    lock["initialised"] = "2026-13-45"
    (target / "framework.lock").write_text(json.dumps(lock), encoding="utf-8")
    assert _run(source, target, answers) == 1
    assert "initialised" in capsys.readouterr().err


def test_a_lost_or_older_lock_cannot_seed_a_second_dated_file(source: Path, answers: Path, tmp_path: Path) -> None:
    _write(source, "journal/{{today}}-session-01.md", "# Session 01 - {{today}}\n")
    _with_rule(source, "journal/*")
    target = tmp_path / "proj"
    argv = ["new", "--answers", str(answers), "--target", str(target), "--no-sync", "--no-checks"]
    assert ini.main(argv, source=source, today="2026-10-10") == 0
    lock = json.loads((target / "framework.lock").read_text(encoding="utf-8"))
    del lock["initialised"]  # an older lock without the field
    (target / "framework.lock").write_text(json.dumps(lock), encoding="utf-8")
    assert ini.main(argv, source=source, today="2026-11-02") == 0
    recovered = json.loads((target / "framework.lock").read_text(encoding="utf-8"))
    assert recovered["initialised"] == "2026-10-10"  # the day in the retained file's name, not the day of this run
    (target / "framework.lock").unlink()  # the documented recovery: delete a bad lock
    assert ini.main(argv, source=source, today="2026-12-01") == 0
    assert [p.name for p in (target / "journal").iterdir()] == ["2026-10-10-session-01.md"]
    recovered = json.loads((target / "framework.lock").read_text(encoding="utf-8"))
    assert recovered["initialised"] == "2026-10-10"
    assert "initialised 2026-10-10" in _last_record(target)


def test_a_dated_file_under_another_day_than_the_lock_still_blocks_a_second_seed(
    source: Path, answers: Path, tmp_path: Path
) -> None:
    _write(source, "journal/{{today}}-session-01.md", "# Session 01 - {{today}}\n")
    _with_rule(source, "journal/*")
    target = tmp_path / "proj"
    argv = ["new", "--answers", str(answers), "--target", str(target), "--no-sync", "--no-checks"]
    assert ini.main(argv, source=source, today="2026-10-10") == 0
    (target / "journal" / "2026-10-10-session-01.md").rename(target / "journal" / "2026-10-09-session-01.md")
    assert ini.main(argv, source=source, today="2026-11-02") == 0  # the lock says 2026-10-10; the file says 2026-10-09
    assert [p.name for p in (target / "journal").iterdir()] == ["2026-10-09-session-01.md"]
    assert "earlier dated file" in _last_record(target)


def test_the_earliest_of_several_dated_seeds_gives_the_recovered_day(
    source: Path, answers: Path, tmp_path: Path
) -> None:
    _write(source, "journal/{{today}}-session-01.md", "# Session 01 - {{today}}\n")
    _with_rule(source, "journal/*")
    target = tmp_path / "proj"
    _write(target, "journal/2026-09-03-session-01.md", "older\n")
    _write(target, "journal/2026-08-30-session-01.md", "oldest\n")
    _write(target, "journal/2026-09-03-session-02.md", "not the seeded shape\n")
    _write(target, "journal/2026-00-10-session-01.md", "an impossible day sorts first but is not a day\n")
    argv = ["new", "--answers", str(answers), "--target", str(target), "--no-sync", "--no-checks"]
    assert ini.main(argv, source=source, today="2026-12-01") == 0
    assert json.loads((target / "framework.lock").read_text(encoding="utf-8"))["initialised"] == "2026-08-30"


def test_malformed_braces_in_a_payload_path_are_refused(source: Path, answers: Path, tmp_path: Path, capsys) -> None:
    for index, name in enumerate(["{{today.foo}}.md", "x}}.md", "{{today}}{{.md", "{today}}.md"]):
        for leftover in (source / "notes").glob("*") if (source / "notes").exists() else []:
            leftover.unlink()
        _write(source, f"notes/{name}", "x\n")
        _with_rule(source, "notes/*")
        assert _run(source, tmp_path / f"p{index}", answers) == 1, name
        assert "only {{today}} may appear in a payload path" in capsys.readouterr().err
        assert not (tmp_path / f"p{index}").exists()


def test_the_template_version_is_a_token_and_the_record_names_the_day(
    source: Path, answers: Path, tmp_path: Path
) -> None:
    _write(source, "README.md", "# {{name}}\n\nMade from template {{template_version}}.\n")
    target = tmp_path / "proj"
    assert _run(source, target, answers) == 0
    assert (target / "README.md").read_text(encoding="utf-8").endswith("Made from template 0.1.0.\n")
    assert f"initialised {ini._dt.date.today().isoformat()}" in _last_record(target)


def test_init_new_needs_the_journal_when_the_payload_seeds_one(
    source: Path, answers: Path, tmp_path: Path, capsys
) -> None:
    rule = '\n[[rule]]\npattern = "journal/*"\nmodule = "journal"\nkind = "project-owned"\n'
    _write(source, "framework-manifest.toml", MANIFEST + rule)
    _write(source, "journal/README.md", "# Journal\n")
    for state in ("off", "planned"):
        _write(source, "framework.toml", _framework_text(journal=state))
        assert _run(source, tmp_path / state, answers) == 1
        assert "modules.journal" in capsys.readouterr().err and not (tmp_path / state).exists()
    _write(source, "framework.toml", _framework_text(journal="on"))
    assert _run(source, tmp_path / "on", answers) == 0
    assert (tmp_path / "on" / "journal" / "README.md").exists()


# --------------------------------------------------------------------------- the end of a run, and failures
def test_sync_and_the_checks_run_in_the_target_and_a_failure_exits_two(
    source: Path, answers: Path, tmp_path: Path
) -> None:
    _write(source, "tools/check.py", "# the gate\n")
    target = tmp_path / "proj"
    ok = _Runner()
    args = ["new", "--answers", str(answers), "--target", str(target)]
    assert ini.main(args, source=source, runner=ok) == 0
    assert [c[0][:2] for c in ok.calls] == [["uv", "sync"], ["uv", "run"]]
    assert all(c[1] == target for c in ok.calls) and "tools/check.py" in " ".join(ok.calls[1][0])

    failing_check = _Runner({"check.py": 1}, output="line one\nFAILED: the gate said no\n")
    assert ini.main(args, source=source, runner=failing_check) == 2
    record = _last_record(target)
    assert "tools/check.py exited 1" in record and "FAILED: the gate said no" in record  # the output is in the record

    failing_sync = _Runner({"sync": 1}, output="resolution failed\n")
    assert ini.main(args, source=source, runner=failing_sync) == 2
    assert len(failing_sync.calls) == 1  # the checks do not run on a repository that did not sync
    record = _last_record(target)
    assert "the gate was not run: uv sync failed" in record and "resolution failed" in record


def test_without_a_gate_script_there_is_nothing_to_run_and_the_record_says_so(
    source: Path, answers: Path, tmp_path: Path
) -> None:
    runner = _Runner()
    target = tmp_path / "proj"
    argv = ["new", "--answers", str(answers), "--target", str(target), "--no-sync"]
    assert ini.main(argv, source=source, runner=runner) == 0
    assert runner.calls == []
    assert "no tools/check.py" in _last_record(target)


def test_a_missing_uv_is_reported_as_such(tmp_path: Path) -> None:
    result = ini._default_runner(["definitely-not-a-program-xyz"], tmp_path)
    assert result.code == 127 and "could not start" in result.output and "PATH" in result.output


def test_the_default_runner_returns_what_the_command_printed(tmp_path: Path, capsys) -> None:
    result = ini._default_runner([sys.executable, "-c", "print('hello from the child')"], tmp_path)
    assert result.code == 0 and "hello from the child" in result.output
    assert "hello from the child" in capsys.readouterr().out


def test_a_failure_while_writing_exits_two_leaves_a_record_and_no_lock_and_a_rerun_recovers(
    source: Path, answers: Path, tmp_path: Path, monkeypatch, capsys
) -> None:
    target = tmp_path / "proj"
    real = ini.write_atomic
    calls = {"n": 0}

    def flaky(dest: Path, data: bytes) -> None:
        calls["n"] += 1
        if calls["n"] == 3:
            raise PermissionError("denied")
        real(dest, data)

    monkeypatch.setattr(ini, "write_atomic", flaky)
    assert _run(source, target, answers) == 2
    assert "denied" in capsys.readouterr().err
    assert not (target / "framework.lock").exists()  # the lock is written last
    assert not list(target.rglob("*.init-tmp"))
    text = _last_record(target)
    assert "FAILED while writing" in text and "denied" in text and text.rstrip().endswith("exit 2")
    monkeypatch.setattr(ini, "write_atomic", real)
    assert _run(source, target, answers) == 0  # a re-run recovers
    assert (target / "framework.lock").exists()


@pytest.mark.parametrize("name", ["framework.lock", "project.json", "logs"])
def test_the_wrong_kind_of_path_where_a_generated_file_or_the_record_goes_is_refused_before_any_write(
    source: Path, answers: Path, tmp_path: Path, capsys, name: str
) -> None:
    """A directory named like a generated file, or a plain file named logs (the record's directory)."""
    target = tmp_path / "proj"
    target.mkdir()
    if name == "logs":
        (target / name).write_text("a file, not a directory", encoding="utf-8")
    else:
        (target / name).mkdir()
    before = sorted(p.relative_to(target).as_posix() for p in target.rglob("*"))
    assert _run(source, target, answers) == 1
    assert name in capsys.readouterr().err
    assert sorted(p.relative_to(target).as_posix() for p in target.rglob("*")) == before  # nothing else was written


def test_a_lock_with_a_malformed_entry_is_a_corrupt_lock_not_an_edited_file(
    source: Path, answers: Path, tmp_path: Path, capsys
) -> None:
    target = tmp_path / "proj"
    good = "a" * 64
    for entry in ("null", "123", '"short"', f'"{"A" * 64}"', f'"{good}x"', "[]"):
        _write(target, "framework.lock", f'{{"template_version": "0.1.0", "files": {{"tools/one.py": {entry}}}}}')
        assert _run(source, target, answers) == 1
        err = capsys.readouterr().err
        assert "framework.lock" in err and "SHA-256" in err and "differs from the lock" not in err


def test_a_temporary_file_never_clobbers_an_unrelated_file_and_names_are_unique(tmp_path: Path) -> None:
    dest = tmp_path / "out.txt"
    unrelated = tmp_path / "out.txt.init-tmp"  # the old fixed temporary name
    unrelated.write_text("somebody else's file", encoding="utf-8")
    ini.write_atomic(dest, b"data")
    assert dest.read_bytes() == b"data" and unrelated.read_text(encoding="utf-8") == "somebody else's file"
    seen = set()
    real_mkstemp = ini.tempfile.mkstemp

    def spy(*args, **kwargs):
        descriptor, name = real_mkstemp(*args, **kwargs)
        seen.add(name)
        return descriptor, name

    ini.tempfile.mkstemp = spy
    try:
        for _ in range(5):
            ini.write_atomic(dest, b"again")
    finally:
        ini.tempfile.mkstemp = real_mkstemp
    assert len(seen) == 5 and not [p for p in tmp_path.iterdir() if p.name not in ("out.txt", "out.txt.init-tmp")]


def test_a_record_that_cannot_be_written_does_not_replace_the_outcome(
    source: Path, answers: Path, tmp_path: Path, monkeypatch, capsys
) -> None:
    def refuse(target: Path, lines: list[str]) -> Path:
        raise PermissionError("logs is read-only")

    monkeypatch.setattr(ini, "_record", refuse)
    target = tmp_path / "proj"
    assert _run(source, target, answers) == 0  # the repository was written; the missing record is a warning
    assert "record could not be written" in capsys.readouterr().err
    assert (target / "framework.lock").exists()
    failing = _Runner({"sync": 1})
    argv = ["new", "--answers", str(answers), "--target", str(tmp_path / "proj2"), "--no-checks"]
    assert ini.main(argv, source=source, runner=failing) == 2  # a real failure is still exit 2


def test_an_atomic_write_leaves_no_temporary_file_and_replaces_in_place(tmp_path: Path, monkeypatch) -> None:
    dest = tmp_path / "a" / "b.txt"
    ini.write_atomic(dest, b"one")
    ini.write_atomic(dest, b"two")
    assert dest.read_bytes() == b"two" and not list(tmp_path.rglob("*.init-tmp"))

    def boom(src, dst):
        raise OSError("replace failed")

    monkeypatch.setattr(ini.os, "replace", boom)
    with pytest.raises(OSError):
        ini.write_atomic(dest, b"three")
    assert dest.read_bytes() == b"two" and not list(tmp_path.rglob("*.init-tmp"))


# --------------------------------------------------------------------------- prompts
def test_prompts_build_the_answers_with_defaults() -> None:
    replies = iter(["Example Project", "", "Ada Example", "ada@example.org", "", "", "acme, internal"])
    asked: list[str] = []

    def ask(prompt: str) -> str:
        asked.append(prompt)
        return next(replies)

    project = ini.prompt_answers(ask, lambda text: None)
    assert project.slug == "example-project" and project.default_branch == "main" and project.signoff is True
    assert project.hygiene == ("acme", "internal")
    assert len(asked) == 7


def test_a_prompt_reasks_until_the_answer_is_valid() -> None:
    replies = iter(["Example", "Bad Slug", "example", "Ada", "not-an-email", "ada@example.org", "", "n", ""])
    said: list[str] = []
    project = ini.prompt_answers(lambda prompt: next(replies), said.append)
    assert project.slug == "example" and project.owner.email == "ada@example.org" and project.signoff is False
    assert any("slug" in line for line in said) and any("owner.email" in line for line in said)


def test_a_mistyped_signoff_answer_is_reasked_not_read_as_no() -> None:
    replies = iter(["Example", "", "Ada", "ada@example.org", "", "yse", "Y", ""])
    said: list[str] = []
    project = ini.prompt_answers(lambda prompt: next(replies), said.append)
    assert project.signoff is True and any("answer y or n" in line for line in said)
    for reply, expected in (("yes", True), ("TRUE", True), ("no", False), ("False", False)):
        assert ini._yes_no(reply) is expected


def test_input_ending_during_the_questions_exits_one(source: Path, tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)

    def eof(prompt: str) -> str:
        raise EOFError

    args = ini.argparse.Namespace(
        answers=None, target=str(tmp_path / "proj"), dry_run=False, no_sync=True, no_checks=True
    )
    assert ini.run_new(args, source, _Runner(), print, lambda t: print(t, file=sys.stderr), eof) == 1
    assert "not answered" in capsys.readouterr().err
    assert not (tmp_path / "proj").exists()


def test_without_answers_and_without_a_terminal_it_exits_one(source: Path, tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    assert ini.main(["new", "--target", str(tmp_path / "proj"), "--no-sync", "--no-checks"], source=source) == 1
    assert "--answers" in capsys.readouterr().err


def test_a_broken_payload_is_reported_as_a_template_bug(source: Path, answers: Path, tmp_path: Path, capsys) -> None:
    (source / "framework-manifest.toml").write_text("not = [valid", encoding="utf-8")
    assert _run(source, tmp_path / "proj", answers) == 1
    assert "template bug" in capsys.readouterr().err


def test_target_is_required_and_a_bare_command_is_a_usage_error() -> None:
    with pytest.raises(SystemExit) as caught:
        ini.main([])
    assert caught.value.code != 0
    with pytest.raises(SystemExit) as caught:
        ini.main(["new", "--no-sync"])
    assert caught.value.code != 0


# --------------------------------------------------------------------------- the real payload
@only_in_the_template
def test_the_real_payload_initialises_a_repository_and_is_stable(answers: Path, tmp_path: Path) -> None:
    target = tmp_path / "proj"
    assert _run(ROOT, target, answers) == 0
    snap = _snapshot(target)
    assert b'name = "example-project"' in snap["pyproject.toml"]
    assert "tools/init.py" in snap and "tools/framework_config.py" in snap and "tests/test_init.py" in snap
    assert _run(ROOT, target, answers) == 0
    assert _snapshot(target) == snap


def test_init_new_also_needs_the_python_uv_module_the_entry_file_links_to(
    source: Path, answers: Path, tmp_path: Path, capsys
) -> None:
    for state in ("off", "planned"):
        _write(source, "framework.toml", _framework_text(**{"python-uv": state}))
        assert _run(source, tmp_path / state, answers) == 1
        assert "modules.python-uv" in capsys.readouterr().err and not (tmp_path / state).exists()


# ---- what the sync check shares with init
def test_lock_hash_is_the_hash_the_lock_records_whatever_the_line_endings() -> None:
    assert ini.lock_hash(b"a\r\nb\r\n") == ini.lock_hash(b"a\nb\n") == ini.file_hash(b"a\nb\n")
    assert ini.lock_hash(b"a\nb\n") != ini.lock_hash(b"a\nc\n")


def test_lock_hash_leaves_a_binary_file_alone() -> None:
    raw = b"\x00\x01\r\n\xff"
    assert ini.lock_hash(raw) == ini.file_hash(raw)


def test_read_lock_is_none_without_a_lock_and_the_locked_hashes_with_one(tmp_path: Path) -> None:
    assert ini.read_lock(tmp_path) is None
    digest = ini.lock_hash(b"x")
    (tmp_path / "framework.lock").write_text(
        json.dumps({"template_version": "1.2.3", "initialised": "2026-10-15", "files": {"a.md": digest}}),
        encoding="utf-8",
    )
    assert ini.read_lock(tmp_path) == ("1.2.3", {"a.md": digest}, "2026-10-15")


def test_read_lock_refuses_one_it_cannot_read(tmp_path: Path) -> None:
    (tmp_path / "framework.lock").write_text("{not json", encoding="utf-8")
    with pytest.raises(fc.ConfigError, match="cannot be read"):
        ini.read_lock(tmp_path)


# ---- Copilot's review: create_only is one step, and a symlink is never replaced by it
def test_create_only_writes_a_new_file_and_leaves_no_temporary(tmp_path: Path) -> None:
    dest = tmp_path / "sub" / "new.txt"
    ini.write_atomic(dest, b"one", create_only=True)
    assert dest.read_bytes() == b"one"
    assert [p.name for p in dest.parent.iterdir()] == ["new.txt"]


def test_create_only_refuses_an_existing_file_and_leaves_it_and_no_temporary(tmp_path: Path) -> None:
    dest = tmp_path / "there.txt"
    dest.write_bytes(b"mine")
    with pytest.raises(FileExistsError, match="appeared after the plan was made"):
        ini.write_atomic(dest, b"theirs", create_only=True)
    assert dest.read_bytes() == b"mine"
    assert [p.name for p in tmp_path.iterdir()] == ["there.txt"]


def test_create_only_refuses_a_symlink_even_to_nowhere(tmp_path: Path) -> None:
    dest = tmp_path / "link.txt"
    try:
        dest.symlink_to(tmp_path / "nowhere.txt")
    except (OSError, NotImplementedError):
        pytest.skip("this account cannot create a symlink")
    with pytest.raises(FileExistsError):
        ini.write_atomic(dest, b"data", create_only=True)
    assert dest.is_symlink()
    assert not (tmp_path / "nowhere.txt").exists()
    assert [p.name for p in tmp_path.iterdir()] == ["link.txt"]


def test_create_only_does_not_replace_a_file_that_appears_between_the_check_and_the_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dest = tmp_path / "race.txt"
    real = ini.os.link

    def appears_first(src, dst, *args, **kwargs):
        Path(dst).write_bytes(b"made in between")
        return real(src, dst, *args, **kwargs)

    monkeypatch.setattr(ini.os, "link", appears_first)
    with pytest.raises(FileExistsError):
        ini.write_atomic(dest, b"mine", create_only=True)
    assert dest.read_bytes() == b"made in between"
    assert [p.name for p in tmp_path.iterdir()] == ["race.txt"]


def test_where_hard_links_are_not_available_create_only_still_refuses_what_exists_and_creates_what_does_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_links(*args, **kwargs):
        raise OSError(1, "Operation not permitted")

    monkeypatch.setattr(ini.os, "link", no_links)
    fresh = tmp_path / "fresh.txt"
    ini.write_atomic(fresh, b"data", create_only=True)
    assert fresh.read_bytes() == b"data"
    taken = tmp_path / "taken.txt"
    taken.write_bytes(b"mine")
    with pytest.raises(FileExistsError):
        ini.write_atomic(taken, b"theirs", create_only=True)
    assert taken.read_bytes() == b"mine"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["fresh.txt", "taken.txt"]


def test_a_symlink_to_nowhere_where_the_payload_has_a_file_is_a_refusal_not_a_create(
    source: Path, answers: Path, tmp_path: Path
) -> None:
    target = tmp_path / "proj"
    (target / "tools").mkdir(parents=True)
    try:
        (target / "tools" / "one.py").symlink_to(target / "tools" / "missing.py")
    except (OSError, NotImplementedError):
        pytest.skip("this account cannot create a symlink")
    plan = ini.plan_new(source, target, fc.load_answers(answers), "2026-10-16")
    assert any("tools/one.py: is a symlink to nowhere" in r for r in plan.refusals)


# --------------------------------------------------------------------------- the board seeds are conditional
BOARD_MANIFEST = (
    MANIFEST
    + """
[[rule]]
pattern = "Docs/plan/*"
module = "core"
kind = "project-owned"
"""
)
BOARD_SEEDS = {
    "Docs/plan/board/README.md": "# Rows\n\n**Status:** Living.\n",
    "Docs/plan/board/{{today}}-first-gate.md": "# G1\n\n**Section:** gate\n**Owner:** none\n**State:** Open\n",
}


@pytest.fixture
def board_source(tmp_path: Path) -> Path:
    src = tmp_path / "payload-board"
    _write(src, "framework-manifest.toml", BOARD_MANIFEST)
    _write(src, "framework.toml", _framework_text())
    _write(src, "tools/one.py", "print('managed one')\n")
    _write(src, "AGENTS.md", "# {{name}}\n")
    _write(src, "framework-manifest.toml", BOARD_MANIFEST)
    for rel, text in BOARD_SEEDS.items():
        _write(src, rel, text)
    return src


def test_a_fresh_repository_is_seeded_the_board_rows_and_a_rerun_seeds_none_again(
    board_source: Path, answers: Path, tmp_path: Path
) -> None:
    target = tmp_path / "proj"
    assert _run(board_source, target, answers) == 0
    rows = sorted(p.name for p in (target / "Docs/plan/board").iterdir())
    assert rows == ["2026-10-16-first-gate.md", "README.md"] or len(rows) == 2 and "README.md" in rows
    before = _snapshot(target)
    assert _run(board_source, target, answers) == 0
    assert _snapshot(target) == before


@pytest.mark.parametrize(
    "existing",
    ["Docs/plan/BOARD.md", "Docs/plan/board/2026-01-01-mine.md"],
    ids=["a-hand-kept-page", "a-row-file-of-its-own"],
)
def test_a_repository_with_a_board_in_either_form_is_seeded_no_board_rows(
    board_source: Path, answers: Path, tmp_path: Path, existing: str
) -> None:
    """A hand-kept page beside seeded rows would be two trackers; a repository's own rows need no examples."""
    target = tmp_path / "proj"
    _write(target, existing, "# Mine\n\n**Section:** now\n**Owner:** @ada\n**State:** Open\n")
    assert _run(board_source, target, answers) == 0
    assert not (target / "Docs/plan/board/README.md").exists()
    assert not list((target / "Docs/plan").glob("board/*-first-gate.md"))
    assert (target / existing).read_text(encoding="utf-8").startswith("# Mine")
    assert (target / "tools/one.py").is_file()  # the rest of the payload is seeded as ever


@pytest.mark.parametrize(
    "name",
    ["2026-10-02-build-it.md", "2026-13-02-build-it.md", "2026-10-02-Build-It.md", "build-it.md", "README.md", "a.txt"],
)
def test_init_counts_as_a_row_file_exactly_what_the_docs_check_does(name: str) -> None:
    """``init`` keeps its own copy of the row-file name rule; a drift would change what it counts as a board."""
    import check_docs as cd

    assert (ini._ROW_SEED_RE.fullmatch(name) is not None) == (cd.row_file_name(name) is not None), name


def test_a_target_that_keeps_its_rows_elsewhere_is_still_seeded_no_board_rows(
    board_source: Path, answers: Path, tmp_path: Path
) -> None:
    """The seeds live where the payload keeps its rows; the board the target has is wherever its configuration says."""
    target = tmp_path / "proj"
    assert _run(board_source, target, answers) == 0
    for seeded in (target / "Docs/plan/board").iterdir():
        seeded.unlink()
    (target / "Docs/plan/board").rmdir()
    toml = target / "framework.toml"
    toml.write_text(toml.read_text(encoding="utf-8") + '\n[docs]\nboard_dir = "Docs/rows"\n', encoding="utf-8")
    _write(target, "Docs/rows/2026-01-01-mine.md", "# Mine\n\n**Section:** now\n**Owner:** @ada\n**State:** Open\n")
    assert _run(board_source, target, answers) == 0
    assert not (target / "Docs/plan/board").exists()
