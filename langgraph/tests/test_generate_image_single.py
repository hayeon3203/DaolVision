"""node_generate_image 1장 고정 회귀 테스트.

1장 시나리오 확정(job 78f91567 — flux_server.py 동시요청 레이스로 500 재현) 이후,
state에 옛 다중 image_queries가 남아있어도(예: 재생성 루프에서 stale 값) 방어적으로
1개까지만 생성 호출해야 한다.

    cd langgraph && ./.venv/bin/python tests/test_generate_image_single.py
"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import nodes


async def test_generate_image_calls_t2i_once_even_with_stale_multi_queries():
    mock = AsyncMock(side_effect=lambda job_id, q, seed=None, index=0: f"/jobs/{job_id}/gen_img_{index}.png")
    with patch("tools.generate_t2i_image", new=mock):
        result = await nodes.node_generate_image({
            "job_id": "job1",
            "image_queries": ["a cat", "a dog", "a bird"],
        })
    assert mock.await_count == 1, "1장 고정인데 여러 번 호출됨"
    assert result["gen_image_paths"] == ["/jobs/job1/gen_img_0.png"]
    assert result["phase"] == "image_generating"


if __name__ == "__main__":
    asyncio.run(test_generate_image_calls_t2i_once_even_with_stale_multi_queries())
    print("ok: node_generate_image는 stale 다중 queries가 있어도 1장만 생성")
