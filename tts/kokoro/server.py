"""Local Kokoro-82M Korean narration service for DaolVision."""

from __future__ import annotations

import io
import os
import threading
import time

import soundfile as sf
from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, Field
from pykokoro import GenerationConfig, KokoroPipeline, PipelineConfig
from pykokoro.short_sentence_handler import ShortSentenceConfig


VOICE = os.environ.get("KOKORO_VOICE", "af_heart")
HOST = os.environ.get("KOKORO_HOST", "127.0.0.1")
PORT = int(os.environ.get("KOKORO_PORT", "8503"))

app = FastAPI(title="DaolVision Kokoro Korean TTS")
_pipeline: KokoroPipeline | None = None
_pipeline_lock = threading.RLock()


class GenerateRequest(BaseModel):
    text: str
    language: str = "ko"
    speed: float = Field(default=1.0, ge=0.5, le=2.0)


def get_pipeline() -> KokoroPipeline:
    global _pipeline
    if _pipeline is None:
        with _pipeline_lock:
            if _pipeline is None:
                config = PipelineConfig(
                    voice=VOICE,
                    generation=GenerationConfig(
                        lang="ko",
                        speed=1.0,
                        pause_mode="tts",
                    ),
                    short_sentence_config=ShortSentenceConfig(enabled=False),
                )
                _pipeline = KokoroPipeline(config)
    return _pipeline


@app.get("/health")
def health():
    return {
        "status": "ok",
        "backend": "kokoro-82m",
        "language": "ko",
        "voice": VOICE,
        "loaded": _pipeline is not None,
    }


@app.post("/generate")
def generate(req: GenerateRequest):
    text = req.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required")
    if req.language != "ko":
        raise HTTPException(status_code=400, detail="only language=ko is supported")

    started = time.monotonic()
    with _pipeline_lock:
        result = get_pipeline().run(
            text,
            generation=GenerationConfig(
                lang="ko",
                speed=req.speed,
                pause_mode="tts",
            ),
        )

    buffer = io.BytesIO()
    sf.write(buffer, result.audio, result.sample_rate, format="WAV", subtype="PCM_16")
    return Response(
        content=buffer.getvalue(),
        media_type="audio/wav",
        headers={
            "X-TTS-Engine": "kokoro",
            "X-TTS-Voice": VOICE,
            "X-Generation-Seconds": f"{time.monotonic() - started:.3f}",
        },
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT)
