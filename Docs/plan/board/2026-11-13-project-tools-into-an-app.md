# HogNoise's own tools out of the framework's tools/, into an app

**Section:** icebox
**Owner:** none
**State:** Iceboxed
**Cost:** 0.5 d (`git mv` of three tools and two tests, an app manifest, two launchers, the paths in the docs)
**Verdict:** Good, later
**Raised:** [PR #18](https://github.com/HogJonny-AMZN/HogNoise/pull/18), its review

[layout.md](../../standards/layout.md) says `tools/` and the root `tests/` are the framework's. HogNoise's own generators
live there all the same: `tools/gen_noise_vectors.py`, `tools/noise_gallery.py` and `tools/noise_oracle/`, with
`tests/test_gen_noise_vectors.py` and `tests/test_noise_gallery.py`. So the boundary check does not read them and no
launcher runs them. The template's 0.7.0 steps say nothing about a project's own tools (a template finding in PR #18).

The move: an app, `apps/hog-noise-tools/`, depending on the `hog-noise` member, with launchers for the generator and the
gallery. Not now: the 0.9.4 update is already a large pull request, nothing is broken by the tools' place, and the
template may answer its finding first. Good, because the GPU port will add a shader emitter that belongs with them.

The template answered in 0.10.1 ([ai-first-template #207](https://github.com/HogJonny-AMZN/ai-first-template/issues/207),
item 3): `updating.md`'s *0.7.0* now says a project's own tools are an app, or wait with a board row as this one does. So
the row stands as written; the move is the template's answer, taken when the GPU port's emitter needs a home.
