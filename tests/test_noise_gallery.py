"""
HogNoise: the noise gallery page tracks the kernel record's enums, and the committed page is current.
Package: tests/test_noise_gallery
"""

from pathlib import Path

import pytest

import _tools_path  # noqa: F401  (puts tools/ on sys.path -- see that module; ledger entry 23)
import noise_gallery  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

from hog_noise import (  # noqa: E402
    CELLULAR_RETURN_NAMES,
    DOMAIN_WARP_NAMES,
    FRACTAL_TYPE_NAMES,
    IMPLEMENTED_FRACTAL_TYPES,
    IMPLEMENTED_NOISE_TYPES,
    NOISE_TYPE_NAMES,
    PERTURB_NAMES,
    CellularReturn,
    DomainWarpType,
    FractalType,
    PerturbType,
    enum_name,
)


@pytest.fixture(scope="module")
def page() -> str:
    return noise_gallery.render_page(write_images=False)


def test_every_implemented_noise_and_fractal_is_on_the_page(page):
    """The families come from the enums, so a newly ported type cannot be left out of the gallery."""
    for nt in IMPLEMENTED_NOISE_TYPES:
        assert f"`{enum_name(NOISE_TYPE_NAMES, nt)}" in page, nt.name
    for ft in IMPLEMENTED_FRACTAL_TYPES:
        if ft not in (FractalType.DOMAIN_WARP_PROGRESSIVE, FractalType.DOMAIN_WARP_INDEPENDENT):
            assert f"`{enum_name(FRACTAL_TYPE_NAMES, ft)}" in page, ft.name
    for ret in CellularReturn:
        assert enum_name(CELLULAR_RETURN_NAMES, ret) in page, ret.name
    for warp in DomainWarpType:
        if warp != DomainWarpType.NONE:
            assert enum_name(DOMAIN_WARP_NAMES, warp) in page, warp.name
    for pt in PerturbType:
        if pt != PerturbType.NONE:
            assert enum_name(PERTURB_NAMES, pt) in page, pt.name


def test_the_committed_page_is_current(page):
    """Regenerate after porting a noise: `python tools/noise_gallery.py`. The sheets must exist too."""
    committed = noise_gallery.PAGE.read_text(encoding="utf-8")
    assert committed == page, "Docs/noise/GALLERY.md is behind the enums; run python tools/noise_gallery.py"
    for key, _title, _builder, _columns in noise_gallery.FAMILIES:
        assert (noise_gallery.OUT_DIR / f"{key}.png").exists(), key
    assert (noise_gallery.OUT_DIR / "comparisons.png").exists()


def test_a_tile_is_a_square_heightfield():
    from hog_noise import NoiseParams

    tile = noise_gallery.render_tile(NoiseParams(seed=1, frequency=0.03), size=32)
    assert tile.shape == (32, 32) and tile.std() > 0.01
