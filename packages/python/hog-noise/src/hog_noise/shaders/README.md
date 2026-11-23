# The emitted shaders

**Status:** Living. Generated files beside a hand-written page: this README and `__init__.py` are the only files here
written by hand.

HogNoise's noise as compute shaders for a host that does not run WGSL: naga's translation of
[`noise.wgsl`](../wgsl/noise.wgsl), the shader the wgpu rung runs, into HLSL, GLSL and SPIR-V. Read them with
`hog_noise.shaders`, which needs no `wgpu` and no GPU (only numpy, the package's one dependency), or take the files
from this folder:

```python
from hog_noise import shaders

hlsl = shaders.source("hlsl")  # str, every entry point
glsl = shaders.source("glsl", "sample_points_3d")  # str, one entry point per file
spirv = shaders.source("spirv")  # bytes
table = shaders.tables()  # the 8,192 bytes binding 1 holds
shaders.path("hlsl")  # where it is on disk
```

## The files

Every file below is written by `make shaders` (`uv run hog-noise-emit-shaders`) with the naga-cli version pinned in
`apps/hog-noise-tools/naga-version.txt`. **Never edit one by hand**: CI regenerates them on every push and fails on any
difference, and the drift tests fail when `noise.wgsl` or `tables.py` changes without a new run.

| File | What it is |
| --- | --- |
| `noise.hlsl` | HLSL, every entry point; compiles in FXC (`cs_5_0`) and DXC (`cs_6_0`) |
| `noise.<entry_point>.comp` | GLSL 4.30 core, one file per entry point; validates in `glslangValidator` |
| `noise.spv` | SPIR-V, every entry point; validates in `spirv-val` |
| `tables.f32` | The lookup tables binding 1 holds, 2,048 float32 little-endian (`hog_noise.tables.binding_table()`) |
| `manifest.json` | The run that wrote them: the naga version, the WGSL's hash, each file's command and hash, the bindings |

Metal is not shipped: naga's command line writes it with placeholder bindings (`[[user(fake0)]]`) no host can bind, and
on Apple hardware `wgpu` already runs the WGSL (the stage 3 spec's decision 1).

## The entry points

`sample_points_3d`, `sample_points_2d`, `sample_grid`, `warp_points_3d`, `warp_points_2d`. Each is
`@workgroup_size(64)`, one invocation per point.

**Dispatch.** `ceil(n / 64)` workgroups along x. Past 65,535 (the most one dimension allows), dispatch 65,535 along x and
`ceil(groups / 65535)` along y: the shader's point index is `gid.x + gid.y * 65535 * 64`, and an invocation past the
output's end returns at once.

**Output** (binding 5): one float per point from the `sample_` entry points; three per point (x, y, z) from
`warp_points_3d` and two (x, y) from `warp_points_2d`, the warped coordinates. `sample_grid` writes its cells x-major:
point `i` is cell `(i / (ny * nz), (i / nz) % ny, i % nz)`.

## The bindings

All in group (descriptor set) 0. The table is `manifest.json`'s `bindings`, which the emitter reads from the files it
wrote, so a naga rename shows in the manifest's diff before it reaches a host.

| Binding | WGSL | Holds | HLSL register | GLSL variable | SPIR-V set, binding | Read by |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | `P` | `Params` uniform (`gpu.pack_params`) | `b0` | `_group_0_binding_0_cs` | 0, 0 | every one |
| 1 | `T` | the tables, 2,048 `f32` (`shaders.tables()`) | `t1` | `_group_0_binding_1_cs` | 0, 1 | every one |
| 2 | `XS` | x per point, `f32` | `t2` | `_group_0_binding_2_cs` | 0, 2 | `sample_points_3d`, `sample_points_2d`, `warp_points_3d`, `warp_points_2d` |
| 3 | `YS` | y per point, `f32` | `t3` | `_group_0_binding_3_cs` | 0, 3 | `sample_points_3d`, `sample_points_2d`, `warp_points_3d`, `warp_points_2d` |
| 4 | `ZS` | z per point, `f32` | `t4` | `_group_0_binding_4_cs` | 0, 4 | `sample_points_3d`, `warp_points_3d` |
| 5 | `OUT` | the output, `f32`, read-write | `u5` | `_group_0_binding_5_cs` | 0, 5 | every one |
| 6 | `G` | `Grid` uniform (`gpu.pack_grid`) | `b6` | `_group_0_binding_6_cs` | 0, 6 | `sample_grid` |

**GLSL binds by name.** naga writes no `binding =` qualifier, so a GLSL host binds each block by its name, and the
names differ per entry point: the variable is the one member of a block naga names, such as
`layout(std140) uniform Params_block_0Compute { Params _group_0_binding_0_cs; };`, and an entry point that does not read
a binding has no block for it. `manifest.json` records every block under `bindings[n].glsl.blocks`, by entry point.
A GL host in a process that also uses `wgpu` makes its own context current before each build and call: wgpu's
OpenGL back end can leave its own context current, and the next program then fails to build.

**An entry point that does not read a binding.** HLSL and SPIR-V declare all seven in every entry point. The wgpu rung
binds a one-float buffer for an unused coordinate and 48 zero bytes for an unused `Grid`; a host can do the same.

## Filling the uniforms

The two uniforms are packed in Python by the functions the wgpu rung uses, which need no `wgpu`:

- `hog_noise.gpu.pack_params(params)`: the `Params` uniform for a `NoiseParams`, 112 bytes, the seed wrapped to a
  signed 32-bit integer.
- `hog_noise.gpu.pack_grid(start, shape, scales)`: the `Grid` uniform for `sample_grid`, 48 bytes: the start cell
  (three `i32`), the shape (three `u32`) and the per-axis scales (three `f32`), padded.

A host with no Python reads the layouts from the `Params` and `Grid` structs at the top of `noise.wgsl`, and binding 1
from `tables.f32`.

## What is proven, and what is not

Proven on every push: each file is what the pinned naga writes from the current `noise.wgsl`, and each compiles or
validates in its own language's tools. Two of them also run, each in a host written from this page alone
(`hog_noise_tools.hosts` in `apps/hog-noise-tools`), and pass every hog case of the
[reference vectors](https://github.com/HogJonny-AMZN/HogNoise/tree/main/vectors) within the wgpu rung's tolerance,
`vectors/tolerance/wgpu.json`, unmodified:

| File | Host | Adapters, on every push |
| --- | --- | --- |
| `noise.spv` | wgpu's SPIR-V front end: naga reads the file back, so no driver consumes it | WARP (D3D12), llvmpipe (Vulkan, and OpenGL beside the GLSL), Apple's paravirtual GPU (Metal) |
| `noise.<entry_point>.comp` | moderngl, OpenGL 4.3 | Mesa llvmpipe through EGL |

On D3D12, Vulkan and OpenGL, `noise.spv` through naga gives the wgpu rung's output bit for bit. On Metal it does not:
`sample_points_3d` differs by up to 3.58e-7 (2026-11-23), within the tolerance.

Not yet run: `noise.hlsl` (D3D11 and D3D12 on WARP), and `noise.spv` read by a Vulkan driver (lavapipe), each its own
pull request.
