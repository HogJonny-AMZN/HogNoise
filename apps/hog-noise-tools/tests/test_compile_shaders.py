"""
HogNoise tools: the compile script runs each language's own compiler on every emitted file.
Package: apps/hog-noise-tools/tests/test_compile_shaders
"""

import subprocess

import pytest

from hog_noise import shaders
from hog_noise_tools import compile_shaders as c


@pytest.fixture
def calls(monkeypatch):
    seen = []

    def run(argv, **kwargs):
        seen.append([str(a) for a in argv])
        return subprocess.CompletedProcess(argv, 0, "version 1\n", "")

    monkeypatch.setattr(c.subprocess, "run", run)
    monkeypatch.setattr(c, "find", lambda name: f"/bin/{name}")
    return seen


def test_hlsl_compiles_every_entry_point_in_both_compilers(calls):
    assert c.main(["hlsl"]) == 0
    for ep in shaders.ENTRY_POINTS:
        assert any(a[0] == "/bin/fxc" and "cs_5_0" in a and ep in a for a in calls)
        assert any(a[0] == "/bin/dxc" and "cs_6_0" in a and ep in a for a in calls)


def test_glsl_validates_every_file_and_spirv_is_validated(calls):
    assert c.main(["glsl", "spirv"]) == 0
    assert sum(a[0] == "/bin/glslangValidator" and a[-1].endswith(".comp") for a in calls) == 5
    assert any(a[0] == "/bin/spirv-val" and a[-1].endswith("noise.spv") for a in calls)


def test_a_missing_compiler_fails_and_names_it(monkeypatch, capsys):
    monkeypatch.setattr(c, "find", lambda name: None)
    assert c.main(["spirv"]) == 2
    assert "spirv-val not found" in capsys.readouterr().err


def test_a_compile_error_fails_with_its_output(monkeypatch, calls, caplog):
    def run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 1, "", "error X3000: syntax error")

    monkeypatch.setattr(c.subprocess, "run", run)
    with caplog.at_level("INFO", logger=c._MODULE_NAME):
        assert c.main(["hlsl"]) == 1
    assert any(r.levelname == "ERROR" and "X3000" in r.getMessage() for r in caplog.records)


def test_every_failure_is_counted_not_only_the_first(monkeypatch, calls, caplog, capsys):
    def run(argv, **kwargs):
        failed = "--version" not in argv and "sample_grid" in argv
        return subprocess.CompletedProcess(argv, int(failed), "", "error X3000" if failed else "")

    monkeypatch.setattr(c.subprocess, "run", run)
    with caplog.at_level("INFO", logger=c._MODULE_NAME):
        assert c.main(["hlsl"]) == 1
    lines = [r.getMessage() for r in caplog.records]
    assert sum(m.startswith("FAIL") for m in lines) == 2 and sum(m.startswith("ok  ") for m in lines) == 8
    assert "2 of 10 failed" in capsys.readouterr().out


def test_a_compiler_that_cannot_start_is_missing_not_a_crash(monkeypatch, calls, capsys):
    def run(argv, **kwargs):
        raise OSError("exec format error")

    monkeypatch.setattr(c.subprocess, "run", run)
    assert c.main(["spirv"]) == 2
    assert "spirv-val at /bin/spirv-val cannot run" in capsys.readouterr().err


def test_a_hung_compile_is_a_failure(monkeypatch, calls, caplog):
    def run(argv, **kwargs):
        if "--version" in argv:
            return subprocess.CompletedProcess(argv, 0, "v1\n", "")
        raise subprocess.TimeoutExpired(argv, kwargs.get("timeout"))

    monkeypatch.setattr(c.subprocess, "run", run)
    with caplog.at_level("INFO", logger=c._MODULE_NAME):
        assert c.main(["spirv"]) == 1
    assert any(r.levelname == "ERROR" and "timed out" in r.getMessage() for r in caplog.records)
