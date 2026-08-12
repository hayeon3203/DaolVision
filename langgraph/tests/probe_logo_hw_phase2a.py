"""로고+GB10 하루 몽타주 시나리오를 그래프 직호출(HTTP API 아님, driver.py와
동일하게 graph.ainvoke 직접 호출)로 끝까지 실행 — 승인게이트는 자동승인.
Phase 2(b)의 실제 UI 실행과 같은 입력으로 비교하기 위한 스크립트/API측 기준선.

실행: cd langgraph && ./.venv/bin/python tests/probe_logo_hw_phase2a.py
결과: jobs/<job_id>/final_video.mp4, jobs/probe_logo_hw/phase2a_log.json
"""
import asyncio
import base64
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langgraph.types import Command

import tools  # noqa: E402
from api import _save_ref_images  # noqa: E402
from graph import compile_graph  # noqa: E402

REF_IMAGE = (
    Path(__file__).resolve().parent.parent
    / "jobs" / "probe_logo_hw" / "assets" / "ref_composite.png"
)
LOG_PATH = (
    Path(__file__).resolve().parent.parent
    / "jobs" / "probe_logo_hw" / "phase2a_log.json"
)

SCRIPT_TEXT = (
    "시네마틱한 아침 햇살 아래, 사람이 출근 준비를 하는 동안 책상 위 DaolFusion "
    "GB10 워크스테이션이 이미 조용히 켜져 데이터를 정리하고 있다. 낮, 사무실에서 사람은 회의와 창작에 "
    "몰입하고 워크스테이션은 화면에 진행률을 띄운 채 반복 작업을 대신 처리한다. "
    "저녁, 사람이 가족과 식탁에 둘러앉아 웃는 동안 워크스테이션은 거실 한쪽에서 "
    "여전히 조용히 켜져 있다. 밤, 다들 잠든 집 안에서 워크스테이션의 로고만 "
    "은은히 빛나며 여전히 작동하고 있다."
)


def _auto_decision(cp: dict) -> dict:
    name = cp.get("checkpoint", "")
    if name.startswith("1-4"):
        return {"approved": True}
    if name.startswith("2-3"):
        return {"approved": True}
    if name.startswith("3-5"):
        return {"action": "approve_all"}
    if name.startswith("4-5"):
        return {"approved": True}
    raise RuntimeError(f"알 수 없는 체크포인트: {cp}")


async def main() -> int:
    job_id = f"logohw2a-{uuid.uuid4().hex[:8]}"
    graph = await compile_graph(str(tools.JOBS_DIR / f"checkpoints_{job_id}.db"))
    config = {"configurable": {"thread_id": job_id}}

    # ponytail: api.py의 실제 /jobs 엔트리와 동일하게 data-URI를 refs_dir(job_id)에
    # 저장하고 '파일명'을 state.ref_images에 넣는다(브리프 원안처럼 data-URI 문자열을
    # 그대로 넣으면 node_split_scenes가 이걸 통째로 LLM 프롬프트에 박아 넣어 810k
    # 토큰으로 Ollama num_ctx=8192를 초과, 400 Bad Request — 실측 확인된 스크립트 버그).
    ref_b64 = base64.b64encode(REF_IMAGE.read_bytes()).decode()
    ref_names = _save_ref_images(job_id, [f"data:image/png;base64,{ref_b64}"])
    print(f"[job {job_id}] 시작 (ref_images={ref_names})", flush=True)
    result = await graph.ainvoke(
        {
            "job_id": job_id,
            "script_text": SCRIPT_TEXT,
            "ref_images": ref_names,
            "scenes": [],
            "clip_results": [],
            "regen_target_ids": [],
        },
        config=config,
    )
    # ponytail: driver.py와 동일하게 result["__interrupt__"] 패턴 사용
    # (브리프 원안의 aget_state().tasks[].interrupts 순회는 이 langgraph 버전에서
    # 실제 interrupt를 못 잡아 즉시 빈 채로 빠져나옴 — driver.py 실증 패턴으로 교체)
    step = 0
    while "__interrupt__" in result:
        cp = result["__interrupt__"][0].value
        decision = _auto_decision(cp)
        step += 1
        print(f"  checkpoint {cp.get('checkpoint')} -> {decision}", flush=True)
        result = await graph.ainvoke(Command(resume=decision), config=config)

    final_state = (await graph.aget_state(config)).values
    log = {
        "job_id": job_id,
        "final_video_path": final_state.get("final_video_path"),
        "scenes": [
            {
                "id": s.get("id"),
                "matched_image": s.get("matched_image"),
                "subject_type": s.get("subject_type"),
                "image_role": s.get("image_role"),
                "mode": s.get("mode"),
                "prompt": s.get("prompt"),
                "mood": s.get("mood"),
            }
            for s in final_state.get("scenes", [])
        ],
    }
    LOG_PATH.write_text(json.dumps(log, ensure_ascii=False, indent=2))
    print(f"\n최종 영상: {final_state.get('final_video_path')}")
    print(f"로그: {LOG_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
