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


def test_an_app_root_that_is_the_repository_refuses(tmp_path):
    (tmp_path / "framework.toml").write_text("", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    site = tmp_path / ".venv" / "Lib" / "site-packages" / "hog_noise_tools"
    site.mkdir(parents=True)
    with pytest.raises(RuntimeError, match=r"not inside apps/hog-noise-tools/"):
        repo.app_root(site, tmp_path)


def test_no_marker_says_which_and_where(tmp_path):
    with pytest.raises(RuntimeError, match=r"no framework\.toml at or above"):
        repo.above(tmp_path, "framework.toml")
