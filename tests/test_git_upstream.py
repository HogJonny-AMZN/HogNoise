"""
Framework: the smoke test of the git upstream fixture (tests/git_upstream.py), which the git read's tests stand on.
Package: tests/test_git_upstream
"""

from __future__ import annotations

import datetime
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))

import git_upstream as gu  # noqa: E402

HOOK = "#!/bin/sh\nexit 0\n"


def _releases() -> list[gu.Release]:
    return [
        gu.Release("v0.1.0", {"a.txt": "one\n"}, day=datetime.date(2026, 10, 1)),
        gu.Release(
            "v0.2.0",
            {"a.txt": "two\n", "hooks/post-merge": HOOK},
            executable=frozenset({"hooks/post-merge"}),
            annotated=False,
            day=datetime.date(2026, 10, 5),
        ),
    ]


def test_the_upstream_holds_each_tag_reached_by_a_file_url(tmp_path: Path) -> None:
    upstream = gu.make_upstream(tmp_path, _releases())
    assert upstream.url.startswith("file://")
    refs = gu.git(tmp_path, "ls-remote", "--tags", "--refs", upstream.url)
    assert sorted(line.split("\t")[1] for line in refs.splitlines()) == ["refs/tags/v0.1.0", "refs/tags/v0.2.0"]


def test_each_tag_holds_its_own_payload_and_a_dropped_file_is_gone(tmp_path: Path) -> None:
    upstream = gu.make_upstream(tmp_path, _releases())
    assert gu.git(upstream.bare, "show", "v0.1.0:payload/a.txt") == "one\n"
    assert gu.git(upstream.bare, "show", "v0.2.0:payload/a.txt") == "two\n"
    assert "post-merge" not in gu.git(upstream.bare, "ls-tree", "-r", "--name-only", "v0.1.0")


def test_a_hook_without_a_suffix_is_committed_executable_on_every_system(tmp_path: Path) -> None:
    upstream = gu.make_upstream(tmp_path, _releases())
    entry = gu.git(upstream.bare, "ls-tree", "-r", "v0.2.0", "--", "payload/hooks/post-merge")
    assert entry.startswith("100755 ")


def test_a_repository_made_from_a_tag_is_committed_with_an_identity_and_its_lock_names_the_tag(tmp_path: Path) -> None:
    files = gu.payload_files("0.1.0", {"tools/one.py": "print('one')\n", "AGENTS.md": "# {{name}}\n"})
    upstream = gu.make_upstream(tmp_path, [gu.Release("v0.1.0", files)])
    repo = gu.make_repository(upstream, "v0.1.0", tmp_path)
    assert gu.git(repo, "status", "--porcelain") == ""
    assert gu.git(repo, "config", "user.email").strip() == gu.IDENTITY[1]
    assert '"template_version": "0.1.0"' in (repo / "framework.lock").read_text(encoding="utf-8")
    assert (repo / "AGENTS.md").read_text(encoding="utf-8") == "# Example Project\n"


def test_a_repository_is_made_by_the_tag_s_own_initialiser_not_this_checkout_s(tmp_path: Path) -> None:
    # Copilot's review of #226: the fixture imported this checkout's init, so a tag's own init never ran
    files = gu.payload_files("0.1.0", {"AGENTS.md": "# {{name}}\n"})
    marker = "from __future__ import annotations\n"
    files["tools/init.py"] = str(files["tools/init.py"]).replace(
        marker,
        marker + "import pathlib\npathlib.Path(__file__).parents[2].joinpath('ran-from-the-tag').write_text('y')\n",
        1,
    )  # beside the tag's payload/, not in it, where init would refuse it as a file no rule matches
    upstream = gu.make_upstream(tmp_path, [gu.Release("v0.1.0", files)])
    gu.make_repository(upstream, "v0.1.0", tmp_path)
    assert (tmp_path / "source-v0.1.0" / "ran-from-the-tag").is_file()


def test_an_annotated_and_a_lightweight_tag_each_carry_their_release_s_day(tmp_path: Path) -> None:
    upstream = gu.make_upstream(tmp_path, _releases())
    form = "--format=%(refname:short) %(objecttype) %(creatordate:short)"
    kinds = gu.git(upstream.bare, "for-each-ref", form, "refs/tags")
    assert sorted(kinds.splitlines()) == ["v0.1.0 tag 2026-10-01", "v0.2.0 commit 2026-10-05"]


def test_route_answers_the_written_out_url_from_the_upstream_and_any_other_from_nowhere(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    upstream = gu.make_upstream(tmp_path / "up", _releases())
    gu.route(monkeypatch, upstream, "https://github.sie.example.com/acme/template.git", tmp_path / "empty")
    refs = gu.git(tmp_path, "ls-remote", "--tags", "--refs", "https://github.sie.example.com/acme/template.git")
    assert sorted(line.split("\t")[1] for line in refs.splitlines()) == ["refs/tags/v0.1.0", "refs/tags/v0.2.0"]
    for other in ("https://github.com/acme/template.git", "https://github.sie.example.com/acme/other.git"):
        result = subprocess.run(
            ["git", "ls-remote", other],
            cwd=tmp_path,
            env=gu.isolated_env(),
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=60,
            check=False,
        )
        assert result.returncode != 0
        assert (tmp_path / "empty").resolve().as_posix() in result.stderr.replace("\\", "/")  # local, never the network
