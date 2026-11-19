"""
HogNoise tools: the shader emitter refuses before it writes, and writes all or nothing (ledger P-13).
Package: apps/hog-noise-tools/tests/test_emit_shaders
"""

import json
import sys

import pytest

from hog_noise import shaders
from hog_noise_tools import emit_shaders as e

FAKE = """
import pathlib, sys
args = sys.argv[1:]
if args == ["--version"]:
    print("{version}")
    sys.exit(0)
out = pathlib.Path(args[-1])
if out.name in {fail!r}:
    sys.exit(3)
out.write_bytes(b"" if out.name in {empty!r} else ("// " + out.name + "\\r\\n").encode())
"""


def fake_naga(tmp_path, version="29.0.2", fail=(), empty=()):
    script = tmp_path / "fake_naga.py"
    script.write_text(FAKE.format(version=version, fail=list(fail), empty=list(empty)), encoding="utf-8")
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
    expected = {"README.md", "manifest.json", "tables.f32", "noise.hlsl", "noise.spv"}
    expected |= {f"noise.{ep}.comp" for ep in shaders.ENTRY_POINTS}
    assert names == expected
    assert b"\r\n" not in (dest / "noise.hlsl").read_bytes()
    assert (dest / "README.md").read_text(encoding="utf-8") == "hand-written"
    m = json.loads((dest / "manifest.json").read_text(encoding="utf-8"))
    assert m["naga"] == "29.0.2"
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


def test_the_pin_is_one_line_in_one_file():
    assert e.pinned_version() == "29.0.2"
