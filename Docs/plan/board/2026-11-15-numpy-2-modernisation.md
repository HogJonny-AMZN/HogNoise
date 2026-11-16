# The numpy rung on modern numpy: the array API, uint32 hashing, free threading

**Section:** icebox
**Owner:** none
**State:** Iceboxed
**Cost:** unsized: three options of very different size, from 1 d to a rewrite; the rung comparison below (0.5 d) sizes them
**Verdict:** Good, later: measure first
**Raised:** [the journal, 2026-11-15](../../journal/2026-11/2026-11-15-HogJonny-AMZN-0551.md)

The owner asked what a numpy 2.5+ port would look like. The constraint first: the package's floor is `numpy>=1.26`
(`packages/python/hog-noise/pyproject.toml`), CI keeps a leg on it (`tests.yml`, *3.11 + numpy 1.26 (floor)*), and DCC
hosts such as Maya ship numpy 1.x. So nothing that needs numpy 2 can replace `vectorized.py`; it is a new rung beside
it, or it waits for a floor bump.

Three options, ranked by what they buy:

| Option | Needs | Cost | Verdict |
| --- | --- | --- | --- |
| **The array API standard.** The numpy kernels written once against the standard numpy 2 implements, so they run unchanged on PyTorch (CUDA, Apple MPS), CuPy and JAX: noise sampled on the caller's own device, no copy | numpy 2, as a new rung | A rewrite, not a port: `vectorized.py` writes through masks in place, and JAX arrays are immutable. 8 to 15 d, unmeasured | The exciting one, and a product decision about the tensor ecosystem rather than about speed. It serves a different user from the `wgpu` rung (ML and simulation code that already holds tensors) |
| **uint32 hashing.** The hash done in uint32, which wraps by itself, viewed as int32 at the end, instead of int64 with a `_wrap32` after each step (150 calls in `vectorized.py`) | Nothing: numpy 1.26 has it | 1 to 2 d, the vectors prove it bit for bit | Good and cheap, and on the path the owner's project runs |
| **Free-threaded Python** (3.13t, 3.14t). The points split across threads with no GIL, near-linear CPU scaling without numba | A free-threaded build of Python and numpy | 1 to 2 d for the chunking, more for CI | Interesting later: numba is the fast CPU rung, and free-threaded builds are still settling |

**Two numpy paths, both maintained.** The owner, 2026-11-15 (on PR #25): HogNoise can and should keep more than one
numpy path; the 1.26 one is what the owner's current project needs, and a 2.5+ one would be future-proofing. So the
1.26 rung, `vectorized.py`, stays and is in use, and a numpy 2.5+ rung would sit beside it, never replace it. That
answers who lands on the numpy rung, which a timing could not. uint32 hashing is worth more for it, since it speeds the
path the owner's project runs; the array API standard would live on the 2.5+ rung.

**First, measure how slow.** `vectorized`, numba, the binding and `wgpu` at one commit, at 1M points: a rung comparison
of about 0.5 d, this row's own first step, which sizes what uint32 hashing and free threading would buy. The
[published benchmarks](2026-11-01-published-benchmarks.md) are different work, evidence for the README's speed claims
against the original libraries, and may share the script without answering this row.
