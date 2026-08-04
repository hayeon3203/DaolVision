"""text anchor fix(_make_style_bible에 image_query 전달) 실측.
mock 없이 실제 FLUX.1-schnell(:8501) + Ollama로 예전 불일치 재현했던 시나리오
(job 41df3d06, 잔디밭 고양이)를 다시 돌려 image_query와 style_bible을 나란히
찍는다. 사용자 눈 판정용 — text anchor만으로 충분한지, vision 캡션까지
필요한지는 이 결과 보고 결정.

실행: cd langgraph && ./.venv/bin/python tests/probe_style_bible_anchor.py
결과: langgraph/jobs/probe_style_bible/gen_img_0.png + 콘솔에 image_query,
style_bible 나란히 출력.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import tools  # noqa: E402
from nodes import node_rewrite_image_query, _make_style_bible  # noqa: E402

JOB_ID = "probe_style_bible"
SCRIPT = "햇살 내리쬐는 잔디밭에서 고양이가 뛰어노는 이미지 생성해줘"


async def main() -> int:
    out_dir = tools.JOBS_DIR / JOB_ID
    out_dir.mkdir(parents=True, exist_ok=True)

    state = {"job_id": JOB_ID, "image_request": SCRIPT}
    print("[1/3] image_query 생성 중 (Ollama)…")
    state.update(await node_rewrite_image_query(state))
    print("image_query:", state["image_query"])

    print("[2/3] 이미지 생성 중 (FLUX.1-schnell :8501)…")
    png = await tools.generate_t2i_image(JOB_ID, state["image_query"])
    print("gen_image_path:", png)

    print("[3/3] style_bible 생성 중 (Ollama, image_query 앵커 포함)…")
    state["script_text"] = SCRIPT
    state["scenes"] = [{"text": "햇살이 쏟아지는 잔디밭에 고양이가 뛰어놀고 있는 장면."}]
    state["ref_captions"] = {}
    bible, _sheet = await _make_style_bible(state)

    print("\n=== 결과 ===")
    print("image_query :", state["image_query"])
    print("style_bible :", bible)
    print(f"\n이미지 파일: {png}")
    print("→ 이미지 열어서 style_bible 문구가 실제 그림체와 맞는지 눈으로 판정.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
