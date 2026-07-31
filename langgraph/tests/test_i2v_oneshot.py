"""Task 4.6 검증: POST /i2v가 단발샷 영상(base64)을 반환하는지, 3.8 후속 버그
(하드코딩 768x512가 세로 사진 이마를 크롭하던 문제)가 입력 비율에 맞춘 32배수
해상도로 고쳐졌는지, 빈 prompt/이미지 누락/백엔드 장애가 올바른 HTTP 상태로
표면되는지 확인. ComfyUI(:8188) 실호출 없이 tools.generate_i2v_oneshot을
가짜로 교체해 GPU 없이 돈다.

    ./.venv/bin/python tests/test_i2v_oneshot.py
"""
import asyncio
import base64
import sys
from pathlib import Path

import httpx
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # langgraph/ 모듈 import용

import tools
import api


class _FakeUpload:
    def __init__(self, data: bytes):
        self._data = data

    async def read(self) -> bytes:
        return self._data


def test_dims_match_input_aspect_ratio_in_32_multiples():
    # 가로 사진(1.5:1, 3.8 스파이크의 원래 하드코딩값과 동일 비율) — 그대로 768x512 근방.
    w, h = tools._ltx13b_dims(1536, 1024)
    assert w % 32 == 0 and h % 32 == 0, (w, h)
    assert w == tools.LTX13B_MAX_DIM
    assert abs(w / h - 1536 / 1024) < 0.05, (w, h)

    # 세로 사진(3.8 후속 버그 재현 케이스: 856x1141) — 하드코딩 768x512(가로)를 쓰면
    # 안 되고, 세로가 긴 변이 돼야 한다.
    w, h = tools._ltx13b_dims(856, 1141)
    assert h > w, (w, h)
    assert h == tools.LTX13B_MAX_DIM
    assert w % 32 == 0 and h % 32 == 0, (w, h)
    assert abs(w / h - 856 / 1141) < 0.05, (w, h)
    print("ok: 해상도가 입력 비율에 맞춰 32배수로 산정됨")


async def _async_main():
    async def fake_i2v(image_bytes, prompt, seed=None):
        assert prompt == "test"
        assert image_bytes == b"fake-jpg-bytes"
        return {"video_base64": base64.b64encode(b"fake-webp-bytes").decode(),
                "width": 768, "height": 512}

    tools.generate_i2v_oneshot = fake_i2v

    result = await api.i2v_oneshot(prompt="test", image=_FakeUpload(b"fake-jpg-bytes"), seed=None)
    assert result.get("video_base64"), result
    assert base64.b64decode(result["video_base64"]) == b"fake-webp-bytes"
    print("PASS: /i2v가 base64 영상 반환")

    try:
        await api.i2v_oneshot(prompt="  ", image=_FakeUpload(b"fake-jpg-bytes"), seed=None)
        raise AssertionError("빈 prompt가 거부되지 않음")
    except HTTPException as e:
        assert e.status_code == 400, e
    print("PASS: 빈 prompt -> 400")

    try:
        await api.i2v_oneshot(prompt="test", image=_FakeUpload(b""), seed=None)
        raise AssertionError("빈 이미지가 거부되지 않음")
    except HTTPException as e:
        assert e.status_code == 422, e
    print("PASS: 빈 이미지 -> 422")

    async def failing_i2v(image_bytes, prompt, seed=None):
        raise httpx.ConnectError("connection refused")

    tools.generate_i2v_oneshot = failing_i2v
    try:
        await api.i2v_oneshot(prompt="test", image=_FakeUpload(b"fake-jpg-bytes"), seed=None)
        raise AssertionError("백엔드 장애가 502로 표면되지 않음")
    except HTTPException as e:
        assert e.status_code == 502, e
    print("PASS: I2V 백엔드 장애 -> 502")


def main():
    test_dims_match_input_aspect_ratio_in_32_multiples()
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()
    sys.exit(0)
