# inference_server

Host-GPU inference servers (FastAPI) for the DaolVision studio, tuned for the
**NVIDIA GB10 / Grace-Blackwell (DGX Spark)** unified-memory platform.

> **Backend: FLUX.1-schnell.** Dedicated text-to-image server for the agent's
> "generate anchor image" step. Video generation (T2V/I2V) is handled separately
> by LTX-Video-0.9.8-13B-distilled via ComfyUI (:8188) — not part of this
> directory. The old Wan2.2-TI2V-5B video server (`server.py`, :8500) and the
> Wan2.2-Animate server (`animate_server.py`, :8600) that used to live here were
> both removed as dead code once `langgraph/` stopped calling them (see git
> history / `.harness/STATE.md`).

## Components

| File | Purpose |
|------|---------|
| `flux_server.py` | FastAPI server. `POST /generate` (T2I), `/health`, `/outputs/<file>.png`. |
| `run_flux.sh` | Start script (env defaults + launch). |
| `bench_t2i.py` | One-shot T2I benchmark harness used to pick the FLUX.1-schnell model (see file docstring). |
| `metrics.py` | Prometheus metrics (per-step timing, generation duration, GPU/RAM). |
| `deploy/flux.service` | systemd user unit for `run_flux.sh`. |
| `monitoring/` | Prometheus + Grafana dashboard for the `/metrics` endpoint. |
| `editing/` | `make_ad.sh` — standalone shell pipeline that concatenates clips with Korean subtitles + BGM (unrelated to the inference server; see `editing/README.md`). |

## Run

```bash
python -m venv .venv && source .venv/bin/activate
pip install "diffusers>=0.39.0.dev0" torch transformers accelerate \
            fastapi uvicorn pillow prometheus-client psutil pynvml
./run_flux.sh
```

Server listens on `http://0.0.0.0:8501`.

### Environment variables

| Var | Default | Meaning |
|-----|---------|---------|
| `FLUX_MODEL_PATH` | `black-forest-labs/FLUX.1-schnell` | model repo / local path |
| `FLUX_WIDTH` / `FLUX_HEIGHT` | `1024` / `1024` | default frame size (overridable per request) |
| `FLUX_STEPS` | `4` | schnell's distilled step count |
| `FLUX_KEEP_RESIDENT` | `0` | `0` = unload after every request (coexist with comfyui.service); `1` only if no other GPU-heavy service needs the freed headroom |
| `HYV_HOST` / `HYV_PORT` | `0.0.0.0` / `8501` | bind address |

### API

```
POST /generate   {prompt, [width, height, num_inference_steps, seed]}
GET  /health  GET /outputs/<file>.png
```
