# ADR-001: Adopt the AI-first framework from ai-first-template

**Status:** Accepted (HogJonny-AMZN, 2026-10-31, by making this repository from the template).

## Context

HogNoise is developed with AI agents whose sessions are stateless, so the repository has to carry what a session needs:
where the work is, what only a person may decide, the project's words, and how the process has failed before. The
framework in `ai-first-template` is one place that holds those patterns, with checks that go red when a rule is broken.

## Decision

This repository starts from `ai-first-template` version 0.4.0 and runs its process from the first commit: the entry file and the handoff, the
board with its gates and Icebox, the glossary, the journal, ADRs, and (as the template's increments land) the standards,
the ledger and the checks. `framework.toml` says which modules are on and `framework.lock` records the template version
and the day the files were made from it.

## Consequences

- Managed files are the template's: `init` refuses to overwrite one that was edited since the lock, unless `framework.toml`
  lists an override with a reason. The template's sync check, which reports the same drift in CI, is a later increment.
- An improvement to the process is made in the template first; until the sync check and `--update` exist, a newer
  template version is ported by hand.
- The seeded documents are this project's from now on; the template never overwrites them.
- Cost: a process to follow from day one, and a template version to keep track of.

## Revisit if

The framework's cost in this project outweighs what it catches, or the template stops being maintained.
