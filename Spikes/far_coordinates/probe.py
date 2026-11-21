"""
HogNoise probe: does every feature's GPU tolerance rule hold far from the origin?
Package: Spikes/far_coordinates/probe

Evidence, not product (Docs/design/2026-11-20-gpu-fast-track-account.md, gap 1; the board row
2026-11-21-far-coordinate-probe-for-every-feature). The tolerance file is measured out to 4,096 units at frequency 0.01.
This takes every hog case's parameters and output (noise or warp, 2D or 3D), samples fresh points in widening
coordinate bands, renders them with numpy (the reference, as the hog set is) and with the wgpu rung, and judges the
GPU's values by the feature's own rule from vectors/tolerance/wgpu.json, exactly as the conformance check does.

    uv run python -I Spikes/far_coordinates/probe.py                         # the default adapter
    WGPU_BACKEND_TYPE=D3D12 uv run python -I Spikes/far_coordinates/probe.py

Writes results_<adapter slug>.json beside this file and prints the summary table.
"""

import dataclasses
import json
import logging
import re
import sys
import time
from pathlib import Path

import numpy as np

from hog_noise import conformance, gpu

HERE = Path(__file__).resolve().parent
VECTORS = HERE.parent.parent / "vectors"
N = 65536  # points per band, as the stage 1 spike used: 16 times a scatter point set, so a rare tail shows
SEED = 20261121
#: Bands of the larger coordinate magnitude, in world units. The first is inside the measured range (a control: every
#: rule must pass there); the rest are outside it.
BANDS = [
    (0.0, 4096.0),
    (4096.0, 32768.0),
    (32768.0, 262144.0),
    (262144.0, 1048576.0),
]

_LOGGER = logging.getLogger("far_coordinates")


def points(lo: float, hi: float, dims: int, rng: np.random.Generator) -> tuple[np.ndarray, ...]:
    """N points whose largest coordinate magnitude lies in [lo, hi), signs mixed; the other axes smaller."""
    big = rng.uniform(lo, hi, N) * rng.choice([-1.0, 1.0], N)
    axes = [rng.uniform(-1.0, 1.0, N) * np.abs(big) for _ in range(dims)]
    which = rng.integers(0, dims, N)
    for d in range(dims):
        axes[d] = np.where(which == d, big, axes[d])
    return tuple(a.astype(np.float32) for a in axes)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    vectors = conformance.load(VECTORS, sets="hog")
    tolerance = conformance.Tolerance.load(VECTORS / "tolerance" / "wgpu.json", vectors)
    raw = json.loads((VECTORS / "tolerance" / "wgpu.json").read_text(encoding="utf-8"))
    kinds = {(r["feature"], r.get("output")): r["kind"] for r in raw["rules"]}
    ref_sample, ref_warp = conformance.renderings("numpy")
    gpu_sample, gpu_warp = conformance.renderings("wgpu")
    info = gpu.adapter_info()
    _LOGGER.info(f"adapter: {info}")

    # one probe per (feature, output, dims): the hog set repeats a feature's parameters across its point sets
    probes: dict[tuple[str, str, int], conformance.Case] = {}
    for case in vectors.cases:
        dims = vectors.point_sets[case.point_set].dims
        feature = conformance._feature(case)
        probes.setdefault((feature, case.output, dims), case)
    _LOGGER.info(f"{len(probes)} probes over {len({k[0] for k in probes})} features, {len(BANDS)} bands of {N} points")

    rng = np.random.default_rng(SEED)
    rows = []
    controls = 0
    t0 = time.perf_counter()
    for (feature, output, dims), case in sorted(probes.items()):
        rule = tolerance.rule_for(case)
        ref_fn, gpu_fn = (ref_warp, gpu_warp) if output == "warp" else (ref_sample, gpu_sample)
        # the control: on the case's own committed points (scatter sets; a grid case is rendered as points), the
        # reference must be the hog set bit for bit and the GPU must pass, as the conformance check says it does
        own = vectors.point_sets[case.point_set]
        if own.origin is None:
            oz = own.axes[2] if own.dims == 3 else None
            ref_own = np.asarray(ref_fn(case.params, own.axes[0], own.axes[1], oz), np.float32)
            if not np.array_equal(ref_own, case.values):
                raise SystemExit(f"control: numpy does not reproduce {case.id} bit for bit; the reference is wrong")
            gpu_own = np.asarray(gpu_fn(case.params, own.axes[0], own.axes[1], oz), np.float32)
            control = conformance._points(case, own, gpu_own, None, rule)
            if control.status != "pass":
                raise SystemExit(f"control: {case.id} fails on its own points ({control.detail}); the judging is wrong")
            controls += 1
        for lo, hi in BANDS:
            axes = points(lo, hi, dims, rng)
            zs = axes[2] if dims == 3 else None
            ref = np.asarray(ref_fn(case.params, axes[0], axes[1], zs), np.float32)
            ours = np.asarray(gpu_fn(case.params, axes[0], axes[1], zs), np.float32)
            ps = conformance.PointSet(name=f"band_{int(lo)}", dims=dims, count=N, axes=axes)
            probe_case = dataclasses.replace(case, id=f"{feature}/{output}/{dims}d/{int(lo)}", values=ref)
            result = conformance._points(probe_case, ps, ours, None, rule)
            diff = np.abs(ours.astype(np.float64) - ref.astype(np.float64))
            if diff.ndim == 2:
                diff = diff.max(axis=1)
            b = rule["bound"]
            allowed = conformance.Bound(float(b["scale"]), bool(b.get("coordinate_scaled", False))).per_point(
                case.params.frequency, axes
            )
            rows.append(
                {
                    "feature": feature,
                    "output": output,
                    "dims": dims,
                    "kind": kinds.get((feature, output), kinds.get((feature, None))),
                    "coordinate_scaled": bool(rule["bound"].get("coordinate_scaled", False)),
                    "past": int(np.count_nonzero(~(diff <= allowed))),  # NaN counts as past, as in conformance
                    "band": [lo, hi],
                    "status": result.status,
                    "max_abs": result.max_abs,
                    "max_normalised": result.max_normalised,
                    "detail": result.detail,
                    "finite": bool(np.isfinite(ours).all()),
                    "exact_fraction": float(np.mean(diff == 0.0)),
                }
            )
    _LOGGER.info(
        f"done in {time.perf_counter() - t0:.0f} s; control: {controls} probes reproduce the hog set and pass on their own points"
    )

    label = f"{info['device']} ({info['backend_type']})"
    out = HERE / f"results_{slug(label)}.json"
    out.write_text(
        json.dumps({"adapter": label, "n": N, "seed": SEED, "bands": BANDS, "controls": controls, "rows": rows}, indent=1)
        + "\n",
        encoding="utf-8",
    )
    _LOGGER.info(f"wrote {out}")

    # the summary: per band, how many probes pass, and the worst ratio of drift to the rule's bound
    print(f"\n{label}: probes passing their feature's rule, per band (worst drift / bound)")
    for lo, hi in BANDS:
        band = [r for r in rows if r["band"] == [lo, hi]]
        passed = sum(r["status"] == "pass" for r in band)
        worst = max(r["max_normalised"] for r in band)
        print(f"  [{int(lo)}, {int(hi)}): {passed}/{len(band)} pass, worst {worst:.3g}x the bound")
    return 0


if __name__ == "__main__":
    sys.exit(main())
