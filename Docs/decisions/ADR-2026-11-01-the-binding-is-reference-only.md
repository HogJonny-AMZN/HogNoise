# ADR-2026-11-01: The FastNoiseLite binding is the reference, not a rung users land on

**Status:** Accepted (HogJonny-AMZN, 2026-11-01: "we need to make it easy"; chose "same numbers always"). Amends
[ADR-007](ADR-007-noise-kernels-port.md) and [ADR-009](ADR-009-backend-ladder.md), whose ladder put the binding in the middle.

## Context

The ladder chose numba, then the `pyfastnoiselite` binding, then the numpy base. numba and numpy agree bit for bit; the
binding agrees with them only to float32 rounding. So the noise a user got depended on which optional packages happened to be
installed, and the README had to explain a binding most users never asked for.

## Decision

The binding's priority is negative (`-10`): an override-only rung, never chosen automatically, reachable by name
(`make_sampler(params, backend="fastnoiselite")`, `HOG_NOISE_BACKEND_NOISE=fastnoiselite`) and used by the tests as the
reference it has always been. The ladder's wording for a negative-priority rung is now "override-only" rather than "legacy",
since a reference is not legacy. The speed extra is renamed `fast` (it was `jit`).

## Consequences

- Installing numba changes the speed, never the result. A machine without numba gets numpy, not the binding.
- Code that relied on the binding being picked automatically, for its speed over numpy, now gets numpy unless it names the
  binding. Nothing outside the tests did.

## Revisit if

A use case needs the binding's speed without numba and cannot name it explicitly.
