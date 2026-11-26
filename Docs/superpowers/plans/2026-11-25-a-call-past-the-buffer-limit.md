# A call past the device's buffer limit: refused before any upload, in the caller's terms

**Status:** Proposed 2026-11-25. Option A of three, on the owner's "Yes" (refuse before any upload, not chunk, not
document only). Decisions D2 to D7 are recommendations. Trial-run in task order before proposing (*The trial*, below),
and again after Copilot's review moved `sample_grid`'s `Grid` upload after the check (D7).
**Board:** [`2026-11-21-a-call-past-the-devices-buffer-limit`](../../plan/board/2026-11-21-a-call-past-the-devices-buffer-limit.md)

> **For agentic workers:** REQUIRED SUB-SKILL: use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to carry this out task by task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** a wgpu-rung call with more points than the device binds in one buffer is refused before anything is
uploaded, with a `ValueError` that names the call, the most points it can take on this adapter and the adapter, the
same on every back end.

**Architecture:** `gpu._Gpu` reads the device's limit once, the smaller of `max-storage-buffer-binding-size` and
`max-buffer-size`. `_Gpu.run`, through which every call passes, checks the output's bytes against it after the axes'
lengths and before any buffer is made. The output is the largest buffer a call makes (`n * width * 4` bytes, where an
axis is `n * 4`), so one check covers every buffer. `sample_grid` uploaded its `Grid` uniform before calling `run`;
it now passes the packed bytes, and `run` uploads them after the check, so no call uploads anything before it.

**Tech stack:** Python 3.11 to 3.13, numpy, wgpu 0.33 (the `gpu` group); pytest through the `pytest` console script
(`uv run pytest`, never `python -m pytest`); `make check` as the gate.

---

## Before you start

- Read [the row](../../plan/board/2026-11-21-a-call-past-the-devices-buffer-limit.md) and gap 7 of [the
  account](../../design/2026-11-20-gpu-fast-track-account.md).
- Read [the project ledger](../../standards/failure-modes-project.md), above all P-14 (never `python -`), P-23 (a plan's
  code is trial-run in task order) and P-27 (a fact a change makes untrue is searched for as a concept, in several
  wordings, across every documents folder).
- Work in a worktree on a branch from `origin/main`, with `uv sync --all-packages --all-extras --group dev`. Commits are
  signed off (`git commit -s`) with the owner's identity and no AI attribution; write each message to a file and pass
  it with `-F`. Stage named paths, never `git add -A` or `-u`. Revert `vectors/portability.md` if the gate re-stamps it.
- The commands are written for bash (Git Bash). A GPU step needs an adapter; `HOG_NOISE_REQUIRE_GPU=1` turns its skip
  into a failure.
- **One pull request**, Tasks 1 to 4.

## Facts this plan rests on

Measured on the RTX 5090 machine (Windows 11 Pro 10.0.26300) at `3a83792` (the merge of
[PR #59](https://github.com/HogJonny-AMZN/HogNoise/pull/59)), wgpu 0.33.0, by scripts run with
`uv run --no-sync python -I`:

- **Every adapter here binds at most 2,147,483,644 bytes** (`max-storage-buffer-binding-size`): the 5090 on Vulkan,
  D3D12 and OpenGL, and WARP. `max-buffer-size` is 2,147,483,647 on D3D12 and OpenGL and 1 TiB on Vulkan. The device
  `gpu.device()` makes (`request_device_sync()`, no limits asked) gets the adapter's own. So one call takes at most
  536,870,911 points writing one float a point, 268,435,455 writing two (`warp_points_2d`) and 178,956,970 writing three
  (`warp_points`).
- **One point past it, wgpu refuses, and nothing worse happens.** On WARP and on the 5090's Vulkan, an axis past the
  limit (`sample_points_2d`, 536,870,912 points) and an output past it (`warp_points`, 178,956,971 points) each raised
  `wgpu.GPUValidationError` in 0.4 to 2.3 s, and a small call on the same device then ran. No wrong answer and no crash.
- **The error is in wgpu's terms and differs by back end.** On D3D12, `wgpuDeviceCreateBuffer`: "Buffer size
  2147483652 is greater than the maximum buffer size (2147483647)". On Vulkan, `wgpuDeviceCreateBindGroup`: "Buffer
  binding 5 range 2147483652 exceeds `max_*_buffer_binding_size` limit 2147483644". Neither names the argument, the
  points or the most a call may take, and the axes are uploaded first.
- **A device asked for WebGPU's defaults gets them:** `required_limits` of 134,217,728 and 268,435,456 bytes gave a WARP
  device exactly those. `device.adapter_info["device"]` names the adapter.
- **`_Gpu.run` is the one path:** every `GpuSampler` call (`sample_points`, `sample_points_2d`, `sample_grid`,
  `warp_points`, `warp_points_2d`) reaches it with `n` and `width`, after `_point_count` (`gpu.py:161`) has checked the
  lengths. Inside `run`, the first upload is `self.storage(a)` for the axes (`gpu.py:242`), then the output's
  `create_buffer` (`gpu.py:243`). One upload comes before `run`: `sample_grid` makes its `Grid` uniform with
  `self._gpu.uniform(pack_grid(...))` (`gpu.py:314`) and passes the buffer (Copilot's review of this plan, D7).
  `GpuSampler.__init__` uploads `Params` once (`gpu.py:276`), when the sampler is made, not on a call.

## Files

| File | Change |
| --- | --- |
| `packages/python/hog-noise/src/hog_noise/gpu.py` | `_Gpu.binding_limit`, `_Gpu.max_points`, the check in `_Gpu.run`; `run` uploads the `Grid` after it; `__updated__` |
| `packages/python/hog-noise/tests/test_gpu.py` | three tests (nine cases) and the fixture |
| `README.md` | *On the GPU*: the refusal; *Limits*: the most points a call takes |
| the row, the account, the handoff, the journal | Task 4 |

### Task 1: the tests, failing

**Files:** Modify: `packages/python/hog-noise/tests/test_gpu.py` (append at the end)

- [ ] **Step 1:** append:

```python
def test_the_limit_is_the_devices_own(device):
    """The smaller of the two limits a call's buffers meet: one storage binding, and one buffer."""
    limits = device.limits
    expected = min(limits["max-storage-buffer-binding-size"], limits["max-buffer-size"])
    assert gpu._Gpu.get().binding_limit == expected


#: WebGPU's default binding limit, 128 MiB, put in place of the device's own (2 GiB on the adapters measured): the
#: refusal is the same code at any limit, and a call past this one needs no memory to build.
SMALL_LIMIT = 134_217_728


class Uploaded(Exception):
    """A call reached its first upload: the limit's check let it through."""


@pytest.fixture
def small(device, monkeypatch):
    """
    A sampler on the process's `gpu._Gpu`, its limit lowered to `SMALL_LIMIT`. The sampler is made first, since making
    it uploads its own `Params`; then every upload, storage and uniform, is stopped: a call that reaches one has been
    let through the check, and nothing is computed either way.
    """
    gpu_ = gpu._Gpu.get()
    monkeypatch.setattr(gpu_, "binding_limit", SMALL_LIMIT)
    sampler = gpu.GpuSampler(NoiseParams(frequency=0.01))

    def stop(data):
        raise Uploaded

    monkeypatch.setattr(gpu_, "storage", stop)
    monkeypatch.setattr(gpu_, "uniform", stop)
    return sampler


def _lazy(n):
    """``n`` float32 zeros that take no memory: a call past the limit is refused before it reads them."""
    return np.broadcast_to(np.float32(0), (n,))


CALLS = {
    "sample_points": (1, lambda s, a: s.sample_points(a, a, a, _lazy(len(a)))),
    "sample_points_2d": (1, lambda s, a: s.sample_points_2d(a, a, _lazy(len(a)))),
    "sample_grid": (1, lambda s, a: s.sample_grid((0, 0, 0), (len(a), 1, 1))),
    "warp_points": (3, lambda s, a: s.warp_points(a, a, a)),
    "warp_points_2d": (2, lambda s, a: s.warp_points_2d(a, a)),
}


@pytest.mark.parametrize("name", list(CALLS))
def test_a_call_past_the_devices_limit_is_refused_before_any_upload(small, name):
    """
    Past the limit wgpu refuses too, but in its own terms (a buffer size, a binding number) that differ by backend,
    and only after the axes are uploaded. The refusal names the call, the most points it takes and the adapter, and
    comes before any upload: an axis's, and `sample_grid`'s `Grid`.
    """
    width, call = CALLS[name]
    most = SMALL_LIMIT // (4 * width)
    with pytest.raises(ValueError, match=f"past the {most:,} one call can take on .+ split the call"):
        call(small, _lazy(most + 1))


@pytest.mark.parametrize("name", ["sample_points_2d", "sample_grid", "warp_points"])
def test_a_call_at_the_devices_limit_is_let_through(small, name):
    """Not one point early: a call writing exactly the limit's bytes passes the check and reaches its upload."""
    width, call = CALLS[name]
    with pytest.raises(Uploaded):
        call(small, _lazy(SMALL_LIMIT // (4 * width)))
```

- [ ] **Step 2:** run them, and see them fail:

```bash
HOG_NOISE_REQUIRE_GPU=1 uv run pytest packages/python/hog-noise/tests/test_gpu.py -n 0 -q -k "devices_limit or devices_own"
```

Expected: `1 failed, 8 errors`, each on `_Gpu` having no `binding_limit`.

- [ ] **Step 3:** commit (`CI proof follow-on, task 1: a call past the buffer limit, tests first`).

### Task 2: the check

**Files:** Modify: `packages/python/hog-noise/src/hog_noise/gpu.py`

- [ ] **Step 1:** at the end of `_Gpu.__init__`, after `self.no_grid = self.uniform(bytes(48))`, add:

```text
        # the most bytes one buffer may hold and one binding may see: the output, the largest buffer a call makes, is
        # checked against it before any upload
        self.binding_limit = min(dev.limits["max-storage-buffer-binding-size"], dev.limits["max-buffer-size"])

    def max_points(self, width: int) -> int:
        """The most points one call writing ``width`` floats a point may take on this device."""
        return self.binding_limit // (4 * width)
```

- [ ] **Step 2:** `_Gpu.run` takes the `Grid` as bytes and uploads it after the check. Its signature's last parameter
  becomes `grid: bytes | None = None`, and its docstring and its body down to the bind group become:

```text
        """
        Dispatch ``entry`` over ``n`` points and read back ``n * width`` floats. ``grid`` is the packed `Grid`
        (`pack_grid`), uploaded here after the checks, like every buffer a call makes.

        :raises ValueError: An axis whose length is not ``n``, or more points than the device binds in one call (both
            checked before any GPU work).
        """
        if axes and _point_count(axes) != n:
            raise ValueError(f"the axes have {len(axes[0])} points, not {n}")
        if n == 0:
            return np.empty(0, np.float32)
        if n > self.max_points(width):
            adapter = self.device.adapter_info.get("device")
            raise ValueError(
                f"{entry}: {n:,} points is past the {self.max_points(width):,} one call can take on {adapter}, which "
                f"binds at most {self.binding_limit:,} bytes a buffer ({width} float32 a point out): split the call"
            )
        wgpu, dev = self.wgpu, self.device
        grid_buffer = self.uniform(grid) if grid is not None else self.no_grid
        coords = [self.storage(a) for a in axes] + [self.unused] * (3 - len(axes))
        out = dev.create_buffer(size=n * width * 4, usage=wgpu.BufferUsage.STORAGE | wgpu.BufferUsage.COPY_SRC)
        buffers = [params_buffer, self.tables, *coords, out, grid_buffer]
```

- [ ] **Step 3:** in `GpuSampler.sample_grid`, pass the bytes, not a buffer:

```text
        grid = pack_grid(start, shape, scales)
        return self._gpu.run("sample_grid", self._params, (), math.prod(shape), 1, grid).reshape(shape)
```

and set `__updated__` to the day. `sample_grid` is `run`'s only caller with a `Grid` (`grep -rn "_Gpu\b\|\._gpu\."`
over `packages`, `apps` and `Spikes` finds none outside `gpu.py` and its tests).

- [ ] **Step 4:** run Task 1's command. Expected: `9 passed`. Then the whole file,
  `HOG_NOISE_REQUIRE_GPU=1 uv run pytest packages/python/hog-noise/tests/test_gpu.py -n 0 -q`: every test passes,
  `test_a_power_of_two_grid_equals_its_points_bit_for_bit` among them, which runs `sample_grid` through the moved upload.
- [ ] **Step 5:** each mutant of the check, applied alone, fails its tests (a script that applies one, runs Task 1's
  command and restores `gpu.py` byte for byte):
  - `if n > self.max_points(width):` to `if False:`: 5 failed (every refusal);
  - `>` to `>=`, one point early: 3 failed (each at the limit);
  - `binding_limit` from `max-buffer-size` alone: 1 failed on any adapter whose two limits differ (every one measured);
  - the `grid_buffer` line moved above the check: 1 failed (`sample_grid`'s refusal).
- [ ] **Step 6:** the real refusal, past the real limit: the probe calls of *Facts* (`sample_points_2d` at 536,870,912
  points, `warp_points` at 178,956,971) on WARP and on any hardware adapter at hand now raise the `ValueError` in under
  0.1 s, and a small call then runs.
- [ ] **Step 7:** `make check`, unpiped. Commit (`... task 2: refused before any upload, in the caller's terms`).

### Task 3: the README

**Files:** Modify: `README.md`

- [ ] **Step 1:** in *On the GPU*, after the sentence ending "since a loop that long can stall the device.", add:
  "A call with more points than the device binds in one buffer is refused before anything is uploaded, naming the
  most it can take. On an RTX 5090 and on WARP, the adapters measured, a buffer holds 2 GiB: 536,870,911 points a call,
  268,435,455 for `warp_points_2d` and 178,956,970 for `warp_points`, which write two and three floats a point. Split a
  larger call; the rung does not split it for you."
- [ ] **Step 2:** in *Limits*, in the bullet beginning "The GPU rung is float32", after "It is not benchmarked.", add:
  "One call takes at most what the device binds in one buffer (2 GiB on the RTX 5090 and WARP), and a larger one is
  refused, not split."
- [ ] **Step 3:** P-27: search `Docs/`, `README.md`, `llms.txt`, `packages/` and `vectors/` for the limit as a concept
  ("buffer limit", "binding size", "2 GiB", "536", "chunk", "too many points") and correct any sentence the refusal
  makes untrue. At `3a83792`, `grep -rn -i` for them over those folders' `.md` and `.txt` (the journal aside) finds the
  row (lines 1, 10, 11), the account (lines 31, 68, 110, 133) and the handoff (lines 9, 25), all of which Task 4
  updates, and two unrelated hits: CPU chunking in `Docs/DETAILED_FASTNOISE_PERF.md` and the free-threaded row in
  `Docs/plan/board/2026-11-15-numpy-2-modernisation.md`. None is untrue before Task 4.
- [ ] **Step 4:** `make check`. Commit (`... task 3: the README says what a call past the limit gets`).

### Task 4: the records, the review, the pull request

- [ ] **Step 1:** the row: `State:` Landed with the pull request, `Section:` now. The account: a line under *Since the
  account* that gap 7 is closed, with the pull request. The handoff: the lead, and the order's next item (PyPI, on the
  owner's go). The journal. The plan's ticks and a *Built* table.
- [ ] **Step 2:** the deliberate review (`local-review`, diff mode); answer every finding in the pull request's *Review*.
- [ ] **Step 3:** push, open the pull request from `.github/pull_request_template.md`, read CI (`gh pr checks <n>
  --watch`), and assess Copilot's review when it arrives (`review-and-pr`). The owner merges.

## The trial

Run 2026-11-25 on the 5090 machine, from a worktree at `3a83792`, in task order: the tests alone, then with the check.
Run twice: as first proposed, and again after Copilot's review on
[PR #60](https://github.com/HogJonny-AMZN/HogNoise/pull/60) found `sample_grid`'s `Grid` uploaded before the check
(D7). The second trial's tests, run first against the first trial's code, failed on exactly that case
(`sample_grid`'s refusal: 1 failed, 8 passed). The table is the second trial's, except where a row says otherwise.

| Step | Result |
| --- | --- |
| Task 1, step 2 | `1 failed, 8 errors`, each `AttributeError` on `binding_limit` |
| Task 2, step 4 | `9 passed` on the 5090's Vulkan; the whole `test_gpu.py`, 35 passed on the 5090's Vulkan and on WARP (`HOG_NOISE_WGPU_ADAPTER="Microsoft Basic Render Driver"`) |
| Task 2, step 5 | on the 5090's Vulkan: no check, 5 failed; one point early, 3 failed; `max-buffer-size` alone, 1 failed; the `Grid` uploaded before the check, 1 failed; `gpu.py` restored |
| Task 2, step 6 | the first trial, the points calls unchanged since: on the 5090's Vulkan, `ValueError` in 0.0 s for both calls, then a small call ran. The message: "sample_points_2d: 536,870,912 points is past the 536,870,911 one call can take on NVIDIA GeForce RTX 5090, which binds at most 2,147,483,644 bytes a buffer (1 float32 a point out): split the call" |
| The cost | the new tests take under 0.01 s each; the process's pipelines, which the suite builds anyway, are the only setup (76 s on WARP) |
| A real device at its limit | an earlier form of the tests made a second device with the default limits and ran `sample_points_2d` at exactly 33,554,432 points on WARP: it ran (26 s) and its last points were finite. Dropped from the standing tests for its cost (D5) |

## Decisions

| # | Decision | Recommended | Alternative | Why |
| --- | --- | --- | --- | --- |
| D1 | What a call past the limit gets | Refused before any upload (option A, the owner's "Yes") | Split into chunks (B); wgpu's own error, documented (C) | The first public caller past the limit gets a message they can act on, the same on every back end, without 2 GB uploaded first. B changes behaviour and costs three times as much; it can be an Icebox row if a caller asks |
| D2 | The exception | `ValueError`, as `run` already raises for an axis of the wrong length | A new `GpuLimitError` | It is a value the caller passed; a new type is public API to keep for one check |
| D3 | The limit | The smaller of `max-storage-buffer-binding-size` and `max-buffer-size` | The binding limit alone | The output is both bound and read back through a buffer of its own size; on D3D12 and OpenGL the buffer limit is the one wgpu named |
| D4 | A public "most points" | Not now: `_Gpu.max_points` is private, and the message gives the number | `GpuSampler.max_points(width)` | A public function is kept forever once on PyPI; a caller who splits can be given one when one asks |
| D5 | How the standing tests reach the limit | Lower `binding_limit` on the process's device and stop at the first upload: nothing computed, no second device | A second device with the default limits, run at its limit | The second device cost 86 s to build its pipelines on WARP and 26 s to run, about 2 min on a leg already 7 min; the boundary on a real device is in *The trial*, and the mutants show the check is exact |
| D6 | The name in the message | The entry point (`warp_points_3d`), which `run` has | The Python method (`warp_points`) | One fewer table; the entry point names the method plainly. Cheap to change if the review prefers the method |
| D7 | Where `sample_grid`'s `Grid` is uploaded | In `run`, after the check: `run` takes the packed bytes | Keep the upload in `sample_grid`, and check there too | One check and one place where a call's buffers are made; the `Grid` was the one upload outside `run`. Found by Copilot's review of this plan |

## Terms introduced

None. Checked: *rung* and *GPU adapter* have glossary rows; "the device's limit" is wgpu's own term, used in its plain
sense.
