"""Task 6.1 검증: POST /i2i가 style_presets.py(4.5) 6종 프리픽스로 base64 이미지를
반환하는지, 미지원 style/이미지 누락/백엔드 장애가 올바른 HTTP 상태로 표면되는지,
_flux_kontext_dims가 ComfyUI FluxKontextImageScale과 동일한 해상도 버킷을 고르는지
확인. ComfyUI(:8188) 실호출 없이 tools.generate_i2i_style을 가짜로 교체해 GPU 없이 돈다
— Flux Kontext dev 체크포인트가 아직 다운로드되지 않아 실제 추론은 별도 검증 필요.

    ./.venv/bin/python tests/test_i2i_style.py
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


def test_dims_match_nearest_kontext_resolution_bucket():
    # 1024x1024 근방 정방형 입력 → 정확히 1024x1024 버킷.
    w, h = tools._flux_kontext_dims(1000, 1000)
    assert (w, h) == (1024, 1024), (w, h)

    # 세로로 긴 입력 → 세로가 긴 버킷 선택.
    w, h = tools._flux_kontext_dims(672, 1568)
    assert h > w, (w, h)
    assert (w, h) in tools.FLUX_KONTEXT_RESOLUTIONS, (w, h)
    print("ok: 해상도가 FluxKontextImageScale과 동일한 버킷으로 산정됨")


async def _async_main():
    async def fake_i2i(image_bytes, style, seed=None):
        assert style == "cinematic"
        assert image_bytes == b"fake-jpg-bytes"
        return {"image_base64": base64.b64encode(b"fake-png-bytes").decode(),
                "width": 1024, "height": 1024}

    tools.generate_i2i_style = fake_i2i

    result = await api.i2i_style(style="cinematic", image=_FakeUpload(b"fake-jpg-bytes"), seed=None)
    assert result.get("image_base64"), result
    assert base64.b64decode(result["image_base64"]) == b"fake-png-bytes"
    print("PASS: /i2i가 base64 이미지 반환")

    try:
        await api.i2i_style(style="does-not-exist", image=_FakeUpload(b"fake-jpg-bytes"), seed=None)
        raise AssertionError("미지원 style이 거부되지 않음")
    except HTTPException as e:
        assert e.status_code == 400, e
    print("PASS: 미지원 style -> 400")

    try:
        await api.i2i_style(style="cinematic", image=_FakeUpload(b""), seed=None)
        raise AssertionError("빈 이미지가 거부되지 않음")
    except HTTPException as e:
        assert e.status_code == 422, e
    print("PASS: 빈 이미지 -> 422")

    async def failing_i2i(image_bytes, style, seed=None):
        raise httpx.ConnectError("connection refused")

    tools.generate_i2i_style = failing_i2i
    try:
        await api.i2i_style(style="cinematic", image=_FakeUpload(b"fake-jpg-bytes"), seed=None)
        raise AssertionError("백엔드 장애가 502로 표면되지 않음")
    except HTTPException as e:
        assert e.status_code == 502, e
    print("PASS: I2I 백엔드 장애 -> 502")


def main():
    test_dims_match_nearest_kontext_resolution_bucket()
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()
    sys.exit(0)
