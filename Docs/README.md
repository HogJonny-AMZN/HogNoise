# Docs

**Status:** Living

| Read this | For |
| --- | --- |
| [noise/GALLERY.md](noise/GALLERY.md) | every noise type rendered, generated from the enums |
| [decisions/ADR-007-noise-kernels-port.md](decisions/ADR-007-noise-kernels-port.md) | why a port rather than a binding, with the measurements |
| [decisions/ADR-008-numba-optional-and-benchmarked.md](decisions/ADR-008-numba-optional-and-benchmarked.md) | numba is optional, and only where a benchmark says so |
| [decisions/ADR-009-backend-ladder.md](decisions/ADR-009-backend-ladder.md) | the ladder: one capability, ordered rungs, an override that never falls through |
| [standards/failure-modes.md](standards/failure-modes.md) | how the work has gone wrong, as triggers |
| [PYTHON_UPGRADE_AND_FASTNOISE.md](PYTHON_UPGRADE_AND_FASTNOISE.md) | the original planning document; section 4 specifies the kernel |
| [DETAILED_FASTNOISE_PERF.md](DETAILED_FASTNOISE_PERF.md) | the performance measurements |

## These came from another project

The three ADRs, the planning document and the performance note were written in the private project this code was cut
from (LargeWorlds), before HogNoise existed. They are kept as the record of the decisions, so they still say
`large_worlds`, `FastNoiseSignal` and the old module paths. Read `large_worlds.signals.noise_kernels` as `hog_noise`,
`large_worlds.backends` as `hog_noise.backends`, and the override variable as `HOG_NOISE_BACKEND_<CAPABILITY>`. The
`legacy_numpy` rung they describe was not carried over. [../PROVENANCE.md](../PROVENANCE.md) lists what changed.
