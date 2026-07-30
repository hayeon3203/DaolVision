"""씬별 seed 분리 회귀 방지.

과거엔 job_seed(job_id) 하나를 전 씬이 공유해 STANDIN_STEPS=4 같은 저스텝
조합에서 씬마다 다른 프롬프트를 줘도 모션이 수렴하는 문제 실측(2026-07-10,
job f1be24f6-aaf7-4e39-bc0c-49ac3ca64e5c). scene_seed는 씬마다 달라야 하고,
같은 (job_id, scene_id)에 대해선 재실행해도 결정적이어야 한다.

    ./.venv/bin/python tests/test_scene_seed.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nodes import scene_seed


def main():
    job_id = "test-job-abc"
    s1 = scene_seed(job_id, 1)
    s2 = scene_seed(job_id, 2)
    assert s1 != s2, "씬끼리 seed가 같음"
    assert scene_seed(job_id, 1) == s1, "같은 (job_id, scene_id)인데 seed가 안 바뀜(비결정적)"
    assert scene_seed("other-job", 1) != s1, "job_id 다른데 우연히 seed 충돌"
    print("ok: scene_seed는 씬마다 다르고 재호출해도 결정적")


if __name__ == "__main__":
    main()
