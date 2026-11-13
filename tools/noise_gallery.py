"""
HogNoise: the noise gallery, every ported noise rendered once, and the comparisons against the oracles.
Package: tools/noise_gallery

Writes contact sheets under ``Docs/noise/gallery/`` and the page that embeds them, ``Docs/noise/GALLERY.md``.
The families come from the kernel record's own enums (``IMPLEMENTED_NOISE_TYPES``, ``IMPLEMENTED_FRACTAL_TYPES``,
`CellularDistance`, `CellularReturn`, `DomainWarpType`, `PerturbType`), so a noise ported later appears here
by regenerating, and ``tests/test_noise_gallery.py`` fails when the committed page falls behind the enums.

Run from the repo root::

    python tools/noise_gallery.py            # regenerate the sheets and the page
    python tools/noise_gallery.py --check    # exit 1 if the committed page differs from a fresh render

Every tile is a 96 x 96 heightfield over x and z at y = 0 through `sample_grid`, seed 12345, the frequency
in the caption, mapped to grey over the tile's own range (printed) so a cellular distance and a signed
noise both show their structure. The comparison sheets put the oracle's grid, ours and the signed
difference side by side for the features the oracles check by point.
"""

import argparse
import logging as _logging
import sys
from collections.abc import Sequence
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "Build" / "ArtTools" / "hog-py-packages"))

from hog_noise import (  # noqa: E402
    NoiseParams,
    NumpySampler,
    compare,
    conformance,
)
from hog_noise.families import FAMILIES, enum_name  # noqa: E402

_MODULE_NAME = "tools.noise_gallery"
__version__ = "0.1.0"
__updated__ = "2026-10-03"
_LOGGER = _logging.getLogger(_MODULE_NAME)

OUT_DIR = ROOT / "Docs" / "noise" / "gallery"
PAGE = ROOT / "Docs" / "noise" / "GALLERY.md"
VECTORS = ROOT / "vectors"
TILE = 96

Tile = tuple[str, np.ndarray]  # caption, uint8 image (H, W) grey or (H, W, 3)


#: The docs' spelling of an enum value, the families module's
_name = enum_name


def _sampler(params: NoiseParams):
    # The numpy base, always installed and exact with the numba kernel: generated documentation must not
    # depend on which rung the environment selects, or a clean checkout would rewrite committed pixels
    return NumpySampler(params)


def render_tile(params: NoiseParams, size: int = TILE) -> np.ndarray:
    """A ``(size, size)`` float32 heightfield over x and z at y = 0, through the grid driver."""
    half = size // 2
    grid = _sampler(params).sample_grid((-half, 0, -half), (size, 1, size), (1.0, 1.0, 1.0))
    return grid[:, 0, :]


def _grey(values: np.ndarray) -> tuple[np.ndarray, float, float]:
    lo, hi = float(values.min()), float(values.max())
    if hi - lo < 1e-9:
        hi = lo + 1.0
    return compare._to_gray(values, lo, hi), lo, hi


def _tile(caption: str, params: NoiseParams) -> Tile:
    img, lo, hi = _grey(render_tile(params))
    return f"{caption}  [{lo:+.2f}, {hi:+.2f}]", img


def contact_sheet(tiles: Sequence[Tile], columns: int, path: Path, title: str) -> Path:
    """Tiles in rows of ``columns`` with a caption under each, a title line on top; writes ``path``."""
    from PIL import Image, ImageDraw

    if not tiles:
        raise ValueError("no tiles")
    th, tw = tiles[0][1].shape[:2]
    pad, cap_h, title_h = 6, 26, 18
    rows = (len(tiles) + columns - 1) // columns
    width = columns * (tw + pad) + pad
    height = title_h + rows * (th + cap_h + pad) + pad
    grey_only = all(img.ndim == 2 for _, img in tiles)  # a grey sheet is a third the bytes of an RGB one
    sheet = Image.new("L" if grey_only else "RGB", (width, height), 32 if grey_only else (32, 32, 32))
    draw = ImageDraw.Draw(sheet)
    bright, dim = (240, (200, 200, 200)) if not grey_only else (240, 200)
    draw.text((pad, 3), title, fill=bright)
    chars = max(1, tw // 6)
    for index, (caption, img) in enumerate(tiles):
        r, c = divmod(index, columns)
        x = pad + c * (tw + pad)
        y = title_h + r * (th + cap_h + pad)
        sheet.paste(Image.fromarray(img), (x, y))
        name, _, rng = caption.partition("  ")  # the caption's two lines: the name, then its range
        draw.text((x, y + th + 1), name[:chars], fill=dim)
        if rng:
            draw.text((x, y + th + 13), rng[:chars], fill=dim)
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(path, optimize=True)
    return path


# -------------------------------------------------------------------------
# the families, each a list of (caption, params)
# -------------------------------------------------------------------------
# comparisons against the oracles, for the features they check by point
#: A representative set, one or two per feature family, not every by-point comparison the tests make (those
#: are all of PORTED and every perturb mode; portability.md lists them). (library, feature): the case is the
#: feature's grid, and its parameters are already HogNoise's (FastNoiseSIMD's simplex is its classic Simplex).
COMPARISONS: tuple[tuple[str, str], ...] = (
    ("fns", "simplex_none"),
    ("fns", "simplex_fbm"),
    ("fns", "simplex_billow"),
    ("fns", "simplex_rigidmulti"),
    ("fns", "whitenoise_none"),
    ("fns", "simplex_fbm_perturb_gradient"),
    ("fns", "simplex_fbm_perturb_gradientfractal_normalise"),
    ("fnl", "simplex_fbm"),
    ("fnl", "simplex_smooth_fbm"),
    ("fnl", "cellular_euclidean_distance2div"),
    ("fnl", "warp_opensimplex2_domain_warp_progressive"),
)


def comparison_rows() -> list[tuple[str, compare.ComparisonStats, np.ndarray, np.ndarray]]:
    """For each listed vector: its caption, the statistics, the oracle's grid and ours."""
    vectors = conformance.load(VECTORS)
    grid_x, grid_y, grid_z = vectors.point_sets["grid_y0"].axes
    n = int(np.sqrt(len(grid_x)))
    rows = []
    for family, name in COMPARISONS:
        case = vectors.case(f"original/{family}/{name}/grid_y0")
        ours = _sampler(case.params).sample_points(grid_x, grid_y, grid_z, np.empty(n * n, np.float32))
        stats = compare.compare_values(ours, case.values)
        rows.append((f"{family}/{name}", stats, case.values.reshape(n, n), ours.reshape(n, n)))
    return rows


def comparison_sheet(rows, path: Path) -> Path:
    tiles: list[Tile] = []
    for caption, stats, ref, ours in rows:
        lo = min(stats.range_ours[0], stats.range_ref[0])
        hi = max(stats.range_ours[1], stats.range_ref[1])
        diff = ours - ref
        limit = float(np.abs(diff).max()) or 1.0
        ref, ours, diff = (
            ref[::2, ::2],
            ours[::2, ::2],
            diff[::2, ::2],
        )  # 64 px tiles: the page is a look, not a measurement
        family, _, feature = caption.partition("/")
        tiles.append((f"{feature}  {family} oracle", compare._to_gray(ref, lo, hi)))
        tiles.append((f"ours  {compare.classify(stats.max_abs)}", compare._to_gray(ours, lo, hi)))
        tiles.append((f"diff  max {stats.max_abs:.1e}", compare._diverging(diff, limit)))
    return contact_sheet(
        tiles, 3, path, "Oracle grid | ours | signed difference, per feature the oracles check by point"
    )


# -------------------------------------------------------------------------
def render_page(write_images: bool = True) -> str:
    """Render every sheet (when ``write_images``) and return the page's markdown."""
    lines = [
        "# Noise gallery",
        "",
        "**Status:** Living. Generated by `tools/noise_gallery.py` from the kernel record's enums; regenerate after",
        "porting a noise (`python tools/noise_gallery.py`), and `tests/test_noise_gallery.py` fails when this page",
        "falls behind them. Do not edit by hand.",
        "",
        "Every tile is a 96 x 96 heightfield over x and z at y = 0, seed 12345, through `sample_grid`, mapped to grey",
        "over the tile's own range (in the caption). The names are the caller-facing ones from",
        "`hog_noise.families` (the enum names); what each is and",
        "where it came from is in [PYTHON_UPGRADE_AND_FASTNOISE.md](../PYTHON_UPGRADE_AND_FASTNOISE.md), section 4.2.",
        "",
    ]
    for key, title, builder, columns in FAMILIES:
        items = builder()
        if write_images:
            contact_sheet([_tile(c, p) for c, p in items], columns, OUT_DIR / f"{key}.png", title)
        lines += [
            f"## {title}",
            "",
            f"![{title}](gallery/{key}.png)",
            "",
            "| # | Tile | Record |",
            "| --- | --- | --- |",
        ]
        for i, (caption, params) in enumerate(items):
            fields = _nondefault(params)
            lines.append(f"| {i} | `{caption}` | `{fields}` |")
        lines.append("")
    rows = comparison_rows()
    if write_images:
        comparison_sheet(rows, OUT_DIR / "comparisons.png")
    lines += [
        "## Comparisons against the oracles, a representative set",
        "",
        "A representative set of the features the oracles check by point, one or two per family (the tests compare",
        "every ported feature and every perturb mode; portability.md has them all): the oracle's 128 x 128 grid,",
        "ours, and the signed difference.",
        "`fns` is the retired FastNoiseSIMD (its own hash, so only its own features compare by point); `fnl` is",
        "`pyfastnoiselite`, and the warp row comes from the C++ harness in `tools/noise_oracle`. Every other",
        "comparison the tests make is in [portability.md](../../vectors/portability.md); a mismatch past",
        "the advisory bar writes a sheet to `vectors/reports/` and waits for a verdict in `accepted.json`.",
        "",
        "Read the difference tile, not the grids: the captured grids span 4096 units at frequency 0.01, about three",
        "samples per period, so at 128 px they alias into static for every feature but the smoothest. The",
        "difference is scaled to its own maximum (white is zero) and the caption carries the measured maximum.",
        "",
        "![comparisons](gallery/comparisons.png)",
        "",
        "| Feature | Class | Max abs | Mean abs | Correlation |",
        "| --- | --- | --- | --- | --- |",
    ]
    for caption, stats, _ref, _ours in rows:
        lines.append(
            f"| `{caption}` | {compare.classify(stats.max_abs)} "
            f"| {stats.max_abs:.2e} | {stats.mean_abs:.2e} | {stats.correlation:.6f} |"
        )
    lines.append("")
    return "\n".join(lines)


def _nondefault(params: NoiseParams) -> str:
    default = NoiseParams()
    parts = []
    for field in params.__dataclass_fields__:
        v = getattr(params, field)
        if v != getattr(default, field) and field != "seed":
            parts.append(f"{field}={getattr(v, 'name', v).lower() if hasattr(v, 'name') else v}")
    return ", ".join(parts) or "defaults"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="compare a fresh page with the committed one; no writes")
    args = parser.parse_args(argv)
    _logging.basicConfig(level=_logging.INFO, format="%(levelname)s %(message)s")
    if args.check:
        fresh = render_page(write_images=False)
        current = PAGE.read_text(encoding="utf-8") if PAGE.exists() else ""
        if fresh != current:
            print("noise gallery: the committed page is behind the enums; run python tools/noise_gallery.py")
            return 1
        missing = [f"{key}.png" for key, *_ in FAMILIES if not (OUT_DIR / f"{key}.png").exists()]
        if not (OUT_DIR / "comparisons.png").exists():
            missing.append("comparisons.png")
        if missing:
            print(
                f"noise gallery: sheets missing under {OUT_DIR}: {', '.join(missing)}; "
                "run python tools/noise_gallery.py"
            )
            return 1
        print("noise gallery: page current")
        return 0
    page = render_page()
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    PAGE.write_text(page, encoding="utf-8", newline="\n")
    print(f"noise gallery: {len(FAMILIES)} sheets and the comparisons under {OUT_DIR}; page {PAGE}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
