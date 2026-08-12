"""씬별 재구성 참조 이미지(ref_scene1_dell.png / ref_scene3_dell.png)로 subject_ref
I2V까지 돌려서 구도 자유도가 영상까지 이어지는지 확인. Task 2 Phase 1 패턴처럼
씬분할/매칭 없이 씬마다 다른 참조 이미지를 직접 지정 — 씬 텍스트는 원 시나리오의
1번/3번 그대로 쓴다.

실행: cd langgraph && ./.venv/bin/python tests/probe_logo_hw_recompose_i2v.py
결과: jobs/probe_logo_hw_recompose/clip1.mp4, clip3.mp4
"""
import asyncio
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import tools  # noqa: E402
from nodes import node_generate_prompts, scene_seed  # noqa: E402

JOB_ID = "probe_logo_hw_recompose_s45"
ASSETS = Path(__file__).resolve().parent.parent / "jobs" / "probe_logo_hw" / "assets"

SCENES = [
    {
        "id": 1,
        "src": ASSETS / "ref_scene1_dell_s45.png",
        "ref_name": "img_scene1.png",
        "text": ("시네마틱한 아침 햇살 아래, 사람이 출근 준비를 하는 동안 책상 위 "
                  "워크스테이션이 이미 조용히 켜져 데이터를 정리하고 있다."),
        "mood": "calm",
    },
    {
        "id": 3,
        "src": ASSETS / "ref_scene3_dell_s45.png",
        "ref_name": "img_scene3.png",
        "text": ("저녁, 사람이 가족과 식탁에 둘러앉아 웃는 동안 워크스테이션은 거실 "
                  "한쪽에서 여전히 조용히 켜져 있다."),
        "mood": "happy",
    },
]


async def main() -> int:
    scenes_state = []
    for s in SCENES:
        shutil.copyfile(s["src"], str(tools.refs_dir(JOB_ID) / s["ref_name"]))
        scenes_state.append({
            "id": s["id"],
            "text": s["text"],
            "duration": 3.0,
            "mood": s["mood"],
            "matched_image": s["ref_name"],
            "image_role": "character_ref",
            "quality_flag": "pending",
            "approved": False,
        })

    state = {
        "job_id": JOB_ID,
        "script_text": " ".join(s["text"] for s in SCENES),
        "ref_captions": {},
        "wardrobe_locks": {},
        "image_query": "",
        "scenes": scenes_state,
    }

    print("[1/2] 씬 프롬프트 생성 중...")
    state.update(await node_generate_prompts(state))
    for scene in state["scenes"]:
        assert scene["mode"] == "SUBJECT_REF", f"scene {scene['id']}: mode={scene['mode']}"
        print(f"scene {scene['id']} ref={scene['matched_image']} prompt: {scene['prompt'][:200]}...")

    print("[2/2] SUBJECT_REF 클립 생성 중 (씬별 다른 참조 이미지, ComfyUI :8188)…")
    for scene, s in zip(state["scenes"], SCENES):
        clip_path = await tools.generate_subject_ref_clip(
            job_id=JOB_ID, scene_id=scene["id"], prompt=scene["prompt"],
            ref_image=s["ref_name"], duration=scene["duration"],
            seed=scene_seed(JOB_ID, scene["id"]), force_new=True,
        )
        print(f"  scene {scene['id']} -> {clip_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
