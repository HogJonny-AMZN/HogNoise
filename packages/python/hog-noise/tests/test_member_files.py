"""
HogNoise: the member's own copies of the repository's licence files stay identical to them.
Package: packages/python/hog-noise/tests/test_member_files

A workspace member's wheel cannot carry a file outside its folder, so ``LICENSE`` and ``NOTICE`` are copied into the
member. ``NOTICE`` carries the FastNoiseLite and FastNoiseSIMD licences the MIT terms require to travel with the
code, so a copy that drifts from the repository's would ship the wrong terms.
"""

import pytest
from hog_noise_repo import MEMBER_ROOT, REPO_ROOT


@pytest.mark.parametrize("name", ["LICENSE", "NOTICE"])
def test_the_member_ships_the_repositorys_licence_files_unchanged(name):
    assert (MEMBER_ROOT / name).read_bytes() == (REPO_ROOT / name).read_bytes(), f"copy {name} into {MEMBER_ROOT}"


def test_the_member_is_not_the_repository_root():
    assert MEMBER_ROOT != REPO_ROOT and (MEMBER_ROOT / "src" / "hog_noise").is_dir()


def test_the_path_helper_says_which_marker_it_could_not_find(tmp_path):
    import hog_noise_repo

    with pytest.raises(RuntimeError, match="no framework.toml at or above"):
        hog_noise_repo._above(tmp_path, "framework.toml")
