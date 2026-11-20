"""
Framework: tests for tools/framework_sync.py --upstream (has the template moved on since this repository was locked).
Package: tests/test_framework_sync_upstream

The upstream is a local bare git repository (``tests/git_upstream.py``) reached by a ``file://`` URL, whose ``vX.Y.Z``
tags hold small synthetic payloads with the real ``init.py`` and ``framework_config.py`` copied in, so no test touches
the network and git does what it does for real. A repository is made from the first version with ``init new`` and
checked against a later one. The release's code runs in a real child process, as it does for real; a "malicious"
release is one whose ``init.py`` has been edited here to misbehave. The hostile-tarball cases call ``_extract_payload``
directly, since git's own archive cannot hold them.
"""

from __future__ import annotations

import dataclasses
import datetime
import io
import json
import shutil
import subprocess
import sys
import tarfile
import time
from collections.abc import Callable
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))

import framework_config as fc  # noqa: E402
import framework_sync as fs  # noqa: E402
import git_upstream as gu  # noqa: E402
import init as ini  # noqa: E402

UPSTREAM = "acme/template"
NAMED = "github.sie.example.com/acme/template"
TAG_DATE = datetime.date(2026, 10, 20)
GIT = shutil.which("git") or "git"
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
pattern = "tools/two.py"
module = "python-uv"
kind = "managed"

[[rule]]
pattern = "tools/*.py"
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
pattern = "framework.toml"
module = "core"
kind = "project-owned"

[[rule]]
pattern = "framework-manifest.toml"
module = "core"
kind = "managed"
"""


def _framework_text(version: str, **modules: str) -> str:
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


def _files(version: str, files: dict[str, str]) -> dict[str, str]:
    """A synthetic payload at ``version`` with the real initialiser inside it (the tag's own classifier)."""
    return {
        "framework-manifest.toml": MANIFEST,
        "framework.toml": _framework_text(version),
        "tools/init.py": (ROOT / "tools" / "init.py").read_text(encoding="utf-8"),
        "tools/framework_config.py": (ROOT / "tools" / "framework_config.py").read_text(encoding="utf-8"),
        **files,
    }


def _payload(root: Path, version: str, files: dict[str, str]) -> Path:
    """The same synthetic payload, written to a folder (for ``init new``, and for the hand procedure)."""
    for rel, text in _files(version, files).items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
    return root


def _tarball(payload: Path, extra: list[tarfile.TarInfo] | None = None) -> bytes:
    """A gzipped tar whose top folder holds the payload, as ``git archive --prefix`` makes it, with ``extra`` added."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for path in sorted(payload.rglob("*")):
            if path.is_file():
                tar.add(path, arcname=f"release/payload/{path.relative_to(payload).as_posix()}")
        tar.add(payload / "framework.toml", arcname="release/README.md")  # a file outside payload/
        for info in extra or []:
            tar.addfile(info, io.BytesIO(b"x") if info.isfile() else None)
    return buffer.getvalue()


V1_FILES = {
    "tools/one.py": "print('one')\n",
    "tools/two.py": "print('two')\n",
    "AGENTS.md": "# {{name}}\n",
    "notes/{{today}}.md": "# {{name}} notes\n",
}
V2_FILES = {
    "tools/one.py": "print('one, improved')\n",
    "tools/three.py": "print('three')\n",
    "AGENTS.md": "# {{name}}\n",
    "notes/{{today}}.md": "# {{name}} notes\n",
}


def _release(version: str, files: dict[str, str], day: datetime.date = TAG_DATE, annotated: bool = True) -> gu.Release:
    return gu.Release(f"v{version}", _files(version, files), day=day, annotated=annotated)


def _v2(version: str = "0.2.0", **kwargs) -> gu.Release:
    return _release(version, V2_FILES, **kwargs)


Serve = Callable[[list[gu.Release]], gu.Upstream]


@pytest.fixture
def serve(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Serve:
    """Serve releases from a local upstream: ``release_url`` points at it, and git sees no user configuration."""
    gu.isolate(monkeypatch)
    made: list[gu.Upstream] = []

    def make(releases: list[gu.Release]) -> gu.Upstream:
        upstream = gu.make_upstream(tmp_path / f"upstream-{len(made)}", releases)
        made.append(upstream)
        monkeypatch.setattr(fs, "release_url", lambda name: upstream.url)
        return upstream

    return make


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repository made from the synthetic payload at 0.1.0."""
    source = _payload(tmp_path / "v1", "0.1.0", V1_FILES)
    answers = tmp_path / "answers.json"
    answers.write_text(json.dumps(ANSWERS), encoding="utf-8")
    target = tmp_path / "made"
    code = ini.main(
        ["new", "--answers", str(answers), "--target", str(target), "--no-sync", "--no-checks"], source=source
    )
    assert code == 0
    return target


def _run(repo: Path, *, today: datetime.date = TAG_DATE, which=lambda tool: GIT) -> tuple[int, str]:
    code, lines = fs.upstream_report(repo, today=today, which=which)
    return code, "\n".join(lines)


def _spy_git(
    monkeypatch: pytest.MonkeyPatch, fail: str | None = None, code: int = 1, err: str | None = None
) -> list[list[str]]:
    """Record every git call; with ``fail``, the call whose subcommand it is exits ``code`` with ``err`` on stderr
    (as given, every line of it) instead of running."""
    calls: list[list[str]] = []
    real = fs.run_git

    def spy(argv: list[str], cwd: Path, timeout: int = fs.GIT_TIMEOUT) -> subprocess.CompletedProcess:
        calls.append(argv)
        if fail is not None and argv[1] == fail:
            return subprocess.CompletedProcess(argv, code, "", f"fatal: {fail} went wrong" if err is None else err)
        return real(argv, cwd, timeout)

    monkeypatch.setattr(fs, "run_git", spy)
    return calls


def _set_upstream(repo: Path, value: str) -> None:
    """Point the repository's ``framework.toml`` at ``value`` in place of the upstream it was made with."""
    toml = repo / "framework.toml"
    text = toml.read_text(encoding="utf-8")
    assert f'upstream = "{UPSTREAM}"' in text
    toml.write_text(text.replace(f'upstream = "{UPSTREAM}"', f'upstream = "{value}"'), encoding="utf-8")


def _edit_init(files: dict[str, str], extra: str) -> dict[str, str]:
    """Make a release's ``init.py`` misbehave: ``extra`` runs at import, before anything else."""
    text = files["tools/init.py"]
    marker = "from __future__ import annotations\n"
    assert marker in text
    return {**files, "tools/init.py": text.replace(marker, marker + extra + "\n", 1)}


# ---- behind, current
def test_a_lock_behind_the_newest_release_lists_what_changed_added_and_removed(repo: Path, serve: Serve) -> None:
    serve([_v2()])
    code, out = _run(repo)
    assert code == 0  # inside the window on the day of the release
    assert "lock is behind: 0.1.0 locked, 0.2.0 current, 3 managed file(s) changed" in out
    assert "changed: tools/one.py" in out
    assert "added: tools/three.py" in out
    assert "removed: tools/two.py" in out
    assert out.splitlines()[0] == "upstream github.com/acme/template: newest release v0.2.0 (2026-10-20, from the tag)"


def test_a_lock_at_the_newest_release_is_current_and_fetches_nothing(
    repo: Path, serve: Serve, monkeypatch: pytest.MonkeyPatch
) -> None:
    serve([_release("0.1.0", V1_FILES)])
    calls = _spy_git(monkeypatch)
    code, out = _run(repo)
    assert code == 0
    assert out.splitlines() == [
        "upstream github.com/acme/template: newest release v0.1.0",
        "lock is current: 0.1.0 locked, 0.1.0 is the latest release",
    ]
    assert [call[1] for call in calls] == ["ls-remote"]


def test_a_lock_newer_than_the_newest_release_is_said_and_is_not_a_failure(repo: Path, serve: Serve) -> None:
    serve([_release("0.0.9", V1_FILES)])
    code, out = _run(repo)
    assert code == 0
    assert "0.1.0 is newer than the latest release 0.0.9" in out


def test_the_highest_version_wins_not_the_last_or_the_alphabetical(repo: Path, serve: Serve) -> None:
    others = [gu.Release(t, {"a.txt": t}) for t in ("v0.9.0", "v1", "release-1", "v1.2.3-rc1", "v0.1.0", "v0.2.0")]
    serve([others[0], _v2("0.10.0"), *others[1:]])
    _, out = _run(repo)
    assert "0.10.0 current" in out


@pytest.mark.parametrize("tag", ["v\u0661.\u0662.\u0663", "v1234567890.0.0", "v1.2.3.4", "v01.2.x", "V1.2.3"])
def test_a_tag_that_is_not_plain_ascii_x_y_z_is_not_a_release(repo: Path, serve: Serve, tag: str) -> None:
    serve([gu.Release(tag, {"a.txt": "a"})])
    code, out = _run(repo)
    assert code == 2
    assert "no tagged release" in out


# ---- the age window, and the tag's day it counts from
@pytest.mark.parametrize(("days", "code"), [(0, 0), (14, 0), (15, 1), (400, 1)])
def test_it_fails_only_when_the_lock_has_been_behind_longer_than_the_window(
    repo: Path, serve: Serve, days: int, code: int
) -> None:
    serve([_v2()])
    result, out = _run(repo, today=TAG_DATE + datetime.timedelta(days=days))
    assert result == code, out
    assert f"behind for {days} day(s)" in out


def test_the_window_is_the_repositorys_own(repo: Path, serve: Serve) -> None:
    toml = repo / "framework.toml"
    text = toml.read_text(encoding="utf-8").replace(
        'upstream = "acme/template"', 'upstream = "acme/template"\nmax_age_days = 3'
    )
    toml.write_text(text, encoding="utf-8")
    serve([_v2()])
    for days, code in ((3, 0), (4, 1)):
        assert _run(repo, today=TAG_DATE + datetime.timedelta(days=days))[0] == code


@pytest.mark.parametrize("annotated", [True, False])
def test_the_window_counts_from_the_tag_s_day_for_either_kind_of_tag(repo: Path, serve: Serve, annotated: bool) -> None:
    serve([_v2(day=datetime.date(2026, 10, 18), annotated=annotated)])
    code, out = _run(repo, today=datetime.date(2026, 10, 20))
    assert code == 0
    assert "(2026-10-18, from the tag)" in out
    assert "behind for 2 day(s)" in out


def test_a_release_day_in_the_future_of_today_is_zero_days_not_negative(repo: Path, serve: Serve) -> None:
    serve([_v2()])
    code, out = _run(repo, today=TAG_DATE - datetime.timedelta(days=1))
    assert code == 0
    assert "behind for 0 day(s)" in out


def test_a_release_that_changes_no_managed_file_is_calm_even_past_the_window(repo: Path, serve: Serve) -> None:
    serve([_release("0.2.0", V1_FILES)])
    code, out = _run(repo, today=TAG_DATE + datetime.timedelta(days=400))
    assert code == 0
    assert "no managed file differs" in out


# ---- what counts as removed, and what as changed
def test_a_file_the_repository_turned_off_locally_is_not_reported_as_removed(repo: Path, serve: Serve) -> None:
    toml = repo / "framework.toml"
    toml.write_text(
        toml.read_text(encoding="utf-8").replace('python-uv = "on"', 'python-uv = "planned"'), encoding="utf-8"
    )
    serve([_release("0.2.0", {**V2_FILES, "tools/two.py": "print('two, still shipped')\n"})])
    _, out = _run(repo)
    assert "removed:" not in out
    assert "added: tools/three.py" in out


def test_a_file_the_repository_overrides_is_marked_as_changed_and_overridden(repo: Path, serve: Serve) -> None:
    toml = repo / "framework.toml"
    toml.write_text(
        toml.read_text(encoding="utf-8") + '\n[[overrides]]\ntarget = "tools/one.py"\nreason = "pinned"\n',
        encoding="utf-8",
    )
    serve([_v2()])
    _, out = _run(repo)
    assert "changed: tools/one.py (you override this file)" in out


def test_a_removed_file_the_repository_overrides_is_marked_so_its_override_can_be_dropped(
    repo: Path, serve: Serve
) -> None:
    toml = repo / "framework.toml"
    toml.write_text(
        toml.read_text(encoding="utf-8") + '\n[[overrides]]\ntarget = "tools/two.py"\nreason = "pinned"\n',
        encoding="utf-8",
    )
    serve([_v2()])
    _, out = _run(repo)
    assert "removed: tools/two.py (you override this file)" in out


def test_a_file_the_release_s_own_init_refuses_is_a_note_not_a_removal(repo: Path, serve: Serve) -> None:
    serve([_release("0.2.0", {**V2_FILES, "AGENTS.md": "# {{name}} {{bogus}}\n"})])
    _, out = _run(repo)
    assert "removed: AGENTS.md" not in out
    assert "note: the release's init refuses: AGENTS.md: unknown token" in out
    assert "framework.lock is for template" not in out


# ---- when it cannot tell
def test_no_tagged_release_is_exit_2_and_says_so(repo: Path, serve: Serve) -> None:
    serve([gu.Release("notes", {"a.txt": "a"})])
    code, out = _run(repo)
    assert code == 2
    assert "no tagged release" in out


def test_git_not_installed_is_exit_2_and_says_so(repo: Path) -> None:
    code, out = _run(repo, which=lambda tool: None)
    assert code == 2
    assert "git is not on the path" in out


def test_every_git_call_uses_the_path_that_was_found_not_a_bare_name(
    repo: Path, serve: Serve, monkeypatch: pytest.MonkeyPatch
) -> None:
    serve([_v2()])
    calls = _spy_git(monkeypatch)
    asked: list[str] = []
    _run(repo, which=lambda tool: asked.append(tool) or GIT)
    assert asked == ["git"]
    assert calls
    assert {call[0] for call in calls} == {GIT}


def test_an_upstream_git_cannot_read_is_exit_2_with_git_s_own_words(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gu.isolate(monkeypatch)
    monkeypatch.setattr(fs, "release_url", lambda name: (tmp_path / "nowhere.git").as_uri())
    code, out = _run(repo)
    assert code == 2
    assert "git ls-remote failed (128)" in out


def test_a_fetch_that_fails_is_exit_2_with_git_s_own_words(
    repo: Path, serve: Serve, monkeypatch: pytest.MonkeyPatch
) -> None:
    serve([_v2()])
    _spy_git(monkeypatch, fail="fetch")
    code, out = _run(repo)
    assert code == 2
    assert "git fetch failed (1): fatal: fetch went wrong" in out


# ---- the hint when git has no working credential for the upstream's host
NO_USERNAME = "fatal: could not read Username for 'https://github.sie.example.com': terminal prompts disabled"
REFUSED = "fatal: Authentication failed for 'https://github.sie.example.com/acme/template.git/'"
GCM = "fatal: Cannot prompt because user interactivity has been disabled."
UNRESOLVED = (
    "fatal: unable to access 'https://github.sie.example.com/acme/template.git/':"
    " Could not resolve host: github.sie.example.com"
)


def _hint(host: str) -> str:
    return (
        f"; git has no working credential for {host}: sign in to it once with git (a credential manager stores it),"
        f" or run gh auth login --hostname {host} and gh auth setup-git --hostname {host}, then run this again"
    )


@pytest.mark.parametrize(
    ("err", "first"),
    [
        (NO_USERNAME, NO_USERNAME),
        (REFUSED, REFUSED),
        (chr(10).join([GCM, NO_USERNAME]), GCM),  # Git Credential Manager's line comes first, git's after it
    ],
    ids=["no-credential", "a-credential-refused", "git-credential-manager"],
)
def test_ls_remote_without_a_working_credential_keeps_git_s_line_and_adds_the_hint(
    repo: Path, monkeypatch: pytest.MonkeyPatch, err: str, first: str
) -> None:
    _set_upstream(repo, NAMED)
    _spy_git(monkeypatch, fail="ls-remote", code=128, err=err)
    code, out = _run(repo)
    assert code == 2, out
    assert f"git ls-remote failed (128): {first}{_hint('github.sie.example.com')}" in out


def test_the_hint_names_the_host_as_written(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _set_upstream(repo, "GitHub.SIE.Example.COM/acme/template")
    _spy_git(monkeypatch, fail="ls-remote", code=128, err=NO_USERNAME)
    code, out = _run(repo)
    assert code == 2, out
    assert out.endswith(_hint("GitHub.SIE.Example.COM"))


@pytest.mark.parametrize(
    ("host", "url"),
    [
        ("git.proxy.example.com", "https://git.proxy.example.com/acme/template.git"),
        ("example.org", "https://example.org/acme/proxy-template.git"),
    ],
    ids=["proxy-in-the-host", "proxy-in-the-name"],
)
def test_proxy_in_the_url_alone_keeps_the_hint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, host: str, url: str
) -> None:
    """Only a proxy's own refusal is passed over; the word in a host or a repository name is not one."""
    words = f"fatal: Authentication failed for '{url}/'"
    _canned(monkeypatch, 128, err=words)
    with pytest.raises(fs.UpstreamError) as caught:
        fs.release_tags(url, GIT, tmp_path, host)
    assert str(caught.value) == f"git ls-remote failed (128): {words}{_hint(host)}"


def test_a_failure_that_is_not_a_credential_s_keeps_git_s_line_alone(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The regression guard: it passes before the hint and after it."""
    _set_upstream(repo, NAMED)
    _spy_git(monkeypatch, fail="ls-remote", code=128, err=UNRESOLVED)
    code, out = _run(repo)
    assert code == 2, out
    assert out.endswith(f"git ls-remote failed (128): {UNRESOLVED}")
    assert "credential" not in out


def test_a_fetch_failing_with_the_credential_words_has_no_hint(
    repo: Path, serve: Serve, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The hint is ``ls-remote``'s only: a fetch after a good ``ls-remote`` has the credential."""
    serve([_v2()])
    _spy_git(monkeypatch, fail="fetch", code=128, err=NO_USERNAME)
    code, out = _run(repo)
    assert code == 2, out
    assert out.endswith(f"git fetch failed (128): {NO_USERNAME}")


def test_no_upstream_in_framework_toml_is_exit_2(repo: Path) -> None:
    toml = repo / "framework.toml"
    toml.write_text(toml.read_text(encoding="utf-8").replace('upstream = "acme/template"\n', ""), encoding="utf-8")
    code, out = _run(repo)
    assert code == 2
    assert "no upstream is configured" in out
    assert 'set [framework] upstream = "owner/name" (or "host/owner/name") in framework.toml' in out


def test_no_project_file_no_lock_or_a_bad_project_file_is_exit_2_before_any_network_call(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _spy_git(monkeypatch)
    (repo / "project.json").write_text("{not json", encoding="utf-8")
    assert _run(repo)[0] == 2
    (repo / "project.json").unlink()
    code, out = _run(repo)
    assert code == 2
    assert "project.json" in out
    (repo / "framework.lock").unlink()
    code, out = _run(repo)
    assert code == 2
    assert "framework.lock" in out
    assert calls == []


def test_a_lock_whose_version_is_not_x_y_z_is_exit_2_not_a_crash(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _spy_git(monkeypatch)
    lock = json.loads((repo / "framework.lock").read_text(encoding="utf-8"))
    lock["template_version"] = "0.1.0-rc1"
    (repo / "framework.lock").write_text(json.dumps(lock), encoding="utf-8")
    code, out = _run(repo)
    assert code == 2
    assert "not X.Y.Z" in out
    assert calls == []


def test_a_release_larger_than_the_limit_is_refused(repo: Path, serve: Serve, monkeypatch: pytest.MonkeyPatch) -> None:
    serve([_v2()])
    monkeypatch.setattr(fs, "MAX_PAYLOAD_BYTES", 10)
    code, out = _run(repo)
    assert code == 2
    assert "larger than the limit" in out


# ---- the payload's extraction: members that could write outside, and members that are not our business
def _extract(tmp_path: Path, extra: list[tarfile.TarInfo] | None = None, data: bytes | None = None) -> Path:
    tarball = tmp_path / "release.tar.gz"
    if data is None:
        data = _tarball(_payload(tmp_path / "v2", "0.2.0", V2_FILES), extra)
    tarball.write_bytes(data)
    return fs._extract_payload(tarball, tmp_path / "out" / "payload")


def test_a_tarball_without_a_payload_folder_is_refused(tmp_path: Path) -> None:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        info = tarfile.TarInfo("release/README.md")
        info.size = 1
        tar.addfile(info, io.BytesIO(b"x"))
    with pytest.raises(fs.UpstreamError, match="no payload"):
        _extract(tmp_path, data=buffer.getvalue())


def test_a_download_that_is_not_a_tarball_is_refused(tmp_path: Path) -> None:
    with pytest.raises(fs.UpstreamError, match="not a readable tarball"):
        _extract(tmp_path, data=b"this is not gzip")


@pytest.mark.parametrize(
    "name",
    [
        "payload/../../evil.txt",
        "payload/D:evil/x.txt",
        "payload/tools/a:stream.py",
        "payload/tools/NUL",
        "payload/tools/con.py",
        "payload/tools/trailing.",
        "payload/tools/space ",
        "payload/tools/back\\slash.py",
    ],
)
def test_a_payload_member_that_could_land_somewhere_else_is_refused_and_nothing_is_written_outside(
    tmp_path: Path, name: str
) -> None:
    info = tarfile.TarInfo(f"release/{name}")
    info.size = 1
    with pytest.raises(fs.UpstreamError, match="unsafe"):
        _extract(tmp_path, [info])
    assert not (tmp_path / "evil.txt").exists()


def test_a_symlink_inside_the_payload_is_refused(tmp_path: Path) -> None:
    link = tarfile.TarInfo("release/payload/tools/link.py")
    link.type = tarfile.SYMTYPE
    link.linkname = "/etc/passwd"
    with pytest.raises(fs.UpstreamError, match="unsafe"):
        _extract(tmp_path, [link])


def test_a_payload_member_with_an_absolute_name_is_refused(tmp_path: Path) -> None:
    info = tarfile.TarInfo("/payload/tools/abs.py")
    info.size = 1
    with pytest.raises(fs.UpstreamError, match="unsafe"):
        _extract(tmp_path, [info])


@pytest.mark.parametrize("kind", ["symlink", "traversal", "absolute"])
def test_a_member_outside_the_payload_is_ignored_not_a_reason_to_give_up(tmp_path: Path, kind: str) -> None:
    """A symlink in the release's docs, or any name that is never extracted, must not stop the extraction."""
    if kind == "symlink":
        info = tarfile.TarInfo("release/docs/link")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
    else:
        info = tarfile.TarInfo("../evil.txt" if kind == "traversal" else "/abs/evil.txt")
        info.size = 1
    payload = _extract(tmp_path, [info])
    assert (payload / "tools" / "one.py").is_file()
    assert not (tmp_path / "evil.txt").exists()


# ---- a release that misbehaves: its code runs in a child process and can only make the answer "cannot tell"
def _misbehaving(repo: Path, serve: Serve, extra: str) -> tuple[int, str]:
    serve([gu.Release("v0.2.0", _edit_init(_files("0.2.0", V2_FILES), extra), day=TAG_DATE)])
    return _run(repo)


def test_a_release_whose_init_exits_at_import_cannot_end_this_process_or_pass_as_current(
    repo: Path, serve: Serve
) -> None:
    code, out = _misbehaving(repo, serve, "import sys\nsys.exit(0)")
    assert code == 2
    assert "SystemExit" in out
    assert "lock is current" not in out


def test_a_release_whose_init_raises_at_import_is_exit_2_with_its_reason(repo: Path, serve: Serve) -> None:
    code, out = _misbehaving(repo, serve, "raise RuntimeError('boom at import')")
    assert code == 2
    assert "RuntimeError: boom at import" in out


def test_a_release_whose_init_dies_without_a_result_is_exit_2(repo: Path, serve: Serve) -> None:
    code, out = _misbehaving(repo, serve, "import os\nos._exit(3)")
    assert code == 2
    assert "exited 3 without a result" in out


def test_what_a_release_prints_is_dropped_from_the_report(repo: Path, serve: Serve) -> None:
    code, out = _misbehaving(repo, serve, "print('lock is current: nothing to see')")
    assert code == 0
    assert "lock is current: nothing to see" not in out
    assert "lock is behind" in out


def test_a_release_that_never_finishes_is_stopped_at_the_timeout(
    repo: Path, serve: Serve, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(fs, "CHILD_TIMEOUT", 2)
    code, out = _misbehaving(repo, serve, "import time\ntime.sleep(60)")
    assert code == 2
    assert "did not finish in 2 s" in out


def test_a_release_cannot_see_a_token_in_this_environment(
    repo: Path, serve: Serve, monkeypatch: pytest.MonkeyPatch
) -> None:
    names = ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN")
    for name in names:
        monkeypatch.setenv(name, "secret")
    leak = f"import os\nassert not any(k in os.environ for k in {names!r}), 'leaked'"
    code, out = _misbehaving(repo, serve, leak)
    assert code == 0, out
    assert "lock is behind" in out


def test_the_child_environment_has_only_what_a_plan_needs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GH_TOKEN", "secret")
    monkeypatch.setenv("HOME", "/home/me")
    monkeypatch.setenv("USERPROFILE", "C:/Users/me")
    env = fs._child_env()
    assert set(env) <= set(fs.CHILD_ENV_KEYS) | {"PYTHONUTF8"}
    assert env["PYTHONUTF8"] == "1"


def test_a_release_whose_init_cannot_read_this_repository_is_exit_2_with_its_reason(repo: Path, serve: Serve) -> None:
    files = _files("0.2.0", V2_FILES)
    files["tools/framework_config.py"] += "\n\ndef load_project(path):\n    raise ValueError('the schema changed')\n"
    serve([gu.Release("v0.2.0", files, day=TAG_DATE)])
    code, out = _run(repo)
    assert code == 2
    assert "v0.2.0's init cannot read this repository" in out
    assert "the schema changed" in out


def test_a_release_with_unreadable_tools_is_exit_2(repo: Path, serve: Serve) -> None:
    files = {**_files("0.2.0", V2_FILES), "tools/init.py": "this is not python (\n"}
    serve([gu.Release("v0.2.0", files, day=TAG_DATE)])
    code, out = _run(repo)
    assert code == 2
    assert "SyntaxError" in out


def test_the_release_s_code_runs_in_an_isolated_interpreter(
    repo: Path, serve: Serve, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[list[str]] = []
    real = subprocess.Popen

    def spy(argv, *args, **kwargs):
        seen.append(list(argv))
        return real(argv, *args, **kwargs)

    serve([_v2()])
    monkeypatch.setattr(fs.subprocess, "Popen", spy)
    _run(repo)
    child = next(argv for argv in seen if "-c" in argv)
    assert child[1:3] == ["-I", "-c"]


def test_output_a_release_prints_after_its_result_is_dropped_too(repo: Path, serve: Serve) -> None:
    code, out = _misbehaving(repo, serve, "import atexit\natexit.register(lambda: print('printed at exit'))")
    assert code == 0, out
    assert "printed at exit" not in out
    assert "lock is behind" in out


def test_a_planner_that_exits_nonzero_after_printing_a_result_is_not_trusted(repo: Path, serve: Serve) -> None:
    code, out = _misbehaving(repo, serve, "import atexit, os\natexit.register(lambda: os._exit(7))")
    assert code == 2
    assert "exited 7 after printing a result" in out


def test_an_unchanged_parametrised_file_with_a_dated_name_is_not_removed_or_changed(repo: Path, serve: Serve) -> None:
    """The lock holds the rendered name (notes/<day>.md); the release ships the template name (notes/{{today}}.md)."""
    assert list((repo / "notes").glob("*.md")), "the made repository has the dated file"
    serve([_release("0.2.0", V1_FILES)])
    code, out = _run(repo, today=TAG_DATE + datetime.timedelta(days=400))
    assert code == 0, out
    assert "no managed file differs" in out
    assert "removed:" not in out


# ---- it reads and writes nothing of the repository's
def _snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def test_the_repository_is_not_touched_and_this_process_is_left_as_it_was(repo: Path, serve: Serve) -> None:
    serve([_v2()])
    before = _snapshot(repo)
    config_module, init_module = sys.modules["framework_config"], sys.modules["init"]
    modules, path = set(sys.modules), list(sys.path)
    # Only the release's own tools can say it was loaded here: any other module may be imported for the first time by
    # the run itself (gzip, for the tarball) in a fresh worker, so comparing all of sys.modules races (project ledger
    # P-29). The release served is 0.2.0, whose tools the made repository (0.1.0) lacks in part (three).
    release = {
        Path(name).stem for name in _files("0.2.0", V2_FILES) if name.startswith("tools/") and name.endswith(".py")
    }
    _run(repo)
    assert _snapshot(repo) == before
    # framework_config and init were imported before the run, so they can never be new: their identity is the check.
    assert sys.modules["framework_config"] is config_module
    assert sys.modules["init"] is init_module
    new = set(sys.modules) - modules
    assert not new & release  # the release's modules were never loaded here
    # Nor under another name: a module new to this process comes from the interpreter's own library or the
    # environment's packages, never from a checkout of the release.
    homes = [Path(p).resolve() for p in {sys.prefix, sys.base_prefix}]
    files = {name: getattr(sys.modules.get(name), "__file__", None) for name in new}
    elsewhere = sorted(n for n, f in files.items() if f and not any(Path(f).resolve().is_relative_to(h) for h in homes))
    assert not elsewhere, elsewhere
    assert sys.path == path


def test_the_scratch_folder_is_removed(repo: Path, serve: Serve, monkeypatch: pytest.MonkeyPatch) -> None:
    import tempfile

    made: list[Path] = []
    real = tempfile.mkdtemp

    def record(*args, **kwargs):
        path = Path(real(*args, **kwargs))
        made.append(path)
        return str(path)

    serve([_v2()])
    monkeypatch.setattr(fs.tempfile, "mkdtemp", record)
    _run(repo)
    assert made
    assert not any(path.exists() for path in made)


# ---- git itself: run_git
def _py(code: str) -> list[str]:
    """A stand-in for git: this interpreter running ``code``."""
    return [sys.executable, "-c", code]


def test_run_git_returns_the_output_of_a_command_that_succeeds(tmp_path: Path) -> None:
    result = fs.run_git(_py("print('hello')"), tmp_path)
    assert (result.returncode, result.stdout.strip()) == (0, "hello")


def test_run_git_returns_a_failure_with_its_own_words_and_does_not_raise(tmp_path: Path) -> None:
    result = fs.run_git(_py("import sys; sys.stderr.write('fatal: nope'); sys.exit(128)"), tmp_path)
    assert (result.returncode, result.stderr.strip()) == (128, "fatal: nope")


def test_run_git_runs_in_the_folder_it_is_given(tmp_path: Path) -> None:
    result = fs.run_git(_py("import os; print(os.getcwd())"), tmp_path)
    assert Path(result.stdout.strip()).resolve() == tmp_path.resolve()


def test_run_git_gives_git_no_stdin_so_a_prompt_reads_nothing(tmp_path: Path) -> None:
    result = fs.run_git(_py("import sys; print(repr(sys.stdin.read()))"), tmp_path)
    assert result.stdout.strip() == "''"


def test_run_git_turns_off_both_credential_prompts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_TERMINAL_PROMPT", "1")
    monkeypatch.setenv("GCM_INTERACTIVE", "always")
    code = "import os; print(os.environ['GIT_TERMINAL_PROMPT'], os.environ['GCM_INTERACTIVE'])"
    assert fs.run_git(_py(code), tmp_path).stdout.split() == ["0", "never"]


def test_run_git_reads_output_that_is_not_utf8_without_failing(tmp_path: Path) -> None:
    result = fs.run_git(_py("import sys; sys.stdout.buffer.write(b'caf\\xff\\n')"), tmp_path)
    assert (result.returncode, result.stdout.strip()) == (0, "caf�")


def test_run_git_says_127_for_a_program_that_cannot_start(tmp_path: Path) -> None:
    result = fs.run_git(["definitely-not-a-program-xyz", "--version"], tmp_path)
    assert result.returncode == 127
    assert "definitely-not-a-program-xyz" in result.stderr


#: A stand-in for git that starts its own child (as git starts git-remote-https), which beats a heartbeat into a file,
#: and then waits on it forever.
_GRANDPARENT = """
import subprocess, sys, time
beat = sys.argv[1]
child = "import sys, time\\nwhile True:\\n    open(sys.argv[1], 'w').write(str(time.time()))\\n    time.sleep(0.1)\\n"
subprocess.Popen([sys.executable, "-c", child, beat])
time.sleep(600)
"""


def test_run_git_ends_the_whole_tree_on_a_timeout_and_says_124(tmp_path: Path) -> None:
    beat = tmp_path / "beat"
    result = fs.run_git([*_py(_GRANDPARENT), str(beat)], tmp_path, timeout=3)
    assert result.returncode == 124
    assert "did not finish in 3 s" in result.stderr
    assert beat.exists(), "the grandchild never started, so the test proves nothing"
    time.sleep(0.5)  # a beat already in flight may land once
    stamp = beat.read_text(encoding="utf-8")
    time.sleep(1.0)  # ten beats, were it alive
    assert beat.read_text(encoding="utf-8") == stamp, "git's own child outlived the timeout"


# ---- the git read: release_url, release_tags, fetch_tags, tag_day
SHA = "0123456789abcdef0123456789abcdef01234567"


@pytest.fixture
def no_user_git(monkeypatch: pytest.MonkeyPatch) -> None:
    """The code under test sees no user or system git configuration, as the fixture's own git calls do."""
    gu.isolate(monkeypatch)


def _canned(monkeypatch: pytest.MonkeyPatch, code: int, out: str = "", err: str = "") -> list[list[str]]:
    """Make ``run_git`` answer ``(code, out, err)`` to every call; return the calls."""
    calls: list[list[str]] = []

    def answer(argv: list[str], cwd: Path, timeout: int = fs.GIT_TIMEOUT) -> subprocess.CompletedProcess:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, code, out, err)

    monkeypatch.setattr(fs, "run_git", answer)
    return calls


def test_the_release_url_is_github_s_for_owner_and_repo() -> None:
    assert fs.release_url("acme/template") == "https://github.com/acme/template.git"


def test_the_release_url_is_on_the_host_the_upstream_names_whatever_gh_host_says(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GH_HOST", "elsewhere.example.com")
    assert fs.release_url("acme/template") == "https://github.com/acme/template.git"
    assert fs.release_url(NAMED) == "https://github.sie.example.com/acme/template.git"


@pytest.mark.parametrize(
    ("value", "shown"),
    [
        ("acme/template", "github.com/acme/template"),
        (NAMED, "github.sie.example.com/acme/template"),
        ("GitHub.SIE.Example.COM/acme/template", "GitHub.SIE.Example.COM/acme/template"),
    ],
)
def test_qualified_names_the_host_as_written(value: str, shown: str) -> None:
    assert fs.qualified(value) == shown


@pytest.mark.parametrize("name", ["release_url", "qualified"])
def test_a_value_that_skipped_validation_cannot_tell_rather_than_crash(name: str) -> None:
    with pytest.raises(fs.UpstreamError, match="a/b/c"):
        getattr(fs, name)("a/b/c")


@pytest.mark.parametrize(
    ("value", "expected", "shown"),
    [
        ("acme/template", "https://github.com/acme/template.git", "github.com/acme/template"),
        (NAMED, "https://github.sie.example.com/acme/template.git", "github.sie.example.com/acme/template"),
    ],
)
def test_a_run_behind_asks_git_for_the_host_the_upstream_names(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: str, expected: str, shown: str
) -> None:
    """``release_url`` is not patched: git's own ``insteadOf`` answers only the written-out URL from the upstream."""
    gu.isolate(monkeypatch)
    upstream = gu.make_upstream(tmp_path / "up", [_v2()])
    gu.route(monkeypatch, upstream, expected, tmp_path / "empty")
    monkeypatch.setenv("GH_HOST", "elsewhere.example.com")
    _set_upstream(repo, value)
    calls = _spy_git(monkeypatch)
    code, out = _run(repo)
    assert code == 0, out
    assert out.splitlines()[0] == f"upstream {shown}: newest release v0.2.0 (2026-10-20, from the tag)"
    assert out.splitlines()[1:5] == [
        "lock is behind: 0.1.0 locked, 0.2.0 current, 3 managed file(s) changed",
        "  changed: tools/one.py",
        "  added: tools/three.py",
        "  removed: tools/two.py",
    ]
    network = [call for call in calls if call[1] in ("ls-remote", "fetch")]
    assert [call[1] for call in network] == ["ls-remote", "fetch"]
    assert all(expected in call for call in network), network


def test_the_newest_tag_is_the_highest_version_not_the_last_made(tmp_path: Path, no_user_git: None) -> None:
    releases = [gu.Release(t, {"a.txt": t}) for t in ("v0.10.0", "v0.9.0", "v0.2.0", "notes", "v1.0.0-rc1")]
    upstream = gu.make_upstream(tmp_path, releases)
    tags = fs.release_tags(upstream.url, GIT, tmp_path, "example.org")
    assert tags == {"v0.10.0": (0, 10, 0), "v0.9.0": (0, 9, 0), "v0.2.0": (0, 2, 0)}
    assert max(tags, key=tags.__getitem__) == "v0.10.0"


def test_an_upstream_with_no_release_tag_cannot_tell(tmp_path: Path, no_user_git: None) -> None:
    upstream = gu.make_upstream(tmp_path, [gu.Release("notes", {"a.txt": "a"})])
    with pytest.raises(fs.UpstreamError, match="has no tagged release"):
        fs.release_tags(upstream.url, GIT, tmp_path, "example.org")


def test_an_upstream_git_cannot_read_cannot_tell_in_git_s_own_words(tmp_path: Path, no_user_git: None) -> None:
    missing = (tmp_path / "nowhere.git").as_uri()
    with pytest.raises(fs.UpstreamError, match=r"git ls-remote failed \(128\): .*nowhere"):
        fs.release_tags(missing, GIT, tmp_path, "example.org")


@pytest.mark.parametrize(
    ("out", "err", "first"),
    [("", "", "no message"), ("fatal: on stdout only", "", "fatal: on stdout only")],
    ids=["nothing-said", "stdout-only"],
)
def test_ls_remote_failing_without_stderr_says_no_message_or_gives_stdout_s_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, out: str, err: str, first: str
) -> None:
    _canned(monkeypatch, 128, out=out, err=err)
    with pytest.raises(fs.UpstreamError) as caught:
        fs.release_tags("https://example.org/x.git", GIT, tmp_path, "example.org")
    assert str(caught.value) == f"git ls-remote failed (128): {first}"


def test_a_proxy_refusing_its_credential_is_not_the_upstream_host_s_and_has_no_hint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    words = "fatal: unable to access 'https://example.org/x.git/': Proxy Authentication failed"
    _canned(monkeypatch, 128, err=words)
    with pytest.raises(fs.UpstreamError) as caught:
        fs.release_tags("https://example.org/x.git", GIT, tmp_path, "example.org")
    assert str(caught.value) == f"git ls-remote failed (128): {words}"


@pytest.mark.parametrize(("code", "words"), [(124, "did not finish"), (127, "cannot start")])
def test_git_that_times_out_or_cannot_start_cannot_tell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, code: int, words: str
) -> None:
    _canned(monkeypatch, code, err=f"git {words}")
    with pytest.raises(fs.UpstreamError, match=rf"\({code}\): git {words}"):
        fs.release_tags("https://example.org/x.git", GIT, tmp_path, "example.org")


@pytest.mark.parametrize(
    "line",
    [
        f"{SHA} refs/tags/v1.0.0",  # a space, not a tab
        f"{SHA[:-1]}\trefs/tags/v1.0.0",  # 39 hex digits
        f"{SHA.upper()}x\trefs/tags/v1.0.0",
        f"{SHA}\trefs/heads/v1.0.0",
        f"{SHA}\trefs/tags/v1.0.0\textra",
    ],
)
def test_a_malformed_ls_remote_line_cannot_tell(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, line: str) -> None:
    _canned(monkeypatch, 0, out=f"{SHA}\trefs/tags/v0.1.0\n{line}\n")
    with pytest.raises(fs.UpstreamError, match="malformed"):
        fs.release_tags("https://example.org/x.git", GIT, tmp_path, "example.org")


def test_a_sha256_object_name_is_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _canned(monkeypatch, 0, out=f"{'a' * 64}\trefs/tags/v0.3.0\n")
    assert fs.release_tags("https://example.org/x.git", GIT, tmp_path, "example.org") == {"v0.3.0": (0, 3, 0)}


def test_ls_remote_is_asked_for_tags_only_with_the_url_after_the_options(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _canned(monkeypatch, 0, out=f"{SHA}\trefs/tags/v0.1.0\n")
    fs.release_tags("https://example.org/x.git", GIT, tmp_path, "example.org")
    assert calls == [[GIT, "ls-remote", "--tags", "--refs", "--", "https://example.org/x.git", "refs/tags/v*"]]


def _two_releases(tmp_path: Path) -> gu.Upstream:
    return gu.make_upstream(
        tmp_path,
        [
            gu.Release("v0.1.0", {"tools/a.py": "one\n"}, day=datetime.date(2026, 10, 1)),
            gu.Release(
                "v0.2.0",
                {"tools/a.py": "two\n", "hooks/post-merge": "#!/bin/sh\nexit 0\n"},
                executable=frozenset({"hooks/post-merge"}),
                annotated=False,
                day=datetime.date(2026, 10, 5),
            ),
        ],
    )


def test_fetch_unpacks_each_tag_s_payload_into_its_own_folder(tmp_path: Path, no_user_git: None) -> None:
    upstream = _two_releases(tmp_path / "up")
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    payloads = fs.fetch_tags(upstream.url, ["v0.1.0", "v0.2.0"], scratch, GIT)
    assert (payloads["v0.1.0"] / "tools" / "a.py").read_text(encoding="utf-8") == "one\n"
    assert (payloads["v0.2.0"] / "tools" / "a.py").read_text(encoding="utf-8") == "two\n"
    assert not (payloads["v0.1.0"] / "hooks").exists()
    assert all(path.is_relative_to(scratch) for path in payloads.values())


@pytest.mark.parametrize("tag", ["--upload-pack=touch x", "main", "v1.2", "v1.2.3;x"])
def test_fetch_refuses_a_name_that_is_not_a_release_tag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tag: str
) -> None:
    calls = _canned(monkeypatch, 0)
    with pytest.raises(fs.UpstreamError, match="not a release tag"):
        fs.fetch_tags("https://example.org/x.git", [tag], tmp_path, GIT)
    assert calls == []


def test_a_fetch_git_cannot_make_cannot_tell(tmp_path: Path, no_user_git: None) -> None:
    upstream = _two_releases(tmp_path / "up")
    with pytest.raises(fs.UpstreamError, match=r"git fetch failed \(\d+\)"):
        fs.fetch_tags(upstream.url, ["v9.9.9"], tmp_path / "scratch", GIT)


def test_the_tag_s_day_is_the_tagger_s_for_an_annotated_tag_and_the_commit_s_for_a_lightweight_one(
    tmp_path: Path, no_user_git: None
) -> None:
    upstream = _two_releases(tmp_path / "up")
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    fs.fetch_tags(upstream.url, ["v0.1.0", "v0.2.0"], scratch, GIT)
    assert fs.tag_day(scratch / "git", "v0.1.0", GIT) == datetime.date(2026, 10, 1)
    assert fs.tag_day(scratch / "git", "v0.2.0", GIT) == datetime.date(2026, 10, 5)


@pytest.mark.parametrize("answer", ["", "yesterday", "2026-13-40"])
def test_a_tag_day_that_is_not_a_date_cannot_tell(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, answer: str) -> None:
    _canned(monkeypatch, 0, out=answer + "\n")
    with pytest.raises(fs.UpstreamError, match="no usable date"):
        fs.tag_day(tmp_path, "v0.1.0", GIT)


@pytest.mark.skipif(sys.platform == "win32", reason="Windows keeps no executable bit in the file system")
def test_an_extracted_file_keeps_its_executable_bit(tmp_path: Path, no_user_git: None) -> None:
    upstream = _two_releases(tmp_path / "up")
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    payload = fs.fetch_tags(upstream.url, ["v0.2.0"], scratch, GIT)["v0.2.0"]
    assert (payload / "hooks" / "post-merge").stat().st_mode & 0o111
    assert not (payload / "tools" / "a.py").stat().st_mode & 0o111


# ---- the command line and the log
def test_the_command_line_runs_upstream_and_returns_its_code(
    repo: Path, serve: Serve, capsys: pytest.CaptureFixture[str]
) -> None:
    serve([_v2()])
    code = fs.main(
        ["--upstream", "--root", str(repo)], today=TAG_DATE + datetime.timedelta(days=20), which=lambda tool: GIT
    )
    assert code == 1
    assert "lock is behind" in capsys.readouterr().out


def test_the_command_line_hands_its_which_to_upstream_so_a_machine_without_git_is_seen(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # A real git on the path must not matter either way: the command line passes the one it is given (#200).
    code = fs.main(["--upstream", "--root", str(repo)], which=lambda tool: None)
    assert code == 2
    assert "git is not on the path" in capsys.readouterr().out


def test_check_and_upstream_are_exclusive(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as caught:
        fs.main(["--check", "--upstream"])
    assert caught.value.code == 2
    capsys.readouterr()


def test_the_run_leaves_a_log_of_the_upstream_tag_and_the_decision(
    repo: Path, serve: Serve, caplog: pytest.LogCaptureFixture
) -> None:
    serve([_release("0.1.5", V1_FILES), _v2()])
    with caplog.at_level("INFO", logger="tools.framework_sync"):
        _run(repo)
    messages = [r.getMessage() for r in caplog.records]
    assert any("2 release tag(s), the newest is v0.2.0" in m for m in messages)
    assert any("locked 0.1.0, newest 0.2.0" in m for m in messages)
    assert any("planning with v0.2.0's init for the paths it changes, in a child process" in m for m in messages)
    assert any(m.startswith("extracted ") and "from the release" in m for m in messages)


# ---- the hand procedure in Docs/standards/updating.md
EXTRA_RULE = """
[[rule]]
pattern = "extras/*.md"
module = "specimens"
kind = "managed"
"""


def _made_with_choices(tmp_path: Path) -> Path:
    """A repository made on 2026-10-01 with specimens off, overriding ``tools/one.py`` and ``tools/four.py``."""
    files = {**V1_FILES, "tools/four.py": "print('four')\n", "extras/e.md": "# extra\n"}
    source = _payload(tmp_path / "made-from", "0.1.0", {**files, "framework-manifest.toml": MANIFEST + EXTRA_RULE})
    target = tmp_path / "chosen"
    target.mkdir()
    seed = {
        "framework": {"template_version": "0.1.0", "upstream": UPSTREAM},
        "modules": {
            **{name: "planned" for name in fc.MODULES},
            **{"core": "on", "python-uv": "on", "lanes": "off", "specimens": "off"},
        },
        "harnesses": {"enabled": []},
        "checks": {"handoff_max_lines": 150},
        "overrides": [
            {"target": "tools/one.py", "reason": "the repository's own"},
            {"target": "tools/four.py", "reason": "the repository's own"},
        ],
    }
    (target / "framework.toml").write_text(fc.dump_framework(fc.parse_framework(seed)), encoding="utf-8")
    answers = tmp_path / "choices.json"
    answers.write_text(json.dumps(ANSWERS), encoding="utf-8")
    args = ["new", "--answers", str(answers), "--target", str(target), "--no-sync", "--no-checks"]
    assert ini.main(args, source=source, today="2026-10-01") == 0
    (target / "tools" / "one.py").write_text("print('one, locally edited')\n", encoding="utf-8")
    (target / "tools" / "four.py").write_text("print('four, locally edited')\n", encoding="utf-8")
    return target


def _take_the_release(repo: Path, tmp_path: Path, files: dict[str, str]) -> set[str]:
    """Steps 3 to 5 of the guide, by hand: render the release for this repository, copy what changed or was added,
    remove what the release dropped, set the version and the lock. Returns the paths the release removed."""
    release = _payload(tmp_path / "release", "0.2.0", files)

    scratch = tmp_path / "rendered"  # step 3: the repository's own choices, seeded, the version set to the release's
    scratch.mkdir()
    for name in ("project.json", "framework.toml", "framework.lock"):
        (scratch / name).write_bytes((repo / name).read_bytes())
    for name in ("framework.toml", "framework.lock"):
        text = (scratch / name).read_text(encoding="utf-8")
        assert '"0.1.0"' in text
        (scratch / name).write_text(text.replace('"0.1.0"', '"0.2.0"'), encoding="utf-8")
    args = ["new", "--answers", str(scratch / "project.json"), "--target", str(scratch), "--no-sync", "--no-checks"]
    assert ini.main(args, source=release, today="2026-10-22") == 0

    old = json.loads((repo / "framework.lock").read_text(encoding="utf-8"))["files"]
    lock = json.loads((scratch / "framework.lock").read_text(encoding="utf-8"))
    config = fc.load_framework(repo / "framework.toml")
    overridden = {o.target for o in config.overrides}
    for rel in sorted(lock["files"]):  # step 4: changed and added are copied, unless the repository overrides the path
        if old.get(rel) != lock["files"][rel] and rel not in overridden:
            (repo / rel).parent.mkdir(parents=True, exist_ok=True)
            (repo / rel).write_bytes((scratch / rel).read_bytes())
    gone = set(old) - set(lock["files"])
    for rel in sorted(gone - overridden):
        (repo / rel).unlink()
    kept = tuple(o for o in config.overrides if o.target not in gone)  # four.py stays as its own; its override goes
    updated = dataclasses.replace(config, overrides=kept, template_version="0.2.0")  # step 5: the version
    (repo / "framework.toml").write_text(fc.dump_framework(updated), encoding="utf-8")
    (repo / "framework.lock").write_bytes((scratch / "framework.lock").read_bytes())
    return gone


def test_the_update_procedure_in_the_guide_ends_with_a_clean_check_and_a_current_lock(
    tmp_path: Path, serve: Serve
) -> None:
    repo = _made_with_choices(tmp_path)
    assert fs.main(["--check", "--root", str(repo)]) == 0
    files = {**V2_FILES, "extras/e.md": "# extra, changed\n", "framework-manifest.toml": MANIFEST + EXTRA_RULE}
    gone = _take_the_release(repo, tmp_path, files)
    assert gone == {"tools/two.py", "tools/four.py"}  # removed by the release; the repository overrides four.py

    assert fs.main(["--check", "--root", str(repo)]) == 0  # step 6
    serve([_v2()])
    code, out = _run(repo)
    assert code == 0
    assert "lock is current: 0.2.0 locked, 0.2.0 is the latest release" in out
    assert not (repo / "extras").exists()  # specimens stayed off, though the release changed a file in it
    assert not (repo / "tools" / "two.py").exists()  # a removed file went
    assert (repo / "notes" / "2026-10-01.md").is_file() and not (repo / "notes" / "2026-10-22.md").exists()
    assert "locally edited" in (repo / "tools" / "one.py").read_text(encoding="utf-8")  # an override is not overwritten
    assert (repo / "tools" / "four.py").is_file()  # a removed, overridden file stays unless the owner deletes it
    assert (repo / "tools" / "three.py").is_file()  # an added file arrived


def _render(repo: Path, release: Path, scratch: Path, *, edit_toml: bool) -> dict[str, bytes]:
    """Step 3 by hand, into ``scratch``: the three files copied, the lock's version set to the release's (and the
    ``framework.toml`` copy's too, when ``edit_toml``), then ``init new``. Returns every file the render wrote."""
    scratch.mkdir()
    for name in ("project.json", "framework.toml", "framework.lock"):
        (scratch / name).write_bytes((repo / name).read_bytes())
    for name in ("framework.lock", "framework.toml") if edit_toml else ("framework.lock",):
        text = (scratch / name).read_text(encoding="utf-8")
        (scratch / name).write_text(text.replace('"0.1.0"', '"0.2.0"'), encoding="utf-8")
    args = ["new", "--answers", str(scratch / "project.json"), "--target", str(scratch), "--no-sync", "--no-checks"]
    assert ini.main(args, source=release, today="2026-10-22") == 0
    return {
        p.relative_to(scratch).as_posix(): p.read_bytes()
        for p in sorted(scratch.rglob("*"))
        if p.is_file() and p.parts[len(scratch.parts)] != "logs" and p.name != "framework.toml"
    }


def test_step_3_renders_the_same_without_editing_the_framework_toml_copy(tmp_path: Path) -> None:
    """#224: init takes the version from the payload, so only the lock's copy needs the release's version."""
    repo = _made_with_choices(tmp_path)
    release = _payload(tmp_path / "release", "0.2.0", {**V2_FILES, "framework-manifest.toml": MANIFEST + EXTRA_RULE})
    edited = _render(repo, release, tmp_path / "edited", edit_toml=True)
    left = _render(repo, release, tmp_path / "left", edit_toml=False)
    assert edited == left
    assert json.loads(left["framework.lock"])["template_version"] == "0.2.0"


def test_step_3_with_the_lock_left_at_the_old_version_is_refused_with_its_cause_named(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """#224: the guide said nothing names the cause; init's refusal does."""
    repo = _made_with_choices(tmp_path)
    release = _payload(tmp_path / "release", "0.2.0", {**V2_FILES, "framework-manifest.toml": MANIFEST + EXTRA_RULE})
    scratch = tmp_path / "rendered"
    scratch.mkdir()
    for name in ("project.json", "framework.toml", "framework.lock"):
        (scratch / name).write_bytes((repo / name).read_bytes())
    args = ["new", "--answers", str(scratch / "project.json"), "--target", str(scratch), "--no-sync", "--no-checks"]
    assert ini.main(args, source=release, today="2026-10-22") != 0
    captured = capsys.readouterr()
    said = " ".join((captured.out + captured.err).split())  # the refusal is on standard error, and may wrap
    assert "framework.lock is for template 0.1.0 but this payload is 0.2.0" in said


def test_a_repository_keeping_its_old_seeds_takes_a_release_that_adds_a_file_and_changes_them(tmp_path: Path) -> None:
    """The journal release, in miniature: a managed file is added and the project-owned seed (the README) changes in
    the release. The guide copies only what the lock records, so the repository keeps its own README and its check is
    clean; the new managed file is the only way the release reaches it."""
    repo = _made_with_choices(tmp_path)
    (repo / "README.md").write_text("# The repository's own readme, written before the release\n", encoding="utf-8")
    own = (repo / "README.md").read_bytes()
    files = {
        **V2_FILES,
        "extras/e.md": "# extra, changed\n",
        "framework-manifest.toml": MANIFEST + EXTRA_RULE,
        "README.md": "# The release's new seed readme, which links to tools/standard.py\n",
        "tools/standard.py": "print('new managed file')\n",
    }
    _take_the_release(repo, tmp_path, files)
    assert (repo / "README.md").read_bytes() == own  # a project-owned seed is never overwritten
    assert (repo / "tools" / "standard.py").is_file()  # the added managed file arrived
    assert fs.main(["--check", "--root", str(repo)]) == 0
