# Spec: the emitted languages, HLSL, GLSL and SPIR-V from the WGSL by naga

**Status:** Accepted 2026-11-15 (the owner: "all your recommendations make sense to me"), with the six decisions as recommended. Copilot's review on
[PR #26](https://github.com/HogJonny-AMZN/HogNoise/pull/26) then tightened three details, each marked *Amended
2026-11-15*: line endings in the hashes, an accessor for the tables, and the regeneration job's trigger; no decision
changed. Written from
[the GPU fast track](../../design/2026-11-01-gpu-fast-track.md) (Accepted 2026-11-01), its stage 3, after stage 2 landed in
[PR #22](https://github.com/HogJonny-AMZN/HogNoise/pull/22).
**Board:** [`2026-11-01-gpu-fast-track`](../../plan/board/2026-11-01-gpu-fast-track.md)

What gets built, exactly enough that the plan is a list of tasks and a reviewer can check the result against this page. The
design says why; this says what. Where the two disagree, the design's decisions hold and this page is the bug. Its decision
2 is not reopened: **WGSL is the source and naga makes the rest**. Nothing here is written by hand in another language.

The design's stage 3 row: `tools/emit_shaders.py` runs naga to write HLSL, GLSL, Metal and SPIR-V beside the WGSL, shipped
with the package; each file compiles with its own language's compiler in CI, and a drift test fails when they fall behind the
WGSL. Running each emitted file in its own host against the vectors is a later harness, not this stage. This spec keeps that
and corrects one thing the design could not know: **Metal does not come out of naga's command line bindable** (below), so
it is a decision, not a given. The title names the three languages the recommendations ship.

Why it matters now: the owner deferred PyPI until the core deploys "in numpy, WGSL and at least HLSL, maybe GLSL as well"
(the handoff, 2026-11-13). This stage is the last piece of that condition.

## Facts this rests on

Measured on the owner's Windows machine at `989ff6b`, with the naga command line 30.0.1 (`naga --version`) and the Windows
SDK 10.0.18362's `dxc.exe` and `fxc.exe`; not assumed. The commands and their outputs are in the journal entry for this
pull request.

- **The source.** `packages/python/hog-noise/src/hog_noise/wgsl/noise.wgsl`, 74,489 bytes: seven bindings in group 0 and
  five compute entry points (`gpu.ENTRY_POINTS`), each `@workgroup_size(64)`:

  | Binding | WGSL | What a host binds |
  | --- | --- | --- |
  | 0 | `var<uniform> P : Params` | `gpu.pack_params(params)`: 27 scalars, 112 bytes |
  | 1 | `var<storage, read> T : array<f32, 2048>` | the four tables concatenated (`gpu.py:203`), 8 KB |
  | 2, 3, 4 | `var<storage, read> XS, YS, ZS : array<f32>` | the point coordinates, one array per axis |
  | 5 | `var<storage, read_write> OUT : array<f32>` | the output: one float per point, two or three per warp point |
  | 6 | `var<uniform> G : Grid` | `gpu.pack_grid(start, shape, scales)`, `sample_grid` only |

- **naga translates the whole module.** `naga noise.wgsl out.hlsl out.metal out.spv` writes HLSL (133,801 bytes), Metal
  (138,354) and SPIR-V (113,252) with no error, in under a second. GLSL has one entry point per file:
  `naga --entry-point <name> --shader-stage compute --profile core430` writes each (about 119 KB), with no error for any of
  the five, and with `core430`, `core450` and the default `es 310` profiles alike.
- **HLSL compiles in both of Microsoft's compilers.** naga's default HLSL is shader model 5.0 (`--shader-model 50` writes
  the same bytes). Every entry point compiles with `fxc -T cs_5_0` and with `dxc -T cs_6_0`, with warnings only (extraneous
  parentheses around comparisons). The bindings map one to one: `cbuffer P : register(b0)`, `ByteAddressBuffer T :
  register(t1)` through `ZS : register(t4)`, `RWByteAddressBuffer OUT : register(u5)`, `cbuffer G : register(b6)`.
- **GLSL has no binding numbers.** The blocks carry `std140` or `std430` but no `binding =`, and their names are naga's
  (`type_4_block_2Compute`, the variable `_group_0_binding_2_cs`), so a host binds by those names. naga's command line has
  no option for a binding map.
- **Metal is not bindable as written.** Without a binding map every resource in every entry point is `[[user(fake0)]]` (31 of
  them), not `[[buffer(n)]]`, and the kernels take an extra `_mslBufferSizes` argument for `arrayLength`. naga takes a Metal
  binding map only as a library (`naga::back::msl::Options::per_entry_point_map`), not on the command line. So a Metal file
  a host can use needs a small Rust program that calls naga, a Rust toolchain in this repository's CI, or a text rewrite
  of naga's output.
- **No padding.** `Params` and `Grid` are scalars only; naga adds no padding fields to either in HLSL, GLSL or Metal, so
  `pack_params` and `pack_grid` give the bytes every emitted language reads. `gpu.py` imports `wgpu` only inside functions,
  so those two run without the `gpu` extra.
- **Which naga.** The `gpu` extra pins `wgpu>=0.33,<0.34`; `wgpu` 0.33.0 loads wgpu-native 29.0.1.1
  (`wgpu.backends.wgpu_native.__version__`), whose `Cargo.toml` depends on naga 29.0.1. The command line installed here is
  30.0.1. crates.io has naga-cli 29.0.0 to 29.0.4 and 30.0.0 to 30.0.2.
- **Compilers on runners.** This machine has `dxc` and `fxc` (Windows SDK) and no `glslangValidator`, `spirv-val` or Metal
  compiler. Ubuntu's `glslang-tools` and `spirv-tools` packages carry the two; a macOS runner's Xcode carries
  `xcrun metal`. Whether `windows-latest` has `dxc.exe` and `fxc.exe` on a known path is not yet proven for this
  repository (the plan's first task).
- **Where the emitter goes.** The Icebox row
  [`2026-11-13-project-tools-into-an-app`](../../plan/board/2026-11-13-project-tools-into-an-app.md) says HogNoise's own
  tools belong in an app, `apps/hog-noise-tools/`, and that the move is taken "when the GPU port's emitter needs a home".

## The emitter

`emit_shaders.py`, in the app the tools move to (decision 5), with a launcher and a `make shaders` target:

1. Checks that `naga --version` prints the pinned version (decision 2) and refuses otherwise, naming both versions and how
   to install the pinned one (`cargo install naga-cli --version <pin> --locked`).
2. Builds every output in a temporary directory: `noise.hlsl` (whole module), `noise.spv` (whole module), and one GLSL file
   per entry point, `noise.<entry_point>.comp`, at the GLSL profile of decision 4. Then `tables.f32`, the 2,048 table floats
   little-endian, from `tables.py` in `gpu.py`'s order (decision 6). Then `manifest.json`.
3. Refuses before writing anything if naga fails for any file or writes nothing for one (ledger P-13). Only then replaces the
   files in `packages/python/hog-noise/src/hog_noise/shaders/`, each atomically.

`manifest.json`: the WGSL's SHA-256, the naga version, the command line for each file, each file's SHA-256 and size, the
binding table above per language (the HLSL register, the GLSL block and variable name, the SPIR-V set and binding), the
workgroup size, and the dispatch rule (`point_index`: `gid.x + gid.y * 65535 * 64`).

*Amended 2026-11-15 (review):* **one byte form per file on every checkout.** `.gitattributes` says `* text=auto`, so a
Windows checkout has CRLF where Ubuntu has LF (`git ls-files --eol` shows `noise.wgsl` as `i/lf w/crlf` on the owner's
machine), and a hash of the raw bytes would differ between them with no shader changed. So: `.gitattributes` gains
`*.wgsl`, `*.hlsl` and `*.comp` as `text eol=lf` and `*.spv` as `binary` (`*.f32` is binary already); the emitter writes
text with `newline="\n"`; and every hash of a text file, in the emitter and in the drift test alike, is taken over its
bytes with `\r\n` replaced by `\n`, so a checkout that predates the attributes still agrees. Binary files are hashed as
they are.

## The package surface

- **`hog_noise.shaders`**, a new module with no dependencies beyond the standard library:
  `path(language, entry_point=None) -> Path`, `source(language, entry_point=None) -> str | bytes` (bytes for SPIR-V),
  `tables() -> bytes` (the 8,192 bytes of `tables.f32`, for binding 1), `manifest() -> dict`, and
  `LANGUAGES = ("wgsl", "hlsl", "glsl", "spirv")`. An unknown language or entry point raises `ValueError` naming the
  known ones. *Amended 2026-11-15 (review):* the tables have their own accessor; they were promised through `source`,
  which no language in `LANGUAGES` selects.
- **`gpu.pack_params` and `gpu.pack_grid`** become part of the documented surface: they are how a host fills the two
  uniforms. They stay in `gpu.py` (moving them is churn for no reader); the shaders README links them.
- **`shaders/README.md`**, shipped: the binding table per language, the dispatch rule, how to pack the uniforms and the
  tables, and that the files are generated (never edit them; run `make shaders`).
- The wheel grows by about 1 MB (the sizes above, times one HLSL, one SPIR-V and five GLSL files).

## The checks

1. **The drift test** (`test_shaders.py`, in the package's tests, no naga needed): the manifest's WGSL hash equals the
   current `noise.wgsl`'s, each file's hash equals its manifest entry, and `tables.f32` equals the bytes built from
   `tables.py` at test time (so a change to the tables alone fails here, with no naga). Hashes as the manifest section says.
   A failure says to run `make shaders`. Proven to fail once by changing one byte of the WGSL (the golden rule on
   instruments).
2. **The surface test** (same file): every language and entry point `shaders.source` names exists; `shaders.tables()`
   returns 8,192 bytes; an unknown language or entry point raises.
3. **The regeneration job** in CI (Ubuntu), on every push: installs the pinned naga-cli (cached), runs the emitter, and
   fails on `git diff --exit-code`. This catches a hand edit the hashes would not, a shader and its manifest hash edited
   together included, since the hashes are written by the same run. *Amended 2026-11-15 (review):* unconditional; the
   path filter the first draft offered as a fallback would have skipped a change to `tables.py` alone.
4. **The compile jobs** in CI: `fxc -T cs_5_0` and `dxc -T cs_6_0` on every HLSL entry point (Windows);
   `glslangValidator` on each GLSL file and `spirv-val` on `noise.spv` (Ubuntu). Each compiler's version printed in the log.
5. **The emitter's tests** (in the app): a missing or wrong naga version refuses with nothing written; a naga failure on one
   file leaves every committed file byte-identical (P-13).

## Acceptance

1. `make shaders` on the owner's machine with the pinned naga writes the files, and running it twice changes nothing.
2. The five checks above pass in CI on the pull request's head, read with `gh pr checks`, not assumed.
3. A one-byte change to `noise.wgsl` fails the drift test, shown once in the pull request (then reverted).
4. `hog_noise.shaders.source("hlsl")` returns the HLSL in an environment without `wgpu` (`uv run --exact`).

## Not in this

- **Running the emitted files against the vectors** in D3D, OpenGL or Vulkan: the design's later harness. This stage proves
  each file compiles and matches its WGSL, not that a host gets the same numbers. `wgpu` running the WGSL on DirectX 12 and
  Vulkan, which stage 2 already does on WARP and llvmpipe, tests naga's translation at run time, not these files.
- **FastNoiseLite's own HLSL and GLSL** as a cross-check: the design names them, and that is the later harness's job too.
- **Metal**, unless decision 1 says otherwise.
- **PyPI.** The release stays the owner's go.

## Decisions for the owner

Accepted 2026-11-15, each as recommended.

| # | Decision | Recommended | Alternative |
| --- | --- | --- | --- |
| 1 | Which languages | HLSL, GLSL and SPIR-V now; Metal later, its own small row, when someone needs it (on Apple hardware `wgpu` already runs the WGSL through naga) | Metal now, by a small Rust program over the naga library with a binding map (adds a Rust toolchain to CI, about 1 d more); or Metal with naga's fake bindings, which no host can use as written |
| 2 | Which naga | naga-cli 29.0.x, the major the `gpu` extra's wgpu-native runs, so the emitted files come from the translator the rung uses; bumped with the `gpu` extra | The newest naga-cli (30.0.2 today), which drifts from what `wgpu` runs |
| 3 | Where the files live | In the package, `hog_noise/shaders/`, in the wheel (about 1 MB) | Release assets only, which a `pip install` does not bring |
| 4 | Which GLSL | `core430`, the first desktop OpenGL with compute shaders | `core450`; or `es 310` for OpenGL ES 3.1 (WebGL 2 has no compute shaders, so the web is `wgpu`'s) |
| 5 | Where the emitter lives | Take the Icebox move first (0.5 d, its row's own trigger): `apps/hog-noise-tools/` with the generator, the gallery and the emitter | `tools/emit_shaders.py` beside the others, and the move stays iceboxed |
| 6 | The tables | Shipped as `tables.f32` beside the shaders, so a host needs no Python | The host calls Python to build them, or `tables.py` is documented as the source |

## Open risks

- **The Windows runner's compilers.** `dxc.exe` and `fxc.exe` are in the Windows SDK, but their path on `windows-latest`
  is not yet read. The plan's first task is a CI step that only finds and runs both; if either is missing, the step
  installs DXC from its GitHub release, and FXC's check is dropped and the pull request says so.
- **naga 29 versus 30.** Every fact above is from 30.0.1. The plan's first task installs 29.0.x and repeats the
  facts' commands. If 29 differs in what matters here (an error, padding, the binding names), decision 2 comes back to the
  owner with the difference.
- **cargo in CI.** `cargo install naga-cli` builds from source, minutes on a hosted runner, so the binary is cached by the
  version. If that is still too slow, a path filter may narrow the job only if it lists every input and every output:
  `noise.wgsl`, `tables.py`, `gpu.py` (the table order), the emitter, the naga pin, `.gitattributes` and the whole
  `shaders/` directory, manifest included; the plan's task says which, and the owner hears of it.
- **Hand-held hosts.** A host must bind GLSL blocks by naga's generated names. The manifest records them, and a rename in a
  naga bump is caught by the regeneration job's diff.

## Cost

2 to 4 d, the design's estimate, plus 0.5 d if decision 5 takes the move first and about 1 d if decision 1 takes Metal.

## Terms introduced

- **Emitted shader**: a shader file naga writes from `noise.wgsl` (HLSL, GLSL, SPIR-V), shipped in
  `hog_noise/shaders/`, generated by `make shaders` and never edited by hand.
- **Shader manifest**: `hog_noise/shaders/manifest.json`, the record of one emitter run: the WGSL's hash, the naga version,
  each emitted shader's command and hash, and the binding table per language. The drift test reads it.
