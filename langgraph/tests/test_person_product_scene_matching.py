"""6.23 — 인물 참조 1장 + 제품 참조 1장 job의 결정론적 씬 배정 회귀 테스트.

E2E job f11798c7(2026-08-13) 실측: 참조 2장을 주면 LLM이 4씬 중 2씬을 틀리게
매칭했다.
  - "벤치 앞에 멈춰 음료수를 집어 든다" → subject_type=nonhuman (주인공이 지워지는
    조합. _scene_prompt_system이 "사람을 만들지 마라"를 건다)
  - "고개를 들고 들이켰다" → subject_type=human인데 matched_image=제품 사진.
    _normalise_image_role이 role=ref로 정규화해 Face-ID에 병 사진이 들어갈 뻔했다.

그래서 이 조합에서는 LLM 매칭을 무시하고 참조 종류만으로 배정한다. 이 결정론이
깨지면 위 두 증상이 그대로 재발한다.

    cd langgraph && ./.venv/bin/python tests/test_person_product_scene_matching.py
"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import nodes

PERSON = "gen_0.png"
PRODUCT = "img_0.png"
CAPTIONS = {
    PERSON: "Young East Asian male, white tank top, standing in a dark corridor.",
    PRODUCT: 'Plastic bottle containing liquid labeled "Urtage"',
}
# E2E에서 LLM이 실제로 뱉었던(틀린) 매칭 — 결정론 배정이 이걸 덮어써야 한다.
LLM_SCENES = [
    {"text": "한 남자가 농구장에서 땀 흘리며 드리블하고 점프슛을 쏜다.",
     "duration": 3, "mood": "excited", "matched_image": PERSON,
     "subject_type": "human", "image_role": "ref"},
    {"text": "그는 코트 한쪽 벤치에 놓인 음료수를 향해 달려간다.",
     "duration": 3, "mood": "excited", "matched_image": PERSON,
     "subject_type": "human", "image_role": "ref"},
    {"text": "벤치 앞에 멈춰 음료수를 집어 든다.",
     "duration": 3, "mood": "neutral", "matched_image": PRODUCT,
     "subject_type": "nonhuman", "image_role": "character_ref"},
    # E2E job 911ebd9c 실측: 4B가 이 문장만 영어로 번역해 뱉었다. "음료수"도
    # bottle/drink도 안 걸리므로 씬별 키워드 매칭으로는 제품 씬으로 못 잡는다.
    {"text": "heads up, he takes a sip of cool water.",
     "duration": 3, "mood": "happy", "matched_image": PRODUCT,
     "subject_type": "human", "image_role": "ref"},
]


async def _split() -> list[dict]:
    state = {
        "job_id": "t",
        "script_text": "\n".join(s["text"] for s in LLM_SCENES),
        "ref_images": [PERSON, PRODUCT],
        "ref_captions": CAPTIONS,
    }
    import json
    with patch("tools.call_llm", new=AsyncMock(return_value=json.dumps(LLM_SCENES, ensure_ascii=False))):
        return (await nodes.node_split_scenes(state))["scenes"]


async def test_person_is_face_ref_in_every_scene():
    scenes = await _split()
    assert len(scenes) == 4
    for sc in scenes:
        assert sc["face_id_ref"] == PERSON, f"씬{sc['id']} 주인공 얼굴 참조 누락: {sc}"
        assert sc["subject_type"] == "human", \
            f"씬{sc['id']} subject_type={sc['subject_type']} — 주인공이 지워지는 조합"


async def test_product_scenes_use_product_as_character_ref():
    """제품은 첫 등장 이후 forward-fill된다. 씬4는 LLM이 영어로 번역해버려 키워드가
    하나도 안 걸리는데(실측), 씬2에서 이미 등장했으므로 제품 씬으로 유지돼야 한다."""
    scenes = await _split()
    # 1번 씬만 제품 등장 전이다.
    assert scenes[0]["matched_image"] == PERSON
    assert scenes[0]["image_role"] == "ref"
    for sc in scenes[1:]:
        assert sc["matched_image"] == PRODUCT, f"씬{sc['id']}이 제품을 안 잡음"
        assert sc["image_role"] == "character_ref"


async def test_scene_before_first_product_mention_stays_person_only():
    """등장 전 씬까지 제품으로 칠하면 안 된다 — 씬1(농구)은 순수 인물 생성 경로다."""
    scenes = await _split()
    assert not nodes._PRODUCT_TEXT.search(scenes[0]["text"])
    assert scenes[0]["image_role"] == "ref"
    assert scenes[0]["matched_image"] == PERSON


async def test_classify_preserves_preset_face_ref():
    """제품 씬은 matched_image가 제품이라 기존 식으로는 face_id_ref가 None이 된다.
    미리 설정된 값이 보존되지 않으면 주인공 identity가 통째로 날아간다."""
    scenes = await _split()
    out = nodes.node_classify_faceid_scenes({"scenes": scenes})["scenes"]
    for sc in out:
        assert sc["face_id_ref"] == PERSON, f"씬{sc['id']} face_id_ref 소실: {sc}"
    # 제품 없는 씬만 Face-ID 배치로 간다(제품 씬은 조립 경로 담당).
    assert out[0]["mode"] == "LTX_FACEID"
    for sc in out[1:]:
        assert sc["mode"] != "LTX_FACEID", f"씬{sc['id']}이 Face-ID 배치로 샜다"


async def main() -> None:
    await test_person_is_face_ref_in_every_scene()
    await test_product_scenes_use_product_as_character_ref()
    await test_scene_before_first_product_mention_stays_person_only()
    await test_classify_preserves_preset_face_ref()
    print("test_person_product_scene_matching: all passed")


if __name__ == "__main__":
    asyncio.run(main())
