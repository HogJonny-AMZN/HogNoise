"""
Framework: tests for .claude/hooks/no_inline_python.py (refuse Python with no script file; let every other command run).
Package: tests/test_no_inline_python_hook
"""

from __future__ import annotations

import importlib.util
import io
import json
import shlex
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / ".claude" / "hooks" / "no_inline_python.py"
_spec = importlib.util.spec_from_file_location("no_inline_python", HOOK)
hook = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hook)

REFUSED = [
    'python -c "print(1)"',
    "python3 -c 'import sys'",
    'uv run python -c "import your_project_name"',
    'uv run python -I -c "pass"',
    'uv run --extra docs python -c "import yaml"',
    "python -Ic 'pass'",
    "python - <<'EOF'\nprint(1)\nEOF",
    "uv run python - </dev/null",
    "python <<EOF\nprint(1)\nEOF",
    "cat probe.py | python",
    "cat probe.py | uv run python -",
    "cd /d/repo && python -c 'x'",
    "echo hi; python",
    "py -c 1",
    "C:/Python314/python.exe -c 1",
    "$(python -c 'print(1)')",
    "FOO=1 python -c 1",
    "python -W ignore -c 1",
    "@'\nprint(1)\n'@ | python -",
    # a redirection straight after the interpreter
    "python<<'EOF'\nprint(1)\nEOF",
    "python</dev/null",
    # a quoted interpreter or a quoted option is still run
    '"python" -c "pass"',
    'python "-c" "pass"',
    '"C:/Program Files/Python314/python.exe" -c 1',
    '& "C:\\Program Files\\Python314\\python.exe" -c 1',
    # an option's attached value is not a switch
    'python -Ximporttime -c "pass"',
    # an output redirection is not a script
    "python > out.txt",
    "python 2>&1",
    'python 2>/dev/null -c "pass"',
    # a shell's -c script is a command of its own
    "bash -c \"python -c 'print(1)'\"",
    "pwsh -NoProfile -Command \"python -c 'print(1)'\"",
    "env -i PATH=/usr/bin python -c 1",
    "x=$(uv run --no-project --quiet python -c 1)",
    # a substitution inside double quotes still runs
    "echo \"$(python -c 'print(1)')\"",
    'x="$(python -c 1)"',
    'echo "a $(echo b; python -) c"',
    # uv's own options before run, and the wrappers that time or reprioritise a command
    "uv --quiet run python -c 1",
    "uv --directory sub run python -c 1",
    "timeout 10 python -c 1",
    "timeout -s KILL 10 python -",
    "nice -n 5 python -c 1",
    # #241: xargs, sudo and cmd /c, with their options
    "xargs python -c 1",
    "xargs -n 1 -P 4 python -c 1",
    "sudo python -c 1",
    "sudo -u root -E python -",
    "sudo -- python -c 1",
    "cmd /c python -c 1",
    "cmd.exe /d /c python -c 1",
    "CMD /C uv run python -c 1",
    # Copilot's review of #248: bare GNU long options with an optional value, a short cluster, cmd's one-string line
    "xargs --replace python -c 1",
    "xargs --eof python -c 1",
    "xargs --max-lines python -c 1",
    "sudo -Eu root python -c 1",
    'cmd /c "C:/Program Files/Python314/python.exe" -c 1',
    'cmd /c "python -c 1"',
    'cmd /c "echo x & python -c 1"',
    # a downstream review: a substitution in a heredoc body may span lines
    "cat <<EOF\n$(\npython -c 'print(1)'\n)\nEOF",
    # Copilot's review: a quoted ")" does not close a substitution; backquotes run inside double quotes; an unquoted
    # heredoc's body runs its substitutions; a quoted assignment value is still an assignment
    "echo \"$(printf ')'; python -c 'print(1)')\"",
    "echo \"`python -c 'print(1)'`\"",
    "cat <<EOF\n$(python -c 'print(1)')\nEOF",
    "cat <<EOF\n`python -c 1`\nEOF",
    'FOO="a b" python -c 1',
    "FOO='a b' python -c 1",
    # #316: an escape outside quotes is consumed, so the quotes after it pair as Bash pairs them; env's long
    # options and a shell's options take their value as a separate word
    "printf '%s\\n' 'it'\\''s'; python -c 'print(1)'",
    "echo a\\ b; python -c 1",
    "env --unset PYTHONPATH python -c 1",
    "env --chdir /tmp python -c 1",
    "bash -O extglob -c 'python -c 1'",
    "bash +O extglob -c 'python -c 1'",
    "bash -o pipefail -c 'python -c 1'",
    "bash -euo pipefail -c 'python -c 1'",
    "bash --rcfile /dev/null -c 'python -c 1'",
    "bash --init-file /dev/null -c 'python -c 1'",
    # the fresh-eyes review of #316: a Windows path in Bash keeps its backslashes (the escape's negative control);
    # a backslash inside the command word or before a dash is removed as Bash removes it; a shell reads all its
    # options before the script, whatever their order; env -S carries a command; env's and time's other values
    "C:\\Python314\\python.exe -c 1",
    "py\\thon -c 1",
    "\\p\\y\\t\\h\\o\\n -c 1",
    "python \\-c 1",
    "echo a\\\\; python -c 1",
    "bash -co pipefail 'python -c 1'",
    "bash -c -o pipefail 'python -c 1'",
    "bash -oc pipefail 'python -c 1'",
    "bash -ox pipefail -c 'python -c 1'",
    "env -S 'python -c 1'",
    "env -S python -c 1",
    "env --split-string 'python -c 1'",
    "env --split-string='python -c 1'",
    "env -P /usr/bin python -c 1",
    "env --argv0 x python -c 1",
    "/usr/bin/time -o out.txt python -c 1",
    "/usr/bin/time -f %e python -c 1",
    # Copilot's review of #318: env -S splits its value into words and keeps the boundaries of the words after it
    "env -S 'bash -c' 'exec python -c 1'",
    "env -S'python -c 1'",
    "env -S 'python\\_-c\\_1'",
]

ALLOWED = [
    "uv run python tools/check_docs.py",
    "uv run python C:/scratch/probe.py --flag",
    "python -m pytest",
    "uv run pytest -q",
    "python --version",
    "python -V",
    "python -I tools/check.py",
    "python -W ignore script.py",
    'git commit -s -m "never run python -c or python - again"',
    "grep -n 'python -c' Docs/standards/failure-modes.md",
    "which python",
    "ls",
    "uv run ruff check .",
    "python script.py < input.txt",
    # a runner's own command is not Python, whatever its arguments say
    "uv run pytest -k python",
    "uv run which python",
    "command -v python",
    # an attached value is not a switch
    "python -Wonce script.py",
    "python -mcompileall .",
    # an output redirection after the script
    "python script.py > out.txt",
    "python script.py 2>&1",
    # a heredoc's body is data, not a command
    "cat <<'EOF' > notes.md\npython -c 1\nEOF",
    'echo "python -c 1"',
    "uv run --python 3.12 python tools/check_docs.py",
    "uv run -- python tools/check_docs.py",
    "uv run -m pytest -q",
    "python tools/check.py  # not python -c",
    "C:\\Python314\\python.exe tools\\check.py",
    "py -3.12 tools/check.py",
    "bash tools/run.sh",
    # a substitution that runs a file; a single-quoted one is text, not run
    'echo "$(uv run python tools/check.py)"',
    "echo '$(python -c 1)'",
    'echo "unterminated $(python tools/check.py"',
    # the same wrappers around a file
    "uv --quiet run python tools/check.py",
    "timeout 10 uv run python tools/check.py",
    "nice -n 5 python tools/check.py",
    "xargs -n 1 python tools/check.py",
    "sudo -u root python tools/check.py",
    "cmd /c python tools/check.py",
    "cmd /c dir",
    # sudo's queries run nothing; cmd's quoted text is text
    "sudo -l python -c 1",
    "sudo --list python -c 1",
    'cmd /c echo "literal & python -c 1"',
    # a downstream review: a heredoc's delimiter runs nothing, and an escaped one makes the body data
    'cat <<"$(python -c 1)"\nplain data\n$(python -c 1)\n',
    "cat <<\\EOF\n$(python -c 'print(1)')\nEOF",
    "xargs grep -l python",
    # the Windows launcher's queries list interpreters
    "py -0p",
    "py --list",
    # text the lexer cannot close is let through, not crashed on
    "echo 'unterminated",
    'echo "unterminated',
    "cat <<EOF",
    # Copilot's review: a substitution is part of its word, so it can name the script; an unquoted heredoc's body is
    # still data, and a quoted delimiter's body runs nothing; a quoted word that looks like an assignment is a command
    "python $(printf '%s' tools/check.py)",
    "python `printf '%s' tools/check.py`",
    "cat <<EOF\npython -c 1\nEOF",
    "cat <<'EOF'\n$(python -c 1)\nEOF",
    'cat <<"EOF"\n`python -c 1`\nEOF',
    'echo "a \\`python -c 1\\` b"',
    '"FOO=1" tools/run.sh',
    # #316: an escaped separator or substitution is text; a shell option's value is not its script
    "echo text\\; python -c 1",
    "echo \\$\\(python -c 1\\)",
    "echo \\`python -c 1\\`",
    "bash -o pipefail script.sh",
    "env --unset PYTHONPATH python tools/check.py",
    "env --unset=PYTHONPATH python tools/check.py",
    "echo a\\&\\& python -c 1",
    "echo a \\| python -c 1",
    "bash -co pipefail 'python tools/check.py'",
    "env -S 'python tools/check.py'",
    # an option with nothing after it runs nothing
    "bash -o",
    "bash -c",
    "bash --rcfile",
    "env -S",
    # Copilot's review of #318: an argument after env -S's value is one word, and an escaped character in a
    # heredoc's delimiter makes its body data
    "env -S echo 'hello; python -c 1'",
    "cat <<E\\ OF\\n$(python -c 1)\\nE OF",
]


@pytest.mark.parametrize("command", REFUSED)
def test_a_command_running_python_without_a_file_is_refused(command: str) -> None:
    assert hook.verdict(command) is not None


@pytest.mark.parametrize("command", ALLOWED)
def test_a_command_running_a_file_or_no_python_is_allowed(command: str) -> None:
    assert hook.verdict(command) is None


# PowerShell's backquote is its escape character, not a substitution: an escaped character is text, and one before
# a newline continues the line (issue #241's false positive)
POWERSHELL_REFUSED = [
    'Write-Host "x`ty"; python -c 1',
    "python `\n  -c 1",
    'pwsh -Command "Write-Host x`ty; python -c 1"',
    # #316: a backslash is not PowerShell's escape, so it neither closes a quote early nor continues a line
    'Write-Host "C:\\"; python -c 1',
    "Write-Host C:\\\npython -c 1",
]

POWERSHELL_ALLOWED = [
    "uv run python `\n  tools/check.py",
    "uv run python `\r\n  tools/check.py",
    'Write-Host "a`nb"; uv run python tools/check.py',
    'Write-Host "a`"b python -c 1"',
    "Write-Host done`; python -c 1",
    # Copilot's review of #248: cmd reads a backquote as text
    "cmd /c 'echo `python -c 1`'",
    'Write-Host "C:\\"; uv run python tools/check.py',
    "C:\\Python314\\python.exe tools\\check.py",
]


@pytest.mark.parametrize("command", POWERSHELL_REFUSED)
def test_a_powershell_command_running_python_without_a_file_is_refused(command: str) -> None:
    assert hook.verdict(command, powershell=True) is not None


@pytest.mark.parametrize("command", POWERSHELL_ALLOWED)
def test_a_powershell_command_running_a_file_or_no_python_is_allowed(command: str) -> None:
    assert hook.verdict(command, powershell=True) is None


def _run(payload: str) -> subprocess.CompletedProcess:
    done = subprocess.run([sys.executable, str(HOOK)], input=payload.encode("utf-8"), capture_output=True, timeout=30)
    return subprocess.CompletedProcess(done.args, done.returncode, done.stdout.decode(), done.stderr.decode("utf-8"))


def test_the_hook_refuses_with_exit_2_and_advice() -> None:
    done = _run(json.dumps({"tool_name": "Bash", "tool_input": {"command": 'python -c "1"'}}))
    assert done.returncode == 2
    assert "entry 48" in done.stderr and "Write tool" in done.stderr
    # Named, so a repository that keeps its own ledger can still find it (a downstream test of 0.11.0).
    assert "the template's failure-modes ledger" in done.stderr
    assert "An interpreter started with nothing to read" in done.stderr


def test_the_hook_allows_with_exit_0_and_says_nothing() -> None:
    done = _run(json.dumps({"tool_name": "PowerShell", "tool_input": {"command": "uv run python tools/check.py"}}))
    assert done.returncode == 0
    assert done.stderr == ""


@pytest.mark.parametrize(("tool", "code"), [("PowerShell", 0), ("Bash", 2)])
def test_the_hook_reads_a_backquote_the_way_the_tool_s_shell_does(tool: str, code: int) -> None:
    command = "echo `python -c 1`"  # Bash runs the substitution; to PowerShell it is text with two escapes
    assert _run(json.dumps({"tool_name": tool, "tool_input": {"command": command}})).returncode == code


def test_a_command_in_utf_8_is_read_as_utf_8_whatever_the_console_s_code_page() -> None:
    done = _run(json.dumps({"tool_input": {"command": "echo 'café œ' && python -c 1"}}, ensure_ascii=False))
    assert done.returncode == 2


@pytest.mark.parametrize(
    "payload",
    [
        "",
        "not json",
        "[1]",
        json.dumps({"tool_input": {}}),
        json.dumps({"tool_input": None}),
        json.dumps({"tool_input": "python -c 1"}),
        json.dumps({"tool_input": ["python -c 1"]}),
        json.dumps({"tool_input": {"command": 3}}),
        "[" * 100_000 + "]" * 100_000,
    ],
    ids=[
        "empty",
        "not-json",
        "a-list",
        "no-command",
        "null-input",
        "string-input",
        "list-input",
        "int-command",
        "deep",
    ],
)
def test_a_payload_it_cannot_read_is_allowed_and_never_crashes(payload: str) -> None:
    done = _run(payload)
    assert done.returncode == 0, done.stderr
    assert done.stderr == ""


def _wired(settings: dict, *, no_config: bool = False) -> bool:
    """Whether a ``PreToolUse`` entry on the shell tools runs this hook, however the rest of the file is laid out.

    With ``no_config``, the entry must also run it with ``uv run --no-config``, so a uv floor cannot refuse it.
    """
    for entry in (settings.get("hooks") or {}).get("PreToolUse") or []:
        if not {"Bash", "PowerShell"} <= set((entry.get("matcher") or "").split("|")):
            continue
        for hook in entry.get("hooks") or []:
            command = hook.get("command", "") if isinstance(hook, dict) else ""
            if not isinstance(command, str) or ".claude/hooks/no_inline_python.py" not in command:
                continue
            if not no_config or _uv_run_skips_its_configuration(command):
                return True
    return False


def _uv_run_skips_its_configuration(command: str) -> bool:
    """Whether ``--no-config`` is one of ``uv run``'s own options in ``command``, before what it runs.

    A command that does not start with ``uv run`` is not refused by a uv floor, so it passes.
    """
    try:
        words = shlex.split(command)
    except ValueError:
        return False
    if words[:2] != ["uv", "run"]:
        return words[:1] != ["uv"]
    options = []
    for word in words[2:]:
        if not word.startswith("-"):
            break
        options.append(word)
    return "--no-config" in options


def test_the_hook_is_wired_where_its_harness_is_enabled() -> None:
    # Ledger entry 27: a shipped hook nothing runs holds nothing. The settings file is the project's own (entry 28), so
    # this reads it as JSON and looks only for the one entry, wherever the project put it among its own settings.
    sys.path.insert(0, str(ROOT / "tools"))
    import framework_config as fc

    if "claude" not in fc.load_framework(ROOT / "framework.toml").harnesses:
        pytest.skip("the harness this hook is for is not enabled in framework.toml")
    settings = ROOT / ".claude" / "settings.json"
    assert settings.is_file(), "no .claude/settings.json: wire the hook (compatibility-matrix.md, entry 48)"
    assert _wired(json.loads(settings.read_text(encoding="utf-8"))), (
        ".claude/settings.json does not run .claude/hooks/no_inline_python.py on Bash|PowerShell: add the entry "
        "compatibility-matrix.md shows (ledger entry 48)"
    )
    # A uv floor in the project's own pyproject.toml refuses every `uv run` below it, the hook's too, unless the
    # hook's command skips uv's configuration (updating.md, 0.11.0). Read from the project's file, not the seed (P-30).
    project = ROOT / "pyproject.toml"
    floor = project.is_file() and tomllib.loads(project.read_text(encoding="utf-8")).get("tool", {}).get("uv", {})
    if floor and floor.get("required-version"):
        assert _wired(json.loads(settings.read_text(encoding="utf-8")), no_config=True), (
            "pyproject.toml sets [tool.uv] required-version, and the hook's command lacks --no-config: a uv below the "
            "floor refuses the hook and every shell call with it (compatibility-matrix.md shows the command)"
        )


@pytest.mark.skipif(not (ROOT / "payload").is_dir(), reason="the template's own: the matrix and the seed agree")
def test_the_matrix_shows_the_entry_the_seed_carries() -> None:
    matrix = (ROOT / "Docs/standards/compatibility-matrix.md").read_text(encoding="utf-8")
    block = matrix.split('```json\n  "PreToolUse": ', 1)[1].split("\n  ```", 1)[0]
    seed = json.loads((ROOT / "payload/.claude/settings.json").read_text(encoding="utf-8"))
    assert json.loads(block) == seed["hooks"]["PreToolUse"]


@pytest.mark.skipif(not (ROOT / "payload").is_dir(), reason="the template's own: the seed's command")
def test_the_seed_s_hook_command_skips_uv_s_configuration() -> None:
    # The hook runs before every shell call, and `[tool.uv] required-version` makes a uv below it refuse even
    # `uv run --no-project`: without `--no-config` the floor would refuse every shell call, `uv self update` included.
    # This holds the command; that it runs under an old uv was proved by hand (the spec's acceptance 5).
    seed = json.loads((ROOT / "payload/.claude/settings.json").read_text(encoding="utf-8"))
    commands = [h["command"] for entry in seed["hooks"]["PreToolUse"] for h in entry["hooks"]]
    assert commands
    assert all(c.startswith("uv run --no-config ") for c in commands), commands


def test_the_wiring_check_can_say_no() -> None:
    assert not _wired({})
    plain = {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Bash|PowerShell",
                    "hooks": [{"command": 'uv run python "$D/.claude/hooks/no_inline_python.py"'}],
                }
            ]
        }
    }
    assert _wired(plain) and not _wired(plain, no_config=True)
    script = '"$D/.claude/hooks/no_inline_python.py"'
    elsewhere = {  # --no-config on another hook of the entry (Copilot's review of #246)
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Bash|PowerShell",
                    "hooks": [{"command": f"uv run python {script}"}, {"command": "uv run --no-config other.py"}],
                }
            ]
        }
    }
    assert _wired(elsewhere) and not _wired(elsewhere, no_config=True)
    after = {
        "hooks": {
            "PreToolUse": [
                {"matcher": "Bash|PowerShell", "hooks": [{"command": f"uv run python {script} --no-config"}]}
            ]
        }
    }
    assert not _wired(after, no_config=True)
    right = {
        "hooks": {
            "PreToolUse": [
                {"matcher": "Bash|PowerShell", "hooks": [{"command": f"uv run --no-config --quiet python {script}"}]}
            ]
        }
    }
    assert _wired(right, no_config=True)
    assert not _wired({"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"command": "x"}]}]}})
    assert _wired(
        {
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "Bash|PowerShell",
                        "hooks": [{"command": 'uv run python "$D/.claude/hooks/no_inline_python.py"'}],
                    }
                ]
            }
        }
    )


def test_a_command_nested_past_the_recursion_limit_fails_open(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    def too_deep(command: str, powershell: bool = False) -> str:
        raise RecursionError

    monkeypatch.setattr(hook, "verdict", too_deep)
    payload = json.dumps({"tool_input": {"command": "python -c 1"}}).encode("utf-8")
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(payload), encoding="utf-8"))
    assert hook.main() == 0
    assert capsys.readouterr().err == ""
