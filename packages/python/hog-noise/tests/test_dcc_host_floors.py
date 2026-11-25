"""
HogNoise: the declared Python and numpy floors are the oldest supported DCC host's, and nothing caps them.
Package: packages/python/hog-noise/tests/test_dcc_host_floors

HogNoise is imported inside DCC hosts on each host's own Python and numpy, which it cannot replace (the owner,
2026-11-25: "we will need to be able to have a HogNoise that is importable to the DCC packages that we are going to
support, their versions of Python. and their versions of NumPy"). The oldest is Maya 2026: mayapy 3.11.9 with numpy
1.26.4, as are Houdini 21 and Unreal 5.8. The host versions are LargeWorlds' table,
https://github.com/HogJonny-AMZN/LargeWorlds/blob/main/Docs/knowledge/shared-dependency-versions.md

A floor raised to numpy 2 was tried once and was the wrong direction (the owner, 2026-11-25). Dependabot rewrote a
declared floor twice (PR #28 and #47, uv-build), so it is held to the lock (`.github/dependabot.yml`); this test is
what says why, if anything else raises one.
"""

import tomllib
from pathlib import Path

import pytest

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"
#: The oldest supported DCC host's Python and numpy, as the floors `pyproject.toml` declares them.
OLDEST_HOST = "Maya 2026 (mayapy 3.11.9, numpy 1.26.4)"
PYTHON_FLOOR = ">=3.11"
NUMPY_FLOOR = "numpy>=1.26.0"
WHY = (
    f"HogNoise's floors are the oldest supported DCC host's, {OLDEST_HOST}: raising one drops that host. It moves only "
    "when the owner drops the host (Docs/handoffs/CURRENT.md, *What the owner has said that still holds*)"
)


@pytest.fixture(scope="module")
def project() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]


def test_the_python_floor_is_the_oldest_hosts(project):
    assert project["requires-python"].split(",")[0].strip() == PYTHON_FLOOR, WHY


def test_the_numpy_floor_is_the_oldest_hosts_and_has_no_cap(project):
    numpy = [d for d in project["dependencies"] if d.replace(" ", "").startswith("numpy")]
    assert numpy == [NUMPY_FLOOR], f"{WHY}; found {numpy}. A cap would refuse a newer host's numpy, as Blender 5.2's"


if __name__ == "__main__":
    print(PYPROJECT, tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["dependencies"])
