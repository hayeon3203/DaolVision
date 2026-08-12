"""_subject_type_from_caption(nodes.py) 회귀 테스트.

로고+GB10 일관성 스파이크(Task 3, 2026-08-12)에서 캡션 "Dark gray NVIDIA
computing accelerator unit..."이 _NONHUMAN_HINTS에 안 걸려 human으로 오분류되던
버그를 _NONHUMAN_HINTS에 workstation/server/computer/... 어휘를 추가해 고쳤다
(nodes.py:343-349, 커밋 afed722). 이 픽스가 반대로 진짜 사람 캡션("a man at his
computer")까지 nonhuman으로 잘못 분류하는 회귀를 일으키지 않는지 고정한다.

    ./.venv/bin/python tests/test_subject_caption_classification.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nodes import _subject_type_from_caption  # noqa: E402


def main():
    # 이번에 고친 케이스: 컴퓨팅 하드웨어 캡션은 nonhuman으로 잡혀야 한다.
    assert _subject_type_from_caption(
        "Dark gray NVIDIA computing accelerator unit on a black background"
    ) == "nonhuman"
    assert _subject_type_from_caption(
        "NVIDIA computing module with a blue tree logo"
    ) == "nonhuman"

    # 회귀 가드: 사람 캡션은 여전히 human이어야 한다(리뷰 Important 1 우려 지점).
    assert _subject_type_from_caption("a man sitting at his computer") == "human"
    assert _subject_type_from_caption("a person standing near a server rack") == "human"

    print("ok: 하드웨어 캡션 nonhuman + 사람 캡션 human 회귀 없음")


if __name__ == "__main__":
    main()
