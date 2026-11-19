# Testing: HogNoise's additions

**Status:** Living. Extends [testing.md](testing.md): these rules add to it and never weaken it.

## The vectors are the oracle

[`vectors/`](../../vectors/README.md) holds two reference sets as raw float32 and one manifest: `original/`, captured from
the original libraries (`fnl/` from `pyfastnoiselite`, `fns/` from `pyfastnoisesimd`, the domain warp from the C++ harness in
`apps/hog-noise-tools/noise_oracle`), and `hog/`, this package's numpy rendering, which every rendering must match bit for bit. The suite
reads them through `hog_noise.conformance`. An advisory difference past `tight` (or with correlation below 0.99) writes a
comparison sheet under `vectors/reports/` and waits for a human verdict in `accepted.json`; it never fails the build.
**Never loosen a bound or edit a vector to make a test pass.** A kernel change that moves a value fails the hog set until
`uv run hog-noise-vectors` (the hog set) is rerun, and that rerun is a decision the pull request records.
[NOTICE](../../NOTICE) says where each original set came from.

## Generated files are never edited by hand

- `Docs/noise/GALLERY.md` and its sheets come from `uv run hog-noise-gallery`; `apps/hog-noise-tools/tests/test_noise_gallery.py`
  fails when the page falls behind the enums.
- `vectors/manifest.json` and every `.f32` file come from `hog-noise-vectors` (`--set hog` anywhere numpy is;
  `--set original` where the bindings are), which recomputes every digest; `load` refuses a hand-edited file.
- `vectors/portability.md` is rewritten by a full-environment test run (numba and `pyfastnoiselite` both
  installed). A partial run skips the writer on purpose, so a numpy-only run cannot replace the full table with a partial one.
- `vectors/tolerance/wgpu.json`, `vectors/portability-gpu.md` and a GPU record's `record.md` come from
  `hog-noise-measure-gpu derive`, and each GPU adapter's measurement record under `vectors/reports/gpu/<commit>/` from
  `hog-noise-measure-gpu run`.
- Every file in `packages/python/hog-noise/src/hog_noise/shaders/` but `__init__.py` and `README.md` comes from
  `make shaders` (`hog-noise-emit-shaders`), below.

## The emitted shaders

`noise.wgsl` is the source; naga's HLSL, GLSL and SPIR-V of it, `tables.f32` and `manifest.json` are generated. Three
things hold them:

- **The drift tests** (`packages/python/hog-noise/tests/test_shaders.py`, every `tests.yml` leg): the manifest names the
  current WGSL's hash, every file matches its manifest entry, and `tables.f32` is `tables.binding_table()`. Each was seen
  to fail on a one-character change. They fail with "make shaders".
- **The regeneration job** (`shaders.yml`, `regenerate`): on every push it builds the pinned naga-cli, emits, and fails on
  any difference or new file. It catches what the drift tests cannot: a shader edited by hand together with its hash.
- **The compile jobs** (`shaders.yml`, `hlsl` and `glsl-spirv`): `hog-noise-compile-shaders` runs FXC (`cs_5_0`) and DXC
  (`cs_6_0`) on every entry point on Windows, and `glslangValidator` on each GLSL file and `spirv-val` on the SPIR-V on
  Ubuntu.

Regenerating locally needs the pinned naga-cli, the version in `apps/hog-noise-tools/naga-version.txt`; the emitter
refuses any other, with nothing written. **`HOG_NOISE_NAGA`** points at it when the `naga` on `PATH` is another version:
`cargo install naga-cli --version 29.0.2 --locked --root <folder>`, then `HOG_NOISE_NAGA=<folder>/bin/naga make shaders`.
A second run changes nothing. The emitter's own tests (`apps/hog-noise-tools/tests/test_emit_shaders.py`) drive it with
a fake naga, so they need none.

## The environments that must pass

Three, because each catches what the others cannot: Python 3.13 with every extra; Python 3.11 with numpy 1.26 (the library
floor); and numpy alone, with no extras, which proves the package stands on its one runtime dependency. A test that names the
best rung it expects computes it from what is installed (`HAVE_NUMBA`, `_have_fastnoiselite()`).

And two for the `wgpu` rung, each Python 3.13 with the `dev` and `gpu` extras on a software GPU adapter, so CI runs the
GPU tests with no GPU: Windows with Direct3D 12's WARP ("Microsoft Basic Render Driver"), and Ubuntu with Mesa's
llvmpipe Vulkan driver (`mesa-vulkan-drivers`). Both set `HOG_NOISE_REQUIRE_GPU=1`, print the adapter they found, and
after the tests measure the rung with `hog-noise-measure-gpu run`, kept as the run's artifact. The other legs install no `wgpu`,
and their GPU tests skip with the reason.

## The GPU tests

`test_gpu.py` and the `wgpu` tests of `test_package_boundary.py` need `wgpu` and a GPU adapter; without them they skip,
naming why ("wgpu is not installed: install hog-noise[gpu]", "no adapter: ...").

- **`uv run --group gpu pytest`** installs `wgpu` (the root `gpu` group) and runs them. A plain `uv run pytest` does not
  remove a `wgpu` already installed, because `uv run` syncs inexactly; a run without it is
  `uv run --exact pytest`. A later `--group gpu` puts it back.
- **`HOG_NOISE_REQUIRE_GPU=1`** turns those skips into failures, so a leg that loses its adapter cannot go green. The two
  software-adapter legs set it; set it locally to prove a run really used the GPU.
- **`HOG_NOISE_WGPU_ADAPTER`** picks the adapter: the first whose name contains it, ignoring case, instead of wgpu's
  default. On Windows, `HOG_NOISE_WGPU_ADAPTER="Microsoft Basic Render Driver"` runs the suite on WARP beside a real GPU.
  A name that matches nothing is "no adapter", naming the ones found. One device is made per process, so set it before
  the run.
- **The judge is `vectors/tolerance/wgpu.json`**, through `conformance.check(..., tolerance=...)`. Its numbers come only
  from `hog-noise-measure-gpu derive` over the committed record, and `apps/hog-noise-tools/tests/test_measure_gpu.py` recomputes them: a number
  edited by hand fails it. A rule a GPU adapter fails is a measurement finding to record, never a number to loosen in
  the same change ([vectors/README.md](../../vectors/README.md), *Tolerance files*). Re-measuring is
  `uv run --group gpu hog-noise-measure-gpu run` on each local adapter, CI's two records downloaded into the same `vectors/reports/gpu/<commit>/`,
  then `uv run hog-noise-measure-gpu derive vectors/reports/gpu/<commit>`.

What the GPU tests do not show, found while building the rung
([the plan](../superpowers/plans/2026-11-14-gpu-port.md), Tasks 7, 10 and 12):

- **NoiseLookup through any noise but OpenSimplex2 is ported and compared by no hog case**: every `noiselookup` case
  looks up OpenSimplex2.
- **The grid features are judged as discrete.** A `genasgrid` point sits on the lattice, where classic Simplex and
  OpenSimplex2 choose a corner on a tie that float32 and float64 round opposite ways, so a few points jump. The rule
  counts them; it cannot tell a new jump of the same size from those.
- **An adapter's compiler can be wrong.** WARP computed the single domain warp wrongly, and differently from run to run,
  when the shader had the CPU's separate single-warp branch; the shader runs it as the progressive loop with a count of
  one, which is the same arithmetic. A shader change that looks equivalent is not proven until it passes on every adapter, WARP's CI leg among them.
