"""
Framework: tests for tools/sync_adapters.py (the harness layer: adapters, skills mirrors, probes, neutral wording).
Package: tests/test_sync_adapters

Each check has a case that breaks exactly its rule and a clean one beside it. The harness names that appear below are
the data under test; this file is a test, not a managed document, and the neutral-wording check reads documents only.

The scratch repositories are built from fixed text, not from the repository's own ``framework.toml`` and matrix: this
file
is managed, and a project that enables a harness changes both of those.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import framework_config as fc  # noqa: E402
import sync_adapters as sa  # noqa: E402

TODAY = datetime.datetime.now(datetime.UTC).date().isoformat()  # the tool judges by the UTC day
PASSED = f"passed {TODAY} by Ada Example"

FRAMEWORK = """[framework]
template_version = "0.1.0"

[modules]
core = "on"
journal = "on"
ux = "planned"
python-uv = "on"
tasking = "planned"
hygiene = "on"
graph = "on"
harness-adapters = "on"
specimens = "planned"
lanes = "off"
branch-ownership = "off"
devblog = "off"

[harnesses]
enabled = [{names}]

[checks]
handoff_max_lines = 150
"""


def _blank_matrix() -> str:
    """The real matrix with every probe cell back to ``not run`` and the probe log emptied."""
    text = (ROOT / sa.MATRIX).read_text(encoding="utf-8")
    lines = []
    for line in text.splitlines():
        if re.match(r"^\| .* \| `[a-z]+` \|", line):
            line = re.sub(r"\|\s*[^|]*\|$", "| not run |", line)
        lines.append(line)
    head, _, _ = "\n".join(lines).partition("## Probe log")
    log = (
        "## Probe log\n\nRows.\n\n| Date | Harness | Version tested | Result | Run by |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| (none yet) | | | | |\n"
    )
    return head + log


def _repo(
    tmp_path: Path,
    enabled: tuple[str, ...] = (),
    passed: tuple[str, ...] = (),
    *,
    date: str = TODAY,
    log: bool = True,
) -> Path:
    """A small repository: the payload's manifest, skills and one managed standard, a blank matrix with the probes of
    ``passed`` recorded (and logged unless ``log`` is false), and ``enabled`` harnesses in a fixed
    ``framework.toml``."""
    root = tmp_path / "repo"
    (root / "Docs/standards").mkdir(parents=True)
    names = ", ".join(f'"{h}"' for h in enabled)
    (root / "framework.toml").write_text(FRAMEWORK.format(names=names), encoding="utf-8")
    shutil.copy(ROOT / "framework-manifest.toml", root / "framework-manifest.toml")
    nl = chr(10)
    # written here, not copied from ROOT: a repository that overrides a skill or a standard (with its own wording, which
    # may name a harness) must not change what these fixtures mean
    (root / ".agents/skills/local-review").mkdir(parents=True)
    (root / ".agents/skills/local-review/SKILL.md").write_text(
        "---" + nl + "name: local-review" + nl + "---" + nl + "A review.", encoding="utf-8"
    )
    (root / "Docs/standards/testing.md").write_text("# Testing" + nl + "Run the tests.", encoding="utf-8")
    matrix = _blank_matrix()
    for key in passed:
        row = next(line for line in matrix.splitlines() if f"| `{key}` |" in line)
        matrix = matrix.replace(row, row[: -len("not run |")] + f"passed {date} by Ada Example |")
        if log:
            matrix = matrix.replace(
                "| (none yet) | | | | |", f"| (none yet) | | | | |\n| {date} | `{key}` | 1.0 | passed | Ada |"
            )
    (root / sa.MATRIX).write_text(matrix, encoding="utf-8")
    return root


def _checks(root: Path) -> list[str]:
    return [str(f) for f in sa.run_checks(root)]


# ---- the table
def test_the_harness_table_covers_every_known_harness_in_order() -> None:
    assert [h.key for h in sa.HARNESS_TABLE] == list(fc.HARNESSES)


def test_each_generated_adapter_points_to_agents_md_and_nothing_else() -> None:
    for harness in sa.HARNESS_TABLE:
        if harness.content is None:
            continue
        assert "AGENTS.md" in harness.content, harness.key
        if harness.adapter and harness.adapter.endswith(".md"):  # the JSON one is checked by what it parses to
            body = [ln for ln in harness.content.splitlines() if ln.strip() and not ln.startswith("<!--")]
            assert len(body) <= 2, harness.key
    assert json.loads(sa.GEMINI_JSON) == {"context": {"fileName": ["AGENTS.md"]}}
    assert "@AGENTS.md" in sa.CLAUDE_MD and "](../AGENTS.md)" in sa.COPILOT_MD


def test_a_harness_without_an_adapter_has_no_mirror_either() -> None:
    for harness in sa.HARNESS_TABLE:
        if harness.adapter is None:
            assert harness.content is None and harness.mirror is None and not harness.shared, harness.key


def test_the_scratch_matrix_is_blank_and_the_real_one_has_a_row_per_harness() -> None:
    blank = tmp = _blank_matrix()
    assert "passed 20" not in blank and tmp.count("| not run |") == len(fc.HARNESSES)
    matrix_only = (ROOT / sa.MATRIX).read_text(encoding="utf-8").partition("## Probe log")[0]  # not the log rows
    real_keys = re.findall(r"^\| [^|]+ \| `([a-z]+)` \|", matrix_only, re.MULTILINE)
    assert real_keys == list(fc.HARNESSES)


@pytest.mark.skipif(
    (ROOT / "project.json").exists() or (ROOT / "framework.lock").exists(),
    reason="the payload's own seed, checked in the payload and not in the template's root or a made repository",
)
def test_the_payload_enables_exactly_the_harnesses_whose_probe_has_passed() -> None:
    """Owner gate G1: a harness is in the seed only after its probe passed (Claude Code 2026-10-15, Copilot
    2026-10-17). The probes document says what changes when another does: this test, the manifest and the matrix."""
    passed = {key for key, value in sa.probe_status(ROOT).items() if value is not None}
    assert passed == {"claude", "copilot"}
    assert fc.load_framework(ROOT / "framework.toml").harnesses == ("claude", "copilot")


def test_the_repositorys_own_state_is_clean() -> None:
    assert _checks(ROOT) == []


# ---- the matrix parser
@pytest.mark.parametrize(
    ("cell", "ok"),
    [
        (f"passed {TODAY} by Ada Example", True),
        (f"passed {TODAY} by x", True),
        ("not run", False),
        ("passed 2026-13-45 by Ada", False),  # not a day
        (f"passed {TODAY} by ", False),  # nobody
        (f"passed {TODAY}", False),
        (f"Passed {TODAY} by Ada", False),
        ("", False),
    ],
)
def test_only_a_dated_and_signed_pass_counts(tmp_path: Path, cell: str, ok: bool) -> None:
    root = _repo(tmp_path)
    matrix = root / sa.MATRIX
    row = next(line for line in matrix.read_text(encoding="utf-8").splitlines() if "| `gemini` |" in line)
    matrix.write_text(
        matrix.read_text(encoding="utf-8").replace(row, row[: -len("not run |")] + cell + " |"), encoding="utf-8"
    )
    assert (sa.probe_status(root)["gemini"] is not None) is ok


def test_a_probe_log_row_cannot_revoke_a_recorded_pass(tmp_path: Path) -> None:
    """The log names the harness in backticks too; only the table under the matrix heading is a matrix row."""
    root = _repo(tmp_path, enabled=("claude",), passed=("claude",))
    assert _checks(root) == ["[adapter] CLAUDE.md: missing for the enabled harness claude", *_mirror_missing(root)]
    text = (root / sa.MATRIX).read_text(encoding="utf-8")
    (root / sa.MATRIX).write_text(text + f"| {TODAY} | `claude` | 2.1 | failed | Ada |\n", encoding="utf-8")
    assert sa.probe_status(root)["claude"] == (TODAY, "Ada Example")  # still the matrix row, not the last row seen


def _mirror_missing(root: Path) -> list[str]:
    return [f"[mirror] .claude/skills/{rel}: is missing from the mirror" for rel in _files(root / ".agents/skills")]


# ---- probe
def test_an_enabled_harness_whose_probe_has_not_passed_is_a_finding(tmp_path: Path) -> None:
    found = _checks(_repo(tmp_path, enabled=("claude",)))
    assert any(f.startswith("[probe] ") and "claude is enabled but its probe has not passed" in f for f in found)


def test_an_enabled_harness_with_no_matrix_row_is_a_finding(tmp_path: Path) -> None:
    root = _repo(tmp_path, enabled=("claude",))
    kept = [ln for ln in (root / sa.MATRIX).read_text(encoding="utf-8").splitlines() if "| `claude` |" not in ln]
    (root / sa.MATRIX).write_text("\n".join(kept) + "\n", encoding="utf-8")
    assert any("has no row for the enabled harness claude" in f for f in _checks(root))


def test_two_rows_for_one_harness_are_a_finding_not_a_last_one_wins(tmp_path: Path) -> None:
    root = _repo(tmp_path, enabled=("claude",), passed=("claude",))
    text = (root / sa.MATRIX).read_text(encoding="utf-8")
    row = next(line for line in text.splitlines() if "| `claude` |" in line and "| passed" in line)
    (root / sa.MATRIX).write_text(text.replace(row, row + "\n" + row.replace(PASSED, "not run")), encoding="utf-8")
    assert any("has 2 rows for claude; there must be one" in f for f in _checks(root))


def test_an_enabled_harness_with_no_matrix_at_all_is_a_corpus_finding(tmp_path: Path) -> None:
    root = _repo(tmp_path, enabled=("claude",))
    (root / sa.MATRIX).unlink()
    assert any(f.startswith("[corpus] ") and "no probe can be shown to have passed" in f for f in _checks(root))


class _LocalDate(datetime.date):
    @classmethod
    def today(cls):  # noqa: ANN206 - the signature date.today has
        return cls(2026, 1, 1)


class _UtcAhead(datetime.datetime):
    """A clock at 2026-01-02 01:00 UTC whose local date is still 2026-01-01 (an evening in the Americas)."""

    @classmethod
    def now(cls, tz=None):  # noqa: ANN001, ANN206 - the signature datetime.now has
        return cls(2026, 1, 2, 1, 0, tzinfo=tz) if tz is not None else cls(2026, 1, 1, 19, 0)


def test_a_pass_recorded_on_the_utc_day_is_not_in_the_future_where_the_local_date_is_behind(
    tmp_path: Path, monkeypatch
) -> None:
    """Records carry the UTC day (framework ledger 38); judging one against the local date called it the future."""
    root = _repo(tmp_path, enabled=("claude",), passed=("claude",), date="2026-01-02")
    clock = type("clock", (), {"date": _LocalDate, "datetime": _UtcAhead, "UTC": datetime.UTC, "timedelta": None})
    monkeypatch.setattr(sa, "datetime", clock)
    assert not any("in the future" in f for f in _checks(root)), _checks(root)


def test_a_pass_dated_in_the_future_is_a_finding(tmp_path: Path) -> None:
    future = (datetime.datetime.now(datetime.UTC).date() + datetime.timedelta(days=1)).isoformat()
    found = _checks(_repo(tmp_path, enabled=("claude",), passed=("claude",), date=future))
    assert any("records a pass dated" in f and "in the future" in f for f in found)


def test_a_pass_with_no_entry_in_the_probe_log_is_a_finding(tmp_path: Path) -> None:
    found = _checks(_repo(tmp_path, enabled=("claude",), passed=("claude",), log=False))
    assert any(f"claude passed on {TODAY} but the probe log has no passed entry for that day" in f for f in found)


def test_a_failed_log_entry_does_not_back_a_pass(tmp_path: Path) -> None:
    root = _repo(tmp_path, enabled=("claude",), passed=("claude",))
    text = (root / sa.MATRIX).read_text(encoding="utf-8")
    (root / sa.MATRIX).write_text(text.replace("| passed | Ada |", "| failed: it searched | Ada |"), encoding="utf-8")
    assert any("probe log has no passed entry" in f for f in _checks(root))


def test_write_refuses_to_generate_for_an_unproven_harness_and_writes_nothing(tmp_path: Path, capsys) -> None:
    root = _repo(tmp_path, enabled=("claude", "gemini"), passed=("gemini",))
    assert sa.main(["--write", "--root", str(root)]) == 1
    out = capsys.readouterr().out
    assert "[probe]" in out and "claude is enabled but its probe has not passed" in out and "gemini" not in out
    assert not (root / "CLAUDE.md").exists() and not (root / ".gemini").exists()  # not even the proven one
    with pytest.raises(sa.AdapterError):
        sa.write_all(root)


# ---- adapters
@pytest.mark.parametrize("key", [h.key for h in sa.HARNESS_TABLE if h.adapter is not None])
def test_write_generates_the_adapter_and_check_then_passes_and_a_second_write_changes_nothing(
    tmp_path: Path, key: str
) -> None:
    root = _repo(tmp_path, enabled=(key,), passed=(key,))
    harness = next(h for h in sa.HARNESS_TABLE if h.key == key)
    assert harness.adapter in sa.write_all(root)
    assert (root / harness.adapter).read_text(encoding="utf-8") == harness.content
    assert _checks(root) == []
    assert sa.write_all(root) == []  # idempotent


@pytest.mark.parametrize("key", [h.key for h in sa.HARNESS_TABLE if h.adapter is not None and not h.shared])
def test_an_adapter_edited_by_hand_a_missing_one_and_a_crlf_one(tmp_path: Path, key: str) -> None:
    root = _repo(tmp_path, enabled=(key,), passed=(key,))
    harness = next(h for h in sa.HARNESS_TABLE if h.key == key)
    sa.write_all(root)
    adapter = root / harness.adapter
    adapter.write_bytes(adapter.read_bytes().replace(b"\n", b"\r\n"))  # a Windows checkout: still the pointer
    assert _checks(root) == []
    adapter.write_text(harness.content + "\nAlso: always be nice.\n", encoding="utf-8")
    (finding,) = _checks(root)
    assert finding.startswith("[adapter] ") and "holds no text of its own" in finding
    adapter.unlink()
    (finding,) = _checks(root)
    assert "missing for the enabled harness" in finding


@pytest.mark.parametrize("key", [h.key for h in sa.HARNESS_TABLE if h.adapter is not None])
def test_an_adapter_for_a_harness_that_is_not_enabled_is_a_finding_with_its_remedy(tmp_path: Path, key: str) -> None:
    root = _repo(tmp_path)
    harness = next(h for h in sa.HARNESS_TABLE if h.key == key)
    (root / harness.adapter).parent.mkdir(parents=True, exist_ok=True)
    (root / harness.adapter).write_text(harness.content, encoding="utf-8")
    (finding,) = _checks(root)
    assert finding == (
        f"[adapter] {harness.adapter}: belongs to {key}, which is not enabled in framework.toml: "
        f"delete it, or enable {key}"
    )


def test_a_harness_that_reads_agents_md_natively_gets_nothing_generated(tmp_path: Path) -> None:
    root = _repo(tmp_path, enabled=("codex", "cursor"), passed=("codex", "cursor"))
    assert sa.write_all(root) == []
    assert _checks(root) == []


# ---- the shared Gemini settings file
def _gemini_repo(tmp_path: Path, settings: str | bytes | None) -> Path:
    root = _repo(tmp_path, enabled=("gemini",), passed=("gemini",))
    if settings is not None:
        (root / ".gemini").mkdir()
        data = settings if isinstance(settings, bytes) else settings.encode("utf-8")
        (root / ".gemini/settings.json").write_bytes(data)
    return root


@pytest.mark.parametrize(
    "settings",
    [
        '{"context": {"fileName": ["AGENTS.md"]}}',
        '{"context": {"fileName": "AGENTS.md"}}',
        '{"theme": "dark", "mcpServers": {"x": {}}, "context": {"fileName": ["GEMINI.md", "AGENTS.md"]}}',
    ],
)
def test_the_gemini_settings_may_hold_the_projects_own_settings_if_they_name_agents_md(
    tmp_path: Path, settings: str
) -> None:
    root = _gemini_repo(tmp_path, settings)
    assert _checks(root) == []
    assert sa.write_all(root) == []  # nothing to change


@pytest.mark.parametrize(
    ("settings", "reason"),
    [
        ("{not json", "is not valid JSON"),
        ("{}", "does not name AGENTS.md"),
        ('{"context": {"fileName": ["GEMINI.md"]}}', "does not name AGENTS.md"),
        ('{"context": []}', "does not name AGENTS.md"),
        (b"\xef\xbb\xbf" + b'{"context": {"fileName": ["AGENTS.md"]}}', "is not valid JSON"),  # a byte order mark
    ],
)
def test_a_gemini_settings_file_that_does_not_name_agents_md_is_a_finding(
    tmp_path: Path, settings: str | bytes, reason: str
) -> None:
    (finding,) = _checks(_gemini_repo(tmp_path, settings))
    assert finding.startswith("[adapter] .gemini/settings.json: ") and reason in finding


def test_write_adds_agents_md_to_the_settings_and_keeps_every_other_setting(tmp_path: Path) -> None:
    root = _gemini_repo(tmp_path, '{"theme": "dark", "context": {"fileName": ["GEMINI.md"], "x": 1}}')
    assert sa.write_all(root) == [".gemini/settings.json"]
    merged = json.loads((root / ".gemini/settings.json").read_text(encoding="utf-8"))
    assert merged == {"theme": "dark", "context": {"fileName": ["GEMINI.md", "AGENTS.md"], "x": 1}}
    assert _checks(root) == []


def test_write_does_not_overwrite_a_settings_file_it_cannot_read(tmp_path: Path) -> None:
    root = _gemini_repo(tmp_path, "{not json")
    with pytest.raises(sa.AdapterError, match="not overwritten"):
        sa.write_all(root)
    assert (root / ".gemini/settings.json").read_text(encoding="utf-8") == "{not json"


def test_settings_that_do_not_name_agents_md_are_not_a_finding_when_gemini_is_not_enabled(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / ".gemini").mkdir()
    (root / ".gemini/settings.json").write_text('{"theme": "dark"}', encoding="utf-8")
    assert _checks(root) == []  # the project's own settings file
    (root / ".gemini/settings.json").write_text(sa.GEMINI_JSON, encoding="utf-8")
    (finding,) = _checks(root)
    assert "belongs to gemini, which is not enabled" in finding


# ---- mirror
def _files(base: Path) -> list[str]:
    return sorted(p.relative_to(base).as_posix() for p in base.rglob("*") if p.is_file())


def test_the_mirror_is_a_copy_of_the_skills_tree(tmp_path: Path) -> None:
    root = _repo(tmp_path, enabled=("claude",), passed=("claude",))
    sa.write_all(root)
    source = _files(root / ".agents/skills")
    assert source and _files(root / ".claude/skills") == source
    for rel in source:
        # a text file is compared with its line endings normalised (the working copy may be CRLF)
        source_bytes = (root / ".agents/skills" / rel).read_bytes().replace(b"\r\n", b"\n")
        assert (root / ".claude/skills" / rel).read_bytes() == source_bytes
    assert _checks(root) == []


def test_a_mirror_file_that_differs_is_missing_or_stray_is_found_and_write_repairs_them(tmp_path: Path) -> None:
    root = _repo(tmp_path, enabled=("claude",), passed=("claude",))
    sa.write_all(root)
    first = _files(root / ".claude/skills")[0]
    (root / ".claude/skills" / first).write_text("edited by hand\n", encoding="utf-8")
    assert any(f"{first}: differs from" in f for f in _checks(root))
    (root / ".claude/skills" / first).unlink()
    assert any(f"{first}: is missing from the mirror" in f for f in _checks(root))
    (root / ".claude/skills/stray.md").write_text("x\n", encoding="utf-8")
    assert any("stray.md: is not in .agents/skills (a stray file)" in f for f in _checks(root))
    written = sa.write_all(root)
    assert any(first in item for item in written) and any("stray.md (removed" in item for item in written)
    assert _checks(root) == [] and not (root / ".claude/skills/stray.md").exists()


def test_a_mirror_for_a_harness_that_is_not_enabled_is_a_finding_with_its_remedy(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    shutil.copytree(root / ".agents/skills", root / ".claude/skills")
    (finding,) = _checks(root)
    assert finding == (
        "[mirror] .claude/skills: is a skills mirror for claude, which is not enabled: delete it, or enable claude"
    )


def test_a_crlf_text_file_in_the_mirror_is_current(tmp_path: Path) -> None:
    root = _repo(tmp_path, enabled=("claude",), passed=("claude",))
    sa.write_all(root)
    for path in (root / ".claude/skills").rglob("*.md"):
        path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    assert _checks(root) == []


def test_a_binary_file_in_the_skills_is_copied_exactly_and_never_crashes_a_run(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    blob = bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A, 0xFF, 0xFE])  # not UTF-8, and holds a CRLF pair
    (root / ".agents/skills/local-review/diagram.png").write_bytes(blob)
    assert _checks(root) == []  # nothing enabled, nothing read as text
    enabled = _repo(tmp_path / "again", enabled=("claude",), passed=("claude",))
    (enabled / ".agents/skills/local-review/diagram.png").write_bytes(blob)
    sa.write_all(enabled)
    assert (enabled / ".claude/skills/local-review/diagram.png").read_bytes() == blob  # the CRLF pair was kept
    assert _checks(enabled) == []
    (enabled / ".claude/skills/local-review/diagram.png").write_bytes(blob.replace(b"\r\n", b"\n"))
    assert any("diagram.png: differs from" in f for f in _checks(enabled))  # a binary is compared exactly


@pytest.mark.skipif(os.name == "nt", reason="Windows has no execute bit")
def test_the_execute_bit_of_a_skill_script_is_kept_in_the_mirror(tmp_path: Path) -> None:
    root = _repo(tmp_path, enabled=("claude",), passed=("claude",))
    script = root / ".agents/skills/local-review/run.sh"
    script.write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
    script.chmod(0o755)
    sa.write_all(root)
    assert os.access(root / ".claude/skills/local-review/run.sh", os.X_OK)
    assert _checks(root) == []
    (root / ".claude/skills/local-review/run.sh").chmod(0o644)
    assert any("run.sh: differs from" in f for f in _checks(root))


def test_a_symbolic_link_in_the_skills_tree_is_refused(tmp_path: Path) -> None:
    root = _repo(tmp_path, enabled=("claude",), passed=("claude",))
    secret = tmp_path / "secret.txt"
    secret.write_text("not a skill\n", encoding="utf-8")
    try:
        (root / ".agents/skills/local-review/link.md").symlink_to(secret)
    except OSError:
        pytest.skip("this account may not create symbolic links")
    with pytest.raises(sa.AdapterError, match="symbolic link"):
        sa.write_all(root)
    assert not (root / ".claude").exists()


def test_the_enabled_mirror_with_no_skills_to_copy_is_a_corpus_finding_not_a_pass(tmp_path: Path) -> None:
    root = _repo(tmp_path, enabled=("claude",), passed=("claude",))
    shutil.rmtree(root / ".agents/skills")
    assert any(f.startswith("[corpus] ") and "no skills to mirror" in f for f in _checks(root))
    with pytest.raises(sa.AdapterError, match="no skills to mirror"):
        sa.write_all(root)


def test_a_file_where_a_folder_belongs_is_an_error_not_a_traceback(tmp_path: Path, capsys) -> None:
    root = _repo(tmp_path, enabled=("claude",), passed=("claude",))
    (root / ".claude").write_text("in the way\n", encoding="utf-8")
    assert sa.main(["--write", "--root", str(root)]) == 2
    assert "cannot write" in capsys.readouterr().err


def test_a_stray_file_that_cannot_be_removed_is_an_error_not_a_traceback(tmp_path: Path, capsys, monkeypatch) -> None:
    root = _repo(tmp_path, enabled=("claude",), passed=("claude",))
    sa.write_all(root)
    (root / ".claude/skills/stray.md").write_text("x\n", encoding="utf-8")

    def refuse(self, *args, **kwargs):
        raise PermissionError("locked")

    monkeypatch.setattr(Path, "unlink", refuse)
    assert sa.main(["--write", "--root", str(root)]) == 2
    assert "cannot remove" in capsys.readouterr().err


# ---- neutral wording
def test_a_managed_document_that_names_a_harness_is_found_with_its_line(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / "Docs/standards/testing.md").write_text("line one\nSee how Claude Code does it.\n", encoding="utf-8")
    (finding,) = _checks(root)
    assert finding == "[neutral] Docs/standards/testing.md:2: names a harness ('Claude'); only the matrix may"


def test_the_matrix_and_the_probes_document_may_name_harnesses(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    shutil.copy(ROOT / sa.PROBES, root / sa.PROBES)
    assert _checks(root) == []
    assert sa._NAME_RE.search((root / sa.MATRIX).read_text(encoding="utf-8"))  # the exemption is doing something


@pytest.mark.parametrize("text", ["a cursory look", "the Geminis", "precopilot", "codexes", "the text cursor moved"])
def test_a_word_that_only_contains_a_name_or_is_an_ordinary_word_is_not_a_harness_name(
    tmp_path: Path, text: str
) -> None:
    root = _repo(tmp_path)
    (root / "Docs/standards/testing.md").write_text(f"{text}\n", encoding="utf-8")
    assert _checks(root) == []


@pytest.mark.parametrize("name", [*sa.NEUTRAL_WORDS, "Cursor IDE", "the Cursor agent", ".cursorrules", "GPT-4"])
def test_every_listed_name_and_phrase_is_found_in_any_case(tmp_path: Path, name: str) -> None:
    root = _repo(tmp_path)
    for spelling in (name, name.upper()):
        (root / "Docs/standards/testing.md").write_text(f"about {spelling} here\n", encoding="utf-8")
        assert len(_checks(root)) == 1, spelling


def test_a_project_owned_document_may_name_a_harness(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / "Docs/glossary.md").write_text("we use Claude Code here\n", encoding="utf-8")  # seeded once, the project's
    assert _checks(root) == []


def test_a_managed_json_file_is_read_too_and_the_suffix_is_matched_in_any_case(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / "Docs/knowledge").mkdir()
    (root / "Docs/knowledge/ai-first-framework.graph.json").write_text('{"note": "copilot"}\n', encoding="utf-8")
    assert [f.split(":")[0] for f in _checks(root)] == ["[neutral] Docs/knowledge/ai-first-framework.graph.json"]
    (root / ".agents/skills/local-review/NOTES.MD").write_text("Claude\n", encoding="utf-8")  # matches .agents/skills/*
    assert len(_checks(root)) == 2


def test_a_repository_with_no_managed_document_is_a_corpus_finding_not_a_pass(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / "Docs/standards/testing.md").unlink()
    shutil.rmtree(root / ".agents")  # the skills are managed documents too
    assert any(f.startswith("[corpus] ") and "no managed document" in f for f in _checks(root))


def test_a_missing_manifest_is_a_corpus_finding_and_an_unreadable_one_is_unusable(tmp_path: Path, capsys) -> None:
    root = _repo(tmp_path)
    (root / "framework-manifest.toml").unlink()
    assert any(f.startswith("[corpus] framework-manifest.toml") for f in _checks(root))
    (root / "framework-manifest.toml").write_text("not = = toml", encoding="utf-8")
    assert sa.main(["--check", "--root", str(root)]) == 2
    assert "cannot run" in capsys.readouterr().err


def _override(root: Path, target: str) -> None:
    nl = chr(10)
    table = nl.join(["", "[[overrides]]", f'target = "{target}"', 'reason = "the project own text"', ""])
    with (root / "framework.toml").open("a", encoding="utf-8") as f:
        f.write(table)


def test_an_overridden_file_is_the_projects_text_and_is_not_asked_to_be_neutral(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / "Docs/standards/testing.md").write_text("Copilot reviews every pull request.", encoding="utf-8")
    assert [f.split(":")[0] for f in _checks(root)] == ["[neutral] Docs/standards/testing.md"]
    _override(root, "Docs/standards/testing.md")
    assert _checks(root) == []


def test_an_override_excuses_only_the_file_it_names(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / "Docs/standards/testing.md").write_text("Copilot reviews every pull request.", encoding="utf-8")
    (root / ".agents/skills/local-review/NOTES.md").write_text("Claude", encoding="utf-8")
    _override(root, "Docs/standards/testing.md")
    assert [f.split(":")[0] for f in _checks(root)] == ["[neutral] .agents/skills/local-review/NOTES.md"]


def test_a_skills_mirror_file_inherits_the_exemption_of_its_source_and_a_divergent_copy_is_still_found(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path, enabled=("claude",), passed=("claude",))
    skill = "local-review/SKILL.md"
    (root / ".agents/skills" / skill).write_text("Claude reviews it.", encoding="utf-8")
    sa.write_all(root)  # the mirror is a copy of the source
    found = [f.split(":")[0] for f in _checks(root)]
    assert found == ["[neutral] .agents/skills/" + skill, "[neutral] .claude/skills/" + skill]
    _override(root, ".agents/skills/" + skill)
    assert _checks(root) == []  # source and mirror equal: both excused
    (root / ".claude/skills" / skill).write_text("Claude reviews it, differently.", encoding="utf-8")
    assert [f.split(":")[0] for f in _checks(root)] == ["[mirror] .claude/skills/" + skill]


def test_a_skills_extension_may_name_a_harness_in_the_canonical_folder_and_in_a_mirror(tmp_path: Path) -> None:
    root = _repo(tmp_path, enabled=("claude",), passed=("claude",))
    (root / ".agents/skills/local-review/project.md").write_text("Here, Claude reviews our way.", encoding="utf-8")
    sa.write_all(root)  # the mirror carries the extension as a copy
    assert (root / ".claude/skills/local-review/project.md").is_file()
    assert _checks(root) == []
    (root / ".agents/skills/local-review/SKILL.md").write_text("Claude reviews it.", encoding="utf-8")
    sa.write_all(root)
    found = [f.split(":")[0] for f in _checks(root)]
    assert found == ["[neutral] .agents/skills/local-review/SKILL.md", "[neutral] .claude/skills/local-review/SKILL.md"]


def test_a_project_md_anywhere_but_directly_in_a_skills_folder_is_still_held_neutral(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / ".agents/skills/local-review/notes").mkdir()
    (root / ".agents/skills/local-review/notes/project.md").write_text("Claude", encoding="utf-8")
    (root / ".agents/skills/project.md").write_text("Claude", encoding="utf-8")
    found = [f.split(":")[0] for f in _checks(root)]
    assert found == ["[neutral] .agents/skills/project.md", "[neutral] .agents/skills/local-review/notes/project.md"]


def test_a_mirror_is_not_excused_by_an_override_of_a_different_skill(tmp_path: Path) -> None:
    root = _repo(tmp_path, enabled=("claude",), passed=("claude",))
    (root / ".agents/skills/local-review/SKILL.md").write_text("Claude reviews it.", encoding="utf-8")
    sa.write_all(root)
    _override(root, ".agents/skills/other/SKILL.md")
    assert len(_checks(root)) == 2


def test_a_repository_that_overrides_every_managed_document_has_a_corpus_but_one_with_none_does_not(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    for target in ("Docs/standards/testing.md", ".agents/skills/local-review/SKILL.md"):
        _override(root, target)
    assert _checks(root) == []
    (root / "Docs/standards/testing.md").unlink()
    shutil.rmtree(root / ".agents")
    assert any(f.startswith("[corpus] ") and "no managed document" in f for f in _checks(root))


def test_the_neutral_check_skips_environments_and_run_records(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    for skipped in (".venv/lib", "logs", ".git/hooks"):
        (root / skipped).mkdir(parents=True)
        (root / skipped / "notes.md").write_text("Claude\n", encoding="utf-8")
    assert _checks(root) == []


def test_the_walk_never_descends_into_an_environment(tmp_path: Path, monkeypatch) -> None:
    """Pruned, not filtered afterwards: a ``.venv`` holds thousands of files that nothing here would read."""
    root = _repo(tmp_path)
    for skipped in (".venv/lib", "logs", ".git/hooks", "node_modules/x"):
        (root / skipped).mkdir(parents=True)
    entered: list[str] = []
    real_walk = os.walk

    def spy(top, **kwargs):
        for dirpath, dirnames, filenames in real_walk(top, **kwargs):
            yield dirpath, dirnames, filenames
            entered.extend(dirnames)  # what is left after the caller pruned it

    monkeypatch.setattr(sa.os, "walk", spy)
    assert _checks(root) == []
    assert entered and not set(entered) & sa.SKIPPED_DIRS


def test_a_folder_that_cannot_be_listed_is_a_finding_not_a_silent_pass(tmp_path: Path, monkeypatch) -> None:
    root = _repo(tmp_path)
    real_walk = os.walk

    def denying(top, onerror=None, **kwargs):
        if onerror is not None:
            onerror(PermissionError(13, "Permission denied", str(Path(top) / "Docs" / "locked")))
        yield from real_walk(top, **kwargs)

    monkeypatch.setattr(sa.os, "walk", denying)
    (finding,) = _checks(root)
    assert finding.startswith("[corpus] Docs/locked: cannot be listed, so it was not checked: PermissionError")


def test_the_seed_test_and_the_check_exempt_the_same_documents() -> None:
    seed = (ROOT / "tests" / "test_seed_documents.py").read_text(encoding="utf-8")
    assert "NEUTRAL_EXEMPT" in seed


# ---- the command line
def test_main_exit_codes(tmp_path: Path, capsys) -> None:
    root = _repo(tmp_path)
    assert sa.main(["--check", "--root", str(root)]) == 0
    assert "adapters: clean" in capsys.readouterr().out
    (root / "Docs/standards/testing.md").write_text("Claude\n", encoding="utf-8")
    assert sa.main(["--check", "--root", str(root)]) == 1
    out = capsys.readouterr().out
    assert "[neutral]" in out and "adapters: 1 finding(s)" in out
    assert sa.main(["--check", "--root", str(tmp_path / "nowhere")]) == 2
    assert "is not a directory" in capsys.readouterr().err
    (root / "framework.toml").write_text("not = = toml", encoding="utf-8")
    assert sa.main(["--check", "--root", str(root)]) == 2
    assert "cannot run" in capsys.readouterr().err


def test_main_needs_exactly_one_mode() -> None:
    with pytest.raises(SystemExit) as caught:
        sa.main([])
    assert caught.value.code == 2
    with pytest.raises(SystemExit):
        sa.main(["--check", "--write"])


def test_main_write_reports_what_it_wrote_and_then_nothing(tmp_path: Path, capsys) -> None:
    root = _repo(tmp_path, enabled=("claude",), passed=("claude",))
    assert sa.main(["--write", "--root", str(root)]) == 0
    first = capsys.readouterr().out
    assert "wrote CLAUDE.md" in first and "wrote .claude/skills/" in first
    assert sa.main(["--write", "--root", str(root)]) == 0
    assert "adapters: wrote 0 file(s)" in capsys.readouterr().out


def test_a_failed_write_is_reported_and_leaves_no_temporary_and_no_adapter(tmp_path: Path, capsys, monkeypatch) -> None:
    root = _repo(tmp_path, enabled=("copilot",), passed=("copilot",))
    created: list[Path] = []
    real_replace = os.replace

    def refuse(source, destination):
        created.append(Path(source))
        assert Path(source).exists()  # the temporary was written before the move was refused
        raise PermissionError("denied")

    monkeypatch.setattr(sa.os, "replace", refuse)
    assert sa.main(["--write", "--root", str(root)]) == 2
    assert "cannot write" in capsys.readouterr().err
    assert len(created) == 1 and not created[0].exists()  # and it was cleaned up
    assert not (root / ".github/copilot-instructions.md").exists()
    assert real_replace is not None


def test_non_ascii_text_in_a_finding_does_not_crash_a_narrow_stdout(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    named = (
        root / ".agents/skills" / ("caf" + chr(0xE9))
    )  # the finding names the file, so the name is what must survive
    named.mkdir()
    (named / "SKILL.md").write_text("Claude\n", encoding="utf-8")
    ran = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "sync_adapters.py"), "--check", "--root", str(root)],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONIOENCODING": "ascii"},
    )
    assert ran.returncode == 1 and "Traceback" not in ran.stderr
    assert "caf" + chr(92) + "xe9/SKILL.md:1" in ran.stdout  # written as an escape: not lost, not a crash


def test_verbose_is_the_only_thing_that_makes_it_log(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    base = [sys.executable, str(ROOT / "tools" / "sync_adapters.py"), "--check", "--root", str(root)]
    quiet = subprocess.run(base, capture_output=True, text=True, check=False)
    loud = subprocess.run([*base, "-v"], capture_output=True, text=True, check=False)
    assert quiet.returncode == loud.returncode == 0
    assert quiet.stderr == "" and "enabled harnesses: none" in loud.stderr


def test_the_finding_format_names_the_check_the_place_and_the_reason() -> None:
    assert str(sa.Finding("adapter", "CLAUDE.md", "is wrong")) == "[adapter] CLAUDE.md: is wrong"
    assert re.fullmatch(r"\[[a-z]+\] \S+: .+", str(sa.Finding("probe", sa.MATRIX, "has no row")))


# ---- the automated review's findings
def test_a_pass_dated_tomorrow_is_in_the_future_too() -> None:
    """No slack: a probe cannot have passed on a day that has not happened."""
    today = datetime.date(2026, 10, 14)
    assert isinstance(sa._passed("passed 2026-10-15 by Ada", today), str)
    assert sa._passed("passed 2026-10-14 by Ada", today) == ("2026-10-14", "Ada")


@pytest.mark.parametrize("key", [h.key for h in sa.HARNESS_TABLE if h.adapter is not None and not h.shared])
def test_an_edited_adapter_for_a_harness_that_is_not_enabled_is_still_a_finding(tmp_path: Path, key: str) -> None:
    root = _repo(tmp_path)
    harness = next(h for h in sa.HARNESS_TABLE if h.key == key)
    (root / harness.adapter).parent.mkdir(parents=True, exist_ok=True)
    (root / harness.adapter).write_text(harness.content + "Always be nice.\n", encoding="utf-8")
    (finding,) = _checks(root)
    assert f"belongs to {key}, which is not enabled" in finding


def test_a_missing_matrix_is_a_finding_even_when_no_harness_is_enabled(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / sa.MATRIX).unlink()
    (finding,) = _checks(root)
    assert finding.startswith("[corpus] ") and "is missing, so no probe can be shown to have passed" in finding


@pytest.mark.parametrize("name", [3, {"a": 1}, [1, 2], None, True])
def test_a_context_file_setting_of_the_wrong_shape_is_refused_not_a_traceback(tmp_path: Path, name: object) -> None:
    root = _gemini_repo(tmp_path, json.dumps({"context": {"fileName": name}}))
    assert any("does not name AGENTS.md" in f for f in _checks(root))
    before = (root / ".gemini/settings.json").read_text(encoding="utf-8")
    with pytest.raises(sa.AdapterError, match="not a string or an array of strings"):
        sa.write_all(root)
    assert (root / ".gemini/settings.json").read_text(encoding="utf-8") == before


def test_a_symbolic_link_as_the_mirror_folder_or_the_source_folder_is_refused(tmp_path: Path) -> None:
    root = _repo(tmp_path, enabled=("claude",), passed=("claude",))
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.md").write_text("not ours\n", encoding="utf-8")
    try:
        (root / ".claude").mkdir()
        (root / ".claude/skills").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("this account may not create symbolic links")
    with pytest.raises(sa.AdapterError, match="symbolic link"):
        sa.write_all(root)
    assert (outside / "keep.md").read_text(encoding="utf-8") == "not ours\n"  # nothing outside was touched
    assert sorted(p.name for p in outside.iterdir()) == ["keep.md"]


def test_a_v_run_logs_with_the_tools_prefix(tmp_path: Path) -> None:
    """Every tool logs through log_setup: the time, the level and the module, at INFO with -v (logging in tiers)."""
    from test_log_setup import PROBE_LINE, tool_log_line

    line, level = tool_log_line(
        "sync_adapters", [a.replace("{empty}", str(tmp_path)) for a in ["-v", "--check", "--root", "{empty}"]]
    )
    assert PROBE_LINE.fullmatch(line), line
    assert level == 20
