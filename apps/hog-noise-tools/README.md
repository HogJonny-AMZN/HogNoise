# hog-noise-tools

HogNoise's own tools, a workspace app (`Docs/standards/layout.md`). Never published: they read and write the
repository's own folders, so they run from a checkout, which `hog_noise_tools.repo` finds by its marker,
`framework.toml`.

| Script | Module | What it does |
| --- | --- | --- |
| `hog-noise-vectors` | `gen_noise_vectors` | Writes the reference vectors under `vectors/`: the hog set by default, `--set original` from the original libraries |
| `hog-noise-gallery` | `noise_gallery` | Renders `Docs/noise/GALLERY.md` and its sheets; `--check` fails when the committed page is behind |
| `hog-noise-measure-gpu` | `measure_gpu` | `run` measures the wgpu rung on this adapter, on the vectors' points and 65,536 fresh points a case against numpy; `derive` writes the tolerance file from every adapter's record |

Run them with `uv run <script>` from the root, or the launchers in `launchers/`. The GPU measurement needs the `gpu`
group: `uv run --group gpu hog-noise-measure-gpu run`.

`noise_oracle/` is the C++ harness `hog-noise-vectors --set original --source fnl` builds on first use (`build.bat`) for
the domain-warp vectors the FastNoiseLite binding does not expose.

## Hosts

`hog_noise_tools.hosts` runs the emitted shaders the way a host would, written from
[the shaders' README](../../packages/python/hog-noise/src/hog_noise/shaders/README.md) alone, and judges them with
`conformance.check` against `vectors/tolerance/wgpu.json`:

| Host | Runs | Needs |
| --- | --- | --- |
| `spirv-naga` | `noise.spv` through wgpu's SPIR-V front end | the `gpu` group and an adapter |
| `glsl` | the five `noise.<entry_point>.comp` in moderngl | the `hosts` group and an OpenGL 4.3 context |

`uv run --group gpu --group hosts pytest apps/hog-noise-tools/tests/hosts` runs both. A host that is missing skips
with the reason, unless `HOG_NOISE_REQUIRE_HOST` names it (a comma-separated list), which makes the skip a failure.
`HOG_NOISE_HOST_TARGET` is part of the adapter or renderer a host must run on; unset, the target is logged and not
asserted. `HOG_NOISE_GL_BACKEND` names moderngl's context back end; unset, it is `egl` on Linux and the default
elsewhere.

The tests are in `tests/`: `uv run pytest apps/hog-noise-tools`.
