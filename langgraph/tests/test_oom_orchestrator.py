"""oom_orchestrator.phase()가 batch 모드에서 서로 다른 backend의 겹침을 막고
(로드순서 직렬화 + 전환시 언로드 호출), resident 모드에서는 게이팅 없이 통과시키며,
같은 backend끼리는 여전히 동시 실행을 허용하는지 검증.

회귀 방지: docs/spikes/2.4-oom-residency.md — 백엔드 전환 구간의 동시 이중 상주가
118GB/119GB OOM 크래시 원인으로 추정됨. 이 게이팅이 사라지면 재현 가능.

    ./.venv/bin/python tests/test_oom_orchestrator.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # langgraph/ 모듈 import용

import oom_orchestrator as oom


async def _run_two_backends(mode: str, delay: float = 0.03):
    """backend A(2개 동시)와 backend B(1개)를 겹치게 실행 → (동시-backend peak, A peak, unload 순서)."""
    oom.reset(mode)
    live = {"distinct": set(), "distinct_peak": 0, "a_cur": 0, "a_peak": 0}
    unloaded = []
    oom.register_unload("a", lambda: unloaded.append("a"))
    oom.register_unload("b", lambda: unloaded.append("b"))

    async def work(backend: str, n: float):
        async with oom.phase(backend):
            live["distinct"].add(backend)
            live["distinct_peak"] = max(live["distinct_peak"], len(live["distinct"]))
            if backend == "a":
                live["a_cur"] += 1
                live["a_peak"] = max(live["a_peak"], live["a_cur"])
            await asyncio.sleep(n)
            if backend == "a":
                live["a_cur"] -= 1
            live["distinct"].discard(backend)

    await asyncio.gather(
        work("a", delay), work("a", delay), work("b", delay),
    )
    return live["distinct_peak"], live["a_peak"], unloaded


def main():
    # batch: a 두 개는 같은 backend라 동시 실행 허용(peak 2), 그러나 서로 다른 backend(a/b)는 절대 안 겹침.
    distinct_peak, a_peak, unloaded = asyncio.run(_run_two_backends("batch"))
    assert distinct_peak == 1, f"batch 모드인데 서로 다른 backend가 동시에 활성 (peak={distinct_peak})"
    assert a_peak == 2, f"같은 backend(a) 내부 동시성까지 막힘 (peak={a_peak}, 2 기대)"
    assert unloaded == ["a"], f"backend 전환 전 언로드 훅이 정확히 한 번 호출돼야 함: {unloaded}"

    # resident: 게이팅 없음 → 서로 다른 backend도 자유롭게 겹칠 수 있고, unload 훅은 안 불림.
    distinct_peak_r, a_peak_r, unloaded_r = asyncio.run(_run_two_backends("resident"))
    assert distinct_peak_r == 2, f"resident 모드인데 겹침이 막힘 (peak={distinct_peak_r})"
    assert unloaded_r == [], f"resident 모드에서 unload 훅이 호출되면 안 됨: {unloaded_r}"

    print("ok: batch=서로 다른 backend 직렬화(peak 1)+같은 backend 동시성 유지(peak 2)+전환시 언로드 1회 / "
          "resident=게이팅 없음(peak 2)+언로드 없음")


if __name__ == "__main__":
    main()
