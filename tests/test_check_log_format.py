"""
Framework: tests for tools/check_log_format.py (no lazy %-format log call; the message is an f-string).
Package: tests/test_check_log_format

The fixtures are the ones the check was first written against, in the repository it came from; each rule has a case that
fails it and one that passes it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

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
specimens = "planned"
lanes = "off"
branch-ownership = "off"
devblog = "off"

[harnesses]
enabled = []

[checks]
handoff_max_lines = 150
"""
sys.path.insert(0, str(ROOT / "tools"))

import check_log_format as clf  # noqa: E402


def _check(line: str) -> list[clf.Finding]:
    return clf.check_source(f"def f():\n    {line}\n")


@pytest.mark.parametrize(
    "line",
    [
        '_LOGGER.info("wrote %s", path)',
        '_LOGGER.warning("%d of %d", a, b)',
        '_LOGGER.error("failed on %s: %s" % (a, b))',
        'logging.debug("value %.2f", x)',
        'logger.info("%(name)s ready", {"name": n})',
        'self._log.exception("boom %r", e)',
        '_LOGGER.fatal("gone %s", why)',
        '_LOGGER.log(logging.INFO, "x %s", value)',
        '_LOGGER.log(logging.INFO, "x %s" % value)',
        '_LOGGER.info("mode %o", mode)',
        '_LOGGER.info("count %u", n)',
        '_LOGGER.info("text %a", s)',
        '_LOGGER.info("pi %.*f", 3, x)',
        '_LOGGER.info("big %ld", n)',
        '_LOGGER.info("pad %-8.3f|", x)',
        '_LOGGER.info("100%%%s", x)',
        'logging.getLogger("a").info("x %s", y)',
        '_LOGGER.info("# lazy-log: %s", value)',
        '_LOGGER.info("wrote %s", path)  # lazy-log:',
        '_LOGGER.info("wrote %s", path)  # lazy-log:   ',
    ],
)
def test_a_lazy_percent_log_call_is_a_finding(line: str) -> None:
    assert [f.line for f in _check(line)] == [2], line


@pytest.mark.parametrize(
    "line",
    [
        '_LOGGER.info(f"wrote {path}")',
        '_LOGGER.info("a plain message")',
        '_LOGGER.info("100%% sure")',
        '_LOGGER.info("100%%s of them", x)',
        '_LOGGER.log(logging.INFO, f"x {value}")',
        '_LOGGER.log(logging.INFO, "no arguments, 100% sure")',
        '_LOGGER.info("100% sure, nothing to format")',
        'registry.info("wrote %s", path)',
        'blog.info("wrote %s", path)',
        'dialog.warning("wrote %s", path)',
        "_LOGGER.debug(i % 10)",
        "_LOGGER.info(str(e))",
        '_LOGGER.info("wrote %s", path)  #   lazy-log: 40 ms a frame',
        '_LOGGER.info("wrote %s", path)  # lazy-log: measured at 40 ms a frame in the cook loop',
        '_LOGGER.info("wrote %s", path)  # noqa: E501  # lazy-log: 40 ms a frame',
    ],
)
def test_f_strings_plain_messages_other_objects_and_marked_hot_paths_pass(line: str) -> None:
    assert _check(line) == [], line


@pytest.mark.parametrize(
    "source",
    [
        'def f():\n    out.info("wrote %s", path)\n',
        'def f():\n    log_it = _LOGGER.info\n    log_it("wrote %s", path)\n',
        'def f():\n    template = "wrote %s"\n    _LOGGER.info(template, path)\n',
    ],
    ids=["another-name", "method-as-variable", "template-in-a-variable"],
)
def test_the_known_gaps_stay_gaps_until_someone_decides_otherwise(source: str) -> None:
    """The module docstring lists these as not seen; a test pins them so closing one is a deliberate change."""
    assert clf.check_source(source) == []


def test_the_wrong_marker_finding_says_what_is_missing() -> None:
    (finding,) = _check('_LOGGER.info("wrote %s", path)  # lazy-log:')
    assert "needs the measurement" in finding.reason
    (finding,) = _check('_LOGGER.info("wrote %s", path)')
    assert "f-string" in finding.reason


def test_a_multi_line_call_is_found_at_its_first_line_and_marked_there() -> None:
    source = 'def f():\n    _LOGGER.info(\n        "a %s and %s",\n        a,\n        b,\n    )\n'
    assert [f.line for f in clf.check_source(source)] == [2]
    marked = source.replace("_LOGGER.info(\n", "_LOGGER.info(  # lazy-log: measured\n")
    assert clf.check_source(marked) == []


def test_a_file_that_does_not_parse_is_a_finding_not_a_pass() -> None:
    (finding,) = clf.check_source("def f(:\n", "bad.py")
    assert finding.path == "bad.py" and "does not parse" in finding.reason
    assert clf.check_source('x = "\x00"\n', "nul.py"), "a null byte must not pass silently either"


def test_findings_come_back_in_line_order_even_when_the_syntax_tree_visits_them_out_of_order() -> None:
    """The tree is walked breadth first, so a call inside a function is visited after a later module-level call."""
    source = 'def f():\n    _LOGGER.info("b %s", x)\n\n\n_LOGGER.info("a %s", y)\n'
    assert [f.line for f in clf.check_source(source)] == [2, 5]


# ---- the tree
def _write(root: Path, rel: str, content: str | bytes) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8", newline="\n")


def test_a_byte_order_mark_does_not_hide_a_lazy_call(tmp_path: Path) -> None:
    _write(tmp_path, "src/bom.py", b'\xef\xbb\xbf_LOGGER.info("x %s", y)\n')
    assert [f.line for f in clf.check_tree(tmp_path)] == [1]


def test_a_file_that_is_not_utf8_is_a_finding_not_a_traceback(tmp_path: Path) -> None:
    _write(tmp_path, "tools/latin.py", b"# caf\xe9\n")
    (finding,) = clf.check_tree(tmp_path)
    assert finding.path == "tools/latin.py" and "cannot be decoded" in finding.reason


def test_every_python_file_is_read_wherever_it_sits(tmp_path: Path) -> None:
    for where in ("a.py", "pkg/b.py", "pkg/deep/c.py", "tools/d.py"):
        _write(tmp_path, where, '_LOGGER.info("x %s", y)\n')
    assert [f.path for f in clf.check_tree(tmp_path)] == ["a.py", "pkg/b.py", "pkg/deep/c.py", "tools/d.py"]


@pytest.mark.parametrize(
    "where", [".venv/lib/x.py", "node_modules/p/x.py", "build/x.py", "dist/x.py", ".git/hooks/x.py"]
)
def test_environments_caches_and_build_output_are_not_scanned(tmp_path: Path, where: str) -> None:
    _write(tmp_path, "ok.py", "x = 1\n")
    _write(tmp_path, where, '_LOGGER.info("x %s", y)\n')
    assert clf.check_tree(tmp_path) == []


def test_the_docs_tables_exclusions_are_honoured_and_a_spike_is_skipped_by_default(tmp_path: Path, capsys) -> None:
    _write(tmp_path, "ok.py", "x = 1\n")
    _write(tmp_path, "Spikes/s/a.py", '_LOGGER.info("x %s", y)\n')
    _write(tmp_path, "vendor/b.py", '_LOGGER.info("x %s", y)\n')
    assert [f.path for f in clf.check_tree(tmp_path, fc_default_exclusions())] == ["vendor/b.py"]
    assert clf.main([str(tmp_path)]) == 1
    assert "vendor/b.py" in capsys.readouterr().out


def fc_default_exclusions() -> tuple[str, ...]:
    import framework_config as fc

    return fc.DocsConfig().exclude_parts


def test_a_scan_that_finds_no_python_is_a_finding(tmp_path: Path) -> None:
    (finding,) = clf.check_tree(tmp_path)
    assert "no Python file found" in finding.reason


def test_a_directory_that_cannot_be_listed_is_a_finding(tmp_path: Path, monkeypatch) -> None:
    _write(tmp_path, "ok.py", "x = 1\n")
    real_walk = clf.os.walk

    def denying_walk(top, onerror=None, **kwargs):
        if onerror is not None:
            onerror(PermissionError(13, "Permission denied", str(Path(top) / "locked")))
        yield from real_walk(top, **kwargs)

    monkeypatch.setattr(clf.os, "walk", denying_walk)
    (finding,) = clf.check_tree(tmp_path)
    assert finding.path == "locked" and "cannot be listed" in finding.reason


def _link(link: Path, target: Path) -> None:
    """``link`` made a symlink to the folder ``target``, or the test skipped where this account cannot make one."""
    try:
        link.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("this account cannot create a symlink")


def test_a_symlinked_folder_is_a_finding_not_a_clean_pass(tmp_path: Path) -> None:
    """``os.walk`` lists a linked folder and never enters it: its calls are unchecked, and the report says so (#78)."""
    root, elsewhere = tmp_path / "repo", tmp_path / "elsewhere"
    _write(root, "ok.py", "x = 1\n")
    _write(elsewhere, "hidden.py", '_LOGGER.info("x %s", y)\n')
    _link(root / "linked", elsewhere)
    (finding,) = clf.check_tree(root)
    assert finding.path == "linked" and "outside the root" in finding.reason, finding


def test_a_link_to_a_folder_inside_the_root_is_read_where_it_points_not_reported(tmp_path: Path) -> None:
    """A venv's ``lib64 -> lib``, or a monorepo's link to a shared folder: its files are read at their target, so the
    link is not source unseen (the deliberate review of the fix for #78)."""
    _write(tmp_path, "pkg/lib/a.py", '_LOGGER.info("x %s", y)\n')
    _link(tmp_path / "pkg" / "lib64", tmp_path / "pkg" / "lib")
    assert [(f.path, f.line) for f in clf.check_tree(tmp_path)] == [("pkg/lib/a.py", 1)]


def _junction(link: Path, target: Path) -> None:
    """``link`` made a Windows junction to ``target``, or the test skipped off Windows or before Python 3.12."""
    if sys.platform != "win32" or not hasattr(Path, "is_junction"):
        pytest.skip("a junction is a Windows folder link, recognised from Python 3.12")
    import _winapi  # noqa: PLC0415 - Windows only

    _winapi.CreateJunction(str(target), str(link))


def test_a_junction_loop_is_one_finding_not_a_walk_round_it(tmp_path: Path) -> None:
    """``os.walk`` follows a junction: a loop would recurse until the path is too long, each file scanned each time."""
    _write(tmp_path, "pkg/a.py", "x = 1\n")
    _junction(tmp_path / "pkg" / "j", tmp_path / "pkg")
    assert clf.check_tree(tmp_path) == []  # the junction leads back inside the root: read where it points


def test_a_junction_out_of_the_root_is_reported_not_followed(tmp_path: Path) -> None:
    root, elsewhere = tmp_path / "repo", tmp_path / "elsewhere"
    _write(root, "ok.py", "x = 1\n")
    _write(elsewhere, "hidden.py", '_LOGGER.info("x %s", y)\n')
    _junction(root / "j", elsewhere)
    (finding,) = clf.check_tree(root)
    assert finding.path == "j" and "outside the root" in finding.reason, finding


def test_a_symlink_loop_is_a_finding(tmp_path: Path) -> None:
    _write(tmp_path, "ok.py", "x = 1\n")
    _link(tmp_path / "loop", tmp_path / "loop")
    (finding,) = clf.check_tree(tmp_path)
    assert finding.path == "loop" and "cannot be read" in finding.reason, finding


def test_a_link_to_a_folder_the_walk_skips_is_reported_not_passed(tmp_path: Path) -> None:
    """Inside the root is not enough: a link to ``build/gen`` points where the walk does not go, so its calls were not
    seen by another path (Copilot on #144)."""
    _write(tmp_path, "build/gen/a.py", '_LOGGER.info("x %s", y)\n')
    _write(tmp_path, "pkg/ok.py", "x = 1\n")
    _link(tmp_path / "pkg" / "gen", tmp_path / "build" / "gen")
    (finding,) = clf.check_tree(tmp_path)
    assert finding.path == "pkg/gen" and "a folder the walk skips" in finding.reason, finding


def _refuse_lstat(monkeypatch: pytest.MonkeyPatch, target: Path) -> None:
    """``Path.lstat`` of ``target`` refused, as a folder that can be listed but not searched refuses it on POSIX."""
    real = Path.lstat

    def lstat(self: Path) -> object:
        if self == target:
            raise PermissionError(13, "Permission denied", str(self))
        return real(self)

    monkeypatch.setattr(Path, "lstat", lstat)


def test_a_folder_whose_kind_cannot_be_read_is_a_finding_not_a_crash(tmp_path: Path, monkeypatch) -> None:
    """Whether an entry is a link is read with ``lstat``, which can be refused: a finding, and not entered (Copilot on
    #144; ledger P-16)."""
    _write(tmp_path, "ok.py", "x = 1\n")
    _write(tmp_path, "pkg/a.py", '_LOGGER.info("x %s", y)\n')
    _refuse_lstat(monkeypatch, tmp_path / "pkg")
    (finding,) = clf.check_tree(tmp_path)
    assert finding.path == "pkg" and "cannot be read" in finding.reason, finding


def test_a_dangling_link_and_a_skipped_linked_folder_are_nothing(tmp_path: Path) -> None:
    """The negative control: a link to nothing holds no calls, and a link where the tree is skipped is skipped."""
    _write(tmp_path, "ok.py", "x = 1\n")
    _link(tmp_path / "gone", tmp_path / "nowhere")
    _write(tmp_path / "outside", "x.py", '_LOGGER.info("x %s", y)\n')
    _link(tmp_path / "node_modules", tmp_path / "outside")
    assert [f for f in clf.check_tree(tmp_path) if f.path != "outside/x.py"] == []


# ---- the command line
def test_main_exits_one_on_a_finding_zero_when_clean_and_two_when_it_cannot_run(tmp_path: Path, capsys) -> None:
    bad = tmp_path / "bad.py"
    bad.write_text('_LOGGER.info("x %s", y)\n', encoding="utf-8")
    assert clf.main([str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "[log-format] bad.py:1: a lazy %-format log call with arguments" in out and "1 finding(s)" in out
    bad.write_text('_LOGGER.info(f"x {y}")\n', encoding="utf-8")
    assert clf.main([str(tmp_path)]) == 0
    assert "clean" in capsys.readouterr().out
    assert clf.main([str(tmp_path / "nowhere")]) == 2
    assert "is not a directory" in capsys.readouterr().err
    assert clf.main(["--bogus"]) == 2 and "usage" in capsys.readouterr().err
    assert clf.main(["a", "b"]) == 2
    (tmp_path / "framework.toml").write_text("not = = toml", encoding="utf-8")
    assert clf.main([str(tmp_path)]) == 2
    assert "cannot run" in capsys.readouterr().err


def test_a_verbose_run_leaves_a_record(tmp_path: Path, caplog) -> None:
    _write(tmp_path, "ok.py", "x = 1\n")
    with caplog.at_level("INFO", logger="tools.check_log_format"):
        assert clf.main(["-v", str(tmp_path)]) == 0
    assert "read 1 Python file(s)" in caplog.text


def test_the_tree_is_clean() -> None:
    """The payload's own tools and tests follow the rule they enforce."""
    bad = clf.check_tree(ROOT, ("Spikes",))
    assert bad == [], "\n".join(str(f) for f in bad)


# --------------------------------------------------------------------------- the review
@pytest.mark.parametrize("error", [RecursionError("depth"), MemoryError("heap")])
def test_a_source_too_deeply_nested_to_parse_is_a_finding_and_the_other_files_are_still_read(
    tmp_path: Path, monkeypatch, error: Exception
) -> None:
    """The first version let a RecursionError out, which ended the scan with a traceback naming no file.

    The parser is made to raise: whether a given input trips the limit depends on the platform's stack (6,000 chained
    additions did on Windows and parsed on Linux), and the rule under test is what the check does when it happens."""
    real_parse = clf.ast.parse

    def parse(source, *args, **kwargs):
        if "deep" in str(source):
            raise error
        return real_parse(source, *args, **kwargs)

    monkeypatch.setattr(clf.ast, "parse", parse)
    deep = "deep = 1\n"
    (finding,) = clf.check_source(deep, "deep.py")
    assert finding.path == "deep.py" and "does not parse" in finding.reason
    assert type(error).__name__ in finding.reason
    _write(tmp_path, "deep.py", deep)
    _write(tmp_path, "other.py", '_LOGGER.info("x %s", y)\n')
    assert sorted(f.path for f in clf.check_tree(tmp_path)) == ["deep.py", "other.py"]


@pytest.mark.parametrize(
    "line",
    [
        'app_log.info("x %s", y)',
        'my_log.warning("x %s", y)',
        'logger2.error("x %s", y)',
        'self.module_logger.info("x %s", y)',
    ],
)
def test_more_ways_of_naming_a_logger_are_seen(line: str) -> None:
    assert [f.line for f in _check(line)] == [2], line


@pytest.mark.parametrize(
    "line",
    [
        'dialog.info("x %s", y)',
        'blog.info("x %s", y)',
        'catalog.warning("x %s", y)',
        'obj.notgetLogger("a").info("x %s", y)',
        'x.getLoggerX("a").info("x %s", y)',
        'logs.info("x %s", y)',
    ],
)
def test_names_that_only_look_like_loggers_are_not(line: str) -> None:
    assert _check(line) == [], line


@pytest.mark.parametrize("level", ["debug", "info", "warning", "warn", "error", "exception", "critical", "fatal"])
def test_every_logging_level_is_checked(level: str) -> None:
    assert [f.line for f in _check(f'_LOGGER.{level}("x %s", y)')] == [2]


@pytest.mark.parametrize(
    "conversion", ["%c", "%e", "%x", "%X", "%E", "%g", "%G", "%i", "%#x", "%05d", "% d", "%+d", "%*d"]
)
def test_every_percent_conversion_counts_as_a_placeholder(conversion: str) -> None:
    assert [f.line for f in _check(f'_LOGGER.info("v {conversion}", y)')] == [2], conversion


def test_string_concatenation_and_format_calls_are_not_percent_formatting() -> None:
    assert _check('_LOGGER.info("a" + x)') == []
    assert _check('_LOGGER.info("a {}".format(x))') == []
    assert _check('_LOGGER.info("a " "b")') == []


@pytest.mark.parametrize("where", ["pkg/build/mod.py", "pkg/dist/mod.py", "pkg/venv/mod.py"])
def test_build_dist_and_venv_are_skipped_only_at_the_top(tmp_path: Path, where: str) -> None:
    _write(tmp_path, where, '_LOGGER.info("x %s", y)\n')
    assert [f.path for f in clf.check_tree(tmp_path)] == [where]


@pytest.mark.parametrize(
    "where", ["build/mod.py", "dist/mod.py", "venv/mod.py", "a/site-packages/x.py", "a/__pycache__/x.py"]
)
def test_build_output_and_installed_packages_are_skipped(tmp_path: Path, where: str) -> None:
    _write(tmp_path, "ok.py", "x = 1\n")
    _write(tmp_path, where, '_LOGGER.info("x %s", y)\n')
    assert clf.check_tree(tmp_path) == []


def test_a_coding_declaration_is_honoured_and_a_bad_one_is_a_finding(tmp_path: Path) -> None:
    _write(tmp_path, "latin.py", b"# -*- coding: latin-1 -*-\n_LOGGER.info('x %s', y)  # caf\xe9\n")
    assert [(f.path, f.line) for f in clf.check_tree(tmp_path)] == [("latin.py", 2)]  # found, not 'cannot be decoded'
    _write(tmp_path, "bad.py", b"# -*- coding: no-such-codec -*-\nx = 1\n")
    found = {f.path: f.reason for f in clf.check_tree(tmp_path)}
    assert "cannot be decoded" in found["bad.py"]


def test_pyw_is_read_and_other_extensions_are_not(tmp_path: Path) -> None:
    _write(tmp_path, "gui.pyw", '_LOGGER.info("x %s", y)\n')
    _write(tmp_path, "types.pyi", '_LOGGER.info("x %s", y)\n')
    _write(tmp_path, "ok.py", "x = 1\n")
    assert [f.path for f in clf.check_tree(tmp_path)] == ["gui.pyw"]


def test_a_file_that_cannot_be_read_is_a_finding(tmp_path: Path, monkeypatch) -> None:
    _write(tmp_path, "locked.py", "x = 1\n")
    real = Path.read_bytes

    def deny(self: Path) -> bytes:
        if self.name == "locked.py":
            raise PermissionError(13, "Permission denied")
        return real(self)

    monkeypatch.setattr(Path, "read_bytes", deny)
    (finding,) = clf.check_tree(tmp_path)
    assert finding.path == "locked.py" and "cannot be read" in finding.reason


def test_main_honours_the_docs_tables_exclusions_and_a_custom_list_replaces_the_default(tmp_path: Path, capsys) -> None:
    _write(tmp_path, "ok.py", "x = 1\n")
    _write(tmp_path, "Spikes/s/a.py", '_LOGGER.info("x %s", y)\n')
    _write(tmp_path, "vendor/b.py", '_LOGGER.info("x %s", y)\n')
    assert clf.main([str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "vendor/b.py" in out and "Spikes" not in out  # the default exclusions keep spikes out
    configured = FRAMEWORK + '\n[docs]\nexclude_parts = ["vendor"]\n'
    (tmp_path / "framework.toml").write_text(configured, encoding="utf-8")
    assert clf.main([str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "Spikes/s/a.py" in out and "vendor/b.py" not in out  # a configured list replaces the default one


def test_tree_findings_are_ordered_by_path_not_by_the_order_the_walk_met_them(tmp_path: Path) -> None:
    """The walk reads a directory's files before its sub-directories, so "z.py" is met before "a/b.py"."""
    _write(tmp_path, "z.py", '_LOGGER.info("x %s", y)\n')
    _write(tmp_path, "a/b.py", '_LOGGER.info("x %s", y)\n')
    assert [f.path for f in clf.check_tree(tmp_path)] == ["a/b.py", "z.py"]


# --------------------------------------------------------------------------- Copilot's review
BAD = '.info("x %s", y)\n'


@pytest.mark.parametrize(
    "source",
    [
        "from logging import getLogger\n\ndef f():\n    getLogger(__name__)" + BAD,
        "from logging import getLogger as gl\n\ndef f():\n    gl(__name__)" + BAD,
        "import logging as lg\n\ndef f():\n    lg.getLogger(__name__)" + BAD,
        "import logging\n\ndef f():\n    logging.getLogger(__name__)" + BAD,
        "def f():\n    logging.getLogger(__name__)" + BAD,  # a snippet without its import reads as written
    ],
)
def test_get_logger_is_recognised_when_it_provably_comes_from_logging(source: str) -> None:
    assert [f.line for f in clf.check_source(source)], source


@pytest.mark.parametrize(
    "source",
    [
        "def f():\n    getLogger(__name__)" + BAD,  # never imported from logging
        "def getLogger(name):\n    return name\n\ndef f():\n    getLogger(__name__)" + BAD,  # one defined here
        "def f():\n    client.getLogger()" + BAD,  # a method of another object
        "import logging\n\ndef f():\n    client.getLogger()" + BAD,
        "from other import getLogger\n\ndef f():\n    getLogger(__name__)" + BAD,
        "import logging as lg\n\ndef f():\n    other.getLogger(__name__)" + BAD,  # another module than the alias
    ],
)
def test_a_get_logger_that_is_not_the_standard_librarys_is_not_a_logger(source: str) -> None:
    assert clf.check_source(source) == [], source


@pytest.mark.parametrize(
    "line",
    [
        '_LOGGER.info(f"x {x}")  # lazy-log:',  # a compliant call with a bare marker
        '_LOGGER.info("a plain message")  # lazy-log:   ',
        "x = 1  # lazy-log:",  # no log call on the line at all
    ],
)
def test_a_marker_with_no_measurement_is_a_finding_wherever_it_sits(line: str) -> None:
    (finding,) = _check(line)
    assert finding.line == 2 and "needs the measurement" in finding.reason


def test_a_bare_marker_on_a_lazy_call_is_reported_once() -> None:
    assert len(_check('_LOGGER.info("wrote %s", path)  # lazy-log:')) == 1


def test_a_marker_with_a_measurement_on_a_compliant_call_is_harmless() -> None:
    assert _check('_LOGGER.info(f"x {x}")  # lazy-log: not needed any more') == []


def test_a_v_run_logs_with_the_tools_prefix(tmp_path: Path) -> None:
    """Every tool logs through log_setup: the time, the level and the module, at INFO with -v (logging in tiers)."""
    from test_log_setup import PROBE_LINE, tool_log_line

    line, level = tool_log_line("check_log_format", [a.replace("{empty}", str(tmp_path)) for a in ["-v", "{empty}"]])
    assert PROBE_LINE.fullmatch(line), line
    assert level == 20
