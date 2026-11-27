"""
Framework: tests for tools/framework_sync.py --update (take the newest release onto a local branch, as one commit).
Package: tests/test_framework_sync_update

The upstream is a local bare git repository (``tests/git_upstream.py``) reached by a ``file://`` URL, whose tags hold
small synthetic payloads with the real initialiser in them. A repository is made from the older tag with that tag's own
``init new``, committed, with a git identity configured, as a person's clone would be. Nothing touches the network, and
every git call sees no user or system git configuration.

"Nothing written" is checked, not assumed: the working tree's files, ``git status``, the index (``git ls-files -s``),
the branches and ``HEAD`` are compared before and after.
"""

from __future__ import annotations

import datetime
import json
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))

import framework_sync as fs  # noqa: E402
import git_upstream as gu  # noqa: E402

GIT = shutil.which("git") or "git"
DAY_A = datetime.date(2026, 10, 1)
DAY_B = datetime.date(2026, 10, 20)

V1 = {
    "tools/one.py": "print('one')\n",
    "tools/two.py": "print('two')\n",
    "AGENTS.md": "# {{name}}\n",
    "notes/{{today}}.md": "# {{name}} notes\n",
    "README.md": "# {{name}}\n",
}
V2 = {
    "tools/one.py": "print('one, improved')\n",
    "tools/three.py": "print('three')\n",
    "AGENTS.md": "# {{name}}\n",
    "notes/{{today}}.md": "# {{name}} notes\n",
    "README.md": "# {{name}}\n",
}


def _release(version: str, files: dict[str, str], day: datetime.date) -> gu.Release:
    return gu.Release(f"v{version}", gu.payload_files(version, files), day=day)


@pytest.fixture
def made(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[..., Path]:
    """``made(releases, from_tag)``: an upstream holding ``releases`` (default 0.1.0 and 0.2.0) and a repository made
    from ``from_tag`` (default the first), committed on ``main``. ``release_url`` points at the upstream."""
    gu.isolate(monkeypatch)

    def make(releases: list[gu.Release] | None = None, from_tag: str | None = None) -> Path:
        releases = releases or [_release("0.1.0", V1, DAY_A), _release("0.2.0", V2, DAY_B)]
        upstream = gu.make_upstream(tmp_path / "up", releases)
        monkeypatch.setattr(fs, "release_url", lambda name: upstream.url)
        return gu.make_repository(upstream, from_tag or releases[0].tag, tmp_path)

    return make


def _update(repo: Path, which: Callable[[str], str | None] = lambda tool: GIT) -> tuple[int, str]:
    code, lines = fs.update_report(repo, which=which)
    return code, "\n".join(lines)


def _state(repo: Path) -> dict[str, object]:
    """Everything a run must leave as it was when it writes nothing."""
    files = {
        p.relative_to(repo).as_posix(): p.read_bytes()
        for p in sorted(repo.rglob("*"))
        if p.is_file() and ".git" not in p.relative_to(repo).parts
    }
    folders = [  # git status hides an empty folder, so a rollback that leaves one is seen only here
        p.relative_to(repo).as_posix()
        for p in sorted(repo.rglob("*"))
        if p.is_dir() and ".git" not in p.relative_to(repo).parts
    ]
    return {
        "files": files,
        "folders": folders,
        "status": gu.git(repo, "status", "--porcelain=v1", "--untracked-files=all"),
        "index": gu.git(repo, "ls-files", "-s"),
        "branches": gu.git(repo, "for-each-ref", "--format=%(refname) %(objectname)", "refs/heads"),
        "head": gu.git(repo, "rev-parse", "HEAD"),
        "on": gu.git(repo, "rev-parse", "--abbrev-ref", "HEAD"),  # "HEAD" when detached
    }


def _spy_git(
    monkeypatch: pytest.MonkeyPatch, fail: str | None = None, code: int = 1, err: str | None = None
) -> list[list[str]]:
    """Record every git call; with ``fail``, the call whose subcommand it is exits ``code`` with ``err`` on stderr
    (as given, every line of it) instead of running."""
    calls: list[list[str]] = []
    real = fs.run_git

    def spy(argv: list[str], cwd: Path, timeout: int = fs.GIT_TIMEOUT) -> subprocess.CompletedProcess:
        calls.append(argv)
        if fail is not None and fs.subcommand(argv[1:]) == fail:
            return subprocess.CompletedProcess(argv, code, "", f"fatal: {fail} went wrong" if err is None else err)
        return real(argv, cwd, timeout)

    monkeypatch.setattr(fs, "run_git", spy)
    return calls


def _network(calls: list[list[str]]) -> list[list[str]]:
    return [call for call in calls if call[1] in ("ls-remote", "fetch")]


def _commit_all(repo: Path, message: str = "chore: a change") -> None:
    gu.git(repo, "add", "-A")
    gu.git(repo, "commit", "-q", "--no-verify", "-m", message)


# ---- before any network call: the repository cannot be read (exit 2, nothing written)
def _without_upstream(repo: Path) -> None:
    toml = repo / "framework.toml"
    toml.write_text(toml.read_text(encoding="utf-8").replace('upstream = "acme/template"\n', ""), encoding="utf-8")


def _bad_project(repo: Path) -> None:
    (repo / "project.json").write_text("{not json", encoding="utf-8")


def _no_lock(repo: Path) -> None:
    (repo / "framework.lock").unlink()


def _odd_version(repo: Path) -> None:
    lock = json.loads((repo / "framework.lock").read_text(encoding="utf-8"))
    lock["template_version"] = "0.1.0-rc1"
    (repo / "framework.lock").write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")


@pytest.mark.parametrize(
    ("spoil", "words"),
    [
        (_without_upstream, 'set [framework] upstream = "owner/name" (or "host/owner/name") in framework.toml'),
        (_bad_project, "project.json"),
        (_no_lock, "framework.lock"),
        (_odd_version, "not X.Y.Z"),
    ],
)
def test_a_repository_that_cannot_be_read_is_exit_2_before_any_network_call(
    made: Callable[..., Path], monkeypatch: pytest.MonkeyPatch, spoil: Callable[[Path], None], words: str
) -> None:
    repo = made()
    spoil(repo)
    _commit_all(repo)
    before = _state(repo)
    calls = _spy_git(monkeypatch)
    code, out = _update(repo)
    assert code == 2, out
    assert words in out
    assert _network(calls) == []
    assert _state(repo) == before


def test_git_not_on_the_path_is_exit_2(made: Callable[..., Path]) -> None:
    repo = made()
    code, out = _update(repo, which=lambda tool: None)
    assert code == 2
    assert "git is not on the path" in out


# ---- the refusals (exit 1, nothing written, the branch list unchanged)
def _modified(repo: Path) -> None:
    (repo / "README.md").write_text("# changed and not committed\n", encoding="utf-8")


def _staged(repo: Path) -> None:
    (repo / "README.md").write_text("# changed and staged\n", encoding="utf-8")
    gu.git(repo, "add", "README.md")


def _untracked(repo: Path) -> None:
    (repo / "scratch.txt").write_text("left lying about\n", encoding="utf-8")


def _drifted(repo: Path) -> None:
    (repo / "tools" / "one.py").write_text("print('edited here')\n", encoding="utf-8")
    _commit_all(repo)


def _stale_override(repo: Path) -> None:
    toml = repo / "framework.toml"
    toml.write_text(
        toml.read_text(encoding="utf-8") + '\n[[overrides]]\ntarget = "tools/one.py"\nreason = "was edited once"\n',
        encoding="utf-8",
    )
    _commit_all(repo)


def _detached(repo: Path) -> None:
    gu.git(repo, "checkout", "-q", "--detach")


def _branch_exists(repo: Path) -> None:
    gu.git(repo, "branch", "template-update/v0.2.0")


@pytest.mark.parametrize(
    ("spoil", "words"),
    [
        (_modified, "README.md"),
        (_staged, "README.md"),
        (_untracked, "scratch.txt"),
        (_drifted, "[edited] tools/one.py"),
        (_stale_override, "[override-stale] tools/one.py"),
        (_detached, "HEAD is detached"),
        (_branch_exists, "template-update/v0.2.0 exists; delete it or finish it first"),
    ],
)
def test_a_repository_not_ready_for_an_update_is_refused_and_nothing_is_written(
    made: Callable[..., Path], spoil: Callable[[Path], None], words: str
) -> None:
    repo = made()
    spoil(repo)
    before = _state(repo)
    code, out = _update(repo)
    assert code == 1, out
    assert words in out
    assert _state(repo) == before


def test_an_unclean_tree_is_refused_before_any_network_call(
    made: Callable[..., Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = made()
    _untracked(repo)
    calls = _spy_git(monkeypatch)
    assert _update(repo)[0] == 1
    assert _network(calls) == []


def test_a_dirty_tree_lists_ten_paths_and_counts_the_rest(made: Callable[..., Path]) -> None:
    repo = made()
    for n in range(12):
        (repo / f"stray-{n:02}.txt").write_text("x\n", encoding="utf-8")
    code, out = _update(repo)
    assert code == 1
    assert "stray-09.txt" in out
    assert "stray-10.txt" not in out
    assert "12 path(s)" in out


def test_a_root_below_the_top_level_is_refused(made: Callable[..., Path]) -> None:
    repo = made()
    before = _state(repo)
    code, out = fs.update_report(repo / "tools", which=lambda tool: GIT)
    assert code == 1
    assert "top level" in "\n".join(out)
    assert _state(repo) == before


@pytest.mark.parametrize("step", ["status", "symbolic-ref", "rev-parse"])
def test_git_failing_in_the_first_step_is_exit_2_never_read_as_clean(
    made: Callable[..., Path], monkeypatch: pytest.MonkeyPatch, step: str
) -> None:
    repo = made()
    before = _state(repo)
    calls = _spy_git(monkeypatch, fail=step, code=128)
    code, out = _update(repo)
    assert code == 2, out
    assert f"git {step} failed (128)" in out
    assert _network(calls) == []
    assert _state(repo) == before


def test_a_branch_check_that_answers_neither_yes_nor_no_is_exit_2(
    made: Callable[..., Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = made()
    before = _state(repo)
    real = fs.run_git

    def odd(argv: list[str], cwd: Path, timeout: int = fs.GIT_TIMEOUT) -> subprocess.CompletedProcess:
        if argv[1:3] == ["rev-parse", "--verify"]:
            return subprocess.CompletedProcess(argv, 129, "", "usage: something odd")
        return real(argv, cwd, timeout)

    monkeypatch.setattr(fs, "run_git", odd)
    code, out = _update(repo)
    assert code == 2, out
    assert "rev-parse" in out
    assert _state(repo) == before


# ---- nothing to do (exit 0, nothing written)
def test_a_lock_at_the_newest_release_has_nothing_to_update(made: Callable[..., Path]) -> None:
    repo = made([_release("0.1.0", V1, DAY_A)])
    before = _state(repo)
    code, out = _update(repo)
    assert code == 0
    assert "nothing to update: 0.1.0 locked, 0.1.0 is the newest release" in out
    assert _state(repo) == before


def test_a_lock_ahead_of_the_newest_release_writes_nothing(
    made: Callable[..., Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = made([_release("0.1.0", V1, DAY_A), _release("0.2.0", V2, DAY_B)], from_tag="v0.2.0")
    older = gu.make_upstream(repo.parent / "older", [_release("0.1.0", V1, DAY_A)])
    monkeypatch.setattr(fs, "release_url", lambda name: older.url)
    before = _state(repo)
    code, out = _update(repo)
    assert code == 0
    assert "lock is ahead: 0.2.0 locked, 0.1.0 is the newest release; nothing written" in out
    assert _state(repo) == before


# ---- the child: the release's own init plans, one process per payload
def _payload_dir(base: Path, files: dict[str, str | bytes]) -> Path:
    for rel, content in files.items():
        path = base / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
    return base


def _with_init(files: dict[str, str | bytes], extra: str) -> dict[str, str | bytes]:
    """The release's ``init.py`` with ``extra`` run at import, before anything else."""
    text = str(files["tools/init.py"])
    marker = "from __future__ import annotations\n"
    return {**files, "tools/init.py": text.replace(marker, marker + extra + "\n", 1)}


@pytest.fixture
def child(made: Callable[..., Path], tmp_path: Path) -> Callable[..., tuple[Path, Path]]:
    """``child(files)``: a repository made from 0.1.0, and a release payload folder holding ``files`` at 0.2.0."""

    def make(files: dict[str, str | bytes] | None = None) -> tuple[Path, Path]:
        repo = made()
        payload = _payload_dir(tmp_path / "release" / "payload", files or gu.payload_files("0.2.0", V2))
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        return repo, payload

    return make


def test_the_newest_release_s_plan_writes_its_files_under_the_output_folder_only(
    child: Callable[..., tuple[Path, Path]], tmp_path: Path
) -> None:
    repo, payload = child()
    before = _state(repo)
    planned = fs._plan_release(payload, repo, tmp_path / "scratch", "write", "v0.2.0")
    out = tmp_path / "scratch" / "out"
    assert (out / "tools" / "one.py").read_text(encoding="utf-8") == "print('one, improved')\n"
    assert (out / "tools" / "three.py").is_file()
    assert ["tools/one.py", "update", "managed"] in planned["actions"]
    assert ["tools/two.py", "orphan", "managed"] in planned["actions"]
    assert json.loads(planned["lock"])["template_version"] == "0.2.0"
    assert "tools/two.py" not in planned["shipped"]
    assert any(r.startswith("framework.lock is for template 0.1.0") for r in planned["refusals"])
    assert _state(repo) == before


def test_the_locked_release_s_plan_names_its_project_owned_paths_and_writes_nothing(
    child: Callable[..., tuple[Path, Path]], tmp_path: Path
) -> None:
    repo, _ = child()
    older = _payload_dir(tmp_path / "older" / "payload", gu.payload_files("0.1.0", V1))
    planned = fs._plan_release(older, repo, tmp_path / "scratch", "paths", "v0.1.0")
    assert "README.md" in planned["project_owned"]
    assert "framework.toml" in planned["project_owned"]
    assert not (tmp_path / "scratch" / "out").exists()


@pytest.mark.parametrize(
    ("extra", "words"),
    [
        ("raise RuntimeError('boom at import')", "RuntimeError: boom at import"),
        ("import sys\nsys.exit(0)", "SystemExit"),
        ("import os\nos._exit(3)", "exited 3 without a result"),
    ],
)
def test_a_release_whose_init_misbehaves_cannot_plan_and_touches_nothing(
    child: Callable[..., tuple[Path, Path]], tmp_path: Path, extra: str, words: str
) -> None:
    repo, payload = child(_with_init(gu.payload_files("0.2.0", V2), extra))
    before = _state(repo)
    with pytest.raises(fs.UpstreamError, match=words) as caught:
        fs._plan_release(payload, repo, tmp_path / "scratch", "write", "v0.2.0")
    assert "v0.2.0's init" in str(caught.value)  # #230: the error names the release whose init failed
    assert _state(repo) == before


def test_each_planning_run_names_its_release_and_what_it_is_for(
    made: Callable[..., Path], caplog: pytest.LogCaptureFixture
) -> None:
    # #230: --update plans with two releases, and the log told them apart by nothing
    repo = made(_releases())
    with caplog.at_level("INFO", logger="tools.framework_sync"):
        code, out = _update(repo)
    assert code == 0, out
    planning = [r.getMessage() for r in caplog.records if r.getMessage().startswith("planning with ")]
    assert [m.split(", in a child process")[0] for m in planning] == [
        "planning with v0.2.0's init for the files to write",
        "planning with v0.1.0's init for the locked release's project-owned files",
    ]


def test_what_a_release_prints_is_not_its_result(child: Callable[..., tuple[Path, Path]], tmp_path: Path) -> None:
    fake = json.dumps({"ok": True, "project_owned": []})
    repo, payload = child(_with_init(gu.payload_files("0.2.0", V2), f"print({fs.RESULT_MARK!r} + {fake!r})"))
    planned = fs._plan_release(payload, repo, tmp_path / "scratch", "write", "v0.2.0")
    assert "actions" in planned


def test_a_release_that_never_finishes_is_stopped(
    child: Callable[..., tuple[Path, Path]], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(fs, "CHILD_TIMEOUT", 2)
    repo, payload = child(_with_init(gu.payload_files("0.2.0", V2), "import time\ntime.sleep(60)"))
    with pytest.raises(fs.UpstreamError, match="did not finish in 2 s"):
        fs._plan_release(payload, repo, tmp_path / "scratch", "write", "v0.2.0")


def test_a_release_whose_init_leaves_a_child_holding_its_output_is_still_stopped_on_time(
    child: Callable[..., tuple[Path, Path]], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # the review's probe: a timeout that ends only the first process waits for the grandchild holding the pipe
    monkeypatch.setattr(fs, "CHILD_TIMEOUT", 2)
    extra = (
        "import subprocess, sys, time\n"
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        "time.sleep(60)"
    )
    repo, payload = child(_with_init(gu.payload_files("0.2.0", V2), extra))
    started = time.monotonic()
    with pytest.raises(fs.UpstreamError, match="did not finish in 2 s"):
        fs._plan_release(payload, repo, tmp_path / "scratch", "write", "v0.2.0")
    assert time.monotonic() - started < 30


def test_run_git_does_not_pass_on_where_another_repository_is(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # the review's probe: a GIT_DIR set by a hook or a wrapper aimed the scratch folder's git calls at that repository
    other, scratch = tmp_path / "other", tmp_path / "scratch"
    for folder in (other, scratch):
        folder.mkdir()
        gu.git(folder, "init", "-q")
    for key, value in (("GIT_DIR", other / ".git"), ("GIT_WORK_TREE", other), ("GIT_INDEX_FILE", other / "x")):
        monkeypatch.setenv(key, str(value))
    result = fs.run_git([GIT, "rev-parse", "--absolute-git-dir"], scratch)
    assert result.returncode == 0, result.stderr
    assert Path(result.stdout.strip()).resolve() == (scratch / ".git").resolve()


@pytest.mark.parametrize("bad", ["../escape.txt", "/abs.txt", "a/../../escape.txt", "C:/x.txt", "a\\\\b.txt", ""])
def test_a_plan_naming_a_path_outside_the_output_folder_is_refused(
    child: Callable[..., tuple[Path, Path]], tmp_path: Path, bad: str
) -> None:
    wrap = (
        "def _wrap(real):\n"
        "    def plan_new(*a, **k):\n"
        "        plan = real(*a, **k)\n"
        f"        plan.contents[{bad!r}] = b'x'\n"
        "        return plan\n"
        "    return plan_new\n"
    )
    files = gu.payload_files("0.2.0", V2)
    files = {**files, "tools/init.py": str(files["tools/init.py"]) + "\n" + wrap + "plan_new = _wrap(plan_new)\n"}
    repo, payload = child(files)
    with pytest.raises(fs.UpstreamError, match="outside the output folder"):
        fs._plan_release(payload, repo, tmp_path / "scratch", "write", "v0.2.0")
    assert not (tmp_path / "escape.txt").exists()
    assert not (tmp_path / "scratch" / "escape.txt").exists()


def test_an_output_that_is_not_a_regular_file_is_refused(tmp_path: Path) -> None:
    out = tmp_path / "out"
    (out / "tools").mkdir(parents=True)
    (out / "tools" / "one.py").write_text("x\n", encoding="utf-8")
    (out / "tools" / "dir.py").mkdir()
    assert fs._output(out, "tools/one.py").read_text(encoding="utf-8") == "x\n"
    with pytest.raises(fs.UpstreamError, match="not a regular file"):
        fs._output(out, "tools/dir.py")
    with pytest.raises(fs.UpstreamError, match="not a regular file"):
        fs._output(out, "tools/missing.py")
    try:
        (out / "tools" / "link.py").symlink_to(out / "tools" / "one.py")
    except OSError as e:
        pytest.skip(f"this system cannot make a symlink here: {e}")
    with pytest.raises(fs.UpstreamError, match="not a regular file"):
        fs._output(out, "tools/link.py")


# ---- decide: every row of the table, judged before any write
HOOK = "#!/bin/sh\nexit 0\n"
A_FILES = {
    "tools/one.py": "print('one')\n",
    "tools/two.py": "print('two')\n",
    "tools/four.py": "print('four')\n",
    "tools/five.py": "print('five')\n",
    "tools/six.py": "print('six')\n",
    "AGENTS.md": "# {{name}}\n",
    "notes/{{today}}.md": "# {{name}} notes\n",
    "README.md": "# {{name}}\n",
    "seeds/mock.md": "# a mock project\n",
    "seeds/{{today}}-log.md": "# log\n",
}
B_FILES = {
    "tools/one.py": "print('one, improved')\n",  # changed
    "tools/three.py": "print('three')\n",  # added
    "tools/four.py": "print('four')\n",  # unchanged
    "tools/five.py": "print('five, improved')\n",  # changed, and overridden here
    "tools/six.py": "print('six')\n",  # unchanged, and overridden here
    "hooks/post-merge": HOOK,  # added, a hook without a suffix
    "AGENTS.md": "# {{name}}, the agents' map\n",  # a parametrised file, changed
    "notes/{{today}}.md": "# {{name}} notes\n",
    "README.md": "# {{name}}\n",
    "seeds/mock.md": "# a mock project\n",
    "seeds/{{today}}-log.md": "# log\n",
    "seeds/new.md": "# a seed the release adds\n",
}


def _releases(a: dict | None = None, b: dict | None = None) -> list[gu.Release]:
    return [
        gu.Release("v0.1.0", gu.payload_files("0.1.0", a or A_FILES), day=DAY_A),
        gu.Release(
            "v0.2.0",
            gu.payload_files("0.2.0", b or B_FILES),
            executable=frozenset({"hooks/post-merge"}),
            day=DAY_B,
        ),
    ]


def _override(repo: Path, target: str, reason: str = "the repository's own") -> None:
    toml = repo / "framework.toml"
    toml.write_text(
        toml.read_text(encoding="utf-8") + f'\n[[overrides]]\ntarget = "{target}"\nreason = "{reason}"\n',
        encoding="utf-8",
    )


def _overridden(repo: Path) -> None:
    """five.py and six.py edited here and overridden; the mock project deleted, as a repository replaces it."""
    (repo / "tools" / "five.py").write_text("print('five, ours')\n", encoding="utf-8")
    (repo / "tools" / "six.py").write_text("print('six, ours')\n", encoding="utf-8")
    _override(repo, "tools/five.py", "five is ours")
    _override(repo, "tools/six.py", "six is ours")
    (repo / "seeds" / "mock.md").unlink()
    _commit_all(repo, "chore: our own five and six; no mock project")


@pytest.fixture
def decided(monkeypatch: pytest.MonkeyPatch) -> Callable[[Path], fs.UpdatePlan]:
    """``decided(repo)``: run ``--update`` up to the write and return what it decided; nothing is written."""

    def run(repo: Path) -> fs.UpdatePlan:
        seen: list[fs.UpdatePlan] = []

        def capture(plan: fs.UpdatePlan, root: Path, git: str) -> tuple[int, list[str]]:
            seen.append(plan)
            return 0, ["captured"]

        monkeypatch.setattr(fs, "_carry_out", capture)
        before = _state(repo)
        code, out = _update(repo)
        assert code == 0, out
        assert _state(repo) == before
        assert len(seen) == 1
        return seen[0]

    return run


def test_every_row_of_the_table(made: Callable[..., Path], decided: Callable[[Path], fs.UpdatePlan]) -> None:
    repo = made(_releases())
    _overridden(repo)
    plan = decided(repo)
    assert sorted(plan.write) == ["AGENTS.md", "hooks/post-merge", "tools/one.py", "tools/three.py"]
    assert plan.delete == ["tools/two.py"]  # the release dropped it
    assert plan.kept == [("tools/five.py", "five is ours")]  # overridden and changed by the release
    assert plan.kept_unchanged == 1  # six.py: overridden, not changed by the release
    assert plan.seeds == ["seeds/new.md"]  # the mock project, deleted here, is not written back
    assert plan.removed_overrides == []
    assert plan.left == []
    lock = json.loads(plan.lock_text)
    assert lock["template_version"] == "0.2.0"
    assert lock["initialised"] == json.loads((repo / "framework.lock").read_text(encoding="utf-8"))["initialised"]
    assert (plan.tag, plan.old_tag, plan.start, plan.branch) == ("v0.2.0", "v0.1.0", "main", "template-update/v0.2.0")


def test_a_hook_without_a_suffix_is_executable_on_every_system(
    made: Callable[..., Path], decided: Callable[[Path], fs.UpdatePlan]
) -> None:
    repo = made(_releases())
    plan = decided(repo)
    assert "hooks/post-merge" in plan.executable
    assert "tools/one.py" not in plan.executable


def test_a_file_of_a_module_turned_off_still_shipped_is_left_in_place_and_listed(
    made: Callable[..., Path], decided: Callable[[Path], fs.UpdatePlan]
) -> None:
    def in_hygiene(version: str, files: dict[str, str]) -> gu.Release:
        """two.py in the hygiene module (one the seeded documents do not link to), which starts on."""
        payload = gu.payload_files(version, files)
        payload["framework-manifest.toml"] = gu.MANIFEST.replace(
            'pattern = "tools/two.py"\nmodule = "python-uv"', 'pattern = "tools/two.py"\nmodule = "hygiene"'
        )
        payload["framework.toml"] = gu.framework_text(version, hygiene="on")
        return gu.Release(f"v{version}", payload, day=DAY_A if version == "0.1.0" else DAY_B)

    repo = made(
        [in_hygiene("0.1.0", A_FILES), in_hygiene("0.2.0", {**B_FILES, "tools/two.py": "print('two, still')\n"})]
    )
    toml = repo / "framework.toml"
    assert 'hygiene = "on"' in toml.read_text(encoding="utf-8")
    toml.write_text(toml.read_text(encoding="utf-8").replace('hygiene = "on"', 'hygiene = "off"'), encoding="utf-8")
    _commit_all(repo, "chore: hygiene off")
    plan = decided(repo)
    assert "tools/two.py" not in plan.delete
    assert plan.left == ["tools/two.py"]


def test_a_deleted_file_under_an_override_is_not_written_back(
    made: Callable[..., Path], decided: Callable[[Path], fs.UpdatePlan]
) -> None:
    repo = made(_releases())
    (repo / "tools" / "four.py").unlink()
    _override(repo, "tools/four.py", "we do without four")
    _commit_all(repo)
    plan = decided(repo)
    assert "tools/four.py" not in plan.write
    assert plan.removed_overrides == []


def test_an_override_the_release_makes_stale_is_removed_and_its_file_left_alone(
    made: Callable[..., Path], decided: Callable[[Path], fs.UpdatePlan]
) -> None:
    repo = made(_releases())
    (repo / "tools" / "one.py").write_text("print('one, improved')\n", encoding="utf-8")  # what the release ships
    _override(repo, "tools/one.py", "we had the fix first")
    _commit_all(repo)
    plan = decided(repo)
    assert plan.removed_overrides == [("tools/one.py", "stale")]
    assert "tools/one.py" not in plan.write


def test_an_overridden_file_the_release_drops_is_kept_and_its_override_removed(
    made: Callable[..., Path], decided: Callable[[Path], fs.UpdatePlan]
) -> None:
    repo = made(_releases())
    (repo / "tools" / "two.py").write_text("print('two, ours')\n", encoding="utf-8")
    _override(repo, "tools/two.py", "two is ours")
    _commit_all(repo)
    plan = decided(repo)
    assert "tools/two.py" not in plan.delete
    assert plan.left == ["tools/two.py"]
    assert plan.removed_overrides == [("tools/two.py", "no longer the template's: keep it or delete it")]


def test_an_overridden_symlink_whose_target_matches_the_release_keeps_its_override(
    made: Callable[..., Path], decided: Callable[[Path], fs.UpdatePlan]
) -> None:
    repo = made(_releases())
    (repo / "shared").mkdir()
    (repo / "shared" / "five.py").write_text("print('five, improved')\n", encoding="utf-8")
    (repo / "tools" / "five.py").unlink()
    try:
        (repo / "tools" / "five.py").symlink_to(Path("..") / "shared" / "five.py")
    except OSError as e:
        pytest.skip(f"this system cannot make a symlink here: {e}")
    _override(repo, "tools/five.py", "a link to the shared copy")
    _commit_all(repo)
    plan = decided(repo)
    assert plan.removed_overrides == []
    assert "tools/five.py" not in plan.write


def test_a_dated_seed_is_not_written_a_second_time(
    made: Callable[..., Path], decided: Callable[[Path], fs.UpdatePlan]
) -> None:
    repo = made(_releases())
    for dated in (repo / "seeds").glob("*-log.md"):
        dated.unlink()
    _commit_all(repo, "chore: no log")
    plan = decided(repo)
    assert not any(path.endswith("-log.md") for path in plan.seeds)


def test_a_lock_whose_release_has_no_tag_writes_no_seed_and_says_why(
    made: Callable[..., Path], decided: Callable[[Path], fs.UpdatePlan], tmp_path: Path
) -> None:
    repo = made(_releases())
    gu.git(tmp_path / "up" / "upstream.git", "tag", "-d", "v0.1.0")
    plan = decided(repo)
    assert plan.seeds == []
    assert "v0.1.0 has no tag, so no project-owned seed is written" in plan.notes


def test_a_plan_refusal_is_refused_with_its_text_and_nothing_written(made: Callable[..., Path]) -> None:
    repo = made(_releases(b={**B_FILES, "AGENTS.md": "# {{name}} {{bogus}}\n"}))
    before = _state(repo)
    code, out = _update(repo)
    assert code == 1, out
    assert "AGENTS.md: unknown token" in out
    assert "framework.lock is for template" not in out
    assert _state(repo) == before


def test_a_path_the_repository_ignores_is_refused_not_forced(made: Callable[..., Path]) -> None:
    repo = made(_releases())
    (repo / ".gitignore").write_text("tools/three.py\n", encoding="utf-8")
    _commit_all(repo, "chore: ignore three")
    before = _state(repo)
    code, out = _update(repo)
    assert code == 1, out
    assert "tools/three.py" in out
    assert ".gitignore" in out
    assert _state(repo) == before


# ---- the framework.toml edit: made to the text, checked by parsing it again
TOML = """# The repository's choices. A comment at the top.
[framework]
template_version = "0.1.0"  # the release this repository is at
upstream = "acme/template"

[modules]
core = "on"

[harnesses]
enabled = []

# The overrides: each a file this repository differs on, on purpose.
[[overrides]]
target = "tools/one.py"
reason = "ours"
# one.py: the journal of 2026-10-02 says why.

[[overrides]]
target = "tools/two.py"
reason = "ours too"

# This introduces the next table and stays.
[checks]
handoff_max_lines = 150
"""


def _config(text: str):
    import framework_config as fc

    return fc.parse_framework_text(text)


def _toml(base: str = TOML, modules: str = 'core = "on"') -> str:
    import framework_config as fc

    states = "\n".join(f'{name} = "{"on" if name in ("core", "python-uv") else "planned"}"' for name in fc.MODULES)
    return base.replace(modules, states.replace('lanes = "planned"', 'lanes = "off"'))


def test_the_version_line_changes_and_every_comment_stays() -> None:
    text = _toml()
    out = fs._edit_framework_text(text, _config(text), "0.1.0", "0.2.0", [])
    assert out == text.replace('template_version = "0.1.0"', 'template_version = "0.2.0"')


def test_an_override_s_entry_goes_and_the_comment_introducing_the_next_table_stays() -> None:
    text = _toml()
    out = fs._edit_framework_text(text, _config(text), "0.1.0", "0.2.0", ["tools/two.py"])
    assert 'target = "tools/two.py"' not in out
    assert "# This introduces the next table and stays.\n[checks]" in out
    assert 'target = "tools/one.py"' in out
    assert "# The overrides: each a file this repository differs on, on purpose." in out
    assert [o.target for o in _config(out).overrides] == ["tools/one.py"]


def test_the_first_of_two_overrides_goes_with_its_blank_line_and_nothing_else() -> None:
    text = _toml()
    out = fs._edit_framework_text(text, _config(text), "0.1.0", "0.2.0", ["tools/one.py"])
    assert [o.target for o in _config(out).overrides] == ["tools/two.py"]
    assert "# The overrides: each a file this repository differs on, on purpose.\n" in out
    assert "\n\n\n" not in out


def test_line_endings_are_kept() -> None:
    text = _toml().replace("\n", "\r\n")
    out = fs._edit_framework_text(text, _config(text), "0.1.0", "0.2.0", ["tools/two.py"])
    assert "\n" not in out.replace("\r\n", "")
    assert 'template_version = "0.2.0"  # the release this repository is at\r\n' in out


@pytest.mark.parametrize(
    "line", ['template_version = "0.1.0"', 'template_version="0.1.0"#at', '  template_version = "0.1.0"  ']
)
def test_a_version_line_in_its_usual_shapes_is_edited(line: str) -> None:
    text = _toml().replace('template_version = "0.1.0"  # the release this repository is at', line)
    out = fs._edit_framework_text(text, _config(text), "0.1.0", "0.2.0", [])
    assert _config(out).template_version == "0.2.0"


def test_a_version_line_that_is_not_on_its_own_is_refused() -> None:
    text = _toml().replace('template_version = "0.1.0"  # the release this repository is at\n', "")
    text = text.replace("[framework]\n", '[framework]\ntemplate_version = "0.1.0"; upstream_extra = 1\n')
    with pytest.raises(fs.Refused, match="cannot set the version by a plain edit"):
        fs._edit_framework_text(text, _config(_toml()), "0.1.0", "0.2.0", [])


def test_an_override_in_an_inline_table_is_refused_not_rewritten() -> None:
    inline = 'overrides = [{ target = "tools/one.py", reason = "ours" }, { target = "tools/two.py", reason = "too" }]'
    base = (
        '[framework]\ntemplate_version = "0.1.0"\nupstream = "acme/template"\n\n[modules]\ncore = "on"\n\n'
        "[harnesses]\nenabled = []\n\n[checks]\nhandoff_max_lines = 150\n"
    )
    text = _toml(inline + "\n" + base)
    with pytest.raises(fs.Refused, match="cannot remove the override of tools/two.py by a plain edit"):
        fs._edit_framework_text(text, _config(text), "0.1.0", "0.2.0", ["tools/two.py"])


def test_an_override_that_cannot_be_removed_by_a_plain_edit_refuses_the_run(made: Callable[..., Path]) -> None:
    repo = made(_releases())
    (repo / "tools" / "one.py").write_text("print('one, improved')\n", encoding="utf-8")  # makes it stale
    toml = repo / "framework.toml"
    text = toml.read_text(encoding="utf-8")
    toml.write_text('overrides = [{ target = "tools/one.py", reason = "ours" }]\n' + text, encoding="utf-8")
    _commit_all(repo)
    before = _state(repo)
    code, out = _update(repo)
    assert code == 1, out
    assert "framework.toml: cannot remove the override of tools/one.py by a plain edit" in out
    assert _state(repo) == before


def test_the_run_decides_the_new_framework_toml(
    made: Callable[..., Path], decided: Callable[[Path], fs.UpdatePlan]
) -> None:
    repo = made(_releases())
    (repo / "tools" / "one.py").write_text("print('one, improved')\n", encoding="utf-8")
    _override(repo, "tools/one.py", "we had the fix first")
    _commit_all(repo)
    plan = decided(repo)
    assert 'template_version = "0.2.0"' in plan.toml_text
    assert "tools/one.py" not in plan.toml_text


# ---- the hand steps and the message
GUIDE = """# Taking a template release into a repository

## The steps

1. Something general.

## 0.1.0: the first

Nothing to do.

## 0.2.0: the second

1. **Do this.** By hand.

```text
## 9.9.9: a heading inside a fence, which ends nothing
```

2. **And this.**

## 0.3.0: the third

1. **Three.**

## 0.4.0: beyond the range

Not taken.
"""


def test_the_sections_in_range_are_taken_in_version_order_and_a_fence_ends_nothing() -> None:
    shuffled = (
        GUIDE.replace("## 0.2.0: the second", "## 0.2.0: the second").replace(
            "## 0.3.0: the third\n\n1. **Three.**\n\n", ""
        )
        + "\n## 0.3.0: the third\n\n1. **Three.**\n"
    )
    steps = fs._hand_steps(shuffled, (0, 1, 0), (0, 3, 0))
    assert [(v, title) for v, title, _ in steps] == [("0.2.0", "the second"), ("0.3.0", "the third")]
    second = steps[0][2]
    assert second.startswith("## 0.2.0: the second\n")
    assert "## 9.9.9: a heading inside a fence, which ends nothing" in second
    assert "2. **And this.**" in second
    assert "0.4.0" not in "".join(text for _, _, text in steps)
    assert "## 0.3.0" not in second


def test_one_section_and_none() -> None:
    assert [v for v, _, _ in fs._hand_steps(GUIDE, (0, 2, 0), (0, 3, 0))] == ["0.3.0"]
    assert fs._hand_steps(GUIDE, (0, 4, 0), (0, 5, 0)) == []


def _guided(b: dict | None = None, guide: str | bytes = GUIDE) -> list[gu.Release]:
    return _releases(b={**(b or B_FILES), "Docs/standards/updating.md": guide})


def test_the_message_names_the_release_the_counts_the_groups_and_the_sign_off(
    made: Callable[..., Path], decided: Callable[[Path], fs.UpdatePlan]
) -> None:
    repo = made(_guided())
    _overridden(repo)
    (repo / "tools" / "two.py").write_text("print('two, ours')\n", encoding="utf-8")
    _override(repo, "tools/two.py", "two is ours")
    _commit_all(repo)
    plan = decided(repo)
    assert plan.message == (
        "chore(framework): take template v0.2.0 (from v0.1.0)\n"
        "\n"
        "2 managed file(s) changed, 3 added, 0 removed; 1 project-owned seed(s) added.\n"  # updating.md is new too
        "\n"
        "Kept, overridden, and changed by the release (merge by hand):\n"
        "- tools/five.py: five is ours\n"
        "  see: git diff v0.1.0 v0.2.0 -- payload/tools/five.py, in a clone of the template\n"
        "1 other override(s) in force, unchanged by this release.\n"
        "\n"
        "Overrides removed (the new lock makes them stale or unknown):\n"
        "- tools/two.py: no longer the template's: keep it or delete it\n"
        "\n"
        "Left in place, no longer locked:\n"
        "- tools/two.py\n"
        "\n"
        "Hand steps (Docs/standards/updating.md, v0.1.0 to v0.2.0):\n"
        "- [ ] 0.2.0: the second\n"
        "\n"
        "Signed-off-by: Ada Example <ada@example.org>\n"
    )


def test_an_empty_group_is_one_line(made: Callable[..., Path], decided: Callable[[Path], fs.UpdatePlan]) -> None:
    repo = made(_guided(guide="# nothing\n"))
    plan = decided(repo)
    assert "Kept, overridden, and changed by the release: none\n" in plan.message
    assert "Overrides removed: none\n" in plan.message
    assert "Left in place, no longer locked: none\n" in plan.message
    assert "Hand steps: none\n" in plan.message
    assert "no hand steps between v0.1.0 and v0.2.0 in updating.md" in plan.notes


def test_no_updating_md_in_the_release_is_a_note(
    made: Callable[..., Path], decided: Callable[[Path], fs.UpdatePlan]
) -> None:
    repo = made(_releases())
    plan = decided(repo)
    assert plan.hand_steps == []
    assert "no hand steps between v0.1.0 and v0.2.0 in updating.md" in plan.notes


def test_an_updating_md_that_cannot_be_decoded_is_exit_2_and_nothing_is_written(made: Callable[..., Path]) -> None:
    repo = made(_guided(guide=b"## 0.2.0: bad \xff\xfe bytes\n"))
    before = _state(repo)
    code, out = _update(repo)
    assert code == 2, out
    assert "updating.md" in out
    assert _state(repo) == before


def test_a_section_s_trailers_stay_out_of_the_message(
    made: Callable[..., Path], decided: Callable[[Path], fs.UpdatePlan]
) -> None:
    guide = (
        "## 0.2.0: the second\n\n1. Quote this:\n\n    Co-Authored-By: Claude <noreply@anthropic.com>\n"
        "    Signed-off-by: Someone Else <else@example.org>\n"
    )
    repo = made(_guided(guide=guide))
    plan = decided(repo)
    assert "Co-Authored-By" not in plan.message
    assert "Someone Else" not in plan.message
    assert "Co-Authored-By: Claude" in plan.hand_steps[0][2]


def test_a_message_the_repository_s_own_check_rejects_is_refused_and_nothing_is_written(
    made: Callable[..., Path],
) -> None:
    repo = made(_releases())
    gu.git(repo, "config", "user.name", "Bob Stranger")
    gu.git(repo, "config", "user.email", "bob@example.org")
    before = _state(repo)
    code, out = _update(repo)
    assert code == 1, out
    assert "the sign-off is missing or is not an accepted identity" in out
    assert _state(repo) == before


# ---- write, commit, roll back
HOOKS = ("pre-commit", "commit-msg", "prepare-commit-msg", "post-commit")


def _failing_hooks(repo: Path) -> Path:
    """Install hooks of all four kinds that fail and leave a mark; return the mark's folder."""
    marks = repo.parent / "hook-marks"
    marks.mkdir(exist_ok=True)
    hooks = repo / ".git" / "hooks"
    for name in HOOKS:
        hook = hooks / name
        hook.write_text(f"#!/bin/sh\ntouch '{marks.as_posix()}/{name}'\nexit 1\n", encoding="utf-8", newline="\n")
        hook.chmod(0o755)
    return marks


def _full(made: Callable[..., Path]) -> Path:
    """The richer repository: five and six overridden, the mock project gone, one.py made stale under an override."""
    repo = made(_guided())
    _overridden(repo)
    return repo


def test_a_run_makes_one_commit_on_the_branch_from_the_start_with_no_hook_run(made: Callable[..., Path]) -> None:
    repo = _full(made)
    marks = _failing_hooks(repo)
    start = gu.git(repo, "rev-parse", "HEAD").strip()
    code, out = _update(repo)
    assert code == 0, out
    assert gu.git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip() == "template-update/v0.2.0"
    assert gu.git(repo, "rev-parse", "HEAD~1").strip() == start
    assert gu.git(repo, "rev-list", "--count", f"{start}..HEAD").strip() == "1"
    assert list(marks.iterdir()) == [], "a hook ran"
    assert gu.git(repo, "status", "--porcelain", "--untracked-files=all") == ""
    body = gu.git(repo, "log", "-1", "--format=%B")
    assert body.startswith("chore(framework): take template v0.2.0 (from v0.1.0)\n")
    assert body.rstrip().endswith("Signed-off-by: Ada Example <ada@example.org>")


def test_a_run_writes_what_was_decided(made: Callable[..., Path]) -> None:
    repo = _full(made)
    initialised = json.loads((repo / "framework.lock").read_text(encoding="utf-8"))["initialised"]
    dated = sorted(p.name for p in (repo / "seeds").glob("*-log.md"))
    assert _update(repo)[0] == 0
    read = lambda rel: (repo / rel).read_text(encoding="utf-8")  # noqa: E731
    assert read("tools/one.py") == "print('one, improved')\n"  # changed
    assert read("tools/three.py") == "print('three')\n"  # added
    assert not (repo / "tools" / "two.py").exists()  # removed
    assert read("AGENTS.md") == "# Example Project, the agents' map\n"  # parametrised, rendered here
    assert read("tools/five.py") == "print('five, ours')\n"  # overridden, changed by the release: kept
    assert read("seeds/new.md") == "# a seed the release adds\n"  # the seed the release adds
    assert not (repo / "seeds" / "mock.md").exists()  # deleted here, not written back
    assert sorted(p.name for p in (repo / "seeds").glob("*-log.md")) == dated  # no second dated seed
    assert (repo / "notes" / f"{initialised}.md").is_file()
    lock = json.loads(read("framework.lock"))
    assert (lock["template_version"], lock["initialised"]) == ("0.2.0", initialised)
    toml = read("framework.toml")
    assert 'template_version = "0.2.0"' in toml
    assert 'target = "tools/five.py"' in toml and 'target = "tools/six.py"' in toml
    assert fs.report(repo).findings == []


def test_a_new_hook_without_a_suffix_is_committed_executable(made: Callable[..., Path]) -> None:
    repo = made(_releases())
    assert _update(repo)[0] == 0
    entry = gu.git(repo, "ls-tree", "HEAD", "--", "hooks/post-merge")
    assert entry.startswith("100755 "), entry


def test_a_stale_override_goes_and_its_file_is_not_touched(made: Callable[..., Path]) -> None:
    repo = made(_releases())
    (repo / "tools" / "one.py").write_text("print('one, improved')\n", encoding="utf-8")
    _override(repo, "tools/one.py", "we had the fix first")
    _commit_all(repo)
    before = (repo / "tools" / "one.py").read_bytes()
    assert _update(repo)[0] == 0
    assert (repo / "tools" / "one.py").read_bytes() == before
    assert "tools/one.py" not in (repo / "framework.toml").read_text(encoding="utf-8")


def _started(repo: Path) -> dict[str, object]:
    state = _state(repo)
    state.pop("files")
    return state


def test_a_write_that_fails_rolls_back_to_the_start(made: Callable[..., Path], monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _full(made)
    before = _state(repo)
    real = fs.ini.write_atomic
    count = {"n": 0}

    def third_fails(dest: Path, data: bytes, **kwargs) -> None:
        count["n"] += 1
        if count["n"] == 3:
            raise OSError("the disk is full")
        real(dest, data, **kwargs)

    monkeypatch.setattr(fs.ini, "write_atomic", third_fails)
    code, out = _update(repo)
    assert code == 2, out
    assert "the disk is full" in out
    # the review's probe: the folders named before the failing write were never made, and none is reported as failed
    assert "rolled back: " in out, out
    assert _state(repo) == before
    assert not list(repo.rglob("*.init-tmp"))


def test_the_undo_order_is_the_files_then_the_folders_deepest_first() -> None:
    created = ["Docs/", "Docs/standards/", "Docs/standards/new.md", "hooks/", "hooks/pre-push", "tools/three.py"]
    assert fs._undo_order(created) == [
        "Docs/standards/new.md",
        "hooks/pre-push",
        "tools/three.py",
        "Docs/standards/",
        "Docs/",
        "hooks/",
    ]


def test_an_os_error_in_the_commit_rolls_back_to_the_start(
    made: Callable[..., Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _full(made)
    before = _state(repo)

    def unwritable(*args: object) -> None:
        raise PermissionError("the scratch folder is read-only")

    monkeypatch.setattr(fs, "_commit", unwritable)
    code, out = _update(repo)
    assert code == 2, out
    assert "the scratch folder is read-only" in out
    assert "rolled back: " in out, out
    assert _state(repo) == before


def test_a_check_that_cannot_run_after_the_write_rolls_back_to_the_start(
    made: Callable[..., Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _full(made)
    before = _state(repo)

    real = fs.report
    calls = {"n": 0}

    def broken_after_the_write(root: Path) -> object:  # step 1 checks first, so only the second call fails
        calls["n"] += 1
        if calls["n"] == 2:
            raise fs.fc.ConfigError("modules", "the check cannot read it", "framework.toml")
        return real(root)

    monkeypatch.setattr(fs, "report", broken_after_the_write)
    code, out = _update(repo)
    assert code == 2, out
    assert "the check could not run" in out
    assert "rolled back: " in out, out
    assert _state(repo) == before


@pytest.mark.parametrize("step", ["ls-tree", "var", "check-ignore", "switch"])
def test_git_failing_in_a_later_step_is_exit_2_and_nothing_is_left(
    made: Callable[..., Path], monkeypatch: pytest.MonkeyPatch, step: str
) -> None:
    repo = _full(made)
    before = _state(repo)
    _spy_git(monkeypatch, fail=step, code=128)
    code, out = _update(repo)
    assert code == 2, out
    assert f"git {step} failed (128)" in out, out
    assert _state(repo) == before


def test_an_executable_whose_name_git_would_quote_is_still_executable(tmp_path: Path) -> None:
    # the review: ls-tree without -z quotes a non-ASCII name (core.quotePath), and it no longer matched
    names = ["hooks/caf" + chr(0xE9), "hooks/plain"]
    release = gu.Release("v0.2.0", {name: "#!/bin/sh\n" for name in names}, executable=frozenset(names))
    upstream = gu.make_upstream(tmp_path, [release])
    assert fs._executable_in_tree(upstream.bare, "v0.2.0", GIT) == set(names)


def _checker(root: Path, body: str) -> Path:
    (root / "tools").mkdir(parents=True, exist_ok=True)
    (root / "tools" / "check_commit_msg.py").write_text(body, encoding="utf-8")
    return root


@pytest.mark.parametrize(
    ("body", "words"),
    [
        (None, "has no tools/check_commit_msg.py"),
        ("import sys\nprint('it broke')\nsys.exit(2)\n", "exited 2: it broke"),
        ("import time\ntime.sleep(60)\n", "could not run"),
    ],
)
def test_a_message_check_that_cannot_answer_is_cannot_finish_not_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str | None, words: str
) -> None:
    monkeypatch.setattr(fs, "CHILD_TIMEOUT", 2)
    root = tmp_path / "repo"
    root.mkdir()
    if body is not None:
        _checker(root, body)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    with pytest.raises(fs.UpstreamError, match=words):
        fs._check_message(root, "chore: a message\n", scratch)


def test_an_updating_md_that_is_not_a_file_is_exit_2_not_read_as_absent(made: Callable[..., Path]) -> None:
    repo = made(_releases(b={**B_FILES, "Docs/standards/updating.md/inside.md": "a folder, not the guide\n"}))
    before = _state(repo)
    code, out = _update(repo)
    assert code == 2, out
    assert "updating.md is not a regular file" in out, out
    assert _state(repo) == before


def test_a_commit_that_fails_rolls_back_to_the_start(
    made: Callable[..., Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _full(made)
    before = _state(repo)
    _spy_git(monkeypatch, fail="commit")
    code, out = _update(repo)
    assert code == 2, out
    assert "git commit failed" in out
    assert _state(repo) == before


def test_a_finding_after_the_write_keeps_the_branch_and_says_how_to_drop_it(
    made: Callable[..., Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _full(made)
    before = _state(repo)
    real = fs.ini.write_atomic

    def spoil(dest: Path, data: bytes, **kwargs) -> None:
        real(dest, b"print('not what the lock says')\n" if dest.name == "three.py" else data, **kwargs)

    monkeypatch.setattr(fs.ini, "write_atomic", spoil)
    code, out = _update(repo)
    assert code == 2, out
    assert "[edited] tools/three.py" in out
    assert "the update is left uncommitted on template-update/v0.2.0 for inspection; to drop it:" in out
    assert gu.git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip() == "template-update/v0.2.0"
    steps = out.split("to drop it:", 1)[1].strip().splitlines()
    assert steps[0].strip() == "git switch --force main"
    assert steps[-1].strip() == "git branch -D template-update/v0.2.0"
    created = [line.strip().removeprefix("delete ") for line in steps[1:-1]]
    assert "tools/three.py" in created and "seeds/new.md" in created
    gu.git(repo, "switch", "--force", "main")
    for rel in created:  # the files first, then the folders the run made, deepest first
        (repo / rel).rmdir() if rel.endswith("/") else (repo / rel).unlink()
    gu.git(repo, "branch", "-D", "template-update/v0.2.0")
    assert _state(repo) == before


# ---- an upstream on another GitHub host
NAMED = "github.sie.example.com/acme/template"
NAMED_URL = "https://github.sie.example.com/acme/template.git"


def _named(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A repository made from 0.1.0 whose ``framework.toml`` names the upstream on another host, committed, with git
    answering only ``NAMED_URL`` from the upstream (``release_url`` is not patched)."""
    gu.isolate(monkeypatch)
    upstream = gu.make_upstream(tmp_path / "up", [_release("0.1.0", V1, DAY_A), _release("0.2.0", V2, DAY_B)])
    repo = gu.make_repository(upstream, "v0.1.0", tmp_path)
    toml = repo / "framework.toml"
    text = toml.read_text(encoding="utf-8")
    assert 'upstream = "acme/template"' in text
    toml.write_text(text.replace('upstream = "acme/template"', f'upstream = "{NAMED}"'), encoding="utf-8")
    _commit_all(repo, "chore: the template lives on another host")
    gu.route(monkeypatch, upstream, NAMED_URL, tmp_path / "empty")
    monkeypatch.setenv("GH_HOST", "elsewhere.example.com")
    return repo


def test_an_update_from_a_named_host_asks_git_for_that_host_and_commits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _named(tmp_path, monkeypatch)
    calls = _spy_git(monkeypatch)
    code, out = _update(repo)
    assert code == 0, out
    assert gu.git(repo, "log", "-1", "--format=%s", "template-update/v0.2.0").strip()
    assert gu.git(repo, "status", "--porcelain") == ""
    assert "release: https://github.sie.example.com/acme/template/releases/tag/v0.2.0" in out.splitlines()
    network = _network(calls)
    assert [call[1] for call in network] == ["ls-remote", "fetch"]
    assert all(NAMED_URL in call for call in network), network


def test_an_update_without_a_credential_for_the_named_host_is_exit_2_with_the_hint_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _named(tmp_path, monkeypatch)
    before = _state(repo)
    words = "fatal: could not read Username for 'https://github.sie.example.com': terminal prompts disabled"
    _spy_git(monkeypatch, fail="ls-remote", code=128, err=words)
    code, out = _update(repo)
    assert code == 2, out
    assert out.endswith(
        f"git ls-remote failed (128): {words}; git has no working credential for github.sie.example.com: sign in to it"
        " once with git (a credential manager stores it), or run gh auth login --hostname github.sie.example.com and"
        " gh auth setup-git --hostname github.sie.example.com, then run this again"
    )
    assert _state(repo) == before


# ---- the report
def test_the_report_is_the_message_then_each_hand_step_s_text_then_where_and_what_next(
    made: Callable[..., Path],
) -> None:
    repo = _full(made)
    code, out = _update(repo)
    assert code == 0, out
    message = gu.git(repo, "log", "-1", "--format=%B").rstrip("\n")
    lines = out.splitlines()
    assert "\n".join(lines[: len(message.splitlines())]) == message
    rest = lines[len(message.splitlines()) :]
    assert rest[0] == ""
    assert rest[1].startswith("hand steps, oldest first, by updating.md's Several releases at once")
    assert rest[4] == "## 0.2.0: the second"
    assert "2. **And this.**" in rest
    assert rest[-5:] == [
        "release: https://github.com/acme/template/releases/tag/v0.2.0",
        "branch: template-update/v0.2.0, one commit, not pushed",
        "next: sync as your CI syncs, extras included (make sync syncs the dev group only and removes them),",
        "      then make check on the branch (its commit ran no hooks); the hand steps and the kept overrides;",
        "      then push it and open one pull request with Template findings (updating.md, step 7)",
    ]


def test_the_report_names_the_seeds_it_wrote_so_a_hand_step_that_copies_one_is_seen_done() -> None:
    # A downstream finding on 0.11.0: the hand step said to copy the seeded settings, which --update had written.
    plan = fs.UpdatePlan(
        tag="v0.2.0",
        old_tag="v0.1.0",
        start="main",
        branch="template-update/v0.2.0",
        scratch=Path("."),
        upstream="acme/template",
        seeds=[".claude/settings.json"],
        message="m",
    )
    seeded = "seeded by this run, so a hand step that copies one from the render is done: .claude/settings.json"
    assert seeded in fs._report(plan)
    plan.seeds = []
    assert not any(line.startswith("seeded by this run") for line in fs._report(plan))


def test_the_report_carries_the_notes(made: Callable[..., Path]) -> None:
    repo = made(_releases())
    code, out = _update(repo)
    assert code == 0, out
    assert "note: no hand steps between v0.1.0 and v0.2.0 in updating.md" in out.splitlines()
    assert "Several releases at once" not in out  # no hand steps, so no line about them


SKIPPED = """## 0.10.1: a release in between

1. **Fetch the history first.** Before the render.
2. **Take 0.10.1**, by the steps above. `make check` brings no new finding.
3. **Taken from the old guide.** A step whose name only starts like Take.
4. **Check it.** `make check` passes, and `--upstream` says `lock is current: 0.10.1 locked`.
"""


def test_a_skipped_release_s_take_and_check_it_are_marked_as_several_releases_at_once_reads_them() -> None:
    # #229: after --update to 0.10.2, 0.10.1's Check it can never pass, so the report must not print it as a step to do
    assert fs._marked_steps(SKIPPED, "0.10.1", "0.10.2") == [
        "## 0.10.1: a release in between",
        "",
        "1. **Fetch the history first.** Before the render.",
        "2. (done: --update's render) **Take 0.10.1**, by the steps above. `make check` brings no new finding.",
        "3. **Taken from the old guide.** A step whose name only starts like Take.",
        "4. (not here: the one check against 0.10.2, below) **Check it.** `make check` passes, and `--upstream` says "
        "`lock is current: 0.10.1 locked`.",
    ]


def test_the_newest_release_s_check_it_stays_a_step_and_its_take_is_marked_done() -> None:
    newest = SKIPPED.replace("0.10.1", "0.10.2")
    marked = fs._marked_steps(newest, "0.10.2", "0.10.2")
    assert marked[3].startswith("2. (done: --update's render) **Take 0.10.2**")
    assert marked[5].startswith("4. **Check it.**")


def test_the_report_marks_every_section_it_prints(made: Callable[..., Path]) -> None:
    guide = SKIPPED.replace("0.10.1", "0.1.5") + "\n" + SKIPPED.replace("0.10.1", "0.2.0")
    repo = made(_guided(guide=guide))
    code, out = _update(repo)
    assert code == 0, out
    lines = out.splitlines()
    assert any(line.startswith("4. (not here: the one check against 0.2.0, below) **Check it.**") for line in lines)
    assert "4. **Check it.** `make check` passes, and `--upstream` says `lock is current: 0.2.0 locked`." in lines
    assert sum(line.startswith("2. (done: --update's render) **Take") for line in lines) == 2


# ---- the command line
def test_update_is_a_third_mode_beside_check_and_upstream(capsys: pytest.CaptureFixture[str]) -> None:
    for pair in (["--update", "--check"], ["--update", "--upstream"]):
        with pytest.raises(SystemExit) as caught:
            fs.main(pair)
        assert caught.value.code == 2
    capsys.readouterr()


def test_the_command_line_runs_update_and_returns_its_code(
    made: Callable[..., Path], capsys: pytest.CaptureFixture[str]
) -> None:
    repo = made([_release("0.1.0", V1, DAY_A)])
    assert fs.main(["--update", "--root", str(repo)], which=lambda tool: GIT) == 0
    assert "nothing to update" in capsys.readouterr().out
