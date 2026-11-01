"""
HogNoise: compare two noise renderings, draw the difference, and record the human's verdict.
Package: hog_noise/compare

The comparison discipline from Docs/PYTHON_UPGRADE_AND_FASTNOISE.md, section 4.3:

- **Always run, always report.** `compare_values` returns the numbers: max and mean absolute
  difference, correlation, both value ranges, and a match class.
- **A mismatch is not a failure.** `render_sheet` writes a PNG (reference, ours, signed difference
  as a diverging heatmap, histogram of the difference, the numbers) so a human can look; the test
  layer marks the case ``needs-review`` and consults `Verdicts` for a recorded decision.
- **Portability is written down.** `write_portability` regenerates the per-feature table of which
  rungs matched which and how closely.

Pillow only; no matplotlib in this project. The verdict file is JSON rather than TOML because the
supported floor still lacks ``tomllib``; the name ``accepted.json`` is what the docs mean by the
accepted manifest.
"""

import dataclasses
import json
import logging as _logging
from datetime import date
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np
from numpy.typing import NDArray

_MODULE_NAME = "hog_noise.compare"
__version__ = "0.1.0"
__updated__ = "2026-09-13"
_LOGGER = _logging.getLogger(_MODULE_NAME)

#: Match classes, tightest first. The class is the first whose threshold the max difference meets.
MATCH_CLASSES: Tuple[Tuple[str, float], ...] = (
    ("exact", 0.0),
    ("float32", 1e-6),
    ("tight", 1e-4),
    ("loose", 1e-2),
)
#: Below this, the comparison is flagged for a human even if the range still looks right.
MIN_CORRELATION = 0.99


@dataclasses.dataclass(frozen=True)
class ComparisonStats:
    """The numbers one comparison produced."""

    max_abs: float
    mean_abs: float
    correlation: float
    range_ours: Tuple[float, float]
    range_ref: Tuple[float, float]
    count: int
    match_class: str

    @property
    def needs_review(self) -> bool:
        """True when the match is looser than ``tight`` or the correlation is below the bar."""
        return self.match_class in ("loose", "mismatch") or self.correlation < MIN_CORRELATION

    def summary(self) -> str:
        return (
            f"max {self.max_abs:.3e}, mean {self.mean_abs:.3e}, corr {self.correlation:.6f}, "
            f"ours [{self.range_ours[0]:+.4f}, {self.range_ours[1]:+.4f}], "
            f"ref [{self.range_ref[0]:+.4f}, {self.range_ref[1]:+.4f}], class {self.match_class}"
        )


def classify(max_abs: float) -> str:
    for name, threshold in MATCH_CLASSES:
        if max_abs <= threshold:
            return name
    return "mismatch"


def compare_values(ours: NDArray, ref: NDArray) -> ComparisonStats:
    """
    Compare two arrays of the same shape.

    :param ours: Values from the implementation under test.
    :param ref: Values from the reference.
    :return: The statistics.
    :raises ValueError: On a shape mismatch.
    """
    a = np.asarray(ours, dtype=np.float64).ravel()
    b = np.asarray(ref, dtype=np.float64).ravel()
    if a.shape != b.shape:
        raise ValueError(f"shape mismatch: ours {a.shape} vs ref {b.shape}")
    diff = np.abs(a - b)
    if a.std() == 0.0 or b.std() == 0.0:
        corr = 1.0 if diff.max() == 0.0 else 0.0
    else:
        corr = float(np.corrcoef(a, b)[0, 1])
    max_abs = float(diff.max()) if diff.size else 0.0
    return ComparisonStats(
        max_abs=max_abs,
        mean_abs=float(diff.mean()) if diff.size else 0.0,
        correlation=corr,
        range_ours=(float(a.min()), float(a.max())),
        range_ref=(float(b.min()), float(b.max())),
        count=int(a.size),
        match_class=classify(max_abs),
    )


# -------------------------------------------------------------------------
# sheets
def _to_gray(grid: NDArray, lo: float, hi: float) -> NDArray[np.uint8]:
    span = hi - lo if hi > lo else 1.0
    return np.clip((grid - lo) / span * 255.0, 0, 255).astype(np.uint8)


def _diverging(diff: NDArray, limit: float) -> NDArray[np.uint8]:
    """Signed difference as blue (negative), white (zero), red (positive), symmetric about 0."""
    limit = limit if limit > 0 else 1.0
    t = np.clip(diff / limit, -1.0, 1.0)
    rgb = np.empty(diff.shape + (3,), dtype=np.float64)
    pos = t >= 0
    rgb[..., 0] = np.where(pos, 1.0, 1.0 + t)
    rgb[..., 1] = 1.0 - np.abs(t)
    rgb[..., 2] = np.where(pos, 1.0 - t, 1.0)
    return (rgb * 255.0).astype(np.uint8)


def render_sheet(
    ref_grid: NDArray, ours_grid: NDArray, path: Path, title: str, stats: Optional[ComparisonStats] = None
) -> Path:
    """
    Write a comparison sheet: reference, ours, signed difference, difference histogram, numbers.

    :param ref_grid: 2D array from the reference.
    :param ours_grid: 2D array from ours, same shape.
    :param path: PNG to write; parents are created.
    :param title: Caption, usually the feature name.
    :param stats: Precomputed statistics; computed when omitted.
    :return: The path written.
    """
    from PIL import Image, ImageDraw

    ref_grid = np.asarray(ref_grid, dtype=np.float64)
    ours_grid = np.asarray(ours_grid, dtype=np.float64)
    if stats is None:
        stats = compare_values(ours_grid, ref_grid)
    lo = min(stats.range_ours[0], stats.range_ref[0])
    hi = max(stats.range_ours[1], stats.range_ref[1])
    diff = ours_grid - ref_grid
    limit = float(np.abs(diff).max()) or 1.0

    h, w = ref_grid.shape
    pad = 8
    text_h = 64
    hist_h = 64
    sheet = Image.new("RGB", (3 * w + 4 * pad, h + hist_h + text_h + 4 * pad), (32, 32, 32))
    sheet.paste(Image.fromarray(_to_gray(ref_grid, lo, hi)), (pad, pad))
    sheet.paste(Image.fromarray(_to_gray(ours_grid, lo, hi)), (2 * pad + w, pad))
    sheet.paste(Image.fromarray(_diverging(diff, limit)), (3 * pad + 2 * w, pad))

    # histogram of the signed difference, 64 bins, drawn as bars under the panels
    draw = ImageDraw.Draw(sheet)
    counts, edges = np.histogram(diff, bins=64, range=(-limit, limit))
    top = pad * 2 + h
    total_w = 3 * w + 2 * pad
    bar_w = max(1, total_w // 64)
    peak = counts.max() or 1
    for i, c in enumerate(counts):
        bh = int(hist_h * c / peak)
        x0 = pad + i * bar_w
        draw.rectangle([x0, top + hist_h - bh, x0 + bar_w - 1, top + hist_h], fill=(200, 200, 200))
    draw.line([pad + total_w // 2, top, pad + total_w // 2, top + hist_h], fill=(255, 80, 80))

    y = top + hist_h + pad
    draw.text(
        (pad, y),
        f"{title}    reference | ours | ours - reference (blue < 0 < red, +-{limit:.3e})",
        fill=(240, 240, 240),
    )
    draw.text((pad, y + 16), stats.summary(), fill=(240, 240, 240))
    draw.text(
        (pad, y + 32),
        "needs review" if stats.needs_review else "within the advisory bar",
        fill=(255, 200, 80) if stats.needs_review else (120, 220, 120),
    )

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(path)
    _LOGGER.info(f"Comparison sheet written: {path}")
    return path


# -------------------------------------------------------------------------
# verdicts and portability
class Verdicts:
    """
    The accepted manifest: a human's decision per feature key, in a JSON file.

    Shape: ``{"<feature>": {"verdict": "accepted" | "rejected", "by": "...", "date": "YYYY-MM-DD",
    "note": "..."}}``. Missing key means no decision yet.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._data: Dict[str, Dict[str, str]] = {}
        if self.path.exists():
            self._data = json.loads(self.path.read_text(encoding="utf-8"))

    def verdict_for(self, feature: str) -> Optional[str]:
        entry = self._data.get(feature)
        return entry.get("verdict") if entry else None

    def is_accepted(self, feature: str) -> bool:
        return self.verdict_for(feature) == "accepted"

    def record(self, feature: str, verdict: str, by: str, note: str = "") -> None:
        """Write a decision. ``verdict`` is ``accepted`` or ``rejected``."""
        if verdict not in ("accepted", "rejected"):
            raise ValueError("verdict must be 'accepted' or 'rejected'")
        self._data[feature] = {"verdict": verdict, "by": by, "date": date.today().isoformat(), "note": note}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


@dataclasses.dataclass(frozen=True)
class PortabilityRow:
    """One line of the portability table: how closely two rungs agreed on one feature."""

    feature: str
    left: str
    right: str
    stats: ComparisonStats


def write_portability(rows: Iterable[PortabilityRow], path: Path) -> Path:
    """
    Regenerate the portability table as Markdown.

    :param rows: Comparison rows, any order; written sorted by feature then rung pair.
    :param path: Markdown file to write.
    :return: The path written.
    """
    rows = sorted(rows, key=lambda r: (r.feature, r.left, r.right))
    lines: List[str] = [
        "# Noise portability",
        "",
        "Regenerated by the noise kernel tests; do not edit. Which rungs matched which, and how",
        "closely, per feature. `exact` is bit-identical; `float32` is within 1e-6; `tight` within",
        "1e-4; `loose` within 1e-2; `mismatch` beyond that and flagged for review.",
        "",
        f"Generated {date.today().isoformat()}.",
        "",
        "| Feature | Left | Right | Class | Max abs | Mean abs | Correlation |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in rows:
        s = r.stats
        lines.append(
            f"| {r.feature} | {r.left} | {r.right} | {s.match_class} | {s.max_abs:.2e} | {s.mean_abs:.2e} | {s.correlation:.6f} |"
        )
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# -------------------------------------------------------------------------
def _cli(argv: Optional[List[str]] = None) -> int:
    """``python -m hog_noise.compare simplex fbm --left numba --right fastnoiselite``"""
    import argparse

    from hog_noise import NoiseParams, make_sampler, parse_fractal_type, parse_noise_type

    parser = argparse.ArgumentParser(description="Compare two noise rungs on a grid and write a sheet.")
    parser.add_argument("noise", help="noise type name, e.g. simplex")
    parser.add_argument("fractal", help="fractal type name, e.g. fbm")
    parser.add_argument("--left", default="numba")
    parser.add_argument("--right", default="fastnoiselite")
    parser.add_argument("--size", type=int, default=256)
    parser.add_argument("--extent", type=float, default=2048.0, help="half-width of the sampled square")
    parser.add_argument("--seed", type=int, default=12345)
    parser.add_argument("--octaves", type=int, default=4)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    _logging.basicConfig(level=_logging.INFO)

    params = NoiseParams(
        seed=args.seed,
        frequency=0.01,
        noise_type=parse_noise_type(args.noise),
        fractal_type=parse_fractal_type(args.fractal),
        octaves=args.octaves,
    )
    axis = np.linspace(-args.extent, args.extent, args.size, dtype=np.float32)
    gx, gz = np.meshgrid(axis, axis)
    xs, zs = gx.ravel(), gz.ravel()
    ys = np.zeros_like(xs)
    grids = []
    for name in (args.left, args.right):
        sampler, _ = make_sampler(params, backend=name)
        out = np.empty(xs.size, np.float32)
        grids.append(sampler.sample_points(xs, ys, zs, out).reshape(args.size, args.size))
    stats = compare_values(grids[0], grids[1])
    print(stats.summary())
    out = args.out or Path(f"compare_{args.noise}_{args.fractal}_{args.left}_vs_{args.right}.png")
    render_sheet(grids[1], grids[0], out, f"{args.noise}/{args.fractal}: {args.left} vs {args.right}", stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
