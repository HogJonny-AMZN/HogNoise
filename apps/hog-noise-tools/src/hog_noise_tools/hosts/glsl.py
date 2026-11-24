"""
HogNoise tools: the glsl host. The five ``noise.<entry_point>.comp`` files in moderngl, each block bound by the name
``manifest.json`` records for that entry point.
Package: hog_noise_tools.hosts.glsl

naga writes no ``binding =`` qualifier, so a GLSL host binds by block name, and the names differ per entry point (the
shaders README, *GLSL binds by name*). Every call makes this host's context current first: in a process that has used
wgpu, wgpu's OpenGL back end can leave its own context current, and the next program fails to build (the CI proof's
spec, *Facts*). ``HOG_NOISE_GL_BACKEND`` names moderngl's context back end; unset, it is ``egl`` on Linux (headless CI)
and the platform's default elsewhere.
"""

from __future__ import annotations

import logging as _logging
import os
import sys
from collections.abc import Sequence
from typing import Any

import numpy as np
from numpy.typing import NDArray

from hog_noise import shaders
from hog_noise_tools.hosts import BINDING_KINDS, HostUnavailable, verified, verified_tables, workgroups

_MODULE_NAME = "hog_noise_tools.hosts.glsl"
__version__ = "0.1.0"
__updated__ = "2026-11-23"
_LOGGER = _logging.getLogger(_MODULE_NAME)

BACKEND_ENV = "HOG_NOISE_GL_BACKEND"


def _backend() -> str | None:
    """moderngl's context back end: `BACKEND_ENV`'s value (empty means the default), else egl on Linux."""
    if BACKEND_ENV in os.environ:
        return os.environ[BACKEND_ENV] or None
    return "egl" if sys.platform.startswith("linux") else None


def context() -> Any:
    """
    A standalone OpenGL 4.3 context.

    :raises HostUnavailable: moderngl missing, or no OpenGL 4.3 context here, naming the back end tried.
    """
    try:
        import moderngl
    except ImportError as e:
        raise HostUnavailable("moderngl is not installed: uv sync --group hosts") from e
    backend = _backend()
    _LOGGER.info(f"glsl: asking moderngl for an OpenGL 4.3 context, {backend or 'default'} back end ({BACKEND_ENV})")
    try:
        return moderngl.create_standalone_context(require=430, **({"backend": backend} if backend else {}))
    except Exception as e:  # moderngl's Error, or glcontext's own when no driver or display exists
        raise HostUnavailable(
            f"no OpenGL 4.3 context ({backend or 'default'} back end): {type(e).__name__}: {e}"
        ) from e


def open_host() -> Glsl:
    """The host on a context of its own. :raises HostUnavailable: As `context`."""
    return Glsl(context())


class Glsl:
    """One compute program per entry point, each block bound to its binding, and the tables' buffer."""

    name = "glsl"

    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx
        bindings = shaders.manifest()["bindings"]
        #: per entry point, the bindings it reads: those with a block for it
        self.reads: dict[str, list[int]] = {}
        self.programs: dict[str, Any] = {}
        with ctx:
            # read with this context current: moderngl reads ctx.info once, from whichever context is current, and
            # caches it; after wgpu's OpenGL back end it could be wgpu's
            self.target = f"{ctx.info['GL_RENDERER']} (OpenGL {ctx.info['GL_VERSION']})"
            for entry in shaders.ENTRY_POINTS:
                program = ctx.compute_shader(verified("glsl", entry))
                self.reads[entry] = []
                for b in bindings:
                    block = b["glsl"]["blocks"].get(entry)
                    if block is not None:
                        try:
                            program[block].binding = b["binding"]
                        except KeyError as e:
                            raise ValueError(
                                f"{entry}: the manifest's block {block!r} for binding {b['binding']} is not in "
                                f"{shaders.file_name('glsl', entry)}: run make shaders"
                            ) from e
                        self.reads[entry].append(b["binding"])
                self.programs[entry] = program
            self.tables = ctx.buffer(verified_tables())
        _LOGGER.info(f"glsl: {len(self.programs)} programs on {self.target}")

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
        ctx = self.ctx
        with ctx:
            made = {0: ctx.buffer(params), 5: ctx.buffer(reserve=n * width * 4)}
            made.update({2 + i: ctx.buffer(a.tobytes()) for i, a in enumerate(axes)})
            if grid is not None:
                made[6] = ctx.buffer(grid)
            buffers = {1: self.tables, **made}
            for binding in self.reads[entry]:
                if BINDING_KINDS[binding] == "uniform":
                    buffers[binding].bind_to_uniform_block(binding)
                else:
                    buffers[binding].bind_to_storage_buffer(binding)
            self.programs[entry].run(*workgroups(n))
            # storage writes are incoherent: OpenGL makes them visible to a buffer read only after this barrier
            # (glMemoryBarrier); finish alone waits for the dispatch but promises nothing about visibility
            ctx.memory_barrier(ctx.BUFFER_UPDATE_BARRIER_BIT)
            ctx.finish()
            values = np.frombuffer(made[5].read(), dtype=np.float32).copy()
            for buffer in made.values():
                buffer.release()
        return values


if __name__ == "__main__":
    _logging.basicConfig(level=_logging.INFO)
    from hog_noise import NoiseParams
    from hog_noise_tools.hosts import HostSampler

    host = open_host()
    xs = np.linspace(-100, 100, 5, dtype=np.float32)
    s = HostSampler(NoiseParams(frequency=0.01), host)
    print(host.target, np.round(s.sample_points(xs, xs, np.zeros(5, np.float32), np.empty(5, np.float32)), 5))
