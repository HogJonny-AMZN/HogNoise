# A grid shape the `Grid` cannot hold is refused in the caller's terms, not as `struct.error`

**Section:** icebox
**Owner:** none
**State:** Iceboxed
**Cost:** 0.1 d (a shape check in `gpu.GpuSampler.sample_grid`, or in `pack_grid`, and its test)
**Verdict:** Minor, but cheap and worth it before PyPI if one is pulled forward: a public caller who passes a negative shape should read their shape, not `struct`'s. Not built in the buffer limit's pull request, whose plan did not name it
**Raised:** [the session journal, 2026-11-25](../../journal/2026-11/2026-11-25-HogJonny-AMZN-0245.md), the deliberate review of [the buffer limit's build](../../superpowers/plans/2026-11-25-a-call-past-the-buffer-limit.md)

`gpu.pack_grid` packs the shape as `u32`, so a `sample_grid` shape with a negative dimension, or one of 2^32 or more,
raises `struct.error: 'I' format requires 0 <= number <= 4294967295` before any GPU work, naming neither the argument nor
the shape. The review probed `(-1, 1, 1)` and `(-5, -5, 1)`. Nothing is uploaded and nothing wrong is returned; only the
message is in the wrong terms. Whether the CPU rungs' `sample_grid` refuses the same shapes, and how, is to be read
before the GPU's message is chosen, so the rungs agree.
