"""M2 T2I 앵커(generate_t2i_image) 해상도 회귀 테스트.

전에는 WIDTH/HEIGHT(영상 프리셋, 1280x704 — LTX/Wan 32배수 제약용)를 그대로 재사용해
승인 후 ref_images로 첨부되는 기본 생성 이미지가 16:9가 아니었다. T2I_WIDTH/HEIGHT는
그 프리셋과 분리된 전용 상수라 값이 바뀌어도 서로 영향을 주면 안 된다.

    cd langgraph && ./.venv/bin/python tests/test_t2i_resolution.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tools


def test_t2i_resolution_is_16_9():
    assert tools.T2I_WIDTH * 9 == tools.T2I_HEIGHT * 16


def test_t2i_resolution_decoupled_from_video_preset():
    assert (tools.T2I_WIDTH, tools.T2I_HEIGHT) != (tools.WIDTH, tools.HEIGHT)


if __name__ == "__main__":
    test_t2i_resolution_is_16_9()
    test_t2i_resolution_decoupled_from_video_preset()
    print("test_t2i_resolution: all passed")
