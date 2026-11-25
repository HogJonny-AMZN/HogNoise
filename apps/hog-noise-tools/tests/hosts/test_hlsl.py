"""
HogNoise tools: the HLSL hosts' own paths, beside test_hosts' acceptance: what is a skip (no Windows, no harness, no
compiler) and what is an error (a compiler or the harness refusing what it was given), which must never be a skip.
Package: apps/hog-noise-tools/tests/hosts/test_hlsl
"""

import os
import sys
import time

import pytest

from hog_noise import shaders
from hog_noise_tools import compile_shaders
from hog_noise_tools.hosts import HostUnavailable, hlsl, verified_tables


def test_off_windows_the_hosts_are_unavailable(monkeypatch):
    monkeypatch.setattr(hlsl.sys, "platform", "linux")
    with pytest.raises(HostUnavailable, match="need Windows"):
        hlsl.harness()


def test_a_harness_never_built_is_unavailable_naming_the_build_script(monkeypatch, tmp_path):
    """Never built here from nothing: tests.yml's Windows legs have MSVC and did not ask for these hosts."""
    monkeypatch.setattr(hlsl.sys, "platform", "win32")
    monkeypatch.setattr(hlsl, "EXE", tmp_path / "hlsl_host.exe")
    with pytest.raises(HostUnavailable, match=r"not built: run .*build\.bat"):
        hlsl.harness()


def test_no_compiler_is_unavailable(monkeypatch):
    monkeypatch.setattr(compile_shaders, "find", lambda name: None)
    with pytest.raises(HostUnavailable, match="fxc is not on PATH"):
        hlsl.compile_entry_points("d3d11", "anything")


def test_a_harness_older_than_its_source_is_unavailable(monkeypatch, tmp_path):
    """A stale harness would run code the source no longer says; it is rebuilt by hand, never by a test worker."""
    exe, source = tmp_path / "hlsl_host.exe", tmp_path / "hlsl_host.cpp"
    exe.write_bytes(b"")
    source.write_text("// newer")
    os.utime(exe, (1_000_000, 1_000_000))
    monkeypatch.setattr(hlsl.sys, "platform", "win32")
    monkeypatch.setattr(hlsl, "EXE", exe)
    monkeypatch.setattr(hlsl, "SOURCE", source)
    with pytest.raises(HostUnavailable, match=r"older than hlsl_host\.cpp: run .*build\.bat"):
        hlsl.harness()


@pytest.mark.parametrize("api", sorted(hlsl.COMPILERS))
def test_a_source_the_compiler_refuses_is_an_error_not_a_skip(api):
    name = hlsl.COMPILERS[api][0]
    if compile_shaders.find(name) is None:
        pytest.skip(f"{name} is not here")
    with pytest.raises(RuntimeError, match=f"{name} refused sample_points_3d"):
        hlsl.compile_entry_points(api, "this is not HLSL")


@pytest.fixture
def built():
    try:
        return hlsl.harness()
    except HostUnavailable as e:
        pytest.skip(f"hlsl: {e}")


@pytest.mark.parametrize("api", sorted(hlsl.COMPILERS))
def test_programs_the_device_refuses_are_an_error_not_a_skip(built, api):
    """
    Bytes that are no compiled shader reach the device and are refused there: a RuntimeError naming the call. With no
    WARP device here the host is unavailable, a skip; HostUnavailable is a RuntimeError too, so it is told apart first.
    """
    garbage = [b"not a compiled shader"] * len(shaders.ENTRY_POINTS)
    try:
        hlsl.Hlsl(api, garbage, verified_tables())
    except HostUnavailable as e:
        pytest.skip(f"hlsl: {e}")
    except RuntimeError as e:
        assert "refused the programs: Create" in str(e), e
    else:
        pytest.fail("the harness accepted bytes that are no compiled shader")


def test_an_unknown_api_is_refused_by_the_harness(built):
    with pytest.raises(RuntimeError, match="unknown --api metal"):
        hlsl.Hlsl("metal", [b""] * len(shaders.ENTRY_POINTS), verified_tables())


def test_the_harness_ends_when_its_input_closes(built):
    """Opening needs DXC and a WARP device as well as the harness: without either, a skip naming which."""
    try:
        host = hlsl.open_d3d12()
    except HostUnavailable as e:
        pytest.skip(f"hlsl: {e}")
    process = host.process
    host.close()
    assert process.returncode == 0


def test_a_harness_that_finds_no_device_is_unavailable_not_an_error(tmp_path):
    """
    No harness needed: a stand-in that answers the init frame as the harness does with no WARP device, status 2.
    That is a skip (HostUnavailable), what the two tests above tell apart from a refusal; any other status is an error.
    """
    stand_in = tmp_path / "no_device.py"
    stand_in.write_text(
        "import struct, sys\n"
        "message = b'no WARP adapter'\n"
        "sys.stdout.buffer.write(struct.pack('<II', 2, len(message)) + message)\n"
        "sys.stdout.buffer.flush()\n"
        "sys.stdin.buffer.read()\n"
    )
    with pytest.raises(HostUnavailable, match="no WARP adapter"):
        hlsl.Hlsl("d3d11", [b""] * len(shaders.ENTRY_POINTS), b"", command=[sys.executable, str(stand_in)])


def test_a_harness_that_never_replies_fails_within_the_timeout(monkeypatch, tmp_path):
    """
    No harness needed: a stand-in that neither reads nor replies for 30 s. Without the watchdog the call waits until the
    stand-in exits and then fails another way, so the message and the time both fail it: a hang in conformance.check
    would stall the gate with no message.
    """
    silent = tmp_path / "silent.py"
    silent.write_text("import time\ntime.sleep(30)\n")
    monkeypatch.setattr(hlsl, "TIMEOUT", 2)
    started = time.monotonic()
    with pytest.raises(RuntimeError, match="did not reply within 2 s, and was ended"):
        hlsl.Hlsl("d3d11", [b""] * len(shaders.ENTRY_POINTS), b"", command=[sys.executable, str(silent)])
    assert time.monotonic() - started < 20
