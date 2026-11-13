"""
HogNoise: scalar noise kernels, written once, compiled by numba when it is present.
Package: hog_noise/scalar

Every function here is plain Python over scalars and NumPy arrays, in the shape numba compiles
without help: integer hashing emulated at 32 bits, no Python objects, no allocation inside the
per-point loop. With numba installed the module-level `_jit` decorator compiles them and the two
drivers at the bottom run under `prange`; without it the same functions run as ordinary Python,
which is the slow reference used by tests, never by the world loop (that is what `vectorized.py`
is for).

The algorithms are a line-for-line port of FastNoiseLite.h (MIT, Jordan Peck and contributors):
OpenSimplex2 and OpenSimplex2S (2D and 3D), Perlin, Value, ValueCubic, Cellular (every distance
function and return type), and the FBm, Ridged and PingPong fractals.
Two deliberate deviations from the reference, both recorded in the comparison report rather than
hidden: arithmetic is float64 after the float32 frequency multiply, and `fastmath` is off, so the
numpy base and this kernel agree exactly on every machine.
"""

import logging as _logging

import numpy as np

from hog_noise.tables import GRADIENTS_2D, GRADIENTS_3D, RAND_VECS_2D, RAND_VECS_3D

_MODULE_NAME = "hog_noise.scalar"
__version__ = "0.1.0"
__updated__ = "2026-09-13"
_LOGGER = _logging.getLogger(_MODULE_NAME)

try:
    from numba import njit, prange

    HAVE_NUMBA = True
except ImportError:  # pragma: no cover - exercised only where numba is absent
    HAVE_NUMBA = False
    prange = range

    def njit(*args, **kwargs):  # type: ignore[misc]
        """No-op stand-in so the module imports and runs as plain Python."""
        if args and callable(args[0]) and len(args) == 1 and not kwargs:
            return args[0]

        def _wrap(fn):
            return fn

        return _wrap


#: Kernel options. `fastmath` stays off: the numpy base and this kernel must agree exactly (D3).
_KERNEL_OPTS = dict(cache=True, fastmath=False, nogil=True)
_jit = njit(**_KERNEL_OPTS)

# Hash primes and constants from the reference.
PRIME_X = 501125321
PRIME_Y = 1136930381
PRIME_Z = 1720413743
_HASH_MUL = 0x27D4EB2D
_SQRT3 = 1.7320508075688772935274463415059
_F2 = 0.5 * (_SQRT3 - 1.0)
_G2 = (3.0 - _SQRT3) / 6.0
_R3 = 2.0 / 3.0

NOISE_OPEN_SIMPLEX2 = 0
NOISE_OPEN_SIMPLEX2S = 1
NOISE_CELLULAR = 2
NOISE_PERLIN = 3
NOISE_VALUE_CUBIC = 4
NOISE_VALUE = 5
NOISE_WHITE_NOISE = 6  # FastNoiseSIMD's (Phase C); past FastNoiseLite's range, which has none
NOISE_SIMPLEX_CLASSIC = 7  # FastNoiseSIMD's Simplex (Phase C): the look old seeds were authored with
# FastNoiseSIMD's hash, kept for the features that are its and not FastNoiseLite's (white noise).
_FNS_PRIME_X = 1619
_FNS_PRIME_Y = 31337
_FNS_PRIME_Z = 6971
_FNS_HASH_MUL = 60493
_FNS_HASH_TO_FLOAT = 1.0 / 2147483648.0
FRACTAL_NONE = 0
FRACTAL_FBM = 1
FRACTAL_RIDGED = 2
FRACTAL_PING_PONG = 3
FRACTAL_BILLOW = 6  # FastNoiseSIMD's (Phase C); numbered past FastNoiseLite's range on purpose
FRACTAL_RIGID_MULTI = 7  # FastNoiseSIMD's RigidMulti (Phase C): not FastNoiseLite's Ridged, which F1 assumed
CELL_DIST_EUCLIDEAN = 0
CELL_DIST_EUCLIDEAN_SQ = 1
CELL_DIST_MANHATTAN = 2
CELL_DIST_HYBRID = 3
CELL_DIST_NATURAL = 4  # FastNoiseSIMD's (Phase C): manhattan * euclidean squared, its distance form
CELL_RET_CELL_VALUE = 0
CELL_RET_DISTANCE = 1
CELL_RET_DISTANCE2 = 2
CELL_RET_DISTANCE2_ADD = 3
CELL_RET_DISTANCE2_SUB = 4
CELL_RET_DISTANCE2_MUL = 5
CELL_RET_DISTANCE2_DIV = 6
CELL_RET_NOISE_LOOKUP = 7  # FastNoiseSIMD's (Phase C)
CELL_RET_DISTANCE2_CAVE = 8
TRANSFORM_NONE = 0
TRANSFORM_IMPROVE_XY = 1
TRANSFORM_IMPROVE_XZ = 2
TRANSFORM_DEFAULT_OS2 = 3
# Domain warp (Phase B): the function, and how its octaves are applied.
WARP_NONE = 0
WARP_OPEN_SIMPLEX2 = 1
WARP_OPEN_SIMPLEX2_REDUCED = 2
WARP_BASIC_GRID = 3
WARP_SINGLE = 0
WARP_PROGRESSIVE = 1
WARP_INDEPENDENT = 2
# FastNoiseSIMD's gradient perturb (Phase C): applied to the frequency-scaled point, before the noise.
PERTURB_NONE = 0
PERTURB_GRADIENT = 1
PERTURB_GRADIENT_FRACTAL = 2
PERTURB_NORMALISE = 3
PERTURB_GRADIENT_NORMALISE = 4
PERTURB_GRADIENT_FRACTAL_NORMALISE = 5


# -------------------------------------------------------------------------
# 32-bit integer emulation and interpolation helpers
@_jit
def _wrap32(v):
    """Reduce an int64 to the int32 the reference would hold, two's complement."""
    return ((v + 0x80000000) & 0xFFFFFFFF) - 0x80000000


@_jit
def _hash2(seed, xp, yp):
    return _wrap32(_wrap32(seed ^ xp ^ yp) * _HASH_MUL)


@_jit
def _hash3(seed, xp, yp, zp):
    return _wrap32(_wrap32(seed ^ xp ^ yp ^ zp) * _HASH_MUL)


@_jit
def _val_coord2(seed, xp, yp):
    h = _hash2(seed, xp, yp)
    h = _wrap32(h * h)
    h = _wrap32(h ^ _wrap32(h << 19))
    return h * (1.0 / 2147483648.0)


@_jit
def _val_coord3(seed, xp, yp, zp):
    h = _hash3(seed, xp, yp, zp)
    h = _wrap32(h * h)
    h = _wrap32(h ^ _wrap32(h << 19))
    return h * (1.0 / 2147483648.0)


@_jit
def _grad_coord2(seed, xp, yp, xd, yd):
    h = _hash2(seed, xp, yp)
    h ^= h >> 15
    h &= 127 << 1
    return xd * GRADIENTS_2D[h] + yd * GRADIENTS_2D[h | 1]


@_jit
def _grad_coord3(seed, xp, yp, zp, xd, yd, zd):
    h = _hash3(seed, xp, yp, zp)
    h ^= h >> 15
    h &= 63 << 2
    return xd * GRADIENTS_3D[h] + yd * GRADIENTS_3D[h | 1] + zd * GRADIENTS_3D[h | 2]


@_jit
def _fast_floor(f):
    # The reference's quirk, kept for parity: (int)f - 1 for any negative f, integral or not.
    i = int(f)
    if f < 0:
        i -= 1
    return i


@_jit
def _fast_round(f):
    if f >= 0:
        return int(f + 0.5)
    return int(f - 0.5)


@_jit
def _lerp(a, b, t):
    return a + t * (b - a)


@_jit
def _interp_hermite(t):
    return t * t * (3.0 - 2.0 * t)


@_jit
def _interp_quintic(t):
    return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)


@_jit
def _cubic_lerp(a, b, c, d, t):
    p = (d - c) - (a - b)
    return t * t * t * p + t * t * ((a - b) - p) + t * (c - a) + b


@_jit
def _ping_pong(t):
    t -= int(t * 0.5) * 2
    return t if t < 1.0 else 2.0 - t


# -------------------------------------------------------------------------
# single-octave noise, 2D
@_jit
def simplex2(seed, x, y):
    """2D OpenSimplex2. ``x, y`` are already skewed by `_transform2`."""
    i = _fast_floor(x)
    j = _fast_floor(y)
    xi = x - i
    yi = y - j
    t = (xi + yi) * _G2
    x0 = xi - t
    y0 = yi - t
    i = _wrap32(i * PRIME_X)
    j = _wrap32(j * PRIME_Y)

    a = 0.5 - x0 * x0 - y0 * y0
    if a <= 0.0:
        n0 = 0.0
    else:
        n0 = (a * a) * (a * a) * _grad_coord2(seed, i, j, x0, y0)

    c = (2.0 * (1.0 - 2.0 * _G2) * (1.0 / _G2 - 2.0)) * t + ((-2.0 * (1.0 - 2.0 * _G2) * (1.0 - 2.0 * _G2)) + a)
    if c <= 0.0:
        n2 = 0.0
    else:
        x2 = x0 + (2.0 * _G2 - 1.0)
        y2 = y0 + (2.0 * _G2 - 1.0)
        n2 = (c * c) * (c * c) * _grad_coord2(seed, _wrap32(i + PRIME_X), _wrap32(j + PRIME_Y), x2, y2)

    if y0 > x0:
        x1 = x0 + _G2
        y1 = y0 + (_G2 - 1.0)
        b = 0.5 - x1 * x1 - y1 * y1
        if b <= 0.0:
            n1 = 0.0
        else:
            n1 = (b * b) * (b * b) * _grad_coord2(seed, i, _wrap32(j + PRIME_Y), x1, y1)
    else:
        x1 = x0 + (_G2 - 1.0)
        y1 = y0 + _G2
        b = 0.5 - x1 * x1 - y1 * y1
        if b <= 0.0:
            n1 = 0.0
        else:
            n1 = (b * b) * (b * b) * _grad_coord2(seed, _wrap32(i + PRIME_X), j, x1, y1)

    return (n0 + n1 + n2) * 99.83685446303647


@_jit
def simplex2s(seed, x, y):
    """2D OpenSimplex2S: the smoother variant, a modified 2D simplex. ``x, y`` already skewed by `_transform2`."""
    i = _fast_floor(x)
    j = _fast_floor(y)
    xi = x - i
    yi = y - j

    i = _wrap32(i * PRIME_X)
    j = _wrap32(j * PRIME_Y)
    i1 = _wrap32(i + PRIME_X)
    j1 = _wrap32(j + PRIME_Y)

    t = (xi + yi) * _G2
    x0 = xi - t
    y0 = yi - t

    a0 = (2.0 / 3.0) - x0 * x0 - y0 * y0
    value = (a0 * a0) * (a0 * a0) * _grad_coord2(seed, i, j, x0, y0)

    a1 = (2.0 * (1.0 - 2.0 * _G2) * (1.0 / _G2 - 2.0)) * t + ((-2.0 * (1.0 - 2.0 * _G2) * (1.0 - 2.0 * _G2)) + a0)
    x1 = x0 - (1.0 - 2.0 * _G2)
    y1 = y0 - (1.0 - 2.0 * _G2)
    value += (a1 * a1) * (a1 * a1) * _grad_coord2(seed, i1, j1, x1, y1)

    xmyi = xi - yi
    if t > _G2:
        if xi + xmyi > 1.0:
            x2 = x0 + (3.0 * _G2 - 2.0)
            y2 = y0 + (3.0 * _G2 - 1.0)
            a2 = (2.0 / 3.0) - x2 * x2 - y2 * y2
            if a2 > 0.0:
                value += (a2 * a2) * (a2 * a2) * _grad_coord2(seed, _wrap32(i + (PRIME_X << 1)), j1, x2, y2)
        else:
            x2 = x0 + _G2
            y2 = y0 + (_G2 - 1.0)
            a2 = (2.0 / 3.0) - x2 * x2 - y2 * y2
            if a2 > 0.0:
                value += (a2 * a2) * (a2 * a2) * _grad_coord2(seed, i, j1, x2, y2)

        if yi - xmyi > 1.0:
            x3 = x0 + (3.0 * _G2 - 1.0)
            y3 = y0 + (3.0 * _G2 - 2.0)
            a3 = (2.0 / 3.0) - x3 * x3 - y3 * y3
            if a3 > 0.0:
                value += (a3 * a3) * (a3 * a3) * _grad_coord2(seed, i1, _wrap32(j + (PRIME_Y << 1)), x3, y3)
        else:
            x3 = x0 + (_G2 - 1.0)
            y3 = y0 + _G2
            a3 = (2.0 / 3.0) - x3 * x3 - y3 * y3
            if a3 > 0.0:
                value += (a3 * a3) * (a3 * a3) * _grad_coord2(seed, i1, j, x3, y3)
    else:
        if xi + xmyi < 0.0:
            x2 = x0 + (1.0 - _G2)
            y2 = y0 - _G2
            a2 = (2.0 / 3.0) - x2 * x2 - y2 * y2
            if a2 > 0.0:
                value += (a2 * a2) * (a2 * a2) * _grad_coord2(seed, _wrap32(i - PRIME_X), j, x2, y2)
        else:
            x2 = x0 + (_G2 - 1.0)
            y2 = y0 + _G2
            a2 = (2.0 / 3.0) - x2 * x2 - y2 * y2
            if a2 > 0.0:
                value += (a2 * a2) * (a2 * a2) * _grad_coord2(seed, i1, j, x2, y2)

        if yi < xmyi:
            x3 = x0 - _G2
            y3 = y0 - (_G2 - 1.0)
            a3 = (2.0 / 3.0) - x3 * x3 - y3 * y3
            if a3 > 0.0:
                value += (a3 * a3) * (a3 * a3) * _grad_coord2(seed, i, _wrap32(j - PRIME_Y), x3, y3)
        else:
            x3 = x0 + _G2
            y3 = y0 + (_G2 - 1.0)
            a3 = (2.0 / 3.0) - x3 * x3 - y3 * y3
            if a3 > 0.0:
                value += (a3 * a3) * (a3 * a3) * _grad_coord2(seed, i, j1, x3, y3)

    return value * 18.24196194486065


@_jit
def perlin2(seed, x, y):
    x0 = _fast_floor(x)
    y0 = _fast_floor(y)
    xd0 = x - x0
    yd0 = y - y0
    xd1 = xd0 - 1.0
    yd1 = yd0 - 1.0
    xs = _interp_quintic(xd0)
    ys = _interp_quintic(yd0)
    x0 = _wrap32(x0 * PRIME_X)
    y0 = _wrap32(y0 * PRIME_Y)
    x1 = _wrap32(x0 + PRIME_X)
    y1 = _wrap32(y0 + PRIME_Y)
    xf0 = _lerp(_grad_coord2(seed, x0, y0, xd0, yd0), _grad_coord2(seed, x1, y0, xd1, yd0), xs)
    xf1 = _lerp(_grad_coord2(seed, x0, y1, xd0, yd1), _grad_coord2(seed, x1, y1, xd1, yd1), xs)
    return _lerp(xf0, xf1, ys) * 1.4247691104677813


@_jit
def value2(seed, x, y):
    x0 = _fast_floor(x)
    y0 = _fast_floor(y)
    xs = _interp_hermite(x - x0)
    ys = _interp_hermite(y - y0)
    x0 = _wrap32(x0 * PRIME_X)
    y0 = _wrap32(y0 * PRIME_Y)
    x1 = _wrap32(x0 + PRIME_X)
    y1 = _wrap32(y0 + PRIME_Y)
    xf0 = _lerp(_val_coord2(seed, x0, y0), _val_coord2(seed, x1, y0), xs)
    xf1 = _lerp(_val_coord2(seed, x0, y1), _val_coord2(seed, x1, y1), xs)
    return _lerp(xf0, xf1, ys)


@_jit
def value_cubic2(seed, x, y):
    x1 = _fast_floor(x)
    y1 = _fast_floor(y)
    xs = x - x1
    ys = y - y1
    x1 = _wrap32(x1 * PRIME_X)
    y1 = _wrap32(y1 * PRIME_Y)
    x0 = _wrap32(x1 - PRIME_X)
    y0 = _wrap32(y1 - PRIME_Y)
    x2 = _wrap32(x1 + PRIME_X)
    y2 = _wrap32(y1 + PRIME_Y)
    x3 = _wrap32(x1 + _wrap32(PRIME_X << 1))
    y3 = _wrap32(y1 + _wrap32(PRIME_Y << 1))
    return _cubic_lerp(
        _cubic_lerp(
            _val_coord2(seed, x0, y0),
            _val_coord2(seed, x1, y0),
            _val_coord2(seed, x2, y0),
            _val_coord2(seed, x3, y0),
            xs,
        ),
        _cubic_lerp(
            _val_coord2(seed, x0, y1),
            _val_coord2(seed, x1, y1),
            _val_coord2(seed, x2, y1),
            _val_coord2(seed, x3, y1),
            xs,
        ),
        _cubic_lerp(
            _val_coord2(seed, x0, y2),
            _val_coord2(seed, x1, y2),
            _val_coord2(seed, x2, y2),
            _val_coord2(seed, x3, y2),
            xs,
        ),
        _cubic_lerp(
            _val_coord2(seed, x0, y3),
            _val_coord2(seed, x1, y3),
            _val_coord2(seed, x2, y3),
            _val_coord2(seed, x3, y3),
            xs,
        ),
        ys,
    ) * (1.0 / (1.5 * 1.5))


# -------------------------------------------------------------------------
# single-octave noise, 3D
@_jit
def opensimplex2_3(seed, x, y, z):
    """3D OpenSimplex2. ``x, y, z`` are already rotated by `_transform3`."""
    i = _fast_round(x)
    j = _fast_round(y)
    k = _fast_round(z)
    x0 = x - i
    y0 = y - j
    z0 = z - k

    x_nsign = int(-1.0 - x0) | 1
    y_nsign = int(-1.0 - y0) | 1
    z_nsign = int(-1.0 - z0) | 1

    ax0 = x_nsign * -x0
    ay0 = y_nsign * -y0
    az0 = z_nsign * -z0

    i = _wrap32(i * PRIME_X)
    j = _wrap32(j * PRIME_Y)
    k = _wrap32(k * PRIME_Z)

    value = 0.0
    a = (0.6 - x0 * x0) - (y0 * y0 + z0 * z0)
    for step in range(2):
        if a > 0.0:
            value += (a * a) * (a * a) * _grad_coord3(seed, i, j, k, x0, y0, z0)

        b = a + 1.0
        i1 = i
        j1 = j
        k1 = k
        x1 = x0
        y1 = y0
        z1 = z0
        if ax0 >= ay0 and ax0 >= az0:
            x1 += x_nsign
            b -= x_nsign * 2.0 * x1
            i1 = _wrap32(i1 - x_nsign * PRIME_X)
        elif ay0 > ax0 and ay0 >= az0:
            y1 += y_nsign
            b -= y_nsign * 2.0 * y1
            j1 = _wrap32(j1 - y_nsign * PRIME_Y)
        else:
            z1 += z_nsign
            b -= z_nsign * 2.0 * z1
            k1 = _wrap32(k1 - z_nsign * PRIME_Z)

        if b > 0.0:
            value += (b * b) * (b * b) * _grad_coord3(seed, i1, j1, k1, x1, y1, z1)

        if step == 1:
            break

        ax0 = 0.5 - ax0
        ay0 = 0.5 - ay0
        az0 = 0.5 - az0
        x0 = x_nsign * ax0
        y0 = y_nsign * ay0
        z0 = z_nsign * az0
        a += (0.75 - ax0) - (ay0 + az0)
        i = _wrap32(i + ((x_nsign >> 1) & PRIME_X))
        j = _wrap32(j + ((y_nsign >> 1) & PRIME_Y))
        k = _wrap32(k + ((z_nsign >> 1) & PRIME_Z))
        x_nsign = -x_nsign
        y_nsign = -y_nsign
        z_nsign = -z_nsign
        seed = ~seed

    return value * 32.69428253173828125


@_jit
def opensimplex2s_3(seed, x, y, z):
    """3D OpenSimplex2S: two offset rotated cube grids. ``x, y, z`` are already rotated by `_transform3`."""
    i = _fast_floor(x)
    j = _fast_floor(y)
    k = _fast_floor(z)
    xi = x - i
    yi = y - j
    zi = z - k

    i = _wrap32(i * PRIME_X)
    j = _wrap32(j * PRIME_Y)
    k = _wrap32(k * PRIME_Z)
    seed2 = _wrap32(seed + 1293373)

    # 0 or -1 per axis: which half of the cell the point sits in (C truncation toward zero)
    x_nmask = int(-0.5 - xi)
    y_nmask = int(-0.5 - yi)
    z_nmask = int(-0.5 - zi)

    x0 = xi + x_nmask
    y0 = yi + y_nmask
    z0 = zi + z_nmask
    a0 = 0.75 - x0 * x0 - y0 * y0 - z0 * z0
    value = (
        (a0 * a0)
        * (a0 * a0)
        * _grad_coord3(
            seed,
            _wrap32(i + (x_nmask & PRIME_X)),
            _wrap32(j + (y_nmask & PRIME_Y)),
            _wrap32(k + (z_nmask & PRIME_Z)),
            x0,
            y0,
            z0,
        )
    )

    x1 = xi - 0.5
    y1 = yi - 0.5
    z1 = zi - 0.5
    a1 = 0.75 - x1 * x1 - y1 * y1 - z1 * z1
    value += (
        (a1 * a1)
        * (a1 * a1)
        * _grad_coord3(seed2, _wrap32(i + PRIME_X), _wrap32(j + PRIME_Y), _wrap32(k + PRIME_Z), x1, y1, z1)
    )

    x_flip0 = ((x_nmask | 1) << 1) * x1
    y_flip0 = ((y_nmask | 1) << 1) * y1
    z_flip0 = ((z_nmask | 1) << 1) * z1
    x_flip1 = (-2 - (x_nmask << 2)) * x1 - 1.0
    y_flip1 = (-2 - (y_nmask << 2)) * y1 - 1.0
    z_flip1 = (-2 - (z_nmask << 2)) * z1 - 1.0

    skip5 = False
    a2 = x_flip0 + a0
    if a2 > 0.0:
        x2 = x0 - (x_nmask | 1)
        value += (
            (a2 * a2)
            * (a2 * a2)
            * _grad_coord3(
                seed,
                _wrap32(i + (~x_nmask & PRIME_X)),
                _wrap32(j + (y_nmask & PRIME_Y)),
                _wrap32(k + (z_nmask & PRIME_Z)),
                x2,
                y0,
                z0,
            )
        )
    else:
        a3 = y_flip0 + z_flip0 + a0
        if a3 > 0.0:
            y3 = y0 - (y_nmask | 1)
            z3 = z0 - (z_nmask | 1)
            value += (
                (a3 * a3)
                * (a3 * a3)
                * _grad_coord3(
                    seed,
                    _wrap32(i + (x_nmask & PRIME_X)),
                    _wrap32(j + (~y_nmask & PRIME_Y)),
                    _wrap32(k + (~z_nmask & PRIME_Z)),
                    x0,
                    y3,
                    z3,
                )
            )

        a4 = x_flip1 + a1
        if a4 > 0.0:
            x4 = (x_nmask | 1) + x1
            value += (
                (a4 * a4)
                * (a4 * a4)
                * _grad_coord3(
                    seed2,
                    _wrap32(i + (x_nmask & (PRIME_X * 2))),
                    _wrap32(j + PRIME_Y),
                    _wrap32(k + PRIME_Z),
                    x4,
                    y1,
                    z1,
                )
            )
            skip5 = True

    skip9 = False
    a6 = y_flip0 + a0
    if a6 > 0.0:
        y6 = y0 - (y_nmask | 1)
        value += (
            (a6 * a6)
            * (a6 * a6)
            * _grad_coord3(
                seed,
                _wrap32(i + (x_nmask & PRIME_X)),
                _wrap32(j + (~y_nmask & PRIME_Y)),
                _wrap32(k + (z_nmask & PRIME_Z)),
                x0,
                y6,
                z0,
            )
        )
    else:
        a7 = x_flip0 + z_flip0 + a0
        if a7 > 0.0:
            x7 = x0 - (x_nmask | 1)
            z7 = z0 - (z_nmask | 1)
            value += (
                (a7 * a7)
                * (a7 * a7)
                * _grad_coord3(
                    seed,
                    _wrap32(i + (~x_nmask & PRIME_X)),
                    _wrap32(j + (y_nmask & PRIME_Y)),
                    _wrap32(k + (~z_nmask & PRIME_Z)),
                    x7,
                    y0,
                    z7,
                )
            )

        a8 = y_flip1 + a1
        if a8 > 0.0:
            y8 = (y_nmask | 1) + y1
            value += (
                (a8 * a8)
                * (a8 * a8)
                * _grad_coord3(
                    seed2,
                    _wrap32(i + PRIME_X),
                    _wrap32(j + (y_nmask & _wrap32(PRIME_Y << 1))),
                    _wrap32(k + PRIME_Z),
                    x1,
                    y8,
                    z1,
                )
            )
            skip9 = True

    skip_d = False
    aa = z_flip0 + a0
    if aa > 0.0:
        za = z0 - (z_nmask | 1)
        value += (
            (aa * aa)
            * (aa * aa)
            * _grad_coord3(
                seed,
                _wrap32(i + (x_nmask & PRIME_X)),
                _wrap32(j + (y_nmask & PRIME_Y)),
                _wrap32(k + (~z_nmask & PRIME_Z)),
                x0,
                y0,
                za,
            )
        )
    else:
        ab = x_flip0 + y_flip0 + a0
        if ab > 0.0:
            xb = x0 - (x_nmask | 1)
            yb = y0 - (y_nmask | 1)
            value += (
                (ab * ab)
                * (ab * ab)
                * _grad_coord3(
                    seed,
                    _wrap32(i + (~x_nmask & PRIME_X)),
                    _wrap32(j + (~y_nmask & PRIME_Y)),
                    _wrap32(k + (z_nmask & PRIME_Z)),
                    xb,
                    yb,
                    z0,
                )
            )

        ac = z_flip1 + a1
        if ac > 0.0:
            zc = (z_nmask | 1) + z1
            value += (
                (ac * ac)
                * (ac * ac)
                * _grad_coord3(
                    seed2,
                    _wrap32(i + PRIME_X),
                    _wrap32(j + PRIME_Y),
                    _wrap32(k + (z_nmask & _wrap32(PRIME_Z << 1))),
                    x1,
                    y1,
                    zc,
                )
            )
            skip_d = True

    if not skip5:
        a5 = y_flip1 + z_flip1 + a1
        if a5 > 0.0:
            y5 = (y_nmask | 1) + y1
            z5 = (z_nmask | 1) + z1
            value += (
                (a5 * a5)
                * (a5 * a5)
                * _grad_coord3(
                    seed2,
                    _wrap32(i + PRIME_X),
                    _wrap32(j + (y_nmask & _wrap32(PRIME_Y << 1))),
                    _wrap32(k + (z_nmask & _wrap32(PRIME_Z << 1))),
                    x1,
                    y5,
                    z5,
                )
            )

    if not skip9:
        a9 = x_flip1 + z_flip1 + a1
        if a9 > 0.0:
            x9 = (x_nmask | 1) + x1
            z9 = (z_nmask | 1) + z1
            value += (
                (a9 * a9)
                * (a9 * a9)
                * _grad_coord3(
                    seed2,
                    _wrap32(i + (x_nmask & (PRIME_X * 2))),
                    _wrap32(j + PRIME_Y),
                    _wrap32(k + (z_nmask & _wrap32(PRIME_Z << 1))),
                    x9,
                    y1,
                    z9,
                )
            )

    if not skip_d:
        ad = x_flip1 + y_flip1 + a1
        if ad > 0.0:
            xd = (x_nmask | 1) + x1
            yd = (y_nmask | 1) + y1
            value += (
                (ad * ad)
                * (ad * ad)
                * _grad_coord3(
                    seed2,
                    _wrap32(i + (x_nmask & _wrap32(PRIME_X << 1))),
                    _wrap32(j + (y_nmask & _wrap32(PRIME_Y << 1))),
                    _wrap32(k + PRIME_Z),
                    xd,
                    yd,
                    z1,
                )
            )

    return value * 9.046026385208288


@_jit
def perlin3(seed, x, y, z):
    x0 = _fast_floor(x)
    y0 = _fast_floor(y)
    z0 = _fast_floor(z)
    xd0 = x - x0
    yd0 = y - y0
    zd0 = z - z0
    xd1 = xd0 - 1.0
    yd1 = yd0 - 1.0
    zd1 = zd0 - 1.0
    xs = _interp_quintic(xd0)
    ys = _interp_quintic(yd0)
    zs = _interp_quintic(zd0)
    x0 = _wrap32(x0 * PRIME_X)
    y0 = _wrap32(y0 * PRIME_Y)
    z0 = _wrap32(z0 * PRIME_Z)
    x1 = _wrap32(x0 + PRIME_X)
    y1 = _wrap32(y0 + PRIME_Y)
    z1 = _wrap32(z0 + PRIME_Z)
    xf00 = _lerp(_grad_coord3(seed, x0, y0, z0, xd0, yd0, zd0), _grad_coord3(seed, x1, y0, z0, xd1, yd0, zd0), xs)
    xf10 = _lerp(_grad_coord3(seed, x0, y1, z0, xd0, yd1, zd0), _grad_coord3(seed, x1, y1, z0, xd1, yd1, zd0), xs)
    xf01 = _lerp(_grad_coord3(seed, x0, y0, z1, xd0, yd0, zd1), _grad_coord3(seed, x1, y0, z1, xd1, yd0, zd1), xs)
    xf11 = _lerp(_grad_coord3(seed, x0, y1, z1, xd0, yd1, zd1), _grad_coord3(seed, x1, y1, z1, xd1, yd1, zd1), xs)
    yf0 = _lerp(xf00, xf10, ys)
    yf1 = _lerp(xf01, xf11, ys)
    return _lerp(yf0, yf1, zs) * 0.964921414852142333984375


@_jit
def value3(seed, x, y, z):
    x0 = _fast_floor(x)
    y0 = _fast_floor(y)
    z0 = _fast_floor(z)
    xs = _interp_hermite(x - x0)
    ys = _interp_hermite(y - y0)
    zs = _interp_hermite(z - z0)
    x0 = _wrap32(x0 * PRIME_X)
    y0 = _wrap32(y0 * PRIME_Y)
    z0 = _wrap32(z0 * PRIME_Z)
    x1 = _wrap32(x0 + PRIME_X)
    y1 = _wrap32(y0 + PRIME_Y)
    z1 = _wrap32(z0 + PRIME_Z)
    xf00 = _lerp(_val_coord3(seed, x0, y0, z0), _val_coord3(seed, x1, y0, z0), xs)
    xf10 = _lerp(_val_coord3(seed, x0, y1, z0), _val_coord3(seed, x1, y1, z0), xs)
    xf01 = _lerp(_val_coord3(seed, x0, y0, z1), _val_coord3(seed, x1, y0, z1), xs)
    xf11 = _lerp(_val_coord3(seed, x0, y1, z1), _val_coord3(seed, x1, y1, z1), xs)
    yf0 = _lerp(xf00, xf10, ys)
    yf1 = _lerp(xf01, xf11, ys)
    return _lerp(yf0, yf1, zs)


@_jit
def _value_cubic3_row(seed, x0, x1, x2, x3, yp, zp, xs):
    return _cubic_lerp(
        _val_coord3(seed, x0, yp, zp),
        _val_coord3(seed, x1, yp, zp),
        _val_coord3(seed, x2, yp, zp),
        _val_coord3(seed, x3, yp, zp),
        xs,
    )


@_jit
def _value_cubic3_plane(seed, x0, x1, x2, x3, y0, y1, y2, y3, zp, xs, ys):
    return _cubic_lerp(
        _value_cubic3_row(seed, x0, x1, x2, x3, y0, zp, xs),
        _value_cubic3_row(seed, x0, x1, x2, x3, y1, zp, xs),
        _value_cubic3_row(seed, x0, x1, x2, x3, y2, zp, xs),
        _value_cubic3_row(seed, x0, x1, x2, x3, y3, zp, xs),
        ys,
    )


@_jit
def value_cubic3(seed, x, y, z):
    x1 = _fast_floor(x)
    y1 = _fast_floor(y)
    z1 = _fast_floor(z)
    xs = x - x1
    ys = y - y1
    zs = z - z1
    x1 = _wrap32(x1 * PRIME_X)
    y1 = _wrap32(y1 * PRIME_Y)
    z1 = _wrap32(z1 * PRIME_Z)
    x0 = _wrap32(x1 - PRIME_X)
    y0 = _wrap32(y1 - PRIME_Y)
    z0 = _wrap32(z1 - PRIME_Z)
    x2 = _wrap32(x1 + PRIME_X)
    y2 = _wrap32(y1 + PRIME_Y)
    z2 = _wrap32(z1 + PRIME_Z)
    x3 = _wrap32(x1 + _wrap32(PRIME_X << 1))
    y3 = _wrap32(y1 + _wrap32(PRIME_Y << 1))
    z3 = _wrap32(z1 + _wrap32(PRIME_Z << 1))
    return _cubic_lerp(
        _value_cubic3_plane(seed, x0, x1, x2, x3, y0, y1, y2, y3, z0, xs, ys),
        _value_cubic3_plane(seed, x0, x1, x2, x3, y0, y1, y2, y3, z1, xs, ys),
        _value_cubic3_plane(seed, x0, x1, x2, x3, y0, y1, y2, y3, z2, xs, ys),
        _value_cubic3_plane(seed, x0, x1, x2, x3, y0, y1, y2, y3, z3, xs, ys),
        zs,
    ) * (1.0 / (1.5 * 1.5 * 1.5))


# -------------------------------------------------------------------------
# cellular (Worley) noise
@_jit
def _cellular_finish(dist_func, ret_type, distance0, distance1, closest_hash):
    if dist_func == CELL_DIST_EUCLIDEAN and ret_type >= CELL_RET_DISTANCE:
        distance0 = np.sqrt(distance0)
        if ret_type >= CELL_RET_DISTANCE2:
            distance1 = np.sqrt(distance1)
    if ret_type == CELL_RET_CELL_VALUE:
        return closest_hash * (1.0 / 2147483648.0)
    if ret_type == CELL_RET_DISTANCE:
        return distance0 - 1.0
    if ret_type == CELL_RET_DISTANCE2:
        return distance1 - 1.0
    if ret_type == CELL_RET_DISTANCE2_ADD:
        return (distance1 + distance0) * 0.5 - 1.0
    if ret_type == CELL_RET_DISTANCE2_SUB:
        return distance1 - distance0 - 1.0
    if ret_type == CELL_RET_DISTANCE2_MUL:
        return distance1 * distance0 * 0.5 - 1.0
    if ret_type == CELL_RET_DISTANCE2_DIV:
        return distance0 / distance1 - 1.0
    return 0.0


@_jit
def _lookup_single2(noise_type, seed, x, y):
    """The noise a NoiseLookup cell samples, any type but cellular (a jitted function cannot recurse)."""
    x, y = _transform2(noise_type, x, y)
    if noise_type == NOISE_OPEN_SIMPLEX2:
        return simplex2(seed, x, y)
    if noise_type == NOISE_OPEN_SIMPLEX2S:
        return simplex2s(seed, x, y)
    if noise_type == NOISE_PERLIN:
        return perlin2(seed, x, y)
    if noise_type == NOISE_VALUE_CUBIC:
        return value_cubic2(seed, x, y)
    if noise_type == NOISE_VALUE:
        return value2(seed, x, y)
    if noise_type == NOISE_WHITE_NOISE:
        return white_noise2(seed, x, y)
    if noise_type == NOISE_SIMPLEX_CLASSIC:
        return simplex_classic2(seed, x, y)
    return 0.0


@_jit
def _lookup_single3(noise_type, seed, x, y, z):
    if noise_type == NOISE_OPEN_SIMPLEX2 or noise_type == NOISE_OPEN_SIMPLEX2S:
        x, y, z = _transform3(TRANSFORM_DEFAULT_OS2, x, y, z)
    if noise_type == NOISE_OPEN_SIMPLEX2:
        return opensimplex2_3(seed, x, y, z)
    if noise_type == NOISE_OPEN_SIMPLEX2S:
        return opensimplex2s_3(seed, x, y, z)
    if noise_type == NOISE_PERLIN:
        return perlin3(seed, x, y, z)
    if noise_type == NOISE_VALUE_CUBIC:
        return value_cubic3(seed, x, y, z)
    if noise_type == NOISE_VALUE:
        return value3(seed, x, y, z)
    if noise_type == NOISE_WHITE_NOISE:
        return white_noise3(seed, x, y, z)
    if noise_type == NOISE_SIMPLEX_CLASSIC:
        return simplex_classic3(seed, x, y, z)
    return 0.0


@_jit
def _cellular2_scan(seed, x, y, dist_func, jitter_mod):
    """The 3 x 3 scan: the two nearest distances, the nearest cell's hash and its jittered point."""
    xr = _fast_round(x)
    yr = _fast_round(y)
    distance0 = 1e10
    distance1 = 1e10
    closest_hash = 0
    cell_x = 0.0
    cell_y = 0.0
    jitter = 0.43701595 * jitter_mod
    x_primed = _wrap32((xr - 1) * PRIME_X)
    y_primed_base = _wrap32((yr - 1) * PRIME_Y)
    for xi in range(xr - 1, xr + 2):
        y_primed = y_primed_base
        for yi in range(yr - 1, yr + 2):
            h = _hash2(seed, x_primed, y_primed)
            idx = h & (255 << 1)
            vec_x = (xi - x) + RAND_VECS_2D[idx] * jitter
            vec_y = (yi - y) + RAND_VECS_2D[idx | 1] * jitter
            if dist_func == CELL_DIST_MANHATTAN:
                new_distance = abs(vec_x) + abs(vec_y)
            elif dist_func == CELL_DIST_HYBRID:
                new_distance = (abs(vec_x) + abs(vec_y)) + (vec_x * vec_x + vec_y * vec_y)
            elif dist_func == CELL_DIST_NATURAL:
                new_distance = (abs(vec_x) + abs(vec_y)) * (vec_x * vec_x + vec_y * vec_y)
            else:
                new_distance = vec_x * vec_x + vec_y * vec_y
            distance1 = max(min(distance1, new_distance), distance0)
            if new_distance < distance0:
                distance0 = new_distance
                closest_hash = h
                cell_x = xi + RAND_VECS_2D[idx] * jitter
                cell_y = yi + RAND_VECS_2D[idx | 1] * jitter
            y_primed = _wrap32(y_primed + PRIME_Y)
        x_primed = _wrap32(x_primed + PRIME_X)
    return distance0, distance1, closest_hash, cell_x, cell_y


@_jit
def cellular2(seed, x, y, dist_func, ret_type, jitter_mod, lookup_type, lookup_freq):
    if ret_type == CELL_RET_DISTANCE2_CAVE:
        # FastNoiseSIMD: the lesser of two Distance2Div fields, the second half a cell over and one seed on
        d0, d1, h, _cx, _cy = _cellular2_scan(seed, x, y, dist_func, jitter_mod)
        c0 = _cellular_finish(dist_func, CELL_RET_DISTANCE2_DIV, d0, d1, h)
        d0, d1, h, _cx, _cy = _cellular2_scan(_wrap32(seed + 1), x + 0.5, y + 0.5, dist_func, jitter_mod)
        c1 = _cellular_finish(dist_func, CELL_RET_DISTANCE2_DIV, d0, d1, h)
        return min(c0, c1)
    d0, d1, h, cx, cy = _cellular2_scan(seed, x, y, dist_func, jitter_mod)
    if ret_type == CELL_RET_NOISE_LOOKUP:
        # FastNoiseSIMD: the lookup noise at the nearest cell point, at its own frequency
        return _lookup_single2(lookup_type, seed, cx * lookup_freq, cy * lookup_freq)
    return _cellular_finish(dist_func, ret_type, d0, d1, h)


@_jit
def _cellular3_scan(seed, x, y, z, dist_func, jitter_mod):
    xr = _fast_round(x)
    yr = _fast_round(y)
    zr = _fast_round(z)
    distance0 = 1e10
    distance1 = 1e10
    closest_hash = 0
    cell_x = 0.0
    cell_y = 0.0
    cell_z = 0.0
    jitter = 0.39614353 * jitter_mod
    x_primed = _wrap32((xr - 1) * PRIME_X)
    y_primed_base = _wrap32((yr - 1) * PRIME_Y)
    z_primed_base = _wrap32((zr - 1) * PRIME_Z)
    for xi in range(xr - 1, xr + 2):
        y_primed = y_primed_base
        for yi in range(yr - 1, yr + 2):
            z_primed = z_primed_base
            for zi in range(zr - 1, zr + 2):
                h = _hash3(seed, x_primed, y_primed, z_primed)
                idx = h & (255 << 2)
                vec_x = (xi - x) + RAND_VECS_3D[idx] * jitter
                vec_y = (yi - y) + RAND_VECS_3D[idx | 1] * jitter
                vec_z = (zi - z) + RAND_VECS_3D[idx | 2] * jitter
                if dist_func == CELL_DIST_MANHATTAN:
                    new_distance = abs(vec_x) + abs(vec_y) + abs(vec_z)
                elif dist_func == CELL_DIST_HYBRID:
                    new_distance = (abs(vec_x) + abs(vec_y) + abs(vec_z)) + (
                        vec_x * vec_x + vec_y * vec_y + vec_z * vec_z
                    )
                elif dist_func == CELL_DIST_NATURAL:
                    new_distance = (abs(vec_x) + abs(vec_y) + abs(vec_z)) * (
                        vec_x * vec_x + vec_y * vec_y + vec_z * vec_z
                    )
                else:
                    new_distance = vec_x * vec_x + vec_y * vec_y + vec_z * vec_z
                distance1 = max(min(distance1, new_distance), distance0)
                if new_distance < distance0:
                    distance0 = new_distance
                    closest_hash = h
                    cell_x = xi + RAND_VECS_3D[idx] * jitter
                    cell_y = yi + RAND_VECS_3D[idx | 1] * jitter
                    cell_z = zi + RAND_VECS_3D[idx | 2] * jitter
                z_primed = _wrap32(z_primed + PRIME_Z)
            y_primed = _wrap32(y_primed + PRIME_Y)
        x_primed = _wrap32(x_primed + PRIME_X)
    return distance0, distance1, closest_hash, cell_x, cell_y, cell_z


@_jit
def cellular3(seed, x, y, z, dist_func, ret_type, jitter_mod, lookup_type, lookup_freq):
    if ret_type == CELL_RET_DISTANCE2_CAVE:
        d0, d1, h, _cx, _cy, _cz = _cellular3_scan(seed, x, y, z, dist_func, jitter_mod)
        c0 = _cellular_finish(dist_func, CELL_RET_DISTANCE2_DIV, d0, d1, h)
        d0, d1, h, _cx, _cy, _cz = _cellular3_scan(_wrap32(seed + 1), x + 0.5, y + 0.5, z + 0.5, dist_func, jitter_mod)
        c1 = _cellular_finish(dist_func, CELL_RET_DISTANCE2_DIV, d0, d1, h)
        return min(c0, c1)
    d0, d1, h, cx, cy, cz = _cellular3_scan(seed, x, y, z, dist_func, jitter_mod)
    if ret_type == CELL_RET_NOISE_LOOKUP:
        return _lookup_single3(lookup_type, seed, cx * lookup_freq, cy * lookup_freq, cz * lookup_freq)
    return _cellular_finish(dist_func, ret_type, d0, d1, h)


# -------------------------------------------------------------------------
# white noise (Phase C): FastNoiseSIMD's WhiteNoiseSingle, a hash of the scaled coordinates' float32 bits
@_jit
def _fns_val_coord(seed, xp, yp, zp):
    h = _wrap32(seed ^ xp ^ yp ^ zp)
    h = _wrap32(_wrap32(_wrap32(h * h) * _FNS_HASH_MUL) * h)
    return h * _FNS_HASH_TO_FLOAT


@_jit
def _fns_bits(v):
    """The int32 bit pattern of ``v`` as float32, mixed as the reference mixes it: ``b ^ (b >> 16)``."""
    b = np.int64(np.float32(v).view(np.int32))
    return b ^ (b >> 16)


@_jit
def white_noise3(seed, x, y, z):
    """FastNoiseSIMD white noise: ``x, y, z`` are the frequency-scaled coordinates; float32 bits are hashed."""
    return _fns_val_coord(
        seed,
        _wrap32(_fns_bits(x) * _FNS_PRIME_X),
        _wrap32(_fns_bits(y) * _FNS_PRIME_Y),
        _wrap32(_fns_bits(z) * _FNS_PRIME_Z),
    )


@_jit
def white_noise2(seed, x, y):
    """The 3D function at z = 0, whose bits are zero, so the 2D field is the 3D field's z = 0 plane."""
    return _fns_val_coord(seed, _wrap32(_fns_bits(x) * _FNS_PRIME_X), _wrap32(_fns_bits(y) * _FNS_PRIME_Y), 0)


# -------------------------------------------------------------------------
# classic simplex (Phase C): FastNoiseSIMD's SimplexSingle with its hash and gradient selection, so a
# seed that was authored against the retired library gives the same field by name
_FNS_F3 = 1.0 / 3.0
_FNS_G3 = 1.0 / 6.0
_FNS_G33 = (3.0 / 6.0) - 1.0


@_jit
def _fns_hash(seed, xp, yp, zp):
    h = _wrap32(seed ^ xp ^ yp ^ zp)
    h = _wrap32(_wrap32(_wrap32(h * h) * _FNS_HASH_MUL) * h)
    return (h >> 13) ^ h


@_jit
def _fns_grad_coord(seed, xp, yp, zp, x, y, z):
    """FastNoiseSIMD's GradCoord (the SSE/AVX2 path the vectors were captured on): one of twelve edge vectors."""
    h = _fns_hash(seed, xp, yp, zp)
    a = h & 13
    u = x if a < 8 else y
    v = y if a < 2 else (x if a == 12 else z)
    if h & 1:
        u = -u
    if h & 2:
        v = -v
    return u + v


@_jit
def simplex_classic3(seed, x, y, z):
    f = _FNS_F3 * ((x + y) + z)
    xf = np.floor(x + f)
    yf = np.floor(y + f)
    zf = np.floor(z + f)
    i = _wrap32(int(xf) * _FNS_PRIME_X)
    j = _wrap32(int(yf) * _FNS_PRIME_Y)
    k = _wrap32(int(zf) * _FNS_PRIME_Z)
    g = _FNS_G3 * ((xf + yf) + zf)
    x0 = x - (xf - g)
    y0 = y - (yf - g)
    z0 = z - (zf - g)

    x_ge_y = x0 >= y0
    y_ge_z = y0 >= z0
    x_ge_z = x0 >= z0
    i1 = x_ge_y and x_ge_z
    j1 = (not x_ge_y) and y_ge_z
    k1 = (not x_ge_z) and (not y_ge_z)
    i2 = x_ge_y or x_ge_z
    j2 = (not x_ge_y) or y_ge_z
    k2 = not (x_ge_z and y_ge_z)

    x1 = (x0 - 1.0 if i1 else x0) + _FNS_G3
    y1 = (y0 - 1.0 if j1 else y0) + _FNS_G3
    z1 = (z0 - 1.0 if k1 else z0) + _FNS_G3
    x2 = (x0 - 1.0 if i2 else x0) + _FNS_F3
    y2 = (y0 - 1.0 if j2 else y0) + _FNS_F3
    z2 = (z0 - 1.0 if k2 else z0) + _FNS_F3
    x3 = x0 + _FNS_G33
    y3 = y0 + _FNS_G33
    z3 = z0 + _FNS_G33

    t0 = ((0.6 - x0 * x0) - y0 * y0) - z0 * z0
    t1 = ((0.6 - x1 * x1) - y1 * y1) - z1 * z1
    t2 = ((0.6 - x2 * x2) - y2 * y2) - z2 * z2
    t3 = ((0.6 - x3 * x3) - y3 * y3) - z3 * z3

    total = 0.0
    if t3 >= 0.0:
        t3 = t3 * t3
        total += (t3 * t3) * _fns_grad_coord(
            seed, _wrap32(i + _FNS_PRIME_X), _wrap32(j + _FNS_PRIME_Y), _wrap32(k + _FNS_PRIME_Z), x3, y3, z3
        )
    if t2 >= 0.0:
        t2 = t2 * t2
        total += (t2 * t2) * _fns_grad_coord(
            seed,
            _wrap32(i + _FNS_PRIME_X) if i2 else i,
            _wrap32(j + _FNS_PRIME_Y) if j2 else j,
            _wrap32(k + _FNS_PRIME_Z) if k2 else k,
            x2,
            y2,
            z2,
        )
    if t1 >= 0.0:
        t1 = t1 * t1
        total += (t1 * t1) * _fns_grad_coord(
            seed,
            _wrap32(i + _FNS_PRIME_X) if i1 else i,
            _wrap32(j + _FNS_PRIME_Y) if j1 else j,
            _wrap32(k + _FNS_PRIME_Z) if k1 else k,
            x1,
            y1,
            z1,
        )
    if t0 >= 0.0:
        t0 = t0 * t0
        total += (t0 * t0) * _fns_grad_coord(seed, i, j, k, x0, y0, z0)
    return 32.0 * total


@_jit
def simplex_classic2(seed, x, y):
    """The retired library was 3D only; its 2D use was z = 0, so that is the 2D field."""
    return simplex_classic3(seed, x, y, 0.0)


# -------------------------------------------------------------------------
# domain warp (Phase B): FastNoiseLite's DomainWarp, applied to raw coordinates before the noise
@_jit
def _grad_out2(seed, xp, yp):
    h = _hash2(seed, xp, yp) & (255 << 1)
    return RAND_VECS_2D[h], RAND_VECS_2D[h | 1]


@_jit
def _grad_out3(seed, xp, yp, zp):
    h = _hash3(seed, xp, yp, zp) & (255 << 2)
    return RAND_VECS_3D[h], RAND_VECS_3D[h | 1], RAND_VECS_3D[h | 2]


@_jit
def _grad_dual2(seed, xp, yp, xd, yd):
    h = _hash2(seed, xp, yp)
    i1 = h & (127 << 1)
    i2 = (h >> 7) & (255 << 1)
    v = xd * GRADIENTS_2D[i1] + yd * GRADIENTS_2D[i1 | 1]
    return v * RAND_VECS_2D[i2], v * RAND_VECS_2D[i2 | 1]


@_jit
def _grad_dual3(seed, xp, yp, zp, xd, yd, zd):
    h = _hash3(seed, xp, yp, zp)
    i1 = h & (63 << 2)
    i2 = (h >> 6) & (255 << 2)
    v = xd * GRADIENTS_3D[i1] + yd * GRADIENTS_3D[i1 | 1] + zd * GRADIENTS_3D[i1 | 2]
    return v * RAND_VECS_3D[i2], v * RAND_VECS_3D[i2 | 1], v * RAND_VECS_3D[i2 | 2]


@_jit
def _rv2(i):
    # The table is float32; promote before the lerp's float32 - float32 would round, so the numpy
    # base (float64 tables) and this kernel agree exactly
    return np.float64(RAND_VECS_2D[i])


@_jit
def _rv3(i):
    return np.float64(RAND_VECS_3D[i])


@_jit
def _warp_basic_grid2(seed, amp, freq, x, y):
    xf = x * freq
    yf = y * freq
    x0 = _fast_floor(xf)
    y0 = _fast_floor(yf)
    xs = _interp_hermite(xf - x0)
    ys = _interp_hermite(yf - y0)
    x0 = _wrap32(x0 * PRIME_X)
    y0 = _wrap32(y0 * PRIME_Y)
    x1 = _wrap32(x0 + PRIME_X)
    y1 = _wrap32(y0 + PRIME_Y)

    h0 = _hash2(seed, x0, y0) & (255 << 1)
    h1 = _hash2(seed, x1, y0) & (255 << 1)
    lx0x = _lerp(_rv2(h0), _rv2(h1), xs)
    ly0x = _lerp(_rv2(h0 | 1), _rv2(h1 | 1), xs)
    h0 = _hash2(seed, x0, y1) & (255 << 1)
    h1 = _hash2(seed, x1, y1) & (255 << 1)
    lx1x = _lerp(_rv2(h0), _rv2(h1), xs)
    ly1x = _lerp(_rv2(h0 | 1), _rv2(h1 | 1), xs)
    return _lerp(lx0x, lx1x, ys) * amp, _lerp(ly0x, ly1x, ys) * amp


@_jit
def _warp_basic_grid3(seed, amp, freq, x, y, z):
    xf = x * freq
    yf = y * freq
    zf = z * freq
    x0 = _fast_floor(xf)
    y0 = _fast_floor(yf)
    z0 = _fast_floor(zf)
    xs = _interp_hermite(xf - x0)
    ys = _interp_hermite(yf - y0)
    zs = _interp_hermite(zf - z0)
    x0 = _wrap32(x0 * PRIME_X)
    y0 = _wrap32(y0 * PRIME_Y)
    z0 = _wrap32(z0 * PRIME_Z)
    x1 = _wrap32(x0 + PRIME_X)
    y1 = _wrap32(y0 + PRIME_Y)
    z1 = _wrap32(z0 + PRIME_Z)

    h0 = _hash3(seed, x0, y0, z0) & (255 << 2)
    h1 = _hash3(seed, x1, y0, z0) & (255 << 2)
    lx0x = _lerp(_rv3(h0), _rv3(h1), xs)
    ly0x = _lerp(_rv3(h0 | 1), _rv3(h1 | 1), xs)
    lz0x = _lerp(_rv3(h0 | 2), _rv3(h1 | 2), xs)
    h0 = _hash3(seed, x0, y1, z0) & (255 << 2)
    h1 = _hash3(seed, x1, y1, z0) & (255 << 2)
    lx1x = _lerp(_rv3(h0), _rv3(h1), xs)
    ly1x = _lerp(_rv3(h0 | 1), _rv3(h1 | 1), xs)
    lz1x = _lerp(_rv3(h0 | 2), _rv3(h1 | 2), xs)
    lx0y = _lerp(lx0x, lx1x, ys)
    ly0y = _lerp(ly0x, ly1x, ys)
    lz0y = _lerp(lz0x, lz1x, ys)

    h0 = _hash3(seed, x0, y0, z1) & (255 << 2)
    h1 = _hash3(seed, x1, y0, z1) & (255 << 2)
    lx0x = _lerp(_rv3(h0), _rv3(h1), xs)
    ly0x = _lerp(_rv3(h0 | 1), _rv3(h1 | 1), xs)
    lz0x = _lerp(_rv3(h0 | 2), _rv3(h1 | 2), xs)
    h0 = _hash3(seed, x0, y1, z1) & (255 << 2)
    h1 = _hash3(seed, x1, y1, z1) & (255 << 2)
    lx1x = _lerp(_rv3(h0), _rv3(h1), xs)
    ly1x = _lerp(_rv3(h0 | 1), _rv3(h1 | 1), xs)
    lz1x = _lerp(_rv3(h0 | 2), _rv3(h1 | 2), xs)
    return (
        _lerp(lx0y, _lerp(lx0x, lx1x, ys), zs) * amp,
        _lerp(ly0y, _lerp(ly0x, ly1x, ys), zs) * amp,
        _lerp(lz0y, _lerp(lz0x, lz1x, ys), zs) * amp,
    )


@_jit
def _warp_simplex_grad2(seed, amp, freq, x, y, grad_only):
    """OpenSimplex2 gradient warp, 2D. ``x, y`` are skewed already; ``grad_only`` is the Reduced variant."""
    x = x * freq
    y = y * freq
    i = _fast_floor(x)
    j = _fast_floor(y)
    xi = x - i
    yi = y - j
    t = (xi + yi) * _G2
    x0 = xi - t
    y0 = yi - t
    i = _wrap32(i * PRIME_X)
    j = _wrap32(j * PRIME_Y)

    vx = 0.0
    vy = 0.0
    a = 0.5 - x0 * x0 - y0 * y0
    if a > 0.0:
        aaaa = (a * a) * (a * a)
        if grad_only:
            xo, yo = _grad_out2(seed, i, j)
        else:
            xo, yo = _grad_dual2(seed, i, j, x0, y0)
        vx += aaaa * xo
        vy += aaaa * yo

    c = (2.0 * (1.0 - 2.0 * _G2) * (1.0 / _G2 - 2.0)) * t + ((-2.0 * (1.0 - 2.0 * _G2) * (1.0 - 2.0 * _G2)) + a)
    if c > 0.0:
        x2 = x0 + (2.0 * _G2 - 1.0)
        y2 = y0 + (2.0 * _G2 - 1.0)
        cccc = (c * c) * (c * c)
        if grad_only:
            xo, yo = _grad_out2(seed, _wrap32(i + PRIME_X), _wrap32(j + PRIME_Y))
        else:
            xo, yo = _grad_dual2(seed, _wrap32(i + PRIME_X), _wrap32(j + PRIME_Y), x2, y2)
        vx += cccc * xo
        vy += cccc * yo

    if y0 > x0:
        x1 = x0 + _G2
        y1 = y0 + (_G2 - 1.0)
        b = 0.5 - x1 * x1 - y1 * y1
        if b > 0.0:
            bbbb = (b * b) * (b * b)
            if grad_only:
                xo, yo = _grad_out2(seed, i, _wrap32(j + PRIME_Y))
            else:
                xo, yo = _grad_dual2(seed, i, _wrap32(j + PRIME_Y), x1, y1)
            vx += bbbb * xo
            vy += bbbb * yo
    else:
        x1 = x0 + (_G2 - 1.0)
        y1 = y0 + _G2
        b = 0.5 - x1 * x1 - y1 * y1
        if b > 0.0:
            bbbb = (b * b) * (b * b)
            if grad_only:
                xo, yo = _grad_out2(seed, _wrap32(i + PRIME_X), j)
            else:
                xo, yo = _grad_dual2(seed, _wrap32(i + PRIME_X), j, x1, y1)
            vx += bbbb * xo
            vy += bbbb * yo

    return vx * amp, vy * amp


@_jit
def _warp_simplex_grad3(seed, amp, freq, x, y, z, grad_only):
    """OpenSimplex2 gradient warp, 3D. ``x, y, z`` are rotated already; ``grad_only`` is the Reduced variant."""
    x = x * freq
    y = y * freq
    z = z * freq
    i = _fast_round(x)
    j = _fast_round(y)
    k = _fast_round(z)
    x0 = x - i
    y0 = y - j
    z0 = z - k

    x_nsign = int(-x0 - 1.0) | 1
    y_nsign = int(-y0 - 1.0) | 1
    z_nsign = int(-z0 - 1.0) | 1

    ax0 = x_nsign * -x0
    ay0 = y_nsign * -y0
    az0 = z_nsign * -z0

    i = _wrap32(i * PRIME_X)
    j = _wrap32(j * PRIME_Y)
    k = _wrap32(k * PRIME_Z)

    vx = 0.0
    vy = 0.0
    vz = 0.0
    a = (0.6 - x0 * x0) - (y0 * y0 + z0 * z0)
    for step in range(2):
        if a > 0.0:
            aaaa = (a * a) * (a * a)
            if grad_only:
                xo, yo, zo = _grad_out3(seed, i, j, k)
            else:
                xo, yo, zo = _grad_dual3(seed, i, j, k, x0, y0, z0)
            vx += aaaa * xo
            vy += aaaa * yo
            vz += aaaa * zo

        b = a + 1.0
        i1 = i
        j1 = j
        k1 = k
        x1 = x0
        y1 = y0
        z1 = z0
        if ax0 >= ay0 and ax0 >= az0:
            x1 += x_nsign
            b -= x_nsign * 2.0 * x1
            i1 = _wrap32(i1 - x_nsign * PRIME_X)
        elif ay0 > ax0 and ay0 >= az0:
            y1 += y_nsign
            b -= y_nsign * 2.0 * y1
            j1 = _wrap32(j1 - y_nsign * PRIME_Y)
        else:
            z1 += z_nsign
            b -= z_nsign * 2.0 * z1
            k1 = _wrap32(k1 - z_nsign * PRIME_Z)

        if b > 0.0:
            bbbb = (b * b) * (b * b)
            if grad_only:
                xo, yo, zo = _grad_out3(seed, i1, j1, k1)
            else:
                xo, yo, zo = _grad_dual3(seed, i1, j1, k1, x1, y1, z1)
            vx += bbbb * xo
            vy += bbbb * yo
            vz += bbbb * zo

        if step == 1:
            break

        ax0 = 0.5 - ax0
        ay0 = 0.5 - ay0
        az0 = 0.5 - az0
        x0 = x_nsign * ax0
        y0 = y_nsign * ay0
        z0 = z_nsign * az0
        a += (0.75 - ax0) - (ay0 + az0)
        i = _wrap32(i + ((x_nsign >> 1) & PRIME_X))
        j = _wrap32(j + ((y_nsign >> 1) & PRIME_Y))
        k = _wrap32(k + ((z_nsign >> 1) & PRIME_Z))
        x_nsign = -x_nsign
        y_nsign = -y_nsign
        z_nsign = -z_nsign
        seed = _wrap32(seed + 1293373)

    return vx * amp, vy * amp, vz * amp


@_jit
def _warp_transform2(warp_type, x, y):
    if warp_type == WARP_OPEN_SIMPLEX2 or warp_type == WARP_OPEN_SIMPLEX2_REDUCED:
        t = (x + y) * _F2
        return x + t, y + t
    return x, y


@_jit
def _do_warp2(warp_type, seed, amp, freq, x, y):
    if warp_type == WARP_OPEN_SIMPLEX2:
        return _warp_simplex_grad2(seed, amp * 38.283687591552734375, freq, x, y, False)
    if warp_type == WARP_OPEN_SIMPLEX2_REDUCED:
        return _warp_simplex_grad2(seed, amp * 16.0, freq, x, y, True)
    return _warp_basic_grid2(seed, amp, freq, x, y)


@_jit
def _do_warp3(warp_type, seed, amp, freq, x, y, z):
    if warp_type == WARP_OPEN_SIMPLEX2:
        return _warp_simplex_grad3(seed, amp * 32.69428253173828125, freq, x, y, z, False)
    if warp_type == WARP_OPEN_SIMPLEX2_REDUCED:
        return _warp_simplex_grad3(seed, amp * 7.71604938271605, freq, x, y, z, True)
    return _warp_basic_grid3(seed, amp, freq, x, y, z)


@_jit
def warp2(warp_type, warp_fractal, seed, amp, freq, octaves, lacunarity, gain, x, y):
    """
    The reference's ``DomainWarp(x, y)``: ``x, y`` raw (unscaled) coordinates, warped in place.

    ``amp`` is ``domain_warp_amp * fractal_bounding`` already; ``freq`` the base frequency. A single
    warp uses the first octave's seed, amplitude and frequency; progressive re-transforms the
    running warped point each octave; independent transforms the original once.
    """
    if warp_type == WARP_NONE:  # no warp configured: the raw point, not the BasicGrid fallback
        return x, y
    if warp_fractal == WARP_SINGLE:
        xs, ys = _warp_transform2(warp_type, x, y)
        dx, dy = _do_warp2(warp_type, seed, amp, freq, xs, ys)
        return x + dx, y + dy
    if warp_fractal == WARP_PROGRESSIVE:
        for _ in range(octaves):
            xs, ys = _warp_transform2(warp_type, x, y)
            dx, dy = _do_warp2(warp_type, seed, amp, freq, xs, ys)
            x += dx
            y += dy
            seed = _wrap32(seed + 1)
            amp *= gain
            freq *= lacunarity
        return x, y
    xs, ys = _warp_transform2(warp_type, x, y)
    for _ in range(octaves):
        dx, dy = _do_warp2(warp_type, seed, amp, freq, xs, ys)
        x += dx
        y += dy
        seed = _wrap32(seed + 1)
        amp *= gain
        freq *= lacunarity
    return x, y


@_jit
def warp3(warp_type, warp_fractal, warp_transform, seed, amp, freq, octaves, lacunarity, gain, x, y, z):
    """The reference's ``DomainWarp(x, y, z)``; ``warp_transform`` is the warp's own `Transform3D`."""
    if warp_type == WARP_NONE:  # no warp configured: the raw point, not the BasicGrid fallback
        return x, y, z
    if warp_fractal == WARP_SINGLE:
        xs, ys, zs = _transform3(warp_transform, x, y, z)
        dx, dy, dz = _do_warp3(warp_type, seed, amp, freq, xs, ys, zs)
        return x + dx, y + dy, z + dz
    if warp_fractal == WARP_PROGRESSIVE:
        for _ in range(octaves):
            xs, ys, zs = _transform3(warp_transform, x, y, z)
            dx, dy, dz = _do_warp3(warp_type, seed, amp, freq, xs, ys, zs)
            x += dx
            y += dy
            z += dz
            seed = _wrap32(seed + 1)
            amp *= gain
            freq *= lacunarity
        return x, y, z
    xs, ys, zs = _transform3(warp_transform, x, y, z)
    for _ in range(octaves):
        dx, dy, dz = _do_warp3(warp_type, seed, amp, freq, xs, ys, zs)
        x += dx
        y += dy
        z += dz
        seed = _wrap32(seed + 1)
        amp *= gain
        freq *= lacunarity
    return x, y, z


# -------------------------------------------------------------------------
# gradient perturb (Phase C): FastNoiseSIMD's GradientPerturbSingle and its PERTURB_SWITCH, on the
# frequency-scaled point, with its own frequency and octaves; the normalise modes rescale the point
@_jit
def _fns_grad_vec(seed, xp, yp, zp):
    """HashHB (no shift-xor), ten bits per axis, centred: an unnormalised random vector per lattice point."""
    h = _wrap32(seed ^ xp ^ yp ^ zp)
    h = _wrap32(_wrap32(_wrap32(h * h) * _FNS_HASH_MUL) * h)
    return (h & 1023) - 511.5, ((h >> 10) & 1023) - 511.5, ((h >> 20) & 1023) - 511.5


@_jit
def _perturb_single3(seed, amp, freq, x, y, z):
    xf = x * freq
    yf = y * freq
    zf = z * freq
    xs = np.floor(xf)
    ys = np.floor(yf)
    zs = np.floor(zf)
    x0 = _wrap32(int(xs) * _FNS_PRIME_X)
    y0 = _wrap32(int(ys) * _FNS_PRIME_Y)
    z0 = _wrap32(int(zs) * _FNS_PRIME_Z)
    x1 = _wrap32(x0 + _FNS_PRIME_X)
    y1 = _wrap32(y0 + _FNS_PRIME_Y)
    z1 = _wrap32(z0 + _FNS_PRIME_Z)
    xs = _interp_quintic(xf - xs)
    ys = _interp_quintic(yf - ys)
    zs = _interp_quintic(zf - zs)

    x000, y000, z000 = _fns_grad_vec(seed, x0, y0, z0)
    x001, y001, z001 = _fns_grad_vec(seed, x0, y0, z1)
    x010, y010, z010 = _fns_grad_vec(seed, x0, y1, z0)
    x011, y011, z011 = _fns_grad_vec(seed, x0, y1, z1)
    x100, y100, z100 = _fns_grad_vec(seed, x1, y0, z0)
    x101, y101, z101 = _fns_grad_vec(seed, x1, y0, z1)
    x110, y110, z110 = _fns_grad_vec(seed, x1, y1, z0)
    x111, y111, z111 = _fns_grad_vec(seed, x1, y1, z1)

    x0y = _lerp(_lerp(x000, x100, xs), _lerp(x010, x110, xs), ys)
    y0y = _lerp(_lerp(y000, y100, xs), _lerp(y010, y110, xs), ys)
    z0y = _lerp(_lerp(z000, z100, xs), _lerp(z010, z110, xs), ys)
    x1y = _lerp(_lerp(x001, x101, xs), _lerp(x011, x111, xs), ys)
    y1y = _lerp(_lerp(y001, y101, xs), _lerp(y011, y111, xs), ys)
    z1y = _lerp(_lerp(z001, z101, xs), _lerp(z011, z111, xs), ys)
    return _lerp(x0y, x1y, zs) * amp + x, _lerp(y0y, y1y, zs) * amp + y, _lerp(z0y, z1y, zs) * amp + z


@_jit
def perturb3(ptype, seed, bounding, amp, freq, octaves, lacunarity, gain, normalise, x, y, z):
    """
    The reference's PERTURB_SWITCH on a frequency-scaled point. ``normalise`` is the normalise length
    already multiplied by the noise frequency; ``bounding`` is the noise's fractal bounding, which the
    reference (not its own perturb bounding) multiplies into a fractal perturb's amplitude.
    """
    amp = amp / 511.5  # the reference's SetPerturbAmp: its random vectors are ten bits wide, +-511.5
    if ptype == PERTURB_GRADIENT or ptype == PERTURB_GRADIENT_NORMALISE:
        x, y, z = _perturb_single3(_wrap32(seed - 1), amp, freq, x, y, z)
    elif ptype == PERTURB_GRADIENT_FRACTAL or ptype == PERTURB_GRADIENT_FRACTAL_NORMALISE:
        seed_f = _wrap32(seed - 1)
        freq_f = freq
        amp_f = amp * bounding
        x, y, z = _perturb_single3(seed_f, amp_f, freq_f, x, y, z)
        for _ in range(1, octaves):
            freq_f *= lacunarity
            seed_f = _wrap32(seed_f - 1)
            amp_f *= gain
            x, y, z = _perturb_single3(seed_f, amp_f, freq_f, x, y, z)
    if ptype >= PERTURB_NORMALISE:
        # The reference used an approximate rsqrt and made NaN of the origin; a zero-length point stays
        # where it is instead (found by the gallery tile that includes the origin, 2026-10-02)
        length = np.sqrt(x * x + y * y + z * z)
        inv = normalise / length if length > 0.0 else 0.0
        x *= inv
        y *= inv
        z *= inv
    return x, y, z


@_jit
def perturb2(ptype, seed, bounding, amp, freq, octaves, lacunarity, gain, normalise, x, y):
    """The reference was 3D only; its 2D use was z = 0, and the z displacement is dropped."""
    x, y, _z = perturb3(ptype, seed, bounding, amp, freq, octaves, lacunarity, gain, normalise, x, y, 0.0)
    return x, y


# -------------------------------------------------------------------------
# dispatch, transforms, fractals
@_jit
def noise_single2(noise_type, seed, x, y, cell_dist, cell_ret, cell_jitter, lookup_type, lookup_freq):
    if noise_type == NOISE_OPEN_SIMPLEX2:
        return simplex2(seed, x, y)
    if noise_type == NOISE_OPEN_SIMPLEX2S:
        return simplex2s(seed, x, y)
    if noise_type == NOISE_CELLULAR:
        return cellular2(seed, x, y, cell_dist, cell_ret, cell_jitter, lookup_type, lookup_freq)
    if noise_type == NOISE_PERLIN:
        return perlin2(seed, x, y)
    if noise_type == NOISE_VALUE_CUBIC:
        return value_cubic2(seed, x, y)
    if noise_type == NOISE_VALUE:
        return value2(seed, x, y)
    if noise_type == NOISE_WHITE_NOISE:
        return white_noise2(seed, x, y)
    if noise_type == NOISE_SIMPLEX_CLASSIC:
        return simplex_classic2(seed, x, y)
    return 0.0


@_jit
def noise_single3(noise_type, seed, x, y, z, cell_dist, cell_ret, cell_jitter, lookup_type, lookup_freq):
    if noise_type == NOISE_OPEN_SIMPLEX2:
        return opensimplex2_3(seed, x, y, z)
    if noise_type == NOISE_OPEN_SIMPLEX2S:
        return opensimplex2s_3(seed, x, y, z)
    if noise_type == NOISE_CELLULAR:
        return cellular3(seed, x, y, z, cell_dist, cell_ret, cell_jitter, lookup_type, lookup_freq)
    if noise_type == NOISE_PERLIN:
        return perlin3(seed, x, y, z)
    if noise_type == NOISE_VALUE_CUBIC:
        return value_cubic3(seed, x, y, z)
    if noise_type == NOISE_VALUE:
        return value3(seed, x, y, z)
    if noise_type == NOISE_WHITE_NOISE:
        return white_noise3(seed, x, y, z)
    if noise_type == NOISE_SIMPLEX_CLASSIC:
        return simplex_classic3(seed, x, y, z)
    return 0.0


@_jit
def _transform2(noise_type, x, y):
    """Skew for the simplex family; identity otherwise. Frequency is applied by the caller."""
    if noise_type == NOISE_OPEN_SIMPLEX2 or noise_type == NOISE_OPEN_SIMPLEX2S:
        t = (x + y) * _F2
        return x + t, y + t
    return x, y


@_jit
def _transform3(transform, x, y, z):
    if transform == TRANSFORM_IMPROVE_XY:
        xy = x + y
        s2 = xy * -0.211324865405187
        z *= 0.577350269189626
        x += s2 - z
        y = y + s2 - z
        z += xy * 0.577350269189626
        return x, y, z
    if transform == TRANSFORM_IMPROVE_XZ:
        xz = x + z
        s2 = xz * -0.211324865405187
        y *= 0.577350269189626
        x += s2 - y
        z += s2 - y
        y += xz * 0.577350269189626
        return x, y, z
    if transform == TRANSFORM_DEFAULT_OS2:
        r = (x + y + z) * _R3
        return r - x, r - y, r - z
    return x, y, z


@_jit
def fractal2(
    noise_type, fractal_type, seed, x, y, octaves, lacunarity, gain, weighted, ping_pong, bounding, cd, cr, cj, cl, cf
):
    if fractal_type == FRACTAL_NONE:
        return noise_single2(noise_type, seed, x, y, cd, cr, cj, cl, cf)
    total = 0.0
    amp = 1.0 if fractal_type == FRACTAL_RIGID_MULTI else bounding
    for octave in range(octaves):
        n = noise_single2(noise_type, seed, x, y, cd, cr, cj, cl, cf)
        seed += 1
        if fractal_type == FRACTAL_FBM:
            total += n * amp
            amp *= _lerp(1.0, min(n + 1.0, 2.0) * 0.5, weighted)
        elif fractal_type == FRACTAL_RIDGED:
            n = abs(n)
            total += (n * -2.0 + 1.0) * amp
            amp *= _lerp(1.0, 1.0 - n, weighted)
        elif (
            fractal_type == FRACTAL_RIGID_MULTI
        ):  # FastNoiseSIMD: 1 - |n|, first added, the rest subtracted, unnormalised
            n = 1.0 - abs(n)
            total += n * amp if octave == 0 else -n * amp
        elif fractal_type == FRACTAL_BILLOW:  # FastNoiseSIMD: |n| * 2 - 1 per octave
            n = abs(n) * 2.0 - 1.0
            total += n * amp
            amp *= _lerp(1.0, (n + 1.0) * 0.5, weighted)
        else:  # PING_PONG
            n = _ping_pong((n + 1.0) * ping_pong)
            total += (n - 0.5) * 2.0 * amp
            amp *= _lerp(1.0, n, weighted)
        x *= lacunarity
        y *= lacunarity
        amp *= gain
    return total


@_jit
def fractal3(
    noise_type,
    fractal_type,
    seed,
    x,
    y,
    z,
    octaves,
    lacunarity,
    gain,
    weighted,
    ping_pong,
    bounding,
    cd,
    cr,
    cj,
    cl,
    cf,
):
    if fractal_type == FRACTAL_NONE:
        return noise_single3(noise_type, seed, x, y, z, cd, cr, cj, cl, cf)
    total = 0.0
    amp = 1.0 if fractal_type == FRACTAL_RIGID_MULTI else bounding
    for octave in range(octaves):
        n = noise_single3(noise_type, seed, x, y, z, cd, cr, cj, cl, cf)
        seed += 1
        if fractal_type == FRACTAL_FBM:
            total += n * amp
            amp *= _lerp(1.0, (n + 1.0) * 0.5, weighted)
        elif fractal_type == FRACTAL_RIDGED:
            n = abs(n)
            total += (n * -2.0 + 1.0) * amp
            amp *= _lerp(1.0, 1.0 - n, weighted)
        elif (
            fractal_type == FRACTAL_RIGID_MULTI
        ):  # FastNoiseSIMD: 1 - |n|, first added, the rest subtracted, unnormalised
            n = 1.0 - abs(n)
            total += n * amp if octave == 0 else -n * amp
        elif fractal_type == FRACTAL_BILLOW:  # FastNoiseSIMD: |n| * 2 - 1 per octave
            n = abs(n) * 2.0 - 1.0
            total += n * amp
            amp *= _lerp(1.0, (n + 1.0) * 0.5, weighted)
        else:  # PING_PONG
            n = _ping_pong((n + 1.0) * ping_pong)
            total += (n - 0.5) * 2.0 * amp
            amp *= _lerp(1.0, n, weighted)
        x *= lacunarity
        y *= lacunarity
        z *= lacunarity
        amp *= gain
    return total


# -------------------------------------------------------------------------
# single-point entry points: no parallel launch, for callers that sample one value at a time
@_jit
def sample_one_2d(
    x,
    y,
    seed,
    frequency,
    noise_type,
    fractal_type,
    octaves,
    lacunarity,
    gain,
    weighted,
    ping_pong,
    bounding,
    cd,
    cr,
    cj,
    warp_type,
    warp_amp,
    warp_fractal,
    lookup_type,
    lookup_freq,
    perturb_type,
    perturb_amp,
    perturb_freq,
    perturb_octaves,
    perturb_lacunarity,
    perturb_gain,
    perturb_normalise,
):
    """One 2D value. Same scalar contract as `sample_2d` minus the arrays; a few microseconds."""
    seed = _wrap32(seed)
    if warp_type != WARP_NONE:
        xw, yw = warp2(
            warp_type,
            warp_fractal,
            seed,
            warp_amp,
            np.float64(frequency),
            octaves,
            lacunarity,
            gain,
            np.float64(np.float32(x)),
            np.float64(np.float32(y)),
        )
        xf = xw * np.float64(frequency)
        yf = yw * np.float64(frequency)
    else:
        xf = np.float64(np.float32(x) * frequency)
        yf = np.float64(np.float32(y) * frequency)
    if perturb_type != PERTURB_NONE:
        xf, yf = perturb2(
            perturb_type,
            seed,
            bounding,
            perturb_amp,
            perturb_freq,
            perturb_octaves,
            perturb_lacunarity,
            perturb_gain,
            perturb_normalise * np.float64(frequency),
            xf,
            yf,
        )
    xf, yf = _transform2(noise_type, xf, yf)
    return fractal2(
        noise_type,
        fractal_type,
        seed,
        xf,
        yf,
        octaves,
        lacunarity,
        gain,
        weighted,
        ping_pong,
        bounding,
        cd,
        cr,
        cj,
        lookup_type,
        lookup_freq,
    )


@_jit
def sample_one_3d(
    x,
    y,
    z,
    seed,
    frequency,
    noise_type,
    fractal_type,
    octaves,
    lacunarity,
    gain,
    weighted,
    ping_pong,
    bounding,
    cd,
    cr,
    cj,
    transform,
    warp_type,
    warp_amp,
    warp_fractal,
    warp_transform,
    lookup_type,
    lookup_freq,
    perturb_type,
    perturb_amp,
    perturb_freq,
    perturb_octaves,
    perturb_lacunarity,
    perturb_gain,
    perturb_normalise,
):
    """One 3D value. Same scalar contract as `sample_3d` minus the arrays; a few microseconds."""
    seed = _wrap32(seed)
    if warp_type != WARP_NONE:
        xw, yw, zw = warp3(
            warp_type,
            warp_fractal,
            warp_transform,
            seed,
            warp_amp,
            np.float64(frequency),
            octaves,
            lacunarity,
            gain,
            np.float64(np.float32(x)),
            np.float64(np.float32(y)),
            np.float64(np.float32(z)),
        )
        xf = xw * np.float64(frequency)
        yf = yw * np.float64(frequency)
        zf = zw * np.float64(frequency)
    else:
        xf = np.float64(np.float32(x) * frequency)
        yf = np.float64(np.float32(y) * frequency)
        zf = np.float64(np.float32(z) * frequency)
    if perturb_type != PERTURB_NONE:
        xf, yf, zf = perturb3(
            perturb_type,
            seed,
            bounding,
            perturb_amp,
            perturb_freq,
            perturb_octaves,
            perturb_lacunarity,
            perturb_gain,
            perturb_normalise * np.float64(frequency),
            xf,
            yf,
            zf,
        )
    xf, yf, zf = _transform3(transform, xf, yf, zf)
    return fractal3(
        noise_type,
        fractal_type,
        seed,
        xf,
        yf,
        zf,
        octaves,
        lacunarity,
        gain,
        weighted,
        ping_pong,
        bounding,
        cd,
        cr,
        cj,
        lookup_type,
        lookup_freq,
    )


# -------------------------------------------------------------------------
# drivers: one call per batch, parallel over points
@njit(parallel=True, **_KERNEL_OPTS)
def sample_2d(
    xs,
    ys,
    out,
    seed,
    frequency,
    noise_type,
    fractal_type,
    octaves,
    lacunarity,
    gain,
    weighted,
    ping_pong,
    bounding,
    cd,
    cr,
    cj,
    warp_type,
    warp_amp,
    warp_fractal,
    lookup_type,
    lookup_freq,
    perturb_type,
    perturb_amp,
    perturb_freq,
    perturb_octaves,
    perturb_lacunarity,
    perturb_gain,
    perturb_normalise,
):
    """
    Fill ``out[i]`` with 2D noise at ``(xs[i], ys[i])``.

    ``xs``, ``ys``: float32 arrays. ``frequency``: float32. ``out``: float32, preallocated.
    Remaining scalars: `NoiseParams.kernel_args()` minus the two 3D transforms, which 2D derives itself.
    With a warp the raw point is warped first (the reference's ``DomainWarp`` then ``GetNoise``).
    """
    seed = _wrap32(seed)
    freq64 = np.float64(frequency)
    for idx in prange(xs.shape[0]):
        if warp_type != WARP_NONE:
            xw, yw = warp2(
                warp_type,
                warp_fractal,
                seed,
                warp_amp,
                freq64,
                octaves,
                lacunarity,
                gain,
                np.float64(xs[idx]),
                np.float64(ys[idx]),
            )
            x = xw * freq64
            y = yw * freq64
        else:
            x = np.float64(xs[idx] * frequency)
            y = np.float64(ys[idx] * frequency)
        if perturb_type != PERTURB_NONE:
            x, y = perturb2(
                perturb_type,
                seed,
                bounding,
                perturb_amp,
                perturb_freq,
                perturb_octaves,
                perturb_lacunarity,
                perturb_gain,
                perturb_normalise * freq64,
                x,
                y,
            )
        x, y = _transform2(noise_type, x, y)
        out[idx] = fractal2(
            noise_type,
            fractal_type,
            seed,
            x,
            y,
            octaves,
            lacunarity,
            gain,
            weighted,
            ping_pong,
            bounding,
            cd,
            cr,
            cj,
            lookup_type,
            lookup_freq,
        )


@njit(parallel=True, **_KERNEL_OPTS)
def sample_3d(
    xs,
    ys,
    zs,
    out,
    seed,
    frequency,
    noise_type,
    fractal_type,
    octaves,
    lacunarity,
    gain,
    weighted,
    ping_pong,
    bounding,
    cd,
    cr,
    cj,
    transform,
    warp_type,
    warp_amp,
    warp_fractal,
    warp_transform,
    lookup_type,
    lookup_freq,
    perturb_type,
    perturb_amp,
    perturb_freq,
    perturb_octaves,
    perturb_lacunarity,
    perturb_gain,
    perturb_normalise,
):
    """
    Fill ``out[i]`` with 3D noise at ``(xs[i], ys[i], zs[i])``.

    Same contract as `sample_2d` with a third coordinate, the resolved `Transform3D` and the warp's own.
    """
    seed = _wrap32(seed)
    freq64 = np.float64(frequency)
    for idx in prange(xs.shape[0]):
        if warp_type != WARP_NONE:
            xw, yw, zw = warp3(
                warp_type,
                warp_fractal,
                warp_transform,
                seed,
                warp_amp,
                freq64,
                octaves,
                lacunarity,
                gain,
                np.float64(xs[idx]),
                np.float64(ys[idx]),
                np.float64(zs[idx]),
            )
            x = xw * freq64
            y = yw * freq64
            z = zw * freq64
        else:
            x = np.float64(xs[idx] * frequency)
            y = np.float64(ys[idx] * frequency)
            z = np.float64(zs[idx] * frequency)
        if perturb_type != PERTURB_NONE:
            x, y, z = perturb3(
                perturb_type,
                seed,
                bounding,
                perturb_amp,
                perturb_freq,
                perturb_octaves,
                perturb_lacunarity,
                perturb_gain,
                perturb_normalise * freq64,
                x,
                y,
                z,
            )
        x, y, z = _transform3(transform, x, y, z)
        out[idx] = fractal3(
            noise_type,
            fractal_type,
            seed,
            x,
            y,
            z,
            octaves,
            lacunarity,
            gain,
            weighted,
            ping_pong,
            bounding,
            cd,
            cr,
            cj,
            lookup_type,
            lookup_freq,
        )


@njit(parallel=True, **_KERNEL_OPTS)
def warp_2d(xs, ys, out_x, out_y, seed, frequency, octaves, lacunarity, gain, warp_type, warp_amp, warp_fractal):
    """The warped raw coordinates alone (the reference's ``DomainWarp``), for the oracle comparison."""
    seed = _wrap32(seed)
    freq64 = np.float64(frequency)
    for idx in prange(xs.shape[0]):
        xw, yw = warp2(
            warp_type,
            warp_fractal,
            seed,
            warp_amp,
            freq64,
            octaves,
            lacunarity,
            gain,
            np.float64(xs[idx]),
            np.float64(ys[idx]),
        )
        out_x[idx] = xw
        out_y[idx] = yw


@njit(parallel=True, **_KERNEL_OPTS)
def warp_3d(
    xs,
    ys,
    zs,
    out_x,
    out_y,
    out_z,
    seed,
    frequency,
    octaves,
    lacunarity,
    gain,
    warp_type,
    warp_amp,
    warp_fractal,
    warp_transform,
):
    """3D twin of `warp_2d`."""
    seed = _wrap32(seed)
    freq64 = np.float64(frequency)
    for idx in prange(xs.shape[0]):
        xw, yw, zw = warp3(
            warp_type,
            warp_fractal,
            warp_transform,
            seed,
            warp_amp,
            freq64,
            octaves,
            lacunarity,
            gain,
            np.float64(xs[idx]),
            np.float64(ys[idx]),
            np.float64(zs[idx]),
        )
        out_x[idx] = xw
        out_y[idx] = yw
        out_z[idx] = zw


@njit(parallel=True, **_KERNEL_OPTS)
def sample_grid(
    out,
    x0,
    y0,
    z0,
    sx,
    sy,
    sz,
    seed,
    frequency,
    noise_type,
    fractal_type,
    octaves,
    lacunarity,
    gain,
    weighted,
    ping_pong,
    bounding,
    cd,
    cr,
    cj,
    transform,
    warp_type,
    warp_amp,
    warp_fractal,
    warp_transform,
    lookup_type,
    lookup_freq,
    perturb_type,
    perturb_amp,
    perturb_freq,
    perturb_octaves,
    perturb_lacunarity,
    perturb_gain,
    perturb_normalise,
):
    """
    Fill ``out[ix, iy, iz]`` with the noise at ``((x0 + ix) * sx, (y0 + iy) * sy, (z0 + iz) * sz)``: the
    retired library's ``genAsGrid`` with its axis scales, and no coordinate arrays. The coordinates are
    the float32 values the point drivers would see, so a grid equals `sample_3d` over the same points.
    ``x0, y0, z0`` are integer cell indices; ``sx, sy, sz`` the cell size per axis in coordinate units.
    """
    nx, ny, nz = out.shape
    for ix in prange(nx):
        x = np.float32((x0 + ix) * sx)
        for iy in range(ny):
            y = np.float32((y0 + iy) * sy)
            for iz in range(nz):
                z = np.float32((z0 + iz) * sz)
                out[ix, iy, iz] = sample_one_3d(
                    x,
                    y,
                    z,
                    seed,
                    frequency,
                    noise_type,
                    fractal_type,
                    octaves,
                    lacunarity,
                    gain,
                    weighted,
                    ping_pong,
                    bounding,
                    cd,
                    cr,
                    cj,
                    transform,
                    warp_type,
                    warp_amp,
                    warp_fractal,
                    warp_transform,
                    lookup_type,
                    lookup_freq,
                    perturb_type,
                    perturb_amp,
                    perturb_freq,
                    perturb_octaves,
                    perturb_lacunarity,
                    perturb_gain,
                    perturb_normalise,
                )


if __name__ == "__main__":
    import time

    print("numba:", HAVE_NUMBA)
    n = 4096
    rng = np.random.RandomState(1)
    xs = rng.uniform(-4096, 4096, n).astype(np.float32)
    ys = rng.uniform(-4096, 4096, n).astype(np.float32)
    zs = np.zeros(n, np.float32)
    out = np.empty(n, np.float32)
    from hog_noise.params import FractalType, NoiseParams, NoiseType

    # the record's own order, so this block cannot fall behind the drivers' signatures; frequency as float32
    p = NoiseParams(
        seed=1337, frequency=0.01, noise_type=NoiseType.OPEN_SIMPLEX2, fractal_type=FractalType.FBM, octaves=4
    )
    a = p.kernel_args()
    args = (a[0], np.float32(a[1]), *a[2:])
    t = time.perf_counter()
    sample_3d(xs, ys, zs, out, *args)
    print(f"first call (compile) {1000 * (time.perf_counter() - t):.0f} ms")
    t = time.perf_counter()
    sample_3d(xs, ys, zs, out, *args)
    print(f"second call {1000 * (time.perf_counter() - t):.3f} ms; range {out.min():.3f}..{out.max():.3f}")
