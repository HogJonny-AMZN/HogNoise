"""
HogNoise: the emitted shaders, their manifest and the tables a host binds.
Package: packages/python/hog-noise/tests/test_shaders
"""

import ast
import sys

import numpy as np
import pytest

from hog_noise import gpu, shaders, tables


def test_the_binding_table_is_the_four_tables_in_order():
    t = tables.binding_table()
    assert t.dtype == np.float32 and t.shape == (2048,)
    parts = [tables.GRADIENTS_2D, tables.GRADIENTS_3D, tables.RAND_VECS_2D, tables.RAND_VECS_3D]
    assert np.array_equal(t, np.concatenate(parts))


def test_the_entry_points_are_the_rungs():
    assert shaders.ENTRY_POINTS == gpu.ENTRY_POINTS


def test_the_module_imports_the_standard_library_only():
    tree = ast.parse(open(shaders.__file__, encoding="utf-8").read())
    names = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    names |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert names - {"__future__"} <= sys.stdlib_module_names, names - sys.stdlib_module_names


def test_text_hashes_ignore_line_endings_and_binary_hashes_do_not():
    assert shaders.sha256(b"a\r\nb\n", text=True) == shaders.sha256(b"a\nb\n", text=True)
    assert shaders.sha256(b"a\r\nb\n", text=False) != shaders.sha256(b"a\nb\n", text=False)


@pytest.mark.parametrize("call", [lambda: shaders.path("metal"), lambda: shaders.source("cuda")])
def test_an_unknown_language_names_the_known_ones(call):
    with pytest.raises(ValueError, match=r"wgsl, hlsl, glsl, spirv"):
        call()


def test_glsl_needs_an_entry_point_and_names_them():
    with pytest.raises(ValueError, match=r"sample_points_3d"):
        shaders.path("glsl")
    with pytest.raises(ValueError, match=r"sample_points_3d"):
        shaders.path("glsl", "sample_points_4d")


def test_a_whole_module_language_refuses_an_entry_point():
    with pytest.raises(ValueError, match=r"one file for every entry point"):
        shaders.path("hlsl", "sample_grid")


def test_wgsl_is_the_rungs_source():
    assert shaders.path("wgsl").name == "noise.wgsl"
    assert "@compute" in shaders.source("wgsl")
