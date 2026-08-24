"""이미 만들어둔 씬별 인물 정본으로 조립 경로만 이어서 돌린다 (2026-08-14).

job ca755c9b가 인물 정본 4장(person_1~4.png)까지 만들고 멈췄다. 남은 미검증 구간은
**Kontext가 그 정본을 "빈 원통형 그립 손" 자세로 재렌더하는가** 하나뿐이다. 씬 분할·
프롬프트 생성·정본 생성을 다시 돌리면 20분 넘게 걸리므로 여기서는 전부 건너뛰고
`tools.generate_product_scene_clip`을 프로덕션과 동일하게 직접 호출한다.

T2I로 배경을 처음부터 그린 경로는 두 번 실패했다:
  - 씬 문장을 주입 → 빈 손에 우유잔 (job 8820932b)
  - 문장을 빼도 손이 활짝 펴짐 + 그립 검출 clamped → 병이 어깨 (job 872beeee)
정본이 있으면 Kontext가 그 사람을 **다시 포즈시키는** 경로로 가고, 그건 베이스라인
job 3ded2f29에서 검증된 유일한 조합이다.

실행:
  cd langgraph && ./.venv/bin/python -u tests/probe_person_ref_assembly.py        # 씬1만
  cd langgraph && ./.venv/bin/python -u tests/probe_person_ref_assembly.py all    # 5씬 전부
산출: jobs/probe_person_ref/assembly/scene{N}_{bg,flat,recomposed}.png, clip{N}.mp4
"""
import asyncio
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import nodes  # noqa: E402
import tools  # noqa: E402

JOB_ID = "probe_person_ref"
ROOT = Path(__file__).resolve().parent.parent
# 인물 정본이 남아 있는 job. 시드가 고정이라 다시 뽑아도 같은 사람이 나온다.
SRC_REFS = ROOT / "jobs" / "ca755c9b-5865-4f81-a2c5-083eed9004f8" / "refs"

LIGHTING = "soft warm key light, bright clear exposure, gentle natural shadows"

# 씬 프롬프트·인물 외형·장소는 job ca755c9b의 LLM 산출물을 그대로 쓴다(지어내지 않는다).
# person은 _make_scene_context가 뽑은 값, prompt는 씬 문장을 영어 촬영 지시로 옮긴 것.
SCENES = [
    {"id": 1, "face": "person_1.png", "hand_held": True, "hero": False,
     "setting": "an indoor gymnasium with mirrored walls and fitness equipment",
     "person": "a woman in her 20s who has just finished a workout",
     "prompt": ("A cinematic medium-close commercial shot of a woman in her 20s who has "
                "just finished working out in an indoor gymnasium. She raises the drink "
                "to her lips and takes a refreshing sip, her expression relaxed and "
                "satisfied. The camera holds steady on her")},
    {"id": 2, "face": "person_2.png", "hand_held": True, "hero": False,
     "setting": "an open-plan office at a desk with documents and a laptop",
     "person": "a man in his 30s, an office worker",
     "prompt": ("A cinematic medium-close commercial shot of a man in his 30s at his "
                "office desk. He lifts the drink and takes a single sip, then lowers it "
                "slightly, looking calm and refreshed. The camera holds steady on him")},
    {"id": 3, "face": "person_3.png", "hand_held": True, "hero": False,
     "setting": "a quiet university library with tall bookshelves",
     "person": "a man in his 20s wearing glasses, a university student",
     "prompt": ("A cinematic medium-close commercial shot of a man in his 20s studying in "
                "a quiet library. He raises the drink and sips slowly, his shoulders "
                "easing. The camera holds steady on him")},
    {"id": 4, "face": "person_4.png", "hand_held": True, "hero": False,
     "setting": "an outdoor construction site with scaffolding",
     "person": "a man in his 40s wearing a yellow hard hat, a construction worker",
     "prompt": ("A cinematic medium-close commercial shot of a man in his 40s at a "
                "construction site. He tilts the drink up and takes a long, hearty gulp, "
                "his expression relieved. The camera holds steady on him")},
    # 히어로컷 — 인물 없음. face=None이라 T2I + PRODUCT_HERO_FRAMING 경로.
    {"id": 5, "face": None, "hand_held": False, "hero": True,
     "setting": "an empty cafe table by a window",
     "person": "",
     "prompt": ("A cinematic product commercial shot: the camera pushes in slowly toward "
                "the empty cafe table by a window and comes to rest")},
]


async def run_scene(sc: dict) -> str:
    print(f"\n=== 씬{sc['id']} face={sc['face']} hand_held={sc['hand_held']} "
          f"hero={sc['hero']}", flush=True)
    clip = await tools.generate_product_scene_clip(
        JOB_ID, sc["id"],
        prompt=sc["prompt"],
        product_ref="img_0.png",
        face_ref=sc["face"],
        hero=sc["hero"],
        hand_held=sc["hand_held"],
        duration=3.0,
        # 프로덕션과 같은 씬별 시드(nodes.scene_seed, base 20260813)
        seed=[1931120819, 1283379657, 2096494895, 1098672158, 1559181043][sc["id"] - 1],
        scene_context=f"{sc['setting']}, {LIGHTING}",
        person_appearance=sc["person"],
        force_new=True,
    )
    work = tools.job_dir(JOB_ID) / "assembly"
    print(f"씬{sc['id']} 완료: {clip}", flush=True)
    for name in (f"scene{sc['id']}_bg.png", f"scene{sc['id']}_recomposed.png"):
        if (work / name).exists():
            print(f"  {work / name}", flush=True)
    return clip


async def main(which: str) -> int:
    refs = tools.refs_dir(JOB_ID)
    refs.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / "jobs" / "probe_bev_ad" / "assets" / "bottle_canonical_v3.png",
                    refs / "img_0.png")

    targets = SCENES if which == "all" else SCENES[:1]
    # 인물 정본은 프로덕션과 **같은 프롬프트**(nodes.PERSON_REF_PORTRAIT_PROMPT)로 뽑는다.
    # 이미 있으면 재사용 — 의상 지시를 바꿔 다시 보려면 해당 파일을 지우고 실행한다.
    for sc in targets:
        if not sc["face"]:
            continue
        dest = refs / sc["face"]
        if dest.exists():
            print(f"[정본] 씬{sc['id']} {sc['face']} 재사용", flush=True)
            continue
        query = nodes.PERSON_REF_PORTRAIT_PROMPT.format(description=sc["person"])
        print(f"[정본] 씬{sc['id']} 생성: {sc['person']}", flush=True)
        path = await tools.generate_t2i_image(
            JOB_ID, query, seed=nodes.scene_seed(JOB_ID, sc["id"]), index=2000 + sc["id"])
        shutil.copyfile(path, dest)
        print(f"[정본] 씬{sc['id']} -> {dest}", flush=True)

    for sc in targets:
        await run_scene(sc)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "one")))
