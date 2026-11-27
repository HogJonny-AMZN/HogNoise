"""
HogNoise tools: the HLSL hosts' own paths, beside test_hosts' acceptance: what is a skip (no Windows, no harness, no
compiler) and what is an error (a compiler or the harness refusing what it was given), which must never be a skip.
How Python drives any harness is test_harness's.
Package: apps/hog-noise-tools/tests/hosts/test_hlsl
"""

import os
import struct
import subprocess

import numpy as np
import pytest

from hog_noise import NoiseParams, shaders
from hog_noise.gpu import pack_grid, pack_params
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


@pytest.mark.parametrize("stale", ["SOURCE", "FRAMES"])
def test_a_harness_older_than_its_source_or_frames_h_is_unavailable(monkeypatch, tmp_path, stale):
    """A stale harness would run code the source no longer says; it is rebuilt by hand, never by a test worker."""
    exe = tmp_path / "hlsl_host.exe"
    sources = {"SOURCE": tmp_path / "hlsl_host.cpp", "FRAMES": tmp_path / "frames.h"}
    for source in sources.values():
        source.write_text("// a source")
        os.utime(source, (1_000_000, 1_000_000))
    exe.write_bytes(b"")
    os.utime(exe, (2_000_000, 2_000_000))
    os.utime(sources[stale], (3_000_000, 3_000_000))
    monkeypatch.setattr(hlsl.sys, "platform", "win32")
    monkeypatch.setattr(hlsl, "EXE", exe)
    for name, path in sources.items():
        monkeypatch.setattr(hlsl, name, path)
    with pytest.raises(HostUnavailable, match=rf"older than {sources[stale].name}: run .*build\.bat"):
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


def test_a_compiler_that_exits_0_and_writes_nothing_is_an_error(monkeypatch):
    monkeypatch.setattr(compile_shaders, "find", lambda name: "fxc")
    monkeypatch.setattr(hlsl.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, "", ""))
    with pytest.raises(RuntimeError, match=r"fxc exited 0 on sample_points_3d and wrote no sample_points_3d\.cso"):
        hlsl.compile_entry_points("d3d11", "anything")


def test_a_compiler_past_its_timeout_is_an_error_naming_it(monkeypatch):
    def too_slow(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])

    monkeypatch.setattr(compile_shaders, "find", lambda name: "dxc")
    monkeypatch.setattr(hlsl.subprocess, "run", too_slow)
    with pytest.raises(RuntimeError, match=f"dxc did not finish sample_points_3d within {compile_shaders.TIMEOUT} s"):
        hlsl.compile_entry_points("d3d12", "anything")


def _dispatch(host: hlsl.Hlsl, n: int = 4) -> np.ndarray:
    xs = np.zeros(n, np.float32)
    return host.run("sample_points_2d", pack_params(NoiseParams()), [xs, xs], n, 1, None)


# The harness's own refusals, frame by frame: these need it built, and the last two a WARP device.


def _raw(frame: bytes, api: str = "d3d12") -> tuple[int, bytes, int]:
    """Send ``frame`` to the built harness with its input then closed: its one reply and its exit code."""
    done = subprocess.run([str(hlsl.EXE), "--api", api], input=frame, capture_output=True, timeout=60)
    status, length = struct.unpack("<II", done.stdout[:8])
    return status, done.stdout[8 : 8 + length], done.returncode


def _blob(data: bytes) -> bytes:
    return struct.pack("<I", len(data)) + data


def test_the_harness_ends_on_a_frame_that_ends_early(built):
    status, message, exit_code = _raw(b"HN")
    assert (status, exit_code) == (1, 1)
    assert message == b"standard input ended inside a frame"


def test_the_harness_refuses_an_init_frame_without_five_programs(built):
    status, message, _ = _raw(b"HNH1" + _blob(b"") + struct.pack("<I", 0))
    assert status == 1
    assert message == b"the init frame has 0 programs, not 5"


def test_the_harness_refuses_an_init_frame_naming_an_entry_point_the_readme_does_not(built):
    names = [*shaders.ENTRY_POINTS[:4], "sample_points_4d"]
    programs = b"".join(_blob(name.encode()) + _blob(b"") for name in names)
    status, message, _ = _raw(b"HNH1" + _blob(b"") + struct.pack("<I", 5) + programs)
    assert status == 1
    assert message == b'the init frame names "sample_points_4d", not one of the README\'s entry points'


def test_the_harness_refuses_a_blob_past_its_limit_before_allocating_it(built):
    status, message, _ = _raw(b"HNH1" + struct.pack("<I", 0xFFFFFFF0))
    assert status == 1
    assert b"past the 1073741824 a frame may hold" in message


@pytest.fixture(scope="module")
def d3d12():
    try:
        host = hlsl.open_d3d12()
    except HostUnavailable as e:
        pytest.skip(f"hlsl: {e}")
    yield host
    host.close()


def test_the_harness_refuses_an_axis_shorter_than_its_points(d3d12):
    """Not zeros read past the axis's end and passed off as output: an axis holding 1 float for 4 points is refused."""
    params = pack_params(NoiseParams())
    with pytest.raises(RuntimeError, match="axis 0 holds 4 bytes, not 16 for 4 points"):
        d3d12.run("sample_points_2d", params, [np.zeros(1, np.float32)] * 2, 4, 1, None)
    assert _dispatch(d3d12).shape == (4,)  # a refused request leaves the harness reading on


_XS = np.zeros(4, np.float32)
_GRID = pack_grid((0, 0, 0), (4, 1, 1), (1.0, 1.0, 1.0))


@pytest.mark.parametrize(
    ("entry", "axes", "width", "grid", "refusal"),
    [
        # each would return status 0 with output that looks valid: part unwritten, or read from zero coordinates
        ("warp_points_3d", [_XS] * 3, 1, None, "warp_points_3d writes 3 floats per point, not 1"),
        ("sample_points_3d", [], 1, None, "sample_points_3d reads 3 axes, not 0"),
        ("sample_points_2d", [_XS] * 3, 1, None, "sample_points_2d reads 2 axes, not 3"),
        ("sample_grid", [], 1, None, "sample_grid reads a 48-byte Grid, and the request sent 0 bytes"),
        ("sample_points_2d", [_XS] * 2, 1, _GRID, "sample_points_2d reads no Grid, and the request sent 48 bytes"),
    ],
    ids=["width", "no-axes", "extra-axis", "no-grid", "extra-grid"],
)
def test_the_harness_refuses_a_request_its_entry_point_does_not_take(d3d12, entry, axes, width, grid, refusal):
    with pytest.raises(RuntimeError, match=refusal):
        d3d12.run(entry, pack_params(NoiseParams()), axes, 4, width, grid)
    assert _dispatch(d3d12).shape == (4,)  # a refused request leaves the harness reading on


def test_the_harness_refuses_an_entry_past_the_five(d3d12):
    request = struct.pack("<5I", 99, 4, 1, 1, 1) + _blob(pack_params(NoiseParams())) + _blob(b"") + struct.pack("<I", 0)
    status, message = d3d12._exchange(request)
    assert status == 1
    assert message == b"entry 99 is not one of the 5"
