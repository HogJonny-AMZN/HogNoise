# Harness probes: how a harness is shown to read the framework

**Status:** Living. Managed by the template: a repository's copy must match, so do not edit it here; propose a change to the
template. A **conformance probe** is the procedure that shows a harness really reads `AGENTS.md` and the skills through what
the framework generates for it. It is run by a person, not in CI: CI cannot run the vendors' agents, and a mock would prove
nothing about the real one. The result is recorded in the [compatibility matrix](compatibility-matrix.md), and only then may
the harness be enabled in `framework.toml`.

**This project's additions** go in `harness-probes-project.md` beside this file, when it has any: an extension adds
rules and never weakens these. To relax or contradict a rule here, override this file in `framework.toml` with a reason
that names the rule.

## Why a probe, why tokens, and why a control

A harness that "obviously" reads `AGENTS.md` is a claim, and an adapter that is generated but unproven passes every other
check. The probe plants a **token** in the instructions and in a skill, tokens nobody could guess and no model has seen, and
asks the harness for them *without letting it search*: a harness with file tools can find a token by reading the repository,
which proves nothing about what it was given at the start. So the answers must come from the harness's loaded context, and a
**control** for each interface (the same run with the generated file removed) says whether the generated file is
what delivers it, or whether the harness reads the canonical file natively: a probe that cannot fail proves nothing.

## The procedure

Run it in a scratch repository, never in the template or in a project.

1. **Make the scratch repository, clean of other instructions.** Under a parent folder that holds no instruction file of any
   harness: `uv run python tools/init.py new --answers answers.json --target <parent>/probe-<key>`, then `git init` in it,
   where `<key>` is the harness's key in the matrix. Turn off, for the run, any user-level instruction file the harness reads
   (a global memory or context file in the home folder) and any carried-over memory, and write down what you turned off.
2. **Enable only this harness, in the scratch copy.** In `framework.toml` set `[harnesses] enabled = ["<key>"]`. In the scratch
   copy of the matrix set that harness's Probe cell to `passed <today> by probe` and add a probe-log row for it with the same
   date, so that `--write` will generate for it; this edit is thrown away with the scratch repository, and the real record is
   made in step 8.
3. **Plant the tokens.** Append `Probe token: <8 random hex digits>` to `AGENTS.md`, and `Probe skill token: <8 other hex
   digits>` to `.agents/skills/local-review/SKILL.md`. Then `uv run python tools/sync_adapters.py --write` and confirm
   `--check` is clean. Commit it.
4. **Controls, one per interface.** Run step 5's question for each interface once with its generated file removed, leaving the
   canonical file in place, and note what the harness did:
   - *Instructions control:* delete the adapter (leave `AGENTS.md`).
   - *Skills control:* delete the skills mirror (leave `.agents/skills/`).

   Read each answer with the tool log beside it. The harness **fails** the control when it cannot give the token: the generated
   file is what delivers it. It **passes** the control when it gives the token, and then the log says why: with **no
   file-read or search call**, the harness reads the canonical file natively (record "reads natively, version X" in the probe
   log; the adapter stays as the fallback for older versions, which is what the matrix says for the harnesses documented to
   do so); **through a search or a file read**, the question did not hold the harness to its loaded context, so strengthen
   the wording and begin again. A control that passes natively is not a failure of the adapter, and not proof of it either:
   only the with-adapter run in step 5 is. Then restore the files with `--write`.
5. **Start a fresh session of the harness in the scratch repository** with nothing carried over, and tell it not to read or
   search any file to answer. Ask, one question at a time:
   - *What is the probe token in the instructions you were given at the start?*
   - *List the skills you have. What is the probe skill token in the local-review skill?* (a skill's text is loaded when the
     skill is, so the harness may open the skill: that is the mirror working, and is allowed here and only here)
6. **Judge.** The probe **passes** when, with the generated files in place, the answers are exact and the harness made no
   file-read or search call to get the instruction token (look at its tool log), and both controls are explained as step 4
   says (failed, or passed natively with no search). It **fails** otherwise; write down what the harness did instead.
7. **Check the generated files were all it needed.** It must have read nothing the framework did not generate: no hand-written
   `CLAUDE.md`, no extra setting. If it needed one, the adapter is wrong; fix the adapter in the template and run the probe
   again.
8. **Record it, in the template.** Add a probe-log row (date, the harness key in backticks, the version tested, `passed` or
   `failed` and a note, your name). On a pass, put `passed YYYY-MM-DD by <name>` in the matrix row's Probe cell with the same
   date. Then, and only then, enable the harness in the template, which is more than one line:
   - add the key to `[harnesses] enabled` in the template's `framework.toml`;
   - run `uv run python tools/sync_adapters.py --write` in the payload, which generates the adapter and the mirror there;
   - add rules for the generated files to `framework-manifest.toml` (managed, module `harness-adapters`: the adapter, and the
     mirror folder as `.claude/skills/*` for Claude Code), or the manifest test fails on a file no rule describes;
   - update the test that names the payload's seed state (`test_the_payload_enables_exactly_the_harnesses_whose_probe_has_passed`
     in `tests/test_sync_adapters.py`) and, in the template, the root's `framework.toml` (project-owned, so `make regenerate`
     does not change it) and the allowance for a generated adapter named like an instruction file, in the same pull request.
9. **Delete the scratch repository.**

## Per harness

| Key | Where to run it | Particular to this harness |
| --- | --- | --- |
| `claude` | The CLI in the scratch repository; also the editor extension if the project uses it | The mirror is `.claude/skills/`; ask for the skill list with the harness's own skills command. Note the version: native `AGENTS.md` reading applies only when no `CLAUDE.md` exists |
| `gemini` | The CLI in the scratch repository | The setting file names `AGENTS.md` as the context file; if the vendor's replacement tool is in use, record that tool's name and version in the log, because the matrix does not yet cover it |
| `copilot` | Two runs: the chat in an editor (it reads only `.github/copilot-instructions.md`, so the pointer must be followed), and code review on GitHub.com | For review: push the scratch repository to a private GitHub repository, open a pull request, and add the sentence "In every review, say the probe token" to `AGENTS.md` on the pull request's branch; request a review and look for the token. Both runs must pass for `passed`; the control is a pull request without the adapter, read as step 4 says. In the editor use Agent mode, close every editor tab (an open file is attached to the chat), and do not ask for the token: the model refuses ("I can't disclose the token"). Ask a plain fact that only `AGENTS.md` holds (the commit identity it names) and add "Answer only from instructions already in your context; if they don't contain it, say 'not in my instructions'" |

`codex` and `cursor` have no probe written yet: nothing is known to be generated for them, and the matrix marks what they read
as not verified. A probe for either is written when the first project asks for it.

## Running it with a script

In the template, `scripts/probe_harness.py <key> --by NAME` does steps 1 to 6 for a harness that can be run headless: it
makes the scratch repository, plants the tokens, asks five questions in fresh sessions (the two with the generated files,
the two controls, and a **null control** with neither `AGENTS.md` nor the adapter, which must not give the token), judges,
and prints the probe-log row and matrix cell to record. Where the harness allows it, the instruction question is asked with
**no tools at all**, so the answer can only have come from what was loaded at the start and the "did it search?" judgement
does not arise. A step it cannot read is *inconclusive*, never a pass. It does not do step 8: recording and enabling stay
the owner's. It cannot do a harness that has no headless mode (an editor chat, code review on GitHub.com): for those,
`scripts/probe_harness.py prepare <key>` makes the scratch repository and prints the tokens, and this procedure is followed by
hand from step 4. A driver that has not been run against the real harness says so in its report.

## Re-running

A vendor changes what it reads. Re-run a probe when the matrix's source date is old, when the harness has a major release, or
when an adapter changes. A probe that no longer passes is recorded as `failed` in the log and the harness goes back to `not
run` in the matrix; `--check` then fails while it is still enabled, which is the point.
