# Trials: the emitted shaders in Unreal, Godot, Blender, O3DE and Maya

**Section:** icebox
**Owner:** none
**State:** Iceboxed
**Cost:** unsized: one trial per host, each its own size; sized when one is pulled forward
**Verdict:** Good as trials: each shows the shaders used where people work, none is a product; Unity declined by the owner
**Raised:** [the session journal, 2026-11-18](../../journal/2026-11/2026-11-18-HogJonny-AMZN-0147.md)
**Waits on:** [the SPIR-V on lavapipe](2026-11-23-the-emitted-spirv-runs-on-lavapipe.md), the last of the CI proof's three pull requests

Each trial loads one [emitted shader](../../../packages/python/hog-noise/src/hog_noise/shaders/README.md) in a real host,
binds it from the manifest, and compares a grid with the vectors. The owner's choice, 2026-11-18: these five, as trials,
not Unity; done when the core is done, after the hardening. The HLSL on WARP, the first of the two this row waited
on, landed in [PR #59](https://github.com/HogJonny-AMZN/HogNoise/pull/59).

- **Unreal**: its shaders are HLSL, so `noise.hlsl` as a global compute shader in a plugin, the seven bindings mapped to
  a shader parameter struct and the tables uploaded as a buffer. The best fit and the most work (C++).
- **Godot** (open source): its compute API takes GLSL and SPIR-V.
- **Blender**: compute from Python, but Blender declares resources its own way, so the naga GLSL is adapted; the current
  API to be checked when the trial is sized.
- **O3DE** (open source): its shader language, AZSL, is HLSL-like.
- **Maya**: the weakest fit, since its shader plugins draw and Python has no general compute; the trial says whether a
  route exists. The numpy package in Maya is a different question and does not wait on this row.

The [CI proof](2026-11-18-emitted-shaders-run-against-the-vectors.md) goes first: a host that disagrees with the vectors
is otherwise a question with two suspects.
