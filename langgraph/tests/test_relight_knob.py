"""M3-8 서버측 relight 노브 검증.

mood가 참조와 크게 괴리된 씬(sad/tense)만 첫프레임 latent 잠금을 완화하고,
밝은/중립 씬은 기존 1.0 동작을 유지하는지 확인. 워크플로 노드 105가 override할
키를 실제로 갖고 있는지도 함께 검사(워크플로 드리프트 방지).

    ./.venv/bin/python tests/test_relight_knob.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tools
from nodes import _needs_relight


def test_relight_decision():
    assert _needs_relight("sad") and _needs_relight("tense"), "저조도 mood가 relight 대상 아님"
    assert not _needs_relight("happy"), "밝은 씬에 relight 켜짐"
    assert not _needs_relight("neutral") and not _needs_relight(""), "중립/빈 mood에 relight 켜짐"
    print("ok: sad/tense만 relight, 밝은/중립 미적용")


def test_overrides():
    assert tools._relight_embed_overrides(False) == {}, "미적용 씬인데 override 발생(기존 동작 깨짐)"
    ov = tools._relight_embed_overrides(True)
    assert set(ov) == {"start_latent_strength", "end_latent_strength", "noise_aug_strength"}
    assert ov["start_latent_strength"] < 1.0 and ov["end_latent_strength"] < 1.0, "latent 잠금이 완화 안됨"
    assert ov["noise_aug_strength"] > 0.0, "noise_aug로 밝기 잠금 해제 안됨"
    print("ok: relight override가 latent 잠금 완화")


def test_workflow_has_override_keys():
    """override 대상 키가 워크플로 노드 105(embeds)에 실제 존재 — 이름 바뀌면 무시돼 조용히 실패."""
    graph = json.loads(tools.STANDIN_WORKFLOW.read_text())
    embeds = graph[tools._SI["embeds"]]["inputs"]
    for key in tools._relight_embed_overrides(True):
        assert key in embeds, f"워크플로 embeds 노드에 {key} 없음 — override 무시됨"
    print("ok: 워크플로 노드가 override 키 보유")


def main():
    test_relight_decision()
    test_overrides()
    test_workflow_has_override_keys()
    print("\nall M3-8 relight tests passed")


if __name__ == "__main__":
    main()
