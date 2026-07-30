"""M3-11 LLM 스토리텔링 자막 검증.

LLM이 장면 흐름에 맞춰 자막을 새로 쓰되, 개수·순서 계약을 지키고
실패·개수불일치 시 원문 text로 폴백해 자막이 비지 않는지 확인.

    ./.venv/bin/python tests/test_subtitle_storytelling.py
"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tools

SCENES = [
    {"id": 2, "text": "회의실 책상", "duration": 3, "mood": "neutral"},
    {"id": 1, "text": "밝은 방", "duration": 2, "mood": "bright"},
]


def _run(coro):
    return asyncio.run(coro)


def test_uses_llm_lines_in_scene_order():
    """LLM이 개수 맞게 반환하면 그 자막을, 항상 id 오름차순으로 사용."""
    llm_out = '["아침 햇살이 방을 채운다.", "회의가 시작되려 한다."]'
    with patch.object(tools, "call_llm", AsyncMock(return_value=llm_out)):
        lines = _run(tools.generate_subtitle_lines(SCENES))
    assert lines == ["아침 햇살이 방을 채운다.", "회의가 시작되려 한다."], lines
    print("ok: LLM 자막을 id 순서대로 사용")


def test_fallback_on_count_mismatch():
    """개수 불일치는 신뢰 불가 — 원문 text로 폴백(순서도 id 오름차순)."""
    with patch.object(tools, "call_llm", AsyncMock(return_value='["한 줄뿐"]')):
        lines = _run(tools.generate_subtitle_lines(SCENES))
    assert lines == ["밝은 방", "회의실 책상"], lines
    print("ok: 개수 불일치 시 원문 폴백")


def test_fallback_on_llm_error():
    """LLM 예외에도 자막이 비지 않는다."""
    with patch.object(tools, "call_llm", AsyncMock(side_effect=RuntimeError("down"))):
        lines = _run(tools.generate_subtitle_lines(SCENES))
    assert lines == ["밝은 방", "회의실 책상"], lines
    print("ok: LLM 실패 시 원문 폴백")


if __name__ == "__main__":
    test_uses_llm_lines_in_scene_order()
    test_fallback_on_count_mismatch()
    test_fallback_on_llm_error()
    print("\nPASS: M3-11 스토리텔링 자막")
