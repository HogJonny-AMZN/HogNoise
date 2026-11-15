"""
HogNoise: the wgpu rung. Runs where wgpu and an adapter exist; skips with the reason elsewhere, and fails instead of
skipping under HOG_NOISE_REQUIRE_GPU=1 (the software-adapter CI legs), so a leg that loses its adapter cannot go green.
Package: packages/python/hog-noise/tests/test_gpu
"""

import fnmatch
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


def test_the_rung_is_registered_override_only():
    from hog_noise.backends import registered

    rung = {b.name: b for b in registered("noise")}["wgpu"]
    assert rung.priority == -20 and rung.factory is gpu.GpuSampler


def test_an_installed_wgpu_never_changes_the_ladder(device):
    """Acceptance 5: with wgpu and an adapter here, the ladder still chooses numba or numpy."""
    _, selection = make_sampler(NoiseParams())
    assert selection.backend.name in ("numba", "numpy")
    assert ("wgpu", "override-only rung") in selection.skipped


#: The port's working check, ~50x the spike's measured drift. The measured rules replace it in Task 15.
DEV_SCALE = 1e-4
#: Features whose output jumps where float32 flips a choice: held at 99% of points during the port. A grid's points
#: sit on the lattice, where a corner choice ties and float32 and float64 round it apart (owner's decision, 2026-11-14).
DEV_DISCRETE = ("cellvalue", "noiselookup", "whitenoise", "genasgrid")


def close_to_the_cpu(select: str) -> int:
    """
    Every hog case matching ``select``, on the GPU, finite and within DEV_SCALE per point (coordinate-scaled) at every
    point (99% for a discrete feature); grids through ``sample_grid``. Returns how many cases it checked, so a pattern
    that matches nothing fails.
    """
    vectors = conformance.load(VECTORS, sets="hog")
    sample, warp = conformance.renderings("wgpu")
    grid = conformance.grid_rendering("wgpu")
    tight = Bound(DEV_SCALE, coordinate_scaled=True)
    checked = 0
    for case in vectors.cases:
        if not fnmatch.fnmatchcase(case.id, select):
            continue
        ps = vectors.point_sets[case.point_set]
        if ps.origin is not None and case.output == "noise":
            o = ps.origin
            ours = grid(case.params, tuple(o["start"]), tuple(o["shape"]), tuple(o["scales"])).ravel()
        else:
            fn = warp if case.output == "warp" else sample
            ours = fn(case.params, ps.axes[0], ps.axes[1], ps.axes[2] if ps.dims == 3 else None)
        ours = np.asarray(ours, np.float32)
        assert ours.shape == case.values.shape, case.id
        assert np.isfinite(ours).all(), f"{case.id}: not finite"
        diff = np.abs(ours.astype(np.float64) - case.values.astype(np.float64))
        if diff.ndim == 2:
            diff = diff.max(axis=1)
        within = float(np.mean(diff <= tight.per_point(case.params.frequency, ps.axes)))
        need = 0.99 if any(k in case.id for k in DEV_DISCRETE) else 1.0
        assert within >= need, f"{case.id}: {within:.4f} of points within {DEV_SCALE} scaled; max {diff.max():.3e}"
        checked += 1
    assert checked, f"no hog case matches {select!r}"
    return checked


@pytest.mark.parametrize(
    "select",
    [
        "hog/fnl/simplex_*",
        "hog/fnl/perlin_*",
        "hog/fnl/value_*",
        "hog/fnl/cubic_*",
        "hog/fnl/cellular_*",
        "hog/fns/cellular_*",
        "hog/fns/simplex_none/*",
        "hog/fns/simplex_fbm/*",
        "hog/fns/simplex_billow/*",
        "hog/fns/simplex_rigidmulti/*",
        "hog/fns/perlin_*",
        "hog/fns/value_*",
        "hog/fns/cubic_*",
        "hog/fns/whitenoise_none/*",
        "hog/fns/genasgrid_*",
        "hog/fnl/genasgrid_*",
        "hog/fns/simplex_fbm_perturb_*",
        "hog/fnl/warp_*",
    ],
)
def test_the_gpu_matches_the_cpu(device, select):
    close_to_the_cpu(select)


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


def test_a_feature_not_yet_ported_is_unsupported_not_wrong(device, monkeypatch):
    """While the port grows, an unported feature reports unsupported (Tasks 6 to 12). The gate is emptied here, so
    the test holds whatever the port has reached; Task 13 deletes both."""
    monkeypatch.setattr(gpu, "_PORTED_NOISE", set())
    with pytest.raises(NotImplementedError, match="not yet ported to WGSL: noise_type OPEN_SIMPLEX2"):
        gpu.GpuSampler(NoiseParams())
    # A NoiseLookup's own noise is gated too: _lookup_single2/3 call the leaf noises directly.
    with pytest.raises(NotImplementedError, match="cellular_lookup_type OPEN_SIMPLEX2"):
        gpu.GpuSampler(NoiseParams())
