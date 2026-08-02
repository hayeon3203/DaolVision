"""FLUX.1-schnell text-to-image server (host GPU, FastAPI).

Dedicated still-image model for the agent's front-end "generate anchor image"
step (langgraph node_generate_image), which previously reused the full
Wan2.2-TI2V-5B video pipeline at :8500 with num_frames=1 -- a ~120s detour
through a video model to produce one frame. Replaced Z-Image-Turbo
(Tongyi-MAI, China) with FLUX.1-schnell (Black Forest Labs, Germany) per
DaolVision R10 (non-Chinese/NVIDIA-first stack) -- see DaolVision
.harness/STATE.md Task 2.3.5 for the GB10 bench comparison (SDXL/FLUX/
nvidia-Qwen-Image-Flash) behind this choice.

Endpoints:
  POST /generate  -> text-to-image
  GET  /health, GET /outputs/<file>.png

Env vars:
  FLUX_MODEL_PATH    HF repo id or local path (default black-forest-labs/FLUX.1-schnell)
  FLUX_WIDTH         default width  (default 1024)
  FLUX_HEIGHT        default height (default 1024)
  FLUX_STEPS         default num_inference_steps (default 4, schnell's distilled step count)
  HYV_HOST           bind host (default 0.0.0.0)
  HYV_PORT           bind port (default 8501)
"""

import os
import gc
import time
import uuid
import logging
import threading

os.environ.setdefault("DIFFUSERS_ATTN_BACKEND", "native")  # flash-attn (FA-2) broken on GB10/Blackwell

import torch
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from diffusers import FluxPipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("flux")

MODEL_PATH = os.environ.get("FLUX_MODEL_PATH", "black-forest-labs/FLUX.1-schnell")
DEF_W = int(os.environ.get("FLUX_WIDTH", "1024"))
DEF_H = int(os.environ.get("FLUX_HEIGHT", "1024"))
DEF_STEPS = int(os.environ.get("FLUX_STEPS", "4"))
# Default: unload after every request so this coexists with comfyui.service (measured
# CUDA OOM otherwise on this GB10 -- see _unload() docstring). Set to 1 only if :8500
# (wan.service, 22GB) is stopped and the freed headroom is going to this model instead.
KEEP_RESIDENT = os.environ.get("FLUX_KEEP_RESIDENT", "0") not in ("0", "false", "False", "")
HOST = os.environ.get("HYV_HOST", "0.0.0.0")
PORT = int(os.environ.get("HYV_PORT", "8501"))
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")
os.makedirs(OUT_DIR, exist_ok=True)

app = FastAPI(title="FLUX.1-schnell Server")
app.mount("/outputs", StaticFiles(directory=OUT_DIR), name="outputs")

_pipe = None
_lock = threading.Lock()


def _load():
    global _pipe
    # check-and-set must be inside _lock -- otherwise two overlapping requests
    # (e.g. a client retry after its own timeout, while the first call is still
    # loading) both see _pipe is None and each start a full ~34GB load, doubling
    # GPU memory mid-load and getting OOM-killed (observed: status=9/KILL).
    with _lock:
        if _pipe is not None:
            return
        log.info("Loading FluxPipeline from %s", MODEL_PATH)
        t0 = time.time()
        pipe = FluxPipeline.from_pretrained(MODEL_PATH, torch_dtype=torch.bfloat16)
        pipe.to("cuda")
        _pipe = pipe
        log.info("FLUX.1-schnell ready in %.1fs", time.time() - t0)


def _unload():
    """Free the ~34GB weight set right after use so this server can coexist with
    comfyui.service (Stand-In). Measured (Z-Image-Turbo predecessor): both resident
    at once -> CUDA OOM on this GB10 even though node_generate_image and Stand-In
    never run at the same instant in the real pipeline (image step completes before
    scene/clip generation starts). Costs a reload on the next request; runs once
    per job, so that's a good trade for guaranteed coexistence. Skipped when
    KEEP_RESIDENT."""
    global _pipe
    if KEEP_RESIDENT or _pipe is None:
        return
    del _pipe
    _pipe = None
    gc.collect()
    torch.cuda.empty_cache()


class GenerateRequest(BaseModel):
    prompt: str
    width: int | None = None
    height: int | None = None
    num_inference_steps: int | None = None
    seed: int | None = None


@app.get("/health")
def health():
    return {
        "status": "ok",
        "model": MODEL_PATH,
        "backend": "flux-schnell",
        "loaded": _pipe is not None,
        "cuda": torch.cuda.is_available(),
        "device": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
    }


@app.post("/generate")
def generate(req: GenerateRequest):
    if not req.prompt or not req.prompt.strip():
        raise HTTPException(status_code=400, detail="prompt is required")
    _load()
    kwargs = dict(
        prompt=req.prompt,
        width=req.width or DEF_W,
        height=req.height or DEF_H,
        num_inference_steps=req.num_inference_steps or DEF_STEPS,
        guidance_scale=0.0,  # schnell: distilled, CFG off
    )
    if req.seed is not None:
        kwargs["generator"] = torch.Generator("cuda").manual_seed(req.seed)
    log.info("generate: size=%sx%s steps=%s seed=%s",
             kwargs["width"], kwargs["height"], kwargs["num_inference_steps"], req.seed)
    t0 = time.time()
    try:
        with _lock:
            image = _pipe(**kwargs).images[0]
    finally:
        _unload()
    fname = f"{uuid.uuid4().hex}.png"
    out_path = os.path.join(OUT_DIR, fname)
    image.save(out_path)
    dt = time.time() - t0
    log.info("generate done in %.1fs -> %s", dt, out_path)
    return {"image_url": f"/outputs/{fname}", "filename": fname, "seconds": round(dt, 1)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT)
