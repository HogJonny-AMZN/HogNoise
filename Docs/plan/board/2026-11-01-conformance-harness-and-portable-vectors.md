# A conformance harness other ports can run, and the vectors in a language-neutral format

**Section:** icebox
**Owner:** none
**State:** Iceboxed
**Cost:** 1 to 2 d
**Verdict:** Good, first
**Raised:** [README, Wanted](../../../README.md)

`hog_noise.conformance.check(callable)` runs any sampler against the committed vectors, and the vectors are also exported as
raw arrays with a JSON manifest, so a port in another language (WGSL, HLSL, C#) can validate itself. It turns the vectors
from this package's test data into the reference anyone can use. Not now: publishing comes first.
