"""_make_scene_context의 setting 폴백 회귀 테스트.

2026-08-13 A/B 실측(Nemotron 4B·exaone 32b 공통): 4씬 중 씬1만 장소 추출에 성공하고
2~4는 폴백이 걸려 setting에 **한국어 씬 원문**이 그대로 들어갔다. 장소 정보가 사실상
없으니 프롬프트 LLM이 장소를 자유 창작해 같은 광고 안에서 농구장이 광장·공원·
테니스장으로 튀었다(테니스 라켓까지 등장).

폴백을 "가장 가까운 유효 장소 상속"으로 바꿨다. 이게 풀리면 배경 불일치가 재발한다.

    cd langgraph && ./.venv/bin/python tests/test_scene_setting_forward_fill.py
"""
import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import nodes

SCENES = [
    {"id": 1, "text": "한 남자가 농구장에서 드리블한다.", "mood": "excited"},
    {"id": 2, "text": "그는 코트 한쪽 벤치의 음료수를 향해 달려간다.", "mood": "excited"},
    {"id": 3, "text": "벤치 앞에서 멈춰 음료수를 들이켠다.", "mood": "happy"},
    {"id": 4, "text": "다시 코트로 돌아가 공을 잡는다.", "mood": "excited"},
]


async def _context(llm_reply: dict) -> dict[int, str]:
    state = {"scenes": SCENES, "script_text": "..."}
    with patch("tools.call_llm", new=AsyncMock(return_value=json.dumps(llm_reply, ensure_ascii=False))):
        _, setting, _person = await nodes._make_scene_context(state)
    return setting


async def test_missing_settings_inherit_instead_of_raw_korean_text():
    """씬1만 장소를 얻은 실측 케이스. 2~4가 원문으로 채워지면 안 된다."""
    setting = await _context({
        "1": {"lighting": "bright", "setting": "an outdoor basketball court"},
        "2": {"lighting": "bright", "setting": ""},
        "3": {"lighting": "soft", "setting": ""},
        "4": {"lighting": "bright", "setting": ""},
    })
    for sid in (2, 3, 4):
        assert setting[sid] == "an outdoor basketball court", f"씬{sid} 상속 실패: {setting[sid]}"
        assert "음료수" not in setting[sid] and "벤치" not in setting[sid], \
            f"씬{sid} setting에 한국어 원문이 들어감: {setting[sid]}"


async def test_leading_gap_uses_first_valid_setting():
    """선두 씬의 장소가 비면 뒤에서 나온 첫 유효값을 끌어온다(빈 문자열 방지)."""
    setting = await _context({
        "1": {"setting": ""},
        "2": {"setting": "a rooftop at dusk"},
        "3": {"setting": ""},
        "4": {"setting": ""},
    })
    assert setting[1] == "a rooftop at dusk"
    assert setting[4] == "a rooftop at dusk"


async def test_explicit_location_change_is_respected():
    """장소가 실제로 바뀌는 스토리는 그 지점부터 갈아탄다 — 전 씬을 첫 장소로 덮으면 안 된다."""
    setting = await _context({
        "1": {"setting": "an outdoor basketball court"},
        "2": {"setting": ""},
        "3": {"setting": "a quiet locker room"},
        "4": {"setting": ""},
    })
    assert setting[2] == "an outdoor basketball court"
    assert setting[3] == "a quiet locker room"
    assert setting[4] == "a quiet locker room"


async def main() -> None:
    await test_missing_settings_inherit_instead_of_raw_korean_text()
    await test_leading_gap_uses_first_valid_setting()
    await test_explicit_location_change_is_respected()
    print("test_scene_setting_forward_fill: all passed")


if __name__ == "__main__":
    asyncio.run(main())
