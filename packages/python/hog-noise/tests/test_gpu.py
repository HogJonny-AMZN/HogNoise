"""
HogNoise: the wgpu rung. Runs where wgpu and an adapter exist; skips with the reason elsewhere, and fails instead of
skipping under HOG_NOISE_REQUIRE_GPU=1 (the software-adapter CI legs), so a leg that loses its adapter cannot go green.
Package: packages/python/hog-noise/tests/test_gpu
"""

import math
import os
import struct

import numpy as np
import pytest
from hog_noise_repo import VECTORS

from hog_noise import FractalType, NoiseParams, conformance, gpu, make_sampler
from hog_noise.conformance import Bound

REQUIRE_GPU = os.environ.get("HOG_NOISE_REQUIRE_GPU") == "1"


@pytest.fixture(scope="module")
def device():
    """The process's device, or a skip (a failure under HOG_NOISE_REQUIRE_GPU=1) naming why there is none."""
    try:
        return gpu.device()
    except RuntimeError as e:
        if REQUIRE_GPU:
            pytest.fail(f"HOG_NOISE_REQUIRE_GPU=1, but {e}")
        pytest.skip(str(e))


PROBE = """
@group(0) @binding(0) var<storage, read_write> OUT : array<f32>;

@compute @workgroup_size(64)
fn main(@builtin(global_invocation_id) id : vec3<u32>) {
    if (id.x < arrayLength(&OUT)) {
        OUT[id.x] = f32(id.x) * 0.5;
    }
}
"""


def test_a_device_dispatches_one_pipeline(device):
    """The CI probe: a device exists here and runs a compute pass end to end."""
    import wgpu

    n = 100
    out = device.create_buffer(size=n * 4, usage=wgpu.BufferUsage.STORAGE | wgpu.BufferUsage.COPY_SRC)
    module = device.create_shader_module(code=PROBE)
    pipeline = device.create_compute_pipeline(layout="auto", compute={"module": module, "entry_point": "main"})
    group = device.create_bind_group(
        layout=pipeline.get_bind_group_layout(0),
        entries=[{"binding": 0, "resource": {"buffer": out, "offset": 0, "size": out.size}}],
    )
    encoder = device.create_command_encoder()
    compute = encoder.begin_compute_pass()
    compute.set_pipeline(pipeline)
    compute.set_bind_group(0, group)
    compute.dispatch_workgroups(math.ceil(n / 64))
    compute.end()
    device.queue.submit([encoder.finish()])
    values = np.frombuffer(device.queue.read_buffer(out), dtype=np.float32)
    assert values.tolist() == [i * 0.5 for i in range(n)]
    info = gpu.adapter_info()
    assert info["device"], info
    print(f"adapter: {info}")


def test_without_wgpu_or_an_adapter_the_reason_is_named(monkeypatch):
    """The probe's failure carries its cause, which is what the ladder will show."""
    monkeypatch.delitem(gpu._STATE, "device", raising=False)  # restored after the test, so the device is kept
    monkeypatch.setenv(gpu.ADAPTER_ENV, "no adapter is called this")
    try:
        import wgpu  # noqa: F401
    except ImportError:
        with pytest.raises(RuntimeError, match=r"wgpu is not installed: install hog-noise\[gpu\]"):
            gpu.device()
        return
    with pytest.raises(RuntimeError, match="no adapter: none named like 'no adapter is called this'"):
        gpu.device()


def test_param_kinds_follow_kernel_args_types():
    for params in (NoiseParams(), NoiseParams(fractal_type=FractalType.DOMAIN_WARP_PROGRESSIVE)):
        args = params.kernel_args()
        assert len(gpu.PARAM_KINDS) == len(args) == 27
        for kind, value in zip(gpu.PARAM_KINDS, args, strict=True):
            assert (kind == "i") == (isinstance(value, int) and not isinstance(value, bool)), (kind, value)


def test_the_uniform_packs_every_kernel_arg_in_order_with_the_seed_wrapped():
    params = NoiseParams(seed=2**40 + 5, frequency=0.02, octaves=3, lacunarity=2.5, gain=0.4)
    data = gpu.pack_params(params)
    assert len(data) == 112  # 27 four-byte fields, padded to 16
    values = struct.unpack("<" + gpu.PARAM_KINDS, data[:108])
    assert values[0] == 5
    for kind, got, want in zip(gpu.PARAM_KINDS[1:], values[1:], params.kernel_args()[1:], strict=True):
        assert got == (int(want) if kind == "i" else float(np.float32(want)))


def test_the_grid_uniform_packs_start_shape_and_scales():
    data = gpu.pack_grid((-64, -64, 1), (128, 128, 1), (0.7, 1.0, 1.3))
    assert len(data) == 48
    assert struct.unpack("<iiiIIIfff", data[:36]) == (-64, -64, 1, 128, 128, 1, np.float32(0.7), 1.0, np.float32(1.3))


@pytest.mark.parametrize(
    "n, groups", [(1, (1, 1, 1)), (64, (1, 1, 1)), (65, (2, 1, 1)), (65535 * 64 + 1, (65535, 2, 1))]
)
def test_a_dispatch_past_65535_workgroups_wraps_into_y(n, groups):
    assert gpu._workgroups(n) == groups


def test_more_than_32_octaves_is_refused_as_not_implemented_before_any_device():
    with pytest.raises(NotImplementedError, match="octaves=33"):
        gpu.GpuSampler(NoiseParams(octaves=33))
    with pytest.raises(NotImplementedError, match="perturb_octaves=40"):
        gpu.GpuSampler(NoiseParams(perturb_octaves=40))


def test_axes_of_unequal_length_are_refused_before_any_device():
    """WGSL's robust access would clamp a short axis to its last value, silently: the lengths are checked first."""
    xs, short = np.zeros(4, np.float32), np.zeros(3, np.float32)
    assert gpu._point_count((xs, xs, xs)) == 4
    assert gpu._point_count((xs, xs), np.empty(4, np.float32)) == 4
    with pytest.raises(ValueError, match=r"\[4, 3, 4\]"):
        gpu._point_count((xs, short, xs))
    with pytest.raises(ValueError, match="out has 3"):
        gpu._point_count((xs, xs), short)


@pytest.mark.parametrize(
    "call",
    [
        lambda s, a, b: s.sample_points(a, b, a, np.empty(len(a), np.float32)),
        lambda s, a, b: s.sample_points_2d(a, b, np.empty(len(a), np.float32)),
        lambda s, a, b: s.sample_points(a, a, a, np.empty(len(b), np.float32)),
        lambda s, a, b: s.warp_points(a, b, a),
        lambda s, a, b: s.warp_points_2d(a, b),
    ],
    ids=["sample_points", "sample_points_2d", "out", "warp_points", "warp_points_2d"],
)
def test_every_entry_point_refuses_a_short_axis(device, call):
    sampler = gpu.GpuSampler(NoiseParams(frequency=0.01))
    xs = np.linspace(-10, 10, 100, dtype=np.float32)
    with pytest.raises(ValueError, match="100"):
        call(sampler, xs, xs[:99])


def test_the_rung_is_registered_override_only():
    from hog_noise.backends import registered

    rung = {b.name: b for b in registered("noise")}["wgpu"]
    assert rung.priority == -20 and rung.factory is gpu.GpuSampler


def test_an_installed_wgpu_never_changes_the_ladder(device):
    """Acceptance 5: with wgpu and an adapter here, the ladder still chooses numba or numpy."""
    _, selection = make_sampler(NoiseParams())
    assert selection.backend.name in ("numba", "numpy")
    assert ("wgpu", "override-only rung") in selection.skipped


TOLERANCE = VECTORS / "tolerance" / "wgpu.json"


@pytest.fixture(scope="module")
def judged(device):
    vectors = conformance.load(VECTORS)
    return vectors, conformance.Tolerance.load(TOLERANCE, vectors)


def test_the_rung_passes_every_hog_case_against_its_tolerance(judged):
    """Acceptance 1 (and 2, run on the owner's GPU): every feature, every entry point, nothing unsupported."""
    vectors, tolerance = judged
    sample, warp = conformance.renderings("wgpu")
    report = conformance.check(sample, vectors, warp=warp, grid=conformance.grid_rendering("wgpu"), tolerance=tolerance)
    print(f"adapter: {gpu.adapter_info()}")
    assert report.ok and report.complete, report.table()


def test_a_seed_off_by_one_fails(judged):
    vectors, tolerance = judged
    sample, _ = conformance.renderings("wgpu")

    def off(params, xs, ys, zs):
        return sample(params.replace(seed=params.seed + 1), xs, ys, zs)

    assert not conformance.check(off, vectors, tolerance=tolerance, select="hog/fnl/simplex_fbm/*").ok


def test_a_rule_at_0_9_of_its_worst_fails(judged):
    """Acceptance 3: the rule is tight enough to matter. The worst is this adapter's own, so the test holds anywhere."""
    vectors, tolerance = judged
    sample, _ = conformance.renderings("wgpu")
    feature = "fnl/simplex_fbm"
    unit = Bound(1.0, coordinate_scaled=True)
    worst = 0.0
    for case in (c for c in vectors.cases if c.id.startswith(f"hog/{feature}/")):
        ps = vectors.point_sets[case.point_set]
        ours = sample(case.params, ps.axes[0], ps.axes[1], ps.axes[2] if ps.dims == 3 else None)
        diff = np.abs(np.asarray(ours, np.float64) - case.values.astype(np.float64))
        worst = max(worst, float((diff / unit.per_point(case.params.frequency, ps.axes)).max()))
    assert worst > 0.0, "a feature with no drift here cannot show the rule failing; choose another"
    rules = dict(tolerance.rules)
    rules[(feature, None)] = dict(rules[(feature, None)], bound={"scale": 0.9 * worst, "coordinate_scaled": True})
    tight = conformance.Tolerance(tolerance.rendering, tolerance.range, rules)
    assert not conformance.check(sample, vectors, tolerance=tight, select=f"hog/{feature}/*").ok
    # the same worst as a continuous rule's within, under its own outer bound: the tight tier bites too
    within = {"scale": 0.9 * worst, "coordinate_scaled": True, "fraction": 1.0}
    rules[(feature, None)] = dict(tolerance.rules[(feature, None)], within=within)
    two_tier = conformance.Tolerance(tolerance.rendering, tolerance.range, rules)
    report = conformance.check(sample, vectors, tolerance=two_tier, select=f"hog/{feature}/*")
    assert not report.ok and all("past the bound" not in r.detail for r in report.results), report.table()


def test_more_than_32_octaves_reports_unsupported_and_the_run_continues(judged):
    vectors, tolerance = judged
    sample, _ = conformance.renderings("wgpu")

    def deep(params, xs, ys, zs):
        return sample(params.replace(octaves=33), xs, ys, zs)

    report = conformance.check(deep, vectors, tolerance=tolerance, select="hog/fnl/simplex_*/scatter_3d")
    assert len(report.results) > 1 and all(r.status == "unsupported" for r in report.results)
    assert report.ok and not report.complete


def test_every_feature_builds_a_sampler(device):
    """No feature is left unported: every hog case's parameters build a GpuSampler."""
    vectors = conformance.load(VECTORS, sets="hog")
    for params in {case.params for case in vectors.cases}:
        gpu.GpuSampler(params)


def test_every_pipeline_builds(device):
    """The spec's *The shader*: naga validates noise.wgsl and all five pipelines build, on any adapter."""
    assert set(gpu._Gpu.get().pipelines) == set(gpu.ENTRY_POINTS)


def test_a_power_of_two_grid_equals_its_points_bit_for_bit(device):
    """sample_grid computes its coordinates on the GPU; at scale 1 they are exact, so grid and points agree exactly."""
    from hog_noise.samplers import grid_points

    sampler = gpu.GpuSampler(NoiseParams(frequency=0.01))
    start, shape = (-64, -64, 1), (128, 128, 1)
    xs, ys, zs = grid_points(start, shape)
    points = sampler.sample_points(xs, ys, zs, np.empty(len(xs), np.float32))
    assert np.array_equal(sampler.sample_grid(start, shape).ravel(), points)


def test_a_dispatch_past_65535_workgroups_reaches_its_last_points(judged):
    """
    noise.wgsl's ``point_index`` strides y by ``65535u * 64u``, which must be `gpu._MAX_GROUPS` times `gpu.WORKGROUP`:
    the last 64 points, the only ones in the second row of workgroups, match the numpy rendering by the feature's rule.
    A stride of ``65536u * 64u`` leaves them unwritten and fails here (tried); a smaller one only computes some points
    twice, with the same values. Value noise, one octave, is the cheapest feature: about 5 s on WARP once the pipelines
    are built, 4,194,304 points.
    """
    from hog_noise import NumpySampler

    vectors, tolerance = judged
    case = next(c for c in vectors.cases if c.id.startswith("hog/fnl/value_none/"))
    params, rule = case.params, tolerance.rule_for(case)
    i = np.arange(gpu._MAX_GROUPS * gpu.WORKGROUP + gpu.WORKGROUP)
    # distinct at every point, so a point read from the wrong index has another value; inside the measured range
    xs, ys, zs = (((i % m) - m // 2).astype(np.float32) for m in (4093, 4091, 4099))
    assert gpu._workgroups(len(xs)) == (65535, 2, 1)
    ours = gpu.GpuSampler(params).sample_points(xs, ys, zs, np.empty(len(xs), np.float32))[-64:]
    tail = tuple(a[-64:] for a in (xs, ys, zs))
    numpy = NumpySampler(params).sample_points(*tail, np.empty(64, np.float32))
    allowed = Bound(**rule["bound"]).per_point(params.frequency, tail)
    diff = np.abs(ours.astype(np.float64) - numpy.astype(np.float64))
    assert rule["rule"] == "continuous" and np.all(diff <= allowed), diff.max()


def test_the_limit_is_the_devices_own(device):
    """The smaller of the two limits a call's buffers meet: one storage binding, and one buffer."""
    limits = device.limits
    expected = min(limits["max-storage-buffer-binding-size"], limits["max-buffer-size"])
    assert gpu._Gpu.get().binding_limit == expected


#: WebGPU's default binding limit, 128 MiB, put in place of the device's own (2 GiB on the adapters measured): the
#: refusal is the same code at any limit, and a call past this one needs no memory to build.
SMALL_LIMIT = 134_217_728


class Uploaded(Exception):
    """A call reached its first upload: the limit's check let it through."""


@pytest.fixture
def small(device, monkeypatch):
    """
    A sampler on the process's `gpu._Gpu`, its limit lowered to `SMALL_LIMIT`. The sampler is made first, since making
    it uploads its own `Params`; then every upload, storage and uniform, is stopped: a call that reaches one has been
    let through the check, and nothing is computed either way.
    """
    gpu_ = gpu._Gpu.get()
    monkeypatch.setattr(gpu_, "binding_limit", SMALL_LIMIT)
    sampler = gpu.GpuSampler(NoiseParams(frequency=0.01))

    def stop(data):
        raise Uploaded

    monkeypatch.setattr(gpu_, "storage", stop)
    monkeypatch.setattr(gpu_, "uniform", stop)
    return sampler


def _lazy(n):
    """``n`` float32 zeros that take no memory: a call past the limit is refused before it reads them."""
    return np.broadcast_to(np.float32(0), (n,))


CALLS = {
    "sample_points": (1, lambda s, a: s.sample_points(a, a, a, _lazy(len(a)))),
    "sample_points_2d": (1, lambda s, a: s.sample_points_2d(a, a, _lazy(len(a)))),
    "sample_grid": (1, lambda s, a: s.sample_grid((0, 0, 0), (len(a), 1, 1))),
    "warp_points": (3, lambda s, a: s.warp_points(a, a, a)),
    "warp_points_2d": (2, lambda s, a: s.warp_points_2d(a, a)),
}


@pytest.mark.parametrize("name", list(CALLS))
def test_a_call_past_the_devices_limit_is_refused_before_any_upload(small, name):
    """
    Past the limit wgpu refuses too, but in its own terms (a buffer size, a binding number) that differ by backend,
    and only after the axes are uploaded. The refusal names the call, the most points it takes and the adapter, and
    comes before any upload: an axis's, and `sample_grid`'s `Grid`.
    """
    width, call = CALLS[name]
    most = SMALL_LIMIT // (4 * width)
    with pytest.raises(ValueError, match=f"past the {most:,} one call can take on .+ split the call"):
        call(small, _lazy(most + 1))


@pytest.mark.parametrize("name", ["sample_points_2d", "sample_grid", "warp_points"])
def test_a_call_at_the_devices_limit_is_let_through(small, name):
    """Not one point early: a call writing exactly the limit's bytes passes the check and reaches its upload."""
    width, call = CALLS[name]
    with pytest.raises(Uploaded):
        call(small, _lazy(SMALL_LIMIT // (4 * width)))
