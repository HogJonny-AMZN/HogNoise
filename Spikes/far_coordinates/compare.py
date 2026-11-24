"""
HogNoise probe: the far-coordinate results before and after the warp rules became coordinate-scaled, per adapter,
band and output.
Package: Spikes/far_coordinates/compare

    uv run python -I Spikes/far_coordinates/compare.py Spikes/far_coordinates Spikes/far_coordinates/after-warp-rules

Prints, for each adapter in the second folder, the probes passing their rule, the worst drift as a multiple of the
bound and the points past it, for the warp outputs and the noise probes apart.
"""

import json
import sys
from pathlib import Path


def summary(path: Path) -> list[str]:
    """One line per band and output of a probe's results file."""
    data = json.loads(path.read_text(encoding="utf-8"))
    lines = [f"{data['adapter']}: {path.parent.name}/, controls {data['controls']}"]
    for lo, hi in data["bands"]:
        band = [r for r in data["rows"] if r["band"] == [lo, hi]]
        for output in ("warp", "noise"):
            rows = [r for r in band if r["output"] == output]
            passed = sum(r["status"] == "pass" for r in rows)
            worst = max(r["max_normalised"] for r in rows)
            past = sum(r["past"] for r in rows)
            lines.append(f"  [{int(lo)}, {int(hi)}) {output}: {passed}/{len(rows)} pass, worst {worst:.3g}x, {past} past")
    return lines


def main() -> int:
    """Compare every results file in the second folder with its namesake in the first."""
    before, after = Path(sys.argv[1]), Path(sys.argv[2])
    files = sorted(after.glob("results_*.json"))
    if not files:
        print(f"no results_*.json in {after}")
        return 1
    for new in files:
        old = before / new.name
        print("\n".join((summary(old) if old.exists() else [f"{old}: missing"]) + summary(new)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
