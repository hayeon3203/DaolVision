"""SUBJECT_REF identity-lock 문구 수정 실측 — "카메라가 피사체를 안 따라감" 회귀
재현했던 시나리오(job f1be24f6, 고양이 SUBJECT_REF) 그대로 다시 돌려 카메라가
움직이는지 확인. mock 없음, 실제 ComfyUI(:8188) 사용.

실행: cd langgraph && ./.venv/bin/python tests/probe_subject_ref_camera.py
결과: langgraph/jobs/probe_subject_ref/clip1.mp4
"""
import asyncio
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import tools  # noqa: E402
from nodes import node_generate_prompts, scene_seed  # noqa: E402

JOB_ID = "probe_subject_ref"
SRC_IMAGE = Path(__file__).resolve().parent.parent / "jobs" / "probe_style_bible" / "gen_img_0.png"


async def main() -> int:
    ref_name = "img_0.png"
    shutil.copyfile(SRC_IMAGE, str(tools.refs_dir(JOB_ID) / ref_name))

    state = {
        "job_id": JOB_ID,
        "script_text": "햇살 내리쬐는 잔디밭에서 고양이가 뛰어노는 이미지 생성해줘",
        "ref_captions": {},
        "wardrobe_locks": {},
        "image_query": "Anime illustration style of a fluffy cat running joyfully in a sunlit meadow.",
        "scenes": [{
            "id": 2,
            "text": "고양이가 햇살 아래서 자유롭게 뛰어노는 모습이 보인다.",
            "duration": 3.0,
            "mood": "excited",
            "matched_image": ref_name,
            "image_role": "character_ref",   # 강제 SUBJECT_REF
            "quality_flag": "pending",
            "approved": False,
        }],
    }
    print("[1/2] style_bible + 씬 프롬프트 생성 중 (SUBJECT_REF 강제)…")
    state.update(await node_generate_prompts(state))
    scene = state["scenes"][0]
    print("mode:", scene["mode"])
    print("prompt:", scene["prompt"])
    assert scene["mode"] == "SUBJECT_REF"

    print("[2/2] SUBJECT_REF 클립 생성 중 (ComfyUI :8188)…")
    clip_path = await tools.generate_subject_ref_clip(
        job_id=JOB_ID, scene_id=2, prompt=scene["prompt"],
        ref_image=ref_name, duration=scene["duration"],
        seed=scene_seed(JOB_ID, 2), force_new=True,
    )
    print("\n영상:", clip_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
