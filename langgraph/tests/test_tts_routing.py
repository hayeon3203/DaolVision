"""Task 4.2.1: narration and cloned-voice TTS stay on separate engines."""

import asyncio
import sys
from io import BytesIO
from pathlib import Path

import httpx
from fastapi import HTTPException, UploadFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import api
import tools


FAKE_WAV = b"RIFF" + (b"\x00" * 4) + b"WAVEfmt " + (b"\x00" * 32)


def upload(data: bytes = FAKE_WAV, filename: str = "reference.wav") -> UploadFile:
    return UploadFile(filename=filename, file=BytesIO(data))


async def main():
    clone_calls = []
    kokoro_calls = []

    async def fake_clone(text, reference_wav, filename):
        clone_calls.append((text, reference_wav, filename))
        return FAKE_WAV

    async def forbidden_kokoro(text, speed=1.0):
        kokoro_calls.append((text, speed))
        raise AssertionError("/tts/clone must not fall back to Kokoro")

    tools.generate_chatterbox_clone = fake_clone
    tools.generate_kokoro_narration = forbidden_kokoro

    response = await api.tts_clone(text=" 안녕하세요 ", reference=upload())
    assert response.media_type == "audio/wav", response.media_type
    assert response.body == FAKE_WAV
    assert response.headers["x-tts-engine"] == "chatterbox-v3"
    assert clone_calls == [("안녕하세요", FAKE_WAV, "reference.wav")]
    assert kokoro_calls == []
    print("PASS: /tts/clone -> Chatterbox V3 WAV only")

    for bad_reference in (None, upload(b"not a wav"), upload(filename="voice.mp3")):
        try:
            await api.tts_clone(text="안녕하세요", reference=bad_reference)
            raise AssertionError("missing/invalid reference was accepted")
        except HTTPException as exc:
            assert 400 <= exc.status_code < 500, exc
    print("PASS: missing/invalid reference -> 4xx")

    try:
        await api.tts_clone(text="  ", reference=upload())
        raise AssertionError("empty text was accepted")
    except HTTPException as exc:
        assert exc.status_code == 400, exc
    print("PASS: empty clone text -> 400")

    async def failing_clone(text, reference_wav, filename):
        raise httpx.ConnectError("connection refused")

    tools.generate_chatterbox_clone = failing_clone
    try:
        await api.tts_clone(text="안녕하세요", reference=upload())
        raise AssertionError("backend failure was not surfaced")
    except HTTPException as exc:
        assert exc.status_code == 502, exc
        assert "Chatterbox" in exc.detail
    assert kokoro_calls == []
    print("PASS: Chatterbox failure -> 502 without Kokoro fallback")


if __name__ == "__main__":
    asyncio.run(main())
