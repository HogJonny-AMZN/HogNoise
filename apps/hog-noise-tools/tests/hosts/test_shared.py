"""
HogNoise tools: what every host harness shares, with no GPU: the dispatch shape, the file check, the target check and
the sampler's own refusals.
Package: apps/hog-noise-tools/tests/hosts/test_shared
"""

import numpy as np
import pytest

from hog_noise import NoiseParams, gpu, shaders
from hog_noise_tools import hosts


class FakeHost:
    """A host that records each dispatch and returns ``n * width`` ascending floats."""

    name = "fake"
    target = "a fake adapter (none)"

    def __init__(self):
        self.calls = []

    def run(self, entry, params, axes, n, width, grid):
        self.calls.append((entry, params, [a.copy() for a in axes], n, width, grid))
        return np.arange(n * width, dtype=np.float32)


@pytest.mark.parametrize(
    "n, groups", [(1, (1, 1, 1)), (64, (1, 1, 1)), (65, (2, 1, 1)), (65535 * 64 + 1, (65535, 2, 1))]
)
def test_the_dispatch_is_the_readmes(n, groups):
    """The README's *Dispatch*: ceil(n / 64) along x, wrapping into y past 65,535."""
    assert hosts.workgroups(n) == groups


def test_the_binding_kinds_are_the_manifests_registers():
    """b is a uniform, t read-only storage, u read-write storage: the README's table, read from the manifest."""
    kind = {"b": "uniform", "t": "read", "u": "write"}
    found = [kind[b["hlsl"][0]] for b in sorted(shaders.manifest()["bindings"], key=lambda b: b["binding"])]
    assert found == list(hosts.BINDING_KINDS)


def test_every_entry_point_has_a_width():
    assert set(hosts.WIDTH) == set(shaders.ENTRY_POINTS) == set(gpu.ENTRY_POINTS)


def test_a_file_that_is_not_the_manifests_is_refused():
    with pytest.raises(ValueError, match=r"noise\.spv hashes to .*, the manifest says"):
        hosts.check_hash("noise.spv", b"not the shipped bytes")


def test_every_shipped_file_hashes_to_its_manifest_entry():
    """The positive side of the refusal above: each file a host loads passes, so the refusal is not always on."""
    for language in ("spirv", "glsl"):
        for entry in shaders.ENTRY_POINTS if language == "glsl" else (None,):
            assert hosts.verified(language, entry)


def test_a_host_on_another_target_is_refused():
    with pytest.raises(hosts.HostTargetError, match="not on 'llvmpipe'"):
        hosts.check_target("glsl", "NVIDIA GeForce RTX 5090 (OpenGL 4.6)", "llvmpipe")


def test_a_host_on_its_target_passes_ignoring_case():
    hosts.check_target("glsl", "llvmpipe (LLVM 19.1.1, 256 bits) (OpenGL 4.5)", "LLVMpipe")


def test_with_no_target_named_the_host_is_not_checked():
    hosts.check_target("glsl", "anything", None)
    hosts.check_target("glsl", "anything", "")


def test_an_unknown_host_is_refused_naming_the_known_ones():
    with pytest.raises(ValueError, match="glsl, spirv-naga"):
        hosts.open_host("metal")


def test_the_sampler_packs_the_uniforms_and_runs_each_entry_point():
    host = FakeHost()
    params = NoiseParams(frequency=0.02, seed=7)
    s = hosts.HostSampler(params, host)
    xs = np.linspace(-1, 1, 5, dtype=np.float32)
    s.sample_points(xs, xs, xs, np.empty(5, np.float32))
    s.sample_points_2d(xs, xs, np.empty(5, np.float32))
    assert s.warp_points(xs, xs, xs).shape == (5, 3)
    assert s.warp_points_2d(xs, xs).shape == (5, 2)
    assert s.sample_grid((0, 0, 0), (2, 3, 1)).shape == (2, 3, 1)
    entries = [c[0] for c in host.calls]
    assert entries == ["sample_points_3d", "sample_points_2d", "warp_points_3d", "warp_points_2d", "sample_grid"]
    assert all(c[1] == gpu.pack_params(params) for c in host.calls)
    assert host.calls[-1][5] == gpu.pack_grid((0, 0, 0), (2, 3, 1), (1.0, 1.0, 1.0))
    assert [len(c[2]) for c in host.calls] == [3, 2, 3, 2, 0]


@pytest.mark.parametrize(
    "call",
    [
        lambda s, a, b: s.sample_points(a, b, a, np.empty(len(a), np.float32)),
        lambda s, a, b: s.sample_points_2d(a, b, np.empty(len(a), np.float32)),
        lambda s, a, b: s.sample_points(a, a, a, np.empty(len(b), np.float32)),
        lambda s, a, b: s.warp_points(a, b, a),
        lambda s, a, b: s.warp_points_2d(a, b),
    ],
    ids=["sample_points", "sample_points_2d", "out", "warp_points", "warp_points_2d"],
)
def test_a_short_axis_is_refused_before_any_dispatch(call):
    """A shader's robust access would clamp a short axis to its last value and answer, silently."""
    host = FakeHost()
    xs = np.linspace(-10, 10, 100, dtype=np.float32)
    with pytest.raises(ValueError, match="100"):
        call(hosts.HostSampler(NoiseParams(), host), xs, xs[:99])
    assert host.calls == []


def test_more_than_32_octaves_is_not_implemented_before_any_dispatch():
    with pytest.raises(NotImplementedError, match="octaves=33"):
        hosts.HostSampler(NoiseParams(octaves=33), FakeHost())


def test_no_points_dispatch_nothing():
    host = FakeHost()
    empty = np.empty(0, np.float32)
    assert len(hosts.HostSampler(NoiseParams(), host).sample_points(empty, empty, empty, empty)) == 0
    assert host.calls == []


def test_renderings_build_one_sampler_per_parameter_record():
    host = FakeHost()
    sample, warp, grid = hosts.renderings(host)
    xs = np.zeros(3, np.float32)
    p = NoiseParams()
    sample(p, xs, xs, None)
    sample(p, xs, xs, xs)
    warp(p, xs, xs, None)
    grid(p, (0, 0, 0), (1, 1, 1), (1.0, 1.0, 1.0))
    assert [c[0] for c in host.calls] == ["sample_points_2d", "sample_points_3d", "warp_points_2d", "sample_grid"]


def test_the_bytes_hashed_are_the_bytes_returned(monkeypatch):
    """No second read: with ``shaders.source`` made to return something else, ``verified`` still gives the file."""
    monkeypatch.setattr(shaders, "source", lambda *a, **k: b"a second read, never hashed")
    assert hosts.verified("spirv") == shaders.path("spirv").read_bytes()
    text = hosts.verified("glsl", "sample_grid")
    assert isinstance(text, str) and "\r\n" not in text and text.startswith("#version 430")


def test_an_altered_file_on_disk_is_refused(monkeypatch, tmp_path):
    altered = tmp_path / "noise.spv"
    altered.write_bytes(shaders.path("spirv").read_bytes()[:-4] + b"\0\0\0\0")
    monkeypatch.setattr(shaders, "path", lambda *a, **k: altered)
    with pytest.raises(ValueError, match=r"noise\.spv hashes to"):
        hosts.verified("spirv")


def test_tables_that_are_not_the_manifests_are_refused(monkeypatch):
    monkeypatch.setattr(shaders, "tables", lambda: bytes(shaders.TABLES_BYTES))
    with pytest.raises(ValueError, match=r"tables\.f32 hashes to"):
        hosts.verified_tables()


def test_the_shipped_tables_pass():
    """The positive side of the refusal above."""
    assert hosts.verified_tables() == shaders.tables()


def test_missing_tables_are_an_error_not_a_skip(monkeypatch, tmp_path):
    monkeypatch.setattr(shaders.importlib.resources, "files", lambda package: tmp_path)
    with pytest.raises(FileNotFoundError):
        hosts.verified_tables()


def test_unreadable_tables_are_an_error_not_a_skip(monkeypatch, tmp_path):
    """A directory where tables.f32 should be: IsADirectoryError on Linux, PermissionError on Windows."""
    (tmp_path / "shaders" / shaders.TABLES_FILE).mkdir(parents=True)
    monkeypatch.setattr(shaders.importlib.resources, "files", lambda package: tmp_path)
    with pytest.raises(OSError) as raised:
        hosts.verified_tables()
    assert not isinstance(raised.value, FileNotFoundError)


def test_a_missing_shader_is_an_error_not_a_skip(monkeypatch, tmp_path):
    monkeypatch.setattr(shaders, "path", lambda *a, **k: tmp_path / "noise.spv")
    with pytest.raises(FileNotFoundError):
        hosts.verified("spirv")


def test_an_unreadable_shader_is_an_error_not_a_skip(monkeypatch, tmp_path):
    """A directory where the file should be: IsADirectoryError on Linux, PermissionError on Windows; never a refusal."""
    (tmp_path / "noise.spv").mkdir()
    monkeypatch.setattr(shaders, "path", lambda *a, **k: tmp_path / "noise.spv")
    with pytest.raises(OSError) as raised:
        hosts.verified("spirv")
    assert not isinstance(raised.value, FileNotFoundError)


class FakeContext:
    """Enough of a moderngl context for `glsl.Glsl` to build against, with programs that know no block."""

    info = {"GL_RENDERER": "a fake renderer", "GL_VERSION": "4.3"}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def compute_shader(self, source):
        return {}

    def buffer(self, data=None, reserve=0):
        return data


def test_a_manifest_block_the_program_lacks_names_itself():
    """A naga rename the manifest has not caught up with is named, not a bare KeyError."""
    from hog_noise_tools.hosts import glsl

    with pytest.raises(
        ValueError, match=r"sample_points_3d: the manifest's block 'Params_block_0Compute'.*make shaders"
    ):
        glsl.Glsl(FakeContext())


class RecordingContext:
    """
    A moderngl context that records what is called, and whether it was current: ``info`` refuses to be read while
    another context may be current, and its programs know every block.
    """

    BUFFER_UPDATE_BARRIER_BIT = 0x200

    def __init__(self):
        self.current, self.log = False, []

    def __enter__(self):
        self.current = True
        return self

    def __exit__(self, *exc):
        self.current = False
        return False

    @property
    def info(self):
        assert self.current, "ctx.info read with the context not current"
        return {"GL_RENDERER": "a recorded renderer", "GL_VERSION": "4.3"}

    def compute_shader(self, source):
        log = self.log

        class Program(dict):
            def __missing__(self, block):
                return type("Block", (), {"binding": None})()

            def run(self, *groups):
                log.append("run")

        return Program()

    def buffer(self, data=None, reserve=0):
        log, size = self.log, len(data) if data is not None else reserve

        class Buffer:
            def bind_to_uniform_block(self, binding): ...

            def bind_to_storage_buffer(self, binding): ...

            def read(self):
                log.append("read")
                return bytes(size)

            def release(self): ...

        return Buffer()

    def memory_barrier(self, barriers, by_region=False):
        self.log.append(("barrier", barriers))

    def finish(self):
        self.log.append("finish")


def test_the_gl_target_is_read_with_its_context_current():
    """moderngl caches ctx.info from whichever context is current: after wgpu's OpenGL back end, maybe wgpu's."""
    from hog_noise_tools.hosts import glsl

    assert glsl.Glsl(RecordingContext()).target == "a recorded renderer (OpenGL 4.3)"


def test_the_gl_output_is_read_after_a_buffer_update_barrier():
    """Storage writes are incoherent: glMemoryBarrier(GL_BUFFER_UPDATE_BARRIER_BIT) before the read, not finish."""
    from hog_noise_tools.hosts import glsl

    ctx = RecordingContext()
    xs = np.zeros(4, np.float32)
    hosts.HostSampler(NoiseParams(), glsl.Glsl(ctx)).sample_points_2d(xs, xs, np.empty(4, np.float32))
    run, read = ctx.log.index("run"), ctx.log.index("read")
    barriers = [i for i, e in enumerate(ctx.log) if isinstance(e, tuple) and e[1] & ctx.BUFFER_UPDATE_BARRIER_BIT]
    assert any(run < i < read for i in barriers), ctx.log
