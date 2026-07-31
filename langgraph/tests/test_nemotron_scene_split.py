"""Task 5.1: Nemotron 기본 배선과 한국어 4씬 분할 계약 회귀 테스트."""
import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import nodes
import tools


NEMOTRON_MODEL = "hf.co/nvidia/NVIDIA-Nemotron-3-Nano-4B-GGUF:Q4_K_M"


async def _run():
    llm_result = """[
      {"text":"우주비행사가 발사대로 향한다","duration":2,"mood":"tense","subject_type":"human"},
      {"text":"우주비행사가 우주를 유영한다","duration":3,"mood":"calm","subject_type":"human"},
      {"text":"우주비행사가 외계행성에 착륙한다","duration":3,"mood":"surprised","subject_type":"human"},
      {"text":"우주비행사가 지구로 귀환한다","duration":2,"mood":"happy","subject_type":"human"}
    ]"""
    with patch("tools.call_llm", new=AsyncMock(return_value=llm_result)) as call:
        result = await nodes.node_split_scenes({
            "script_text": (
                "우주비행사가 발사대를 떠나 우주를 유영하고 외계행성에 착륙한 뒤 "
                "무사히 지구로 귀환한다."
            ),
            "ref_images": [],
            "ref_captions": {},
        })
    system_prompt = call.await_args.args[0]
    assert "정확히 4개 씬" in system_prompt
    assert len(result["scenes"]) == 4
    assert [scene["id"] for scene in result["scenes"]] == [1, 2, 3, 4]
    assert all(any("가" <= ch <= "힣" for ch in scene["text"]) for scene in result["scenes"])

    three_scenes = json.dumps(json.loads(llm_result)[:3], ensure_ascii=False)
    retry_llm = AsyncMock(side_effect=[three_scenes, three_scenes])
    with patch("tools.call_llm", new=retry_llm):
        retried = await nodes.node_split_scenes({
            "script_text": "우주비행사가 발사하고 우주를 탐사한 뒤 지구로 귀환한다.",
            "ref_images": [],
            "ref_captions": {},
        })
    assert retry_llm.await_count == 2
    assert len(retried["scenes"]) == 4


if __name__ == "__main__":
    assert tools.LLM_MODEL == NEMOTRON_MODEL, tools.LLM_MODEL
    asyncio.run(_run())
    print("ok: Nemotron-4B default + Korean story split into exactly 4 scenes")
