"""Wan2.2-TI2V-5B inference server (host GPU, FastAPI).

One checkpoint serves BOTH text-to-video and image-to-video. The T2V pipeline is
loaded once and the I2V pipeline reuses its components (WanImageToVideoPipeline
.from_pipe), so both modes are resident with a single ~23GB weight set — no swap,
no single-residency unloading (unlike the previous HunyuanVideo setup where T2V
and I2V were two ~44GB models that could not coexist on the 119GB GB10).

Attention is forced to PyTorch SDPA ("native") because flash-attn is broken on
GB10/Blackwell.

Endpoints:
  POST /generate      -> text-to-video (T2V)
  POST /generate_i2v  -> image-to-video (I2V); base64 image + prompt
  GET  /health, GET /metrics, GET /outputs/<file>.mp4

Env vars:
  WAN_MODEL_ID   HF repo / local path (default Wan-AI/Wan2.2-TI2V-5B-Diffusers)
  WAN_WIDTH      default frame width  (default 832)
  WAN_HEIGHT     default frame height (default 480)
  HYV_HOST       bind host (default 0.0.0.0)
  HYV_PORT       bind port (default 8500)
  HYV_DTYPE      bfloat16 (default) | float16
"""

import os
import io
import gc
import time
import uuid
import base64
import binascii
import threading
import logging
import subprocess

# flash-attn is broken on Blackwell; force diffusers to PyTorch SDPA.
os.environ.setdefault("DIFFUSERS_ATTENTION_BACKEND", "native")

import torch
from PIL import Image, ImageOps
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

import metrics
from pydantic import BaseModel, Field

from diffusers import WanPipeline, WanImageToVideoPipeline
from diffusers.utils import export_to_video

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("wan")

MODEL_ID = os.environ.get("WAN_MODEL_ID", "Wan-AI/Wan2.2-TI2V-5B-Diffusers")
DEF_W = int(os.environ.get("WAN_WIDTH", "832"))
DEF_H = int(os.environ.get("WAN_HEIGHT", "480"))
HOST = os.environ.get("HYV_HOST", "0.0.0.0")
PORT = int(os.environ.get("HYV_PORT", "8500"))
DTYPE = torch.bfloat16 if os.environ.get("HYV_DTYPE", "bfloat16") == "bfloat16" else torch.float16
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")
os.makedirs(OUT_DIR, exist_ok=True)

# Brand logo overlay: diffusion video models can't render legible text/logos, so we
# composite a crisp PNG in post with ffmpeg instead of letting the model garble it.
# Toggle/tune via env. Applies to both /generate and /generate_i2v.
LOGO_OVERLAY = os.environ.get("WAN_LOGO_OVERLAY", "1") not in ("0", "false", "False", "")
LOGO_PATH = os.environ.get(
    "WAN_LOGO_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "DaolFusion Image", "DaolFusion_세로.png"),
)
LOGO_SCALE = float(os.environ.get("WAN_LOGO_SCALE", "0.16"))   # logo width = 16% of video width
LOGO_MARGIN = int(os.environ.get("WAN_LOGO_MARGIN", "24"))     # px inset from bottom-right corner

app = FastAPI(title="Wan2.2-TI2V-5B Server")
# Serve generated videos over HTTP so Open WebUI references them by URL instead of
# inlining the whole mp4 as base64 (which overflows the socket message limit).
app.mount("/outputs", StaticFiles(directory=OUT_DIR), name="outputs")

# Single GPU -> serialize all inference with one lock across both pipelines.
# T2V and I2V share the same underlying modules (from_pipe), so there is only one
# weight set resident; the lock just prevents concurrent GPU use.
_t2v = None
_i2v = None
_lock = threading.Lock()
# Set by POST /cancel; checked each denoising step to abort the running generation
# (diffusers stops the loop when pipe._interrupt is True).
_cancel = threading.Event()


def _cancel_cb(p, i, t, kw):  # noqa: ANN001
    if _cancel.is_set():
        p._interrupt = True
    return kw


def _load():
    """Load the T2V pipeline and derive the I2V pipeline from its components."""
    global _t2v, _i2v
    if _t2v is not None:
        return
    log.info("Loading WanPipeline (T2V) from %s (dtype=%s)", MODEL_ID, DTYPE)
    t0 = time.time()
    t2v = WanPipeline.from_pretrained(MODEL_ID, torch_dtype=DTYPE)
    for name in ("transformer", "transformer_2"):
        m = getattr(t2v, name, None)
        if m is not None:
            try:
                m.set_attention_backend("native")
                log.info("[wan] %s attention backend -> native (SDPA)", name)
            except Exception as e:  # noqa: BLE001
                log.warning("[wan] %s set_attention_backend failed (%s)", name, e)
    t2v.to("cuda")
    # I2V reuses the SAME modules already on the GPU (no extra memory). NOTE: use
    # the constructor with shared components, NOT from_pipe -- from_pipe duplicates
    # the weights (~+34GB) on this checkpoint. expand_timesteps must be carried over
    # or I2V conditioning builds the wrong latent channel count.
    i2v = WanImageToVideoPipeline(**t2v.components, expand_timesteps=t2v.config.expand_timesteps)
    try:
        metrics.wrap_scheduler(t2v)
    except Exception as e:  # noqa: BLE001
        log.warning("metrics.wrap_scheduler failed (%s)", e)
    _t2v, _i2v = t2v, i2v
    log.info("Wan pipelines ready in %.1fs (T2V+I2V share one weight set)", time.time() - t0)


def _decode_image(data: str) -> Image.Image:
    """Decode a base64 (optionally data-URI) string into an RGB PIL image."""
    if not data or not data.strip():
        raise HTTPException(status_code=400, detail="image is required for I2V")
    payload = data.strip()
    if payload.startswith("data:"):
        _, _, payload = payload.partition(",")
    try:
        raw = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as e:
        raise HTTPException(status_code=400, detail=f"image is not valid base64: {e}") from e
    try:
        with Image.open(io.BytesIO(raw)) as opened:
            return ImageOps.exif_transpose(opened).copy()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"could not decode image: {e}") from e


def _prepare_i2v_image(image: Image.Image, width: int, height: int) -> Image.Image:
    """Produce an opaque, aspect-ratio-correct first frame without stretching."""
    if "A" in image.getbands():
        rgba = image.convert("RGBA")
        background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        image = Image.alpha_composite(background, rgba).convert("RGB")
    else:
        image = image.convert("RGB")
    # Bias portrait crops slightly upward so a face/upper body is not cut off.
    centering = (0.5, 0.35) if image.height > image.width else (0.5, 0.5)
    return ImageOps.fit(image, (width, height), method=Image.Resampling.LANCZOS,
                        centering=centering)


class GenerateRequest(BaseModel):
    prompt: str
    negative_prompt: str | None = None
    num_frames: int = 49                 # 4k+1 (Wan VAE temporal=4)
    num_inference_steps: int = 20        # Wan base (not step-distilled): ~20 is the sweet spot
    height: int | None = None
    width: int | None = None
    guidance_scale: float | None = None  # None -> pipeline default (~5.0)
    fps: int = 24
    seed: int | None = None


class GenerateI2VRequest(BaseModel):
    image: str                           # base64 image (optionally data: URI)
    prompt: str
    negative_prompt: str | None = None
    num_frames: int = 49
    num_inference_steps: int = 20
    height: int | None = None
    width: int | None = None
    guidance_scale: float | None = None
    fps: int = 24
    seed: int | None = None


class ReelScene(BaseModel):
    prompt: str                          # already-enhanced cinematic prompt for this cut


class GenerateReelRequest(BaseModel):
    scenes: list[ReelScene]              # ordered cuts, generated then stitched
    negative_prompt: str | None = None
    num_frames: int = 33
    num_inference_steps: int = 20
    height: int | None = None
    width: int | None = None
    fps: int = 24


@app.get("/health")
def health():
    return {
        "status": "ok",
        "model": MODEL_ID,
        "backend": "wan2.2-ti2v-5b",
        "loaded": _t2v is not None,
        "i2v_loaded": _i2v is not None,
        "dtype": str(DTYPE),
        "default_size": f"{DEF_W}x{DEF_H}",
        "cuda": torch.cuda.is_available(),
        "device": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
    }


@app.get("/metrics")
def prometheus_metrics():
    body, content_type = metrics.render()
    return Response(content=body, media_type=content_type)


@app.post("/cancel")
def cancel():
    """Abort the currently running generation at the next denoising step."""
    _cancel.set()
    log.info("cancel requested")
    return {"cancelled": True}


def _overlay_logo(path, width):
    """Composite the brand logo into the bottom-right corner with ffmpeg.
    No-op (keeps the original video) on any failure or when disabled/missing."""
    if not (LOGO_OVERLAY and os.path.exists(LOGO_PATH)):
        return
    logo_w = max(1, int(width * LOGO_SCALE))
    tmp = path + ".ovl.mp4"
    # scale logo to logo_w (aspect preserved), overlay inset from bottom-right
    fc = (f"[1:v]scale={logo_w}:-1[lg];"
          f"[0:v][lg]overlay=W-w-{LOGO_MARGIN}:H-h-{LOGO_MARGIN}")
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", path, "-i", LOGO_PATH,
             "-filter_complex", fc, "-c:a", "copy", "-movflags", "+faststart", tmp],
            check=True, capture_output=True,
        )
        os.replace(tmp, path)
        log.info("logo overlaid -> %s", os.path.basename(path))
    except Exception as e:  # noqa: BLE001 - overlay is best-effort, never fail the request
        log.warning("logo overlay skipped: %s", getattr(e, "stderr", e))
        if os.path.exists(tmp):
            os.remove(tmp)


def _gen_to_path(pipe, kwargs, fps):
    """Run one generation under the GPU lock and export to a fresh mp4 (no overlay)."""
    _cancel.clear()
    with _lock:
        try:
            pipe._interrupt = False
            result = pipe(**kwargs, callback_on_step_end=_cancel_cb)
            if _cancel.is_set():
                raise HTTPException(status_code=499, detail="generation cancelled")
            frames = result.frames[0]
        except torch.cuda.OutOfMemoryError as e:
            torch.cuda.empty_cache()
            raise HTTPException(status_code=507, detail=f"CUDA OOM: {e}") from e
        finally:
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
    out_path = os.path.join(OUT_DIR, f"{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.mp4")
    export_to_video(frames, out_path, fps=fps)
    return out_path


def _concat_clips(paths, out_path):
    """Stitch clips (same resolution) into out_path with ffmpeg concat."""
    ins = []
    for p in paths:
        ins += ["-i", p]
    n = len(paths)
    fc = "".join(f"[{i}:v]" for i in range(n)) + f"concat=n={n}:v=1:a=0[v]"
    subprocess.run(["ffmpeg", "-y", *ins, "-filter_complex", fc, "-map", "[v]",
                    "-movflags", "+faststart", out_path], check=True, capture_output=True)


def _run(pipe, kwargs, label, fps, t0):
    """Single-clip path: generate, overlay logo, return response dict."""
    metrics.generation_start(kwargs.get("num_inference_steps"))
    ok = False
    try:
        out_path = _gen_to_path(pipe, kwargs, fps)
        _overlay_logo(out_path, kwargs.get("width") or DEF_W)
        dt = time.time() - t0
        log.info("%s done in %.1fs -> %s", label, dt, out_path)
        ok = True
        fname = os.path.basename(out_path)
        return {"video_url": f"/outputs/{fname}", "filename": fname, "seconds": round(dt, 1)}
    finally:
        metrics.generation_end(label, "success" if ok else "error", time.time() - t0)


@app.post("/generate")
def generate(req: GenerateRequest):
    if not req.prompt or not req.prompt.strip():
        raise HTTPException(status_code=400, detail="prompt is required")
    _load()
    kwargs = dict(
        prompt=req.prompt,
        negative_prompt=req.negative_prompt,
        height=req.height or DEF_H,
        width=req.width or DEF_W,
        num_frames=req.num_frames,
        num_inference_steps=req.num_inference_steps,
    )
    if req.guidance_scale is not None:
        kwargs["guidance_scale"] = req.guidance_scale
    if req.seed is not None:
        kwargs["generator"] = torch.Generator(device="cpu").manual_seed(req.seed)
    log.info("generate(T2V): frames=%s steps=%s size=%sx%s seed=%s",
             req.num_frames, req.num_inference_steps, kwargs["width"], kwargs["height"], req.seed)
    return _run(_t2v, kwargs, "t2v", req.fps, time.time())


@app.post("/generate_i2v")
def generate_i2v(req: GenerateI2VRequest):
    if not req.prompt or not req.prompt.strip():
        raise HTTPException(status_code=400, detail="prompt is required")
    image = _decode_image(req.image)
    _load()
    W = req.width or DEF_W
    H = req.height or DEF_H
    image = _prepare_i2v_image(image, W, H)
    kwargs = dict(
        image=image,
        prompt=req.prompt,
        negative_prompt=req.negative_prompt,
        height=H,
        width=W,
        num_frames=req.num_frames,
        num_inference_steps=req.num_inference_steps,
    )
    if req.guidance_scale is not None:
        kwargs["guidance_scale"] = req.guidance_scale
    if req.seed is not None:
        kwargs["generator"] = torch.Generator(device="cpu").manual_seed(req.seed)
    log.info("generate_i2v: img=%sx%s frames=%s steps=%s seed=%s",
             W, H, req.num_frames, req.num_inference_steps, req.seed)
    return _run(_i2v, kwargs, "i2v", req.fps, time.time())


@app.post("/generate_reel")
def generate_reel(req: GenerateReelRequest):
    """Multi-cut: generate each scene as a T2V clip, stitch them, overlay logo once."""
    scenes = [s for s in req.scenes if s.prompt and s.prompt.strip()]
    if not scenes:
        raise HTTPException(status_code=400, detail="scenes is required")
    _load()
    t0 = time.time()
    W = req.width or DEF_W
    H = req.height or DEF_H
    clips = []
    try:
        for i, sc in enumerate(scenes):
            kwargs = dict(
                prompt=sc.prompt,
                negative_prompt=req.negative_prompt,
                height=H, width=W,
                num_frames=req.num_frames,
                num_inference_steps=req.num_inference_steps,
            )
            log.info("reel scene %d/%d: %s", i + 1, len(scenes), sc.prompt[:60])
            metrics.generation_start(req.num_inference_steps)
            ok = False
            try:
                clips.append(_gen_to_path(_t2v, kwargs, req.fps))
                ok = True
            finally:
                metrics.generation_end("reel_scene", "success" if ok else "error", 0)
        out_path = os.path.join(OUT_DIR, f"{time.strftime('%Y%m%d_%H%M%S')}_reel_{uuid.uuid4().hex[:8]}.mp4")
        if len(clips) == 1:
            os.replace(clips[0], out_path)          # single scene -> just serve it
        else:
            _concat_clips(clips, out_path)
        _overlay_logo(out_path, W)
        dt = time.time() - t0
        fname = os.path.basename(out_path)
        log.info("reel done: %d scenes in %.1fs -> %s", len(clips), dt, fname)
        return {"video_url": f"/outputs/{fname}", "filename": fname,
                "seconds": round(dt, 1), "scenes": len(clips)}
    finally:
        if len(clips) > 1:                          # concatenated -> drop the per-scene temps
            for c in clips:
                try:
                    os.remove(c)
                except OSError:
                    pass


@app.exception_handler(Exception)
def on_error(request, exc):  # noqa: ANN001
    log.exception("request failed")
    return JSONResponse(status_code=500, content={"detail": str(exc)})


if __name__ == "__main__":
    import uvicorn

    _load()  # preload so the first request isn't a multi-minute wait
    uvicorn.run(app, host=HOST, port=PORT, workers=1, timeout_keep_alive=600)
