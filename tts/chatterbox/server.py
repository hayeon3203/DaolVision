"""Local Chatterbox Multilingual V3 voice-cloning service for DaolVision."""

from __future__ import annotations

import io
import os
import tempfile
import threading
import time
from pathlib import Path

import soundfile as sf
import torch
import torchaudio.functional as audio_functional
from chatterbox.mtl_tts import ChatterboxMultilingualTTS
from fastapi import FastAPI, File, Form, HTTPException, Response, UploadFile


HOST = os.environ.get("CHATTERBOX_HOST", "127.0.0.1")
PORT = int(os.environ.get("CHATTERBOX_PORT", "8504"))
DEVICE = os.environ.get("CHATTERBOX_DEVICE", "cuda")
TARGET_SAMPLE_RATE = 24_000

app = FastAPI(title="DaolVision Chatterbox V3 Voice Clone")
_model: ChatterboxMultilingualTTS | None = None
_model_lock = threading.RLock()


def get_model() -> ChatterboxMultilingualTTS:
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                if DEVICE == "cuda" and not torch.cuda.is_available():
                    raise RuntimeError("CUDA is required but unavailable")
                _model = ChatterboxMultilingualTTS.from_pretrained(
                    device=DEVICE,
                    t3_model="v3",
                )
    return _model


@app.get("/health")
def health():
    return {
        "status": "ok",
        "backend": "chatterbox-multilingual-v3",
        "language": "ko",
        "loaded": _model is not None,
    }


@app.post("/generate")
def generate(
    text: str = Form(...),
    reference: UploadFile | None = File(None),
    # Sampling knobs. Defaults match ChatterboxMultilingualTTS.generate(), so
    # callers that send nothing keep the exact previous behaviour. They exist
    # because the default temperature rambles: the same Korean sentence came out
    # 3-4x too long (2 chars/s against the reference speaker's own 6.2 chars/s)
    # on roughly half of all takes. Lower temperature + higher repetition
    # penalty is the knob that stops it.
    language: str = Form("ko"),
    exaggeration: float = Form(0.5),
    cfg_weight: float = Form(0.5),
    temperature: float = Form(0.8),
    repetition_penalty: float = Form(1.2),
):
    text = text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required")
    if reference is None or not reference.filename:
        raise HTTPException(status_code=422, detail="reference WAV is required")
    if not reference.filename.lower().endswith(".wav"):
        raise HTTPException(status_code=415, detail="reference must be a WAV file")

    reference_bytes = reference.file.read()
    if (
        len(reference_bytes) < 12
        or reference_bytes[:4] != b"RIFF"
        or reference_bytes[8:12] != b"WAVE"
    ):
        raise HTTPException(status_code=415, detail="reference is not a valid WAV file")

    started = time.monotonic()
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp:
            temp.write(reference_bytes)
            temp_path = Path(temp.name)

        with _model_lock, torch.inference_mode():
            model = get_model()
            wav = model.generate(
                text,
                language_id=language,
                audio_prompt_path=str(temp_path),
                exaggeration=exaggeration,
                cfg_weight=cfg_weight,
                temperature=temperature,
                repetition_penalty=repetition_penalty,
            ).squeeze().detach().cpu()
            if model.sr != TARGET_SAMPLE_RATE:
                wav = audio_functional.resample(wav, model.sr, TARGET_SAMPLE_RATE)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=500, detail=f"generation failed: {exc}") from exc
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)

    buffer = io.BytesIO()
    sf.write(
        buffer,
        wav.numpy(),
        TARGET_SAMPLE_RATE,
        format="WAV",
        subtype="PCM_16",
    )
    return Response(
        content=buffer.getvalue(),
        media_type="audio/wav",
        headers={
            "X-TTS-Engine": "chatterbox-v3",
            "X-Sample-Rate": str(TARGET_SAMPLE_RATE),
            "X-Channels": "1",
            "X-Generation-Seconds": f"{time.monotonic() - started:.3f}",
        },
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT)
