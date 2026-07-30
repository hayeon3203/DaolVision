"""AGENT_CAPTION_REFS=0 이면 caption_image(gemma)가 호출되지 않는지 검증.

회귀 방지: 이 가드가 사라지면 참조 이미지가 있을 때마다 gemma가 다시 로드돼
GPU 압박이 커진다(OOM 재발 경로). 참조: [[gb10-gpu-contention-comfyui-ollama]]

    ./.venv/bin/python test_caption_flag.py
"""
import asyncio

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # langgraph/ 모듈 import용

import tools
import nodes


async def _run(flag: bool):
    calls = []

    async def spy(path):
        calls.append(path)
        return "some caption"

    tools.caption_image = spy
    tools.refs_dir = lambda job_id: __import__("pathlib").Path("/tmp")
    tools.CAPTION_REFS = flag

    state = {"script_text": " hi ", "ref_images": ["img_0.png", "img_1.png"], "job_id": "t"}
    out = await nodes.node_parse_input(state)
    return calls, out


def main():
    calls_on, out_on = asyncio.run(_run(True))
    assert len(calls_on) == 2 and "ref_captions" in out_on, (calls_on, out_on)

    calls_off, out_off = asyncio.run(_run(False))
    assert calls_off == [] and "ref_captions" not in out_off, (calls_off, out_off)

    print("ok: CAPTION_REFS=1 → gemma 2회 호출 / =0 → gemma 미호출")


if __name__ == "__main__":
    main()
