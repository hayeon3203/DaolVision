"""M3-7 분위기 적응형 재조명 검증.

같은 참조/화풍이라도 씬 mood에 따라 조명 텍스트가 달라지고(밝은 씬≠어두운 씬),
그 큐가 각 씬 프롬프트에 실제로 주입되며, 화풍(style_bible)은 씬 간 불변인지 확인.

    ./.venv/bin/python tests/test_scene_lighting.py
"""
import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nodes import _mood_to_lighting, _LIGHTING_SYSTEM, node_generate_prompts


def test_fallback_distinct():
    """LLM 없이도 mood 폴백만으로 어두운 씬≠밝은 씬 조명 텍스트."""
    dark = _mood_to_lighting("sad")
    bright = _mood_to_lighting("happy")
    assert dark != bright, "sad/happy 조명 텍스트가 동일"
    assert "low-key" in dark and "shadow" in dark, f"어두운 씬에 저조도/그림자 없음: {dark}"
    assert "high-key" in bright or "bright" in bright, f"밝은 씬에 고조도 없음: {bright}"
    # 미지 mood는 neutral 폴백
    assert _mood_to_lighting("bogus") == _mood_to_lighting("neutral")
    print("ok: mood 폴백 조명 큐 밝은 씬≠어두운 씬")


def _base_state():
    return {
        "script_text": "이야기",
        "style_bible": "flat 2D anime illustration, cel-shaded, teal-amber palette",
        "ref_captions": {},
        "wardrobe_locks": {},
        "scenes": [
            {"id": 1, "text": "밤에 홀로 운다", "mood": "sad"},
            {"id": 2, "text": "축제에서 웃는다", "mood": "happy"},
        ],
    }


def test_injection_and_style_invariant():
    """LLM 씬별 조명 맵이 각 씬 프롬프트에 주입되고, 화풍 문자열은 씬 간 불변."""
    lighting_json = json.dumps({
        "1": "low-key dim lighting, deep shadows, cold blue cast",
        "2": "bright high-key lighting, warm saturated highlights",
    })

    async def fake_llm(system, user):
        if system == _LIGHTING_SYSTEM:
            return lighting_json
        return "a dynamic cinematic shot"

    with patch("tools.call_llm", new=AsyncMock(side_effect=fake_llm)):
        out = asyncio.run(node_generate_prompts(_base_state()))

    s1, s2 = out["scenes"]
    assert s1["lighting"] != s2["lighting"], "씬별 조명 큐가 동일하게 뭉개짐"
    assert "low-key" in s1["prompt"] and "deep shadows" in s1["prompt"], "어두운 씬 조명 미주입"
    assert "high-key" in s2["prompt"], "밝은 씬 조명 미주입"
    # 화풍(bible)은 두 씬 프롬프트 모두에 동일하게 포함 = 불변
    bible = _base_state()["style_bible"]
    assert bible in s1["prompt"] and bible in s2["prompt"], "화풍 규칙이 씬 프롬프트에서 누락"
    print("ok: 씬별 조명 주입 + 화풍 불변")


def test_regen_skips_lighting_llm():
    """모든 씬이 이미 lighting/setting을 가지면(재생성) 조명 LLM 재호출 생략.

    node_generate_prompts의 have_ctx 체크(nodes.py)는 lighting과 setting을
    모두 요구한다 — 재조명 LLM 호출 한 번이 둘 다 채우므로, 재생성 스킵
    조건도 둘 다 이미 있을 때만 성립해야 부분 상태로 재호출을 건너뛰지 않는다.
    """
    state = _base_state()
    for s in state["scenes"]:
        s["lighting"] = "preset cue"
        s["setting"] = "preset setting"

    calls = {"lighting": 0}

    async def fake_llm(system, user):
        if system == _LIGHTING_SYSTEM:
            calls["lighting"] += 1
        return "a shot"

    with patch("tools.call_llm", new=AsyncMock(side_effect=fake_llm)):
        out = asyncio.run(node_generate_prompts(state))

    assert calls["lighting"] == 0, "재생성인데 조명 LLM 재호출됨"
    assert all("preset cue" in s["prompt"] for s in out["scenes"]), "기존 lighting 큐 유지 실패"
    print("ok: 재생성 시 조명 LLM 생략 + 기존 큐 유지")


def main():
    test_fallback_distinct()
    test_injection_and_style_invariant()
    test_regen_skips_lighting_llm()
    print("\nall M3-7 lighting tests passed")


if __name__ == "__main__":
    main()
