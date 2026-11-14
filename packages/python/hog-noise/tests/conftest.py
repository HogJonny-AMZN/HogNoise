"""
HogNoise: puts this folder on sys.path, so the tests here import ``hog_noise_repo`` by its bare name.
Package: packages/python/hog-noise/tests/conftest

Under ``--import-mode=importlib`` a test's own folder is not on the path (layout.md, *Tests across members*).
"""

import sys
from pathlib import Path

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
