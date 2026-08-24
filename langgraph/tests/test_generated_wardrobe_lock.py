"""생성 인물의 의상이 전 씬 wardrobe lock으로 승격되는지 회귀 테스트.

2026-08-13 job 953eeea2 clip1 실측: 인물 정본은 흰 반팔인데 영상에서는 검은 바시티
재킷을 입고 나왔다. Face-ID는 얼굴만 잡고 의상은 프롬프트가 결정하는데, 씬 프롬프트에
의상 지시가 하나도 없었기 때문이다.

wardrobe_locks는 원래 사용자가 시나리오에 "img_0 의상: ..."처럼 직접 선언한 경우에만
채워졌다. 이미지를 생성해 쓰는 M2 플로우에는 그 선언이 없으므로, 이미지 생성
프롬프트의 `wearing ...` 구절을 인물 참조의 lock으로 승격한다.

    cd langgraph && ./.venv/bin/python tests/test_generated_wardrobe_lock.py
"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import nodes

PERSON, PRODUCT = "gen_0.png", "img_0.png"
IMAGE_QUERY = ("A photorealistic portrait of a 20-year-old Korean man with short black "
               "hair wearing a white short-sleeve t-shirt, facing the camera directly.")


def test_wardrobe_extracted_from_image_query():
    assert nodes._wardrobe_from_query(IMAGE_QUERY) == "a white short-sleeve t-shirt"
    assert nodes._wardrobe_from_query("no clothing clause here") == ""


async def _prompts(scene: dict, image_query: str, script_locks: dict | None = None) -> dict:
    state = {
        "job_id": "t", "scenes": [scene], "image_query": image_query,
        "ref_images": [PERSON, PRODUCT],
        "ref_captions": {PERSON: "Young East Asian man", PRODUCT: "Plastic bottle with orange cap"},
        "wardrobe_locks": script_locks or {},
        "style_bible": "cinematic golden hour", "character_sheet": "",
    }
    captured = {}

    async def fake_llm(system, user):
        captured.setdefault("user", user)
        return "a man runs across the court"

    with patch("tools.call_llm", new=AsyncMock(side_effect=fake_llm)):
        out = await nodes.node_generate_prompts(state)
    return {"scene": out["scenes"][0], "user_prompt": captured.get("user", "")}


async def test_faceid_scene_gets_generated_wardrobe():
    """인물 참조가 붙은 씬(Face-ID 경로)의 프롬프트에 의상이 들어가야 한다."""
    scene = {"id": 1, "text": "한 남자가 농구장에서 달린다.", "mood": "excited",
             "duration": 3.0, "matched_image": PERSON, "image_role": "ref",
             "subject_type": "human", "setting": "an outdoor court", "lighting": "warm"}
    result = await _prompts(scene, IMAGE_QUERY)
    assert "short-sleeve" in result["scene"]["prompt"], \
        f"의상 lock이 프롬프트에 안 들어감: {result['scene']['prompt'][:200]}"


async def test_user_declared_lock_wins():
    """사용자가 시나리오에 직접 선언한 의상이 생성 프롬프트 값보다 우선한다."""
    scene = {"id": 1, "text": "한 남자가 달린다.", "mood": "excited", "duration": 3.0,
             "matched_image": PERSON, "image_role": "ref", "subject_type": "human",
             "setting": "an outdoor court", "lighting": "warm"}
    result = await _prompts(scene, IMAGE_QUERY, script_locks={PERSON: "빨간 유니폼"})
    assert "빨간 유니폼" in result["scene"]["prompt"]
    assert "short-sleeve" not in result["scene"]["prompt"]


async def main() -> None:
    test_wardrobe_extracted_from_image_query()
    await test_faceid_scene_gets_generated_wardrobe()
    await test_user_declared_lock_wins()
    print("test_generated_wardrobe_lock: all passed")


if __name__ == "__main__":
    asyncio.run(main())
