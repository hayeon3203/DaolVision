"""style_prefix()가 6개 프리셋(cinematic/anime/cyberpunk/lowpoly/claymation/watercolor)을
정확한 문자열로 매핑하고, 미선택/미지원 키는 빈 문자열(기존 LLM 자동 style_bible 경로
유지)로 떨어지는지 검증. 또한 _make_style_bible이 selected_style이 있으면 LLM 호출 없이
그 프리픽스를 즉시 style_bible로 쓰는지 확인(Task 4.5, docs/PRD.md R7).

    ./.venv/bin/python tests/test_style_prefix.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # langgraph/ 모듈 import용

import nodes
import tools
from style_presets import STYLE_PREFIXES, style_prefix


def test_six_presets_map_exact_prefix():
    assert set(STYLE_PREFIXES) == {
        "cinematic", "anime", "cyberpunk", "lowpoly", "claymation", "watercolor",
    }, f"6개 테마여야 함: {set(STYLE_PREFIXES)}"
    for key, expected in STYLE_PREFIXES.items():
        assert style_prefix(key) == expected, f"{key}: 매핑 불일치"
    print("ok: 6개 테마 프리픽스 매핑 정확")


def test_unselected_and_unknown_fall_back_to_empty():
    assert style_prefix(None) == ""
    assert style_prefix("") == ""
    assert style_prefix("does-not-exist") == ""
    print("ok: 미선택/미지원 키 → 빈 문자열(LLM 자동 style_bible 경로 유지)")


def test_style_bible_skips_llm_when_style_selected():
    called = {"n": 0}

    async def fake_call_llm(system_prompt, user_prompt):
        called["n"] += 1
        return "should not be used"

    tools.call_llm = fake_call_llm
    state = {
        "job_id": "t", "script_text": "s", "scenes": [{"id": 1, "text": "x"}],
        "selected_style": "cyberpunk",
    }
    bible = asyncio.run(nodes._make_style_bible(state))
    assert bible == STYLE_PREFIXES["cyberpunk"], f"선택된 프리셋이 그대로 style_bible이어야 함: {bible!r}"
    assert called["n"] == 0, "프리셋 선택 시 LLM(call_llm)을 부르면 안 됨"
    print("ok: selected_style 있으면 LLM 우회, 프리픽스가 곧 style_bible")


def main():
    test_six_presets_map_exact_prefix()
    test_unselected_and_unknown_fall_back_to_empty()
    test_style_bible_skips_llm_when_style_selected()


if __name__ == "__main__":
    main()
