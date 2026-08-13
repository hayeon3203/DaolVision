"""_negative_prompt_for_i2v_scene(nodes.py) 회귀 테스트.

음료 광고 스파이크(2026-08-12/13)에서 병 제품을 든 채 마시는 I2V 씬이 LTX에서
와인병으로 드리프트하는 문제를 negative prompt로 억제했다. 이 값을 프로덕션
파이프라인(node_generate_prompts)이 ref 캡션을 보고 자동으로 채우도록 배선했는데
(nodes.py:977-980,999-1002), 그 판정 함수 자체를 고정한다.

    ./.venv/bin/python tests/test_i2v_bottle_negative_prompt.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tools  # noqa: E402
from nodes import _negative_prompt_for_i2v_scene  # noqa: E402


def main():
    # 병 캡션 → 와인병 드리프트 억제 negative가 채워져야 한다.
    result = _negative_prompt_for_i2v_scene(
        "A clear plastic PET bottle with a blue and orange gradient label")
    assert result is not None
    assert "wine bottle" in result
    assert tools.LTX13B_DEFAULT_NEGATIVE in result  # 화질 negative는 유지

    # 병이 아닌 캡션 → None(호출부가 tools 기본 negative로 폴백).
    assert _negative_prompt_for_i2v_scene("A young man running on a basketball court") is None
    assert _negative_prompt_for_i2v_scene("") is None

    print("ok: 병 캡션 negative 자동 채움 + 비병 캡션 None 폴백")


if __name__ == "__main__":
    main()
