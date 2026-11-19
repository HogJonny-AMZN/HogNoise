"""
HogNoise tools: the shader emitter refuses before it writes (ledger P-13), and says so when replacing stops part way.
Package: apps/hog-noise-tools/tests/test_emit_shaders
"""

import json
import sys

import pytest

from hog_noise import shaders
from hog_noise_tools import emit_shaders as e

# A fake naga: prints a version, or writes the file it is asked for. Unless `bare`, the HLSL names a register and each
# GLSL file a block for every binding noise.wgsl declares, as naga does, so the binding table reads whole.
FAKE = """
import pathlib, sys
args = sys.argv[1:]
if args == ["--version"]:
    print("{version}")
    sys.exit(0)
out = pathlib.Path(args[-1])
if out.name in {fail!r}:
    sys.exit(3)
body = "// " + out.name + "\\r\\n"
if not {bare!r}:
    for group, binding, name in {declared!r}:
        var = "_group_%d_binding_%d_cs" % (group, binding)
        body += "%s : register(t%d);\\r\\n" % (name, binding) if out.suffix == ".hlsl" else ""
        body += "B%d {{ float %s; }};\\r\\n" % (binding, var) if out.suffix == ".comp" else ""
out.write_bytes(b"" if out.name in {empty!r} else body.encode())
"""


def fake_naga(tmp_path, version="29.0.2", fail=(), empty=(), bare=False):
    script = tmp_path / "fake_naga.py"
    declared = e.wgsl_bindings(e.WGSL.read_text(encoding="utf-8"))
    source = FAKE.format(version=version, fail=list(fail), empty=list(empty), bare=bare, declared=declared)
    script.write_text(source, encoding="utf-8")
    return [sys.executable, str(script)]


@pytest.fixture
def dest(tmp_path):
    d = tmp_path / "shaders"
    d.mkdir()
    (d / "README.md").write_text("hand-written", encoding="utf-8")
    (d / "noise.hlsl").write_text("old", encoding="utf-8")
    return d


def snapshot(d):
    return {p.name: p.read_bytes() for p in d.iterdir()}


def test_a_wrong_naga_version_refuses_and_writes_nothing(tmp_path, dest):
    before = snapshot(dest)
    with pytest.raises(
        e.EmitError, match=r"naga 30\.0\.1 .* the pin is 29\.0\.2.*cargo install naga-cli --version 29\.0\.2"
    ):
        e.emit(fake_naga(tmp_path, version="30.0.1"), dest, pin="29.0.2")
    assert snapshot(dest) == before


def test_a_naga_that_prints_no_version_refuses_and_writes_nothing(tmp_path, dest):
    before = snapshot(dest)
    with pytest.raises(e.EmitError, match=r"printed no version.*cargo install naga-cli --version 29\.0\.2"):
        e.emit(fake_naga(tmp_path, version=""), dest, pin="29.0.2")
    assert snapshot(dest) == before


def test_a_missing_naga_refuses_and_says_how_to_install_it(tmp_path, dest):
    before = snapshot(dest)
    with pytest.raises(e.EmitError, match=r"cannot run naga.*cargo install naga-cli --version 29\.0\.2"):
        e.emit([str(tmp_path / "no-such-naga")], dest, pin="29.0.2")
    assert snapshot(dest) == before


def test_a_naga_failure_on_one_file_leaves_every_file_as_it_was(tmp_path, dest):
    before = snapshot(dest)
    with pytest.raises(e.EmitError, match=r"noise\.sample_grid\.comp"):
        e.emit(fake_naga(tmp_path, fail=["noise.sample_grid.comp"]), dest, pin="29.0.2")
    assert snapshot(dest) == before


def test_an_empty_output_refuses_like_a_failure(tmp_path, dest):
    before = snapshot(dest)
    with pytest.raises(e.EmitError, match=r"noise\.spv.*empty"):
        e.emit(fake_naga(tmp_path, empty=["noise.spv"]), dest, pin="29.0.2")
    assert snapshot(dest) == before


def test_a_refusal_leaves_no_build_folder_behind(tmp_path, dest):
    with pytest.raises(e.EmitError):
        e.emit(fake_naga(tmp_path, fail=["noise.spv"]), dest, pin="29.0.2")
    assert not list(tmp_path.glob(".emit-*"))


def test_a_run_writes_every_file_lf_with_its_manifest_and_keeps_the_readme(tmp_path, dest):
    e.emit(fake_naga(tmp_path), dest, pin="29.0.2")
    names = {p.name for p in dest.iterdir()}
    assert names == e.expected_files() | {"README.md"}
    assert b"\r\n" not in (dest / "noise.hlsl").read_bytes()
    assert (dest / "README.md").read_text(encoding="utf-8") == "hand-written"
    m = json.loads((dest / "manifest.json").read_text(encoding="utf-8"))
    assert m["naga"] == "29.0.2"
    assert set(m["files"]) | {"manifest.json"} == e.expected_files()
    assert [r["binding"] for r in m["bindings"]] == list(range(7))
    for name, entry in m["files"].items():
        data = (dest / name).read_bytes()
        assert entry["sha256"] == shaders.sha256(data, text=entry["text"]) and entry["bytes"] == len(data)


def test_running_twice_changes_nothing(tmp_path, dest):
    naga = fake_naga(tmp_path)
    e.emit(naga, dest, pin="29.0.2")
    first = snapshot(dest)
    e.emit(naga, dest, pin="29.0.2")
    assert snapshot(dest) == first


def test_a_stale_emitted_file_is_removed(tmp_path, dest):
    (dest / "noise.retired_entry.comp").write_text("old", encoding="utf-8")
    e.emit(fake_naga(tmp_path), dest, pin="29.0.2")
    assert not (dest / "noise.retired_entry.comp").exists()


def test_a_binding_table_naga_did_not_write_refuses_and_writes_nothing(tmp_path, dest):
    before = snapshot(dest)
    with pytest.raises(e.EmitError, match=r"binding 0 \(P\): no HLSL register"):
        e.emit(fake_naga(tmp_path, bare=True), dest, pin="29.0.2")
    assert snapshot(dest) == before


def test_a_wgsl_declaring_no_binding_refuses(monkeypatch, tmp_path, dest):
    source = tmp_path / "empty.wgsl"
    source.write_text("// @group(0) @binding(0) var<uniform> P : Params; is a comment\n", encoding="utf-8")
    monkeypatch.setattr(e, "WGSL", source)
    before = snapshot(dest)
    with pytest.raises(e.EmitError, match=r"no @group/@binding declaration found in empty\.wgsl"):
        e.emit(fake_naga(tmp_path), dest, pin="29.0.2")
    assert snapshot(dest) == before


def test_bindings_are_read_in_either_attribute_order_and_never_from_comments():
    wgsl = (
        "@group(0) @binding(0) var<uniform> P : Params;\n"
        "@binding(1) @group(0) var<storage, read> T : array<f32>;\n"
        "// @group(0) @binding(9) var<uniform> Gone : Params;\n"
    )
    assert e.wgsl_bindings(wgsl) == [(0, 0, "P"), (0, 1, "T")]


def test_a_failure_while_replacing_is_partial_names_what_was_replaced_and_leaves_the_manifest(
    monkeypatch, tmp_path, dest
):
    old_manifest = b'{"old": true}\n'
    (dest / "manifest.json").write_bytes(old_manifest)
    real = e.os.replace
    calls = []

    def replace(src, dst):
        calls.append(dst)
        if len(calls) == 2:
            raise PermissionError("held by another process")
        real(src, dst)

    monkeypatch.setattr(e.os, "replace", replace)
    with pytest.raises(e.PartialWrite, match=r"replaced 1 of 9 \(noise\.hlsl\).*rerun make shaders"):
        e.emit(fake_naga(tmp_path), dest, pin="29.0.2")
    assert (dest / "manifest.json").read_bytes() == old_manifest
    assert not list(tmp_path.glob(".emit-*"))


def test_main_says_partial_not_nothing_written(monkeypatch, capsys):
    def stop(naga):
        raise e.PartialWrite("replaced 1 of 9")

    monkeypatch.setattr(e, "emit", stop)
    assert e.main([]) == 1
    assert "stopped part way" in capsys.readouterr().err


def test_the_pin_is_one_line_in_one_file():
    assert e.pinned_version() == "29.0.2"
