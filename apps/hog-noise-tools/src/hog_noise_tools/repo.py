"""
HogNoise tools: where the repository is, found by walking up to its marker, never by counting parents.
Package: hog_noise_tools.repo

The tools read and write the repository's own folders (``vectors/``, ``Docs/noise/``), so they run from a checkout. A
counted ``Path(__file__).parents[N]`` shifts silently when a folder moves, as this app's move would have shown; a
marker does not.
"""

from pathlib import Path

_MODULE_NAME = "hog_noise_tools.repo"
__version__ = "0.1.0"

HERE = Path(__file__).resolve().parent


def above(start: Path, marker: str) -> Path:
    """The nearest folder at or above ``start`` holding the file ``marker``.

    :raises RuntimeError: When none does, naming the marker and the start: the tools run from a checkout.
    """
    found = next((p for p in [start, *start.parents] if (p / marker).is_file()), None)
    if found is None:
        raise RuntimeError(f"no {marker} at or above {start}: run HogNoise's tools from a checkout of the repository")
    return found


REPO_ROOT = above(HERE, "framework.toml")
APP_ROOT = above(HERE, "pyproject.toml")
VECTORS = REPO_ROOT / "vectors"


if __name__ == "__main__":
    print(f"repository {REPO_ROOT}\napp        {APP_ROOT}\nvectors    {VECTORS}")
