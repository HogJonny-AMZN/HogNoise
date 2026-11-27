"""
HogNoise tools: the HLSL hosts. ``noise.hlsl``, compiled per entry point by FXC (``cs_5_0``) for D3D11 or DXC
(``cs_6_0``) for D3D12, dispatched on WARP by a persistent C++ harness, ``apps/hog-noise-tools/hosts/hlsl``.
Package: hog_noise_tools.hosts.hlsl

The harness reads no file. This module hashes ``noise.hlsl`` and the tables against the manifest, compiles the hashed
source with the Windows SDK's compilers (``compile_shaders.find``), and sends the tables and the five programs down the
harness's standard input; each dispatch is one request and one reply (``harness``, and the frames in ``frames.h``).
The harness is built by ``build.bat`` (MSVC), by hand or by CI, never by this module.
"""

from __future__ import annotations

import logging as _logging
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from hog_noise import shaders
from hog_noise_tools import compile_shaders
from hog_noise_tools.hosts import HostUnavailable, verified, verified_tables
from hog_noise_tools.hosts.harness import FRAMES, Harness, built
from hog_noise_tools.repo import APP_ROOT

_MODULE_NAME = "hog_noise_tools.hosts.hlsl"
__version__ = "0.2.0"
__updated__ = "2026-11-27"
_LOGGER = _logging.getLogger(_MODULE_NAME)

HARNESS_DIR = APP_ROOT / "hosts" / "hlsl"
SOURCE = HARNESS_DIR / "hlsl_host.cpp"
EXE = HARNESS_DIR / "hlsl_host.exe"
#: Per API, the SDK compiler and its arguments before ``-E <entry point> -Fo <out> <source>``: compile_shaders' own.
COMPILERS = {api: (name, compile_shaders.HLSL_ARGS[name]) for api, name in (("d3d11", "fxc"), ("d3d12", "dxc"))}


def harness() -> Path:
    """
    The built harness. Never built here: a Windows leg with MSVC that did not ask for the HLSL hosts must not get them.
    CI builds it; by hand, ``build.bat``.

    :raises HostUnavailable: Not Windows, not built, or older than its source or ``frames.h``, naming the build script.
    """
    if sys.platform != "win32":
        raise HostUnavailable("D3D11 and D3D12 need Windows")
    return built(EXE, (SOURCE, FRAMES), HARNESS_DIR / "build.bat")


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
            try:
                done = subprocess.run(cmd, capture_output=True, text=True, timeout=compile_shaders.TIMEOUT)
            except subprocess.TimeoutExpired as e:
                raise RuntimeError(f"{name} did not finish {entry} within {compile_shaders.TIMEOUT} s") from e
            said = (done.stdout + done.stderr).strip()
            if done.returncode != 0:
                raise RuntimeError(f"{name} refused {entry}: {said}")
            if not out.is_file():
                raise RuntimeError(f"{name} exited 0 on {entry} and wrote no {out.name}: {said}")
            return out.read_bytes()

        # one process per entry point, at once: FXC takes about 14 s for each (2026-11-23, the RTX 5090 machine)
        with ThreadPoolExecutor(len(shaders.ENTRY_POINTS)) as pool:
            programs = list(pool.map(one, shaders.ENTRY_POINTS))
    _LOGGER.info(f"hlsl: {name} compiled {len(programs)} entry points with {tool}")
    return programs


class Hlsl(Harness):
    """One harness process, on one API."""

    def __init__(
        self, api: str, programs: Sequence[bytes], tables: bytes, command: Sequence[str] | None = None
    ) -> None:
        """
        :param command: What to run in place of the harness: the tests' stand-ins.
        :raises ValueError: ``programs`` is not one per entry point; checked before any process starts.
        :raises HostUnavailable: The harness found no device here.
        :raises RuntimeError: It refused the programs, stopped, or did not reply within ``harness.TIMEOUT``.
        """
        self.api = api
        super().__init__(f"hlsl-{api}", command or [str(harness()), "--api", api], programs, tables)


def _open(api: str) -> Hlsl:
    _LOGGER.info(f"hlsl: harness {harness()}")  # first, so a missing harness skips before the compile's seconds
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
