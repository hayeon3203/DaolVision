"""비인간 피사체(고양이 등) 씬이 image_role="start"/"ref"로 오분류돼도
character_ref로 보정되는지 검증.

회귀 방지: 캡션 OFF(기본)일 때 LLM이 이미지를 못 보고 텍스트만으로 role을
판단해 "비인간=character_ref" 지시를 무시하는 사례가 실측됨(2026-07-10, job
0bd352aa-f260-499d-8425-16a90981aa9b). 코드 가드 없인 STANDIN(얼굴 identity
전용) 파이프라인이 잘못 태워진다.

    ./.venv/bin/python test_nonhuman_role_guard.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nodes import _is_nonhuman_subject


def main():
    assert _is_nonhuman_subject("햇살이 비친 잔디밭과 그것을 뛰노는 고양이")
    assert _is_nonhuman_subject("손을 흔드는 로봇 마스코트")
    assert not _is_nonhuman_subject("한 남자가 거리를 걷는다")
    print("ok: 비인간 키워드 감지")


if __name__ == "__main__":
    main()
