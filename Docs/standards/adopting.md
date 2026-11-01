# Adopting a repository that predates the template

**Status:** Living. Managed by the template: a repository's copy must match, so do not edit it here; propose a change to the
template. `init adopt` brings an existing repository under the template without losing anything it owns. A repository made
with `init new` never needs it; this is for the ones that were written first and learned the practices the hard way.

**This project's additions** go in `adopting-project.md` beside this file, when it has any: an extension adds rules and
never weakens these. To relax or contradict a rule here, override this file in `framework.toml` with a reason that names
the rule.

## What adoption is, and is not

It is **one reviewable diff**: the template's managed files are added or reconciled, the lock records what the template
would write, and every file where the repository differs on purpose carries an **override** with a reason. After it,
`tools/framework_sync.py --check` passes, `--upstream` can tell the repository when the template has moved on, and
`init new` over the result changes nothing.

It does not rewrite the repository's own documents, code or history, run `uv sync` or the repository's checks, commit, or push.
A project-owned file (a README, `pyproject.toml`, the board, the handoff) is **never overwritten**: if it is absent it is
seeded, and if it is present it is left alone.

## The steps

1. **Answers.** An `answers.json` in the `project.json` schema: the name, slug, owner, default branch, whether commits are
   signed off, and any identifiers the hygiene check must refuse.
2. **The report (nothing is written).** From the template's checkout:
   `uv run python payload/tools/init.py adopt --target <the repository> --answers answers.json [--off specimens]`.
   Each file the template would write is one of: `identical` (already what the template would write), `differs` (a managed or
   parametrised file with other content, with how many lines), `missing` (would be added), `seed-present` / `seed-absent` (a
   project-owned file the repository has / lacks), `skipped` (its module is off) or `blocked` (a file where a directory
   belongs, a symlinked folder that leaves the repository, a name that differs only in capitalisation, an unknown token, no
   rule: resolve it first). The report starts with the counts, then the `differs` files largest first, then the rest counted
   per folder (`-v` lists every file; `--json` gives every entry). `--diff PATH` shows how one file differs. Run it on a
   **copy** the first time, read the `differs` list, and decide per file.
3. **Leave out what does not apply.** `--off MODULE` leaves a module off (a repository with its own source layout turns
   `specimens` off, so the mock `src/` is neither added nor reported). A module the seeded documents link to (`journal`,
   `python-uv`, `graph`, `harness-adapters`) cannot be off: the report says so as `blocked`. Turning `specimens` off also
   drops the seeded `[layers]` table, which names the mock `src/`: if the repository has a `src/` the table is written from
   the packages found there **in alphabetical order, a placeholder**, and the apply says to set the real order (see *Layers*
   in `python.md`); the boundary test then holds the repository to it.
4. **Apply.** On the root of a clean git working tree (it refuses otherwise, so that the adoption is one diff, and it refuses
   a path the repository's `.gitignore` would hide from that commit, such as `*.lock` or a generated folder): the same command with
   `--apply`. It adds what is missing, seeds what is absent, writes `project.json`, `framework.toml` (the repository must not
   have one yet) and `framework.lock`, and for each `differs` file records an override: `adopted: differs from template X;
   reconcile`. `--take PATH` (repeatable) or `--take-all` takes the template's version of a differing file instead.
5. **Commit it on a branch** and open one pull request. Nothing was committed for you.
6. **Reconcile the overrides, one at a time.** Each is a decision, and each is its own commit:
   - *take the template's*: copy it over, delete the override (the sync check calls a stale override a finding);
   - *extend*: the repository only adds rules; move them into the extension the base names (`python-project.md`
     beside `python.md`, `project.md` in a skill's folder), copy the template's base over, delete the override. An
     update never touches an extension;
   - *keep the repository's*: it contradicts or relaxes a rule of the template's; leave the override and make its
     reason name that rule. A reason that says only "reconcile" is a to-do, not a reason;
   - *improve the template*: the repository's version is better; propose it to the template and take it back when it lands.

## What the files mean afterwards

`framework.lock` holds the **template's** hash of every managed and parametrised file, including the ones the repository
overrides, so an override is a standing difference from the template and not a difference from the lock. The sync check lists
every override in force on every run; a growing list is the repository drifting.

An override is the repository's own text, and the checks treat it so: the neutrality check (no managed document names a
harness) does not read an overridden file, and a test that pins the framework's wording of a document skips, with the
reason shown, while that document is overridden (`tests/pins.py`, `@pins("Docs/standards/workflow.md")`). The skip ends
when the override does. What an override cannot excuse is a generated adapter (an enabled harness's pointer file holds no text of its
own) or a skills mirror: override the canonical `.agents/skills/` file and regenerate the mirror instead.

## When it refuses

- the target is not the root of a git working tree, or has uncommitted changes (commit or stash first);
- it already has a `framework.toml` or a `framework.lock` (it is adopted, made, or half adopted: to take a newer release into one, see [updating.md](updating.md); after a failed
  adoption restore the tree first);
- the `.gitignore` would hide a file the adoption writes (change the rule, or `git add -f` after);
- a file is blocked (the report names it);
- `--take` names a file that does not differ, or `--off` names a module that cannot be off.

Nothing is written when it refuses. If a write fails part-way (exit 2) the files are written in this order: the added and
seeded files, `project.json`, `framework.toml`, and the lock last, so no lock ever claims files that are not there. `git
status` shows what was written; put the tree back with `git stash -u` (or `git clean -fd` and `git checkout .`) and run adopt
again. A file that appears after the plan was made is never replaced, and an existing file keeps its permissions when the
template's version is taken.
