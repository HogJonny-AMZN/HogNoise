"""
Framework: tests for tools/framework_config.py (the schemas and loader for framework.toml, project.json, answers.json).
Package: tests/test_framework_config
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import framework_config as fc  # noqa: E402
import pins  # noqa: E402


# --------------------------------------------------------------------------- fixtures
def _framework_data() -> dict:
    return {
        "framework": {"template_version": "0.1.0"},
        "modules": {
            "core": "on",
            "journal": "on",
            "ux": "planned",
            "python-uv": "on",
            "tasking": "on",
            "hygiene": "on",
            "graph": "on",
            "harness-adapters": "on",
            "specimens": "planned",
            "lanes": "off",
            "branch-ownership": "off",
            "devblog": "off",
        },
        "harnesses": {"enabled": ["claude"]},
        "checks": {"handoff_max_lines": 150},
        "overrides": [],
    }


def _project_data() -> dict:
    return {
        "name": "Example Project",
        "slug": "example-project",
        "owner": {"name": "Ada Example", "email": "ada@example.org"},
        "default_branch": "main",
        "signoff": True,
        "hygiene": ["acme-internal"],
    }


def _toml_text(data: dict) -> str:
    """The emitter's own output for ``data``, built by loading through the model and dumping it back."""
    return fc.dump_framework(fc.parse_framework(data))


@pytest.fixture
def framework_data() -> dict:
    return _framework_data()


@pytest.fixture
def project_data() -> dict:
    return _project_data()


def _refused(parse, data: dict, field: str) -> fc.ConfigError:
    with pytest.raises(fc.ConfigError) as caught:
        parse(data)
    assert caught.value.field == field, str(caught.value)
    assert field in str(caught.value)
    return caught.value


# --------------------------------------------------------------------------- the valid files
def test_a_valid_framework_file_round_trips(framework_data: dict) -> None:
    config = fc.parse_framework(framework_data)
    assert config.template_version == "0.1.0"
    assert config.modules["core"] == "on" and config.modules["ux"] == "planned" and config.modules["lanes"] == "off"
    assert config.harnesses == ("claude",)
    assert config.handoff_max_lines == 150
    text = fc.dump_framework(config)
    assert fc.parse_framework_text(text) == config
    assert fc.dump_framework(fc.parse_framework_text(text)) == text  # the emitter is deterministic


def test_a_valid_project_file_round_trips(project_data: dict) -> None:
    config = fc.parse_project(project_data)
    assert config.slug == "example-project" and config.owner.email == "ada@example.org" and config.signoff is True
    assert config.hygiene == ("acme-internal",)
    assert fc.parse_project_text(fc.dump_project(config)) == config


def test_the_answers_file_uses_the_project_schema(tmp_path: Path, project_data: dict) -> None:
    answers = tmp_path / "answers.json"
    answers.write_text(json.dumps(project_data), encoding="utf-8")
    assert fc.load_answers(answers) == fc.parse_project(project_data)
    # and a refusal names the file as well as the field
    project_data["slug"] = "Not A Slug"
    answers.write_text(json.dumps(project_data), encoding="utf-8")
    with pytest.raises(fc.ConfigError) as caught:
        fc.load_answers(answers)
    assert "answers.json" in str(caught.value) and caught.value.field == "slug"


def test_files_load_from_disk(tmp_path: Path, framework_data: dict, project_data: dict) -> None:
    (tmp_path / "framework.toml").write_text(_toml_text(framework_data), encoding="utf-8")
    (tmp_path / "project.json").write_text(json.dumps(project_data), encoding="utf-8")
    assert fc.load_framework(tmp_path / "framework.toml") == fc.parse_framework(framework_data)
    assert fc.load_project(tmp_path / "project.json") == fc.parse_project(project_data)


def test_a_missing_or_unreadable_file_is_a_config_error(tmp_path: Path) -> None:
    for loader, name in ((fc.load_framework, "framework.toml"), (fc.load_project, "project.json")):
        with pytest.raises(fc.ConfigError) as caught:
            loader(tmp_path / name)
        assert name in str(caught.value)
    bad = tmp_path / "project.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(fc.ConfigError):
        fc.load_project(bad)
    toml = tmp_path / "framework.toml"
    toml.write_text("not = [valid", encoding="utf-8")
    with pytest.raises(fc.ConfigError):
        fc.load_framework(toml)
    toml.write_bytes(bytes([0xFF, 0xFE]) + b"x")
    with pytest.raises(fc.ConfigError):
        fc.load_framework(toml)


# --------------------------------------------------------------------------- framework.toml refusals
def test_a_missing_top_level_table_is_refused(framework_data: dict) -> None:
    for table in ("framework", "modules", "harnesses", "checks"):
        data = copy.deepcopy(framework_data)
        del data[table]
        _refused(fc.parse_framework, data, table)


def test_the_version_must_be_semver(framework_data: dict) -> None:
    for bad in ("1", "v1.0.0", "1.0", "1.0.0.0", "", 1.0, None):
        data = copy.deepcopy(framework_data)
        data["framework"]["template_version"] = bad
        _refused(fc.parse_framework, data, "framework.template_version")


def test_an_unknown_module_or_state_is_refused(framework_data: dict) -> None:
    framework_data["modules"]["sparkles"] = "on"
    _refused(fc.parse_framework, framework_data, "modules.sparkles")
    framework_data = _framework_data()
    framework_data["modules"]["ux"] = "maybe"
    _refused(fc.parse_framework, framework_data, "modules.ux")
    framework_data = _framework_data()
    framework_data["modules"]["ux"] = True
    _refused(fc.parse_framework, framework_data, "modules.ux")


def test_a_missing_module_is_refused(framework_data: dict) -> None:
    del framework_data["modules"]["graph"]
    _refused(fc.parse_framework, framework_data, "modules.graph")


def test_the_core_cannot_be_off_or_planned(framework_data: dict) -> None:
    for state in ("off", "planned"):
        data = copy.deepcopy(framework_data)
        data["modules"]["core"] = state
        _refused(fc.parse_framework, data, "modules.core")


def test_harnesses_must_be_known_distinct_and_backed_by_the_adapter_module(framework_data: dict) -> None:
    framework_data["harnesses"]["enabled"] = ["claude", "claude"]
    _refused(fc.parse_framework, framework_data, "harnesses.enabled")
    framework_data = _framework_data()
    framework_data["harnesses"]["enabled"] = ["claude", "skynet"]
    _refused(fc.parse_framework, framework_data, "harnesses.enabled")
    framework_data = _framework_data()
    framework_data["harnesses"]["enabled"] = "claude"
    _refused(fc.parse_framework, framework_data, "harnesses.enabled")
    framework_data = _framework_data()
    framework_data["modules"]["harness-adapters"] = "off"
    _refused(fc.parse_framework, framework_data, "harnesses.enabled")  # enabled harnesses need the module on
    framework_data["harnesses"]["enabled"] = []
    fc.parse_framework(framework_data)  # nothing enabled and the module off is consistent


def test_the_handoff_limit_is_a_bounded_integer(framework_data: dict) -> None:
    for bad in (0, 19, 1001, -5, 150.5, "150", True, None):
        data = copy.deepcopy(framework_data)
        data["checks"]["handoff_max_lines"] = bad
        _refused(fc.parse_framework, data, "checks.handoff_max_lines")


def test_changing_the_handoff_limit_needs_an_override_with_a_reason(framework_data: dict) -> None:
    framework_data["checks"]["handoff_max_lines"] = 200
    _refused(fc.parse_framework, framework_data, "checks.handoff_max_lines")
    framework_data["overrides"] = [{"target": "handoff_max_lines", "reason": "a long-running programme"}]
    assert fc.parse_framework(framework_data).handoff_max_lines == 200


def _repo_with_overrides(tmp_path: Path, framework_data: dict, *targets: str) -> Path:
    framework_data["overrides"] = [{"target": target, "reason": "the project's own text"} for target in targets]
    (tmp_path / "framework.toml").write_text(_toml_text(framework_data), encoding="utf-8")
    return tmp_path


def test_overridden_names_the_overrides_among_the_paths_asked_about_in_the_order_asked(
    tmp_path: Path, framework_data: dict
) -> None:
    root = _repo_with_overrides(tmp_path, framework_data, "Docs/a.md", "Docs/b.md")
    assert fc.overridden(root, "Docs/b.md", "Docs/c.md", "Docs/a.md") == ["Docs/b.md", "Docs/a.md"]
    assert fc.overridden(root, "Docs/c.md") == []
    assert fc.overridden(root) == []


def test_overridden_excuses_nothing_when_the_configuration_cannot_be_read(tmp_path: Path) -> None:
    assert fc.overridden(tmp_path, "Docs/a.md") == []  # no framework.toml
    (tmp_path / "framework.toml").write_text("not = = toml", encoding="utf-8")
    assert fc.overridden(tmp_path, "Docs/a.md") == []


def test_pins_skips_with_the_reason_shown_only_for_a_document_the_repository_overrides(
    tmp_path: Path, framework_data: dict
) -> None:
    root = _repo_with_overrides(tmp_path, framework_data, "Docs/standards/workflow.md")
    skipped = pins.pins("Docs/standards/workflow.md", "Docs/standards/python.md", root=root).mark
    assert skipped.args == (True,)
    assert "Docs/standards/workflow.md overridden in framework.toml" in skipped.kwargs["reason"]
    assert "python.md" not in skipped.kwargs["reason"]
    assert pins.pins("Docs/standards/python.md", root=root).mark.args == (False,)
    assert pins.pins("Docs/standards/workflow.md", root=tmp_path / "elsewhere").mark.args == (False,)


def test_overrides_are_validated(framework_data: dict) -> None:
    cases = [
        ([{"target": "tools/check_docs.py"}], "overrides[0].reason"),
        ([{"target": "tools/check_docs.py", "reason": "  "}], "overrides[0].reason"),
        ([{"reason": "no target"}], "overrides[0].target"),
        ([{"target": "../outside.py", "reason": "x"}], "overrides[0].target"),
        ([{"target": "/etc/passwd", "reason": "x"}], "overrides[0].target"),
        ([{"target": "C:/Windows/x", "reason": "x"}], "overrides[0].target"),
        ([{"target": "a\\b.py", "reason": "x"}], "overrides[0].target"),
        (["tools/check_docs.py"], "overrides[0]"),
        ({"target": "x"}, "overrides"),
        (
            [{"target": "a.py", "reason": "x"}, {"target": "a.py", "reason": "y"}],
            "overrides[1].target",
        ),
    ]
    for value, field in cases:
        data = copy.deepcopy(framework_data)
        data["overrides"] = value
        _refused(fc.parse_framework, data, field)
    framework_data["overrides"] = [{"target": "tools/check_docs.py", "reason": "pinned to a fork"}]
    assert fc.parse_framework(framework_data).overrides[0].target == "tools/check_docs.py"


def test_unknown_keys_are_refused_so_a_typo_is_not_silently_ignored(framework_data: dict) -> None:
    framework_data["checks"]["handoff_max_line"] = 100
    _refused(fc.parse_framework, framework_data, "checks.handoff_max_line")
    framework_data = _framework_data()
    framework_data["surprise"] = {}
    _refused(fc.parse_framework, framework_data, "surprise")


def test_a_non_table_where_a_table_belongs_is_refused(framework_data: dict) -> None:
    for table in ("framework", "modules", "harnesses", "checks"):
        data = copy.deepcopy(framework_data)
        data[table] = "text"
        _refused(fc.parse_framework, data, table)


# --------------------------------------------------------------------------- project.json refusals
def test_every_project_field_is_required(project_data: dict) -> None:
    for field in ("name", "slug", "owner", "default_branch", "signoff", "hygiene"):
        data = copy.deepcopy(project_data)
        del data[field]
        _refused(fc.parse_project, data, field)
    for field in ("name", "email"):
        data = copy.deepcopy(project_data)
        del data["owner"][field]
        _refused(fc.parse_project, data, f"owner.{field}")


def test_name_and_owner_text_fields(project_data: dict) -> None:
    for bad in ("", "   ", 3, None, "x" * 81):
        data = copy.deepcopy(project_data)
        data["name"] = bad
        _refused(fc.parse_project, data, "name")
    for bad in ("", " ", 7):
        data = copy.deepcopy(project_data)
        data["owner"]["name"] = bad
        _refused(fc.parse_project, data, "owner.name")


def test_slug_is_lower_case_kebab(project_data: dict) -> None:
    for bad in ("Example", "has space", "-lead", "trail-", "double--dash", "9start", "under_score", "", 5):
        data = copy.deepcopy(project_data)
        data["slug"] = bad
        _refused(fc.parse_project, data, "slug")
    for good in ("a", "abc", "a1-b2-c3"):
        data = copy.deepcopy(project_data)
        data["slug"] = good
        assert fc.parse_project(data).slug == good


def test_email_needs_one_at_and_a_dotted_domain(project_data: dict) -> None:
    for bad in ("", "no-at-sign", "a@b", "a@@b.c", "a b@c.d", "@c.d", "a@.d", 4):
        data = copy.deepcopy(project_data)
        data["owner"]["email"] = bad
        _refused(fc.parse_project, data, "owner.email")


def test_default_branch_is_a_plain_ref_name(project_data: dict) -> None:
    for bad in (
        "",
        "has space",
        "-x",
        "a..b",
        "a~b",
        "a^b",
        "a:b",
        "a?b",
        "a*b",
        "a[b",
        "a\\b",
        "x.lock",
        "/x",
        "x/",
        "@",
        1,
    ):
        data = copy.deepcopy(project_data)
        data["default_branch"] = bad
        _refused(fc.parse_project, data, "default_branch")
    for good in ("main", "master", "release/1.x", "trunk"):
        data = copy.deepcopy(project_data)
        data["default_branch"] = good
        assert fc.parse_project(data).default_branch == good


def test_signoff_is_a_real_boolean(project_data: dict) -> None:
    for bad in ("true", 1, 0, None, "yes"):
        data = copy.deepcopy(project_data)
        data["signoff"] = bad
        _refused(fc.parse_project, data, "signoff")
    project_data["signoff"] = False
    assert fc.parse_project(project_data).signoff is False


def test_hygiene_identifiers(project_data: dict) -> None:
    project_data["hygiene"] = []
    assert fc.parse_project(project_data).hygiene == ()  # empty by default is valid
    for bad, field in (
        ("acme", "hygiene"),
        ([""], "hygiene[0]"),
        (["ok", " "], "hygiene[1]"),
        ([3], "hygiene[0]"),
        (["dup", "DUP"], "hygiene[1]"),
    ):
        data = copy.deepcopy(project_data)
        data["hygiene"] = bad
        _refused(fc.parse_project, data, field)


def test_unknown_project_keys_are_refused(project_data: dict) -> None:
    project_data["licence"] = "mit"
    _refused(fc.parse_project, project_data, "licence")
    project_data = _project_data()
    project_data["owner"]["phone"] = "1"
    _refused(fc.parse_project, project_data, "owner.phone")


def test_a_non_object_project_is_refused() -> None:
    for bad in ([], "x", 3, None):
        with pytest.raises(fc.ConfigError) as caught:
            fc.parse_project(bad)
        assert caught.value.field == "<root>"


def test_the_error_message_names_the_field_and_says_what_is_wrong(project_data: dict) -> None:
    project_data["slug"] = "Bad Slug"
    err = _refused(fc.parse_project, project_data, "slug")
    assert "slug" in str(err) and "lower-case" in str(err)


# --------------------------------------------------------------------------- review hardening
_AWKWARD = 'quo"te back\\slash tab\t newline\n bell\x07 del\x7f é中😀 end'


def test_the_emitter_round_trips_awkward_text_in_overrides(framework_data: dict) -> None:
    """Emoji, quotes and backslashes must survive dump then parse (the emitter once wrote invalid TOML for emoji)."""
    reason = 'quo"te back\\slash é中😀 end'
    framework_data["overrides"] = [{"target": "tools/check_docs.py", "reason": reason}]
    config = fc.parse_framework(framework_data)
    assert fc.parse_framework_text(fc.dump_framework(config)) == config


def test_the_toml_string_escaper_handles_every_control_character() -> None:
    import tomllib

    for code in range(0x80):
        text = f"a{chr(code)}b"
        assert tomllib.loads("v = " + fc._toml_string(text))["v"] == text, hex(code)
    assert tomllib.loads("v = " + fc._toml_string(_AWKWARD))["v"] == _AWKWARD


def test_control_characters_are_refused_in_single_line_text(framework_data: dict, project_data: dict) -> None:
    for bad in ("a\nb", "a\tb", "a\x00b", "a\x07b", "a\x7fb"):
        data = copy.deepcopy(framework_data)
        data["overrides"] = [{"target": "tools/x.py", "reason": bad}]
        _refused(fc.parse_framework, data, "overrides[0].reason")
        data = copy.deepcopy(framework_data)
        data["overrides"] = [{"target": bad, "reason": "r"}]
        _refused(fc.parse_framework, data, "overrides[0].target")
        data = copy.deepcopy(project_data)
        data["name"] = bad
        _refused(fc.parse_project, data, "name")
        data = copy.deepcopy(project_data)
        data["owner"]["name"] = bad
        _refused(fc.parse_project, data, "owner.name")
        data = copy.deepcopy(project_data)
        data["hygiene"] = [bad]
        _refused(fc.parse_project, data, "hygiene[0]")


def test_a_lone_surrogate_is_refused_not_carried_to_a_write(project_data: dict) -> None:
    project_data["name"] = "bad \ud800 name"
    _refused(fc.parse_project, project_data, "name")


def test_the_trailer_breaking_characters_are_refused_in_names_and_emails(project_data: dict) -> None:
    for bad in ("A <b>", "A > B", "<x>"):
        data = copy.deepcopy(project_data)
        data["owner"]["name"] = bad
        _refused(fc.parse_project, data, "owner.name")
        data = copy.deepcopy(project_data)
        data["name"] = bad
        _refused(fc.parse_project, data, "name")
    for bad in ("a<b@c.d", "a>b@c.d", "a,b@c.d", "a;b@c.d", 'a"b@c.d', "a'b@c.d", "a@c.d>", "a@c_d.e", "a@c.d\n"):
        data = copy.deepcopy(project_data)
        data["owner"]["email"] = bad
        _refused(fc.parse_project, data, "owner.email")
    project_data["owner"]["email"] = "ada.l+tag@sub-domain.example.org"
    assert fc.parse_project(project_data).owner.email == "ada.l+tag@sub-domain.example.org"


def test_the_default_branch_is_safe_to_write_into_a_workflow_and_a_hook(project_data: dict) -> None:
    for bad in (
        'main"; curl x|sh #',
        "a,b]",
        "$(x)",
        "a`b`",
        "a'b",
        "a;b",
        "a|b",
        "a&b",
        "a<b",
        "a>b",
        "a#b",
        "a{b",
        "a}b",
        "HEAD",
        "a/.b",
        "a.lock/x",
        "a/./b",
        "a//b",
        "a@{b",
        "a.",
        ".a",
        "a\nb",
        "ünï",
    ):
        data = copy.deepcopy(project_data)
        data["default_branch"] = bad
        _refused(fc.parse_project, data, "default_branch")
    for good in ("main", "release/1.x", "feature/a_b-c.d", "v1.2"):
        data = copy.deepcopy(project_data)
        data["default_branch"] = good
        assert fc.parse_project(data).default_branch == good


def test_the_version_digits_are_ascii(framework_data: dict) -> None:
    framework_data["framework"]["template_version"] = "١.٢.٣"
    _refused(fc.parse_framework, framework_data, "framework.template_version")


def test_hostile_nesting_and_paths_are_config_errors(tmp_path: Path) -> None:
    with pytest.raises(fc.ConfigError):
        fc.parse_project_text("[" * 200000)
    with pytest.raises(fc.ConfigError):
        fc.parse_framework_text("a=" + "[" * 200000)
    with pytest.raises(fc.ConfigError):
        fc.load_project(Path("a\0b"))
    with pytest.raises(fc.ConfigError):
        fc.load_project(tmp_path)  # a directory


def test_duplicate_json_keys_and_json_constants_are_refused(project_data: dict) -> None:
    text = fc.dump_project(fc.parse_project(project_data))
    duplicated = text.replace('"slug": "example-project",', '"slug": "example-project", "slug": "other",')
    assert duplicated != text
    with pytest.raises(fc.ConfigError) as caught:
        fc.parse_project_text(duplicated)
    assert "slug" in str(caught.value)
    for constant in (
        "NaN",
        "Infinity",
        "-Infinity",
    ):  # non-standard JSON constants land in a typed field and fail there
        with pytest.raises(fc.ConfigError):
            fc.parse_project_text(text.replace("true", constant))


def test_a_nested_duplicate_key_is_reported_with_its_full_path(project_data: dict) -> None:
    text = fc.dump_project(fc.parse_project(project_data))
    nested = text.replace('"name": "Ada Example",', '"name": "Ada Example", "name": "Other",')
    assert nested != text
    with pytest.raises(fc.ConfigError) as caught:
        fc.parse_project_text(nested)
    assert caught.value.field == "owner.name"
    in_list = text.replace('"hygiene": [', '"hygiene": [{"a": 1, "a": 2}, ')
    with pytest.raises(fc.ConfigError) as caught:
        fc.parse_project_text(in_list)
    assert caught.value.field == "hygiene[0].a"


def test_email_structure_not_just_its_alphabet(project_data: dict) -> None:
    for bad in (
        ".@-host.example",
        "a..b@host-.example",
        ".a@b.c",
        "a.@b.c",
        "a@-b.c",
        "a@b-.c",
        "a@b..c",
        "a@.b.c",
        "a@b.c.",
        "a@b.-c.d",
    ):
        data = copy.deepcopy(project_data)
        data["owner"]["email"] = bad
        _refused(fc.parse_project, data, "owner.email")
    for good in ("ada@example.org", "a.b.c@d.e", "a+b@x-y.z-w.org", "a_b%c@1.2", "x@a.b.c.d"):
        data = copy.deepcopy(project_data)
        data["owner"]["email"] = good
        assert fc.parse_project(data).owner.email == good


def test_a_large_hygiene_list_validates_in_linear_time(project_data: dict) -> None:
    import time

    project_data["hygiene"] = [f"identifier-{n}" for n in range(20000)]
    started = time.perf_counter()
    assert len(fc.parse_project(project_data).hygiene) == 20000
    assert time.perf_counter() - started < 20.0  # a quadratic version took minutes at this size
    project_data["hygiene"].append("IDENTIFIER-7")
    _refused(fc.parse_project, project_data, "hygiene[20000]")


def test_config_errors_copy_and_pickle(project_data: dict) -> None:
    import pickle

    project_data["slug"] = "Bad"
    err = _refused(fc.parse_project, project_data, "slug").with_source("answers.json")
    for clone in (copy.copy(err), copy.deepcopy(err), pickle.loads(pickle.dumps(err))):
        assert isinstance(clone, fc.ConfigError)
        assert (clone.field, clone.message, clone.source) == (err.field, err.message, err.source)
        assert str(clone) == str(err)
    assert not isinstance(err, ValueError)  # a caller's `except ValueError` must not swallow it


def test_the_loader_chains_the_real_cause_not_itself(tmp_path: Path) -> None:
    with pytest.raises(fc.ConfigError) as caught:
        fc.load_project(tmp_path / "missing.json")
    assert caught.value.__cause__ is not caught.value
    assert isinstance(caught.value.__cause__, OSError)


def test_the_handoff_limit_boundaries_and_the_lower_direction(framework_data: dict) -> None:
    for edge in (20, 1000):
        data = copy.deepcopy(framework_data)
        data["checks"]["handoff_max_lines"] = edge
        data["overrides"] = [{"target": "handoff_max_lines", "reason": "an edge"}]
        assert fc.parse_framework(data).handoff_max_lines == edge
    framework_data["checks"]["handoff_max_lines"] = 100  # lowering needs the reason too
    _refused(fc.parse_framework, framework_data, "checks.handoff_max_lines")
    framework_data["checks"]["handoff_max_lines"] = 150
    framework_data["overrides"] = [{"target": "handoff_max_lines", "reason": "kept for later"}]
    assert fc.parse_framework(framework_data).handoff_max_lines == 150  # an override at the default is harmless


def test_overrides_are_normalised_so_one_file_cannot_be_overridden_twice(framework_data: dict) -> None:
    for bad in ("./a.py", "a//b.py", "a/./b.py", "."):
        data = copy.deepcopy(framework_data)
        data["overrides"] = [{"target": bad, "reason": "r"}]
        _refused(fc.parse_framework, data, "overrides[0].target")


def test_every_known_harness_is_accepted(framework_data: dict) -> None:
    framework_data["harnesses"]["enabled"] = ["claude", "gemini", "copilot", "codex", "cursor"]
    assert fc.parse_framework(framework_data).harnesses == ("claude", "gemini", "copilot", "codex", "cursor")
    for bad in ([["claude"]], [{"a": 1}], [3]):
        data = copy.deepcopy(framework_data)
        data["harnesses"]["enabled"] = bad
        _refused(fc.parse_framework, data, "harnesses.enabled")


def test_hand_written_toml_with_comments_and_no_overrides_parses() -> None:
    text = (
        "# written by a person\n"
        '[framework]\ntemplate_version = "1.2.3"  # trailing comment\n\n'
        "[modules]\n"
        + "".join(f'{name} = "{"on" if name == "core" else "off"}"\n' for name in fc.MODULES)
        + "\n[harnesses]\nenabled = []\n\n[checks]\nhandoff_max_lines = 150\n"
    )
    config = fc.parse_framework_text(text)
    assert config.overrides == () and config.harnesses == () and config.template_version == "1.2.3"


def test_the_dumpers_refuse_an_invalid_config_instead_of_writing_it(framework_data: dict, project_data: dict) -> None:
    config = fc.parse_framework(framework_data)
    broken = fc.FrameworkConfig(config.template_version, {"core": "on"}, (), 150, ())
    with pytest.raises(fc.ConfigError):
        fc.dump_framework(broken)
    project = fc.parse_project(project_data)
    with pytest.raises(fc.ConfigError):
        fc.dump_project(fc.ProjectConfig("", project.slug, project.owner, project.default_branch, True, ()))


def test_the_modules_view_is_read_only(framework_data: dict) -> None:
    config = fc.parse_framework(framework_data)
    with pytest.raises(TypeError):
        config.modules["core"] = "off"  # type: ignore[index]


def test_main_reports_a_bad_file_with_an_exit_code(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    good = tmp_path / "project.json"
    good.write_text(json.dumps(_project_data()), encoding="utf-8")
    assert fc.main([str(good)]) == 0
    bad = tmp_path / "bad.json"
    bad.write_text("{}", encoding="utf-8")
    assert fc.main([str(bad)]) == 1
    assert "bad.json" in capsys.readouterr().err


# --------------------------------------------------------------------------- the [docs] table
def test_an_absent_docs_table_is_the_frameworks_own_layout(framework_data: dict) -> None:
    config = fc.parse_framework(framework_data)
    assert config.docs == fc.DocsConfig()
    assert config.docs.handoff == "Docs/handoffs/CURRENT.md" and config.docs.exclude_parts[0] == ".claude"
    assert "[docs]" not in fc.dump_framework(config)  # defaults are not written out


def test_a_docs_table_round_trips_and_only_its_differences_are_written(framework_data: dict) -> None:
    framework_data["docs"] = {
        "exclude_parts": [".git", "vendor"],
        "handoff": "Docs/handoffs/NOW.md",
        "board_sections": ["## Gates", "## Icebox"],
        "status_exempt": ["Docs/design/old.md"],
    }
    config = fc.parse_framework(framework_data)
    assert config.docs.exclude_parts == (".git", "vendor") and config.docs.handoff == "Docs/handoffs/NOW.md"
    assert config.docs.board_sections == ("## Gates", "## Icebox")
    assert config.docs.board == "Docs/plan/BOARD.md"  # untouched keys keep their default
    text = fc.dump_framework(config)
    assert text.count("[docs]") == 1 and "glossary" not in text and "board =" not in text
    assert fc.parse_framework_text(text) == config
    assert fc.dump_framework(fc.parse_framework_text(text)) == text


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("handoff", "/etc/handoff.md"),
        ("handoff", "Docs/../x.md"),
        ("handoff", "C:/x.md"),
        ("handoff", "Docs\\x.md"),
        ("handoff", "Docs//x.md"),
        ("handoff", ""),
        ("handoff", 3),
        ("board", "Docs/plan/"),
        ("governed_dirs", ["Docs", "Docs"]),
        ("governed_dirs", "Docs"),
        ("governed_dirs", ["../up"]),
        ("exclude_parts", ["a/b"]),
        ("exclude_parts", [".."]),
        ("exclude_parts", [3]),
        ("board_sections", ["Gates"]),
        ("board_sections", ["##"]),
        ("status_exempt", [None]),
        ("governed_dirs", []),
        ("board_sections", []),
    ],
)
def test_a_bad_docs_value_is_refused_naming_its_field(framework_data: dict, key: str, value: object) -> None:
    framework_data["docs"] = {key: value}
    with pytest.raises(fc.ConfigError) as caught:
        fc.parse_framework(framework_data)
    assert caught.value.field.startswith(f"docs.{key}"), str(caught.value)


def test_an_unknown_docs_key_is_refused_not_ignored(framework_data: dict) -> None:
    framework_data["docs"] = {"handof": "Docs/x.md"}
    error = _refused(fc.parse_framework, framework_data, "docs.handof")
    assert "unknown key" in str(error)


def test_a_docs_table_must_be_a_table(framework_data: dict) -> None:
    framework_data["docs"] = ["Docs"]
    _refused(fc.parse_framework, framework_data, "docs")


def test_the_dumper_refuses_a_docs_config_the_parser_would_refuse(framework_data: dict) -> None:
    config = fc.parse_framework(framework_data)
    broken = fc.FrameworkConfig(
        config.template_version, config.modules, config.harnesses, 150, (), fc.DocsConfig(handoff="/abs.md")
    )
    with pytest.raises(fc.ConfigError):
        fc.dump_framework(broken)


@pytest.mark.skipif(
    (ROOT / "project.json").exists(),
    reason="reads the framework file as the payload ships it; a made repository owns it",
)
def test_the_docs_default_matches_what_the_payloads_own_framework_file_says() -> None:
    # The shipped framework.toml carries no [docs] table: a made repository starts on the defaults.
    config = fc.load_framework(ROOT / "framework.toml")
    assert config.docs == fc.DocsConfig()


def test_the_part_two_docs_keys_round_trip(framework_data: dict) -> None:
    framework_data["docs"] = {
        "terms_dirs": ["Docs/design"],
        "terms_grandfathered": ["Docs/design/old.md"],
        "orphan_allow": ["Docs/README.md", "Docs/entry.md"],
        "retired_exempt_dirs": ["Docs/journal"],
        "instructions_allow": ["Docs/sub/AGENTS.md"],
    }
    config = fc.parse_framework(framework_data)
    assert config.docs.terms_dirs == ("Docs/design",) and config.docs.instructions_allow == ("Docs/sub/AGENTS.md",)
    text = fc.dump_framework(config)
    assert fc.parse_framework_text(text) == config and fc.dump_framework(fc.parse_framework_text(text)) == text


@pytest.mark.parametrize(
    "key", ["terms_dirs", "terms_grandfathered", "orphan_allow", "retired_exempt_dirs", "instructions_allow"]
)
def test_the_part_two_docs_keys_refuse_a_bad_path_and_a_duplicate(framework_data: dict, key: str) -> None:
    for bad in (["/abs.md"], ["a/../b.md"], ["a.md", "a.md"], "a.md"):
        framework_data["docs"] = {key: bad}
        with pytest.raises(fc.ConfigError) as caught:
            fc.parse_framework(framework_data)
        assert caught.value.field.startswith(f"docs.{key}")


# --------------------------------------------------------------------------- [[hygiene_allow]]
def test_an_absent_hygiene_allow_is_an_empty_list_and_is_not_written(framework_data: dict) -> None:
    config = fc.parse_framework(framework_data)
    assert config.hygiene_allow == () and "hygiene_allow" not in fc.dump_framework(config)


def test_hygiene_allow_round_trips_in_order_with_its_reasons(framework_data: dict) -> None:
    framework_data["hygiene_allow"] = [
        {"path": "vendor", "reason": "a vendored tree"},
        {"path": "docs/old.md", "reason": r'quotes " and \ survive'},
    ]
    config = fc.parse_framework(framework_data)
    assert config.hygiene_allow == (
        fc.HygieneAllow("vendor", "a vendored tree"),
        fc.HygieneAllow("docs/old.md", r'quotes " and \ survive'),
    )
    text = fc.dump_framework(config)
    assert text.count("[[hygiene_allow]]") == 2
    assert fc.parse_framework_text(text) == config and fc.dump_framework(fc.parse_framework_text(text)) == text


@pytest.mark.parametrize(
    ("entry", "field"),
    [
        ({"path": "vendor"}, "hygiene_allow[0].reason"),
        ({"reason": "why"}, "hygiene_allow[0].path"),
        ({"path": "vendor", "reason": ""}, "hygiene_allow[0].reason"),
        ({"path": "vendor", "reason": "  "}, "hygiene_allow[0].reason"),
        ({"path": "/abs", "reason": "x"}, "hygiene_allow[0].path"),
        ({"path": "a/../b", "reason": "x"}, "hygiene_allow[0].path"),
        ({"path": "vendor/", "reason": "x"}, "hygiene_allow[0].path"),
        ({"path": "vendor", "reason": "x", "extra": 1}, "hygiene_allow[0].extra"),
        ("vendor", "hygiene_allow[0]"),
    ],
)
def test_a_bad_hygiene_allow_entry_is_refused_naming_its_field(framework_data: dict, entry: object, field: str) -> None:
    framework_data["hygiene_allow"] = [entry]
    _refused(fc.parse_framework, framework_data, field)


def test_hygiene_allow_must_be_a_list_and_a_path_may_not_repeat(framework_data: dict) -> None:
    framework_data["hygiene_allow"] = {"path": "vendor", "reason": "x"}
    _refused(fc.parse_framework, framework_data, "hygiene_allow")
    framework_data["hygiene_allow"] = [{"path": "vendor", "reason": "x"}, {"path": "vendor", "reason": "y"}]
    _refused(fc.parse_framework, framework_data, "hygiene_allow[1].path")


# --------------------------------------------------------------------------- the [layers] table
def test_no_layers_table_means_no_layers_and_none_is_written(framework_data: dict) -> None:
    config = fc.parse_framework(framework_data)
    assert config.layers is None
    assert "[layers]" not in fc.dump_framework(config)


def test_a_layers_table_round_trips_with_only_what_it_says(framework_data: dict) -> None:
    framework_data["layers"] = {"order": ["core", "app", "ui"], "pure": ["core"], "unlayered": ["scripts_lib"]}
    config = fc.parse_framework(framework_data)
    assert config.layers == fc.LayersConfig(("core", "app", "ui"), ("core",), ("scripts_lib",))
    text = fc.dump_framework(config)
    assert text.count("[layers]") == 1 and 'order = ["core", "app", "ui"]' in text and 'pure = ["core"]' in text
    assert fc.parse_framework_text(text) == config
    assert fc.dump_framework(fc.parse_framework_text(text)) == text


def test_pure_and_unlayered_default_to_empty_and_are_not_written(framework_data: dict) -> None:
    framework_data["layers"] = {"order": ["core"]}
    config = fc.parse_framework(framework_data)
    assert config.layers == fc.LayersConfig(("core",), (), ())
    text = fc.dump_framework(config)
    assert "pure" not in text and "unlayered" not in text
    assert fc.parse_framework_text(text) == config


@pytest.mark.parametrize(
    ("layers", "field"),
    [
        ({}, "layers.order"),  # order is required
        ({"order": []}, "layers.order"),
        ({"order": "core"}, "layers.order"),
        ({"order": ["core", "core"]}, "layers.order"),
        ({"order": ["Core"]}, "layers.order[0]"),
        ({"order": ["9lives"]}, "layers.order[0]"),
        ({"order": ["with-hyphen"]}, "layers.order[0]"),
        ({"order": ["class"]}, "layers.order[0]"),
        ({"order": ["a.b"]}, "layers.order[0]"),
        ({"order": [3]}, "layers.order[0]"),
        ({"order": ["core"], "pure": ["app"]}, "layers.pure"),
        ({"order": ["core"], "pure": ["core", "core"]}, "layers.pure"),
        ({"order": ["core"], "unlayered": ["core"]}, "layers.unlayered"),
        ({"order": ["core"], "unlayered": "x"}, "layers.unlayered"),
        ({"order": ["core"], "mystery": []}, "layers.mystery"),
    ],
)
def test_each_bad_layers_table_is_refused_naming_the_field(framework_data: dict, layers: dict, field: str) -> None:
    framework_data["layers"] = layers
    _refused(fc.parse_framework, framework_data, field)


def test_a_layers_table_that_is_not_a_table_is_refused(framework_data: dict) -> None:
    framework_data["layers"] = ["core"]
    _refused(fc.parse_framework, framework_data, "layers")


def test_the_dumper_refuses_a_layers_config_the_parser_would_refuse() -> None:
    config = fc.parse_framework(_framework_data())
    bad = fc.FrameworkConfig(
        config.template_version,
        config.modules,
        config.harnesses,
        config.handoff_max_lines,
        config.overrides,
        layers=fc.LayersConfig(("core",), ("app",)),
    )
    with pytest.raises(fc.ConfigError, match="layers.pure"):
        fc.dump_framework(bad)


# --------------------------------------------------------------------------- the upstream and the age window
def test_upstream_and_max_age_days_default_to_none_and_fourteen_and_are_not_written(framework_data: dict) -> None:
    config = fc.parse_framework(framework_data)
    assert config.upstream is None
    assert config.max_age_days == fc.DEFAULT_MAX_AGE_DAYS == 14
    text = fc.dump_framework(config)
    assert "upstream" not in text and "max_age_days" not in text


def test_upstream_and_max_age_days_round_trip(framework_data: dict) -> None:
    framework_data["framework"]["upstream"] = "HogJonny-AMZN/ai-first-template"
    framework_data["framework"]["max_age_days"] = 30
    config = fc.parse_framework(framework_data)
    assert (config.upstream, config.max_age_days) == ("HogJonny-AMZN/ai-first-template", 30)
    again = fc.parse_framework_text(fc.dump_framework(config))
    assert again == config
    text = fc.dump_framework(config)
    assert 'upstream = "HogJonny-AMZN/ai-first-template"' in text
    assert "max_age_days = 30" in text


@pytest.mark.parametrize(
    "value", ["", "template", "a/b/c", "owner/", "/repo", "own er/repo", "../x", "owner/repo name", 5, None, ["a/b"]]
)
def test_an_upstream_must_be_owner_slash_repo(framework_data: dict, value: object) -> None:
    framework_data["framework"]["upstream"] = value
    _refused(fc.parse_framework, framework_data, "framework.upstream")


@pytest.mark.parametrize("value", [0, -1, 366, True, 1.5, "14", None])
def test_max_age_days_must_be_a_whole_number_of_days_from_one_to_a_year(framework_data: dict, value: object) -> None:
    framework_data["framework"]["max_age_days"] = value
    _refused(fc.parse_framework, framework_data, "framework.max_age_days")


@pytest.mark.parametrize("value", [1, 14, 365])
def test_the_ends_of_the_age_window_are_allowed(framework_data: dict, value: int) -> None:
    framework_data["framework"]["max_age_days"] = value
    assert fc.parse_framework(framework_data).max_age_days == value


def test_the_dumper_refuses_an_upstream_the_parser_would(framework_data: dict) -> None:
    config = fc.parse_framework(framework_data)
    bad = fc.FrameworkConfig(
        config.template_version, config.modules, config.harnesses, 150, (), upstream="not a repository"
    )
    with pytest.raises(fc.ConfigError, match="framework.upstream"):
        fc.dump_framework(bad)


@pytest.mark.parametrize("text", ["a.md", "Docs/standards/python.md", ".github/workflows/ci.yml", "a b/c d.md"])
def test_a_normalised_relative_path_is_accepted(text: str) -> None:
    assert fc.is_relative_path(text)


@pytest.mark.parametrize(
    "text", ["", ".", "..", "../x", "/x", "a//b", "a/./b", "a/../b", "a\b", "C:/x", "a/", "a\nb", "a\x00b", "a\x7fb"]
)
def test_anything_else_is_not_a_relative_path(text: str) -> None:
    assert not fc.is_relative_path(text)


# --------------------------------------------------------------------------- [[people]], the roster
def _person(**changes: object) -> dict:
    person: dict = {
        "login": "HogJonny-AMZN",
        "name": "Jonny",
        "role": "owner",
        "emails": ["jonny@example.org"],
    }
    person.update(changes)
    return person


def test_an_absent_roster_is_an_empty_tuple_and_is_not_written(framework_data: dict) -> None:
    config = fc.parse_framework(framework_data)
    assert config.people == () and "[[people]]" not in fc.dump_framework(config)


def test_a_roster_round_trips_in_the_files_order_with_every_field(framework_data: dict) -> None:
    framework_data["people"] = [
        _person(),
        {"login": "ada-l", "name": "Ada", "role": "contributor"},
        _person(login="b2", name="Bo", role="contributor", emails=["bo@example.org", "bo@work.example.org"]),
    ]
    config = fc.parse_framework(framework_data)
    assert config.people == (
        fc.Person("HogJonny-AMZN", "Jonny", "owner", ("jonny@example.org",)),
        fc.Person("ada-l", "Ada", "contributor", ()),
        fc.Person("b2", "Bo", "contributor", ("bo@example.org", "bo@work.example.org")),
    )
    text = fc.dump_framework(config)
    assert text.count("[[people]]") == 3 and fc.parse_framework_text(text) == config
    assert fc.dump_framework(fc.parse_framework_text(text)) == text


def test_a_person_without_emails_writes_no_emails_line(framework_data: dict) -> None:
    framework_data["people"] = [{"login": "ada", "name": "Ada", "role": "owner"}]
    assert "emails" not in fc.dump_framework(fc.parse_framework(framework_data))


@pytest.mark.parametrize(
    ("entry", "field"),
    [
        (_person(extra=1), "people[0].extra"),
        ({"name": "x", "role": "owner"}, "people[0].login"),
        ({"login": "x", "role": "owner"}, "people[0].name"),
        ({"login": "x", "name": "x"}, "people[0].role"),
        (_person(login=""), "people[0].login"),
        (_person(login="-ab"), "people[0].login"),
        (_person(login="ab-"), "people[0].login"),
        (_person(login="a--b"), "people[0].login"),
        (_person(login="a_b"), "people[0].login"),
        (_person(login="a b"), "people[0].login"),
        (_person(login="a" * 40), "people[0].login"),
        (_person(login=7), "people[0].login"),
        (_person(name=""), "people[0].name"),
        (_person(name="  "), "people[0].name"),
        (_person(role="admin"), "people[0].role"),
        (_person(role="Owner"), "people[0].role"),
        (_person(emails="a@b.org"), "people[0].emails"),
        (_person(emails=[""]), "people[0].emails[0]"),
        (_person(emails=["not an email"]), "people[0].emails[0]"),
        (_person(emails=[5]), "people[0].emails[0]"),
        ("HogJonny-AMZN", "people[0]"),
    ],
)
def test_a_bad_person_is_refused_naming_its_field(framework_data: dict, entry: object, field: str) -> None:
    framework_data["people"] = [entry]
    _refused(fc.parse_framework, framework_data, field)


def test_a_login_of_thirty_nine_characters_is_allowed(framework_data: dict) -> None:
    framework_data["people"] = [_person(login="a" * 39)]
    assert fc.parse_framework(framework_data).people[0].login == "a" * 39


def test_two_logins_equal_ignoring_case_are_refused_at_the_second(framework_data: dict) -> None:
    framework_data["people"] = [_person(), _person(login="hogjonny-amzn", role="contributor")]
    _refused(fc.parse_framework, framework_data, "people[1].login")


def test_a_roster_needs_an_owner_and_must_be_a_list(framework_data: dict) -> None:
    framework_data["people"] = [_person(role="contributor")]
    _refused(fc.parse_framework, framework_data, "people")
    framework_data["people"] = {"login": "x"}
    _refused(fc.parse_framework, framework_data, "people")
    framework_data["people"] = []
    _refused(fc.parse_framework, framework_data, "people")


def test_the_dumper_refuses_a_roster_the_parser_would(framework_data: dict) -> None:
    config = fc.parse_framework(framework_data)
    bad = fc.FrameworkConfig(
        config.template_version, config.modules, config.harnesses, 150, (), people=(fc.Person("x y", "X", "owner", ()),)
    )
    with pytest.raises(fc.ConfigError, match="people"):
        fc.dump_framework(bad)


@pytest.mark.parametrize("where", ["framework.toml", "../framework.toml"])
def test_the_frameworks_own_configuration_files_still_load(where: str) -> None:
    path = (ROOT / where).resolve()
    if not path.exists() or (where.startswith("..") and not (ROOT.parent / "payload").exists()):
        pytest.skip(f"{where} is not here")
    assert fc.load_framework(path).people is not None


def test_an_email_may_not_be_on_the_roster_twice_ignoring_case(framework_data: dict) -> None:
    framework_data["people"] = [_person(emails=["a@b.org", "A@B.org"])]
    _refused(fc.parse_framework, framework_data, "people[0].emails[1]")
    framework_data["people"] = [_person(), _person(login="bo", role="contributor")]
    _refused(fc.parse_framework, framework_data, "people[1].emails[0]")


def test_the_handoff_people_dir_key_round_trips_and_refuses_a_bad_path(framework_data: dict) -> None:
    framework_data["docs"] = {"handoff_people_dir": "Docs/people"}
    config = fc.parse_framework(framework_data)
    assert (
        config.docs.handoff_people_dir == "Docs/people" and fc.DocsConfig().handoff_people_dir == "Docs/handoffs/people"
    )
    text = fc.dump_framework(config)
    assert fc.parse_framework_text(text) == config and 'handoff_people_dir = "Docs/people"' in text
    for bad in ("/abs", "a/../b", 7):
        framework_data["docs"] = {"handoff_people_dir": bad}
        with pytest.raises(fc.ConfigError) as caught:
            fc.parse_framework(framework_data)
        assert caught.value.field == "docs.handoff_people_dir"


def test_the_board_dir_key_round_trips_and_refuses_a_bad_path(framework_data: dict) -> None:
    framework_data["docs"] = {"board_dir": "Docs/rows"}
    config = fc.parse_framework(framework_data)
    assert config.docs.board_dir == "Docs/rows" and fc.DocsConfig().board_dir == "Docs/plan/board"
    text = fc.dump_framework(config)
    assert fc.parse_framework_text(text) == config and 'board_dir = "Docs/rows"' in text
    for bad in ("/abs", "a/../b", 7):
        framework_data["docs"] = {"board_dir": bad}
        with pytest.raises(fc.ConfigError) as caught:
            fc.parse_framework(framework_data)
        assert caught.value.field == "docs.board_dir"
