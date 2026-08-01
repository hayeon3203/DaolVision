"""
헤드리스 검증 드라이버.

  python driver.py --dry     # Ollama/Wan 미호출, 가짜 클립으로 그래프+ffmpeg 전 경로 검증
  python driver.py           # 실서버(Ollama Nemotron-4B + Wan :8500) end-to-end

--dry 는 배선/interrupt/resume/xfade/자막 로직을, 실모드는 진짜 생성을 확인한다.
사람 승인 자리는 자동 승인 payload로 대체.
"""
import argparse
import asyncio
import subprocess
import sys
import uuid

from langgraph.types import Command

import tools


def _auto_decision(cp: dict) -> dict:
    name = cp.get("checkpoint", "")
    if name.startswith("2-3"):
        return {"approved": True}
    if name.startswith("2-4"):  # M3-1: 이미지 승인 후 시나리오 입력
        return {"script_text": "귀여운 로봇이 손을 흔들다가 신나게 달려간다."}
    if name.startswith("1-4"):
        return {"approved": True}
    if name.startswith("3-5"):
        return {"action": "approve_all"}
    if name.startswith("4-5"):
        return {"approved": True}
    raise RuntimeError(f"알 수 없는 체크포인트: {cp}")


def _install_fakes():
    """--dry: tools.call_llm / call_video 를 가짜로 교체."""
    import json

    async def fake_llm(system_prompt: str, user_prompt: str) -> str:
        if "스토리보드" in system_prompt:  # node_split_scenes
            return json.dumps([
                {"text": "해질녘 도시를 걷는 주인공", "duration": 2.0,
                 "mood": "calm", "matched_image": None},
                {"text": "주인공이 네온사인을 발견한다", "duration": 2.0,
                 "mood": "surprised", "matched_image": None},
                {"text": "네온사인 아래 달리기 시작", "duration": 2.0,
                 "mood": "tense", "matched_image": None},
                {"text": "도시 끝에 도착해 숨을 고른다", "duration": 2.0,
                 "mood": "calm", "matched_image": None},
            ], ensure_ascii=False)
        if "text-to-image generator" in system_prompt:  # node_rewrite_image_query (M2-1/M2-5)
            style = "pastel watercolor style, soft warm lighting"
            return json.dumps([
                {"query": f"a cute waving robot, {style}"},
                {"query": f"a spaceship background, {style}"},
            ], ensure_ascii=False)
        return "a cinematic shot, camera slowly pushing in"  # node_generate_prompts

    def _fake_clip(job_id, scene_id):
        out = tools.job_dir(job_id) / f"clip{scene_id}.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i",
             f"testsrc=duration=1:size={tools.WIDTH}x{tools.HEIGHT}:rate={tools.DEFAULT_FPS}",
             "-pix_fmt", "yuv420p", str(out)],
            check=True, capture_output=True,
        )
        return str(out)

    async def fake_video(job_id, scene_id, prompt, mode, matched_image,
                         duration=2.0, seed=None, num_frames=None):
        return _fake_clip(job_id, scene_id)

    async def fake_standin(job_id, scene_id, prompt, ref_image, duration=2.0, seed=None, force_new=False):
        return _fake_clip(job_id, scene_id)

    async def fake_t2i_image(job_id, prompt, seed=None, index=0):
        out = tools.job_dir(job_id) / f"gen_img_{index}.png"
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i",
             f"color=c=blue:size={tools.WIDTH}x{tools.HEIGHT}", "-frames:v", "1", str(out)],
            check=True, capture_output=True,
        )
        return str(out)

    async def fake_ltx_faceid_batch(job_id, scenes):
        # ponytail: 실 storyboard가 아직 matched_image를 채우지 않아 오늘은 안 불리지만,
        # 미래에 --dry 픽스처가 인물 참조를 넣으면 실 ComfyUI 호출을 막는 안전망.
        return {scene["id"]: _fake_clip(job_id, scene["id"]) for scene in scenes}

    tools.call_llm = fake_llm
    tools.call_video = fake_video
    tools.generate_standin_clip = fake_standin
    tools.generate_t2i_image = fake_t2i_image
    tools.generate_ltx_faceid_batch = fake_ltx_faceid_batch
    tools.CAPTION_REFS = False  # dry: 비전(gemma) 미호출 — 이미지 분기 승인 후 ref 캡션 스킵


async def main(dry: bool):
    if dry:
        _install_fakes()

    from graph import compile_graph  # tools 패치 후 import

    job_id = f"test-{uuid.uuid4().hex[:8]}"
    graph = await compile_graph(str(tools.JOBS_DIR / f"checkpoints_{job_id}.db"))
    config = {"configurable": {"thread_id": job_id}}

    print(f"[job {job_id}] 시작 (dry={dry})", flush=True)
    result = await graph.ainvoke(
        {
            "job_id": job_id,
            "script_text": "해질녘 도시를 배경으로 한 짧은 애니메이션. 주인공이 걷다가 뛰기 시작한다.",
            "ref_images": [],
            "scenes": [],
            "clip_results": [],
            "regen_target_ids": [],
        },
        config=config,
    )

    step = 0
    while "__interrupt__" in result:
        cp = result["__interrupt__"][0].value
        decision = _auto_decision(cp)
        step += 1
        print(f"[interrupt {step}] {cp.get('checkpoint')} → 자동승인 {decision}", flush=True)
        result = await graph.ainvoke(Command(resume=decision), config=config)

    final = result.get("final_video_path")
    print(f"[done] phase={result.get('phase')} final={final}", flush=True)
    if not final or not tools.Path(final).exists():
        print("FAIL: 최종 영상 없음", flush=True)
        sys.exit(1)
    dur = tools._probe_duration(final)
    print(f"PASS: 최종 영상 존재, {dur:.2f}s", flush=True)


async def image_roundtrip(dry: bool):
    """M2-3 검증: 이미지 분기의 interrupt/resume 왕복(수정 루프 + 승인 → 완료)."""
    if dry:
        _install_fakes()

    from graph import compile_graph

    job_id = f"img-{uuid.uuid4().hex[:8]}"
    graph = await compile_graph(str(tools.JOBS_DIR / f"checkpoints_{job_id}.db"))
    config = {"configurable": {"thread_id": job_id}}

    print(f"[job {job_id}] 이미지 분기 시작 (dry={dry})", flush=True)
    result = await graph.ainvoke(
        {
            "job_id": job_id,
            "script_text": "귀여운 로봇이 등장하는 짧은 애니메이션.",
            "image_request": "귀여운 로봇 한 마리랑 우주선 배경을 그려줘, 두 그림 다 파스텔톤 수채화 느낌으로",
            "ref_images": [],
            "scenes": [],
            "clip_results": [],
            "regen_target_ids": [],
        },
        config=config,
    )
    # 1) 첫 인터럽트 = 이미지 승인 게이트, gen_image_paths 2장 존재 (M2-5: 다중 이미지)
    assert "__interrupt__" in result, "이미지 승인 게이트 미도달"
    cp = result["__interrupt__"][0].value
    assert cp.get("checkpoint", "").startswith("2-3"), cp
    assert len(cp.get("gen_image_paths") or []) == 2, f"gen_image_paths 개수 불일치: {cp.get('gen_image_paths')}"
    assert len(cp.get("image_queries") or []) == 2, f"image_queries 개수 불일치: {cp.get('image_queries')}"
    assert cp.get("gen_image_path"), "gen_image_path(하위호환) 없음"
    print(f"[interrupt] {cp.get('checkpoint')} gen_images={cp.get('gen_image_paths')}", flush=True)

    # 2) 자연어 수정 → rewrite부터 재실행 → 다시 이미지 게이트 (수정 루프 검증)
    result = await graph.ainvoke(Command(resume={"feedback": "더 파랗게 해줘"}), config=config)
    assert "__interrupt__" in result, "수정 후 게이트 재도달 실패"
    cp = result["__interrupt__"][0].value
    assert cp.get("checkpoint", "").startswith("2-3"), f"수정 루프가 2-3로 안 돌아옴: {cp}"
    print(f"[interrupt] 수정 루프 OK → {cp.get('checkpoint')}", flush=True)

    # 3) 승인 → 시나리오 입력 게이트(2-4, M3-1) 도달 확인
    result = await graph.ainvoke(Command(resume={"approved": True}), config=config)
    assert "__interrupt__" in result, "승인 후 시나리오 입력 게이트 미도달"
    cp = result["__interrupt__"][0].value
    assert cp.get("checkpoint", "").startswith("2-4"), f"승인 후 2-4가 아님: {cp}"
    print(f"[interrupt] {cp.get('checkpoint')} → 시나리오 입력", flush=True)

    # 3.5) 승인 시 2장 모두 ref_images/ref_captions로 주입됐는지 확인 (M2-5)
    snapshot = await graph.aget_state(config)
    ref_images = snapshot.values.get("ref_images") or []
    ref_captions = snapshot.values.get("ref_captions") or {}
    assert len(ref_images) == 2, f"승인 후 ref_images 개수 불일치: {ref_images}"
    assert len(ref_captions) == 2, f"승인 후 ref_captions 개수 불일치: {ref_captions}"
    print(f"[state] ref_images={ref_images} ref_captions={ref_captions}", flush=True)

    # 4) 시나리오 입력 → 씬분할 진입 → 나머지 게이트 자동승인 → 완료
    result = await graph.ainvoke(
        Command(resume={"script_text": "귀여운 로봇이 손을 흔들다가 신나게 달려간다."}),
        config=config)
    step = 0
    while "__interrupt__" in result:
        cp = result["__interrupt__"][0].value
        decision = _auto_decision(cp)
        step += 1
        print(f"[interrupt +{step}] {cp.get('checkpoint')} → 자동승인 {decision}", flush=True)
        result = await graph.ainvoke(Command(resume=decision), config=config)

    final = result.get("final_video_path")
    print(f"[done] phase={result.get('phase')} final={final}", flush=True)
    if not final or not tools.Path(final).exists():
        print("FAIL: 이미지 분기 최종 영상 없음", flush=True)
        sys.exit(1)
    print("PASS: 이미지 분기 interrupt/resume 왕복 + 완료", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--image", action="store_true", help="M2 이미지 분기 왕복 검증")
    args = ap.parse_args()
    if args.image:
        asyncio.run(image_roundtrip(args.dry))
    else:
        asyncio.run(main(args.dry))
