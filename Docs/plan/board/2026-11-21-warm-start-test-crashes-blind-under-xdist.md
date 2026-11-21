# The warm-start test crashed once under parallel tests, and hid why

**Section:** icebox
**Owner:** none
**State:** Iceboxed
**Cost:** 0.5 d (keep the child's stderr in the failure, then find the cause: likely two workers writing numba's cache at once)
**Verdict:** Proposed: Good, cheap; a flake that hides its cause will cost more each time it recurs. The owner's to confirm
**Raised:** [the session journal, 2026-11-21](../../journal/2026-11/2026-11-21-HogJonny-AMZN-0543.md)

`packages/python/hog-noise/tests/test_kernels.py::test_warm_start_from_cache_is_fast` failed once in `make check` on
2026-11-21 (Windows, `-n auto`, 3,100 passed beside it). The first subprocess, the one that primes numba's cache, exited
1. The test runs it with `check=True` and `capture_output=True`, so the failure shows the command and not its stderr.
Run alone, it passed in 1.5 s. The first step is to keep the child's output in the assertion message. The likely cause
is another worker compiling into the same numba cache at the same moment; that is a guess, not a measurement. Not built
now because the session was on the GPU records.
