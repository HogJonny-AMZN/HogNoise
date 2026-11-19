# hog-noise-tools

HogNoise's own tools, a workspace app (`Docs/standards/layout.md`). Never published: they read and write the
repository's own folders, so they run from a checkout, which `hog_noise_tools.repo` finds by its marker,
`framework.toml`.

| Script | Module | What it does |
| --- | --- | --- |
| `hog-noise-vectors` | `gen_noise_vectors` | Writes the reference vectors under `vectors/`: the hog set by default, `--set original` from the original libraries |
| `hog-noise-gallery` | `noise_gallery` | Renders `Docs/noise/GALLERY.md` and its sheets; `--check` fails when the committed page is behind |
| `hog-noise-measure-gpu` | `measure_gpu` | `run` measures the wgpu rung on this adapter; `derive` writes the tolerance file from every adapter's record |

Run them with `uv run <script>` from the root, or the launchers in `launchers/`. The GPU measurement needs the `gpu`
group: `uv run --group gpu hog-noise-measure-gpu run`.

`noise_oracle/` is the C++ harness `hog-noise-vectors --set original --source fnl` builds on first use (`build.bat`) for
the domain-warp vectors the FastNoiseLite binding does not expose.

The tests are in `tests/`: `uv run pytest apps/hog-noise-tools`.
