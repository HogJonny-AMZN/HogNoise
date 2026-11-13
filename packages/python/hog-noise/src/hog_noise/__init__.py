"""
HogNoise: procedural noise kernels, the union of FastNoiseSIMD and FastNoiseLite over time.
Package: hog_noise

One parameter record (`NoiseParams`), one algorithm per
feature, rendered three ways and compared with the same tooling:

- `vectorized.py`: the numpy base. Always present, exact, allocates.
- `scalar.py`: the same algorithms compiled by numba when it is installed; the fast rung.
- the `pyfastnoiselite` binding: the reference the port was validated against, and the fallback
  on a machine without numba.

`samplers.py` registers those as the ``"noise"`` capability with `hog_noise.backends`, and
`make_sampler` is how a caller gets one. `compare.py` is the comparison tooling. Feature scope and
the phase plan: Docs/PYTHON_UPGRADE_AND_FASTNOISE.md, section 4.

Importing this package imports numba when it is installed (about 0.3 s, once per process) and
registers the ladder. Compilation is deferred to first use or to `warm_up`; without numba the
package imports with no extra cost and the ladder resolves to `pyfastnoiselite` or numpy.
"""

import logging as _logging

from hog_noise.families import FAMILIES, all_presets, enum_name
from hog_noise.params import (
    CELLULAR_DISTANCE_NAMES,
    CELLULAR_RETURN_NAMES,
    DOMAIN_WARP_NAMES,
    FRACTAL_TYPE_NAMES,
    IMPLEMENTED_FRACTAL_TYPES,
    IMPLEMENTED_NOISE_TYPES,
    NOISE_TYPE_NAMES,
    PERTURB_NAMES,
    CellularDistance,
    CellularReturn,
    DomainWarpType,
    FractalType,
    NoiseParams,
    NoiseType,
    PerturbType,
    Rotation3D,
    Transform3D,
    parse_cellular_distance,
    parse_cellular_return,
    parse_domain_warp,
    parse_fractal_type,
    parse_noise_type,
    parse_perturb,
)
from hog_noise.samplers import (
    CAPABILITY,
    FastNoiseLiteSampler,
    NumbaSampler,
    NumpySampler,
    make_sampler,
    warm_up,
)
from hog_noise.scalar import HAVE_NUMBA

_MODULE_NAME = "hog_noise"
__version__ = "0.1.0"
__updated__ = "2026-10-03"
_LOGGER = _logging.getLogger(_MODULE_NAME)

__all__ = [
    "CAPABILITY",
    "CELLULAR_DISTANCE_NAMES",
    "CELLULAR_RETURN_NAMES",
    "CellularDistance",
    "CellularReturn",
    "DOMAIN_WARP_NAMES",
    "DomainWarpType",
    "PERTURB_NAMES",
    "PerturbType",
    "parse_cellular_distance",
    "parse_cellular_return",
    "parse_domain_warp",
    "parse_perturb",
    "FRACTAL_TYPE_NAMES",
    "HAVE_NUMBA",
    "IMPLEMENTED_FRACTAL_TYPES",
    "IMPLEMENTED_NOISE_TYPES",
    "NOISE_TYPE_NAMES",
    "FastNoiseLiteSampler",
    "FractalType",
    "NoiseParams",
    "NoiseType",
    "NumbaSampler",
    "NumpySampler",
    "Rotation3D",
    "Transform3D",
    "FAMILIES",
    "all_presets",
    "enum_name",
    "make_sampler",
    "parse_fractal_type",
    "parse_noise_type",
    "warm_up",
]
