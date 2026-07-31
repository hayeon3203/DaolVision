"""Task 4.2: POST /tts/narration Kokoro proxy contract.

Kokoro itself is replaced with a stub, so this test is GPU/model independent.
"""

import asyncio
import sys
from pathlib import Path

import httpx
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import api
import tools


FAKE_WAV = b"RIFF" + (b"\x00" * 32) + b"WAVEfmt " + (b"\x00" * 32)


async def main():
    calls = []

    async def fake_narration(text, speed=1.0):
        calls.append({"text": text, "speed": speed})
        return FAKE_WAV

    tools.generate_kokoro_narration = fake_narration

    response = await api.tts_narration(
        api.TTSNarrationRequest(text="안녕하세요", speed=0.95)
    )
    assert response.media_type == "audio/wav", response.media_type
    assert response.body == FAKE_WAV
    assert response.headers["x-tts-engine"] == "kokoro"
    assert calls == [{"text": "안녕하세요", "speed": 0.95}]
    print("PASS: /tts/narration -> Kokoro WAV")

    try:
        await api.tts_narration(api.TTSNarrationRequest(text="  "))
        raise AssertionError("empty text was accepted")
    except HTTPException as exc:
        assert exc.status_code == 400, exc
    print("PASS: empty text -> 400")

    async def failing_narration(text, speed=1.0):
        raise httpx.ConnectError("connection refused")

    tools.generate_kokoro_narration = failing_narration
    try:
        await api.tts_narration(api.TTSNarrationRequest(text="안녕하세요"))
        raise AssertionError("backend failure was not surfaced")
    except HTTPException as exc:
        assert exc.status_code == 502, exc
        assert "Kokoro" in exc.detail
    print("PASS: Kokoro backend failure -> 502")


if __name__ == "__main__":
    asyncio.run(main())
