"""
HogNoise tools: the spirv-naga host. ``noise.spv`` through wgpu's SPIR-V front end, bound as the shaders README says.
Package: hog_noise_tools.hosts.spirv_naga

wgpu 0.33 has no SPIR-V passthrough, so naga reads the shipped bytes back into its own IR and wgpu translates that for
the device (the CI proof's spec, *Facts*): this proves the file is naga-readable and binds as documented, not that a
Vulkan driver consumes it; the spirv-vulkan host does that. The device is ``hog_noise.gpu.device()``, the process's
one, so ``HOG_NOISE_WGPU_ADAPTER`` and ``WGPU_BACKEND_TYPE`` choose it as they choose the rung's.
"""

from __future__ import annotations

import logging as _logging
from collections.abc import Sequence
from typing import Any

import numpy as np
from numpy.typing import NDArray

from hog_noise import shaders
from hog_noise_tools.hosts import BINDING_KINDS, HostUnavailable, verified, verified_tables, workgroups

_MODULE_NAME = "hog_noise_tools.hosts.spirv_naga"
__version__ = "0.1.0"
__updated__ = "2026-11-23"
_LOGGER = _logging.getLogger(_MODULE_NAME)


def open_host() -> SpirvNaga:
    """
    The host on the process's wgpu device.

    :raises HostUnavailable: wgpu missing, or no adapter, with the rung's own message.
    """
    from hog_noise import gpu

    try:
        dev = gpu.device()
    except RuntimeError as e:
        raise HostUnavailable(str(e)) from e
    return SpirvNaga(dev, gpu.adapter_info())


class SpirvNaga:
    """``noise.spv``'s five pipelines on one device, with the buffers that never change."""

    name = "spirv-naga"

    def __init__(self, dev: Any, info: dict[str, object]) -> None:
        import wgpu

        self.wgpu, self.device = wgpu, dev
        self.target = f"{info['device']} ({info['backend_type']})"
        module = dev.create_shader_module(code=verified("spirv"))
        kinds = {
            "uniform": wgpu.BufferBindingType.uniform,
            "read": wgpu.BufferBindingType.read_only_storage,
            "write": wgpu.BufferBindingType.storage,
        }
        layout = dev.create_bind_group_layout(
            entries=[
                {"binding": i, "visibility": wgpu.ShaderStage.COMPUTE, "buffer": {"type": kinds[k]}}
                for i, k in enumerate(BINDING_KINDS)
            ]
        )
        self.layout = layout
        pipeline_layout = dev.create_pipeline_layout(bind_group_layouts=[layout])
        self.pipelines = {
            entry: dev.create_compute_pipeline(layout=pipeline_layout, compute={"module": module, "entry_point": entry})
            for entry in shaders.ENTRY_POINTS
        }
        self.tables = self._buffer(verified_tables(), wgpu.BufferUsage.STORAGE)
        self.unused = self._buffer(bytes(4), wgpu.BufferUsage.STORAGE)  # the README: a one-float buffer
        self.no_grid = self._buffer(bytes(48), wgpu.BufferUsage.UNIFORM)  # the README: 48 zero bytes
        _LOGGER.info(f"spirv-naga: {len(self.pipelines)} pipelines from noise.spv on {self.target}")

    def _buffer(self, data: bytes, usage: Any) -> Any:
        return self.device.create_buffer_with_data(data=data, usage=usage)

    def run(
        self,
        entry: str,
        params: bytes,
        axes: Sequence[NDArray[np.float32]],
        n: int,
        width: int,
        grid: bytes | None,
    ) -> NDArray[np.float32]:
        """Dispatch ``entry`` over ``n`` points and read back ``n * width`` floats."""
        usage = self.wgpu.BufferUsage
        coords = [self._buffer(a.tobytes(), usage.STORAGE) for a in axes] + [self.unused] * (3 - len(axes))
        out = self.device.create_buffer(size=n * width * 4, usage=usage.STORAGE | usage.COPY_SRC)
        uniform_grid = self._buffer(grid, usage.UNIFORM) if grid is not None else self.no_grid
        buffers = [self._buffer(params, usage.UNIFORM), self.tables, *coords, out, uniform_grid]
        group = self.device.create_bind_group(
            layout=self.layout,
            entries=[
                {"binding": i, "resource": {"buffer": b, "offset": 0, "size": b.size}} for i, b in enumerate(buffers)
            ],
        )
        encoder = self.device.create_command_encoder()
        compute = encoder.begin_compute_pass()
        compute.set_pipeline(self.pipelines[entry])
        compute.set_bind_group(0, group)
        compute.dispatch_workgroups(*workgroups(n))
        compute.end()
        self.device.queue.submit([encoder.finish()])
        return np.frombuffer(self.device.queue.read_buffer(out), dtype=np.float32).copy()


if __name__ == "__main__":
    _logging.basicConfig(level=_logging.INFO)
    from hog_noise import NoiseParams
    from hog_noise_tools.hosts import HostSampler

    host = open_host()
    xs = np.linspace(-100, 100, 5, dtype=np.float32)
    s = HostSampler(NoiseParams(frequency=0.01), host)
    print(host.target, np.round(s.sample_points(xs, xs, np.zeros(5, np.float32), np.empty(5, np.float32)), 5))
