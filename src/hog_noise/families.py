"""
HogNoise: the parameter families every ported noise is shown in: the gallery's sheets and an app's presets.
Package: hog_noise/families

One list per family of `NoiseParams`, each row captioned. `tools/noise_gallery.py` renders them as contact
sheets for `Docs/noise/GALLERY.md`; an app can offer them as presets. They are built from
the enums, so a newly ported noise appears in both the moment its enum is implemented.
"""

import logging as _logging
from collections.abc import Callable, Sequence

from hog_noise.params import (
    CELLULAR_DISTANCE_NAMES,
    CELLULAR_RETURN_NAMES,
    DOMAIN_WARP_NAMES,
    FRACTAL_TYPE_NAMES,
    IMPLEMENTED_FRACTAL_TYPES,
    IMPLEMENTED_NOISE_TYPES,
    NOISE_TYPE_NAMES,
    PERTURB_NAMES,
    CellularDistance,
    CellularReturn,
    DomainWarpType,
    FractalType,
    NoiseParams,
    NoiseType,
    PerturbType,
    parse_noise_type,
)

_MODULE_NAME = "hog_noise.families"
__version__ = "0.1.0"
__updated__ = "2026-10-03"
_LOGGER = _logging.getLogger(_MODULE_NAME)

#: The seed and frequency every family shares, so sheets and presets compare like with like
SEED = 12345
FREQ = 0.03

#: A captioned parameter record
Preset = tuple[str, NoiseParams]
#: ``(key, title, builder, sheet columns)``
Family = tuple[str, str, Callable[[], list[Preset]], int]


def enum_name(table: dict[str, object], value: object) -> str:
    """The first (canonical) name a `*_NAMES` table gives ``value``."""
    for key, v in table.items():
        if v == value:
            return key
    return str(getattr(value, "name", value)).lower()


def family_types() -> list[Preset]:
    """Every implemented noise type, one octave."""
    return [
        (enum_name(NOISE_TYPE_NAMES, nt), NoiseParams(seed=SEED, frequency=FREQ, noise_type=nt))
        for nt in sorted(IMPLEMENTED_NOISE_TYPES)
    ]


def family_fractals() -> list[Preset]:
    """Every implemented fractal over OpenSimplex2, four octaves; the warp fractals belong to the warp family."""
    out = []
    for ft in sorted(IMPLEMENTED_FRACTAL_TYPES):
        if ft in (FractalType.DOMAIN_WARP_PROGRESSIVE, FractalType.DOMAIN_WARP_INDEPENDENT):
            continue  # those shape the warp, shown in the warp family
        out.append(
            (enum_name(FRACTAL_TYPE_NAMES, ft), NoiseParams(seed=SEED, frequency=FREQ, fractal_type=ft, octaves=4))
        )
    return out


def family_cellular() -> list[Preset]:
    """Every cellular distance against every return, rows by distance."""
    out = []
    for dist in CellularDistance:
        for ret in CellularReturn:
            out.append(
                (
                    f"{enum_name(CELLULAR_DISTANCE_NAMES, dist)} {enum_name(CELLULAR_RETURN_NAMES, ret)}",
                    NoiseParams(
                        seed=SEED,
                        frequency=FREQ * 2,
                        noise_type=NoiseType.CELLULAR,
                        cellular_distance=dist,
                        cellular_return=ret,
                        cellular_lookup_type=NoiseType.PERLIN,
                        cellular_lookup_frequency=0.3,
                    ),
                )
            )
    return out


def family_warp() -> list[Preset]:
    """Every domain warp type in its single, progressive and independent modes over OpenSimplex2 FBm."""
    out = [("no warp", NoiseParams(seed=SEED, frequency=FREQ, fractal_type=FractalType.FBM, octaves=3))]
    modes = (
        ("single", FractalType.NONE),
        ("progressive", FractalType.DOMAIN_WARP_PROGRESSIVE),
        ("independent", FractalType.DOMAIN_WARP_INDEPENDENT),
    )
    for warp in DomainWarpType:
        if warp == DomainWarpType.NONE:
            continue
        for mode_name, ft in modes:
            out.append(
                (
                    f"{enum_name(DOMAIN_WARP_NAMES, warp)} {mode_name}",
                    NoiseParams(
                        seed=SEED, frequency=FREQ, fractal_type=ft, octaves=3, domain_warp=warp, domain_warp_amp=20.0
                    ),
                )
            )
    return out


def family_perturb() -> list[Preset]:
    """Every gradient perturb mode over classic Simplex FBm."""
    base = NoiseParams(
        seed=SEED, frequency=FREQ, noise_type=NoiseType.SIMPLEX_CLASSIC, fractal_type=FractalType.FBM, octaves=4
    )
    out = [("no perturb", base)]
    for pt in PerturbType:
        if pt == PerturbType.NONE:
            continue
        out.append(
            (enum_name(PERTURB_NAMES, pt), base.replace(perturb=pt, perturb_amp=1.0, perturb_normalise_length=30.0))
        )
    return out


def family_simplex_lineage() -> list[Preset]:
    """The three simplexes at one seed."""
    return [
        (name, NoiseParams(seed=SEED, frequency=FREQ, noise_type=parse_noise_type(name)))
        for name in ("simplex_classic", "simplex", "simplex_smooth")
    ]


FAMILIES: Sequence[Family] = (
    ("types", "Noise types, one octave", family_types, 4),
    ("fractals", "Fractals over OpenSimplex2, four octaves", family_fractals, 3),
    (
        "cellular",
        "Cellular: every distance (rows) against every return (columns)",
        family_cellular,
        len(CellularReturn),
    ),
    ("warp", "Domain warp over OpenSimplex2 FBm, amplitude 20", family_warp, 5),
    ("perturb", "Gradient perturb over classic Simplex FBm", family_perturb, 3),
    (
        "simplex_lineage",
        "The three simplexes at one seed: the retired library's, FastNoiseLite's, and the smooth variant",
        family_simplex_lineage,
        3,
    ),
)


def all_presets() -> list[tuple[str, str, NoiseParams]]:
    """Every family's rows flattened as ``(family key, caption, params)``, in family order."""
    out: list[tuple[str, str, NoiseParams]] = []
    for key, _title, builder, _columns in FAMILIES:
        out.extend((key, caption, params) for caption, params in builder())
    return out


if __name__ == "__main__":
    for key, title, builder, columns in FAMILIES:
        rows = builder()
        print(f"{key}: {title} ({len(rows)} tiles, {columns} columns)")
        for caption, params in rows[:3]:
            print(f"    {caption}: {params.noise_type.name} {params.fractal_type.name}")
    print(f"{len(all_presets())} presets in all")
