"""AGENT_FACE_BACKEND 라우팅 검증 — 인물 참조 씬이 백엔드에 따라
LTX_FACEID(LTX 13B + Face-ID) / STANDIN(Wan2.1-14B + Stand-In)으로 갈리는지.

이 스위치가 생기기 전에는 node_classify_faceid_scenes가 인물 씬을 무조건
LTX_FACEID로 승격시켜 Stand-In 경로가 도달 불가였다. 그 회귀를 막는 게 목적.

  ./.venv/bin/python tests/test_face_backend_routing.py   # GPU/LLM 미호출, ~1초
"""
import importlib
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def classify_modes(backend: str) -> list[str]:
    """인물 참조 씬 2개를 해당 백엔드로 분류시키고 mode만 뽑는다."""
    os.environ["AGENT_FACE_BACKEND"] = backend
    import tools
    import nodes
    importlib.reload(tools)
    importlib.reload(nodes)

    def scene(i: int) -> dict:
        return {"id": i, "text": "그녀가 창가로 걸어간다", "matched_image": "img_0.png",
                "subject_type": "human", "image_role": "start", "mode": "STANDIN"}

    out = nodes.node_classify_faceid_scenes(
        {"scenes": [scene(1), scene(2)], "ref_images": ["img_0.png"]})
    return [s["mode"] for s in out["scenes"]]


# LTX 경로: 첫 씬만 Face-ID 정원(FACEID_MAX_SCENES=1) 안에 들고 나머지는 조립으로 강등.
assert classify_modes("ltx_faceid") == ["LTX_FACEID", "PERSON_ASSEMBLY"], \
    classify_modes("ltx_faceid")

# Stand-In 경로: 승격 없음 = 정원 제약도 없음. 인물 씬 전부 STANDIN.
assert classify_modes("standin") == ["STANDIN", "STANDIN"], classify_modes("standin")

# 오타난 백엔드 이름은 import 시점에 죽는다 — 조용히 LTX로 폴백하면 안 된다.
os.environ["AGENT_FACE_BACKEND"] = "wan"
import tools
try:
    importlib.reload(tools)
except ValueError as e:
    assert "AGENT_FACE_BACKEND" in str(e), e
else:
    raise AssertionError("잘못된 AGENT_FACE_BACKEND가 통과했다")

print("face backend routing self-check ok")
