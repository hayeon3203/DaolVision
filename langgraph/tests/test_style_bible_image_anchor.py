"""image_query(정지 이미지 앵커 프롬프트)가 있으면 _make_style_bible이 이를
LLM에 넘겨 영상 스타일을 이미지 화풍과 맞추도록 강제하는지 검증.

회귀 방지: image_query와 style_bible이 서로 다른 독립 LLM 호출로 생성돼
그림체가 어긋난 사례 실측(2026-07-10, job 41df3d06-d54a-424b-a56a-e6f08d1c7136
— 이미지는 anime illustration style, 영상 프롬프트는 3D render로 결정됨).

    ./.venv/bin/python tests/test_style_bible_image_anchor.py
"""
import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nodes import _make_style_bible


async def _run(state):
    with patch("tools.call_llm", new=AsyncMock(return_value="anime illustration style, cel-shaded")) as mock_llm:
        bible, _sheet = await _make_style_bible(state)  # no-ref 시트는 이 테스트 범위 밖
    return bible, mock_llm


def main():
    state = {
        "script_text": "고양이가 잔디밭에서 뛰어논다.",
        "scenes": [{"text": "고양이가 뛰어논다."}],
        "ref_captions": {},
        "image_query": "A fluffy cat ... anime illustration style.",
    }
    bible, mock_llm = asyncio.run(_run(state))
    system_prompt, user_prompt = mock_llm.call_args[0]
    assert "MUST match that image's" in system_prompt, "anchor 지시가 system_prompt에 없음"
    payload = json.loads(user_prompt)
    assert payload.get("image_anchor_prompt") == state["image_query"], "image_query가 user_prompt에 전달 안됨"
    assert bible == "anime illustration style, cel-shaded"
    print("ok: image_query 있으면 anchor 지시 + payload 주입")

    state_no_image = {**state, "image_query": ""}
    bible2, mock_llm2 = asyncio.run(_run(state_no_image))
    system_prompt2, user_prompt2 = mock_llm2.call_args[0]
    assert "MUST match that image's" not in system_prompt2, "image_query 없는데 anchor 지시 섞여들어감"
    assert "image_anchor_prompt" not in json.loads(user_prompt2)
    print("ok: image_query 없으면 기존 동작 유지")


if __name__ == "__main__":
    main()
