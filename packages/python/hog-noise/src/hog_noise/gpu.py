"""
HogNoise: the wgpu rung, every noise in WGSL on whatever adapter wgpu finds. Override only: never chosen by the ladder.
Package: hog_noise/gpu

`wgpu` is imported inside the functions here and never at the top, so importing `hog_noise`, or using any other rung,
never loads it (Docs/standards/python-project.md, *The package boundary*). One device per process, made on first use
and kept with its pipelines. Spec: Docs/superpowers/specs/2026-11-14-gpu-port.md.
"""

from __future__ import annotations

import importlib.resources
import logging as _logging
import math
import os
import struct
import time
from collections.abc import Sequence
from typing import Any

import numpy as np
from numpy.typing import NDArray

from hog_noise import tables
from hog_noise.backends import Backend, register
from hog_noise.params import NoiseParams
from hog_noise.samplers import CAPABILITY

_MODULE_NAME = "hog_noise.gpu"
__version__ = "0.1.0"
__updated__ = "2026-11-18"
_LOGGER = _logging.getLogger(_MODULE_NAME)

#: Part of an adapter's name: the first adapter whose name contains it is used instead of wgpu's default.
ADAPTER_ENV = "HOG_NOISE_WGPU_ADAPTER"

#: The process's one device and its adapter's description, made on first use. Kept apart from `_Gpu`'s pipelines on
#: purpose: `adapter_info` and `is_available` (CI's *Adapter* step, the ladder's probe) need the device and nothing
#: else, and building the five pipelines would make every probe pay for compiling noise.wgsl.
_STATE: dict[str, Any] = {}

# wgpu's objects are typed `Any` here: wgpu is never imported at module level (the package boundary), so its types
# cannot be named in a signature.


def _wgpu() -> Any:
    """The wgpu module, or a RuntimeError naming the extra that installs it."""
    try:
        import wgpu
    except ImportError as e:
        raise RuntimeError("wgpu is not installed: install hog-noise[gpu]") from e
    except OSError as e:  # installed, but its native library will not load here
        raise RuntimeError(f"wgpu cannot load its native library: {e}") from e
    return wgpu


def _pick_adapter(wgpu: Any) -> Any:
    """
    The GPU adapter to use: the first whose name contains `ADAPTER_ENV`'s value, ignoring case, else wgpu's
    high-performance choice.

    :raises RuntimeError: "no adapter", naming the ones found.
    """
    wanted = os.environ.get(ADAPTER_ENV, "").strip()
    if wanted:
        adapters = wgpu.gpu.enumerate_adapters_sync()
        for adapter in adapters:
            if wanted.lower() in str(adapter.info.get("device", "")).lower():
                return adapter
        found = [f"{a.info.get('device')} ({a.info.get('backend_type')})" for a in adapters]
        raise RuntimeError(f"no adapter: none named like {wanted!r} ({ADAPTER_ENV}); found {found}")
    try:
        adapter = wgpu.gpu.request_adapter_sync(power_preference="high-performance")
    except Exception as e:  # wgpu raises its own error types when no adapter exists
        adapter, cause = None, f"{type(e).__name__}: {e}"
    else:
        cause = "wgpu chose none"
    if adapter is None:
        try:
            found = [
                f"{a.info.get('device')} ({a.info.get('backend_type')})" for a in wgpu.gpu.enumerate_adapters_sync()
            ]
        except Exception as e:  # the list is for the message; failing to make it must not hide the cause
            found = [f"cannot list adapters: {e}"]
        raise RuntimeError(f"no adapter: {cause}; found {found}; name one in {ADAPTER_ENV}")
    return adapter


def device() -> Any:
    """
    The process's one device, made on first use and kept.

    :raises RuntimeError: Naming why there is none: wgpu missing, or no adapter (or none matching `ADAPTER_ENV`).
    """
    if "device" not in _STATE:
        wgpu = _wgpu()
        adapter = _pick_adapter(wgpu)
        try:
            _STATE["device"] = adapter.request_device_sync()
        except Exception as e:  # an adapter that will not give a device is no adapter
            raise RuntimeError(f"no device from {adapter.info.get('device')}: {type(e).__name__}: {e}") from e
        _STATE["info"] = {k: adapter.info.get(k) for k in ("device", "backend_type", "adapter_type", "vendor")}
        info = _STATE["info"]
        _LOGGER.info(f"wgpu adapter: {info['device']} ({info['backend_type']}, {info['adapter_type']})")
    return _STATE["device"]


def adapter_info() -> dict[str, object]:
    """The chosen adapter's name, back end, type and vendor, making the device if it is not made yet."""
    device()
    return dict(_STATE["info"])


def is_available() -> bool:
    """The ladder's probe: makes the device, or raises with the cause so the ladder's message carries it."""
    device()
    return True


#: Below every CPU rung and the reference: never chosen by the ladder, only by name.
PRIORITY = -20
#: The longest octave loop the shader is given; a longer one can stall the device until the driver resets it.
MAX_OCTAVES = 32
WORKGROUP = 64
_MAX_GROUPS = 65535
#: The shader's ``Params`` struct, field for field in `NoiseParams.kernel_args()` order: ``i`` an i32, ``f`` an f32.
PARAM_KINDS = "ifiiifffffiifiifiiififfifff"
ENTRY_POINTS = ("sample_points_3d", "sample_points_2d", "sample_grid", "warp_points_3d", "warp_points_2d")


def pack_params(params: NoiseParams) -> bytes:
    """The ``Params`` uniform: `kernel_args()` with the seed wrapped to i32, little-endian, padded to 16 bytes.

    The documented way a host running the emitted shaders fills binding 0; needs no ``wgpu`` (``shaders/README.md``).
    """
    args = list(params.kernel_args())
    args[0] = ((int(args[0]) + 0x80000000) & 0xFFFFFFFF) - 0x80000000
    values = [int(a) if kind == "i" else float(a) for kind, a in zip(PARAM_KINDS, args, strict=True)]
    data = struct.pack("<" + PARAM_KINDS, *values)
    return data + bytes(-len(data) % 16)


def pack_grid(start: Sequence[int], shape: Sequence[int], scales: Sequence[float]) -> bytes:
    """The ``Grid`` uniform: the start cell, the shape and the per-axis scales, padded to 16 bytes.

    The documented way a host running the emitted shaders fills binding 6 for ``sample_grid``; needs no ``wgpu``
    (``shaders/README.md``).
    """
    data = struct.pack("<iiiIIIfff", *(int(v) for v in start), *(int(n) for n in shape), *(float(s) for s in scales))
    return data + bytes(-len(data) % 16)


def _workgroups(n: int) -> tuple[int, int, int]:
    """Workgroups for ``n`` points: along x, wrapping into y past the 65,535 a dimension allows (``point_index``)."""
    groups = math.ceil(n / WORKGROUP)
    if groups <= _MAX_GROUPS:
        return (groups, 1, 1)
    return (_MAX_GROUPS, math.ceil(groups / _MAX_GROUPS), 1)


def _point_count(axes: Sequence[NDArray[np.float32]], out: NDArray[np.float32] | None = None) -> int:
    """
    The number of points: every axis's length, and ``out``'s where given, which must all be one.

    :raises ValueError: Naming the lengths. Checked before any GPU work: WGSL's robust access would clamp a short axis
        to its last value and give an answer, silently.
    """
    lengths = [len(a) for a in axes]
    if len(set(lengths)) > 1:
        raise ValueError(f"the axes have lengths {lengths}; every axis needs one per point")
    if out is not None and len(out) != lengths[0]:
        raise ValueError(f"out has {len(out)} values for {lengths[0]} points")
    return lengths[0]


class _Gpu:
    """
    The process's one device, the buffers that never change, and one pipeline per entry point. The device itself lives
    in `_STATE`, not here, so the probes that need only the device never build the pipelines.
    """

    _instance: _Gpu | None = None  # the pipelines, built on the first sampler; the device is `_STATE`'s

    @classmethod
    def get(cls) -> _Gpu:
        """The process's one `_Gpu`, built on first use: the device, the shader's pipelines and the tables."""
        if cls._instance is None:
            cls._instance = cls(device())
        return cls._instance

    def __init__(self, dev: Any) -> None:
        wgpu = _wgpu()
        self.wgpu, self.device = wgpu, dev
        source = (importlib.resources.files("hog_noise") / "wgsl" / "noise.wgsl").read_text(encoding="utf-8")
        t0 = time.perf_counter()
        module = dev.create_shader_module(code=source)  # naga validates here
        stage, kind = wgpu.ShaderStage.COMPUTE, wgpu.BufferBindingType
        layout = [kind.uniform, kind.read_only_storage, kind.read_only_storage, kind.read_only_storage,
                  kind.read_only_storage, kind.storage, kind.uniform]  # fmt: skip
        self.layout = dev.create_bind_group_layout(
            entries=[{"binding": i, "visibility": stage, "buffer": {"type": t}} for i, t in enumerate(layout)]
        )
        pipeline_layout = dev.create_pipeline_layout(bind_group_layouts=[self.layout])
        self.pipelines = {
            name: dev.create_compute_pipeline(layout=pipeline_layout, compute={"module": module, "entry_point": name})
            for name in ENTRY_POINTS
        }
        self.build_seconds = time.perf_counter() - t0
        _LOGGER.info(f"noise.wgsl: {len(ENTRY_POINTS)} pipelines built in {1000 * self.build_seconds:.0f} ms")
        self.tables = self.storage(tables.binding_table())
        self.unused = self.storage(np.zeros(1, np.float32))  # bound where an entry point reads nothing
        self.no_grid = self.uniform(bytes(48))

    def storage(self, values: NDArray[np.float32]) -> Any:
        """A read-only storage buffer holding ``values`` as float32."""
        data = np.ascontiguousarray(values, dtype=np.float32).tobytes()
        return self.device.create_buffer_with_data(data=data, usage=self.wgpu.BufferUsage.STORAGE)

    def uniform(self, data: bytes) -> Any:
        """A uniform buffer holding ``data``."""
        return self.device.create_buffer_with_data(data=data, usage=self.wgpu.BufferUsage.UNIFORM)

    def run(
        self,
        entry: str,
        params_buffer: Any,
        axes: Sequence[NDArray[np.float32]],
        n: int,
        width: int,
        grid: Any | None = None,
    ) -> NDArray[np.float32]:
        """
        Dispatch ``entry`` over ``n`` points and read back ``n * width`` floats.

        :raises ValueError: An axis whose length is not ``n`` (checked before any GPU work).
        """
        if axes and _point_count(axes) != n:
            raise ValueError(f"the axes have {len(axes[0])} points, not {n}")
        if n == 0:
            return np.empty(0, np.float32)
        wgpu, dev = self.wgpu, self.device
        coords = [self.storage(a) for a in axes] + [self.unused] * (3 - len(axes))
        out = dev.create_buffer(size=n * width * 4, usage=wgpu.BufferUsage.STORAGE | wgpu.BufferUsage.COPY_SRC)
        buffers = [params_buffer, self.tables, *coords, out, grid if grid is not None else self.no_grid]
        group = dev.create_bind_group(
            layout=self.layout,
            entries=[
                {"binding": i, "resource": {"buffer": b, "offset": 0, "size": b.size}} for i, b in enumerate(buffers)
            ],
        )
        encoder = dev.create_command_encoder()
        compute = encoder.begin_compute_pass()
        compute.set_pipeline(self.pipelines[entry])
        compute.set_bind_group(0, group)
        compute.dispatch_workgroups(*_workgroups(n))
        compute.end()
        dev.queue.submit([encoder.finish()])
        return np.frombuffer(dev.queue.read_buffer(out), dtype=np.float32).copy()


class GpuSampler:
    """The wgpu rung's sampler: the calls every sampler has, run by noise.wgsl on the process's one device."""

    name = "wgpu"

    def __init__(self, params: NoiseParams) -> None:
        for field in ("octaves", "perturb_octaves"):
            value = getattr(params, field)
            if value > MAX_OCTAVES:
                raise NotImplementedError(
                    f"{field}={value} is past the wgpu rung's cap of {MAX_OCTAVES}: a shader loop that long can stall "
                    f"the device"
                )
        self.params = params
        self._gpu = _Gpu.get()
        self._params = self._gpu.uniform(pack_params(params))

    def sample_points(
        self,
        xs: NDArray[np.float32],
        ys: NDArray[np.float32],
        zs: NDArray[np.float32],
        out: NDArray[np.float32],
    ) -> NDArray[np.float32]:
        """
        3D noise at each ``(xs[i], ys[i], zs[i])`` into ``out``.

        :raises ValueError: Axes, or ``out``, of unequal length.
        """
        n = _point_count((xs, ys, zs), out)
        out[...] = self._gpu.run("sample_points_3d", self._params, (xs, ys, zs), n, 1)
        return out

    def sample_points_2d(
        self, xs: NDArray[np.float32], ys: NDArray[np.float32], out: NDArray[np.float32]
    ) -> NDArray[np.float32]:
        """
        2D noise at each ``(xs[i], ys[i])`` into ``out``.

        :raises ValueError: Axes, or ``out``, of unequal length.
        """
        n = _point_count((xs, ys), out)
        out[...] = self._gpu.run("sample_points_2d", self._params, (xs, ys), n, 1)
        return out

    def sample_grid(
        self,
        start: Sequence[int],
        shape: Sequence[int],
        scales: Sequence[float] = (1.0, 1.0, 1.0),
    ) -> NDArray[np.float32]:
        """The grid `samplers._KernelSampler.sample_grid` describes, its coordinates computed on the GPU."""
        shape = tuple(int(n) for n in shape)
        grid = self._gpu.uniform(pack_grid(start, shape, scales))
        return self._gpu.run("sample_grid", self._params, (), math.prod(shape), 1, grid).reshape(shape)

    def warp_points(
        self, xs: NDArray[np.float32], ys: NDArray[np.float32], zs: NDArray[np.float32]
    ) -> NDArray[np.float32]:
        """
        The warped raw coordinates, ``(N, 3)``: the reference's ``DomainWarp`` alone, as `scalar.warp_3d` gives.

        :raises ValueError: Axes of unequal length.
        """
        n = _point_count((xs, ys, zs))
        return self._gpu.run("warp_points_3d", self._params, (xs, ys, zs), n, 3).reshape(n, 3)

    def warp_points_2d(self, xs: NDArray[np.float32], ys: NDArray[np.float32]) -> NDArray[np.float32]:
        """
        The warped raw coordinates, ``(N, 2)``: the 2D twin of `warp_points`.

        :raises ValueError: Axes of unequal length.
        """
        n = _point_count((xs, ys))
        return self._gpu.run("warp_points_2d", self._params, (xs, ys), n, 2).reshape(n, 2)

    def sample(self, x: float, y: float, z: float = 0.0) -> float:
        """`sample_points` on one point: correct, and slow on purpose (a dispatch per value)."""
        one = np.empty(1, np.float32)
        return float(
            self.sample_points(np.array([x], np.float32), np.array([y], np.float32), np.array([z], np.float32), one)[0]
        )


register(
    Backend(CAPABILITY, "wgpu", PRIORITY, is_available, GpuSampler, note="noise.wgsl on wgpu, float32; override only")
)


if __name__ == "__main__":
    _logging.basicConfig(level=_logging.INFO)
    try:
        print(adapter_info())
    except RuntimeError as e:
        print(f"no GPU here: {e}")
    else:
        sampler = GpuSampler(NoiseParams(frequency=0.01))
        xs = np.linspace(-100, 100, 5, dtype=np.float32)
        print("wgpu", np.round(sampler.sample_points(xs, xs, np.zeros(5, np.float32), np.empty(5, np.float32)), 5))
