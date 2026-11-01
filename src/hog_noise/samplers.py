"""
HogNoise: the rungs of the noise ladder, each a sampler built from `NoiseParams`.
Package: hog_noise/samplers

Registered with `hog_noise.backends` under the capability ``"noise"``:

| name             | priority | what                                                         |
| ---------------- | -------- | ------------------------------------------------------------ |
| ``numba``        | 100      | `scalar.py` compiled by numba, parallel over points          |
| ``fastnoiselite``| 50       | the `pyfastnoiselite` binding, the reference for the port    |
| ``numpy``        | 0        | `vectorized.py`, always available, slow but exact            |

All three produce the same noise for the same `NoiseParams` (within float32 rounding for the
binding, exactly between numba and numpy).

Every sampler exposes the same three calls, all filling a preallocated float32 ``out``:
``sample_points(xs, ys, zs, out)``, ``sample_points_2d(xs, ys, out)`` and ``sample(x, y, z)`` for a
single value.
"""

import logging as _logging
import sys
from typing import Optional, Tuple

import numpy as np
from numpy.typing import NDArray

from hog_noise import scalar, vectorized
from hog_noise.backends import Backend, register
from hog_noise.params import (
    IMPLEMENTED_FRACTAL_TYPES,
    IMPLEMENTED_NOISE_TYPES,
    CellularDistance,
    CellularReturn,
    FractalType,
    NoiseParams,
    NoiseType,
    PerturbType,
)

_MODULE_NAME = "hog_noise.samplers"
__version__ = "0.1.0"
__updated__ = "2026-09-13"
_LOGGER = _logging.getLogger(_MODULE_NAME)

CAPABILITY = "noise"


# -------------------------------------------------------------------------
class _KernelSampler:
    """Sampler over the `scalar`/`vectorized` driver pair; the two share one calling convention."""

    name = "kernel"

    def __init__(self, params: NoiseParams, module) -> None:
        self.params = params
        self._module = module
        args = params.kernel_args()
        self._seed = args[0]
        self._frequency = np.float32(args[1])
        self._common = args[2:13]  # noise/fractal scalars through the cellular settings
        self._transform = args[13]
        self._warp_2d = args[14:17]  # domain_warp, warp_amp, warp_fractal
        self._warp_3d = args[14:18]  # ... and the warp's own 3D transform
        self._lookup = args[18:20]  # the NoiseLookup return's noise type and frequency
        self._perturb = args[20:27]  # FastNoiseSIMD's gradient perturb
        self._octaves, self._lacunarity, self._gain = args[4], args[5], args[6]
        self._scratch = np.empty(1, dtype=np.float32)

    def sample_points(self, xs: NDArray, ys: NDArray, zs: NDArray, out: NDArray[np.float32]) -> NDArray[np.float32]:
        self._module.sample_3d(
            np.asarray(xs, np.float32),
            np.asarray(ys, np.float32),
            np.asarray(zs, np.float32),
            out,
            self._seed,
            self._frequency,
            *self._common,
            self._transform,
            *self._warp_3d,
            *self._lookup,
            *self._perturb,
        )
        return out

    def sample_points_2d(self, xs: NDArray, ys: NDArray, out: NDArray[np.float32]) -> NDArray[np.float32]:
        self._module.sample_2d(
            np.asarray(xs, np.float32),
            np.asarray(ys, np.float32),
            out,
            self._seed,
            self._frequency,
            *self._common,
            *self._warp_2d,
            *self._lookup,
            *self._perturb,
        )
        return out

    def sample_grid(
        self,
        start: Tuple[int, int, int],
        shape: Tuple[int, int, int],
        scales: Tuple[float, float, float] = (1.0, 1.0, 1.0),
    ) -> NDArray[np.float32]:
        """
        Values on an axis-aligned grid, ``(nx, ny, nz)`` float32 indexed ``[ix, iy, iz]``, at
        ``((x0 + ix) * sx, (y0 + iy) * sy, (z0 + iz) * sz)``: the retired library's ``genAsGrid`` with its
        axis scales. On the numba rung the kernel computes the coordinates itself, so a tile heightfield costs
        no coordinate arrays; the numpy base and the binding materialise them (three float32
        arrays of the grid's size) and sample. A heightfield over x and z is ``shape=(nx, 1, nz)`` with
        ``start[1]`` the row's y cell.
        """
        out = np.empty(tuple(int(n) for n in shape), dtype=np.float32)
        x0, y0, z0 = (int(v) for v in start)
        sx, sy, sz = (float(v) for v in scales)
        self._module.sample_grid(
            out,
            x0,
            y0,
            z0,
            sx,
            sy,
            sz,
            self._seed,
            self._frequency,
            *self._common,
            self._transform,
            *self._warp_3d,
            *self._lookup,
            *self._perturb,
        )
        return out

    def warp_points(self, xs: NDArray, ys: NDArray, zs: NDArray) -> NDArray[np.float32]:
        """
        The warped raw coordinates, ``(N, 3)`` float32: what the noise would sample at. The reference's
        ``DomainWarp`` on its own, for the oracle comparison and for callers that want the warp field.
        """
        n = len(xs)
        out = np.empty((n, 3), dtype=np.float32)
        self._module.warp_3d(
            np.asarray(xs, np.float32),
            np.asarray(ys, np.float32),
            np.asarray(zs, np.float32),
            out[:, 0],
            out[:, 1],
            out[:, 2],
            self._seed,
            self._frequency,
            self._octaves,
            self._lacunarity,
            self._gain,
            *self._warp_3d,
        )
        return out

    def warp_points_2d(self, xs: NDArray, ys: NDArray) -> NDArray[np.float32]:
        """2D twin of `warp_points`: ``(N, 2)`` float32."""
        n = len(xs)
        out = np.empty((n, 2), dtype=np.float32)
        self._module.warp_2d(
            np.asarray(xs, np.float32),
            np.asarray(ys, np.float32),
            out[:, 0],
            out[:, 1],
            self._seed,
            self._frequency,
            self._octaves,
            self._lacunarity,
            self._gain,
            *self._warp_2d,
        )
        return out

    def sample(self, x: float, y: float, z: float = 0.0) -> float:
        # One value through the scalar entry, never the parallel driver: a prange launch costs
        # tens of microseconds, the scalar path a few. Both rungs use `scalar` here; with numba it
        # is compiled, without it plain Python, and both produce the same float64 arithmetic as
        # the vectorised base, so the rungs still agree exactly.
        return float(
            scalar.sample_one_3d(
                float(x),
                float(y),
                float(z),
                self._seed,
                self._frequency,
                *self._common,
                self._transform,
                *self._warp_3d,
                *self._lookup,
                *self._perturb,
            )
        )


class NumbaSampler(_KernelSampler):
    """The compiled kernel. `scalar.HAVE_NUMBA` gates its availability."""

    name = "numba"

    def __init__(self, params: NoiseParams) -> None:
        super().__init__(params, scalar)


class NumpySampler(_KernelSampler):
    """The vectorised base implementation. Always available."""

    name = "numpy"

    def __init__(self, params: NoiseParams) -> None:
        super().__init__(params, vectorized)


# -------------------------------------------------------------------------
_FNL_NOISE = {
    NoiseType.OPEN_SIMPLEX2: "NoiseType_OpenSimplex2",
    NoiseType.OPEN_SIMPLEX2S: "NoiseType_OpenSimplex2S",
    NoiseType.CELLULAR: "NoiseType_Cellular",
    NoiseType.PERLIN: "NoiseType_Perlin",
    NoiseType.VALUE_CUBIC: "NoiseType_ValueCubic",
    NoiseType.VALUE: "NoiseType_Value",
}
_FNL_FRACTAL = {
    FractalType.NONE: "FractalType_None",
    FractalType.FBM: "FractalType_FBm",
    FractalType.RIDGED: "FractalType_Ridged",
    FractalType.PING_PONG: "FractalType_PingPong",
    FractalType.DOMAIN_WARP_PROGRESSIVE: "FractalType_DomainWarpProgressive",
    FractalType.DOMAIN_WARP_INDEPENDENT: "FractalType_DomainWarpIndependent",
}
_FNL_ROTATION = {0: "RotationType3D_None", 1: "RotationType3D_ImproveXYPlanes", 2: "RotationType3D_ImproveXZPlanes"}
_FNL_CELL_DIST = {
    CellularDistance.EUCLIDEAN: "CellularDistanceFunction_Euclidean",
    CellularDistance.EUCLIDEAN_SQ: "CellularDistanceFunction_EuclideanSq",
    CellularDistance.MANHATTAN: "CellularDistanceFunction_Manhattan",
    CellularDistance.HYBRID: "CellularDistanceFunction_Hybrid",
}
_FNL_CELL_RET = {
    CellularReturn.CELL_VALUE: "CellularReturnType_CellValue",
    CellularReturn.DISTANCE: "CellularReturnType_Distance",
    CellularReturn.DISTANCE2: "CellularReturnType_Distance2",
    CellularReturn.DISTANCE2_ADD: "CellularReturnType_Distance2Add",
    CellularReturn.DISTANCE2_SUB: "CellularReturnType_Distance2Sub",
    CellularReturn.DISTANCE2_MUL: "CellularReturnType_Distance2Mul",
    CellularReturn.DISTANCE2_DIV: "CellularReturnType_Distance2Div",
}


def _have_fastnoiselite() -> bool:
    try:
        import pyfastnoiselite.pyfastnoiselite  # noqa: F401
    except ImportError:
        return False
    return True


def grid_points(
    start: Tuple[int, int, int], shape: Tuple[int, int, int], scales: Tuple[float, float, float] = (1.0, 1.0, 1.0)
) -> Tuple[NDArray[np.float32], NDArray[np.float32], NDArray[np.float32]]:
    """The coordinates a `sample_grid` call samples, materialised, flat and in the grid's C order."""
    nx, ny, nz = (int(n) for n in shape)
    x0, y0, z0 = (int(v) for v in start)
    sx, sy, sz = (float(v) for v in scales)
    ix, iy, iz = np.meshgrid(np.arange(nx), np.arange(ny), np.arange(nz), indexing="ij")
    return (
        ((x0 + ix) * sx).astype(np.float32).ravel(),
        ((y0 + iy) * sy).astype(np.float32).ravel(),
        ((z0 + iz) * sz).astype(np.float32).ravel(),
    )


def _grid_via_points(sampler, start, shape, scales) -> NDArray[np.float32]:
    xs, ys, zs = grid_points(start, shape, scales)
    out = np.empty(len(xs), dtype=np.float32)
    sampler.sample_points(xs, ys, zs, out)
    return out.reshape(tuple(int(n) for n in shape))


class FastNoiseLiteSampler:
    """The `pyfastnoiselite` binding configured from `NoiseParams`. The port's reference."""

    name = "fastnoiselite"

    def __init__(self, params: NoiseParams) -> None:
        from pyfastnoiselite.pyfastnoiselite import CellularDistanceFunction as CDF
        from pyfastnoiselite.pyfastnoiselite import CellularReturnType as CRT
        from pyfastnoiselite.pyfastnoiselite import FastNoiseLite
        from pyfastnoiselite.pyfastnoiselite import FractalType as FT
        from pyfastnoiselite.pyfastnoiselite import NoiseType as NT
        from pyfastnoiselite.pyfastnoiselite import RotationType3D as RT

        self.params = params
        noise = FastNoiseLite(seed=params.seed)
        noise.noise_type = getattr(NT, _FNL_NOISE.get(params.noise_type, "NoiseType_OpenSimplex2"))
        noise.frequency = params.frequency
        noise.rotation_type_3d = getattr(RT, _FNL_ROTATION[int(params.rotation_3d)])
        noise.fractal_type = getattr(FT, _FNL_FRACTAL.get(params.fractal_type, "FractalType_None"))
        noise.fractal_octaves = params.octaves
        noise.fractal_lacunarity = params.lacunarity
        noise.fractal_gain = params.gain
        noise.fractal_weighted_strength = params.weighted_strength
        noise.fractal_ping_pong_strength = params.ping_pong_strength
        noise.cellular_distance_function = getattr(
            CDF, _FNL_CELL_DIST.get(params.cellular_distance, "CellularDistanceFunction_EuclideanSq")
        )
        noise.cellular_return_type = getattr(
            CRT, _FNL_CELL_RET.get(params.cellular_return, "CellularReturnType_Distance")
        )
        noise.cellular_jitter = params.cellular_jitter
        self._noise = noise
        # pyfastnoiselite 0.0.7 binds GetNoise only, never DomainWarp, so a warped configuration
        # warps through the numpy base and samples the binding at the warped points (logged once).
        self._warp: Optional[NumpySampler] = NumpySampler(params) if params.domain_warp else None
        if self._warp is not None:
            _LOGGER.info("pyfastnoiselite exposes no DomainWarp; the numpy base warps, the binding samples")
        # FastNoiseLite has no Billow and no white noise (FastNoiseSIMD's, Phase C): the numpy base
        # answers for the binding on those
        fns_only = (
            params.fractal_type in (FractalType.BILLOW, FractalType.RIGID_MULTI)
            or params.noise_type in (NoiseType.WHITE_NOISE, NoiseType.SIMPLEX_CLASSIC)
            or (
                params.noise_type == NoiseType.CELLULAR  # cellular settings are ignored by other types
                and (
                    params.cellular_distance == CellularDistance.NATURAL
                    or params.cellular_return in (CellularReturn.NOISE_LOOKUP, CellularReturn.DISTANCE2_CAVE)
                )
            )
            or params.perturb != PerturbType.NONE
        )
        self._delegate: Optional[NumpySampler] = NumpySampler(params) if fns_only else None
        if self._delegate is not None:
            _LOGGER.info("pyfastnoiselite lacks this FastNoiseSIMD feature; the numpy base answers on this rung")

    def sample_points(self, xs: NDArray, ys: NDArray, zs: NDArray, out: NDArray[np.float32]) -> NDArray[np.float32]:
        if self._delegate is not None:
            return self._delegate.sample_points(xs, ys, zs, out)
        coords = np.stack([np.asarray(xs, np.float32), np.asarray(ys, np.float32), np.asarray(zs, np.float32)])
        if self._warp is not None:
            coords = np.ascontiguousarray(self._warp.warp_points(xs, ys, zs).T)
        out[...] = self._noise.gen_from_coords(coords)
        return out

    def sample_points_2d(self, xs: NDArray, ys: NDArray, out: NDArray[np.float32]) -> NDArray[np.float32]:
        if self._delegate is not None:
            return self._delegate.sample_points_2d(xs, ys, out)
        coords = np.stack([np.asarray(xs, np.float32), np.asarray(ys, np.float32)])
        if self._warp is not None:
            coords = np.ascontiguousarray(self._warp.warp_points_2d(xs, ys).T)
        out[...] = self._noise.gen_from_coords(coords)
        return out

    def sample_grid(self, start, shape, scales=(1.0, 1.0, 1.0)) -> NDArray[np.float32]:
        return _grid_via_points(self, start, shape, scales)

    def sample(self, x: float, y: float, z: float = 0.0) -> float:
        if self._delegate is not None:
            return self._delegate.sample(x, y, z)
        if self._warp is not None:
            x, y, z = (float(v) for v in self._warp.warp_points([x], [y], [z])[0])
        return float(self._noise.get_noise(float(x), float(y), float(z)))


# -------------------------------------------------------------------------
register(
    Backend(
        CAPABILITY, "numba", 100, lambda: scalar.HAVE_NUMBA, NumbaSampler, note="compiled kernels, parallel over points"
    )
)
register(
    Backend(
        CAPABILITY,
        "fastnoiselite",
        50,
        _have_fastnoiselite,
        FastNoiseLiteSampler,
        note="pyfastnoiselite binding, single-threaded",
    )
)
register(Backend(CAPABILITY, "numpy", 0, lambda: True, NumpySampler, note="vectorised numpy base"))


def make_sampler(params: NoiseParams, backend: Optional[str] = None):
    """
    Build a sampler for ``params`` from the selected backend.

    :param params: Noise parameters.
    :param backend: A backend name to use instead of `backends.select`; tests and tools.
    :return: A sampler and the `backends.Selection` behind it (``None`` when ``backend`` is given).
    """
    from hog_noise import backends

    if backend is not None:
        # An explicit name goes through the ladder's forced path so an unavailable rung raises
        # (BackendUnavailable) instead of building a sampler that would silently run the
        # uncompiled Python. Same contract as the environment override.
        selection = backends.select(CAPABILITY, environ={backends.env_var_for(CAPABILITY): backend})
        return selection.backend.factory(params), None
    selection = backends.select(CAPABILITY)
    return selection.backend.factory(params), selection


def warm_up() -> float:
    """
    Trigger the numba compile (or cache load) so it never lands inside a frame.

    :return: Seconds spent, 0.0 when numba is absent.
    """
    if not scalar.HAVE_NUMBA:
        return 0.0
    import time

    t0 = time.perf_counter()
    xs = np.zeros(8, np.float32)
    out = np.empty(8, np.float32)
    # Every implemented type against every implemented fractal. numba compiles a driver whole on its first
    # call, whatever the integer arguments, so one call would do for the compile; the full matrix also runs
    # every branch once at setup, where a runtime error belongs, not in a frame
    for noise_type in sorted(IMPLEMENTED_NOISE_TYPES):
        for fractal_type in sorted(IMPLEMENTED_FRACTAL_TYPES):
            sampler = NumbaSampler(NoiseParams(noise_type=noise_type, fractal_type=fractal_type, octaves=2))
            sampler.sample_points(xs, xs, xs, out)
            sampler.sample(0.0, 0.0, 0.0)  # the scalar entry compiles separately from the batch drivers
            sampler.sample_points_2d(xs, xs, out)
    # the grid driver compiles separately from the point drivers
    NumbaSampler(NoiseParams(octaves=2)).sample_grid((0, 0, 0), (2, 1, 2))
    elapsed = time.perf_counter() - t0
    _LOGGER.info(f"noise kernels warm: {1000 * elapsed:.0f} ms (numba {sys.modules['numba'].__version__})")
    return elapsed


if __name__ == "__main__":
    _logging.basicConfig(level=_logging.INFO)

    p = NoiseParams(
        seed=42, frequency=0.01, noise_type=NoiseType.OPEN_SIMPLEX2, fractal_type=FractalType.FBM, octaves=4
    )
    sampler, selection = make_sampler(p)
    print(selection.describe())
    print("sample(10, 20, 0):", sampler.sample(10.0, 20.0, 0.0))
    xs = np.linspace(-100, 100, 5, dtype=np.float32)
    out = np.empty(5, np.float32)
    for name in ("numba", "fastnoiselite", "numpy"):
        s, _ = make_sampler(p, backend=name)
        print(f"{name:14s}", np.round(s.sample_points(xs, xs, np.zeros(5, np.float32), out.copy()), 5))
    print(f"warm-up: {1000 * warm_up():.0f} ms")
