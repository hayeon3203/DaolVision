"""씬 장소 추출 누락 시 직전 장소가 아니라 해당 씬 원문으로 폴백하는지 검증."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import nodes


def test_missing_settings_fall_back_to_each_scene_text():
    responses = iter([
        '{"1":{"lighting":"soft dawn","setting":"눈 덮인 산골짜기"},'
        '"2":{"lighting":"warm daylight","setting":""},'
        '"3":{"lighting":"natural light","setting":""},'
        '"4":{"lighting":"dim light","setting":""}}',
        '{"1":{"lighting":"soft dawn","setting":"눈 덮인 산골짜기"},'
        '"2":{"lighting":"warm daylight","setting":""},'
        '"3":{"lighting":"natural light","setting":""},'
        '"4":{"lighting":"dim light","setting":""}}',
    ])

    async def fake_llm(*_args, **_kwargs):
        return next(responses)

    original = nodes.tools.call_llm
    nodes.tools.call_llm = fake_llm
    try:
        scenes = [
            {"id": 1, "text": "눈 덮인 산골짜기의 얼어붙은 호수", "mood": "calm"},
            {"id": 2, "text": "봄 들판에 야생화가 피어난다", "mood": "happy"},
            {"id": 3, "text": "여름 숲에 소나기와 무지개가 나타난다", "mood": "neutral"},
            {"id": 4, "text": "가을 호수에 붉은 낙엽이 내려앉는다", "mood": "sad"},
        ]
        _, settings = asyncio.run(nodes._make_scene_context({
            "script_text": " ".join(scene["text"] for scene in scenes),
            "scenes": scenes,
        }))
    finally:
        nodes.tools.call_llm = original

    assert settings == {
        1: "눈 덮인 산골짜기",
        2: scenes[1]["text"],
        3: scenes[2]["text"],
        4: scenes[3]["text"],
    }


if __name__ == "__main__":
    test_missing_settings_fall_back_to_each_scene_text()
    print("test_scene_context_fallback: all passed")
