"""
HogNoise: the declared Python and numpy requirements admit every supported DCC host's own versions, and the floors are
the oldest host's.
Package: packages/python/hog-noise/tests/test_dcc_host_floors

HogNoise is imported inside DCC hosts on each host's own Python and numpy, which it cannot replace (the owner,
2026-11-25: "we will need to be able to have a HogNoise that is importable to the DCC packages that we are going to
support, their versions of Python. and their versions of NumPy"). The host versions are LargeWorlds' table,
https://github.com/HogJonny-AMZN/LargeWorlds/blob/main/Docs/knowledge/shared-dependency-versions.md, and the rule is
Docs/standards/compatibility-matrix-project.md.

A floor raised to numpy 2 was tried once and was the wrong direction (the owner, 2026-11-25). Dependabot rewrote a
declared floor twice (PR #28 and #47, uv-build), so it is held to the lock (`.github/dependabot.yml`); this test is
what says why, if anything else narrows a requirement.
"""

import tomllib
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"
#: Every supported DCC host's own Python and numpy (LargeWorlds' table, *Host versions*). A requirement must admit all.
HOSTS = {
    "Maya 2026": ("3.11.9", "1.26.4"),
    "Houdini 21": ("3.11.7", "1.26.4"),
    "Unreal 5.8": ("3.11.8", "1.26.4"),
    "Blender 5.2": ("3.13.13", "2.3.4"),
}
#: The oldest host's, as floors: a floor above these drops a Python or numpy the oldest host could have had.
PYTHON_FLOOR, NUMPY_FLOOR = "3.11", "1.26"
#: numpy is never capped or excluded: a newer host brings a newer numpy, and HogNoise cannot choose it.
NUMPY_NARROWING = ("<", "!=", "==", "~=", "===")
WHY = "HogNoise imports on each supported DCC host's own Python and numpy (compatibility-matrix-project.md)"


def problems(requires_python: str, dependencies: list[str]) -> list[str]:
    """What, in these declared requirements, would refuse a supported host or raise a floor; empty when nothing."""
    found = []
    python = SpecifierSet(requires_python)
    numpy = [Requirement(d) for d in dependencies if Requirement(d).name == "numpy"]
    if len(numpy) != 1:
        return [f"numpy is declared {len(numpy)} times, not once"]
    for host, (py, np_version) in HOSTS.items():
        if py not in python:
            found.append(f"requires-python {requires_python!r} refuses {host}'s Python {py}")
        if np_version not in numpy[0].specifier:
            found.append(f"{numpy[0]} refuses {host}'s numpy {np_version}")
    if f"{PYTHON_FLOOR}.0" not in python:
        found.append(f"requires-python {requires_python!r} is above the oldest host's floor, Python {PYTHON_FLOOR}")
    if f"{NUMPY_FLOOR}.0" not in numpy[0].specifier:
        found.append(f"{numpy[0]} is above the oldest host's floor, numpy {NUMPY_FLOOR}")
    narrowed = [str(s) for s in numpy[0].specifier if s.operator in NUMPY_NARROWING]
    if narrowed:
        found.append(f"numpy is capped or excluded ({', '.join(narrowed)}): a newer host's numpy would be refused")
    return found


def test_the_declared_requirements_admit_every_supported_host():
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]
    assert problems(project["requires-python"], project["dependencies"]) == [], WHY


@pytest.mark.parametrize(
    "requires_python, numpy, says",
    [
        (">=3.12,<3.14", "numpy>=1.26.0", "refuses Maya 2026's Python"),
        (">=3.11,<3.13", "numpy>=1.26.0", "refuses Blender 5.2's Python"),
        (">=3.11,!=3.11.9,<3.14", "numpy>=1.26.0", "refuses Maya 2026's Python"),
        (">=3.11.8,<3.14", "numpy>=1.26.0", "refuses Houdini 21's Python"),
        (">=3.11,<3.14", "numpy>=2.0", "refuses Maya 2026's numpy"),
        (">=3.11,<3.14", "numpy>=1.26.0,<2.3", "refuses Blender 5.2's numpy"),
        (">=3.11,<3.14", "numpy>=1.26.0,<2.6", "capped or excluded"),
        (">=3.11,<3.14", "numpy>=1.26.0,!=2.5.4", "capped or excluded"),
        (">=3.11,<3.14", "numpy>=1.26.3", "above the oldest host's floor"),
    ],
)
def test_a_narrowed_requirement_is_refused_naming_what_it_drops(requires_python, numpy, says):
    found = problems(requires_python, [numpy, "numba>=0.61"])
    assert any(says in p for p in found), found


if __name__ == "__main__":
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]
    print(problems(project["requires-python"], project["dependencies"]) or "every supported host admitted")
