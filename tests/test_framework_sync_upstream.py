"""
Framework: tests for tools/framework_sync.py --upstream (has the template moved on since this repository was locked).
Package: tests/test_framework_sync_upstream

``gh`` is replaced by a fake that answers from a table, so no test touches the network. The "upstream" is a small
synthetic payload built here, with the real ``init.py`` and ``framework_config.py`` copied into it, packed as the
tarball GitHub would send. A repository is made from the first version with ``init new`` and checked against the second.
The release's code runs in a real child process, as it does for real; a "malicious" release is one whose ``init.py`` has
been edited here to misbehave.
"""

from __future__ import annotations

import dataclasses
import datetime
import io
import json
import subprocess
import sys
import tarfile
from collections.abc import Callable
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import framework_config as fc  # noqa: E402
import framework_sync as fs  # noqa: E402
import init as ini  # noqa: E402

UPSTREAM = "acme/template"
TAG_DATE = datetime.date(2026, 10, 20)
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


def _payload(root: Path, version: str, files: dict[str, str]) -> Path:
    """A synthetic payload at ``version`` with the real initialiser inside it (the tag's own classifier)."""
    root.mkdir(parents=True, exist_ok=True)
    everything = {
        "framework-manifest.toml": MANIFEST,
        "framework.toml": _framework_text(version),
        "tools/init.py": (ROOT / "tools" / "init.py").read_text(encoding="utf-8"),
        "tools/framework_config.py": (ROOT / "tools" / "framework_config.py").read_text(encoding="utf-8"),
        **files,
    }
    for rel, text in everything.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
    return root


def _tarball(payload: Path, extra: list[tarfile.TarInfo] | None = None) -> bytes:
    """What GitHub sends for a tag: a gzipped tar whose top folder is ``owner-repo-<sha>``, the payload under it."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for path in sorted(payload.rglob("*")):
            if path.is_file():
                tar.add(path, arcname=f"acme-template-abc1234/payload/{path.relative_to(payload).as_posix()}")
        tar.add(payload / "framework.toml", arcname="acme-template-abc1234/README.md")  # a file outside payload/
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


class FakeGh:
    """Answers ``gh api`` calls from tables of tags (name to commit date), releases (name to published date) and a
    tarball; records every call."""

    def __init__(
        self,
        tags: dict[str, str],
        tarball: bytes | None = None,
        fail: str | None = None,
        releases: dict[str, str] | None = None,
        release_error: str | None = None,
    ) -> None:
        self.tags, self.tarball, self.fail, self.releases = tags, tarball, fail, releases or {}
        self.release_error = release_error
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str], output: Path | None = None) -> subprocess.CompletedProcess:
        self.calls.append(argv)
        if self.fail:
            return subprocess.CompletedProcess(argv, 1, "", self.fail)
        joined = " ".join(argv)
        tag = argv[2].rsplit("/", 1)[-1] if len(argv) > 2 else ""
        if "git/matching-refs/tags" in joined:
            return subprocess.CompletedProcess(argv, 0, "".join(f"refs/tags/{t}\n" for t in self.tags), "")
        if "/releases/tags/" in joined:
            if self.release_error:
                return subprocess.CompletedProcess(argv, 1, "", self.release_error)
            if tag in self.releases:
                return subprocess.CompletedProcess(argv, 0, self.releases[tag] + "\n", "")
            return subprocess.CompletedProcess(argv, 1, "", "HTTP 404: Not Found")
        if "/commits/" in joined:
            return subprocess.CompletedProcess(argv, 0, self.tags[tag] + "\n", "")
        if "/tarball/" in joined:
            assert output is not None and self.tarball is not None
            output.write_bytes(self.tarball)
            return subprocess.CompletedProcess(argv, 0, "", "")
        raise AssertionError(f"unexpected gh call: {argv}")


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


def _day_iso(days_before: int = 0) -> str:
    return (TAG_DATE - datetime.timedelta(days=days_before)).isoformat() + "T10:00:00Z"


def _upstream_v2(tmp_path: Path, version: str = "0.2.0") -> bytes:
    return _tarball(_payload(tmp_path / f"v2-{version}", version, V2_FILES))


def _run(repo: Path, gh: Callable, *, today: datetime.date = TAG_DATE, which=lambda tool: "/bin/gh") -> tuple[int, str]:
    code, lines = fs.upstream_report(repo, gh=gh, today=today, which=which)
    return code, "\n".join(lines)


def _edit_init(payload_dir: Path, extra: str) -> None:
    """Make a release's ``init.py`` misbehave: ``extra`` runs at import, before anything else."""
    path = payload_dir / "tools" / "init.py"
    text = path.read_text(encoding="utf-8")
    marker = "from __future__ import annotations\n"
    assert marker in text
    path.write_text(text.replace(marker, marker + extra + "\n", 1), encoding="utf-8")


# ---- behind, current
def test_a_lock_behind_the_latest_release_lists_what_changed_added_and_removed(repo: Path, tmp_path: Path) -> None:
    gh = FakeGh({"v0.2.0": _day_iso()}, _upstream_v2(tmp_path))
    code, out = _run(repo, gh)
    assert code == 0  # inside the window on the day of the release
    assert "lock is behind: 0.1.0 locked, 0.2.0 current, 3 managed file(s) changed" in out
    assert "changed: tools/one.py" in out
    assert "added: tools/three.py" in out
    assert "removed: tools/two.py" in out
    assert "latest release v0.2.0 (2026-10-20, from the commit)" in out


def test_a_lock_at_the_latest_release_is_current_and_downloads_nothing(repo: Path) -> None:
    gh = FakeGh({"v0.1.0": _day_iso(30)})
    code, out = _run(repo, gh)
    assert code == 0
    assert "lock is current: 0.1.0 locked, 0.1.0 is the latest release" in out
    assert not any("/tarball/" in " ".join(call) for call in gh.calls)


def test_a_lock_newer_than_the_latest_release_is_said_and_is_not_a_failure(repo: Path) -> None:
    code, out = _run(repo, FakeGh({"v0.0.9": _day_iso(30)}))
    assert code == 0
    assert "0.1.0 is newer than the latest release 0.0.9" in out


def test_the_highest_version_wins_not_the_last_or_the_alphabetical(repo: Path, tmp_path: Path) -> None:
    tags = {t: _day_iso() for t in ("v0.9.0", "v0.10.0", "v0.2.0", "v1", "release-1", "v1.2.3-rc1", "v0.1.0")}
    gh = FakeGh(tags, _upstream_v2(tmp_path, "0.10.0"))
    _, out = _run(repo, gh)
    assert "0.10.0 current" in out
    assert any("/tarball/v0.10.0" in " ".join(call) for call in gh.calls)


@pytest.mark.parametrize("tag", ["v\u0661.\u0662.\u0663", "v1234567890.0.0", "v1.2.3.4", "v01.2.x", "V1.2.3"])
def test_a_tag_that_is_not_plain_ascii_x_y_z_is_not_a_release(repo: Path, tag: str) -> None:
    code, out = _run(repo, FakeGh({tag: _day_iso()}))
    assert code == 2
    assert "no tagged release" in out


# ---- the age window, and where its day comes from
@pytest.mark.parametrize(("days", "code"), [(0, 0), (14, 0), (15, 1), (400, 1)])
def test_it_fails_only_when_the_lock_has_been_behind_longer_than_the_window(
    repo: Path, tmp_path: Path, days: int, code: int
) -> None:
    gh = FakeGh({"v0.2.0": _day_iso()}, _upstream_v2(tmp_path))
    result, out = _run(repo, gh, today=TAG_DATE + datetime.timedelta(days=days))
    assert result == code, out
    assert f"behind for {days} day(s)" in out


def test_the_window_is_the_repositorys_own(repo: Path, tmp_path: Path) -> None:
    toml = repo / "framework.toml"
    text = toml.read_text(encoding="utf-8").replace(
        'upstream = "acme/template"', 'upstream = "acme/template"\nmax_age_days = 3'
    )
    toml.write_text(text, encoding="utf-8")
    for days, code in ((3, 0), (4, 1)):
        gh = FakeGh({"v0.2.0": _day_iso()}, _upstream_v2(tmp_path))
        assert _run(repo, gh, today=TAG_DATE + datetime.timedelta(days=days))[0] == code


def test_a_published_release_gives_the_day_the_window_counts_from_and_says_so(repo: Path, tmp_path: Path) -> None:
    """The commit may be weeks older than the release (merged Monday, tagged Friday): the release's day counts."""
    gh = FakeGh({"v0.2.0": _day_iso(40)}, _upstream_v2(tmp_path), releases={"v0.2.0": _day_iso()})
    code, out = _run(repo, gh, today=TAG_DATE + datetime.timedelta(days=2))
    assert code == 0
    assert "(2026-10-20, from the release)" in out
    assert "behind for 2 day(s)" in out


def test_a_release_day_in_the_future_of_today_is_zero_days_not_negative(repo: Path, tmp_path: Path) -> None:
    gh = FakeGh({"v0.2.0": _day_iso()}, _upstream_v2(tmp_path))
    code, out = _run(repo, gh, today=TAG_DATE - datetime.timedelta(days=1))
    assert code == 0
    assert "behind for 0 day(s)" in out


def test_a_release_that_changes_no_managed_file_is_calm_even_past_the_window(repo: Path, tmp_path: Path) -> None:
    same = _tarball(_payload(tmp_path / "v2-same", "0.2.0", V1_FILES))
    code, out = _run(repo, FakeGh({"v0.2.0": _day_iso()}, same), today=TAG_DATE + datetime.timedelta(days=400))
    assert code == 0
    assert "no managed file differs" in out


# ---- what counts as removed, and what as changed
def test_a_file_the_repository_turned_off_locally_is_not_reported_as_removed(repo: Path, tmp_path: Path) -> None:
    toml = repo / "framework.toml"
    toml.write_text(
        toml.read_text(encoding="utf-8").replace('python-uv = "on"', 'python-uv = "planned"'), encoding="utf-8"
    )
    v2 = {**V2_FILES, "tools/two.py": "print('two, still shipped')\n"}
    tarball = _tarball(_payload(tmp_path / "v2", "0.2.0", v2))
    _, out = _run(repo, FakeGh({"v0.2.0": _day_iso()}, tarball))
    assert "removed:" not in out
    assert "added: tools/three.py" in out


def test_a_file_the_repository_overrides_is_marked_as_changed_and_overridden(repo: Path, tmp_path: Path) -> None:
    toml = repo / "framework.toml"
    toml.write_text(
        toml.read_text(encoding="utf-8") + '\n[[overrides]]\ntarget = "tools/one.py"\nreason = "pinned"\n',
        encoding="utf-8",
    )
    _, out = _run(repo, FakeGh({"v0.2.0": _day_iso()}, _upstream_v2(tmp_path)))
    assert "changed: tools/one.py (you override this file)" in out


def test_a_removed_file_the_repository_overrides_is_marked_so_its_override_can_be_dropped(
    repo: Path, tmp_path: Path
) -> None:
    toml = repo / "framework.toml"
    toml.write_text(
        toml.read_text(encoding="utf-8") + '\n[[overrides]]\ntarget = "tools/two.py"\nreason = "pinned"\n',
        encoding="utf-8",
    )
    _, out = _run(repo, FakeGh({"v0.2.0": _day_iso()}, _upstream_v2(tmp_path)))
    assert "removed: tools/two.py (you override this file)" in out


def test_a_file_the_release_s_own_init_refuses_is_a_note_not_a_removal(repo: Path, tmp_path: Path) -> None:
    v2 = {**V2_FILES, "AGENTS.md": "# {{name}} {{bogus}}\n"}
    tarball = _tarball(_payload(tmp_path / "v2", "0.2.0", v2))
    _, out = _run(repo, FakeGh({"v0.2.0": _day_iso()}, tarball))
    assert "removed: AGENTS.md" not in out
    assert "note: the release's init refuses: AGENTS.md: unknown token" in out
    assert "framework.lock is for template" not in out


# ---- when it cannot tell
def test_no_tagged_release_is_exit_2_and_says_so(repo: Path) -> None:
    code, out = _run(repo, FakeGh({}))
    assert code == 2
    assert "no tagged release" in out


def test_gh_not_installed_is_exit_2_and_says_so(repo: Path) -> None:
    code, out = _run(repo, FakeGh({}), which=lambda tool: None)
    assert code == 2
    assert "gh is not on the path" in out


def test_every_gh_call_uses_the_path_that_was_found_not_a_bare_name(repo: Path, tmp_path: Path) -> None:
    gh = FakeGh({"v0.2.0": _day_iso()}, _upstream_v2(tmp_path))
    _run(repo, gh, which=lambda tool: "/opt/found/gh")
    assert gh.calls
    assert {call[0] for call in gh.calls} == {"/opt/found/gh"}


def test_a_gh_failure_is_exit_2_with_gh_s_own_words(repo: Path) -> None:
    code, out = _run(repo, FakeGh({}, fail="HTTP 404: Not Found (repos/acme/template)"))
    assert code == 2
    assert "HTTP 404: Not Found" in out


def test_no_upstream_in_framework_toml_is_exit_2(repo: Path) -> None:
    toml = repo / "framework.toml"
    toml.write_text(toml.read_text(encoding="utf-8").replace('upstream = "acme/template"\n', ""), encoding="utf-8")
    code, out = _run(repo, FakeGh({}))
    assert code == 2
    assert "no upstream is configured" in out


def test_no_project_file_no_lock_or_a_bad_project_file_is_exit_2_before_any_network_call(repo: Path) -> None:
    gh = FakeGh({"v0.2.0": _day_iso()})
    (repo / "project.json").write_text("{not json", encoding="utf-8")
    assert _run(repo, gh)[0] == 2
    (repo / "project.json").unlink()
    code, out = _run(repo, gh)
    assert code == 2
    assert "project.json" in out
    (repo / "framework.lock").unlink()
    code, out = _run(repo, gh)
    assert code == 2
    assert "framework.lock" in out
    assert gh.calls == []


def test_a_lock_whose_version_is_not_x_y_z_is_exit_2_not_a_crash(repo: Path) -> None:
    lock = json.loads((repo / "framework.lock").read_text(encoding="utf-8"))
    lock["template_version"] = "0.1.0-rc1"
    (repo / "framework.lock").write_text(json.dumps(lock), encoding="utf-8")
    code, out = _run(repo, FakeGh({"v0.2.0": _day_iso()}))
    assert code == 2
    assert "not X.Y.Z" in out


def test_a_tarball_without_a_payload_folder_is_exit_2(repo: Path) -> None:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        info = tarfile.TarInfo("acme-template-abc1234/README.md")
        info.size = 1
        tar.addfile(info, io.BytesIO(b"x"))
    code, out = _run(repo, FakeGh({"v0.2.0": _day_iso()}, buffer.getvalue()))
    assert code == 2
    assert "no payload" in out


def test_a_download_that_is_not_a_tarball_is_exit_2(repo: Path) -> None:
    code, out = _run(repo, FakeGh({"v0.2.0": _day_iso()}, b"this is not gzip"))
    assert code == 2
    assert "not a readable tarball" in out


# ---- the download: members that could write outside, and members that are not our business
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
    repo: Path, tmp_path: Path, name: str
) -> None:
    info = tarfile.TarInfo(f"acme-template-abc1234/{name}")
    info.size = 1
    payload = _payload(tmp_path / "v2", "0.2.0", V2_FILES)
    code, out = _run(repo, FakeGh({"v0.2.0": _day_iso()}, _tarball(payload, [info])))
    assert code == 2, out
    assert "unsafe" in out
    assert not (tmp_path / "evil.txt").exists()


def test_a_symlink_inside_the_payload_is_refused(repo: Path, tmp_path: Path) -> None:
    link = tarfile.TarInfo("acme-template-abc1234/payload/tools/link.py")
    link.type = tarfile.SYMTYPE
    link.linkname = "/etc/passwd"
    payload = _payload(tmp_path / "v2", "0.2.0", V2_FILES)
    code, out = _run(repo, FakeGh({"v0.2.0": _day_iso()}, _tarball(payload, [link])))
    assert code == 2
    assert "unsafe" in out


@pytest.mark.parametrize("kind", ["symlink", "traversal", "absolute"])
def test_a_member_outside_the_payload_is_ignored_not_a_reason_to_give_up(repo: Path, tmp_path: Path, kind: str) -> None:
    """A symlink in the release's docs, or any name that is never extracted, must not turn --upstream into exit 2."""
    if kind == "symlink":
        info = tarfile.TarInfo("acme-template-abc1234/docs/link")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
    else:
        info = tarfile.TarInfo("../evil.txt" if kind == "traversal" else "/abs/evil.txt")
        info.size = 1
    payload = _payload(tmp_path / "v2", "0.2.0", V2_FILES)
    code, out = _run(repo, FakeGh({"v0.2.0": _day_iso()}, _tarball(payload, [info])))
    assert code == 0, out
    assert "lock is behind" in out
    assert not (tmp_path / "evil.txt").exists()


def test_a_release_larger_than_the_limit_is_refused(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(fs, "MAX_PAYLOAD_BYTES", 10)
    code, out = _run(repo, FakeGh({"v0.2.0": _day_iso()}, _upstream_v2(tmp_path)))
    assert code == 2
    assert "larger than the limit" in out


# ---- a release that misbehaves: its code runs in a child process and can only make the answer "cannot tell"
def _misbehaving(repo: Path, tmp_path: Path, extra: str) -> tuple[int, str]:
    payload = _payload(tmp_path / "v2", "0.2.0", V2_FILES)
    _edit_init(payload, extra)
    return _run(repo, FakeGh({"v0.2.0": _day_iso()}, _tarball(payload)))


def test_a_release_whose_init_exits_at_import_cannot_end_this_process_or_pass_as_current(
    repo: Path, tmp_path: Path
) -> None:
    code, out = _misbehaving(repo, tmp_path, "import sys\nsys.exit(0)")
    assert code == 2
    assert "SystemExit" in out
    assert "lock is current" not in out


def test_a_release_whose_init_raises_at_import_is_exit_2_with_its_reason(repo: Path, tmp_path: Path) -> None:
    code, out = _misbehaving(repo, tmp_path, "raise RuntimeError('boom at import')")
    assert code == 2
    assert "RuntimeError: boom at import" in out


def test_a_release_whose_init_dies_without_a_result_is_exit_2(repo: Path, tmp_path: Path) -> None:
    code, out = _misbehaving(repo, tmp_path, "import os\nos._exit(3)")
    assert code == 2
    assert "exited 3 without a result" in out


def test_what_a_release_prints_is_dropped_from_the_report(repo: Path, tmp_path: Path) -> None:
    code, out = _misbehaving(repo, tmp_path, "print('lock is current: nothing to see')")
    assert code == 0
    assert "lock is current: nothing to see" not in out
    assert "lock is behind" in out


def test_a_release_that_never_finishes_is_stopped_at_the_timeout(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(fs, "CHILD_TIMEOUT", 2)
    code, out = _misbehaving(repo, tmp_path, "import time\ntime.sleep(60)")
    assert code == 2
    assert "did not finish in 2 s" in out


def test_a_release_cannot_see_the_token_in_this_environment(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN"):
        monkeypatch.setenv(name, "secret")
    names = ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN")
    leak = f"import os\nassert not any(k in os.environ for k in {names!r}), 'leaked'"
    code, out = _misbehaving(repo, tmp_path, leak)
    assert code == 0, out
    assert "lock is behind" in out


def test_the_child_environment_has_only_what_a_plan_needs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GH_TOKEN", "secret")
    monkeypatch.setenv("HOME", "/home/me")
    monkeypatch.setenv("USERPROFILE", "C:/Users/me")
    env = fs._child_env()
    assert set(env) <= set(fs.CHILD_ENV_KEYS) | {"PYTHONUTF8"}
    assert env["PYTHONUTF8"] == "1"


def test_a_release_whose_init_cannot_read_this_repository_is_exit_2_with_its_reason(repo: Path, tmp_path: Path) -> None:
    payload = _payload(tmp_path / "v2", "0.2.0", V2_FILES)
    config = payload / "tools" / "framework_config.py"
    config.write_text(
        config.read_text(encoding="utf-8")
        + "\n\ndef load_project(path):\n    raise ValueError('the schema changed')\n",
        encoding="utf-8",
    )
    code, out = _run(repo, FakeGh({"v0.2.0": _day_iso()}, _tarball(payload)))
    assert code == 2
    assert "the release's init cannot read this repository" in out
    assert "the schema changed" in out


def test_a_release_with_unreadable_tools_is_exit_2(repo: Path, tmp_path: Path) -> None:
    payload = _payload(tmp_path / "v2", "0.2.0", V2_FILES)
    (payload / "tools" / "init.py").write_text("this is not python (\n", encoding="utf-8")
    code, out = _run(repo, FakeGh({"v0.2.0": _day_iso()}, _tarball(payload)))
    assert code == 2
    assert "SyntaxError" in out


# ---- it reads and writes nothing of the repository's
def _snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def test_the_repository_is_not_touched_and_this_process_is_left_as_it_was(repo: Path, tmp_path: Path) -> None:
    before = _snapshot(repo)
    config_module = sys.modules["framework_config"]
    modules, path = set(sys.modules), list(sys.path)
    _run(repo, FakeGh({"v0.2.0": _day_iso()}, _upstream_v2(tmp_path)))
    assert _snapshot(repo) == before
    assert sys.modules["framework_config"] is config_module
    assert set(sys.modules) == modules  # the release's modules were never loaded here
    assert sys.path == path


def test_the_scratch_download_is_removed(repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import tempfile

    made: list[Path] = []
    real = tempfile.mkdtemp

    def record(*args, **kwargs):
        path = Path(real(*args, **kwargs))
        made.append(path)
        return str(path)

    monkeypatch.setattr(fs.tempfile, "mkdtemp", record)
    _run(repo, FakeGh({"v0.2.0": _day_iso()}, _upstream_v2(tmp_path)))
    assert made
    assert not any(path.exists() for path in made)


# ---- gh itself
def test_run_gh_returns_the_output_of_a_command_that_succeeds() -> None:
    result = fs.run_gh([sys.executable, "-c", "print('hello')"])
    assert result.returncode == 0
    assert result.stdout.strip() == "hello"


def test_run_gh_writes_binary_output_to_the_file_asked_for(tmp_path: Path) -> None:
    target = tmp_path / "out.bin"
    result = fs.run_gh([sys.executable, "-c", "import sys; sys.stdout.buffer.write(bytes(range(256)))"], target)
    assert result.returncode == 0
    assert target.read_bytes() == bytes(range(256))


def test_run_gh_reports_a_failure_a_missing_program_and_a_timeout_without_raising(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    failed = fs.run_gh([sys.executable, "-c", "import sys; sys.stderr.write('nope'); sys.exit(4)"])
    assert (failed.returncode, failed.stderr.strip()) == (4, "nope")
    assert fs.run_gh(["definitely-not-a-program-xyz"]).returncode == 127
    assert fs.run_gh(["definitely-not-a-program-xyz"], tmp_path / "x").returncode == 127

    def slow(*args, **kwargs):
        raise subprocess.TimeoutExpired("gh", 1)

    monkeypatch.setattr(fs.subprocess, "run", slow)
    assert fs.run_gh(["gh", "api", "x"]).returncode == 124


# ---- the command line and the log
def test_the_command_line_runs_upstream_and_returns_its_code(
    repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    gh = FakeGh({"v0.2.0": _day_iso()}, _upstream_v2(tmp_path))
    code = fs.main(["--upstream", "--root", str(repo)], gh=gh, today=TAG_DATE + datetime.timedelta(days=20))
    assert code == 1
    assert "lock is behind" in capsys.readouterr().out


def test_check_and_upstream_are_exclusive(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as caught:
        fs.main(["--check", "--upstream"])
    assert caught.value.code == 2
    capsys.readouterr()


def test_the_run_leaves_a_log_of_the_upstream_tag_and_the_decision(
    repo: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level("INFO", logger="tools.framework_sync"):
        _run(repo, FakeGh({"v0.2.0": _day_iso(), "v0.1.5": _day_iso(9)}, _upstream_v2(tmp_path)))
    messages = [r.getMessage() for r in caplog.records]
    assert any("2 release tag(s), the highest is v0.2.0" in m for m in messages)
    assert any("locked 0.1.0, latest 0.2.0" in m for m in messages)
    assert any("planning with the release's init in a child process" in m for m in messages)
    assert any(m.startswith("extracted ") and "from the release" in m for m in messages)


# ---- survivors of the hardened mutation table
def test_a_payload_member_with_an_absolute_name_is_refused(repo: Path, tmp_path: Path) -> None:
    info = tarfile.TarInfo("/payload/tools/abs.py")
    info.size = 1
    payload = _payload(tmp_path / "v2", "0.2.0", V2_FILES)
    code, out = _run(repo, FakeGh({"v0.2.0": _day_iso()}, _tarball(payload, [info])))
    assert code == 2
    assert "unsafe" in out


def test_the_release_s_code_runs_in_an_isolated_interpreter(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[list[str]] = []
    real = subprocess.run

    def spy(argv, *args, **kwargs):
        seen.append(list(argv))
        return real(argv, *args, **kwargs)

    monkeypatch.setattr(fs.subprocess, "run", spy)
    _run(repo, FakeGh({"v0.2.0": _day_iso()}, _upstream_v2(tmp_path)))
    child = next(argv for argv in seen if "-c" in argv)
    assert child[1:3] == ["-I", "-c"]


def test_output_a_release_prints_after_its_result_is_dropped_too(repo: Path, tmp_path: Path) -> None:
    code, out = _misbehaving(repo, tmp_path, "import atexit\natexit.register(lambda: print('printed at exit'))")
    assert code == 0, out
    assert "printed at exit" not in out
    assert "lock is behind" in out


# ---- Copilot's review of the pull request
def test_a_release_lookup_that_fails_for_another_reason_than_not_found_is_exit_2_not_a_fallback(
    repo: Path, tmp_path: Path
) -> None:
    for error in ("HTTP 500: Server Error", "gh timed out", "HTTP 502: Bad Gateway"):
        gh = FakeGh({"v0.2.0": _day_iso(40)}, _upstream_v2(tmp_path), release_error=error)
        code, out = _run(repo, gh, today=TAG_DATE + datetime.timedelta(days=2))
        assert code == 2, out
        assert error in out


def test_a_release_that_is_not_found_falls_back_to_the_commit_date(repo: Path, tmp_path: Path) -> None:
    gh = FakeGh({"v0.2.0": _day_iso()}, _upstream_v2(tmp_path), release_error="HTTP 404: Not Found")
    code, out = _run(repo, gh)
    assert code == 0
    assert "from the commit" in out


def test_a_planner_that_exits_nonzero_after_printing_a_result_is_not_trusted(repo: Path, tmp_path: Path) -> None:
    code, out = _misbehaving(repo, tmp_path, "import atexit, os\natexit.register(lambda: os._exit(7))")
    assert code == 2
    assert "exited 7 after printing a result" in out


def test_an_unchanged_parametrised_file_with_a_dated_name_is_not_removed_or_changed(repo: Path, tmp_path: Path) -> None:
    """The lock holds the rendered name (notes/<day>.md); the release ships the template name (notes/{{today}}.md)."""
    assert list((repo / "notes").glob("*.md")), "the made repository has the dated file"
    same = _tarball(_payload(tmp_path / "v2-same", "0.2.0", V1_FILES))
    code, out = _run(repo, FakeGh({"v0.2.0": _day_iso()}, same), today=TAG_DATE + datetime.timedelta(days=400))
    assert code == 0, out
    assert "no managed file differs" in out
    assert "removed:" not in out


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

    scratch = (
        tmp_path / "rendered"
    )  # step 3: the repository's own choices, seeded, with the version set to the release's
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


def test_the_update_procedure_in_the_guide_ends_with_a_clean_check_and_a_current_lock(tmp_path: Path) -> None:
    repo = _made_with_choices(tmp_path)
    assert fs.main(["--check", "--root", str(repo)]) == 0
    files = {**V2_FILES, "extras/e.md": "# extra, changed\n", "framework-manifest.toml": MANIFEST + EXTRA_RULE}
    gone = _take_the_release(repo, tmp_path, files)
    assert gone == {"tools/two.py", "tools/four.py"}  # removed by the release; the repository overrides four.py

    assert fs.main(["--check", "--root", str(repo)]) == 0  # step 6
    code, out = _run(repo, FakeGh({"v0.2.0": _day_iso()}, _upstream_v2(tmp_path)))
    assert code == 0
    assert "lock is current: 0.2.0 locked, 0.2.0 is the latest release" in out
    assert not (repo / "extras").exists()  # specimens stayed off, though the release changed a file in it
    assert not (repo / "tools" / "two.py").exists()  # a removed file went
    assert (repo / "notes" / "2026-10-01.md").is_file() and not (repo / "notes" / "2026-10-22.md").exists()
    assert "locally edited" in (repo / "tools" / "one.py").read_text(encoding="utf-8")  # an override is not overwritten
    assert (repo / "tools" / "four.py").is_file()  # a removed, overridden file stays unless the owner deletes it
    assert (repo / "tools" / "three.py").is_file()  # an added file arrived


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
