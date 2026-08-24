"""음료수 광고 스파이크 씬2 v13 — 사용자 피드백 2건 반영(2026-08-13):

1) 트림 지점에서 액션이 뚝 끊김 → 병을 짚으려는 동작으로 마무리
2) 달리는 걸음이 살짝 주춤함

첫 프레임은 확정본을 그대로 재사용한다(`refs/scene2_final_r10s4.png`,
= assets/scene2_final_r10s4_recomposed.png와 md5 동일). 배경 T2I·제품 합성·
Kontext 재통합은 이미 승인된 픽셀이라 다시 돌릴 이유가 없다 — 이번에 바꾸는 건
I2V 프롬프트 꼬리 하나뿐이다.

**시드는 20260813 고정**. v9가 "벤치 앞에서 멈춰선다" 프롬프트로 실패했을 때는
시드까지 같이 바꿨던 조합이라(identity 드리프트 + 쭈그려앉는 자세), 시드 고정 +
프롬프트만 변경은 아직 안 해본 조합이다.

실행: cd langgraph && ./.venv/bin/python tests/probe_bev_ad_scene2_v13.py
결과: jobs/probe_bev_ad/clip12.mp4 (clip2.mp4 덮어쓰지 않도록 scene_id=12)
      트림 지점은 생성 후 프레임 확인하고 결정 — 이 스크립트는 풀클립만 만든다.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import tools  # noqa: E402

JOB_ID = "probe_bev_ad"
REF_NAME = "scene2_final_r10s4.png"   # 확정 첫 프레임(재생성 금지, 픽셀 재사용)
I2V_SEED = 20260813                   # 확정본과 동일 — 바꾸면 identity 드리프트(v9 실측)
SCENE_ID = 12                         # clip2.mp4 보존용(생성 파일은 clip12.mp4)

# 확정본 프롬프트 + 마지막 절만 추가(감속 → 병으로 손 뻗음).
I2V_PROMPT = (
    "cinematic, the man runs from far in the distance straight toward the "
    "camera, growing larger and closer with each stride, camera stays low and "
    "steady near the bench where a clear plastic sports drink bottle stands, "
    "he slows to a stop beside the bench and reaches his hand down toward the "
    "bottle, golden late-afternoon light"
)


async def main() -> int:
    clip = await tools.generate_i2v_fallback_clip(
        job_id=JOB_ID, scene_id=SCENE_ID, prompt=I2V_PROMPT,
        matched_image=REF_NAME, duration=3.0, seed=I2V_SEED, force_new=True,
    )
    print(f"scene 2 (v13, 풀클립) -> {clip}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
