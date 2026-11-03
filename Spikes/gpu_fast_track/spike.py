"""
HogNoise spike (the GPU fast track, stage 1): how far does an f32 WGSL rendering of 2D OpenSimplex2 drift from the CPU?
Package: Spikes/gpu_fast_track/spike

Evidence, not product (Docs/design/2026-11-01-gpu-fast-track.md). Runs `noise2.wgsl` as a compute pass over scattered
points in widening coordinate bands, reads the result back, and compares it with HogNoise's numpy rendering of the same
parameters (and numba, which must equal numpy bit for bit). Run it with wgpu supplied on the fly, once per back end:

    uv run --with wgpu python Spikes/gpu_fast_track/spike.py                  # the default back end
    WGPU_BACKEND_TYPE=D3D12  uv run --with wgpu python Spikes/gpu_fast_track/spike.py
    WGPU_BACKEND_TYPE=Vulkan uv run --with wgpu python Spikes/gpu_fast_track/spike.py
"""

import json
import math
import sys
from pathlib import Path

import numpy as np
import wgpu

from hog_noise import HAVE_NUMBA, FractalType, NoiseParams, NoiseType, make_sampler
from hog_noise.tables import GRADIENTS_2D

HERE = Path(__file__).resolve().parent
N = 65536
BANDS = [(0.0, 10.0), (10.0, 100.0), (100.0, 1000.0), (1000.0, 4096.0), (4096.0, 32768.0), (32768.0, 262144.0)]
CASES = {
    "simplex, one octave, f=0.01": NoiseParams(seed=1337, frequency=0.01, noise_type=NoiseType.OPEN_SIMPLEX2),
    "simplex FBm x4, f=0.01": NoiseParams(
        seed=1337, frequency=0.01, noise_type=NoiseType.OPEN_SIMPLEX2, fractal_type=FractalType.FBM, octaves=4
    ),
    "simplex FBm x4, f=0.05": NoiseParams(
        seed=7, frequency=0.05, noise_type=NoiseType.OPEN_SIMPLEX2, fractal_type=FractalType.FBM, octaves=4
    ),
}


BOUND = 3e-6  # the claimed contract: |gpu - cpu| <= BOUND * max(1, max(|x|, |y|) * frequency)


def points(lo: float, hi: float, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    """N points whose larger coordinate magnitude, max(|x|, |y|), lies in [lo, hi), signs mixed."""
    big = rng.uniform(lo, hi, N) * rng.choice([-1.0, 1.0], N)
    small = rng.uniform(-1.0, 1.0, N) * np.abs(big)
    x_is_big = rng.random(N) < 0.5
    return np.where(x_is_big, big, small).astype(np.float32), np.where(x_is_big, small, big).astype(np.float32)


def coordinate_norm(xs: np.ndarray, ys: np.ndarray, frequency: float) -> np.ndarray:
    """The noise-space coordinate the bound scales with: the larger magnitude, times the base-octave frequency."""
    return np.maximum(np.abs(xs.astype(np.float64)), np.abs(ys.astype(np.float64))) * abs(frequency)


class Gpu:
    def __init__(self) -> None:
        self.adapter = wgpu.gpu.request_adapter_sync(power_preference="high-performance")
        self.device = self.adapter.request_device_sync()
        module = self.device.create_shader_module(code=(HERE / "noise2.wgsl").read_text(encoding="utf-8"))
        self.pipeline = self.device.create_compute_pipeline(
            layout="auto", compute={"module": module, "entry_point": "main"}
        )
        self.grad = self.device.create_buffer_with_data(
            data=np.asarray(GRADIENTS_2D, np.float32).tobytes(), usage=wgpu.BufferUsage.STORAGE
        )

    def run(self, params: NoiseParams, xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
        n = len(xs)
        fractal = 1 if params.fractal_type == FractalType.FBM else 0
        uniform = np.zeros(8, np.uint32)
        uniform.view(np.int32)[0] = params.seed
        uniform.view(np.float32)[1] = params.frequency
        uniform[2] = params.octaves
        uniform.view(np.float32)[3] = params.lacunarity
        uniform.view(np.float32)[4] = params.gain
        uniform.view(np.float32)[5] = params.fractal_bounding
        uniform[6] = n
        uniform[7] = fractal
        dev = self.device
        ubuf = dev.create_buffer_with_data(data=uniform.tobytes(), usage=wgpu.BufferUsage.UNIFORM)
        pbuf = dev.create_buffer_with_data(
            data=np.stack([xs, ys], axis=1).astype(np.float32).tobytes(), usage=wgpu.BufferUsage.STORAGE
        )
        obuf = dev.create_buffer(size=n * 4, usage=wgpu.BufferUsage.STORAGE | wgpu.BufferUsage.COPY_SRC)
        entries = [
            {"binding": 0, "resource": {"buffer": ubuf, "offset": 0, "size": ubuf.size}},
            {"binding": 1, "resource": {"buffer": self.grad, "offset": 0, "size": self.grad.size}},
            {"binding": 2, "resource": {"buffer": pbuf, "offset": 0, "size": pbuf.size}},
            {"binding": 3, "resource": {"buffer": obuf, "offset": 0, "size": obuf.size}},
        ]
        group = dev.create_bind_group(layout=self.pipeline.get_bind_group_layout(0), entries=entries)
        enc = dev.create_command_encoder()
        cp = enc.begin_compute_pass()
        cp.set_pipeline(self.pipeline)
        cp.set_bind_group(0, group)
        cp.dispatch_workgroups(math.ceil(n / 64))
        cp.end()
        dev.queue.submit([enc.finish()])
        return np.frombuffer(dev.queue.read_buffer(obuf), dtype=np.float32).copy()


def cpu(params: NoiseParams, backend: str, xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
    sampler, _ = make_sampler(params, backend=backend)
    out = np.empty(len(xs), np.float32)
    return sampler.sample_points_2d(xs, ys, out)


def main() -> int:
    gpu = Gpu()
    info = gpu.adapter.info
    label = f"{info.get('device', '?')} / {info.get('backend_type', '?')}"
    print(f"adapter: {label}; numba: {HAVE_NUMBA}")
    rng = np.random.default_rng(12345)
    results = {
        "adapter": info.get("device"),
        "backend": info.get("backend_type"),
        "adapter_type": info.get("adapter_type"),
        "cases": {},
    }
    for name, params in CASES.items():
        rows = []
        print(f"\n{name}")
        print(
            f"{'band':>20} | {'max abs':>9} | {'p99.9 abs':>9} | {'mean abs':>9} | {'exact':>6}"
            f" | {'max norm':>9} | {'over':>5} | numba==numpy"
        )
        for lo, hi in BANDS:
            xs, ys = points(lo, hi, rng)
            ref = cpu(params, "numpy", xs, ys)
            same = bool(np.array_equal(cpu(params, "numba", xs, ys), ref)) if HAVE_NUMBA else None
            got = gpu.run(params, xs, ys)
            d = np.abs(got.astype(np.float64) - ref.astype(np.float64))
            # pointwise, each error against its own coordinate's bound, so a band's maximum cannot hide a violation
            normalised = d / np.maximum(1.0, coordinate_norm(xs, ys, params.frequency))
            row = {
                "band": [lo, hi],
                "max_abs": float(d.max()),
                "p999_abs": float(np.quantile(d, 0.999)),
                "mean_abs": float(d.mean()),
                "exact_fraction": float(np.mean(d == 0.0)),
                "max_normalised": float(normalised.max()),
                "over_bound": int(np.count_nonzero(normalised > BOUND)),
                "numba_equals_numpy": same,
            }
            rows.append(row)
            print(
                f"{f'[{lo:g}, {hi:g})':>20} | {row['max_abs']:9.2e} | {row['p999_abs']:9.2e} | {row['mean_abs']:9.2e}"
                f" | {row['exact_fraction']:6.1%} | {row['max_normalised']:9.2e} | {row['over_bound']:>5} | {same}"
            )
        results["cases"][name] = rows
    tag = (results["backend"] or "default").lower().replace(" ", "_")
    out = HERE / f"results_{tag}.json"
    out.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {out.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
