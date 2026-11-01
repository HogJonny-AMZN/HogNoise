"""
HogNoise: generate the noise oracle vectors from the original bindings.
Package: tools/gen_noise_vectors

Writes ``tests/vectors/noise/<source>/<feature>.npz`` files, one per feature and parameter set,
each holding the coordinates, the binding's values for them, and the parameters as JSON. These are
the oracles the kernel port is compared against (Docs/PYTHON_UPGRADE_AND_FASTNOISE.md, 4.3 and 4.4).

Two sources:

- ``fnl``: `pyfastnoiselite`, the FastNoiseLite reference. Regenerable on any supported Python.
- ``fnl`` also holds the domain-warp vectors (``warp_*.npz``), produced by the C++ oracle harness in
  ``tools/noise_oracle`` because the binding does not expose ``DomainWarp``; the harness is built on
  first use and reproduces the binding's ``gen_from_coords`` bit for bit.
- ``fns``: `pyfastnoisesimd`, the FastNoiseSIMD library this project shipped with. Only importable
  where its cp39 wheel or a source build exists, which is why these vectors are captured now and
  committed: they are the only oracle for the Phase C features (classic Simplex, Billow, WhiteNoise,
  Natural distance, NoiseLookup, Distance2Cave, gradient perturb, ``genAsGrid``).

Run from the repo root on the Python 3.9 venv to capture both::

    python tools/gen_noise_vectors.py            # both sources, skips a missing binding with a note
    python tools/gen_noise_vectors.py --source fnl

Coordinates are fixed by seed so a regeneration produces value-identical files when the binding is
unchanged (not byte-identical: the zip entries carry a timestamp, so revert the untouched files after a
regeneration and commit only the new ones; checked 2026-09-28, 54 files, zero value differences). Scattered samples: 4096 points, x and z in [-4096, 4096], y in [-256, 256]. Grid: 128 x 128
over x, z in [-2048, 2048] at y = 0, the XZ-plane heightfield case. Coordinates are written once to
``coords.npz``; each feature file holds only values, so the set stays under 10 MB.
"""

import argparse
import json
import logging as _logging
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

_MODULE_NAME = "tools.gen_noise_vectors"
__version__ = "0.1.0"
__updated__ = "2026-09-13"
_LOGGER = _logging.getLogger(_MODULE_NAME)

ROOT = Path(__file__).resolve().parent.parent
VECTORS = ROOT / "tests" / "vectors" / "noise"
N_SCATTER = 4096
GRID = 128
GRID_EXTENT = 2048.0
SEED = 12345
COORD_SEED = 7


def coordinates() -> Dict[str, np.ndarray]:
    rng = np.random.RandomState(COORD_SEED)
    xs = rng.uniform(-4096, 4096, N_SCATTER).astype(np.float32)
    ys = rng.uniform(-256, 256, N_SCATTER).astype(np.float32)
    zs = rng.uniform(-4096, 4096, N_SCATTER).astype(np.float32)
    axis = np.linspace(-GRID_EXTENT, GRID_EXTENT, GRID, dtype=np.float32)
    gx, gz = np.meshgrid(axis, axis)
    return {"xs": xs, "ys": ys, "zs": zs, "grid_x": gx.ravel(), "grid_z": gz.ravel()}


def _write(
    source: str, feature: str, params: Dict[str, object], values: Dict[str, np.ndarray], coords: Dict[str, np.ndarray]
) -> Path:
    out = VECTORS / source / f"{feature}.npz"
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        out,
        params=np.array(json.dumps(params, sort_keys=True)),
        **{k: np.asarray(v, dtype=np.float32) for k, v in values.items()},
    )
    return out


# -------------------------------------------------------------------------
# FastNoiseLite
FNL_NOISE = {
    "simplex": "NoiseType_OpenSimplex2",
    "simplex_smooth": "NoiseType_OpenSimplex2S",
    "perlin": "NoiseType_Perlin",
    "value": "NoiseType_Value",
    "cubic": "NoiseType_ValueCubic",
    "cellular": "NoiseType_Cellular",
}
FNL_FRACTAL = {
    "none": "FractalType_None",
    "fbm": "FractalType_FBm",
    "ridged": "FractalType_Ridged",
    "pingpong": "FractalType_PingPong",
}
FNL_CELL_DIST = {
    "euclidean": "CellularDistanceFunction_Euclidean",
    "euclideansq": "CellularDistanceFunction_EuclideanSq",
    "manhattan": "CellularDistanceFunction_Manhattan",
    "hybrid": "CellularDistanceFunction_Hybrid",
}
FNL_CELL_RET = {
    "cellvalue": "CellularReturnType_CellValue",
    "distance": "CellularReturnType_Distance",
    "distance2": "CellularReturnType_Distance2",
    "distance2add": "CellularReturnType_Distance2Add",
    "distance2sub": "CellularReturnType_Distance2Sub",
    "distance2mul": "CellularReturnType_Distance2Mul",
    "distance2div": "CellularReturnType_Distance2Div",
}


def generate_fnl(coords: Dict[str, np.ndarray]) -> List[Path]:
    from pyfastnoiselite.pyfastnoiselite import (
        CellularDistanceFunction,
        CellularReturnType,
        FastNoiseLite,
        FractalType,
        NoiseType,
        RotationType3D,
    )

    written = []

    def run(feature: str, params: Dict[str, object], configure) -> None:
        noise = FastNoiseLite(seed=SEED)
        noise.frequency = params["frequency"]
        configure(noise)
        values = {
            "scatter_3d": noise.gen_from_coords(np.stack([coords["xs"], coords["ys"], coords["zs"]])),
            "scatter_2d": noise.gen_from_coords(np.stack([coords["xs"], coords["zs"]])),
            "grid_3d": noise.gen_from_coords(
                np.stack([coords["grid_x"], np.zeros_like(coords["grid_x"]), coords["grid_z"]])
            ),
        }
        written.append(_write("fnl", feature, params, values, coords))

    # Phase A and B: every noise type x fractal type, 4 octaves, default gain/lacunarity
    for noise_name, nt in FNL_NOISE.items():
        for fractal_name, ft in FNL_FRACTAL.items():
            params = {
                "source": "pyfastnoiselite",
                "noise_type": noise_name,
                "fractal_type": fractal_name,
                "seed": SEED,
                "frequency": 0.01,
                "octaves": 4,
                "lacunarity": 2.0,
                "gain": 0.5,
                "weighted_strength": 0.0,
                "ping_pong_strength": 2.0,
            }

            def cfg(n, nt=nt, ft=ft, p=params):
                n.noise_type = getattr(NoiseType, nt)
                n.fractal_type = getattr(FractalType, ft)
                n.fractal_octaves = p["octaves"]
                n.fractal_lacunarity = p["lacunarity"]
                n.fractal_gain = p["gain"]

            run(f"{noise_name}_{fractal_name}", params, cfg)

    # weighted strength and rotation variants on the default noise
    for weighted in (0.5,):
        params = {
            "source": "pyfastnoiselite",
            "noise_type": "simplex",
            "fractal_type": "fbm",
            "seed": SEED,
            "frequency": 0.01,
            "octaves": 4,
            "lacunarity": 2.0,
            "gain": 0.5,
            "weighted_strength": weighted,
            "ping_pong_strength": 2.0,
        }

        def cfg_w(n, p=params):
            n.noise_type = NoiseType.NoiseType_OpenSimplex2
            n.fractal_type = FractalType.FractalType_FBm
            n.fractal_octaves = 4
            n.fractal_weighted_strength = p["weighted_strength"]

        run(f"simplex_fbm_weighted{weighted}", params, cfg_w)
    for rot_name, rot in (
        ("improve_xy", "RotationType3D_ImproveXYPlanes"),
        ("improve_xz", "RotationType3D_ImproveXZPlanes"),
    ):
        for noise_name in ("simplex", "perlin"):
            params = {
                "source": "pyfastnoiselite",
                "noise_type": noise_name,
                "fractal_type": "none",
                "seed": SEED,
                "frequency": 0.01,
                "octaves": 1,
                "lacunarity": 2.0,
                "gain": 0.5,
                "weighted_strength": 0.0,
                "ping_pong_strength": 2.0,
                "rotation_3d": rot_name,
            }

            def cfg_r(n, nt=FNL_NOISE[noise_name], r=rot):
                n.noise_type = getattr(NoiseType, nt)
                n.rotation_type_3d = getattr(RotationType3D, r)

            run(f"{noise_name}_none_{rot_name}", params, cfg_r)

    # Phase B cellular: every distance function x return type, jitter 1.0
    for dist_name, dist in FNL_CELL_DIST.items():
        for ret_name, ret in FNL_CELL_RET.items():
            params = {
                "source": "pyfastnoiselite",
                "noise_type": "cellular",
                "fractal_type": "none",
                "seed": SEED,
                "frequency": 0.01,
                "cellular_distance": dist_name,
                "cellular_return": ret_name,
                "cellular_jitter": 1.0,
            }

            def cfg_c(n, d=dist, r=ret):
                n.noise_type = NoiseType.NoiseType_Cellular
                n.cellular_distance_function = getattr(CellularDistanceFunction, d)
                n.cellular_return_type = getattr(CellularReturnType, r)
                n.cellular_jitter = 1.0

            run(f"cellular_{dist_name}_{ret_name}", params, cfg_c)

    try:
        written.extend(generate_fnl_warp(coords))
    except (ImportError, OSError, subprocess.CalledProcessError) as e:
        # the warp vectors need the C++ oracle, which needs MSVC on Windows; the binding's own vectors
        # above do not, so a regeneration elsewhere keeps them and says what it skipped
        _LOGGER.warning(f"fnl: domain-warp vectors skipped, the oracle harness is unavailable here: {e}")
    return written


# -------------------------------------------------------------------------
# FastNoiseLite domain warp, through the C++ oracle (the binding does not expose DomainWarp)
ORACLE_DIR = ROOT / "tools" / "noise_oracle"
ORACLE_EXE = ORACLE_DIR / "fnl_oracle.exe"
WARP_TYPES = {"opensimplex2": 0, "opensimplex2reduced": 1, "basicgrid": 2}
WARP_FRACTALS = {"none": 0, "domain_warp_progressive": 4, "domain_warp_independent": 5}
WARP_AMP = 30.0


def _oracle_exe() -> Path:
    """The harness, built with MSVC on first use (``build.bat`` probes the standard ``vcvars64.bat`` locations)."""
    if not ORACLE_EXE.exists():
        _LOGGER.info("building the FastNoiseLite oracle harness")
        subprocess.run(["cmd", "/c", str(ORACLE_DIR / "build.bat")], check=True)
    if not ORACLE_EXE.exists():
        raise ImportError("fnl_oracle.exe did not build; Visual Studio 2022 with the C++ workload is needed")
    return ORACLE_EXE


def _oracle(
    exe: Path, mode: str, points: np.ndarray, params: Dict[str, object], warp_type: int, fractal: int
) -> np.ndarray:
    import subprocess
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        inp = Path(tmp) / "in.f32"
        outp = Path(tmp) / "out.f32"
        np.ascontiguousarray(points, dtype=np.float32).tofile(inp)
        args = [
            str(exe),
            mode,
            str(inp),
            str(outp),
            str(params["seed"]),
            str(params["frequency"]),
            "0",  # OpenSimplex2
            str(fractal),
            str(params["octaves"]),
            str(params["lacunarity"]),
            str(params["gain"]),
            "0.0",
            "2.0",
            "0",  # no 3D rotation
            str(warp_type),
            str(params["domain_warp_amp"]),
        ]
        subprocess.run(args, check=True)
        return np.fromfile(outp, dtype=np.float32)


def generate_fnl_warp(coords: Dict[str, np.ndarray]) -> List[Path]:
    """
    Every warp type x warp fractal, amplitude 30 at frequency 0.01 over OpenSimplex2: the warped
    coordinates (``warp_2d`` N x 2, ``warp_3d`` N x 3, ``grid_warp_3d``) and the noise the reference
    then samples at them (``scatter_2d``, ``scatter_3d``, ``grid_3d``), so the existing noise
    comparison covers the end-to-end path and a second test covers the warp field itself.
    """
    exe = _oracle_exe()
    written = []
    scatter3 = np.stack([coords["xs"], coords["ys"], coords["zs"]], axis=1)
    scatter2 = np.stack([coords["xs"], coords["zs"]], axis=1)
    grid3 = np.stack([coords["grid_x"], np.zeros_like(coords["grid_x"]), coords["grid_z"]], axis=1)
    for warp_name, warp_type in WARP_TYPES.items():
        for fractal_name, fractal in WARP_FRACTALS.items():
            params = {
                "source": "fnl_oracle",
                "noise_type": "simplex",
                "fractal_type": fractal_name,
                "seed": SEED,
                "frequency": 0.01,
                "octaves": 4,
                "lacunarity": 2.0,
                "gain": 0.5,
                "weighted_strength": 0.0,
                "ping_pong_strength": 2.0,
                "domain_warp": warp_name,
                "domain_warp_amp": WARP_AMP,
            }
            w3 = _oracle(exe, "warp3", scatter3, params, warp_type, fractal).reshape(-1, 3)
            w2 = _oracle(exe, "warp2", scatter2, params, warp_type, fractal).reshape(-1, 2)
            g3 = _oracle(exe, "warp3", grid3, params, warp_type, fractal).reshape(-1, 3)
            values = {
                "warp_3d": w3,
                "warp_2d": w2,
                "grid_warp_3d": g3,
                "scatter_3d": _oracle(exe, "noise3", w3, params, warp_type, fractal),
                "scatter_2d": _oracle(exe, "noise2", w2, params, warp_type, fractal),
                "grid_3d": _oracle(exe, "noise3", g3, params, warp_type, fractal),
            }
            written.append(_write("fnl", f"warp_{warp_name}_{fractal_name}", params, values, coords))
    return written


# -------------------------------------------------------------------------
# FastNoiseSIMD
def generate_fns(coords: Dict[str, np.ndarray]) -> List[Path]:
    import pyfastnoisesimd as fns

    written = []
    n_grid = len(coords["grid_x"])

    def gen_coords(noise, xs, ys, zs):
        buf = fns.empty_coords(len(xs))
        buf[0, : len(xs)] = xs
        buf[1, : len(xs)] = ys
        buf[2, : len(xs)] = zs
        return np.array(noise.genFromCoords(buf)[: len(xs)], dtype=np.float32)

    def run(feature: str, params: Dict[str, object], configure) -> None:
        noise = fns.Noise(seed=SEED, numWorkers=1)
        noise.frequency = params["frequency"]
        configure(noise)
        values = {
            "scatter_3d": gen_coords(noise, coords["xs"], coords["ys"], coords["zs"]),
            "grid_3d": gen_coords(noise, coords["grid_x"], np.zeros(n_grid, np.float32), coords["grid_z"]),
        }
        written.append(_write("fns", feature, params, values, coords))

    noise_types = {
        "simplex": "Simplex",
        "perlin": "Perlin",
        "value": "Value",
        "cubic": "Cubic",
        "whitenoise": "WhiteNoise",
    }
    fractal_variants = {
        "simplex": "SimplexFractal",
        "perlin": "PerlinFractal",
        "value": "ValueFractal",
        "cubic": "CubicFractal",
    }
    fractals = {"fbm": "FBM", "billow": "Billow", "rigidmulti": "RigidMulti"}

    for noise_name, nt in noise_types.items():
        params = {
            "source": "pyfastnoisesimd",
            "noise_type": noise_name,
            "fractal_type": "none",
            "seed": SEED,
            "frequency": 0.01,
        }
        run(f"{noise_name}_none", params, lambda n, nt=nt: setattr(n, "noiseType", getattr(fns.NoiseType, nt)))
    for noise_name, nt in fractal_variants.items():
        for fractal_name, ft in fractals.items():
            params = {
                "source": "pyfastnoisesimd",
                "noise_type": noise_name,
                "fractal_type": fractal_name,
                "seed": SEED,
                "frequency": 0.01,
                "octaves": 4,
                "lacunarity": 2.0,
                "gain": 0.5,
            }

            def cfg(n, nt=nt, ft=ft):
                n.noiseType = getattr(fns.NoiseType, nt)
                n.fractal.octaves = 4
                n.fractal.lacunarity = 2.0
                n.fractal.gain = 0.5
                n.fractal.fractalType = getattr(fns.FractalType, ft)

            run(f"{noise_name}_{fractal_name}", params, cfg)

    # cellular: every distance function x return type
    for dist in ("Euclidean", "Manhattan", "Natural"):
        for ret in (
            "CellValue",
            "Distance",
            "Distance2",
            "Distance2Add",
            "Distance2Sub",
            "Distance2Mul",
            "Distance2Div",
            "NoiseLookup",
            "Distance2Cave",
        ):
            params = {
                "source": "pyfastnoisesimd",
                "noise_type": "cellular",
                "fractal_type": "none",
                "seed": SEED,
                "frequency": 0.01,
                "cellular_distance": dist.lower(),
                "cellular_return": ret.lower(),
                "cellular_jitter": 0.45,
                "lookup_frequency": 0.2,
            }

            def cfg_c(n, d=dist, r=ret):
                n.noiseType = fns.NoiseType.Cellular
                n.cell.distanceFunc = getattr(fns.CellularDistanceFunction, d)
                n.cell.returnType = getattr(fns.CellularReturnType, r)
                n.cell.jitter = 0.45
                n.cell.lookupFrequency = 0.2
                n.cell.noiseLookupType = fns.NoiseType.Simplex

            run(f"cellular_{dist.lower()}_{ret.lower()}", params, cfg_c)

    # gradient perturb, every type, on simplex fbm
    for pt in ("Gradient", "GradientFractal", "Normalise", "Gradient_Normalise", "GradientFractal_Normalise"):
        params = {
            "source": "pyfastnoisesimd",
            "noise_type": "simplex",
            "fractal_type": "fbm",
            "seed": SEED,
            "frequency": 0.01,
            "octaves": 4,
            "lacunarity": 2.0,
            "gain": 0.5,
            "perturb_type": pt.lower(),
            "perturb_amp": 1.0,
            "perturb_frequency": 0.5,
            "perturb_octaves": 3,
            "perturb_lacunarity": 2.0,
            "perturb_gain": 0.5,
            "perturb_normalise_length": 1.0,
        }

        def cfg_p(n, pt=pt):
            n.noiseType = fns.NoiseType.SimplexFractal
            n.fractal.octaves = 4
            n.perturb.perturbType = getattr(fns.PerturbType, pt)
            n.perturb.amp = 1.0
            n.perturb.frequency = 0.5
            n.perturb.octaves = 3
            n.perturb.lacunarity = 2.0
            n.perturb.gain = 0.5
            n.perturb.normaliseLength = 1.0

        run(f"simplex_fbm_perturb_{pt.lower()}", params, cfg_p)

    # genAsGrid with axis scales: the aligned-grid path
    for scales in ((1.0, 1.0, 1.0), (1.0, 0.5, 2.0)):
        noise = fns.Noise(seed=SEED, numWorkers=1)
        noise.frequency = 0.01
        noise.noiseType = fns.NoiseType.SimplexFractal
        noise.fractal.octaves = 4
        noise.axesScales = scales
        grid = np.array(noise.genAsGrid(shape=[GRID, GRID], start=[-GRID // 2, -GRID // 2]), dtype=np.float32)
        params = {
            "source": "pyfastnoisesimd",
            "noise_type": "simplex",
            "fractal_type": "fbm",
            "seed": SEED,
            "frequency": 0.01,
            "octaves": 4,
            "lacunarity": 2.0,
            "gain": 0.5,
            "axes_scales": list(scales),
            "grid_shape": [GRID, GRID],
            "grid_start": [-GRID // 2, -GRID // 2],
        }
        written.append(
            _write(
                "fns",
                f"genasgrid_simplex_fbm_scales_{scales[0]}_{scales[1]}_{scales[2]}",
                params,
                {"grid_as_grid": grid.ravel()},
                coords,
            )
        )
    return written


# -------------------------------------------------------------------------
def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--source", choices=("fnl", "fns", "both"), default="both")
    args = parser.parse_args(argv)
    _logging.basicConfig(level=_logging.INFO, format="%(levelname)s %(message)s")
    coords = coordinates()
    VECTORS.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(VECTORS / "coords.npz", **coords)
    total = 0
    for source, fn in (("fnl", generate_fnl), ("fns", generate_fns)):
        if args.source not in (source, "both"):
            continue
        try:
            written = fn(coords)
        except ImportError as e:
            _LOGGER.warning(f"{source}: binding not importable here, skipped: {e}")
            continue
        total += len(written)
        _LOGGER.info(f"{source}: {len(written)} vector files under {VECTORS / source}")
    print(f"{total} vector files written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
