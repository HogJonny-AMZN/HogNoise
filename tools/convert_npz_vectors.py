"""
HogNoise: one-time conversion of tests/vectors/noise/*.npz to vectors/ (raw float32 and the manifest).
Package: tools/convert_npz_vectors

Run once, with its check (tests/test_hog_noise/test_conversion.py), in the commit that adds vectors/. The next commit
removes the .npz files and this script: there will never be .npz vectors to convert again.
"""

import json
import logging as _logging
import sys
from pathlib import Path

import numpy as np

import gen_noise_vectors as gen

_MODULE_NAME = "tools.convert_npz_vectors"
__version__ = "0.1.0"
__updated__ = "2026-11-12"
_LOGGER = _logging.getLogger(_MODULE_NAME)

ROOT = Path(__file__).resolve().parent.parent
OLD = ROOT / "tests" / "vectors" / "noise"


def captured(old: Path = OLD) -> list[tuple[str, str, dict, dict[str, np.ndarray]]]:
    """Every .npz capture as (library, feature, record, arrays), in file order."""
    out = []
    for library in ("fnl", "fns"):
        for path in sorted((old / library).glob("*.npz")):
            data = np.load(path)
            record = json.loads(str(data["params"]))
            out.append((library, path.stem, record, {k: data[k] for k in data.files if k != "params"}))
    return out


def main() -> int:
    _logging.basicConfig(level=_logging.INFO, format="%(levelname)s %(message)s")
    coords_npz = np.load(OLD / "coords.npz")
    coords = {k: coords_npz[k] for k in coords_npz.files}
    gen.write_originals(gen.OUT, captured(), coords)
    gen.generate_hog(gen.OUT)
    _LOGGER.info(f"converted {OLD} to {gen.OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
