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
REPO_ROOT = next(p for p in HERE.parents if (p / "framework.toml").is_file())
MEMBER_ROOT = next(p for p in [HERE, *HERE.parents] if (p / "pyproject.toml").is_file())
VECTORS = REPO_ROOT / "vectors"


if __name__ == "__main__":
    print(f"repository {REPO_ROOT}\nmember     {MEMBER_ROOT}\nvectors    {VECTORS}")
