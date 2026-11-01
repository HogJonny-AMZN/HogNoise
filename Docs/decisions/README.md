# Decisions

**Status:** Living. One ADR per structural decision, append-only. A decision is changed only by a new ADR that supersedes
it, with both ends stating the link; history is never edited. Every ADR names the condition under which it should be
reopened (*Revisit if*). A new ADR is named `ADR-YYYY-MM-DD-<slug>.md`, the day it was written, so two branches never
choose one name; the numbered ones stay as they are. Two ADRs with one id fail the docs check.

| ADR | Decision | Status |
| --- | --- | --- |
| [ADR-001](ADR-001-adopt-the-framework.md) | Adopt the AI-first framework from `ai-first-template` | Accepted |
| [ADR-007](ADR-007-noise-kernels-port.md) | Procedural noise is our own kernel port, with `pyfastnoiselite` as the reference (carried from the source project) | Accepted |
| [ADR-008](ADR-008-numba-optional-and-benchmarked.md) | numba is optional, and used only where a benchmark says so (carried from the source project) | Accepted |
| [ADR-009](ADR-009-backend-ladder.md) | One backend ladder per capability, with an override that never falls through (carried from the source project) | Accepted |
