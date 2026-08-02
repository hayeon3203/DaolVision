"""Local Cosmos3-Nano text-to-video service for DaolVision (Task 7.6 spike).

Not a resident service (no systemd unit) — the 31GB GPU footprint doesn't fit
alongside ComfyUI's own resident models on this GB10. langgraph/tools.py
launches this process on demand (first /t2v request) and it self-exits after
IDLE_TIMEOUT of inactivity to give the VRAM back."""

from __future__ import annotations

import asyncio
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
# 마지막 요청 "완료" 후 이만큼 지나면 자체 종료(VRAM 반납). 생성 중(in-flight)엔
# _inflight 카운터가 종료를 막으므로 생성 시간(cold ~215s)과는 무관하다.
IDLE_TIMEOUT = float(os.environ.get("COSMOS3NANO_IDLE_TIMEOUT", "180"))
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
_inflight = 0
_last_used = time.monotonic()


async def _idle_watchdog() -> None:
    while True:
        await asyncio.sleep(30)
        if _inflight == 0 and time.monotonic() - _last_used > IDLE_TIMEOUT:
            os._exit(0)  # 디스크에 남길 상태 없음 — 그냥 즉시 종료해 VRAM 반납


@app.on_event("startup")
async def _start_idle_watchdog():
    asyncio.create_task(_idle_watchdog())


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
    global _inflight, _last_used
    prompt = req.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt is required")

    seed = req.seed if req.seed is not None else int(time.time())
    generator = torch.Generator(device="cuda").manual_seed(seed)

    _inflight += 1
    started = time.monotonic()
    try:
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
    finally:
        _inflight -= 1
        _last_used = time.monotonic()

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
