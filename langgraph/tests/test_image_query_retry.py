"""M2-1 node_rewrite_image_query: 파싱 실패 시 조용히 빈 결과 대신 재시도 안내로 실패해야 함."""
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import nodes


async def test_empty_request_short_circuits():
    result = await nodes.node_rewrite_image_query({"image_request": ""})
    assert result == {"image_queries": [], "image_query": ""}


async def test_malformed_json_raises_retry_message():
    with patch("tools.call_llm", new=AsyncMock(return_value="not json at all")):
        try:
            await nodes.node_rewrite_image_query({"image_request": "고양이 그려줘"})
            raise AssertionError("malformed JSON이 예외 없이 통과됨")
        except ValueError as e:
            assert "다시 시도" in str(e), e


async def test_valid_json_returns_queries():
    raw = '[{"query": "a cute cat, anime style"}]'
    with patch("tools.call_llm", new=AsyncMock(return_value=raw)):
        result = await nodes.node_rewrite_image_query({"image_request": "고양이 그려줘"})
    assert result["image_queries"] == ["a cute cat, anime style"]
    assert result["image_query"] == "a cute cat, anime style"


async def test_multi_image_llm_response_capped_to_one():
    """1장 고정 정책(job 78f91567 — flux_server.py 동시요청 레이스로 500 재현) 이후에도
    LLM이 옛 습관대로 여러 개를 반환하면 방어적으로 1개까지만 취해야 한다."""
    raw = '[{"query": "a cat"}, {"query": "a dog"}, {"query": "a bird"}]'
    with patch("tools.call_llm", new=AsyncMock(return_value=raw)):
        result = await nodes.node_rewrite_image_query({"image_request": "고양이랑 강아지랑 새 그려줘"})
    assert result["image_queries"] == ["a cat"]


if __name__ == "__main__":
    asyncio.run(test_empty_request_short_circuits())
    asyncio.run(test_malformed_json_raises_retry_message())
    asyncio.run(test_valid_json_returns_queries())
    asyncio.run(test_multi_image_llm_response_capped_to_one())
    print("ok: empty request short-circuits, no LLM call")
    print("ok: malformed JSON raises ValueError with 다시 시도 guidance (surfaces via /status error)")
    print("ok: valid JSON still returns queries as before")
    print("ok: LLM이 여러 개 반환해도 1개로 방어적 cap")
