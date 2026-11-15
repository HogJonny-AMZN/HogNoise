"""
HogNoise: the wgpu rung, every noise in WGSL on whatever adapter wgpu finds. Override only: never chosen by the ladder.
Package: hog_noise/gpu

`wgpu` is imported inside the functions here and never at the top, so importing `hog_noise`, or using any other rung,
never loads it (Docs/standards/python-project.md, *The package boundary*). One device per process, made on first use
and kept with its pipelines. Spec: Docs/superpowers/specs/2026-11-14-gpu-port.md.
"""

import logging as _logging
import os

_MODULE_NAME = "hog_noise.gpu"
__version__ = "0.1.0"
__updated__ = "2026-11-14"
_LOGGER = _logging.getLogger(_MODULE_NAME)

#: Part of an adapter's name: the first adapter whose name contains it is used instead of wgpu's default.
ADAPTER_ENV = "HOG_NOISE_WGPU_ADAPTER"

#: The process's one device and its adapter's description, made on first use.
_STATE: dict[str, object] = {}


def _wgpu():
    """The wgpu module, or a RuntimeError naming the extra that installs it."""
    try:
        import wgpu
    except ImportError as e:
        raise RuntimeError("wgpu is not installed: install hog-noise[gpu]") from e
    except OSError as e:  # installed, but its native library will not load here
        raise RuntimeError(f"wgpu cannot load its native library: {e}") from e
    return wgpu


def _pick_adapter(wgpu):
    wanted = os.environ.get(ADAPTER_ENV, "").strip()
    if wanted:
        adapters = wgpu.gpu.enumerate_adapters_sync()
        for adapter in adapters:
            if wanted.lower() in str(adapter.info.get("device", "")).lower():
                return adapter
        found = [f"{a.info.get('device')} ({a.info.get('backend_type')})" for a in adapters]
        raise RuntimeError(f"no adapter: none named like {wanted!r} ({ADAPTER_ENV}); found {found}")
    try:
        adapter = wgpu.gpu.request_adapter_sync(power_preference="high-performance")
    except Exception as e:  # wgpu raises its own error types when no adapter exists
        adapter, cause = None, f"{type(e).__name__}: {e}"
    else:
        cause = "wgpu chose none"
    if adapter is None:
        try:
            found = [
                f"{a.info.get('device')} ({a.info.get('backend_type')})" for a in wgpu.gpu.enumerate_adapters_sync()
            ]
        except Exception as e:  # the list is for the message; failing to make it must not hide the cause
            found = [f"cannot list adapters: {e}"]
        raise RuntimeError(f"no adapter: {cause}; found {found}; name one in {ADAPTER_ENV}")
    return adapter


def device():
    """
    The process's one device, made on first use and kept.

    :raises RuntimeError: Naming why there is none: wgpu missing, or no adapter (or none matching `ADAPTER_ENV`).
    """
    if "device" not in _STATE:
        wgpu = _wgpu()
        adapter = _pick_adapter(wgpu)
        try:
            _STATE["device"] = adapter.request_device_sync()
        except Exception as e:  # an adapter that will not give a device is no adapter
            raise RuntimeError(f"no device from {adapter.info.get('device')}: {type(e).__name__}: {e}") from e
        _STATE["info"] = {k: adapter.info.get(k) for k in ("device", "backend_type", "adapter_type", "vendor")}
        info = _STATE["info"]
        _LOGGER.info(f"wgpu adapter: {info['device']} ({info['backend_type']}, {info['adapter_type']})")
    return _STATE["device"]


def adapter_info() -> dict[str, object]:
    """The chosen adapter's name, back end, type and vendor, making the device if it is not made yet."""
    device()
    return dict(_STATE["info"])


def is_available() -> bool:
    """The ladder's probe: makes the device, or raises with the cause so the ladder's message carries it."""
    device()
    return True


if __name__ == "__main__":
    _logging.basicConfig(level=_logging.INFO)
    try:
        print(adapter_info())
    except RuntimeError as e:
        print(f"no GPU here: {e}")
