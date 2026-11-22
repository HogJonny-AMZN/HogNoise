# Noise in MaterialX: present HogNoise to it, and respect its own noise through the look-dev chain

**Section:** next
**Owner:** @HogJonny-AMZN
**State:** Queued 2026-11-22 on the owner's ask, after the CI proof's spec; the research has started (facts only, gathered for the survey)
**Cost:** 1 d (the survey; anything it recommends is sized there)
**Verdict:** Good, and well timed: OpenPBR content is MaterialX graphs, so a noise that does not line up with MaterialX's forks a material's look between hosts
**Raised:** [the session journal, 2026-11-22](../../journal/2026-11/2026-11-22-HogJonny-AMZN-0712.md)

The owner, 2026-11-22: "we should research noise in material", "I meant materialX", with two goals:

1. **Present HogNoise's noise to MaterialX**: what it takes to ship HogNoise's features as MaterialX nodes (a nodedef
   and an implementation per code generator, packaged as a library a host loads).
2. **MaterialX's own noise respected in the look-dev chain**: its standard noise nodes (`noise2d`/`noise3d`,
   `fractal3d`, `cellnoise`, `worleynoise`, `unifiednoise`) giving the same look from a DCC viewport to an offline
   render to an engine, our own wgpu renderer included.

One survey, written here: how MaterialX defines and implements each noise node, per generator; how far GLSL and OSL
agree; how a custom node library is shipped and which hosts load one; whether a WGSL or HLSL target exists; and where
HogNoise matches or differs. It ends with options and a recommendation for the owner, not a build. The material schema
is HogShade's (its ADR-009), so HogShade's board links here.
