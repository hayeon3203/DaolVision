"""
Prometheus metrics for the HunyuanVideo server.

Exposes two families:
  - generation telemetry: current step / total steps / per-step seconds /
    elapsed / last duration / counts  (the stuff we used to read from logs)
  - system stability: GPU util/power/mem/temp + system RAM/swap

GPU is read via NVML (pynvml). On GB10 the memory is unified, so system RAM
(psutil) is the meaningful "is memory stable" signal; GPU mem is best-effort.
"""

import time
import threading

import psutil
from prometheus_client import Gauge, Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

try:
    import pynvml
    pynvml.nvmlInit()
    _GPU = pynvml.nvmlDeviceGetHandleByIndex(0)
except Exception:  # noqa: BLE001
    pynvml = None
    _GPU = None

# ---- generation telemetry -------------------------------------------------
GEN_IN_PROGRESS = Gauge("hyv_generation_in_progress", "1 while a generation is running")
GEN_CURRENT_STEP = Gauge("hyv_generation_current_step", "current denoising step of the running job")
GEN_TOTAL_STEPS = Gauge("hyv_generation_total_steps", "total denoising steps of the running job")
GEN_LAST_STEP_SECONDS = Gauge("hyv_generation_last_step_seconds", "seconds the last completed step took")
GEN_ELAPSED_SECONDS = Gauge("hyv_generation_elapsed_seconds", "elapsed seconds of the running job")
GEN_LAST_DURATION = Gauge("hyv_generation_last_duration_seconds", "duration of the last finished job", ["kind"])
GEN_TOTAL = Counter("hyv_generations_total", "finished generations", ["kind", "status"])
GEN_DURATION = Histogram(
    "hyv_generation_duration_seconds", "generation wall time", ["kind"],
    buckets=(30, 60, 120, 240, 360, 600, 900, 1800, 3600),
)
STEP_DURATION = Histogram(
    "hyv_step_duration_seconds", "per-step wall time",
    buckets=(5, 10, 20, 30, 45, 60, 80, 100, 140, 200),
)

# ---- system / GPU ---------------------------------------------------------
GPU_UTIL = Gauge("hyv_gpu_utilization_percent", "GPU utilization")
GPU_POWER = Gauge("hyv_gpu_power_watts", "GPU power draw")
GPU_MEM_USED = Gauge("hyv_gpu_memory_used_bytes", "GPU memory used (best effort; unified on GB10)")
GPU_TEMP = Gauge("hyv_gpu_temperature_celsius", "GPU temperature")
SYS_MEM_USED = Gauge("hyv_system_memory_used_bytes", "system RAM used")
SYS_MEM_AVAIL = Gauge("hyv_system_memory_available_bytes", "system RAM available")
SYS_SWAP_USED = Gauge("hyv_system_swap_used_bytes", "swap used (high = thrashing risk)")

_lock = threading.Lock()
_state = {"start": None, "last_step_t": None, "running": False}


def generation_start(total_steps: int):
    with _lock:
        _state.update(start=time.time(), last_step_t=time.time(), running=True)
    GEN_IN_PROGRESS.set(1)
    GEN_TOTAL_STEPS.set(total_steps)
    GEN_CURRENT_STEP.set(0)
    GEN_LAST_STEP_SECONDS.set(0)
    GEN_ELAPSED_SECONDS.set(0)


def step_tick():
    """Called once per completed denoising step (via scheduler.step wrapper)."""
    now = time.time()
    with _lock:
        last = _state["last_step_t"]
        _state["last_step_t"] = now
    GEN_CURRENT_STEP.inc()
    if last is not None:
        d = now - last
        GEN_LAST_STEP_SECONDS.set(d)
        STEP_DURATION.observe(d)


def generation_end(kind: str, status: str, duration: float):
    with _lock:
        _state.update(running=False, start=None, last_step_t=None)
    GEN_IN_PROGRESS.set(0)
    GEN_CURRENT_STEP.set(0)
    GEN_ELAPSED_SECONDS.set(0)
    GEN_TOTAL.labels(kind=kind, status=status).inc()
    if status == "success":
        GEN_LAST_DURATION.labels(kind=kind).set(duration)
        GEN_DURATION.labels(kind=kind).observe(duration)


def wrap_scheduler(pipe):
    """Hook scheduler.step so every denoising step increments the step gauge."""
    sched = getattr(pipe, "scheduler", None)
    if sched is None or getattr(sched, "_hyv_wrapped", False):
        return
    orig = sched.step

    def wrapped(*args, **kwargs):
        out = orig(*args, **kwargs)
        try:
            step_tick()
        except Exception:  # noqa: BLE001
            pass
        return out

    sched.step = wrapped
    sched._hyv_wrapped = True


def _refresh():
    if _GPU is not None:
        try:
            GPU_UTIL.set(pynvml.nvmlDeviceGetUtilizationRates(_GPU).gpu)
        except Exception:  # noqa: BLE001
            pass
        try:
            GPU_POWER.set(pynvml.nvmlDeviceGetPowerUsage(_GPU) / 1000.0)
        except Exception:  # noqa: BLE001
            pass
        try:
            GPU_MEM_USED.set(pynvml.nvmlDeviceGetMemoryInfo(_GPU).used)
        except Exception:  # noqa: BLE001
            pass
        try:
            GPU_TEMP.set(pynvml.nvmlDeviceGetTemperature(_GPU, pynvml.NVML_TEMPERATURE_GPU))
        except Exception:  # noqa: BLE001
            pass
    vm = psutil.virtual_memory()
    sw = psutil.swap_memory()
    SYS_MEM_USED.set(vm.used)
    SYS_MEM_AVAIL.set(vm.available)
    SYS_SWAP_USED.set(sw.used)
    with _lock:
        if _state["running"] and _state["start"]:
            GEN_ELAPSED_SECONDS.set(time.time() - _state["start"])


def render():
    """Refresh live gauges and return Prometheus exposition text + content type."""
    _refresh()
    return generate_latest(), CONTENT_TYPE_LATEST
