"""이미지 생성 요청의 역할별 규칙 분기 회귀 테스트(문제 3).

E2E job f11798c7(2026-08-13) 실측: "20대 한국인 남자, 짧은 검은 머리, 흰 반팔 티셔츠,
정면 얼굴" 요청에 범용 규칙(_IMG_QUERY_SYSTEM, 와이드샷 3중 강조)이 걸려
"standing small within the frame several meters from camera ... vast dim space"가
생성됐고 캡션은 "dark indoor corridor"였다. Face-ID 참조로는 못 쓰는 이미지다.
"흰 반팔 티셔츠"가 상반신을 암시해 "tight close-up 아님"으로 분류된 뒤,
_strip_face_emphasis_if_wide가 설계대로 "정면 얼굴" 요구까지 지운 결과다.

    cd langgraph && ./.venv/bin/python tests/test_image_query_role_rules.py
"""
import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import nodes


def test_person_request_uses_portrait_rule():
    system, strip = nodes._image_query_system(
        "20대 한국인 남자, 짧은 검은 머리, 흰 반팔 티셔츠, 정면 얼굴, 사실적인 사진")
    assert system is nodes._IMG_QUERY_PERSON_SYSTEM
    assert strip is False, "인물 규칙에서 얼굴강조 제거가 켜지면 포트레이트가 망가진다"


def test_product_request_uses_studio_rule():
    for request in ("가상 브랜드 음료수 패트병", "파란 라벨이 붙은 캔 제품 사진", "a sports drink bottle"):
        system, strip = nodes._image_query_system(request)
        assert system is nodes._IMG_QUERY_PRODUCT_SYSTEM, request
        assert strip is False


def test_nonhuman_wins_over_human_words():
    """'마스코트 캐릭터를 든 남자' 같은 혼합 요청은 제품/캐릭터 규칙이 이겨야 한다
    (_subject_type_from_text와 같은 우선순위)."""
    system, _ = nodes._image_query_system("귀여운 로봇 마스코트 캐릭터, 남자아이 느낌")
    assert system is nodes._IMG_QUERY_PRODUCT_SYSTEM


def test_ambiguous_request_keeps_generic_rule():
    system, strip = nodes._image_query_system("노을 지는 발사대, 시네마틱")
    assert system is nodes._IMG_QUERY_SYSTEM
    assert strip is True, "범용 규칙에서는 와이드샷 얼굴강조 제거가 유지돼야 한다"


async def test_person_request_keeps_face_wording_end_to_end():
    """인물 요청에서 LLM이 얼굴 문구를 냈는데 후처리가 지워버리면 안 된다."""
    llm_out = json.dumps([{"query":
        "portrait photograph of a young Korean man, short black hair, clear frontal "
        "face visible, head and shoulders, plain background, photorealistic"}])
    captured = {}

    async def fake_call_llm(system, user):
        captured["system"] = system
        return llm_out

    with patch("tools.call_llm", new=AsyncMock(side_effect=fake_call_llm)):
        out = await nodes.node_rewrite_image_query(
            {"image_request": "20대 한국인 남자, 흰 반팔 티셔츠, 정면 얼굴"})

    assert captured["system"] is nodes._IMG_QUERY_PERSON_SYSTEM
    assert "face" in out["image_query"], f"얼굴 문구가 제거됨: {out['image_query']}"


async def main() -> None:
    test_person_request_uses_portrait_rule()
    test_product_request_uses_studio_rule()
    test_nonhuman_wins_over_human_words()
    test_ambiguous_request_keeps_generic_rule()
    await test_person_request_keeps_face_wording_end_to_end()
    print("test_image_query_role_rules: all passed")


if __name__ == "__main__":
    asyncio.run(main())
