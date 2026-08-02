"""Task 7.6 검증: POST /t2v(Cosmos3-Nano 단발샷)가 프롬프트만으로 base64 영상을
반환하는지, 빈 prompt/백엔드 장애가 올바른 HTTP 상태로 표면되는지 확인.
t2v/cosmos3nano 서버(:8505) 실호출 없이 tools.generate_t2v_cosmos3nano를 가짜로
교체해 GPU 없이 돈다.

_ltx13b_dims 회귀 테스트는 이전 I2V 단발샷(Task 4.6)에서 남은 것 — 그 함수는
여전히 job 파이프라인의 I2V 폴백 클립 생성에서 공유되므로 유지한다.

    ./.venv/bin/python tests/test_t2v_oneshot.py
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
    async def fake_t2v(prompt, seed=None, width=640, height=480, num_frames=49):
        assert prompt == "test"
        return {"video_base64": base64.b64encode(b"fake-mp4-bytes").decode(),
                "width": width, "height": height}

    tools.generate_t2v_cosmos3nano = fake_t2v

    result = await api.t2v_oneshot(api.T2VRequest(prompt="test"))
    assert result.get("video_base64"), result
    assert base64.b64decode(result["video_base64"]) == b"fake-mp4-bytes"
    print("PASS: /t2v가 base64 영상 반환")

    try:
        await api.t2v_oneshot(api.T2VRequest(prompt="  "))
        raise AssertionError("빈 prompt가 거부되지 않음")
    except HTTPException as e:
        assert e.status_code == 400, e
    print("PASS: 빈 prompt -> 400")

    async def failing_t2v(prompt, seed=None, width=640, height=480, num_frames=49):
        raise httpx.ConnectError("connection refused")

    tools.generate_t2v_cosmos3nano = failing_t2v
    try:
        await api.t2v_oneshot(api.T2VRequest(prompt="test"))
        raise AssertionError("백엔드 장애가 502로 표면되지 않음")
    except HTTPException as e:
        assert e.status_code == 502, e
    print("PASS: T2V 백엔드 장애 -> 502")


def main():
    test_dims_match_input_aspect_ratio_in_32_multiples()
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()
    sys.exit(0)
