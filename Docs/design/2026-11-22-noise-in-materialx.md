# Noise in MaterialX: what it defines, how far hosts agree, and where HogNoise fits

**Status:** Accepted 2026-11-22: option C with A first, and the other two decisions as recommended (*Decisions*, below), on the owner's "Go with your best recommendations". A survey; nothing built.
**Board:** [`2026-11-22-noise-in-materialx`](../plan/board/2026-11-22-noise-in-materialx.md)

The owner, 2026-11-22, with two goals: **(1) present HogNoise's noise to MaterialX**, and **(2) MaterialX's own noise
respected in the look-dev chain**, the same look from a DCC viewport to an offline render to an engine, our own wgpu
renderer included. OpenPBR content is MaterialX graphs, so a noise that does not line up forks a material's look
between hosts.

Every fact below was read in the cited source unless it says otherwise. MaterialX is v1.39.5 (released 2026-05-22).
Its noise definitions and `mx_noise.glsl` are byte-identical between that tag and `main` (diffed). Read 2026-11-22.

## What MaterialX defines

**The nodes** (`libraries/stdlib/stdlib_defs.mtlx`, the Standard Nodes spec):

| Node | Inputs, with defaults | Outputs |
| --- | --- | --- |
| `noise2d`, `noise3d` | `amplitude` 1, `pivot` 0, `texcoord` UV0 or `position` Pobject | float, color3/4, vector2/3/4 |
| `fractal2d`, `fractal3d` | `amplitude` 1, `octaves` 3, `lacunarity` 2.0, `diminish` 0.5 | the same set |
| `cellnoise2d`, `cellnoise3d` | the coordinate only | float |
| `worleynoise2d`, `worleynoise3d` | `jitter` 1.0, `style` 0 (distance) or 1 (solid) | float F1, vector2 F1 F2, vector3 F1 F2 F3 |
| `unifiednoise2d`, `unifiednoise3d` | `freq`, `offset`, `jitter`, `outmin`, `outmax`, `clampoutput`, `octaves`, `lacunarity`, `diminish`, `type` (Perlin, cell, Worley, fractal), `style` | float |

**Not in the standard:** simplex or OpenSimplex, value noise, ridged, billow or ping-pong fractals, domain warp, a
seed on any noise node, 4D noise, tiling. Worley's `metric` and `period` are proposals only: PR #2090 moved them
there as "not yet implemented". To scale a noise you transform its coordinate; only `unifiednoise` has a frequency.

**The algorithms are defined by prose.** The spec says "2D Perlin noise" and "Worley noise using centered jitter", with
no hash, gradients or constants. The de facto reference is OSL's `oslnoise.h`: MaterialX's GLSL library says it is a
modified version and that "produced results should be identical", and its MDL library says the same. What they share:

- **Perlin:** classic gradient noise with the quintic fade, 8 gradients in 2D (±1, ±2) and Perlin's cube-edge set in
  3D, scaled by 0.6616 (2D) and 0.9820 (3D), "experimentally calculated"; signed, nominally -1 to 1.
- **The hash:** Bob Jenkins' lookup3, seeded `0xdeadbeef + (len << 2) + 13`. No permutation table and no seed: the
  only input is the coordinate.
- **Fractal:** plain fBm, no per-octave offset and no normalisation (three octaves at 0.5 peak at 1.75 times one).
- **Worley:** the 3 by 3 (or 3 by 3 by 3) cells around the point, the feature point at
  `cell + (cellnoise - 0.5) * jitter + 0.5`, always Euclidean in every node implementation.
- **Unified noise** is a node graph over the others, and its "jitter" differs by branch. In `unifiednoise3d` it rotates
  the domain by `(jitter - 1) * 90000` degrees for Perlin, cell and fractal alike. In `unifiednoise2d` it rotates the
  domain for Perlin and cell only; the fractal branch samples 3D fBm at the unrotated, frequency- and offset-adjusted
  coordinates, with `(jitter - 1) * 90000` as Z (`NG_unifiednoise2d`'s `N_combine_with_jitter`).

## How far the code generators agree

| Target | Where its noise comes from |
| --- | --- |
| `genosl` | **The renderer's own OSL** `noise("snoise")` and `cellnoise()`, plus MaterialX helpers for fBm and Worley |
| `genglsl` | `genglsl/lib/mx_noise.glsl`, MaterialX's port of `oslnoise.h` |
| `genmsl`, `genslang`, ESSL | the GLSL files, by target inheritance |
| `genmdl` | `noise.mdl`, a second hand port; its hash-to-float takes another branch for hashes of 2^31 and above (*our reading of the code*) |

The aim is identical output, but **nothing tests it numerically.** The test suite
(`resources/Materials/TestSuite/stdlib/noise`) renders each language locally and compares them side by side, with
an optional RMS image difference; no golden images are stored. A FLIP-based comparison (PR #2774) closed unmerged.
The proposed HLSL generator (PR #2897) reports "30/31 single-material RMSE under 2 on the 0-255 scale" against GLSL,
which is visual parity, not numeric. No issue reporting a GLSL-against-OSL noise mismatch was found, which is absence
of evidence only. The OSL path depends on the renderer's OSL build, and OSL's CPU code has SIMD paths.

**WGSL and HLSL.** The `WgslShaderGenerator` in v1.39.5 emits GLSL meant for a GLSL to SPIR-V to WGSL path
([issue #2751](https://github.com/AcademySoftwareFoundation/MaterialX/issues/2751)). A native `genwgsl`
([PR #2996](https://github.com/AcademySoftwareFoundation/MaterialX/pull/2996), whose data library is the GLSL put
through naga) and a `genhlsl` ([PR #2897](https://github.com/AcademySoftwareFoundation/MaterialX/pull/2897)) are open. three.js ships a hand port of `mx_noise.glsl` in its node language, which compiles to WGSL
(`src/nodes/materialx/MaterialXNoise.js`).

**OpenPBR specifies no noise.** The word appears nowhere in its spec or reference graphs; noise reaches OpenPBR
content only through the pattern graph feeding its inputs.

## How hosts treat the noise nodes

| Host | What it does | How sure |
| --- | --- | --- |
| USD Hydra Storm | runs MaterialX's shader generation (GLSL, MSL) | read in the code (`hdSt`, `hdMtlx`) |
| Unreal 5.8 (MaterialX 1.39.4) | Interchange turns the nodes into native material expressions. Worley's `jitter` is "unsupported", `style` solid is not, and `fractal2d` is not listed | Epic's documentation |
| Blender (USD export) | Noise Texture exports as `fractal3d`; roughness, distortion and 4D are dropped; Voronoi does not export | the exporter's code |
| Unity | no native import; a third-party exporter maps three Shader Graph noises | its documentation |
| Godot | no MaterialX support (proposal #714, open since 2020) | the proposal |
| Houdini Karma, Maya and Arnold | not established: forum posts only, no vendor documentation | gap |

So the chain already forks. An Unreal import of a Worley node loses its jitter, and Blender's noise is not MaterialX's
noise. Whether Karma and Arnold match Storm is not known.

## HogNoise against MaterialX

**They are different noises.** HogNoise's Perlin is FastNoiseLite's: a seeded hash by prime multiplication
(`PRIME_X = 501125321`, `scalar.py:55`) and its own gradient table, not lookup3 and Perlin's set. A MaterialX
`noise3d` is not a HogNoise Perlin, and nothing in HogNoise reproduces MaterialX's noise today. What HogNoise has that
MaterialX lacks: OpenSimplex2 and 2S, value and cubic value noise, ridged and ping-pong fractals, domain warp, a seed,
cellular distance metrics and return types. What MaterialX has that HogNoise lacks: lookup3 Perlin and cell noise,
centred-jitter Worley, F2 and F3 outputs, the unified node.

**What HogNoise already has that MaterialX does not:** a numeric conformance harness. Every rendering, numpy, numba,
wgpu, and soon the emitted HLSL, GLSL and SPIR-V, is held to committed vectors within a measured tolerance. MaterialX
checks agreement by eye.

## For goal 1: presenting HogNoise to MaterialX

A custom node library is a folder of `.mtlx` files and source, found through `MATERIALX_SEARCH_PATH` (and, under USD,
`PXR_MTLX_PLUGIN_SEARCH_PATHS`). Names are namespaced (`hognoise:opensimplex2`); nodedefs carry `version` and
`isdefaultversion`. There is no package registry.

- **Each target needs its own source.** A node graph runs everywhere but can only combine existing nodes, so
  OpenSimplex2 or another hash needs a source function per language: GLSL (which MSL and Slang inherit), OSL and MDL.
- **GLSL is close to what we have.** MaterialX wants functions, not compute kernels; naga emits entry points, so the
  library needs a function-level GLSL (the noise functions without the dispatch), which the emitter could write.
- **OSL and MDL are new hand ports**, with no naga path and, unless CI runs OSL's `testshade`, no numeric check.
- **Not every host would see it.** Storm runs a GLSL implementation. Unreal documents no way to load a third-party
  pattern library, so a HogNoise node would not survive an Unreal import. Karma and Arnold are not established.

**Node graphs instead of source.** A noise built only from standard-library nodes needs no source per target, so it
would run wherever MaterialX graphs run. Asked by the owner 2026-11-22. Read in v1.39.5's `stdlib_defs.mtlx`:

- **HogNoise's own numbers cannot be built this way, in practice.** FastNoiseLite's hash multiplies 32-bit integers by
  primes with wraparound, then XORs and shifts. The standard library has integer `add`, `subtract`, `floor`, `ceil` and
  `round`, but no integer `multiply` or `modulo`, and no bitwise node (`xor` is the boolean one). A float32 holds
  integers exactly only up to 2^24, so emulating the hash means splitting each word into small limbs and rebuilding XOR
  bit by bit: thousands of nodes per hash, called 8 to 27 times per sample per octave. Not a serious option.
- **HogNoise's algorithms can, with MaterialX's hash.** `cellnoise2d` and `cellnoise3d` are MaterialX's lookup3 hash of an
  integer cell, so they can stand in as the random source. OpenSimplex2's lattice and gradients, value noise, and Worley
  with other distance metrics and returns (F2, F2 minus F1, Manhattan, Chebyshev) are floors, dot products and
  comparisons over a fixed set of cells. That is the same shapes, not HogNoise's numbers.
- **The costs:** graphs have no loops, so each octave count is its own unrolled nodedef; a 3D Worley over 27 cells is
  hundreds of nodes; and a large graph runs slower than the same function as source. Whether Unreal imports such a
  graph depends on whether Interchange maps every node it uses, which is not established.
- **Why it is worth considering:** if HogNoise ports MaterialX's lookup3 under option A, HogNoise can render the same
  algorithms with that hash. The graphs would then have a HogNoise reference to be measured against, like every other
  rendering.

## For goal 2: MaterialX's noise respected through the chain

What it takes is a numeric reference for MaterialX's own noise and a way to hold every renderer to it, which is what
HogNoise is built to do:

- **MaterialX as a third original library**, beside FastNoiseLite and FastNoiseSIMD: its Perlin, cell, fBm and
  Worley ported from `mx_noise.glsl` into numpy and WGSL. **Licences:** `mx_noise.glsl` is Apache-2.0 at the project
  level but keeps OSL's BSD-3-Clause copyright, conditions and disclaimer (its lines 9 to 25), which the Apache licence
  does not replace. The port keeps that whole notice in its source files and in the distribution's licence files
  (sdist and wheel), beside MaterialX's Apache-2.0 notice, and HogNoise's NOTICE names both; naming the source alone
  would not meet the BSD conditions.
- **Oracle vectors captured from MaterialX's own code**, the way the others come from FastNoiseLite's: `mx_noise.glsl` run
  headless (the CI proof's GLSL harness can run it), and the OSL that MaterialX's OSL generator emits for each node, run
  through OSL's `testshade`. That OSL includes MaterialX's own helpers in `genosl/include/mx_funcs.h` (its fBm and
  Worley, which are not in `oslnoise.h`), so the comparison is between the two node implementations, not between GLSL
  and a library that only some of them call. The vectors then say whether GLSL and OSL agree, a number no one has
  published.
- **Every HogNoise rendering held to them**, wgpu included, so our renderer's MaterialX noise matches Storm within a
  measured bound.

## Options

| | Option | Cost | Gives | Does not give |
| --- | --- | --- | --- | --- |
| A | **Goal 2 first**: MaterialX as a third original library, its oracle vectors from its own GLSL and OSL | 3 to 5 d | Our renderer matches Storm, checked; the first numeric GLSL-against-OSL answer; reuses the CI proof's harness | HogNoise's own noises inside MaterialX |
| B | **Goal 1 first**: a `hognoise:` MaterialX library, GLSL first, OSL and MDL later | 2 to 3 d for GLSL; 3 to 5 d more for OSL and MDL | HogNoise's noises in Storm and MaterialXView | Unreal (no custom libraries); a numeric check of OSL unless `testshade` runs |
| C | **Both, A then B** | the two added | Both goals, with B's GLSL and OSL checked by A's machinery | — |
| D | **Neither yet**: keep the survey, revisit at the engine trials | 0 | Nothing now | — |

**Recommended: C, with A first.** A is the better step: it serves the renderer we are building, uses machinery that
exists or is about to, and measures how far MaterialX's own GLSL and OSL agree. That answer decides how much B's OSL
port must match. B's GLSL half follows cheaply; its OSL and MDL halves wait until a host that needs them is named. A
waits on the CI proof's first pull request, which brings the GLSL harness.

B now has two forms. In the first, B's source library is written per target. In the second, B's graphs are built from
standard nodes with MaterialX's hash, wherever a graph is small enough. The choice between them is made after A, when
the lookup3 port exists to measure the graphs against.

**Outward-facing:** offering MaterialX a numeric cross-generator test, or HogNoise's vectors, is an ASWF contribution
and the owner's call. The owner has a contact who works on MaterialX (2026-11-22), and may send them findings later.
What A would give that contact is the measured GLSL-against-OSL agreement of the standard noise nodes, the oracle
vectors that measure it, and the unified-noise branch differences above.

## Decisions

The owner, 2026-11-22: "Go with your best recommendations". Each as recommended:

1. **Option C, with A first.** A waits on the CI proof's first pull request.
2. **Oracle vectors from GLSL and OSL.** The OSL vectors are captured with `testshade` and committed. That run happens
   locally, against an OSL version recorded with the vectors, so CI needs no OSL build: it holds the renderings to the
   committed vectors, as it does for FastNoiseLite.
3. **HogShade's board takes a row pointing here**, since the material schema is HogShade's (its ADR-009). That is a
   pull request in HogShade.

## Not established

How Karma, Arnold, RenderMan and V-Ray evaluate the stdlib noise; which Unreal expressions Interchange emits; whether
any measured GLSL-against-OSL comparison exists; ASWF Slack, mailing lists and TSC minutes were not searched.

## Sources

- MaterialX v1.39.5 and `main`: [`stdlib_defs.mtlx`](https://github.com/AcademySoftwareFoundation/MaterialX/blob/main/libraries/stdlib/stdlib_defs.mtlx),
  [`stdlib_ng.mtlx`](https://github.com/AcademySoftwareFoundation/MaterialX/blob/main/libraries/stdlib/stdlib_ng.mtlx),
  [`mx_noise.glsl`](https://github.com/AcademySoftwareFoundation/MaterialX/blob/main/libraries/stdlib/genglsl/lib/mx_noise.glsl),
  [`genosl`](https://github.com/AcademySoftwareFoundation/MaterialX/tree/main/libraries/stdlib/genosl),
  [`noise.mdl`](https://github.com/AcademySoftwareFoundation/MaterialX/blob/main/source/MaterialXGenMdl/mdl/materialx/noise.mdl),
  [targets](https://github.com/AcademySoftwareFoundation/MaterialX/tree/main/libraries/targets),
  [Standard Nodes](https://github.com/AcademySoftwareFoundation/MaterialX/blob/main/documents/Specification/MaterialX.StandardNodes.md),
  [Proposals](https://github.com/AcademySoftwareFoundation/MaterialX/blob/main/documents/Specification/MaterialX.Proposals.md),
  [Specification](https://github.com/AcademySoftwareFoundation/MaterialX/blob/main/documents/Specification/MaterialX.Specification.md),
  [Shader generation](https://github.com/AcademySoftwareFoundation/MaterialX/blob/main/documents/DeveloperGuide/ShaderGeneration.md),
  [libraries README](https://github.com/AcademySoftwareFoundation/MaterialX/blob/main/libraries/README.md),
  [the noise test suite](https://github.com/AcademySoftwareFoundation/MaterialX/tree/main/resources/Materials/TestSuite/stdlib/noise),
  [`tests_to_html.py`](https://github.com/AcademySoftwareFoundation/MaterialX/blob/main/python/MaterialXTest/tests_to_html.py)
- MaterialX pull requests and issues: [#2090](https://github.com/AcademySoftwareFoundation/MaterialX/pull/2090),
  [#2774](https://github.com/AcademySoftwareFoundation/MaterialX/pull/2774),
  [#2842](https://github.com/AcademySoftwareFoundation/MaterialX/pull/2842),
  [#2897](https://github.com/AcademySoftwareFoundation/MaterialX/pull/2897),
  [#2996](https://github.com/AcademySoftwareFoundation/MaterialX/pull/2996),
  [#2751](https://github.com/AcademySoftwareFoundation/MaterialX/issues/2751),
  [#1201](https://github.com/AcademySoftwareFoundation/MaterialX/issues/1201),
  [#2527](https://github.com/AcademySoftwareFoundation/MaterialX/issues/2527)
- [OSL `oslnoise.h`](https://github.com/AcademySoftwareFoundation/OpenShadingLanguage/blob/main/src/include/OSL/oslnoise.h)
- [OpenPBR](https://github.com/AcademySoftwareFoundation/OpenPBR)
- OpenUSD [`hdSt`](https://github.com/PixarAnimationStudios/OpenUSD/tree/dev/pxr/imaging/hdSt),
  [`usdMtlx/utils.cpp`](https://github.com/PixarAnimationStudios/OpenUSD/blob/dev/pxr/usd/usdMtlx/utils.cpp)
- Unreal: [MaterialX support](https://dev.epicgames.com/documentation/unreal-engine/materialx-support-in-unreal-engine?lang=en-US),
  [importing MaterialX](https://dev.epicgames.com/documentation/unreal-engine/importing-materialx-files-in-unreal-engine?lang=en-US)
- Blender: [`node_shader_tex_noise.cc`](https://github.com/blender/blender/blob/main/source/blender/nodes/shader/nodes/node_shader_tex_noise.cc)
- [Godot proposal #714](https://github.com/godotengine/godot-proposals/issues/714);
  [Needle Engine's MaterialX export](https://engine.needle.tools/docs/how-to-guides/export/materialx.html);
  [three.js `MaterialXNoise.js`](https://github.com/mrdoob/three.js/blob/dev/src/nodes/materialx/MaterialXNoise.js)

## Terms introduced

None. "Original library", "oracle vectors" and "rendering" are the glossary's; "family" there means a gallery's
parameter set, so this page does not use it for MaterialX's noise.
