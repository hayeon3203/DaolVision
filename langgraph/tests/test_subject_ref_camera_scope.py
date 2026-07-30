"""SUBJECT_REF identity-lock 문구가 카메라/구도까지 얼려버리지 않는지 검증.

회귀 방지: "Preserve its complete silhouette..." 문구가 카메라 트래킹을 억눌러
배경이 고정된 채 다리만 움직이는 "제자리 걷기"로 나온 사례 실측(2026-07-10, job
f1be24f6-aaf7-4e39-bc0c-49ac3ca64e5c). identity lock은 피사체 외형에만 한정되고
카메라는 별도라고 명시해야 한다. 실제 ComfyUI 실측은 tests/probe_subject_ref_camera.py.

    ./.venv/bin/python tests/test_subject_ref_camera_scope.py
"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nodes import node_generate_prompts


async def _run():
    state = {
        "script_text": "고양이가 잔디밭에서 뛰어논다.",
        "style_bible": "anime style",
        "ref_captions": {},
        "wardrobe_locks": {},
        "scenes": [{
            "id": 1, "text": "고양이가 뛰어논다.", "mood": "happy",
            "matched_image": "img_0.png", "image_role": "character_ref",
        }],
    }
    with patch("tools.USE_STANDIN", True), \
         patch("tools.call_llm", new=AsyncMock(return_value="a cat running, dynamic tracking camera")):
        result = await node_generate_prompts(state)
    return result["scenes"][0]


def main():
    scene = asyncio.run(_run())
    assert scene["mode"] == "SUBJECT_REF"
    prompt = scene["prompt"]
    assert "does NOT fix the camera, framing, composition" in prompt, \
        "identity lock이 카메라/구도 무관하다고 명시 안 됨(회귀)"
    assert "()" not in prompt, "caption 빈 문자열일 때 빈 괄호가 프롬프트에 남음"
    print("ok: identity lock이 카메라를 못 얼리게 스코프 한정됨, 빈 괄호 없음")


if __name__ == "__main__":
    main()
