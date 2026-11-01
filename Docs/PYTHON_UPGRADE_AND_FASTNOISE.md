# Python 3.13, FastNoise, numba, and the road to wgpu

**Status:** Superseded by this repository's own README, PROVENANCE.md and ADRs; kept as history, carried from the private project this code was cut from (LargeWorlds). It is that project's Python 3.13, numba and wgpu roadmap. For HogNoise, **section 4 (the noise kernel, specified) is the part that applies**; the rest is context. Names and paths are the source project's; see [README.md](README.md) in this folder.
**Progress (as written):** Pre-ADR. Measured 2026-09-12, execution not started. Each numbered decision in section 3
is a candidate for its own ADR in [decisions/](decisions/); section 5 is the seed of a
superpowers/plans/ document.
**Supersedes:** the SpriteJammer note of 2026-09-08, archived at
.archive/Docs/PYTHON_UPGRADE_AND_FASTNOISE.spritejammer-2026-09-08.md.
That note correctly identified that the Python pin and the wgpu port are one problem. Its proposed
fix was measured here and does not hold up; this document records why and what to do instead.
**Related:** large_worlds/signals/DETAILED_FASTNOISE_PERF.md,
ADR-001, ADR-004,
SpriteJammer ADR-008 and ADR-018 (numba policy there)

---

## 1. Summary

LargeWorlds is pinned to Python 3.9 by one thing: `pyfastnoisesimd` 0.4.2 has no wheel newer than
cp39. That pin blocks `wgpu` (Python >= 3.11) and therefore the renderer modernisation.

Three ways out were measured:

| Option | 4-octave noise, one 4 096-point bin | Verdict |
| --- | --- | --- |
| `pyfastnoiselite` (the SpriteJammer proposal) | 0.45 ms | 7x slower than today, GIL-bound. Fine as a fallback, not as the path |
| `pyfastnoisesimd` rebuilt from source | 0.06 ms | Works on 3.12 and 3.13, bit-identical. Needs us to build and host wheels forever |
| numba kernel, `parallel=True` | 0.05 ms | Matches today's speed, pure Python source, no wheel problem, deterministic |

**Proposed direction, in one line:** develop on Python 3.13 while the library packages support
3.11 through 3.13, the Maya 2026+ range, with legacy paths gated and sunset explicitly; a numba
fBm kernel ported from FastNoiseLite's algorithms as the fast path, `pyfastnoiselite` as the
reference implementation and fallback, `pyfastnoisesimd` removed once its parity vectors are
captured, all behind one backend-ladder pattern; numba adopted as an optional extra under the same discipline
SpriteJammer already uses; the generation library decoupled from the renderer; then wgpu adopted
incrementally with imgui-bundle for overlays.

The public wheel repo that was floated during scoping is **not needed** for this. Section 3, D3
explains why and what would bring it back.

---

## 2. What was measured

All measurements on this workstation (24 logical cores, AVX2, MSVC 2022 Build Tools present).
Scripts and scratch venvs are reproducible from Appendix A. Nothing was installed into the project
`.venv`.

### 2.1 Noise throughput, 4 fractal octaves, simplex

| Workload | FNS 24 thr | FNS 1 thr | numba parallel | numba serial | FastNoiseLite |
| --- | --- | --- | --- | --- | --- |
| One bin, 4 096 pts | 0.06 ms | 0.06 ms | **0.05 ms** | 0.31 ms | 0.45 ms |
| 65 536 pts | 0.92 ms | 1.07 ms | **0.44 ms** | 5.82 ms | 6.84 ms |
| 512 x 512 grid | 1.54 ms | 4.54 ms | 2.04 ms | 19.1 ms | 28.0 ms |
| 1024 x 1024 grid | 5.83 ms | 18.75 ms | 7.10 ms | 69.2 ms | 112 ms |

FNS = `pyfastnoisesimd` 0.4.2 (cp39 wheel on 3.9; 3.12 and 3.13 source builds are within noise).
numba = a 40-line 2D simplex fBm on numba 0.67.0, Python 3.13.6, `fastmath=True`. The shipped port
(F1, numba 0.60 on 3.9, `fastmath=False`, OpenSimplex2 3D) measures 0.07 / 0.82 / 3.15 / 9.97 ms on the
same four rows; see `signals/DETAILED_FASTNOISE_PERF.md`. FastNoiseLite =
`pyfastnoiselite` 0.0.7, single-threaded, holds the GIL (4 and 8 threads gave 1.02x and 0.99x).

Why the bin row matters: the world-processing budget is about 0.8 ms per frame
(ADR-004) and one bin batch samples four noise
signals. FastNoiseLite spends more than the whole frame budget on noise alone for one batch. numba
does not. The SpriteJammer "205x" figure compared FastNoiseLite against the pure-Python loop in
`noise_signal.py`, not against FastNoiseSIMD.

### 2.2 numba kernel behaviour

| Check | Result |
| --- | --- |
| Cold start, first process (compile, `cache=True`) | 2 350 ms |
| Warm start, second process (load from cache) | 121 ms |
| Run to run, parallel | bit-identical |
| Parallel vs serial | bit-identical |
| `fastmath=True` vs `fastmath=False` | bit-identical on this CPU (see 6, fastmath) |

The kernel used is a plain per-point loop under `prange` with no reductions, which is why parallel
and serial agree exactly. Kernels with reductions would not, and SpriteJammer records that lesson
(section 2.7).

### 2.3 FastNoiseSIMD source builds

| Python | numpy | Build | Parity with cp39 wheel (seed 12345, 4 096 pts) |
| --- | --- | --- | --- |
| 3.12.13 | 1.26.4 | OK, seconds | identical |
| 3.12.13 | 2.5.3 | OK, seconds | identical |
| 3.13.6 | 2.5.3 | OK, seconds | identical |

The default `pip install` fails on 3.10+ only because the 2021 sdist does not declare numpy as a
build requirement. With `--no-build-isolation` and numpy present it compiles cleanly. This is
recorded because it is the escape hatch if the numba kernel ever disappoints: the library is not
dead, only its wheels are.

### 2.4 The numpy pin

`numpy>=1.26.0,<2.0` exists because `DETAILED_FASTNOISE_PERF.md` records the cp39 wheel failing to
import under numpy 2.0.2. That is the numpy 2 ABI break hitting a binary compiled against numpy 1
headers. With `pyfastnoisesimd` gone the pin has no remaining reason. A grep for numpy-2-removed
aliases (`np.float_`, `np.product`, `np.NaN`, `np.in1d`, `copy=False` and friends) over all
packages finds nothing.

### 2.5 The test suite on the new stack

Python 3.12.13, numpy 2.5.3, `pyfastnoisesimd` built from source, PySide6 6.11.2,
`-m "not slow and not benchmark"`:

| Result | Count |
| --- | --- |
| Passed | 2 578 |
| Failed | 1 |
| Skipped | 20 |
| Deselected | 249 |

The single failure is `test_canonical_imports.py::test_the_probe_rejects_an_import_resolved_from_another_tree`,
which spawns a subprocess expecting the packages installed in the interpreter rather than only on
`PYTHONPATH`. It is an artefact of the scratch venv. No numpy deprecation warnings fired. The suite
has not yet been run on 3.13; that must happen before the `requires-python` bump merges.

### 2.6 Dependency resolution, wheels only

`uv pip compile --no-build` for the full set including `wgpu`, `imgui-bundle` and `numba`:

| Python | Result |
| --- | --- |
| 3.11 | resolves |
| 3.12 | resolves once `imgui[glfw]` is removed |
| 3.13 | resolves once `imgui[glfw]` is removed and numpy is unpinned (numpy 1.26 has no cp313 wheel) |

`imgui[glfw]` (old pyimgui) is declared in the `gui` extra, imported nowhere, and has no cp312+
wheels. numba 0.67 ships cp310 through cp314. `pyassimp` is a pure-Python sdist and builds anywhere.

### 2.7 How SpriteJammer uses numba

Surveyed so the pattern here is a copy, not a reinvention. Three production kernels (agent
separation, push-out, flow-field fast sweep), all `@njit`, two `parallel=True`, all `fastmath=True`,
all `cache=True`. Measured 23x on separation at 10k agents, 11x on navigation, 12x serial to
parallel on pose. None is noise-related.

Patterns worth copying verbatim:

- **Optional import.** `try: from numba import njit, prange; HAVE_NUMBA = True except ImportError:
  HAVE_NUMBA = False`, kernels defined under `if HAVE_NUMBA:`, a hand-written numpy twin for every
  kernel, dispatch on the flag, and a `use_numba: bool | None` constructor override that warns once
  and degrades if numba is asked for and absent.
- **Optional dependency.** `jit = ["numba>=0.61"]` extra. CI installs it because the numpy fallback
  made the crowd tests take 20 minutes; a test keeps numba on a blocked list so nothing may
  *require* it.
- **Agreement tests.** Every kernel has a test comparing it against the numpy twin, and one test
  monkeypatches `HAVE_NUMBA = False` to force the slow path.
- **fastmath discipline.** Tests compare one tick only, with `atol=1e-4`, because fastmath may
  reorder float operations. One real bug is recorded: a convergence loop with `<` instead of an
  epsilon never settled under fastmath, 111 ms per solve against 6 ms once fixed.
- **Recorded pain.** JIT warmup is absorbed by generic warmup frames; no `NUMBA_CACHE_DIR` is set so
  `.nbi`/`.nbc` files land in `__pycache__/`; hybrid-CPU tail frames may be numba threads on
  efficiency cores, with `NUMBA_NUM_THREADS` as the proposed control, not yet applied.

### 2.8 wgpu and imgui-bundle, confirmed on 3.12

`wgpu` 0.32.0 ships `wgpu.utils.imgui` with `ImguiRenderer`, `ImguiWgpuBackend` and a `Stats`
overlay, backed by `imgui-bundle` 1.92.9 (wheels cp311 through cp314). The Qt canvas path is
`rendercanvas.qt`, which requires PySide6 to be imported first. Both installed and imported cleanly.
Neither has drawn a frame yet.

---

## 3. Proposed decisions

Each is written to become an ADR: context, decision, consequences.

### D1. Develop on Python 3.13; library packages support 3.11 through 3.13

**Context.** 3.11 is the wgpu floor and 3.13 is where the tools should live. `large_worlds` and
`hog_color` exist to be imported inside DCCs, and the DCC target is **Maya 2026 and later**, which
is Python 3.11 with its own numpy 1.x. Houdini 20.5+ and Blender 4.x are also 3.11. Nothing older
is supported, and nothing looks back. Everything the library needs has cp311 wheels: numba 0.67,
`pyfastnoiselite`, numexpr 2.14, and scipy releases that uv's universal lock selects per
interpreter. The packages are 3.9-clean today, so nothing has to be unwritten; the floor only
decides which newer syntax is allowed in.

**Decision.**

- `requires-python = ">=3.11,<3.14"`. `numpy>=1.26` with no upper bound.
- `.python-version` pins 3.13 for the dev venv and `activate.*`. `ruff` `target-version = "py311"`,
  so `X | Y` unions, `match`, `tomllib` and `ExceptionGroup` are allowed in library code and
  nothing newer is.
- App-only dependencies (`wgpu`, `rendercanvas`, `imgui-bundle`) live in a `render` extra.
  `hog_rendering` and `hog_tools` are 3.13 targets; they are not what a DCC imports.
- CI matrix: 3.11 with numpy 1.26 (library packages, no `gui`/`render` extras, the Maya contract)
  and 3.13 with the latest numpy (everything). Both must be green.
- `setup.py` classifiers match the range; the 3.8 to 3.10 ones go.

**Consequences.** Two interpreters to keep green instead of one. The DCC path is a tested
contract rather than a hope. When Maya moves past 3.11 the floor moves with it, one small PR,
and D9's sunset tests name whatever that bump makes removable.

### D2. Procedural noise moves to a numba kernel; `pyfastnoisesimd` is used once more, then removed

**Context.** Sections 2.1 and 2.2. A 40-line kernel matches FastNoiseSIMD's multithreaded speed on
every workload the world loop runs, is deterministic, needs no compiler on any machine, and its
source lives in this repo where it can grow 3D noise, ridged and billow fractals, domain warp and
cellular noise without depending on a 2021 binding.

**Decision.** `large_worlds/signals/noise_kernels/` holds our own implementations of the noise
family, with the long-term scope being the **union** of FastNoiseSIMD and FastNoiseLite features
(section 4.2), not the subset the current API happens to call. Every feature lands as a numpy base
implementation first, then a numba kernel where the benchmark in D3 says so, then numexpr or
anything else only on the same evidence. FastNoiseLite is MIT and FastNoiseSIMD is MIT; both
reference sources are small and readable; each port is line-by-line and validated against the
original binding on committed test vectors (section 4.4). `FastNoiseSignal`
keeps its name and its public API (`noise_type`, `frequency`, `seed`, `set_fractal_parameters`,
`sample`, `sample_area`, `sample_points`) and is re-implemented over the backend ladder (D9).
`pyfastnoisesimd` leaves the dependency list. Its wheel exists for nothing in the supported range,
so it does not survive as a rung: it is used in Phase 0, on the last 3.9 checkout, to generate the
Phase C oracle vectors (section 4.4) and to validate the Phase A port against the noise the project
shipped with, and then it is deleted in Phase 1. The source-build recipe in section 2.3 stays in
this document as the way to regenerate vectors if a parameter combination was missed.

**Consequences.** Worlds generated with the new kernel differ from worlds generated with
FastNoiseSIMD for the same seed, and that is accepted outright: nothing persists generated worlds,
LargeWorlds and SpriteJammer are the only consumers, and neither has anything that must look the
way it used to. **Our implementation is the definition.** Once a kernel is locked from this
roadmap, regression vectors are generated from *it*, and those are what later changes are held to.
A benchmark test guards the bin-row number in 2.1 within 25 %.

### D3. numba is an optional extra, used where a benchmark says so, and nowhere else

**Context.** Section 2.7. SpriteJammer's policy has survived contact with a real horde and a real
CI. This project has one measured use (noise). The `performance` extra in `setup.py` already names
`numba>=0.50.0`, unused.

**Decision.**

- `jit = ["numba>=0.61"]` extra in `pyproject.toml`; `all` includes it; CI installs it.
- Every kernel has a numpy twin and an agreement test; a test forces `HAVE_NUMBA = False`. A kernel
  without a twin does not merge.
- A kernel is added only with a benchmark in `tests/benchmarks/` showing the gain on a
  world-loop-sized input. "It could be faster" is not a reason.
- `fastmath` is a per-kernel benchmark decision like everything else. Section 2.2 shows it is free
  on this CPU for the noise kernel; if a later kernel gains from it, it takes it. Cross-CPU
  bit-identity is not a requirement of this project. What is required is that the same machine
  gives the same world for the same seed, which `prange`-without-reductions kernels already do.
- `cache=True` everywhere; `NUMBA_CACHE_DIR` set by `activate.ps1`/`activate.cmd` to
  `.venv/numba_cache/` so cache files stay out of the source tree.
- `World.setup_progressive_generation()` warms the kernels once so the compile cost never lands in
  a frame. Log which path each signal resolved to at setup.
- `NUMBA_NUM_THREADS` is left to numba unless a hybrid-CPU tail shows up in a profile, in which case
  the loop caps it and records why.

**Consequences.** One more optional dependency with a compile step, and a class of test (numba vs
numpy agreement) this repo has not needed before. The `hog_color` numexpr precedent already
established "fast path behind a single dispatch point"; this is the same shape.

**On the separate public repo.** A wheel-building repo was considered for `pyfastnoisesimd`
(section 2.3 shows it would work). With D2 there is no C extension left that needs one, so it is not
created. If a second unmaintained C extension ever blocks a Python bump, revisit; the recipe
(fork, declare numpy in `[build-system]`, cibuildwheel, PEP 503 index on GitHub Pages, consumed
through an explicit `[[tool.uv.index]]`) is straightforward and would take a day. A git submodule
was rejected outright: it distributes source, not binaries, so every clone would compile.
If a public artefact is wanted, the numba noise kernels are a better candidate than rebuilt wheels,
but not yet: SpriteJammer already vendors `large_worlds/signals/` file by file, which is the
extraction path if and when a second consumer appears.

### D4. `pyfastnoiselite` is the reference implementation and the fallback

**Context.** The numba port needs an oracle. `pyfastnoiselite` wraps the exact algorithms being
ported, has wheels cp38 through cp313, and is fast enough for tools, tests and any machine without
numba. SpriteJammer's `fastnoiselite_signal.py` is the starting point but is not a drop-in: it
lacks `sample_points`, `set_fractal_parameters`, `cubic`, ridged and billow.

**Decision.** Default resolution order inside `FastNoiseSignal`, on every Python in the supported
range: numba kernel, then `pyfastnoiselite`, then the numpy twin of the kernel. All three produce
the same values within the tight bar in 4.3, since all three are ours.
One further rung exists outside the default order and is reachable only by override (D9): the
legacy numpy generators in `noise_signal.py`, which produce different noise, log a warning when
selected, and carry a sunset string of "remove when nothing references them", to be checked at
the end of Phase 1.

**Decision, same ADR.** The `hasattr(signal, "sample_points")` guards in `core.py:586` and
`bin.py:505` are vacuous because `BaseSignal` defines the method. Replace with an explicit
`BaseSignal.supports_batch: ClassVar[bool]`, `True` only on implementations that batch. A signal on
the per-point path must be visible in the setup log, not discovered in a profiler.

**Consequences.** `pyfastnoiselite` becomes a hard dependency (small, wheels everywhere). `billow`
has no FastNoiseLite equivalent and is dropped from the accepted fractal types with a clear error;
nothing in the repo uses it.

### D5. Retire the `hog_python` conda tree: port, then delete

**Context.** `Build/ArtTools/hog_python/` is the environment pattern from the pre-uv conda era:
conda venvs per Python version, `.cmd` launchers, shared site-packages, and a half-finished
migration of those `.cmd` files to dynaconf (`hog_env/`, `scripts/generate_env.py`,
`bin/launch_vscode_dynaconf.py`). 55 tracked files, 781 MB on disk with the untracked venvs, last
commit April 2026. The uv layout at the repo root replaced its reason to exist. Nothing outside the
directory imports it; the only live reference is a permission entry in `.claude/settings.json`.
`mesh_world` uses dynaconf directly through its own `config/` and does not touch `hog_env`.

**Decision.** Triage, port what has value for future projects into a source package, then delete
the directory in one PR. Disposition per file:

| Files | Disposition | Where / why |
| --- | --- | --- |
| `hog_env/launchers.py`, `hog_env/env_builder.py` | **Port** | `hog_wild/env/`: build a subprocess environment dict (PATH, PYTHONPATH, QT vars) and launch an app or editor with it. Generic, DCC-launcher shaped, no sibling-package imports, fits `hog_wild`'s charter. Rewrite against `pathlib` and the module header template; drop the dynaconf coupling, take a plain mapping |
| `hog_env/path_resolver.py` | **Port the idea only** | Settings-path interpolation. If `mesh_world/config` wants it, it moves there as a private helper; otherwise dropped |
| `hog_env/config.py`, `config/settings.json`, `config/*.example`, `DYNACONF_README.md` | **Delete** | dynaconf wiring for the `.cmd` migration. `mesh_world/config` is the surviving dynaconf pattern and already documents itself |
| `hog_env/README.md` (402 lines) | **Archive** | `.archive/Docs/hog_env-README.md`. It is the design record of the cmd-to-dynaconf migration; worth keeping as history, not as live docs |
| `scripts/kill_debugpy.cmd`, `scripts/debugpy_msg.cmd`, `scripts/install_vsc_extensions.cmd` | **Keep as scripts** | `tools/` at the repo root, if that directory is created for the Phase 1 activate-script work; otherwise archive. Small, occasionally useful, not worth a package |
| `scripts/delete_pycache_folders.py`, `pip_freeze.py`, `get_python_*.py`, `gen_env_dict.*`, `env.json`, `sketch/` | **Delete** | one-liners and scratch; uv and `git clean` cover them |
| `scripts/validate_environment.py`, `generate_env.py`, `check_env_fresh.py`, `check_dynaconf_install.py`, `bin/launch_vscode_dynaconf.*` | **Delete** | tooling for a migration that will not finish |
| `scripts/cinstall.ps1` (781 lines), `install_chocolately.cmd`, `get_python.bat`, `setup_venv.*`, `update_python_*_packages.cmd`, `upgrade_pip.cmd`, `generate_requirements.py` | **Delete** | machine bootstrap via Chocolatey and conda. uv installs Python and packages; the activate scripts already do `uv sync` |
| `activate.cmd`, `hog_cmd.cmd`, `hog_python_env.cmd`, `python.cmd`, `start_vsc.bat`, `*.lnk`, `hog_python.code-workspace` | **Delete** | superseded by root `activate.*`, `launch_vscode.*`, `LargeWorlds.code-workspace` |
| `shared/requirements*.txt` | **Delete** | superseded by `pyproject.toml` and `uv.lock` |
| `README.md` | **Delete** | describes the conda flow; its replacement is the Environment Setup section of `CLAUDE.md` |

Untracked contents (`.venv/`, `shared/Python-3.9/`, `shared/Python-gui-3.9/`, `typings/`) are
removed from disk by the same PR's instructions; they were never in git.

**Consequences.** One environment system. `hog_wild` gains a small `env` subpackage with its own
tests and a line in hog_wild/CLAUDE.md.
`CLAUDE.md`, `copilot-instructions.md` and `.claude/settings.json` lose their `hog_python` and 3.9
references. The `.gitignore` entries for `hog_python/.venv/` and `hog_python/typings/` go with it.
The port is done before the delete, in the same PR, so the history of the two files that survive
is one `git mv` plus a rewrite rather than an unexplained new module.

### D6. Replace pyimgui with imgui-bundle

**Context.** Sections 2.6 and 2.8.

**Decision.** Remove `imgui[glfw]` in the Python-bump PR. Add `imgui-bundle` when the debug overlay is
next wanted -- on the current OpenGL `BaseViewport` (deleted; now `WgpuViewport`), or in the wgpu spike, whichever comes first. It is
**not** gated on the spike.

**Consequences.** Debug overlays (frustum, tile bounds, stats, camera readouts) get an immediate-mode
UI path in the new renderer instead of hand-drawn GL lines.

**Amended 2026-09-17.** This decision read "as part of the wgpu work", and the title and decision above
are the amended, authoritative form. The two halves came apart: F2 did the removal, while the
replacement stayed parked behind the wgpu spike, which is unscheduled -- so there is now no working
debug overlay at all, and
`hog_rendering/imgui_integration.py` still carries the full `ImGuiOverlay` written against the old
pyimgui API. With nothing installed, `HAS_IMGUI` is permanently `False`: the class, the `~` toggle in
`visualize.py` and the inherited hook in `mesh_world`'s viewport are all dead code that still
advertises itself in the console hint, and no test references any of it. Binding the replacement to
the GPU port was wrong -- an immediate-mode debug UI is a **baseline for refactoring**, not a
consequence of wgpu. `imgui-bundle` may land on the current OpenGL `BaseViewport` (now `WgpuViewport`) whenever the debug
overlay is wanted, ahead of the spike and independently of it. Either it is ported or the dead code
goes; what must not continue is a feature that exists only in the console hint.

### D7. `large_worlds` must not import `hog_rendering`, before any wgpu code exists

**Context.** ADR-001 says `large_worlds` is DCC-importable
with no PySide6 or OpenGL. It is not true today. `import large_worlds.core` pulls PySide6 and
PyOpenGL into the process:

- `large_worlds/core.py:25` and `large_worlds/tiles/culling.py:13` import `hog_rendering.camera.Camera`
- `hog_rendering/camera/__init__.py` imports `camera_viewport` (Qt) and `camera_editor` (Qt, GL)
- `large_worlds/ui/views/model_viewer.py` was a `QOpenGLWidget` inside the generation package (now `hog_tools/model_viewer/`)
- `large_worlds/io/{image_processor,mesh_handler,model_loader}.py` re-exported from `hog_rendering.io` (deleted in F3)

A second renderer on top of this couples the generation library to both.

**Decision.** Before the wgpu spike:

1. A numpy-only camera protocol in `large_worlds` (position, direction, view-projection, frustum
   planes, `is_aabb_visible`). `CameraData` in `hog_rendering/camera/camera_data.py` is already
   numpy-pure and can move down behind it.
2. `culling.py`, `core.py`, `world_generator.py` depend on the protocol, not on `hog_rendering`.
3. `large_worlds/ui/` moves to `hog_tools/` or `hog_rendering/`; it is app code.
4. `large_worlds/io/*` stops re-exporting from `hog_rendering.io`.
5. A boundary test in the style of `tests/test_hog_wild/test_package_boundary.py`: importing every
   `large_worlds` module leaves no `PySide6*` or `OpenGL*` entry in `sys.modules`.

**Consequences.** This is the step the SpriteJammer note skipped, and it is the one that makes the
renderer swappable. It also makes the ADR-001 claim true.

### D8. Adopt wgpu incrementally, behind the viewport seam, with a spike first

*(Heading as planned, which said `BaseViewport` -- deleted when D8 landed, and the seam is now `WgpuViewport`.)*

**Context.** Surface area:

| Area | Size |
| --- | --- |
| `hog_rendering` files importing OpenGL | 20 |
| `gl*` calls in `hog_rendering` | ~1 100 |
| GLSL shaders to rewrite in WGSL | 2 |
| `QOpenGLWidget` subclasses | 4: `base_viewport.py`, `camera/camera_viewport.py`, `mesh_world/controller.py`, `hog_tools/model_viewer/viewer.py` |

Known trap: `camera_data.py:288` builds an OpenGL projection (clip z in [-1, 1]); WebGPU is [0, 1].
Reusing it gives wrong depth, not an error, and the frustum planes inherit the error.

**Decision.** In order:

1. **Spike.** One tile mesh through `wgpu` on a `rendercanvas.qt` canvas in a PySide6 window, with an
   `imgui-bundle` stats overlay, a projection with a `clip_range` parameter and a unit test that
   near and far map to 0 and 1. No production code changes. Output is a written go/no-go.
2. **Backend seam.** `BaseViewport` (now `WgpuViewport`) gains a backend enum; each renderer gets a wgpu implementation,
   one PR each, PyOpenGL untouched and still the default.
3. **Flip the default** per app, `visualize_synthetic_world.py` first, `mesh_world` last.
4. **Delete PyOpenGL** when no app selects it. Done 2026-09-21.

**Consequences.** Weeks, not days, and not sizeable until the spike is done. The "VBOs are lazily
allocated on first render" rule gets a wgpu analogue and the thread-safety table in `CLAUDE.md`
gets a wgpu column.

### D9. One backend-ladder pattern, with explicit gating and explicit sunset

**Context.** D2, D4 and `hog_color`'s numexpr dispatch are the same shape: a base implementation
that always works, optional optimised implementations layered above it, and a rule for which one
runs. The wgpu port (D8) will be the fourth instance. Without a shared pattern each one grows its
own env var, its own log line and its own "remove this later" comment that nobody removes.

**Decision.** `large_worlds/backends.py`, small and dependency-free:

```python
@dataclass(frozen=True)
class Backend:
    capability: str          # "noise" (points), "noise_grid" (grids, may be GPU), later "render"
    name: str                # "numba", "fastnoiselite", "numpy", "fastnoisesimd"
    priority: int            # higher wins; legacy rungs are negative and never win by default
    is_available: Callable[[], bool]
    factory: Callable[..., Any]
    python_max: tuple[int, int] | None = None   # e.g. (3, 12) => not attempted on 3.13+
    sunset: str | None = None                   # "remove when requires-python >= 3.13"

def select(capability: str) -> Backend: ...
```

Selection rules, in order:

1. `LARGE_WORLDS_<CAPABILITY>_BACKEND=<name>` forces a backend. If it is unavailable, raise at
   setup with the reason. Never fall through silently from an explicit request.
2. Otherwise the highest-priority backend whose `is_available()` is true and whose `python_max`
   admits the running interpreter. Negative-priority backends are skipped here.
3. `World.setup_progressive_generation()` logs one line per capability: chosen backend, why, and
   which rungs were skipped and why. Tests assert the line exists; a profiler should never be the
   first place a fallback is noticed.

Gating rules:

- Version gates are `sys.version_info` checks in `is_available`, not scattered `if` statements.
- DCC detection (`maya`, `hou`, `bpy` in `sys.modules`) is exposed as `is_dcc_host()` for logging
  and for tests, not for selection. A DCC gets the same ladder as the tool; only the availability
  differs.
- Every backend with a `sunset` string has a matching test in `tests/test_backends.py` that fails
  once `requires-python` in `pyproject.toml` crosses the version named. The failing test's message
  is the removal PR's checklist: the backend module, its registration, its vectors, this row.

**Consequences.** One place to look for "which implementation is running and why", the same
answer in a DCC and in the tool, and legacy code that announces its own expiry instead of waiting
to be noticed. The numexpr dispatch in `hog_color` is *not* migrated onto this in Phase 0; it works
and has its own tests. It becomes a candidate the next time it is touched.

---

## 4. The noise kernel, specified

### 4.1 Package

`large_worlds/signals/noise_kernels/`, one module per family (`simplex.py`, `perlin.py`,
`value.py`, `cellular.py`, `fractal.py`, `warp.py`, `grid.py`). Pure functions, no classes, no
logging inside kernels. Every kernel is a pair: `simplex2_numpy` always present, `simplex2_numba`
under `if HAVE_NUMBA:`. Signature convention: `(xs, ys, zs, params..., out)` with `out`
preallocated by the caller, per .instructions/performance.md
(no allocations per frame). Parameters travel as a frozen `NoiseParams` dataclass so a kernel
signature does not grow a positional argument per feature.

### 4.2 Scope of the port: the union, phased

Phase A is what the current API calls plus the parity oracle. Phase B is the rest of FastNoiseLite.
Phase C is what only FastNoiseSIMD had. Phase D is what neither had and terrain will want. Each row
is a numpy base first; the numba column says whether a kernel is expected to pay for itself on a
world-loop input, and is a guess until the benchmark in D3 says otherwise.

| Feature | Source | Phase | numba kernel expected | Notes |
| --- | --- | --- | --- | --- |
| OpenSimplex2 2D/3D | FNL | A | yes | new default `simplex` |
| Perlin 2D/3D | both | A | yes | `world_generator.py` |
| Value, ValueCubic | both | A | yes | `value`, `cubic`; FNS `Cubic` maps here |
| FBm, Ridged | both | A | in the same kernel | `fbm`, `ridged`. F1 mapped FNS `RigidMulti` to Ridged; Phase C found them different (the classic-simplex vectors correlate 0.5 under that alias) and gave RigidMulti its own type, `FractalType.RIGID_MULTI`, 2026-09-28 |
| OpenSimplex2S | FNL | B (done 2026-09-28) | in the same kernel | smoother variant; numba and numpy exact, tight class against the FNL vectors in 2D and 3D, every fractal |
| PingPong fractal, weighted strength | FNL | A (done in F1) | in the same kernel | |
| Cellular: CellValue, Distance, Distance2, Distance2Add/Sub/Mul/Div | both | A (done in F1) | yes | pulled forward: the synthetic world's biomes use `cellular` |
| Cellular distance: Euclidean, EuclideanSq, Manhattan, Hybrid | FNL | A (done in F1) | yes | |
| Cellular jitter | both | A (done in F1) | yes | |
| Domain warp: OpenSimplex2, OpenSimplex2Reduced, BasicGrid; progressive and independent | FNL | B (done 2026-09-28) | in the same kernel | replaces FNS perturb; `NoiseParams(domain_warp=, domain_warp_amp=)`; the oracle is the C++ harness in `tools/noise_oracle`, since `pyfastnoiselite` binds no `DomainWarp` |
| Rotation type 3D (ImproveXYPlanes, ImproveXZPlanes) | FNL | A (done in F1) | in the same kernel | terrain is XZ, so `ImproveXZPlanes` is the interesting one |
| Classic Simplex 2D/3D | FNS | C (done 2026-09-28) | in the same kernel | `NoiseType.SIMPLEX_CLASSIC`: FNS's hash, gradient selection and skew, so old seeds reproduce by name; 2D is the 3D field at z = 0, as FNS was used |
| Billow fractal | FNS | C (done 2026-09-28) | in the same kernel | `FractalType.BILLOW`, numbered past FNL's range; weighted strength applies to the folded value; proven from its octaves, shape-checked against the FNS vectors |
| WhiteNoise | FNS | C (done 2026-09-28) | in the same kernel (the bit cast numba supports) | `NoiseType.WHITE_NOISE`, FNS's hash kept so the values match its vectors point for point (max 1e-6); `WhiteNoiseSignal` (cell-hashed, `RandomState`) stays a different, coarser thing and is not unified |
| Cellular distance: Natural | FNS | C (done 2026-09-28) | in the same kernel | `CellularDistance.NATURAL`: manhattan times euclidean squared, FNS's distance form (its CellValue used the sum, which is our `hybrid`) |
| Cellular return: NoiseLookup, Distance2Cave | FNS | C (done 2026-09-28) | in the same kernel | `NOISE_LOOKUP` samples `cellular_lookup_type` at the nearest cell point at `cellular_lookup_frequency` (single octave; FNS's fractal lookups are not carried); `DISTANCE2_CAVE` is the lesser of two Distance2Div fields, the second at seed + 1 and half a cell over |
| Gradient perturb: Gradient, GradientFractal, Normalise variants | FNS | C (done 2026-09-28) | in the same kernel | `NoiseParams(perturb=, perturb_amp=, perturb_frequency=, perturb_octaves=, ...)`, `FastNoiseSignal.set_perturb`; on the frequency-scaled point after FNL's warp on the raw one; by point with the FNS vectors over classic Simplex |
| Grid generation with axis scales (`genAsGrid`) | FNS | C (done 2026-09-28) | yes | `sampler.sample_grid(start, shape, scales)` / `FastNoiseSignal.sample_grid`: the kernel computes the coordinates, a 1024 x 1024 heightfield in 17 ms against 39 ms for building the coordinates and sampling them; equals `sample_points` exactly; the two FNS grids reproduce (the binding's 2D `start` padded z with 1) |
| 4D noise | neither | D | yes | time-varying fields, biome drift |
| Analytic derivatives / normals | neither | D | yes | slope and normal maps without finite differences |
| Tileable / periodic noise | neither | D | yes | texture and atlas generation |
| WGSL compute rung for grid workloads | neither | D | not numba; GPU | per 4.5; first kernel OpenSimplex2 FBm, gated on the D8 spike |

Phase A is Phase 0 of the plan in section 5. Phases B and C are scheduled by need, one feature
per PR, each with its base, its vectors and its benchmark. Phase D is recorded so the design does
not close it off; nothing schedules it.

### 4.3 Validation

Two different standards, deliberately:

- **Between our own rungs, tight.** The numba kernel and the numpy base of the same feature agree
  within `atol=1e-6` (float32), exact where the arithmetic allows. We own both; disagreement is a
  bug in one of them.
- **Against the original binding, always run, human-decided.** `tests/vectors/noise/<family>/<feature>.npy`
  holds 4 096 scattered points plus one 256 x 256 grid per feature from `pyfastnoiselite` or
  `pyfastnoisesimd`. The comparison always runs and always reports: max and mean absolute
  difference, correlation, value range, and whether the match is bit-exact, within `1e-6`, or
  looser. A mismatch does **not** fail the build. It writes a comparison sheet to
  `tests/vectors/noise/reports/<feature>.png` (reference, ours, signed difference as a diverging
  heatmap, difference histogram) and the test is marked `needs-review` until a human records a
  verdict in `tests/vectors/noise/accepted.json` (`{"feature": {"verdict": "accepted", "by": ..., "date": ...,
  "note": ...}}`; JSON rather than TOML because the supported floor lacks `tomllib`). A feature with an unrecorded mismatch is visible in every test run and blocks *lock*,
  not merge. `large_worlds/signals/noise_kernels/compare.py` produces the sheet and is also a CLI,
  so the same picture can be made for any two rungs on demand.
- **After lock, ours are the reference.** When a feature is marked locked in 4.2, its regression
  vectors are regenerated from our numba kernel and committed under
  `tests/vectors/noise/locked/`. From then on the tight test is against those, and the binding
  vectors are kept only as the record of where the port started.
- **Portability is recorded, not assumed.** The comparison report also states, per feature, which
  rungs matched which and how closely: numpy vs numba, numba `fastmath` on vs off, and later CPU
  vs GPU (4.6). That table lives in `tests/vectors/noise/portability.md`, regenerated by the
  tests, so the day something needs the same seed to give the same values on CPU and GPU, the
  answer is already written down per feature, along with which ones cannot and why.
- Benchmark in `tests/benchmarks/`: the bin row of 2.1 within 25 % for every feature with a numba
  kernel; a feature whose kernel does not beat its numpy base by the D3 bar ships numpy-only.
- Warm-start test: importing `noise_kernels` with a populated cache costs under 250 ms, measured
  again each time a family is added, since every kernel adds to the cache load.

### 4.4 Oracles, and why some vectors must be generated now

| Features | Oracle | Available |
| --- | --- | --- |
| Everything in Phase A and B except domain warp | `pyfastnoiselite` | on every supported Python, forever |
| Domain warp (Phase B) | `tools/noise_oracle/fnl_oracle.exe`, a 100-line harness over the vendored `FastNoiseLite.h`, built with MSVC by its `build.bat` | wherever Visual Studio's C++ tools are; the binding exposes `GetNoise` only (found 2026-09-28). The harness reproduces the binding's `gen_from_coords` bit for bit, so the two oracles are one |
| Everything in Phase C | `pyfastnoisesimd` | on the 3.9 venv today, or a 3.13 source build (2.3) |
| Phase D | none; algorithm papers and hand-checked cases | |

Phase C vectors are generated **in Phase 0**, before the 3.9 environment is retired, for every
FNS-only feature and for classic Simplex, Billow and `genAsGrid` at a range of parameters. They
cost nothing to hold and they are the only way a later Phase C port can check its intent. The
generator script is committed beside the vectors so they can be regenerated from a 3.13 source
build if a parameter combination was missed.

### 4.5 GPU rung: WGSL compute shaders under wgpu

**Why it belongs in this roadmap.** Once wgpu is in (D8), the same device that draws the terrain
can generate it. Heightmaps, texture fields and biome masks are grid workloads where a compute
shader wins by orders of magnitude over any CPU rung and delivers the result already in GPU
memory. The scattered-point world loop stays on the CPU: 4 096 points per bin at 0.05 ms is
below the cost of a GPU round trip.

**Design choices that make it possible, taken now:**

- **Hash-based gradient selection, no permutation tables.** FastNoiseLite already does this; the
  port keeps it. Integer hashing is bit-exact on CPU and GPU. A 512-entry permutation table would
  work too, but it is a texture or storage buffer on the GPU and a cache miss on the CPU, and the
  hash is what every modern GPU noise uses.
- **`NoiseParams` maps to a uniform buffer.** The frozen dataclass in 4.1 has a fixed field order
  and float32 or int32 fields only, so the same struct layout is the WGSL uniform.
- **One algorithm per feature, three renderings of it.** numpy base, numba kernel, WGSL kernel,
  written from the same reference and compared with the same tooling. The WGSL rung is a
  `Backend` in D9's ladder under a separate capability name (`noise_grid`), because it serves grids,
  not points, and because a machine without a GPU device must never have it selected.

**What will not match, and is recorded as such (4.3):** WGSL has no `fastmath` switch but
implementations may fuse multiply-adds and reorder; `sin`, `exp` and friends are
implementation-approximate on GPUs. Features built only on adds, multiplies, floors, integer ops
and hashing (simplex, perlin, value, cellular distance, FBm, ridged) should match a
`fastmath=False` numba kernel to float32 rounding. Anything using transcendental functions
(PingPong's `sin`-shaped fold, some domain-warp variants) will match to a tolerance and no
tighter, and the portability table says so per feature.

**Scheduling.** Phase D in 4.2, gated on the D8 spike: the first WGSL kernel is written against
whatever compute path the spike proves, as a second spike of a few days, for OpenSimplex2 FBm on a
1024 x 1024 grid, compared against the numba rung with the 4.3 tooling. Nothing before that.

### 4.6 Threading

Parallel kernels use `prange` over points with no reductions, so output does not depend on thread
count. Cellular noise is per-point and qualifies. Nothing in the noise path needs `nogil`; the
world loop is single-threaded by design (ADR-004).

---

## 5. Plan: a fast track, then incremental work

Two tracks. The **fast track** ends with every current LargeWorlds app running on the new stack
and SpriteJammer consuming `large_worlds` core as a dependency instead of vendoring files. Its
sub-phases are ordered so each is one reviewable PR and nothing waits on work it does not need.
The **incremental track** is everything that can land one feature at a time afterwards. Boxes are
flipped as work lands.

### The gate, applied to every fast-track PR

Two conditions, both mandatory, neither negotiable by phase:

1. **All tests pass.** The full suite, including `slow`, on both CI legs once F2 lands. A test is
   never deleted or skipped to get green. It is either fixed, or deprecated **in the same PR** with
   a replacement that covers the same intent better, and the PR description names the old test,
   the new one, and why the new one is the better instrument. A `@pytest.mark.skip` without a
   linked replacement is a review block.
2. **Every app and runtime is functional.** The gate is the things people actually run:

   | Entry point | Functional means |
   | --- | --- |
   | `test_app.py` | CLI world generation completes; bin count and timing printed; no warnings from the backend ladder that were not there before |
   | `visualize.py` | Launches; world generates progressively; every shortcut in `CLAUDE.md` (`G T P V M L F C I O`) does what it says; both cameras switch |
   | `visualize_synthetic_world.py` | Launches; heightmap-driven terrain renders; the scale-preset dropdown and terrain controller work |
   | `mesh_world/main.py` | Launches; config resolves; viewport has a live context. Terrain load is a stub in `MeshWorldController.load_world_data()` as of 2026-09-13, so "a Gaea terrain loads" joins the gate when that lands; the editor's own `run_tests.ps1` is green |
   | `ColorStackWindow` | Launches; operations add, reorder, edit; the thumbnails update; export writes |

   "Functional" is checked two ways. Automated: `tools/smoke_apps.py` launches each entry point
   under the native Qt platform (offscreen gives `QOpenGLWidget` no GL context on Windows), drives
   a fixed script (generate N bins, render frames, toggle each shortcut, add/edit/remove operations
   through the panel, close) and exits non-zero on any exception, on a frame that is all background
   colour, or on a skipped GL target unless `--allow-skips` is passed explicitly for a headless
   runner; it runs in CI on the 3.13 leg from F2 onward and was added in F0 so it existed before
   anything moved. Human: the PR author launches each app for real and says so in the PR, because
   a smoke test cannot see that the terrain looks wrong.

Nothing on the fast track merges without both. The incremental track keeps condition 1 always and
condition 2 for any PR that touches a renderer, a signal, or an app.

### Fast track

#### F0. `hog_python` out (independent of everything; do it first)

Low-hanging fruit with no dependency on the Python bump, and removing it stops the 3.9 pattern
from confusing anyone during the rest of the track.

- [x] `tools/smoke_apps.py` written and green on 3.9 before anything else changes, so the gate
      has a baseline
- [x] Triage per D5's table: `hog_wild/env/` ported with tests, `hog_env/README.md` archived,
      the three debugpy/vsc scripts kept under `tools/`, everything else deleted
- [x] `.gitignore`, `.claude/settings.json`, `CLAUDE.md`, `copilot-instructions.md`, `hog_wild/CLAUDE.md`
      cleaned; untracked venvs removed from disk; `activate.*`, `launch_vscode.*` verified on a
      clean checkout
- [x] ADR D5

#### F1. Backend ladder and Phase A noise, on 3.9 (last use of FastNoiseSIMD)

- [x] `large_worlds/backends.py` per D9: `select`, env override, `supports_batch` capability,
      setup log line, sunset test scaffold
- [x] `jit` extra, `HAVE_NUMBA` guard, `NUMBA_CACHE_DIR` in the activate scripts
- [x] `pyfastnoiselite` added; Phase A vectors from it, Phase C oracle vectors from the 3.9
      `pyfastnoisesimd` (classic Simplex, Billow, Natural, NoiseLookup, Distance2Cave, all perturb
      types, `genAsGrid` with axis scales), committed with their generator scripts, per 4.4
- [x] `noise_kernels/` with OpenSimplex2 2D/3D, Perlin, Value, ValueCubic, Cellular (pulled forward
      from Phase B: the synthetic world's biome layer uses it); FBm, Ridged, PingPong; numpy base
      and numba kernel for each; `NoiseParams` frozen dataclass, hash-based gradients
- [x] `noise_kernels/compare.py`: comparison sheets, `accepted.json` (JSON, not TOML: the floor lacks `tomllib`), `portability.md`; wired
      into the vector tests as `needs-review`, never as a build failure
- [x] `FastNoiseSignal` re-implemented over the ladder, public API unchanged; `hasattr` guards in
      `core.py` and `bin.py` replaced; warm-up in `setup_progressive_generation()`
- [x] Benchmarks: bin row 0.07 ms (FastNoiseSIMD 0.06, prototype 0.05; the 25 % bar was against the
      prototype and the port lands at 40 % over it, 17 % over FastNoiseSIMD, accepted);
      `Testing/benchmark_bin_generation.py` rerun and recorded in `signals/DETAILED_FASTNOISE_PERF.md`
- [x] Visualizer, synthetic world and `mesh_world` run on the numba rung (smoke gate 5/5); the
      human verdict on "looks right" and on the one needs-review sheet (`simplex_pingpong`,
      1.6e-4) is recorded in `accepted.json` at review
- [x] `signals/*.md` rewritten (two FastNoiseSIMD tuning docs archived); ADR-007 (D2 + D4), ADR-008 (D3), ADR-009 (D9)

#### F2. Python 3.11 to 3.13, every app on 3.13

- [x] `requires-python = ">=3.11,<3.14"`, `numpy>=1.26`, classifiers; `.python-version` = 3.13;
      ruff `target-version = "py311"`; `uv lock` universal
- [x] `pyfastnoisesimd` wrapper, tests and `Testing/` scripts deleted; `imgui[glfw]` removed;
      `render` extra declared empty
- [x] CI matrix: 3.11 + numpy 1.26 (library packages only) and 3.13 + latest numpy (all), in
      `.github/workflows/tests.yml` (the repo had no CI before F2); green on this workstation on
      3.13 including `slow`; the hosted-runner legs are proven by the PR itself
- [x] Sunset tests pass; the only current sunset (`legacy_numpy`) is a human condition, so no
      floor bump can fire it yet and `test_the_sunset_check_would_fire` is what proves the mechanism
- [x] `visualize.py`, `visualize_synthetic_world.py`, `mesh_world/main.py`, the colour stack
      window: launched on 3.13 (smoke gate 5/5), PyOpenGL still the renderer
- [x] `CLAUDE.md`, `copilot-instructions.md`, package READMEs; ADR-010 (D1 + D6)

#### F3. Import hygiene: `large_worlds` importable with no graphics stack

The half of D7 SpriteJammer needs. The camera protocol and the `large_worlds/ui/` relocation are
part of it; the `hog_rendering` backend seam is not.

- [x] `large_worlds/view.py`: `Viewer` protocol, the numpy cores moved down from
      `hog_rendering/legacy_camera.py`, `SimpleCamera`; `culling.py`, `core.py`, `tile_manager.py`
      type against `Viewer`; the generators take `camera_factory=` and the visualizers pass
      `hog_rendering.camera.Camera`
- [x] `large_worlds/ui/` moved to `hog_tools/`; `large_worlds/io/` no longer re-exports
      `hog_rendering.io`
- [x] Boundary test `tests/test_package_boundaries.py`: static scan of every module plus a
      fresh-interpreter import of the whole package; one recorded allowance (`Tile.load_mesh`
      reaches `hog_rendering.io` at call time); on the 3.11 CI leg, which deselects nothing now
- [x] `PyOpenGL` moved into the `gui` extra beside `pyside6`, so a consumer of `large_worlds`
      alone does not install a renderer
- [x] ADR-011 (D7); ADR-001 amended

#### F4. SpriteJammer consumes `large_worlds` core

- [x] SpriteJammer's `pyproject.toml` takes `large-worlds` as a dependency: the git tag `v0.2.4`
      (a7f08dd4) only, no `[tool.uv.sources]` path override. A path source would let this repo move
      the WGSL oracle under SpriteJammer's goldens with no commit there, which is the property its
      ADR-017 vendored to keep; the tag pin keeps it and local work bumps the tag. Deletes its
      vendored `src/large_worlds/` and, because this wheel ships `hog_color` too and two copies on
      `sys.path` is a `.pth` ordering accident, its vendored `src/hog_color/` as well; the
      `VENDORED.md` files go with them and SpriteJammer's ADR-028 (supersedes its ADR-017) is the
      closing record (SpriteJammer PR #46)
- [x] SpriteJammer's `fastnoiselite_signal.py` retired in favour of the F1 ladder; its noise
      call site (`sj_assets.terrain.build_heightfield`) uses `FastNoiseSignal.sample_points` on
      the z=0 plane, which reproduces the old 3D-at-z=0 field within float32 noise (max abs
      diff 1e-3), so its terracing and navigation bars hold unchanged; `pyfastnoiselite` is no
      longer a direct dependency there
- [x] Whatever SpriteJammer needs from tiles, bins and `World` that the vendored subset never
      covered is listed as issues here, not patched there: nothing yet. Its ADR-023 (`Layer`
      takes `large_worlds.layers`' meaning) and world-semantics work can now import them without
      another vendoring decision
- [x] Both repos green on 3.13 in CI against the same `large-worlds` tag `v0.2.4` (2026-09-18).

**Fast track done** means: every LargeWorlds app runs on 3.13 with the numba noise rung,
`large_worlds` imports clean in a wgpu process, and SpriteJammer depends on it by tag.

### Incremental track (after the fast track, one feature per PR, no fixed order)

- [ ] **Maya 2026 proof of life.** `mayapy` imports `large_worlds`, builds a small world and samples
      one signal, on the real 3.11 interpreter Maya ships. D1's whole floor exists to serve Maya and
      Maya is the one interpreter never tested; CI cannot cover it, since no runner has Maya. A
      scripted check plus its recorded output, run by hand at each floor bump, is what turns the
      contract from a plan into a fact. Resolves the standing risk in section 6
- [ ] **imgui-bundle on the current viewport** (D6 as amended) -- restore the debug overlay against
      `BaseViewport` (now `WgpuViewport`) as it stands, or delete the orphaned `imgui_integration.py` and its call sites.
      Not blocked by the wgpu spike
- [x] Noise Phase B features (4.2), each with base, kernel if it earns it, vectors, sheet, verdict
      (OpenSimplex2S and domain warp done 2026-09-28: Phase B complete)
- [x] Noise Phase C features (4.2), validated against the oracle vectors captured in F1. Done 2026-09-28:
      Billow, WhiteNoise, cellular Natural / NoiseLookup / Distance2Cave, classic Simplex, and RigidMulti
      as its own fractal (F1's alias to Ridged was wrong). WhiteNoise and classic Simplex match the FNS
      vectors by point; the rest by shape, since FNS hashes its other base noises differently. Then the
      gradient perturb (five modes, by point over classic Simplex) and `genAsGrid` (`sample_grid`). Phase C
      complete 2026-09-28
- [ ] Sunset removals as D9 tests fire; legacy `noise_signal.py` generators first
- [x] Core dependency list trimmed (2026-09-18): `click`, `colorama`, `requests`, `python-box`,
      `cachetools` were imported by nothing and are gone; `dynaconf` (mesh_world) and `pyassimp`
      (`hog_rendering.io.model_loader`, guarded) moved to the `gui` extra. What `large-worlds` now
      installs for a headless consumer such as SpriteJammer is numpy, scipy, trimesh, rtree, numexpr,
      pillow and pyfastnoiselite, each imported by `large_worlds` or `hog_color`
- [x] (2026-09-18: `ModelLoader` and `MeshHandler` moved whole to `large_worlds.mesh.io`, the
      `QObject` base was unused, `hog_rendering.io` re-exports, allowance list empty)
      Split the pure loading out of `hog_rendering.io` (it carries a Qt `QObject`) and move it down,
      so `Tile.load_mesh` stops reaching `hog_rendering` and the boundary test's one allowance goes away
- [x] wgpu spike (D8 step 1, plus the compute-pass question for 4.5 and section 7): **go**,
      2026-09-19, `Spikes/wgpu_tile/README.md`. A tile drawn through wgpu in a PySide6 window with
      its heights from a compute pass on the same device (readback matches numpy to 4.6e-5),
      `clip_range=(0, 1)` projection with the OpenGL trap pinned by test, imgui overlay. 3.2 ms/frame
      Python-bound at 16k and 262k vertices alike. `render` extra filled; `imgui-bundle<1.92.9`
      until wgpu's backend catches up
- [ ] wgpu backend seam and per-renderer ports (D8 steps 2 to 4), sized after the spike; ADR-012
  - [x] The seam (2026-09-19): `hog_rendering.wgpu.WgpuViewport` beside `BaseViewport` with the same
        renderer contract; camera controls shared through `viewport_controls`; the choice is the
        `viewport` capability on the ladder (`LARGE_WORLDS_VIEWPORT_BACKEND=wgpu`, opengl default);
        `CameraCore(clip_range=)` with the frustum planes generalised; the grid as the first pass
        (`GridPass` over the shared `grid_geometry`); smoke target `wgpu_grid`
  - [x] Tile pass (2026-09-19): `hog_rendering.wgpu.TilePass` with `TileRenderer`'s surface (terrain
        fill + edge wireframe + bounds; labels wait for the overlay); `WgpuMesh` over `MeshData`;
        colour formulas moved to `mesh/vertex_colors.py` and shared with `GPUMesh` (now `WgpuMesh`); bounds and edges
        from `world/tile_geometry.py`; `LineBatch` for per-frame lines; smoke target `wgpu_terrain`
  - [x] Points pass (2026-09-19): `hog_rendering.wgpu.PointPass` with `PointRenderer`'s batched-mode
        surface (per-tile instance buffer, a slot per bin, `mark_bins_dirty` incremental uploads,
        per-tile culling, the same `stats` keys); points are instanced round sprites of
        `point_size` pixels since WebGPU has no point size; smoke target `wgpu_points`
  - [x] Bins pass (2026-09-20): `hog_rendering.wgpu.BinPass` with `BinRenderer`'s surface; the colour
        rules and line geometry moved to `world/bin_geometry.py`, which `BinRenderer` now uses too;
        `LineBatch` learned alpha blending; bins join the `wgpu_points` smoke scene
  - [x] Camera pass (2026-09-20): `hog_rendering.wgpu.CameraPass` with `CameraRenderer.render`'s
        call; frustum, body, axes and look-at geometry moved to `camera/camera_geometry.py`, which
        `CameraRenderer` now draws from (one client-array draw per line-width group); in the
        `wgpu_points` smoke scene as the world's main camera seen from the demo camera
  - [x] Scene graph pass (2026-09-20): `hog_rendering.wgpu.ScenePass` walks a `Scene` like
        `SceneRenderer`; locator, transform and marker gizmos from
        `scene/renderers/gizmo_geometry.py`, which the PyOpenGL node renderers now draw from too;
        camera nodes through `camera_geometry`, grid nodes through `GridPass` under the node's
        matrix; marker labels reach the overlay below as `ScenePass.labels`; smoke target `wgpu_scene`
  - [x] imgui overlay (2026-09-20): `hog_rendering.wgpu.overlay.DebugOverlay` on `wgpu.utils.imgui`,
        owned by `WgpuViewport` (`~` toggles the debug window: frame time, mesh / point / bin stats,
        camera, world, render options, custom sections); world-space `Label`s projected to screen
        text give the grid its X/Z/Y letters, tiles their coordinates and markers their titles
  - [x] wgpu `WorldRenderer` (2026-09-20): `hog_rendering.wgpu.WgpuWorldRenderer` composes the passes
        behind `WorldRenderer`'s surface (now `WgpuWorldRenderer`) (same flags, toggles and sub-renderer names; the same draw
        order; LOD drain; labels for the overlay), builds the frame's view-projection with a `(0, 1)`
        clip range from any camera's lens; smoke target `wgpu_world` draws a synthetic world with
        every layer on
  - [x] Flip `visualize_synthetic_world.py` (2026-09-20): the visualizer's viewport logic is
        `WorldViewportMixin` over whichever base the ladder picks; `select(..., prefer=)` lets an app
        prefer a rung without forcing it (the env override still wins, and an unavailable preference
        falls back with the reason logged); the synthetic app's viewport prefers `wgpu`. Smoke target
        `synthetic` proves it got the wgpu rung where wgpu runs
  - [x] Flip `visualize.py` (2026-09-20): `WorldViewport` prefers `wgpu`; `MainWindow`'s redraws are
        backend-neutral (`update_viewport()`, and `redraw_now()` for the profiler's synchronous frame:
        `repaint()` on PyOpenGL, rendercanvas `force_draw()` on wgpu); smoke target `visualizer` asserts
        the rung and that points drew. Found on the flip: the legacy app's bins hold up to 1.5x the point
        density, over the 10 750-point slot both point renderers reserve; the PyOpenGL `TilePointVBO`
        clamps and drops the surplus silently, `PointPass` now reserves 1.5x the world's density and
        regrows a tile's slots (re-uploading its bins) if a bin still exceeds them
  - [x] Flip `mesh_world` (2026-09-20): `MeshWorldViewport` prefers `wgpu` and the controller builds
        its renderer through `backend.world_renderer_class(viewport_class(prefer="wgpu"))`; the
        `ScenePass` switches carry `NodeRenderer`'s thickness API and `CONFIG` so the app's renderer
        settings panel drives both rungs; the viewport no longer overrides `paintGL` (the renderer
        clears, the base draws the overlay); smoke target `mesh_world` asserts the rung and that the
        scene drew. Every app is on the wgpu rung where it runs
  - [x] The two GL-only widgets ported (2026-09-20), the prerequisite for the deletion: the model
        viewer app (`hog_tools/model_viewer/viewer.py`, a `WgpuViewport` over `wgpu.mesh_pass.MeshPass`:
        lit fill, wireframe overlay, backface wireframe as hidden edges) and `CameraViewport` (the
        camera editor's view, a `WgpuViewport` with a `GridPass`; render callbacks draw through
        `draw_lines`). `hog_rendering.camera` loads its widgets on first use so the package still
        imports without the render extra. Smoke targets `model_viewer` (a mesh drawn) and `camera_editor`
  - [x] Delete PyOpenGL (2026-09-21): the GL renderers (`world/*_renderer.py`, `tile_point_vbo`,
        `scene/scene_renderer.py` and the node renderers, `camera/camera_renderer.py`, `mesh/gpu_mesh.py`,
        `mesh/instanced_points.py`), `base_viewport.py`, `imgui_integration.py`, `config/render_settings.py`,
        the GLSL files, the `opengl` rung and the PyOpenGL dependency. The `gui` extra carries wgpu,
        rendercanvas and imgui-bundle; `render` is an alias of it. The shared geometry modules, styles and
        `vertex_colors` stay; `camera_geometry.scene_camera_style` and `world/point_colors.py` hold what the
        node renderers still supplied. Tests bound to the GL classes went with them (`test_rendering.py`,
        `test_terrain_color_modes.py`, the `opengl_*` parity tests), each covered by the wgpu tests that
        replaced them: `test_wgpu_world_renderer.py`, `test_wgpu_viewport.py`, `test_wgpu_mesh_pass.py`,
        `test_vertex_colors.py`, `test_lod.py` (ported to `TilePass` / `WgpuWorldRenderer`)
- [ ] GPU noise rung for grids (4.5), after the spike
- [ ] `hog_color` numba rung via `_ne_dispatch.py`, per operation, benchmarked (section 7)
- [ ] `hog_color` GPU stack, fragment form first (section 7)
- [ ] Noise Phase D (4D, derivatives, tileable) as terrain work asks for them
- [ ] Floor bump to whatever Maya ships next, with the sunset tests naming what it frees

## 6. Risks and open questions

- **The port is real work.** The 40-line benchmark kernel is a plain 2D simplex, not FastNoiseLite's
  OpenSimplex2. The measured speed should carry over (same arithmetic shape) but the port itself is
  the bulk of Phase 0, and its correctness rests on the vectors in 4.3.
- **fastmath across CPUs.** Identical here with and without; D3 chooses `fastmath=False` for noise
  so this never becomes a question. If a later profile wants it back, the vectors will say whether
  it is safe on the machines that matter.
- **numba release lag.** numba historically trails a new CPython by a few months. 0.67 already
  ships cp314 wheels, so 3.13 is not at risk. Note it for the next bump.
- **Cold-start on a fresh machine.** About 2.4 s once per cache. The activate scripts could prime
  it; decide in Phase 0 whether that is worth the noise in `activate.ps1`.
- **3.13 suite run.** Measured on 3.12. Must be repeated on 3.13 before Phase 1 merges.
- **Maya's own 3.11 has not been run.** The Maya contract in D1 was asserted from wheel availability
  and the code being 3.9-clean. The 3.11 CI leg added in F2 narrows that: the library packages import
  and pass on a clean CPython 3.11 with numpy 1.26, with no `gui` or `render` extras. It does not
  settle it. Maya ships its own interpreter build, its own `site-packages` and its own numpy, with
  PySide6/shiboken already loaded in the process -- none of which a GitHub runner reproduces. A Maya
  2026 smoke test (import `large_worlds`, sample one signal) inside `mayapy` is what closes that gap;
  **2026-09-17:** it is now a scheduled item in section 5's incremental track, and CI can never run it,
  since no runner has Maya. Until it has run once, the floor is demonstrated on generic 3.11 and still
  only asserted on Maya's.
- **Sunset discipline.** A sunset test that fails is only useful if the failure is acted on rather
  than skipped. The removal PR should be the fix; a `@pytest.mark.skip` on a sunset test is a
  review block.
- **wgpu inside Qt.** Drawn, with a compute pass and an overlay: `Spikes/wgpu_tile/` (2026-09-19, go).
- **Worlds change shape.** Accepted by decision, not a risk. The day something persists a world,
  the locked-vector version goes into its metadata so a stale world is detectable.

---

## 7. Further out: the same ladder for `hog_color`

Recorded so the noise decisions do not accidentally close it off. Nothing here is scheduled.

**Why it is the same problem.** A `ColorOperation` is an elementwise function over an N x 3 or
N x 4 float32 array with a handful of scalar parameters, which is the same shape as a noise kernel
over an N x 3 coordinate array. The use case that matters is large per-vertex colour arrays under
live editing: a slider moves, the stack re-evaluates from the changed operation, the viewport
repaints. Today that is numpy with a numexpr fast path above 100K elements (`_ne_dispatch.py`).

**numba, measured before believed.** numexpr already wins on the pure-arithmetic operations
(`aces`, `agx`, `reinhard`, `levels`, the sRGB conversions), and SpriteJammer measured numexpr at
only 1.23x on a workload where numba gave 23x, so the two are not interchangeable. numba's likely
wins in `hog_color` are the operations numexpr cannot express: per-pixel branching (`rgb_to_hsv`
and back, hue-dependent logic), lookups (gradient ramp evaluation, curves via `PchipInterpolator`
tables), and anything that is a loop today. The `_ne_dispatch.py` single dispatch point is already
the shape of a D9 ladder (`numpy`, `numexpr`, `numba`), so adopting it is a refactor of one file
plus per-operation kernels, each gated on the same benchmark bar as D3. `hog_color` keeps its
"pure numpy, no PySide6, no OpenGL, no LargeWorlds" contract; numba is an optional import there
exactly as in `large_worlds`.

**GPU, and where it has to live.** For live editing the right architecture is not "run the stack
faster on the CPU and re-upload", it is "keep the vertex colours resident on the GPU and run the
stack there". Two forms, both under wgpu:

- **Compute pass.** The stack as a sequence of WGSL compute kernels over a storage buffer, one per
  operation, parameters as uniforms. Maps directly onto `ColorOperationStack`'s partial cache:
  changing operation N re-runs kernels N onward on the GPU and touches nothing before it. Output
  is the colour buffer the mesh draws from, so the repaint is free.
- **Fragment pass.** The same operations applied at draw time in the terrain or mesh shader.
  Cheaper to prototype, zero extra buffers, but the result never exists as data, so anything that
  needs to read colours back (export, statistics, the thumbnails in `hog_color_ui`) still needs
  the compute form.

The GPU implementations cannot live in `hog_color`; that package must stay importable with no
graphics stack, which is what lets a DCC use it. They live beside the other WGSL kernels in
`hog_rendering` (or a `hog_color_gpu` package that imports `hog_color` and wgpu) and register as a
`color_stack_gpu` capability in the D9 ladder. `hog_color` gains only what the GPU side needs from
it: a stable per-operation parameter struct with fixed float32 layout, the same requirement 4.5
puts on `NoiseParams`, and an operation registry the GPU side can enumerate to know which
operations it has kernels for and which force a CPU fallback. The 4.3 comparison tooling applies
unchanged: CPU stack against GPU stack on the same input, difference sheet, human verdict,
portability row per operation. Tone mappers with `pow` and `exp` will match to a tolerance;
`levels`, channel maths and gradient lookups should match to float32 rounding.

**Order, if and when.** After the D8 spike proves a compute pass on the drawing device (the same
gate as 4.5). First candidate is the fragment form on the terrain shader, because it is a few
dozen lines of WGSL and immediately shows whether live editing at the target vertex counts is a
GPU problem or a UI-event problem. The compute form follows only if the fragment form shows the
GPU is the bottleneck, which at per-vertex scale it may not be.

---

## Appendix A. Reproducing the measurements

```powershell
# Scratch venv on 3.13 with numba and pyfastnoiselite
uv venv --python 3.13 py313
uv pip install --python py313/Scripts/python.exe "numpy>=2" numba pyfastnoiselite

# FastNoiseSIMD from source on 3.13 (the escape hatch, not the plan)
uv pip install --python py313/Scripts/python.exe setuptools
uv pip install --python py313/Scripts/python.exe --no-build-isolation --no-binary pyfastnoisesimd pyfastnoisesimd

# Wheel-only resolution check
uv pip compile --python-version 3.13 --python-platform windows --no-build requirements.in

# Suite on the new stack (repo root, packages on PYTHONPATH)
$env:PYTHONPATH = "D:\Depot\LargeWorlds\Build\ArtTools\hog-py-packages"
py313\Scripts\python.exe -m pytest --no-cov -p no:cacheprovider -m "not slow and not benchmark"
```

Benchmark scripts generate four coordinate sets (4 096, 65 536, 512x512, 1024x1024 points), run the
binding or kernel at 1 and 4 octaves, and report the best of five. The parity script samples 4 096
points at seed 12345, 4 octaves FBm, single worker, for `np.array_equal` across interpreters. The
numba determinism script compares parallel, serial, fastmath and exact variants on 1M points.

## Appendix B. What the SpriteJammer note got right

- The Python pin and the wgpu port are one problem, and the noise library is the pin.
- The clip-space convention in `camera_data.py` is a wrong-depth bug waiting to happen.
- `culling.py`'s module-level import of `hog_rendering.camera.Camera` must break for a wgpu port.
- Writing `FastNoiseLiteSignal` against `BaseSignal` with no `sj_*` imports was the right shape; it
  becomes the `pyfastnoiselite` rung of D4.
- Its numba discipline (section 2.7) is adopted here as D3, almost unchanged.
