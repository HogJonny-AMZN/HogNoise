"""
Acme Viewer: the logging setup of an App that takes the tool-root pattern (the reference copy, from python.md).
Package: acme_viewer/main

An example: its Package line and ``_MODULE_NAME`` name the App it stands for, not the folder it is kept in. Copy it into
the App's entry point module and change the constants. ``configure_logging()`` is called from ``main()`` (and from a
GUI's base window), never at import; a repeat call in one launch returns the same file and leaves one set of handlers.
"""

from __future__ import annotations

import logging as _logging
import os
import re
import stat
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

if sys.platform != "win32":
    import fcntl  # Linux and macOS delete a file another process holds open: a lock is what marks it in use

_MODULE_NAME = "acme_viewer.main"  # the import path, under the tool-root logger
__version__ = "0.1.3"
__updated__ = "2026-11-11"
_LOGGER = _logging.getLogger(_MODULE_NAME)
_TOOL_LOGGER = _LOGGER  # the same logger, for messages meant for users

_TOOL_NAME = "acme_viewer"  # the App's top-level import package
_TOOL_ROOT_LOGGER = _logging.getLogger(_TOOL_NAME)
_SHARED_LIBRARIES = ("acme_core",)  # each shared library's own root
_THIRD_PARTY = ("httpx", "openai")  # namespaces the project does not own
_THIRDPARTY_DEBUG = "ACME_LOG_THIRDPARTY_DEBUG"
_KEEP = 15  # launches whose log files are kept, this one included
_HOLD_TRIES = 5  # attempts at locking a launch file another instance's prune holds for the moment
_FORMAT = "%(asctime)s [%(levelname)s][%(name)s] >> %(message)s ::(%(filename)s:%(lineno)d)"
_MARK = "_acme_viewer_handler"  # set on each handler this module attaches
_OWNER_MARK = "_process_owner_handler"  # the same in every App: the one console handler on Python's root
_STAMP = r"[0-9]{8}T[0-9]{12}Z"  # a launch's UTC time, to the microsecond: names sort as times (ASCII digits only)
# Every character str.splitlines() breaks on, shown on the console as its escape (a line feed as the two characters \n)
_BREAKS = {ord(c): ascii(c)[1:-1] for c in "\n\r\x0b\x0c\x1c\x1d\x1e\x85\u2028\u2029"}


class _ConsoleFormatter(_logging.Formatter):
    """One line per record: the traceback goes to the file only, and a line break in the message shows as its escape.
    Formats a copy, so the file still gets the record as it was written."""

    def format(self, record: _logging.LogRecord) -> str:
        copy = _logging.makeLogRecord(record.__dict__)
        copy.exc_info, copy.exc_text, copy.stack_info = None, None, None
        return super().format(copy).translate(_BREAKS)


def _log_dir(app: str) -> Path:
    """Where this App's log files go, per platform. An unset, empty or relative variable is not used."""

    def absolute(name: str) -> Path | None:
        value = os.environ.get(name, "")
        return Path(value) if value and Path(value).is_absolute() else None

    if sys.platform == "win32":
        return (absolute("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / app / "logs"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Logs" / app
    return (absolute("XDG_STATE_HOME") or Path.home() / ".local" / "state") / app / "logs"


def _prune(folder: Path, prefix: str, current: str, problems: list[str]) -> None:
    """Delete all but the newest ``_KEEP - 1`` files named ``<prefix><stamp>.log`` other than ``current``, this
    launch's own file, which is never deleted: after a clock rollback it is not the newest by name. Best effort: a file
    another instance holds open, or an entry that is not a file, stays and is reported. On Linux and macOS only a
    holder that took the lock (``_hold``) is seen: an older copy of the App, or another program, is not."""
    pattern = re.compile(rf"{re.escape(prefix)}{_STAMP}\.log")
    try:
        names = sorted((n for n in os.listdir(folder) if pattern.fullmatch(n) and n != current), reverse=True)
    except OSError as e:
        problems.append(f"cannot list {folder}: {e}")
        return
    for name in names[_KEEP - 1 :]:
        try:
            _delete_unless_held(folder / name)
        except OSError as e:
            problems.append(f"kept {name}: {e}")


def _delete_unless_held(path: Path) -> None:
    """Delete ``path``; a link is removed, never followed. Windows refuses to delete a file another process holds open.
    Linux and macOS do not, so there a regular file is first locked without waiting: a running instance holds a shared
    lock on each file it writes (``_hold``), and its file raises here and stays. A file that cannot be opened to lock
    is not known to be free, and stays too. The lock is granted on the file opened, so the name is deleted only while it
    still leads there: another prune may have deleted that file and a launch opened a new one in its place (#186).
    A path already gone when it is looked at raises and stays, for the same reason: only an entry that exists and is
    not a regular file is deleted without the lock."""
    if sys.platform == "win32" or not stat.S_ISREG(os.lstat(path).st_mode):  # one look; a missing path raises
        path.unlink()
        return
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise OSError("another instance holds it open") from None
        if not _names(path, fd):
            raise OSError("its name no longer names the file locked: another prune deleted it")
        path.unlink()
    finally:
        os.close(fd)


def _hold(handler: _logging.FileHandler, problems: list[str]) -> None:
    """On Linux and macOS, a shared lock on a file this launch writes, held for as long as the handler keeps it open, so
    another instance's ``_prune`` finds it in use (``_delete_unless_held``). Shared locks do not exclude each other,
    so a second handler on the same file takes one too. A file system without locks is a warning, not a failed start.

    Another instance can prune the file between its opening and this lock (after a clock rollback a new file is not
    among the newest), so the lock counts only once the name still leads to the locked file; a file deleted in between
    is opened again. A lock refused for longer than another prune takes is a warning too.

    :raises OSError: a deleted file cannot be opened again."""
    if sys.platform == "win32":
        return
    path = Path(handler.baseFilename)
    for attempt in range(_HOLD_TRIES):
        if attempt:
            time.sleep(0.01)  # another prune holds the file only while it deletes it
        if not _names(path, handler.stream.fileno()):
            handler.stream.close()
            handler.stream = handler._open()
        try:
            fcntl.flock(handler.stream.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            continue
        except OSError as e:
            problems.append(f"cannot lock {path.name}, so another instance may prune it: {e}")
            return
        if _names(path, handler.stream.fileno()):
            return
    problems.append(f"cannot lock {path.name}, so another instance may prune it: another instance kept it locked")


def _names(path: Path, fd: int) -> bool:
    """Whether ``path`` still leads to the open file ``fd``, which another instance has not deleted."""
    try:
        return os.path.samestat(os.stat(path), os.fstat(fd))
    except FileNotFoundError:
        return False


def _marked(handler: _logging.Handler, level: int, formatter: _logging.Formatter) -> _logging.Handler:
    handler.setLevel(level)
    handler.setFormatter(formatter)
    setattr(handler, _MARK, True)
    return handler


def _replace_handlers(logger: _logging.Logger, handlers: list[_logging.Handler], mark: str | None = None) -> None:
    """Remove the handlers carrying ``mark`` (this module's ``_MARK``, read when called), then attach ``handlers``:
    called twice, one set remains."""
    mark = mark or _MARK
    for old in [h for h in logger.handlers if getattr(h, mark, False)]:
        logger.removeHandler(old)
        old.close()
    for handler in handlers:
        logger.addHandler(handler)


def _launch_file(folder: Path) -> tuple[Path, bool]:
    """This launch's log file, and whether it is new: the one already open on the tool-root logger on a repeat call,
    else a new name in a folder that now exists."""
    for handler in _TOOL_ROOT_LOGGER.handlers:
        if getattr(handler, _MARK, False) and isinstance(handler, _logging.FileHandler):
            return Path(handler.baseFilename), False
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{datetime.now(UTC):%Y%m%dT%H%M%S%fZ}.log", True


def configure_logging(*, verbose: bool = False, owns_process: bool = True, log_dir: Path | None = None) -> Path:
    """Configure the tool-root logger, each shared library's root (once per process) and, when this App owns the
    process, the third-party cap. Returns this launch's log file.

    Exactly one App in a process passes ``owns_process=True``: the one that started it. Inside a host it is False.

    :raises OSError: the log folder cannot be created, or the log file cannot be opened: an App that cannot keep its
        log does not start silently.
    """
    problems: list[str] = []
    folder = log_dir or _log_dir(_TOOL_NAME)
    path, new_launch = _launch_file(folder)
    console = _ConsoleFormatter(_FORMAT)
    plain = _logging.Formatter(_FORMAT)
    flag = os.environ.get(_THIRDPARTY_DEBUG)
    lifted = owns_process and flag == "1"
    # Every handler is made before any logger is changed: if one cannot be opened, those already made are closed and
    # the loggers are left as they were.
    staged: list[_logging.Handler] = []

    def stage(handler: _logging.Handler, level: int, formatter: _logging.Formatter) -> _logging.Handler:
        staged.append(_marked(handler, level, formatter))
        return handler

    try:
        tool_handlers = [
            stage(_logging.StreamHandler(sys.stderr), _logging.DEBUG if verbose else _logging.INFO, console),
            stage(_logging.FileHandler(path, encoding="utf-8"), _logging.DEBUG, plain),
        ]
        libraries: dict[str, list[_logging.Handler]] = {}
        for name in _SHARED_LIBRARIES:  # once per process: the first App to configure it wins
            if getattr(_logging.getLogger(name), "_configured_by", None) is None:
                libraries[name] = [
                    stage(
                        _logging.FileHandler(folder / f"{name}-{path.name}", encoding="utf-8"), _logging.DEBUG, plain
                    ),
                    stage(_logging.StreamHandler(sys.stderr), _logging.WARNING, console),
                ]
        # Python's root shows a capped vendor's warnings in this App's format, never its INFO
        owner = stage(_logging.StreamHandler(sys.stderr), _logging.WARNING, console) if owns_process else None
        # lifted, the vendor's DEBUG records go to this launch's file, which then holds what the SDK logs (request
        # bodies included) for as long as the file is kept
        vendor_files = (
            {
                vendor: stage(_logging.FileHandler(path, encoding="utf-8"), _logging.DEBUG, plain)
                for vendor in _THIRD_PARTY
            }
            if lifted
            else {}
        )
        for handler in staged:
            if isinstance(handler, _logging.FileHandler):
                _hold(handler, problems)
    except OSError:
        for handler in staged:
            handler.close()
        raise

    # Old files are pruned only once every handler is open: a start that fails keeps the logs of the launches before it
    if new_launch:
        _prune(folder, "", path.name, problems)
    for name in libraries:
        _prune(folder, f"{name}-", f"{name}-{path.name}", problems)
    _TOOL_ROOT_LOGGER.setLevel(_logging.DEBUG)
    _TOOL_ROOT_LOGGER.propagate = False
    _replace_handlers(_TOOL_ROOT_LOGGER, tool_handlers)
    for name, handlers in libraries.items():
        library = _logging.getLogger(name)
        library.setLevel(_logging.DEBUG)
        library.propagate = False
        for handler in handlers:
            library.addHandler(handler)
        library._configured_by = _TOOL_NAME  # type: ignore[attr-defined]
    root = _logging.getLogger()
    if owner is not None:
        # The owner's marker is the same in every App, so a second App that (wrongly) also owns the process replaces
        # this handler rather than doubling it
        setattr(owner, _OWNER_MARK, True)
        _replace_handlers(root, [owner], mark=_OWNER_MARK)
        for vendor in _THIRD_PARTY:
            logger = _logging.getLogger(vendor)
            level = _logging.DEBUG if lifted else _logging.WARNING
            capped = getattr(logger, "_capped_by", None)
            original = capped[2] if capped and capped[0] == _TOOL_NAME else logger.level  # kept across repeat calls
            logger.setLevel(level)
            logger._capped_by = (_TOOL_NAME, level, original)  # type: ignore[attr-defined]
            _replace_handlers(logger, [vendor_files[vendor]] if lifted else [])
        if flag is not None and flag != "1":
            problems.append(f"{_THIRDPARTY_DEBUG}={ascii(flag)} ignored: only 1 lifts the third-party cap")
    else:
        # A host's loggers are the host's. Only what this App set on them before (a call that owned the process) is
        # undone: its own handlers, by its own marker (never another App's), and a cap whose level the host has not
        # changed since, back to the level it had before. The cap's marker goes either way: once the host has changed
        # the level the cap is not this App's, and a later call must not take the host's own choice for it
        _replace_handlers(root, [])
        for vendor in _THIRD_PARTY:
            logger = _logging.getLogger(vendor)
            _replace_handlers(logger, [])
            capped = getattr(logger, "_capped_by", None)
            if capped and capped[0] == _TOOL_NAME:
                if capped[1] == logger.level:
                    logger.setLevel(capped[2])
                del logger._capped_by  # type: ignore[attr-defined]
        if flag is not None:
            problems.append(
                f"{_THIRDPARTY_DEBUG} ignored inside a host: the cap applies only when the App owns the process"
            )
    for problem in problems:
        _LOGGER.warning(f"Logging setup: {problem}")
    for name in ("", _TOOL_NAME, *_SHARED_LIBRARIES) if new_launch else ():  # the logging self-check, once per launch
        logger = _logging.getLogger(name)
        handlers = ", ".join(type(h).__name__ for h in logger.handlers) or "none"
        _LOGGER.debug(
            f"logger {name or 'root'}: level {_logging.getLevelName(logger.level)}, "
            f"propagate {logger.propagate}, handlers {handlers}"
        )
    return path
