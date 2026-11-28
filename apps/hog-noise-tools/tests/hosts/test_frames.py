"""
HogNoise tools: frames.h's refusals, on every C++ harness built here. One header holds the frames for both, so each
built harness is held to them: a frame it cannot read ends it, a request its entry point cannot take is refused and the
harness reads on. A harness not built here skips, naming its build script.
Package: apps/hog-noise-tools/tests/hosts/test_frames
"""

import struct
import subprocess

import numpy as np
import pytest

from hog_noise import NoiseParams, shaders
from hog_noise.gpu import pack_grid, pack_params
from hog_noise_tools.hosts import HostUnavailable, hlsl, vulkan

#: Per harness: its module and the --api a raw frame is sent with.
HARNESSES = {"hlsl": (hlsl, "d3d12"), "vulkan": (vulkan, "vulkan")}
#: Per harness: what opens a host on it, with its device.
OPENERS = {"hlsl": hlsl.open_d3d12, "vulkan": vulkan.open_host}


@pytest.fixture(params=sorted(HARNESSES))
def raw(request):
    """Send a frame to the built harness with its input then closed: its one reply and its exit code."""
    module, api = HARNESSES[request.param]
    try:
        exe = module.harness()
    except HostUnavailable as e:
        pytest.skip(f"{request.param}: {e}")

    def send(frame: bytes) -> tuple[int, bytes, int]:
        done = subprocess.run([str(exe), "--api", api], input=frame, capture_output=True, timeout=60)
        status, length = struct.unpack("<II", done.stdout[:8])
        return status, done.stdout[8 : 8 + length], done.returncode

    return send


def _blob(data: bytes) -> bytes:
    return struct.pack("<I", len(data)) + data


def test_the_harness_ends_on_a_frame_that_ends_early(raw):
    status, message, exit_code = raw(b"HN")
    assert (status, exit_code) == (1, 1)
    assert message == b"standard input ended inside a frame"


def test_the_harness_refuses_an_init_frame_without_five_programs(raw):
    status, message, _ = raw(b"HNH1" + _blob(b"") + struct.pack("<I", 0))
    assert status == 1
    assert message == b"the init frame has 0 programs, not 5"


def test_the_harness_refuses_an_init_frame_naming_an_entry_point_the_readme_does_not(raw):
    names = [*shaders.ENTRY_POINTS[:4], "sample_points_4d"]
    programs = b"".join(_blob(name.encode()) + _blob(b"") for name in names)
    status, message, _ = raw(b"HNH1" + _blob(b"") + struct.pack("<I", 5) + programs)
    assert status == 1
    assert message == b'the init frame names "sample_points_4d", not one of the README\'s entry points'


def test_the_harness_refuses_a_blob_past_its_limit_before_allocating_it(raw):
    status, message, _ = raw(b"HNH1" + struct.pack("<I", 0xFFFFFFF0))
    assert status == 1
    assert b"past the 1073741824 a frame may hold" in message


@pytest.fixture(scope="module", params=sorted(OPENERS))
def opened(request):
    try:
        host = OPENERS[request.param]()
    except HostUnavailable as e:
        pytest.skip(f"{request.param}: {e}")
    yield host
    host.close()


def _dispatch(host, n: int = 4) -> np.ndarray:
    xs = np.zeros(n, np.float32)
    return host.run("sample_points_2d", pack_params(NoiseParams()), [xs, xs], n, 1, None)


def test_the_harness_refuses_an_axis_shorter_than_its_points(opened):
    """Not zeros read past the axis's end and passed off as output: an axis holding 1 float for 4 points is refused."""
    params = pack_params(NoiseParams())
    with pytest.raises(RuntimeError, match="axis 0 holds 4 bytes, not 16 for 4 points"):
        opened.run("sample_points_2d", params, [np.zeros(1, np.float32)] * 2, 4, 1, None)
    assert _dispatch(opened).shape == (4,)  # a refused request leaves the harness reading on


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
def test_the_harness_refuses_a_request_its_entry_point_does_not_take(opened, entry, axes, width, grid, refusal):
    with pytest.raises(RuntimeError, match=refusal):
        opened.run(entry, pack_params(NoiseParams()), axes, 4, width, grid)
    assert _dispatch(opened).shape == (4,)  # a refused request leaves the harness reading on


def test_the_harness_refuses_an_entry_past_the_five(opened):
    request = struct.pack("<5I", 99, 4, 1, 1, 1) + _blob(pack_params(NoiseParams())) + _blob(b"") + struct.pack("<I", 0)
    status, message = opened._exchange(request)
    assert status == 1
    assert message == b"entry 99 is not one of the 5"


def _request(entry: int, n: int, gx: int, gy: int, params: bytes, grid: bytes = b"", axes: int = 2) -> bytes:
    """A request frame as `Harness.run` writes one, with its workgroups and Params given, not computed."""
    head = struct.pack("<5I", entry, n, 1, gx, gy) + _blob(params) + _blob(grid) + struct.pack("<I", axes)
    return head + b"".join(_blob(np.zeros(n, np.float32).tobytes()) for _ in range(axes))


_P2 = shaders.ENTRY_POINTS.index("sample_points_2d")


@pytest.mark.parametrize(
    ("n", "gx", "gy", "refusal"),
    [
        # fewer would leave points unwritten, past 65,535 along x is more than one dimension allows: each looks valid
        (200, 1, 1, "workgroups 1 x 1 for 200 points, not the README's 4 x 1"),
        (4, 0, 0, "workgroups 0 x 0 for 4 points, not the README's 1 x 1"),
        (4, 70000, 1, "workgroups 70000 x 1 for 4 points, not the README's 1 x 1"),
    ],
    ids=["too-few", "none", "past-65535"],
)
def test_the_harness_refuses_workgroups_that_are_not_the_readmes(opened, n, gx, gy, refusal):
    status, message = opened._exchange(_request(_P2, n, gx, gy, pack_params(NoiseParams())))
    assert (status, message.decode()) == (1, refusal)
    assert _dispatch(opened).shape == (4,)  # a refused request leaves the harness reading on


@pytest.mark.parametrize(
    ("request_frame", "refusal"),
    [
        (_request(_P2, 0, 0, 0, pack_params(NoiseParams()), axes=0), "a request for 0 points"),
        (_request(_P2, 4, 1, 1, bytes(100)), "Params is 100 bytes, not 112"),
        # 2**31 cells of sample_grid: 65,535 x 513 workgroups, and 8 GiB of output, refused before any buffer
        (
            _request(
                shaders.ENTRY_POINTS.index("sample_grid"), 2**31, 65535, 513, pack_params(NoiseParams()), _GRID, 0
            ),
            "an output of 8589934592 bytes, past 4 GiB",
        ),
    ],
    ids=["no-points", "short-params", "past-4-GiB"],
)
def test_the_harness_refuses_a_request_its_bindings_cannot_hold(opened, request_frame, refusal):
    status, message = opened._exchange(request_frame)
    assert (status, message.decode()) == (1, refusal)
    assert _dispatch(opened).shape == (4,)


@pytest.fixture(params=sorted(OPENERS))
def fresh(request):
    """A host of its own, for a test that ends its harness."""
    try:
        host = OPENERS[request.param]()
    except HostUnavailable as e:
        pytest.skip(f"{request.param}: {e}")
    yield host
    host.close()


def test_the_harness_ends_on_a_request_with_more_than_three_axes(fresh):
    """The stream cannot be read past a broken frame, so the harness replies and exits rather than reading on."""
    status, message = fresh._exchange(
        struct.pack("<5I", _P2, 4, 1, 1, 1) + _blob(bytes(112)) + _blob(b"") + struct.pack("<I", 4)
    )
    assert (status, message) == (1, b"4 axes, not at most 3")
    assert fresh.process.wait(timeout=30) == 1
