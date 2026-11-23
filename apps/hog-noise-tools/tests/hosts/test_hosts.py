"""
HogNoise tools: every host harness against the vectors, judged by the wgpu rung's tolerance file, with its controls.
Each host runs where its library and device exist; it skips with the reason elsewhere, and fails instead of skipping
when HOG_NOISE_REQUIRE_HOST names it (CI's host legs), so a leg that loses its host cannot go green.
Package: apps/hog-noise-tools/tests/hosts/test_hosts
"""

import os

import numpy as np
import pytest

from hog_noise import FractalType, NoiseParams, conformance
from hog_noise.conformance import Bound
from hog_noise_tools import hosts
from hog_noise_tools.repo import VECTORS

REQUIRED = {h.strip() for h in os.environ.get(hosts.REQUIRE_ENV, "").split(",") if h.strip()}
TOLERANCE = VECTORS / "tolerance" / "wgpu.json"


def test_every_required_host_is_known():
    """A misspelt name in HOG_NOISE_REQUIRE_HOST would require nothing, and the leg would go green on skips."""
    assert REQUIRED <= set(hosts.HOSTS), sorted(REQUIRED - set(hosts.HOSTS))


@pytest.fixture(scope="module", params=sorted(hosts.HOSTS))
def host(request):
    """The host, or a skip (a failure when HOG_NOISE_REQUIRE_HOST names it) naming why it is not here."""
    try:
        return hosts.open_host(request.param)
    except hosts.HostUnavailable as e:
        if request.param in REQUIRED:
            pytest.fail(f"{hosts.REQUIRE_ENV} names {request.param}, but {e}")
        pytest.skip(f"{request.param}: {e}")


@pytest.fixture(scope="module")
def judged():
    vectors = conformance.load(VECTORS)
    return vectors, conformance.Tolerance.load(TOLERANCE, vectors)


def test_every_hog_case_passes_within_the_wgpu_tolerance(host, judged):
    """The spec's acceptance: every hog case, every entry point, nothing unsupported, the file unmodified."""
    vectors, tolerance = judged
    sample, warp, grid = hosts.renderings(host)
    report = conformance.check(sample, vectors, warp=warp, grid=grid, tolerance=tolerance)
    print(f"{host.name}: {host.target}")
    assert report.ok and report.complete, report.table()


def test_a_seed_off_by_one_fails(host, judged):
    vectors, tolerance = judged
    sample, _, _ = hosts.renderings(host)

    def off(params, xs, ys, zs):
        return sample(params.replace(seed=params.seed + 1), xs, ys, zs)

    assert not conformance.check(off, vectors, tolerance=tolerance, select="hog/fnl/simplex_fbm/*").ok


def test_a_rule_at_0_9_of_its_worst_fails(host, judged):
    """The rule is tight enough to matter on this host. A host with no drift on the feature cannot show it: say so."""
    vectors, tolerance = judged
    sample, _, _ = hosts.renderings(host)
    feature = "fnl/simplex_fbm"
    unit = Bound(1.0, coordinate_scaled=True)
    worst = 0.0
    for case in (c for c in vectors.cases if c.id.startswith(f"hog/{feature}/")):
        ps = vectors.point_sets[case.point_set]
        ours = sample(case.params, ps.axes[0], ps.axes[1], ps.axes[2] if ps.dims == 3 else None)
        diff = np.abs(np.asarray(ours, np.float64) - case.values.astype(np.float64))
        worst = max(worst, float((diff / unit.per_point(case.params.frequency, ps.axes)).max()))
    assert worst > 0.0, f"{host.name} has no drift on {feature}: choose another feature for this control"
    rules = dict(tolerance.rules)
    rules[(feature, None)] = dict(rules[(feature, None)], bound={"scale": 0.9 * worst, "coordinate_scaled": True})
    tight = conformance.Tolerance(tolerance.rendering, tolerance.range, rules)
    assert not conformance.check(sample, vectors, tolerance=tight, select=f"hog/{feature}/*").ok


def test_a_host_told_another_target_refuses(host):
    """P-22's control: the target check fails when the host is told to expect an adapter it is not on."""
    with pytest.raises(hosts.HostTargetError, match="no adapter is called this"):
        hosts.open_host(host.name, target="no adapter is called this")


def test_a_power_of_two_grid_equals_its_points_bit_for_bit(host):
    """sample_grid computes its coordinates in the shader; at scale 1 they are exact, so grid and points agree."""
    from hog_noise.samplers import grid_points

    s = hosts.HostSampler(NoiseParams(frequency=0.01), host)
    start, shape = (-64, -64, 1), (128, 128, 1)
    xs, ys, zs = grid_points(start, shape)
    points = s.sample_points(xs, ys, zs, np.empty(len(xs), np.float32))
    assert np.array_equal(s.sample_grid(start, shape).ravel(), points)


def test_a_dispatch_past_65535_workgroups_reaches_its_last_points(host, judged):
    """The README's y stride: the last 64 points, alone in the second row of workgroups, are written and right."""
    from hog_noise import NumpySampler

    vectors, tolerance = judged
    case = next(c for c in vectors.cases if c.id.startswith("hog/fnl/value_none/"))
    params, rule = case.params, tolerance.rule_for(case)
    i = np.arange(hosts.MAX_GROUPS * hosts.WORKGROUP + hosts.WORKGROUP)
    xs, ys, zs = (((i % m) - m // 2).astype(np.float32) for m in (4093, 4091, 4099))
    assert hosts.workgroups(len(xs)) == (65535, 2, 1)
    ours = hosts.HostSampler(params, host).sample_points(xs, ys, zs, np.empty(len(xs), np.float32))[-64:]
    tail = tuple(a[-64:] for a in (xs, ys, zs))
    numpy = NumpySampler(params).sample_points(*tail, np.empty(64, np.float32))
    allowed = Bound(**rule["bound"]).per_point(params.frequency, tail)
    diff = np.abs(ours.astype(np.float64) - numpy.astype(np.float64))
    assert rule["rule"] == "continuous" and np.all(diff <= allowed), diff.max()


def test_spirv_naga_is_the_wgpu_rung_bit_for_bit(host):
    """
    The spec's first fact, as a test: naga reads the shipped SPIR-V back into the IR it made the WGSL from, so on one
    device the two agree exactly, for every entry point. A seed off by one does not, so the comparison can fail.
    """
    if host.name != "spirv-naga":
        pytest.skip("the bit-for-bit claim is spirv-naga's alone: another compiler differs by its rounding")
    from hog_noise import gpu

    rng = np.random.default_rng(20261122)
    xs, ys, zs = (rng.uniform(-4096, 4096, 4096).astype(np.float32) for _ in range(3))
    for params in (NoiseParams(frequency=0.01), NoiseParams(frequency=0.01, octaves=4, fractal_type=FractalType.FBM)):
        ours, theirs = hosts.HostSampler(params, host), gpu.GpuSampler(params)
        off = hosts.HostSampler(params.replace(seed=params.seed + 1), host)
        out = lambda: np.empty(len(xs), np.float32)  # noqa: E731
        pairs = [
            (ours.sample_points(xs, ys, zs, out()), theirs.sample_points(xs, ys, zs, out())),
            (ours.sample_points_2d(xs, ys, out()), theirs.sample_points_2d(xs, ys, out())),
            (ours.warp_points(xs, ys, zs), theirs.warp_points(xs, ys, zs)),
            (ours.warp_points_2d(xs, ys), theirs.warp_points_2d(xs, ys)),
            (ours.sample_grid((-8, -8, 0), (16, 16, 1)), theirs.sample_grid((-8, -8, 0), (16, 16, 1))),
        ]
        entries = ("sample_points_3d", "sample_points_2d", "warp_points_3d", "warp_points_2d", "sample_grid")
        differ = []
        for entry, (a, b) in zip(entries, pairs, strict=True):
            if not np.array_equal(a, b):
                diff = np.abs(a.astype(np.float64) - b.astype(np.float64))
                differ.append(f"{entry}: {int((diff > 0).sum())} of {diff.size} differ, largest {diff.max():.3g}")
        assert not differ, f"{host.target}, octaves={params.octaves}: " + "; ".join(differ)
        assert not np.array_equal(off.sample_points(xs, ys, zs, out()), pairs[0][1])


def test_a_gl_host_builds_after_wgpu_has_enumerated_its_adapters():
    """
    The spec's third fact, as a test, in its order: a GL context exists, wgpu then enumerates its adapters (its OpenGL
    back end among them, which can leave its own context current), and only then does the GL host build its programs.
    They build and run because the host makes its context current first. A context of its own, not the shared one, so
    the order is this test's and not the fixtures'.
    """
    from hog_noise_tools.hosts import glsl

    try:
        import wgpu
    except ImportError as e:
        if "glsl" in REQUIRED:  # the glsl job installs wgpu for this test alone: losing it must not go green
            pytest.fail(f"{hosts.REQUIRE_ENV} names glsl, and this test needs wgpu beside it: {e}")
        pytest.skip(f"needs wgpu: {e}")
    try:
        ctx = glsl.context()
    except hosts.HostUnavailable as e:
        if "glsl" in REQUIRED:
            pytest.fail(f"{hosts.REQUIRE_ENV} names glsl, but {e}")
        pytest.skip(f"glsl: {e}")
    wgpu.gpu.enumerate_adapters_sync()
    host = glsl.Glsl(ctx)
    xs = np.linspace(-100, 100, 64, dtype=np.float32)
    values = hosts.HostSampler(NoiseParams(frequency=0.01), host).sample_points_2d(xs, xs, np.empty(64, np.float32))
    assert np.isfinite(values).all() and values.std() > 0
