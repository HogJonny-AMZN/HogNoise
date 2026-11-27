"""
HogNoise tools: a C++ harness as Python drives it, with no harness needed: stand-ins that answer the frames as a harness
does, then fail one way each. A harness that stops, hangs, crashes or replies short is an error naming how, never a
hang or a short array.
Package: apps/hog-noise-tools/tests/hosts/test_harness
"""

import os
import sys
import time

import numpy as np
import pytest

from hog_noise import NoiseParams, shaders
from hog_noise.gpu import pack_params
from hog_noise_tools.hosts import HostUnavailable, harness

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

_PROGRAMS = [b""] * len(shaders.ENTRY_POINTS)


def _script(tmp_path, text: str) -> list[str]:
    script = tmp_path / "stand_in.py"
    script.write_text(text)
    return [sys.executable, str(script)]


def _stand_in(tmp_path, lines: str) -> harness.Harness:
    """A harness over a stand-in that answers init, then runs ``lines``."""
    return harness.Harness("stand-in", _script(tmp_path, _ANSWERS_INIT + lines), _PROGRAMS, b"")


def _dispatch(host: harness.Harness, n: int = 4) -> np.ndarray:
    xs = np.zeros(n, np.float32)
    return host.run("sample_points_2d", pack_params(NoiseParams()), [xs, xs], n, 1, None)


def test_a_harness_never_built_is_unavailable_naming_the_build_script(tmp_path):
    with pytest.raises(HostUnavailable, match=r"not built: run .*build\.sh"):
        harness.built(tmp_path / "host", [], tmp_path / "build.sh")


@pytest.mark.parametrize("stale", [0, 1], ids=["its-source", "frames.h"])
def test_a_harness_older_than_any_of_its_sources_is_unavailable(tmp_path, stale):
    """A stale harness would run code its sources no longer say, frames.h's as much as its own."""
    exe, sources = tmp_path / "host", [tmp_path / "host.cpp", tmp_path / "frames.h"]
    for source in sources:
        source.write_text("// a source")
        os.utime(source, (1_000_000, 1_000_000))
    exe.write_bytes(b"")
    os.utime(exe, (2_000_000, 2_000_000))
    os.utime(sources[stale], (3_000_000, 3_000_000))
    with pytest.raises(HostUnavailable, match=rf"older than {sources[stale].name}: run .*build\.sh"):
        harness.built(exe, sources, tmp_path / "build.sh")


def test_a_harness_newer_than_its_sources_is_the_one_run(tmp_path):
    exe, source = tmp_path / "host", tmp_path / "host.cpp"
    source.write_text("// a source")
    exe.write_bytes(b"")
    os.utime(source, (1_000_000, 1_000_000))
    assert harness.built(exe, [source], tmp_path / "build.sh") == exe


def test_a_harness_that_finds_no_device_is_unavailable_not_an_error(tmp_path):
    """
    A stand-in that answers the init frame as a harness does with no device, status 2. That is a skip
    (HostUnavailable), what a refusal is told apart from; any other status is an error.
    """
    command = _script(
        tmp_path,
        "import struct, sys\n"
        "message = b'no device'\n"
        "sys.stdout.buffer.write(struct.pack('<II', 2, len(message)) + message)\n"
        "sys.stdout.buffer.flush()\n"
        "sys.stdin.buffer.read()\n",
    )
    with pytest.raises(HostUnavailable, match="no device"):
        harness.Harness("stand-in", command, _PROGRAMS, b"")


def test_a_harness_that_never_replies_fails_within_the_timeout(monkeypatch, tmp_path):
    """
    A stand-in that neither reads nor replies for 30 s. Without the watchdog the call waits until the stand-in exits
    and then fails another way, so the message and the time both fail it: a hang in conformance.check would stall the
    gate with no message.
    """
    monkeypatch.setattr(harness, "TIMEOUT", 2)
    started = time.monotonic()
    with pytest.raises(RuntimeError, match="did not reply within 2 s, and was ended"):
        harness.Harness("stand-in", _script(tmp_path, "import time\ntime.sleep(30)\n"), _PROGRAMS, b"")
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
    monkeypatch.setattr(harness, "TIMEOUT", 20)
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

    monkeypatch.setattr(harness.subprocess, "Popen", no_process)
    with pytest.raises(ValueError, match="zip"):
        harness.Harness("stand-in", ["unused"], [b""] * 2, b"")


def test_a_harness_that_ignores_its_input_closing_is_ended(tmp_path, monkeypatch):
    monkeypatch.setattr(harness, "END_TIMEOUT", 1)
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
    monkeypatch.setattr(harness.threading, "Timer", _InFlightTimer)
    with pytest.raises(RuntimeError, match="did not reply within"):
        _dispatch(host)
    assert host.process.returncode is not None
