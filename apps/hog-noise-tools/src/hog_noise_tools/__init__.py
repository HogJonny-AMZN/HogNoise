"""
HogNoise tools: the project's own tools, an app member of the workspace, never published.
Package: hog_noise_tools

The reference-vector generator (``hog-noise-vectors``), the gallery (``hog-noise-gallery``) and the GPU measurement
(``hog-noise-measure-gpu``). They read and write the repository's own folders, so they run from a checkout; ``repo``
finds it.
"""

from __future__ import annotations

import logging as _logging

_MODULE_NAME = "hog_noise_tools"
__version__ = "0.1.0"
__updated__ = "2026-11-17"
_LOGGER = _logging.getLogger(_MODULE_NAME)
