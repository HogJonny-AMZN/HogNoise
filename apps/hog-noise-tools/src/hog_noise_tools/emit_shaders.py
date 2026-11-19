"""
HogNoise tools: write naga's HLSL, GLSL and SPIR-V of noise.wgsl, the tables and the manifest into hog_noise/shaders/.
Package: hog_noise_tools.emit_shaders

    make shaders                      # == uv run hog-noise-emit-shaders
    HOG_NOISE_NAGA=/path/to/naga make shaders

The naga that writes them is pinned (``apps/hog-noise-tools/naga-version.txt``, the stage 3 spec's decision 2): a
different version is refused before anything runs. Every file is built in a temporary folder beside the destination;
a naga failure, an empty output, or a binding table that cannot be read whole from what naga wrote refuses with nothing
written (ledger P-13). Only then is each file replaced, one atomic replace per file, the manifest last, and an emitted
file the run no longer writes is removed. A failure while replacing is reported as partial, naming what was replaced.
Text is written LF, and every hash is ``shaders.sha256``.
"""

from __future__ import annotations

import argparse
import json
import logging as _logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from hog_noise import shaders, tables
from hog_noise_tools.repo import APP_ROOT, REPO_ROOT

_MODULE_NAME = "hog_noise_tools.emit_shaders"
__version__ = "0.1.0"
__updated__ = "2026-11-18"
_LOGGER = _logging.getLogger(_MODULE_NAME)

NAGA_ENV = "HOG_NOISE_NAGA"
PIN_FILE = APP_ROOT / "naga-version.txt"
GLSL_PROFILE = "core430"
WGSL = shaders.path("wgsl")
DEST = shaders.path("hlsl").parent
WORKGROUP_SIZE = 64
DISPATCH = "point_index = gid.x + gid.y * 65535 * 64"
#: Seconds one naga call may take; it writes each file in well under one.
TIMEOUT = 300
#: Names this emitter owns in the destination; anything else there (README.md, __init__.py) is left alone.
_OWNED = re.compile(r"^(noise\.[\w.]+|tables\.f32|manifest\.json)$")
#: A WGSL resource declaration, its two attributes in either order (WGSL allows both).
_WGSL_BINDING = re.compile(
    r"(?:@group\((?P<g1>\d+)\)\s*@binding\((?P<b1>\d+)\)|@binding\((?P<b2>\d+)\)\s*@group\((?P<g2>\d+)\))"
    r"\s*var(?:<[^>]*>)?\s+(?P<name>\w+)"
)


class EmitError(RuntimeError):
    """The emitter refused; nothing was written."""


class PartialWrite(EmitError):
    """Replacing the files failed part way: the destination holds a mixed set until the next run."""


def pinned_version() -> str:
    """The naga-cli version the shaders are written with."""
    return PIN_FILE.read_text(encoding="utf-8").strip()


def default_naga() -> list[str]:
    """``HOG_NOISE_NAGA`` if set, else ``naga`` on PATH."""
    return [os.environ.get(NAGA_ENV) or "naga"]


def check_naga(naga: Sequence[str], pin: str) -> None:
    """Refuse a naga that is missing or not the pinned version, saying how to install the pinned one."""
    install = f"cargo install naga-cli --version {pin} --locked"
    try:
        done = subprocess.run([*naga, "--version"], capture_output=True, text=True, check=True, timeout=TIMEOUT)
    except (OSError, subprocess.SubprocessError) as exc:
        raise EmitError(f"cannot run naga ({' '.join(naga)}): {exc}; {install}") from exc
    found = done.stdout.strip()
    if not found.split():
        raise EmitError(f"{' '.join(naga)} printed no version for --version; {install}")
    if found.split()[-1] != pin:
        raise EmitError(
            f"naga {found} at {' '.join(naga)}, but the pin is {pin}: {install} --root <folder>, then set {NAGA_ENV} "
            f"to its bin/naga"
        )
    _LOGGER.info(f"naga {pin} at {' '.join(naga)}")


def jobs() -> list[tuple[str, list[str]]]:
    """Each emitted file and the naga arguments that write it, the output path last."""
    out: list[tuple[str, list[str]]] = [("noise.hlsl", []), ("noise.spv", [])]
    out += [
        (f"noise.{ep}.comp", ["--profile", GLSL_PROFILE, "--entry-point", ep, "--shader-stage", "compute"])
        for ep in shaders.ENTRY_POINTS
    ]
    return out


def expected_files() -> set[str]:
    """Every file one run writes: the shaders, the tables and the manifest."""
    return {name for name, _ in jobs()} | {shaders.TABLES_FILE, shaders.MANIFEST_FILE}


def wgsl_bindings(wgsl: str) -> list[tuple[int, int, str]]:
    """``(group, binding, name)`` for every resource the WGSL declares, comments ignored."""
    code = re.sub(r"//[^\n]*", "", wgsl)
    return [
        (int(m["g1"] or m["g2"]), int(m["b1"] or m["b2"]), m["name"]) for m in _WGSL_BINDING.finditer(code)
    ]  # fmt: skip


def declared_bindings() -> list[tuple[int, int, str]]:
    """The WGSL's bindings; read before naga runs, so a source with none is refused at once.

    :raises EmitError: When the WGSL declares no binding (ledger P-13: an input that yields nothing).
    """
    declared = wgsl_bindings(WGSL.read_text(encoding="utf-8"))
    if not declared:
        raise EmitError(f"no @group/@binding declaration found in {WGSL.name}")
    return declared


def bindings(build: Path, declared: list[tuple[int, int, str]]) -> list[dict[str, Any]]:
    """The binding table per language, read from what was emitted, so a naga rename shows in the manifest's diff.

    :raises EmitError: When a binding has no HLSL register or no GLSL block in any entry point: a table a host cannot
        use is refused, not written (ledger P-13).
    """
    hlsl = (build / "noise.hlsl").read_text(encoding="utf-8")
    glsl = {ep: (build / f"noise.{ep}.comp").read_text(encoding="utf-8") for ep in shaders.ENTRY_POINTS}
    rows = []
    for group, binding, name in declared:
        register = re.search(rf"\b{name}\s*:\s*register\(([btu]\d+)\)", hlsl)
        var = f"_group_{group}_binding_{binding}_cs"
        blocks = {}
        for ep, text in glsl.items():
            # naga writes `layout(std140) uniform Params_block_0Compute { Params _group_0_binding_0_cs; };`: the
            # variable is the block's one member, and an entry point that does not use a binding has no block for it.
            found = re.search(rf"(\w+)\s*\{{[^}}]*\b{var}\b", text)
            if found:
                blocks[ep] = found.group(1)
        if register is None or not blocks:
            missing = "no HLSL register" if register is None else "no GLSL block in any entry point"
            raise EmitError(f"binding {binding} ({name}): {missing} in what naga wrote")
        rows.append({
            "binding": binding, "wgsl": name, "hlsl": register.group(1),
            "glsl": {"variable": var, "blocks": blocks}, "spirv": {"set": group, "binding": binding},
        })  # fmt: skip
    return rows


def build(naga: Sequence[str], pin: str, folder: Path) -> dict[str, Any]:
    """Write every file into ``folder`` and return the manifest; raise ``EmitError`` on any failure or empty file."""
    declared = declared_bindings()
    files: dict[str, Any] = {}
    for name, args in jobs():
        out = folder / name
        cmd = [*naga, *args, str(WGSL), str(out)]
        try:
            done = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=TIMEOUT)
        except (OSError, subprocess.SubprocessError) as exc:
            raise EmitError(f"naga could not write {name}: {exc}") from exc
        if done.returncode != 0:
            raise EmitError(f"naga failed writing {name} (rc {done.returncode}): {done.stderr.strip()[:400]}")
        if not out.is_file() or out.stat().st_size == 0:
            raise EmitError(f"naga wrote {name} empty or not at all")
        text = not name.endswith(".spv")
        if text:
            out.write_bytes(out.read_bytes().replace(b"\r\n", b"\n"))
        data = out.read_bytes()
        command = " ".join(["naga", *args, "noise.wgsl", name])
        files[name] = {"command": command, "text": text, "sha256": shaders.sha256(data, text=text), "bytes": len(data)}
        _LOGGER.info(f"{name}: {len(data):,} bytes")
    table = tables.binding_table().astype("<f4").tobytes()
    (folder / shaders.TABLES_FILE).write_bytes(table)
    files[shaders.TABLES_FILE] = {
        "command": "hog_noise.tables.binding_table(), float32 little-endian", "text": False,
        "sha256": shaders.sha256(table, text=False), "bytes": len(table),
    }  # fmt: skip
    return {
        "generator": _MODULE_NAME,
        "naga": pin,
        "wgsl": {
            "path": WGSL.relative_to(REPO_ROOT).as_posix(),
            "sha256": shaders.sha256(WGSL.read_bytes(), text=True),
        },
        "glsl_profile": GLSL_PROFILE,
        "workgroup_size": WORKGROUP_SIZE,
        "dispatch": DISPATCH,
        "files": files,
        "bindings": bindings(folder, declared),
    }


def install(folder: Path, dest: Path, written: set[str]) -> None:
    """Replace ``dest``'s emitted files from ``folder``, the manifest last, then remove the stale ones.

    :raises PartialWrite: When a replace or a removal fails, naming the files already replaced.
    """
    order = sorted(written - {shaders.MANIFEST_FILE}) + [shaders.MANIFEST_FILE]
    done: list[str] = []
    try:
        for name in order:
            os.replace(folder / name, dest / name)
            done.append(name)
        for stale in (p for p in dest.iterdir() if p.is_file() and _OWNED.match(p.name) and p.name not in written):
            stale.unlink()
            _LOGGER.info(f"removed {stale.name}: no longer emitted")
    except OSError as exc:
        raise PartialWrite(
            f"{exc}; replaced {len(done)} of {len(order)} ({', '.join(done) or 'none'}): the folder is a mixed set, "
            f"rerun make shaders"
        ) from exc


def emit(naga: Sequence[str], dest: Path = DEST, pin: str | None = None) -> dict[str, Any]:
    """Check naga, build everything beside ``dest``, then replace ``dest``'s emitted files."""
    pin = pin or pinned_version()
    check_naga(naga, pin)
    folder = Path(tempfile.mkdtemp(prefix=".emit-", dir=dest.parent))
    try:
        manifest = build(naga, pin, folder)
        text = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
        (folder / shaders.MANIFEST_FILE).write_bytes(text.encode("utf-8"))
        written = set(manifest["files"]) | {shaders.MANIFEST_FILE}
        install(folder, dest, written)
        _LOGGER.info(f"wrote {len(written)} files to {dest} with naga {pin}")
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    return manifest


def main(argv: list[str] | None = None) -> int:
    """Emit the shaders; exit 1 with the reason when the emitter refuses or stops part way."""
    parser = argparse.ArgumentParser(prog="hog-noise-emit-shaders", description=(__doc__ or "").split("\n\n")[0])
    parser.parse_args(argv)
    _logging.basicConfig(level=_logging.INFO, format="%(message)s")
    try:
        emit(default_naga())
    except PartialWrite as exc:
        print(f"emit-shaders: stopped part way: {exc}", file=sys.stderr)
        return 1
    except EmitError as exc:
        print(f"emit-shaders: refused, nothing written: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
