# Taking a template release into a repository

**Status:** Living. Managed by the template: a repository's copy must match, so do not edit it here; propose a change to the
template. How a repository made from the template (`init new`) or brought under it (`init adopt`) takes a newer release:
`framework_sync.py --update` does the mechanical part on a local branch (*With `--update`*), and the steps by hand stay,
as what it does and for a release it cannot take.

**This project's additions** go in `updating-project.md` beside this file, when it has any: an extension adds rules and
never weakens these. To relax or contradict a rule here, override this file in `framework.toml` with a reason that names
the rule.

## What an update is, and is not

It is **one reviewable pull request**: the managed and parametrised files that the release changed, added or removed, the
lock that records the release's hash of every managed file, and the version in `framework.toml`. It does not touch a
project-owned file (a README, `pyproject.toml`, the board, the handoff, the glossary, `framework.toml` beyond its version), a
file the repository overrides, or the repository's history.

`init new` over a repository locked to another version **refuses**, on purpose: it would overwrite what the repository has
changed since. So the release is rendered into a scratch folder and ported from there.

A release that adds a renderer may need two project-owned lines the repository adds by hand, because the update does not
touch its Makefile or `.gitignore`: a target that runs the renderer, and an ignore line for the page it writes (`make journal`
and `Docs/journal/INDEX.md`; `make board` and `Docs/plan/BOARD.md`). The release notes say which. A hand-kept board stays
valid: a repository takes the row-file form when it converts its board, never through an update.

## Before you start

- The working tree is clean and on a branch (`git switch -c chore/template-X.Y.Z`).
- `uv run python tools/framework_sync.py --check` is clean. An edit that is already there would be mixed into the update's
  diff and hidden by the new lock.
- Start the findings log (below). It is kept as the work goes, not written from memory at the end.

## Keep a findings log

This procedure, and the release's notes, are wrong somewhere for some repository. When it is yours, write it down as it
happens, so that the template is fixed for the next one: the log is how a repository reports back. Record:

- **What is a finding.** A step or the notes were wrong, unclear, or silent where a decision was needed. A guess was
  made. A check passed while the repository was not done. Something broke that no step mentioned. A step cost far more
  than it said.
- **Each entry:** the guide, its section and step; what it said; what was true; what was done instead; and the evidence
  (a command and its output, a commit).
- **Where it goes.** The update's pull request (step 7) has a section *Template findings*: the log, or "none". A
  repository with a handoff notes it there too, for a session that resumes the update.
- **Back to the template.** Once the pull request is open, file the log as one issue on the upstream
  (`gh issue create --repo <upstream>`, where `<upstream>` is the upstream as `--upstream`'s first line prints it,
  with its host: `github.com/owner/name` for a bare value), and link each to the other. **Filing waits for the owner's
  go**: it writes to another repository.
- **Do not fix the template from here.** Work around the finding, say so in the entry, and leave the fix to the
  template's own pull request.

## With `--update`

`uv run python tools/framework_sync.py --update` does steps 2 to 5 below and commits the result as **one commit on a new
local branch**, `template-update/vB`. The code that runs is the repository's own copy of the tool, so the release that
first ships `--update` is taken by hand, by its own section; every later release can be taken with it. That release
can also be taken by running its own `tools/framework_sync.py --update --root <repository>` from a clone of its tag:
the same trust as step 3's render, which runs the release's code too.

- **Where it starts.** On the branch the update goes on top of (usually the default branch), with a clean tree and a
  clean `--check`, as *Before you start* says; it makes the branch itself. It refuses, exit 1 and nothing written, a
  dirty tree (it lists the paths), a detached `HEAD`, a sync finding, a `--root` below the top level, and a branch
  `template-update/vB` that already exists. When the lock is the newest release, or ahead of it, it says so and writes
  nothing.
- **What it does.** It lists the tags with `git ls-remote`, fetches the newest and the locked one, and plans with each
  release's own `init` in a child process (the same trust `--upstream` extends). It decides every path as step 4 does,
  edits `framework.toml` as text (the version, and any override the release made stale or no longer names), keeping its
  comments, and checks the commit message with the repository's own `tools/check_commit_msg.py`, all before it writes.
  Then it writes on the new branch, runs `--check`, and commits with no hook run, so `make check` on the branch is
  the commit's first check. A failure in the write or the commit
  rolls back to where it started. A `--check` finding after the write is the tool's own fault: it keeps the branch,
  uncommitted, and prints how to drop it.
- **What it leaves to you.** Each overridden file the release changed, listed in the message with the `git diff` that
  shows what changed (step 4's judgment); the release's hand steps, their titles a checklist in the commit message and
  their text in the report, read by *Several releases at once*: each *Take* is marked as the render it did, the
  seeds it wrote are named, so a step that copies one is done, and a
  skipped release's *Check it* as waiting for the one check against B; `make sync` and `make check` on the branch; and
  step 7: push the branch and open one pull request with *Template findings*. It pushes nothing.
- **What it does not take.** A release whose plan refuses this repository, a path the repository's `.gitignore`
  ignores, a `framework.toml` it cannot edit by plain lines (an override in an inline table), and a message the
  repository's check rejects are each refused, exit 1, nothing written: take that release by the steps below, or fix
  the cause and run it again. So is a file the release first makes managed that the repository already has a copy
  of, which the lock does not record (`exists with different content and is not recorded in framework.lock`):
  commit the removal of the repository's own copy first, then run it again, and the release's copy is written.
- **Credentials.** It reads the upstream with git, at `https://<upstream>.git`, so a private upstream needs git's own
  credentials (a credential manager, or SSH through git's configuration), not `gh`'s login. An upstream on another
  GitHub host is named `host/owner/name` in `framework.toml`; git needs a credential for that host too. It never
  prompts: a credential git cannot get is exit 2, with git's own words. `git ls-remote https://<upstream>.git` from the
  repository shows whether git can read it. Until a repository has taken the release that accepts `host/owner/name`,
  configuration that sends git to another host (`url.<base>.insteadOf`) goes in the global config, not the
  repository's: the fetch runs in a scratch folder, which does not read the repository's configuration.

## The steps

By hand: what `--update` does, and the way to take a release it cannot.

1. **See what moved.** `uv run python tools/framework_sync.py --upstream` prints `lock is behind: A locked, B current, N managed
   file(s) changed` and lists each path as `changed`, `added` or `removed` (and marks one the repository overrides). It writes
   nothing. **It says "current" whenever the versions are equal, without comparing files**, so a fix released without a version
   bump is not seen: the template bumps the version for every release. It names the latest release, never `main`:
   the version bump merges before its tag, so for a while `main` names a version that is not yet one to take
   ([#178](https://github.com/HogJonny-AMZN/ai-first-template/issues/178)).
2. **Get the release.** Clone the tag into a scratch folder **outside** the repository:
   `git clone --branch vB --depth 1 https://<upstream>.git <scratch>/template` (`<upstream>` is the upstream as
   `--upstream`'s first line prints it, with its host). The tag is annotated, so the clone prints
   `warning: refs/tags/vB ... is not a commit!` and git's advice about a detached HEAD: both are expected, and the
   checkout is the release. Read the release's notes (`https://<upstream>/releases/tag/vB`, or
   `gh release view vB --repo <upstream>`): they say what a repository has to do beyond the files.
3. **Render it for this repository.** Make `<scratch>/rendered` and copy the repository's `project.json`, `framework.toml` and
   `framework.lock` into it, then change `"template_version": "A"` to `"B"` **in the lock's copy** (JSON), so `init`
   accepts it. A lock left at A is refused, and the refusal names the cause: `framework.lock is for template A but this
   payload is B`. The `framework.toml` copy stays as it is: `init` takes the version from the release, and reads only
   the module choices, the overrides and the roster from it
   ([#224](https://github.com/HogJonny-AMZN/ai-first-template/issues/224)).
   `init` reads the repository's module choices and overrides from `framework.toml`, and the day it was first run from the
   lock, not from `project.json`: render into an empty folder and a module the repository turned off comes back on and a
   dated file takes today's name. Then, from the repository's root:
   `uv run python <scratch>/template/payload/tools/init.py new --answers project.json --target <scratch>/rendered --no-sync --no-checks`.
   This is what the release would write for this repository, in a folder that is not the repository. **It runs code from the release** (the same trust `--upstream` extends); read the diff of
   `payload/tools/init.py` first if you do not trust the tag's author.
4. **Port the files, one path at a time**, from the list in step 1:
   - *changed*, not overridden: copy `<scratch>/rendered/<path>` over `<path>`.
   - *added*: copy it in. *Removed*, not overridden: delete it.
   - *removed and overridden* (the report says so): the release no longer ships the file, so the new lock drops it. Decide
     whether the repository keeps the file as its own (it stays, unlocked, like a project-owned file) or deletes it, and
     **delete its `[[overrides]]` entry either way**: an override for a path the lock does not list is `override-unknown`.
   - *changed and overridden* (the report says so): do not copy. Compare (`diff <path> <scratch>/rendered/<path>`) and decide as
     in *Adopting*, step 6: take the template's (copy it, delete the override), extend (the repository's additions move
     into the extension the base names, the template's base is copied over, the override goes), keep the repository's
     (the override and its reason stay, and the reason must still name the rule it contradicts), or improve the
     template. **To keep it, first read what the release changed in the file**: in a clone with both tags,
     `git diff vA vB -- payload/<path>`. A tool ported in the same update may now enforce a rule that only the new text
     states (a new board field, a new ledger entry): carry each such rule into the kept file, and say so in the
     override's reason. A kept `failure-modes.md` never receives the release's new framework entries, while the
     managed files that cite them by number (the definition of done, the skills) do: the release notes list the
     entries added, so carry them in, or cite them as the template's entries. When the release changed only text the
     kept file never had (a row the repository's copy left out), and no check that runs here enforces a rule from it
     (its check is off, or needs what the repository does not have), there is nothing to carry: keep the override as
     it is, and say so in the pull request ([#213](https://github.com/HogJonny-AMZN/ai-first-template/issues/213)). A
     check counts whether this update ported it or it ran before: where `landed-rows` already ran, 0.10.1's draft-first
     step had to be carried into a kept copy of the `review-and-pr` skill
     ([#220](https://github.com/HogJonny-AMZN/ai-first-template/issues/220)). An extension (`python-project.md` beside `python.md`, `project.md` in a skill's folder) is never
     touched by an update: it is the project's, and no release ships one.
   - A *skills mirror* or a generated adapter is not ported by hand: port the canonical `.agents/skills/` file, then
     `uv run python tools/sync_adapters.py --write`.
5. **Record the release.** Copy `<scratch>/rendered/framework.lock` over `framework.lock` (it keeps the repository's own
   `initialised` day, because step 3 seeded it). Set `template_version` in `framework.toml` to B. The lock holds the
   template's hash of every managed file **including the ones the repository overrides**, so an override stays a standing
   difference from the template, not from the lock. Do not copy the rendered `framework.toml`: it is the template's seed, not
   the repository's.
6. **Check it.** `uv run python tools/framework_sync.py --check` is clean (every override in force still listed with its
   reason), `--upstream` says `lock is current: B locked, B is the latest release`, and `make check` passes. If the docs
   check calls a document the release **added** an orphan, the managed file that links it is one this repository overrides
   (an overridden file keeps the repository's text, so the template's new link never arrives): link the new document from
   the repository's own map, `Docs/README.md`, beside the other standards.
7. **Commit it on the branch and open one pull request** that names the release, lists the paths ported, says what was
   kept as an override and why, and carries *Template findings*: the findings log, or "none". Nothing is committed for
   you.

**Several releases at once.** B is always the latest release, however far behind A is: one render of B ports every
managed file changed since A, so there is no stop at a release in between, which would be rendered and locked only to be
replaced. What the render does not carry is each release's hand steps. After step 4, work through the release sections
below from the one after A up to B's, oldest first, and do each one's steps in its order, with three exceptions found by
name, not by number. A section's *Take* step is the render already done, though what it says `make check` then reports
still holds. A step that comes before *Take* (0.8.0's history fetch in CI) is done before the render. A section's
*Check it* waits: step 5 records B, and step 6 checks once, against B
([#218](https://github.com/HogJonny-AMZN/ai-first-template/issues/218)).

## Turning a module on

A module that is off (`process-map`, say) is turned on later by its own procedure, not by an update: `--upstream` says
*current* whenever the versions are equal and lists no path, the lock lists managed files only, so a project-owned seed is in
no list, and step 5 keeps the repository's own `framework.toml`, so a module set on only in the scratch copy is off again in
the repository. The release locked must be one that ships the module; take that release first if it is not.

1. **Set it on in the repository's own `framework.toml`** (`process-map = "on"` under `[modules]`). This is the choice that
   persists.
2. **Render the locked version, not a new one:** steps 2 and 3 above with B the version already locked, so nothing else
   changes. The render reads the repository's `framework.toml`, now with the module on.
3. **The managed files:** every path in `<scratch>/rendered/framework.lock` that the repository's lock lacks is the module's;
   copy each one in. A skills mirror is regenerated (`uv run python tools/sync_adapters.py --write`), not copied.
4. **The project-owned seeds:** the render's record (the log under `<scratch>/rendered/logs/` whose path the render prints)
   names each file with its class and module (`create  <path>  [project-owned, <module>]`); copy each one the repository
   lacks, and **never one it has**: a file there is the project's.
5. **Record it:** copy the rendered lock over the repository's (it keeps the repository's `initialised` day, which the
   render in step 2 seeded).
6. **The workflow step:** the CI parity test (`tests/test_tooling.py`) names the command of every stage the workflow does not
   run; add a step for the module's stage to `.github/workflows/ci.yml`, in the check runner's order.
7. **Check it:** `uv run python tools/framework_sync.py --check` is clean, `make check` passes with the module's stage in its
   summary, and the docs check is clean. Commit it on a branch and open one pull request that names the module.

## When it goes wrong

- *Step 3 refuses (exit 1) or fails (exit 2).* The message names the file or the answer: the lock's copy left at A (step
  3), a managed file in the folder that differs and the lock does not record, two names that differ only in capitals,
  a file where a folder must go, or a release that changed what `project.json` must hold (read the release notes). A
  folder that is not empty is not refused as such ([#224](https://github.com/HogJonny-AMZN/ai-first-template/issues/224)).
  The rendered folder is scratch: delete it and run again.
- *`--update` refuses (exit 1) or cannot tell (exit 2).* Its first line says which and why, and nothing was written,
  unless it says it kept its branch after a `--check` finding: then it prints the steps that drop it. A refusal it
  cannot get past is a release to take by the steps above, and a finding for the log.
- *`--check` reports `edited` after step 5.* A path from the list in step 1 was not ported, or was ported from the wrong
  folder. Run `diff <path> <scratch>/rendered/<path>`.
- *`--check` reports `override-stale`.* A kept override now equals the template's version: delete the override.
- *`--upstream` says git has no credential for a host.* An enterprise host is a separate sign-in: sign in to it once
  with git, or run `gh auth login --hostname <host>` and `gh auth setup-git --hostname <host>`, then run step 1 again.
- *`--upstream` still says behind.* The version in `framework.toml` or the lock was not set to B, or B is not the latest
  release: run step 1 again.
- *A file you did not expect is in the list.* The release changed a managed file for every repository; read the release
  notes before keeping an override.

Missing the next release costs more than this one: `--upstream` exits 1 when a lock has been behind for longer than
`max_age_days` (default 14, under `[framework]` in `framework.toml`), so the procedure is best run when it is first reported.

## 0.6.0: board rows stay true

0.6.0 adds two docs-check findings for a board kept as row files, `board-state` and `waits-on`, and framework ledger
entries 33 and 34. It was released with its steps in [its notes](https://github.com/HogJonny-AMZN/ai-first-template/releases/tag/v0.6.0)
only; this section is them, so a repository taking several releases by this guide does not miss them
([#207](https://github.com/HogJonny-AMZN/ai-first-template/issues/207)).

1. **Take 0.6.0**, by the steps above.
2. **The board README and the glossary are the repository's own**, so the update does not change them. Copy from the
   release's seeds: into `Docs/plan/board/README.md`, the `Waits on` line in the example, `Verdict` on any row but a
   gate, the *Moving a row* and *A wait on other work* paragraphs, and the rule that a row is work in this repository;
   into `Docs/glossary.md`, a **Waits on** row, and the **Row file** row naming its new line.
3. **Tidy what `make check` finds.** A landed row in *Next*: its `Section` becomes `now`. A queued row in *Now*: `next`.
   An Icebox row saying it was pulled forward beside its *Now* row: delete it (the *Now* row keeps the history). A
   verdict that waits on other work in prose ("after X lands"): a `Waits on` line linking X's row, and if X has
   landed, the row decided again. A row moved off the Icebox to *Now* also needs an `Owner`.
4. **Check it.** `make check` passes.

## 0.7.0: the repository layout

0.7.0 moves a repository's code into workspace members ([layout.md](layout.md)), from a root `src/` or from a package
at the root (a flat layout). The update itself (the steps above) brings the managed files, and after it the gate fails
(`legacy-src`, `legacy-root`) until the code moves. Moving it is this section, done in the repository's own session, one
step at a time, each ending with the check it names. Paste the section into that session as it is, and keep the
findings log (above) through it.

1. **Take 0.8.0 or later first**, by the steps above: `legacy-root` arrived in 0.8.0, so a repository that stops at 0.7.0
   is not checked for the flat layout. `make check` then fails with `legacy-src` for each package of a root `src/`, and
   with `legacy-root` for a root manifest that builds a project (`[project]`) and for each package folder at the root,
   and with nothing else that the release did not bring. So the 0.8.0 update's own *Check it* passes except for those
   two findings, which this section clears; the update and this section may be one pull request or two.
2. **Choose the members.** For each package either finding names, under `src/` or at the root: an app (`apps/<app>/`) if
   it is launched, a library (`packages/python/<name>/`) if other code imports it. Name each from the slug: folders and
   distribution names with hyphens (`acme-tools-core`), import packages with underscores (`acme_tools_core`). A package
   that keeps its import name keeps every import of it working; a rename is a separate change, after this one.
3. **Before moving, search** for what the move breaks without failing an import or a test:
   - **Counted parents.** `Path(__file__).parents[N]` and `__file__` that find the checkout: the move shifts every count
     silently, and an off-by-N path fails far from its cause. Replace the count with a walk up to a marker
     (`framework.toml`), in one helper.
   - **Each folder that moves, by name**, not only `src/`: string literals in code and tests included (a job's default
     output naming the old folder recreates it).

   **Move each package**, with `git mv` so its history follows: `git mv src/<package> apps/<app>/src/<package>`, or from
   the root `git mv <package> packages/python/<name>/src/<package>` (or the app's). Write the member's
   `pyproject.toml`: `[project]` with its name, version, `requires-python`, `authors` (each with a name and an email:
   `no-authors` refuses either missing; a project that deliberately named no address takes the owner's from
   `project.json`, which its signed-off commits already carry) and `dependencies` (each member it imports, with `[tool.uv.sources] <name> = { workspace = true }`),
   `[project.scripts]` for an app's entry points, and `[build-system]` (`requires = ["uv_build>=0.9,<0.12"]`,
   `build-backend = "uv_build"`). `uv_build` looks for the package under the distribution's name with underscores
   (`src/acme_tools_core/`): a package that keeps another import name (`core`) says so, with
   `[tool.uv.build-backend] module-name = "core"`, or `uv sync` fails with "Expected a Python module at". What the root
   manifest held for the package moves with it:
   - **Optional dependencies** stay on the member (`[project.optional-dependencies]`); `uv sync --all-extras` at the root
     installs them.
   - **Data files** under the package (a schema, a template) are packed by `uv_build` as they are; setuptools
     `package-data` has no counterpart to write.
   - **The license** is an SPDX string (`license = "Apache-2.0"`): a member cannot ship a file outside its folder, so
     `license = { file = "LICENSE" }` at the root does not carry over. A file the licence's terms require to travel
     with the code (the `LICENSE` text, a `NOTICE`) is copied into the member and named in
     `license-files = ["LICENSE", "NOTICE"]`; a test that compares each copy with the root's keeps them level.

   **A project's own scripts in `tools/`** (with their tests in the root `tests/`) are launchable units, so they are
   an app: `tools/` and the root `tests/` hold only the framework's files ([layout.md](layout.md)). Move them as a
   package is moved; when that is too much for this update, leave them, and say so in the pull request's *Decisions*
   with a board row for the move.

   Move its tests to the member's `tests/` with `git mv`, and remove every `tests/__init__.py`, the root's included. A test
   that added `src/` to `sys.path` stops doing so: the member is installed. A test that imports a helper beside it by bare
   name needs its folder's `conftest.py` to put that folder on `sys.path`, and the name unique across the members
   ([layout.md](layout.md), *Tests across members*). Then `uv run ruff check --fix .` removes the imports that leaves
   unused (`sys`, `Path`), and re-sorts the blocks when the project selects the isort rules (`I`), since each member's
   package is now first-party.
4. **The root manifest.** Remove the root `pyproject.toml`'s `[project]` table, and the `[build-system]` and
   `[project.scripts]` with it, now in the members. Add `[tool.uv.workspace] members = ["apps/*", "packages/python/*"]`
   (and any nested part). Keep the `dev` group and the tools' configuration; set ruff's `src` to
   `["tools", "tests", "apps/*/src", "packages/*/*/src"]`, and pytest's `testpaths` to
   `["tests", "apps/*/tests", "packages/*/*/tests"]` with `addopts = "--import-mode=importlib"` and
   `pythonpath = ["tests"]`. A member nested one level deeper (`apps/<app>/<part>/`) is named in all three
   ([layout.md](layout.md), *Workspace members*). List both families in all three even before the first app: a glob
   that matches nothing is accepted, and the first app then needs no edit. Then `uv sync` (it installs every member) and `uv run pytest`:
   every test is collected. The virtual root builds nothing: a test or script that ran `uv build` at the root builds a
   member, `uv build --package <member>`.
5. **`[layers]`.** Name the import packages in `framework.toml`, lowest first. Run `uv run python tools/boundaries.py` and
   fix each finding: `undeclared` is a dependency to add to the importing member's manifest; `app-import` and `app-to-app`
   are code to move into a package; `unreached` is a member folder to add to the members list; `cycle` is modules that
   import each other in a ring, which the code may never have been checked for. A late import counts, one under
   `if __name__ == "__main__":` included: move what both sides need into a module of its own.
6. **The rest of the repository.** Each module's `Package:` line and `_MODULE_NAME` become its import path; a test
   file's `Package:` line becomes its path from the root without `.py` ([python.md](python.md)). A launcher in
   `launchers/` for each entry point, a `.cmd` and a `.sh` that pass on their arguments ([layout.md](layout.md),
   *Launchers*); on Windows, `git add --chmod=+x launchers/*.sh`.
   - **The documents that name the old path** (`src/`, or the package's old folder at the root). Rewrite the living ones:
     the standards, the README, the handoff, the board. Leave the records as they were (the journal, the ADRs, the
     ledgers, a built spec or plan): they describe the code as it was, and only a broken link in one is fixed. The text
     of a generated block changes in its generator, not in the document.
   - **Every script and CI step** of the repository's own that names the old path.
   - **Where else the package is imported from**, outside the uv environment: a DCC's Python, a worker profile, a CI
     image, a `PYTHONPATH`. Nothing in the gate sees them. Point each at the member's `src/`, and run one job there
     before step 7.
   - **Two files are the repository's own** and the update does not change them. The map, `Docs/README.md`, gets a row
     for [layout.md](layout.md) ("adding an app or a library, or asking where code lives"). The glossary,
     `Docs/glossary.md`, gets the five words *layout.md* uses (**Workspace member**, **App root**, **Package root**,
     **Launcher**, **Experiment**), and adds or amends its **Layer** and **Boundary test** rows to say members, not
     `src/`, as the template's seed does; the **Mock project** and **Faux library** rows (the second is defined by the
     first) only where the repository has the mock project.
   - **Install lines that name the repository.** A `pip install "<dist> @ git+<url>"` in the README or the docs now
     meets a virtual root that builds nothing: it needs `#subdirectory=packages/python/<name>` (or the app's folder).
     Nothing in the gate runs these lines: run one.
7. **Check it.** `make check` passes, with no `legacy-src` and no `legacy-root`; each launcher's `--help` prints its
   tool's usage; a job ran where step 6 found another importer. Commit it on a branch and open one pull request that names
   this section and carries *Template findings*.

## 0.8.0: the row id and member authors

0.8.0 makes a board row's file name its id, kept for life, and has every design, spec and plan name its row
([workflow.md](workflow.md), *A row's id is its file name*). It brings two findings of the docs check, `row-ref` and
`row-kept`. Both apply only to a board in directory form (row files under `Docs/plan/board/`); a repository whose
board has always been one page meets neither, and its `make check` says `row-kept: skipped: the board is one page`.
It also has `init new` ask for the owner's GitHub login and seed the owner's roster row from it (step 5), and every
app and package manifest name its authors, a new finding of the boundary check, `no-authors` (step 6), and CI
recheck every commit message on a pull request (step 7). The boundary check gains `legacy-root` (step 8), and the
update guides a findings log (step 9).

1. **Fetch the history in CI, before the update.** Your workflows are your own, so the update does not change them:
   add `with: fetch-depth: 0` to the `actions/checkout` step of **every workflow that runs the docs check** (`ci.yml`,
   and any other that runs `check_docs.py` or `make check`), in the update's pull request or before it. Without it, `row-kept` cannot read a pull request's base and stops the docs check with a message that says
   so, starting with that pull request.
2. **Take 0.8.0**, by the steps above. `make check` then names each design, spec and plan with no `**Board:**`
   header line, and each with the old plain `Board:` line (`row-ref`), and nothing else the release did not bring,
   but for a repository not yet moved: `legacy-src` or `legacy-root` until *0.7.0: the repository layout* is done (step 8).
3. **Name each one's row.** In its header, after `**Status:**`: ``**Board:** [`<row id>`](<path to the row file>)``,
   the id being the row file's name without `.md`, or `**Board:** none (reason)` for one that serves no row. Rewrite an
   old `Board:` line the same way. The new line stands on its own line, and only the header (the lines before the
   first `##`) is edited: an old link that runs on into other prose, or wraps across lines, is split off by hand, and a
   whole-file clean-up must not touch the body (it can remove blank lines a code block needs). Where rows' files
   already link the document, the `row-ref` finding names them.
4. **Your seeds.** The board README (`Docs/plan/board/README.md`) gets the paragraph *A row's id* and the UTC day in
   its first line, as the template's seed has them; the glossary gets the **Row id** row.
5. **The owner's login (optional).** `init new` now asks for the owner's GitHub login and seeds the owner's
   `[[people]]` row from it. A repository made earlier may do the same by hand: add `"login"` to `owner` in
   `project.json`, and the owner's row to `framework.toml` ([journal.md](journal.md), *The roster*). Both are optional,
   and nothing in the update needs them.
6. **Authors in every app and package manifest.** Add `[project] authors` to each member under `apps/` and
   `packages/`, each entry with a name and an email: `authors = [{ name = "Ada Example", email = "ada@example.org" }]`.
   Without it, `make check` fails on the boundary test, naming each manifest (`no-authors`). An experiment needs none.
   `python.md` also stops banning `__author__`: a repository that overrode `python.md` for that alone can drop the
   override.
7. **The `commits` job.** `.github/workflows/ci.yml` is your own, so the update does not change it: copy the
   `commits` job from the release's `payload/.github/workflows/ci.yml` into yours, after the `check` job. It runs on pull
   requests only and checks every commit's message with `tools/check_commit_msg.py --range` (the file this release
   updates). It accepts Dependabot's own sign-off only on a pull request Dependabot opened.
8. **`legacy-root`.** A repository that took 0.7.0 with its package at the root, or with a root manifest that still
   builds a project, now fails the boundary check with `legacy-root`. *0.7.0: the repository layout* (above) moves it.
9. **The findings log.** The glossary is your own, so the update does not change it: copy the **Findings log** row from
   the release's `payload/Docs/glossary.md` (that row, which links the guide, not the template's own). Keep the log
   (*Keep a findings log*, above) from this update on.
10. **Check it.** `make check` passes, or fails only with `legacy-src` or `legacy-root`, which the 0.7.0 section clears
    next. Then, on a scratch branch, rename one row file: `make check` fails with
    `row-kept` naming the old id. Undo the rename.

## 0.9.0: logging in tiers

0.9.0 replaces `python.md`'s *The three loggers* with *The tool-root pattern*: one `_LOGGER` per module is the default,
and an App takes the pattern only when it has a second audience for its logs or an embedding host, and says so in its
design. The pattern's reference is `Docs/standards/examples/tool_root_logging.py`, with its tests in
`tests/test_tool_root_logging.py` (both python-uv). `testing.md` gains *Capturing logs under a tool-root logger*. The
template's own tools log through `tools/log_setup.py` (core), so every diagnostic line on stderr carries the time, the
level and the module. The gate gains no stage. The docs check gains one finding, `control-char`, and reads two things
more loosely: an Icebox `Cost` may be `unsized: <reason>`, and `status-copy` no longer reads a per-login handoff.

1. **Take 0.9.0**, by the steps above. `make check` then brings one new finding, and only if your documents have the
   fault: `control-char`, a C0 control character (but tab and line feed) or DEL in a Markdown file, named by file, line
   and code point. Delete the character: it is invisible in an editor, and usually came through a shell heredoc that
   turned a backslash escape into the character (framework ledger 3).
2. **Your own tests of a tool's stderr.** The template's tests pass unchanged, but a test of your own that compares a
   tool's whole stderr line with a bare message now meets the time, level and module in front of it. Compare the
   message's part of the line instead.
3. **An App that followed the 2026-11-03 text** (*The three loggers*): move its handler setup into a
   `configure_logging()` called from `main()`, never at import; configure each shared library's root once per process;
   cap the vendor namespaces only in the App that owns the process. The variable names are unchanged, and the example
   is the reference: copy it and change its constants. An App that does not need the pattern drops it for one `_LOGGER`
   per module.
4. **An override of `python.md`** kept only to stay with one logger per module can be dropped: that is now the default.
5. **Your glossary.** Copy six rows from the release's `payload/Docs/glossary.md`: **Tool-root pattern**, **Logging
   self-check** and **Unsized** (new), **Tool-root logger**, **Third-party cap** and **Status copy** (changed, or new where your glossary lacks
   them: the 2026-11-03 text that introduced the first two came with no step to copy them,
   [#176](https://github.com/HogJonny-AMZN/ai-first-template/issues/176)).
6. **The ledger.** `failure-modes.md` gains entries 45, 46 and 47. A repository that keeps its own copy (an override)
   receives none of them: copy them, with their rows in the trigger index. A ledger kept in its own numbering has no
   place for an entry 45: carry each entry's rule into the files that cite it, or first split the ledger into the
   template's base and your extension (`failure-modes-project.md`), then copy them
   ([#175](https://github.com/HogJonny-AMZN/ai-first-template/issues/175)).
7. **Your board README** (`Docs/plan/board/README.md`, yours): the `Cost` rule gains two forms. A row's `Cost` is a
   number and a unit, or `unsized: <reason>`; and a `Closed` or `Dropped` Icebox row may leave it out. A README with
   the seed's example block copies the two lines from the release's seed; one in its own form says the rule in its
   own words ([#177](https://github.com/HogJonny-AMZN/ai-first-template/issues/177)). An Icebox row whose cost was a guess written as a
   number may now say `unsized: <reason>`, and a `Closed` or `Dropped` Icebox row may drop its `Cost`. Delete the line:
   a placeholder kept there (`Cost: -`) is still read, and still a finding. `workflow.md`'s *A mentioned feature is not
   a work order* names the `unsized` form too.
8. **Your `.gitignore`** (yours): add `.worktrees/`, as the seed now has it. Framework entry 47 sends work beside a
   checkout another session holds into a worktree there, which `git status` would otherwise list.
9. **`DTZ` (optional).** `pyproject.toml` is your own: add `"DTZ"` to `select` under `[tool.ruff.lint]`, as the seed
   now has it, to refuse `date.today()` and `datetime.now()` without a zone. A record date is the UTC day:
   `datetime.now(UTC).date()`. It does not see a call made through a module alias.
10. **Check it.** `make check` passes, and `uv run python tools/boundaries.py -v` writes lines to stderr that start
   with the time, the level and `tools.boundaries:`.

## 0.9.1: the other invisible characters

0.9.1 widens `control-char` ([#159](https://github.com/HogJonny-AMZN/ai-first-template/issues/159)). It changes no
contract, gains no stage and adds no finding name. A repository on 0.8.0 does *0.9.0*'s hand steps too, by *Several releases at once*.

1. **Take 0.9.1**, by the steps above. `make check` brings `control-char` findings only if your files hold one of the
   characters it now also reads: a C1 control (U+0080 to U+009F); a bidirectional embedding, override or isolate
   (U+202A to U+202E, U+2066 to U+2069), which makes a line display other than it reads; the zero-width space
   (U+200B); or a byte-order mark after the start of a file. Each is named by file, line and code point. Delete it.
   The joiners (U+200C, U+200D), the direction marks (U+200E, U+200F) and the word joiner (U+2060) still pass.
2. **Check it.** `make check` passes.

## 0.9.2: the logging example's faults, and the line separators

0.9.2 fixes the logging example a repository's update found faults in ([#172](https://github.com/HogJonny-AMZN/ai-first-template/issues/172) to
[#174](https://github.com/HogJonny-AMZN/ai-first-template/issues/174)), widens `control-char` once more, and corrects three of 0.9.0's steps
([#175](https://github.com/HogJonny-AMZN/ai-first-template/issues/175) to [#177](https://github.com/HogJonny-AMZN/ai-first-template/issues/177)). It changes no contract, gains no stage, adds no
finding name and adds no framework ledger entry. A repository on 0.9.0 does *0.9.1*'s hand steps too, by *Several releases at once*.

1. **Take 0.9.2**, by the steps above. `make check` brings `control-char` findings only if your Markdown holds a line
   separator (U+2028) or a paragraph separator (U+2029): invisible in an editor, and a line break to
   `str.splitlines()`. The usual cause is an escape written as the character, by a heredoc or an agent's file tools.
   Write the escape back, or delete the character.
2. **An App that copied `tool_root_logging.py`** (python-uv): the reference arrives fixed
   (`Docs/standards/examples/tool_root_logging.py`, `__version__` 0.1.1), but your App's copy keeps the faults. Bring
   the copy level with it: `git diff v0.9.1 v0.9.2 -- payload/Docs/standards/examples/tool_root_logging.py` in a clone
   of the template shows every changed line, and your constants stay as they are. The copy then:
   - on Linux and macOS, holds a shared lock on each file it writes, and its pruning keeps a file another instance
     holds (before, it deleted a running instance's log there); a file pruned before it was locked is opened again.
     Only an instance that takes the lock is protected: one still running an older copy, or another program with
     the file open, is not, so bring every copy of the App level
     ([#184](https://github.com/HogJonny-AMZN/ai-first-template/issues/184));
   - shows a line break in a console message as its escape, so one record is one console line (the file still gets
     the message as written);
   - inside a host, never takes the host's own level for its earlier cap.

   A test of your own that compares a multi-line message on the console now meets the escape. The reference's tests,
   `tests/test_tool_root_logging.py`, show each case.
3. **0.9.0's steps, corrected.** A repository that took 0.9.0 and skipped a step for one of these reasons reads it
   again: step 5 (a glossary row marked changed is new where yours lacks it), step 6 (a ledger in its own numbering)
   and step 7 (the board README's `Cost` rule, for a README without the seed's example block).
4. **Check it.** `make check` passes, and `--upstream` says `lock is current: 0.9.2 locked`.

## 0.9.3: the logging example's prune, and who its lock protects

0.9.3 fixes one more fault in the logging example's pruning ([#186](https://github.com/HogJonny-AMZN/ai-first-template/issues/186)) and says who its lock
protects ([#184](https://github.com/HogJonny-AMZN/ai-first-template/issues/184)). It changes no contract, gains no stage, adds no finding name and adds no
framework ledger entry. A repository on 0.9.1 does *0.9.2*'s hand steps too, by *Several releases at once*.

1. **Take 0.9.3**, by the steps above. `make check` brings no new finding.
2. **An App that copied `tool_root_logging.py`** (python-uv): the reference arrives fixed (`__version__` 0.1.2), and
   your App's copy is brought level as in *0.9.2*, with
   `git diff v0.9.2 v0.9.3 -- payload/Docs/standards/examples/tool_root_logging.py` (from `v0.9.1` for a copy that
   skipped 0.9.2). The copy then:
   - on Linux and macOS, deletes a file while pruning only while its name still leads to the file it locked. Before,
     two prunes overlapping a launch that re-opened its file could delete the launch's new log;
   - says in `_prune`'s docstring that only a holder that took the lock is protected: an instance still running an
     older copy, or another program with the file open, is not. Bring every copy of the App level before relying on
     it (*0.9.2*'s step 2 now says so too).

   The reference's tests, `tests/test_tool_root_logging.py`, show the case.
3. **Check it.** `make check` passes, and `--upstream` says `lock is current: 0.9.3 locked`.

## 0.9.4: a prune whose file was gone when it looked

0.9.4 fixes one more fault in the logging example's pruning ([#190](https://github.com/HogJonny-AMZN/ai-first-template/issues/190)). It changes no contract,
gains no stage, adds no finding name and adds no framework ledger entry. A repository on 0.9.2 does *0.9.3*'s hand steps too,
by *Several releases at once*.

1. **Take 0.9.4**, by the steps above. `make check` brings no new finding.
2. **An App that copied `tool_root_logging.py`** (python-uv): the reference arrives fixed (`__version__` 0.1.3), and
   your App's copy is brought level as in *0.9.2*, with
   `git diff v0.9.3 v0.9.4 -- payload/Docs/standards/examples/tool_root_logging.py` (from the tag your copy came
   from, if older). The copy then, on Linux and macOS, looks at a file it prunes once, with `os.lstat`: a file another
   prune already deleted is kept and reported, never deleted without the lock. Before, it counted as "not a file", and
   a launch that re-opened its file at that name in between lost it.

   The reference's tests, `tests/test_tool_root_logging.py`, show the case.
3. **Check it.** `make check` passes, and `--upstream` says `lock is current: 0.9.4 locked`.

## 0.10.0: a `##` in a session file, and the journal's story

0.10.0 adds a `journal-author` finding, gives the template's own gate a stage, and fixes a test that needed the GitHub
CLI ([#200](https://github.com/HogJonny-AMZN/ai-first-template/issues/200)). It changes no contract a repository acts on
and adds no framework ledger entry. A repository on 0.9.3 does *0.9.4*'s hand steps too, by *Several releases at once*.

1. **Take 0.10.0**, by the steps above.
2. **A `##` heading in a session file** (with a `[[people]]` roster): `make check` reports it as `journal-author`,
   "'## Title' is not an entry heading: an entry is a ### heading". The checks read `###` entries only, so what followed
   a `##` was checked by nothing. Make it a `###` entry with its `**By:**` line, or plain text if it was never an entry.
   The words stay as they were written; only the heading changes.
3. **The new stage, `payload`**, belongs to the `payload-suite` module, the template's own. Your `framework.toml` does
   not name it, and an absent module reads as off: there is nothing to add.
4. **`journal.md`** arrives with two rules: an entry tells the session's story for a person (what the developer is
   doing, the outcome they drive towards and why), and two pull requests open at once from one session stack the second
   on the first, since both append to its file.
5. **A repository that patched `framework_sync.main`** to take `which` (a CI runner without the GitHub CLI fails
   `test_the_command_line_runs_upstream_and_returns_its_code` otherwise): the release has the fix
   (`framework_sync.py` `__version__` 0.1.1). Drop your edit and its override.
6. **The seeded glossary** gains *Payload suite*: copy the row from the release's `payload/Docs/glossary.md` if you
   want it, or leave it, since your repository has no such module.
7. **Check it.** `make check` passes, and `--upstream` says `lock is current: 0.10.0 locked`.

## 0.10.1: two error paths, and the guide's gaps

0.10.1 answers what two repositories' updates found
([#207](https://github.com/HogJonny-AMZN/ai-first-template/issues/207) to
[#209](https://github.com/HogJonny-AMZN/ai-first-template/issues/209),
[#213](https://github.com/HogJonny-AMZN/ai-first-template/issues/213)). It changes no contract, gains no stage, adds no
finding name and adds no framework ledger entry. A repository on 0.9.4 does *0.10.0*'s hand steps too, by *Several releases at once*.

1. **Take 0.10.1**, by the steps above. `make check` brings no new finding.
2. **Two tools behave better where a folder cannot be read.** `check_hygiene.py` (`__version__` 0.3.2), run without
   git, no longer reports a folder the allowlist covers, nor calls its entry, or one beneath it, stale. `init_adopt.py`
   (`__version__` 0.2.1) refuses, naming the folder, where `src/` or a package under it cannot be listed, instead of
   failing with a traceback or leaving the package out.
3. **The guide and the standards say more.** Nothing to do unless one of these is a decision your repository met:
   - this guide has a *0.6.0* section, and its *0.7.0* covers install lines, a project's own tools, licence files,
     authors, the members lists and a test file's `Package:` line; step 4 covers a kept override that never had the
     changed text;
   - `journal.md`: work that must merge before a long-running branch goes off the default branch;
   - `python.md`: a test file's `Package:` line is its path from the root without `.py`;
   - the `review-and-pr` skill: a pull request that lands a board row opens first, as a draft (its steps are renumbered
     from 3).
4. **Check it.** `make check` passes, and `--upstream` says `lock is current: 0.10.1 locked`.

## 0.10.2: several releases in one render, and the guide's gaps

0.10.2 answers what two repositories' 0.10.1 updates found
([#218](https://github.com/HogJonny-AMZN/ai-first-template/issues/218),
[#220](https://github.com/HogJonny-AMZN/ai-first-template/issues/220)). It changes the guide and the journal standard
only: no tool, no contract, no stage, no finding name and no framework ledger entry. A repository on 0.10.0 does
*0.10.1*'s hand steps too, by *Several releases at once*.

1. **Take 0.10.2**, by the steps above. `make check` brings no new finding.
2. **The guide and the journal standard say more.** Nothing to do unless one of these is a decision your repository met:
   - this guide: *Several releases at once* says how a repository more than one release behind takes the latest in one
     render and then each skipped release's hand steps; step 2 says the clone's `is not a commit!` warning is expected;
     step 4's kept-override clause asks whether a check that runs here enforces the new text, however it arrived;
   - `journal.md`: a session continued past midnight names its next-day file for the time it opens, in UTC.
3. **Check it.** `make check` passes, and `--upstream` says `lock is current: 0.10.2 locked`.

## 0.11.0: `--update`, and `--upstream` on git

0.11.0 adds `framework_sync.py --update` (*With `--update`*, above) and moves `--upstream` from `gh` to git,
ships a harness hook for ledger entry 48, and brings parallel suites and a uv floor. It gains no stage and adds no finding name. A repository on 0.10.1 or earlier
does the hand steps of each release it skipped too, by *Several releases at once*. Before taking it, an `upstream` in
`framework.toml` that ends in `.git` loses the suffix: 0.11.0 refuses it, since the URL git is given adds its own
`.git` ([#238](https://github.com/HogJonny-AMZN/ai-first-template/issues/238)).

**The order, for a template on another GitHub host:** take 0.11.0 with the bare `owner/name` still in `upstream`,
and only then change it to `host/owner/name`. The tools a repository runs before the update refuse the host form;
until then git reaches a template on another host with a global `url.<base>.insteadOf`, as *Credentials* says.
Step 1 runs the repository's own `--upstream`, which before 0.11.0 reads with `gh`, and `gh` ignores git's
`insteadOf`: set `GH_HOST=<host>` for that run and log `gh` in to the host (`gh auth login --hostname <host>`),
or skip step 1 and read the release's version from its notes.

1. **Take 0.11.0 by hand**, by the steps above. The repository's own `framework_sync.py` is the one that runs, and
   before this release it has no `--update`; every later release can be taken with it. `make check` brings no new
   finding.
2. **`--upstream` reads the upstream with git, not `gh`.** A private upstream now needs git's credentials for
   `https://<upstream>.git` (with `github.com/` before a bare `owner/name`): run `git ls-remote https://<upstream>.git`
   from the repository to see that git can read it. The report's first line says `newest release vB`, with the tag's day when the lock is behind,
   and the window counts from the tag's day, not from a published GitHub Release's.
   **`upstream` can name its host:** `host/owner/name` is accepted, and the report names the host. A repository does
   nothing unless its template lives on another GitHub host; then it sets `upstream = "host/owner/name"` and gives
   git a credential for that host. Only a release that carries this change reads a host-qualified value, since
   `--upstream` and `--update` plan with the release's own `init`, which reads `framework.toml` with the release's
   own validator.
3. **The guide says more.** *With `--update`*; step 2 clones with git; step 3 sets the version in the lock's copy only,
   and a lock left at the old version is refused with its cause named; *When it goes wrong* names the refusals `init`
   makes ([#224](https://github.com/HogJonny-AMZN/ai-first-template/issues/224)).
4. **Wire the inline-script hook** (ledger entry 48), when `harness-adapters` is on. The managed list brings the hook
   and its test; the settings file that runs it is project-owned, so no list brings it. The
   [compatibility matrix](compatibility-matrix.md) names that file:
   - **The repository has none:** copy the one the render seeded, from `<scratch>/rendered/`.
   - **It has its own:** add the entry the matrix's *What follows from the matrix* shows, beside what is already
     there.

   The entry runs the hook with `uv run --no-config`, so a uv below the floor of step 5 cannot refuse it, and
   every shell call with it (with a floor, the hook's test fails a command without it). The hook's test fails until one of the two is done. Prove it once more by hand, from the repository's root:
   `printf '%s' '{"tool_name":"Bash","tool_input":{"command":"python -c 1"}}' | <the entry's command>`, with
   the project folder variable in it replaced by `.`, exits 2 with the entry's advice, and the same with `git status` exits 0. Asking the agent to run an inline
   script proves it too, but only in a session whose project folder is this repository (a downstream test of the
   0.11.0 candidate). A repository that already carries its own copy of the hook
   replaces it with this one, and adds a `**Promoted:**` line to its project entry; with `--update`, it commits the
   removal of its own copy and of the copy's test first, or `--update` refuses to plan (*With `--update`*).
5. **Parallel suites and a uv floor**, in this order:
   - **Update uv first** to 0.12.22 or later (`uv self update`), the first uv that writes `uv.lock`'s revision 5;
     an older one rewrites the lock as revision 3 and no check sees it. Once the floor is in `pyproject.toml`, an
     older uv refuses every `uv run` in the repository, and the hook too if its command lacks `--no-config`.
   - **The hook's command** is the one with `--no-config` (step 4). That also skips a user's or a system `uv.toml`
     (a Python install mirror, `native-tls`): a machine that needs one for the hook's Python sets the matching
     `UV_*` environment variable instead.
   - **The repository's own `pyproject.toml`** (project-owned, so no list brings it): `"pytest-xdist>=3.8"` in the
     `dev` group, `-n auto` at the end of `[tool.pytest.ini_options]` `addopts`, and
     `[tool.uv]` `required-version = ">=0.12.22"`. Then `uv lock`: the lock's first lines read `revision = 5`,
     whatever an older uv had written. `uv run` installs pytest-xdist with its next sync; where it cannot sync
     (`UV_NO_SYNC` set, or a sync that failed), run `uv sync` first, or pytest stops with `unrecognized
     arguments: -n`.
   - **Everything else that runs pytest gets pytest-xdist too:** a workflow, script, tox or nox session that
     installs a member's extras with pip, not the root's `dev` group, still reads `-n auto` from the root's
     `addopts` and stops with `unrecognized arguments: -n`. `make check` cannot see it, since it syncs the `dev`
     group; add `pytest-xdist>=3.8` to the extra those runs install, and relock (a downstream test of 0.11.0).
   - **A conftest hook that reports what tests set** (a terminal summary, a session-finish writer) prints nothing
     in parallel, with no failure: the tests run in workers and the hook in the controller. Look for one, and
     have the workers hand the state over or write it where the controller reads it (a downstream test of 0.11.0).
     The controller loads only the conftest at a test root, so the hook that reports goes there, not in a deeper
     folder's conftest; and a run started above a test root (`pytest packages`) loads none of them, so run the
     configured test paths.
   - **A test of the project's own that fails only in parallel shares state, or has a time bound** set on an idle
     machine, which a run with every core busy exceeds ([testing.md](testing.md)): fix it,
     or leave `-n auto` out until it is fixed. The managed files work without it, but not quickly: 0.11.0's
     `--update` and upstream tests run git many times, and on Windows they took one repository's serial suite from about
     2 minutes to about 10 (in parallel, under 3).
6. **Check it.** `make check` passes, and `--upstream` says `lock is current: 0.11.0 locked`.

## 0.11.1: the hook's wrappers and heredocs, and what 0.11.0's downstream updates found

0.11.1 is a patch: it fixes managed files and asks nothing new of a repository. The inline-script hook reads `xargs`,
`sudo` and `cmd /c` ([#241](https://github.com/HogJonny-AMZN/ai-first-template/issues/241)), reads a heredoc's body
whole, and no longer refuses a delimiter that holds `$(...)` or an escaped `<<\EOF`; `init` keeps the executable bit
when a release asks for it on a file that exists (from the update after this one: `--update` writes with the
repository's own `init`); `--update`'s report names the seeds it wrote and says its commit ran
no hooks. It gains no stage and adds no finding name or framework ledger entry. A repository on 0.10.x takes 0.11.0's
hand steps too, by *Several releases at once*.

1. **Take 0.11.1.** A repository on 0.11.0 runs its own `uv run python tools/framework_sync.py --update`, the first
   release it can take that way (*With `--update`*); one that keeps its own copy of the hook commits the removal of the
   copy first, or `--update` refuses to plan. `make check` brings no new finding.
2. **The guide says more about 0.11.0's step 5.** A repository that took 0.11.0 reads its new bullets: everything else
   that runs pytest (a pip extra, tox, nox) needs pytest-xdist too; a time bound set on an idle machine fails in
   parallel; a reporting conftest hook lives at a test root, and a run started above one loads none. `testing.md` says
   a filtered run (`-k`) can be slower in parallel.
3. **Check it.** `make check` passes, and `--upstream` says `lock is current: 0.11.1 locked`.
