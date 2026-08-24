"""6.23 라이브 검증 — 조립 노드가 노드별로 어떤 산출을 내는지 실제로 만들어 본다.

프로덕션 경로(nodes.node_generate_one_clip → tools.generate_product_scene_clip)를
그대로 호출한다. LLM 씬분할/프롬프트 노드는 건너뛴다 — 그 노드들이 만들어냈을
Scene dict를 직접 구성해 넣는다(probe_bev_ad_prod_parity.py와 같은 방식). 여기서
보려는 건 "조립 배선이 단계별로 정상 산출을 내는가"이고, LLM 프롬프트 품질은
별개 변수다.

씬 2종을 만든다:
  - 놓인 제품(hand_held=False): T2I 배경 → 합성 → 재통합 → I2V
  - 쥔 제품(hand_held=True):   Kontext 그립 손 배경 → 합성(occlusion) → 재통합 → I2V

중간 산출물은 전부 jobs/<JOB_ID>/assembly/ 에 남는다:
  scene{N}_bg.png / scene{N}_flat.png / scene{N}_recomposed.png / clip{N}.mp4

실행: cd langgraph && ./.venv/bin/python tests/probe_product_assembly_live.py
"""
import asyncio
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import nodes  # noqa: E402
import tools  # noqa: E402

JOB_ID = "probe_product_assembly"
SPIKE = Path(__file__).resolve().parent.parent / "jobs" / "probe_bev_ad" / "assets"
SEED = 20260813

PLACED_PROMPT = (
    "cinematic sports commercial, low ground-level shot from right beside an empty "
    "wooden bench at the edge of an outdoor basketball court, the bench top is close "
    "to the camera and empty, in the far background a young Korean man wearing a plain "
    "white short-sleeve t-shirt and black shorts is running toward the camera, facing "
    "the camera, small distant figure far away on the court, deep perspective, golden "
    "late-afternoon light, wide-angle lens, photorealistic"
)
HELD_PROMPT = (
    "cinematic, he lifts the clear plastic bottle he is already holding a short "
    "distance up to his mouth and drinks, the bottle rim rests against his lower lip "
    "at chin height and stays there, only his right hand touches the bottle and his "
    "grip never changes, his head tips back only slightly, natural continuous motion, "
    "golden light"
)


def _seed_refs() -> None:
    refs = tools.refs_dir(JOB_ID)
    shutil.copyfile(SPIKE / "bottle_canonical_v3.png", refs / "img_0.png")
    shutil.copyfile(SPIKE / "person_canonical.png", refs / "gen_0.png")


def _scene(scene_id: int, prompt: str, hand_held: bool) -> dict:
    return {
        "id": scene_id,
        "prompt": prompt,
        "duration": 3.0,
        "mode": "PRODUCT_ASSEMBLY",
        "matched_image": "img_0.png",
        "face_id_ref": "gen_0.png",
        "image_role": "character_ref",
        "subject_type": "human",
        "product_hand_held": hand_held,
        "negative_prompt": nodes._BOTTLE_DRIFT_NEGATIVE,
        "mood": "neutral",
    }


async def run(scene: dict) -> str:
    result = await nodes.node_generate_one_clip(
        {"scene": scene, "job_id": JOB_ID, "seed": SEED, "force_new": True})
    clip = result["clip_results"][0]["clip_path"]
    if not clip:
        raise RuntimeError(f"씬{scene['id']} 조립 실패: {result}")
    return clip


async def main() -> int:
    _seed_refs()
    work = tools.job_dir(JOB_ID) / "assembly"
    print(f"중간 산출물 디렉토리: {work}\n")

    print("[1/2] 놓인 제품 씬(hand_held=False) — T2I 배경 경로")
    clip2 = await run(_scene(2, PLACED_PROMPT, hand_held=False))
    print(f"  -> {clip2}")

    print("\n[2/2] 쥔 제품 씬(hand_held=True) — Kontext 그립 손 배경 경로")
    clip3 = await run(_scene(3, HELD_PROMPT, hand_held=True))
    print(f"  -> {clip3}")

    print("\n=== 단계별 산출물 ===")
    for path in sorted(work.iterdir()):
        print(f"  {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
