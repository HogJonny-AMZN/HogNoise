"""
Framework: tests of the tool-root pattern's reference, the example python.md points at.
Package: tests/test_tool_root_logging

The example is loaded by path (it is a document's example, not an importable module) and its ``configure_logging()`` is
run against ``tmp_path``. Every logger a case touches is restored afterwards: handlers, levels, ``propagate`` and the
two attributes the example sets (``_configured_by``, ``_capped_by``), so no case leaks into the next or into pytest's
own capture.
"""

from __future__ import annotations

import importlib.util
import logging
import os
import re
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "Docs" / "standards" / "examples" / "tool_root_logging.py"
FLAG = "ACME_LOG_THIRDPARTY_DEBUG"
MARK = "_acme_viewer_handler"
OWNER_MARK = "_process_owner_handler"
TOUCHED = ("", "acme_viewer", "acme_core", "httpx", "openai", "other_app", "asyncio")
LAUNCH = re.compile(r"\d{8}T\d{12}Z\.log")


def _load(name: str = "tool_root_logging_example") -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, EXAMPLE)
    assert spec is not None and spec.loader is not None, EXAMPLE
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _second_app() -> ModuleType:
    """The example again, as another App: its own tool root and marker, no shared library."""
    other = _load("tool_root_logging_other")
    other._TOOL_NAME = "other_app"
    other._TOOL_ROOT_LOGGER = logging.getLogger("other_app")
    other._MARK = "_other_app_handler"
    other._MODULE_NAME = "other_app.main"
    other._LOGGER = logging.getLogger("other_app.main")
    other._SHARED_LIBRARIES = ()
    return other


@pytest.fixture
def ex(monkeypatch: pytest.MonkeyPatch) -> Iterator[ModuleType]:
    monkeypatch.delenv(FLAG, raising=False)
    saved = {}
    for name in TOUCHED:
        logger = logging.getLogger(name)
        saved[name] = (list(logger.handlers), logger.level, logger.propagate)
        for attr in ("_configured_by", "_capped_by"):
            assert not hasattr(logger, attr), f"{name or 'root'} carries {attr} before the case"
    yield _load()
    for name, (handlers, level, propagate) in saved.items():
        logger = logging.getLogger(name)
        for handler in [h for h in logger.handlers if h not in handlers]:
            logger.removeHandler(handler)
            handler.close()
        for handler in [h for h in handlers if h not in logger.handlers]:
            logger.addHandler(handler)
        logger.setLevel(level)
        logger.propagate = propagate
        for attr in ("_configured_by", "_capped_by"):
            if hasattr(logger, attr):
                delattr(logger, attr)


@pytest.fixture
def tool_root_caplog(caplog: pytest.LogCaptureFixture) -> Iterator[pytest.LogCaptureFixture]:
    """The fixture testing.md gives an App, here on the example's tool root."""
    root = logging.getLogger("acme_viewer")
    root.addHandler(caplog.handler)
    yield caplog
    root.removeHandler(caplog.handler)


def _marked(name: str, mark: str = MARK) -> list[logging.Handler]:
    return [h for h in logging.getLogger(name).handlers if getattr(h, mark, False)]


def _new_launch() -> None:
    """What a new process starts with: no handlers on the App's or the library's root, the library unconfigured."""
    for name in ("acme_viewer", "acme_core"):
        logger = logging.getLogger(name)
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()
        if hasattr(logger, "_configured_by"):
            del logger._configured_by


def _seed(folder: Path, count: int, first_day: int = 10) -> list[str]:
    names = [f"202601{first_day + i:02d}T000000000000Z.log" for i in range(count)]
    for name in names:
        (folder / name).write_text("x", encoding="utf-8")
    return names


# 1
def test_a_repeat_call_returns_the_same_file_and_leaves_one_set_of_handlers(ex: ModuleType, tmp_path: Path) -> None:
    first = ex.configure_logging(log_dir=tmp_path)
    second = ex.configure_logging(log_dir=tmp_path)
    assert first == second
    assert len([p for p in tmp_path.iterdir() if LAUNCH.fullmatch(p.name)]) == 1
    assert len(_marked("acme_viewer")) == 2
    assert len(logging.getLogger("acme_core").handlers) == 2  # the library configured once


# 2
def test_another_apps_records_do_not_reach_this_apps_file(ex: ModuleType, tmp_path: Path) -> None:
    path = ex.configure_logging(log_dir=tmp_path)
    logging.getLogger("other_app.x").warning("from the other App")
    logging.getLogger("acme_viewer.render").info("from the viewer")
    text = path.read_text(encoding="utf-8")
    assert "from the viewer" in text and "from the other App" not in text


# 3
def test_an_exception_is_one_line_on_the_console_and_its_traceback_is_in_the_file(
    ex: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = ex.configure_logging(log_dir=tmp_path)
    try:
        raise ValueError("boom")
    except ValueError:
        logging.getLogger("acme_viewer.render").exception("Failed to render x")
    err = capsys.readouterr().err
    assert "Failed to render x" in err and "Traceback" not in err, err
    assert "Traceback" in path.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("message", "shown"),
    [
        ("first\nsecond", r"first\nsecond"),
        ("first\r\nsecond", r"first\r\nsecond"),
        ("first\rsecond", r"first\rsecond"),  # a terminal would write the second part over the first
        ("first\u2028second", r"first\u2028second"),
        ("first\x85second", r"first\x85second"),
    ],
)
def test_a_message_with_a_line_break_is_one_console_line_and_the_file_has_it_as_written(
    ex: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str], message: str, shown: str
) -> None:
    """#173: one line per record on the console, with the break shown as its escape; the file is not escaped."""
    path = ex.configure_logging(log_dir=tmp_path)
    capsys.readouterr()
    logging.getLogger("acme_viewer.render").info(message)
    err = capsys.readouterr().err
    assert len(err.splitlines()) == 1 and f">> {shown} ::(" in err, err
    written = path.read_bytes().decode("utf-8")
    assert shown not in written and "first" in written and "second" in written, written


# 4
def test_a_line_renders_in_the_fixed_format(ex: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ex.configure_logging(log_dir=tmp_path)
    logging.getLogger("acme_viewer.render").info("hello")
    line = capsys.readouterr().err.strip().splitlines()[-1]
    assert re.fullmatch(
        r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d{3} "
        r"\[INFO\]\[acme_viewer\.render\] >> hello ::\(test_tool_root_logging\.py:\d+\)",
        line,
    ), line


# 5
def test_the_opt_out_puts_listed_vendor_debug_in_the_file_only(
    ex: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(FLAG, "1")
    path = ex.configure_logging(log_dir=tmp_path)
    logging.getLogger("httpx").debug("request body")
    logging.getLogger("httpx").info("vendor info line")
    logging.getLogger("asyncio").debug("unlisted debug")
    assert "vendor info line" not in capsys.readouterr().err
    text = path.read_text(encoding="utf-8")
    assert "request body" in text and "vendor info line" in text and "unlisted debug" not in text


# 6
def test_the_cap_drops_vendor_info_and_formats_a_vendor_warning_once(
    ex: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = ex.configure_logging(log_dir=tmp_path)
    logging.getLogger("httpx").info("chatty")
    logging.getLogger("httpx").warning("vendor warning")
    err = capsys.readouterr().err
    assert "chatty" not in err and "chatty" not in path.read_text(encoding="utf-8")
    assert err.count("[WARNING][httpx] >> vendor warning") == 1, err


# 7
@pytest.mark.parametrize(("value", "shown"), [("yes", "'yes'"), ("ja\xe9", "'ja" + chr(92) + "xe9'"), ("", "''")])
def test_a_flag_other_than_1_is_a_warning_shown_as_ascii(
    ex: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    value: str,
    shown: str,
) -> None:
    monkeypatch.setenv(FLAG, value)
    ex.configure_logging(log_dir=tmp_path)
    line = next(ln for ln in capsys.readouterr().err.splitlines() if "ignored" in ln)
    assert line.isascii() and f"{FLAG}={shown} ignored: only 1 lifts" in line, line
    assert logging.getLogger("httpx").level == logging.WARNING  # still capped


# 8
def test_inside_a_host_the_app_leaves_the_hosts_loggers_and_says_the_flag_is_ignored(
    ex: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    logging.getLogger("httpx").setLevel(logging.DEBUG)  # the host's choice
    monkeypatch.setenv(FLAG, "1")
    ex.configure_logging(log_dir=tmp_path, owns_process=False)
    assert logging.getLogger("httpx").level == logging.DEBUG
    assert not _marked("") and not _marked("", OWNER_MARK) and not _marked("httpx")
    assert "ignored inside a host" in capsys.readouterr().err


def test_a_cap_set_earlier_is_undone_back_to_the_level_it_found(ex: ModuleType, tmp_path: Path) -> None:
    logging.getLogger("httpx").setLevel(logging.ERROR)
    ex.configure_logging(log_dir=tmp_path, owns_process=True)
    ex.configure_logging(log_dir=tmp_path, owns_process=True)  # a repeat owning call keeps the level found first
    assert logging.getLogger("httpx").level == logging.WARNING
    ex.configure_logging(log_dir=tmp_path, owns_process=False)
    assert logging.getLogger("httpx").level == logging.ERROR
    assert not _marked("", OWNER_MARK) and not hasattr(logging.getLogger("httpx"), "_capped_by")


def test_a_cap_the_host_changed_since_is_left_as_the_host_set_it(ex: ModuleType, tmp_path: Path) -> None:
    ex.configure_logging(log_dir=tmp_path, owns_process=True)
    logging.getLogger("httpx").setLevel(logging.CRITICAL)  # the host's later choice
    ex.configure_logging(log_dir=tmp_path, owns_process=False)
    assert logging.getLogger("httpx").level == logging.CRITICAL


def test_a_cap_the_host_changed_is_given_up_so_the_hosts_later_choice_stays(ex: ModuleType, tmp_path: Path) -> None:
    """#174: once the host has changed the level, the cap is no longer this App's; a later call that finds the host's
    own WARNING must not take it for the cap and restore the level from before it."""
    vendor = logging.getLogger("httpx")
    ex.configure_logging(log_dir=tmp_path, owns_process=True)  # caps at WARNING; the level before is NOTSET
    vendor.setLevel(logging.INFO)  # the host changes it
    ex.configure_logging(log_dir=tmp_path, owns_process=False)
    assert vendor.level == logging.INFO and not hasattr(vendor, "_capped_by")
    vendor.setLevel(logging.WARNING)  # the host's own choice, later
    ex.configure_logging(log_dir=tmp_path, owns_process=False)
    assert vendor.level == logging.WARNING


# 9
def test_two_owning_apps_format_a_vendor_warning_once(
    ex: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    other = _second_app()
    ex.configure_logging(log_dir=tmp_path / "a")
    other.configure_logging(log_dir=tmp_path / "b")
    logging.getLogger("httpx").warning("vendor warn")
    assert capsys.readouterr().err.count("[WARNING][httpx] >> vendor warn") == 1


def test_a_hosted_app_leaves_the_owners_root_console_handler(
    ex: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    hosted = _second_app()
    ex.configure_logging(log_dir=tmp_path / "a", owns_process=True)
    hosted.configure_logging(log_dir=tmp_path / "b", owns_process=False)
    assert len(_marked("", OWNER_MARK)) == 1
    logging.getLogger("httpx").warning("vendor warn")
    assert capsys.readouterr().err.count("[WARNING][httpx] >> vendor warn") == 1


# 10
def test_twenty_launches_keep_fifteen_app_files_and_fifteen_library_files(ex: ModuleType, tmp_path: Path) -> None:
    (tmp_path / "notes.log").write_text("mine", encoding="utf-8")
    for _ in range(20):
        ex.configure_logging(log_dir=tmp_path)
        _new_launch()
        time.sleep(0.002)  # each launch its own stamp
    app = [p for p in tmp_path.iterdir() if LAUNCH.fullmatch(p.name)]
    library = [p for p in tmp_path.iterdir() if p.name.startswith("acme_core-")]
    assert (len(app), len(library)) == (15, 15)
    assert (tmp_path / "notes.log").read_text(encoding="utf-8") == "mine"


def test_after_a_clock_rollback_this_launchs_own_files_are_kept(ex: ModuleType, tmp_path: Path) -> None:
    """Copilot on #156: 20 launches stamped later than now (the clock went back) sort as newest; this launch's own
    files, already open, must not be the ones pruned."""
    future = [f"2099010{i % 10}T{i:012d}Z" for i in range(20)]
    for stamp in future:
        (tmp_path / f"{stamp}.log").write_text("x", encoding="utf-8")
        (tmp_path / f"acme_core-{stamp}.log").write_text("x", encoding="utf-8")
    path = ex.configure_logging(log_dir=tmp_path)
    assert path.is_file() and (tmp_path / f"acme_core-{path.name}").is_file()
    app = [p for p in tmp_path.iterdir() if LAUNCH.fullmatch(p.name)]
    library = [p for p in tmp_path.iterdir() if p.name.startswith("acme_core-")]
    assert (len(app), len(library)) == (15, 15)
    logging.getLogger("acme_viewer.x").info("still written")
    assert "still written" in path.read_text(encoding="utf-8")


def test_the_oldest_launch_files_are_the_ones_pruned(ex: ModuleType, tmp_path: Path) -> None:
    names = _seed(tmp_path, 20)
    path = ex.configure_logging(log_dir=tmp_path)
    kept = sorted(p.name for p in tmp_path.iterdir() if LAUNCH.fullmatch(p.name))
    assert kept == sorted([*names[-14:], path.name])


# 11
def test_a_file_that_cannot_be_deleted_and_a_folder_named_like_one_are_warnings(
    ex: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    names = _seed(tmp_path, 20)
    (tmp_path / names[0]).unlink()
    (tmp_path / names[0]).mkdir()  # oldest, named like a launch file: unlink refuses a folder
    real = type(tmp_path).unlink

    def unlink(self: Path, *args: object, **kwargs: object) -> None:
        if self.name == names[1]:
            raise PermissionError(32, "in use by another process", str(self))
        real(self, *args, **kwargs)

    monkeypatch.setattr(type(tmp_path), "unlink", unlink)
    ex.configure_logging(log_dir=tmp_path)
    err = capsys.readouterr().err
    assert f"kept {names[0]}" in err and f"kept {names[1]}" in err, err
    assert (tmp_path / names[0]).is_dir() and (tmp_path / names[1]).is_file()


# Another instance of the App: it configures logging into the folder, prints its launch file's name, and keeps the file
# open until its stdin closes
_HOLDER = (
    "import importlib.util, sys\n"
    "from pathlib import Path\n"
    "spec = importlib.util.spec_from_file_location('holder', sys.argv[1])\n"
    "module = importlib.util.module_from_spec(spec)\n"
    "spec.loader.exec_module(module)\n"
    "print(module.configure_logging(log_dir=Path(sys.argv[2])).name, flush=True)\n"
    "sys.stdin.read()\n"
)


def test_a_launch_file_another_instance_holds_open_is_kept(
    ex: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """#172: another instance is another process, on every platform. Linux and macOS delete a file another process
    holds open, so the example's own lock is what keeps it there; Windows refuses the delete by itself."""
    holder = subprocess.Popen(
        [sys.executable, "-c", _HOLDER, str(EXAMPLE), str(tmp_path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    assert holder.stdin is not None and holder.stdout is not None
    try:
        held = holder.stdout.readline().strip()
        assert LAUNCH.fullmatch(held), f"the holder did not start: {held!r}"
        for i in range(20):  # later than the holder's launch, so its file is the oldest: in the delete set
            (tmp_path / f"20990101T{i:012d}Z.log").write_text("x", encoding="utf-8")
        ex.configure_logging(log_dir=tmp_path)
        assert f"kept {held}" in capsys.readouterr().err
        assert (tmp_path / held).is_file()
    finally:
        holder.stdin.close()
        try:
            holder.wait(timeout=30)
        except subprocess.TimeoutExpired:
            holder.kill()
            holder.wait()


@pytest.mark.skipif(sys.platform == "win32", reason="the lock is taken on Linux and macOS only")
def test_a_launch_file_that_cannot_be_locked_is_a_warning_and_the_app_starts(
    ex: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A file system without locks (some network mounts): the App still starts, and says its file is unprotected."""

    def refuse(fd: int, operation: int) -> None:
        raise OSError(37, "No locks available")

    monkeypatch.setattr(ex.fcntl, "flock", refuse)
    path = ex.configure_logging(log_dir=tmp_path)
    assert f"cannot lock {path.name}" in capsys.readouterr().err
    logging.getLogger("acme_viewer.x").info("still written")
    assert "still written" in path.read_text(encoding="utf-8")


def _pruned_first(ex: ModuleType, folder: Path, monkeypatch: pytest.MonkeyPatch, *, refuse: int) -> None:
    """Another instance's prune, between this launch opening its files and locking them: it deletes every launch file
    here, and this launch's first ``refuse`` shared locks are refused as if that prune still held its exclusive one."""
    real = ex.fcntl.flock
    pruned = []
    refused = []
    monkeypatch.setattr(ex.time, "sleep", lambda seconds: None)

    def flock(fd: int, operation: int) -> None:
        if operation & ex.fcntl.LOCK_SH:
            if not pruned:
                pruned.append(fd)
                for stale in folder.glob("*.log"):
                    stale.unlink()
            if len(refused) < refuse:
                refused.append(fd)
                raise BlockingIOError(11, "Resource temporarily unavailable")
        real(fd, operation)

    monkeypatch.setattr(ex.fcntl, "flock", flock)


@pytest.mark.skipif(sys.platform == "win32", reason="the lock is taken on Linux and macOS only")
@pytest.mark.parametrize("refuse", [0, 1])
def test_a_launch_file_pruned_before_it_was_locked_is_opened_again(
    ex: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    refuse: int,
) -> None:
    """Copilot on #179: after a clock rollback a new launch file is not among the newest, so another instance can prune
    it in the moment between its opening and its lock. The lock is checked against the name, and a deleted file is
    opened again, so the launch never writes to a file that is gone."""
    _pruned_first(ex, tmp_path, monkeypatch, refuse=refuse)
    path = ex.configure_logging(log_dir=tmp_path)
    logging.getLogger("acme_viewer.x").info("still written")
    logging.getLogger("acme_core.x").info("library still written")
    assert "still written" in path.read_text(encoding="utf-8")
    assert "library still written" in (tmp_path / f"acme_core-{path.name}").read_text(encoding="utf-8")
    assert "cannot lock" not in capsys.readouterr().err


@pytest.mark.skipif(sys.platform == "win32", reason="the lock is taken on Linux and macOS only")
def test_a_prune_whose_file_was_deleted_and_replaced_before_its_lock_keeps_the_replacement(
    ex: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#186: pruner A opens a file; pruner B deletes it; the launch opens a replacement at the same name. A's exclusive
    lock is then granted on the deleted file, which nobody holds, and the name must not be deleted on its account."""
    path = tmp_path / "20260101T000000000000Z.log"
    path.write_text("old\n", encoding="utf-8")
    real = ex.fcntl.flock

    def flock(fd: int, operation: int) -> None:
        if operation & ex.fcntl.LOCK_EX:  # between A's open and A's lock: B deletes, the launch re-opens
            path.unlink()
            path.write_text("the launch's replacement\n", encoding="utf-8")
        real(fd, operation)

    monkeypatch.setattr(ex.fcntl, "flock", flock)
    with pytest.raises(OSError, match="no longer names"):
        ex._delete_unless_held(path)
    assert path.read_text(encoding="utf-8") == "the launch's replacement\n"


@pytest.mark.skipif(sys.platform == "win32", reason="the lock is taken on Linux and macOS only")
def test_a_prune_whose_file_was_deleted_before_it_looked_never_deletes_the_name(
    ex: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#186, one step earlier: pruner A lists a file; pruner B deletes it before A looks at it; the launch then opens a
    replacement at the same name. A missing path is not "not a file": it is kept, and its name is never deleted without
    the lock, or the launch's replacement goes with it."""
    path = tmp_path / "20260101T000000000000Z.log"  # listed by A, already deleted by B
    real = os.unlink
    deleted: list[str] = []

    def unlink(target: object, *args: object, **kwargs: object) -> None:
        if os.fspath(target) == os.fspath(path):  # the launch re-opened its file before A deletes the name
            path.write_text("the launch's replacement\n", encoding="utf-8")
            deleted.append(os.fspath(target))
        real(target, *args, **kwargs)

    monkeypatch.setattr(os, "unlink", unlink)
    with pytest.raises(OSError):
        ex._delete_unless_held(path)
    assert deleted == [], "a path missing when the prune looked was deleted by name, with no lock"


@pytest.mark.skipif(sys.platform == "win32", reason="the lock is taken on Linux and macOS only")
def test_a_launch_file_it_never_gets_to_lock_is_a_warning_and_the_app_starts(
    ex: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Refused every time: a bounded wait, then the App starts and says its file is unprotected."""
    _pruned_first(ex, tmp_path, monkeypatch, refuse=1000)
    path = ex.configure_logging(log_dir=tmp_path)
    assert f"cannot lock {path.name}" in capsys.readouterr().err
    assert path.is_file()


@pytest.mark.skipif(sys.platform == "win32", reason="the lock is taken on Linux and macOS only")
def test_a_launch_file_that_cannot_be_read_is_kept_and_a_warning(
    ex: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """P-16: pruning opens a file to lock it; one it cannot open is not known to be free, so it stays."""
    names = _seed(tmp_path, 20)
    (tmp_path / names[0]).chmod(0)
    try:
        if os.access(tmp_path / names[0], os.R_OK):
            pytest.skip("this user reads a file with no permissions (root)")
        ex.configure_logging(log_dir=tmp_path)
    finally:
        if (tmp_path / names[0]).exists():
            (tmp_path / names[0]).chmod(0o600)
    assert (tmp_path / names[0]).is_file()
    assert f"kept {names[0]}" in capsys.readouterr().err


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="no named pipes here")
def test_a_named_pipe_named_like_a_launch_file_is_removed_without_waiting(ex: ModuleType, tmp_path: Path) -> None:
    """P-16: opening a pipe to lock it would wait for a writer; it is not a file, so it is removed as one is."""
    names = _seed(tmp_path, 20)
    (tmp_path / names[0]).unlink()
    os.mkfifo(tmp_path / names[0])
    ex.configure_logging(log_dir=tmp_path)
    assert not (tmp_path / names[0]).exists()


def test_a_folder_that_cannot_be_listed_is_a_warning_and_nothing_is_pruned(
    ex: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    names = _seed(tmp_path, 20)

    def refuse(path: object) -> list[str]:
        raise PermissionError(13, "Permission denied", str(path))

    monkeypatch.setattr(ex.os, "listdir", refuse)
    ex.configure_logging(log_dir=tmp_path)
    assert f"cannot list {tmp_path}" in capsys.readouterr().err
    assert all((tmp_path / name).exists() for name in names)


# 12
def test_a_missing_folder_is_created(ex: ModuleType, tmp_path: Path) -> None:
    assert ex.configure_logging(log_dir=tmp_path / "a" / "logs").parent.is_dir()


@pytest.mark.parametrize("value", ["", "relative/state"])
def test_an_empty_or_relative_variable_is_not_used(ex: ModuleType, monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("LOCALAPPDATA", value)
    monkeypatch.setenv("XDG_STATE_HOME", value)
    folder = ex._log_dir("acme_viewer")
    assert folder.is_absolute(), folder
    assert "relative" not in folder.parts, folder


# 13
def _refusing(match: str, monkeypatch: pytest.MonkeyPatch, calls_before: int | None = None) -> None:
    real = logging.FileHandler
    calls: list[str] = []

    def refuse(filename: object, *args: object, **kwargs: object) -> logging.FileHandler:
        calls.append(str(filename))
        if (calls_before is not None and len(calls) == calls_before) or (
            calls_before is None and match in str(filename)
        ):
            raise PermissionError(13, "Permission denied", str(filename))
        return real(filename, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(logging, "FileHandler", refuse)


def _state() -> dict[str, tuple[list[logging.Handler], int, bool]]:
    return {
        name: (list(logging.getLogger(name).handlers), logging.getLogger(name).level, logging.getLogger(name).propagate)
        for name in TOUCHED
    }


@pytest.mark.parametrize(
    ("case", "match", "nth", "lifted"),
    [
        ("the tool root's file", "", 1, False),
        ("a shared library's file", "acme_core-", None, False),
        ("a lifted vendor's file", "", 3, True),
    ],
)
def test_a_file_that_cannot_be_opened_raises_and_changes_no_logger(
    ex: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    match: str,
    nth: int | None,
    lifted: bool,
) -> None:
    if lifted:
        monkeypatch.setenv(FLAG, "1")
    old = _seed(tmp_path, 20)  # the logs of earlier launches: the evidence of why a start fails
    _refusing(match, monkeypatch, nth)
    before = _state()
    with pytest.raises(PermissionError):
        ex.configure_logging(log_dir=tmp_path)
    assert _state() == before, case
    for name in TOUCHED:
        assert not hasattr(logging.getLogger(name), "_configured_by") and not hasattr(
            logging.getLogger(name), "_capped_by"
        )
    assert all((tmp_path / name).exists() for name in old), "a start that failed pruned the earlier logs"


def test_a_folder_that_cannot_be_created_raises_and_changes_no_logger(ex: ModuleType, tmp_path: Path) -> None:
    (tmp_path / "afile").write_text("a file, where the folder would go", encoding="utf-8")
    before = _state()
    with pytest.raises(OSError):
        ex.configure_logging(log_dir=tmp_path / "afile" / "logs")
    assert _state() == before


def _link_or_skip(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target)
    except OSError as e:  # Windows without the privilege to make links
        pytest.skip(f"cannot make a symbolic link here: {e}")


def test_a_link_named_like_a_launch_file_is_removed_and_its_target_kept(
    ex: ModuleType, tmp_path: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    outside = tmp_path_factory.mktemp("outside") / "precious.log"
    outside.write_text("not the App's", encoding="utf-8")
    names = _seed(tmp_path, 20, first_day=12)
    (tmp_path / names[0]).unlink()
    _link_or_skip(tmp_path / names[0], outside)  # among the oldest: in the delete set
    _link_or_skip(tmp_path / "20260111T000000000000Z.log", tmp_path / "gone.log")  # dangling, the oldest
    ex.configure_logging(log_dir=tmp_path)
    assert outside.read_text(encoding="utf-8") == "not the App's"
    assert not (tmp_path / names[0]).is_symlink() and not (tmp_path / "20260111T000000000000Z.log").is_symlink()


def test_a_name_with_non_ascii_digits_is_not_a_launch_file(ex: ModuleType, tmp_path: Path) -> None:
    """P-15: \\d matches Arabic-Indic and fullwidth digits; such a file is someone else's, never counted or deleted."""
    foreign = "٢٠٢٦٠١٠١T000000000000Z.log"
    (tmp_path / foreign).write_text("mine", encoding="utf-8")
    names = _seed(tmp_path, 20)
    path = ex.configure_logging(log_dir=tmp_path)
    kept = sorted(p.name for p in tmp_path.iterdir() if LAUNCH.fullmatch(p.name) and p.name.isascii())
    assert kept == sorted([*names[-14:], path.name])
    assert (tmp_path / foreign).read_text(encoding="utf-8") == "mine"


# 14
def test_the_fixture_sees_a_record_under_the_tool_root(
    ex: ModuleType, tmp_path: Path, tool_root_caplog: pytest.LogCaptureFixture
) -> None:
    ex.configure_logging(log_dir=tmp_path)
    logging.getLogger("acme_viewer.render").info("seen by the fixture")
    assert "seen by the fixture" in tool_root_caplog.text


def test_plain_caplog_does_not(ex: ModuleType, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """The control: propagate=False keeps the record from the root logger, where caplog listens."""
    ex.configure_logging(log_dir=tmp_path)
    logging.getLogger("acme_viewer.render").info("hidden from caplog")
    assert "hidden from caplog" not in caplog.text


# 15
def test_the_logging_self_check_names_the_three_loggers(ex: ModuleType, tmp_path: Path) -> None:
    text = ex.configure_logging(log_dir=tmp_path).read_text(encoding="utf-8")
    for name in ("root", "acme_viewer", "acme_core"):
        assert re.search(
            rf"\[DEBUG\]\[acme_viewer\.main\] >> logger {name}: level \w+, propagate \w+, handlers ", text
        ), name


def test_the_logging_self_check_is_written_once_per_launch(ex: ModuleType, tmp_path: Path) -> None:
    path = ex.configure_logging(log_dir=tmp_path)
    ex.configure_logging(log_dir=tmp_path)  # a GUI's base window, in the same launch
    assert path.read_text(encoding="utf-8").count(">> logger root:") == 1
