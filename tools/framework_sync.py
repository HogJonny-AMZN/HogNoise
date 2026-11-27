"""
Framework: the sync check: is every managed file as the lock says, has the template moved on, and take it.
Package: tools/framework_sync

``framework.lock`` records the hash of every managed and parametrised file ``init`` wrote. ``--check`` compares each
with the file on disk, offline, so CI can run it anywhere, and reports as ``[rule] path: detail``:

``edited``          a locked file differs from the lock (line endings aside) and has no override in ``framework.toml``
``missing``         a locked file is not on disk and has no override
``unreadable``      a locked file cannot be read, so it was not checked
``override-stale``  an override names a locked file that equals the lock: it can go
``override-unknown`` an override names neither a locked file nor a setting (a typo, or a file the lock never had)
``lock``            ``framework.lock`` cannot be read, or its template version disagrees with ``framework.toml``
``corpus``          there is no lock, or it lists no files: a check that could not see what it checks is not a pass

An **override** (``[[overrides]]`` in ``framework.toml``, with a reason) is the one way to differ from the template on
purpose: it accepts an edit, a deletion or a symlink in place of that file, but not a file that cannot be read. Every
override in force is printed with its reason on every run, so the list is the repository's visible debt to the template.
A project-owned file is never in the lock, so it is never checked here. A locked path must be a normalised relative path
(the lock reader refuses any other), a locked file must be a regular file inside the repository (a symlink, or a file
reached through a folder that leaves the repository, is an edit), and the comparison is as case-sensitive as the file
system is: a lock written on Linux and checked on Windows can disagree about the case of a name.

**What it does not defend against.** The lock, this tool, ``tools/check.py`` and the CI workflow are files of the
repository, so whoever can edit the repository can regenerate the lock or remove the stage. An offline check holds a
repository to its own record, honestly; whether the record is the template's is ``--upstream``'s question.

The hash is ``init.lock_hash``, the function ``init`` writes the lock with, so this check and the initialiser cannot
disagree about what "as locked" means.

``--upstream`` asks the other question: has the template moved on? It reads the newest **tagged release** (``vX.Y.Z``)
of the repository named by ``[framework] upstream`` in ``framework.toml`` (``owner/name`` on github.com, or
``host/owner/name`` on another GitHub host) with git (``git ls-remote`` on ``https://<host>/<owner>/<name>.git``; a
private upstream needs git's own credentials, and git is told never to prompt).
If the lock is behind, it fetches that tag, unpacks its payload and runs the tag's own ``init`` classifier and renderer
read-only, with this repository's ``project.json``, to see which locked files would change, appear or go. So the answer
is what ``init`` would write, not a second implementation of its rules. It prints::

    upstream github.com/acme/template: newest release v0.2.0 (2026-10-20, from the tag)
    lock is behind: 0.1.0 locked, 0.2.0 current, 3 managed file(s) changed
      changed: tools/check.py
      added: tools/new.py
      removed: tools/old.py
    behind for 2 day(s), inside the 14-day window

and exits 0 when current or inside the window (``max_age_days`` in ``framework.toml``, default 14, counted from the
tag's day: an annotated tag's tagger date, a lightweight tag's commit date), 1 when the lock has been behind for
longer, and 2 when it could not tell: no git, no network or no credential, no upstream configured, no tagged release,
no lock or ``project.json``, a payload that is unsafe or missing. Nothing in the repository is written by it, and the
fetched copy is removed.

``--update`` takes the newest release onto a new local branch, ``template-update/vB``, as **one commit**, doing the
mechanical part of ``Docs/standards/updating.md``'s steps and leaving the judgment to a person. In order: it refuses a
repository that is not ready (not the top level, a detached ``HEAD``, an unclean tree, a sync finding, the branch
already there) before any network call; finds the newest tag (the lock current or ahead: nothing to do); fetches it and
the locked one; plans with each release's own ``init`` in a child process (``UPDATE_DRIVER``); decides every path,
edits ``framework.toml`` as text, reads the release's hand steps and checks the commit message with the repository's
own ``tools/check_commit_msg.py``, all before writing; then writes on the new branch, runs ``--check`` and commits with
no hook run. A failure in the write or the commit rolls back to the start; a ``--check`` finding after the write keeps
the branch uncommitted and prints how to drop it. It exits 0 updated or nothing to update, 1 refused with nothing
written, 2 could not tell or could not finish. It pushes nothing. The code that runs is the repository's own copy of
this tool, so the release that first ships ``--update`` is taken by hand.

**Both execute code from the release.** The tag's own ``tools/init.py`` and ``tools/framework_config.py`` are run, in
a child process (``python -I``, a scrubbed environment with no token and no home folder, a timeout, the scratch folder
as its working directory) whose output is discarded except one marked result line, so the release's code cannot end
this process, change its modules, print into the report or see a token in the environment. That is not a sandbox: the
child can still reach any file the user can, and ``plan_new`` is read-only because the code is, not because anything
enforces it; ``--update`` takes only regular files from the child's output folder, and only this process writes the
repository. What is trusted is **whoever can push a ``vX.Y.Z`` tag to the upstream**. Point ``upstream`` only at a
repository you trust at that level.

Run standalone (exit code 0 clean, 1 findings or refused, 2 the repository or its configuration is unusable)::

    uv run python tools/framework_sync.py (--check | --upstream | --update) [-v] [--root PATH]
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime
import json
import logging as _logging
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import tomllib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import framework_config as fc
import init as ini
import log_setup

# -------------------------------------------------------------------------
# module global scope
_MODULE_NAME = "tools.framework_sync"
__version__ = "0.3.0"
__updated__ = "2026-11-16"
_LOGGER = _logging.getLogger(_MODULE_NAME)

ROOT = Path(__file__).resolve().parent.parent
LOCK = "framework.lock"
_TAG_RE = re.compile(r"v(\d{1,9})\.(\d{1,9})\.(\d{1,9})", re.ASCII)
#: The most a downloaded payload may unpack to; the template is well under a tenth of this.
MAX_PAYLOAD_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True)
class Report:
    """What a run found: the findings, and the overrides in force (path and reason): debt, not a finding."""

    findings: list[Finding]
    honoured: list[tuple[str, str]]


@dataclass(frozen=True)
class Finding:
    """One thing wrong: which rule, which path (relative to the repository), and why."""

    rule: str
    path: str
    detail: str

    def __str__(self) -> str:
        return f"[{self.rule}] {self.path}: {self.detail}"


def check(root: Path) -> list[Finding]:
    """Every finding for the locked files under ``root``, sorted by path and then rule (see ``report``)."""
    return report(root).findings


def report(root: Path) -> Report:
    """The findings and the overrides in force for the locked files under ``root``.

    :raises fc.ConfigError: ``framework.toml`` cannot be read (the lock being unreadable is a finding, not an error).
    """
    config = fc.load_framework(root / "framework.toml")
    overrides = {o.target: o.reason for o in config.overrides}
    try:
        lock = ini.read_lock(root)
    except fc.ConfigError as e:
        _LOGGER.warning(f"{root / LOCK} cannot be read: {e.message}")
        return Report([Finding("lock", LOCK, e.message)], [])
    if lock is None:
        _LOGGER.warning(f"{root} has no {LOCK}")
        return Report(
            [Finding("corpus", LOCK, "there is no lock, so there is nothing to compare with (run init new)")], []
        )
    version, files, _ = lock
    if not files:
        _LOGGER.warning(f"{root / LOCK} lists no files")
        return Report([Finding("corpus", LOCK, "the lock lists no files, so nothing was checked")], [])
    findings: list[Finding] = []
    if version != config.template_version:
        findings.append(
            Finding(
                "lock",
                LOCK,
                f"locked at template {version} and framework.toml says {config.template_version}; "
                "run init (or --update) to bring them together",
            )
        )
    honoured: list[tuple[str, str]] = []
    top = root.resolve()
    for rel, locked in sorted(files.items()):
        found, accepted = _file(root, top, rel, locked, overrides.get(rel))
        findings += found
        if accepted is not None:
            honoured.append((rel, accepted))
    for target in sorted(overrides):
        if target not in files and target != fc.HANDOFF_OVERRIDE_TARGET:
            findings.append(
                Finding("override-unknown", target, "names no locked file and no setting; fix the name or remove it")
            )
    _LOGGER.info(
        f"checked {len(files)} locked file(s) in {root}: {len(findings)} finding(s), "
        f"{len(honoured)} override(s) in force"
    )
    return Report(sorted(findings, key=lambda f: (f.path, f.rule, f.detail)), honoured)


def _file(root: Path, top: Path, rel: str, locked: str, reason: str | None) -> tuple[list[Finding], str | None]:
    """The findings for one locked file, and the override's reason if one is what accepted it (else ``None``).

    ``top`` is the resolved repository root. An override accepts an edit, a deletion or a symlink, never a file that
    cannot be read."""
    path = root / rel
    remedy = "; fix it in the template (or list it under [[overrides]] with a reason)"

    def differs(rule: str, detail: str) -> tuple[list[Finding], str | None]:
        if reason is not None:
            _LOGGER.info(f"{rel} {detail} and is an override: {reason}")
            return [], reason
        return [Finding(rule, rel, detail + (remedy if detail == "differs from the lock" else ""))], None

    try:
        parent = path.parent.resolve()
    except (OSError, RuntimeError) as e:  # a symlink loop raises RuntimeError before Python 3.13
        return [Finding("unreadable", rel, f"its folder cannot be resolved, so it was not checked: {e}")], None
    if parent != top and top not in parent.parents:
        return differs("edited", "resolves outside the repository")
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return differs(
            "missing", "is in the lock and not on disk; restore it, or list it under [[overrides]] with a reason"
        )
    except OSError as e:
        return [Finding("unreadable", rel, f"cannot be read, so it was not checked: {e}")], None
    if stat.S_ISLNK(info.st_mode):
        return differs("edited", "is a symlink, and init writes a regular file")
    if not stat.S_ISREG(info.st_mode):
        return differs("edited", "is not a file")
    try:
        current = ini.lock_hash(path.read_bytes())
    except OSError as e:
        return [Finding("unreadable", rel, f"cannot be read, so it was not checked: {e}")], None
    if current == locked:
        if reason is not None:
            detail = f"the file equals the lock, so the override can be removed (reason was: {reason})"
            return [Finding("override-stale", rel, detail)], None
        return [], None
    return differs("edited", "differs from the lock")


# -------------------------------------------------------------------------
# --upstream
#: The marker the child process puts before its one JSON result line, so that anything the release's code prints cannot
#: be mistaken for it (and is dropped).
RESULT_MARK = "FRAMEWORK-SYNC-RESULT "
#: Seconds the release's ``init`` may take to plan.
CHILD_TIMEOUT = 120
#: The environment the release's code is given: no token, no home folder, nothing a plan does not need.
CHILD_ENV_KEYS = ("PATH", "SYSTEMROOT", "SYSTEMDRIVE", "TEMP", "TMP", "TMPDIR", "LANG", "LC_ALL")
_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL", *(f"COM{n}" for n in range(1, 10)), *(f"LPT{n}" for n in range(1, 10))}
)
_SEMVER_RE = re.compile(r"(\d{1,9})\.(\d{1,9})\.(\d{1,9})", re.ASCII)

#: Run in a child process (``python -I -c``): loads the release's own ``framework_config`` and ``init`` and plans a
#: ``new`` over the repository, writing nothing, then prints one marked JSON line. Anything the release's code does at
#: import, prints, raises or exits becomes ``{"ok": false, ...}`` or no line at all, and the parent says "cannot tell".
CHILD_DRIVER = r"""
import importlib.util, json, sys
from pathlib import Path
payload, root = Path(sys.argv[1]), Path(sys.argv[2])
def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod
try:
    tools = payload / "tools"
    sys.path.insert(0, str(tools))
    config = load("framework_config", tools / "framework_config.py")
    initialiser = load("upstream_init", tools / "init.py")
    project = config.load_project(root / "project.json")
    plan = initialiser.plan_new(payload, root, project)
    text = plan.generated.get("framework.lock")
    if not text:
        raise RuntimeError("the release's init produced no lock to compare with")
    out = {
        "ok": True,
        "files": json.loads(text)["files"],
        "shipped": sorted(initialiser.discover(payload)),
        "refusals": list(plan.refusals),
    }
except BaseException as e:
    out = {"ok": False, "error": type(e).__name__ + ": " + str(e)}
sys.stdout.write("\n" + MARK + json.dumps(out) + "\n")
sys.stdout.flush()
""".replace("MARK", repr(RESULT_MARK))


class UpstreamError(Exception):
    """The upstream could not be read; the message says why. Exit code 2, never a pass."""


NO_UPSTREAM = (
    'no upstream is configured: set [framework] upstream = "owner/name" (or "host/owner/name") in framework.toml'
)


#: Seconds a git call may take; a fetch gets ``FETCH_TIMEOUT``.
GIT_TIMEOUT = 120
FETCH_TIMEOUT = 300
#: What git is told so that a credential prompt is a failure, never a hang: git's own prompt, and Git Credential
#: Manager's window.
GIT_NO_PROMPT = {"GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"}


#: Where git finds a repository, set by a hook or a wrapper that runs this tool. Inherited, they would aim a git call
#: meant for the scratch folder at that repository instead, so ``run_git`` drops them.
GIT_LOCATION_KEYS = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_NAMESPACE",
)


def _run_bounded(argv: list[str], cwd: Path, env: dict[str, str], timeout: int) -> tuple[int, str, str] | None:
    """Run ``argv`` in ``cwd`` with no stdin, in a process group of its own, and return ``(exit code, stdout,
    stderr)`` decoded as UTF-8 with undecodable bytes replaced; ``None`` when it did not finish in ``timeout``
    seconds, after its whole process tree was ended (a child's own children included).

    :raises OSError: the program could not start."""
    group: dict = (
        {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
    )
    process = subprocess.Popen(
        argv,
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        **group,
    )
    try:
        out, err = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _end_tree(process)
        return None
    return process.returncode, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")


def run_git(argv: list[str], cwd: Path, timeout: int = GIT_TIMEOUT) -> subprocess.CompletedProcess:
    """Run git (``argv[0]`` is its path) in ``cwd`` with no stdin and no prompt; never raises.

    The output is UTF-8 with undecodable bytes replaced. A program that cannot start is exit 127. On a timeout the
    whole process tree is ended, since git runs helpers under it (``git-remote-https`` for a fetch), and the answer is
    exit 124. The variables that tell git where a repository is (``GIT_LOCATION_KEYS``) are not passed on."""
    env = {key: value for key, value in os.environ.items() if key not in GIT_LOCATION_KEYS} | GIT_NO_PROMPT
    _LOGGER.info(f"git {' '.join(argv[1:])} (in {cwd})")
    try:
        result = _run_bounded(argv, cwd, env, timeout)
    except OSError as e:
        return subprocess.CompletedProcess(argv, 127, "", f"cannot start {argv[0]}: {e}")
    if result is None:
        _LOGGER.warning(f"git {' '.join(argv[1:])} did not finish in {timeout} s; its process tree was ended")
        return subprocess.CompletedProcess(argv, 124, "", f"git did not finish in {timeout} s")
    return subprocess.CompletedProcess(argv, *result)


#: One line of ``git ls-remote``: an object name (SHA-1 or SHA-256), a tab, and a tag's full name.
_LS_REMOTE_RE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\trefs/tags/([^\t\n]+)", re.ASCII)


def _split(upstream: str) -> tuple[str, str]:
    """``fc.split_upstream``, with a value that skipped validation an ``UpstreamError`` (exit 2), never a traceback."""
    try:
        return fc.split_upstream(upstream)
    except ValueError as e:
        raise UpstreamError(f"[framework] upstream is {upstream!r}: {e}") from e


def release_url(upstream: str) -> str:
    """The URL git reads the upstream at: ``https://<host>/<owner>/<name>.git``, github.com for a bare
    ``owner/name``, the host as written. Git never reads ``GH_HOST``, so nothing else can move it.

    :raises UpstreamError: the value is not a repository (it skipped ``parse_framework``)."""
    host, name = _split(upstream)
    return f"https://{host}/{name}.git"


def qualified(upstream: str) -> str:
    """The upstream as it is printed: ``<host>/<owner>/<name>``, ``github.com/owner/name`` for a bare value.

    :raises UpstreamError: the value is not a repository (it skipped ``parse_framework``)."""
    host, name = _split(upstream)
    return f"{host}/{name}"


def _git(git: str, args: list[str], cwd: Path, timeout: int = GIT_TIMEOUT) -> str:
    """Run ``git <args>`` and return its standard output.

    :raises UpstreamError: git exited nonzero, timed out or could not start; the message has git's first line."""
    result = run_git([git, *args], cwd, timeout)
    if result.returncode != 0:
        raise UpstreamError(_failure(args, result))
    return result.stdout or ""


def _failure(args: list[str], result: subprocess.CompletedProcess) -> str:
    """``git <subcommand> failed (<code>): <git's first line>``, stdout's when stderr is empty, else ``no message``."""
    words = (result.stderr or result.stdout or "").strip().splitlines()
    return f"git {subcommand(args)} failed ({result.returncode}): {words[0] if words else 'no message'}"


def subcommand(args: list[str]) -> str:
    """The git subcommand in ``args``, after any ``-c name=value`` pairs and options before it."""
    skip = False
    for arg in args:
        if skip:
            skip = False
        elif arg == "-c":
            skip = True
        elif not arg.startswith("-"):
            return arg
    return args[0] if args else "?"


#: What git (or a credential manager before it) says on stderr when it has no working credential for a host: none
#: (it cannot prompt for one), or one the host refused. Matched on any line, in any case; a line where a proxy
#: refuses its own credential is the proxy's, not the host's, so it is passed over. The word "proxy" alone is not
#: enough: it can be part of the host's name or the repository's.
_NO_CREDENTIAL_WORDS = ("could not read username", "terminal prompts disabled", "authentication failed")


def _credential_hint(stderr: str, host: str) -> str:
    """The words for a person when stderr says git has no working credential for ``host``, else nothing. Only words:
    the exit code is the same with them or without them."""
    lines = [line.lower() for line in stderr.splitlines() if "proxy authentication" not in line.lower()]
    if not any(words in line for line in lines for words in _NO_CREDENTIAL_WORDS):
        return ""
    return (
        f"; git has no working credential for {host}: sign in to it once with git (a credential manager stores it),"
        f" or run gh auth login --hostname {host} and gh auth setup-git --hostname {host}, then run this again"
    )


def release_tags(url: str, git: str, cwd: Path, host: str) -> dict[str, tuple[int, int, int]]:
    """Every ``vX.Y.Z`` tag at ``url`` and its version; a tag of another form is left out. ``host`` is the upstream's
    host as written (from ``split_upstream``, never from the URL), named in the hint when git has no credential.

    This is the first network call of both modes, so it reads the whole of stderr: with a credential manager, the
    first line is the manager's, and git's own words come after it.

    :raises UpstreamError: git failed, its answer is malformed, or there is no release tag."""
    args = ["ls-remote", "--tags", "--refs", "--", url, "refs/tags/v*"]
    result = run_git([git, *args], cwd)
    if result.returncode != 0:
        raise UpstreamError(_failure(args, result) + _credential_hint(result.stderr or "", host))
    out = result.stdout or ""
    found: dict[str, tuple[int, int, int]] = {}
    for line in out.splitlines():
        match = _LS_REMOTE_RE.fullmatch(line)
        if match is None:
            raise UpstreamError(f"git ls-remote gave a malformed line, so the tags cannot be read: {line!r}")
        name = match.group(1)
        version = _TAG_RE.fullmatch(name)
        if version is None:
            _LOGGER.debug(f"ignored tag {name!r}: not vX.Y.Z")
            continue
        major, minor, patch = (int(n) for n in version.groups())
        found[name] = (major, minor, patch)
    if not found:
        raise UpstreamError(f"{url} has no tagged release (a tag like v0.2.0): there is nothing to compare with")
    _LOGGER.info(f"{url}: {len(found)} release tag(s), the newest is {max(found, key=found.__getitem__)}")
    return found


def fetch_tags(url: str, tags: list[str], scratch: Path, git: str) -> dict[str, Path]:
    """Fetch each tag's commit from ``url`` into ``scratch/git`` and unpack its ``payload/`` folder into
    ``scratch/<tag>/payload``; return those folders by tag.

    :raises UpstreamError: a name is not a release tag, git failed, or a payload is unsafe or missing."""
    for tag in tags:
        if _TAG_RE.fullmatch(tag) is None:
            raise UpstreamError(f"{tag!r} is not a release tag, so it is not fetched")
    repo = scratch / "git"
    repo.mkdir(parents=True, exist_ok=True)
    _git(git, ["init", "-q"], repo)
    refspecs = [part for tag in tags for part in ("tag", tag)]
    _git(git, ["fetch", "--depth", "1", "--no-tags", "--", url, *refspecs], repo, FETCH_TIMEOUT)
    payloads: dict[str, Path] = {}
    for tag in tags:
        tarball = scratch / f"{tag}.tar.gz"
        _git(git, ["archive", "--format=tar.gz", "--prefix=release/", "-o", str(tarball), tag, "payload"], repo)
        payloads[tag] = _extract_payload(tarball, scratch / tag / "payload")
    return payloads


def tag_day(repo: Path, tag: str, git: str) -> datetime.date:
    """The day ``tag`` was made, from a fetched copy: an annotated tag's tagger date, a lightweight tag's commit date.

    :raises UpstreamError: git failed or did not answer with a date."""
    stamp = _git(git, ["for-each-ref", "--format=%(creatordate:short)", f"refs/tags/{tag}"], repo).strip()
    try:
        return datetime.date.fromisoformat(stamp)
    except ValueError as e:
        raise UpstreamError(f"git gave no usable date for {tag}: {stamp!r}") from e


def remove_tree(path: Path) -> None:
    """Remove a scratch folder, git's read-only object files included (Windows will not delete a read-only file).
    What still cannot be removed is logged, never raised: the work is done, and only a temporary folder is left."""

    def writable(func: Callable[..., object], name: str, error: object) -> None:
        os.chmod(name, stat.S_IWRITE)
        func(name)

    try:
        if sys.version_info >= (3, 12):
            shutil.rmtree(path, onexc=writable)
        else:  # onexc is new in 3.12; a repository's tools may run on 3.11
            shutil.rmtree(path, onerror=writable)
    except OSError as e:
        _LOGGER.warning(f"could not remove the scratch folder {path}: {e}")


def _end_tree(process: subprocess.Popen) -> None:
    """End ``process`` and every process under it, then reap it. A tree already gone is not an error."""
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(process.pid)],
                capture_output=True,
                stdin=subprocess.DEVNULL,
                timeout=30,
                check=False,
            )
        else:
            os.killpg(process.pid, 9)  # SIGKILL, by number: signal.SIGKILL does not exist on Windows
    except (OSError, subprocess.TimeoutExpired) as e:
        _LOGGER.warning(f"could not end the process tree of {process.args[0]} ({process.pid}): {e}")
    try:
        process.kill()
    except OSError:
        pass
    try:
        process.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        _LOGGER.warning(f"{process.args[0]} ({process.pid}) still holds its output after being ended")


def _unsafe_part(part: str) -> bool:
    """A path component Windows would read as something other than a plain name: a drive (``D:x``), a stream (``a:b``),
    a trailing dot or space, or a device name (``NUL``, ``con.txt``)."""
    return ":" in part or part != part.rstrip(". ") or part.split(".")[0].upper() in _RESERVED_NAMES


def _extract_payload(tarball: Path, dest: Path) -> Path:
    """Unpack the ``payload/`` folder of a GitHub tag tarball into ``dest`` and return it. Only members under
    ``payload/`` are looked at; a symlink or a special file elsewhere in the tarball is ignored.

    :raises UpstreamError: a member could escape or is not a plain file or folder, it is too big, or no payload.
    """
    total = 0
    written = 0
    base = dest.resolve()
    try:
        with tarfile.open(tarball, "r:gz") as tar:
            for member in tar:
                parts = PurePosixPath(member.name).parts
                if len(parts) < 2 or parts[1] != "payload":
                    continue
                if (
                    member.name.startswith("/")
                    or "\\" in member.name
                    or any(_unsafe_part(part) for part in parts[1:])  # a ".." part is one: it ends in a dot
                    or not (member.isfile() or member.isdir())
                ):
                    raise UpstreamError(f"the download has an unsafe member: {member.name!r}")
                if len(parts) < 3 or not member.isfile():
                    continue
                total += member.size
                if total > MAX_PAYLOAD_BYTES:
                    raise UpstreamError("the downloaded payload is larger than the limit; refusing to unpack it")
                target = dest.joinpath(*parts[2:])
                if not target.resolve().is_relative_to(base):
                    raise UpstreamError(f"the download has an unsafe member: {member.name!r}")
                target.parent.mkdir(parents=True, exist_ok=True)
                source = tar.extractfile(member)
                if source is None:
                    raise UpstreamError(f"the download has an unreadable member: {member.name!r}")
                target.write_bytes(source.read())
                if os.name != "nt" and member.mode & 0o111:  # a hook without a suffix stays executable
                    target.chmod(target.stat().st_mode | (member.mode & 0o111))
                written += 1
                _LOGGER.debug(f"extracted {'/'.join(parts[2:])} ({member.size} bytes)")
    except (tarfile.TarError, OSError, EOFError) as e:
        raise UpstreamError(f"the download is not a readable tarball: {e}") from e
    if not written:
        raise UpstreamError("the download has no payload/ folder, so it is not a template release")
    _LOGGER.info(f"extracted {written} file(s), {total} bytes, from the release")
    return dest


def _child_env() -> dict[str, str]:
    return {key: os.environ[key] for key in CHILD_ENV_KEYS if key in os.environ} | {"PYTHONUTF8": "1"}


def _plan_in_child(payload: Path, root: Path, cwd: Path, tag: str) -> dict:
    """What the release's own ``init`` would lock for ``root``, computed in a child process and read-only by intent.

    The child is isolated (``python -I``), has a scrubbed environment (no token, no home folder), a timeout, and runs in
    ``cwd`` (the scratch folder). **This executes the release's ``tools/init.py`` and ``tools/framework_config.py``**:
    it is not a sandbox (the child can still reach any file the user can), so what is trusted is whoever can push a
    ``vX.Y.Z`` tag to the upstream.

    :raises UpstreamError: the child failed, timed out, or printed no result.
    """
    argv = [sys.executable, "-I", "-c", CHILD_DRIVER, str(payload), str(root)]
    return _run_child(argv, cwd, tag, "the paths it changes")


def _run_child(argv: list[str], cwd: Path, tag: str, purpose: str) -> dict:
    """Run a driver over the release ``tag``'s code in a child process and return its one marked result. ``tag`` and
    ``purpose`` name the run in the log and in every error, since ``--update`` plans with two releases (#230).

    :raises UpstreamError: the child failed, timed out, printed no result, or said it could not plan."""
    _LOGGER.info(f"planning with {tag}'s init for {purpose}, in a child process (timeout {CHILD_TIMEOUT} s, cwd {cwd})")
    try:
        bounded = _run_bounded(argv, cwd, _child_env(), CHILD_TIMEOUT)  # a group: its own children end with it
    except OSError as e:
        raise UpstreamError(f"{tag}'s init could not be started: {e}") from e
    if bounded is None:
        raise UpstreamError(f"{tag}'s init did not finish in {CHILD_TIMEOUT} s, so its process tree was ended")
    result = subprocess.CompletedProcess(argv, *bounded)
    lines = [line for line in (result.stdout or "").splitlines() if line.startswith(RESULT_MARK)]
    if not lines:
        tail = (result.stderr or "").strip().splitlines()
        raise UpstreamError(
            f"{tag}'s init exited {result.returncode} without a result" + (f": {tail[-1]}" if tail else "")
        )
    try:
        out = json.loads(lines[-1][len(RESULT_MARK) :])
    except ValueError as e:
        raise UpstreamError(f"{tag}'s init printed an unreadable result: {e}") from e
    if result.returncode != 0:
        raise UpstreamError(f"{tag}'s init exited {result.returncode} after printing a result, so it is not trusted")
    if not isinstance(out, dict) or not out.get("ok"):
        raise UpstreamError(
            f"{tag}'s init cannot read this repository: {out.get('error') if isinstance(out, dict) else out}"
        )
    return out


#: Run in a child process for ``--update``, once per payload: plans ``new`` over the repository with the release's
#: own code. Mode ``write`` (the newest release) writes the bytes of every create and update under the output folder,
#: refusing a path that would leave it, and returns the actions, the new lock, the refusals, the executable paths and
#: what the payload ships; mode ``paths`` (the locked release) returns the paths it has a project-owned action for and
#: writes nothing. Only the parent writes the repository.
UPDATE_DRIVER = r"""
import importlib.util, json, sys
from pathlib import Path
payload, root, mode, out_dir = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], Path(sys.argv[4])
def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod
def inside(rel):
    parts = rel.split("/")
    return bool(rel) and not rel.startswith("/") and "\\" not in rel and ":" not in rel and all(
        part not in ("", ".", "..") for part in parts
    )
try:
    tools = payload / "tools"
    sys.path.insert(0, str(tools))
    config = load("framework_config", tools / "framework_config.py")
    initialiser = load("upstream_init", tools / "init.py")
    project = config.load_project(root / "project.json")
    plan = initialiser.plan_new(payload, root, project)
    if mode == "paths":
        out = {"ok": True, "project_owned": sorted({a.path for a in plan.actions if a.kind == "project-owned"})}
    elif mode == "write":
        text = plan.generated.get("framework.lock")
        if not text:
            raise RuntimeError("the release's init produced no lock")
        bad = sorted(rel for rel in plan.contents if not inside(rel))
        if bad:
            raise RuntimeError(f"the plan names a path outside the output folder: {bad[0]!r}")
        base = out_dir.resolve()
        for rel, data in plan.contents.items():
            dest = out_dir.joinpath(*rel.split("/"))
            if not dest.resolve().is_relative_to(base):
                raise RuntimeError(f"the plan names a path outside the output folder: {rel!r}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            with open(dest, "xb") as handle:
                handle.write(data)
        out = {
            "ok": True,
            "actions": [[a.path, a.op, a.kind] for a in plan.actions],
            "lock": text,
            "refusals": list(plan.refusals),
            "executable": sorted(plan.executable),
            "shipped": sorted(initialiser.discover(payload)),
        }
    else:
        raise RuntimeError(f"unknown mode {mode!r}")
except BaseException as e:
    out = {"ok": False, "error": type(e).__name__ + ": " + str(e)}
sys.stdout.write("\n" + MARK + json.dumps(out) + "\n")
sys.stdout.flush()
""".replace("MARK", repr(RESULT_MARK))


def _plan_release(payload: Path, root: Path, scratch: Path, mode: str, tag: str) -> dict:
    """The release ``tag``'s own plan for ``root``, in a child process (``mode`` ``write`` or ``paths``; see
    ``UPDATE_DRIVER``). ``write`` puts its output under ``scratch/out``.

    :raises UpstreamError: the child failed, or its result is not the shape asked for."""
    argv = [sys.executable, "-I", "-c", UPDATE_DRIVER, str(payload), str(root), mode, str(scratch / "out")]
    purpose = "the files to write" if mode == "write" else "the locked release's project-owned files"
    out = _run_child(argv, scratch, tag, purpose)
    keys = {"actions", "lock", "refusals", "executable", "shipped"} if mode == "write" else {"project_owned"}
    if not keys <= set(out):
        raise UpstreamError(f"{tag}'s init answered without {sorted(keys - set(out))}")
    return out


def _output(out_dir: Path, rel: str) -> Path:
    """The file the release's plan wrote for ``rel``, which must be a regular file under ``out_dir``.

    :raises UpstreamError: it is missing, a symlink, a folder, or not under ``out_dir``."""
    path = out_dir.joinpath(*rel.split("/"))
    try:
        info = os.lstat(path)
    except OSError as e:
        raise UpstreamError(f"the release's plan for {rel} is not a regular file: {e}") from e
    if not stat.S_ISREG(info.st_mode) or not path.resolve().is_relative_to(out_dir.resolve()):
        raise UpstreamError(f"the release's plan for {rel} is not a regular file under its output folder")
    return path


def upstream_report(
    root: Path,
    *,
    today: datetime.date | None = None,
    which: Callable[[str], str | None] = shutil.which,
) -> tuple[int, list[str]]:
    """The ``--upstream`` report as ``(exit code, lines)``; see the module docstring. ``which`` finds git."""
    try:
        return _upstream(root, today or datetime.datetime.now(datetime.UTC).date(), which)
    except (UpstreamError, fc.ConfigError) as e:
        _LOGGER.warning(f"cannot tell: {e}")
        return 2, [f"upstream: cannot tell: {e}"]


def _find_git(which: Callable[[str], str | None]) -> str:
    """The path of git.

    :raises UpstreamError: git is not on the path."""
    git = which("git")
    if git is None:
        raise UpstreamError("git is not on the path: install git, then run this again")
    return git


def _locked_version(text: str) -> tuple[int, int, int]:
    """The lock's template version as numbers.

    :raises UpstreamError: it is not X.Y.Z."""
    semver = _SEMVER_RE.fullmatch(text)
    if semver is None:
        raise UpstreamError(f"framework.lock has template version {text!r}, which is not X.Y.Z")
    major, minor, patch = (int(n) for n in semver.groups())
    return major, minor, patch


def _upstream(root: Path, today: datetime.date, which: Callable[[str], str | None]) -> tuple[int, list[str]]:
    config = fc.load_framework(root / "framework.toml")
    if config.upstream is None:
        raise UpstreamError(NO_UPSTREAM)
    lock = ini.read_lock(root)
    if lock is None:
        raise UpstreamError("there is no framework.lock, so there is nothing to compare with the release")
    fc.load_project(root / "project.json")
    git = _find_git(which)
    locked_text, files, _ = lock
    locked = _locked_version(locked_text)
    url = release_url(config.upstream)
    tags = release_tags(url, git, root, _split(config.upstream)[0])
    tag = max(tags, key=tags.__getitem__)
    latest = tags[tag]
    latest_text = ".".join(str(n) for n in latest)
    header = f"upstream {qualified(config.upstream)}: newest release {tag}"
    _LOGGER.info(f"locked {locked_text}, newest {latest_text}")
    if latest == locked:
        return 0, [header, f"lock is current: {locked_text} locked, {latest_text} is the latest release"]
    if latest < locked:
        return 0, [header, f"lock is ahead: {locked_text} is newer than the latest release {latest_text}"]
    scratch = Path(tempfile.mkdtemp(prefix="framework-sync-"))
    try:
        payload = fetch_tags(url, [tag], scratch, git)[tag]
        day = tag_day(scratch / "git", tag, git)
        planned = _plan_in_child(payload, root, scratch, tag)
    finally:
        remove_tree(scratch)
    header += f" ({day.isoformat()}, from the tag)"
    theirs: dict[str, str] = planned["files"]
    shipped = set(planned["shipped"])
    overridden = {o.target for o in config.overrides}
    changed = sorted(p for p in files if p in theirs and files[p] != theirs[p])
    added = sorted(set(theirs) - set(files))
    removed = sorted(p for p in files if p not in shipped and p not in theirs)  # theirs has rendered names
    moved = len(changed) + len(added) + len(removed)
    lines = [header]
    if moved:
        lines.append(f"lock is behind: {locked_text} locked, {latest_text} current, {moved} managed file(s) changed")
    else:
        lines.append(f"lock is behind: {locked_text} locked, {latest_text} current, no managed file differs")
    lines += [f"  changed: {p}" + (" (you override this file)" if p in overridden else "") for p in changed]
    lines += [f"  added: {p}" for p in added]
    lines += [f"  removed: {p}" + (" (you override this file)" if p in overridden else "") for p in removed]
    for refusal in planned["refusals"]:
        if not refusal.startswith("framework.lock is for template"):  # always true for a lock that is behind
            lines.append(f"  note: the release's init refuses: {refusal}")
    behind = max(0, (today - day).days)
    window = config.max_age_days
    if moved and behind > window:
        lines.append(f"behind for {behind} day(s), past the {window}-day window")
        return 1, lines
    lines.append(
        f"behind for {behind} day(s), inside the {window}-day window" if moved else f"{behind} day(s) since the release"
    )
    return 0, lines


# -------------------------------------------------------------------------
# --update
class Refused(Exception):
    """The repository is not in a state to update, or the release cannot be taken as it is; nothing was written.
    Exit code 1. ``details`` are printed after the message, one per line."""

    def __init__(self, message: str, details: list[str] | None = None) -> None:
        super().__init__(message)
        self.details = details or []


#: How many unclean paths a refusal lists before it counts the rest.
SHOWN_PATHS = 10
UPDATE_BRANCH = "template-update/{tag}"


def update_report(root: Path, *, which: Callable[[str], str | None] = shutil.which) -> tuple[int, list[str]]:
    """The ``--update`` run as ``(exit code, lines)``: 0 updated or nothing to update, 1 refused with nothing written,
    2 could not tell or could not finish (the repository as it was found, or the step-7 branch kept). See the module
    docstring."""
    try:
        return _update(root, which)
    except Refused as e:
        _LOGGER.warning(f"refused: {e}")
        return 1, [f"update: refused: {e}", *(f"  {line}" for line in e.details)]
    except (UpstreamError, fc.ConfigError, OSError) as e:  # never exit 1: that says refused, with nothing written
        _LOGGER.warning(f"cannot update: {e}")
        return 2, [f"update: cannot tell: {e}"]


def _unclean(git: str, root: Path) -> list[str]:
    """The paths ``git status`` names (modified, staged or untracked); a git failure raises ``UpstreamError``."""
    out = _git(git, ["status", "--porcelain=v1", "-z", "--untracked-files=all"], root)
    entries = [entry for entry in out.split("\0") if entry]
    paths: list[str] = []
    skip = False
    for entry in entries:
        if skip:  # the source of a rename or a copy follows its entry
            skip = False
            continue
        paths.append(entry[3:])
        skip = entry[0] in "RC"
    return paths


def _start(git: str, root: Path) -> tuple[fc.FrameworkConfig, str, dict[str, str], str]:
    """Step 1, before any network call: the repository read and found ready. Returns the configuration, the locked
    version, the locked files and the starting branch.

    :raises Refused: not the top level, a detached ``HEAD``, an unclean tree, or a sync finding.
    :raises UpstreamError: a file cannot be read, or git failed."""
    top = _git(git, ["rev-parse", "--show-toplevel"], root).strip()
    if Path(top).resolve() != root.resolve():
        raise Refused(f"--root must be the repository's top level, {top}; {root} is below it")
    config = fc.load_framework(root / "framework.toml")
    if config.upstream is None:
        raise UpstreamError(NO_UPSTREAM)
    fc.load_project(root / "project.json")
    lock = ini.read_lock(root)
    if lock is None:
        raise UpstreamError("there is no framework.lock, so there is nothing to update from")
    locked_text, files, _ = lock
    _locked_version(locked_text)
    head = run_git([git, "symbolic-ref", "--quiet", "--short", "HEAD"], root)
    if head.returncode == 1:
        raise Refused("HEAD is detached: switch to the branch the update should start from")
    if head.returncode != 0:
        words = (head.stderr or "").strip().splitlines()
        raise UpstreamError(f"git symbolic-ref failed ({head.returncode}): {words[0] if words else 'no message'}")
    start = head.stdout.strip()
    unclean = _unclean(git, root)
    if unclean:
        shown = unclean[:SHOWN_PATHS]
        more = [f"... and {len(unclean) - len(shown)} more"] if len(unclean) > len(shown) else []
        raise Refused(
            f"the working tree is not clean ({len(unclean)} path(s)): commit or remove them first", [*shown, *more]
        )
    found = report(root).findings
    if found:
        raise Refused("the sync check has findings: fix them first", [str(f) for f in found])
    return config, locked_text, files, start


def _update(root: Path, which: Callable[[str], str | None]) -> tuple[int, list[str]]:
    git = _find_git(which)
    config, locked_text, old_files, start = _start(git, root)
    assert config.upstream is not None  # _start refuses a configuration without one
    url = release_url(config.upstream)
    tags = release_tags(url, git, root, _split(config.upstream)[0])
    tag = max(tags, key=tags.__getitem__)
    newest = ".".join(str(n) for n in tags[tag])
    locked = _locked_version(locked_text)
    _LOGGER.info(f"locked {locked_text}, newest {newest}, starting on {start}")
    if tags[tag] == locked:
        return 0, [f"nothing to update: {locked_text} locked, {newest} is the newest release"]
    if tags[tag] < locked:
        return 0, [f"lock is ahead: {locked_text} locked, {newest} is the newest release; nothing written"]
    branch = UPDATE_BRANCH.format(tag=tag)
    exists = run_git([git, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"], root)
    if exists.returncode == 0:
        raise Refused(f"{branch} exists; delete it or finish it first")
    if exists.returncode != 1:
        words = (exists.stderr or "").strip().splitlines()
        raise UpstreamError(f"git rev-parse failed ({exists.returncode}): {words[0] if words else 'no message'}")
    old_tag = f"v{locked_text}"
    scratch = Path(tempfile.mkdtemp(prefix="framework-update-"))
    try:
        fetched = [tag, old_tag] if old_tag in tags else [tag]
        payloads = fetch_tags(url, fetched, scratch, git)
        plan = UpdatePlan(
            tag=tag,
            old_tag=old_tag,
            start=start,
            branch=branch,
            scratch=scratch,
            upstream=config.upstream,
            payload=payloads[tag],
        )
        planned = _plan_release(payloads[tag], root, scratch, "write", tag)
        older: set[str] | None = None
        if old_tag in payloads:
            older = set(_plan_release(payloads[old_tag], root, scratch, "paths", old_tag)["project_owned"])
        else:
            plan.notes.append(f"{old_tag} has no tag, so no project-owned seed is written")
        _decide(plan, root, git, config, old_files, planned, older)
        return _carry_out(plan, root, git)
    finally:
        remove_tree(scratch)


@dataclass
class UpdatePlan:
    """What ``--update`` decided, before any write (step 5), and what the report needs."""

    tag: str
    old_tag: str
    start: str
    branch: str
    scratch: Path
    upstream: str
    write: list[str] = field(default_factory=list)  # managed and parametrised files, from scratch/out
    seeds: list[str] = field(default_factory=list)  # project-owned files the release adds, written create-only
    delete: list[str] = field(default_factory=list)
    kept: list[tuple[str, str]] = field(default_factory=list)  # overridden, changed by the release: path, reason
    kept_unchanged: int = 0
    removed_overrides: list[tuple[str, str]] = field(default_factory=list)  # target, why
    left: list[str] = field(default_factory=list)  # no longer locked, left in place
    executable: set[str] = field(default_factory=set)
    lock_text: str = ""
    toml_text: str = ""  # framework.toml with the new version and without the overrides removed
    payload: Path | None = None  # the newest release's payload, unpacked in the scratch folder
    hand_steps: list[tuple[str, str, str]] = field(default_factory=list)  # version, title, the section's text
    message: str = ""
    counts: tuple[int, int, int] = (0, 0, 0)  # managed files changed, added, removed
    notes: list[str] = field(default_factory=list)


#: Why an override goes, as the report says it.
STALE = "stale"
DROPPED = "no longer the template's: keep it or delete it"


def _decide(
    plan: UpdatePlan,
    root: Path,
    git: str,
    config: fc.FrameworkConfig,
    old: dict[str, str],
    planned: dict,
    older: set[str] | None,
) -> None:
    """Step 5's table: fill ``plan`` from the release's plan, or refuse. Writes nothing.

    :raises Refused: the release's plan refuses, ``project.json`` would change, or a path to write is ignored.
    :raises UpstreamError: the plan is not the shape expected, or git failed."""
    refusals = [r for r in planned["refusals"] if not r.startswith("framework.lock is for template")]
    if refusals:
        raise Refused("the release's init refuses to plan this repository", refusals)
    try:
        new: dict[str, str] = json.loads(planned["lock"])["files"]
    except (ValueError, KeyError, TypeError) as e:
        raise UpstreamError(f"the release's init gave a lock that cannot be read: {e}") from e
    plan.lock_text = planned["lock"]
    shipped = set(planned["shipped"])
    removed = {p for p in old if p not in shipped and p not in new}  # --upstream's rule
    overrides = {o.target: o.reason for o in config.overrides}
    managed: set[str] = set()
    for path, op, kind in planned["actions"]:
        if kind == "generated":
            if path == "project.json" and op != "unchanged":
                raise Refused(f"the release would {op} project.json; take this release by hand")
            continue
        if kind == "project-owned":
            if op == "create" and older is not None and path not in older:
                plan.seeds.append(path)
            continue
        managed.add(path)
        if op == "update" or (op == "create" and path not in overrides):
            plan.write.append(path)
        elif op == "override":
            if old.get(path) != new.get(path):
                plan.kept.append((path, overrides[path]))
            else:
                plan.kept_unchanged += 1
        elif op == "orphan":
            if path in removed and path not in overrides:
                plan.delete.append(path)
            else:
                plan.left.append(path)
        elif op == "refuse":
            raise Refused(f"the release's init refuses {path}")
    top = root.resolve()
    for target, reason in overrides.items():
        if target == fc.HANDOFF_OVERRIDE_TARGET:
            continue
        if target not in new:
            plan.removed_overrides.append((target, DROPPED if target in old else "unknown"))
            continue
        found, _ = _file(root, top, target, new[target], reason)
        if any(f.rule == "override-stale" for f in found):
            plan.removed_overrides.append((target, STALE))
    for path in [*plan.write, *plan.seeds]:
        _output(plan.scratch / "out", path)  # a regular file the release's plan wrote, or cannot tell
    plan.executable = set(planned["executable"]) | (_executable_in_tree(plan.scratch / "git", plan.tag, git) & managed)
    _refuse_ignored(git, root, [*plan.write, *plan.seeds])
    try:
        text = (root / "framework.toml").read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise UpstreamError(f"framework.toml cannot be read: {e}") from e
    plan.toml_text = _edit_framework_text(
        text, config, plan.old_tag[1:], plan.tag[1:], [target for target, _ in plan.removed_overrides]
    )
    changed = sum(1 for p in plan.write if p in old)
    plan.counts = (changed, len(plan.write) - changed, len(plan.delete))
    guide = plan.payload / "Docs" / "standards" / "updating.md" if plan.payload else None
    if guide is not None and _guide_exists(guide):
        try:
            text = guide.read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError) as e:
            raise UpstreamError(f"the release's updating.md cannot be read: {e}") from e
        old_version = _locked_version(plan.old_tag[1:])
        new_version = _locked_version(plan.tag[1:])
        plan.hand_steps = _hand_steps(text, old_version, new_version)
    if not plan.hand_steps:
        plan.notes.append(f"no hand steps between {plan.old_tag} and {plan.tag} in updating.md")
    plan.message = _message(plan, _signoff(git, root))
    _check_message(root, plan.message, plan.scratch)
    _LOGGER.info(
        f"decided: {len(plan.write)} to write, {len(plan.seeds)} seed(s), {len(plan.delete)} to delete, "
        f"{len(plan.kept)} kept override(s) the release changed, {len(plan.removed_overrides)} override(s) to remove"
    )


def _guide_exists(guide: Path) -> bool:
    """Whether the release ships ``updating.md``: absent is ``False`` (a note); anything else not a regular file is a
    release that cannot be read, never read as absent (project ledger P-16).

    :raises UpstreamError: it is there but is not a regular file, or cannot be looked at."""
    try:
        info = os.lstat(guide)
    except FileNotFoundError:
        return False
    except OSError as e:
        raise UpstreamError(f"the release's updating.md cannot be read: {e}") from e
    if not stat.S_ISREG(info.st_mode):
        raise UpstreamError("the release's updating.md is not a regular file")
    return True


_SECTION_RE = re.compile(r"## (\d{1,9})\.(\d{1,9})\.(\d{1,9}): (.+)")
_FENCE_RE = re.compile(r"\s*(```|~~~)")
_IDENT_RE = re.compile(r"(.+) <([^<>]+)> \d+ [+-]\d{4}")


def _hand_steps(text: str, old: tuple[int, int, int], new: tuple[int, int, int]) -> list[tuple[str, str, str]]:
    """The sections of ``updating.md`` headed ``## X.Y.Z: <title>`` with ``old < X.Y.Z <= new``, in version order, as
    ``(version, title, text)``; a section runs to the next ``## `` heading outside a fenced code block."""
    sections: list[tuple[tuple[int, int, int], str, list[str]]] = []
    current: list[str] | None = None
    fence: str | None = None
    for line in text.splitlines():
        opened = _FENCE_RE.match(line)
        if opened and (fence is None or opened.group(1) == fence):
            fence = None if fence else opened.group(1)
        elif fence is None and line.startswith("## "):
            current = None
            heading = _SECTION_RE.fullmatch(line.rstrip())
            if heading:
                version = (int(heading.group(1)), int(heading.group(2)), int(heading.group(3)))
                if old < version <= new:
                    current = []
                    sections.append((version, heading.group(4), current))
        if current is not None:
            current.append(line)
    sections.sort(key=lambda section: section[0])
    return [(".".join(map(str, v)), title, "\n".join(body).rstrip() + "\n") for v, title, body in sections]


def _signoff(git: str, root: Path) -> str:
    """The ``Signed-off-by:`` line of the identity git commits as here.

    :raises UpstreamError: git has no identity to give."""
    ident = _git(git, ["var", "GIT_COMMITTER_IDENT"], root).strip()
    match = _IDENT_RE.fullmatch(ident)
    if match is None:
        raise UpstreamError(f"git var GIT_COMMITTER_IDENT gave no name and email: {ident!r}")
    return f"Signed-off-by: {match.group(1)} <{match.group(2)}>"


def _message(plan: UpdatePlan, signoff: str) -> str:
    """The commit message: the titles of the hand steps, never their text (see the spec's *The commit message*)."""
    changed, added, removed = plan.counts
    a, b = plan.old_tag, plan.tag
    lines = [f"chore(framework): take template {b} (from {a})", ""]
    lines += [
        f"{changed} managed file(s) changed, {added} added, {removed} removed; {len(plan.seeds)} project-owned "
        "seed(s) added.",
        "",
    ]

    def group(title: str, items: list[str], tail: list[str] | None = None) -> None:
        """A heading and its items; an empty group is one line, its heading without the parenthesis."""
        if items:
            lines.extend([f"{title}:", *items])
        else:
            lines.append(f"{title.partition(' (')[0]}: none")
        lines.extend(tail or [])
        lines.append("")

    kept = [f"- {p}: {r}\n  see: git diff {a} {b} -- payload/{p}, in a clone of the template" for p, r in plan.kept]
    others = (
        [f"{plan.kept_unchanged} other override(s) in force, unchanged by this release."] if plan.kept_unchanged else []
    )
    group("Kept, overridden, and changed by the release (merge by hand)", kept, others)
    group(
        "Overrides removed (the new lock makes them stale or unknown)",
        [f"- {t}: {w}" for t, w in plan.removed_overrides],
    )
    group("Left in place, no longer locked", [f"- {p}" for p in plan.left])
    group(
        f"Hand steps (Docs/standards/updating.md, {a} to {b})",
        [f"- [ ] {version}: {title}" for version, title, _ in plan.hand_steps],
    )
    lines.append(signoff)
    return "\n".join(lines) + "\n"


def _check_message(root: Path, message: str, scratch: Path) -> None:
    """Check ``message`` with the repository's own ``tools/check_commit_msg.py``, as its ``commit-msg`` hook would.

    :raises Refused: the check rejects it.
    :raises UpstreamError: the check could not run."""
    checker = root / "tools" / "check_commit_msg.py"
    if not checker.is_file():
        raise UpstreamError("the repository has no tools/check_commit_msg.py to check the message with")
    path = scratch / "message"
    path.write_text(message, encoding="utf-8", newline="\n")
    try:
        result = subprocess.run(
            [sys.executable, "-B", str(checker), "--root", str(root), str(path)],  # -B: no __pycache__ written here
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
            timeout=CHILD_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        raise UpstreamError(f"the repository's commit-message check could not run: {e}") from e
    said = [line for line in (result.stdout + result.stderr).splitlines() if line.strip()]
    if result.returncode == 1:
        raise Refused("the repository's commit-message check rejects the update's message", said)
    if result.returncode != 0:
        raise UpstreamError(
            f"the repository's commit-message check exited {result.returncode}" + (f": {said[-1]}" if said else "")
        )


_TABLE_RE = re.compile(r"\s*\[")
_FRAMEWORK_TABLE_RE = re.compile(r"\s*\[\s*framework\s*\]\s*(#.*)?")
_OVERRIDES_TABLE_RE = re.compile(r"\s*\[\[\s*overrides\s*\]\]\s*(#.*)?")


def _edit_framework_text(text: str, config: fc.FrameworkConfig, old: str, new: str, targets: list[str]) -> str:
    """``framework.toml``'s text with its version set to ``new`` and the ``[[overrides]]`` entries of ``targets``
    removed, comments, order and line endings kept. The result must parse to ``config`` with exactly those changes.

    :raises Refused: the edit cannot be made by plain lines (an inline table, a version not on a line of its own)."""
    lines = text.splitlines(keepends=True)
    bare = [line.rstrip("\r\n") for line in lines]
    tables = [i for i, line in enumerate(bare) if _TABLE_RE.match(line)]

    def table_end(start: int) -> int:
        return next((i for i in tables if i > start), len(lines))

    version_re = re.compile(rf'\s*template_version\s*=\s*"{re.escape(old)}"\s*(#.*)?')
    framework = [i for i in tables if _FRAMEWORK_TABLE_RE.fullmatch(bare[i])]
    hits = [i for s in framework for i in range(s + 1, table_end(s)) if version_re.fullmatch(bare[i])]
    if len(hits) != 1:
        raise Refused("framework.toml: cannot set the version by a plain edit; make it by hand and run again")
    i = hits[0]
    lines[i] = lines[i].replace(f'"{old}"', f'"{new}"', 1)
    drop: set[int] = set()
    for target in targets:
        found = []
        for start in (s for s in tables if _OVERRIDES_TABLE_RE.fullmatch(bare[s])):
            end = table_end(start)
            try:
                entry = tomllib.loads("".join(bare[k] + "\n" for k in range(start, end)))["overrides"][0]
            except (tomllib.TOMLDecodeError, KeyError, IndexError, TypeError):
                continue
            if entry.get("target") == target:
                last = max(k for k in range(start, end) if bare[k].strip() and not bare[k].lstrip().startswith("#"))
                found.append(range(start, last + 1))
                if start > 0 and not bare[start - 1].strip():
                    found[-1] = range(start - 1, last + 1)
        if len(found) != 1:
            raise Refused(
                f"framework.toml: cannot remove the override of {target} by a plain edit; make it by hand and run again"
            )
        drop.update(found[0])
    edited = "".join(line for k, line in enumerate(lines) if k not in drop)
    expected = dataclasses.replace(
        config, template_version=new, overrides=tuple(o for o in config.overrides if o.target not in targets)
    )
    try:
        same = fc.parse_framework_text(edited) == expected
    except fc.ConfigError:
        same = False
    if not same:
        raise Refused("framework.toml: cannot make this change by a plain edit; make it by hand and run again")
    return edited


def _executable_in_tree(repo: Path, tag: str, git: str) -> set[str]:
    """The payload's paths whose mode in ``tag``'s tree is ``100755``, without ``payload/``: the release records the
    mode on every system, where Windows' file system does not."""
    out = _git(git, ["ls-tree", "-r", "-z", "--full-tree", tag, "--", "payload"], repo)  # -z: no name is quoted
    found: set[str] = set()
    for line in out.split("\0"):
        meta, _, name = line.partition("\t")
        if meta.split(" ")[0] == "100755" and name.startswith("payload/"):
            found.add(name.removeprefix("payload/"))
    return found


def _refuse_ignored(git: str, root: Path, paths: list[str]) -> None:
    """Refuse when the repository's ``.gitignore`` ignores a path to write: the template never forces a file past it.

    :raises Refused: one or more are ignored.
    :raises UpstreamError: git answered neither yes nor no."""
    ignored: list[str] = []
    for start in range(0, len(paths), 100):
        chunk = paths[start : start + 100]
        result = run_git([git, "check-ignore", "--", *chunk], root)
        if result.returncode == 0:
            ignored += [line.strip() for line in result.stdout.splitlines() if line.strip()]
        elif result.returncode != 1:
            words = (result.stderr or "").strip().splitlines()
            raise UpstreamError(f"git check-ignore failed ({result.returncode}): {words[0] if words else 'no message'}")
    if ignored:
        raise Refused(
            "the repository's .gitignore ignores a file the release writes: un-ignore it, or take this release by hand",
            ignored,
        )


class _Written:
    """What step 6 changed, so that a rollback can undo it: the paths it created, the folders it wrote in."""

    def __init__(self) -> None:
        self.created: list[str] = []
        self.folders: set[Path] = set()


def _carry_out(plan: UpdatePlan, root: Path, git: str) -> tuple[int, list[str]]:
    """Steps 6 to 9: write on the new branch, check, commit, and report. A failure in the write or the commit rolls
    back to the start (exit 2); a finding in the check keeps the branch, uncommitted, and says how to drop it."""
    written = _Written()
    try:
        _git(git, ["switch", "-c", plan.branch], root)
    except UpstreamError as e:
        return 2, [f"update: cannot finish: {e}", *_rollback(plan, root, git, written, switched=False)]
    try:
        edited = _write(plan, root, written)
    except (OSError, UpstreamError) as e:
        return 2, [f"update: cannot finish: the write failed: {e}", *_rollback(plan, root, git, written)]
    try:
        found = report(root).findings
    except (OSError, fc.ConfigError) as e:
        return 2, [f"update: cannot finish: the check could not run: {e}", *_rollback(plan, root, git, written)]
    if found:
        for finding in found:
            _LOGGER.warning(f"step 7: {finding}")
        undo = [f"  git switch --force {plan.start}", *(f"  delete {p}" for p in _undo_order(written.created))]
        undo.append(f"  git branch -D {plan.branch}")
        return 2, [
            "update: the result has sync findings, which is this tool's fault:",
            *(f"  {f}" for f in found),
            f"the update is left uncommitted on {plan.branch} for inspection; to drop it:",
            *undo,
        ]
    try:
        _commit(plan, root, git, edited)
    except (OSError, UpstreamError) as e:
        return 2, [f"update: cannot finish: {e}", *_rollback(plan, root, git, written)]
    return 0, _report(plan)


def _undo_order(created: list[str]) -> list[str]:
    """The paths a run created, in an order they can be removed in: the files, then the folders (ending ``/``)
    deepest first."""
    files = [p for p in created if not p.endswith("/")]
    folders = sorted((p for p in created if p.endswith("/")), key=lambda p: p.count("/"), reverse=True)
    return files + folders


def _write(plan: UpdatePlan, root: Path, written: _Written) -> list[str]:
    """Step 6: every file decided, then the deletions, the lock and ``framework.toml``. Returns every path written,
    deleted or edited, for the commit."""
    out = plan.scratch / "out"
    paths: list[str] = []
    for rel in [*plan.write, *plan.seeds]:
        source = _output(out, rel)
        dest = root / rel
        existed = os.path.lexists(dest)
        written.folders.add(dest.parent)
        for parent in reversed(dest.relative_to(root).parents):
            if parent != Path(".") and not (root / parent).exists():
                written.created.append(parent.as_posix() + "/")
        ini.write_atomic(dest, source.read_bytes(), create_only=rel in plan.seeds, executable=rel in plan.executable)
        if not existed:
            written.created.append(rel)
        _LOGGER.debug(f"wrote {rel}" + (" (a seed)" if rel in plan.seeds else ""))
        paths.append(rel)
    for rel in plan.delete:
        (root / rel).unlink(missing_ok=True)
        _LOGGER.debug(f"deleted {rel}")
        paths.append(rel)
    for rel, text in (("framework.lock", plan.lock_text), ("framework.toml", plan.toml_text)):
        written.folders.add(root)
        ini.write_atomic(root / rel, text.encode("utf-8"))
        paths.append(rel)
    _LOGGER.info(
        f"wrote {len(plan.write)} file(s) and {len(plan.seeds)} seed(s), deleted {len(plan.delete)}, "
        "edited framework.lock and framework.toml"
    )
    return paths


def _commit(plan: UpdatePlan, root: Path, git: str, paths: list[str]) -> None:
    """Step 8: stage exactly ``paths``, mark the executable ones, and commit with the checked message and no hook.

    :raises UpstreamError: git failed."""
    listing = plan.scratch / "paths"
    listing.write_bytes(b"".join(p.encode("utf-8") + b"\0" for p in paths))
    _git(
        git,
        ["--literal-pathspecs", "add", "-A", f"--pathspec-from-file={listing}", "--pathspec-file-nul"],
        root,
    )
    for rel in sorted(set(paths) & plan.executable):
        _git(git, ["--literal-pathspecs", "update-index", "--chmod=+x", "--", rel], root)
    no_hooks = plan.scratch / "no-hooks"
    no_hooks.mkdir(exist_ok=True)
    message = plan.scratch / "message"
    message.write_text(plan.message, encoding="utf-8", newline="\n")
    _git(git, ["-c", f"core.hooksPath={no_hooks}", "commit", "--no-verify", "-q", "-F", str(message)], root)


def _rollback(plan: UpdatePlan, root: Path, git: str, written: _Written, *, switched: bool = True) -> list[str]:
    """Restore the start: the starting branch checked out by force, every path the run created removed (with any
    ``*.init-tmp`` left in a folder it wrote to), the new branch deleted. Returns what it could not restore."""
    failed: list[str] = []
    if switched:
        result = run_git([git, "switch", "--force", plan.start], root)
        if result.returncode != 0:
            failed.append(f"git switch --force {plan.start} failed: {result.stderr.strip()}")
    for rel in _undo_order(written.created):  # a write can fail before every folder it named was made
        path = root / rel.rstrip("/")
        try:
            if rel.endswith("/"):
                path.rmdir()
            elif os.path.lexists(path):
                path.unlink()
        except FileNotFoundError:
            pass
        except OSError as e:
            failed.append(f"{rel} could not be removed: {e}")
    for folder in written.folders:
        for leftover in folder.glob("*.init-tmp") if folder.is_dir() else []:
            try:
                leftover.unlink()
            except OSError as e:
                failed.append(f"{leftover.relative_to(root).as_posix()} could not be removed: {e}")
    if switched:
        result = run_git([git, "branch", "-D", plan.branch], root)
        if result.returncode != 0:
            failed.append(f"git branch -D {plan.branch} failed: {result.stderr.strip()}")
    if failed:
        for line in failed:
            _LOGGER.warning(f"rollback: {line}")
        return ["the rollback could not restore everything:", *(f"  {line}" for line in failed)]
    _LOGGER.info(f"rolled back to {plan.start}; {plan.branch} deleted")
    return [f"rolled back: {plan.start} checked out, {plan.branch} deleted, nothing left behind"]


#: A hand step found by name, as *Several releases at once* finds it: ``N. **Take`` or ``N. **Check it``.
_NAMED_STEP_RE = re.compile(r"(\d+\.\s+)\*\*(Take|Check it)\b")


def _marked_steps(text: str, version: str, newest: str) -> list[str]:
    """A release section's lines, its *Take* and *Check it* steps marked as *Several releases at once* reads them
    (#229): every *Take* is the render ``--update`` did, and a *Check it* before the newest release's waits for the one
    check against it."""
    lines = []
    for line in text.rstrip("\n").splitlines():
        step = _NAMED_STEP_RE.match(line)
        if step and step.group(2) == "Take":
            line = f"{step.group(1)}(done: --update's render) {line[step.end(1) :]}"
        elif step and version != newest:
            line = f"{step.group(1)}(not here: the one check against {newest}, below) {line[step.end(1) :]}"
        lines.append(line)
    return lines


def _report(plan: UpdatePlan) -> list[str]:
    """Step 9: the message, each hand step's text, then where the release is and what is next."""
    lines = plan.message.rstrip("\n").splitlines()
    newest = plan.tag.removeprefix("v")
    if plan.hand_steps:
        lines += [
            "",
            "hand steps, oldest first, by updating.md's Several releases at once: each Take is this run's render;",
            f"a step before a Take is done now; each Check it waits for the one check against {newest}",
        ]
    for version, _, text in plan.hand_steps:
        lines += ["", *_marked_steps(text, version, newest)]
    lines += [""] + [f"note: {note}" for note in plan.notes]
    if plan.seeds:
        # A hand step that copies a seed from the render is done: this run wrote it (a downstream finding on 0.11.0).
        lines.append(
            f"seeded by this run, so a hand step that copies one from the render is done: {', '.join(plan.seeds)}"
        )
    lines += [
        f"release: https://{qualified(plan.upstream)}/releases/tag/{plan.tag}",
        f"branch: {plan.branch}, one commit, not pushed",
        # make sync first: a fresh clone's environment is not CI's until it is synced the way CI syncs it, extras
        # included (a downstream update of 0.11.1: make sync alone uninstalled them and make check skipped their tests)
        "next: sync as your CI syncs, extras included (make sync syncs the dev group only and removes them),",
        "      then make check on the branch (its commit ran no hooks); the hand steps and the kept overrides;",
        "      then push it and open one pull request with Template findings (updating.md, step 7)",
    ]
    return lines


def main(
    argv: list[str] | None = None,
    *,
    today: datetime.date | None = None,
    which: Callable[[str], str | None] = shutil.which,
) -> int:
    """Run the sync check; returns 0 clean, 1 findings, 2 unusable. ``which`` finds git for ``--upstream``."""
    for stream in (sys.stdout, sys.stderr):  # a finding naming a non-ASCII file must not crash the report
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="backslashreplace")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="compare every locked file with the lock (offline)")
    mode.add_argument("--upstream", action="store_true", help="has the template moved on? (needs git and the network)")
    mode.add_argument(
        "--update", action="store_true", help="take the newest release onto a local branch, as one commit (needs git)"
    )
    parser.add_argument("--root", type=Path, default=ROOT, help="the repository (default: this one)")
    parser.add_argument("-v", "--verbose", action="store_true", help="log what was checked to standard error")
    args = parser.parse_args(argv)
    log_setup.configure(args.verbose)
    root = args.root.resolve()
    if not root.is_dir():
        print(f"sync check: cannot run: {root} is not a directory")
        return 2
    if args.upstream or args.update:
        if args.upstream:
            code, lines = upstream_report(root, today=today, which=which)
        else:
            code, lines = update_report(root, which=which)
        for line in lines:
            print(line)
        return code
    try:
        result = report(root)
    except fc.ConfigError as e:
        print(f"sync check: cannot run: {e}")
        return 2
    for finding in result.findings:
        print(finding)
    for path, reason in result.honoured:
        print(f"override in force: {path}: {reason}")
    if result.findings:
        print(f"sync check: {len(result.findings)} finding(s)")
        return 1
    count = len(result.honoured)
    print("sync check: clean" + (f" ({count} override{'s' if count != 1 else ''} in force)" if count else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
