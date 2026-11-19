"""
HogNoise tools: compile every emitted shader with its own language's compiler, printing each compiler's version.
Package: hog_noise_tools.compile_shaders

    uv run hog-noise-compile-shaders hlsl            # fxc cs_5_0 and dxc cs_6_0, every entry point (Windows)
    uv run hog-noise-compile-shaders glsl spirv      # glslangValidator per file, spirv-val (Ubuntu)

A compiler is found on PATH, or for fxc and dxc in the newest Windows SDK's x64 folder. Exit 0 when every file compiles,
1 when one does not (its output printed), 2 when a compiler is missing.
"""

from __future__ import annotations

import argparse
import logging as _logging
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from hog_noise import shaders

_MODULE_NAME = "hog_noise_tools.compile_shaders"
__version__ = "0.1.0"
__updated__ = "2026-11-18"
_LOGGER = _logging.getLogger(_MODULE_NAME)

SDK_BIN = Path("C:/Program Files (x86)/Windows Kits/10/bin")
NEEDS = {"hlsl": ("fxc", "dxc"), "glsl": ("glslangValidator",), "spirv": ("spirv-val",)}


def find(name: str) -> str | None:
    """``name`` on PATH, else (fxc, dxc) in the newest Windows SDK's ``x64`` folder."""
    on_path = shutil.which(name)
    if on_path or name not in ("fxc", "dxc") or not SDK_BIN.is_dir():
        return on_path
    found = sorted(SDK_BIN.glob(f"10.*/x64/{name}.exe"))
    return str(found[-1]) if found else None


def commands(language: str, tool: dict[str, str], out: Path) -> list[list[str]]:
    """Every compiler call for ``language``."""
    if language == "hlsl":
        src = str(shaders.path("hlsl"))
        fxc = [[tool["fxc"], "-nologo", "-T", "cs_5_0", "-E", ep, "-Fo", str(out), src] for ep in shaders.ENTRY_POINTS]
        dxc = [[tool["dxc"], "-T", "cs_6_0", "-E", ep, "-Fo", str(out), src] for ep in shaders.ENTRY_POINTS]
        return fxc + dxc
    if language == "glsl":
        return [[tool["glslangValidator"], str(shaders.path("glsl", ep))] for ep in shaders.ENTRY_POINTS]
    return [[tool["spirv-val"], str(shaders.path("spirv"))]]


def main(argv: list[str] | None = None) -> int:
    """Compile the named languages; see the module's docstring for the exit codes."""
    parser = argparse.ArgumentParser(prog="hog-noise-compile-shaders", description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("languages", nargs="+", choices=sorted(NEEDS))
    args = parser.parse_args(argv)
    tool: dict[str, str] = {}
    for name in (n for lang in args.languages for n in NEEDS[lang]):
        found = find(name)
        if found is None:
            print(f"compile-shaders: {name} not found on PATH or in the Windows SDK", file=sys.stderr)
            return 2
        tool[name] = found
        # fxc has no version option and prints only a complaint; its path, the SDK's folder, names its build.
        version = subprocess.run([found, "--version"], capture_output=True, text=True, check=False)
        first = next(iter((version.stdout or version.stderr).strip().splitlines()), "")
        print(f"{name}: {found}: {first}")
    failed = 0
    with tempfile.TemporaryDirectory() as tmp:
        for lang in args.languages:
            for cmd in commands(lang, tool, Path(tmp) / "out.bin"):
                done = subprocess.run(cmd, capture_output=True, text=True, check=False)
                ok = done.returncode == 0
                print(f"{'ok  ' if ok else 'FAIL'} {' '.join([Path(cmd[0]).name, *cmd[1:]])}")
                if not ok:
                    failed += 1
                    print(f"{done.stdout}{done.stderr}", file=sys.stderr)
    print(f"compile-shaders: {failed} failed" if failed else "compile-shaders: every file compiled")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
