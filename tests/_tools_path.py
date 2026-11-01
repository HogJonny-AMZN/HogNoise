"""
HogNoise: put tools/ on sys.path, for pytest and for a module's own mini-test alike.
Package: tests/_tools_path

Importing this module is the one way a test reaches a script in ``tools/``::

    import _tools_path  # noqa: F401  (puts tools/ on sys.path)

    import check_docs

``tools/`` holds scripts, not an installed package. The dotted spellings -- ``import tools.x`` and
``from tools import x`` -- resolve only under ``python -m pytest``, which prepends the working
directory and makes ``tools`` an implicit namespace package; under the ``pytest`` console script that
CI runs they fail, and a failed import at collection takes down the *whole* suite. #87 shipped the
first spelling and turned ``main`` red.

Why a module rather than ``conftest.py``: a conftest runs only under pytest, and nearly every module
here carries an ``if __name__ == "__main__":`` mini-test that the owner runs directly. Importing this
works under the console script, under ``python -m pytest``, and under ``python tests/test_x.py``,
because ``tests/`` is on ``sys.path`` in all three -- pytest prepends the test file's own directory,
and the interpreter prepends a script's directory.

``tests/test_tools_imports.py`` fails if any test reaches a tool another way.
"""

import sys
from pathlib import Path

_MODULE_NAME = "tests._tools_path"
__version__ = "0.1.0"
__updated__ = "2026-10-04"

TOOLS = Path(__file__).resolve().parents[1] / "tools"

if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
