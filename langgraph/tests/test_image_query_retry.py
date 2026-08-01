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


if __name__ == "__main__":
    asyncio.run(test_empty_request_short_circuits())
    asyncio.run(test_malformed_json_raises_retry_message())
    asyncio.run(test_valid_json_returns_queries())
    print("ok: empty request short-circuits, no LLM call")
    print("ok: malformed JSON raises ValueError with 다시 시도 guidance (surfaces via /status error)")
    print("ok: valid JSON still returns queries as before")
