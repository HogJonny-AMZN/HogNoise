"""
HogNoise: the wgpu rung. Runs where wgpu and an adapter exist; skips with the reason elsewhere, and fails instead of
skipping under HOG_NOISE_REQUIRE_GPU=1 (the software-adapter CI legs), so a leg that loses its adapter cannot go green.
Package: packages/python/hog-noise/tests/test_gpu
"""

import math
import os

import numpy as np
import pytest

from hog_noise import gpu

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
