"""
Framework: the one logging setup of the template's tools.
Package: tools/log_setup

Each tool calls ``configure(verbose)`` once, in ``main()``, whether or not ``-v`` was given. A tool's report (its
findings, its summary, a usage line) is printed, not logged, so only its diagnostic lines carry this prefix. An App that
takes the tool-root pattern configures its own logging (``python.md``, *The tool-root pattern*); this is for the tools.
"""

from __future__ import annotations

import logging as _logging
import sys

_MODULE_NAME = "tools.log_setup"
__version__ = "0.1.0"
__updated__ = "2026-11-08"
_LOGGER = _logging.getLogger(_MODULE_NAME)

#: The time, the level and the module, as ``init.py`` and the mock App already log.
FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def configure(verbose: bool) -> None:
    """The template's tools' logging: stderr, at INFO with -v and WARNING without, with the time, the level and the
    module. ``basicConfig`` does nothing when the root logger already has a handler (pytest's capture, a second call),
    which is the behaviour the tools had before this helper."""
    _logging.basicConfig(level=_logging.INFO if verbose else _logging.WARNING, format=FORMAT, stream=sys.stderr)
