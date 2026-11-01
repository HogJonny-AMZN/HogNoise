// Spike (the GPU fast track, stage 1): 2D OpenSimplex2 with FBm, ported line for line from src/hog_noise/scalar.py.
// Evidence, not product. Integer arithmetic is done on u32 and reinterpreted, so it wraps exactly as the CPU's 32-bit
// emulation does; floats are f32 throughout, where the CPU uses float64 after the frequency multiply.

struct Params {
    seed : i32,
    frequency : f32,
    octaves : u32,
    lacunarity : f32,
    gain : f32,
    bounding : f32,
    count : u32,
    fractal : u32,   // 0 none, 1 FBm
};

@group(0) @binding(0) var<uniform> P : Params;
@group(0) @binding(1) var<storage, read> GRAD2 : array<f32, 256>;
@group(0) @binding(2) var<storage, read> POS : array<vec2<f32>>;
@group(0) @binding(3) var<storage, read_write> OUT : array<f32>;

const PRIME_X : u32 = 501125321u;
const PRIME_Y : u32 = 1136930381u;
const HASH_MUL : u32 = 0x27D4EB2Du;
const SQRT3 : f32 = 1.7320508075688772;
const F2 : f32 = 0.5 * (SQRT3 - 1.0);
const G2 : f32 = (3.0 - SQRT3) / 6.0;

fn wmul(a : i32, b : u32) -> i32 { return bitcast<i32>(bitcast<u32>(a) * b); }
fn wadd(a : i32, b : u32) -> i32 { return bitcast<i32>(bitcast<u32>(a) + b); }

fn hash2(seed : i32, xp : i32, yp : i32) -> i32 {
    return wmul(seed ^ xp ^ yp, HASH_MUL);
}

fn grad_coord2(seed : i32, xp : i32, yp : i32, xd : f32, yd : f32) -> f32 {
    var h = hash2(seed, xp, yp);
    h = h ^ (h >> 15u);            // arithmetic shift on i32, as the CPU's signed shift
    h = h & (127 << 1u);
    return xd * GRAD2[h] + yd * GRAD2[h | 1];
}

fn fast_floor(f : f32) -> i32 {
    // the reference's quirk: (int)f - 1 for any negative f, integral or not
    var i = i32(f);
    if (f < 0.0) { i = i - 1; }
    return i;
}

fn simplex2(seed : i32, x : f32, y : f32) -> f32 {
    var i = fast_floor(x);
    var j = fast_floor(y);
    let xi = x - f32(i);
    let yi = y - f32(j);
    let t = (xi + yi) * G2;
    let x0 = xi - t;
    let y0 = yi - t;
    i = wmul(i, PRIME_X);
    j = wmul(j, PRIME_Y);

    let a = 0.5 - x0 * x0 - y0 * y0;
    var n0 = 0.0;
    if (a > 0.0) { n0 = (a * a) * (a * a) * grad_coord2(seed, i, j, x0, y0); }

    let c = (2.0 * (1.0 - 2.0 * G2) * (1.0 / G2 - 2.0)) * t + ((-2.0 * (1.0 - 2.0 * G2) * (1.0 - 2.0 * G2)) + a);
    var n2 = 0.0;
    if (c > 0.0) {
        let x2 = x0 + (2.0 * G2 - 1.0);
        let y2 = y0 + (2.0 * G2 - 1.0);
        n2 = (c * c) * (c * c) * grad_coord2(seed, wadd(i, PRIME_X), wadd(j, PRIME_Y), x2, y2);
    }

    var n1 = 0.0;
    if (y0 > x0) {
        let x1 = x0 + G2;
        let y1 = y0 + (G2 - 1.0);
        let b = 0.5 - x1 * x1 - y1 * y1;
        if (b > 0.0) { n1 = (b * b) * (b * b) * grad_coord2(seed, i, wadd(j, PRIME_Y), x1, y1); }
    } else {
        let x1 = x0 + (G2 - 1.0);
        let y1 = y0 + G2;
        let b = 0.5 - x1 * x1 - y1 * y1;
        if (b > 0.0) { n1 = (b * b) * (b * b) * grad_coord2(seed, wadd(i, PRIME_X), j, x1, y1); }
    }
    return (n0 + n1 + n2) * 99.83685446303647;
}

fn sample2(px : f32, py : f32) -> f32 {
    var x = px * P.frequency;
    var y = py * P.frequency;
    let t = (x + y) * F2;          // the simplex skew (_transform2)
    x = x + t;
    y = y + t;
    var seed = P.seed;
    if (P.fractal == 0u) { return simplex2(seed, x, y); }
    var total = 0.0;
    var amp = P.bounding;
    for (var o = 0u; o < P.octaves; o = o + 1u) {
        let n = simplex2(seed, x, y);
        seed = wadd(seed, 1u);
        total = total + n * amp;   // weighted strength 0: amp keeps its value
        x = x * P.lacunarity;
        y = y * P.lacunarity;
        amp = amp * P.gain;
    }
    return total;
}

@compute @workgroup_size(64)
fn main(@builtin(global_invocation_id) gid : vec3<u32>) {
    let k = gid.x;
    if (k >= P.count) { return; }
    let p = POS[k];
    OUT[k] = sample2(p.x, p.y);
}
