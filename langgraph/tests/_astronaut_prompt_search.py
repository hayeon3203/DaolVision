"""
1회성 실측 스크립트 — 우주비행사 시나리오 프롬프트 5종 비교.
driver.py의 image_roundtrip 패턴을 재사용해 실서버(Ollama/FLUX/LTX-13B)로 5개 job을
순차 실행하고 각 최종 영상 경로 + 소요시간을 출력한다. 커밋 대상 아님(_ 프리픽스).
"""
import asyncio
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # langgraph/ 모듈 import용

from langgraph.types import Command

import tools

ANCHOR_IMAGE_REQUEST = (
    "우주비행사 헬멧을 쓴 젊은 남자, 얼굴이 잘 보이는 정면 클로즈업, 사실적인 사진 스타일"
)

CANDIDATES = [
    "한 청년 우주비행사가 지구를 떠나 우주선을 타고 미지의 행성을 향해 나아간다.",
    "우주비행사가 우주선 창밖으로 지구를 바라보다가, 낯선 행성에 착륙해 첫 발을 내딛는다.",
    "한 우주비행사의 여정. 발사, 우주 비행, 행성 착륙, 그리고 첫 발걸음.",
    "우주비행사가 별들 사이를 항해하다 낯선 행성을 발견하고 조심스럽게 착륙선에서 내린다.",
    "지구를 떠난 한 우주비행사가 광활한 우주를 가로질러 마침내 새로운 세계에 도착한다.",
]


def _auto_decision(cp: dict, script_text: str) -> dict:
    name = cp.get("checkpoint", "")
    if name.startswith("2-3"):
        return {"approved": True}
    if name.startswith("2-4"):
        return {"script_text": script_text}
    if name.startswith("1-4"):
        return {"approved": True}
    if name.startswith("3-5"):
        return {"action": "approve_all"}
    if name.startswith("4-5"):
        return {"approved": True}
    raise RuntimeError(f"unknown checkpoint: {cp}")


async def run_one(graph, idx: int, script_text: str) -> dict:
    job_id = f"astro{idx}-{uuid.uuid4().hex[:6]}"
    config = {"configurable": {"thread_id": job_id}}
    t0 = time.time()
    print(f"\n=== [{idx}] job={job_id} ===", flush=True)
    print(f"story: {script_text}", flush=True)

    result = await graph.ainvoke(
        {
            "job_id": job_id,
            "script_text": script_text,
            "image_request": ANCHOR_IMAGE_REQUEST,
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
        decision = _auto_decision(cp, script_text)
        step += 1
        print(f"  [interrupt {step}] {cp.get('checkpoint')} -> {decision}", flush=True)
        result = await graph.ainvoke(Command(resume=decision), config=config)

    dt = time.time() - t0
    final = result.get("final_video_path")
    scenes = result.get("scenes") or []
    ok = bool(final and tools.Path(final).exists())
    print(f"  done in {dt:.1f}s final={final} ok={ok}", flush=True)
    return {
        "idx": idx,
        "job_id": job_id,
        "script_text": script_text,
        "final_video_path": final if ok else None,
        "seconds": dt,
        "scene_texts": [s.get("text") for s in scenes],
    }


async def main():
    from graph import compile_graph

    graph = await compile_graph(str(tools.JOBS_DIR / "checkpoints_astro_search.db"))
    results = []
    # run 1은 astro1-9044f4로 이미 성공(final.mp4 존재) — ComfyUI 재시작으로 run 2가
    # 사라진 prompt_id를 기다리며 멈춰있던 것만 재실행. 2번부터 재개.
    for i, story in enumerate(CANDIDATES, start=1):
        if i == 1:
            print(f"\n=== [1] skip (already done: jobs/astro1-9044f4/final.mp4) ===", flush=True)
            continue
        try:
            r = await run_one(graph, i, story)
        except Exception as e:
            print(f"  FAILED: {type(e).__name__}: {e}", flush=True)
            r = {"idx": i, "job_id": None, "script_text": story,
                 "final_video_path": None, "seconds": None, "error": str(e)}
        results.append(r)

    print("\n=== SUMMARY ===", flush=True)
    for r in results:
        print(r, flush=True)


if __name__ == "__main__":
    asyncio.run(main())
