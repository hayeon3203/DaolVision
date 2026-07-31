"""style_prefix()가 6개 프리셋(cinematic/anime/cyberpunk/lowpoly/claymation/watercolor)을
정확한 문자열로 매핑하고, 미선택/미지원 키는 빈 문자열로 떨어지는지 검증(Task 4.5).
I2I(S2, Kontext) 프롬프트에 주입할 순수 매핑 함수 — S1(T2I 앵커/I2V)에는 배선 안 함.

    ./.venv/bin/python tests/test_style_prefix.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # langgraph/ 모듈 import용

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


def main():
    test_six_presets_map_exact_prefix()
    test_unselected_and_unknown_fall_back_to_empty()


if __name__ == "__main__":
    main()
