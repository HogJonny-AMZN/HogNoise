"""
HogNoise tools: the HLSL hosts' own paths, beside test_hosts' acceptance: what is a skip (no Windows, no harness, no
compiler) and what is an error (a compiler or the harness refusing what it was given), which must never be a skip.
Package: apps/hog-noise-tools/tests/hosts/test_hlsl
"""

import os
import struct
import subprocess
import sys
import time

import numpy as np
import pytest

from hog_noise import NoiseParams, shaders
from hog_noise.gpu import pack_grid, pack_params
from hog_noise_tools import compile_shaders
from hog_noise_tools.hosts import HostUnavailable, hlsl, verified_tables

#: The opening of a stand-in harness: it reads the init frame and answers it as a harness with a device does, then the
#: test's lines. ``request()`` reads one whole request frame, so a stand-in that then exits cannot break the pipe while
#: Python is still writing it: that is the "is gone" path, and a test naming another path failed on Linux by its timing.
_ANSWERS_INIT = (
    "import struct, sys, time\n"
    "def reply(status, body):\n"
    "    sys.stdout.buffer.write(struct.pack('<II', status, len(body)) + body)\n"
    "    sys.stdout.buffer.flush()\n"
    "def u32():\n"
    "    return struct.unpack('<I', sys.stdin.buffer.read(4))[0]\n"
    "def blob():\n"
    "    return sys.stdin.buffer.read(u32())\n"
    "def request():\n"
    "    sys.stdin.buffer.read(20)\n"
    "    blob(), blob()\n"
    "    for _ in range(u32()):\n"
    "        blob()\n"
    "sys.stdin.buffer.read(4)\n"
    "blob()\n"
    "for _ in range(u32()):\n"
    "    blob(), blob()\n"
    "reply(0, b'stand-in')\n"
)


def _stand_in(tmp_path, lines: str) -> hlsl.Hlsl:
    """A host over a stand-in harness that answers init, then runs ``lines``."""
    script = tmp_path / "stand_in.py"
    script.write_text(_ANSWERS_INIT + lines)
    return hlsl.Hlsl("d3d11", [b""] * len(shaders.ENTRY_POINTS), b"", command=[sys.executable, str(script)])


def _dispatch(host: hlsl.Hlsl, n: int = 4) -> np.ndarray:
    xs = np.zeros(n, np.float32)
    return host.run("sample_points_2d", pack_params(NoiseParams()), [xs, xs], n, 1, None)


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


def test_a_harness_that_crashes_mid_dispatch_reports_its_exit_code_and_stderr(tmp_path):
    """The evidence a crash leaves: its exit code and what it wrote to standard error, read after it is reaped."""
    host = _stand_in(tmp_path, "request()\nsys.stderr.write('access violation at 0x0')\nsys.exit(3)\n")
    with pytest.raises(RuntimeError, match=r"\(exit 3\) access violation at 0x0"):
        _dispatch(host)


def test_a_truncated_reply_is_an_error_naming_how_the_harness_ended(tmp_path):
    host = _stand_in(tmp_path, "request()\nsys.stdout.buffer.write(struct.pack('<II', 0, 16) + b'abcd')\n")
    with pytest.raises(RuntimeError, match=r"the harness stopped \(exit 0\)"):
        _dispatch(host)


def test_a_reply_of_the_wrong_length_is_an_error_not_a_short_array(tmp_path):
    host = _stand_in(tmp_path, "request()\nreply(0, b'\\0' * 8)\nsys.stdin.buffer.read()\n")
    with pytest.raises(RuntimeError, match="sent 8 bytes for 4 points x 1 floats"):
        _dispatch(host)
    host.close()


def test_a_harness_writing_much_to_stderr_does_not_block(tmp_path, monkeypatch):
    """Standard error goes to a file, not a pipe nobody drains: 1 MB of it, then a reply, arrives within seconds."""
    monkeypatch.setattr(hlsl, "TIMEOUT", 20)
    host = _stand_in(
        tmp_path,
        "request()\nsys.stderr.write('x' * 1_000_000)\nsys.stderr.flush()\n"
        "reply(0, b'\\0' * 16)\nsys.stdin.buffer.read()\n",
    )
    started = time.monotonic()
    assert _dispatch(host).tolist() == [0.0] * 4
    assert time.monotonic() - started < 15
    host.close()


def test_programs_not_one_per_entry_point_are_refused_before_any_process_starts(monkeypatch):
    def no_process(*args, **kwargs):
        raise AssertionError("a process was started")

    monkeypatch.setattr(hlsl.subprocess, "Popen", no_process)
    with pytest.raises(ValueError, match="zip"):
        hlsl.Hlsl("d3d11", [b""] * 2, b"", command=["unused"])


def test_a_harness_that_ignores_its_input_closing_is_ended(tmp_path, monkeypatch):
    monkeypatch.setattr(hlsl, "END_TIMEOUT", 1)
    host = _stand_in(tmp_path, "time.sleep(60)\n")
    with pytest.raises(RuntimeError, match="did not end within 1 s of its input closing, and was ended"):
        host.close()
    assert host.process.returncode is not None


class _InFlightTimer:
    """
    A watchdog whose callback has already started when the exchange cancels it: `cancel` cannot stop it, and it
    finishes only when joined. Without the join, the exchange returns success and the callback kills the harness later.
    """

    def __init__(self, interval, function):
        self.function = function

    def start(self):
        pass

    def cancel(self):
        pass

    def join(self):
        self.function()


def test_a_timeout_in_flight_ends_with_its_exchange_not_during_the_next(tmp_path, monkeypatch):
    host = _stand_in(tmp_path, "request()\nreply(0, b'\\0' * 16)\nsys.stdin.buffer.read()\n")
    monkeypatch.setattr(hlsl.threading, "Timer", _InFlightTimer)
    with pytest.raises(RuntimeError, match="did not reply within"):
        _dispatch(host)
    assert host.process.returncode is not None


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
