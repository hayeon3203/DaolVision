"""text anchor fix 전체 파이프라인 실측 — 이미지뿐 아니라 실제 STANDIN 클립까지
real infra(FLUX.1-schnell :8501, Ollama, ComfyUI :8188)로 뽑아 사용자 눈으로
그림체 일치 여부 판정. mock 없음, 예전 불일치 재현했던 시나리오(job 41df3d06,
잔디밭 고양이) 그대로 재사용. node_generate_prompts/node_generate_one_clip과
동일한 실제 코드 경로를 그대로 호출한다(그래프 skip, 프로덕션 함수는 그대로).

실행: cd langgraph && ./.venv/bin/python tests/probe_style_bible_e2e.py
결과: langgraph/jobs/probe_style_bible/gen_img_0.png (이미지)
      langgraph/jobs/probe_style_bible/clip1.mp4     (영상)
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import tools  # noqa: E402
from nodes import node_rewrite_image_query, node_generate_prompts, scene_seed  # noqa: E402

JOB_ID = "probe_style_bible"
SCRIPT = "햇살 내리쬐는 잔디밭에서 고양이가 뛰어노는 이미지 생성해줘"


async def main() -> int:
    state = {"job_id": JOB_ID, "image_request": SCRIPT}

    print("[1/4] image_query 생성 중 (Ollama)…")
    state.update(await node_rewrite_image_query(state))
    print("image_query:", state["image_query"])

    print("[2/4] 이미지 생성 중 (FLUX.1-schnell :8501)…")
    png = await tools.generate_t2i_image(JOB_ID, state["image_query"])
    print("gen_image_path:", png)

    # 실제 job 41df3d06과 동일한 구조로 참조 이미지 주입 + 씬 구성
    ref_name = "img_0.png"
    import shutil
    shutil.copyfile(png, str(tools.refs_dir(JOB_ID) / ref_name))
    state["script_text"] = SCRIPT
    state["ref_captions"] = {}
    state["wardrobe_locks"] = {}
    state["scenes"] = [{
        "id": 1,
        "text": "햇살이 쏟아지는 잔디밭에 고양이가 뛰어놀고 있는 장면.",
        "duration": 3.0,
        "mood": "happy",
        "matched_image": ref_name,
        "image_role": "start",
        "quality_flag": "pending",
        "approved": False,
    }]

    print("[3/4] style_bible + 씬 프롬프트 생성 중 (Ollama, 실제 node_generate_prompts)…")
    state.update(await node_generate_prompts(state))
    scene = state["scenes"][0]
    print("style_bible:", state["style_bible"])
    print("mode:", scene["mode"])
    print("prompt:", scene["prompt"])

    print("[4/4] STANDIN 클립 생성 중 (ComfyUI :8188)… 1~2분 소요")
    clip_path = await tools.generate_standin_clip(
        job_id=JOB_ID, scene_id=1, prompt=scene["prompt"],
        ref_image=ref_name, duration=scene["duration"], seed=scene_seed(JOB_ID, 1),
        force_new=True,
    )

    print("\n=== 결과 ===")
    print("이미지:", png)
    print("영상  :", clip_path)
    print("→ 두 파일 열어서 그림체(선/채색/톤) 일치하는지 눈으로 판정.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
