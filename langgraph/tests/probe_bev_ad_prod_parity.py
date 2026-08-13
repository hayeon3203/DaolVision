"""음료수 광고 스파이크 — 프로덕션 파이프라인 동일성 검증 (사용자 지시 2026-08-13).
스파이크가 tools.py 함수를 직접 호출한 것과, 실제 :8700이 타는 nodes.py 경로
(node_generate_ltx_batch/node_generate_one_clip)를 거친 것이 같은 결과를
내는지 확인한다. LLM이 씬을 분류·프롬프트를 새로 쓰는 전체 그래프
(node_generate_prompts/node_classify_faceid_scenes)는 일부러 건너뛴다 — 그건
"LLM이 이번에도 똑같은 프롬프트를 쓸까"라는 별개 변수라, 지금 확인하려는
"코드 배선이 스파이크와 같은 산출물을 낼 수 있는가"와 섞이면 원인 분리가 안 된다.
그래서 classify/prompt 노드가 만들어냈을 Scene dict(mode/face_id_ref/negative_prompt
등)를 직접 구성해 nodes.node_generate_ltx_batch / node_generate_one_clip에 넘긴다
— 이건 정확히 이 두 노드가 프로덕션에서 받는 입력 모양과 같다.

실행: cd langgraph && ./.venv/bin/python tests/probe_bev_ad_prod_parity.py
결과: jobs/probe_bev_ad_prod/clip1.mp4 (씬1 프로덕션 경로),
      jobs/probe_bev_ad_prod/clip3.mp4 (씬3a 프로덕션 경로)
"""
import asyncio
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import nodes  # noqa: E402
import tools  # noqa: E402

JOB_ID = "probe_bev_ad_prod"
SPIKE_ASSETS = Path(__file__).resolve().parent.parent / "jobs" / "probe_bev_ad" / "assets"
SEED = 20260813

SCENE1_PROMPT = (
    "cinematic sports commercial, a young Korean man wearing a plain white "
    "sleeveless jersey and black shorts playing basketball alone on an outdoor "
    "court in golden late-afternoon light, dribbling fast then leaping for a "
    "jump shot, sweat glistening on his face, dynamic tracking camera, "
    "shallow depth of field"
)
SCENE3A_PROMPT = (
    "cinematic, he raises the clear plastic bottle from chest height up to "
    "his lips and tilts it back to drink, the bottle stays a clear plastic "
    "PET sports drink bottle with an orange cap throughout, natural "
    "continuous motion, golden light"
)
SCENE3A_NEGATIVE = (
    "worst quality, blurry, jittery, distorted, low resolution, wine bottle, "
    "beer bottle, glass bottle, dark green glass, dark bottle, wine, alcohol, "
    "champagne, opaque bottle, different object, morphing shape"
)


async def run_scene1_via_production() -> str:
    """node_generate_ltx_batch — 실제 :8700이 LTX_FACEID 씬을 처리하는 그 노드."""
    ref_name = "prod_face.png"
    shutil.copyfile(SPIKE_ASSETS / "person_canonical.png", tools.refs_dir(JOB_ID) / ref_name)
    scene = {
        "id": 1,
        "prompt": SCENE1_PROMPT,
        "duration": 3.0,
        "mode": "LTX_FACEID",          # node_classify_faceid_scenes가 만들어냈을 값
        "face_id_ref": ref_name,       # 위와 동일 노드가 채웠을 값
        "matched_image": ref_name,
        "subject_type": "human",
        "image_role": "start",
    }
    state = {"job_id": JOB_ID, "scenes": [scene], "regen_target_ids": None}
    result = await nodes.node_generate_ltx_batch(state)
    updated = next(s for s in result["scenes"] if s["id"] == 1)
    if not updated.get("clip_path"):
        raise RuntimeError(f"씬1 프로덕션 경로 실패: {updated}")
    return updated["clip_path"]


async def run_scene3a_via_production() -> str:
    """node_generate_one_clip — 실제 :8700이 mode=I2V 씬을 처리하는 그 노드.
    negative_prompt는 이번에 nodes.py/tools.py에 새로 배선한 필드(7544555)."""
    ref_name = "prod_scene3a_first.png"
    shutil.copyfile(SPIKE_ASSETS / "scene3a_v5_first.png", tools.refs_dir(JOB_ID) / ref_name)
    scene = {
        "id": 3,
        "prompt": SCENE3A_PROMPT,
        "negative_prompt": SCENE3A_NEGATIVE,
        "matched_image": ref_name,
        "duration": 3.0,
        "mode": "I2V",                 # node_generate_prompts(956행)가 만들어냈을 값
    }
    payload = {"scene": scene, "job_id": JOB_ID, "seed": SEED, "force_new": True}
    result = await nodes.node_generate_one_clip(payload)
    clip_path = result["clip_results"][0]["clip_path"]
    if not clip_path:
        raise RuntimeError(f"씬3a 프로덕션 경로 실패: {result}")
    return clip_path


async def main() -> int:
    print("[1/2] 씬1(LTX_FACEID) 프로덕션 경로로 생성 중...")
    clip1 = await run_scene1_via_production()
    print(f"  -> {clip1}")

    print("[2/2] 씬3a(I2V + negative_prompt) 프로덕션 경로로 생성 중...")
    clip3 = await run_scene3a_via_production()
    print(f"  -> {clip3}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
