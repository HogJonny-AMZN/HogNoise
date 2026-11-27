"""
HogNoise tools: the Vulkan host's own paths, beside test_hosts' acceptance: what is a skip (not Linux, no harness, no
Vulkan driver, no CPU device) and what is an error (the driver refusing the module), which must never be a skip.
Package: apps/hog-noise-tools/tests/hosts/test_vulkan
"""

import os

import pytest

from hog_noise import shaders
from hog_noise_tools.hosts import HostUnavailable, harness, verified_tables, vulkan


def test_off_linux_the_host_is_unavailable(monkeypatch):
    monkeypatch.setattr(vulkan.sys, "platform", "win32")
    with pytest.raises(HostUnavailable, match="built and run on Linux"):
        vulkan.harness()


def test_a_harness_never_built_is_unavailable_naming_the_build_script(monkeypatch, tmp_path):
    monkeypatch.setattr(vulkan.sys, "platform", "linux")
    monkeypatch.setattr(vulkan, "EXE", tmp_path / "vulkan_host")
    with pytest.raises(HostUnavailable, match=r"not built: run .*build\.sh"):
        vulkan.harness()


@pytest.mark.parametrize("stale", ["SOURCE", "FRAMES"])
def test_a_harness_older_than_its_source_or_frames_h_is_unavailable(monkeypatch, tmp_path, stale):
    exe = tmp_path / "vulkan_host"
    sources = {"SOURCE": tmp_path / "vulkan_host.cpp", "FRAMES": tmp_path / "frames.h"}
    for source in sources.values():
        source.write_text("// a source")
        os.utime(source, (1_000_000, 1_000_000))
    exe.write_bytes(b"")
    os.utime(exe, (2_000_000, 2_000_000))
    os.utime(sources[stale], (3_000_000, 3_000_000))
    monkeypatch.setattr(vulkan.sys, "platform", "linux")
    monkeypatch.setattr(vulkan, "EXE", exe)
    for name, path in sources.items():
        monkeypatch.setattr(vulkan, name, path)
    with pytest.raises(HostUnavailable, match=rf"older than {sources[stale].name}: run .*build\.sh"):
        vulkan.harness()


@pytest.fixture
def built():
    try:
        return vulkan.harness()
    except HostUnavailable as e:
        pytest.skip(f"vulkan: {e}")


def _harness(exe, programs):
    return harness.Harness(vulkan.NAME, [str(exe), "--api", "vulkan"], programs, verified_tables())


def test_bytes_that_are_not_spirv_words_are_an_error_not_a_skip(built):
    """Refused before the driver sees them: a module is whole 32-bit words."""
    try:
        _harness(built, [b"abc"] * len(shaders.ENTRY_POINTS))
    except HostUnavailable as e:
        pytest.skip(f"vulkan: {e}")
    except RuntimeError as e:
        assert "refused the programs: the program for sample_points_3d is 3 bytes, not whole SPIR-V words" in str(e)
    else:
        pytest.fail("the harness accepted 3 bytes as a SPIR-V module")


def test_a_module_without_an_entry_point_is_an_error_not_a_skip(built):
    """
    The driver itself refuses: noise.spv with its ``sample_grid`` entry point renamed, so the pipeline for
    ``sample_grid`` names an entry point the module does not have. The harness passes the name, the driver refuses it.
    Measured on lavapipe (Mesa 26.0.8, 2026-11-27); a driver that does not check would fail this test, not skip it.
    """
    spirv = bytearray(shaders.source("spirv"))
    i = spirv.find(b"sample_grid\0")
    assert i > 0, "noise.spv has no sample_grid name to rename"
    spirv[i : i + len("sample_grid")] = b"sample_gri_"
    try:
        _harness(built, [bytes(spirv)] * len(shaders.ENTRY_POINTS))
    except HostUnavailable as e:
        pytest.skip(f"vulkan: {e}")
    except RuntimeError as e:
        assert "refused the programs: vkCreateComputePipelines (sample_grid) failed" in str(e), e
    else:
        pytest.fail("the driver made a pipeline for an entry point the module does not have")


def test_an_unknown_api_is_refused_by_the_harness(built):
    with pytest.raises(RuntimeError, match="unknown --api metal: vulkan"):
        harness.Harness(vulkan.NAME, [str(built), "--api", "metal"], [b""] * 5, verified_tables())


def test_no_vulkan_driver_is_unavailable_naming_what_it_found(built, monkeypatch, tmp_path):
    """
    The loader told to load no driver finds no device: a skip naming that it found none, never an error. The
    instrument's other answer is test_hosts, which opens lavapipe on the same harness.
    """
    monkeypatch.setenv("VK_DRIVER_FILES", str(tmp_path / "no-such-driver.json"))
    monkeypatch.setenv("VK_ICD_FILENAMES", str(tmp_path / "no-such-driver.json"))
    with pytest.raises(HostUnavailable, match="no Vulkan driver|no Vulkan device of type CPU"):
        _harness(built, [shaders.source("spirv")] * len(shaders.ENTRY_POINTS))


def test_the_harness_ends_when_its_input_closes(built):
    try:
        host = vulkan.open_host()
    except HostUnavailable as e:
        pytest.skip(f"vulkan: {e}")
    process = host.process
    host.close()
    assert process.returncode == 0
