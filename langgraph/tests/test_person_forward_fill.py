"""인물 등장 판정 forward-fill 회귀 테스트.

2026-08-13 job 24df6fce 실측: "다시 농구 코트로 돌아가 공을 잡고 힘차게 달려나간다."가
제품 단독 히어로컷으로 처리됐다(face_id_ref=None, subject_type=nonhuman). 한국어가
주어를 생략해 사람 명사가 없고, "잡고"·"돌아가"는 손동작 어휘 목록에도 없기 때문.
공을 잡는 주체가 없는 씬이 될 수 없으므로 명백한 오판이다.

동사 목록을 늘리는 건 한국어에서 끝이 없어서, setting·제품 등장에 이미 쓰는
forward-fill을 인물 판정에도 적용했다. 단 진짜 히어로컷(제품이 문장의 주인공)은
상속을 끊어야 한다.

    cd langgraph && ./.venv/bin/python tests/test_person_forward_fill.py
"""
import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import nodes

PERSON, PRODUCT = "gen_0.png", "img_0.png"
CAPTIONS = {
    PERSON: "Young East Asian man wearing a white t-shirt",
    PRODUCT: "Plastic bottle with orange cap and blue-orange label",
}


async def _split(texts: list[str]) -> list[dict]:
    raw = [{"text": t, "duration": 3, "mood": "neutral", "matched_image": None,
            "subject_type": "none", "image_role": None} for t in texts]
    state = {"job_id": "t", "script_text": " ".join(texts),
             "ref_images": [PERSON, PRODUCT], "ref_captions": CAPTIONS}
    with patch("tools.call_llm", new=AsyncMock(return_value=json.dumps(raw, ensure_ascii=False))):
        return (await nodes.node_split_scenes(state))["scenes"]


async def test_subject_dropped_sentence_inherits_person():
    scenes = await _split([
        "젊은 남자가 농구 코트에서 드리블하고 있다.",
        "그는 점프슛을 쏘아 올린다.",
        "벤치 앞에서 음료수를 집어 들고 들이킨다.",
        "다시 농구 코트로 돌아가 공을 잡고 힘차게 달려나간다.",
    ])
    last = scenes[3]
    assert last["face_id_ref"] == PERSON, f"주어 생략 문장이 인물을 잃음: {last}"
    assert last["subject_type"] == "human"


async def test_real_hero_cut_breaks_inheritance():
    """제품이 문장의 주인공인 씬은 인물 씬 뒤에 와도 히어로컷으로 인정된다."""
    scenes = await _split([
        "젊은 남자가 농구 코트에서 드리블하고 있다.",
        "그는 벤치에 놓인 음료수를 향해 달려간다.",
        "노을빛을 받은 음료수 병이 벤치 위에서 반짝인다.",
        "음료수 병이 천천히 회전하며 라벨이 드러난다.",
    ])
    assert scenes[2]["face_id_ref"] is None, f"히어로컷에 인물이 상속됨: {scenes[2]}"
    assert scenes[2]["subject_type"] == "nonhuman"
    assert scenes[3]["face_id_ref"] is None


async def test_person_returns_after_hero_cut():
    """히어로컷 뒤에 다시 인물이 명시되면 인물 씬으로 복귀한다."""
    scenes = await _split([
        "젊은 남자가 농구 코트에서 드리블하고 있다.",
        "음료수 병이 벤치 위에서 반짝인다.",
        "그는 음료수를 집어 들고 들이킨다.",
        "코트로 돌아가 공을 잡는다.",
    ])
    assert scenes[1]["face_id_ref"] is None
    assert scenes[2]["face_id_ref"] == PERSON
    assert scenes[3]["face_id_ref"] == PERSON, "복귀 후 주어 생략 문장이 다시 인물을 잃음"


async def main() -> None:
    await test_subject_dropped_sentence_inherits_person()
    await test_real_hero_cut_breaks_inheritance()
    await test_person_returns_after_hero_cut()
    print("test_person_forward_fill: all passed")


if __name__ == "__main__":
    asyncio.run(main())
