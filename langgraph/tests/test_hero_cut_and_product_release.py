"""마무리 히어로컷(씬5) + 제품 상속 해제 + 배경 제품 명사 제거 회귀 테스트.

2026-08-13 UI E2E job 3ded2f29 실측 증상 3개를 고정한다.
  - clip2 페트병 2개: 배경 T2I 프롬프트에서 제품 명사구가 안 지워졌다
    (`a water bottle`, `the approaching bottle` — 수식어 열거형 정규식이 뚫림).
  - clip4 뜬금없는 페트병: 제품 forward-fill이 안 끊겨, 제품이 손을 떠난 뒤의 씬까지
    조립 경로로 갔다.
  - 마무리 히어로컷 부재: 씬 개수가 4로 하드코딩돼 있고, 인물 없는 제품 단독 컷에도
    "인물이 카메라로 다가온다" 프레이밍이 강제됐다.

    cd langgraph && AGENT_SCENE_COUNT=5 ./.venv/bin/python tests/test_hero_cut_and_product_release.py
"""
import asyncio
import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# nodes.SCENE_COUNT는 import 시점에 env를 읽는다 — import 전에 세팅해야 한다.
os.environ["AGENT_SCENE_COUNT"] = "5"

import nodes            # noqa: E402
import tools            # noqa: E402

PERSON, PRODUCT = "gen_0.png", "img_0.png"
CAPTIONS = {
    PERSON: "Young East Asian male in a white t-shirt.",
    PRODUCT: 'Plastic bottle containing liquid labeled "Urtage"',
}
SCENES_5 = [
    {"text": "젊은 남자가 농구 코트를 가로질러 공을 드리블하며 달린다.",
     "duration": 3, "mood": "excited", "matched_image": PERSON,
     "subject_type": "human", "image_role": "ref"},
    {"text": "남자는 코트 한쪽 벤치에 놓인 물병을 향해 힘차게 달려간다.",
     "duration": 3, "mood": "excited", "matched_image": PERSON,
     "subject_type": "human", "image_role": "ref"},
    {"text": "남자가 벤치 앞에 멈춰 물병을 집어 들고 시원하게 들이켠다.",
     "duration": 3, "mood": "happy", "matched_image": PRODUCT,
     "subject_type": "nonhuman", "image_role": "character_ref"},
    # 제품이 손을 떠난 씬 — 여기에 제품이 합성되면 clip4 증상 재발이다.
    {"text": "남자는 다시 농구 코트로 돌아가 공을 잡고 힘차게 달려나간다.",
     "duration": 3, "mood": "excited", "matched_image": PRODUCT,
     "subject_type": "human", "image_role": "character_ref"},
    # 마무리 히어로컷 — 인물 없이 제품만.
    {"text": "빈 농구 코트를 배경으로 제품이 벤치 위에 홀로 놓여 크게 빛난다.",
     "duration": 3, "mood": "calm", "matched_image": PRODUCT,
     "subject_type": "nonhuman", "image_role": "character_ref"},
]


async def _split() -> list[dict]:
    state = {
        "job_id": "t",
        "script_text": "\n".join(s["text"] for s in SCENES_5),
        "ref_images": [PERSON, PRODUCT],
        "ref_captions": CAPTIONS,
    }
    with patch("tools.call_llm",
               new=AsyncMock(return_value=json.dumps(SCENES_5, ensure_ascii=False))):
        return (await nodes.node_split_scenes(state))["scenes"]


async def test_five_scenes_survive_normalisation():
    """SCENE_COUNT를 안 맞춰두면 LLM에 '4개로 나눠라'가 나가고 정규화가 5번째를 합친다."""
    assert nodes.SCENE_COUNT == 5
    scenes = await _split()
    assert len(scenes) == 5, f"씬 개수 {len(scenes)} — 히어로컷이 합쳐졌다"


async def test_product_released_when_it_leaves_the_hand():
    """clip4 회귀: 제품 명사도 손동작도 없는 인물 씬은 제품 상속을 끊는다."""
    scenes = await _split()
    s4 = scenes[3]
    assert s4["matched_image"] == PERSON, "제품이 손을 떠난 씬에 제품이 붙었다(clip4 증상)"
    assert s4["image_role"] == "ref"
    assert s4["face_id_ref"] == PERSON


async def test_drinking_scene_keeps_product_even_when_translated():
    """상속 해제가 과하면 안 된다 — 번역돼 제품 명사가 사라진 음용 씬은 유지돼야 한다."""
    text = "heads up, he takes a sip of cool water."
    assert nodes._PRODUCT_TEXT.search(text), "번역된 음용 씬을 제품 씬으로 못 잡는다"


async def test_hero_cut_has_no_face_ref():
    """히어로컷에 얼굴 참조가 붙으면 조립 경로가 인물 배경을 그려 제품 단독 컷이 안 된다."""
    scenes = await _split()
    hero = scenes[4]
    assert hero["face_id_ref"] is None, f"히어로컷에 얼굴 참조가 붙음: {hero}"
    assert hero["subject_type"] == "nonhuman"
    assert hero["matched_image"] == PRODUCT
    assert hero["image_role"] == "character_ref"


async def test_hero_cut_routes_to_assembly():
    """face_id_ref가 없어도 제품 씬은 조립 경로다(제품 픽셀을 diffusion에 안 태우는 게 요지)."""
    scenes = await _split()
    state = {
        "job_id": "t", "scenes": scenes[4:], "ref_images": [PERSON, PRODUCT],
        "ref_captions": CAPTIONS, "style_bible": "cinematic golden hour",
        "character_sheet": "",
    }
    with patch("tools.call_llm", new=AsyncMock(return_value="the product rests on a bench")):
        out = (await nodes.node_generate_prompts(state))["scenes"]
    assert out[0]["mode"] == "PRODUCT_ASSEMBLY", f"히어로컷 라우팅: {out[0]['mode']}"
    assert out[0]["product_hand_held"] is False


def test_hero_framing_has_no_person_clause():
    """PRODUCT_PLACED_FRAMING을 히어로컷에 쓰면 사람이 생긴다."""
    hero = tools.PRODUCT_HERO_FRAMING.lower()
    assert "no people" in hero and "no person visible" in hero
    for banned in ("approaching the viewer", "face and chest visible", "moving toward the camera"):
        assert banned not in hero, f"히어로컷 프레이밍에 인물 강제 문구: {banned}"
    # 히어로컷 제품은 소품이 아니라 화면의 주인공이어야 한다. 배수로 재면 놓인 씬 폭이
    # 바뀔 때마다 같이 흔들리므로(2026-08-14 놓인 폭 0.075→0.15,
    # docs/spikes/2026-08-13-scene5-e2e-handoff.md §4.5-2) 사용자가 "딱 좋음"으로 승인한
    # 실측값 자체를 못박는다 — 폭 383px/1280 = 0.30(같은 문서 §4.5 표, 씬5).
    assert tools.PRODUCT_HERO_RATIOS[0] >= 0.30
    assert tools.PRODUCT_HERO_RATIOS[0] > tools.PRODUCT_PLACED_RATIOS[0]


def test_strip_product_phrases_catches_real_e2e_prompts():
    """job 3ded2f29 씬2 프롬프트 원문 — 이 둘이 안 지워져 배경에 병이 생겼다."""
    src = ("reaching towards a water bottle resting on the wooden bench beside him; "
           "focused intently on the approaching bottle")
    out = tools._strip_product_phrases(src)
    assert "bottle" not in out.lower(), f"제품 명사가 남음: {out}"
    # 배경 정보는 보존돼야 한다 — 벤치가 사라지면 제품이 놓일 면이 없어진다.
    assert "wooden bench" in out, f"배경 서술까지 지워짐: {out}"


def test_strip_product_phrases_keeps_unrelated_nouns():
    """과잉 삭제 방지 — 제품이 아닌 명사구는 그대로 남는다."""
    src = "a young man sprints across the asphalt court toward the empty bench"
    assert tools._strip_product_phrases(src) == src


async def main() -> None:
    await test_five_scenes_survive_normalisation()
    await test_product_released_when_it_leaves_the_hand()
    await test_drinking_scene_keeps_product_even_when_translated()
    await test_hero_cut_has_no_face_ref()
    await test_hero_cut_routes_to_assembly()
    test_hero_framing_has_no_person_clause()
    test_strip_product_phrases_catches_real_e2e_prompts()
    test_strip_product_phrases_keeps_unrelated_nouns()
    print("test_hero_cut_and_product_release: all passed")


if __name__ == "__main__":
    asyncio.run(main())
