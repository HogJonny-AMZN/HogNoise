"""
Framework: a Claude Code PreToolUse hook that refuses a shell command running Python with no script file.
Package: .claude/hooks/no_inline_python

Run by the harness, not imported.
The failure-modes ledger's entry 48: an interpreter whose script arrives on stdin (``python -``, a heredoc, a pipe, a
bare ``python``) waits for ever when the script comes out empty, and ``python -c`` is the same habit one step removed.
A rule in an agent's brief did not hold (five subagents broke it in one session), so this hook holds it for every agent
in the session. It reads the hook's JSON on stdin; exit 2 with a message on stderr refuses the call and tells the agent
what to do instead; exit 0 lets it run. Stdlib only, so it starts fast and needs no environment.

The command is read the way a shell reads it, enough for this question: words with their quotes removed, separators
(``;``, ``&``, ``|``, newlines, ``(``, ``)``), redirections with their targets, comments, and heredoc bodies, which
are data. A command substitution (``$(...)``, or backquotes in Bash) runs wherever it is not single-quoted, an
unquoted heredoc's body included, so each is judged as a command of its own. Each simple command is then judged by
its command word, after assignments and wrappers (``uv run``, ``env``, ``exec``, ``time``, ``nohup``,
``command``, ``xargs``, ``sudo``); ``cmd /c``'s command, a shell's ``-c`` script and PowerShell's ``-Command``
are judged too. Bash and PowerShell differ in places: in Bash a backslash outside quotes makes a quote, a
separator, a space or a substitution text and is kept before any other character, so Windows paths survive; a
command from the PowerShell tool reads a backquote as PowerShell's escape character (an escaped character is
text, and one before a newline continues the line), not as a substitution, and a backslash as text. Neither is
parsed in full, only as far as finding the Python a command starts.

Wired in ``.claude/settings.json`` as a ``PreToolUse`` hook on ``Bash|PowerShell`` (``updating.md``, 0.11.0). Run
standalone with the hook's JSON on stdin (exit code 0 allowed, 2 refused)::

    uv run --no-project python .claude/hooks/no_inline_python.py < payload.json
"""

from __future__ import annotations

import json
import logging as _logging
import re
import shlex
import sys

# -------------------------------------------------------------------------
# module global scope
_MODULE_NAME = "claude.hooks.no_inline_python"
__version__ = "0.1.0"
__updated__ = "2026-11-25"
_LOGGER = _logging.getLogger(_MODULE_NAME)  # declared by the standard; the advice on stderr is the hook's record

_ADVICE = (
    # The template's entry, by its name: a repository that keeps its own failure-modes.md may have no entry 48.
    "Refused by the no-inline-python hook (the template's failure-modes ledger, entry 48, An interpreter started "
    "with nothing to read): {why}. Write the script to a "
    "file in your scratchpad with the Write tool, then run the file, e.g. `uv run python <scratchpad>/probe.py`."
)

_INLINE = "`python -c` runs a script written inline"
_STDIN_DASH = "`python -` reads its script from stdin"
_NO_SCRIPT = "Python with no script file reads one from stdin (a heredoc, a redirect, a pipe or the terminal)"

_REDIRECT = re.compile(r"<<<|<<-|<<|<>|<&|<|>>|>&|>\||>|&>>|&>")
_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
_PYTHON = re.compile(r"(?:python[0-9.]*w?|pyw?)(?:\.exe)?")
_SHELLS = {"bash", "sh", "zsh", "dash", "bash.exe", "sh.exe"}
_POWERSHELLS = {"pwsh", "powershell", "pwsh.exe", "powershell.exe"}
# A backslash outside quotes makes the next character text in Bash. The hook consumes it only before a character the
# shell would read specially, and keeps it before any other, so C:\\Python314\\python.exe keeps its path.
_BASH_ESCAPED = frozenset(" \t'\"\\;&|()<>$`#*?[]{}!~-")
# A shell's long options that take the next word as their value; -o and -O take it too, from anywhere in a cluster
_SHELL_VALUED_LONG = {"--rcfile", "--init-file"}
_KEYWORDS = {"{", "}", "!", "if", "then", "else", "elif", "do", "while", "until", "nohup"}
# uv's own options before ``run`` that take the next word as their value
_UV_GLOBAL_VALUED = {"--directory", "--project", "--cache-dir", "--config-file", "--color", "--python", "-p"}
# the Windows launcher's queries: they list interpreters, they run no script
_PY_LAUNCHER_QUERIES = re.compile(r"-0p?|--list(?:-paths)?")
# uv run's options that take the next word as their value; every other option is a flag
_UV_VALUED = {
    "--extra", "--no-extra", "--with", "--with-editable", "--with-requirements", "--python", "-p", "--package",
    "--group", "--only-group", "--no-group", "--directory", "--project", "--env-file", "--index", "--default-index",
    "--index-url", "--extra-index-url", "--find-links", "-f", "--config-file", "--cache-dir", "--color",
    "--prerelease", "--resolution", "--index-strategy", "--keyring-provider", "--exclude-newer", "--link-mode",
    "--refresh-package", "--upgrade-package", "-P", "--reinstall-package", "--no-binary-package",
    "--no-build-package", "--config-setting", "-C",
}  # fmt: skip
# The wrappers #241 named: the short letters and long options that take a value, and the options that make the
# wrapper a query that runs nothing. A GNU long option whose value is optional (xargs --replace) takes it only with =.
_XARGS_VALUED = (
    "adEILnPs",
    {"--arg-file", "--delimiter", "--max-args", "--max-procs", "--max-chars", "--process-slot-var"},
)
_SUDO_VALUED = (
    "ugCDhprtUTR",
    {
        "--user",
        "--group",
        "--close-from",
        "--chdir",
        "--prompt",
        "--role",
        "--type",
        "--other-user",
        "--command-timeout",
        "--chroot",
        "--host",
    },
)
_SUDO_QUERIES = ("lvV", {"--list", "--validate", "--version"})
# env's, exec's and time's options that take the next word as their value (a long one with = carries its own);
# env's -S and --split-string carry a command instead, which is judged
_ENV_VALUED = {"-u", "-C", "-a", "-P", "--unset", "--chdir", "--argv0", "-o", "-f", "--output", "--format"}
_PY_SAFE_LONG = {"--version", "--help", "--help-env", "--help-xoptions", "--help-all"}
_PY_VALUED_LONG = {"--check-hash-based-pycs"}

# a word is (text, quoted); a redirection is (operator, None)
Token = tuple[str, "bool | None"]


def verdict(command: str, powershell: bool = False) -> str | None:
    """Why ``command`` is refused, or ``None`` when every Python it starts runs a file, a module or a query.

    ``powershell`` is true for a command PowerShell runs, whose backquote is an escape character.
    """
    substitutions: list[str] = []
    for tokens in _simple_commands(command, substitutions, powershell):
        why = _judge_command(_without_redirections(tokens))
        if why:
            return why
    for inner in substitutions:
        why = verdict(inner, powershell)
        if why:
            return why
    return None


def _substitution(command: str, start: int, escape: str = "\\") -> tuple[str, int]:
    """The text of the ``$(...)`` whose ``(`` is at ``start``, and the index after its ``)``.

    Parentheses are balanced outside quotes, escapes and comments, as the shell balances them: a ``)`` inside
    ``')'`` does not close the substitution. ``escape`` is the shell's escape character.
    """
    depth, i, n = 1, start + 1, len(command)
    while i < n and depth:
        ch = command[i]
        if ch == escape:
            i += 2
            continue
        if ch == "'":
            close = command.find("'", i + 1)
            i = n if close < 0 else close + 1
            continue
        if ch == '"':
            i += 1
            while i < n and command[i] != '"':
                i += 2 if command[i] == escape else 1
            i += 1
            continue
        if ch == "#" and (i == start + 1 or command[i - 1] in " \t\n;&|("):
            close = command.find("\n", i)
            i = n if close < 0 else close
            continue
        depth += {"(": 1, ")": -1}.get(ch, 0)
        i += 1
    i = min(i, n)
    return command[start + 1 : i - 1 if not depth else i], i


def _backquote(command: str, start: int) -> tuple[str, int]:
    """The text of the backquoted substitution whose opening backquote is at ``start``, and the index after it.

    A backslash before a backquote, ``$`` or backslash escapes it, as Bash reads the old form.
    """
    inner: list[str] = []
    i, n = start + 1, len(command)
    while i < n and command[i] != "`":
        if command[i] == "\\" and i + 1 < n and command[i + 1] in "`$\\":
            i += 1
        inner.append(command[i])
        i += 1
    return "".join(inner), min(i + 1, n)


def _expanded_substitutions(text: str, substitutions: list[str]) -> None:
    """Append each ``$(...)`` and backquoted command in ``text``, read as an unquoted heredoc's body is expanded."""
    i, n = 0, len(text)
    while i < n:
        if text[i] == "\\":
            i += 2
        elif text[i] == "$" and i + 1 < n and text[i + 1] == "(":
            inner, i = _substitution(text, i + 1)
            substitutions.append(inner)
        elif text[i] == "`":
            inner, i = _backquote(text, i)
            substitutions.append(inner)
        else:
            i += 1


def _simple_commands(command: str, substitutions: list[str], powershell: bool = False) -> list[list[Token]]:
    """Split ``command`` into simple commands of words and redirection operators, skipping comments and heredocs.

    A ``$(...)`` or backquoted command runs wherever it is not single-quoted: in a word, inside double quotes and in
    an unquoted heredoc's body. It stays part of its word, as the shell expands it there, and its text is appended to
    ``substitutions`` to be judged on its own. A word's flag is true when a quote came before it could be read as an
    assignment (``NAME=``) or a keyword, so ``FOO="a b" python`` still reaches ``python`` and ``"FOO=1"`` does not.
    When ``powershell`` is true a backquote escapes the next character instead, and before a newline continues the
    line.
    """
    commands: list[list[Token]] = []
    tokens: list[Token] = []
    buf: list[str] = []
    state = {"in_word": False, "quoted": False, "want_delimiter": None, "prefix": None, "delimiter_at": 0}
    heredocs: list[tuple[str, bool, bool]] = []  # (delimiter, strip tabs, body expanded)
    i, n = 0, len(command)
    escape = "`" if powershell else "\\"

    def start_quote() -> None:
        if state["prefix"] is None:
            state["prefix"] = sum(len(part) for part in buf)
        state["in_word"] = state["quoted"] = True

    def end_word() -> None:
        if state["in_word"]:
            text = "".join(buf)
            if state["want_delimiter"]:
                # A delimiter's quotes and backslashes are removed and nothing in it runs; either makes the body data.
                del substitutions[state["delimiter_at"] :]
                escaped = "\\" in text and not powershell
                body_runs = not (state["quoted"] or escaped)
                heredocs.append(
                    (text.replace("\\", "") if escaped else text, state["want_delimiter"] == "<<-", body_runs)
                )
                state["want_delimiter"] = None
            lead = text[: state["prefix"]] if state["prefix"] is not None else text
            tokens.append((text, state["quoted"] and not _ASSIGNMENT.match(lead)))
        buf.clear()
        state["in_word"] = state["quoted"] = False
        state["prefix"] = None

    def end_command() -> None:
        end_word()
        if tokens:
            commands.append(list(tokens))
        tokens.clear()

    while i < n:
        ch = command[i]
        nxt = command[i + 1] if i + 1 < n else ""
        if ch == "'":
            start_quote()
            close = command.find("'", i + 1)
            close = n if close < 0 else close
            buf.append(command[i + 1 : close])
            i = close + 1
        elif ch == '"':
            start_quote()
            i += 1
            while i < n and command[i] != '"':
                if powershell and command[i] == "`":
                    buf.append(command[i + 1 : i + 2])  # an escaped character is text
                    i += 2
                    continue
                if command[i] == "$" and i + 1 < n and command[i + 1] == "(":
                    inner, after = _substitution(command, i + 1, escape)
                    substitutions.append(inner)
                    buf.append(command[i:after])
                    i = after
                    continue
                if command[i] == "`":
                    inner, after = _backquote(command, i)
                    substitutions.append(inner)
                    buf.append(command[i:after])
                    i = after
                    continue
                if not powershell and command[i] == "\\" and i + 1 < n and command[i + 1] in '"\\$`':
                    i += 1
                buf.append(command[i])
                i += 1
            i += 1
        elif powershell and ch == "`":
            if nxt == "\n" or command.startswith("\r\n", i + 1):
                i += 2 if nxt == "\n" else 3  # a continued line
            else:
                start_quote()  # an escaped character is text
                buf.append(nxt)
                i += 2
        elif not powershell and ch == "\\" and nxt == "\n":
            i += 2  # a continued line
        elif not powershell and ch == "\\" and nxt and nxt in _BASH_ESCAPED:
            start_quote()  # an escaped quote, separator, space or substitution is text, and quotes its word
            buf.append(nxt)
            i += 2
        elif ch in " \t\r":
            end_word()
            i += 1
        elif ch == "#" and not state["in_word"]:
            close = command.find("\n", i)
            i = n if close < 0 else close
        elif ch == "\n":
            end_command()
            i += 1
            for delimiter, strip_tabs, expanded in heredocs:
                body: list[str] = []
                while i < n:
                    close = command.find("\n", i)
                    line = command[i : n if close < 0 else close].rstrip("\r")
                    i = n if close < 0 else close + 1
                    if (line.lstrip("\t") if strip_tabs else line) == delimiter:
                        break
                    body.append(line)
                if expanded:  # an unquoted delimiter: the body's text is data, its substitutions run, across lines too
                    _expanded_substitutions("\n".join(body), substitutions)
            heredocs.clear()
        elif ch in "<>" or (ch == "&" and nxt == ">"):
            if state["in_word"] and not state["quoted"] and "".join(buf).isdigit():
                buf.clear()  # a file descriptor: 2>&1
                state["in_word"] = False
            end_word()
            op = _REDIRECT.match(command, i).group()
            tokens.append((op, None))
            if op in ("<<", "<<-"):
                state["want_delimiter"] = op
                state["delimiter_at"] = len(substitutions)
            i += len(op)
        elif ch in ";&|()":
            end_command()
            i += 2 if (ch + nxt) in ("&&", "||", "|&", ";;") else 1
        elif (ch == "$" and nxt == "(") or (ch == "`" and not powershell):
            inner, after = _substitution(command, i + 1, escape) if ch == "$" else _backquote(command, i)
            substitutions.append(inner)
            buf.append(command[i:after])  # the word keeps its substitution: python $(echo x.py) runs x.py
            state["in_word"] = True
            i = after
        else:
            buf.append(ch)
            state["in_word"] = True
            i += 1
    end_command()
    return commands


def _without_redirections(tokens: list[Token]) -> list[tuple[str, bool]]:
    """The words of a simple command once each redirection and its target are removed, as the shell removes them."""
    words: list[tuple[str, bool]] = []
    skip = False
    for text, quoted in tokens:
        if quoted is None:
            skip = True
        elif skip:
            skip = False
        else:
            words.append((text, quoted))
    return words


def _name(text: str) -> str:
    """A command word's program name: the last path component, lower case."""
    return re.split(r"[/\\]", text)[-1].lower()


def _judge_command(words: list[tuple[str, bool]]) -> str | None:
    """Why this simple command runs Python with no script file, or ``None``."""
    i = 0
    while i < len(words):
        text, quoted = words[i]
        name = _name(text)
        if not quoted and (_ASSIGNMENT.match(text) or text in _KEYWORDS):
            i += 1
        elif name == "uv":
            i += 1
            while i < len(words) and words[i][0].startswith("-"):  # uv's own options: uv --quiet run ...
                i += 2 if words[i][0] in _UV_GLOBAL_VALUED else 1
            if i >= len(words) or words[i][0] != "run":
                return None  # uv sync, uv pip...: no interpreter of ours
            i += 1
            while i < len(words) and words[i][0].startswith("-"):
                option = words[i][0]
                if option == "--":
                    i += 1
                    break
                if option in ("-m", "--module"):
                    return None  # uv run -m: a module
                i += 2 if option in _UV_VALUED else 1
        elif name in ("env", "time", "exec"):
            i += 1
            while i < len(words) and (words[i][0].startswith("-") or _ASSIGNMENT.match(words[i][0])):
                option = words[i][0]
                split = _split_string(option, words, i)
                if split is not None:
                    return _judge_command(split)  # env -S: its value split into words, then the words after it
                i += 2 if option in _ENV_VALUED else 1
        elif name in ("timeout", "nice"):
            i += 1
            while i < len(words) and words[i][0].startswith("-"):
                i += 2 if words[i][0] in ("-n", "-s", "-k", "--signal", "--kill-after", "--adjustment") else 1
            if name == "timeout":
                i += 1  # the duration
        elif name in ("xargs", "sudo"):
            after = _past_options(words, i + 1, *(_XARGS_VALUED if name == "xargs" else _SUDO_VALUED),
                                  *(("", set()) if name == "xargs" else _SUDO_QUERIES))  # fmt: skip
            if after is None:
                return None  # sudo -l, -v, -V: a query, nothing runs
            i = after
        elif name in ("cmd", "cmd.exe"):
            for k in range(i + 1, len(words)):
                if words[k][0].lower() in ("/c", "/k"):
                    rest = words[k + 1 :]
                    # One word is cmd's whole line, read as cmd reads it; several keep the boundaries the shell gave.
                    return _judge_cmd_line(rest[0][0]) if len(rest) == 1 else _judge_command(rest)
                if not words[k][0].startswith("/"):
                    return None
            return None
        elif name == "command":
            i += 1
            while i < len(words) and words[i][0].startswith("-"):
                if words[i][0] in ("-v", "-V"):
                    return None  # a query: it names the program, it does not run it
                i += 1
        elif name in _SHELLS:
            return _judge_shell([w for w, _ in words[i + 1 :]])
        elif name in _POWERSHELLS:
            return _judge_powershell([w for w, _ in words[i + 1 :]])
        elif _PYTHON.fullmatch(name) or _PYTHON.fullmatch(_name(text.replace("\\", ""))):
            args = [w for w, _ in words[i + 1 :]]
            if (
                name.startswith("py")
                and not name.startswith("python")
                and args
                and _PY_LAUNCHER_QUERIES.fullmatch(args[0])
            ):
                return None  # py -0p, py --list: the launcher lists interpreters
            return _judge_python(args)
        else:
            return None
    return None


def _split_string(option: str, words: list[tuple[str, bool]], i: int) -> list[tuple[str, bool]] | None:
    """The words ``env -S`` or ``--split-string`` runs, or ``None`` when ``option`` is neither.

    The value is split into words as env splits it (whitespace, quotes, backslash escapes; ``\\_`` separates words, as
    GNU env reads it outside double quotes), not read as shell syntax, and the words after it follow with their
    boundaries kept.
    """
    if option in ("-S", "--split-string"):
        value, rest = (words[i + 1][0], i + 2) if i + 1 < len(words) else ("", i + 1)
    elif option.startswith("--split-string="):
        value, rest = option.split("=", 1)[1], i + 1
    elif option.startswith("-S"):
        value, rest = option[2:], i + 1
    else:
        return None
    try:
        split = shlex.split(value.replace("\\_", " "))
    except ValueError:  # an unclosed quote: env refuses it, so split on whitespace and judge what is there
        split = value.split()
    return [(word, False) for word in split] + words[rest:]


def _past_options(
    words: list[tuple[str, bool]], i: int, valued: str, valued_long: set[str], queries: str, query_long: set[str]
) -> int | None:
    """The index of the first word after a wrapper's options from ``i``, or ``None`` when one makes it a query.

    A short option cluster (``-Eu``) is read letter by letter: a letter that takes a value takes the rest of the word,
    or the next word when nothing is left.
    A long option takes the next word only when it needs a value and has no ``=``.
    """
    while i < len(words) and words[i][0].startswith("-") and words[i][0] != "-":
        option = words[i][0]
        i += 1
        if option == "--":
            break
        if option.startswith("--"):
            name = option.split("=", 1)[0]
            if name in query_long:
                return None
            if name in valued_long and "=" not in option:
                i += 1
            continue
        letters = option[1:]
        for at, letter in enumerate(letters):
            if letter in queries:
                return None
            if letter in valued:
                if at == len(letters) - 1:
                    i += 1
                break
    return i


def _judge_cmd_line(line: str) -> str | None:
    """``cmd /c``'s command given as one string, read as cmd reads it: ``&`` and ``|`` (doubled or not) separate
    commands outside double quotes, a double quote groups a word, and a backquote or a single quote is text."""
    commands: list[list[tuple[str, bool]]] = [[]]
    buf: list[str] = []
    quoted = in_quote = False

    def end_word() -> None:
        nonlocal quoted
        if buf or quoted:
            commands[-1].append(("".join(buf), quoted))
        buf.clear()
        quoted = False

    for ch in line:
        if ch == '"':
            in_quote, quoted = not in_quote, True
        elif in_quote:
            buf.append(ch)
        elif ch in "&|":
            end_word()
            if commands[-1]:
                commands.append([])
        elif ch in " \t":
            end_word()
        else:
            buf.append(ch)
    end_word()
    for words in commands:
        reason = _judge_command(words) if words else None
        if reason:
            return reason
    return None


def _judge_shell(args: list[str]) -> str | None:
    """A shell's ``-c`` script is judged as a command of its own.

    The options are read as the shell reads them, all of them first: each ``o`` or ``O`` in a cluster takes the next
    word as its value (``-o pipefail``, ``-ox pipefail``, ``+O extglob``), as ``--rcfile FILE`` does, and a ``c``
    anywhere says the first plain word after the options is the script (``bash -co pipefail '...'``). Without ``c`` that
    word is a script file.
    """
    script = False
    k = 0
    while k < len(args):
        arg = args[k]
        k += 1
        if arg == "--":
            break
        if arg in _SHELL_VALUED_LONG:
            k += 1
        elif arg.startswith("--"):
            continue  # --login, --norc: a flag
        elif len(arg) > 1 and arg[0] in "-+":
            script = script or (arg[0] == "-" and "c" in arg[1:])
            k += sum(letter in "oO" for letter in arg[1:])
        else:
            k -= 1  # the first plain word
            break
    return verdict(args[k]) if script and k < len(args) else None


def _judge_powershell(args: list[str]) -> str | None:
    """PowerShell's ``-Command`` (any prefix of it, any case) is judged as a command of its own."""
    for k, arg in enumerate(args):
        if len(arg) > 1 and "-command".startswith(arg.lower()) and k + 1 < len(args):
            return verdict(" ".join(args[k + 1 :]), powershell=True)
    return None


def _judge_python(args: list[str]) -> str | None:
    """The reason the interpreter's arguments ``args`` read a script from somewhere other than a file, or ``None``.

    Options are read the way CPython reads them, left to right: ``-c`` and ``-m`` end the options, ``-W`` and ``-X``
    take the rest of their word as their value, or the next word when nothing is left.
    """
    k = 0
    while k < len(args):
        arg = args[k]
        k += 1
        if arg == "-":
            return _STDIN_DASH
        if arg.startswith("--"):
            option = arg.split("=", 1)[0]
            if option in _PY_SAFE_LONG:
                return None
            if option in _PY_VALUED_LONG and "=" not in arg:
                k += 1
            continue
        if arg.startswith("-"):
            letters = arg[1:]
            for at, letter in enumerate(letters):
                if letter == "c":
                    return _INLINE
                if letter in "mhV?":
                    return None  # a module, or a help or version query
                if letter in "WXQ":
                    if at == len(letters) - 1:
                        k += 1  # the value is the next word
                    break  # the value is the rest of this word
            continue
        return None  # the first plain word is the script file
    return _NO_SCRIPT


def main() -> int:
    """The hook: 2 with advice on stderr to refuse, 0 to allow. Anything it cannot read or parse is allowed: a guard
    that crashed would only show the agent a traceback, so it fails open, on purpose, with exit 0."""
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8", errors="replace"))
    except (ValueError, RecursionError):  # not JSON, or nested past the parser's depth
        return 0
    tool_input = payload.get("tool_input") if isinstance(payload, dict) else None
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str):
        return 0
    try:
        why = verdict(command, powershell=payload.get("tool_name") == "PowerShell")
    except RecursionError:  # shells nested past the recursion limit
        return 0
    if why is None:
        return 0
    print(_ADVICE.format(why=why), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
