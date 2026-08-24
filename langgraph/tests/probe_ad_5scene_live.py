"""음료 광고 5컷 라이브 생성 — 프로덕션 노드로 전 씬을 만든다(2026-08-13).

씬 구성(사용자 지시):
  1 농구        인물만            → LTX Face-ID
  2 달리기      제품 놓임          → 조립(hand_held=False)
  3 마시기      제품 쥠            → 조립(hand_held=True, 그립 좌표 자동 산출)
  4 코트 복귀   인물만            → LTX Face-ID
  5 히어로컷    제품 단독          → 조립(hand_held=False, 얼굴 참조 없음)

LLM 씬분할/프롬프트 노드는 건너뛰고 그 노드들이 만들어냈을 Scene dict를 직접 넣는다
(probe_bev_ad_prod_parity.py와 같은 방식) — 여기서 보려는 건 조립 배선과 산출물이지
LLM 프롬프트 품질이 아니다.

실행: cd langgraph && ./.venv/bin/python tests/probe_ad_5scene_live.py
결과: jobs/probe_ad_5scene/clip{1..5}.mp4, assembly/scene{2,3,5}_*.png
"""
import asyncio
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import nodes  # noqa: E402
import tools  # noqa: E402

JOB_ID = "probe_ad_5scene"
SPIKE = Path(__file__).resolve().parent.parent / "jobs" / "probe_bev_ad" / "assets"
SEED = 20260813

FACEID_SCENES = {
    1: ("cinematic sports commercial, a young Korean man wearing a plain white "
        "short-sleeve t-shirt and black shorts playing basketball alone on an outdoor "
        "court in golden late-afternoon light, dribbling fast then leaping for a jump "
        "shot, sweat glistening on his face, dynamic tracking camera, shallow depth of field"),
    4: ("cinematic sports commercial, the same young Korean man in a plain white "
        "short-sleeve t-shirt and black shorts jogs back onto the outdoor basketball "
        "court with renewed energy, picks up the ball and drives forward past the "
        "free-throw line, golden late-afternoon light, dynamic tracking camera, "
        "shallow depth of field"),
}
# 조립 경로의 배경 프롬프트는 씬 프롬프트(동작 서술)가 아니라 setting/lighting만 쓴다.
# 동작을 넣으면 Kontext가 그 동작을 그려 첫 프레임이 '동작 직전'이 아니게 된다.
SCENE_SETTING = "outdoor basketball court, wearing a plain white short-sleeve t-shirt"
SCENE_LIGHTING = "warm golden late-afternoon backlight, shallow depth of field"

ASSEMBLY_SCENES = {
    2: dict(hand_held=False, prompt=(
        "cinematic sports commercial, low ground-level shot from right beside an empty "
        "wooden bench at the edge of an outdoor basketball court, the bench top is close "
        "to the camera and empty, in the far background a young Korean man wearing a "
        "plain white short-sleeve t-shirt and black shorts is running toward the camera, "
        "golden late-afternoon light, wide-angle lens, photorealistic")),
    3: dict(hand_held=True, prompt=(
        "cinematic, he lifts the clear plastic bottle he is already holding a short "
        "distance up to his mouth and drinks, the bottle rim rests against his lower lip "
        "at chin height and stays there, only his right hand touches the bottle and his "
        "grip never changes, his head tips back only slightly, outdoor basketball court, "
        "warm golden late-afternoon backlight, natural continuous motion")),
    5: dict(hand_held=False, prompt=(
        "cinematic product hero shot, the sports drink bottle stands alone on the wooden "
        "bench at the edge of an empty outdoor basketball court, condensation beading on "
        "the plastic, warm golden late-afternoon backlight rimming the bottle, very "
        "shallow depth of field with the court far out of focus, slow subtle push-in, "
        "photorealistic")),
}


def _seed_refs() -> None:
    refs = tools.refs_dir(JOB_ID)
    shutil.copyfile(SPIKE / "bottle_canonical_v3.png", refs / "img_0.png")
    shutil.copyfile(SPIKE / "person_canonical.png", refs / "gen_0.png")


async def run_faceid(scene_id: int, prompt: str) -> str:
    scene = {"id": scene_id, "prompt": prompt, "duration": 3.0, "mode": "LTX_FACEID",
             "face_id_ref": "gen_0.png", "matched_image": "gen_0.png",
             "subject_type": "human", "image_role": "ref"}
    state = {"job_id": JOB_ID, "scenes": [scene], "regen_target_ids": None}
    result = await nodes.node_generate_ltx_batch(state)
    updated = next(s for s in result["scenes"] if s["id"] == scene_id)
    if not updated.get("clip_path"):
        raise RuntimeError(f"씬{scene_id} Face-ID 실패: {updated}")
    return updated["clip_path"]


async def run_assembly(scene_id: int, prompt: str, hand_held: bool) -> str:
    scene = {
        "id": scene_id, "prompt": prompt, "duration": 3.0, "mode": "PRODUCT_ASSEMBLY",
        "matched_image": "img_0.png",
        # 히어로컷(씬5)은 인물이 없으므로 얼굴 참조를 붙이지 않는다.
        "face_id_ref": "gen_0.png" if hand_held else None,
        "image_role": "character_ref", "subject_type": "human" if hand_held else "nonhuman",
        "product_hand_held": hand_held, "mood": "neutral",
        "negative_prompt": nodes._BOTTLE_DRIFT_NEGATIVE,
        "setting": SCENE_SETTING, "lighting": SCENE_LIGHTING,
    }
    result = await nodes.node_generate_one_clip(
        {"scene": scene, "job_id": JOB_ID, "seed": SEED, "force_new": True})
    clip = result["clip_results"][0]["clip_path"]
    if not clip:
        raise RuntimeError(f"씬{scene_id} 조립 실패: {result}")
    return clip


async def main() -> int:
    _seed_refs()
    made = {}
    # 인자로 씬 번호를 주면 그 씬만 다시 만든다(예: `... probe_ad_5scene_live.py 3 5`).
    wanted = [int(a) for a in sys.argv[1:] if a.isdigit()] or [1, 2, 3, 4, 5]
    for scene_id in wanted:
        if scene_id in FACEID_SCENES:
            print(f"[씬{scene_id}] Face-ID 생성 중...")
            made[scene_id] = await run_faceid(scene_id, FACEID_SCENES[scene_id])
        else:
            spec = ASSEMBLY_SCENES[scene_id]
            label = "쥔 제품" if spec["hand_held"] else "놓인 제품"
            print(f"[씬{scene_id}] 조립({label}) 생성 중...")
            made[scene_id] = await run_assembly(scene_id, spec["prompt"], spec["hand_held"])
        print(f"      -> {made[scene_id]}")

    print("\n=== 클립 ===")
    for scene_id, path in sorted(made.items()):
        print(f"  씬{scene_id}: {path}")
    work = tools.job_dir(JOB_ID) / "assembly"
    if work.exists():
        print("\n=== 조립 중간 산출물 ===")
        for path in sorted(work.iterdir()):
            print(f"  {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
