"""Wan2.2-Animate-14B API server for character animation.

This is intentionally separate from the TI2V-5B server.  The model is loaded
lazily with CPU offload so the existing text/image-to-video service can remain
available on unified-memory GB10 systems.
"""

import base64
import binascii
import gc
import io
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

import torch
from diffusers import WanAnimatePipeline
from diffusers.utils import export_to_video, load_image, load_video
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel, Field

os.environ.setdefault("DIFFUSERS_ATTENTION_BACKEND", "native")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("wan-animate")

BASE_DIR = Path(__file__).resolve().parent
MODEL_ID = os.environ.get("WAN_ANIMATE_MODEL_ID", "Wan-AI/Wan2.2-Animate-14B-Diffusers")
WAN_REPO = Path(os.environ.get("WAN_ANIMATE_REPO", "/home/admin/video_generator/Wan2.2-Animate"))
PROCESS_CKPT = Path(os.environ.get("WAN_ANIMATE_PROCESS_CKPT", str(BASE_DIR / "process_checkpoint")))
HOST = os.environ.get("WAN_ANIMATE_HOST", "0.0.0.0")
PORT = int(os.environ.get("WAN_ANIMATE_PORT", "8600"))
WIDTH = int(os.environ.get("WAN_ANIMATE_WIDTH", "832"))
HEIGHT = int(os.environ.get("WAN_ANIMATE_HEIGHT", "480"))
MAX_SECONDS = float(os.environ.get("WAN_ANIMATE_MAX_SECONDS", "5"))
OUT_DIR = BASE_DIR / "outputs"
OUT_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Wan2.2-Animate-14B Server")
app.mount("/outputs", StaticFiles(directory=OUT_DIR), name="outputs")

_pipe = None
_lock = threading.Lock()
_cancel = threading.Event()


def _cancel_cb(pipe, step, timestep, kwargs):  # noqa: ANN001
    if _cancel.is_set():
        pipe._interrupt = True
    return kwargs


def _decode(value: str, name: str) -> bytes:
    if not value or not value.strip():
        raise HTTPException(status_code=400, detail=f"{name} is required")
    payload = value.strip()
    if payload.startswith("data:"):
        payload = payload.partition(",")[2]
    try:
        return base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"invalid {name} base64: {exc}") from exc


def _load_pipeline():
    global _pipe
    if _pipe is not None:
        return _pipe
    log.info("loading %s with CPU offload", MODEL_ID)
    started = time.time()
    pipe = WanAnimatePipeline.from_pretrained(MODEL_ID, torch_dtype=torch.bfloat16)
    transformer = getattr(pipe, "transformer", None)
    if transformer is not None:
        try:
            transformer.set_attention_backend("native")
        except Exception as exc:  # noqa: BLE001
            log.warning("native attention setup failed: %s", exc)
    pipe.enable_model_cpu_offload()
    _pipe = pipe
    log.info("Animate pipeline ready in %.1fs", time.time() - started)
    return pipe


def _trim_video(source: Path, target: Path, seconds: float, fps: int):
    command = [
        "ffmpeg", "-y", "-i", str(source), "-t", str(seconds),
        "-vf", f"fps={fps}", "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(target),
    ]
    try:
        subprocess.run(command, check=True, capture_output=True)
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.decode("utf-8", "replace")[-1000:]
        raise HTTPException(status_code=400, detail=f"invalid driving video: {detail}") from exc


def _preprocess(image_path: Path, video_path: Path, output_dir: Path, fps: int):
    script = WAN_REPO / "wan/modules/animate/preprocess/preprocess_data.py"
    if not script.exists():
        raise RuntimeError(f"Wan Animate preprocess script not found: {script}")
    required = [
        PROCESS_CKPT / "det/yolov10m.onnx",
        PROCESS_CKPT / "pose2d/vitpose_h_wholebody.onnx",
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise RuntimeError("missing preprocessing checkpoints: " + ", ".join(missing))
    command = [
        sys.executable, str(script), "--ckpt_path", str(PROCESS_CKPT),
        "--video_path", str(video_path), "--refer_path", str(image_path),
        "--save_path", str(output_dir), "--resolution_area", str(WIDTH), str(HEIGHT),
        "--fps", str(fps),
    ]
    log.info("preprocessing driving video")
    result = subprocess.run(
        command, cwd=script.parent, text=True, capture_output=True, timeout=900
    )
    if result.returncode:
        raise RuntimeError("Animate preprocessing failed: " + result.stderr[-2000:])


class AnimateRequest(BaseModel):
    image: str = Field(description="Reference character image as base64 or data URI")
    video: str = Field(description="Driving video as base64 or data URI")
    prompt: str = "A person performs the motion naturally."
    negative_prompt: str | None = None
    num_inference_steps: int = Field(default=20, ge=1, le=50)
    guidance_scale: float = Field(default=1.0, ge=0.0, le=20.0)
    fps: int = Field(default=16, ge=8, le=30)
    seed: int | None = None


@app.get("/health")
def health():
    return {
        "status": "ok",
        "model": MODEL_ID,
        "backend": "wan2.2-animate-14b",
        "loaded": _pipe is not None,
        "size": f"{WIDTH}x{HEIGHT}",
        "max_seconds": MAX_SECONDS,
        "preprocess_ready": (PROCESS_CKPT / "det/yolov10m.onnx").exists(),
    }


@app.post("/cancel")
def cancel():
    _cancel.set()
    return {"cancelled": True}


@app.post("/animate")
def animate(req: AnimateRequest):
    image_bytes = _decode(req.image, "image")
    video_bytes = _decode(req.video, "video")
    try:
        Image.open(io.BytesIO(image_bytes)).verify()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"invalid reference image: {exc}") from exc

    started = time.time()
    with _lock, tempfile.TemporaryDirectory(prefix="wan-animate-") as tmp:
        tmpdir = Path(tmp)
        image_path = tmpdir / "reference.png"
        raw_video = tmpdir / "driving-input"
        driving_video = tmpdir / "driving.mp4"
        process_dir = tmpdir / "processed"
        process_dir.mkdir()
        image_path.write_bytes(image_bytes)
        raw_video.write_bytes(video_bytes)
        _trim_video(raw_video, driving_video, MAX_SECONDS, req.fps)
        try:
            _preprocess(image_path, driving_video, process_dir, req.fps)
            image = load_image(str(process_dir / "src_ref.png"))
            pose_video = load_video(str(process_dir / "src_pose.mp4"))
            face_video = load_video(str(process_dir / "src_face.mp4"))
            pipe = _load_pipeline()
            _cancel.clear()
            pipe._interrupt = False
            kwargs = {
                "image": image,
                "pose_video": pose_video,
                "face_video": face_video,
                "prompt": req.prompt,
                "negative_prompt": req.negative_prompt,
                "height": HEIGHT,
                "width": WIDTH,
                "segment_frame_length": min(77, len(pose_video)),
                "num_inference_steps": req.num_inference_steps,
                "guidance_scale": req.guidance_scale,
                "prev_segment_conditioning_frames": 1,
                "generator": torch.Generator(device="cpu").manual_seed(
                    req.seed if req.seed is not None else torch.seed()
                ),
                "callback_on_step_end": _cancel_cb,
            }
            result = pipe(**kwargs)
            if _cancel.is_set():
                raise HTTPException(status_code=499, detail="generation cancelled")
            output = OUT_DIR / f"{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.mp4"
            export_to_video(result.frames[0], str(output), fps=req.fps)
        except HTTPException:
            raise
        except torch.cuda.OutOfMemoryError as exc:
            raise HTTPException(status_code=507, detail=f"CUDA OOM: {exc}") from exc
        except Exception as exc:  # noqa: BLE001
            log.exception("Animate generation failed")
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        finally:
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

    elapsed = round(time.time() - started, 1)
    log.info("animation done in %.1fs -> %s", elapsed, output)
    return {
        "video_url": f"/outputs/{output.name}",
        "filename": output.name,
        "seconds": elapsed,
        "input_frames": len(pose_video),
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT)
