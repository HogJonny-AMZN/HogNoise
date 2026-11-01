"""
HogNoise: one backend ladder for every capability that has a base implementation and faster ones.
Package: hog_noise/backends

A capability ("noise", later "noise_grid", "render") has one or more `Backend` registrations. Each
says what it is, how good it is (priority), whether it can run here (`is_available`), which Pythons
it applies to (`python_max`), and when it is due for removal (`sunset`). `select` picks one.

Selection rules, in order:

1. ``HOG_NOISE_BACKEND_<CAPABILITY>=<name>`` forces a backend. If it is unavailable the call
   raises with the reason; an explicit request never falls through silently.
2. Otherwise the highest-priority available backend whose `python_max` admits the running
   interpreter. Negative-priority backends are legacy rungs: skipped here, reachable only by 1.
3. Every selection can be logged with `describe`, which names what ran and what was skipped and
   why, so the setup log answers "which implementation and why" without a profiler.

Sunset: a backend carrying a `sunset` string is checked by `tests/test_hog_noise/test_backends.py` against the
project's `requires-python`; when the floor crosses the named version the test fails and its
message is the removal checklist. See Docs/PYTHON_UPGRADE_AND_FASTNOISE.md, D9.

This module imports nothing beyond the standard library so any package can register against it.
"""

import dataclasses
import logging as _logging
import os
import sys
from collections.abc import Callable
from typing import Any

_MODULE_NAME = "hog_noise.backends"
__version__ = "0.1.0"
__updated__ = "2026-10-11"
_LOGGER = _logging.getLogger(_MODULE_NAME)

ENV_PREFIX = "HOG_NOISE_BACKEND_"
ENV_SUFFIX = ""


class BackendUnavailable(RuntimeError):
    """An explicitly requested backend cannot run here, or no backend can."""


@dataclasses.dataclass(frozen=True)
class Backend:
    """
    One implementation of a capability.

    :param capability: Capability name, e.g. ``"noise"``.
    :param name: Backend name, unique within the capability, e.g. ``"numba"``.
    :param priority: Higher wins. Negative marks a legacy rung that only an override selects.
    :param is_available: Cheap check that the backend can run in this process. Called at
        selection time, never at registration, so importing optional dependencies stays lazy.
    :param factory: Called by the consumer with whatever arguments the capability defines.
    :param python_max: ``(major, minor)`` above which the backend is not attempted, or ``None``.
    :param sunset: Human sentence naming when this backend is to be removed, or ``None``.
    :param note: One line for the log: what this backend is.
    """

    capability: str
    name: str
    priority: int
    is_available: Callable[[], bool]
    factory: Callable[..., Any]
    python_max: tuple[int, int] | None = None
    sunset: str | None = None
    note: str = ""

    def admits_python(self, version: tuple[int, int] = sys.version_info[:2]) -> bool:
        """Whether `python_max` admits ``version`` (defaults to the running interpreter)."""
        return self.python_max is None or version <= self.python_max


_REGISTRY: dict[str, dict[str, Backend]] = {}


def register(backend: Backend) -> Backend:
    """
    Register a backend. Re-registering the same capability and name replaces it.

    :param backend: The backend.
    :return: The backend, for use as a decorator-free one-liner.
    """
    _REGISTRY.setdefault(backend.capability, {})[backend.name] = backend
    return backend


def registered(capability: str) -> list[Backend]:
    """All backends for ``capability``, highest priority first, then by name."""
    return sorted(_REGISTRY.get(capability, {}).values(), key=lambda b: (-b.priority, b.name))


def clear(capability: str | None = None) -> None:
    """Forget registrations; tests use this. ``None`` clears everything."""
    if capability is None:
        _REGISTRY.clear()
    else:
        _REGISTRY.pop(capability, None)


def env_var_for(capability: str) -> str:
    """The environment variable that forces a backend for ``capability``."""
    return f"{ENV_PREFIX}{capability.upper()}{ENV_SUFFIX}"


def _availability(backend: Backend) -> tuple[bool, str]:
    """(available, reason-if-not). Never raises: an availability probe that throws is 'no'."""
    if not backend.admits_python():
        return (
            False,
            f"python_max={backend.python_max[0]}.{backend.python_max[1]} "
            f"excludes {sys.version_info[0]}.{sys.version_info[1]}",
        )
    try:
        ok = bool(backend.is_available())
    except Exception as e:  # a probe that raises is an unavailable backend, not a crash
        return False, f"availability probe raised {type(e).__name__}: {e}"
    return ok, "" if ok else "is_available() returned False"


@dataclasses.dataclass(frozen=True)
class Selection:
    """What `select` chose and why, for the setup log."""

    capability: str
    backend: Backend
    reason: str
    skipped: tuple[tuple[str, str], ...]  # (name, why) for every backend not chosen

    def describe(self) -> str:
        """One log line: chosen backend, reason, and every skipped rung with its reason."""
        parts = [f"{self.capability}: using '{self.backend.name}' ({self.reason})"]
        if self.backend.note:
            parts.append(self.backend.note)
        for name, why in self.skipped:
            parts.append(f"skipped '{name}': {why}")
        return "; ".join(parts)


def select(capability: str, environ: dict[str, str] | None = None, prefer: str | None = None) -> Selection:
    """
    Choose a backend for ``capability``.

    :param capability: Capability name.
    :param environ: Environment mapping to read the override from; defaults to ``os.environ``.
    :param prefer: A rung the caller would rather have than the ladder's default: chosen when it is
        registered, not legacy and available, else the ladder decides as usual (the skip is logged).
        The environment override still wins over a preference. How an app flips its default.
    :return: The `Selection`.
    :raises BackendUnavailable: If an explicitly requested backend cannot run, or if nothing can.
    :raises KeyError: If nothing is registered for ``capability``.
    """
    backends = registered(capability)
    if not backends:
        raise KeyError(f"No backends registered for capability {capability!r}")
    environ = os.environ if environ is None else environ
    forced = environ.get(env_var_for(capability), "").strip()

    if forced:
        by_name = {b.name: b for b in backends}
        if forced not in by_name:
            raise BackendUnavailable(
                f"{env_var_for(capability)}={forced!r} names no registered {capability} backend; "
                f"registered: {sorted(by_name)}"
            )
        chosen = by_name[forced]
        ok, why = _availability(chosen)
        if not ok:
            raise BackendUnavailable(f"{env_var_for(capability)}={forced!r} requested but unavailable: {why}")
        skipped = tuple((b.name, f"not requested by {env_var_for(capability)}") for b in backends if b is not chosen)
        return Selection(capability, chosen, f"forced by {env_var_for(capability)}", skipped)

    skipped: list[tuple[str, str]] = []
    chosen: Backend | None = None
    if prefer:
        preferred = next((b for b in backends if b.name == prefer), None)
        if preferred is None:
            skipped.append((prefer, "preferred by the app but not registered"))
        elif preferred.priority < 0:
            skipped.append((prefer, "preferred by the app but a legacy rung, override only"))
        else:
            ok, why = _availability(preferred)
            if ok:
                rest = tuple((b.name, "not the app's preference") for b in backends if b is not preferred)
                return Selection(capability, preferred, "preferred by the app", rest)
            skipped.append((prefer, f"preferred by the app but unavailable: {why}"))
    already = {name for name, _ in skipped}  # the preferred rung's reason is the one worth keeping
    for backend in backends:  # highest priority first
        if backend.name in already:
            continue
        if backend.priority < 0:
            skipped.append((backend.name, "legacy rung, override only"))
            continue
        if chosen is not None:
            skipped.append((backend.name, "lower priority"))
            continue
        ok, why = _availability(backend)
        if ok:
            chosen = backend
        else:
            skipped.append((backend.name, why))
    if chosen is None:
        raise BackendUnavailable(f"No {capability} backend is available: " + "; ".join(f"{n}: {w}" for n, w in skipped))
    return Selection(capability, chosen, "highest priority available", tuple(skipped))


def is_dcc_host() -> str | None:
    """
    Name the DCC this process is running inside, if any. For logging and tests, never for selection.

    :return: ``"maya"``, ``"houdini"``, ``"blender"`` or ``None``.
    """
    for module, name in (("maya", "maya"), ("hou", "houdini"), ("bpy", "blender")):
        if module in sys.modules:
            return name
    return None


if __name__ == "__main__":
    _logging.basicConfig(level=_logging.INFO)
    clear("demo")
    register(Backend("demo", "fast", 10, lambda: False, lambda: "fast", note="pretend the fast one is missing"))
    register(Backend("demo", "base", 0, lambda: True, lambda: "base"))
    register(
        Backend("demo", "legacy", -1, lambda: True, lambda: "legacy", sunset="remove when requires-python >= 3.13")
    )
    print(select("demo").describe())
    print(select("demo", {"HOG_NOISE_BACKEND_DEMO": "legacy"}).describe())
    try:
        select("demo", {"HOG_NOISE_BACKEND_DEMO": "fast"})
    except BackendUnavailable as e:
        print("refused:", e)
    print("dcc host:", is_dcc_host())
