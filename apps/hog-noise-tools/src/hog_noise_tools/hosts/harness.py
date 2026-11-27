"""
HogNoise tools: a C++ host harness, as Python drives it. One persistent process per host, spoken to in the frames of
``apps/hog-noise-tools/hosts/frames.h``: an init frame with the tables and the five entry points' programs, then one
request and one reply per dispatch.
Package: hog_noise_tools.hosts.harness

What every harness shares: the frames, a watchdog on each reply, standard error kept in a file and read back when a
harness stops, and a close that ends it. Each host module supplies the command and the programs (``hlsl``: FXC's or
DXC's output; ``vulkan``: ``noise.spv``, once per entry point). Never built here: `built` names the build script.
"""

from __future__ import annotations

import logging as _logging
import struct
import subprocess
import tempfile
import threading
from collections.abc import Sequence
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from hog_noise import shaders
from hog_noise_tools.hosts import HostUnavailable, workgroups
from hog_noise_tools.repo import APP_ROOT

_MODULE_NAME = "hog_noise_tools.hosts.harness"
__version__ = "0.1.0"
__updated__ = "2026-11-27"
_LOGGER = _logging.getLogger(_MODULE_NAME)

#: The header every harness includes: an edit to it makes every built harness stale.
FRAMES = APP_ROOT / "hosts" / "frames.h"
#: Seconds a harness may take over one reply; a dispatch past 65,535 workgroups on WARP takes a few.
TIMEOUT = 600
#: Seconds a harness may take to end: after its input closes, or after it stops replying, before it is ended.
END_TIMEOUT = 30
#: The most of a stopped harness's standard error a message carries.
STDERR_TAIL = 4000
_OK, _ERROR, _UNAVAILABLE = 0, 1, 2


def built(exe: Path, sources: Sequence[Path], build: Path) -> Path:
    """
    ``exe``, if it is built and no older than any of its ``sources``. Never built here: pytest's workers would each
    rebuild a stale one over a harness another is running, and a leg that did not ask for a host must not get it.

    :raises HostUnavailable: Not built, or older than a source, naming the ``build`` script.
    """
    if not exe.exists():
        raise HostUnavailable(f"the harness is not built: run {build}")
    for source in sources:
        if exe.stat().st_mtime < source.stat().st_mtime:
            raise HostUnavailable(f"{exe.name} is older than {source.name}: run {build}")
    return exe


def blob(data: bytes) -> bytes:
    """A frame's blob: a u32 length and the bytes."""
    return struct.pack("<I", len(data)) + data


class Harness:
    """One harness process, for one host."""

    def __init__(self, name: str, command: Sequence[str], programs: Sequence[bytes], tables: bytes) -> None:
        """
        :param name: The host's name, in every message.
        :param programs: One per entry point, in ``shaders.ENTRY_POINTS`` order.
        :raises ValueError: ``programs`` is not one per entry point; checked before any process starts.
        :raises HostUnavailable: The harness found no device here.
        :raises RuntimeError: It refused the programs, stopped, or did not reply within `TIMEOUT`.
        """
        self.name = name
        self._expired = False
        named = b"".join(blob(e.encode()) + blob(p) for e, p in zip(shaders.ENTRY_POINTS, programs, strict=True))
        init = b"HNH1" + blob(tables) + struct.pack("<I", len(programs)) + named
        # standard error goes to a file, never a pipe nobody drains: a harness that writes more than a pipe holds
        # would block there, and a crash's message is read back from it
        self._stderr = tempfile.TemporaryFile()
        self.process = subprocess.Popen(
            list(command), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self._stderr
        )
        try:
            status, body = self._exchange(init)
        except BaseException:
            self._end()
            raise
        text = body.decode(errors="replace")
        if status != _OK:
            self._end()  # it exits after a failed start anyway; never leave one behind
            if status == _UNAVAILABLE:
                raise HostUnavailable(f"{self.name}: {text}")
            raise RuntimeError(f"{self.name}: the harness refused the programs: {text}")
        self.target = text
        _LOGGER.info(f"{self.name}: {len(programs)} programs on {self.target}")

    def _end(self) -> None:
        """End the process if it still runs, reap it, and close its standard error file."""
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait()
        self._stderr.close()

    def _stderr_text(self) -> str:
        self._stderr.seek(0)
        return self._stderr.read().decode(errors="replace").strip()[-STDERR_TAIL:]

    def _stopped(self, why: str) -> RuntimeError:
        """
        The error for a harness that is gone: whether the watchdog ended it, else its exit code and standard error,
        read after it is reaped (its output ends a moment before its exit code exists).
        """
        if self._expired:
            self.process.wait()
            return RuntimeError(f"{self.name}: the harness did not reply within {TIMEOUT} s, and was ended")
        try:
            exit_code: int | str = self.process.wait(timeout=END_TIMEOUT)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
            exit_code = f"none: still running after {END_TIMEOUT} s, and ended"
        return RuntimeError(f"{self.name}: the harness {why} (exit {exit_code}) {self._stderr_text()}".strip())

    def _read(self, n: int) -> bytes:
        data = self.process.stdout.read(n)
        if len(data) != n:
            raise self._stopped("stopped")
        return data

    def _expire(self) -> None:
        self._expired = True
        self.process.kill()

    def _exchange(self, frame: bytes) -> tuple[int, bytes]:
        """
        One frame out, one reply back, within `TIMEOUT`: past it a watchdog ends the harness, so a harness that stops
        replying fails the call instead of hanging ``conformance.check`` and the gate.
        """
        watchdog = threading.Timer(TIMEOUT, self._expire)
        watchdog.start()
        try:
            try:
                self.process.stdin.write(frame)
                self.process.stdin.flush()
            except OSError as e:
                raise self._stopped("is gone") from e
            status, length = struct.unpack("<II", self._read(8))
            reply = self._read(length)
        finally:
            # cancel cannot stop a callback already running: join it, so a timeout in flight ends with this exchange
            # and never kills the harness during the next one
            watchdog.cancel()
            watchdog.join()
        if self._expired:  # the watchdog fired as the reply arrived: the harness is ended, so say so now
            raise self._stopped("replied")
        return status, reply

    def run(
        self,
        entry: str,
        params: bytes,
        axes: Sequence[NDArray[np.float32]],
        n: int,
        width: int,
        grid: bytes | None,
    ) -> NDArray[np.float32]:
        """Dispatch ``entry`` over ``n`` points and read back ``n * width`` floats."""
        gx, gy, _ = workgroups(n)
        head = struct.pack("<5I", shaders.ENTRY_POINTS.index(entry), n, width, gx, gy)
        body = blob(params) + blob(grid or b"") + struct.pack("<I", len(axes))
        status, reply = self._exchange(head + body + b"".join(blob(a.tobytes()) for a in axes))
        if status != _OK:
            raise RuntimeError(f"{self.name} {entry}: {reply.decode(errors='replace')}")
        if len(reply) != n * width * 4:
            raise RuntimeError(
                f"{self.name} {entry}: the harness sent {len(reply)} bytes for {n} points x {width} floats"
            )
        return np.frombuffer(reply, dtype=np.float32).copy()

    def close(self) -> None:
        """
        End the harness: its standard input closing is its signal.

        :raises RuntimeError: It did not end within `END_TIMEOUT`; it is ended, not left running.
        """
        try:
            if self.process.poll() is None:
                self.process.stdin.close()
                try:
                    self.process.wait(timeout=END_TIMEOUT)
                except subprocess.TimeoutExpired:
                    raise RuntimeError(
                        f"{self.name}: the harness did not end within {END_TIMEOUT} s of its input closing, "
                        "and was ended"
                    ) from None
        finally:
            self._end()
