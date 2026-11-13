"""
Tests for hog_noise.backends: selection order, the env override, override-only rungs, sunset strings.
"""

import re
import sys

import pytest
from hog_noise_repo import MEMBER_ROOT

from hog_noise import backends
from hog_noise.backends import Backend, BackendUnavailable, env_var_for, is_dcc_host

CAP = "test_cap"


@pytest.fixture(autouse=True)
def _clean_registry():
    backends.clear(CAP)
    yield
    backends.clear(CAP)


def _reg(name, priority, available=True, python_max=None, sunset=None):
    return backends.register(
        Backend(CAP, name, priority, (lambda: available), (lambda: name), python_max=python_max, sunset=sunset)
    )


def test_highest_available_priority_wins():
    _reg("fast", 10, available=False)
    _reg("mid", 5)
    _reg("base", 0)
    sel = backends.select(CAP, environ={})
    assert sel.backend.name == "mid"
    assert dict(sel.skipped) == {"fast": "is_available() returned False", "base": "lower priority"}


def test_registered_is_sorted_by_priority_then_name():
    _reg("b", 1)
    _reg("a", 1)
    _reg("z", 9)
    assert [b.name for b in backends.registered(CAP)] == ["z", "a", "b"]


def test_legacy_rung_is_never_chosen_by_default():
    _reg("legacy", -1)
    _reg("base", 0)
    sel = backends.select(CAP, environ={})
    assert sel.backend.name == "base"
    assert ("legacy", "override-only rung") in sel.skipped


def test_override_selects_a_legacy_rung():
    _reg("legacy", -1)
    _reg("base", 0)
    sel = backends.select(CAP, environ={env_var_for(CAP): "legacy"})
    assert sel.backend.name == "legacy"
    assert "forced" in sel.reason


def test_override_of_an_unavailable_backend_raises_instead_of_falling_through():
    _reg("fast", 10, available=False)
    _reg("base", 0)
    with pytest.raises(BackendUnavailable, match="requested but unavailable"):
        backends.select(CAP, environ={env_var_for(CAP): "fast"})


def test_override_of_an_unknown_name_raises_and_lists_the_options():
    _reg("base", 0)
    with pytest.raises(BackendUnavailable, match=r"names no registered .*\['base'\]"):
        backends.select(CAP, environ={env_var_for(CAP): "nope"})


def test_python_max_excludes_newer_interpreters():
    here = sys.version_info[:2]
    older = (here[0], here[1] - 1)
    _reg("old_only", 10, python_max=older)
    _reg("base", 0)
    sel = backends.select(CAP, environ={})
    assert sel.backend.name == "base"
    assert any(name == "old_only" and "python_max" in why for name, why in sel.skipped)


def test_a_probe_that_raises_counts_as_unavailable():
    def boom():
        raise RuntimeError("driver missing")

    backends.register(Backend(CAP, "gpu", 10, boom, lambda: "gpu"))
    _reg("base", 0)
    sel = backends.select(CAP, environ={})
    assert sel.backend.name == "base"
    assert ("gpu", "availability probe raised RuntimeError: driver missing") in sel.skipped


def test_nothing_available_raises_with_every_reason():
    _reg("a", 2, available=False)
    _reg("b", 1, available=False)
    with pytest.raises(BackendUnavailable, match="a: is_available.*b: is_available"):
        backends.select(CAP, environ={})


def test_unregistered_capability_is_a_key_error():
    with pytest.raises(KeyError):
        backends.select("never_registered", environ={})


def test_describe_names_the_choice_and_every_skip():
    _reg("fast", 10, available=False)
    _reg("base", 0)
    line = backends.select(CAP, environ={}).describe()
    assert line.startswith(f"{CAP}: using 'base' (highest priority available)")
    assert "skipped 'fast': is_available() returned False" in line


def test_env_var_name_is_upper_cased_capability():
    assert env_var_for("noise") == "HOG_NOISE_BACKEND_NOISE"


def test_is_dcc_host_is_none_under_pytest():
    assert is_dcc_host() is None


# -------------------------------------------------------------------------
# Sunset: every registered backend that names a Python floor in its sunset string is checked
# against pyproject.toml's requires-python. The failure message is the removal checklist (D9).
_PYPROJECT = MEMBER_ROOT / "pyproject.toml"


def _requires_python_floor():
    text = _PYPROJECT.read_text(encoding="utf-8")
    m = re.search(r'requires-python\s*=\s*"[^"]*>=\s*(\d+)\.(\d+)', text)
    assert m, "requires-python with a >= floor not found in pyproject.toml"
    return int(m.group(1)), int(m.group(2))


def _all_real_backends():
    import hog_noise  # noqa: F401  registers the noise ladder

    return [b for cap in list(backends._REGISTRY) if cap != CAP for b in backends.registered(cap)]


@pytest.mark.parametrize("backend", _all_real_backends(), ids=lambda b: f"{b.capability}:{b.name}")
def test_sunset_has_not_passed(backend):
    """
    A backend whose sunset names 'requires-python >= X.Y' must be removed once the floor is X.Y.

    When this fails, the fix is the removal PR: delete the backend module and its registration,
    its vectors and its rows in Docs/PYTHON_UPGRADE_AND_FASTNOISE.md. Do not skip this test.
    """
    if not backend.sunset:
        pytest.skip("no sunset declared")
    m = re.search(r"requires-python\s*>=\s*(\d+)\.(\d+)", backend.sunset)
    if not m:
        pytest.skip(f"sunset is a human condition, not a Python floor: {backend.sunset!r}")
    named = (int(m.group(1)), int(m.group(2)))
    floor = _requires_python_floor()
    assert floor < named, (
        f"SUNSET: {backend.capability}:{backend.name} was to be removed when requires-python >= "
        f"{named[0]}.{named[1]}; the floor is now {floor[0]}.{floor[1]}. Remove the backend, its "
        f"registration, its vectors and its documentation rows."
    )


def test_the_sunset_check_would_fire():
    """The instrument can produce the other answer: a sunset already behind the floor fails."""
    floor = _requires_python_floor()
    past = Backend(
        CAP, "expired", -1, lambda: True, lambda: None, sunset=f"remove when requires-python >= {floor[0]}.{floor[1]}"
    )
    m = re.search(r"requires-python\s*>=\s*(\d+)\.(\d+)", past.sunset)
    named = (int(m.group(1)), int(m.group(2)))
    assert not (floor < named), "a sunset equal to the floor must count as passed"


def test_an_app_preference_is_granted_when_available():
    """How an app flips its default without forcing it on every process (the wgpu viewport flip)."""
    _reg("fast", 10)
    _reg("new", 5)
    sel = backends.select(CAP, environ={}, prefer="new")
    assert sel.backend.name == "new" and sel.reason == "preferred by the app"
    assert dict(sel.skipped) == {"fast": "not the app's preference"}


def test_an_unavailable_preference_falls_back_with_the_reason():
    _reg("fast", 10)
    _reg("new", 5, available=False)
    sel = backends.select(CAP, environ={}, prefer="new")
    assert sel.backend.name == "fast"
    assert dict(sel.skipped)["new"] == "preferred by the app but unavailable: is_available() returned False"
    sel = backends.select(CAP, environ={}, prefer="nope")
    assert sel.backend.name == "fast" and dict(sel.skipped)["nope"] == "preferred by the app but not registered"


def test_a_preference_never_picks_a_legacy_rung_and_the_override_beats_it():
    _reg("legacy", -1)
    _reg("base", 0)
    sel = backends.select(CAP, environ={}, prefer="legacy")
    assert sel.backend.name == "base"
    assert dict(sel.skipped)["legacy"] == "preferred by the app but an override-only rung"
    sel = backends.select(CAP, environ={env_var_for(CAP): "legacy"}, prefer="base")
    assert sel.backend.name == "legacy" and "forced" in sel.reason
