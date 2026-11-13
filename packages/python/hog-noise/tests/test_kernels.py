"""
Tests for hog_noise: the two standards from the pre-ADR, section 4.3.
Package: packages/python/hog-noise/tests/test_kernels

Tight, between rungs we own: the numba kernel and the numpy base agree exactly.
Advisory, against the original binding: every Phase A feature is compared with the committed
`pyfastnoiselite` vectors; a mismatch writes a comparison sheet and is marked needs-review unless
`accepted.json` records a verdict. It never fails the build. The portability table is regenerated
from the same comparisons.
"""

import os
import subprocess
import sys
import time

import numpy as np
import pytest
from hog_noise_repo import VECTORS as VECTORS_ROOT

from hog_noise import (
    HAVE_NUMBA,
    CellularReturn,
    DomainWarpType,
    FractalType,
    NoiseParams,
    NoiseType,
    NumpySampler,
    PerturbType,
    compare,
    conformance,
    make_sampler,
    parse_cellular_distance,
    parse_cellular_return,
    parse_fractal_type,
    parse_noise_type,
    parse_perturb,
    scalar,
    vectorized,
)

VECTORS = VECTORS_ROOT
REPORTS = VECTORS / "reports"
ACCEPTED = VECTORS / "accepted.json"
PORTABILITY = VECTORS / "portability.md"

PHASE_A_NOISE = ("simplex", "perlin", "value", "cubic")
PHASE_A_FRACTAL = ("none", "fbm", "ridged", "pingpong")
CELL_DIST = ("euclidean", "euclideansq", "manhattan", "hybrid")
CELL_RET = ("cellvalue", "distance", "distance2", "distance2add", "distance2sub", "distance2mul", "distance2div")
PHASE_A = (
    [f"{n}_{f}" for n in PHASE_A_NOISE for f in PHASE_A_FRACTAL]
    + [
        "simplex_fbm_weighted0.5",
        "simplex_none_improve_xy",
        "simplex_none_improve_xz",
        "perlin_none_improve_xy",
        "perlin_none_improve_xz",
    ]
    + [f"cellular_{d}_{r}" for d in CELL_DIST for r in CELL_RET]
    + [f"cellular_{f}" for f in PHASE_A_FRACTAL]
)
#: Phase B, one feature per PR (pre-ADR 4.2): OpenSimplex2S landed 2026-09-28; domain warp the same day.
WARP_TYPES = ("opensimplex2", "opensimplex2reduced", "basicgrid")
WARP_FRACTALS = ("none", "domain_warp_progressive", "domain_warp_independent")
PHASE_B_WARP = [f"warp_{w}_{f}" for w in WARP_TYPES for f in WARP_FRACTALS]
PHASE_B = [f"simplex_smooth_{f}" for f in PHASE_A_FRACTAL] + PHASE_B_WARP
PORTED = PHASE_A + PHASE_B

_portability_rows = []


@pytest.fixture(scope="module")
def vectors():
    return conformance.load(VECTORS)


@pytest.fixture(scope="module")
def coords(vectors):
    """Today's coordinate names over the point sets, so the property tests below read as they did."""
    xs, ys, zs = vectors.point_sets["scatter_3d"].axes
    grid_x, _, grid_z = vectors.point_sets["grid_y0"].axes
    return {"xs": xs, "ys": ys, "zs": zs, "grid_x": grid_x, "grid_z": grid_z}


def _original(vectors, library: str, feature: str, point_set: str, *, warp: bool = False, variant: str = ""):
    suffix = ("/warp" if warp else "") + (f"#{variant}" if variant else "")
    return vectors.case(f"original/{library}/{feature}/{point_set}{suffix}")


# -------------------------------------------------------------------------
# tight: numba vs numpy base, exact
@pytest.mark.skipif(not HAVE_NUMBA, reason="numba not installed; the tight test needs both rungs")
@pytest.mark.parametrize("feature", PORTED)
def test_numba_and_numpy_agree_exactly(feature, vectors, coords):
    params = _original(vectors, "fnl", feature, "scatter_3d").params
    a = np.empty(len(coords["xs"]), np.float32)
    b = np.empty(len(coords["xs"]), np.float32)
    numba_sampler, _ = make_sampler(params, backend="numba")
    numpy_sampler = NumpySampler(params)
    numba_sampler.sample_points(coords["xs"], coords["ys"], coords["zs"], a)
    numpy_sampler.sample_points(coords["xs"], coords["ys"], coords["zs"], b)
    assert np.array_equal(a, b), f"3D: max diff {np.abs(a - b).max()}"
    numba_sampler.sample_points_2d(coords["xs"], coords["zs"], a)
    numpy_sampler.sample_points_2d(coords["xs"], coords["zs"], b)
    assert np.array_equal(a, b), f"2D: max diff {np.abs(a - b).max()}"
    _portability_rows.append(compare.PortabilityRow(feature, "numba", "numpy", compare.compare_values(a, b)))


def test_the_exact_test_would_catch_a_one_ulp_change(coords):
    """The instrument can produce the other answer: nudging one value is a failure, not noise."""
    params = NoiseParams(seed=1, noise_type=NoiseType.PERLIN, fractal_type=FractalType.FBM, octaves=2)
    out = np.empty(64, np.float32)
    NumpySampler(params).sample_points(coords["xs"][:64], coords["ys"][:64], coords["zs"][:64], out)
    nudged = out.copy()
    nudged[10] = np.nextafter(nudged[10], np.float32(np.inf))
    assert not np.array_equal(out, nudged)


# -------------------------------------------------------------------------
# advisory: our kernels vs the pyfastnoiselite vectors
@pytest.mark.parametrize("feature", PORTED)
def test_kernels_against_fastnoiselite_vectors(feature, vectors, coords):
    """
    Always runs, always reports. A mismatch writes a sheet under vectors/reports/ and
    becomes needs-review (xfail) unless accepted.json records a verdict. It never fails the build.
    """
    c3 = _original(vectors, "fnl", feature, "scatter_3d")
    c2 = _original(vectors, "fnl", feature, "scatter_2d")
    cg = _original(vectors, "fnl", feature, "grid_y0")
    params = c3.params
    sampler = NumpySampler(params) if not HAVE_NUMBA else make_sampler(params, backend="numba")[0]
    ours_3d = sampler.sample_points(coords["xs"], coords["ys"], coords["zs"], np.empty(len(coords["xs"]), np.float32))
    stats_3d = compare.compare_values(ours_3d, c3.values)
    ours_2d = sampler.sample_points_2d(coords["xs"], coords["zs"], np.empty(len(coords["xs"]), np.float32))
    stats_2d = compare.compare_values(ours_2d, c2.values)
    rung = sampler.name
    _portability_rows.append(compare.PortabilityRow(f"{feature} (3D)", rung, "fastnoiselite", stats_3d))
    _portability_rows.append(compare.PortabilityRow(f"{feature} (2D)", rung, "fastnoiselite", stats_2d))

    if not (stats_3d.needs_review or stats_2d.needs_review):
        return
    verdicts = compare.Verdicts(ACCEPTED)
    if verdicts.is_accepted(feature):
        # Decided by a human; the committed sheet is the record. Not rewritten here, so an
        # accepted feature does not dirty the tree on every run.
        return
    n = int(np.sqrt(len(coords["grid_x"])))
    grid_ours = sampler.sample_points(
        coords["grid_x"], np.zeros_like(coords["grid_x"]), coords["grid_z"], np.empty(len(coords["grid_x"]), np.float32)
    ).reshape(n, n)
    sheet = compare.render_sheet(
        cg.values.reshape(n, n), grid_ours, REPORTS / f"{feature}.png", f"{feature}: {rung} vs fastnoiselite"
    )
    pytest.xfail(f"needs-review: {feature} 3D {stats_3d.summary()} | 2D {stats_2d.summary()} | sheet {sheet}")


@pytest.mark.parametrize("feature", PHASE_B_WARP)
def test_domain_warp_field_matches_the_reference(feature, vectors, coords):
    """
    The warped coordinates themselves (the reference's ``DomainWarp``), from the C++ oracle in
    tools/noise_oracle since the binding does not expose the call. Exact between our rungs; against
    the oracle, within float32 rounding of the coordinates (about 1 ulp at 4096, so 5e-4), which is the
    oracle's own precision, not ours: that comparison is the harness's (the warp cases, at 4e-3), in
    `test_the_renderings_pass_every_gating_case_and_the_hog_set`. Here: a real displacement, and exact rungs.
    """
    params = _original(vectors, "fnl", feature, "scatter_3d").params
    w3 = _original(vectors, "fnl", feature, "scatter_3d", warp=True).values
    numpy_sampler = NumpySampler(params)
    ours_3d = numpy_sampler.warp_points(coords["xs"], coords["ys"], coords["zs"])
    ours_2d = numpy_sampler.warp_points_2d(coords["xs"], coords["zs"])
    if HAVE_NUMBA:
        numba_sampler, _ = make_sampler(params, backend="numba")
        assert np.array_equal(numba_sampler.warp_points(coords["xs"], coords["ys"], coords["zs"]), ours_3d)
        assert np.array_equal(numba_sampler.warp_points_2d(coords["xs"], coords["zs"]), ours_2d)
    raw_3d = np.stack([coords["xs"], coords["ys"], coords["zs"]], axis=1)
    assert np.abs(w3 - raw_3d).mean() > 1.0, "the vector carries a real displacement"


# -------------------------------------------------------------------------
# Phase C: what only FastNoiseSIMD had. Its base noises hash differently, so its vectors are compared
# by shape (range, spread), not by point; the tight proof is between our rungs and from the parts.
BILLOW_NOISE = ("simplex", "simplex_smooth", "perlin", "value", "cubic", "cellular")


@pytest.mark.parametrize("weighted", [0.0, 0.5])
@pytest.mark.parametrize("noise", BILLOW_NOISE)
def test_billow_is_exact_between_rungs_and_is_the_billow_of_its_octaves(noise, weighted, coords):
    """FastNoiseSIMD's Billow: |n| * 2 - 1 per octave. Exact between rungs in 2D and 3D, with and without
    the weighted-amplitude update, and re-derived from single-octave samples of the same kernel, so the
    fractal is proven from its parts (the re-derivation covers the unweighted sum)."""
    n = 1024
    xs, ys, zs = coords["xs"][:n], coords["ys"][:n], coords["zs"][:n]
    params = NoiseParams(
        seed=99,
        frequency=0.01,
        noise_type=parse_noise_type(noise),
        fractal_type=FractalType.BILLOW,
        octaves=3,
        weighted_strength=weighted,
    )
    numpy_sampler = NumpySampler(params)
    ours = numpy_sampler.sample_points(xs, ys, zs, np.empty(n, np.float32))
    ours_2d = numpy_sampler.sample_points_2d(xs, zs, np.empty(n, np.float32))
    assert -1.05 <= ours.min() and ours.max() <= 1.05 and ours.std() > 0.01
    if HAVE_NUMBA:
        numba_sampler, _ = make_sampler(params, backend="numba")
        assert np.array_equal(numba_sampler.sample_points(xs, ys, zs, np.empty(n, np.float32)), ours)
        assert np.array_equal(numba_sampler.sample_points_2d(xs, zs, np.empty(n, np.float32)), ours_2d)
    if weighted:
        plain = NumpySampler(params.replace(weighted_strength=0.0)).sample_points(xs, ys, zs, np.empty(n, np.float32))
        assert not np.array_equal(ours, plain), "the weighted update changes the sum"
        return
    total = np.zeros(n)
    amp = params.fractal_bounding
    for i in range(params.octaves):
        octave = params.replace(
            fractal_type=FractalType.NONE, seed=params.seed + i, frequency=params.frequency * params.lacunarity**i
        )
        single = NumpySampler(octave).sample_points(xs, ys, zs, np.empty(n, np.float32)).astype(np.float64)
        total += (np.abs(single) * 2.0 - 1.0) * amp
        amp *= params.gain
    np.testing.assert_allclose(ours, total, atol=2e-4)  # float32 frequency rounding per octave, nothing else


# FastNoiseSIMD's Billow by shape (FastNoiseSIMD's Perlin is a differently hashed Perlin, so points cannot match;
# what Billow adds, the fold to [-1, 1] and the spread, must still agree) is the harness's: the `shape` cases on
# original/fns/*_billow/scatter_3d, checked in test_the_renderings_pass_every_gating_case_and_the_hog_set.


def test_warp_points_without_a_warp_returns_the_raw_points(coords):
    """Regression (Copilot on #71): WARP_NONE is zero and the warp dispatch's fallback was BasicGrid, so a
    sampler with no warp configured displaced its warp_points. Now the raw points come back, on both rungs."""
    params = NoiseParams(seed=1, frequency=0.01)
    assert params.domain_warp is DomainWarpType.NONE
    raw_3d = np.stack([coords["xs"], coords["ys"], coords["zs"]], axis=1)
    raw_2d = np.stack([coords["xs"], coords["zs"]], axis=1)
    numpy_sampler = NumpySampler(params)
    assert np.array_equal(numpy_sampler.warp_points(coords["xs"], coords["ys"], coords["zs"]), raw_3d)
    assert np.array_equal(numpy_sampler.warp_points_2d(coords["xs"], coords["zs"]), raw_2d)
    if HAVE_NUMBA:
        numba_sampler, _ = make_sampler(params, backend="numba")
        assert np.array_equal(numba_sampler.warp_points(coords["xs"], coords["ys"], coords["zs"]), raw_3d)
        assert np.array_equal(numba_sampler.warp_points_2d(coords["xs"], coords["zs"]), raw_2d)


def test_white_noise_is_exact_between_rungs_and_matches_fastnoisesimd(vectors, coords):
    """
    FastNoiseSIMD's white noise hashes the float32 bit patterns of the scaled coordinates, so this
    is the one Phase C feature its vectors can check point by point: tight (float32 rounding of the
    hash-to-float multiply; the harness holds it to 1e-6), and exact between our rungs.
    """
    case = _original(vectors, "fns", "whitenoise_none", "scatter_3d")
    params = case.params
    n = len(coords["xs"])
    ours = NumpySampler(params).sample_points(coords["xs"], coords["ys"], coords["zs"], np.empty(n, np.float32))
    if HAVE_NUMBA:
        numba_sampler, _ = make_sampler(params, backend="numba")
        assert np.array_equal(
            numba_sampler.sample_points(coords["xs"], coords["ys"], coords["zs"], np.empty(n, np.float32)), ours
        )
        assert np.array_equal(
            numba_sampler.sample_points_2d(coords["xs"], coords["zs"], np.empty(n, np.float32)),
            NumpySampler(params).sample_points_2d(coords["xs"], coords["zs"], np.empty(n, np.float32)),
        )
    stats = compare.compare_values(ours, case.values)
    _portability_rows.append(compare.PortabilityRow("whitenoise_none (3D)", "numpy", "fastnoisesimd", stats))
    assert -1.0 <= ours.min() and ours.max() <= 1.0
    assert abs(float(ours.mean())) < 0.05 and 0.5 < float(ours.std()) < 0.65, "uniform on [-1, 1]"


CELL_C_CASES = [("natural", r) for r in CELL_RET] + [
    (d, r)
    for d in ("euclidean", "euclideansq", "manhattan", "hybrid", "natural")
    for r in ("noiselookup", "distance2cave")
]


@pytest.mark.parametrize("dist,ret", CELL_C_CASES)
def test_cellular_phase_c_is_exact_between_rungs(dist, ret, coords):
    """Natural distance, NoiseLookup and Distance2Cave (FastNoiseSIMD's): exact between rungs, 2D and 3D."""
    n = 1024
    xs, ys, zs = coords["xs"][:n], coords["ys"][:n], coords["zs"][:n]
    params = NoiseParams(
        seed=3,
        frequency=0.02,
        noise_type=NoiseType.CELLULAR,
        cellular_distance=parse_cellular_distance(dist),
        cellular_return=parse_cellular_return(ret),
        cellular_lookup_type=NoiseType.PERLIN,
        cellular_lookup_frequency=0.2,
    )
    numpy_sampler = NumpySampler(params)
    ours_3d = numpy_sampler.sample_points(xs, ys, zs, np.empty(n, np.float32))
    ours_2d = numpy_sampler.sample_points_2d(xs, zs, np.empty(n, np.float32))
    assert np.isfinite(ours_3d).all() and np.isfinite(ours_2d).all()
    assert ours_3d.std() > 0.01 and ours_2d.std() > 0.01, "a field, not a constant"
    if HAVE_NUMBA:
        numba_sampler, _ = make_sampler(params, backend="numba")
        assert np.array_equal(numba_sampler.sample_points(xs, ys, zs, np.empty(n, np.float32)), ours_3d)
        assert np.array_equal(numba_sampler.sample_points_2d(xs, zs, np.empty(n, np.float32)), ours_2d)


def test_distance2cave_is_the_lesser_of_two_distance2div_fields(coords):
    """FastNoiseSIMD's Distance2Cave, re-derived: Distance2Div at (seed, p) and at (seed + 1, p + half a cell)."""
    n = 2048
    xs, ys, zs = coords["xs"][:n], coords["ys"][:n], coords["zs"][:n]
    base = NoiseParams(
        seed=11, frequency=0.05, noise_type=NoiseType.CELLULAR, cellular_return=CellularReturn.DISTANCE2_CAVE
    )
    cave = NumpySampler(base).sample_points(xs, ys, zs, np.empty(n, np.float32))
    div = base.replace(cellular_return=CellularReturn.DISTANCE2_DIV)
    c0 = NumpySampler(div).sample_points(xs, ys, zs, np.empty(n, np.float32))
    half = np.float32(0.5) / np.float32(base.frequency)  # half a cell, in world units
    c1 = NumpySampler(div.replace(seed=12)).sample_points(xs + half, ys + half, zs + half, np.empty(n, np.float32))
    np.testing.assert_allclose(cave, np.minimum(c0, c1), atol=2e-3)  # the half-cell offset rounds in float32


def test_noise_lookup_is_constant_within_a_cell_and_is_the_lookup_noise(coords):
    """NoiseLookup: every point of a cell gets its cell point's lookup value, so a tight cluster of points
    shares one value, and that value is the lookup noise (Perlin here) at a cell point, not at the sample."""
    params = NoiseParams(
        seed=5,
        frequency=0.01,
        noise_type=NoiseType.CELLULAR,
        cellular_return=CellularReturn.NOISE_LOOKUP,
        cellular_lookup_type=NoiseType.PERLIN,
        cellular_lookup_frequency=0.3,
    )
    sampler = NumpySampler(params)
    cluster = np.array([100.0, 100.5, 101.0, 100.2], dtype=np.float32)  # well inside one 100-unit cell
    values = sampler.sample_points(
        cluster, np.zeros(4, np.float32), np.full(4, 40.0, np.float32), np.empty(4, np.float32)
    )
    assert np.all(values == values[0]), values
    spread = sampler.sample_points(coords["xs"], coords["ys"], coords["zs"], np.empty(len(coords["xs"]), np.float32))
    assert len(np.unique(spread)) > 100, "many cells, many values"
    assert -1.0 <= spread.min() and spread.max() <= 1.0


# FastNoiseSIMD's Phase C cellular by shape (it jitters cell points onto a sphere and hashes differently, so points
# cannot match; the spread of Natural, NoiseLookup and Distance2Cave must still be the same order) is the harness's:
# the `shape` cases on original/fns/cellular_*/scatter_3d.

#: FastNoiseSIMD's own Simplex, hash and all, so its vectors compare by point: the bounds (the harness's, in
#: tools/gen_noise_vectors.py) are the float32 arithmetic the retired library ran in, growing with the octave sums.
CLASSIC_SIMPLEX_VECTORS = ("simplex_billow", "simplex_fbm", "simplex_none", "simplex_rigidmulti")


@pytest.mark.parametrize("feature", CLASSIC_SIMPLEX_VECTORS)
def test_classic_simplex_matches_fastnoisesimd_by_point(feature, vectors, coords):
    """
    The retired library's Simplex, by name: exact between rungs here, and point for point with the
    FastNoiseSIMD vectors within float32 rounding, in 3D scatter and on the grid, in the harness. The rigidmulti row
    is the one that found F1's alias wrong: under Ridged it correlated 0.5, under RigidMulti it matches.
    """
    case = _original(vectors, "fns", feature, "scatter_3d")
    params = case.params
    n = len(coords["xs"])
    numpy_sampler = NumpySampler(params)
    ours = numpy_sampler.sample_points(coords["xs"], coords["ys"], coords["zs"], np.empty(n, np.float32))
    if HAVE_NUMBA:
        numba_sampler, _ = make_sampler(params, backend="numba")
        assert np.array_equal(
            numba_sampler.sample_points(coords["xs"], coords["ys"], coords["zs"], np.empty(n, np.float32)), ours
        )
        assert np.array_equal(
            numba_sampler.sample_points_2d(coords["xs"], coords["zs"], np.empty(n, np.float32)),
            numpy_sampler.sample_points_2d(coords["xs"], coords["zs"], np.empty(n, np.float32)),
        )
    stats = compare.compare_values(ours, case.values)
    _portability_rows.append(compare.PortabilityRow(f"{feature} (classic, 3D)", "numpy", "fastnoisesimd", stats))


def test_rigidmulti_is_not_ridged_and_is_fastnoisesimd_formula(coords):
    """RigidMulti: 1 - |n| for the first octave, the later octaves subtracted, no bounding; re-derived from
    single-octave samples. And it is not Ridged: the two disagree by far more than rounding."""
    n = 1024
    xs, ys, zs = coords["xs"][:n], coords["ys"][:n], coords["zs"][:n]
    params = NoiseParams(
        seed=21, frequency=0.01, noise_type=NoiseType.PERLIN, fractal_type=FractalType.RIGID_MULTI, octaves=3
    )
    ours = NumpySampler(params).sample_points(xs, ys, zs, np.empty(n, np.float32))
    total = np.zeros(n)
    amp = 1.0
    for i in range(params.octaves):
        octave = params.replace(
            fractal_type=FractalType.NONE, seed=params.seed + i, frequency=params.frequency * params.lacunarity**i
        )
        single = NumpySampler(octave).sample_points(xs, ys, zs, np.empty(n, np.float32)).astype(np.float64)
        total += (1.0 - np.abs(single)) * amp * (1.0 if i == 0 else -1.0)
        amp *= params.gain
    np.testing.assert_allclose(ours, total, atol=2e-4)
    ridged = NumpySampler(params.replace(fractal_type=FractalType.RIDGED)).sample_points(
        xs, ys, zs, np.empty(n, np.float32)
    )
    assert np.abs(ours - ridged).max() > 0.1, "the F1 alias would have been harmless only if these agreed"
    assert parse_fractal_type("rigidmulti") is FractalType.RIGID_MULTI


PERTURB_MODES = ("gradient", "gradientfractal", "normalise", "gradient_normalise", "gradientfractal_normalise")


@pytest.mark.parametrize("mode", PERTURB_MODES)
def test_gradient_perturb_matches_fastnoisesimd_by_point(mode, vectors, coords):
    """
    FastNoiseSIMD's gradient perturb over its classic Simplex FBm, every mode: exact between rungs here, and
    by point with the captured vectors in the harness (float32 rounding; the normalise modes used an approximate
    rsqrt there, which its 1e-3 covers). The record carries the perturb's own frequency and octaves.
    """
    case = _original(vectors, "fns", f"simplex_fbm_perturb_{mode}", "scatter_3d")
    params = case.params
    n = len(coords["xs"])
    numpy_sampler = NumpySampler(params)
    ours = numpy_sampler.sample_points(coords["xs"], coords["ys"], coords["zs"], np.empty(n, np.float32))
    if HAVE_NUMBA:
        numba_sampler, _ = make_sampler(params, backend="numba")
        assert np.array_equal(
            numba_sampler.sample_points(coords["xs"], coords["ys"], coords["zs"], np.empty(n, np.float32)), ours
        )
        assert np.array_equal(
            numba_sampler.sample_points_2d(coords["xs"], coords["zs"], np.empty(n, np.float32)),
            numpy_sampler.sample_points_2d(coords["xs"], coords["zs"], np.empty(n, np.float32)),
        )
    stats = compare.compare_values(ours, case.values)
    _portability_rows.append(
        compare.PortabilityRow(f"simplex_fbm_perturb_{mode} (3D)", "numpy", "fastnoisesimd", stats)
    )
    unperturbed = NumpySampler(params.replace(perturb=PerturbType.NONE)).sample_points(
        coords["xs"], coords["ys"], coords["zs"], np.empty(n, np.float32)
    )
    assert np.abs(ours - unperturbed).max() > 0.05, "the perturb moved the field"


def test_sample_grid_equals_the_points_it_stands_for_and_the_fastnoisesimd_grids(vectors, coords):
    """
    The grid driver (genAsGrid with axis scales): exact against sample_points over the same float32
    coordinates on both rungs, exact between rungs, and by point with the two captured grids. The
    binding padded a 2D start with 1, so its grids sat at z cell 1: that is how they are reproduced.
    """
    from hog_noise.samplers import grid_points

    params = NoiseParams(
        seed=12345, frequency=0.01, noise_type=NoiseType.SIMPLEX_CLASSIC, fractal_type=FractalType.FBM, octaves=4
    )
    start, shape, scales = (-64, 3, -64), (40, 2, 48), (1.0, 0.5, 2.0)
    numpy_sampler = NumpySampler(params)
    grid = numpy_sampler.sample_grid(start, shape, scales)
    assert grid.shape == shape and grid.dtype == np.float32
    xs, ys, zs = grid_points(start, shape, scales)
    assert np.array_equal(grid.ravel(), numpy_sampler.sample_points(xs, ys, zs, np.empty(len(xs), np.float32)))
    if HAVE_NUMBA:
        numba_sampler, _ = make_sampler(params, backend="numba")
        assert np.array_equal(numba_sampler.sample_grid(start, shape, scales), grid)
    for feature, axis_scales in (
        ("genasgrid_simplex_fbm_scales_1.0_1.0_1.0", (1.0, 1.0, 1.0)),
        ("genasgrid_simplex_fbm_scales_1.0_0.5_2.0", (1.0, 0.5, 2.0)),
    ):
        point_set = "genasgrid_" + "_".join(repr(s) for s in axis_scales)
        ref = _original(vectors, "fns", feature, point_set).values  # the design's decision 5: the grid driver itself
        ours = numpy_sampler.sample_grid((-64, -64, 1), (128, 128, 1), axis_scales).ravel()
        err = np.abs(ours - ref)
        assert err.max() < 2e-3 and np.mean(err < 1e-4) > 0.98, f"{feature}: max {err.max():.2e}"


RENDERINGS = ["numpy"] + (["numba"] if HAVE_NUMBA else [])


@pytest.mark.parametrize("rendering", RENDERINGS)
def test_the_renderings_pass_every_gating_case_and_the_hog_set(rendering, vectors):
    """Every hog case at Bound(0) and every gating original, through the harness. Passing hog on numpy is also the
    staleness check: a kernel change that moves a value fails here until `gen_noise_vectors.py --set hog` is rerun."""
    sample, warp = conformance.renderings(rendering)
    report = conformance.check(sample, vectors, reference="both", warp=warp)
    assert report.ok and report.complete, report.table()


def _fastnoiselite_available() -> bool:
    try:
        import pyfastnoiselite.pyfastnoiselite  # noqa: F401
    except ImportError:
        return False
    return True


@pytest.mark.skipif(
    not _fastnoiselite_available(), reason="pyfastnoiselite not installed; the binding rung is optional"
)
def test_fastnoiselite_rung_answers_billow_through_the_numpy_base(coords):
    """The binding has no Billow, so its rung delegates to the numpy base: scalar, 2D and 3D must equal it."""
    from hog_noise import FastNoiseLiteSampler

    params = NoiseParams(
        seed=7, frequency=0.01, noise_type=NoiseType.PERLIN, fractal_type=FractalType.BILLOW, octaves=3
    )
    binding = FastNoiseLiteSampler(params)
    base = NumpySampler(params)
    n = 512
    xs, ys, zs = coords["xs"][:n], coords["ys"][:n], coords["zs"][:n]
    assert np.array_equal(
        binding.sample_points(xs, ys, zs, np.empty(n, np.float32)),
        base.sample_points(xs, ys, zs, np.empty(n, np.float32)),
    )
    assert np.array_equal(
        binding.sample_points_2d(xs, zs, np.empty(n, np.float32)),
        base.sample_points_2d(xs, zs, np.empty(n, np.float32)),
    )
    assert binding.sample(10.0, 20.0, 30.0) == base.sample(10.0, 20.0, 30.0)


@pytest.mark.parametrize("mode", ["normalise", "gradient_normalise", "gradientfractal_normalise"])
def test_normalise_perturb_keeps_the_origin_finite_and_exact_between_rungs(mode, coords):
    """
    Regression (the gallery, 2026-10-02): the normalise modes divided by the point's length, zero at the
    origin. The numba thread raised inside its prange chunk and four rows came back as zeros; the numpy
    base made NaN and hashed it. A zero-length point now stays at the origin on both rungs, and a grid
    through the origin is finite and exact.
    """
    params = NoiseParams(
        seed=3,
        frequency=0.03,
        noise_type=NoiseType.SIMPLEX_CLASSIC,
        perturb=parse_perturb(mode),
        perturb_normalise_length=30.0,
    )
    base = NumpySampler(params)
    grid = base.sample_grid((-4, 0, -4), (9, 1, 9))
    assert np.isfinite(grid).all()
    assert (
        grid[4, 0, 4]
        == base.sample_points(
            np.zeros(1, np.float32), np.zeros(1, np.float32), np.zeros(1, np.float32), np.empty(1, np.float32)
        )[0]
    )
    if HAVE_NUMBA:
        numba_sampler, _ = make_sampler(params, backend="numba")
        assert np.array_equal(numba_sampler.sample_grid((-4, 0, -4), (9, 1, 9)), grid)
        wide = numba_sampler.sample_grid((-48, 0, -48), (96, 1, 96))
        assert np.array_equal(wide, base.sample_grid((-48, 0, -48), (96, 1, 96))) and np.isfinite(wide).all()


def test_write_portability_table():
    """Runs last in this module: regenerates the portability table from what the tests measured."""
    from hog_noise.samplers import _have_fastnoiselite

    if not _portability_rows:
        pytest.skip("no comparisons ran")
    if not (HAVE_NUMBA and _have_fastnoiselite()):
        # The committed table lists every rung pair. A run without numba or the binding measures fewer rows, and
        # writing them would silently replace the full table in the working tree with a partial one.
        pytest.skip("partial environment: the committed table is regenerated only when every rung was compared")
    path = compare.write_portability(_portability_rows, PORTABILITY)
    text = path.read_text(encoding="utf-8")
    assert "| Feature |" in text and ("numba" in text or "numpy" in text)


# -------------------------------------------------------------------------
# API and parameter behaviour
def test_unimplemented_features_say_which_phase():
    assert parse_noise_type("simplex_smooth") is NoiseType.OPEN_SIMPLEX2S  # Phase B, landed
    assert parse_fractal_type("domain_warp_progressive") is FractalType.DOMAIN_WARP_PROGRESSIVE  # Phase B, landed
    assert parse_fractal_type("billow") is FractalType.BILLOW  # Phase C, landed
    with pytest.raises(ValueError):
        parse_noise_type("noise_of_the_spheres")


def test_kernel_args_order_is_stable():
    p = NoiseParams(seed=5, frequency=0.02, noise_type=NoiseType.PERLIN, fractal_type=FractalType.RIDGED, octaves=3)
    args = p.kernel_args()
    assert args[:5] == (5, 0.02, int(NoiseType.PERLIN), int(FractalType.RIDGED), 3)
    assert args[13] == 0, "perlin gets no 3D rotation by default"
    assert NoiseParams(noise_type=NoiseType.OPEN_SIMPLEX2).kernel_args()[13] == 3, (
        "OpenSimplex2 gets its default rotation"
    )
    assert args[10:13] == (1, 1, 1.0), "reference cellular defaults: EuclideanSq, Distance, jitter 1"
    assert args[14:18] == (0, p.fractal_bounding, 0, 0), (
        "warp off: no type, amp is bounding alone, single, no transform"
    )
    warped = NoiseParams(
        noise_type=NoiseType.PERLIN,
        fractal_type=FractalType.DOMAIN_WARP_INDEPENDENT,
        octaves=3,
        domain_warp=DomainWarpType.OPEN_SIMPLEX2,
        domain_warp_amp=20.0,
    ).kernel_args()
    assert warped[3] == int(FractalType.NONE), "the warp fractals leave the noise single-octave, as the reference does"
    assert warped[14:18] == (1, 20.0 * NoiseParams(octaves=3).fractal_bounding, 2, 3), (
        "OpenSimplex2 warp, amplitude scaled by bounding, independent, the warp's default rotation"
    )


def test_fractal_bounding_matches_the_reference_formula():
    p = NoiseParams(octaves=4, gain=0.5, fractal_type=FractalType.FBM)
    assert p.fractal_bounding == pytest.approx(1.0 / (1 + 0.5 + 0.25 + 0.125))


def test_seed_is_wrapped_to_int32_like_the_reference(coords):
    """A seed beyond int32 must give the same noise as its wrapped value, not a crash or new noise."""
    big = 2**31 + 17
    wrapped = ((big + 2**31) % 2**32) - 2**31
    a = NumpySampler(NoiseParams(seed=big)).sample_points(
        coords["xs"][:32], coords["ys"][:32], coords["zs"][:32], np.empty(32, np.float32)
    )
    b = NumpySampler(NoiseParams(seed=wrapped)).sample_points(
        coords["xs"][:32], coords["ys"][:32], coords["zs"][:32], np.empty(32, np.float32)
    )
    assert np.array_equal(a, b)


def test_ladder_picks_the_best_available_and_override_is_honoured(monkeypatch):
    params = NoiseParams()
    _, selection = make_sampler(params)
    # The reference binding is override-only, so the choice never depends on whether it is installed.
    assert selection.backend.name == ("numba" if HAVE_NUMBA else "numpy")
    monkeypatch.setenv("HOG_NOISE_BACKEND_NOISE", "numpy")
    sampler, selection = make_sampler(params)
    assert selection.backend.name == "numpy" and sampler.name == "numpy"


def test_the_retired_legacy_rung_is_gone_and_an_override_never_falls_through(monkeypatch):
    """
    The pre-port ``legacy_numpy`` rung belonged to LargeWorlds and was not carried over. Naming it must
    raise, never fall through to another rung (the ladder's explicit-override rule).
    """
    from hog_noise.backends import BackendUnavailable

    params = NoiseParams(noise_type=NoiseType.PERLIN, fractal_type=FractalType.FBM, octaves=2)
    monkeypatch.setenv("HOG_NOISE_BACKEND_NOISE", "legacy_numpy")
    with pytest.raises(BackendUnavailable):
        make_sampler(params)


# -------------------------------------------------------------------------
# performance and warm start
@pytest.mark.skipif(not HAVE_NUMBA, reason="numba not installed")
def test_bin_sized_batch_meets_the_budget(coords):
    """
    One 4096-point, 4-octave OpenSimplex2 batch: the world loop's unit of work. Measured 0.07 ms on
    the reference workstation (Docs/PYTHON_UPGRADE_AND_FASTNOISE.md 2.1: FastNoiseSIMD 0.06 ms).
    The bar is loose enough for CI hardware, tight enough to catch a fallback to the numpy base.
    """
    params = NoiseParams(seed=1, frequency=0.001, fractal_type=FractalType.FBM, octaves=4)
    sampler, _ = make_sampler(params, backend="numba")
    out = np.empty(4096, np.float32)
    sampler.sample_points(coords["xs"], coords["ys"], coords["zs"], out)  # compile / cache load
    best = min(_timed(sampler, coords, out) for _ in range(9))
    assert best < 1.0, f"4096-point 4-octave batch took {best * 1000:.2f} ms; expected well under 1 ms"


def _timed(sampler, coords, out):
    t = time.perf_counter()
    sampler.sample_points(coords["xs"], coords["ys"], coords["zs"], out)
    return time.perf_counter() - t


@pytest.mark.slow
@pytest.mark.skipif(not HAVE_NUMBA, reason="numba not installed")
def test_warm_start_from_cache_is_fast():
    """Second process pays cache load, not compilation: under 1.5 s (measured 0.26 s warm)."""
    code = "import time; import hog_noise as nk; t=time.perf_counter(); nk.warm_up(); print(time.perf_counter()-t)"
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(sys.path)
    subprocess.run([sys.executable, "-c", code], check=True, capture_output=True, text=True, env=env)  # prime the cache
    second = subprocess.run([sys.executable, "-c", code], check=True, capture_output=True, text=True, env=env)
    elapsed = float(second.stdout.strip().splitlines()[-1])
    assert elapsed < 1.5, f"warm-up from cache took {elapsed:.2f} s"


def test_scalar_and_vectorized_expose_the_same_driver_signatures():
    import inspect

    for name in ("sample_2d", "sample_3d", "warp_2d", "warp_3d", "sample_grid"):
        s = inspect.signature(getattr(vectorized, name))
        k = getattr(scalar, name)
        k_params = (
            list(k.py_func.__code__.co_varnames[: k.py_func.__code__.co_argcount])
            if hasattr(k, "py_func")
            else list(inspect.signature(k).parameters)
        )
        assert list(s.parameters) == k_params, name
