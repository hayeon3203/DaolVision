"""Task 4.1 검증: POST /t2i가 앵커 이미지(base64)를 반환하는지, 빈 prompt/백엔드
장애를 올바른 HTTP 상태로 표면하는지 확인. Flux(:8501) 실호출 없이 tools.generate_t2i_anchor를
가짜로 교체해 GPU 없이 돈다.

    python test_t2i_endpoint.py
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


async def main():
    async def fake_anchor(prompt, width=None, height=None, seed=None):
        assert prompt == "test"
        return {"image_base64": base64.b64encode(b"fake-png-bytes").decode(), "seconds": 1.2}

    tools.generate_t2i_anchor = fake_anchor

    result = await api.t2i(api.T2IRequest(prompt="test"))
    assert result.get("image_base64"), result
    assert base64.b64decode(result["image_base64"]) == b"fake-png-bytes"
    print("PASS: /t2i가 base64 이미지 반환")

    try:
        await api.t2i(api.T2IRequest(prompt="  "))
        raise AssertionError("빈 prompt가 거부되지 않음")
    except HTTPException as e:
        assert e.status_code == 400, e
    print("PASS: 빈 prompt -> 400")

    async def failing_anchor(prompt, width=None, height=None, seed=None):
        raise httpx.ConnectError("connection refused")

    tools.generate_t2i_anchor = failing_anchor
    try:
        await api.t2i(api.T2IRequest(prompt="test"))
        raise AssertionError("백엔드 장애가 502로 표면되지 않음")
    except HTTPException as e:
        assert e.status_code == 502, e
    print("PASS: T2I 백엔드 장애 -> 502")


if __name__ == "__main__":
    asyncio.run(main())
    sys.exit(0)
