"""Task 5.1: Nemotron 기본 배선과 한국어 4씬 분할 계약 회귀 테스트."""
import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import nodes
import tools


NEMOTRON_MODEL = "hf.co/nvidia/NVIDIA-Nemotron-3-Nano-4B-GGUF:Q4_K_M"


async def _run():
    llm_result = """[
      {"text":"우주비행사가 발사대로 향한다","duration":2,"mood":"tense","subject_type":"human"},
      {"text":"우주비행사가 우주를 유영한다","duration":3,"mood":"calm","subject_type":"human"},
      {"text":"우주비행사가 외계행성에 착륙한다","duration":3,"mood":"surprised","subject_type":"human"},
      {"text":"우주비행사가 지구로 귀환한다","duration":2,"mood":"happy","subject_type":"human"}
    ]"""
    with patch("tools.call_llm", new=AsyncMock(return_value=llm_result)) as call:
        result = await nodes.node_split_scenes({
            "script_text": (
                "우주비행사가 발사대를 떠나 우주를 유영하고 외계행성에 착륙한 뒤 "
                "무사히 지구로 귀환한다."
            ),
            "ref_images": [],
            "ref_captions": {},
        })
    system_prompt = call.await_args.args[0]
    assert "정확히 4개 씬" in system_prompt
    assert len(result["scenes"]) == 4
    assert [scene["id"] for scene in result["scenes"]] == [1, 2, 3, 4]
    assert all(any("가" <= ch <= "힣" for ch in scene["text"]) for scene in result["scenes"])

    three_scenes = json.dumps(json.loads(llm_result)[:3], ensure_ascii=False)
    retry_llm = AsyncMock(side_effect=[three_scenes, three_scenes])
    with patch("tools.call_llm", new=retry_llm):
        retried = await nodes.node_split_scenes({
            "script_text": "우주비행사가 발사하고 우주를 탐사한 뒤 지구로 귀환한다.",
            "ref_images": [],
            "ref_captions": {},
        })
    assert retry_llm.await_count == 2
    assert len(retried["scenes"]) == 4


def test_normalise_scene_count_never_splits_mid_clause():
    """진짜 근본원인: LLM이 2개만 반환해도 _normalise_scene_count가 4개로 맞추면서
    단어수 반토막으로 '우주선이 지구를'/'향해 다가간다'처럼 목적어·동사를 갈라놓던 버그."""
    two_scenes = [
        {"text": "광활한 우주 공간, 별들이 반짝이고 저 멀리 푸른 지구가 보인다.", "duration": 3},
        {"text": "우주선이 지구를 향해 천천히 다가간다.", "duration": 2},
    ]
    result = nodes._normalise_scene_count(two_scenes, target=4)
    assert len(result) == 4
    texts = [s["text"] for s in result]
    # 핵심 회귀 검증: 목적어(지구)와 동사(다가간다)가 분리된 조각이 있으면 안 됨
    assert "우주선이 지구를" not in texts, texts
    assert "향해 천천히 다가간다." not in texts, texts
    # 원본 두 문장 다 온전한 형태로(부분 문자열로) 결과 어딘가에 남아 있어야 함
    assert any("우주선이 지구를 향해 천천히 다가간다." in t for t in texts), texts
    assert any("지구가 보인다." in t for t in texts), texts


def test_split_scene_text_safely_prefers_punctuation_over_word_count():
    first, second = nodes._split_scene_text_safely("우주선이 지구를 향해 천천히 다가간다.")
    assert (first, second) == (
        "우주선이 지구를 향해 천천히 다가간다.",
        "우주선이 지구를 향해 천천히 다가간다.",
    ), (first, second)

    first, second = nodes._split_scene_text_safely("별들이 반짝이고, 지구가 보인다.")
    assert first == "별들이 반짝이고," and second == "지구가 보인다.", (first, second)


def test_scenes_look_fractured_detects_mid_sentence_cut():
    script = "우주선이 지구를 향해 천천히 다가간다."
    fractured = [
        {"text": "우주선이 지구를"},
        {"text": "향해 천천히 다가간다."},
    ]
    assert nodes._scenes_look_fractured(fractured, script)

    whole = [
        {"text": "우주선이 지구를 향해 천천히 다가간다."},
        {"text": "착륙한다."},
    ]
    assert not nodes._scenes_look_fractured(whole, script + " 착륙한다.")

    comma_split = [  # 쉼표에서 나뉜 두 독립절 — 목적어/동사 분리 아니라 프래그먼트 아님
        {"text": "별들이 반짝이고,"},
        {"text": "지구가 보인다."},
    ]
    assert not nodes._scenes_look_fractured(comma_split, "별들이 반짝이고, 지구가 보인다.")


async def _run_fracture_retry():
    fractured_scenes = json.dumps([
        {"text": "우주선이 지구를", "duration": 2, "mood": "calm", "subject_type": "nonhuman"},
        {"text": "향해 다가간다.", "duration": 2, "mood": "calm", "subject_type": "nonhuman"},
        {"text": "착륙한다.", "duration": 2, "mood": "calm", "subject_type": "nonhuman"},
        {"text": "돌아온다.", "duration": 2, "mood": "calm", "subject_type": "nonhuman"},
    ], ensure_ascii=False)
    corrected_scenes = json.dumps([
        {"text": "우주선이 지구를 향해 다가간다.", "duration": 2, "mood": "calm", "subject_type": "nonhuman"},
        {"text": "지구 궤도에 진입한다.", "duration": 2, "mood": "calm", "subject_type": "nonhuman"},
        {"text": "착륙한다.", "duration": 2, "mood": "calm", "subject_type": "nonhuman"},
        {"text": "돌아온다.", "duration": 2, "mood": "calm", "subject_type": "nonhuman"},
    ], ensure_ascii=False)
    retry_llm = AsyncMock(side_effect=[fractured_scenes, corrected_scenes])
    with patch("tools.call_llm", new=retry_llm):
        result = await nodes.node_split_scenes({
            "script_text": "우주선이 지구를 향해 다가간다. 착륙한다. 돌아온다.",
            "ref_images": [],
            "ref_captions": {},
        })
    assert retry_llm.await_count == 2, "잘림 감지 시 교정 재시도가 트리거되지 않음"
    correction_instruction = json.loads(retry_llm.await_args_list[1].args[1])["instruction"]
    assert "잘랐다" in correction_instruction
    assert result["scenes"][0]["text"] == "우주선이 지구를 향해 다가간다."


if __name__ == "__main__":
    assert tools.LLM_MODEL == NEMOTRON_MODEL, tools.LLM_MODEL
    asyncio.run(_run())
    test_normalise_scene_count_never_splits_mid_clause()
    test_split_scene_text_safely_prefers_punctuation_over_word_count()
    test_scenes_look_fractured_detects_mid_sentence_cut()
    asyncio.run(_run_fracture_retry())
    print("ok: Nemotron-4B default + Korean story split into exactly 4 scenes")
    print("ok: _normalise_scene_count no longer splits a clause mid-object/verb (root cause fix)")
    print("ok: _split_scene_text_safely prefers punctuation, duplicates when no safe cut point")
    print("ok: mid-sentence fracture detected and triggers correction retry")
