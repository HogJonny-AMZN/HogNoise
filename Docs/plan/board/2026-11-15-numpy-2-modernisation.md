# The numpy rung on modern numpy: the array API, uint32 hashing, free threading

**Section:** icebox
**Owner:** none
**State:** Iceboxed
**Cost:** unsized: three options of very different size, from 1 d to a rewrite; the benchmark below sizes them
**Verdict:** Good, later: measure first
**Raised:** [the journal, 2026-11-15](../../journal/2026-11/2026-11-15-HogJonny-AMZN-0551.md)
**Waits on:** [the published benchmarks](2026-11-01-published-benchmarks.md)

The owner asked what a numpy 2.5+ port would look like. The constraint first: the package's floor is `numpy>=1.26`
(`packages/python/hog-noise/pyproject.toml`), CI keeps a leg on it (`tests.yml`, *3.11 + numpy 1.26 (floor)*), and DCC
hosts such as Maya ship numpy 1.x. So nothing that needs numpy 2 can replace `vectorized.py`; it is a new rung beside
it, or it waits for a floor bump.

Three options, ranked by what they buy:

| Option | Needs | Cost | Verdict |
| --- | --- | --- | --- |
| **The array API standard.** The numpy kernels written once against the standard numpy 2 implements, so they run unchanged on PyTorch (CUDA, Apple MPS), CuPy and JAX: noise sampled on the caller's own device, no copy | numpy 2, as a new rung | A rewrite, not a port: `vectorized.py` writes through masks in place, and JAX arrays are immutable. 8 to 15 d, unmeasured | The exciting one, and a product decision about the tensor ecosystem rather than about speed. It serves a different user from the `wgpu` rung (ML and simulation code that already holds tensors) |
| **uint32 hashing.** The hash done in uint32, which wraps by itself, viewed as int32 at the end, instead of int64 with a `_wrap32` after each step (150 calls in `vectorized.py`) | Nothing: numpy 1.26 has it | 1 to 2 d, the vectors prove it bit for bit | Good and cheap, if the numpy rung's speed matters to anyone |
| **Free-threaded Python** (3.13t, 3.14t). The points split across threads with no GIL, near-linear CPU scaling without numba | A free-threaded build of Python and numpy | 1 to 2 d for the chunking, more for CI | Interesting later: numba is the fast CPU rung, and free-threaded builds are still settling |

**First, measure.** What decides all three is who still lands on the numpy rung and how slow it is for them: `vectorized`,
numba, the binding and `wgpu` at one commit, at 1M points. That is the published-benchmarks row's script, so this row
waits on it. If numpy is only the fallback for a machine without numba, the second and third options are polish, and the
first stands or falls on its own as a product question.
