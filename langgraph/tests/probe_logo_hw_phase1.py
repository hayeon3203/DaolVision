"""로고+GB10 합성 이미지로 4씬 subject_ref 클립을 씬분할/승인게이트 없이 직접
생성 — 파이프라인 배선 문제와 모델 자체의 로고 유지 능력을 분리해서 본다.

실행: cd langgraph && ./.venv/bin/python tests/probe_logo_hw_phase1.py
결과: langgraph/jobs/probe_logo_hw/clip1.mp4 ~ clip4.mp4
"""
import asyncio
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import tools  # noqa: E402
from nodes import node_generate_prompts, scene_seed  # noqa: E402

JOB_ID = "probe_logo_hw"
SRC_IMAGE = (
    Path(__file__).resolve().parent.parent
    / "jobs" / "probe_logo_hw" / "assets" / "ref_composite.png"
)

SCENES_TEXT = [
    ("시네마틱한 아침 햇살 아래, 사람이 출근 준비를 하는 동안 책상 위 DaolFusion "
     "GB10 워크스테이션이 이미 조용히 켜져 데이터를 정리하고 있다.", "calm"),
    ("낮, 사무실에서 사람은 회의와 창작에 몰입하고 워크스테이션은 화면에 진행률을 "
     "띄운 채 반복 작업을 대신 처리한다.", "neutral"),
    ("저녁, 사람이 가족과 식탁에 둘러앉아 웃는 동안 워크스테이션은 거실 한쪽에서 "
     "여전히 조용히 켜져 있다.", "happy"),
    ("밤, 다들 잠든 집 안에서 워크스테이션의 로고만 은은히 빛나며 여전히 "
     "작동하고 있다.", "calm"),
]


async def main() -> int:
    ref_name = "img_0.png"
    shutil.copyfile(SRC_IMAGE, str(tools.refs_dir(JOB_ID) / ref_name))

    scenes = [
        {
            "id": i + 1,
            "text": text,
            "duration": 3.0,
            "mood": mood,
            "matched_image": ref_name,
            "image_role": "character_ref",   # 강제 SUBJECT_REF — Task 6.17 단일참조 경로와 동일
            "quality_flag": "pending",
            "approved": False,
        }
        for i, (text, mood) in enumerate(SCENES_TEXT)
    ]
    state = {
        "job_id": JOB_ID,
        "script_text": " ".join(t for t, _ in SCENES_TEXT),
        "ref_captions": {},
        "wardrobe_locks": {},
        "image_query": "",
        "scenes": scenes,
    }

    print("[1/2] style_bible + 씬 프롬프트 생성 중 (cinematic)…")
    state.update(await node_generate_prompts(state))

    for scene in state["scenes"]:
        assert scene["mode"] == "SUBJECT_REF", f"scene {scene['id']}: mode={scene['mode']}"
        print(f"scene {scene['id']} prompt: {scene['prompt']}")

    print("[2/2] SUBJECT_REF 클립 4개 생성 중 (ComfyUI :8188)…")
    for scene in state["scenes"]:
        clip_path = await tools.generate_subject_ref_clip(
            job_id=JOB_ID, scene_id=scene["id"], prompt=scene["prompt"],
            ref_image=ref_name, duration=scene["duration"],
            seed=scene_seed(JOB_ID, scene["id"]), force_new=True,
        )
        print(f"  scene {scene['id']} -> {clip_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
