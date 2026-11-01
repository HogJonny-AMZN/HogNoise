"""
Framework: the sync check: is every managed file as the lock says, and (later) has the template moved on.
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

``--upstream`` asks the other question: has the template moved on? It reads the latest **tagged release** (``vX.Y.Z``)
of the repository named by ``[framework] upstream`` in ``framework.toml`` through ``gh``, and if the lock is behind it
downloads that tag's payload and runs the tag's own ``init`` classifier and renderer read-only, with this repository's
``project.json``, to see which locked files would change, appear or go. So the answer is what ``init`` would write,
not a second implementation of its rules. It prints::

    lock is behind: 0.1.0 locked, 0.2.0 current, 3 managed file(s) changed
      changed: tools/check.py
      added: tools/new.py
      removed: tools/old.py
    behind for 2 day(s), inside the 14-day window

and exits 0 when current or inside the window (``max_age_days`` in ``framework.toml``, default 14, counted from the
tag's date), 1 when the lock has been behind for longer, and 2 when it could not tell: no ``gh``, no network, no
upstream configured, no tagged release, no lock or ``project.json``, a download that is not a payload or has an unsafe
member. Nothing in the repository is written by this tool, and the download is removed.

**It executes code from the release.** The tag's own ``tools/init.py`` and ``tools/framework_config.py`` are run, in a
child process (``python -I``, a scrubbed environment with no token and no home folder, a timeout, the scratch folder
as its working directory) whose output is discarded except one marked result line, so the release's code cannot end
this process, change its modules, print into the report or see ``GH_TOKEN``. That is not a sandbox: the child can
still reach any file the user can (the ``gh`` login lives in the user's home folder), and ``plan_new`` is read-only
because the code is, not because anything enforces it. What is trusted is **whoever can push a ``vX.Y.Z`` tag to the
upstream**; a published GitHub Release for the tag is preferred (its date starts the window, and it is a deliberate
act) but not required. Point ``upstream`` only at a repository you trust at that level.

Run standalone (exit code 0 clean, 1 findings, 2 the repository or its configuration is unusable)::

    uv run python tools/framework_sync.py (--check | --upstream) [-v] [--root PATH]
"""

from __future__ import annotations

import argparse
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
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import framework_config as fc
import init as ini

# -------------------------------------------------------------------------
# module global scope
_MODULE_NAME = "tools.framework_sync"
__version__ = "0.1.0"
__updated__ = "2026-10-15"
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
GhRunner = Callable[..., subprocess.CompletedProcess]

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


def run_gh(argv: list[str], output: Path | None = None) -> subprocess.CompletedProcess:
    """Run ``gh`` with no stdin; with ``output`` its standard output (bytes) goes to that file. Never raises."""
    try:
        if output is None:
            return subprocess.run(
                argv,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                stdin=subprocess.DEVNULL,
                timeout=120,
                check=False,
            )
        with output.open("wb") as handle:
            result = subprocess.run(
                argv, stdout=handle, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, timeout=300, check=False
            )
        return subprocess.CompletedProcess(argv, result.returncode, "", result.stderr.decode("utf-8", "replace"))
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(argv, 124, "", "gh timed out")
    except OSError as e:
        return subprocess.CompletedProcess(argv, 127, "", f"cannot start gh: {e}")


def _gh(gh: GhRunner, argv: list[str], output: Path | None = None) -> str:
    _LOGGER.info(f"gh {' '.join(argv[1:])}")
    result = gh(argv, output) if output is not None else gh(argv)
    if result.returncode != 0:
        words = (result.stderr or result.stdout or "").strip().splitlines()
        raise UpstreamError(f"gh failed ({result.returncode}): {words[0] if words else 'no message'}")
    return result.stdout or ""


def latest_release(
    upstream: str, gh: GhRunner, gh_path: str = "gh"
) -> tuple[str, tuple[int, int, int], datetime.date, str]:
    """The highest ``vX.Y.Z`` tag of ``upstream``, its version, the day it counts from and where that day came from
    (``release`` when a GitHub Release was published for the tag, else ``commit``).

    :raises UpstreamError: there is none, or ``gh`` failed.
    """
    refs = _gh(gh, [gh_path, "api", "--paginate", f"repos/{upstream}/git/matching-refs/tags/v", "--jq", ".[].ref"])
    found = []
    for line in refs.splitlines():
        name = line.strip().removeprefix("refs/tags/")
        match = _TAG_RE.fullmatch(name)
        if match:
            found.append((tuple(int(n) for n in match.groups()), name))
        else:
            _LOGGER.debug(f"ignored tag {name!r}: not vX.Y.Z")
    if not found:
        raise UpstreamError(f"{upstream} has no tagged release (a tag like v0.2.0): there is nothing to compare with")
    version, tag = max(found)
    _LOGGER.info(f"{upstream}: {len(found)} release tag(s), the highest is {tag}")
    source, stamp = "release", ""
    try:
        stamp = _gh(gh, [gh_path, "api", f"repos/{upstream}/releases/tags/{tag}", "--jq", ".published_at"]).strip()
    except UpstreamError as e:
        if "404" not in str(e) and "Not Found" not in str(e):  # a timeout or a 5xx is not proof there is no release
            raise
        _LOGGER.info(f"{tag} has no published release ({e}); the commit's date counts instead")
    if not stamp or stamp == "null":
        source = "commit"
        stamp = _gh(gh, [gh_path, "api", f"repos/{upstream}/commits/{tag}", "--jq", ".commit.committer.date"]).strip()
    try:
        day = datetime.date.fromisoformat(stamp[:10])
    except ValueError as e:
        raise UpstreamError(f"gh gave no usable date for {tag}: {stamp!r}") from e
    return tag, (version[0], version[1], version[2]), day, source


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


def _plan_in_child(payload: Path, root: Path, cwd: Path) -> dict:
    """What the release's own ``init`` would lock for ``root``, computed in a child process and read-only by intent.

    The child is isolated (``python -I``), has a scrubbed environment (no token, no home folder), a timeout, and runs in
    ``cwd`` (the scratch folder). **This executes the release's ``tools/init.py`` and
    ``tools/framework_config.py``**: it
    is not a sandbox (the child can still reach any file the user can), so what is trusted is whoever can push a
    ``vX.Y.Z`` tag to the upstream.

    :raises UpstreamError: the child failed, timed out, or printed no result.
    """
    argv = [sys.executable, "-I", "-c", CHILD_DRIVER, str(payload), str(root)]
    _LOGGER.info(f"planning with the release's init in a child process (timeout {CHILD_TIMEOUT} s, cwd {cwd})")
    try:
        result = subprocess.run(
            argv,
            cwd=cwd,
            env=_child_env(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
            timeout=CHILD_TIMEOUT,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise UpstreamError(f"the release's init did not finish in {CHILD_TIMEOUT} s") from e
    except OSError as e:
        raise UpstreamError(f"the release's init could not be started: {e}") from e
    lines = [line for line in (result.stdout or "").splitlines() if line.startswith(RESULT_MARK)]
    if not lines:
        tail = (result.stderr or "").strip().splitlines()
        raise UpstreamError(
            f"the release's init exited {result.returncode} without a result" + (f": {tail[-1]}" if tail else "")
        )
    try:
        out = json.loads(lines[-1][len(RESULT_MARK) :])
    except ValueError as e:
        raise UpstreamError(f"the release's init printed an unreadable result: {e}") from e
    if result.returncode != 0:
        raise UpstreamError(
            f"the release's init exited {result.returncode} after printing a result, so it is not trusted"
        )
    if not isinstance(out, dict) or not out.get("ok"):
        raise UpstreamError(
            f"the release's init cannot read this repository: {out.get('error') if isinstance(out, dict) else out}"
        )
    return out


def upstream_report(
    root: Path,
    *,
    gh: GhRunner = run_gh,
    today: datetime.date | None = None,
    which: Callable[[str], str | None] = shutil.which,
) -> tuple[int, list[str]]:
    """The ``--upstream`` report as ``(exit code, lines)``; see the module docstring."""
    try:
        return _upstream(root, gh, today or datetime.datetime.now(datetime.UTC).date(), which)
    except (UpstreamError, fc.ConfigError) as e:
        _LOGGER.warning(f"cannot tell: {e}")
        return 2, [f"upstream: cannot tell: {e}"]


def _upstream(
    root: Path, gh: GhRunner, today: datetime.date, which: Callable[[str], str | None]
) -> tuple[int, list[str]]:
    config = fc.load_framework(root / "framework.toml")
    if config.upstream is None:
        raise UpstreamError('no upstream is configured: set [framework] upstream = "owner/repo" in framework.toml')
    lock = ini.read_lock(root)
    if lock is None:
        raise UpstreamError("there is no framework.lock, so there is nothing to compare with the release")
    fc.load_project(root / "project.json")
    gh_path = which("gh")
    if gh_path is None:
        raise UpstreamError("gh is not on the path: install the GitHub CLI and log in, then run this again")
    locked_text, files, _ = lock
    semver = _SEMVER_RE.fullmatch(locked_text)
    if semver is None:
        raise UpstreamError(f"framework.lock has template version {locked_text!r}, which is not X.Y.Z")
    locked = tuple(int(n) for n in semver.groups())
    tag, latest, day, source = latest_release(config.upstream, gh, gh_path)
    latest_text = ".".join(str(n) for n in latest)
    header = f"upstream {config.upstream}: latest release {tag} ({day.isoformat()}, from the {source})"
    _LOGGER.info(f"locked {locked_text}, latest {latest_text}")
    if latest == locked:
        return 0, [header, f"lock is current: {locked_text} locked, {latest_text} is the latest release"]
    if latest < locked:
        return 0, [header, f"lock is ahead: {locked_text} is newer than the latest release {latest_text}"]
    scratch = Path(tempfile.mkdtemp(prefix="framework-sync-"))
    try:
        tarball = scratch / "release.tar.gz"
        _gh(gh, [gh_path, "api", f"repos/{config.upstream}/tarball/{tag}"], tarball)
        payload = _extract_payload(tarball, scratch / "payload")
        planned = _plan_in_child(payload, root, scratch)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
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


def main(argv: list[str] | None = None, *, gh: GhRunner = run_gh, today: datetime.date | None = None) -> int:
    """Run the sync check; returns 0 clean, 1 findings, 2 unusable."""
    for stream in (sys.stdout, sys.stderr):  # a finding naming a non-ASCII file must not crash the report
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="backslashreplace")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="compare every locked file with the lock (offline)")
    mode.add_argument("--upstream", action="store_true", help="has the template moved on? (needs gh and the network)")
    parser.add_argument("--root", type=Path, default=ROOT, help="the repository (default: this one)")
    parser.add_argument("-v", "--verbose", action="store_true", help="log what was checked to standard error")
    args = parser.parse_args(argv)
    _logging.basicConfig(
        level=_logging.INFO if args.verbose else _logging.WARNING, format="%(message)s", stream=sys.stderr
    )
    root = args.root.resolve()
    if not root.is_dir():
        print(f"sync check: cannot run: {root} is not a directory")
        return 2
    if args.upstream:
        code, lines = upstream_report(root, gh=gh, today=today)
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
