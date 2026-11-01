# Compatibility matrix: what each harness reads

**Status:** Living. Managed by the template: a repository's copy must match, so do not edit it here; propose a change to the
template. It is the one place that names the coding-assistant harnesses: what each reads, where that was learned, what the
framework generates for it, and whether its conformance probe has passed. Every other managed document is harness-neutral
(`tools/sync_adapters.py --check` fails on a name outside this file and [harness-probes.md](harness-probes.md)).

**This project's additions** go in `compatibility-matrix-project.md` beside this file, when it has any: an extension
adds rules and never weakens these. To relax or contradict a rule here, override this file in `framework.toml` with a
reason that names the rule.

## The rule

**`AGENTS.md` is the only context.** A harness that reads it natively gets nothing generated. One that does not gets a
generated adapter that points to it and holds nothing else (the Gemini settings file may also hold the project's own
settings, as long as it names `AGENTS.md` as a context file). Skills live in `.agents/skills/`; a harness that reads them
from another folder gets a generated mirror (a copy of the tree, compared byte for byte; line endings are normalised for text
files only). `tools/sync_adapters.py --write` generates both for the harnesses `framework.toml` enables, and `--check` fails
on an adapter with text of its own, a mirror that differs, or a stray one.

**A harness is enabled in `framework.toml` only after its conformance probe has passed**, with the date and who ran it in the
last column below and a matching `passed` entry in the probe log. `--check` fails on an enabled harness whose probe has not
passed (one matrix row, a real date that is not in the future, a name, and the log entry), and `--write` refuses to generate
for it. A harness whose probe has not been run is *planned* and gets no adapter. How to run a probe:
[harness-probes.md](harness-probes.md).

## The matrix

What each harness reads was taken from the vendor's own pages on the date given; a vendor can change it, so the date is part
of the fact. The tooling reads only the Key column (the harness key in backticks) and the Probe column (`not run`, or
`passed YYYY-MM-DD by <name>`), and only in the table under this heading. The wording "documented" and "not documented" is
deliberate: a page that does not mention a path is not proof that the harness ignores it.

| Harness | Key | Reads for instructions | Reads skills from | Source, checked | The framework generates | Probe |
| --- | --- | --- | --- | --- | --- | --- |
| Claude Code | `claude` | `CLAUDE.md`; `AGENTS.md` natively from 2.1.277, but only when no `CLAUDE.md` exists; `@path` imports work (four hops) | Documented: `.claude/skills/<name>/SKILL.md`; `.agents/skills` is not documented | [memory](https://code.claude.com/docs/en/memory), [skills](https://code.claude.com/docs/en/skills), 2026-10-09 | `CLAUDE.md` (a pointer, `@AGENTS.md`) and the `.claude/skills/` mirror | passed 2026-10-15 by HogJonny-AMZN (headless probe script) |
| Gemini CLI | `gemini` | `GEMINI.md`; `context.fileName` in `.gemini/settings.json` takes a string or an array and accepts `AGENTS.md` | `.gemini/skills/`, or the alias `.agents/skills/` (the alias wins) | [GEMINI.md](https://geminicli.com/docs/cli/gemini-md/), [skills](https://geminicli.com/docs/cli/skills/), [configuration](https://geminicli.com/docs/reference/configuration/), 2026-10-09 | `.gemini/settings.json` (a pointer, `AGENTS.md` as the context file) | not run |
| GitHub Copilot | `copilot` | Code review on GitHub.com reads `.github/copilot-instructions.md`, `.github/instructions/**/*.instructions.md` and `AGENTS.md`; in VS Code and Visual Studio it reads `.github/copilot-instructions.md` (VS Code also documents `AGENTS.md` behind the setting `chat.useAgentsMdFile`, off by default); the cloud agent reads `AGENTS.md` (the nearest wins) | `.github/skills`, `.claude/skills` or `.agents/skills`; code review is documented to use `.github/skills` | [support matrix](https://docs.github.com/en/copilot/reference/custom-instructions-support), [code review](https://docs.github.com/en/copilot/concepts/agents/code-review), [skills](https://docs.github.com/en/copilot/concepts/agents/about-agent-skills), 2026-10-09 | `.github/copilot-instructions.md` (a pointer to `AGENTS.md`) | passed 2026-10-17 by jonny verified (editor chat only) |
| Codex | `codex` | not verified (believed to read `AGENTS.md`) | not verified | not yet verified | nothing | not run |
| Cursor | `cursor` | not verified (believed to read `AGENTS.md`) | not verified | not yet verified | nothing | not run |

## What follows from the matrix

- **`.agents/skills/` is canonical.** Gemini CLI documents it and Copilot's agents document it (Copilot code review is
  documented to use `.github/skills`, which a probe has to settle); only Claude Code is documented to need the generated mirror.
- **The Copilot adapter stays**, although code review on GitHub.com reads `AGENTS.md` itself: the IDE paths do not, and the
  adapter is what they read. Review reads the head branch of the pull request, so an adapter change takes effect once pushed.
- **Claude Code's native `AGENTS.md` reading is no reason to drop `CLAUDE.md`**: it applies only when no `CLAUDE.md` exists, and
  only from the version named, so a one-line `CLAUDE.md` is the fallback for older versions and for a repository that
  already has one.
- **Not checked:** whether the tool that replaces Gemini CLI for some users (a banner on its documentation says it was
  replaced on 2026-06-18) behaves the same, and what Codex and Cursor read beyond `AGENTS.md`. The rows say `not verified`
  until a probe says otherwise.

## Probe log

Every probe run, passed or failed, newest last. One row per run: the date (`YYYY-MM-DD`), the harness key in backticks, the
version tested, the result (`passed` or `failed`, then any note) and who ran it. A `passed` entry whose date equals the
matrix's `passed` date is what backs an enabled harness; the matrix above holds only the latest passing result per harness.

| Date | Harness | Version tested | Result | Run by |
| --- | --- | --- | --- | --- |
| 2026-10-17 | `copilot` | VS Code 1.140.0 (Copilot Chat, `@github/copilot` 1.0.89-7) | passed for the editor chat only, by hand: Agent mode, an auto-routed GPT-6 Luna. With the adapter present Copilot opened `AGENTS.md` through the pointer (it asked permission) and gave the commit identity only `AGENTS.md` holds; with the adapter deleted it still gave it, under the strict wording. Whether it loaded `AGENTS.md` natively or read it was NOT established: its step list was not recorded (the second step was an unrelated MCP server signing in) and the owner believes it reads `AGENTS.md` natively, so the adapter is at least the fallback. A token question was refused ("I can't disclose the token"), so the question asks for a plain fact instead. Code review on GitHub.com NOT run (the procedure asks for both; the owner recorded the pass without it); the null control was not run | jonny verified |
| 2026-10-15 | `claude` | 2.1.283 | passed: instructions natively (the token came back with the adapter removed, no tool offered); skills through the generated mirror (`local-review` absent from the skill list without it); null control UNKNOWN; headless by `scripts/probe_harness.py`, model haiku | HogJonny-AMZN (headless probe script) |
