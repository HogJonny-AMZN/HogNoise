"""
HogNoise: the numpy base implementation of the noise kernels.
Package: hog_noise/vectorized

The rung that always works. Same algorithms as `scalar.py`, same 32-bit hashing, same float64
arithmetic after the float32 frequency multiply, written over whole arrays with masks in place of
branches. It agrees with the numba kernel exactly on every machine; that agreement is what the
tests enforce and what makes the numba rung safe to prefer.

It allocates freely: a dozen temporaries per octave. That is fine for a fallback and for tools,
and it is why the world loop prefers the compiled kernel (`.instructions/performance.md`).
"""

import logging as _logging

import numpy as np
from numpy.typing import NDArray

from hog_noise.scalar import (
    _F2,
    _G2,
    _HASH_MUL,
    _R3,
    CELL_DIST_EUCLIDEAN,
    CELL_DIST_HYBRID,
    CELL_DIST_MANHATTAN,
    CELL_DIST_NATURAL,
    CELL_RET_CELL_VALUE,
    CELL_RET_DISTANCE,
    CELL_RET_DISTANCE2,
    CELL_RET_DISTANCE2_ADD,
    CELL_RET_DISTANCE2_CAVE,
    CELL_RET_DISTANCE2_DIV,
    CELL_RET_DISTANCE2_MUL,
    CELL_RET_DISTANCE2_SUB,
    CELL_RET_NOISE_LOOKUP,
    FRACTAL_BILLOW,
    FRACTAL_FBM,
    FRACTAL_NONE,
    FRACTAL_RIDGED,
    FRACTAL_RIGID_MULTI,
    NOISE_CELLULAR,
    NOISE_OPEN_SIMPLEX2,
    NOISE_OPEN_SIMPLEX2S,
    NOISE_PERLIN,
    NOISE_SIMPLEX_CLASSIC,
    NOISE_VALUE,
    NOISE_VALUE_CUBIC,
    NOISE_WHITE_NOISE,
    PERTURB_GRADIENT,
    PERTURB_GRADIENT_FRACTAL,
    PERTURB_GRADIENT_FRACTAL_NORMALISE,
    PERTURB_GRADIENT_NORMALISE,
    PERTURB_NONE,
    PERTURB_NORMALISE,
    PRIME_X,
    PRIME_Y,
    PRIME_Z,
    TRANSFORM_DEFAULT_OS2,
    TRANSFORM_IMPROVE_XY,
    TRANSFORM_IMPROVE_XZ,
    WARP_NONE,
    WARP_OPEN_SIMPLEX2,
    WARP_OPEN_SIMPLEX2_REDUCED,
    WARP_PROGRESSIVE,
    WARP_SINGLE,
)
from hog_noise.tables import GRADIENTS_2D, GRADIENTS_3D, RAND_VECS_2D, RAND_VECS_3D

_MODULE_NAME = "hog_noise.vectorized"
__version__ = "0.1.0"
__updated__ = "2026-09-13"
_LOGGER = _logging.getLogger(_MODULE_NAME)

_I64 = np.int64
_MASK32 = _I64(0xFFFFFFFF)
_HALF32 = _I64(0x80000000)
_G2D = GRADIENTS_2D.astype(np.float64)
_G3D = GRADIENTS_3D.astype(np.float64)
_RV2D = RAND_VECS_2D.astype(np.float64)
_RV3D = RAND_VECS_3D.astype(np.float64)


# -------------------------------------------------------------------------
# 32-bit integer emulation and helpers, array-wide
def _wrap32(v: NDArray[np.int64]) -> NDArray[np.int64]:
    return ((v + _HALF32) & _MASK32) - _HALF32


def _wrap32_scalar(v: int) -> int:
    return ((v + 0x80000000) & 0xFFFFFFFF) - 0x80000000


def _hash2(seed: int, xp, yp):
    return _wrap32(_wrap32(seed ^ xp ^ yp) * _I64(_HASH_MUL))


def _hash3(seed: int, xp, yp, zp):
    return _wrap32(_wrap32(seed ^ xp ^ yp ^ zp) * _I64(_HASH_MUL))


def _val_coord2(seed, xp, yp):
    h = _hash2(seed, xp, yp)
    h = _wrap32(h * h)
    h = _wrap32(h ^ _wrap32(h << 19))
    return h * (1.0 / 2147483648.0)


def _val_coord3(seed, xp, yp, zp):
    h = _hash3(seed, xp, yp, zp)
    h = _wrap32(h * h)
    h = _wrap32(h ^ _wrap32(h << 19))
    return h * (1.0 / 2147483648.0)


def _grad_coord2(seed, xp, yp, xd, yd):
    h = _hash2(seed, xp, yp)
    h ^= h >> 15
    h &= 127 << 1
    return xd * _G2D[h] + yd * _G2D[h | 1]


def _grad_coord3(seed, xp, yp, zp, xd, yd, zd):
    h = _hash3(seed, xp, yp, zp)
    h ^= h >> 15
    h &= 63 << 2
    return xd * _G3D[h] + yd * _G3D[h | 1] + zd * _G3D[h | 2]


def _fast_floor(f):
    i = f.astype(_I64)  # truncation toward zero, like a C cast
    return i - (f < 0)  # the reference subtracts 1 for every negative f, integral or not


def _fast_round(f):
    return np.where(f >= 0, (f + 0.5).astype(_I64), (f - 0.5).astype(_I64))


def _lerp(a, b, t):
    return a + t * (b - a)


def _interp_hermite(t):
    return t * t * (3.0 - 2.0 * t)


def _interp_quintic(t):
    return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)


def _cubic_lerp(a, b, c, d, t):
    p = (d - c) - (a - b)
    return t * t * t * p + t * t * ((a - b) - p) + t * (c - a) + b


def _ping_pong(t):
    t = t - (t * 0.5).astype(_I64) * 2
    return np.where(t < 1.0, t, 2.0 - t)


def _quart(a):
    return (a * a) * (a * a)


# -------------------------------------------------------------------------
# single-octave noise, 2D
def simplex2(seed: int, x, y):
    i = _fast_floor(x)
    j = _fast_floor(y)
    xi = x - i
    yi = y - j
    t = (xi + yi) * _G2
    x0 = xi - t
    y0 = yi - t
    ip = _wrap32(i * PRIME_X)
    jp = _wrap32(j * PRIME_Y)
    ip1 = _wrap32(ip + PRIME_X)
    jp1 = _wrap32(jp + PRIME_Y)

    a = 0.5 - x0 * x0 - y0 * y0
    n0 = np.where(a <= 0.0, 0.0, _quart(a) * _grad_coord2(seed, ip, jp, x0, y0))

    c = (2.0 * (1.0 - 2.0 * _G2) * (1.0 / _G2 - 2.0)) * t + ((-2.0 * (1.0 - 2.0 * _G2) * (1.0 - 2.0 * _G2)) + a)
    x2 = x0 + (2.0 * _G2 - 1.0)
    y2 = y0 + (2.0 * _G2 - 1.0)
    n2 = np.where(c <= 0.0, 0.0, _quart(c) * _grad_coord2(seed, ip1, jp1, x2, y2))

    upper = y0 > x0
    x1 = np.where(upper, x0 + _G2, x0 + (_G2 - 1.0))
    y1 = np.where(upper, y0 + (_G2 - 1.0), y0 + _G2)
    b = 0.5 - x1 * x1 - y1 * y1
    ipn = np.where(upper, ip, ip1)
    jpn = np.where(upper, jp1, jp)
    n1 = np.where(b <= 0.0, 0.0, _quart(b) * _grad_coord2(seed, ipn, jpn, x1, y1))

    return (n0 + n1 + n2) * 99.83685446303647


def simplex2s(seed: int, x, y):
    """2D OpenSimplex2S; the same operation order as `scalar.simplex2s`, branches as masks."""
    i = _fast_floor(x)
    j = _fast_floor(y)
    xi = x - i
    yi = y - j

    ip = _wrap32(i * PRIME_X)
    jp = _wrap32(j * PRIME_Y)
    ip1 = _wrap32(ip + PRIME_X)
    jp1 = _wrap32(jp + PRIME_Y)

    t = (xi + yi) * _G2
    x0 = xi - t
    y0 = yi - t

    a0 = (2.0 / 3.0) - x0 * x0 - y0 * y0
    value = _quart(a0) * _grad_coord2(seed, ip, jp, x0, y0)

    a1 = (2.0 * (1.0 - 2.0 * _G2) * (1.0 / _G2 - 2.0)) * t + ((-2.0 * (1.0 - 2.0 * _G2) * (1.0 - 2.0 * _G2)) + a0)
    x1 = x0 - (1.0 - 2.0 * _G2)
    y1 = y0 - (1.0 - 2.0 * _G2)
    value = value + _quart(a1) * _grad_coord2(seed, ip1, jp1, x1, y1)

    xmyi = xi - yi
    upper = t > _G2
    # third vertex: four candidates, two per half of the cell
    far_x = xi + xmyi > 1.0
    neg_x = xi + xmyi < 0.0
    x2 = np.where(
        upper,
        np.where(far_x, x0 + (3.0 * _G2 - 2.0), x0 + _G2),
        np.where(neg_x, x0 + (1.0 - _G2), x0 + (_G2 - 1.0)),
    )
    y2 = np.where(
        upper,
        np.where(far_x, y0 + (3.0 * _G2 - 1.0), y0 + (_G2 - 1.0)),
        np.where(neg_x, y0 - _G2, y0 + _G2),
    )
    i2 = np.where(
        upper,
        np.where(far_x, _wrap32(ip + (PRIME_X << 1)), ip),
        np.where(neg_x, _wrap32(ip - PRIME_X), ip1),
    )
    j2 = np.where(upper, jp1, jp)
    a2 = (2.0 / 3.0) - x2 * x2 - y2 * y2
    value = value + np.where(a2 > 0.0, _quart(a2) * _grad_coord2(seed, i2, j2, x2, y2), 0.0)

    # fourth vertex
    far_y = yi - xmyi > 1.0
    neg_y = yi < xmyi
    x3 = np.where(
        upper,
        np.where(far_y, x0 + (3.0 * _G2 - 1.0), x0 + (_G2 - 1.0)),
        np.where(neg_y, x0 - _G2, x0 + _G2),
    )
    y3 = np.where(
        upper,
        np.where(far_y, y0 + (3.0 * _G2 - 2.0), y0 + _G2),
        np.where(neg_y, y0 - (_G2 - 1.0), y0 + (_G2 - 1.0)),
    )
    i3 = np.where(upper, ip1, ip)
    j3 = np.where(
        upper,
        np.where(far_y, _wrap32(jp + (PRIME_Y << 1)), jp),
        np.where(neg_y, _wrap32(jp - PRIME_Y), jp1),
    )
    a3 = (2.0 / 3.0) - x3 * x3 - y3 * y3
    value = value + np.where(a3 > 0.0, _quart(a3) * _grad_coord2(seed, i3, j3, x3, y3), 0.0)

    return value * 18.24196194486065


def perlin2(seed: int, x, y):
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


def value2(seed: int, x, y):
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


def value_cubic2(seed: int, x, y):
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
    x3 = _wrap32(x1 + _wrap32_scalar(PRIME_X << 1))
    y3 = _wrap32(y1 + _wrap32_scalar(PRIME_Y << 1))
    rows = [
        _cubic_lerp(
            _val_coord2(seed, x0, yp),
            _val_coord2(seed, x1, yp),
            _val_coord2(seed, x2, yp),
            _val_coord2(seed, x3, yp),
            xs,
        )
        for yp in (y0, y1, y2, y3)
    ]
    return _cubic_lerp(rows[0], rows[1], rows[2], rows[3], ys) * (1.0 / (1.5 * 1.5))


# -------------------------------------------------------------------------
# single-octave noise, 3D
def opensimplex2_3(seed: int, x, y, z):
    i = _fast_round(x)
    j = _fast_round(y)
    k = _fast_round(z)
    x0 = x - i
    y0 = y - j
    z0 = z - k

    xns = (-1.0 - x0).astype(_I64) | 1
    yns = (-1.0 - y0).astype(_I64) | 1
    zns = (-1.0 - z0).astype(_I64) | 1

    ax0 = xns * -x0
    ay0 = yns * -y0
    az0 = zns * -z0

    ip = _wrap32(i * PRIME_X)
    jp = _wrap32(j * PRIME_Y)
    kp = _wrap32(k * PRIME_Z)

    value = np.zeros(x.shape, dtype=np.float64)
    a = (0.6 - x0 * x0) - (y0 * y0 + z0 * z0)
    for step in range(2):
        value += np.where(a > 0.0, _quart(a) * _grad_coord3(seed, ip, jp, kp, x0, y0, z0), 0.0)

        mx = (ax0 >= ay0) & (ax0 >= az0)
        my = ~mx & (ay0 > ax0) & (ay0 >= az0)
        mz = ~mx & ~my
        x1 = x0 + np.where(mx, xns, 0)
        y1 = y0 + np.where(my, yns, 0)
        z1 = z0 + np.where(mz, zns, 0)
        b = (
            a
            + 1.0
            - np.where(mx, xns * 2.0 * x1, 0.0)
            - np.where(my, yns * 2.0 * y1, 0.0)
            - np.where(mz, zns * 2.0 * z1, 0.0)
        )
        i1 = np.where(mx, _wrap32(ip - xns * PRIME_X), ip)
        j1 = np.where(my, _wrap32(jp - yns * PRIME_Y), jp)
        k1 = np.where(mz, _wrap32(kp - zns * PRIME_Z), kp)
        value += np.where(b > 0.0, _quart(b) * _grad_coord3(seed, i1, j1, k1, x1, y1, z1), 0.0)

        if step == 1:
            break

        ax0 = 0.5 - ax0
        ay0 = 0.5 - ay0
        az0 = 0.5 - az0
        x0 = xns * ax0
        y0 = yns * ay0
        z0 = zns * az0
        a = a + (0.75 - ax0) - (ay0 + az0)
        ip = _wrap32(ip + ((xns >> 1) & PRIME_X))
        jp = _wrap32(jp + ((yns >> 1) & PRIME_Y))
        kp = _wrap32(kp + ((zns >> 1) & PRIME_Z))
        xns = -xns
        yns = -yns
        zns = -zns
        seed = ~seed

    return value * 32.69428253173828125


def opensimplex2s_3(seed: int, x, y, z):
    """3D OpenSimplex2S; the same operation and accumulation order as `scalar.opensimplex2s_3`."""
    i = _fast_floor(x)
    j = _fast_floor(y)
    k = _fast_floor(z)
    xi = x - i
    yi = y - j
    zi = z - k

    ip = _wrap32(i * PRIME_X)
    jp = _wrap32(j * PRIME_Y)
    kp = _wrap32(k * PRIME_Z)
    seed2 = _wrap32_scalar(seed + 1293373)

    xn = (-0.5 - xi).astype(_I64)  # 0 or -1, C truncation toward zero
    yn = (-0.5 - yi).astype(_I64)
    zn = (-0.5 - zi).astype(_I64)
    xn1 = xn | 1
    yn1 = yn | 1
    zn1 = zn | 1
    px_n = xn & PRIME_X  # the "negative half" prime offsets, and their complements
    py_n = yn & PRIME_Y
    pz_n = zn & PRIME_Z
    px_p = ~xn & PRIME_X
    py_p = ~yn & PRIME_Y
    pz_p = ~zn & PRIME_Z
    px2 = xn & (PRIME_X * 2)
    py2 = yn & _wrap32_scalar(PRIME_Y << 1)
    pz2 = zn & _wrap32_scalar(PRIME_Z << 1)
    ip1 = _wrap32(ip + PRIME_X)
    jp1 = _wrap32(jp + PRIME_Y)
    kp1 = _wrap32(kp + PRIME_Z)

    x0 = xi + xn
    y0 = yi + yn
    z0 = zi + zn
    a0 = 0.75 - x0 * x0 - y0 * y0 - z0 * z0
    value = _quart(a0) * _grad_coord3(seed, _wrap32(ip + px_n), _wrap32(jp + py_n), _wrap32(kp + pz_n), x0, y0, z0)

    x1 = xi - 0.5
    y1 = yi - 0.5
    z1 = zi - 0.5
    a1 = 0.75 - x1 * x1 - y1 * y1 - z1 * z1
    value = value + _quart(a1) * _grad_coord3(seed2, ip1, jp1, kp1, x1, y1, z1)

    x_flip0 = (xn1 << 1) * x1
    y_flip0 = (yn1 << 1) * y1
    z_flip0 = (zn1 << 1) * z1
    x_flip1 = (-2 - (xn << 2)) * x1 - 1.0
    y_flip1 = (-2 - (yn << 2)) * y1 - 1.0
    z_flip1 = (-2 - (zn << 2)) * z1 - 1.0

    def add(mask, a, s, gi, gj, gk, gx, gy, gz):
        return np.where(mask, _quart(a) * _grad_coord3(s, gi, gj, gk, gx, gy, gz), 0.0)

    # x pair: 2, else 3 and 4 (4 taken means 5 is skipped)
    a2 = x_flip0 + a0
    m2 = a2 > 0.0
    value = value + add(m2, a2, seed, _wrap32(ip + px_p), _wrap32(jp + py_n), _wrap32(kp + pz_n), x0 - xn1, y0, z0)
    a3 = y_flip0 + z_flip0 + a0
    m3 = ~m2 & (a3 > 0.0)
    value = value + add(
        m3, a3, seed, _wrap32(ip + px_n), _wrap32(jp + py_p), _wrap32(kp + pz_p), x0, y0 - yn1, z0 - zn1
    )
    a4 = x_flip1 + a1
    m4 = ~m2 & (a4 > 0.0)
    value = value + add(m4, a4, seed2, _wrap32(ip + px2), jp1, kp1, xn1 + x1, y1, z1)
    skip5 = m4

    # y pair: 6, else 7 and 8 (8 taken means 9 is skipped)
    a6 = y_flip0 + a0
    m6 = a6 > 0.0
    value = value + add(m6, a6, seed, _wrap32(ip + px_n), _wrap32(jp + py_p), _wrap32(kp + pz_n), x0, y0 - yn1, z0)
    a7 = x_flip0 + z_flip0 + a0
    m7 = ~m6 & (a7 > 0.0)
    value = value + add(
        m7, a7, seed, _wrap32(ip + px_p), _wrap32(jp + py_n), _wrap32(kp + pz_p), x0 - xn1, y0, z0 - zn1
    )
    a8 = y_flip1 + a1
    m8 = ~m6 & (a8 > 0.0)
    value = value + add(m8, a8, seed2, ip1, _wrap32(jp + py2), kp1, x1, yn1 + y1, z1)
    skip9 = m8

    # z pair: A, else B and C (C taken means D is skipped)
    aa = z_flip0 + a0
    ma = aa > 0.0
    value = value + add(ma, aa, seed, _wrap32(ip + px_n), _wrap32(jp + py_n), _wrap32(kp + pz_p), x0, y0, z0 - zn1)
    ab = x_flip0 + y_flip0 + a0
    mb = ~ma & (ab > 0.0)
    value = value + add(
        mb, ab, seed, _wrap32(ip + px_p), _wrap32(jp + py_p), _wrap32(kp + pz_n), x0 - xn1, y0 - yn1, z0
    )
    ac = z_flip1 + a1
    mc = ~ma & (ac > 0.0)
    value = value + add(mc, ac, seed2, ip1, jp1, _wrap32(kp + pz2), x1, y1, zn1 + z1)
    skip_d = mc

    a5 = y_flip1 + z_flip1 + a1
    value = value + add(
        ~skip5 & (a5 > 0.0), a5, seed2, ip1, _wrap32(jp + py2), _wrap32(kp + pz2), x1, yn1 + y1, zn1 + z1
    )
    a9 = x_flip1 + z_flip1 + a1
    value = value + add(
        ~skip9 & (a9 > 0.0), a9, seed2, _wrap32(ip + px2), jp1, _wrap32(kp + pz2), xn1 + x1, y1, zn1 + z1
    )
    ad = x_flip1 + y_flip1 + a1
    value = value + add(
        ~skip_d & (ad > 0.0),
        ad,
        seed2,
        _wrap32(ip + (xn & _wrap32_scalar(PRIME_X << 1))),
        _wrap32(jp + py2),
        kp1,
        xn1 + x1,
        yn1 + y1,
        z1,
    )

    return value * 9.046026385208288


def perlin3(seed: int, x, y, z):
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


def value3(seed: int, x, y, z):
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


def value_cubic3(seed: int, x, y, z):
    x1 = _fast_floor(x)
    y1 = _fast_floor(y)
    z1 = _fast_floor(z)
    xs = x - x1
    ys = y - y1
    zs = z - z1
    x1 = _wrap32(x1 * PRIME_X)
    y1 = _wrap32(y1 * PRIME_Y)
    z1 = _wrap32(z1 * PRIME_Z)
    xps = (_wrap32(x1 - PRIME_X), x1, _wrap32(x1 + PRIME_X), _wrap32(x1 + _wrap32_scalar(PRIME_X << 1)))
    yps = (_wrap32(y1 - PRIME_Y), y1, _wrap32(y1 + PRIME_Y), _wrap32(y1 + _wrap32_scalar(PRIME_Y << 1)))
    zps = (_wrap32(z1 - PRIME_Z), z1, _wrap32(z1 + PRIME_Z), _wrap32(z1 + _wrap32_scalar(PRIME_Z << 1)))
    planes = []
    for zp in zps:
        rows = [_cubic_lerp(*[_val_coord3(seed, xp, yp, zp) for xp in xps], xs) for yp in yps]
        planes.append(_cubic_lerp(rows[0], rows[1], rows[2], rows[3], ys))
    return _cubic_lerp(planes[0], planes[1], planes[2], planes[3], zs) * (1.0 / (1.5 * 1.5 * 1.5))


# -------------------------------------------------------------------------
# cellular (Worley) noise
def _cellular_distance(dist_func, parts):
    if dist_func == CELL_DIST_MANHATTAN:
        return sum(np.abs(p) for p in parts)
    if dist_func == CELL_DIST_HYBRID:
        return sum(np.abs(p) for p in parts) + sum(p * p for p in parts)
    if dist_func == CELL_DIST_NATURAL:
        return sum(np.abs(p) for p in parts) * sum(p * p for p in parts)
    return sum(p * p for p in parts)


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
    return np.zeros_like(distance0)


def _lookup_single2(noise_type: int, seed: int, x, y):
    x, y = _transform2(noise_type, x, y)
    return _SINGLE2[noise_type](seed, x, y)


def _lookup_single3(noise_type: int, seed: int, x, y, z):
    if noise_type in (NOISE_OPEN_SIMPLEX2, NOISE_OPEN_SIMPLEX2S):
        x, y, z = _transform3(TRANSFORM_DEFAULT_OS2, x, y, z)
    return _SINGLE3[noise_type](seed, x, y, z)


def _cellular2_scan(seed: int, x, y, dist_func: int, jitter_mod: float):
    xr = _fast_round(x)
    yr = _fast_round(y)
    distance0 = np.full(x.shape, 1e10)
    distance1 = np.full(x.shape, 1e10)
    closest_hash = np.zeros(x.shape, dtype=_I64)
    cell_x = np.zeros(x.shape)
    cell_y = np.zeros(x.shape)
    jitter = 0.43701595 * jitter_mod
    for dx in (-1, 0, 1):
        xp = _wrap32((xr + dx) * PRIME_X)
        for dy in (-1, 0, 1):
            yp = _wrap32((yr + dy) * PRIME_Y)
            h = _hash2(seed, xp, yp)
            idx = h & (255 << 1)
            vec_x = ((xr + dx) - x) + _RV2D[idx] * jitter
            vec_y = ((yr + dy) - y) + _RV2D[idx | 1] * jitter
            new_distance = _cellular_distance(dist_func, (vec_x, vec_y))
            distance1 = np.maximum(np.minimum(distance1, new_distance), distance0)
            closer = new_distance < distance0
            distance0 = np.where(closer, new_distance, distance0)
            closest_hash = np.where(closer, h, closest_hash)
            cell_x = np.where(closer, (xr + dx) + _RV2D[idx] * jitter, cell_x)
            cell_y = np.where(closer, (yr + dy) + _RV2D[idx | 1] * jitter, cell_y)
    return distance0, distance1, closest_hash, cell_x, cell_y


def cellular2(seed: int, x, y, dist_func: int, ret_type: int, jitter_mod: float, lookup_type: int, lookup_freq: float):
    if ret_type == CELL_RET_DISTANCE2_CAVE:
        d0, d1, h, _cx, _cy = _cellular2_scan(seed, x, y, dist_func, jitter_mod)
        c0 = _cellular_finish(dist_func, CELL_RET_DISTANCE2_DIV, d0, d1, h)
        d0, d1, h, _cx, _cy = _cellular2_scan(_wrap32_scalar(seed + 1), x + 0.5, y + 0.5, dist_func, jitter_mod)
        c1 = _cellular_finish(dist_func, CELL_RET_DISTANCE2_DIV, d0, d1, h)
        return np.minimum(c0, c1)
    d0, d1, h, cx, cy = _cellular2_scan(seed, x, y, dist_func, jitter_mod)
    if ret_type == CELL_RET_NOISE_LOOKUP:
        return _lookup_single2(lookup_type, seed, cx * lookup_freq, cy * lookup_freq)
    return _cellular_finish(dist_func, ret_type, d0, d1, h)


def _cellular3_scan(seed: int, x, y, z, dist_func: int, jitter_mod: float):
    xr = _fast_round(x)
    yr = _fast_round(y)
    zr = _fast_round(z)
    distance0 = np.full(x.shape, 1e10)
    distance1 = np.full(x.shape, 1e10)
    closest_hash = np.zeros(x.shape, dtype=_I64)
    cell_x = np.zeros(x.shape)
    cell_y = np.zeros(x.shape)
    cell_z = np.zeros(x.shape)
    jitter = 0.39614353 * jitter_mod
    for dx in (-1, 0, 1):
        xp = _wrap32((xr + dx) * PRIME_X)
        for dy in (-1, 0, 1):
            yp = _wrap32((yr + dy) * PRIME_Y)
            for dz in (-1, 0, 1):
                zp = _wrap32((zr + dz) * PRIME_Z)
                h = _hash3(seed, xp, yp, zp)
                idx = h & (255 << 2)
                vec_x = ((xr + dx) - x) + _RV3D[idx] * jitter
                vec_y = ((yr + dy) - y) + _RV3D[idx | 1] * jitter
                vec_z = ((zr + dz) - z) + _RV3D[idx | 2] * jitter
                new_distance = _cellular_distance(dist_func, (vec_x, vec_y, vec_z))
                distance1 = np.maximum(np.minimum(distance1, new_distance), distance0)
                closer = new_distance < distance0
                distance0 = np.where(closer, new_distance, distance0)
                closest_hash = np.where(closer, h, closest_hash)
                cell_x = np.where(closer, (xr + dx) + _RV3D[idx] * jitter, cell_x)
                cell_y = np.where(closer, (yr + dy) + _RV3D[idx | 1] * jitter, cell_y)
                cell_z = np.where(closer, (zr + dz) + _RV3D[idx | 2] * jitter, cell_z)
    return distance0, distance1, closest_hash, cell_x, cell_y, cell_z


def cellular3(
    seed: int, x, y, z, dist_func: int, ret_type: int, jitter_mod: float, lookup_type: int, lookup_freq: float
):
    if ret_type == CELL_RET_DISTANCE2_CAVE:
        d0, d1, h, _cx, _cy, _cz = _cellular3_scan(seed, x, y, z, dist_func, jitter_mod)
        c0 = _cellular_finish(dist_func, CELL_RET_DISTANCE2_DIV, d0, d1, h)
        d0, d1, h, _cx, _cy, _cz = _cellular3_scan(
            _wrap32_scalar(seed + 1), x + 0.5, y + 0.5, z + 0.5, dist_func, jitter_mod
        )
        c1 = _cellular_finish(dist_func, CELL_RET_DISTANCE2_DIV, d0, d1, h)
        return np.minimum(c0, c1)
    d0, d1, h, cx, cy, cz = _cellular3_scan(seed, x, y, z, dist_func, jitter_mod)
    if ret_type == CELL_RET_NOISE_LOOKUP:
        return _lookup_single3(lookup_type, seed, cx * lookup_freq, cy * lookup_freq, cz * lookup_freq)
    return _cellular_finish(dist_func, ret_type, d0, d1, h)


# -------------------------------------------------------------------------
# dispatch, transforms, fractals
# -------------------------------------------------------------------------
# white noise (Phase C); the twin of scalar's, on arrays
_FNS_PRIME_X = 1619
_FNS_PRIME_Y = 31337
_FNS_PRIME_Z = 6971
_FNS_HASH_MUL = _I64(60493)
_FNS_HASH_TO_FLOAT = 1.0 / 2147483648.0


def _fns_val_coord(seed: int, xp, yp, zp):
    h = _wrap32(seed ^ xp ^ yp ^ zp)
    h = _wrap32(_wrap32(_wrap32(h * h) * _FNS_HASH_MUL) * h)
    return h * _FNS_HASH_TO_FLOAT


def _fns_bits(v):
    b = np.asarray(v, dtype=np.float32).view(np.int32).astype(_I64)
    return b ^ (b >> 16)


def white_noise3(seed: int, x, y, z):
    return _fns_val_coord(
        seed,
        _wrap32(_fns_bits(x) * _FNS_PRIME_X),
        _wrap32(_fns_bits(y) * _FNS_PRIME_Y),
        _wrap32(_fns_bits(z) * _FNS_PRIME_Z),
    )


def white_noise2(seed: int, x, y):
    return _fns_val_coord(seed, _wrap32(_fns_bits(x) * _FNS_PRIME_X), _wrap32(_fns_bits(y) * _FNS_PRIME_Y), 0)


# -------------------------------------------------------------------------
# classic simplex (Phase C); the twin of scalar's, branches as masks, same accumulation order
_FNS_F3 = 1.0 / 3.0
_FNS_G3 = 1.0 / 6.0
_FNS_G33 = (3.0 / 6.0) - 1.0


def _fns_hash(seed: int, xp, yp, zp):
    h = _wrap32(seed ^ xp ^ yp ^ zp)
    h = _wrap32(_wrap32(_wrap32(h * h) * _FNS_HASH_MUL) * h)
    return (h >> 13) ^ h


def _fns_grad_coord(seed: int, xp, yp, zp, x, y, z):
    h = _fns_hash(seed, xp, yp, zp)
    a = h & 13
    u = np.where(a < 8, x, y)
    v = np.where(a < 2, y, np.where(a == 12, x, z))
    u = np.where(h & 1, -u, u)
    v = np.where(h & 2, -v, v)
    return u + v


def simplex_classic3(seed: int, x, y, z):
    f = _FNS_F3 * ((x + y) + z)
    xf = np.floor(x + f)
    yf = np.floor(y + f)
    zf = np.floor(z + f)
    i = _wrap32(xf.astype(_I64) * _FNS_PRIME_X)
    j = _wrap32(yf.astype(_I64) * _FNS_PRIME_Y)
    k = _wrap32(zf.astype(_I64) * _FNS_PRIME_Z)
    g = _FNS_G3 * ((xf + yf) + zf)
    x0 = x - (xf - g)
    y0 = y - (yf - g)
    z0 = z - (zf - g)

    x_ge_y = x0 >= y0
    y_ge_z = y0 >= z0
    x_ge_z = x0 >= z0
    i1 = x_ge_y & x_ge_z
    j1 = ~x_ge_y & y_ge_z
    k1 = ~x_ge_z & ~y_ge_z
    i2 = x_ge_y | x_ge_z
    j2 = ~x_ge_y | y_ge_z
    k2 = ~(x_ge_z & y_ge_z)

    x1 = np.where(i1, x0 - 1.0, x0) + _FNS_G3
    y1 = np.where(j1, y0 - 1.0, y0) + _FNS_G3
    z1 = np.where(k1, z0 - 1.0, z0) + _FNS_G3
    x2 = np.where(i2, x0 - 1.0, x0) + _FNS_F3
    y2 = np.where(j2, y0 - 1.0, y0) + _FNS_F3
    z2 = np.where(k2, z0 - 1.0, z0) + _FNS_F3
    x3 = x0 + _FNS_G33
    y3 = y0 + _FNS_G33
    z3 = z0 + _FNS_G33

    t0 = ((0.6 - x0 * x0) - y0 * y0) - z0 * z0
    t1 = ((0.6 - x1 * x1) - y1 * y1) - z1 * z1
    t2 = ((0.6 - x2 * x2) - y2 * y2) - z2 * z2
    t3 = ((0.6 - x3 * x3) - y3 * y3) - z3 * z3
    ip1 = _wrap32(i + _FNS_PRIME_X)
    jp1 = _wrap32(j + _FNS_PRIME_Y)
    kp1 = _wrap32(k + _FNS_PRIME_Z)

    def term(t, gi, gj, gk, gx, gy, gz):
        tt = t * t
        return np.where(t >= 0.0, (tt * tt) * _fns_grad_coord(seed, gi, gj, gk, gx, gy, gz), 0.0)

    total = term(t3, ip1, jp1, kp1, x3, y3, z3)
    total = total + term(t2, np.where(i2, ip1, i), np.where(j2, jp1, j), np.where(k2, kp1, k), x2, y2, z2)
    total = total + term(t1, np.where(i1, ip1, i), np.where(j1, jp1, j), np.where(k1, kp1, k), x1, y1, z1)
    total = total + term(t0, i, j, k, x0, y0, z0)
    return 32.0 * total


def simplex_classic2(seed: int, x, y):
    return simplex_classic3(seed, x, y, np.zeros_like(x))


# -------------------------------------------------------------------------
# gradient perturb (Phase C); the twin of scalar's, on arrays
def _fns_grad_vec(seed: int, xp, yp, zp):
    h = _wrap32(seed ^ xp ^ yp ^ zp)
    h = _wrap32(_wrap32(_wrap32(h * h) * _FNS_HASH_MUL) * h)
    return (h & 1023) - 511.5, ((h >> 10) & 1023) - 511.5, ((h >> 20) & 1023) - 511.5


def _perturb_single3(seed: int, amp, freq, x, y, z):
    xf = x * freq
    yf = y * freq
    zf = z * freq
    xs = np.floor(xf)
    ys = np.floor(yf)
    zs = np.floor(zf)
    x0 = _wrap32(xs.astype(_I64) * _FNS_PRIME_X)
    y0 = _wrap32(ys.astype(_I64) * _FNS_PRIME_Y)
    z0 = _wrap32(zs.astype(_I64) * _FNS_PRIME_Z)
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


def perturb3(ptype: int, seed: int, bounding, amp, freq, octaves: int, lacunarity, gain, normalise, x, y, z):
    amp = amp / 511.5  # the reference's SetPerturbAmp: its random vectors are ten bits wide, +-511.5
    if ptype in (PERTURB_GRADIENT, PERTURB_GRADIENT_NORMALISE):
        x, y, z = _perturb_single3(_wrap32_scalar(seed - 1), amp, freq, x, y, z)
    elif ptype in (PERTURB_GRADIENT_FRACTAL, PERTURB_GRADIENT_FRACTAL_NORMALISE):
        seed_f = _wrap32_scalar(seed - 1)
        freq_f = freq
        amp_f = amp * bounding
        x, y, z = _perturb_single3(seed_f, amp_f, freq_f, x, y, z)
        for _ in range(1, octaves):
            freq_f *= lacunarity
            seed_f = _wrap32_scalar(seed_f - 1)
            amp_f *= gain
            x, y, z = _perturb_single3(seed_f, amp_f, freq_f, x, y, z)
    if ptype >= PERTURB_NORMALISE:
        length = np.sqrt(x * x + y * y + z * z)
        inv = np.where(length > 0.0, normalise / np.where(length > 0.0, length, 1.0), 0.0)  # the origin stays put
        x = x * inv
        y = y * inv
        z = z * inv
    return x, y, z


def perturb2(ptype: int, seed: int, bounding, amp, freq, octaves: int, lacunarity, gain, normalise, x, y):
    x, y, _z = perturb3(ptype, seed, bounding, amp, freq, octaves, lacunarity, gain, normalise, x, y, np.zeros_like(x))
    return x, y


_SINGLE2 = {
    NOISE_OPEN_SIMPLEX2: simplex2,
    NOISE_OPEN_SIMPLEX2S: simplex2s,
    NOISE_PERLIN: perlin2,
    NOISE_VALUE_CUBIC: value_cubic2,
    NOISE_VALUE: value2,
    NOISE_WHITE_NOISE: white_noise2,
    NOISE_SIMPLEX_CLASSIC: simplex_classic2,
}
_SINGLE3 = {
    NOISE_OPEN_SIMPLEX2: opensimplex2_3,
    NOISE_OPEN_SIMPLEX2S: opensimplex2s_3,
    NOISE_PERLIN: perlin3,
    NOISE_VALUE_CUBIC: value_cubic3,
    NOISE_VALUE: value3,
    NOISE_WHITE_NOISE: white_noise3,
    NOISE_SIMPLEX_CLASSIC: simplex_classic3,
}


def _single2(noise_type: int, cd: int, cr: int, cj: float, cl: int, cf: float):
    if noise_type == NOISE_CELLULAR:
        return lambda seed, x, y: cellular2(seed, x, y, int(cd), int(cr), float(cj), int(cl), float(cf))
    return _SINGLE2[noise_type]


def _single3(noise_type: int, cd: int, cr: int, cj: float, cl: int, cf: float):
    if noise_type == NOISE_CELLULAR:
        return lambda seed, x, y, z: cellular3(seed, x, y, z, int(cd), int(cr), float(cj), int(cl), float(cf))
    return _SINGLE3[noise_type]


# -------------------------------------------------------------------------
# domain warp (Phase B); the twin of scalar's warp block, branches as masks, same operation order
def _grad_out2(seed, xp, yp):
    h = _hash2(seed, xp, yp) & (255 << 1)
    return _RV2D[h], _RV2D[h | 1]


def _grad_out3(seed, xp, yp, zp):
    h = _hash3(seed, xp, yp, zp) & (255 << 2)
    return _RV3D[h], _RV3D[h | 1], _RV3D[h | 2]


def _grad_dual2(seed, xp, yp, xd, yd):
    h = _hash2(seed, xp, yp)
    i1 = h & (127 << 1)
    i2 = (h >> 7) & (255 << 1)
    v = xd * _G2D[i1] + yd * _G2D[i1 | 1]
    return v * _RV2D[i2], v * _RV2D[i2 | 1]


def _grad_dual3(seed, xp, yp, zp, xd, yd, zd):
    h = _hash3(seed, xp, yp, zp)
    i1 = h & (63 << 2)
    i2 = (h >> 6) & (255 << 2)
    v = xd * _G3D[i1] + yd * _G3D[i1 | 1] + zd * _G3D[i1 | 2]
    return v * _RV3D[i2], v * _RV3D[i2 | 1], v * _RV3D[i2 | 2]


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
    lx0x = _lerp(_RV2D[h0], _RV2D[h1], xs)
    ly0x = _lerp(_RV2D[h0 | 1], _RV2D[h1 | 1], xs)
    h0 = _hash2(seed, x0, y1) & (255 << 1)
    h1 = _hash2(seed, x1, y1) & (255 << 1)
    lx1x = _lerp(_RV2D[h0], _RV2D[h1], xs)
    ly1x = _lerp(_RV2D[h0 | 1], _RV2D[h1 | 1], xs)
    return _lerp(lx0x, lx1x, ys) * amp, _lerp(ly0x, ly1x, ys) * amp


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
    lx0x = _lerp(_RV3D[h0], _RV3D[h1], xs)
    ly0x = _lerp(_RV3D[h0 | 1], _RV3D[h1 | 1], xs)
    lz0x = _lerp(_RV3D[h0 | 2], _RV3D[h1 | 2], xs)
    h0 = _hash3(seed, x0, y1, z0) & (255 << 2)
    h1 = _hash3(seed, x1, y1, z0) & (255 << 2)
    lx1x = _lerp(_RV3D[h0], _RV3D[h1], xs)
    ly1x = _lerp(_RV3D[h0 | 1], _RV3D[h1 | 1], xs)
    lz1x = _lerp(_RV3D[h0 | 2], _RV3D[h1 | 2], xs)
    lx0y = _lerp(lx0x, lx1x, ys)
    ly0y = _lerp(ly0x, ly1x, ys)
    lz0y = _lerp(lz0x, lz1x, ys)

    h0 = _hash3(seed, x0, y0, z1) & (255 << 2)
    h1 = _hash3(seed, x1, y0, z1) & (255 << 2)
    lx0x = _lerp(_RV3D[h0], _RV3D[h1], xs)
    ly0x = _lerp(_RV3D[h0 | 1], _RV3D[h1 | 1], xs)
    lz0x = _lerp(_RV3D[h0 | 2], _RV3D[h1 | 2], xs)
    h0 = _hash3(seed, x0, y1, z1) & (255 << 2)
    h1 = _hash3(seed, x1, y1, z1) & (255 << 2)
    lx1x = _lerp(_RV3D[h0], _RV3D[h1], xs)
    ly1x = _lerp(_RV3D[h0 | 1], _RV3D[h1 | 1], xs)
    lz1x = _lerp(_RV3D[h0 | 2], _RV3D[h1 | 2], xs)
    return (
        _lerp(lx0y, _lerp(lx0x, lx1x, ys), zs) * amp,
        _lerp(ly0y, _lerp(ly0x, ly1x, ys), zs) * amp,
        _lerp(lz0y, _lerp(lz0x, lz1x, ys), zs) * amp,
    )


def _warp_simplex_grad2(seed, amp, freq, x, y, grad_only: bool):
    x = x * freq
    y = y * freq
    i = _fast_floor(x)
    j = _fast_floor(y)
    xi = x - i
    yi = y - j
    t = (xi + yi) * _G2
    x0 = xi - t
    y0 = yi - t
    ip = _wrap32(i * PRIME_X)
    jp = _wrap32(j * PRIME_Y)
    ip1 = _wrap32(ip + PRIME_X)
    jp1 = _wrap32(jp + PRIME_Y)
    grad = _grad_out2 if grad_only else _grad_dual2

    def term(mask, w, gi, gj, gx, gy):
        if grad_only:
            xo, yo = grad(seed, gi, gj)
        else:
            xo, yo = grad(seed, gi, gj, gx, gy)
        wwww = _quart(w)
        return np.where(mask, wwww * xo, 0.0), np.where(mask, wwww * yo, 0.0)

    a = 0.5 - x0 * x0 - y0 * y0
    vx, vy = term(a > 0.0, a, ip, jp, x0, y0)

    c = (2.0 * (1.0 - 2.0 * _G2) * (1.0 / _G2 - 2.0)) * t + ((-2.0 * (1.0 - 2.0 * _G2) * (1.0 - 2.0 * _G2)) + a)
    x2 = x0 + (2.0 * _G2 - 1.0)
    y2 = y0 + (2.0 * _G2 - 1.0)
    dx, dy = term(c > 0.0, c, ip1, jp1, x2, y2)
    vx = vx + dx
    vy = vy + dy

    upper = y0 > x0
    x1 = np.where(upper, x0 + _G2, x0 + (_G2 - 1.0))
    y1 = np.where(upper, y0 + (_G2 - 1.0), y0 + _G2)
    b = 0.5 - x1 * x1 - y1 * y1
    dx, dy = term(b > 0.0, b, np.where(upper, ip, ip1), np.where(upper, jp1, jp), x1, y1)
    vx = vx + dx
    vy = vy + dy
    return vx * amp, vy * amp


def _warp_simplex_grad3(seed, amp, freq, x, y, z, grad_only: bool):
    x = x * freq
    y = y * freq
    z = z * freq
    i = _fast_round(x)
    j = _fast_round(y)
    k = _fast_round(z)
    x0 = x - i
    y0 = y - j
    z0 = z - k

    xns = (-x0 - 1.0).astype(_I64) | 1
    yns = (-y0 - 1.0).astype(_I64) | 1
    zns = (-z0 - 1.0).astype(_I64) | 1

    ax0 = xns * -x0
    ay0 = yns * -y0
    az0 = zns * -z0

    ip = _wrap32(i * PRIME_X)
    jp = _wrap32(j * PRIME_Y)
    kp = _wrap32(k * PRIME_Z)

    def term(mask, w, gi, gj, gk, gx, gy, gz):
        if grad_only:
            xo, yo, zo = _grad_out3(seed, gi, gj, gk)
        else:
            xo, yo, zo = _grad_dual3(seed, gi, gj, gk, gx, gy, gz)
        wwww = _quart(w)
        return np.where(mask, wwww * xo, 0.0), np.where(mask, wwww * yo, 0.0), np.where(mask, wwww * zo, 0.0)

    vx = np.zeros(x.shape, dtype=np.float64)
    vy = np.zeros(x.shape, dtype=np.float64)
    vz = np.zeros(x.shape, dtype=np.float64)
    a = (0.6 - x0 * x0) - (y0 * y0 + z0 * z0)
    for step in range(2):
        dx, dy, dz = term(a > 0.0, a, ip, jp, kp, x0, y0, z0)
        vx = vx + dx
        vy = vy + dy
        vz = vz + dz

        mx = (ax0 >= ay0) & (ax0 >= az0)
        my = ~mx & (ay0 > ax0) & (ay0 >= az0)
        mz = ~mx & ~my
        x1 = x0 + np.where(mx, xns, 0)
        y1 = y0 + np.where(my, yns, 0)
        z1 = z0 + np.where(mz, zns, 0)
        b = (
            a
            + 1.0
            - np.where(mx, xns * 2.0 * x1, 0.0)
            - np.where(my, yns * 2.0 * y1, 0.0)
            - np.where(mz, zns * 2.0 * z1, 0.0)
        )
        i1 = np.where(mx, _wrap32(ip - xns * PRIME_X), ip)
        j1 = np.where(my, _wrap32(jp - yns * PRIME_Y), jp)
        k1 = np.where(mz, _wrap32(kp - zns * PRIME_Z), kp)
        dx, dy, dz = term(b > 0.0, b, i1, j1, k1, x1, y1, z1)
        vx = vx + dx
        vy = vy + dy
        vz = vz + dz

        if step == 1:
            break

        ax0 = 0.5 - ax0
        ay0 = 0.5 - ay0
        az0 = 0.5 - az0
        x0 = xns * ax0
        y0 = yns * ay0
        z0 = zns * az0
        a = a + (0.75 - ax0) - (ay0 + az0)
        ip = _wrap32(ip + ((xns >> 1) & PRIME_X))
        jp = _wrap32(jp + ((yns >> 1) & PRIME_Y))
        kp = _wrap32(kp + ((zns >> 1) & PRIME_Z))
        xns = -xns
        yns = -yns
        zns = -zns
        seed = _wrap32_scalar(seed + 1293373)

    return vx * amp, vy * amp, vz * amp


def _warp_transform2(warp_type: int, x, y):
    if warp_type in (WARP_OPEN_SIMPLEX2, WARP_OPEN_SIMPLEX2_REDUCED):
        t = (x + y) * _F2
        return x + t, y + t
    return x, y


def _do_warp2(warp_type: int, seed, amp, freq, x, y):
    if warp_type == WARP_OPEN_SIMPLEX2:
        return _warp_simplex_grad2(seed, amp * 38.283687591552734375, freq, x, y, False)
    if warp_type == WARP_OPEN_SIMPLEX2_REDUCED:
        return _warp_simplex_grad2(seed, amp * 16.0, freq, x, y, True)
    return _warp_basic_grid2(seed, amp, freq, x, y)


def _do_warp3(warp_type: int, seed, amp, freq, x, y, z):
    if warp_type == WARP_OPEN_SIMPLEX2:
        return _warp_simplex_grad3(seed, amp * 32.69428253173828125, freq, x, y, z, False)
    if warp_type == WARP_OPEN_SIMPLEX2_REDUCED:
        return _warp_simplex_grad3(seed, amp * 7.71604938271605, freq, x, y, z, True)
    return _warp_basic_grid3(seed, amp, freq, x, y, z)


def warp2(warp_type: int, warp_fractal: int, seed: int, amp: float, freq: float, octaves: int, lacunarity, gain, x, y):
    """The reference's ``DomainWarp(x, y)`` over arrays; same contract as `scalar.warp2`."""
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
            x = x + dx
            y = y + dy
            seed = _wrap32_scalar(seed + 1)
            amp *= gain
            freq *= lacunarity
        return x, y
    xs, ys = _warp_transform2(warp_type, x, y)
    for _ in range(octaves):
        dx, dy = _do_warp2(warp_type, seed, amp, freq, xs, ys)
        x = x + dx
        y = y + dy
        seed = _wrap32_scalar(seed + 1)
        amp *= gain
        freq *= lacunarity
    return x, y


def warp3(
    warp_type: int,
    warp_fractal: int,
    warp_transform: int,
    seed: int,
    amp: float,
    freq: float,
    octaves: int,
    lacunarity,
    gain,
    x,
    y,
    z,
):
    """The reference's ``DomainWarp(x, y, z)`` over arrays; same contract as `scalar.warp3`."""
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
            x = x + dx
            y = y + dy
            z = z + dz
            seed = _wrap32_scalar(seed + 1)
            amp *= gain
            freq *= lacunarity
        return x, y, z
    xs, ys, zs = _transform3(warp_transform, x, y, z)
    for _ in range(octaves):
        dx, dy, dz = _do_warp3(warp_type, seed, amp, freq, xs, ys, zs)
        x = x + dx
        y = y + dy
        z = z + dz
        seed = _wrap32_scalar(seed + 1)
        amp *= gain
        freq *= lacunarity
    return x, y, z


def _transform2(noise_type: int, x, y):
    if noise_type in (NOISE_OPEN_SIMPLEX2, NOISE_OPEN_SIMPLEX2S):
        t = (x + y) * _F2
        return x + t, y + t
    return x, y


def _transform3(transform: int, x, y, z):
    if transform == TRANSFORM_IMPROVE_XY:
        xy = x + y
        s2 = xy * -0.211324865405187
        z = z * 0.577350269189626
        return x + s2 - z, y + s2 - z, z + xy * 0.577350269189626
    if transform == TRANSFORM_IMPROVE_XZ:
        xz = x + z
        s2 = xz * -0.211324865405187
        y = y * 0.577350269189626
        return x + s2 - y, y + xz * 0.577350269189626, z + s2 - y
    if transform == TRANSFORM_DEFAULT_OS2:
        r = (x + y + z) * _R3
        return r - x, r - y, r - z
    return x, y, z


def _fractal(single, coords, fractal_type, seed, octaves, lacunarity, gain, weighted, ping_pong, bounding, is_3d):
    if fractal_type == FRACTAL_NONE:
        return single(seed, *coords)
    total = np.zeros(coords[0].shape, dtype=np.float64)
    amp = np.full(coords[0].shape, 1.0 if fractal_type == FRACTAL_RIGID_MULTI else bounding, dtype=np.float64)
    coords = [c.copy() for c in coords]
    for octave in range(octaves):
        n = single(seed, *coords)
        seed += 1
        if fractal_type == FRACTAL_FBM:
            total += n * amp
            weight = (n + 1.0) * 0.5 if is_3d else np.minimum(n + 1.0, 2.0) * 0.5
            amp *= _lerp(1.0, weight, weighted)
        elif fractal_type == FRACTAL_RIDGED:
            n = np.abs(n)
            total += (n * -2.0 + 1.0) * amp
            amp *= _lerp(1.0, 1.0 - n, weighted)
        elif (
            fractal_type == FRACTAL_RIGID_MULTI
        ):  # FastNoiseSIMD: 1 - |n|, first added, the rest subtracted, unnormalised
            n = 1.0 - np.abs(n)
            total = total + (n * amp if octave == 0 else -n * amp)
        elif fractal_type == FRACTAL_BILLOW:  # FastNoiseSIMD: |n| * 2 - 1 per octave
            n = np.abs(n) * 2.0 - 1.0
            total += n * amp
            amp *= _lerp(1.0, (n + 1.0) * 0.5, weighted)
        else:  # PING_PONG
            n = _ping_pong((n + 1.0) * ping_pong)
            total += (n - 0.5) * 2.0 * amp
            amp *= _lerp(1.0, n, weighted)
        for c in coords:
            c *= lacunarity
        amp *= gain
    return total


# -------------------------------------------------------------------------
# drivers, matching scalar.sample_2d / sample_3d argument for argument
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
    """Fill ``out`` with 2D noise; same contract as `scalar.sample_2d`."""
    seed = _wrap32_scalar(int(seed))
    if int(warp_type) != WARP_NONE:
        freq64 = float(np.float32(frequency))
        xw, yw = warp2(
            int(warp_type),
            int(warp_fractal),
            seed,
            float(warp_amp),
            freq64,
            int(octaves),
            lacunarity,
            gain,
            np.asarray(xs, dtype=np.float32).astype(np.float64),
            np.asarray(ys, dtype=np.float32).astype(np.float64),
        )
        x = xw * freq64
        y = yw * freq64
    else:
        x = (np.asarray(xs, dtype=np.float32) * np.float32(frequency)).astype(np.float64)
        y = (np.asarray(ys, dtype=np.float32) * np.float32(frequency)).astype(np.float64)
    if int(perturb_type) != PERTURB_NONE:
        x, y = perturb2(
            int(perturb_type),
            seed,
            bounding,
            float(perturb_amp),
            float(perturb_freq),
            int(perturb_octaves),
            perturb_lacunarity,
            perturb_gain,
            float(perturb_normalise) * float(np.float32(frequency)),
            x,
            y,
        )
    x, y = _transform2(int(noise_type), x, y)
    single = _single2(int(noise_type), cd, cr, cj, lookup_type, lookup_freq)
    out[...] = _fractal(
        single, (x, y), int(fractal_type), seed, int(octaves), lacunarity, gain, weighted, ping_pong, bounding, False
    )
    return out


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
    """Fill ``out`` with 3D noise; same contract as `scalar.sample_3d`."""
    seed = _wrap32_scalar(int(seed))
    if int(warp_type) != WARP_NONE:
        freq64 = float(np.float32(frequency))
        xw, yw, zw = warp3(
            int(warp_type),
            int(warp_fractal),
            int(warp_transform),
            seed,
            float(warp_amp),
            freq64,
            int(octaves),
            lacunarity,
            gain,
            np.asarray(xs, dtype=np.float32).astype(np.float64),
            np.asarray(ys, dtype=np.float32).astype(np.float64),
            np.asarray(zs, dtype=np.float32).astype(np.float64),
        )
        x = xw * freq64
        y = yw * freq64
        z = zw * freq64
    else:
        x = (np.asarray(xs, dtype=np.float32) * np.float32(frequency)).astype(np.float64)
        y = (np.asarray(ys, dtype=np.float32) * np.float32(frequency)).astype(np.float64)
        z = (np.asarray(zs, dtype=np.float32) * np.float32(frequency)).astype(np.float64)
    if int(perturb_type) != PERTURB_NONE:
        x, y, z = perturb3(
            int(perturb_type),
            seed,
            bounding,
            float(perturb_amp),
            float(perturb_freq),
            int(perturb_octaves),
            perturb_lacunarity,
            perturb_gain,
            float(perturb_normalise) * float(np.float32(frequency)),
            x,
            y,
            z,
        )
    x, y, z = _transform3(int(transform), x, y, z)
    single = _single3(int(noise_type), cd, cr, cj, lookup_type, lookup_freq)
    out[...] = _fractal(
        single, (x, y, z), int(fractal_type), seed, int(octaves), lacunarity, gain, weighted, ping_pong, bounding, True
    )
    return out


def warp_2d(xs, ys, out_x, out_y, seed, frequency, octaves, lacunarity, gain, warp_type, warp_amp, warp_fractal):
    """The warped raw coordinates alone; same contract as `scalar.warp_2d`."""
    xw, yw = warp2(
        int(warp_type),
        int(warp_fractal),
        _wrap32_scalar(int(seed)),
        float(warp_amp),
        float(np.float32(frequency)),
        int(octaves),
        lacunarity,
        gain,
        np.asarray(xs, dtype=np.float32).astype(np.float64),
        np.asarray(ys, dtype=np.float32).astype(np.float64),
    )
    out_x[...] = xw
    out_y[...] = yw


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
    """3D twin of `warp_2d`; same contract as `scalar.warp_3d`."""
    xw, yw, zw = warp3(
        int(warp_type),
        int(warp_fractal),
        int(warp_transform),
        _wrap32_scalar(int(seed)),
        float(warp_amp),
        float(np.float32(frequency)),
        int(octaves),
        lacunarity,
        gain,
        np.asarray(xs, dtype=np.float32).astype(np.float64),
        np.asarray(ys, dtype=np.float32).astype(np.float64),
        np.asarray(zs, dtype=np.float32).astype(np.float64),
    )
    out_x[...] = xw
    out_y[...] = yw
    out_z[...] = zw


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
    """The grid driver over materialised coordinates; same contract as `scalar.sample_grid`."""
    nx, ny, nz = out.shape
    ix, iy, iz = np.meshgrid(np.arange(nx), np.arange(ny), np.arange(nz), indexing="ij")
    xs = ((x0 + ix) * sx).astype(np.float32).ravel()
    ys = ((y0 + iy) * sy).astype(np.float32).ravel()
    zs = ((z0 + iz) * sz).astype(np.float32).ravel()
    flat = out.reshape(-1)  # a view of the C-contiguous output; sample_3d writes through it
    sample_3d(
        xs,
        ys,
        zs,
        flat,
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
    return out


if __name__ == "__main__":
    import time

    from hog_noise import scalar as K

    n = 4096
    rng = np.random.RandomState(1)
    xs = rng.uniform(-4096, 4096, n).astype(np.float32)
    ys = rng.uniform(-4096, 4096, n).astype(np.float32)
    zs = rng.uniform(-256, 256, n).astype(np.float32)
    a = np.empty(n, np.float32)
    b = np.empty(n, np.float32)
    from hog_noise.params import FractalType, NoiseParams, NoiseType

    def _args(p):
        # the record's own order, so this block cannot fall behind the drivers' signatures; frequency as float32
        k = p.kernel_args()
        return (k[0], np.float32(k[1]), *k[2:])

    args = _args(
        NoiseParams(
            seed=12345, frequency=0.01, noise_type=NoiseType.OPEN_SIMPLEX2, fractal_type=FractalType.FBM, octaves=4
        )
    )
    t = time.perf_counter()
    sample_3d(xs, ys, zs, a, *args)
    print(f"numpy base {1000 * (time.perf_counter() - t):.2f} ms for {n} points, 4 octaves")
    K.sample_3d(xs, ys, zs, b, *args)
    print("max |numpy - numba|:", np.abs(a - b).max())
    cell = _args(NoiseParams(seed=12345, frequency=0.01, noise_type=NoiseType.CELLULAR))
    sample_3d(xs, ys, zs, a, *cell)
    K.sample_3d(xs, ys, zs, b, *cell)
    print("cellular max |numpy - numba|:", np.abs(a - b).max(), "range", a.min(), a.max())
