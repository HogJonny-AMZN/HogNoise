"""
HogNoise: the emitted shaders, their manifest and the tables a host binds.
Package: packages/python/hog-noise/tests/test_shaders
"""

import ast
import subprocess
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


def test_the_manifest_names_the_current_wgsl():
    current = shaders.sha256(shaders.path("wgsl").read_bytes(), text=True)
    assert shaders.manifest()["wgsl"]["sha256"] == current, (
        "noise.wgsl changed since the shaders were emitted: make shaders"
    )


def test_every_emitted_file_matches_its_manifest_entry():
    folder = shaders.path("hlsl").parent
    for name, entry in shaders.manifest()["files"].items():
        data = (folder / name).read_bytes()
        assert shaders.sha256(data, text=entry["text"]) == entry["sha256"], (
            f"{name} differs from its manifest: make shaders"
        )


def test_the_tables_file_is_the_tables_module():
    assert shaders.tables() == tables.binding_table().astype("<f4").tobytes(), "tables.py changed: make shaders"


def test_every_language_and_entry_point_has_its_file():
    for lang in shaders.LANGUAGES:
        for ep in shaders.ENTRY_POINTS if lang == "glsl" else (None,):
            assert shaders.source(lang, ep), (lang, ep)
    assert len(shaders.tables()) == 8192


def test_the_bindings_name_each_languages_slot():
    rows = shaders.manifest()["bindings"]
    assert [r["binding"] for r in rows] == list(range(7))
    assert [r["hlsl"] for r in rows] == ["b0", "t1", "t2", "t3", "t4", "u5", "b6"]
    for r in rows:
        var = r["glsl"]["variable"]
        assert var == f"_group_0_binding_{r['binding']}_cs"
        using = {ep for ep in shaders.ENTRY_POINTS if var in shaders.source("glsl", ep)}
        assert using and set(r["glsl"]["blocks"]) == using, (r["binding"], using)
        assert r["spirv"] == {"set": 0, "binding": r["binding"]}


def test_the_shaders_need_no_wgpu(tmp_path):
    script = tmp_path / "no_wgpu.py"
    script.write_text(
        "import sys\nsys.modules['wgpu'] = None\nfrom hog_noise import shaders\nprint(len(shaders.source('hlsl')))\n",
        encoding="utf-8",
    )
    done = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, check=True)
    assert int(done.stdout) > 100_000
