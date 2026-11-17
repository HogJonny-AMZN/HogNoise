"""
HogNoise tools: the repository is found by its marker.
Package: apps/hog-noise-tools/tests/test_repo
"""

import pytest

from hog_noise_tools import repo


def test_the_repository_root_holds_the_marker_and_the_vectors():
    assert (repo.REPO_ROOT / "framework.toml").is_file()
    assert (repo.VECTORS / "manifest.json").is_file()


def test_the_app_root_is_the_app_not_the_repository():
    assert repo.APP_ROOT.name == "hog-noise-tools"


def test_no_marker_says_which_and_where(tmp_path):
    with pytest.raises(RuntimeError, match=r"no framework\.toml at or above"):
        repo.above(tmp_path, "framework.toml")
