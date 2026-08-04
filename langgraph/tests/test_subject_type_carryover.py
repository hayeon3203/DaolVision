"""한국어 주어 생략(pro-drop) 씬에서 subject_type이 이어지는지 회귀 테스트.

job 14a61492 실측: "한 여성 모델이 옥상에서 걸어온다 / 엘리베이터를 타고 내려온다 /
횡단보도에서 하늘을 본다 / 카페 앞에서 미소 짓는다" — 2~4번째 문장이 주어를 생략해
_subject_type_from_text가 None을 돌려주고 subject_type이 "none"으로 굳었다. 그러면
_scene_prompt_system(has_human_subject=False)가 "do NOT invent a person"을 걸어
주인공을 지웠고, 빈 자리를 트램·우주정거장이 채웠다. 참조 이미지가 있으면 캡션이
빈자리를 메워 가려지므로 참조 없는 job에서만 드러난다.

    cd langgraph && ./.venv/bin/python tests/test_subject_type_carryover.py
"""
import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import nodes


def _llm_scenes(scenes: list[dict]) -> str:
    return json.dumps(scenes, ensure_ascii=False)


async def _split(scenes: list[dict], script: str) -> list[dict]:
    with patch("tools.call_llm", new=AsyncMock(return_value=_llm_scenes(scenes))):
        result = await nodes.node_split_scenes({
            "script_text": script, "ref_images": [], "ref_captions": {},
        })
    return result["scenes"]


async def _run():
    # 1) 주어 생략 씬이 첫 씬의 human을 물려받는다 (핵심 회귀)
    prodrop = [
        {"text": "한 여성 모델이 도심 옥상에서 카메라를 향해 걸어온다", "duration": 3,
         "mood": "calm", "subject_type": "human"},
        {"text": "엘리베이터를 타고 내려와 로비의 유리문을 밀고 거리로 나선다", "duration": 3,
         "mood": "calm", "subject_type": "none"},
        {"text": "횡단보도에서 신호를 기다리며 고개를 들어 하늘을 본다", "duration": 3,
         "mood": "calm", "subject_type": "none"},
        {"text": "해질 무렵 골목 카페 앞에 멈춰 서서 미소 짓는다", "duration": 3,
         "mood": "happy", "subject_type": "none"},
    ]
    scenes = await _split(prodrop, "한 여성 모델의 하루.")
    types = [s["subject_type"] for s in scenes]
    assert types == ["human"] * 4, types

    # 2) 명시적 비인간 키워드는 물려받기를 이긴다 — 마스코트 씬이 human으로 새면 안 된다
    switch = [
        {"text": "한 여성 모델이 무대에 오른다", "duration": 3, "mood": "calm",
         "subject_type": "human"},
        {"text": "무대 위 마스코트 인형이 혼자 춤춘다", "duration": 3, "mood": "happy",
         "subject_type": "none"},
    ]
    # node_split_scenes는 항상 4씬으로 맞추므로(모자라면 마지막 씬 복제) 앞 2개만 본다.
    scenes = await _split(switch, "모델과 마스코트.")
    assert [s["subject_type"] for s in scenes[:2]] == ["human", "nonhuman"], scenes

    # 3) LLM이 틀린 값을 명시해도 텍스트 증거가 없으면 물려받기가 이긴다
    #    (job 74ea0e1a 실측: "횡단보도에서 신호를 기다리며…"를 nonhuman으로 오분류)
    wrong_llm = [
        {"text": "한 여성 모델이 도심 옥상에서 걸어온다", "duration": 3, "mood": "calm",
         "subject_type": "human"},
        {"text": "횡단보도에서 신호를 기다리며 고개를 들어 하늘을 본다", "duration": 3,
         "mood": "calm", "subject_type": "nonhuman"},
    ]
    scenes = await _split(wrong_llm, "한 여성 모델의 하루.")
    assert [s["subject_type"] for s in scenes[:2]] == ["human", "human"], scenes

    # 4) 앞선 씬이 전부 none이면 물려줄 게 없어 none으로 남는다(빈 상속 금지)
    empty = [
        {"text": "빗물이 유리창을 타고 흘러내린다", "duration": 3, "mood": "sad",
         "subject_type": "none"},
        {"text": "젖은 아스팔트에 네온이 번진다", "duration": 3, "mood": "sad",
         "subject_type": "none"},
    ]
    scenes = await _split(empty, "비 오는 밤.")
    assert all(s["subject_type"] == "none" for s in scenes), scenes

    print("test_subject_type_carryover PASS")


asyncio.run(_run())
