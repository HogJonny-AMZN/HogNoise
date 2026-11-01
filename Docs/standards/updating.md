# Taking a template release into a repository

**Status:** Living. Managed by the template: a repository's copy must match, so do not edit it here; propose a change to the
template. How a repository made from the template (`init new`) or brought under it (`init adopt`) takes a newer release. It is
a **hand procedure** until `framework_sync.py --update` exists; when that does, it replaces steps 2 to 5.

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

## The steps

1. **See what moved.** `uv run python tools/framework_sync.py --upstream` prints `lock is behind: A locked, B current, N managed
   file(s) changed` and lists each path as `changed`, `added` or `removed` (and marks one the repository overrides). It writes
   nothing. **It says "current" whenever the versions are equal, without comparing files**, so a fix released without a version
   bump is not seen: the template bumps the version for every release.
2. **Get the release.** Clone the tag into a scratch folder **outside** the repository:
   `gh repo clone <upstream> <scratch>/template -- --branch vB --depth 1` (the upstream is `[framework] upstream` in
   `framework.toml`). Read `gh release view vB --repo <upstream>` (`--repo`, because `gh` otherwise looks at the repository you
   are standing in): it says what a repository has to do beyond the files.
3. **Render it for this repository.** Make `<scratch>/rendered` and copy the repository's `project.json`, `framework.toml` and
   `framework.lock` into it, then change `template_version` to B **in the copies of the last two** (so `init` accepts the lock).
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
     template. An extension (`python-project.md` beside `python.md`, `project.md` in a skill's folder) is never
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
7. **Commit it on the branch and open one pull request** that names the release, lists the paths ported, and says what was
   kept as an override and why. Nothing is committed for you.

## When it goes wrong

- *Step 3 refuses (exit 1) or fails (exit 2).* The message names the file or the answer. The usual causes are a `--target` that
  is not empty, or a release that changed what `project.json` must hold (read the release notes). The rendered folder is
  scratch: delete it and run again.
- *`--check` reports `edited` after step 5.* A path from the list in step 1 was not ported, or was ported from the wrong
  folder. Run `diff <path> <scratch>/rendered/<path>`.
- *`--check` reports `override-stale`.* A kept override now equals the template's version: delete the override.
- *`--upstream` still says behind.* The version in `framework.toml` or the lock was not set to B, or B is not the latest
  release: run step 1 again.
- *A file you did not expect is in the list.* The release changed a managed file for every repository; read the release
  notes before keeping an override.

Missing the next release costs more than this one: `--upstream` exits 1 when a lock has been behind for longer than
`max_age_days` (default 14, under `[framework]` in `framework.toml`), so the procedure is best run when it is first reported.
