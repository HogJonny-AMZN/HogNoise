"""
Framework: tests for tools/roster_join.py (a newcomer adds their own [[people]] row to framework.toml in one step).
Package: tests/test_roster_join

Every case runs over a ``project.json`` and a ``framework.toml`` in ``tmp_path`` and a fake runner for ``git`` and
``gh``, injected into ``main`` as ``run``: no network and no real ``gh``. The one case that runs the real ``git`` is
the identity's, so that ``GIT_COMMITTER_NAME`` and ``GIT_COMMITTER_EMAIL`` count as git counts them.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import framework_config as fc  # noqa: E402
import roster_join as rj  # noqa: E402

OWNER = fc.Person("olive", "Olive Owner", "owner", ("olive@example.org",))
MOON = fc.Person("PlanarKnight", "Moon Mulligan", "contributor", ("moon@example.org",))
ADA = fc.Person("ada", "Ada Lovelace", "contributor", ("ada@example.com",))
ADA_IDENT = "Ada Lovelace <ada@example.com> 1700000000 +0000\n"
ORIGIN = "https://github.com/acme/widget.git\n"
CHECKS = "[checks]\nhandoff_max_lines = 150\n"
DUMP_PERSON = fc.dump_person  # the real one, for a patch that wraps it (rj.fc is this same module)


def _head() -> str:
    modules = "\n".join(f'{m} = "{"on" if m == "core" else "off"}"' for m in fc.MODULES if m not in fc.OPTIONAL_MODULES)
    return f'[framework]\ntemplate_version = "0.11.2"\n\n[modules]\n{modules}\n\n[harnesses]\nenabled = []\n'


def roster_then_checks(*people: fc.Person) -> str:
    """The people, then a comment and ``[checks]`` after them: a new row goes between."""
    return _head() + "".join("\n" + fc.dump_person(p) for p in people) + "\n# the checks\n" + CHECKS


def checks_then_roster(*people: fc.Person) -> str:
    """The people last in the file: a new row goes at the end."""
    return _head() + "\n" + CHECKS + "".join("\n" + fc.dump_person(p) for p in people)


def _project(signoff: bool = True) -> fc.ProjectConfig:
    return fc.ProjectConfig(
        name="Widget",
        slug="widget",
        owner=fc.Owner(name="Olive Owner", email="olive@example.org", login="olive"),
        default_branch="main",
        signoff=signoff,
        hygiene=(),
    )


def repo(tmp_path: Path, framework: str | None, project: fc.ProjectConfig | None = None) -> Path:
    """``tmp_path`` with ``project.json`` and, unless ``None``, ``framework.toml`` written byte for byte."""
    (tmp_path / "project.json").write_text(fc.dump_project(project or _project()), encoding="utf-8")
    if framework is not None:
        (tmp_path / "framework.toml").write_bytes(framework.encode("utf-8"))
    return tmp_path


class Runner:
    """A fake ``subprocess.run`` for ``git var``, ``git remote get-url`` and ``gh api user``.

    An answer is a string (exit 0 with that output), a ``(returncode, output)`` pair, or an exception to raise.
    """

    def __init__(self, ident: object = ADA_IDENT, origin: object = ORIGIN, gh: object = "ada\n") -> None:
        self.answers = {"var": ident, "remote": origin, "gh": gh}
        self.calls: list[tuple[list[str], dict]] = []

    def __call__(self, argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        self.calls.append((list(argv), kwargs))
        answer = self.answers["gh" if argv[0] == "gh" else argv[3]]
        if isinstance(answer, BaseException):
            raise answer
        code, out = answer if isinstance(answer, tuple) else (0, answer)
        return subprocess.CompletedProcess(argv, code, out, "fatal: no" if code else "")

    def ran(self, program: str) -> list[list[str]]:
        return [argv for argv, _ in self.calls if argv[0] == program]


def join(root: Path, capsys, runner: Runner | None = None, *argv: str) -> tuple[int, str, str]:
    code = rj.main(["--root", str(root), *argv], run=runner or Runner())
    out, err = capsys.readouterr()
    return code, out, err


def leftovers(root: Path) -> list[str]:
    return sorted(p.name for p in root.iterdir() if p.name not in ("project.json", "framework.toml"))


# ---- the table: what it does
def test_a_new_person_gets_a_contributor_row_and_the_next_step(tmp_path: Path, capsys) -> None:
    root = repo(tmp_path, roster_then_checks(OWNER, MOON))
    code, out, err = join(root, capsys)
    assert code == 0, err
    assert (root / "framework.toml").read_bytes().decode("utf-8") == roster_then_checks(OWNER, MOON, ADA)
    assert "join: added @ada (Ada Lovelace <ada@example.com>, contributor) to framework.toml" in out
    assert f"next: in {root}, run git add framework.toml, then commit again" in out
    # prose, not a command to paste: a quoted path still expands a $ in a shell
    assert '"' not in next(line for line in out.splitlines() if line.startswith("next:"))
    assert leftovers(root) == []


def test_an_identity_already_on_the_roster_changes_nothing(tmp_path: Path, capsys) -> None:
    before = roster_then_checks(OWNER, ADA)
    root = repo(tmp_path, before)
    code, out, _ = join(root, capsys)
    assert code == 0
    assert "join: Ada Lovelace <ada@example.com> is already on the roster (@ada)" in out
    assert (root / "framework.toml").read_bytes().decode("utf-8") == before


@pytest.mark.parametrize(
    ("gh", "ident"),
    [
        ("ADA\n", ADA_IDENT),  # a login that differs only in case
        ("ada\n", "Ada Lovelace <ADA@Example.COM> 1700000000 +0000\n"),  # an address that differs only in case
    ],
)
def test_login_and_address_compare_without_regard_to_case(tmp_path: Path, capsys, gh: str, ident: str) -> None:
    before = roster_then_checks(OWNER, ADA)
    root = repo(tmp_path, before)
    code, out, _ = join(root, capsys, Runner(ident=ident, gh=gh))
    assert code == 0 and "is already on the roster (@ada)" in out
    assert (root / "framework.toml").read_bytes().decode("utf-8") == before


def test_the_owner_with_no_row_is_told_to_add_their_own_by_hand(tmp_path: Path, capsys) -> None:
    boss = fc.Person("boss", "Bea Boss", "owner", ("bea@example.org",))
    before = roster_then_checks(boss)
    root = repo(tmp_path, before)
    runner = Runner(ident="Olive Owner <olive@example.org> 1700000000 +0000\n", gh="olive\n")
    code, _, err = join(root, capsys, runner)
    assert code == 1 and 'role = "owner"' in err and "by hand" in err
    assert (root / "framework.toml").read_bytes().decode("utf-8") == before


def test_a_row_with_that_login_and_name_gains_the_address(tmp_path: Path, capsys) -> None:
    old = replace(ADA, emails=("ada@old.example.com",))
    root = repo(tmp_path, roster_then_checks(OWNER, old, MOON))
    code, out, err = join(root, capsys, Runner(gh="Ada\n"))
    assert code == 0, err
    want = roster_then_checks(OWNER, replace(ADA, emails=("ada@old.example.com", "ada@example.com")), MOON)
    assert (root / "framework.toml").read_bytes().decode("utf-8") == want
    assert "ada@example.com" in out and "@ada" in out and "comment" not in out


def test_a_row_with_no_emails_gains_its_first(tmp_path: Path, capsys) -> None:
    root = repo(tmp_path, roster_then_checks(OWNER, replace(ADA, emails=())))
    code, _, err = join(root, capsys)
    assert code == 0, err
    assert (root / "framework.toml").read_bytes().decode("utf-8") == roster_then_checks(OWNER, ADA)


def test_a_multi_line_row_with_a_comment_is_rewritten_and_the_loss_is_said(tmp_path: Path, capsys) -> None:
    row = (
        '[[people]]\nlogin = "ada"\n# her first machine\nname = "Ada Lovelace"\nrole = "contributor"\n'
        'emails = [\n  "ada@old.example.com",\n]\n'
    )
    text = _head() + "\n" + fc.dump_person(OWNER) + "\n" + row + "\n# the checks\n" + CHECKS
    root = repo(tmp_path, text)
    code, out, err = join(root, capsys)
    assert code == 0, err
    new = fc.dump_person(replace(ADA, emails=("ada@old.example.com", "ada@example.com")))
    assert (root / "framework.toml").read_bytes().decode("utf-8") == text.replace(row, new)
    assert "comment" in out


def test_a_row_with_that_login_and_another_name_is_left_and_the_difference_named(tmp_path: Path, capsys) -> None:
    before = roster_then_checks(OWNER, replace(ADA, name="Ada King", emails=("ada@old.example.com",)))
    root = repo(tmp_path, before)
    code, _, err = join(root, capsys)
    assert code == 1
    assert 'the roster names @ada "Ada King", git names you "Ada Lovelace": change one so they match' in err
    assert (root / "framework.toml").read_bytes().decode("utf-8") == before


@pytest.mark.parametrize("name", ["Moon Mulligan", "Ada Lovelace"])  # another name, and the same name on another row
def test_an_address_on_another_logins_row_is_left_and_that_login_named(tmp_path: Path, capsys, name: str) -> None:
    other = fc.Person("lovelace", name, "contributor", ("ada@example.com",))
    before = roster_then_checks(OWNER, other)
    root = repo(tmp_path, before)
    code, _, err = join(root, capsys)
    assert code == 1 and "@lovelace" in err
    assert (root / "framework.toml").read_bytes().decode("utf-8") == before


# ---- where the row goes, and the file's line ending
@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_a_new_row_goes_after_the_last_person_and_before_the_next_table(tmp_path: Path, capsys, newline: str) -> None:
    root = repo(tmp_path, roster_then_checks(OWNER, MOON).replace("\n", newline))
    assert join(root, capsys)[0] == 0
    want = roster_then_checks(OWNER, MOON, ADA).replace("\n", newline)
    assert (root / "framework.toml").read_bytes().decode("utf-8") == want


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_a_new_row_goes_at_the_end_of_a_file_with_no_final_newline(tmp_path: Path, capsys, newline: str) -> None:
    root = repo(tmp_path, checks_then_roster(OWNER, MOON).rstrip("\n").replace("\n", newline))
    assert join(root, capsys)[0] == 0
    want = checks_then_roster(OWNER, MOON, ADA).replace("\n", newline)
    assert (root / "framework.toml").read_bytes().decode("utf-8") == want


def test_a_hostile_name_is_written_and_read_back_exactly(tmp_path: Path, capsys) -> None:
    name = 'Ñandú "Q" O\'Brien \\ the-1st'
    root = repo(tmp_path, roster_then_checks(OWNER))
    code, _, err = join(root, capsys, Runner(ident=f"{name} <ada@example.com> 1700000000 +0000\n"))
    assert code == 0, err
    people = fc.load_framework(root / "framework.toml").people
    assert people[-1] == fc.Person("ada", name, "contributor", ("ada@example.com",))


# ---- its inputs, each refused (exit 2, nothing written)
def test_no_project_json_is_refused(tmp_path: Path, capsys) -> None:
    (tmp_path / "framework.toml").write_text(roster_then_checks(OWNER), encoding="utf-8")
    code, _, err = join(tmp_path, capsys)
    assert code == 2 and "project.json" in err


@pytest.mark.parametrize("bad", ["{", '{"name": "x"}'])
def test_an_invalid_project_json_is_refused(tmp_path: Path, capsys, bad: str) -> None:
    before = roster_then_checks(OWNER)
    root = repo(tmp_path, before)
    (root / "project.json").write_text(bad, encoding="utf-8")
    code, _, err = join(root, capsys)
    assert code == 2 and "project.json" in err
    assert (root / "framework.toml").read_bytes().decode("utf-8") == before


def test_no_framework_toml_is_refused(tmp_path: Path, capsys) -> None:
    root = repo(tmp_path, None)
    code, _, err = join(root, capsys)
    assert code == 2 and "framework.toml" in err
    assert not (root / "framework.toml").exists()


@pytest.mark.parametrize("bad", ["[[[", roster_then_checks(OWNER).replace('role = "owner"', 'role = "chief"')])
def test_an_invalid_framework_toml_is_refused(tmp_path: Path, capsys, bad: str) -> None:
    root = repo(tmp_path, bad)
    code, _, err = join(root, capsys)
    assert code == 2 and "framework.toml" in err
    assert (root / "framework.toml").read_bytes().decode("utf-8") == bad


def test_an_unreadable_framework_toml_is_refused_not_taken_for_missing(tmp_path: Path, capsys) -> None:
    root = repo(tmp_path, None)
    (root / "framework.toml").mkdir()
    code, _, err = join(root, capsys)
    assert code == 2 and "framework.toml" in err


def test_a_repository_with_no_roster_is_refused_and_its_owner_named(tmp_path: Path, capsys) -> None:
    before = checks_then_roster()
    root = repo(tmp_path, before)
    code, _, err = join(root, capsys)
    assert code == 2 and "no roster yet" in err and "owner adds the first row" in err
    assert (root / "framework.toml").read_bytes().decode("utf-8") == before


def test_a_framework_toml_that_is_a_link_is_refused(tmp_path: Path, capsys) -> None:
    real = tmp_path / "real.toml"
    real.write_text(roster_then_checks(OWNER), encoding="utf-8")
    (tmp_path / "repo").mkdir()
    root = repo(tmp_path / "repo", None)
    try:
        os.symlink(real, root / "framework.toml")
    except OSError as e:
        pytest.skip(f"cannot make a symlink here: {e}")
    code, _, err = join(root, capsys)
    assert code == 2 and "link" in err
    assert (root / "framework.toml").is_symlink()
    assert real.read_text(encoding="utf-8") == roster_then_checks(OWNER)


def test_an_inline_array_roster_is_refused_and_the_row_printed(tmp_path: Path, capsys) -> None:
    inline = 'people = [{login = "olive", name = "Olive Owner", role = "owner", emails = ["olive@example.org"]}]\n'
    before = inline + _head() + "\n" + CHECKS
    root = repo(tmp_path, before)
    assert fc.load_framework(root / "framework.toml").people == (OWNER,)
    code, out, err = join(root, capsys)
    assert code == 2 and "inline array" in err and "[[people]]" in err
    assert fc.dump_person(ADA) in out + err
    assert (root / "framework.toml").read_bytes().decode("utf-8") == before


@pytest.mark.parametrize("ident", [(128, ""), (0, "Ada Lovelace 1700000000 +0000\n"), (0, "")])
def test_no_git_identity_names_the_commands_that_set_it(tmp_path: Path, capsys, ident: tuple[int, str]) -> None:
    root = repo(tmp_path, roster_then_checks(OWNER))
    code, _, err = join(root, capsys, Runner(ident=ident))
    assert code == 2 and "git config user.name" in err and "user.email" in err


@pytest.mark.parametrize(
    "failure", [FileNotFoundError("git"), subprocess.TimeoutExpired(["git"], 30), PermissionError("git")]
)
def test_git_that_cannot_run_is_said(tmp_path: Path, capsys, failure: BaseException) -> None:
    before = roster_then_checks(OWNER)
    root = repo(tmp_path, before)
    code, _, err = join(root, capsys, Runner(ident=failure))
    assert code == 2 and "cannot run git" in err
    assert (root / "framework.toml").read_bytes().decode("utf-8") == before


def test_git_runs_with_no_input_a_timeout_and_utf8(tmp_path: Path, capsys) -> None:
    root = repo(tmp_path, roster_then_checks(OWNER))
    runner = Runner()
    assert join(root, capsys, runner)[0] == 0
    argv, kwargs = runner.calls[0]
    assert argv == ["git", "-C", str(root), "var", "GIT_COMMITTER_IDENT"]
    assert kwargs["stdin"] == subprocess.DEVNULL and kwargs["timeout"] > 0
    assert kwargs["encoding"] == "utf-8" and kwargs["errors"] == "replace"


@pytest.mark.parametrize(
    "gh",
    [
        FileNotFoundError("gh"),
        (1, ""),
        subprocess.TimeoutExpired(["gh"], 30),
        "ada\nbob\n",
        "-x\n",
        "\n",
    ],
)
def test_gh_that_gives_no_one_login_asks_for_login(tmp_path: Path, capsys, gh: object) -> None:
    before = roster_then_checks(OWNER)
    root = repo(tmp_path, before)
    code, _, err = join(root, capsys, Runner(gh=gh))
    assert code == 2 and "--login=<your login>" in err
    assert (root / "framework.toml").read_bytes().decode("utf-8") == before


def test_gh_is_asked_with_no_input_no_prompt_and_a_timeout(tmp_path: Path, capsys, monkeypatch) -> None:
    root = repo(tmp_path, roster_then_checks(OWNER))
    monkeypatch.setenv("GH_HOST", "ghe.example.com")  # gh's default host; --hostname outranks it
    runner = Runner()
    assert join(root, capsys, runner)[0] == 0
    (argv,) = runner.ran("gh")
    assert argv == ["gh", "api", "user", "--jq", ".login", "--hostname", "github.com"]
    kwargs = next(k for a, k in runner.calls if a[0] == "gh")
    assert kwargs["stdin"] == subprocess.DEVNULL and kwargs["timeout"] > 0
    assert kwargs["env"]["GH_PROMPT_DISABLED"] == "1"


@pytest.mark.parametrize(
    "origin",
    [
        "git@ghe.example.com:acme/widget.git\n",
        "https://ghe.example.com/acme/widget.git\n",
        "ssh://git@ghe.example.com:2222/acme/widget.git\n",
    ],
)
def test_an_origin_on_another_host_asks_gh_of_that_host(tmp_path: Path, capsys, origin: str) -> None:
    root = repo(tmp_path, roster_then_checks(OWNER))
    runner = Runner(origin=origin)
    assert join(root, capsys, runner)[0] == 0
    (argv,) = runner.ran("gh")
    assert argv == ["gh", "api", "user", "--jq", ".login", "--hostname", "ghe.example.com"]
    assert ["git", "-C", str(root), "remote", "get-url", "origin"] in runner.ran("git")


@pytest.mark.parametrize("origin", [(2, ""), "/srv/git/widget.git\n", "C:\\repos\\widget\n", "\n"])
def test_no_origin_host_asks_for_login_and_never_calls_gh(tmp_path: Path, capsys, origin: object) -> None:
    root = repo(tmp_path, roster_then_checks(OWNER))
    runner = Runner(origin=origin)
    code, _, err = join(root, capsys, runner)
    assert code == 2 and "--login=<your login>" in err
    assert runner.ran("gh") == []


def test_login_given_asks_neither_origin_nor_gh(tmp_path: Path, capsys) -> None:
    root = repo(tmp_path, roster_then_checks(OWNER))
    runner = Runner()
    assert join(root, capsys, runner, "--login=ada")[0] == 0
    assert runner.ran("gh") == [] and all(a[3] == "var" for a in runner.ran("git"))


@pytest.mark.parametrize("login", ["-x", "a--b", "ada lovelace", "x" * 40, ""])
def test_a_login_the_roster_refuses_is_refused(tmp_path: Path, capsys, login: str) -> None:
    before = roster_then_checks(OWNER)
    root = repo(tmp_path, before)
    code, _, err = join(root, capsys, Runner(), f"--login={login}")
    assert code == 2 and "login" in err
    assert (root / "framework.toml").read_bytes().decode("utf-8") == before


@pytest.mark.parametrize(
    "ident",
    [
        "Ada Lovelace <ada@localhost> 1700000000 +0000\n",  # an address the roster refuses
        "Ada\u2028Lovelace <ada@example.com> 1700000000 +0000\n",  # a line separator: no sign-off line carries it
        "Ada\x07Lovelace <ada@example.com> 1700000000 +0000\n",  # a control character
    ],
)
def test_an_identity_the_roster_or_the_hook_refuses_is_refused(tmp_path: Path, capsys, ident: str) -> None:
    before = roster_then_checks(OWNER)
    root = repo(tmp_path, before)
    code, _, err = join(root, capsys, Runner(ident=ident))
    assert code == 2, err
    assert (root / "framework.toml").read_bytes().decode("utf-8") == before


# ---- the check before the replace
def test_negative_control_a_row_the_check_refuses_is_never_written(tmp_path: Path, capsys, monkeypatch) -> None:
    before = roster_then_checks(OWNER, MOON)
    root = repo(tmp_path, before)
    monkeypatch.setattr(rj.fc, "dump_person", lambda p: DUMP_PERSON(replace(p, name="Someone Else")))
    code, _, err = join(root, capsys)
    assert code == 2 and "not an accepted identity" in err
    assert (root / "framework.toml").read_bytes().decode("utf-8") == before
    assert leftovers(root) == []


def test_a_candidate_that_does_not_load_is_never_written(tmp_path: Path, capsys, monkeypatch) -> None:
    before = roster_then_checks(OWNER, MOON)
    root = repo(tmp_path, before)
    monkeypatch.setattr(rj.fc, "dump_person", lambda p: '[[people]]\nlogin = "ada"\n')
    code, _, err = join(root, capsys)
    assert code == 2 and "framework.toml" in err
    assert (root / "framework.toml").read_bytes().decode("utf-8") == before
    assert leftovers(root) == []


@pytest.mark.parametrize("signoff", [True, False])
def test_the_check_matches_the_identity_whatever_signoff_says(
    tmp_path: Path, capsys, monkeypatch, signoff: bool
) -> None:
    root = repo(tmp_path, roster_then_checks(OWNER), _project(signoff))
    code, _, err = join(root, capsys)
    assert code == 0, err
    assert fc.load_framework(root / "framework.toml").people[-1] == ADA
    before = (root / "framework.toml").read_bytes()
    monkeypatch.setattr(rj.fc, "dump_person", lambda p: DUMP_PERSON(replace(p, emails=("x@example.org",))))
    code, _, _ = join(root, capsys, Runner(ident="Bo Bee <bo@example.com> 1700000000 +0000\n"), "--login=bo")
    assert code == 2  # the control: with signoff false a check that skipped the sign-off would have written it
    assert (root / "framework.toml").read_bytes() == before


def test_a_replace_that_fails_leaves_the_file_and_no_temporary(tmp_path: Path, capsys, monkeypatch) -> None:
    before = roster_then_checks(OWNER)
    root = repo(tmp_path, before)

    def refuse(src: object, dst: object) -> None:
        raise PermissionError("the file is locked")

    monkeypatch.setattr(rj.os, "replace", refuse)
    code, _, err = join(root, capsys)
    assert code == 2 and "locked" in err
    assert (root / "framework.toml").read_bytes().decode("utf-8") == before
    assert leftovers(root) == []


def test_a_temporary_file_that_cannot_be_made_leaves_the_file(tmp_path: Path, capsys, monkeypatch) -> None:
    before = roster_then_checks(OWNER)
    root = repo(tmp_path, before)

    def refuse(**kwargs: object) -> tuple[int, str]:
        raise PermissionError("the folder is read-only")

    monkeypatch.setattr(rj.tempfile, "mkstemp", refuse)
    code, _, err = join(root, capsys)
    assert code == 2 and "read-only" in err
    assert (root / "framework.toml").read_bytes().decode("utf-8") == before


def test_a_change_made_meanwhile_is_kept_and_nothing_written(tmp_path: Path, capsys, monkeypatch) -> None:
    root = repo(tmp_path, roster_then_checks(OWNER))
    target = root / "framework.toml"
    real = rj.ccm.check_message

    def meanwhile(*args: object, **kwargs: object) -> list[str]:
        with target.open("ab") as f:
            f.write(b"# another edit\n")
        return real(*args, **kwargs)

    monkeypatch.setattr(rj.ccm, "check_message", meanwhile)
    code, _, err = join(root, capsys)
    assert code == 2 and "framework.toml changed while this ran; run it again" in err
    assert target.read_bytes().decode("utf-8") == roster_then_checks(OWNER) + "# another edit\n"
    assert leftovers(root) == []


def test_two_joins_interleaved_at_the_replace_lose_a_row_a_stated_limit(tmp_path: Path, capsys, monkeypatch) -> None:
    """The comparison catches an edit made before it, not a join that replaces the file between it and the replace:
    both exit 0 and the second row is lost. A known limit, stated in the module and the spec, not a lock (#279)."""
    root = repo(tmp_path, roster_then_checks(OWNER))
    real = rj.os.replace
    codes: dict[str, int] = {}

    def replace_after_another_join(src: str, dst: str) -> None:
        if "bob" not in codes:  # join B runs to the end inside join A's gap, with the real replace
            monkeypatch.setattr(rj.os, "replace", real)
            bob = Runner(ident="Bob Builder <bob@example.com> 1700000000 +0000\n", gh="bob\n")
            codes["bob"] = rj.main(["--root", str(root)], run=bob)
        real(src, dst)

    monkeypatch.setattr(rj.os, "replace", replace_after_another_join)
    codes["ada"] = rj.main(["--root", str(root)], run=Runner())
    capsys.readouterr()
    assert codes == {"bob": 0, "ada": 0}
    logins = [p.login for p in fc.load_framework(root / "framework.toml").people]
    assert logins == ["olive", "ada"]  # bob's row was written, then overwritten
    assert leftovers(root) == []


@pytest.mark.parametrize("header", ['[["people"]]', "[['people']]", '[[ "people" ]]'])
def test_a_quoted_people_header_is_a_roster_table(tmp_path: Path, capsys, header: str) -> None:
    root = repo(tmp_path, roster_then_checks(OWNER, MOON).replace("[[people]]", header))
    code, _, err = join(root, capsys)
    assert code == 0, err
    assert fc.load_framework(root / "framework.toml").people == (OWNER, MOON, ADA)


@pytest.mark.skipif(os.name != "posix", reason="POSIX file modes")
def test_the_file_keeps_its_permissions(tmp_path: Path, capsys) -> None:
    root = repo(tmp_path, roster_then_checks(OWNER))
    target = root / "framework.toml"
    target.chmod(0o644)
    assert join(root, capsys)[0] == 0
    assert stat.S_IMODE(target.stat().st_mode) == 0o644


def test_the_roster_and_the_bytes_compared_come_from_one_read(tmp_path: Path, capsys, monkeypatch) -> None:
    """An edit landing just after the first read of framework.toml, however it is read, is caught by the comparison."""
    root = repo(tmp_path, roster_then_checks(OWNER))
    target = root / "framework.toml"
    edited = roster_then_checks(OWNER, MOON)
    reads = {"done": False}

    def after_first_read(real):
        def read(self, *args, **kwargs):
            out = real(self, *args, **kwargs)
            if self == target and not reads["done"]:
                reads["done"] = True
                target.write_bytes(edited.encode("utf-8"))
            return out

        return read

    monkeypatch.setattr(Path, "read_bytes", after_first_read(Path.read_bytes))
    monkeypatch.setattr(Path, "read_text", after_first_read(Path.read_text))
    code, _, err = join(root, capsys)
    assert code == 2 and "framework.toml changed while this ran; run it again" in err
    assert target.read_bytes().decode("utf-8") == edited
    assert leftovers(root) == []


# ---- the identity is the one git commit -s writes
@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
@pytest.mark.parametrize("configured", [True, False])
def test_git_committer_name_and_email_count_as_git_counts_them(
    tmp_path: Path, capsys, monkeypatch, configured: bool
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    for key in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "EMAIL", "GIT_DIR", "GIT_WORK_TREE"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(home / "gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("HOME", str(home))
    (tmp_path / "repo").mkdir()
    root = repo(tmp_path / "repo", None)
    (root / "framework.toml").write_text(roster_then_checks(OWNER), encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(root)], check=True, stdin=subprocess.DEVNULL)
    if configured:
        subprocess.run(["git", "-C", str(root), "config", "user.name", "Someone Else"], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.email", "else@example.org"], check=True)
    monkeypatch.setenv("GIT_COMMITTER_NAME", "Ada Lovelace")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "ada@example.com")
    code = rj.main(["--root", str(root), "--login=ada"])
    out, err = capsys.readouterr()
    assert code == 0, err
    assert fc.load_framework(root / "framework.toml").people[-1] == ADA
