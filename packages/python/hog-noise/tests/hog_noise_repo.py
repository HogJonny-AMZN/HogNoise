"""
HogNoise: where the repository and this member are, found by walking up to a marker, never by counting parents.
Package: packages/python/hog-noise/tests/hog_noise_repo

``REPO_ROOT`` holds ``framework.toml`` (and ``vectors/``); ``MEMBER_ROOT`` is the nearest folder above these tests
with a ``pyproject.toml``. A counted ``Path(__file__).parents[N]`` shifts silently when a folder moves (updating.md,
0.7.0, step 3); a marker does not. The name is unique across the workspace's members, as layout.md asks of a bare-name
helper.
"""

from pathlib import Path

HERE = Path(__file__).resolve().parent


def _above(start: Path, marker: str) -> Path:
    """The nearest folder at or above ``start`` holding ``marker``; a clear error, not ``StopIteration``, when none does
    (these tests run from a checkout of the repository, never from an sdist)."""
    found = next((p for p in [start, *start.parents] if (p / marker).is_file()), None)
    if found is None:
        raise RuntimeError(f"no {marker} at or above {start}: run these tests from a checkout of the repository")
    return found


REPO_ROOT = _above(HERE, "framework.toml")
MEMBER_ROOT = _above(HERE, "pyproject.toml")
VECTORS = REPO_ROOT / "vectors"


if __name__ == "__main__":
    print(f"repository {REPO_ROOT}\nmember     {MEMBER_ROOT}\nvectors    {VECTORS}")
