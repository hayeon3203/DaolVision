"""ffmpeg 노드가 이벤트루프를 막지 않는지 확인.

ReadTimeout 회귀 방지: node_edit_concat 안의 블로킹 ffmpeg 호출이 to_thread로
오프로드되지 않으면, 인코딩 동안 이벤트루프가 멈춰 :8700의 모든 엔드포인트가
응답 못하고 OWU가 ReadTimeout을 본다. 이 테스트는 블로킹 ffmpeg가 도는 동안
동시에 도는 코루틴(=uvicorn 요청 처리 대역)이 계속 tick 하는지를 검사한다.

직접 호출(블로킹)이면 ticks==0 으로 실패, to_thread 오프로드면 통과.
    python test_event_loop_nonblocking.py
"""
import asyncio
import time

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # langgraph/ 모듈 import용

import tools
import nodes


async def main():
    BLOCK = 0.5  # ffmpeg가 이만큼 걸린다고 가정
    tools.ffmpeg_concat = lambda *a, **k: time.sleep(BLOCK)  # 동기 블로킹 stub
    tools.job_dir = lambda job_id: __import__("pathlib").Path("/tmp")

    state = {
        "job_id": "test",
        "scenes": [
            {"id": 1, "clip_path": "/tmp/a.mp4", "mood": "calm"},
            {"id": 2, "clip_path": "/tmp/b.mp4", "mood": "calm"},
        ],
    }

    ticks = 0

    async def heartbeat():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.05)
            ticks += 1

    hb = asyncio.create_task(heartbeat())
    await nodes.node_edit_concat(state)
    hb.cancel()

    # 블로킹이 오프로드됐다면 heartbeat가 BLOCK 동안 여러 번 돌았어야 한다.
    assert ticks >= 3, f"event loop was blocked during ffmpeg (ticks={ticks})"
    print(f"ok: event loop stayed responsive during ffmpeg (ticks={ticks})")


if __name__ == "__main__":
    asyncio.run(main())
