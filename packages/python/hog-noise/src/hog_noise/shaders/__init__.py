"""
HogNoise: the emitted shaders, naga's HLSL, GLSL and SPIR-V of ``noise.wgsl``, and the tables a host binds.
Package: hog_noise.shaders

Every file here except this module and ``README.md`` is written by ``make shaders`` (the app's ``emit_shaders.py``) and
never edited by hand; ``manifest.json`` records the run. This module imports the standard library only, so reading a
shader needs no ``wgpu``; importing it runs the package's ``__init__``, which imports numpy. ``sha256`` is the one hash
the emitter and the drift test share, so a Windows checkout (CRLF) and an Ubuntu one (LF) agree.
"""

from __future__ import annotations

import hashlib
import importlib.resources
import json
import logging as _logging
from pathlib import Path
from typing import Any

_MODULE_NAME = "hog_noise.shaders"
__version__ = "0.1.0"
__updated__ = "2026-11-18"
_LOGGER = _logging.getLogger(_MODULE_NAME)

LANGUAGES = ("wgsl", "hlsl", "glsl", "spirv")
#: The compute entry points of noise.wgsl; ``gpu.ENTRY_POINTS`` holds the same, and a test holds them level.
ENTRY_POINTS = ("sample_points_3d", "sample_points_2d", "sample_grid", "warp_points_3d", "warp_points_2d")
TABLES_FILE = "tables.f32"
TABLES_BYTES = 2048 * 4
MANIFEST_FILE = "manifest.json"
#: The whole-module files; GLSL is one file per entry point, ``noise.<entry_point>.comp``.
_WHOLE = {"hlsl": "noise.hlsl", "spirv": "noise.spv"}


def file_name(language: str, entry_point: str | None = None) -> str:
    """The emitted file's name for ``language`` (and, for GLSL, the entry point).

    :raises ValueError: An unknown language or entry point, naming the known ones; GLSL without an entry point; an
        entry point for a language that is one file for every entry point.
    """
    if language not in LANGUAGES:
        raise ValueError(f"unknown shader language {language!r}; known: {', '.join(LANGUAGES)}")
    if language == "glsl":
        if entry_point not in ENTRY_POINTS:
            raise ValueError(f"GLSL is one file per entry point; pass one of: {', '.join(ENTRY_POINTS)}")
        return f"noise.{entry_point}.comp"
    if entry_point is not None:
        raise ValueError(f"{language} is one file for every entry point; pass no entry_point")
    return "noise.wgsl" if language == "wgsl" else _WHOLE[language]


def path(language: str, entry_point: str | None = None) -> Path:
    """Where the shader is on disk. WGSL is the source, in ``hog_noise/wgsl/``; the rest are here."""
    name = file_name(language, entry_point)
    folder = importlib.resources.files("hog_noise") / ("wgsl" if language == "wgsl" else "shaders")
    return Path(str(folder / name))


def source(language: str, entry_point: str | None = None) -> str | bytes:
    """The shader: text, or bytes for SPIR-V."""
    p = path(language, entry_point)
    return p.read_bytes() if language == "spirv" else p.read_text(encoding="utf-8")


def tables() -> bytes:
    """The 8,192 bytes a host binds at binding 1: the four tables, float32 little-endian (``tables.binding_table``).

    :raises ValueError: When the file is not 8,192 bytes, which the drift test makes impossible on a checkout.
    """
    data = (importlib.resources.files("hog_noise") / "shaders" / TABLES_FILE).read_bytes()
    if len(data) != TABLES_BYTES:
        raise ValueError(f"{TABLES_FILE} is {len(data)} bytes, not {TABLES_BYTES}: run make shaders")
    return data


def manifest() -> dict[str, Any]:
    """The record of the emitter run that wrote these files (the glossary's *Shader manifest*)."""
    return json.loads((importlib.resources.files("hog_noise") / "shaders" / MANIFEST_FILE).read_text(encoding="utf-8"))


def sha256(data: bytes, *, text: bool) -> str:
    """The SHA-256 the manifest records: of a text file's bytes with CRLF made LF, or of a binary file as it is."""
    return hashlib.sha256(data.replace(b"\r\n", b"\n") if text else data).hexdigest()


if __name__ == "__main__":
    for lang in LANGUAGES:
        for ep in ENTRY_POINTS if lang == "glsl" else (None,):
            print(f"{lang:6} {ep or '':18} {path(lang, ep)}")
