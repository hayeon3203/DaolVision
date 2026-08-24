"""서버 재기동이 **취소된 job을 되살리지 않는지** 회귀 테스트.

이전 동작: startup()이 `recoverable_comfy_jobs()`가 준 job을 그대로 _launch 했다. 그
목록은 comfy_prompts에 queued/running/**completed** 행이 남은 job을 전부 돌려주므로
오래전에 취소한 job도 섞인다. 그 결과 서버를 재기동할 때마다 옛 job이 살아나
_gen_semaphore(동시 1개)를 물고 새 job을 굶겼다 — 2026-08-23 실측: 무드등 E2E가
씬분할에서 멈춘 채 872beeee 씬1이 재생성됐다.

    cd langgraph && ./.venv/bin/python tests/test_startup_skips_cancelled.py
"""
import asyncio
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

os.environ["AGENT_JOBS_DIR"] = tempfile.mkdtemp(prefix="anim_test_jobs_")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import api          # noqa: E402
import tools        # noqa: E402

CANCELLED, LIVE = "cancelled-job", "live-job"


class _FakeGraph:
    async def aget_state(self, config):
        # 둘 다 "다음 노드가 남았고 사람 승인 인터럽트는 없다" = 회수 대상 형태
        return SimpleNamespace(next=("node_generate_clips",), values={}, tasks=[])

    async def ainvoke(self, payload, config):
        raise AssertionError("회수된 job이 실제로 실행되면 안 된다(_launch를 대체했다)")


async def main():
    api.RUNNING.clear()
    launched = []

    (tools.job_dir(CANCELLED) / ".cancelled").write_text("user_cancelled\n")
    tools.job_dir(LIVE)

    async def fake_compile_graph(db_path):
        return _FakeGraph()

    api.compile_graph = fake_compile_graph
    tools.recoverable_comfy_jobs = lambda: [CANCELLED, LIVE]
    api._launch = lambda job_id, coro: (launched.append(job_id), coro.close())

    await api.startup()

    assert CANCELLED not in launched, f"취소된 job이 되살아났다: {launched}"
    assert LIVE in launched, f"살아있는 job을 회수하지 못했다: {launched}"
    print("OK: 취소된 job은 건너뛰고 살아있는 job만 회수")


if __name__ == "__main__":
    asyncio.run(main())
