"""
HogNoise tools: the host harnesses. Each runs one emitted shader through one graphics API and hands its output to
``conformance.check``; this module holds what they share.
Package: hog_noise_tools.hosts

A host is written from ``hog_noise/shaders/README.md`` alone, never from ``hog_noise.gpu``'s ``_Gpu``, so a wrong
sentence in the README fails the proof (the CI proof's spec, *What gets built*). The constants below are the README's,
restated; ``test_shared`` holds them to the manifest. Each host module has ``open_host()``, which raises
`HostUnavailable` naming what is missing, and a host object with ``name``, ``target`` and ``run``.
"""

from __future__ import annotations

import functools
import importlib
import logging as _logging
import math
import os
from collections.abc import Callable, Sequence
from typing import Protocol

import numpy as np
from numpy.typing import NDArray

from hog_noise import NoiseParams, shaders
from hog_noise.gpu import MAX_OCTAVES, pack_grid, pack_params

_MODULE_NAME = "hog_noise_tools.hosts"
__version__ = "0.1.0"
__updated__ = "2026-11-23"
_LOGGER = _logging.getLogger(_MODULE_NAME)

#: A comma-separated list of hosts whose absence fails the tests instead of skipping them (CI's host legs).
REQUIRE_ENV = "HOG_NOISE_REQUIRE_HOST"
#: Part of what the host must run on, its ``target`` line, ignoring case; unset, the target is logged and not asserted.
TARGET_ENV = "HOG_NOISE_HOST_TARGET"
#: The hosts, by name, and the module that opens each (the spec's hosts table).
HOSTS = {"glsl": "hog_noise_tools.hosts.glsl", "spirv-naga": "hog_noise_tools.hosts.spirv_naga"}
#: The README's *The entry points*.
WORKGROUP = 64
MAX_GROUPS = 65535
#: The README's *The bindings*, in binding order: a uniform, read-only storage, or read-write storage.
BINDING_KINDS = ("uniform", "read", "read", "read", "read", "write", "uniform")
#: The README's *Output*: floats per point.
WIDTH = {"sample_points_3d": 1, "sample_points_2d": 1, "sample_grid": 1, "warp_points_3d": 3, "warp_points_2d": 2}

Sample = Callable[[NoiseParams, NDArray, NDArray, "NDArray | None"], NDArray]
Grid = Callable[[NoiseParams, Sequence[int], Sequence[int], Sequence[float]], NDArray]


class HostUnavailable(RuntimeError):
    """The host cannot run here: its library, its driver or its device is missing. The message names which."""


class HostTargetError(RuntimeError):
    """The host runs, but not on the target it was told to expect (the project ledger's P-22)."""


class Host(Protocol):
    """A host harness: what it runs on, and one dispatch."""

    name: str
    target: str

    def run(
        self,
        entry: str,
        params: bytes,
        axes: Sequence[NDArray[np.float32]],
        n: int,
        width: int,
        grid: bytes | None,
    ) -> NDArray[np.float32]: ...


def workgroups(n: int) -> tuple[int, int, int]:
    """The README's *Dispatch* for ``n`` points: along x, wrapping into y past 65,535."""
    groups = math.ceil(n / WORKGROUP)
    if groups <= MAX_GROUPS:
        return (groups, 1, 1)
    return (MAX_GROUPS, math.ceil(groups / MAX_GROUPS), 1)


def check_hash(name: str, data: bytes) -> None:
    """
    Refuse a file that is not the one the manifest records.

    :raises ValueError: Naming the file and both hashes.
    """
    record = shaders.manifest()["files"][name]
    found = shaders.sha256(data, text=record["text"])
    if found != record["sha256"]:
        raise ValueError(f"{name} hashes to {found[:12]}, the manifest says {record['sha256'][:12]}: run make shaders")


def verified(language: str, entry_point: str | None = None) -> str | bytes:
    """
    The shipped shader, read once: the bytes hashed against its manifest entry are the bytes returned. Text with CRLF
    made LF, as ``shaders.source`` gives it; bytes for SPIR-V.

    :raises ValueError: The file is not the manifest's (`check_hash`).
    :raises OSError: The file is missing or unreadable, never turned into a skip.
    """
    name = shaders.file_name(language, entry_point)
    data = shaders.path(language, entry_point).read_bytes()
    check_hash(name, data)
    return data if language == "spirv" else data.decode("utf-8").replace("\r\n", "\n")


def verified_tables() -> bytes:
    """The 8,192 bytes binding 1 holds, read once and hashed against the manifest's ``tables.f32`` entry."""
    data = shaders.tables()
    check_hash(shaders.TABLES_FILE, data)
    return data


def check_target(host: str, found: str, expected: str | None) -> None:
    """
    Refuse a host running on anything but ``expected`` (part of its ``target`` line, ignoring case).

    :raises HostTargetError: Naming both. With ``expected`` empty or None the target is logged, not asserted.
    """
    if not expected:
        _LOGGER.info(f"{host}: runs on {found}; {TARGET_ENV} is unset, so the target is not asserted")
        return
    if expected.lower() not in found.lower():
        raise HostTargetError(f"{host} runs on {found!r}, not on {expected!r} ({TARGET_ENV})")
    _LOGGER.info(f"{host}: runs on {found}, the target {expected!r}")


@functools.cache
def _open(name: str) -> Host:
    """The host ``name``, opened once per process: a device or context is costly, and one per process is enough."""
    return importlib.import_module(HOSTS[name]).open_host()


def open_host(name: str, target: str | None = None) -> Host:
    """
    The host ``name``, opened once per process, after its target is checked.

    :param target: What it must run on; None reads `TARGET_ENV`.
    :raises ValueError: An unknown host, naming the known ones.
    :raises HostUnavailable: Naming what is missing here.
    :raises HostTargetError: When it runs on another target.
    """
    if name not in HOSTS:
        raise ValueError(f"unknown host {name!r}; known: {', '.join(sorted(HOSTS))}")
    host = _open(name)
    check_target(name, host.target, os.environ.get(TARGET_ENV) if target is None else target)
    return host


def _lengths(axes: Sequence[NDArray], out: NDArray | None = None) -> int:
    """
    The number of points: every axis's length, and ``out``'s where given, which must all be one.

    :raises ValueError: Naming the lengths, before any dispatch.
    """
    lengths = [len(a) for a in axes]
    if len(set(lengths)) > 1:
        raise ValueError(f"the axes have lengths {lengths}; every axis needs one per point")
    if out is not None and len(out) != lengths[0]:
        raise ValueError(f"out has {len(out)} values for {lengths[0]} points")
    return lengths[0]


class HostSampler:
    """The calls every sampler has, each one dispatch on a host."""

    def __init__(self, params: NoiseParams, host: Host) -> None:
        for field in ("octaves", "perturb_octaves"):
            value = getattr(params, field)
            if value > MAX_OCTAVES:
                raise NotImplementedError(f"{field}={value} is past the emitted shaders' cap of {MAX_OCTAVES}")
        self.params, self.host = params, host
        self._params = pack_params(params)

    def _run(self, entry: str, axes: Sequence[NDArray], n: int, grid: bytes | None = None) -> NDArray[np.float32]:
        if n == 0:
            return np.empty(0, np.float32)
        contiguous = [np.ascontiguousarray(a, dtype=np.float32) for a in axes]
        return self.host.run(entry, self._params, contiguous, n, WIDTH[entry], grid)

    def sample_points(self, xs: NDArray, ys: NDArray, zs: NDArray, out: NDArray[np.float32]) -> NDArray[np.float32]:
        """3D noise at each point into ``out``. :raises ValueError: Axes, or ``out``, of unequal length."""
        out[...] = self._run("sample_points_3d", (xs, ys, zs), _lengths((xs, ys, zs), out))
        return out

    def sample_points_2d(self, xs: NDArray, ys: NDArray, out: NDArray[np.float32]) -> NDArray[np.float32]:
        """2D noise at each point into ``out``. :raises ValueError: Axes, or ``out``, of unequal length."""
        out[...] = self._run("sample_points_2d", (xs, ys), _lengths((xs, ys), out))
        return out

    def sample_grid(
        self, start: Sequence[int], shape: Sequence[int], scales: Sequence[float] = (1.0, 1.0, 1.0)
    ) -> NDArray[np.float32]:
        """The grid, its cells x-major (the README's *Output*), reshaped to ``shape``."""
        shape = tuple(int(n) for n in shape)
        grid = pack_grid(start, shape, scales)
        return self._run("sample_grid", (), math.prod(shape), grid).reshape(shape)

    def warp_points(self, xs: NDArray, ys: NDArray, zs: NDArray) -> NDArray[np.float32]:
        """The warped coordinates, ``(N, 3)``. :raises ValueError: Axes of unequal length."""
        n = _lengths((xs, ys, zs))
        return self._run("warp_points_3d", (xs, ys, zs), n).reshape(n, 3)

    def warp_points_2d(self, xs: NDArray, ys: NDArray) -> NDArray[np.float32]:
        """The warped coordinates, ``(N, 2)``. :raises ValueError: Axes of unequal length."""
        n = _lengths((xs, ys))
        return self._run("warp_points_2d", (xs, ys), n).reshape(n, 2)


def renderings(host: Host) -> tuple[Sample, Sample, Grid]:
    """``sample``, ``warp`` and ``grid`` for ``conformance.check``, one `HostSampler` per distinct parameter record."""
    built: dict[NoiseParams, HostSampler] = {}

    def sampler_for(params: NoiseParams) -> HostSampler:
        if params not in built:
            built[params] = HostSampler(params, host)
        return built[params]

    def sample(params: NoiseParams, xs: NDArray, ys: NDArray, zs: NDArray | None) -> NDArray:
        s, out = sampler_for(params), np.empty(len(xs), np.float32)
        return s.sample_points_2d(xs, ys, out) if zs is None else s.sample_points(xs, ys, zs, out)

    def warp(params: NoiseParams, xs: NDArray, ys: NDArray, zs: NDArray | None) -> NDArray:
        s = sampler_for(params)
        return s.warp_points_2d(xs, ys) if zs is None else s.warp_points(xs, ys, zs)

    def grid(params: NoiseParams, start: Sequence[int], shape: Sequence[int], scales: Sequence[float]) -> NDArray:
        return sampler_for(params).sample_grid(start, shape, scales)

    return sample, warp, grid


if __name__ == "__main__":
    _logging.basicConfig(level=_logging.INFO)
    for host_name in sorted(HOSTS):
        try:
            print(f"{host_name}: {open_host(host_name).target}")
        except (HostUnavailable, HostTargetError) as e:
            print(f"{host_name}: {e}")
