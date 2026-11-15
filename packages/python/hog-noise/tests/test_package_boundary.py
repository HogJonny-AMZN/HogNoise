"""
HogNoise: the package stands alone. It imports the standard library, numpy, and the optional extras, nothing else.
Package: packages/python/hog-noise/tests/test_package_boundary

Two checks, because each catches what the other misses:

- a static scan of every module's imports, which sees an import in a branch that never runs here;
- a fresh interpreter that refuses to load the sibling packages this code came from, which sees an import
  built at run time.

Each check is shown to fail on a violation (`test_the_scan_*`, `test_the_blocker_*`), so a pass means the instrument
can say no.
"""

import ast
import os
import subprocess
import sys
import textwrap

import pytest
from hog_noise_repo import MEMBER_ROOT

SRC = MEMBER_ROOT / "src" / "hog_noise"

#: Third-party top-level names the package may import. numba, pyfastnoiselite and PIL are optional extras,
#: each imported behind a guard; numpy is the only hard dependency.
ALLOWED = {"numpy", "numba", "pyfastnoiselite", "PIL", "hog_noise"}

#: Third-party names one module alone may import, on top of ALLOWED: the GPU fast track's wgpu, in gpu.py, behind the
#: override-only rung and only inside its functions.
MODULE_ALLOWED = {"gpu.py": {"wgpu"}}

#: Names this package must never reach: where its code came from, and the graphics stacks.
FORBIDDEN_AT_RUNTIME = (
    "large_worlds",
    "hog_rendering",
    "hog_color",
    "hog_color_ui",
    "hog_wild",
    "PySide6",
    "wgpu",
    "OpenGL",
)


def imported_top_levels(source: str) -> set[str]:
    """Every top-level module name a source imports, wherever in the file the import sits."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


def foreign(source: str, allowed: set[str] = frozenset()) -> set[str]:
    """Imports that are neither standard library nor on the allowed list (plus ``allowed``, a module's own)."""
    return {
        n for n in imported_top_levels(source) if n not in sys.stdlib_module_names and n not in ALLOWED | set(allowed)
    }


MODULES = sorted(SRC.glob("*.py"))


def test_the_package_has_modules_to_scan():
    assert len(MODULES) >= 8, MODULES


@pytest.mark.parametrize("module", MODULES, ids=lambda p: p.name)
def test_module_imports_only_the_standard_library_numpy_and_the_extras(module):
    assert foreign(module.read_text(encoding="utf-8"), MODULE_ALLOWED.get(module.name, set())) == set(), module.name


def test_the_scan_flags_a_sibling_package_even_inside_a_function():
    source = "def late():\n    from large_worlds.signals import noise_signal\n    import PySide6.QtCore\n"
    assert foreign(source) == {"large_worlds", "PySide6"}


def test_the_scan_passes_a_clean_module():
    assert foreign("import logging\nimport numpy as np\nfrom hog_noise import scalar\n") == set()


_BLOCKED_IMPORT = textwrap.dedent(
    """
    import importlib.abc
    import sys

    FORBIDDEN = {forbidden!r}

    class Refuse(importlib.abc.MetaPathFinder):
        def find_spec(self, name, path=None, target=None):
            if name.split(".")[0] in FORBIDDEN:
                raise ImportError("refused: " + name)
            return None

    sys.meta_path.insert(0, Refuse())
    {extra}
    import hog_noise
    leaked = sorted(m for m in sys.modules if m.split(".")[0] in FORBIDDEN)
    print("leaked=" + ",".join(leaked))
    print("ladder=" + hog_noise.make_sampler(hog_noise.NoiseParams())[1].backend.name)
    """
)


def _run_blocked(extra: str = "") -> subprocess.CompletedProcess:
    code = _BLOCKED_IMPORT.format(forbidden=FORBIDDEN_AT_RUNTIME, extra=extra)
    return subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True)


def test_importing_and_sampling_works_with_the_sibling_packages_refused():
    result = _run_blocked()
    assert result.returncode == 0, result.stderr
    assert "leaked=\n" in result.stdout or result.stdout.startswith("leaked=\n"), result.stdout
    assert "ladder=" in result.stdout


def test_the_blocker_would_stop_a_real_import():
    """The instrument can produce the other answer: with the finder in place, importing a forbidden name fails."""
    result = _run_blocked(extra="import large_worlds")
    assert result.returncode != 0
    assert "refused: large_worlds" in result.stderr


def test_wgpu_is_allowed_in_gpu_py_alone():
    source = "def device():\n    import wgpu\n"
    assert foreign(source) == {"wgpu"}, "any other module importing wgpu fails the scan"
    assert foreign(source, MODULE_ALLOWED["gpu.py"]) == set()


def test_gpu_py_imports_wgpu_only_inside_functions():
    tree = ast.parse((SRC / "gpu.py").read_text(encoding="utf-8"))
    top = imported_top_levels(
        ast.unparse(
            ast.Module(body=[n for n in tree.body if isinstance(n, ast.Import | ast.ImportFrom)], type_ignores=[])
        )
    )
    assert "wgpu" not in top


def test_asking_for_the_wgpu_rung_with_wgpu_refused_names_the_cause():
    """Acceptance 4: BackendUnavailable naming the extra, not an ImportError traceback."""
    code = _BLOCKED_IMPORT.format(forbidden=FORBIDDEN_AT_RUNTIME, extra="") + textwrap.dedent(
        """
        from hog_noise.backends import BackendUnavailable
        try:
            hog_noise.make_sampler(hog_noise.NoiseParams(), backend="wgpu")
        except BackendUnavailable as e:
            print("refused=" + str(e))
        """
    )
    result = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "refused=" in result.stdout and "wgpu is not installed: install hog-noise[gpu]" in result.stdout, (
        result.stdout
    )


def test_with_wgpu_installed_the_default_ladder_never_loads_it():
    """Acceptance 4, the other half; the second line proves the probe can see wgpu load."""
    try:
        import wgpu  # noqa: F401
    except ImportError:
        if os.environ.get("HOG_NOISE_REQUIRE_GPU") == "1":
            pytest.fail("HOG_NOISE_REQUIRE_GPU=1, but wgpu is not installed")
        pytest.skip("wgpu is not installed here (the gpu extra)")
    code = (
        "import sys, hog_noise\n"
        "hog_noise.make_sampler(hog_noise.NoiseParams())[0].sample(1.0, 2.0)\n"
        "print('wgpu' in sys.modules)\n"
        "from hog_noise import gpu\n"
        "gpu._wgpu()\n"
        "print('wgpu' in sys.modules)\n"
    )
    result = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["False", "True"], result.stdout
