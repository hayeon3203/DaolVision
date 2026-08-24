"""제품만 첨부하는 "시나리오만" 모드 — 다양한 사람이 제품을 쓰는 광고 (2026-08-14).

인물 일관성(같은 사람이 5씬 내내 유지)을 포기하고, 대신 씬마다 다른 사람이 제품을
쓰는 시나리오로 간다는 사용자 결정. 인물 생성이 없으므로 job의 참조는 제품 1장뿐이다.

이 조합에서 이전 코드가 깨지던 지점 두 곳을 고정한다.
  1) 참조가 1장이면 전 씬 subject_type을 캡션값(nonhuman)으로 굳혔다 → 사람이 나오는
     씬까지 무인물 씬이 돼 SUBJECT_REF(Wan 참조 경로)로 갔다. 그 경로는 참조에 없는
     인물·손·동작을 못 그린다.
  2) 히어로컷 판정이 `face_ref is None`이었다 → 인물 참조가 아예 없는 이 모드에서는
     전 씬이 히어로컷("no people")이 돼 사람이 통째로 사라진다.

    cd langgraph && AGENT_SCENE_COUNT=5 ./.venv/bin/python tests/test_product_only_various_people.py
"""
import asyncio
import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("AGENT_SCENE_COUNT", "5")

import nodes            # noqa: E402
import tools            # noqa: E402

PRODUCT = "img_0.png"
CAPTIONS = {PRODUCT: 'Plastic bottle containing liquid labeled "Urtage"'}
SCENES_5 = [
    {"text": "운동을 마친 20대 여자가 체육관 벤치에 앉아 음료수를 들고 시원하게 마신다.",
     "duration": 3, "mood": "happy"},
    {"text": "사무실 책상 앞의 30대 남자가 서류에서 눈을 떼고 음료수를 집어 들어 한 모금 마신다.",
     "duration": 3, "mood": "calm"},
    # 번역돼 제품 명사가 사라진 씬 — 영어 손동작 어휘로도 인물 씬으로 잡혀야 한다.
    {"text": "A young woman in a library holds it and takes a slow sip.",
     "duration": 3, "mood": "calm"},
    {"text": "공사장 헬멧을 쓴 남자가 땀을 닦고 음료수를 쥐고 크게 들이켠다.",
     "duration": 3, "mood": "excited"},
    # 마무리 히어로컷 — 인물 명사도 손동작 어휘도 없다.
    {"text": "빈 카페 테이블 위에 놓인 제품에 카메라가 천천히 다가가며 멈춘다.",
     "duration": 3, "mood": "calm"},
]


async def _split() -> list[dict]:
    state = {
        "job_id": "t",
        "script_text": "\n".join(s["text"] for s in SCENES_5),
        "ref_images": [PRODUCT],
        "ref_captions": CAPTIONS,
    }
    with patch("tools.call_llm",
               new=AsyncMock(return_value=json.dumps(SCENES_5, ensure_ascii=False))):
        return (await nodes.node_split_scenes(state))["scenes"]


async def _prompts(scenes: list[dict]) -> list[dict]:
    state = {
        "job_id": "t", "scenes": scenes, "ref_images": [PRODUCT],
        "ref_captions": CAPTIONS, "style_bible": "cinematic golden hour",
        "character_sheet": "",
    }
    with patch("tools.call_llm", new=AsyncMock(return_value="a person drinks it")):
        return (await nodes.node_generate_prompts(state))["scenes"]


async def test_person_scenes_stay_human():
    """제품 1장짜리 job이라도 사람이 나오는 씬은 human이어야 한다(SUBJECT_REF 방지)."""
    scenes = await _split()
    for sc in scenes[:4]:
        assert sc["subject_type"] == "human", f"인물 씬이 nonhuman으로 굳음: {sc['text']}"
        assert sc["matched_image"] == PRODUCT
        assert sc["image_role"] == "character_ref"
        assert sc.get("face_id_ref") is None, "인물 참조가 없는 job에 얼굴 참조가 생겼다"


async def test_hero_cut_is_the_only_nonhuman_scene():
    scenes = await _split()
    assert scenes[4]["subject_type"] == "nonhuman", f"히어로컷 판정 실패: {scenes[4]}"


async def test_all_scenes_route_to_assembly():
    """인물 참조가 없어도 조립 경로다 — SUBJECT_REF로 가면 사람이 안 그려진다."""
    out = await _prompts(await _split())
    modes = [s["mode"] for s in out]
    assert modes == ["PRODUCT_ASSEMBLY"] * 5, f"라우팅: {modes}"
    # 4씬 전부 손에 쥐는 씬 → 빈 그립 손 배경 + 얼굴 기준 크기 경로
    assert [s["product_hand_held"] for s in out] == [True, True, True, True, False]


async def test_mascot_job_still_uses_subject_ref():
    """과잉 적용 방지 — 사람이 한 명도 안 나오는 제품/마스코트 job은 기존 경로 유지."""
    scenes = [{"id": 1, "text": "제품이 회전하며 로고를 보여준다.", "duration": 3,
               "mood": "calm", "matched_image": PRODUCT, "subject_type": "nonhuman",
               "image_role": "character_ref"}]
    out = await _prompts(scenes)
    assert out[0]["mode"] == "SUBJECT_REF", f"마스코트 job 라우팅이 바뀜: {out[0]['mode']}"


def test_hero_flag_drives_framing_not_face_ref():
    """히어로컷 프레이밍("no people")은 hero일 때만 붙는다."""
    assert "no people" in tools.PRODUCT_HERO_FRAMING
    assert "no people" not in tools.PRODUCT_SURFACE_FRAMING
    # 쥔 씬 T2I 배경은 빈 그립 손을 요구하되(없으면 LTX가 손과 제품을 같이 발명한다),
    # 제품 명사를 **부정문으로도** 쓰면 안 된다 — FLUX는 부정을 못 읽고 그 병을 그린다.
    t2i = tools.PRODUCT_HELD_T2I_FRAMING.lower()
    assert "cylindrical grip" in t2i and "empty" in t2i
    for banned in ("bottle", "cup", "can ", "drink"):
        assert banned not in t2i, f"T2I 그립 프레이밍에 제품 명사: {banned}"
    # Kontext 경로 프롬프트는 원본 그대로 남아 있어야 한다(튜닝된 값).
    assert "do not change their identity" in tools.PRODUCT_HELD_BG_PROMPT
    assert "as if holding a drink bottle" in tools.PRODUCT_HELD_BG_PROMPT


async def test_hero_argument_reaches_composition():
    """face_ref=None + hero=False면 히어로 비율이 아니라 그립/놓임 비율을 써야 한다."""
    seen = {}

    async def fake_compose(job_id, scene_id, work, bg, product, grip, *,
                           hand_held, hero, seed, nonce):
        seen["hero"] = hero
        return bg

    async def fake_t2i(job_id, prompt, seed=None, index=0):
        seen["bg_prompt"] = prompt
        path = tools.job_dir(job_id) / "assembly" / "fake_bg.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
        return str(path)

    with patch("tools._compose_and_recompose_product", new=fake_compose), \
         patch("tools.generate_t2i_image", new=fake_t2i), \
         patch("tools.person_mask", new=AsyncMock(side_effect=RuntimeError("no mask"))), \
         patch("tools.generate_i2v_fallback_clip", new=AsyncMock(return_value="clip.mp4")):
        await tools.generate_product_scene_clip(
            "t", 1, prompt="a woman drinks a bottle in a gym", product_ref=PRODUCT,
            face_ref=None, hero=False, hand_held=True, seed=1)
    assert seen["hero"] is False, "hero=False를 넘겼는데 히어로컷으로 합성됐다"
    assert "no people" not in seen["bg_prompt"], f"인물 씬 배경에 무인물 지시: {seen['bg_prompt']}"
    # 씬 문장의 제품 명사구는 지워진 채 배경으로 나가야 한다(안 지우면 병이 둘이 된다).
    assert "bottle" not in seen["bg_prompt"].lower(), f"제품 명사가 남음: {seen['bg_prompt']}"


async def main() -> None:
    await test_person_scenes_stay_human()
    await test_hero_cut_is_the_only_nonhuman_scene()
    await test_all_scenes_route_to_assembly()
    await test_mascot_job_still_uses_subject_ref()
    test_hero_flag_drives_framing_not_face_ref()
    await test_hero_argument_reaches_composition()
    print("test_product_only_various_people: all passed")


if __name__ == "__main__":
    asyncio.run(main())
