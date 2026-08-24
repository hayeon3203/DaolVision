"""1단계 결정론 상수 회귀 테스트 (2026-08-13).

스파이크가 확정한 그림은 프롬프트·시드·길이·조명이 전부 상수였기 때문에 나왔다.
프로덕션은 그것들을 LLM/job_id에 넘겨 매번 다른 결과를 냈다:
  - 시드가 job_id 해시 → 같은 입력이 매번 다른 추첨(재현 불가)
  - duration을 LLM이 2~3초로 정함 → 49프레임 씬은 인물이 이동할 시간이 없어
    "슬로우모션"으로 보임(job e9059c29 씬2·4)
  - 조명이 mood에서 파생 → 한 광고 안에서 deep shadows / cool cast / dusk가 공존
  - setting이 한국어 → Flux Kontext(영어 전용)에 노이즈로 들어가 장소 지시 증발

    cd langgraph && ./.venv/bin/python tests/test_deterministic_scene_constants.py
"""
import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import nodes


def test_seed_is_job_independent_but_scene_varying():
    assert nodes.scene_seed("job-A", 1) == nodes.scene_seed("job-B", 1), \
        "job이 달라지면 시드가 달라져 스파이크 결과를 재현할 수 없다"
    assert nodes.scene_seed("job-A", 1) != nodes.scene_seed("job-A", 2), \
        "씬별 시드가 같으면 저스텝 조합에서 모션이 수렴한다(job f1be24f6 실측)"


async def test_duration_is_fixed_regardless_of_llm():
    """LLM이 2초를 주든 10초를 주든 상수로 고정된다."""
    raw = [{"text": f"씬 {i}", "duration": d, "mood": "neutral"}
           for i, d in enumerate([1.0, 2.0, 5.0, 10.0], 1)]
    state = {"job_id": "t", "script_text": "x", "ref_images": [], "ref_captions": {}}
    with patch("tools.call_llm", new=AsyncMock(return_value=json.dumps(raw, ensure_ascii=False))):
        scenes = (await nodes.node_split_scenes(state))["scenes"]
    assert {s["duration"] for s in scenes} == {nodes.SCENE_DURATION_SECONDS}


def test_lighting_lock_is_golden_hour_and_single():
    """조명 상수가 비어 있으면 mood 파생으로 돌아가 씬마다 톤이 튄다."""
    assert nodes.SCENE_LIGHTING_LOCK, "조명 고정이 꺼져 있다"
    assert "golden" in nodes.SCENE_LIGHTING_LOCK.lower()


def test_setting_prompt_demands_english():
    """setting이 한국어로 나오면 조립 배경 프롬프트에서 장소가 증발한다."""
    system = nodes._LIGHTING_SYSTEM
    assert "ALWAYS written in English" in system
    assert "어두운 사무실" not in system, "예시가 한국어면 모델이 그대로 따라 쓴다"


async def main() -> None:
    test_seed_is_job_independent_but_scene_varying()
    await test_duration_is_fixed_regardless_of_llm()
    test_lighting_lock_is_golden_hour_and_single()
    test_setting_prompt_demands_english()
    print("test_deterministic_scene_constants: all passed")


if __name__ == "__main__":
    asyncio.run(main())
