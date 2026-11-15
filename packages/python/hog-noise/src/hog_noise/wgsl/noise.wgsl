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

// scalar.py: fractal2 (1737). FRACTAL_NONE so far; the other fractals arrive in Tasks 7 and 10.
fn fractal2(
    noise_type : i32, fractal_type : i32, seed : i32, x : f32, y : f32, octaves : i32, lacunarity : f32, gain : f32,
    weighted : f32, ping_pong : f32, bounding : f32, cd : i32, cr : i32, cj : f32, cl : i32, cf : f32,
) -> f32 {
    if (fractal_type == FRACTAL_NONE) {
        return noise_single2(noise_type, seed, x, y, cd, cr, cj, cl, cf);
    }
    return 0.0;
}

// scalar.py: fractal3 (1774). FRACTAL_NONE so far; the other fractals arrive in Tasks 7 and 10.
fn fractal3(
    noise_type : i32, fractal_type : i32, seed : i32, x : f32, y : f32, z : f32, octaves : i32, lacunarity : f32,
    gain : f32, weighted : f32, ping_pong : f32, bounding : f32, cd : i32, cr : i32, cj : f32, cl : i32, cf : f32,
) -> f32 {
    if (fractal_type == FRACTAL_NONE) {
        return noise_single3(noise_type, seed, x, y, z, cd, cr, cj, cl, cf);
    }
    return 0.0;
}

// -------------------------------------------------------------------------
// single-point entry points: the coordinates are arguments, every other scalar is read from P

// scalar.py: sample_one_2d (1830), without the warp and perturb branches (Tasks 11 and 12). The seed is already
// wrapped to i32 by gpu.pack_params. x * frequency is the CPU's float32 product exactly.
fn sample_one_2d(x : f32, y : f32) -> f32 {
    let seed = P.seed;
    let xf = x * P.frequency;
    let yf = y * P.frequency;
    let s = _transform2(P.noise_type, xf, yf);
    return fractal2(
        P.noise_type, P.fractal_type, seed, s.x, s.y, P.octaves, P.lacunarity, P.gain, P.weighted_strength,
        P.ping_pong_strength, P.fractal_bounding, P.cellular_distance, P.cellular_return, P.cellular_jitter,
        P.cellular_lookup_type, P.cellular_lookup_frequency,
    );
}

// scalar.py: sample_one_3d (1915), without the warp and perturb branches (Tasks 11 and 12).
fn sample_one_3d(x : f32, y : f32, z : f32) -> f32 {
    let seed = P.seed;
    let xf = x * P.frequency;
    let yf = y * P.frequency;
    let zf = z * P.frequency;
    let r = _transform3(P.transform_3d, xf, yf, zf);
    return fractal3(
        P.noise_type, P.fractal_type, seed, r.x, r.y, r.z, P.octaves, P.lacunarity, P.gain, P.weighted_strength,
        P.ping_pong_strength, P.fractal_bounding, P.cellular_distance, P.cellular_return, P.cellular_jitter,
        P.cellular_lookup_type, P.cellular_lookup_frequency,
    );
}

// -------------------------------------------------------------------------
// the compute entry points (gpu.ENTRY_POINTS)

// A dispatch past 65,535 workgroups wraps into y (gpu._workgroups).
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

// The warp entry points are ported in Task 12; gpu.py refuses them until then.
@compute @workgroup_size(64)
fn warp_points_3d(@builtin(global_invocation_id) gid : vec3<u32>) {
    let i = point_index(gid);
    if (3u * i >= arrayLength(&OUT)) { return; }
    OUT[3u * i] = XS[i];
    OUT[3u * i + 1u] = YS[i];
    OUT[3u * i + 2u] = ZS[i];
}

@compute @workgroup_size(64)
fn warp_points_2d(@builtin(global_invocation_id) gid : vec3<u32>) {
    let i = point_index(gid);
    if (2u * i >= arrayLength(&OUT)) { return; }
    OUT[2u * i] = XS[i];
    OUT[2u * i + 1u] = YS[i];
}
