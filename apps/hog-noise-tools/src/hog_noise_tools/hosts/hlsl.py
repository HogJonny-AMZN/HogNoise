"""
HogNoise tools: the HLSL hosts. ``noise.hlsl``, compiled per entry point by FXC (``cs_5_0``) for D3D11 or DXC
(``cs_6_0``) for D3D12, dispatched on WARP by a persistent C++ harness, ``apps/hog-noise-tools/hosts/hlsl``.
Package: hog_noise_tools.hosts.hlsl

The harness reads no file. This module hashes ``noise.hlsl`` and the tables against the manifest, compiles the hashed
source with the Windows SDK's compilers (``compile_shaders.find``), and sends the tables and the five programs down the
harness's standard input; each dispatch is one request and one reply (the frames are in ``hlsl_host.cpp``). The harness
is built by ``build.bat`` (MSVC), by hand or by CI, never by this module.
"""

from __future__ import annotations

import logging as _logging
import struct
import subprocess
import sys
import tempfile
import threading
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from hog_noise import shaders
from hog_noise_tools import compile_shaders
from hog_noise_tools.hosts import HostUnavailable, verified, verified_tables, workgroups
from hog_noise_tools.repo import APP_ROOT

_MODULE_NAME = "hog_noise_tools.hosts.hlsl"
__version__ = "0.1.0"
__updated__ = "2026-11-25"
_LOGGER = _logging.getLogger(_MODULE_NAME)

HARNESS_DIR = APP_ROOT / "hosts" / "hlsl"
SOURCE = HARNESS_DIR / "hlsl_host.cpp"
EXE = HARNESS_DIR / "hlsl_host.exe"
#: Per API, the SDK compiler and its arguments before ``-E <entry point> -Fo <out> <source>``: compile_shaders' own.
COMPILERS = {"d3d11": ("fxc", ("-nologo", "-T", "cs_5_0")), "d3d12": ("dxc", ("-T", "cs_6_0"))}
#: Seconds the harness may take over one reply; a dispatch past 65,535 workgroups on WARP takes a few.
TIMEOUT = 600
_OK, _ERROR, _UNAVAILABLE = 0, 1, 2


def harness() -> Path:
    """
    The built harness. Never built here: a Windows leg with MSVC that did not ask for the HLSL hosts must not get them,
    and pytest's workers would each rebuild a stale one over an ``.exe`` another is running. CI builds it; by hand,
    ``build.bat``.

    :raises HostUnavailable: Not Windows, not built, or older than its source, naming the build script.
    """
    if sys.platform != "win32":
        raise HostUnavailable("D3D11 and D3D12 need Windows")
    if not EXE.exists():
        raise HostUnavailable(f"the harness is not built: run {HARNESS_DIR / 'build.bat'}")
    if EXE.stat().st_mtime < SOURCE.stat().st_mtime:
        raise HostUnavailable(f"{EXE.name} is older than {SOURCE.name}: run {HARNESS_DIR / 'build.bat'}")
    return EXE


def compile_entry_points(api: str, source: str) -> list[bytes]:
    """
    ``source`` compiled for ``api``, one program per entry point, in ``shaders.ENTRY_POINTS`` order.

    :raises HostUnavailable: The SDK compiler is not here.
    :raises RuntimeError: It refused the source, with its message: a finding, never a skip.
    """
    name, args = COMPILERS[api]
    tool = compile_shaders.find(name)
    if tool is None:
        raise HostUnavailable(f"{name} is not on PATH or in a Windows SDK")
    with tempfile.TemporaryDirectory(prefix="hog-noise-hlsl-") as tmp:
        src = Path(tmp) / shaders.file_name("hlsl")
        src.write_text(source, encoding="utf-8", newline="\n")

        def one(entry: str) -> bytes:
            out = Path(tmp) / f"{entry}.cso"
            cmd = [tool, *args, "-E", entry, "-Fo", str(out), str(src)]
            done = subprocess.run(cmd, capture_output=True, text=True, timeout=compile_shaders.TIMEOUT)
            if done.returncode != 0:
                raise RuntimeError(f"{name} refused {entry}: {(done.stdout + done.stderr).strip()}")
            return out.read_bytes()

        # one process per entry point, at once: FXC takes about 14 s for each (2026-11-23, the RTX 5090 machine)
        with ThreadPoolExecutor(len(shaders.ENTRY_POINTS)) as pool:
            programs = list(pool.map(one, shaders.ENTRY_POINTS))
    _LOGGER.info(f"hlsl: {name} compiled {len(programs)} entry points with {tool}")
    return programs


def _blob(data: bytes) -> bytes:
    return struct.pack("<I", len(data)) + data


class Hlsl:
    """One harness process, on one API."""

    def __init__(
        self, api: str, programs: Sequence[bytes], tables: bytes, command: Sequence[str] | None = None
    ) -> None:
        """
        :param command: What to run in place of the harness: the tests' stand-in for one that never replies.
        :raises HostUnavailable: The harness found no device here.
        :raises RuntimeError: It refused the programs, stopped, or did not reply within `TIMEOUT`.
        """
        self.api, self.name = api, f"hlsl-{api}"
        self._expired = False
        self.process = subprocess.Popen(
            list(command or [str(harness()), "--api", api]),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        named = b"".join(_blob(e.encode()) + _blob(p) for e, p in zip(shaders.ENTRY_POINTS, programs, strict=True))
        status, body = self._exchange(b"HNH1" + _blob(tables) + struct.pack("<I", len(programs)) + named)
        if status != _OK:
            self.process.kill()  # it exits after a failed start anyway; never leave one behind
            self.process.wait()
            if status == _UNAVAILABLE:
                raise HostUnavailable(f"{self.name}: {body.decode()}")
            raise RuntimeError(f"{self.name}: the harness refused the programs: {body.decode()}")
        self.target = body.decode()
        _LOGGER.info(f"{self.name}: {len(programs)} programs on {self.target}")

    def _stopped(self, why: str) -> RuntimeError:
        """The error for a harness that is gone, saying whether the watchdog ended it."""
        if self._expired:
            self.process.wait()
            return RuntimeError(f"{self.name}: the harness did not reply within {TIMEOUT} s, and was ended")
        exit_code = self.process.poll()
        err = self.process.stderr.read().decode(errors="replace").strip() if exit_code is not None else ""
        return RuntimeError(f"{self.name}: the harness {why} (exit {exit_code}) {err}".strip())

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
            return status, self._read(length)
        finally:
            watchdog.cancel()

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
        body = _blob(params) + _blob(grid or b"") + struct.pack("<I", len(axes))
        status, reply = self._exchange(head + body + b"".join(_blob(a.tobytes()) for a in axes))
        if status != _OK:
            raise RuntimeError(f"{self.name} {entry}: {reply.decode(errors='replace')}")
        return np.frombuffer(reply, dtype=np.float32).copy()

    def close(self) -> None:
        """End the harness: its standard input closing is its signal."""
        if self.process.poll() is None:
            self.process.stdin.close()
            self.process.wait(timeout=30)


def _open(api: str) -> Hlsl:
    exe = harness()
    _LOGGER.info(f"hlsl: harness {exe}")
    return Hlsl(api, compile_entry_points(api, verified("hlsl")), verified_tables())


def open_d3d11() -> Hlsl:
    """FXC's ``cs_5_0`` on D3D11, WARP. :raises HostUnavailable: As `harness` and `compile_entry_points`."""
    return _open("d3d11")


def open_d3d12() -> Hlsl:
    """DXC's ``cs_6_0`` on D3D12, WARP. :raises HostUnavailable: As `harness` and `compile_entry_points`."""
    return _open("d3d12")


if __name__ == "__main__":
    _logging.basicConfig(level=_logging.INFO)
    from hog_noise import NoiseParams
    from hog_noise_tools.hosts import HostSampler

    xs = np.linspace(-100, 100, 5, dtype=np.float32)
    for opener in (open_d3d11, open_d3d12):
        host = opener()
        s = HostSampler(NoiseParams(frequency=0.01), host)
        print(host.target, np.round(s.sample_points(xs, xs, np.zeros(5, np.float32), np.empty(5, np.float32)), 5))
        host.close()
