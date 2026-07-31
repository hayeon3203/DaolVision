# hunyuanvideo-pipeline

Video generation inference server (FastAPI) with Open WebUI integration, tuned for
the **NVIDIA GB10 / Grace-Blackwell (DGX Spark)** unified-memory platform.

> **Backend: Wan2.2-TI2V-5B.** A single 5B checkpoint serves **both** text-to-video
> (T2V) and image-to-video (I2V). It replaced the original HunyuanVideo 1.5 setup
> (two ~44GB models that could not coexist on the 119GB GB10); Wan keeps one shared
> ~23GB weight set for both modes and runs ~6.7× faster per step on this hardware.
> The repo name is kept for continuity.

## Components

| File | Purpose |
|------|---------|
| `server.py` | FastAPI server. `POST /generate` (T2V), `POST /generate_i2v` (I2V), `POST /cancel`, `/health`, `/metrics`. Loads `WanPipeline` once; the I2V pipeline reuses its components (no extra memory). |
| `run.sh` | Start script (env defaults + launch). |
| `hunyuanvideo_pipeline.py` | Open WebUI **Pipelines** plugin. Routes chat (with/without image) to the server; streams heartbeats so a user "stop" calls `POST /cancel`. |
| `openwebui_function.py` | Open WebUI **Function** variant of the integration. |
| `metrics.py` | Prometheus metrics (per-step timing, generation duration, GPU/RAM). |
| `monitoring/` | Prometheus + Grafana dashboard for the `/metrics` endpoint. |

## Why Wan2.2-TI2V-5B on GB10

- **One model, both modes.** `WanPipeline` (T2V) and `WanImageToVideoPipeline` (I2V)
  share the same transformer / umT5 text encoder / VAE. I2V conditions on the image
  via VAE-latent concatenation (no separate image encoder).
- **Fast.** ~3.3 s/step at 832×480 (vs ~21.5 s/step for HunyuanVideo) — the Wan VAE
  (16× spatial) plus transformer `patch_size=2` yields far fewer tokens, so the
  attention memory traffic that bottlenecks the bandwidth-bound GB10 drops sharply.
- **Memory-light.** One shared ~23GB weight set covers T2V+I2V, so no swap / pipeline
  juggling. **Important:** share components with the constructor
  `WanImageToVideoPipeline(**t2v.components, expand_timesteps=t2v.config.expand_timesteps)` —
  `from_pipe()` silently duplicates the weights (+34GB) and triggers a ~3× slowdown.
- **Attention.** flash-attn is broken on Blackwell, so SDPA is forced via
  `set_attention_backend("native")` / `DIFFUSERS_ATTENTION_BACKEND=native`.

## Run

```bash
python -m venv .venv && source .venv/bin/activate
pip install "diffusers>=0.39.0.dev0" torch transformers accelerate \
            fastapi uvicorn pillow prometheus-client psutil pynvml ftfy
./run.sh
```

Server listens on `http://0.0.0.0:8500`. (`ftfy` is required by the Wan prompt
preprocessing — I2V errors without it.)

### Environment variables

| Var | Default | Meaning |
|-----|---------|---------|
| `WAN_MODEL_ID` | `Wan-AI/Wan2.2-TI2V-5B-Diffusers` | model repo / local path |
| `WAN_WIDTH` / `WAN_HEIGHT` | `832` / `480` | default frame size (overridable per request) |
| `HYV_HOST` / `HYV_PORT` | `0.0.0.0` / `8500` | bind address |
| `HYV_DTYPE` | `bfloat16` | `bfloat16` \| `float16` |
| `DIFFUSERS_ATTENTION_BACKEND` | `native` | keep SDPA on Blackwell |

### API

```
POST /generate       {prompt, [negative_prompt, num_frames, num_inference_steps,
                       height, width, guidance_scale, fps, seed]}
POST /generate_i2v   {image (base64/data-URI), prompt, ...same...}
POST /cancel         aborts the running generation at the next denoising step
GET  /health  GET /metrics  GET /outputs/<file>.mp4
```

`num_frames` must be `4k+1` (Wan VAE temporal factor 4). Wan2.2-TI2V-5B is a base
model (not step-distilled): ~20 steps is a good speed/quality point.

## Open WebUI integration

Install `hunyuanvideo_pipeline.py` into the Open WebUI **pipelines** container (or
load `openwebui_function.py` as a Function). Set the `SERVER_URL` valve to this
server (default `localhost:8500`; from a container use the host's address). A
text-only message routes to T2V, a message with an attached image routes to I2V.
Stopping the chat aborts the server-side job via `POST /cancel`.
