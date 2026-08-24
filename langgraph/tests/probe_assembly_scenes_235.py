"""조립 씬(2·3·5)만 라이브로 만들어 오늘 수정 3건을 검증한다 (2026-08-13).

E2E 전체를 돌리면 씬1·4의 LTX 2.3 22B GGUF 축출(CPU 단일스레드 10~40분 정체,
docs/spikes/2026-08-13-scene5-e2e-handoff.md)에 막혀 조립 씬까지 도달하지 못한다.
조립 경로는 13B fp8 + Kontext라 그 병목과 무관하므로, 여기서는 22B를 아예 안 태우고
`tools.generate_product_scene_clip`을 프로덕션과 동일하게 직접 호출한다.

입력은 지어내지 않는다 — 베이스라인 job 3ded2f29의 **실제 LLM 프롬프트를 그대로** 쓴다.
그래야 수정 전에 실패했던 바로 그 문자열로 검증이 된다:
  씬2: "reaching towards a water bottle", "focused on the approaching bottle"
       → 수정 전 정규식이 못 지워 배경 T2I가 무라벨 병을 그렸다(clip2 페트병 2개)
  씬3: 손동작 씬 → locate_grip clamp 경로 확인
  씬5: 히어로컷(face_ref=None) → PRODUCT_HERO_FRAMING/RATIOS 확인

실행: cd langgraph && ./.venv/bin/python -u tests/probe_assembly_scenes_235.py
산출: jobs/probe_assembly_235/assembly/scene{N}_{bg,flat,recomposed}.png, clip{N}.mp4
"""
import asyncio
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import tools  # noqa: E402

JOB_ID = "probe_assembly_235"
ROOT = Path(__file__).resolve().parent.parent
BASELINE_REFS = ROOT / "jobs" / "3ded2f29-769b-4747-ba83-9d319c7effe3" / "refs"
PRODUCT_SRC = ROOT / "jobs" / "probe_bev_ad" / "assets" / "bottle_canonical_v3.png"

SETTING = "an outdoor asphalt basketball court"
LIGHTING = ("warm golden late-afternoon backlight, bright clear exposure, "
            "soft long shadows")
# 베이스라인의 person_appearance에는 한글이 섞여 있었다("a white 반팔 (short-sleeve)
# t-shirt"). clean_llm_prompt 수정으로 이제 프로덕션에서는 안 생기므로 정리본을 쓴다.
APPEARANCE = ("Young adult East Asian man wearing a white crewneck t-shirt, "
              "wearing a white short-sleeve t-shirt")

# 베이스라인 job 3ded2f29의 씬2·씬3 프롬프트 원문(요약 없이 그대로).
SCENE2_PROMPT = (
    "A wide shot, low angle captures a young man powerfully sprinting across the "
    "empty asphalt basketball court as the warm golden late-afternoon backlight "
    "bathes him in light; he moves with determined energy, his stride long and "
    "fluid, reaching towards a water bottle resting on the bench beside him; his "
    "hands outstretched, he gestures with an open palm, anticipating the cool "
    "liquid as if drawing strength; his face is turned slightly down, focused "
    "intently on the approaching bottle, revealing a neutral expression - a quiet "
    "sense of purpose and relaxed anticipation; the camera slowly tracks his "
    "movement horizontally, following his arc through the space with smooth, "
    "natural motion"
)
SCENE3_PROMPT = (
    "A wide shot, low angle, captures the man as he stands before the weathered "
    "asphalt basketball court bathed in warm golden late-afternoon backlight; his "
    "right hand extends slowly to pick up a translucent blue plastic water bottle, "
    "and he tilts his head back with an open-mouthed, joyful expression of "
    "refreshment, savoring the icy liquid; the camera smoothly tracks forward with "
    "a gentle push-in motion following his movement"
)
# 히어로컷 — 씬분할 LLM이 마지막 문장에서 낼 법한 형태(인물 명사 없음).
SCENE5_PROMPT = (
    "A slow cinematic push-in on the product standing alone on the wooden bench at "
    "the edge of the empty asphalt basketball court in the warm golden "
    "late-afternoon backlight, the camera drifts closer and settles, condensation "
    "glistening on its surface"
)

SCENES = [
    {"id": 2, "prompt": SCENE2_PROMPT, "hand_held": False, "face": "gen_0.png",
     "seed": 1283379657, "what": "놓인 제품 — 배경에 병이 생기면 clip2 회귀"},
    {"id": 3, "prompt": SCENE3_PROMPT, "hand_held": True, "face": "gen_0.png",
     "seed": 2096494895, "what": "쥔 제품 — locate_grip clamp"},
    {"id": 5, "prompt": SCENE5_PROMPT, "hand_held": False, "face": None,
     "seed": 2134311925, "what": "히어로컷 — 인물 없이 제품 단독"},
]


async def main() -> int:
    refs = tools.refs_dir(JOB_ID)
    refs.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(PRODUCT_SRC, refs / "img_0.png")
    shutil.copyfile(BASELINE_REFS / "gen_0.png", refs / "gen_0.png")
    print(f"job={JOB_ID}  refs={refs}")

    for sc in SCENES:
        print(f"\n=== 씬{sc['id']} ({sc['what']}) seed={sc['seed']} "
              f"hand_held={sc['hand_held']} face_ref={sc['face']} ===", flush=True)
        try:
            clip = await tools.generate_product_scene_clip(
                JOB_ID, sc["id"],
                prompt=sc["prompt"],
                product_ref="img_0.png",
                face_ref=sc["face"],
                hand_held=sc["hand_held"],
                duration=3.0,
                seed=sc["seed"],
                scene_context=f"{SETTING}, {LIGHTING}",
                person_appearance=APPEARANCE if sc["face"] else "",
                force_new=True,
            )
            print(f"씬{sc['id']} 완료: {clip}", flush=True)
        except Exception as exc:
            print(f"씬{sc['id']} 실패: {type(exc).__name__}: {exc}", flush=True)

    work = tools.job_dir(JOB_ID)
    print(f"\n산출물: {work}")
    for p in sorted(work.rglob("*")):
        if p.is_file():
            print(f"  {p.relative_to(work)}  {p.stat().st_size // 1024}KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
