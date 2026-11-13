"""
HogNoise: generate the reference vectors, raw float32 and one manifest under ``vectors/``.
Package: tools/gen_noise_vectors

The format and the rules are the conformance harness spec's (Docs/superpowers/specs/2026-11-11-conformance-harness.md):
every coordinate and value file is raw little-endian float32, and ``vectors/manifest.json`` names each case, its
parameters in HogNoise's names, its point set and how it is compared. `compare_for` and `params_for` are the rules that
make a captured array a case; `write_originals` and `generate_hog` write through the one writer.

Two sets:

- ``--set hog`` (the default): for every distinct (parameters, point set, output) among the original cases, the numpy
  rendering's output, compared bit for bit. Any environment with numpy; rerun it when a kernel change moves a value.
- ``--set original``: captures from the original libraries, as they always were. ``fnl`` is `pyfastnoiselite`, the
  FastNoiseLite reference, plus the domain-warp vectors from the C++ oracle harness in ``tools/noise_oracle`` (the
  binding does not expose ``DomainWarp``; the harness is built on first use and reproduces the binding's
  ``gen_from_coords`` bit for bit). ``fns`` is `pyfastnoisesimd`, FastNoiseSIMD: its wheels stop at Python 3.9 and this
  tool now needs the package's own floor (3.11), so a capture needs a source build, which ADR-007 records working on
  3.12 and 3.13 with bit-identical output. Then the hog set is regenerated.

    python tools/gen_noise_vectors.py                          # the hog set
    python tools/gen_noise_vectors.py --set original --source fnl

Coordinates are fixed by seed. Scattered samples: 4096 points, x and z in [-4096, 4096], y in [-256, 256]. Grid:
128 x 128 over x, z in [-2048, 2048] at y = 0, the XZ-plane heightfield case. The two ``genasgrid`` grids are
``sample_grid((-64, -64, 1), (128, 128, 1), scales)``'s coordinates, written out so no reader rebuilds a grid.
"""

import argparse
import hashlib
import json
import logging as _logging
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

from hog_noise import (
    NoiseParams,
    conformance,
    parse_cellular_distance,
    parse_cellular_return,
    parse_domain_warp,
    parse_fractal_type,
    parse_noise_type,
    parse_perturb,
)
from hog_noise.samplers import grid_points

_MODULE_NAME = "tools.gen_noise_vectors"
__version__ = "0.1.0"
__updated__ = "2026-11-13"
_LOGGER = _logging.getLogger(_MODULE_NAME)

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "vectors"
N_SCATTER = 4096
GRID = 128
GRID_EXTENT = 2048.0
SEED = 12345
COORD_SEED = 7


def coordinates() -> dict[str, np.ndarray]:
    rng = np.random.RandomState(COORD_SEED)
    xs = rng.uniform(-4096, 4096, N_SCATTER).astype(np.float32)
    ys = rng.uniform(-256, 256, N_SCATTER).astype(np.float32)
    zs = rng.uniform(-4096, 4096, N_SCATTER).astype(np.float32)
    axis = np.linspace(-GRID_EXTENT, GRID_EXTENT, GRID, dtype=np.float32)
    gx, gz = np.meshgrid(axis, axis)
    return {"xs": xs, "ys": ys, "zs": zs, "grid_x": gx.ravel(), "grid_z": gz.ravel()}


#: One capture: (library, feature, the library's own parameter record, its arrays by name).
Capture = tuple[str, str, dict, dict[str, np.ndarray]]


def _write(
    source: str, feature: str, params: dict[str, object], values: dict[str, np.ndarray], coords: dict[str, np.ndarray]
) -> Capture:
    """One capture, returned to the caller; `main` writes them all through `write_originals`."""
    return (source, feature, dict(params), {k: np.asarray(v, np.float32) for k, v in values.items()})


# -------------------------------------------------------------------------
# the vectors folder: raw little-endian float32 and one manifest (spec: 2026-11-11-conformance-harness)
GENASGRID_SCALES = ((1.0, 1.0, 1.0), (1.0, 0.5, 2.0))
GENASGRID_START, GENASGRID_SHAPE = (-64, -64, 1), (128, 128, 1)


def _genasgrid_name(scales) -> str:
    return "genasgrid_" + "_".join(repr(float(s)) for s in scales)


def _point_sets() -> dict[str, dict[str, object]]:
    """Every point set the vectors use, built once: the scatters, the y = 0 grid and the two genAsGrid grids."""
    point_sets: dict[str, dict[str, object]] = {
        "scatter_3d": {
            "dims": 3,
            "count": N_SCATTER,
            "axes": ["points/scatter_x.f32", "points/scatter_y.f32", "points/scatter_z.f32"],
        },
        "scatter_2d": {"dims": 2, "count": N_SCATTER, "axes": ["points/scatter_x.f32", "points/scatter_z.f32"]},
        "grid_y0": {
            "dims": 3,
            "count": GRID * GRID,
            "axes": ["points/grid_x.f32", "points/grid_y.f32", "points/grid_z.f32"],
        },
    }
    for scales in GENASGRID_SCALES:
        name = _genasgrid_name(scales)
        point_sets[name] = {
            "dims": 3,
            "count": 128 * 128,
            "axes": [f"points/{name}_{axis}.f32" for axis in "xyz"],
            "from": {
                "start": list(GENASGRID_START),
                "shape": list(GENASGRID_SHAPE),
                "scales": list(scales),
                "order": "C",
            },
        }
    return point_sets


POINT_SETS = _point_sets()

#: Which point set and output each captured array is on.
ARRAYS = {
    "scatter_3d": ("scatter_3d", "noise"),
    "scatter_2d": ("scatter_2d", "noise"),
    "grid_3d": ("grid_y0", "noise"),
    "warp_3d": ("scatter_3d", "warp"),
    "warp_2d": ("scatter_2d", "warp"),
    "grid_warp_3d": ("grid_y0", "warp"),
}
CLASSIC_SIMPLEX_BOUNDS = {"simplex_none": 5e-5, "simplex_fbm": 2e-4, "simplex_billow": 5e-4, "simplex_rigidmulti": 5e-4}
BILLOW_SHAPE = {"perlin_billow", "value_billow", "cubic_billow", "simplex_billow"}
CELLULAR_SHAPE = {
    "cellular_natural_distance",
    "cellular_natural_cellvalue",
    "cellular_euclidean_noiselookup",
    "cellular_euclidean_distance2cave",
}
#: FastNoiseLite's grid_warp_3d had never been compared. The conversion measured it on 2026-11-12: the largest
#: difference over the nine features was 7.47e-4, inside the warp field's 4e-3, so it is gated there (spec, The cases).
GRID_WARP_COMPARE: dict[str, object] = {"kind": "points", "bound": {"scale": 4e-3, "coordinate_scaled": False}}


def _points(scale: float, **extra: object) -> dict[str, object]:
    return {"kind": "points", "bound": {"scale": scale, "coordinate_scaled": False}, **extra}


def compare_for(library: str, feature: str, array: str, variant: str | None = None) -> dict[str, object]:
    """How a captured array is compared: today's limits from tests/test_hog_noise/test_kernels.py, carried over."""
    if library == "fnl":
        if array in ("warp_3d", "warp_2d"):
            return _points(4e-3)
        if array == "grid_warp_3d":
            return dict(GRID_WARP_COMPARE)
        return {"kind": "advisory"}
    if feature in CLASSIC_SIMPLEX_BOUNDS and variant is None and array in ("scatter_3d", "grid_3d"):
        bound = CLASSIC_SIMPLEX_BOUNDS[feature]
        return _points(bound, min_correlation=0.9999) if array == "scatter_3d" else _points(bound)
    if feature.startswith("simplex_fbm_perturb_") and array == "scatter_3d":
        return _points(1e-3, min_correlation=0.9999)
    if feature == "whitenoise_none" and array == "scatter_3d":
        return _points(1e-6)
    if feature in BILLOW_SHAPE and array == "scatter_3d" and (feature != "simplex_billow" or variant == "shape"):
        return {"kind": "shape", "range": [-1.05, 1.05], "mean_within": 0.2, "std_within": 0.2}
    if feature in CELLULAR_SHAPE and array == "scatter_3d":
        return {"kind": "shape", "finite": True, "std_ratio": [0.3, 3.0]}
    if feature.startswith("genasgrid_"):
        return _points(2e-3, within={"scale": 1e-4, "fraction": 0.98})
    return {"kind": "advisory"}


def params_for(library: str, feature: str, record: dict, variant: str | None = None) -> NoiseParams:
    """
    A capture's record, in its library's spelling, as the parameters the suite samples it with. FastNoiseSIMD's
    ``simplex`` is its classic Simplex, except in the shape comparison of ``simplex_billow``, which is OpenSimplex2.
    """
    noise = record["noise_type"]
    if library == "fns" and noise == "simplex" and variant != "shape":
        noise = "simplex_classic"
    kwargs: dict[str, object] = dict(
        seed=record["seed"],
        frequency=record["frequency"],
        noise_type=parse_noise_type(noise),
        fractal_type=parse_fractal_type(record["fractal_type"]),
        octaves=record.get("octaves", 1),
        lacunarity=record.get("lacunarity", 2.0),
        gain=record.get("gain", 0.5),
        weighted_strength=record.get("weighted_strength", 0.0),
        ping_pong_strength=record.get("ping_pong_strength", 2.0),
        rotation_3d={"improve_xy": 1, "improve_xz": 2}.get(record.get("rotation_3d", ""), 0),
        cellular_distance=parse_cellular_distance(record.get("cellular_distance", "euclideansq")),
        cellular_return=parse_cellular_return(record.get("cellular_return", "distance")),
        cellular_jitter=record.get("cellular_jitter", 1.0),
        cellular_lookup_frequency=record.get("lookup_frequency", 0.2),
        domain_warp=parse_domain_warp(record.get("domain_warp", "none")),
        domain_warp_amp=record.get("domain_warp_amp", 1.0),
    )
    if "perturb_type" in record:
        kwargs.update(
            perturb=parse_perturb(record["perturb_type"]),
            perturb_amp=record["perturb_amp"],
            perturb_frequency=record["perturb_frequency"],
            perturb_octaves=record["perturb_octaves"],
            perturb_lacunarity=record["perturb_lacunarity"],
            perturb_gain=record["perturb_gain"],
            perturb_normalise_length=record["perturb_normalise_length"],
        )
    return NoiseParams(**kwargs)


def _where(array: str, record: dict) -> tuple[str, str]:
    if array == "grid_as_grid":
        return _genasgrid_name(record["axes_scales"]), "noise"
    return ARRAYS[array]


def case_id(set_: str, library: str, feature: str, point_set: str, output: str, variant: str | None = None) -> str:
    warp = "/warp" if output == "warp" else ""
    return f"{set_}/{library}/{feature}/{point_set}{warp}" + (f"#{variant}" if variant else "")


def case_file(set_: str, library: str, feature: str, point_set: str, output: str, variant: str | None = None) -> str:
    warp = ".warp" if output == "warp" else ""
    return f"{set_}/{library}/{feature}.{point_set}{warp}" + (f"#{variant}" if variant else "") + ".f32"


def original_cases(library: str, feature: str, record: dict, arrays: list[str]) -> list[dict[str, object]]:
    """The manifest entries for one capture's arrays; ``simplex_billow``'s scatter is also a ``#shape`` case."""
    cases = []
    for array in arrays:
        point_set, output = _where(array, record)
        file = case_file("original", library, feature, point_set, output)
        variants = [None, "shape"] if (library, feature, array) == ("fns", "simplex_billow", "scatter_3d") else [None]
        for variant in variants:
            cases.append(
                {
                    "id": case_id("original", library, feature, point_set, output, variant),
                    "set": "original",
                    "source": {"library": library, "feature": feature, "array": array, "params": record},
                    "params": params_for(library, feature, record, variant).to_dict(),
                    "point_set": point_set,
                    "output": output,
                    "file": file,
                    "compare": compare_for(library, feature, array, variant),
                }
            )
    return cases


def write_f32(root: Path, rel: str, values: np.ndarray) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(np.ascontiguousarray(np.asarray(values, dtype="<f4")).tobytes())


def write_manifest(root: Path, point_sets: dict[str, dict[str, object]], cases: list[dict[str, object]]) -> Path:
    """Write the manifest sorted, with every digest recomputed from the files on disk."""
    named = [a for ps in point_sets.values() for a in ps["axes"]] + [c["file"] for c in cases]
    files = {rel: hashlib.sha256((root / rel).read_bytes()).hexdigest() for rel in sorted(set(named))}
    manifest = {
        "format": conformance.FORMAT,
        "point_sets": dict(sorted(point_sets.items())),
        "cases": sorted(cases, key=lambda c: c["id"]),
        "files": files,
    }
    path = root / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    _LOGGER.info(f"manifest: {len(cases)} cases, {len(point_sets)} point sets, {len(files)} files digested -> {path}")
    return path


def _point_arrays(coords: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """Every point file's contents, by its path in the folder."""
    arrays = {
        "points/scatter_x.f32": coords["xs"],
        "points/scatter_y.f32": coords["ys"],
        "points/scatter_z.f32": coords["zs"],
        "points/grid_x.f32": coords["grid_x"],
        "points/grid_y.f32": np.zeros_like(coords["grid_x"]),
        "points/grid_z.f32": coords["grid_z"],
    }
    for scales in GENASGRID_SCALES:
        for axis, values in zip("xyz", grid_points(GENASGRID_START, GENASGRID_SHAPE, scales), strict=True):
            arrays[f"points/{_genasgrid_name(scales)}_{axis}.f32"] = values
    return arrays


def _f32_bytes(values: np.ndarray) -> bytes:
    return np.ascontiguousarray(np.asarray(values, dtype="<f4")).tobytes()


def write_originals(root: Path, captured: list[Capture], coords: dict[str, np.ndarray]) -> Path:
    """
    Write captured arrays as original cases. Cases of features captured again are replaced; every other case in an
    existing manifest is kept. Run ``--set hog`` afterwards.

    :raises ValueError: A record that does not map (before anything is written), or coordinates that differ from
        the point files an original case kept here was sampled on: those captures would no longer match their points.
    """
    existing = []
    if (root / "manifest.json").exists():
        existing = json.loads((root / "manifest.json").read_text(encoding="utf-8"))["cases"]
    redone = {(library, feature) for library, feature, _, _ in captured}
    cases = [
        c for c in existing if c["set"] != "original" or (c["source"]["library"], c["source"]["feature"]) not in redone
    ]
    new_cases = []
    for library, feature, record, arrays in captured:
        new_cases.extend(original_cases(library, feature, record, sorted(arrays)))  # maps every record first
    points = _point_arrays(coords)
    kept_axes = {a for c in cases if c["set"] == "original" for a in POINT_SETS[c["point_set"]]["axes"]}
    for rel in sorted(kept_axes):
        if (root / rel).exists() and (root / rel).read_bytes() != _f32_bytes(points[rel]):
            raise ValueError(f"{rel}: these coordinates differ from the ones kept original cases were sampled on")
    for rel, values in points.items():
        write_f32(root, rel, values)
    for library, feature, _record, arrays in captured:
        for case in (c for c in new_cases if c["source"]["library"] == library and c["source"]["feature"] == feature):
            write_f32(root, case["file"], arrays[case["source"]["array"]])
    _LOGGER.info(
        f"original: {len(captured)} captures as {len(new_cases)} cases under {root / 'original'}, "
        f"{len(cases)} cases kept, {len(points)} point files"
    )
    return write_manifest(root, POINT_SETS, cases + new_cases)


def generate_hog(root: Path = OUT) -> list[str]:
    """
    The hog set: for every distinct (parameters, point set, output) among the original cases, the numpy rendering's
    output, compared at Bound(0). Rewritten whole; the first original case (by id) of each key names it.

    It reads only the original cases, and writes the new files into a staging folder beside ``root`` that replaces
    ``hog/`` only once every case has been rendered, so a failure part way leaves the folder as it was and a rerun
    works whatever state the hog files are in.
    """
    vectors = conformance.load(root, sets=("original",))  # verifies the originals and the points
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    originals = sorted((c for c in manifest["cases"] if c["set"] == "original"), key=lambda c: c["id"])
    sample, warp = conformance.renderings("numpy")
    stage = Path(tempfile.mkdtemp(prefix=f"{root.name}.hog-", dir=root.parent))
    try:
        seen: set[tuple[str, str, str]] = set()
        hog: list[dict[str, object]] = []
        for c in originals:
            key = (json.dumps(c["params"], sort_keys=True), c["point_set"], c["output"])
            if key in seen:
                continue
            seen.add(key)
            library, feature = c["source"]["library"], c["source"]["feature"]
            variant = c["id"].partition("#")[2] or None
            ps = vectors.point_sets[c["point_set"]]
            fn = warp if c["output"] == "warp" else sample
            values = fn(
                NoiseParams.from_dict(c["params"]), ps.axes[0], ps.axes[1], ps.axes[2] if ps.dims == 3 else None
            )
            file = case_file("hog", library, feature, c["point_set"], c["output"], variant)
            write_f32(stage, file, values)
            hog.append(
                dict(
                    c,
                    id=case_id("hog", library, feature, c["point_set"], c["output"], variant),
                    set="hog",
                    file=file,
                    compare=_points(0.0),
                    source=dict(c["source"], from_case=c["id"]),
                )
            )
        shutil.rmtree(root / "hog", ignore_errors=True)
        if (stage / "hog").exists():
            shutil.move(str(stage / "hog"), str(root / "hog"))
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    write_manifest(root, manifest["point_sets"], originals + hog)
    _LOGGER.info(f"hog: {len(hog)} cases from {len(originals)} original cases under {root / 'hog'}")
    return [str(c["id"]) for c in hog]


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


def generate_fnl(coords: dict[str, np.ndarray]) -> list[Capture]:
    from pyfastnoiselite.pyfastnoiselite import (
        CellularDistanceFunction,
        CellularReturnType,
        FastNoiseLite,
        FractalType,
        NoiseType,
        RotationType3D,
    )

    captured = []

    def run(feature: str, params: dict[str, object], configure) -> None:
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
        captured.append(_write("fnl", feature, params, values, coords))

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
        captured.extend(generate_fnl_warp(coords))
    except (ImportError, OSError, subprocess.CalledProcessError) as e:
        # the warp vectors need the C++ oracle, which needs MSVC on Windows; the binding's own vectors
        # above do not, so a regeneration elsewhere keeps them and says what it skipped
        _LOGGER.warning(f"fnl: domain-warp vectors skipped, the oracle harness is unavailable here: {e}")
    return captured


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
    exe: Path, mode: str, points: np.ndarray, params: dict[str, object], warp_type: int, fractal: int
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


def generate_fnl_warp(coords: dict[str, np.ndarray]) -> list[Capture]:
    """
    Every warp type x warp fractal, amplitude 30 at frequency 0.01 over OpenSimplex2: the warped
    coordinates (``warp_2d`` N x 2, ``warp_3d`` N x 3, ``grid_warp_3d``) and the noise the reference
    then samples at them (``scatter_2d``, ``scatter_3d``, ``grid_3d``), so the existing noise
    comparison covers the end-to-end path and a second test covers the warp field itself.
    """
    exe = _oracle_exe()
    captured = []
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
            captured.append(_write("fnl", f"warp_{warp_name}_{fractal_name}", params, values, coords))
    return captured


# -------------------------------------------------------------------------
# FastNoiseSIMD
def generate_fns(coords: dict[str, np.ndarray]) -> list[Capture]:
    import pyfastnoisesimd as fns

    captured = []
    n_grid = len(coords["grid_x"])

    def gen_coords(noise, xs, ys, zs):
        buf = fns.empty_coords(len(xs))
        buf[0, : len(xs)] = xs
        buf[1, : len(xs)] = ys
        buf[2, : len(xs)] = zs
        return np.array(noise.genFromCoords(buf)[: len(xs)], dtype=np.float32)

    def run(feature: str, params: dict[str, object], configure) -> None:
        noise = fns.Noise(seed=SEED, numWorkers=1)
        noise.frequency = params["frequency"]
        configure(noise)
        values = {
            "scatter_3d": gen_coords(noise, coords["xs"], coords["ys"], coords["zs"]),
            "grid_3d": gen_coords(noise, coords["grid_x"], np.zeros(n_grid, np.float32), coords["grid_z"]),
        }
        captured.append(_write("fns", feature, params, values, coords))

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
        captured.append(
            _write(
                "fns",
                f"genasgrid_simplex_fbm_scales_{scales[0]}_{scales[1]}_{scales[2]}",
                params,
                {"grid_as_grid": grid.ravel()},
                coords,
            )
        )
    return captured


# -------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--set", choices=("hog", "original"), default="hog", dest="which")
    parser.add_argument("--source", choices=("fnl", "fns", "both"), default="both", help="for --set original")
    args = parser.parse_args(argv)
    _logging.basicConfig(level=_logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    if args.which == "original":
        coords = coordinates()
        captured: list[Capture] = []
        for source, fn in (("fnl", generate_fnl), ("fns", generate_fns)):
            if args.source not in (source, "both"):
                continue
            try:
                captured.extend(fn(coords))
            except ImportError as e:
                _LOGGER.warning(f"{source}: binding not importable here, skipped: {e}")
                continue
        if not captured:
            print("no capture ran; nothing written")
            return 1
        write_originals(OUT, captured, coords)
    hog = generate_hog(OUT)
    print(f"{len(hog)} hog cases written under {OUT / 'hog'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
