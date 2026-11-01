# ADR-001: Adopt the AI-first framework from ai-first-template

**Status:** Accepted (HogJonny-AMZN, 2026-11-01: "I want the HogNoise to be based off of the ai-first-template"; adopt it
before publishing).

## Context

HogNoise was cut from a private project's noise stack and made to stand alone in three stages, with a small hand-written
process (an `AGENTS.md`, a three-entry ledger, a link test). It is developed with AI agents whose sessions are stateless, so
the repository has to carry what a session needs: where the work is, what only a person may decide, the project's words, and
how the process has failed before. `ai-first-template` holds those patterns, with checks that go red when a rule is broken,
and the owner's other repositories already run on it. Adopting before the first publication means the public repository
starts with the process instead of reconciling it later.

## Decision

The repository runs on `ai-first-template` 0.4.0, adopted with `init adopt --off specimens --take-all`, so **no file
overrides the template**: the three files that differed (`AGENTS.md`, `CLAUDE.md`, `Docs/standards/failure-modes.md`) took
the template's version, and HogNoise's own rules moved to the template's extension files (`python-project.md`,
`testing-project.md`, `definition-of-done-project.md`) and its ledger entries to `failure-modes-project.md` as P-1 to P-3.

- **The layout stays `src/hog_noise`**, the template's own convention: `framework.toml`'s `[layers]` table has the one layer
  `hog_noise`, and the boundary test holds it. `specimens`, the template's mock `src/`, is off.
- **The project's `pyproject.toml` stays the project's**, with the template's requirements merged in: the `dev` dependency
  group that `make sync` and CI install, and the template's ruff settings. The code was brought to those rules in full rather
  than excluded file by file, since nothing else was in flight.
- **The two records carried from the source project** (`ADR-009` and the roadmap) are excluded from formatting, since an ADR
  is append-only and the roadmap is history.

## Consequences

- `make check` is the gate, locally and in CI; the hooks run its fast stages on every commit.
- The template's `ci.yml` runs beside HogNoise's own `tests.yml`, whose numpy-only leg the template does not have; folding
  the two is a board row.
- A newer template version arrives through the template's update path; with no overrides, that is a lock and a sync, not a
  reconciliation.
- Cost: a process to follow, and a template version to keep current.

## Revisit if

The framework's cost in this project outweighs what it catches, or the template stops being maintained.
