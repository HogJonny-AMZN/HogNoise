"""
Framework: tests for tools/check_hygiene.py (no project identifier in any file outside the allowlist).
Package: tests/test_check_hygiene

Acceptance 4: every rule can fail. Each test starts from a repository the check passes, breaks exactly one rule and
requires the finding; the same repository unbroken passes.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import check_hygiene as ch  # noqa: E402
import framework_config as fc  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="the check reads the file list from git")

OWNER = {"name": "Ada Example", "email": "ada@example.org"}


def project_json(identifiers: list[str]) -> str:
    return json.dumps(
        {
            "name": "Example",
            "slug": "example",
            "owner": OWNER,
            "default_branch": "main",
            "signoff": True,
            "hygiene": identifiers,
        },
        indent=2,
    )


def make_repo(
    tmp: Path, files: dict[str, str | bytes], identifiers: list[str], *, allow: str = "", git: bool = True
) -> Path:
    """A repository with ``project.json`` listing ``identifiers``, the given files and, optionally, a framework.toml."""
    files = {"project.json": project_json(identifiers), **files}
    for rel, content in files.items():
        path = tmp / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8", newline="\n")
    if allow:
        (tmp / "framework.toml").write_text(framework_toml(allow), encoding="utf-8", newline="\n")
    if git:
        subprocess.run(["git", "init", "-q"], cwd=tmp, check=True)
        subprocess.run(["git", "add", "-A"], cwd=tmp, check=True)
    return tmp


def framework_toml(extra: str) -> str:
    base = fc.dump_framework(
        fc.parse_framework(
            {
                "framework": {"template_version": "0.1.0"},
                "modules": {
                    "core": "on",
                    "journal": "on",
                    "ux": "planned",
                    "python-uv": "on",
                    "tasking": "planned",
                    "hygiene": "on",
                    "graph": "planned",
                    "harness-adapters": "planned",
                    "specimens": "planned",
                    "lanes": "off",
                    "branch-ownership": "off",
                    "devblog": "off",
                },
                "harnesses": {"enabled": []},
                "checks": {"handoff_max_lines": 150},
            }
        )
    )
    return base + extra


def allow_table(path: str, reason: str = "a vendored file") -> str:
    return f'\n[[hygiene_allow]]\npath = "{path}"\nreason = "{reason}"\n'


def run(root: Path, capsys, *args: str) -> tuple[int, str, str]:
    code = ch.main([*args, str(root)])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_a_repository_without_identifiers_passes_and_says_so(tmp_path: Path, capsys) -> None:
    root = make_repo(tmp_path, {"README.md": "anything at all\n"}, [])
    code, out, _ = run(root, capsys)
    assert code == 0 and "no identifiers configured" in out


def test_a_clean_repository_passes(tmp_path: Path, capsys) -> None:
    root = make_repo(tmp_path, {"README.md": "nothing to see\n", "src/a.py": "x = 1\n"}, ["zqsample-internal"])
    code, out, _ = run(root, capsys)
    assert code == 0 and "clean (1 identifier(s)" in out


def test_an_identifier_in_a_file_is_a_finding_with_its_line(tmp_path: Path, capsys) -> None:
    root = make_repo(
        tmp_path, {"docs/a.md": "line one\nthe Zqsample-Internal portal\nline three\n"}, ["zqsample-internal"]
    )
    code, out, _ = run(root, capsys)
    assert code == 1
    assert "[hygiene] docs/a.md:2: holds an identifier" in out and "1 finding(s)" in out
    assert "portal" not in out and "Zqsample" not in out  # the report never copies the line into a CI log


@pytest.mark.parametrize(
    "text", ["ZQSAMPLE-INTERNAL", "zqsample-internal", "xzqsample-internalx", "see:zqsample-internal."]
)
def test_the_match_is_a_case_insensitive_substring(tmp_path: Path, capsys, text: str) -> None:
    root = make_repo(tmp_path, {"a.txt": text + "\n"}, ["zqsample-internal"])
    assert run(root, capsys)[0] == 1, text


def test_every_identifier_in_the_list_counts_and_each_line_is_reported(tmp_path: Path, capsys) -> None:
    root = make_repo(tmp_path, {"a.txt": "one\nzqone here\nzqtwo here\nzqone zqtwo\n"}, ["zqone", "zqtwo"])
    code, out, _ = run(root, capsys)
    assert code == 1 and out.count("[hygiene] a.txt:") == 3


def test_regex_characters_in_an_identifier_are_literal(tmp_path: Path, capsys) -> None:
    root = make_repo(tmp_path, {"a.txt": "version a_b here\nC++ and a.b\n"}, ["a.b", "C++"])
    code, out, _ = run(root, capsys)
    assert code == 1 and "a.txt:2" in out and "a.txt:1" not in out  # "a_b" is not "a.b"; the dot is not a wildcard


def test_a_file_name_that_contains_an_identifier_is_a_finding(tmp_path: Path, capsys) -> None:
    root = make_repo(tmp_path, {"notes/zqsample-internal-plan.md": "clean text\n"}, ["zqsample-internal"])
    code, out, _ = run(root, capsys)
    assert code == 1 and "[hygiene] notes/zqsample-internal-plan.md: the file name contains an identifier" in out


def test_crlf_files_report_the_right_line(tmp_path: Path, capsys) -> None:
    root = make_repo(tmp_path, {"a.txt": b"one\r\ntwo\r\nzqsecret three\r\n"}, ["zqsecret"])
    assert "a.txt:3:" in run(root, capsys)[1]


def test_project_json_is_allowed_because_it_holds_the_identifiers(tmp_path: Path, capsys) -> None:
    root = make_repo(tmp_path, {}, ["zqsample-internal"])
    code, out, _ = run(root, capsys)
    assert code == 0 and "[allowed] project.json: holds the identifiers" in out


# ---- the allowlist
def test_an_allowed_file_passes_with_its_reason_in_the_report(tmp_path: Path, capsys) -> None:
    files = {"vendor/old.txt": "zqsample-internal was here\n"}
    root = make_repo(
        tmp_path, files, ["zqsample-internal"], allow=allow_table("vendor/old.txt", "a frozen vendored record")
    )
    code, out, _ = run(root, capsys)
    assert code == 0 and "[allowed] vendor/old.txt: a frozen vendored record" in out


def test_a_directory_is_allowed_with_everything_below_it_and_not_a_sibling_with_the_same_prefix(
    tmp_path: Path, capsys
) -> None:
    files = {"vendor/deep/a.txt": "zqsample-internal\n", "vendor2/b.txt": "zqsample-internal\n"}
    root = make_repo(tmp_path, files, ["zqsample-internal"], allow=allow_table("vendor", "vendored"))
    code, out, _ = run(root, capsys)
    assert code == 1 and "vendor2/b.txt:1" in out and "vendor/deep" not in out.split("[allowed]")[0]


def test_the_allowlist_only_shrinks_an_entry_that_carries_nothing_is_a_finding(tmp_path: Path, capsys) -> None:
    files = {"vendor/clean.txt": "nothing here\n"}
    root = make_repo(tmp_path, files, ["zqsample-internal"], allow=allow_table("vendor/clean.txt"))
    code, out, _ = run(root, capsys)
    assert code == 1 and "vendor/clean.txt: is in hygiene_allow but carries no identifier" in out


def test_an_entry_for_a_path_that_does_not_exist_is_stale_too(tmp_path: Path, capsys) -> None:
    root = make_repo(tmp_path, {"a.txt": "ok\n"}, ["zqsample-internal"], allow=allow_table("gone/file.txt"))
    assert run(root, capsys)[0] == 1


def test_an_allowlist_entry_cannot_name_a_file_by_an_identifier_without_leaking_it(tmp_path: Path, capsys) -> None:
    """The entry is in framework.toml, which is scanned like any file: rename the file rather than list its name."""
    root = make_repo(
        tmp_path, {"zqsample-internal.md": "clean\n"}, ["zqsample-internal"], allow=allow_table("zqsample-internal.md")
    )
    code, out, _ = run(root, capsys)
    assert code == 1 and "[hygiene] framework.toml:" in out and "[allowed] zqsample-internal.md" in out


# ---- what is scanned
def test_a_gitignored_file_is_not_scanned_and_an_untracked_one_is(tmp_path: Path, capsys) -> None:
    files = {".gitignore": "scratch.txt\n", "scratch.txt": "zqsample-internal\n"}
    root = make_repo(tmp_path, files, ["zqsample-internal"])
    assert run(root, capsys)[0] == 0
    (root / "new.txt").write_text(
        "zqsample-internal\n", encoding="utf-8"
    )  # untracked, not ignored: it would be committed
    assert run(root, capsys)[0] == 1


def test_without_git_the_walk_skips_caches_and_run_records(tmp_path: Path, capsys) -> None:
    files = {
        "logs/run.log": "zqsample-internal\n",
        ".venv/lib/x.py": "zqsample-internal\n",
        "node_modules/p/i.js": "zqsample-internal\n",
        "a.txt": "ok\n",
    }
    root = make_repo(tmp_path, files, ["zqsample-internal"], git=False)
    assert run(root, capsys)[0] == 0
    (root / "b.txt").write_text("zqsample-internal\n", encoding="utf-8")
    assert run(root, capsys)[0] == 1


def test_a_binary_file_is_searched_and_a_large_one_is_a_finding(tmp_path: Path, capsys, monkeypatch) -> None:
    root = make_repo(tmp_path, {"img.bin": b"\0\0\x89PNG zqsample-internal \0"}, ["zqsample-internal"])
    code, out, _ = run(root, capsys)
    assert code == 1 and "img.bin:1: holds an identifier (read as latin-1)" in out
    (root / "img.bin").write_bytes(b"\0\0\x89PNG nothing \0")
    assert run(root, capsys)[0] == 0
    monkeypatch.setattr(ch, "MAX_BYTES", 2000)
    (root / "big.txt").write_text("x" * 5000, encoding="utf-8")
    code, out, _ = run(root, capsys)
    assert code == 1 and "big.txt: not scanned: larger than" in out


LFS = "*.bin filter=lfs diff=lfs merge=lfs -text"


def test_an_lfs_tracked_file_is_not_read_however_large_but_the_same_file_outside_lfs_is_a_finding(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    monkeypatch.setattr(ch, "MAX_BYTES", 2000)
    big = b"x" * 5000
    root = make_repo(tmp_path, {".gitattributes": LFS, "tex.bin": big, "tex.dat": big}, ["zqsample-internal"])
    code, out, _ = run(root, capsys)
    assert code == 1 and "tex.dat: not scanned: larger than" in out and "tex.bin" not in out  # the control: not LFS


def test_an_lfs_file_with_an_identifier_in_its_name_is_still_a_finding(tmp_path: Path, capsys) -> None:
    root = make_repo(tmp_path, {".gitattributes": LFS, "zqsample-internal.bin": b"x"}, ["zqsample-internal"])
    code, out, _ = run(root, capsys)
    assert code == 1 and "zqsample-internal.bin: the file name contains an identifier" in out


def test_without_git_nothing_is_skipped_as_lfs(tmp_path: Path, capsys, monkeypatch) -> None:
    monkeypatch.setattr(ch, "MAX_BYTES", 2000)
    root = make_repo(tmp_path, {".gitattributes": LFS, "tex.bin": b"x" * 5000}, ["zqsample-internal"], git=False)
    code, out, _ = run(root, capsys)
    assert code == 1 and "tex.bin: not scanned: larger than" in out


def test_when_git_cannot_say_which_files_are_lfs_none_is_skipped(tmp_path: Path, capsys, monkeypatch) -> None:
    monkeypatch.setattr(ch, "MAX_BYTES", 2000)
    root = make_repo(tmp_path, {".gitattributes": LFS, "tex.bin": b"x" * 5000}, ["zqsample-internal"])
    real = ch.subprocess.run

    def refuses_check_attr(cmd, *args, **kwargs):
        if cmd[:2] == ["git", "check-attr"]:
            return ch.subprocess.CompletedProcess(cmd, 128, b"", b"fatal")
        return real(cmd, *args, **kwargs)

    monkeypatch.setattr(ch.subprocess, "run", refuses_check_attr)
    code, out, _ = run(root, capsys)
    assert code == 1 and "tex.bin: not scanned: larger than" in out


def test_an_allowed_lfs_file_is_not_stale_because_its_content_was_never_shown_free_of_identifiers(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    monkeypatch.setattr(ch, "MAX_BYTES", 2000)
    root = make_repo(
        tmp_path,
        {".gitattributes": LFS, "tex.bin": b"x" * 5000},
        ["zqsample-internal"],
        allow=allow_table("tex.bin", "an LFS texture, not read"),
    )
    code, out, _ = run(root, capsys)
    assert code == 0 and "stale" not in out and "carries no identifier" not in out


def test_a_large_file_that_is_allowed_is_not_a_finding_and_not_stale(tmp_path: Path, capsys, monkeypatch) -> None:
    monkeypatch.setattr(ch, "MAX_BYTES", 2000)
    root = make_repo(
        tmp_path, {"big.txt": "x" * 5000}, ["zqsample-internal"], allow=allow_table("big.txt", "too big to read")
    )
    assert run(root, capsys)[0] == 0


def test_a_scan_of_nothing_is_a_finding_not_a_pass(tmp_path: Path, capsys, monkeypatch) -> None:
    root = make_repo(tmp_path, {"a.txt": "x\n"}, ["zqsample-internal"])
    monkeypatch.setattr(ch, "candidate_paths", lambda _root, _unlisted=None: ([], "git"))
    code, out, _ = run(root, capsys)
    assert code == 1 and "no files to scan" in out


# ---- the command line
def test_a_missing_or_broken_configuration_exits_2(tmp_path: Path, capsys) -> None:
    assert run(tmp_path, capsys)[0] == 2  # no project.json
    (tmp_path / "project.json").write_text("{not json", encoding="utf-8")
    code, _, err = run(tmp_path, capsys)
    assert code == 2 and "cannot run" in err
    (tmp_path / "project.json").write_text(project_json([]), encoding="utf-8")
    (tmp_path / "framework.toml").write_text("this is = = not toml", encoding="utf-8")
    assert run(tmp_path, capsys)[0] == 2


def test_a_root_that_is_not_a_directory_or_an_unknown_flag_exits_2(tmp_path: Path, capsys) -> None:
    code, _, err = run(tmp_path / "nowhere", capsys)
    assert code == 2 and "is not a directory" in err
    assert ch.main(["--bogus"]) == 2 and "usage" in capsys.readouterr().err
    assert ch.main(["a", "b"]) == 2


def test_a_verbose_run_leaves_a_record_of_what_it_scanned(tmp_path: Path, caplog) -> None:
    root = make_repo(tmp_path, {"a.txt": "ok\n"}, ["zqsample-internal"])
    with caplog.at_level("INFO", logger="tools.check_hygiene"):
        assert ch.main(["-v", str(root)]) == 0
    assert "scanning 2 file(s)" in caplog.text and "list from git" in caplog.text


def test_a_finding_in_a_non_ascii_file_name_is_printed_whatever_the_stream_encoding(tmp_path: Path) -> None:
    root = make_repo(tmp_path, {"g" + chr(0xF6) + "n-zqsample-internal.txt": "x\n"}, ["zqsample-internal"])
    env = {**os.environ, "PYTHONIOENCODING": "ascii"}
    result = subprocess.run(
        [sys.executable, ch.__file__, str(root)], capture_output=True, text=True, env=env, check=False
    )
    assert result.returncode == 1, result.stderr
    assert "finding(s)" in result.stdout


# ---- on a repository made from the payload
# built at run time: this managed test file ships into every made repository and must not hold the identifier itself
LEAK = "zq" + "-leaked-name"
ANSWERS = {
    "name": "Example Project",
    "slug": "example-project",
    "owner": OWNER,
    "default_branch": "main",
    "signoff": True,
    "hygiene": [LEAK],
}


@pytest.mark.skipif(
    (ROOT / "project.json").exists(),
    reason="runs only against the template's payload, not in a repository made from it",
)
def test_a_repository_made_from_the_payload_passes_its_own_hygiene_check(tmp_path: Path, capsys) -> None:
    import init as ini

    answers = tmp_path / "answers.json"
    answers.write_text(json.dumps(ANSWERS), encoding="utf-8")
    target = tmp_path / "proj"
    argv = ["new", "--answers", str(answers), "--target", str(target), "--no-sync", "--no-checks"]
    assert ini.main(argv, source=ROOT, today="2026-10-12") == 0
    code, out, _ = run(target, capsys)
    assert code == 0, out
    (target / "Docs" / "leak.md").write_text(f"the {LEAK} project\n", encoding="utf-8")
    assert run(target, capsys)[0] == 1


def test_a_file_that_is_not_utf8_is_still_scanned(tmp_path: Path, capsys) -> None:
    root = make_repo(tmp_path, {"latin.txt": b"caf\xe9 zqsample-internal\n"}, ["zqsample-internal"])
    code, out, _ = run(root, capsys)
    assert code == 1 and "latin.txt:1" in out


def test_a_line_holding_several_identifiers_is_reported_once(tmp_path: Path, capsys) -> None:
    root = make_repo(tmp_path, {"a.txt": "see zqsample-internal-plan\n"}, ["zqsample", "zqsample-internal-plan"])
    code, out, _ = run(root, capsys)
    assert code == 1 and out.count("[hygiene] a.txt:1:") == 1


# --------------------------------------------------------------------------- the review: what used to escape
ID = "zqsample-internal"


def make_symlink(link: Path, target: str) -> None:
    link.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are not available here")


@pytest.mark.parametrize("encoding", ["utf-16", "utf-16-le", "utf-16-be", "utf-32", "utf-32-le", "utf-32-be"])
def test_a_file_written_in_a_wide_encoding_is_searched(tmp_path: Path, capsys, encoding: str) -> None:
    """Windows PowerShell 5.1 writes UTF-16 by default; the first version read such a file as binary and skipped it."""
    root = make_repo(tmp_path, {"a.txt": f"one\nthe {ID} project\n".encode(encoding)}, [ID])
    code, out, _ = run(root, capsys)
    assert code == 1 and "a.txt:2: holds an identifier (read as utf-" in out, out


def test_a_latin_1_file_matches_an_identifier_with_an_accent(tmp_path: Path, capsys) -> None:
    root = make_repo(tmp_path, {"a.txt": "un caf\xe9 zq\n".encode("latin-1")}, ["caf\xe9 zq"])
    code, out, _ = run(root, capsys)
    assert code == 1 and "a.txt:1: holds an identifier (read as latin-1)" in out


def test_a_file_of_valid_utf8_is_not_also_read_as_latin_1(tmp_path: Path, capsys) -> None:
    """Latin-1 reads any byte string, so it is only a second view of a file that is not valid UTF-8."""
    root = make_repo(tmp_path, {"a.txt": "café\n".encode()}, ["cafÃ©"])  # the UTF-8 bytes seen as Latin-1
    assert run(root, capsys)[0] == 0


@pytest.mark.parametrize(
    ("identifier", "text"),
    [
        ("zq sample", "zq\nsample"),  # wrapped across two lines
        ("zq sample", "zq    sample"),
        ("zq sample", "zq\t\tsample"),
        ("strasse", "the STRAßE"),  # sharp s folds to ss
        ("STRAßE", "the strasse"),
        ("café", "café"),  # composed against decomposed
        ("zqsample", "ｚｑｓａｍｐｌｅ"),  # full-width letters
        ("zqsample", "ZQSAMPLE"),
    ],
)
def test_the_match_is_unicode_normalised_case_folded_and_whitespace_tolerant(
    tmp_path: Path, capsys, identifier: str, text: str
) -> None:
    root = make_repo(tmp_path, {"a.txt": f"line one\n{text}\n"}, [identifier])
    code, out, _ = run(root, capsys)
    assert code == 1 and "a.txt:" in out, (identifier, text)


def test_line_numbers_split_on_line_feeds_and_carriage_returns_only(tmp_path: Path, capsys) -> None:
    sep = "\x0c\x0b\x1c "  # form feed, vertical tab, file separator, line separator: an editor shows one line
    root = make_repo(tmp_path, {"a.txt": f"a{sep}b {ID}\nsecond\n".encode()}, [ID])
    assert "a.txt:1:" in run(root, capsys)[1]
    root2 = make_repo(tmp_path / "cr", {"b.txt": f"one\rtwo\r{ID}\r".encode()}, [ID])
    assert "b.txt:3:" in run(root2, capsys)[1]


def test_a_file_name_is_checked_even_when_the_entry_is_a_dangling_link(tmp_path: Path, capsys) -> None:
    root = make_repo(tmp_path, {"ok.txt": "fine\n"}, [ID], git=False)
    make_symlink(root / f"{ID}-link", "missing-target")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    code, out, _ = run(root, capsys)
    assert code == 1 and f"{ID}-link: the file name contains an identifier" in out


def test_a_link_target_is_checked_and_the_file_it_points_at_is_not_followed(tmp_path: Path, capsys) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text(f"{ID}\n", encoding="utf-8")
    inner = tmp_path / "repo"
    inner.mkdir()
    root = make_repo(inner, {"ok.txt": "fine\n"}, [ID], git=False)
    make_symlink(root / "pointer", str(outside / "secret.txt"))
    make_symlink(root / "named", f"docs/{ID}.md")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    code, out, _ = run(root, capsys)
    assert code == 1
    assert "named: the link target contains an identifier" in out
    assert "pointer" not in out  # the file outside the repository is not ours and not followed


def test_a_tracked_file_deleted_from_disk_is_skipped(tmp_path: Path, capsys) -> None:
    root = make_repo(tmp_path, {"gone.txt": f"{ID}\n", "ok.txt": "fine\n"}, [ID])
    # `git add -A` has staged gone.txt; removing it leaves a path git lists that is not on disk
    (root / "gone.txt").unlink()
    assert run(root, capsys)[0] == 0


def test_a_submodule_is_reported_as_not_scanned(tmp_path: Path, capsys, caplog) -> None:
    inner = tmp_path / "inner"
    inner.mkdir()
    (inner / "a.txt").write_text("x\n", encoding="utf-8")
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.org"]
    subprocess.run(["git", "init", "-q"], cwd=inner, check=True)
    subprocess.run([*git, "add", "-A"], cwd=inner, check=True)
    subprocess.run([*git, "commit", "-q", "-m", "x"], cwd=inner, check=True)
    root = make_repo(tmp_path / "outer", {"ok.txt": "fine\n"}, [ID], git=False)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    shutil.copytree(inner, root / "sub")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    with caplog.at_level("WARNING", logger="tools.check_hygiene"):
        assert run(root, capsys)[0] == 0
    assert "sub is a submodule or a directory entry: its files are not scanned" in caplog.text


# ---- when git cannot give the list
def test_git_missing_is_a_warning_that_names_the_reason_and_the_walk_takes_over(
    tmp_path: Path, capsys, monkeypatch, caplog
) -> None:
    root = make_repo(tmp_path, {".gitignore": "ign.txt\n", "ign.txt": f"{ID}\n"}, [ID])

    def missing(*_args, **_kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(ch.subprocess, "run", missing)
    with caplog.at_level("WARNING", logger="tools.check_hygiene"):
        code, out, _ = run(root, capsys)
    assert code == 1 and "ign.txt:1" in out  # the walk does not honour .gitignore, and the warning says it is the walk
    assert "git could not be run" in caplog.text and "scanning every file" in caplog.text


def test_a_git_failure_other_than_not_a_repository_is_a_warning(tmp_path: Path, capsys, monkeypatch, caplog) -> None:
    root = make_repo(tmp_path, {"a.txt": "x\n"}, [ID])
    failure = subprocess.CompletedProcess([], 128, b"", b"fatal: detected dubious ownership in repository")
    monkeypatch.setattr(ch.subprocess, "run", lambda *_a, **_k: failure)
    with caplog.at_level("WARNING", logger="tools.check_hygiene"):
        run(root, capsys)
    assert any(r.levelname == "WARNING" and "dubious ownership" in r.message for r in caplog.records)


def test_a_tree_that_is_not_a_repository_yet_is_only_information(tmp_path: Path, capsys, caplog) -> None:
    root = make_repo(tmp_path, {"a.txt": "x\n"}, [ID], git=False)
    with caplog.at_level("INFO", logger="tools.check_hygiene"):
        assert run(root, capsys)[0] == 0
    assert not [r for r in caplog.records if r.levelname == "WARNING"]
    assert any("scanning every file" in r.message for r in caplog.records)


# ---- boundaries and the files that cannot be read
def test_a_file_of_exactly_the_limit_is_scanned_and_one_byte_more_is_a_finding(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    monkeypatch.setattr(ch, "MAX_BYTES", 2000)
    root = make_repo(tmp_path, {"exact.txt": "x" * 1999 + "\n"}, [ID])
    assert run(root, capsys)[0] == 0
    (root / "over.txt").write_text("x" * 2000 + "\n", encoding="utf-8")  # 2001 bytes
    code, out, _ = run(root, capsys)
    assert code == 1 and "over.txt: not scanned" in out and "exact.txt" not in out


def test_a_file_that_cannot_be_read_is_a_finding_unless_it_is_allowed(tmp_path: Path, capsys, monkeypatch) -> None:
    root = make_repo(tmp_path, {"locked.txt": "x\n"}, [ID])
    real = Path.read_bytes

    def deny(self: Path) -> bytes:
        if self.name == "locked.txt":
            raise PermissionError(13, "Permission denied")
        return real(self)

    monkeypatch.setattr(Path, "read_bytes", deny)
    code, out, _ = run(root, capsys)
    assert code == 1 and "locked.txt: not scanned: PermissionError" in out
    (root / "framework.toml").write_text(framework_toml(allow_table("locked.txt", "a locked file")), encoding="utf-8")
    assert run(root, capsys)[0] == 0  # allowed, and an entry that cannot be checked is not called stale


def test_an_allowed_wide_file_that_carries_an_identifier_is_not_stale(tmp_path: Path, capsys) -> None:
    root = make_repo(
        tmp_path, {"vendor/a.txt": f"the {ID}\n".encode("utf-16")}, [ID], allow=allow_table("vendor", "a vendored tree")
    )
    code, out, _ = run(root, capsys)
    assert code == 0 and "[allowed] vendor: a vendored tree" in out


def test_findings_and_allowed_paths_are_printed_in_order(tmp_path: Path, capsys) -> None:
    files = {"b.txt": f"{ID}\n", "a.txt": f"{ID}\n", "z/vendor.txt": f"{ID}\n", "m/vendor.txt": f"{ID}\n"}
    allow = allow_table("z", "z tree") + allow_table("m", "m tree")
    root = make_repo(tmp_path, files, [ID], allow=allow)
    out = run(root, capsys)[1]
    found = [line.split(":")[0] for line in out.splitlines() if line.startswith("[hygiene]")]
    assert found == ["[hygiene] a.txt", "[hygiene] b.txt"]
    allowed = [line for line in out.splitlines() if line.startswith("[allowed]")]
    assert [a.split(":")[0] for a in allowed] == ["[allowed] m", "[allowed] project.json", "[allowed] z"]


def test_the_report_is_ordered_by_path_with_stale_entries_among_the_files(tmp_path: Path, capsys) -> None:
    root = make_repo(
        tmp_path,
        {"zzz.txt": f"{ID}\n", "mid/ok.txt": "fine\n"},
        [ID],
        allow=allow_table("aaa/gone.txt", "was a vendored file"),
    )
    lines = [x.split(":")[0] for x in run(root, capsys)[1].splitlines() if x.startswith("[hygiene]")]
    assert lines == ["[hygiene] aaa/gone.txt", "[hygiene] zzz.txt"]


def test_the_candidate_list_is_sorted(tmp_path: Path) -> None:
    names = [f"f{n:02d}.txt" for n in (7, 3, 29, 11, 1, 18, 25, 5, 14, 22, 9, 30)]
    root = make_repo(tmp_path, dict.fromkeys(names, "x\n"), [ID])
    paths, source = ch.candidate_paths(root)
    assert source == "git" and paths == sorted(paths)


def test_a_missing_git_is_a_warning_on_stderr_without_asking_for_a_verbose_run(tmp_path: Path) -> None:
    """Run as a process: the warning must reach a person who did not pass -v, so the logger is configured to show it."""
    root = make_repo(tmp_path, {"a.txt": "fine\n"}, [ID], git=False)
    bare = tmp_path / "empty-path"
    bare.mkdir()
    env = {**os.environ, "PATH": str(bare)}
    result = subprocess.run(
        [sys.executable, ch.__file__, str(root)], capture_output=True, text=True, env=env, check=False
    )
    assert result.returncode == 0, result.stderr
    assert "not a git repository" not in result.stderr  # it was never asked: git could not be run at all
    assert "git could not be run" in result.stderr and "scanning every file" in result.stderr


def test_a_folder_the_walk_cannot_list_is_a_finding_not_a_clean_pass(tmp_path: Path, monkeypatch) -> None:
    """Without git, the walk is the list: a folder it cannot list is files unscanned, and the report says so (the scan
    of #86 to #139, item 6; ledger P-16)."""
    root = make_repo(tmp_path, {"a.txt": "fine\n"}, [ID], git=False)
    real_walk = ch.os.walk

    def denying_walk(top, onerror=None, **kwargs):  # noqa: ANN001, ANN202 - os.walk's own shape
        if onerror is not None:
            onerror(PermissionError(13, "Permission denied", str(Path(top) / "locked")))
        yield from real_walk(top, **kwargs)

    monkeypatch.setattr(ch.os, "walk", denying_walk)
    findings, _ = ch.scan(root, (ID,), ())
    assert [f.path for f in findings] == ["locked"] and "cannot be listed" in findings[0].detail, findings


def test_a_linked_folder_in_the_walk_has_its_link_text_checked_as_git_would(tmp_path: Path) -> None:
    """Without git, a linked folder is a path of its own whose target text is checked, as git's blob for it is; it is
    not entered (the deliberate review of the class A sweep)."""
    root = make_repo(tmp_path / "repo", {"a.txt": "fine\n"}, [ID], git=False)
    outside = tmp_path / f"{ID}-out"
    outside.mkdir()
    try:
        (root / "linked").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("this account cannot create a symlink")
    paths, source = ch.candidate_paths(root)
    assert source == "walk" and "linked" in paths, paths
    findings, _ = ch.scan(root, (ID,), ())
    assert [(f.path, f.detail) for f in findings] == [("linked", "the link target contains an identifier")]


def test_a_linked_folder_the_walk_skips_is_skipped_like_the_folder(tmp_path: Path) -> None:
    """A linked ``.venv`` is skipped as an ordinary one is; its link text is not checked (Copilot on #144)."""
    root = make_repo(tmp_path / "repo", {"a.txt": "fine\n"}, [ID], git=False)
    outside = tmp_path / f"{ID}-venv"
    outside.mkdir()
    try:
        (root / ".venv").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("this account cannot create a symlink")
    paths, _ = ch.candidate_paths(root)
    assert ".venv" not in paths, paths
    assert ch.scan(root, (ID,), ())[0] == []


def _refuse_lstat(monkeypatch: pytest.MonkeyPatch, target: Path) -> None:
    """``Path.lstat`` of ``target`` refused, as a folder that can be listed but not searched refuses it on POSIX."""
    real = Path.lstat

    def lstat(self: Path) -> object:
        if self == target:
            raise PermissionError(13, "Permission denied", str(self))
        return real(self)

    monkeypatch.setattr(Path, "lstat", lstat)


def test_a_folder_whose_kind_the_walk_cannot_read_is_a_finding_not_a_crash(tmp_path: Path, monkeypatch) -> None:
    """Whether a folder is a link is read with ``lstat``, which can be refused: a finding, not entered (Copilot on
    #144; ledger P-16)."""
    root = make_repo(tmp_path, {"a.txt": "fine\n", "sub/b.txt": "fine\n"}, [ID], git=False)
    _refuse_lstat(monkeypatch, root / "sub")
    findings, _ = ch.scan(root, (ID,), ())
    assert [f.path for f in findings] == ["sub"] and "cannot be read" in findings[0].detail, findings


def test_a_listed_path_whose_kind_cannot_be_read_is_a_finding_not_a_crash(tmp_path: Path, monkeypatch) -> None:
    root = make_repo(tmp_path, {"a.txt": "fine\n"}, [ID], git=False)
    out = subprocess.CompletedProcess([], 0, b"a.txt\0", b"")
    monkeypatch.setattr(ch.subprocess, "run", lambda *_a, **_k: out)
    _refuse_lstat(monkeypatch, root / "a.txt")
    findings, _ = ch.scan(root, (ID,), ())
    assert [f.path for f in findings] == ["a.txt"] and "not scanned" in findings[0].detail, findings


# --------------------------------------------------------------------------- Copilot's review
def test_a_git_path_that_is_not_utf8_keeps_its_bytes_instead_of_being_replaced(monkeypatch) -> None:
    """Git prints names as raw bytes. Replacing a bad byte made ``root / name`` miss the real file."""
    out = subprocess.CompletedProcess([], 0, b"ok.txt\0caf\xe9-zq.txt\0", b"")
    monkeypatch.setattr(ch.subprocess, "run", lambda *_a, **_k: out)
    paths, source = ch.candidate_paths(Path("."))
    assert source == "git" and "ok.txt" in paths
    odd = next(p for p in paths if p != "ok.txt")
    assert "\ufffd" not in odd and "\udce9" in odd  # the undecodable byte is kept as a surrogate escape
    assert odd.encode("utf-8", errors="surrogateescape") == b"caf\xe9-zq.txt"


def test_a_name_with_a_surrogate_escape_is_matched_and_printable(tmp_path: Path, capsys, monkeypatch) -> None:
    root = make_repo(tmp_path, {"ok.txt": "fine\n"}, ["zq"])
    out = subprocess.CompletedProcess([], 0, b"ok.txt\0caf\xe9-zq.txt\0", b"")
    monkeypatch.setattr(ch.subprocess, "run", lambda *_a, **_k: out)
    code, text, _ = run(root, capsys)
    assert code == 1 and "the file name contains an identifier" in text


def test_an_allowlist_reason_that_names_an_identifier_is_not_printed(tmp_path: Path, capsys) -> None:
    reason = f"the {ID} archive"
    root = make_repo(tmp_path, {"vendor/a.txt": f"{ID}\n"}, [ID], allow=allow_table("vendor", reason))
    code, out, _ = run(root, capsys)
    assert "[hygiene] framework.toml:" in out  # the identifier in the reason is itself a finding...
    assert ID not in out and "the reason names an identifier" in out  # ...but the report does not copy it
    assert code == 1


def test_a_v_run_logs_with_the_tools_prefix(tmp_path: Path) -> None:
    """Every tool logs through log_setup: the time, the level and the module, at INFO with -v (logging in tiers)."""
    from test_log_setup import PROBE_LINE, tool_log_line

    line, level = tool_log_line("check_hygiene", [a.replace("{empty}", str(tmp_path)) for a in ["-v", "{empty}"]])
    assert PROBE_LINE.fullmatch(line), line
    assert level == 20
