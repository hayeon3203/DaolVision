"""_scene_prompt_system(has_human_subject=...) 회귀 테스트.

job 4265fba0에서 사람 없는 도시 씬(subject_type=nonhuman)인데도 시스템 프롬프트가
무조건 "character's pose/facial expression"을 요구해 LLM이 매번 "a lone figure",
"a figure hunched over" 같은 임의의 사람을 만들어낸 버그 실측. has_human_subject=False면
인물 묘사 지시가 빠지고 "사람을 지어내지 마라"로 뒤집혀야 한다.

    cd langgraph && ./.venv/bin/python tests/test_scene_prompt_subject.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import nodes


def test_human_subject_keeps_pose_and_expression_instructions():
    p = nodes._scene_prompt_system(standin=False, has_wardrobe=False, has_human_subject=True)
    assert "FACIAL" in p
    assert "do NOT invent a person" not in p


def test_nonhuman_subject_forbids_inventing_people():
    p = nodes._scene_prompt_system(standin=False, has_wardrobe=False, has_human_subject=False)
    assert "do NOT invent a person" in p
    assert "FACIAL EXPRESSION and emotional state matching the mood" not in p


def test_standin_always_keeps_face_identity_block_regardless_of_flag():
    p = nodes._scene_prompt_system(standin=True, has_wardrobe=False, has_human_subject=True)
    assert "the character's face and identity come from a separate reference" in p


if __name__ == "__main__":
    test_human_subject_keeps_pose_and_expression_instructions()
    test_nonhuman_subject_forbids_inventing_people()
    test_standin_always_keeps_face_identity_block_regardless_of_flag()
    print("test_scene_prompt_subject: all passed")
