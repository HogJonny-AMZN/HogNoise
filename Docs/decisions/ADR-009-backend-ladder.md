# ADR-009: One backend ladder, with explicit override, gating and sunset

**Date**: 2026-09-13
**Status:** Accepted — Decided — implemented in fast-track phase F1 (Docs/PYTHON_UPGRADE_AND_FASTNOISE.md, D9)

## Context

Several capabilities in this codebase have the same shape: a base implementation that always
works, faster implementations layered above it, and a rule for which one runs. Noise (ADR-007),
`hog_color`'s numexpr dispatch, and soon the renderer (a wgpu port beside PyOpenGL). Before this
decision each grew its own env var, its own log line and its own "remove this later" comment, and
the hot paths guarded the fast path with `hasattr(signal, "sample_points")`, which was always true
because `BaseSignal` defines the method, so a signal on the slow path was invisible until a
profiler found it.

## Decision

`large_worlds/backends.py`, standard library only, so any package can register against it.

```python
@dataclasses.dataclass(frozen=True)
class Backend:
    capability: str          # "noise"; later "noise_grid", "render"
    name: str                # "numba", "fastnoiselite", "numpy", "legacy_numpy"
    priority: int            # higher wins; negative = legacy rung, override only
    is_available: Callable[[], bool]
    factory: Callable[..., Any]
    python_max: tuple[int, int] | None = None   # not attempted above this interpreter
    sunset: str | None = None                   # "remove when requires-python >= 3.13"
    note: str = ""
```

Selection (`backends.select(capability)`), in order:

1. `LARGE_WORLDS_<CAPABILITY>_BACKEND=<name>` forces a backend. If it is unavailable the call
   raises `BackendUnavailable` with the reason. An explicit request never falls through silently.
2. Otherwise the highest-priority backend whose `is_available()` is true and whose `python_max`
   admits the running interpreter. Negative-priority backends are skipped here.
3. `Selection.describe()` is one log line: chosen backend, why, and every skipped rung with its
   reason. `World.setup_progressive_generation()` logs it per signal.

Gating:

- Version gates live in `python_max` or inside `is_available`, not in scattered `if`s.
- `is_dcc_host()` names the host DCC for logging and tests, never for selection. A DCC gets the
  same ladder as the tool; only availability differs.
- Every backend with a `sunset` string naming a Python floor is checked by
  `tests/test_backends.py::test_sunset_has_not_passed` against `pyproject.toml`. When the floor
  crosses the named version the test fails and its message is the removal checklist. A skip on
  that test is a review block.

`BaseSignal.supports_batch` replaces the `hasattr` guards: a property that is true only when
`sample_points` is actually overridden. The hot paths in `core.py` and `bins/bin.py` branch on
it, and world setup logs any signal that lands on the per-point path.

## Consequences

- One place to look for "which implementation is running and why", the same answer in a DCC and
  in the tool.
- Legacy code announces its own expiry. The first carrier is the `legacy_numpy` noise rung, whose
  sunset is a human condition ("when nothing regenerates a pre-2026-09 world"), checked by hand.
- `hog_color`'s `_ne_dispatch.py` is not migrated onto this now; it works and has its own tests.
  It becomes a candidate the next time it is touched.
- The renderer backend seam (pre-ADR D8) registers as a capability here when the wgpu spike lands.
