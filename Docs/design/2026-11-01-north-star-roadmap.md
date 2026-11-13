# The north star, and the roadmap to it

**Status:** Proposed. The owner's intent, 2026-11-01, written down for the owner to lock: FastNoise2 parity, 4D, a GPU path,
and equivalent shader versions (HLSL, WGSL and the rest), byte-identical on the CPU and loose on the GPU.
**Board:** [`2026-11-01-g2-lock-the-north-star-roadmap`](../plan/board/2026-11-01-g2-lock-the-north-star-roadmap.md)

## The north star

The owner, 2026-11-01: *"this needs to be a all-in-one silo, the best most modern version of a fastnoise for all use cases
cpu and gpu."* HogNoise is one self-contained repository and one package: the algorithms, every rendering of them, the
shaders, the vectors that prove them and the tools that make them, with no dependency on any other project. It serves every
use case from that one place: a Python library, a DCC host such as Maya, a game engine or web page that takes the shaders, and
a port in another language that takes the vectors.

It is done, in the sense of this document, when all of these are true at once:

1. **FastNoise2 parity.** Every node FastNoise2 has exists in HogNoise, with the same parameters, in 2D, 3D and 4D, and
   matches FastNoise2's own output where FastNoise2 is the reference.
2. **One graph, many renderings.** A noise is a graph of nodes (as in FastNoise2) and the same graph runs on every rendering:
   numba, numpy, and the GPU through WGSL, HLSL, GLSL and Metal.
3. **A stated contract per rendering.** The CPU renderings are **bit-identical** to each other, as numba and numpy are today.
   The GPU renderings are **loose**: within a tolerance written down per node and checked against the same vectors.
4. **Anyone can check a port.** The vectors are published in a language-neutral form with a harness, so a port in another
   language proves itself the way HogNoise does.
5. **Beyond the edge** stays an open slot: whatever no reference library has, verified by properties, not by vectors.

## Where it starts from

- **Today:** the FastNoiseLite and FastNoiseSIMD algorithms, 2D and 3D, one flat `NoiseParams` record, three CPU renderings,
  208 comparisons against the originals (75 bit-identical, the rest within float32 rounding).
- **The GPU path is proven, not built.** The source project's wgpu spike (2026-09-19) ran a hash-based value noise in a WGSL
  compute pass and read it back against a numpy twin with the same `u32` arithmetic: a worst difference of 4.6e-5 on an
  amplitude of 60 (about 1e-6 relative), on an RTX 5090. That is the evidence that integer hashing makes "loose on the GPU" a
  tight tolerance. It was a toy noise in a spike, not the algorithms.
- **FastNoise2, as its headers stand** (`master`, pushed 2026-10-28): about 50 node types.
  - Generators: Constant, White, Checkerboard, SineWave, Gradient, DistanceToPoint, Value, Perlin, Simplex, SuperSimplex,
    CellularValue, CellularDistance, CellularLookup.
  - Fractals: FBm, Ridged (PingPong is a modifier there).
  - Domain warp: Gradient, Simplex, SuperSimplex, and the progressive and independent fractal warps.
  - Blends: Add, Subtract, Multiply, Divide, Modulus, Min, Max, MinSmooth, MaxSmooth, Fade, PowFloat, PowInt.
  - Modifiers: DomainScale, DomainOffset, DomainRotate, DomainRotatePlane, DomainAxisScale, SeedOffset, Remap, Terrace,
    Abs, SignedSquareRoot, PingPong, ConvertRGBA8, AddDimension, RemoveDimension, GeneratorCache.
  - Cellular distances add MaxAxis and Minkowski to the four HogNoise has; returns are indexed.
  - Generation: single points, position arrays and uniform grids in 2D, 3D and 4D, and tileable 2D.
  - **Any parameter can be another node** (a "hybrid source"), and a graph serialises to an encoded string its node editor
    writes. That is the architectural gap: FastNoise2 is a graph, HogNoise is a record.

## The roadmap

Each stage has its oracle, because a stage nobody can check is not done. Costs are estimates, in working days.

| Stage | What | How it is checked | Cost |
| --- | --- | --- | --- |
| 0 | **Publish** (gate G1) | the gate, CI on the forge | done but for the owner's go |
| 1 | **The conformance harness and portable vectors**: `check(callable)` against every vector; the vectors exported as raw arrays with a JSON manifest | it passes on all three CPU renderings, and fails on a deliberately broken one | 1 to 2 |
| 2 | **The node graph core**: nodes, typed inputs where any input is a constant or another node, evaluation that renders a graph through any rendering, a serialised graph format. `NoiseParams` stays as a front end that builds a graph, so nothing that works today breaks | every existing vector, run through the graph | 5 to 8 |
| 3 | **A FastNoise2 oracle**: a C++ harness over FastNoise2, built like the existing FastNoiseLite one, writing vectors per node | the harness reproduces FastNoise2's own sample outputs | 1 to 2 |
| 4 | **FastNoise2 parity, 2D and 3D**: every node above, one family at a time (generators, then blends and modifiers, then warps and cellular) | each node against the stage 3 vectors | 15 to 25 |
| 5 | **4D**, across every node that has it, and **tileable 2D** | FastNoise2's 4D vectors; periodicity for tileable | 5 to 10 |
| 6 | **The GPU, WGSL first**: the graph compiled to a WGSL compute shader and run through wgpu, as a `noise_grid` rung on the ladder | every vector, within the tolerance contract, on a real adapter and on CI's software adapter | 10 to 15 |
| 7 | **The other shader languages**: HLSL, GLSL, Metal and SPIR-V generated from the WGSL by naga, wgpu's translator (decided 2026-11-01; Slang was the earlier proposal) | the emitted files compile with each language's own compiler in CI, with a drift test against the WGSL; running the WGSL on wgpu's back ends tests wgpu's translation, not the emitted files, so executing each emitted file in its own host is a separate, later harness | 2 to 4 |
| 8 | **Correctness far from the origin**: an integer lattice or float64 coordinates, so that large worlds do not break the float32 hashing (on the GPU most of all, which is float32) | vectors at 1e5 to 1e7 units, against float64 | 3 to 5 |
| 9 | **Speed, published**: benchmarks against FastNoise2, FastNoiseLite and the bindings, and the CPU fast paths the numbers ask for | a reproducible script; numbers quoted with their commit | 3 to 5 |

Roughly 55 to 90 working days end to end, so months, not weeks. The order matters more than the total:

- **1 before everything**, because every later stage is proved by it.
- **2 before 4**, because FastNoise2's nodes compose; porting them onto a flat record would mean porting them twice.
- **3 before 4 and 5**, because parity needs FastNoise2's own numbers to compare against.
- **6 after 2**, because a graph compiles to one shader, where a record would need a shader per feature.
- **8 alongside 6**: a GPU rendering that only works near the origin is not a rendering a large world can use.

## The fast track (2026-11-01)

The owner brought the GPU forward: today's noise on wgpu in WGSL first, the other shader languages as its stretch, before the
node graph and FastNoise2 parity. Stages 6 and 7 below are therefore served first by [the GPU fast track](2026-11-01-gpu-fast-track.md),
which ports the current kernels as one shader; when the node graph lands, it calls the same WGSL functions.

## Decisions to lock

1. **What "parity" means for an algorithm both libraries have.** FastNoise2's Simplex is not FastNoiseLite's OpenSimplex2,
   and hashes differ. Proposed: keep both, by name. FastNoiseLite's and FastNoiseSIMD's stay as they are (old seeds keep
   working), and FastNoise2's arrive as their own nodes, matched to FastNoise2.
2. **The GPU tolerance.** Proposed: a per-node bound, defaulting to 1e-5 relative to the node's output range, derived from
   measurement in stage 6, never loosened to make a test pass.
3. **One shader source.** *Decided 2026-11-01:* WGSL is the source and naga, wgpu's translator, emits HLSL, GLSL, Metal and
   SPIR-V from it ([the GPU fast track](2026-11-01-gpu-fast-track.md)). Slang was the earlier proposal.
4. **The graph's serialised form.** Proposed: HogNoise's own JSON, with an importer for FastNoise2's encoded trees as a
   later, separate row.

## Not in this roadmap

A node editor or any user interface (HogNoise is a library). Derivatives and other features no reference library has: they
are beyond the edge, and get their own design when a consumer needs one.

## Terms introduced

- **North star**: the end state this document defines.
- **Rendering**: one way a noise is computed (numba, numpy, WGSL, HLSL, GLSL, Metal); several renderings of one graph must
  agree to their contract.
- **Tolerance contract**: the stated bound a rendering must meet against the vectors; zero for the CPU renderings.
- **Node graph**: a noise as nodes whose inputs are constants or other nodes, as in FastNoise2.
- **Conformance harness**: the published check any implementation runs against the vectors.
