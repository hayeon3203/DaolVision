"""no-ref 모드 캐릭터 시트 회귀 테스트.

job 1a0b199d 실측: 참조 이미지 없는 job에서 1씬 "a woman model"이 4씬에선 "beside
him"으로 성별까지 바뀌었다. 참조가 없으면 identity를 쥔 게 아무것도 없어서다
(style_bible은 화풍만 담고, 원래 "Do not standardize character identity"라고 명시).
참조가 없고 사람이 등장할 때만 시트를 뽑아 인물 씬 프롬프트에 주입한다.

    cd langgraph && ./.venv/bin/python tests/test_character_sheet_noref.py
"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import nodes

TWO_LINE = (
    "STYLE: photorealistic cinematic live-action, desaturated teal-orange grade\n"
    "CHARACTER: a woman in her late twenties, slim build, shoulder-length black hair, "
    "light-warm skin, a small mole under her left eye, wearing a long charcoal wool coat"
)


def test_split_parses_two_line_response():
    bible, sheet = nodes._split_style_and_character(TWO_LINE)
    assert bible.startswith("photorealistic cinematic"), bible
    assert "CHARACTER" not in bible and "STYLE" not in bible, bible
    assert "shoulder-length black hair" in sheet, sheet


def test_split_falls_back_when_llm_ignores_labels():
    raw = "anime illustration style, cel-shaded"
    bible, sheet = nodes._split_style_and_character(raw)
    assert bible == raw          # 전체를 bible로
    assert sheet == ""           # 시트는 포기 → 호출부가 주입을 건너뛴다


def test_split_treats_none_as_no_character():
    bible, sheet = nodes._split_style_and_character(
        "STYLE: photoreal documentary\nCHARACTER: none")
    assert bible == "photoreal documentary"
    assert sheet == ""


async def _prompts_for(scenes: list[dict], ref_images: list[str]) -> list[str]:
    async def fake_llm(system_prompt, user_prompt):
        # style bible 호출은 2줄로, 씬 프롬프트 호출은 평범한 문장으로 답한다.
        if "art director" in system_prompt:
            return TWO_LINE
        if "cinematographer" in system_prompt:
            return "{}"          # _make_scene_context — 폴백 경로 사용
        return "a shot of the scene"

    with patch("tools.call_llm", new=AsyncMock(side_effect=fake_llm)):
        result = await nodes.node_generate_prompts({
            "script_text": "한 여성 모델의 하루.",
            "scenes": scenes, "ref_images": ref_images, "ref_captions": {},
        })
    return [s["prompt"] for s in result["scenes"]], result


async def _run():
    test_split_parses_two_line_response()
    test_split_falls_back_when_llm_ignores_labels()
    test_split_treats_none_as_no_character()

    human = {"id": 1, "text": "여성 모델이 걸어온다", "duration": 3.0, "mood": "calm",
             "subject_type": "human", "matched_image": None, "image_role": None}
    empty = {"id": 2, "text": "빗물이 유리창을 타고 흘러내린다", "duration": 3.0,
             "mood": "sad", "subject_type": "none", "matched_image": None,
             "image_role": None}

    # 1) 참조 없음 + 인물 씬 → 시트 주입, 무인물 씬 → 주입 안 함
    #    (무인물 씬엔 _scene_prompt_system이 "사람을 만들지 마라"를 걸어 충돌한다)
    prompts, result = await _prompts_for([human, empty], ref_images=[])
    assert "The main character:" in prompts[0], prompts[0]
    assert "shoulder-length black hair" in prompts[0], prompts[0]
    assert "The main character:" not in prompts[1], prompts[1]
    assert result["character_sheet"], result["character_sheet"]

    # 2) 참조 있음 → 시트를 아예 뽑지 않는다(Stand-In/Face-ID latent가 identity 담당)
    prompts, result = await _prompts_for(
        [{**human, "matched_image": "img_0.png", "image_role": "ref"}],
        ref_images=["img_0.png"])
    assert not result.get("character_sheet"), result.get("character_sheet")

    print("test_character_sheet_noref PASS")


asyncio.run(_run())
