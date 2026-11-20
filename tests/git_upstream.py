"""
Framework: a local git upstream with tagged releases, for the tests of framework_sync.py's git read and --update.
Package: tests/git_upstream

``make_upstream`` builds a bare repository reached by a ``file://`` URL whose ``vX.Y.Z`` tags (annotated or lightweight,
each on its own day) each hold a ``payload/`` folder, a file in it optionally committed as executable (``100755``) so a
hook without a suffix has its mode on every system. ``make_repository`` makes a repository from one release's payload
with that payload's own ``init new``, commits it, and configures a git identity in it, as a person's clone would have.

Every git call here runs with the user's and the system's git configuration switched off (``isolated_env``), so a
machine's ``core.autocrlf``, signing or hooks cannot change what a test sees. The code under test reads the environment
it is given, so a test that runs it sets the same variables (``isolate(monkeypatch)``).
"""

from __future__ import annotations

import datetime
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import framework_config as fc  # noqa: E402

IDENTITY = ("Ada Example", "ada@example.org")
UPSTREAM = "acme/template"
ANSWERS = {
    "name": "Example Project",
    "slug": "example-project",
    "owner": {"name": IDENTITY[0], "email": IDENTITY[1]},
    "default_branch": "main",
    "signoff": True,
    "hygiene": [],
}
#: A small manifest: two managed tools (one in a module a repository may turn off), a dated parametrised note, a
#: parametrised entry file, a hook without a suffix, and project-owned seeds.
MANIFEST = """
[[rule]]
pattern = "tools/two.py"
module = "python-uv"
kind = "managed"

[[rule]]
pattern = "tools/*.py"
module = "core"
kind = "managed"

[[rule]]
pattern = "hooks/*"
module = "core"
kind = "managed"

[[rule]]
pattern = "Docs/standards/*.md"
module = "core"
kind = "managed"

[[rule]]
pattern = "notes/*.md"
module = "core"
kind = "parametrised"

[[rule]]
pattern = "AGENTS.md"
module = "core"
kind = "parametrised"

[[rule]]
pattern = "README.md"
module = "core"
kind = "project-owned"

[[rule]]
pattern = "seeds/*"
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
"""


def framework_text(version: str, **modules: str) -> str:
    """A payload's ``framework.toml`` at ``version``, with ``core`` and ``python-uv`` on."""
    states = {name: "planned" for name in fc.MODULES}
    states.update({"core": "on", "python-uv": "on", "lanes": "off"})
    states.update(modules)
    data = {
        "framework": {"template_version": version, "upstream": UPSTREAM},
        "modules": states,
        "harnesses": {"enabled": []},
        "checks": {"handoff_max_lines": 150},
        "overrides": [],
    }
    return fc.dump_framework(fc.parse_framework(data))


def payload_files(version: str, files: dict[str, str | bytes]) -> dict[str, str | bytes]:
    """A synthetic payload at ``version``: the manifest, its ``framework.toml``, the real initialiser (the tag's own
    classifier) and commit-message check (a repository's own, which ``--update`` runs), and ``files``."""
    real = ("init.py", "framework_config.py", "check_commit_msg.py", "log_setup.py")
    return {
        "framework-manifest.toml": MANIFEST,
        "framework.toml": framework_text(version),
        **{f"tools/{name}": (ROOT / "tools" / name).read_text(encoding="utf-8") for name in real},
        **files,
    }


def isolated_env(day: datetime.date | None = None) -> dict[str, str]:
    """The environment for a git call that sees no user or system configuration; with ``day``, commits and tags made
    under it carry that day."""
    env = os.environ | {
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_AUTHOR_NAME": IDENTITY[0],
        "GIT_AUTHOR_EMAIL": IDENTITY[1],
        "GIT_COMMITTER_NAME": IDENTITY[0],
        "GIT_COMMITTER_EMAIL": IDENTITY[1],
    }
    if day is not None:
        stamp = f"{day.isoformat()}T10:00:00+00:00"
        env |= {"GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp}
    return env


def isolate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Switch off the user's and the system's git configuration for the code under test, as ``git()`` does here."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


def route(monkeypatch: pytest.MonkeyPatch, upstream: Upstream, expected: str, empty: Path) -> None:
    """Have git answer a request for ``expected``, a URL a test writes out, from ``upstream``, and any other
    ``https://`` URL from ``empty``, a folder made here with nothing in it, so a wrong URL fails at once and locally.

    It is git's own configuration (``GIT_CONFIG_COUNT``, ``url.<base>.insteadOf``), and git takes the longest prefix
    that matches, so the code under test asks git for a URL without being patched, and only the right one reaches the
    upstream."""
    empty.mkdir(parents=True)
    monkeypatch.setenv("GIT_CONFIG_COUNT", "2")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", f"url.{upstream.url}.insteadOf")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", expected)
    monkeypatch.setenv("GIT_CONFIG_KEY_1", f"url.{empty.resolve().as_uri()}/.insteadOf")
    monkeypatch.setenv("GIT_CONFIG_VALUE_1", "https://")


def git(cwd: Path, *args: str, day: datetime.date | None = None) -> str:
    """Run git in ``cwd`` and return its standard output; a failure raises with git's own words."""
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=isolated_env(day),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdin=subprocess.DEVNULL,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed ({result.returncode}): {result.stderr.strip()}")
    return result.stdout


@dataclass(frozen=True)
class Release:
    """One tagged release: its tag, the files under ``payload/``, which of them are executable, how it is tagged."""

    tag: str
    files: dict[str, str | bytes]
    executable: frozenset[str] = field(default_factory=frozenset)
    annotated: bool = True
    day: datetime.date = datetime.date(2026, 10, 20)


@dataclass(frozen=True)
class Upstream:
    """A bare repository holding the releases, and the URL that reaches it."""

    bare: Path
    url: str
    work: Path


def make_upstream(base: Path, releases: list[Release]) -> Upstream:
    """A bare repository under ``base`` whose history holds each release in order, each tagged. Each release's
    ``payload/`` replaces the one before, so a file a release leaves out is removed by it."""
    work = base / "upstream-work"
    work.mkdir(parents=True)
    git(work, "init", "-q", "-b", "main")
    for release in releases:
        payload = work / "payload"
        if payload.exists():
            git(work, "rm", "-r", "-q", "payload")
        for rel, content in release.files.items():
            path = payload / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
        git(work, "add", "-A")
        for rel in sorted(release.executable):
            git(work, "update-index", "--chmod=+x", "--", f"payload/{rel}")
        git(work, "commit", "-q", "--allow-empty", "-m", f"release {release.tag}", day=release.day)
        if release.annotated:
            git(work, "tag", "-a", release.tag, "-m", f"{release.tag}", day=release.day)
        else:
            git(work, "tag", release.tag, day=release.day)
    bare = base / "upstream.git"
    git(base, "clone", "-q", "--bare", str(work), str(bare))
    return Upstream(bare, bare.resolve().as_uri(), work)


def checkout_payload(upstream: Upstream, tag: str, dest: Path) -> Path:
    """The ``payload/`` folder of ``tag``, written out to ``dest`` (as the release a repository was made from)."""
    git(upstream.work, "worktree", "add", "-q", "--detach", str(dest), tag)
    return dest / "payload"


def make_repository(upstream: Upstream, tag: str, base: Path, answers: dict | None = None) -> Path:
    """A repository made from ``tag``'s payload with that payload's ``init new``, committed on ``main``, with a git
    identity configured in it. The tag's own ``tools/init.py`` runs, in a child process (``-B``: no ``__pycache__`` in
    the tag's checkout), so a release whose initialiser differs from this checkout's makes its own repository."""
    payload = checkout_payload(upstream, tag, base / f"source-{tag}")
    answers_file = base / "answers.json"
    answers_file.write_text(json.dumps(ANSWERS if answers is None else answers), encoding="utf-8")
    target = base / "made"
    argv = [sys.executable, "-B", str(payload / "tools" / "init.py"), "new", "--answers", str(answers_file)]
    made = subprocess.run(
        [*argv, "--target", str(target), "--no-sync", "--no-checks"],
        cwd=base,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdin=subprocess.DEVNULL,
        timeout=120,
        check=False,
    )
    assert made.returncode == 0, f"init new from {tag} failed ({made.returncode}):\n{made.stdout}\n{made.stderr}"
    git(target, "init", "-q", "-b", "main")
    git(target, "config", "user.name", IDENTITY[0])
    git(target, "config", "user.email", IDENTITY[1])
    git(target, "add", "-A")
    git(target, "commit", "-q", "--no-verify", "-m", f"chore: made from {tag}")
    return target
