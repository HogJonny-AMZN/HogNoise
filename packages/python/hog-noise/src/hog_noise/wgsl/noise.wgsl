// HogNoise: every noise in WGSL, ported function for function from src/hog_noise/scalar.py; the CPU function's name and
// line are in the comment above each function. Float32 throughout, where the CPU computes in float64 after the frequency
// multiply. i32 arithmetic wraps, as scalar.py's _wrap32 emulates, and >> on i32 is arithmetic, as Python's is.
// Spec: Docs/superpowers/specs/2026-11-14-gpu-port.md.

struct Params {
    seed : i32,
    frequency : f32,
    noise_type : i32,
    fractal_type : i32,
    octaves : i32,
    lacunarity : f32,
    gain : f32,
    weighted_strength : f32,
    ping_pong_strength : f32,
    fractal_bounding : f32,
    cellular_distance : i32,
    cellular_return : i32,
    cellular_jitter : f32,
    transform_3d : i32,
    domain_warp : i32,
    warp_amp : f32,
    warp_fractal : i32,
    warp_transform_3d : i32,
    cellular_lookup_type : i32,
    cellular_lookup_frequency : f32,
    perturb : i32,
    perturb_amp : f32,
    perturb_frequency : f32,
    perturb_octaves : i32,
    perturb_lacunarity : f32,
    perturb_gain : f32,
    perturb_normalise_length : f32,
};

struct Grid {
    x0 : i32, y0 : i32, z0 : i32,
    nx : u32, ny : u32, nz : u32,
    sx : f32, sy : f32, sz : f32,
};

@group(0) @binding(0) var<uniform> P : Params;
@group(0) @binding(1) var<storage, read> T : array<f32, 2048>;
@group(0) @binding(2) var<storage, read> XS : array<f32>;
@group(0) @binding(3) var<storage, read> YS : array<f32>;
@group(0) @binding(4) var<storage, read> ZS : array<f32>;
@group(0) @binding(5) var<storage, read_write> OUT : array<f32>;
@group(0) @binding(6) var<uniform> G : Grid;

// tables.py, concatenated by gpu._Gpu in this order
fn gradients_2d(i : i32) -> f32 { return T[i]; }
fn gradients_3d(i : i32) -> f32 { return T[256 + i]; }
fn rand_vecs_2d(i : i32) -> f32 { return T[512 + i]; }
fn rand_vecs_3d(i : i32) -> f32 { return T[1024 + i]; }

// -------------------------------------------------------------------------
// scalar.py: the constants (55-62). The float ones are abstract (untyped), so an expression over them is folded at
// full precision and rounded to f32 once where it is used, as the CPU's float64 literal would be.
const PRIME_X : i32 = 501125321;
const PRIME_Y : i32 = 1136930381;
const PRIME_Z : i32 = 1720413743;
// scalar.py writes _wrap32(PRIME_X << 1) and its Y and Z twins (306, 390, 652, 707, 726, 727, 746, 764); an overflowing
// constant shift is a shader-creation error in WGSL, so they are declared wrapped.
const PRIME_X2 : i32 = 1002250642;
const PRIME_Y2 : i32 = -2021106534;
const PRIME_Z2 : i32 = -854139810;
const HASH_MUL : i32 = 668265261; // 0x27D4EB2D
const SQRT3 = 1.7320508075688772935274463415059;
const F2 = 0.5 * (SQRT3 - 1.0);
const G2 = (3.0 - SQRT3) / 6.0;
const R3 = 2.0 / 3.0;

// scalar.py: the noise, fractal, cellular, transform, warp and perturb numbers (64-116)
const NOISE_OPEN_SIMPLEX2 : i32 = 0;
const NOISE_OPEN_SIMPLEX2S : i32 = 1;
const NOISE_CELLULAR : i32 = 2;
const NOISE_PERLIN : i32 = 3;
const NOISE_VALUE_CUBIC : i32 = 4;
const NOISE_VALUE : i32 = 5;
const NOISE_WHITE_NOISE : i32 = 6;
const NOISE_SIMPLEX_CLASSIC : i32 = 7;
const FNS_PRIME_X : i32 = 1619;
const FNS_PRIME_Y : i32 = 31337;
const FNS_PRIME_Z : i32 = 6971;
const FNS_HASH_MUL : i32 = 60493;
const FNS_HASH_TO_FLOAT = 1.0 / 2147483648.0;
const FRACTAL_NONE : i32 = 0;
const FRACTAL_FBM : i32 = 1;
const FRACTAL_RIDGED : i32 = 2;
const FRACTAL_PING_PONG : i32 = 3;
const FRACTAL_BILLOW : i32 = 6;
const FRACTAL_RIGID_MULTI : i32 = 7;
const CELL_DIST_EUCLIDEAN : i32 = 0;
const CELL_DIST_EUCLIDEAN_SQ : i32 = 1;
const CELL_DIST_MANHATTAN : i32 = 2;
const CELL_DIST_HYBRID : i32 = 3;
const CELL_DIST_NATURAL : i32 = 4;
const CELL_RET_CELL_VALUE : i32 = 0;
const CELL_RET_DISTANCE : i32 = 1;
const CELL_RET_DISTANCE2 : i32 = 2;
const CELL_RET_DISTANCE2_ADD : i32 = 3;
const CELL_RET_DISTANCE2_SUB : i32 = 4;
const CELL_RET_DISTANCE2_MUL : i32 = 5;
const CELL_RET_DISTANCE2_DIV : i32 = 6;
const CELL_RET_NOISE_LOOKUP : i32 = 7;
const CELL_RET_DISTANCE2_CAVE : i32 = 8;
const TRANSFORM_NONE : i32 = 0;
const TRANSFORM_IMPROVE_XY : i32 = 1;
const TRANSFORM_IMPROVE_XZ : i32 = 2;
const TRANSFORM_DEFAULT_OS2 : i32 = 3;
const WARP_NONE : i32 = 0;
const WARP_OPEN_SIMPLEX2 : i32 = 1;
const WARP_OPEN_SIMPLEX2_REDUCED : i32 = 2;
const WARP_BASIC_GRID : i32 = 3;
const WARP_SINGLE : i32 = 0;
const WARP_PROGRESSIVE : i32 = 1;
const WARP_INDEPENDENT : i32 = 2;
const PERTURB_NONE : i32 = 0;
const PERTURB_GRADIENT : i32 = 1;
const PERTURB_GRADIENT_FRACTAL : i32 = 2;
const PERTURB_NORMALISE : i32 = 3;
const PERTURB_GRADIENT_NORMALISE : i32 = 4;
const PERTURB_GRADIENT_FRACTAL_NORMALISE : i32 = 5;

// -------------------------------------------------------------------------
// 32-bit integer hashing and interpolation helpers

// scalar.py: _hash2 (128)
fn _hash2(seed : i32, xp : i32, yp : i32) -> i32 {
    return (seed ^ xp ^ yp) * HASH_MUL;
}

// scalar.py: _hash3 (133)
fn _hash3(seed : i32, xp : i32, yp : i32, zp : i32) -> i32 {
    return (seed ^ xp ^ yp ^ zp) * HASH_MUL;
}

// scalar.py: _val_coord2 (138)
fn _val_coord2(seed : i32, xp : i32, yp : i32) -> f32 {
    var h = _hash2(seed, xp, yp);
    h = h * h;
    h = h ^ (h << 19u);
    return f32(h) * (1.0 / 2147483648.0);
}

// scalar.py: _val_coord3 (146)
fn _val_coord3(seed : i32, xp : i32, yp : i32, zp : i32) -> f32 {
    var h = _hash3(seed, xp, yp, zp);
    h = h * h;
    h = h ^ (h << 19u);
    return f32(h) * (1.0 / 2147483648.0);
}

// scalar.py: _grad_coord2 (154)
fn _grad_coord2(seed : i32, xp : i32, yp : i32, xd : f32, yd : f32) -> f32 {
    var h = _hash2(seed, xp, yp);
    h ^= h >> 15u;
    h &= 127 << 1;
    return xd * gradients_2d(h) + yd * gradients_2d(h | 1);
}

// scalar.py: _grad_coord3 (162)
fn _grad_coord3(seed : i32, xp : i32, yp : i32, zp : i32, xd : f32, yd : f32, zd : f32) -> f32 {
    var h = _hash3(seed, xp, yp, zp);
    h ^= h >> 15u;
    h &= 63 << 2;
    return xd * gradients_3d(h) + yd * gradients_3d(h | 1) + zd * gradients_3d(h | 2);
}

// scalar.py: _fast_floor (170). The reference's quirk, kept for parity: (int)f - 1 for any negative f, integral or not.
fn _fast_floor(f : f32) -> i32 {
    var i = i32(f);
    if (f < 0.0) {
        i -= 1;
    }
    return i;
}

// scalar.py: _fast_round (179)
fn _fast_round(f : f32) -> i32 {
    if (f >= 0.0) {
        return i32(f + 0.5);
    }
    return i32(f - 0.5);
}

// scalar.py: _lerp (186)
fn _lerp(a : f32, b : f32, t : f32) -> f32 {
    return a + t * (b - a);
}

// scalar.py: _interp_hermite (191)
fn _interp_hermite(t : f32) -> f32 {
    return t * t * (3.0 - 2.0 * t);
}

// scalar.py: _interp_quintic (196)
fn _interp_quintic(t : f32) -> f32 {
    return t * t * t * (t * (t * 6.0 - 15.0) + 10.0);
}

// scalar.py: _cubic_lerp (201)
fn _cubic_lerp(a : f32, b : f32, c : f32, d : f32, t : f32) -> f32 {
    let p = (d - c) - (a - b);
    return t * t * t * p + t * t * ((a - b) - p) + t * (c - a) + b;
}

// scalar.py: _ping_pong (207)
fn _ping_pong(t_in : f32) -> f32 {
    var t = t_in;
    t -= f32(i32(t * 0.5) * 2);
    return select(2.0 - t, t, t < 1.0);
}

// -------------------------------------------------------------------------
// single-octave noise, 2D

// scalar.py: simplex2 (215). x, y are already skewed by _transform2.
fn simplex2(seed : i32, x : f32, y : f32) -> f32 {
    var i = _fast_floor(x);
    var j = _fast_floor(y);
    let xi = x - f32(i);
    let yi = y - f32(j);
    let t = (xi + yi) * G2;
    let x0 = xi - t;
    let y0 = yi - t;
    i = i * PRIME_X;
    j = j * PRIME_Y;

    var n0 : f32;
    let a = 0.5 - x0 * x0 - y0 * y0;
    if (a <= 0.0) {
        n0 = 0.0;
    } else {
        n0 = (a * a) * (a * a) * _grad_coord2(seed, i, j, x0, y0);
    }

    var n2 : f32;
    let c = (2.0 * (1.0 - 2.0 * G2) * (1.0 / G2 - 2.0)) * t + ((-2.0 * (1.0 - 2.0 * G2) * (1.0 - 2.0 * G2)) + a);
    if (c <= 0.0) {
        n2 = 0.0;
    } else {
        let x2 = x0 + (2.0 * G2 - 1.0);
        let y2 = y0 + (2.0 * G2 - 1.0);
        n2 = (c * c) * (c * c) * _grad_coord2(seed, i + PRIME_X, j + PRIME_Y, x2, y2);
    }

    var n1 : f32;
    if (y0 > x0) {
        let x1 = x0 + G2;
        let y1 = y0 + (G2 - 1.0);
        let b = 0.5 - x1 * x1 - y1 * y1;
        if (b <= 0.0) {
            n1 = 0.0;
        } else {
            n1 = (b * b) * (b * b) * _grad_coord2(seed, i, j + PRIME_Y, x1, y1);
        }
    } else {
        let x1 = x0 + (G2 - 1.0);
        let y1 = y0 + G2;
        let b = 0.5 - x1 * x1 - y1 * y1;
        if (b <= 0.0) {
            n1 = 0.0;
        } else {
            n1 = (b * b) * (b * b) * _grad_coord2(seed, i + PRIME_X, j, x1, y1);
        }
    }

    return (n0 + n1 + n2) * 99.83685446303647;
}

// scalar.py: simplex2s (262). The smoother variant, a modified 2D simplex; x, y are already skewed by _transform2.
fn simplex2s(seed : i32, x : f32, y : f32) -> f32 {
    var i = _fast_floor(x);
    var j = _fast_floor(y);
    let xi = x - f32(i);
    let yi = y - f32(j);

    i = i * PRIME_X;
    j = j * PRIME_Y;
    let i1 = i + PRIME_X;
    let j1 = j + PRIME_Y;

    let t = (xi + yi) * G2;
    let x0 = xi - t;
    let y0 = yi - t;

    let a0 = (2.0 / 3.0) - x0 * x0 - y0 * y0;
    var value = (a0 * a0) * (a0 * a0) * _grad_coord2(seed, i, j, x0, y0);

    let a1 = (2.0 * (1.0 - 2.0 * G2) * (1.0 / G2 - 2.0)) * t + ((-2.0 * (1.0 - 2.0 * G2) * (1.0 - 2.0 * G2)) + a0);
    let x1 = x0 - (1.0 - 2.0 * G2);
    let y1 = y0 - (1.0 - 2.0 * G2);
    value += (a1 * a1) * (a1 * a1) * _grad_coord2(seed, i1, j1, x1, y1);

    let xmyi = xi - yi;
    if (t > G2) {
        if (xi + xmyi > 1.0) {
            let x2 = x0 + (3.0 * G2 - 2.0);
            let y2 = y0 + (3.0 * G2 - 1.0);
            let a2 = (2.0 / 3.0) - x2 * x2 - y2 * y2;
            if (a2 > 0.0) {
                value += (a2 * a2) * (a2 * a2) * _grad_coord2(seed, i + PRIME_X2, j1, x2, y2);
            }
        } else {
            let x2 = x0 + G2;
            let y2 = y0 + (G2 - 1.0);
            let a2 = (2.0 / 3.0) - x2 * x2 - y2 * y2;
            if (a2 > 0.0) {
                value += (a2 * a2) * (a2 * a2) * _grad_coord2(seed, i, j1, x2, y2);
            }
        }

        if (yi - xmyi > 1.0) {
            let x3 = x0 + (3.0 * G2 - 1.0);
            let y3 = y0 + (3.0 * G2 - 2.0);
            let a3 = (2.0 / 3.0) - x3 * x3 - y3 * y3;
            if (a3 > 0.0) {
                value += (a3 * a3) * (a3 * a3) * _grad_coord2(seed, i1, j + PRIME_Y2, x3, y3);
            }
        } else {
            let x3 = x0 + (G2 - 1.0);
            let y3 = y0 + G2;
            let a3 = (2.0 / 3.0) - x3 * x3 - y3 * y3;
            if (a3 > 0.0) {
                value += (a3 * a3) * (a3 * a3) * _grad_coord2(seed, i1, j, x3, y3);
            }
        }
    } else {
        if (xi + xmyi < 0.0) {
            let x2 = x0 + (1.0 - G2);
            let y2 = y0 - G2;
            let a2 = (2.0 / 3.0) - x2 * x2 - y2 * y2;
            if (a2 > 0.0) {
                value += (a2 * a2) * (a2 * a2) * _grad_coord2(seed, i - PRIME_X, j, x2, y2);
            }
        } else {
            let x2 = x0 + (G2 - 1.0);
            let y2 = y0 + G2;
            let a2 = (2.0 / 3.0) - x2 * x2 - y2 * y2;
            if (a2 > 0.0) {
                value += (a2 * a2) * (a2 * a2) * _grad_coord2(seed, i1, j, x2, y2);
            }
        }

        if (yi < xmyi) {
            let x3 = x0 - G2;
            let y3 = y0 - (G2 - 1.0);
            let a3 = (2.0 / 3.0) - x3 * x3 - y3 * y3;
            if (a3 > 0.0) {
                value += (a3 * a3) * (a3 * a3) * _grad_coord2(seed, i, j - PRIME_Y, x3, y3);
            }
        } else {
            let x3 = x0 + G2;
            let y3 = y0 + (G2 - 1.0);
            let a3 = (2.0 / 3.0) - x3 * x3 - y3 * y3;
            if (a3 > 0.0) {
                value += (a3 * a3) * (a3 * a3) * _grad_coord2(seed, i, j1, x3, y3);
            }
        }
    }

    return value * 18.24196194486065;
}

// scalar.py: perlin2 (344)
fn perlin2(seed : i32, x : f32, y : f32) -> f32 {
    var x0 = _fast_floor(x);
    var y0 = _fast_floor(y);
    let xd0 = x - f32(x0);
    let yd0 = y - f32(y0);
    let xd1 = xd0 - 1.0;
    let yd1 = yd0 - 1.0;
    let xs = _interp_quintic(xd0);
    let ys = _interp_quintic(yd0);
    x0 = x0 * PRIME_X;
    y0 = y0 * PRIME_Y;
    let x1 = x0 + PRIME_X;
    let y1 = y0 + PRIME_Y;
    let xf0 = _lerp(_grad_coord2(seed, x0, y0, xd0, yd0), _grad_coord2(seed, x1, y0, xd1, yd0), xs);
    let xf1 = _lerp(_grad_coord2(seed, x0, y1, xd0, yd1), _grad_coord2(seed, x1, y1, xd1, yd1), xs);
    return _lerp(xf0, xf1, ys) * 1.4247691104677813;
}

// scalar.py: value2 (363)
fn value2(seed : i32, x : f32, y : f32) -> f32 {
    var x0 = _fast_floor(x);
    var y0 = _fast_floor(y);
    let xs = _interp_hermite(x - f32(x0));
    let ys = _interp_hermite(y - f32(y0));
    x0 = x0 * PRIME_X;
    y0 = y0 * PRIME_Y;
    let x1 = x0 + PRIME_X;
    let y1 = y0 + PRIME_Y;
    let xf0 = _lerp(_val_coord2(seed, x0, y0), _val_coord2(seed, x1, y0), xs);
    let xf1 = _lerp(_val_coord2(seed, x0, y1), _val_coord2(seed, x1, y1), xs);
    return _lerp(xf0, xf1, ys);
}

// scalar.py: value_cubic2 (378). _wrap32(PRIME_X << 1) is PRIME_X2, and Y likewise (the constants' comment).
fn value_cubic2(seed : i32, x : f32, y : f32) -> f32 {
    var x1 = _fast_floor(x);
    var y1 = _fast_floor(y);
    let xs = x - f32(x1);
    let ys = y - f32(y1);
    x1 = x1 * PRIME_X;
    y1 = y1 * PRIME_Y;
    let x0 = x1 - PRIME_X;
    let y0 = y1 - PRIME_Y;
    let x2 = x1 + PRIME_X;
    let y2 = y1 + PRIME_Y;
    let x3 = x1 + PRIME_X2;
    let y3 = y1 + PRIME_Y2;
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
    ) * (1.0 / (1.5 * 1.5));
}

// -------------------------------------------------------------------------
// single-octave noise, 3D

// scalar.py: opensimplex2_3 (427). x, y, z are already rotated by _transform3.
fn opensimplex2_3(seed_in : i32, x : f32, y : f32, z : f32) -> f32 {
    var seed = seed_in;
    var i = _fast_round(x);
    var j = _fast_round(y);
    var k = _fast_round(z);
    var x0 = x - f32(i);
    var y0 = y - f32(j);
    var z0 = z - f32(k);

    var x_nsign = i32(-1.0 - x0) | 1;
    var y_nsign = i32(-1.0 - y0) | 1;
    var z_nsign = i32(-1.0 - z0) | 1;

    var ax0 = f32(x_nsign) * -x0;
    var ay0 = f32(y_nsign) * -y0;
    var az0 = f32(z_nsign) * -z0;

    i = i * PRIME_X;
    j = j * PRIME_Y;
    k = k * PRIME_Z;

    var value = 0.0;
    var a = (0.6 - x0 * x0) - (y0 * y0 + z0 * z0);
    for (var step = 0; step < 2; step++) {
        if (a > 0.0) {
            value += (a * a) * (a * a) * _grad_coord3(seed, i, j, k, x0, y0, z0);
        }

        var b = a + 1.0;
        var i1 = i;
        var j1 = j;
        var k1 = k;
        var x1 = x0;
        var y1 = y0;
        var z1 = z0;
        if (ax0 >= ay0 && ax0 >= az0) {
            x1 += f32(x_nsign);
            b -= f32(x_nsign) * 2.0 * x1;
            i1 = i1 - x_nsign * PRIME_X;
        } else if (ay0 > ax0 && ay0 >= az0) {
            y1 += f32(y_nsign);
            b -= f32(y_nsign) * 2.0 * y1;
            j1 = j1 - y_nsign * PRIME_Y;
        } else {
            z1 += f32(z_nsign);
            b -= f32(z_nsign) * 2.0 * z1;
            k1 = k1 - z_nsign * PRIME_Z;
        }

        if (b > 0.0) {
            value += (b * b) * (b * b) * _grad_coord3(seed, i1, j1, k1, x1, y1, z1);
        }

        if (step == 1) {
            break;
        }

        ax0 = 0.5 - ax0;
        ay0 = 0.5 - ay0;
        az0 = 0.5 - az0;
        x0 = f32(x_nsign) * ax0;
        y0 = f32(y_nsign) * ay0;
        z0 = f32(z_nsign) * az0;
        a += (0.75 - ax0) - (ay0 + az0);
        i = i + ((x_nsign >> 1u) & PRIME_X);
        j = j + ((y_nsign >> 1u) & PRIME_Y);
        k = k + ((z_nsign >> 1u) & PRIME_Z);
        x_nsign = -x_nsign;
        y_nsign = -y_nsign;
        z_nsign = -z_nsign;
        seed = ~seed;
    }

    return value * 32.69428253173828125;
}

// scalar.py: opensimplex2s_3 (499). Two offset rotated cube grids; x, y, z are already rotated by _transform3. The CPU's
// PRIME_X * 2 (597, 744) is PRIME_X2, as its wrapped PRIME_Y << 1 and PRIME_Z << 1 are PRIME_Y2 and PRIME_Z2.
fn opensimplex2s_3(seed : i32, x : f32, y : f32, z : f32) -> f32 {
    var i = _fast_floor(x);
    var j = _fast_floor(y);
    var k = _fast_floor(z);
    let xi = x - f32(i);
    let yi = y - f32(j);
    let zi = z - f32(k);

    i = i * PRIME_X;
    j = j * PRIME_Y;
    k = k * PRIME_Z;
    let seed2 = seed + 1293373;

    // 0 or -1 per axis: which half of the cell the point sits in (truncation toward zero)
    let x_nmask = i32(-0.5 - xi);
    let y_nmask = i32(-0.5 - yi);
    let z_nmask = i32(-0.5 - zi);

    let x0 = xi + f32(x_nmask);
    let y0 = yi + f32(y_nmask);
    let z0 = zi + f32(z_nmask);
    let a0 = 0.75 - x0 * x0 - y0 * y0 - z0 * z0;
    var value = (a0 * a0) * (a0 * a0) * _grad_coord3(
        seed, i + (x_nmask & PRIME_X), j + (y_nmask & PRIME_Y), k + (z_nmask & PRIME_Z), x0, y0, z0,
    );

    let x1 = xi - 0.5;
    let y1 = yi - 0.5;
    let z1 = zi - 0.5;
    let a1 = 0.75 - x1 * x1 - y1 * y1 - z1 * z1;
    value += (a1 * a1) * (a1 * a1) * _grad_coord3(seed2, i + PRIME_X, j + PRIME_Y, k + PRIME_Z, x1, y1, z1);

    let x_flip0 = f32((x_nmask | 1) << 1u) * x1;
    let y_flip0 = f32((y_nmask | 1) << 1u) * y1;
    let z_flip0 = f32((z_nmask | 1) << 1u) * z1;
    let x_flip1 = f32(-2 - (x_nmask << 2u)) * x1 - 1.0;
    let y_flip1 = f32(-2 - (y_nmask << 2u)) * y1 - 1.0;
    let z_flip1 = f32(-2 - (z_nmask << 2u)) * z1 - 1.0;

    var skip5 = false;
    let a2 = x_flip0 + a0;
    if (a2 > 0.0) {
        let x2 = x0 - f32(x_nmask | 1);
        value += (a2 * a2) * (a2 * a2) * _grad_coord3(
            seed, i + (~x_nmask & PRIME_X), j + (y_nmask & PRIME_Y), k + (z_nmask & PRIME_Z), x2, y0, z0,
        );
    } else {
        let a3 = y_flip0 + z_flip0 + a0;
        if (a3 > 0.0) {
            let y3 = y0 - f32(y_nmask | 1);
            let z3 = z0 - f32(z_nmask | 1);
            value += (a3 * a3) * (a3 * a3) * _grad_coord3(
                seed, i + (x_nmask & PRIME_X), j + (~y_nmask & PRIME_Y), k + (~z_nmask & PRIME_Z), x0, y3, z3,
            );
        }

        let a4 = x_flip1 + a1;
        if (a4 > 0.0) {
            let x4 = f32(x_nmask | 1) + x1;
            value += (a4 * a4) * (a4 * a4) * _grad_coord3(
                seed2, i + (x_nmask & PRIME_X2), j + PRIME_Y, k + PRIME_Z, x4, y1, z1,
            );
            skip5 = true;
        }
    }

    var skip9 = false;
    let a6 = y_flip0 + a0;
    if (a6 > 0.0) {
        let y6 = y0 - f32(y_nmask | 1);
        value += (a6 * a6) * (a6 * a6) * _grad_coord3(
            seed, i + (x_nmask & PRIME_X), j + (~y_nmask & PRIME_Y), k + (z_nmask & PRIME_Z), x0, y6, z0,
        );
    } else {
        let a7 = x_flip0 + z_flip0 + a0;
        if (a7 > 0.0) {
            let x7 = x0 - f32(x_nmask | 1);
            let z7 = z0 - f32(z_nmask | 1);
            value += (a7 * a7) * (a7 * a7) * _grad_coord3(
                seed, i + (~x_nmask & PRIME_X), j + (y_nmask & PRIME_Y), k + (~z_nmask & PRIME_Z), x7, y0, z7,
            );
        }

        let a8 = y_flip1 + a1;
        if (a8 > 0.0) {
            let y8 = f32(y_nmask | 1) + y1;
            value += (a8 * a8) * (a8 * a8) * _grad_coord3(
                seed2, i + PRIME_X, j + (y_nmask & PRIME_Y2), k + PRIME_Z, x1, y8, z1,
            );
            skip9 = true;
        }
    }

    var skip_d = false;
    let aa = z_flip0 + a0;
    if (aa > 0.0) {
        let za = z0 - f32(z_nmask | 1);
        value += (aa * aa) * (aa * aa) * _grad_coord3(
            seed, i + (x_nmask & PRIME_X), j + (y_nmask & PRIME_Y), k + (~z_nmask & PRIME_Z), x0, y0, za,
        );
    } else {
        let ab = x_flip0 + y_flip0 + a0;
        if (ab > 0.0) {
            let xb = x0 - f32(x_nmask | 1);
            let yb = y0 - f32(y_nmask | 1);
            value += (ab * ab) * (ab * ab) * _grad_coord3(
                seed, i + (~x_nmask & PRIME_X), j + (~y_nmask & PRIME_Y), k + (z_nmask & PRIME_Z), xb, yb, z0,
            );
        }

        let ac = z_flip1 + a1;
        if (ac > 0.0) {
            let zc = f32(z_nmask | 1) + z1;
            value += (ac * ac) * (ac * ac) * _grad_coord3(
                seed2, i + PRIME_X, j + PRIME_Y, k + (z_nmask & PRIME_Z2), x1, y1, zc,
            );
            skip_d = true;
        }
    }

    if (!skip5) {
        let a5 = y_flip1 + z_flip1 + a1;
        if (a5 > 0.0) {
            let y5 = f32(y_nmask | 1) + y1;
            let z5 = f32(z_nmask | 1) + z1;
            value += (a5 * a5) * (a5 * a5) * _grad_coord3(
                seed2, i + PRIME_X, j + (y_nmask & PRIME_Y2), k + (z_nmask & PRIME_Z2), x1, y5, z5,
            );
        }
    }

    if (!skip9) {
        let a9 = x_flip1 + z_flip1 + a1;
        if (a9 > 0.0) {
            let x9 = f32(x_nmask | 1) + x1;
            let z9 = f32(z_nmask | 1) + z1;
            value += (a9 * a9) * (a9 * a9) * _grad_coord3(
                seed2, i + (x_nmask & PRIME_X2), j + PRIME_Y, k + (z_nmask & PRIME_Z2), x9, y1, z9,
            );
        }
    }

    if (!skip_d) {
        let ad = x_flip1 + y_flip1 + a1;
        if (ad > 0.0) {
            let xd = f32(x_nmask | 1) + x1;
            let yd = f32(y_nmask | 1) + y1;
            value += (ad * ad) * (ad * ad) * _grad_coord3(
                seed2, i + (x_nmask & PRIME_X2), j + (y_nmask & PRIME_Y2), k + PRIME_Z, xd, yd, z1,
            );
        }
    }

    return value * 9.046026385208288;
}

// scalar.py: perlin3 (776)
fn perlin3(seed : i32, x : f32, y : f32, z : f32) -> f32 {
    var x0 = _fast_floor(x);
    var y0 = _fast_floor(y);
    var z0 = _fast_floor(z);
    let xd0 = x - f32(x0);
    let yd0 = y - f32(y0);
    let zd0 = z - f32(z0);
    let xd1 = xd0 - 1.0;
    let yd1 = yd0 - 1.0;
    let zd1 = zd0 - 1.0;
    let xs = _interp_quintic(xd0);
    let ys = _interp_quintic(yd0);
    let zs = _interp_quintic(zd0);
    x0 = x0 * PRIME_X;
    y0 = y0 * PRIME_Y;
    z0 = z0 * PRIME_Z;
    let x1 = x0 + PRIME_X;
    let y1 = y0 + PRIME_Y;
    let z1 = z0 + PRIME_Z;
    let xf00 = _lerp(_grad_coord3(seed, x0, y0, z0, xd0, yd0, zd0), _grad_coord3(seed, x1, y0, z0, xd1, yd0, zd0), xs);
    let xf10 = _lerp(_grad_coord3(seed, x0, y1, z0, xd0, yd1, zd0), _grad_coord3(seed, x1, y1, z0, xd1, yd1, zd0), xs);
    let xf01 = _lerp(_grad_coord3(seed, x0, y0, z1, xd0, yd0, zd1), _grad_coord3(seed, x1, y0, z1, xd1, yd0, zd1), xs);
    let xf11 = _lerp(_grad_coord3(seed, x0, y1, z1, xd0, yd1, zd1), _grad_coord3(seed, x1, y1, z1, xd1, yd1, zd1), xs);
    let yf0 = _lerp(xf00, xf10, ys);
    let yf1 = _lerp(xf01, xf11, ys);
    return _lerp(yf0, yf1, zs) * 0.964921414852142333984375;
}

// scalar.py: value3 (805)
fn value3(seed : i32, x : f32, y : f32, z : f32) -> f32 {
    var x0 = _fast_floor(x);
    var y0 = _fast_floor(y);
    var z0 = _fast_floor(z);
    let xs = _interp_hermite(x - f32(x0));
    let ys = _interp_hermite(y - f32(y0));
    let zs = _interp_hermite(z - f32(z0));
    x0 = x0 * PRIME_X;
    y0 = y0 * PRIME_Y;
    z0 = z0 * PRIME_Z;
    let x1 = x0 + PRIME_X;
    let y1 = y0 + PRIME_Y;
    let z1 = z0 + PRIME_Z;
    let xf00 = _lerp(_val_coord3(seed, x0, y0, z0), _val_coord3(seed, x1, y0, z0), xs);
    let xf10 = _lerp(_val_coord3(seed, x0, y1, z0), _val_coord3(seed, x1, y1, z0), xs);
    let xf01 = _lerp(_val_coord3(seed, x0, y0, z1), _val_coord3(seed, x1, y0, z1), xs);
    let xf11 = _lerp(_val_coord3(seed, x0, y1, z1), _val_coord3(seed, x1, y1, z1), xs);
    let yf0 = _lerp(xf00, xf10, ys);
    let yf1 = _lerp(xf01, xf11, ys);
    return _lerp(yf0, yf1, zs);
}

// scalar.py: _value_cubic3_row (828)
fn _value_cubic3_row(seed : i32, x0 : i32, x1 : i32, x2 : i32, x3 : i32, yp : i32, zp : i32, xs : f32) -> f32 {
    return _cubic_lerp(
        _val_coord3(seed, x0, yp, zp),
        _val_coord3(seed, x1, yp, zp),
        _val_coord3(seed, x2, yp, zp),
        _val_coord3(seed, x3, yp, zp),
        xs,
    );
}

// scalar.py: _value_cubic3_plane (839)
fn _value_cubic3_plane(
    seed : i32, x0 : i32, x1 : i32, x2 : i32, x3 : i32, y0 : i32, y1 : i32, y2 : i32, y3 : i32, zp : i32, xs : f32,
    ys : f32,
) -> f32 {
    return _cubic_lerp(
        _value_cubic3_row(seed, x0, x1, x2, x3, y0, zp, xs),
        _value_cubic3_row(seed, x0, x1, x2, x3, y1, zp, xs),
        _value_cubic3_row(seed, x0, x1, x2, x3, y2, zp, xs),
        _value_cubic3_row(seed, x0, x1, x2, x3, y3, zp, xs),
        ys,
    );
}

// scalar.py: value_cubic3 (850). _wrap32(PRIME_X << 1) and its Y and Z twins are PRIME_X2, PRIME_Y2, PRIME_Z2.
fn value_cubic3(seed : i32, x : f32, y : f32, z : f32) -> f32 {
    var x1 = _fast_floor(x);
    var y1 = _fast_floor(y);
    var z1 = _fast_floor(z);
    let xs = x - f32(x1);
    let ys = y - f32(y1);
    let zs = z - f32(z1);
    x1 = x1 * PRIME_X;
    y1 = y1 * PRIME_Y;
    z1 = z1 * PRIME_Z;
    let x0 = x1 - PRIME_X;
    let y0 = y1 - PRIME_Y;
    let z0 = z1 - PRIME_Z;
    let x2 = x1 + PRIME_X;
    let y2 = y1 + PRIME_Y;
    let z2 = z1 + PRIME_Z;
    let x3 = x1 + PRIME_X2;
    let y3 = y1 + PRIME_Y2;
    let z3 = z1 + PRIME_Z2;
    return _cubic_lerp(
        _value_cubic3_plane(seed, x0, x1, x2, x3, y0, y1, y2, y3, z0, xs, ys),
        _value_cubic3_plane(seed, x0, x1, x2, x3, y0, y1, y2, y3, z1, xs, ys),
        _value_cubic3_plane(seed, x0, x1, x2, x3, y0, y1, y2, y3, z2, xs, ys),
        _value_cubic3_plane(seed, x0, x1, x2, x3, y0, y1, y2, y3, z3, xs, ys),
        zs,
    ) * (1.0 / (1.5 * 1.5 * 1.5));
}

// -------------------------------------------------------------------------
// cellular (Worley) noise

// scalar.py: _cellular_finish (881)
fn _cellular_finish(dist_func : i32, ret_type : i32, distance0_in : f32, distance1_in : f32, closest_hash : i32) -> f32 {
    var distance0 = distance0_in;
    var distance1 = distance1_in;
    if (dist_func == CELL_DIST_EUCLIDEAN && ret_type >= CELL_RET_DISTANCE) {
        distance0 = sqrt(distance0);
        if (ret_type >= CELL_RET_DISTANCE2) {
            distance1 = sqrt(distance1);
        }
    }
    if (ret_type == CELL_RET_CELL_VALUE) {
        return f32(closest_hash) * (1.0 / 2147483648.0);
    }
    if (ret_type == CELL_RET_DISTANCE) {
        return distance0 - 1.0;
    }
    if (ret_type == CELL_RET_DISTANCE2) {
        return distance1 - 1.0;
    }
    if (ret_type == CELL_RET_DISTANCE2_ADD) {
        return (distance1 + distance0) * 0.5 - 1.0;
    }
    if (ret_type == CELL_RET_DISTANCE2_SUB) {
        return distance1 - distance0 - 1.0;
    }
    if (ret_type == CELL_RET_DISTANCE2_MUL) {
        return distance1 * distance0 * 0.5 - 1.0;
    }
    if (ret_type == CELL_RET_DISTANCE2_DIV) {
        return distance0 / distance1 - 1.0;
    }
    return 0.0;
}

// scalar.py: _lookup_single2 (904). The noise a NoiseLookup cell samples, any type but cellular: it calls the leaf
// noises directly, never noise_single2, so the call graph has no cycle.
fn _lookup_single2(noise_type : i32, seed : i32, x_in : f32, y_in : f32) -> f32 {
    let s = _transform2(noise_type, x_in, y_in);
    let x = s.x;
    let y = s.y;
    if (noise_type == NOISE_OPEN_SIMPLEX2) {
        return simplex2(seed, x, y);
    }
    if (noise_type == NOISE_OPEN_SIMPLEX2S) {
        return simplex2s(seed, x, y);
    }
    if (noise_type == NOISE_PERLIN) {
        return perlin2(seed, x, y);
    }
    if (noise_type == NOISE_VALUE_CUBIC) {
        return value_cubic2(seed, x, y);
    }
    if (noise_type == NOISE_VALUE) {
        return value2(seed, x, y);
    }
    if (noise_type == NOISE_WHITE_NOISE) {
        return white_noise2(seed, x, y);
    }
    if (noise_type == NOISE_SIMPLEX_CLASSIC) {
        return simplex_classic2(seed, x, y);
    }
    return 0.0;
}

// scalar.py: _lookup_single3 (925). As _lookup_single2; the simplex family is rotated by TRANSFORM_DEFAULT_OS2.
fn _lookup_single3(noise_type : i32, seed : i32, x_in : f32, y_in : f32, z_in : f32) -> f32 {
    var x = x_in;
    var y = y_in;
    var z = z_in;
    if (noise_type == NOISE_OPEN_SIMPLEX2 || noise_type == NOISE_OPEN_SIMPLEX2S) {
        let r = _transform3(TRANSFORM_DEFAULT_OS2, x, y, z);
        x = r.x;
        y = r.y;
        z = r.z;
    }
    if (noise_type == NOISE_OPEN_SIMPLEX2) {
        return opensimplex2_3(seed, x, y, z);
    }
    if (noise_type == NOISE_OPEN_SIMPLEX2S) {
        return opensimplex2s_3(seed, x, y, z);
    }
    if (noise_type == NOISE_PERLIN) {
        return perlin3(seed, x, y, z);
    }
    if (noise_type == NOISE_VALUE_CUBIC) {
        return value_cubic3(seed, x, y, z);
    }
    if (noise_type == NOISE_VALUE) {
        return value3(seed, x, y, z);
    }
    if (noise_type == NOISE_WHITE_NOISE) {
        return white_noise3(seed, x, y, z);
    }
    if (noise_type == NOISE_SIMPLEX_CLASSIC) {
        return simplex_classic3(seed, x, y, z);
    }
    return 0.0;
}

// scalar.py: _cellular2_scan's tuple (946)
struct Cellular2Scan {
    distance0 : f32,
    distance1 : f32,
    closest_hash : i32,
    cell_x : f32,
    cell_y : f32,
};

// scalar.py: _cellular2_scan (946). The 3 x 3 scan: the two nearest distances, the nearest cell's hash and its jittered
// point.
fn _cellular2_scan(seed : i32, x : f32, y : f32, dist_func : i32, jitter_mod : f32) -> Cellular2Scan {
    let xr = _fast_round(x);
    let yr = _fast_round(y);
    var distance0 = 1e10;
    var distance1 = 1e10;
    var closest_hash = 0;
    var cell_x = 0.0;
    var cell_y = 0.0;
    let jitter = 0.43701595 * jitter_mod;
    var x_primed = (xr - 1) * PRIME_X;
    let y_primed_base = (yr - 1) * PRIME_Y;
    for (var xi = xr - 1; xi < xr + 2; xi++) {
        var y_primed = y_primed_base;
        for (var yi = yr - 1; yi < yr + 2; yi++) {
            let h = _hash2(seed, x_primed, y_primed);
            let idx = h & (255 << 1);
            let vec_x = (f32(xi) - x) + rand_vecs_2d(idx) * jitter;
            let vec_y = (f32(yi) - y) + rand_vecs_2d(idx | 1) * jitter;
            var new_distance : f32;
            if (dist_func == CELL_DIST_MANHATTAN) {
                new_distance = abs(vec_x) + abs(vec_y);
            } else if (dist_func == CELL_DIST_HYBRID) {
                new_distance = (abs(vec_x) + abs(vec_y)) + (vec_x * vec_x + vec_y * vec_y);
            } else if (dist_func == CELL_DIST_NATURAL) {
                new_distance = (abs(vec_x) + abs(vec_y)) * (vec_x * vec_x + vec_y * vec_y);
            } else {
                new_distance = vec_x * vec_x + vec_y * vec_y;
            }
            distance1 = max(min(distance1, new_distance), distance0);
            if (new_distance < distance0) {
                distance0 = new_distance;
                closest_hash = h;
                cell_x = f32(xi) + rand_vecs_2d(idx) * jitter;
                cell_y = f32(yi) + rand_vecs_2d(idx | 1) * jitter;
            }
            y_primed = y_primed + PRIME_Y;
        }
        x_primed = x_primed + PRIME_X;
    }
    return Cellular2Scan(distance0, distance1, closest_hash, cell_x, cell_y);
}

// scalar.py: cellular2 (985)
fn cellular2(
    seed : i32, x : f32, y : f32, dist_func : i32, ret_type : i32, jitter_mod : f32, lookup_type : i32,
    lookup_freq : f32,
) -> f32 {
    if (ret_type == CELL_RET_DISTANCE2_CAVE) {
        // FastNoiseSIMD: the lesser of two Distance2Div fields, the second half a cell over and one seed on
        let a = _cellular2_scan(seed, x, y, dist_func, jitter_mod);
        let c0 = _cellular_finish(dist_func, CELL_RET_DISTANCE2_DIV, a.distance0, a.distance1, a.closest_hash);
        let b = _cellular2_scan(seed + 1, x + 0.5, y + 0.5, dist_func, jitter_mod);
        let c1 = _cellular_finish(dist_func, CELL_RET_DISTANCE2_DIV, b.distance0, b.distance1, b.closest_hash);
        return min(c0, c1);
    }
    let s = _cellular2_scan(seed, x, y, dist_func, jitter_mod);
    if (ret_type == CELL_RET_NOISE_LOOKUP) {
        // FastNoiseSIMD: the lookup noise at the nearest cell point, at its own frequency
        return _lookup_single2(lookup_type, seed, s.cell_x * lookup_freq, s.cell_y * lookup_freq);
    }
    return _cellular_finish(dist_func, ret_type, s.distance0, s.distance1, s.closest_hash);
}

// scalar.py: _cellular3_scan's tuple (1001)
struct Cellular3Scan {
    distance0 : f32,
    distance1 : f32,
    closest_hash : i32,
    cell_x : f32,
    cell_y : f32,
    cell_z : f32,
};

// scalar.py: _cellular3_scan (1001)
fn _cellular3_scan(seed : i32, x : f32, y : f32, z : f32, dist_func : i32, jitter_mod : f32) -> Cellular3Scan {
    let xr = _fast_round(x);
    let yr = _fast_round(y);
    let zr = _fast_round(z);
    var distance0 = 1e10;
    var distance1 = 1e10;
    var closest_hash = 0;
    var cell_x = 0.0;
    var cell_y = 0.0;
    var cell_z = 0.0;
    let jitter = 0.39614353 * jitter_mod;
    var x_primed = (xr - 1) * PRIME_X;
    let y_primed_base = (yr - 1) * PRIME_Y;
    let z_primed_base = (zr - 1) * PRIME_Z;
    for (var xi = xr - 1; xi < xr + 2; xi++) {
        var y_primed = y_primed_base;
        for (var yi = yr - 1; yi < yr + 2; yi++) {
            var z_primed = z_primed_base;
            for (var zi = zr - 1; zi < zr + 2; zi++) {
                let h = _hash3(seed, x_primed, y_primed, z_primed);
                let idx = h & (255 << 2);
                let vec_x = (f32(xi) - x) + rand_vecs_3d(idx) * jitter;
                let vec_y = (f32(yi) - y) + rand_vecs_3d(idx | 1) * jitter;
                let vec_z = (f32(zi) - z) + rand_vecs_3d(idx | 2) * jitter;
                var new_distance : f32;
                if (dist_func == CELL_DIST_MANHATTAN) {
                    new_distance = abs(vec_x) + abs(vec_y) + abs(vec_z);
                } else if (dist_func == CELL_DIST_HYBRID) {
                    new_distance = (abs(vec_x) + abs(vec_y) + abs(vec_z)) + (
                        vec_x * vec_x + vec_y * vec_y + vec_z * vec_z
                    );
                } else if (dist_func == CELL_DIST_NATURAL) {
                    new_distance = (abs(vec_x) + abs(vec_y) + abs(vec_z)) * (
                        vec_x * vec_x + vec_y * vec_y + vec_z * vec_z
                    );
                } else {
                    new_distance = vec_x * vec_x + vec_y * vec_y + vec_z * vec_z;
                }
                distance1 = max(min(distance1, new_distance), distance0);
                if (new_distance < distance0) {
                    distance0 = new_distance;
                    closest_hash = h;
                    cell_x = f32(xi) + rand_vecs_3d(idx) * jitter;
                    cell_y = f32(yi) + rand_vecs_3d(idx | 1) * jitter;
                    cell_z = f32(zi) + rand_vecs_3d(idx | 2) * jitter;
                }
                z_primed = z_primed + PRIME_Z;
            }
            y_primed = y_primed + PRIME_Y;
        }
        x_primed = x_primed + PRIME_X;
    }
    return Cellular3Scan(distance0, distance1, closest_hash, cell_x, cell_y, cell_z);
}

// scalar.py: cellular3 (1051)
fn cellular3(
    seed : i32, x : f32, y : f32, z : f32, dist_func : i32, ret_type : i32, jitter_mod : f32, lookup_type : i32,
    lookup_freq : f32,
) -> f32 {
    if (ret_type == CELL_RET_DISTANCE2_CAVE) {
        let a = _cellular3_scan(seed, x, y, z, dist_func, jitter_mod);
        let c0 = _cellular_finish(dist_func, CELL_RET_DISTANCE2_DIV, a.distance0, a.distance1, a.closest_hash);
        let b = _cellular3_scan(seed + 1, x + 0.5, y + 0.5, z + 0.5, dist_func, jitter_mod);
        let c1 = _cellular_finish(dist_func, CELL_RET_DISTANCE2_DIV, b.distance0, b.distance1, b.closest_hash);
        return min(c0, c1);
    }
    let s = _cellular3_scan(seed, x, y, z, dist_func, jitter_mod);
    if (ret_type == CELL_RET_NOISE_LOOKUP) {
        return _lookup_single3(
            lookup_type, seed, s.cell_x * lookup_freq, s.cell_y * lookup_freq, s.cell_z * lookup_freq,
        );
    }
    return _cellular_finish(dist_func, ret_type, s.distance0, s.distance1, s.closest_hash);
}

// -------------------------------------------------------------------------
// white noise: FastNoiseSIMD's WhiteNoiseSingle, a hash of the scaled coordinates' float32 bits

// scalar.py: _fns_val_coord (1067)
fn _fns_val_coord(seed : i32, xp : i32, yp : i32, zp : i32) -> f32 {
    var h = seed ^ xp ^ yp ^ zp;
    h = h * h * FNS_HASH_MUL * h;
    return f32(h) * FNS_HASH_TO_FLOAT;
}

// scalar.py: _fns_bits (1074). The int32 bit pattern of v, mixed as the reference mixes it: b ^ (b >> 16), arithmetic.
fn _fns_bits(v : f32) -> i32 {
    let b = bitcast<i32>(v);
    return b ^ (b >> 16u);
}

// scalar.py: white_noise3 (1081). x, y, z are the frequency-scaled coordinates; their float32 bits are hashed.
fn white_noise3(seed : i32, x : f32, y : f32, z : f32) -> f32 {
    return _fns_val_coord(
        seed, _fns_bits(x) * FNS_PRIME_X, _fns_bits(y) * FNS_PRIME_Y, _fns_bits(z) * FNS_PRIME_Z,
    );
}

// scalar.py: white_noise2 (1092). The 3D function at z = 0, whose bits are zero.
fn white_noise2(seed : i32, x : f32, y : f32) -> f32 {
    return _fns_val_coord(seed, _fns_bits(x) * FNS_PRIME_X, _fns_bits(y) * FNS_PRIME_Y, 0);
}

// -------------------------------------------------------------------------
// classic simplex: FastNoiseSIMD's SimplexSingle with its hash and gradient selection

// scalar.py: _FNS_F3, _FNS_G3, _FNS_G33 (1100-1102)
const FNS_F3 = 1.0 / 3.0;
const FNS_G3 = 1.0 / 6.0;
const FNS_G33 = (3.0 / 6.0) - 1.0;

// scalar.py: _fns_hash (1106)
fn _fns_hash(seed : i32, xp : i32, yp : i32, zp : i32) -> i32 {
    var h = seed ^ xp ^ yp ^ zp;
    h = h * h * FNS_HASH_MUL * h;
    return (h >> 13u) ^ h;
}

// scalar.py: _fns_grad_coord (1113). One of twelve edge vectors, as FastNoiseSIMD's SSE/AVX2 GradCoord selects it.
fn _fns_grad_coord(seed : i32, xp : i32, yp : i32, zp : i32, x : f32, y : f32, z : f32) -> f32 {
    let h = _fns_hash(seed, xp, yp, zp);
    let a = h & 13;
    var u = select(y, x, a < 8);
    var v = select(select(z, x, a == 12), y, a < 2);
    if ((h & 1) != 0) {
        u = -u;
    }
    if ((h & 2) != 0) {
        v = -v;
    }
    return u + v;
}

// scalar.py: simplex_classic3 (1127)
fn simplex_classic3(seed : i32, x : f32, y : f32, z : f32) -> f32 {
    let f = FNS_F3 * ((x + y) + z);
    let xf = floor(x + f);
    let yf = floor(y + f);
    let zf = floor(z + f);
    let i = i32(xf) * FNS_PRIME_X;
    let j = i32(yf) * FNS_PRIME_Y;
    let k = i32(zf) * FNS_PRIME_Z;
    let g = FNS_G3 * ((xf + yf) + zf);
    let x0 = x - (xf - g);
    let y0 = y - (yf - g);
    let z0 = z - (zf - g);

    let x_ge_y = x0 >= y0;
    let y_ge_z = y0 >= z0;
    let x_ge_z = x0 >= z0;
    let i1 = x_ge_y && x_ge_z;
    let j1 = !x_ge_y && y_ge_z;
    let k1 = !x_ge_z && !y_ge_z;
    let i2 = x_ge_y || x_ge_z;
    let j2 = !x_ge_y || y_ge_z;
    let k2 = !(x_ge_z && y_ge_z);

    let x1 = select(x0, x0 - 1.0, i1) + FNS_G3;
    let y1 = select(y0, y0 - 1.0, j1) + FNS_G3;
    let z1 = select(z0, z0 - 1.0, k1) + FNS_G3;
    let x2 = select(x0, x0 - 1.0, i2) + FNS_F3;
    let y2 = select(y0, y0 - 1.0, j2) + FNS_F3;
    let z2 = select(z0, z0 - 1.0, k2) + FNS_F3;
    let x3 = x0 + FNS_G33;
    let y3 = y0 + FNS_G33;
    let z3 = z0 + FNS_G33;

    var t0 = ((0.6 - x0 * x0) - y0 * y0) - z0 * z0;
    var t1 = ((0.6 - x1 * x1) - y1 * y1) - z1 * z1;
    var t2 = ((0.6 - x2 * x2) - y2 * y2) - z2 * z2;
    var t3 = ((0.6 - x3 * x3) - y3 * y3) - z3 * z3;

    var total = 0.0;
    if (t3 >= 0.0) {
        t3 = t3 * t3;
        total += (t3 * t3) * _fns_grad_coord(seed, i + FNS_PRIME_X, j + FNS_PRIME_Y, k + FNS_PRIME_Z, x3, y3, z3);
    }
    if (t2 >= 0.0) {
        t2 = t2 * t2;
        total += (t2 * t2) * _fns_grad_coord(
            seed, select(i, i + FNS_PRIME_X, i2), select(j, j + FNS_PRIME_Y, j2), select(k, k + FNS_PRIME_Z, k2),
            x2, y2, z2,
        );
    }
    if (t1 >= 0.0) {
        t1 = t1 * t1;
        total += (t1 * t1) * _fns_grad_coord(
            seed, select(i, i + FNS_PRIME_X, i1), select(j, j + FNS_PRIME_Y, j1), select(k, k + FNS_PRIME_Z, k1),
            x1, y1, z1,
        );
    }
    if (t0 >= 0.0) {
        t0 = t0 * t0;
        total += (t0 * t0) * _fns_grad_coord(seed, i, j, k, x0, y0, z0);
    }
    return 32.0 * total;
}

// scalar.py: simplex_classic2 (1200). The retired library was 3D only; its 2D use was z = 0.
fn simplex_classic2(seed : i32, x : f32, y : f32) -> f32 {
    return simplex_classic3(seed, x, y, 0.0);
}

// -------------------------------------------------------------------------
// domain warp: FastNoiseLite's DomainWarp, applied to the raw coordinates before the noise. The CPU computes it in
// float64 on the raw coordinate; here it is f32, so its drift follows the coordinate, not the coordinate times
// frequency.

// scalar.py: _grad_out2 (1208)
fn _grad_out2(seed : i32, xp : i32, yp : i32) -> vec2<f32> {
    let h = _hash2(seed, xp, yp) & (255 << 1u);
    return vec2<f32>(rand_vecs_2d(h), rand_vecs_2d(h | 1));
}

// scalar.py: _grad_out3 (1214)
fn _grad_out3(seed : i32, xp : i32, yp : i32, zp : i32) -> vec3<f32> {
    let h = _hash3(seed, xp, yp, zp) & (255 << 2u);
    return vec3<f32>(rand_vecs_3d(h), rand_vecs_3d(h | 1), rand_vecs_3d(h | 2));
}

// scalar.py: _grad_dual2 (1220)
fn _grad_dual2(seed : i32, xp : i32, yp : i32, xd : f32, yd : f32) -> vec2<f32> {
    let h = _hash2(seed, xp, yp);
    let i1 = h & (127 << 1u);
    let i2 = (h >> 7u) & (255 << 1u);
    let v = xd * gradients_2d(i1) + yd * gradients_2d(i1 | 1);
    return vec2<f32>(v * rand_vecs_2d(i2), v * rand_vecs_2d(i2 | 1));
}

// scalar.py: _grad_dual3 (1229)
fn _grad_dual3(seed : i32, xp : i32, yp : i32, zp : i32, xd : f32, yd : f32, zd : f32) -> vec3<f32> {
    let h = _hash3(seed, xp, yp, zp);
    let i1 = h & (63 << 2u);
    let i2 = (h >> 6u) & (255 << 2u);
    let v = xd * gradients_3d(i1) + yd * gradients_3d(i1 | 1) + zd * gradients_3d(i1 | 2);
    return vec3<f32>(v * rand_vecs_3d(i2), v * rand_vecs_3d(i2 | 1), v * rand_vecs_3d(i2 | 2));
}

// scalar.py: _rv2 (1238). The CPU promotes the float32 table value to float64 before its lerp; here it stays f32.
fn _rv2(i : i32) -> f32 {
    return rand_vecs_2d(i);
}

// scalar.py: _rv3 (1245)
fn _rv3(i : i32) -> f32 {
    return rand_vecs_3d(i);
}

// scalar.py: _warp_basic_grid2 (1250)
fn _warp_basic_grid2(seed : i32, amp : f32, freq : f32, x : f32, y : f32) -> vec2<f32> {
    let xf = x * freq;
    let yf = y * freq;
    var x0 = _fast_floor(xf);
    var y0 = _fast_floor(yf);
    let xs = _interp_hermite(xf - f32(x0));
    let ys = _interp_hermite(yf - f32(y0));
    x0 = x0 * PRIME_X;
    y0 = y0 * PRIME_Y;
    let x1 = x0 + PRIME_X;
    let y1 = y0 + PRIME_Y;

    var h0 = _hash2(seed, x0, y0) & (255 << 1u);
    var h1 = _hash2(seed, x1, y0) & (255 << 1u);
    let lx0x = _lerp(_rv2(h0), _rv2(h1), xs);
    let ly0x = _lerp(_rv2(h0 | 1), _rv2(h1 | 1), xs);
    h0 = _hash2(seed, x0, y1) & (255 << 1u);
    h1 = _hash2(seed, x1, y1) & (255 << 1u);
    let lx1x = _lerp(_rv2(h0), _rv2(h1), xs);
    let ly1x = _lerp(_rv2(h0 | 1), _rv2(h1 | 1), xs);
    return vec2<f32>(_lerp(lx0x, lx1x, ys) * amp, _lerp(ly0x, ly1x, ys) * amp);
}

// scalar.py: _warp_basic_grid3 (1274)
fn _warp_basic_grid3(seed : i32, amp : f32, freq : f32, x : f32, y : f32, z : f32) -> vec3<f32> {
    let xf = x * freq;
    let yf = y * freq;
    let zf = z * freq;
    var x0 = _fast_floor(xf);
    var y0 = _fast_floor(yf);
    var z0 = _fast_floor(zf);
    let xs = _interp_hermite(xf - f32(x0));
    let ys = _interp_hermite(yf - f32(y0));
    let zs = _interp_hermite(zf - f32(z0));
    x0 = x0 * PRIME_X;
    y0 = y0 * PRIME_Y;
    z0 = z0 * PRIME_Z;
    let x1 = x0 + PRIME_X;
    let y1 = y0 + PRIME_Y;
    let z1 = z0 + PRIME_Z;

    var h0 = _hash3(seed, x0, y0, z0) & (255 << 2u);
    var h1 = _hash3(seed, x1, y0, z0) & (255 << 2u);
    var lx0x = _lerp(_rv3(h0), _rv3(h1), xs);
    var ly0x = _lerp(_rv3(h0 | 1), _rv3(h1 | 1), xs);
    var lz0x = _lerp(_rv3(h0 | 2), _rv3(h1 | 2), xs);
    h0 = _hash3(seed, x0, y1, z0) & (255 << 2u);
    h1 = _hash3(seed, x1, y1, z0) & (255 << 2u);
    var lx1x = _lerp(_rv3(h0), _rv3(h1), xs);
    var ly1x = _lerp(_rv3(h0 | 1), _rv3(h1 | 1), xs);
    var lz1x = _lerp(_rv3(h0 | 2), _rv3(h1 | 2), xs);
    let lx0y = _lerp(lx0x, lx1x, ys);
    let ly0y = _lerp(ly0x, ly1x, ys);
    let lz0y = _lerp(lz0x, lz1x, ys);

    h0 = _hash3(seed, x0, y0, z1) & (255 << 2u);
    h1 = _hash3(seed, x1, y0, z1) & (255 << 2u);
    lx0x = _lerp(_rv3(h0), _rv3(h1), xs);
    ly0x = _lerp(_rv3(h0 | 1), _rv3(h1 | 1), xs);
    lz0x = _lerp(_rv3(h0 | 2), _rv3(h1 | 2), xs);
    h0 = _hash3(seed, x0, y1, z1) & (255 << 2u);
    h1 = _hash3(seed, x1, y1, z1) & (255 << 2u);
    lx1x = _lerp(_rv3(h0), _rv3(h1), xs);
    ly1x = _lerp(_rv3(h0 | 1), _rv3(h1 | 1), xs);
    lz1x = _lerp(_rv3(h0 | 2), _rv3(h1 | 2), xs);
    return vec3<f32>(
        _lerp(lx0y, _lerp(lx0x, lx1x, ys), zs) * amp,
        _lerp(ly0y, _lerp(ly0x, ly1x, ys), zs) * amp,
        _lerp(lz0y, _lerp(lz0x, lz1x, ys), zs) * amp,
    );
}

// scalar.py: _warp_simplex_grad2 (1323). OpenSimplex2 gradient warp, 2D. x, y are skewed already; grad_only is the
// Reduced variant.
fn _warp_simplex_grad2(seed : i32, amp : f32, freq : f32, x_in : f32, y_in : f32, grad_only : bool) -> vec2<f32> {
    let x = x_in * freq;
    let y = y_in * freq;
    var i = _fast_floor(x);
    var j = _fast_floor(y);
    let xi = x - f32(i);
    let yi = y - f32(j);
    let t = (xi + yi) * G2;
    let x0 = xi - t;
    let y0 = yi - t;
    i = i * PRIME_X;
    j = j * PRIME_Y;

    var v = vec2<f32>(0.0, 0.0);
    let a = 0.5 - x0 * x0 - y0 * y0;
    if (a > 0.0) {
        let aaaa = (a * a) * (a * a);
        var o : vec2<f32>;
        if (grad_only) {
            o = _grad_out2(seed, i, j);
        } else {
            o = _grad_dual2(seed, i, j, x0, y0);
        }
        v += aaaa * o;
    }

    let c = (2.0 * (1.0 - 2.0 * G2) * (1.0 / G2 - 2.0)) * t + ((-2.0 * (1.0 - 2.0 * G2) * (1.0 - 2.0 * G2)) + a);
    if (c > 0.0) {
        let x2 = x0 + (2.0 * G2 - 1.0);
        let y2 = y0 + (2.0 * G2 - 1.0);
        let cccc = (c * c) * (c * c);
        var o : vec2<f32>;
        if (grad_only) {
            o = _grad_out2(seed, i + PRIME_X, j + PRIME_Y);
        } else {
            o = _grad_dual2(seed, i + PRIME_X, j + PRIME_Y, x2, y2);
        }
        v += cccc * o;
    }

    if (y0 > x0) {
        let x1 = x0 + G2;
        let y1 = y0 + (G2 - 1.0);
        let b = 0.5 - x1 * x1 - y1 * y1;
        if (b > 0.0) {
            let bbbb = (b * b) * (b * b);
            var o : vec2<f32>;
            if (grad_only) {
                o = _grad_out2(seed, i, j + PRIME_Y);
            } else {
                o = _grad_dual2(seed, i, j + PRIME_Y, x1, y1);
            }
            v += bbbb * o;
        }
    } else {
        let x1 = x0 + (G2 - 1.0);
        let y1 = y0 + G2;
        let b = 0.5 - x1 * x1 - y1 * y1;
        if (b > 0.0) {
            let bbbb = (b * b) * (b * b);
            var o : vec2<f32>;
            if (grad_only) {
                o = _grad_out2(seed, i + PRIME_X, j);
            } else {
                o = _grad_dual2(seed, i + PRIME_X, j, x1, y1);
            }
            v += bbbb * o;
        }
    }

    return v * amp;
}

// scalar.py: _warp_simplex_grad3 (1390). OpenSimplex2 gradient warp, 3D. x, y, z are rotated already; grad_only is the
// Reduced variant. Its second lattice's seed is seed + 1293373, where opensimplex2_3's is ~seed, as on the CPU.
fn _warp_simplex_grad3(
    seed_in : i32, amp : f32, freq : f32, x_in : f32, y_in : f32, z_in : f32, grad_only : bool,
) -> vec3<f32> {
    var seed = seed_in;
    let x = x_in * freq;
    let y = y_in * freq;
    let z = z_in * freq;
    var i = _fast_round(x);
    var j = _fast_round(y);
    var k = _fast_round(z);
    var x0 = x - f32(i);
    var y0 = y - f32(j);
    var z0 = z - f32(k);

    var x_nsign = i32(-x0 - 1.0) | 1;
    var y_nsign = i32(-y0 - 1.0) | 1;
    var z_nsign = i32(-z0 - 1.0) | 1;

    var ax0 = f32(x_nsign) * -x0;
    var ay0 = f32(y_nsign) * -y0;
    var az0 = f32(z_nsign) * -z0;

    i = i * PRIME_X;
    j = j * PRIME_Y;
    k = k * PRIME_Z;

    var v = vec3<f32>(0.0, 0.0, 0.0);
    var a = (0.6 - x0 * x0) - (y0 * y0 + z0 * z0);
    for (var step = 0; step < 2; step++) {
        if (a > 0.0) {
            let aaaa = (a * a) * (a * a);
            var o : vec3<f32>;
            if (grad_only) {
                o = _grad_out3(seed, i, j, k);
            } else {
                o = _grad_dual3(seed, i, j, k, x0, y0, z0);
            }
            v += aaaa * o;
        }

        var b = a + 1.0;
        var i1 = i;
        var j1 = j;
        var k1 = k;
        var x1 = x0;
        var y1 = y0;
        var z1 = z0;
        if (ax0 >= ay0 && ax0 >= az0) {
            x1 += f32(x_nsign);
            b -= f32(x_nsign) * 2.0 * x1;
            i1 = i1 - x_nsign * PRIME_X;
        } else if (ay0 > ax0 && ay0 >= az0) {
            y1 += f32(y_nsign);
            b -= f32(y_nsign) * 2.0 * y1;
            j1 = j1 - y_nsign * PRIME_Y;
        } else {
            z1 += f32(z_nsign);
            b -= f32(z_nsign) * 2.0 * z1;
            k1 = k1 - z_nsign * PRIME_Z;
        }

        if (b > 0.0) {
            let bbbb = (b * b) * (b * b);
            var o : vec3<f32>;
            if (grad_only) {
                o = _grad_out3(seed, i1, j1, k1);
            } else {
                o = _grad_dual3(seed, i1, j1, k1, x1, y1, z1);
            }
            v += bbbb * o;
        }

        if (step == 1) {
            break;
        }

        ax0 = 0.5 - ax0;
        ay0 = 0.5 - ay0;
        az0 = 0.5 - az0;
        x0 = f32(x_nsign) * ax0;
        y0 = f32(y_nsign) * ay0;
        z0 = f32(z_nsign) * az0;
        a += (0.75 - ax0) - (ay0 + az0);
        i = i + ((x_nsign >> 1u) & PRIME_X);
        j = j + ((y_nsign >> 1u) & PRIME_Y);
        k = k + ((z_nsign >> 1u) & PRIME_Z);
        x_nsign = -x_nsign;
        y_nsign = -y_nsign;
        z_nsign = -z_nsign;
        seed = seed + 1293373;
    }

    return v * amp;
}

// scalar.py: _warp_transform2 (1481). The warp's own skew: by warp type, not noise type.
fn _warp_transform2(warp_type : i32, x : f32, y : f32) -> vec2<f32> {
    if (warp_type == WARP_OPEN_SIMPLEX2 || warp_type == WARP_OPEN_SIMPLEX2_REDUCED) {
        let t = (x + y) * F2;
        return vec2<f32>(x + t, y + t);
    }
    return vec2<f32>(x, y);
}

// scalar.py: _do_warp2 (1489)
fn _do_warp2(warp_type : i32, seed : i32, amp : f32, freq : f32, x : f32, y : f32) -> vec2<f32> {
    if (warp_type == WARP_OPEN_SIMPLEX2) {
        return _warp_simplex_grad2(seed, amp * 38.283687591552734375, freq, x, y, false);
    }
    if (warp_type == WARP_OPEN_SIMPLEX2_REDUCED) {
        return _warp_simplex_grad2(seed, amp * 16.0, freq, x, y, true);
    }
    return _warp_basic_grid2(seed, amp, freq, x, y);
}

// scalar.py: _do_warp3 (1498)
fn _do_warp3(warp_type : i32, seed : i32, amp : f32, freq : f32, x : f32, y : f32, z : f32) -> vec3<f32> {
    if (warp_type == WARP_OPEN_SIMPLEX2) {
        return _warp_simplex_grad3(seed, amp * 32.69428253173828125, freq, x, y, z, false);
    }
    if (warp_type == WARP_OPEN_SIMPLEX2_REDUCED) {
        return _warp_simplex_grad3(seed, amp * 7.71604938271605, freq, x, y, z, true);
    }
    return _warp_basic_grid3(seed, amp, freq, x, y, z);
}

// scalar.py: warp2 (1507). The reference's DomainWarp(x, y): x, y raw (unscaled) coordinates, warped. amp is the warp
// amplitude already scaled by the fractal bounding; freq the base frequency. A single warp uses the first octave's
// seed, amplitude and frequency; progressive re-transforms the running warped point each octave; independent
// transforms the original once.
// One shape differs from the CPU's: the single warp is the progressive loop run once (the same arithmetic: transform,
// one _do_warp2 at the first octave's seed, amplitude and frequency, add), not a branch of its own. WARP (D3D12,
// 10.0.26100.9818) computed the CPU-shaped single branch of warp3 wrongly inside sample_one_3d, and differently from
// run to run, while the same warp3 was right through warp_points_3d (Task 12); warp2 takes the same shape so the two
// stay twins.
fn warp2(
    warp_type : i32, warp_fractal : i32, seed_in : i32, amp_in : f32, freq_in : f32, octaves : i32, lacunarity : f32,
    gain : f32, x_in : f32, y_in : f32,
) -> vec2<f32> {
    var p = vec2<f32>(x_in, y_in);
    if (warp_type == WARP_NONE) {  // no warp configured: the raw point, not the BasicGrid fallback
        return p;
    }
    var seed = seed_in;
    var amp = amp_in;
    var freq = freq_in;
    if (warp_fractal == WARP_SINGLE || warp_fractal == WARP_PROGRESSIVE) {
        let count = select(octaves, 1, warp_fractal == WARP_SINGLE);
        for (var octave = 0; octave < count; octave++) {
            let s = _warp_transform2(warp_type, p.x, p.y);
            p += _do_warp2(warp_type, seed, amp, freq, s.x, s.y);
            seed += 1;
            amp *= gain;
            freq *= lacunarity;
        }
        return p;
    }
    let s = _warp_transform2(warp_type, p.x, p.y);
    for (var octave = 0; octave < octaves; octave++) {
        p += _do_warp2(warp_type, seed, amp, freq, s.x, s.y);
        seed += 1;
        amp *= gain;
        freq *= lacunarity;
    }
    return p;
}

// scalar.py: warp3 (1543). The reference's DomainWarp(x, y, z); warp_transform is the warp's own Transform3D. The
// single warp is the progressive loop run once, as in warp2.
fn warp3(
    warp_type : i32, warp_fractal : i32, warp_transform : i32, seed_in : i32, amp_in : f32, freq_in : f32,
    octaves : i32, lacunarity : f32, gain : f32, x_in : f32, y_in : f32, z_in : f32,
) -> vec3<f32> {
    var p = vec3<f32>(x_in, y_in, z_in);
    if (warp_type == WARP_NONE) {  // no warp configured: the raw point, not the BasicGrid fallback
        return p;
    }
    var seed = seed_in;
    var amp = amp_in;
    var freq = freq_in;
    if (warp_fractal == WARP_SINGLE || warp_fractal == WARP_PROGRESSIVE) {
        let count = select(octaves, 1, warp_fractal == WARP_SINGLE);
        for (var octave = 0; octave < count; octave++) {
            let s = _transform3(warp_transform, p.x, p.y, p.z);
            p += _do_warp3(warp_type, seed, amp, freq, s.x, s.y, s.z);
            seed += 1;
            amp *= gain;
            freq *= lacunarity;
        }
        return p;
    }
    let s = _transform3(warp_transform, p.x, p.y, p.z);
    for (var octave = 0; octave < octaves; octave++) {
        p += _do_warp3(warp_type, seed, amp, freq, s.x, s.y, s.z);
        seed += 1;
        amp *= gain;
        freq *= lacunarity;
    }
    return p;
}

// -------------------------------------------------------------------------
// gradient perturb: FastNoiseSIMD's GradientPerturbSingle and its PERTURB_SWITCH, on the frequency-scaled point, with
// its own frequency and octaves; the normalise modes rescale the point.

// scalar.py: _fns_grad_vec (1578). HashHB (no shift-xor), ten bits per axis, centred: an unnormalised random vector.
fn _fns_grad_vec(seed : i32, xp : i32, yp : i32, zp : i32) -> vec3<f32> {
    var h = seed ^ xp ^ yp ^ zp;
    h = h * h * FNS_HASH_MUL * h;
    return vec3<f32>(f32(h & 1023) - 511.5, f32((h >> 10u) & 1023) - 511.5, f32((h >> 20u) & 1023) - 511.5);
}

// scalar.py: _perturb_single3 (1586)
fn _perturb_single3(seed : i32, amp : f32, freq : f32, x : f32, y : f32, z : f32) -> vec3<f32> {
    let xf = x * freq;
    let yf = y * freq;
    let zf = z * freq;
    let xfl = floor(xf);
    let yfl = floor(yf);
    let zfl = floor(zf);
    let x0 = i32(xfl) * FNS_PRIME_X;
    let y0 = i32(yfl) * FNS_PRIME_Y;
    let z0 = i32(zfl) * FNS_PRIME_Z;
    let x1 = x0 + FNS_PRIME_X;
    let y1 = y0 + FNS_PRIME_Y;
    let z1 = z0 + FNS_PRIME_Z;
    let xs = _interp_quintic(xf - xfl);
    let ys = _interp_quintic(yf - yfl);
    let zs = _interp_quintic(zf - zfl);

    let v000 = _fns_grad_vec(seed, x0, y0, z0);
    let v001 = _fns_grad_vec(seed, x0, y0, z1);
    let v010 = _fns_grad_vec(seed, x0, y1, z0);
    let v011 = _fns_grad_vec(seed, x0, y1, z1);
    let v100 = _fns_grad_vec(seed, x1, y0, z0);
    let v101 = _fns_grad_vec(seed, x1, y0, z1);
    let v110 = _fns_grad_vec(seed, x1, y1, z0);
    let v111 = _fns_grad_vec(seed, x1, y1, z1);

    let x0y = _lerp(_lerp(v000.x, v100.x, xs), _lerp(v010.x, v110.x, xs), ys);
    let y0y = _lerp(_lerp(v000.y, v100.y, xs), _lerp(v010.y, v110.y, xs), ys);
    let z0y = _lerp(_lerp(v000.z, v100.z, xs), _lerp(v010.z, v110.z, xs), ys);
    let x1y = _lerp(_lerp(v001.x, v101.x, xs), _lerp(v011.x, v111.x, xs), ys);
    let y1y = _lerp(_lerp(v001.y, v101.y, xs), _lerp(v011.y, v111.y, xs), ys);
    let z1y = _lerp(_lerp(v001.z, v101.z, xs), _lerp(v011.z, v111.z, xs), ys);
    return vec3<f32>(_lerp(x0y, x1y, zs) * amp + x, _lerp(y0y, y1y, zs) * amp + y, _lerp(z0y, z1y, zs) * amp + z);
}

// scalar.py: perturb3 (1622). The reference's PERTURB_SWITCH on a frequency-scaled point. normalise is the normalise
// length already multiplied by the noise frequency; bounding is the noise's fractal bounding, which the reference (not
// its own perturb bounding) multiplies into a fractal perturb's amplitude.
fn perturb3(
    ptype : i32, seed : i32, bounding : f32, amp_in : f32, freq : f32, octaves : i32, lacunarity : f32, gain : f32,
    normalise : f32, x_in : f32, y_in : f32, z_in : f32,
) -> vec3<f32> {
    let amp = amp_in / 511.5;  // the reference's SetPerturbAmp: its random vectors are ten bits wide, +-511.5
    var p = vec3<f32>(x_in, y_in, z_in);
    if (ptype == PERTURB_GRADIENT || ptype == PERTURB_GRADIENT_NORMALISE) {
        p = _perturb_single3(seed - 1, amp, freq, p.x, p.y, p.z);
    } else if (ptype == PERTURB_GRADIENT_FRACTAL || ptype == PERTURB_GRADIENT_FRACTAL_NORMALISE) {
        var seed_f = seed - 1;
        var freq_f = freq;
        var amp_f = amp * bounding;
        p = _perturb_single3(seed_f, amp_f, freq_f, p.x, p.y, p.z);
        for (var octave = 1; octave < octaves; octave++) {
            freq_f *= lacunarity;
            seed_f -= 1;
            amp_f *= gain;
            p = _perturb_single3(seed_f, amp_f, freq_f, p.x, p.y, p.z);
        }
    }
    if (ptype >= PERTURB_NORMALISE) {
        // The reference used an approximate rsqrt and made NaN of the origin; a zero-length point stays where it is.
        let len = sqrt(p.x * p.x + p.y * p.y + p.z * p.z);
        var inv = 0.0;
        if (len > 0.0) {
            inv = normalise / len;
        }
        p = p * inv;
    }
    return p;
}

// scalar.py: perturb2 (1653). The reference was 3D only; its 2D use was z = 0, and the z displacement is dropped
// (after the normalise modes have counted it in the length, as the CPU's does).
fn perturb2(
    ptype : i32, seed : i32, bounding : f32, amp : f32, freq : f32, octaves : i32, lacunarity : f32, gain : f32,
    normalise : f32, x : f32, y : f32,
) -> vec2<f32> {
    return perturb3(ptype, seed, bounding, amp, freq, octaves, lacunarity, gain, normalise, x, y, 0.0).xy;
}

// -------------------------------------------------------------------------
// dispatch, transforms, fractals

// scalar.py: noise_single2 (1662)
fn noise_single2(
    noise_type : i32, seed : i32, x : f32, y : f32, cell_dist : i32, cell_ret : i32, cell_jitter : f32,
    lookup_type : i32, lookup_freq : f32,
) -> f32 {
    if (noise_type == NOISE_OPEN_SIMPLEX2) {
        return simplex2(seed, x, y);
    }
    if (noise_type == NOISE_OPEN_SIMPLEX2S) {
        return simplex2s(seed, x, y);
    }
    if (noise_type == NOISE_CELLULAR) {
        return cellular2(seed, x, y, cell_dist, cell_ret, cell_jitter, lookup_type, lookup_freq);
    }
    if (noise_type == NOISE_PERLIN) {
        return perlin2(seed, x, y);
    }
    if (noise_type == NOISE_VALUE_CUBIC) {
        return value_cubic2(seed, x, y);
    }
    if (noise_type == NOISE_VALUE) {
        return value2(seed, x, y);
    }
    if (noise_type == NOISE_WHITE_NOISE) {
        return white_noise2(seed, x, y);
    }
    if (noise_type == NOISE_SIMPLEX_CLASSIC) {
        return simplex_classic2(seed, x, y);
    }
    return 0.0;
}

// scalar.py: noise_single3 (1683)
fn noise_single3(
    noise_type : i32, seed : i32, x : f32, y : f32, z : f32, cell_dist : i32, cell_ret : i32, cell_jitter : f32,
    lookup_type : i32, lookup_freq : f32,
) -> f32 {
    if (noise_type == NOISE_OPEN_SIMPLEX2) {
        return opensimplex2_3(seed, x, y, z);
    }
    if (noise_type == NOISE_OPEN_SIMPLEX2S) {
        return opensimplex2s_3(seed, x, y, z);
    }
    if (noise_type == NOISE_CELLULAR) {
        return cellular3(seed, x, y, z, cell_dist, cell_ret, cell_jitter, lookup_type, lookup_freq);
    }
    if (noise_type == NOISE_PERLIN) {
        return perlin3(seed, x, y, z);
    }
    if (noise_type == NOISE_VALUE_CUBIC) {
        return value_cubic3(seed, x, y, z);
    }
    if (noise_type == NOISE_VALUE) {
        return value3(seed, x, y, z);
    }
    if (noise_type == NOISE_WHITE_NOISE) {
        return white_noise3(seed, x, y, z);
    }
    if (noise_type == NOISE_SIMPLEX_CLASSIC) {
        return simplex_classic3(seed, x, y, z);
    }
    return 0.0;
}

// scalar.py: _transform2 (1704). Skew for the simplex family; identity otherwise. Frequency is applied by the caller.
fn _transform2(noise_type : i32, x : f32, y : f32) -> vec2<f32> {
    if (noise_type == NOISE_OPEN_SIMPLEX2 || noise_type == NOISE_OPEN_SIMPLEX2S) {
        let t = (x + y) * F2;
        return vec2<f32>(x + t, y + t);
    }
    return vec2<f32>(x, y);
}

// scalar.py: _transform3 (1713)
fn _transform3(transform : i32, x_in : f32, y_in : f32, z_in : f32) -> vec3<f32> {
    var x = x_in;
    var y = y_in;
    var z = z_in;
    if (transform == TRANSFORM_IMPROVE_XY) {
        let xy = x + y;
        let s2 = xy * -0.211324865405187;
        z *= 0.577350269189626;
        x += s2 - z;
        y = y + s2 - z;
        z += xy * 0.577350269189626;
        return vec3<f32>(x, y, z);
    }
    if (transform == TRANSFORM_IMPROVE_XZ) {
        let xz = x + z;
        let s2 = xz * -0.211324865405187;
        y *= 0.577350269189626;
        x += s2 - y;
        z += s2 - y;
        y += xz * 0.577350269189626;
        return vec3<f32>(x, y, z);
    }
    if (transform == TRANSFORM_DEFAULT_OS2) {
        let r = (x + y + z) * R3;
        return vec3<f32>(r - x, r - y, r - z);
    }
    return vec3<f32>(x, y, z);
}

// scalar.py: fractal2 (1737). NONE, FastNoiseLite's FBm, Ridged and PingPong, FastNoiseSIMD's RigidMulti and Billow.
// The 2D FBm clamps n + 1 at 2 (1749); the 3D one does not (1802), as on the CPU.
fn fractal2(
    noise_type : i32, fractal_type : i32, seed_in : i32, x_in : f32, y_in : f32, octaves : i32, lacunarity : f32,
    gain : f32, weighted : f32, ping_pong : f32, bounding : f32, cd : i32, cr : i32, cj : f32, cl : i32, cf : f32,
) -> f32 {
    if (fractal_type == FRACTAL_NONE) {
        return noise_single2(noise_type, seed_in, x_in, y_in, cd, cr, cj, cl, cf);
    }
    var seed = seed_in;
    var x = x_in;
    var y = y_in;
    var total = 0.0;
    var amp = select(bounding, 1.0, fractal_type == FRACTAL_RIGID_MULTI);
    for (var octave = 0; octave < octaves; octave++) {
        var n = noise_single2(noise_type, seed, x, y, cd, cr, cj, cl, cf);
        seed += 1;
        if (fractal_type == FRACTAL_FBM) {
            total += n * amp;
            amp *= _lerp(1.0, min(n + 1.0, 2.0) * 0.5, weighted);
        } else if (fractal_type == FRACTAL_RIDGED) {
            n = abs(n);
            total += (n * -2.0 + 1.0) * amp;
            amp *= _lerp(1.0, 1.0 - n, weighted);
        } else if (fractal_type == FRACTAL_RIGID_MULTI) {
            // FastNoiseSIMD: 1 - |n|, first added, the rest subtracted, unnormalised
            n = 1.0 - abs(n);
            total += select(-n * amp, n * amp, octave == 0);
        } else if (fractal_type == FRACTAL_BILLOW) {  // FastNoiseSIMD: |n| * 2 - 1 per octave
            n = abs(n) * 2.0 - 1.0;
            total += n * amp;
            amp *= _lerp(1.0, (n + 1.0) * 0.5, weighted);
        } else {  // PING_PONG
            n = _ping_pong((n + 1.0) * ping_pong);
            total += (n - 0.5) * 2.0 * amp;
            amp *= _lerp(1.0, n, weighted);
        }
        x *= lacunarity;
        y *= lacunarity;
        amp *= gain;
    }
    return total;
}

// scalar.py: fractal3 (1774). NONE, FastNoiseLite's FBm, Ridged and PingPong, FastNoiseSIMD's RigidMulti and Billow.
fn fractal3(
    noise_type : i32, fractal_type : i32, seed_in : i32, x_in : f32, y_in : f32, z_in : f32, octaves : i32,
    lacunarity : f32, gain : f32, weighted : f32, ping_pong : f32, bounding : f32, cd : i32, cr : i32, cj : f32,
    cl : i32, cf : f32,
) -> f32 {
    if (fractal_type == FRACTAL_NONE) {
        return noise_single3(noise_type, seed_in, x_in, y_in, z_in, cd, cr, cj, cl, cf);
    }
    var seed = seed_in;
    var x = x_in;
    var y = y_in;
    var z = z_in;
    var total = 0.0;
    var amp = select(bounding, 1.0, fractal_type == FRACTAL_RIGID_MULTI);
    for (var octave = 0; octave < octaves; octave++) {
        var n = noise_single3(noise_type, seed, x, y, z, cd, cr, cj, cl, cf);
        seed += 1;
        if (fractal_type == FRACTAL_FBM) {
            total += n * amp;
            amp *= _lerp(1.0, (n + 1.0) * 0.5, weighted);
        } else if (fractal_type == FRACTAL_RIDGED) {
            n = abs(n);
            total += (n * -2.0 + 1.0) * amp;
            amp *= _lerp(1.0, 1.0 - n, weighted);
        } else if (fractal_type == FRACTAL_RIGID_MULTI) {
            // FastNoiseSIMD: 1 - |n|, first added, the rest subtracted, unnormalised
            n = 1.0 - abs(n);
            total += select(-n * amp, n * amp, octave == 0);
        } else if (fractal_type == FRACTAL_BILLOW) {  // FastNoiseSIMD: |n| * 2 - 1 per octave
            n = abs(n) * 2.0 - 1.0;
            total += n * amp;
            amp *= _lerp(1.0, (n + 1.0) * 0.5, weighted);
        } else {  // PING_PONG
            n = _ping_pong((n + 1.0) * ping_pong);
            total += (n - 0.5) * 2.0 * amp;
            amp *= _lerp(1.0, n, weighted);
        }
        x *= lacunarity;
        y *= lacunarity;
        z *= lacunarity;
        amp *= gain;
    }
    return total;
}

// -------------------------------------------------------------------------
// single-point entry points: the coordinates are arguments, every other scalar is read from P

// scalar.py: sample_one_2d (1830). The seed is already wrapped to i32 by gpu.pack_params. Without a warp, x * frequency
// is the CPU's float32 product exactly; with one, the raw point is warped, then multiplied by the frequency, as the CPU
// does in float64 (1861-1875). The perturb's normalise length is multiplied by the frequency, as the CPU passes it
// (1889).
fn sample_one_2d(x : f32, y : f32) -> f32 {
    let seed = P.seed;
    var xf : f32;
    var yf : f32;
    if (P.domain_warp != WARP_NONE) {
        let w = warp2(
            P.domain_warp, P.warp_fractal, seed, P.warp_amp, P.frequency, P.octaves, P.lacunarity, P.gain, x, y,
        );
        xf = w.x * P.frequency;
        yf = w.y * P.frequency;
    } else {
        xf = x * P.frequency;
        yf = y * P.frequency;
    }
    if (P.perturb != PERTURB_NONE) {
        let p = perturb2(
            P.perturb, seed, P.fractal_bounding, P.perturb_amp, P.perturb_frequency, P.perturb_octaves,
            P.perturb_lacunarity, P.perturb_gain, P.perturb_normalise_length * P.frequency, xf, yf,
        );
        xf = p.x;
        yf = p.y;
    }
    let s = _transform2(P.noise_type, xf, yf);
    return fractal2(
        P.noise_type, P.fractal_type, seed, s.x, s.y, P.octaves, P.lacunarity, P.gain, P.weighted_strength,
        P.ping_pong_strength, P.fractal_bounding, P.cellular_distance, P.cellular_return, P.cellular_jitter,
        P.cellular_lookup_type, P.cellular_lookup_frequency,
    );
}

// scalar.py: sample_one_3d (1915). The warp as in sample_one_2d (1949-1966), with the warp's own Transform3D; the
// perturb as there (1981).
fn sample_one_3d(x : f32, y : f32, z : f32) -> f32 {
    let seed = P.seed;
    var xf : f32;
    var yf : f32;
    var zf : f32;
    if (P.domain_warp != WARP_NONE) {
        let w = warp3(
            P.domain_warp, P.warp_fractal, P.warp_transform_3d, seed, P.warp_amp, P.frequency, P.octaves,
            P.lacunarity, P.gain, x, y, z,
        );
        xf = w.x * P.frequency;
        yf = w.y * P.frequency;
        zf = w.z * P.frequency;
    } else {
        xf = x * P.frequency;
        yf = y * P.frequency;
        zf = z * P.frequency;
    }
    if (P.perturb != PERTURB_NONE) {
        let p = perturb3(
            P.perturb, seed, P.fractal_bounding, P.perturb_amp, P.perturb_frequency, P.perturb_octaves,
            P.perturb_lacunarity, P.perturb_gain, P.perturb_normalise_length * P.frequency, xf, yf, zf,
        );
        xf = p.x;
        yf = p.y;
        zf = p.z;
    }
    let r = _transform3(P.transform_3d, xf, yf, zf);
    return fractal3(
        P.noise_type, P.fractal_type, seed, r.x, r.y, r.z, P.octaves, P.lacunarity, P.gain, P.weighted_strength,
        P.ping_pong_strength, P.fractal_bounding, P.cellular_distance, P.cellular_return, P.cellular_jitter,
        P.cellular_lookup_type, P.cellular_lookup_frequency,
    );
}

// -------------------------------------------------------------------------
// the compute entry points (gpu.ENTRY_POINTS)

// A dispatch past 65,535 workgroups wraps into y (gpu._workgroups). The stride is gpu.py's _MAX_GROUPS * WORKGROUP:
// change one and the other together (test_gpu.py, test_a_dispatch_past_65535_workgroups_reaches_its_last_points).
fn point_index(gid : vec3<u32>) -> u32 { return gid.x + gid.y * (65535u * 64u); }

@compute @workgroup_size(64)
fn sample_points_3d(@builtin(global_invocation_id) gid : vec3<u32>) {
    let i = point_index(gid);
    if (i >= arrayLength(&OUT)) { return; }
    OUT[i] = sample_one_3d(XS[i], YS[i], ZS[i]);
}

@compute @workgroup_size(64)
fn sample_points_2d(@builtin(global_invocation_id) gid : vec3<u32>) {
    let i = point_index(gid);
    if (i >= arrayLength(&OUT)) { return; }
    OUT[i] = sample_one_2d(XS[i], YS[i]);
}

// scalar.py: sample_grid (2269). The coordinate is f32(start + index) * f32(scale): equal to the CPU's float64 product
// rounded to float32 when the scale is a power of two and start + index is below 2^24.
@compute @workgroup_size(64)
fn sample_grid(@builtin(global_invocation_id) gid : vec3<u32>) {
    let i = point_index(gid);
    if (i >= arrayLength(&OUT)) { return; }
    let iz = i % G.nz;
    let iy = (i / G.nz) % G.ny;
    let ix = i / (G.nz * G.ny);
    let x = f32(G.x0 + i32(ix)) * G.sx;
    let y = f32(G.y0 + i32(iy)) * G.sy;
    let z = f32(G.z0 + i32(iz)) * G.sz;
    OUT[i] = sample_one_3d(x, y, z);
}

// scalar.py: warp_3d (2228). The warped raw coordinates alone, three floats per point; the seed is wrapped already.
@compute @workgroup_size(64)
fn warp_points_3d(@builtin(global_invocation_id) gid : vec3<u32>) {
    let i = point_index(gid);
    if (3u * i >= arrayLength(&OUT)) { return; }
    let w = warp3(
        P.domain_warp, P.warp_fractal, P.warp_transform_3d, P.seed, P.warp_amp, P.frequency, P.octaves, P.lacunarity,
        P.gain, XS[i], YS[i], ZS[i],
    );
    OUT[3u * i] = w.x;
    OUT[3u * i + 1u] = w.y;
    OUT[3u * i + 2u] = w.z;
}

// scalar.py: warp_2d (2206). Two floats per point.
@compute @workgroup_size(64)
fn warp_points_2d(@builtin(global_invocation_id) gid : vec3<u32>) {
    let i = point_index(gid);
    if (2u * i >= arrayLength(&OUT)) { return; }
    let w = warp2(
        P.domain_warp, P.warp_fractal, P.seed, P.warp_amp, P.frequency, P.octaves, P.lacunarity, P.gain, XS[i], YS[i],
    );
    OUT[2u * i] = w.x;
    OUT[2u * i + 1u] = w.y;
}
