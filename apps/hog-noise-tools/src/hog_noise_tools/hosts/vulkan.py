"""
HogNoise tools: the Vulkan host. ``noise.spv`` given to a Vulkan driver, Mesa's lavapipe, by a persistent C++ harness,
``apps/hog-noise-tools/hosts/vulkan``: the driver consumes the shipped bytes, where ``spirv-naga`` has naga read them.
Package: hog_noise_tools.hosts.vulkan

The harness reads no file. This module hashes ``noise.spv`` and the tables against the manifest and sends them down
the harness's standard input, the one module once per entry point, since a Vulkan pipeline names its entry point; each
dispatch is one request and one reply (``harness``, and the frames in ``frames.h``). The harness is built by
``build.sh`` (g++ and ``libvulkan-dev``), by hand or by CI, never by this module.
"""

from __future__ import annotations

import logging as _logging
import sys
from pathlib import Path

import numpy as np

from hog_noise import shaders
from hog_noise_tools.hosts import HostUnavailable, verified, verified_tables
from hog_noise_tools.hosts.harness import FRAMES, Harness, built
from hog_noise_tools.repo import APP_ROOT

_MODULE_NAME = "hog_noise_tools.hosts.vulkan"
__version__ = "0.1.0"
__updated__ = "2026-11-27"
_LOGGER = _logging.getLogger(_MODULE_NAME)

HARNESS_DIR = APP_ROOT / "hosts" / "vulkan"
SOURCE = HARNESS_DIR / "vulkan_host.cpp"
EXE = HARNESS_DIR / "vulkan_host"
NAME = "spirv-vulkan"


def harness() -> Path:
    """
    The built harness. Never built here, as the HLSL harness is not: CI builds it; by hand, ``build.sh``.

    :raises HostUnavailable: Not Linux, not built, or older than its source or ``frames.h``, naming the build script.
    """
    if not sys.platform.startswith("linux"):
        raise HostUnavailable("the Vulkan harness is built and run on Linux, where lavapipe is a package")
    return built(EXE, (SOURCE, FRAMES), HARNESS_DIR / "build.sh")


def open_host() -> Harness:
    """
    ``noise.spv`` on the first Vulkan device of type CPU.

    :raises HostUnavailable: As `harness`, or no Vulkan driver or CPU device here, naming the devices found.
    :raises RuntimeError: The driver refused the module or a pipeline: a finding, never a skip.
    """
    exe = harness()
    spirv = verified("spirv")
    return Harness(NAME, [str(exe), "--api", "vulkan"], [spirv] * len(shaders.ENTRY_POINTS), verified_tables())


if __name__ == "__main__":
    _logging.basicConfig(level=_logging.INFO)
    from hog_noise import NoiseParams
    from hog_noise_tools.hosts import HostSampler

    xs = np.linspace(-100, 100, 5, dtype=np.float32)
    host = open_host()
    s = HostSampler(NoiseParams(frequency=0.01), host)
    print(host.target, np.round(s.sample_points(xs, xs, np.zeros(5, np.float32), np.empty(5, np.float32)), 5))
    host.close()
