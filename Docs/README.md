# Docs

**Status:** Living

| Read this | For |
| --- | --- |
| [design/2026-11-01-north-star-roadmap.md](design/2026-11-01-north-star-roadmap.md) | the north star and the roadmap to it (Proposed) |
| [findability.md](findability.md) | who searches for HogNoise and why, and the surfaces (README, topics, metadata, llms.txt) that must say so |
| [noise/GALLERY.md](noise/GALLERY.md) | every noise type rendered, generated from the enums |
| [decisions/ADR-007-noise-kernels-port.md](decisions/ADR-007-noise-kernels-port.md) | why a port rather than a binding, with the measurements |
| [decisions/ADR-008-numba-optional-and-benchmarked.md](decisions/ADR-008-numba-optional-and-benchmarked.md) | numba is optional, and only where a benchmark says so |
| [decisions/ADR-009-backend-ladder.md](decisions/ADR-009-backend-ladder.md) | the ladder: one capability, ordered rungs, an override that never falls through |
| [standards/failure-modes.md](standards/failure-modes.md) | the framework's ledger, from the template: how the work has gone wrong, as triggers |
| [PYTHON_UPGRADE_AND_FASTNOISE.md](PYTHON_UPGRADE_AND_FASTNOISE.md) | the original planning document; section 4 specifies the kernel |
| [DETAILED_FASTNOISE_PERF.md](DETAILED_FASTNOISE_PERF.md) | the performance measurements |
| [standards/failure-modes-project.md](standards/failure-modes-project.md) | this project's ledger: how the process went wrong here (P-1 onwards) |
| [standards/python-project.md](standards/python-project.md), [testing-project.md](standards/testing-project.md), [definition-of-done-project.md](standards/definition-of-done-project.md) | HogNoise's additions to the template's standards: the package boundary, the vectors as the oracle, claims that follow the vectors |
| [plan/board/README.md](plan/board/README.md) | how a board row is written |
| [standards/compatibility-matrix.md](standards/compatibility-matrix.md) | which coding harnesses the framework supports, and how well |
| [standards/harness-probes.md](standards/harness-probes.md) | the conformance probe each enabled harness must pass |
| [knowledge/ai-first-framework-graph.md](knowledge/ai-first-framework-graph.md) | the framework's documents and checks, as a graph |

## These came from another project

The three ADRs, the planning document and the performance note were written in the private project this code was cut
from (LargeWorlds), before HogNoise existed. They are kept as the record of the decisions, so they still say
`large_worlds`, `FastNoiseSignal` and the old module paths. Read `large_worlds.signals.noise_kernels` as `hog_noise`,
`large_worlds.backends` as `hog_noise.backends`, and the override variable as `HOG_NOISE_BACKEND_<CAPABILITY>`. The
`legacy_numpy` rung they describe was not carried over. [../PROVENANCE.md](../PROVENANCE.md) lists what changed.
