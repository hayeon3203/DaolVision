"""Local Cosmos3-Nano text-to-video service for DaolVision (Task 7.6 spike)."""

from __future__ import annotations

import os
import tempfile
import threading
import time
from pathlib import Path

import torch
from diffusers import Cosmos3OmniPipeline
from diffusers.utils import export_to_video
from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel

HOST = os.environ.get("COSMOS3NANO_HOST", "127.0.0.1")
PORT = int(os.environ.get("COSMOS3NANO_PORT", "8505"))
MODEL_ID = os.environ.get("COSMOS3NANO_MODEL_ID", "nvidia/Cosmos3-Nano")
# ponytail: enable_sequential_cpu_offload() is designed for discrete-GPU boxes
# where VRAM and system RAM are separate pools — GB10's unified memory means
# CPU and "GPU" are the same physical DRAM, so offload buys nothing but adds
# transfer overhead. Measured 640x480/49-frame/20-step: offload 144s warm vs
# no-offload 61.5s warm, same peak memory footprint either way (see
# docs/model-selection-t2v.md). Default off; set "1" to re-enable if a future
# larger job actually needs the staggered load.
OFFLOAD = os.environ.get("COSMOS3NANO_OFFLOAD", "0") == "1"

app = FastAPI(title="DaolVision Cosmos3-Nano T2V")
_pipe: Cosmos3OmniPipeline | None = None
_pipe_lock = threading.RLock()


def get_pipe() -> Cosmos3OmniPipeline:
    global _pipe
    if _pipe is None:
        with _pipe_lock:
            if _pipe is None:
                if not torch.cuda.is_available():
                    raise RuntimeError("CUDA is required but unavailable")
                pipe = Cosmos3OmniPipeline.from_pretrained(
                    MODEL_ID,
                    torch_dtype=torch.bfloat16,
                    # local-only spike server, never exposed publicly — the
                    # gated NVIDIA safety-checker model needs its own HF
                    # license accept and isn't worth the extra download here.
                    enable_safety_checker=False,
                )
                if OFFLOAD:
                    pipe.enable_sequential_cpu_offload()
                else:
                    pipe.to("cuda")
                _pipe = pipe
    return _pipe


class GenerateRequest(BaseModel):
    prompt: str
    width: int = 640
    height: int = 480
    num_frames: int = 49
    num_inference_steps: int = 20
    guidance_scale: float = 6.0
    seed: int | None = None


@app.get("/health")
def health():
    return {"status": "ok", "backend": "cosmos3-nano", "loaded": _pipe is not None}


@app.post("/generate")
def generate(req: GenerateRequest):
    prompt = req.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt is required")

    seed = req.seed if req.seed is not None else int(time.time())
    generator = torch.Generator(device="cuda").manual_seed(seed)

    started = time.monotonic()
    try:
        with _pipe_lock, torch.inference_mode():
            pipe = get_pipe()
            result = pipe(
                prompt=f'{{"text": "{prompt}"}}',
                num_frames=req.num_frames,
                height=req.height,
                width=req.width,
                num_inference_steps=req.num_inference_steps,
                guidance_scale=req.guidance_scale,
                generator=generator,
            )
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=500, detail=f"generation failed: {exc}") from exc
    elapsed = time.monotonic() - started

    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        export_to_video(result.video, str(tmp_path), fps=24)
        video_bytes = tmp_path.read_bytes()
    finally:
        tmp_path.unlink(missing_ok=True)

    return Response(
        content=video_bytes,
        media_type="video/mp4",
        headers={
            "X-T2V-Engine": "cosmos3-nano",
            "X-Seed": str(seed),
            "X-Generation-Seconds": f"{elapsed:.3f}",
        },
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT)
