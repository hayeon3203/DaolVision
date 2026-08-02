"""_strip_echoed_bible 회귀 테스트.

job 78cb492c에서 씬 프롬프트 LLM이 system 프롬프트의 지시를 무시하고 user
프롬프트의 "Global style: {bible}" 컨텍스트를 그대로 베껴 최종 프롬프트에
스타일 문구가 중복 삽입되는 버그 실측. 이 가드가 사라지면 프롬프트 절반이
다시 중복 boilerplate로 채워져 씬 고유 지시가 희석/트렁케이션당한다.

    cd langgraph && ./.venv/bin/python tests/test_strip_echoed_bible.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import nodes

BIBLE = ("photorealistic, cinematic live-action, face ID identity locked, natural lighting only, "
         "high detail texture density, realistic surface materials, unprocessed line and edge "
         "treatment, organic shape language, consistent prop design minimalism, shallow depth of "
         "field focus on subject, 35mm lens character, no stylized rendering")


def test_strips_global_style_marker():
    raw = ("establishing wide shot low angle view of the astronaut walking across the launch pad"
           f"\nGlobal style: {BIBLE}")
    out = nodes._strip_echoed_bible(raw, BIBLE)
    assert "Global style" not in out
    assert "photorealistic" not in out.lower()
    assert out == "establishing wide shot low angle view of the astronaut walking across the launch pad"


def test_strips_inline_bible_without_marker():
    raw = f"extreme wide low angle shot mid-launch, {BIBLE}."
    out = nodes._strip_echoed_bible(raw, BIBLE)
    assert BIBLE not in out
    assert out == "extreme wide low angle shot mid-launch"


def test_leaves_clean_prompt_untouched():
    raw = "close-up low angle shot, ecstatic expression, camera dolly zoom outward"
    out = nodes._strip_echoed_bible(raw, BIBLE)
    assert out == raw


if __name__ == "__main__":
    test_strips_global_style_marker()
    test_strips_inline_bible_without_marker()
    test_leaves_clean_prompt_untouched()
    print("test_strip_echoed_bible: all passed")
