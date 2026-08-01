"""Wan2.2(:8500, 중국 원산) 백엔드 제거 검증 — docs/model-selection.md의
'비중국 원산' 원칙 위반 해소. T2V/I2V 폴백 씬을 LTX-Video-0.9.8-13B-distilled
(:8188 ComfyUI, Task 4.6이 이미 받아둔 체크포인트)로 통합.
ComfyUI 실호출 없이 GPU 없이 돈다 — 라이브 검증은 별도 수동 단계(플랜 Task 10).

    ./.venv/bin/python tests/test_wan_removal.py
"""
import asyncio
import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # langgraph/ 모듈 import용

import tools
import nodes


def test_to_ltx_len_snaps_to_8k_plus_1():
    assert tools.to_ltx_len(97) == 97       # 8*12+1, 이미 8k+1이면 그대로
    assert tools.to_ltx_len(1) == 25        # 최소 클램프
    assert tools.to_ltx_len(50) == 49       # 49(8*6+1, 차이1)가 57(8*7+1, 차이7)보다 가까움
    for n in (17, 33, 60, 100, 200):
        v = tools.to_ltx_len(n)
        assert (v - 1) % 8 == 0 and v >= 25, (n, v)
    print("ok: LTX length가 8k+1로 스냅되고 최소 25 유지")


def test_t2v_graph_has_no_image_nodes():
    graph = tools._build_ltx13b_t2v_graph(
        prompt="a robot waving", width=832, height=480, length=49, seed=7)
    assert not any(n["class_type"] in ("LoadImage", "LTXVImgToVideo")
                   for n in graph.values()), graph
    assert graph["7"]["class_type"] == "EmptyLTXVLatentVideo"
    assert graph["7"]["inputs"] == {
        "width": 832, "height": 480, "length": 49, "batch_size": 1}
    assert graph["9"]["inputs"]["positive"] == ["12", 0]
    assert graph["9"]["inputs"]["negative"] == ["12", 1]
    assert graph["9"]["inputs"]["latent_image"] == ["7", 0]
    assert graph["9"]["inputs"]["seed"] == 7
    assert graph["9"]["inputs"]["model"] == ["6", 0]
    assert graph["3"]["inputs"]["text"] == "a robot waving"
    assert graph["1"]["inputs"]["ckpt_name"] == tools.LTX13B_CHECKPOINT
    print("ok: T2V 그래프에 이미지 노드 없음, latent/조건 배선 정확")


def main():
    test_to_ltx_len_snaps_to_8k_plus_1()
    test_t2v_graph_has_no_image_nodes()


if __name__ == "__main__":
    main()
    sys.exit(0)
