"""
HogNoise: check any rendering of the noise against the committed reference vectors.
Package: hog_noise/conformance

The vectors are raw little-endian float32 files and one ``manifest.json`` (the format:
Docs/superpowers/specs/2026-11-11-conformance-harness.md). `load` reads them and verifies every file against its digest;
`check` samples each selected case through the caller's ``sample`` (and ``warp``) and compares it by points, by shape,
or advisory. The advisory rule is `compare`'s, called and not restated. Standard library and numpy only.

    python -m hog_noise.conformance vectors --rendering numpy
"""

import dataclasses
import logging as _logging

import numpy as np
from numpy.typing import NDArray

_MODULE_NAME = "hog_noise.conformance"
__version__ = "0.1.0"
__updated__ = "2026-11-12"
_LOGGER = _logging.getLogger(_MODULE_NAME)

#: The manifest format this module reads.
FORMAT = 1
_F32 = np.dtype("<f4")


class ConformanceError(ValueError):
    """The vectors folder does not match its manifest, or the manifest is malformed."""


@dataclasses.dataclass(frozen=True)
class Bound:
    """
    How far a value may be from its reference.

    :param scale: The allowed absolute difference; 0 means bit-identical.
    :param coordinate_scaled: Scale it per point by ``max(1, max(abs(axis)) * frequency)``, for renderings whose error
        grows with the coordinate (float32 on a GPU).
    """

    scale: float
    coordinate_scaled: bool = False

    def __post_init__(self) -> None:
        if not self.scale >= 0.0:
            raise ValueError(f"a bound is not negative: {self.scale}")

    def per_point(self, frequency: float, axes: tuple[NDArray, ...]) -> NDArray[np.float64]:
        """The allowed difference at every point of a point set, given its coordinate arrays."""
        n = len(axes[0])
        if not self.coordinate_scaled:
            return np.full(n, float(self.scale))
        magnitude = np.max(np.abs(np.stack([np.asarray(a, np.float64) for a in axes])), axis=0)
        return float(self.scale) * np.maximum(1.0, magnitude * abs(float(frequency)))


def normalised_difference(diff: NDArray, allowed: NDArray) -> NDArray[np.float64]:
    """``diff / allowed`` per point; where ``allowed`` is 0 it is 0 for an exact match and infinity otherwise."""
    diff = np.asarray(diff, np.float64)
    allowed = np.asarray(allowed, np.float64)
    safe = np.where(allowed > 0.0, allowed, 1.0)
    return np.where(allowed > 0.0, diff / safe, np.where(diff == 0.0, 0.0, np.inf))
