"""SC1 검증: 클립 생성 running 중에 /status 응답이 완성 클립 URL(clips[])을
전체 완료 전에 노출하는지 — OWU 인라인 스트리밍의 데이터 소스.

  ./.venv/bin/python test_status_clips.py   # 가짜 클립, GPU/LLM 미호출, ~10초
"""
import asyncio
import os
import sys
import tempfile

os.environ["AGENT_JOBS_DIR"] = tempfile.mkdtemp(prefix="anim_test_jobs_")

from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # langgraph/ 모듈 import용

import driver
import tools

driver._install_fakes()

# 씬별 완료 시점을 어긋나게 해 '일부만 완성된' running 상태를 폴링이 관측하게 한다.
_orig_video = tools.call_video


async def _staggered_video(job_id, scene_id, *a, **kw):
    await asyncio.sleep(0.3 if scene_id == 1 else 2.0)
    return await _orig_video(job_id, scene_id, *a, **kw)


tools.call_video = _staggered_video

import api  # tools 패치 후 import (graph가 tools 참조를 바인딩하기 전)


async def main():
    await api.startup()
    r = await api.start_job(api.StartJobRequest(
        script_text="주인공이 걷다가 뛰기 시작한다", ref_images=[]))
    job_id = r["job_id"]

    async def wait_for(pred, timeout=60.0, collect=None):
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            s = await api.job_status(job_id)
            if collect is not None and s.get("status") == "running":
                collect.append(s)
            if pred(s):
                return s
            await asyncio.sleep(0.05)
        raise TimeoutError(f"조건 미충족: 마지막 status={s}")

    # 1-4 씬분할 게이트 도달 → 승인
    s = await wait_for(lambda s: s.get("status") == "waiting_for_approval")
    assert s["checkpoint"]["checkpoint"].startswith("1-4"), s
    await api.resume_job(job_id, api.ResumeRequest(payload={"approved": True}))

    # 클립 생성 running 동안 부분 완성 상태를 관측
    # (resume 직후엔 1-4 interrupt가 아직 남아 있어 3-5 도달을 명시적으로 기다린다)
    seen = []
    s = await wait_for(lambda s: s.get("status") == "waiting_for_approval"
                       and s["checkpoint"]["checkpoint"].startswith("3-5"),
                       collect=seen)

    partial = [x for x in seen
               if x.get("clips") and 0 < len(x["clips"]) < (x.get("clips_total") or 0)]
    assert partial, f"부분 완성 running 관측 실패 (관측 {len(seen)}회): clips가 전체 완료 전에 노출되지 않음"
    clip = partial[0]["clips"][0]
    assert clip["scene_id"] == 1 and clip["url"].startswith("/files/") \
        and clip["url"].endswith("clip1.mp4"), clip
    # URL이 실제 서빙 파일과 일치
    assert (tools.JOBS_DIR / job_id / "clip1.mp4").exists()
    print(f"PASS: running 중 부분 완성 clips 노출 확인 — {clip['url']} "
          f"(running 관측 {len(seen)}회, 부분 완성 {len(partial)}회)")


if __name__ == "__main__":
    asyncio.run(main())
    sys.exit(0)
