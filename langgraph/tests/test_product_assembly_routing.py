"""6.23 — 제품 씬이 A노선(첫 프레임 조립)으로 라우팅되는지 회귀 테스트.

제품 참조와 인물 참조가 함께 붙은 씬을 subject_ref(Wan i2v_14b)로 보내면 참조에
**없는** 요소(인물·손·동작)를 못 그린다 — 2026-08-12 스파이크가 A노선을 만든 이유
자체다. 이 라우팅이 풀리면 UI 결과가 조용히 스파이크 이전 품질로 되돌아간다.

배경 전략 분기(product_hand_held)도 같이 검증한다. 쥐는 씬은 배경에 빈 그립 손을
미리 그려야 하고(안 그리면 LTX가 손과 제품을 같이 발명하며 라벨이 날아간다,
clip13/16 실측) 놓인 씬과 배치 비율도 다르다.

    cd langgraph && ./.venv/bin/python tests/test_product_assembly_routing.py
"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import nodes

PERSON, PRODUCT = "gen_0.png", "img_0.png"


def _prompt_state(scenes: list[dict]) -> dict:
    return {
        "job_id": "t",
        "scenes": scenes,
        "ref_images": [PERSON, PRODUCT],
        "ref_captions": {PRODUCT: "Plastic bottle with orange lid", PERSON: "Young man"},
        "style_bible": "cinematic golden hour",
        "character_sheet": "",
    }


async def _run_prompts(scenes: list[dict]) -> list[dict]:
    with patch("tools.call_llm", new=AsyncMock(return_value="a man on a court")):
        out = await nodes.node_generate_prompts(_prompt_state(scenes))
    return out["scenes"]


async def test_product_plus_face_ref_scene_becomes_assembly():
    scenes = [{
        "id": 3, "text": "벤치 앞에 멈춰 음료수를 집어 든다.", "mood": "neutral",
        "duration": 3.0, "matched_image": PRODUCT, "image_role": "character_ref",
        "subject_type": "human", "face_id_ref": PERSON, "lighting": "warm", "setting": "court",
    }]
    out = await _run_prompts(scenes)
    assert out[0]["mode"] == "PRODUCT_ASSEMBLY", f"조립 경로로 안 감: {out[0]['mode']}"
    assert out[0]["product_hand_held"] is True, "집어 든다 = 손에 쥐는 씬"
    assert out[0]["negative_prompt"], "제품 드리프트 억제 negative가 비었음"


async def test_placed_product_scene_is_not_hand_held():
    scenes = [{
        "id": 2, "text": "그는 코트 한쪽 벤치에 놓인 음료수를 향해 달려간다.", "mood": "excited",
        "duration": 3.0, "matched_image": PRODUCT, "image_role": "character_ref",
        "subject_type": "human", "face_id_ref": PERSON, "lighting": "warm", "setting": "court",
    }]
    out = await _run_prompts(scenes)
    assert out[0]["mode"] == "PRODUCT_ASSEMBLY"
    assert out[0]["product_hand_held"] is False, "놓인 제품인데 쥐는 씬으로 분류됨"


async def test_product_only_job_keeps_subject_ref():
    """인물 참조가 아예 없는 순수 제품 job은 기존 subject_ref 경로를 그대로 쓴다.
    (조립 경로는 인물+제품 광고를 위한 것이라 여기 끌어들이지 않는다.)"""
    scenes = [{
        "id": 1, "text": "제품이 회전한다.", "mood": "neutral", "duration": 3.0,
        "matched_image": PRODUCT, "image_role": "character_ref",
        "subject_type": "nonhuman", "lighting": "warm", "setting": "studio",
    }]
    state = _prompt_state(scenes)
    state["ref_images"] = [PRODUCT]
    state["ref_captions"] = {PRODUCT: "Plastic bottle with orange lid"}
    with patch("tools.call_llm", new=AsyncMock(return_value="a bottle spins")):
        out = (await nodes.node_generate_prompts(state))["scenes"]
    assert out[0]["mode"] == "SUBJECT_REF"


async def test_hero_cut_has_no_face_ref_but_still_assembles():
    """히어로컷(제품 단독)은 얼굴 참조 없이도 조립 경로를 탄다 — 제품 픽셀을
    diffusion에 통과시키지 않는 게 이 경로의 요지이기 때문."""
    scenes = [{
        "id": 4, "text": "음료수가 벤치 위에 놓여 노을빛에 빛난다.", "mood": "calm",
        "duration": 3.0, "matched_image": PRODUCT, "image_role": "character_ref",
        "subject_type": "nonhuman", "lighting": "warm", "setting": "court",
    }]
    out = await _run_prompts(scenes)   # captions에 인물 참조가 함께 있는 job
    assert out[0]["mode"] == "PRODUCT_ASSEMBLY"
    assert out[0]["product_hand_held"] is False


async def test_one_clip_dispatches_to_assembly_tool():
    scene = {
        "id": 3, "mode": "PRODUCT_ASSEMBLY", "prompt": "he lifts the bottle",
        "matched_image": PRODUCT, "face_id_ref": PERSON, "product_hand_held": True,
        "duration": 3.0, "negative_prompt": "wine bottle", "mood": "neutral",
    }
    mock = AsyncMock(return_value="/jobs/t/clip3.mp4")
    with patch("tools.generate_product_scene_clip", new=mock):
        out = await nodes.node_generate_one_clip(
            {"scene": scene, "job_id": "t", "seed": 42, "force_new": False})
    assert mock.await_count == 1
    kwargs = mock.await_args.kwargs
    assert kwargs["product_ref"] == PRODUCT
    assert kwargs["face_ref"] == PERSON
    assert kwargs["hand_held"] is True
    assert kwargs["negative_prompt"] == "wine bottle"
    assert kwargs["seed"] == 42
    assert out["clip_results"][0]["clip_path"] == "/jobs/t/clip3.mp4"


async def main() -> None:
    await test_product_plus_face_ref_scene_becomes_assembly()
    await test_placed_product_scene_is_not_hand_held()
    await test_product_only_job_keeps_subject_ref()
    await test_hero_cut_has_no_face_ref_but_still_assembles()
    await test_one_clip_dispatches_to_assembly_tool()
    print("test_product_assembly_routing: all passed")


if __name__ == "__main__":
    asyncio.run(main())
