"""Generation dispatch should group cache-compatible scenes without changing video order.

Success criteria:
- STANDIN scenes with the same reference image are dispatched consecutively, even if a
  different mode sits between them in storyboard order.
- Fan-in merge keeps the original scene order for final approval/editing.
- node_generate_ltx_batch applies the same cache-locality ordering to its non-LTX_FACEID
  fallback_scenes before dispatching them (regression check for the ordering lost when
  node_dispatch_generation stopped being called).

Run:
  ./.venv/bin/python tests/test_generation_order.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import nodes


def _ids(sends):
    return [s.arg["scene"]["id"] for s in sends]


def main():
    scenes = [
        {"id": 1, "mode": "STANDIN", "matched_image": "img_0.png", "image_role": "ref"},
        {"id": 2, "mode": "STANDIN", "matched_image": "img_0.png", "image_role": "ref"},
        {"id": 3, "mode": "SUBJECT_REF", "matched_image": "img_1.png", "image_role": "character_ref"},
        {"id": 4, "mode": "STANDIN", "matched_image": "img_0.png", "image_role": "ref"},
    ]

    sends = nodes.node_dispatch_generation({"job_id": "job", "scenes": scenes})
    assert _ids(sends) == [1, 2, 4, 3], _ids(sends)

    regen_sends = nodes.node_dispatch_generation({
        "job_id": "job",
        "scenes": scenes,
        "regen_target_ids": [3, 4],
    })
    assert _ids(regen_sends) == [4, 3], _ids(regen_sends)

    merged = nodes.node_merge_clip_results({
        "scenes": scenes,
        "clip_results": [
            {"id": 4, "clip_path": "clip4.mp4"},
            {"id": 3, "clip_path": "clip3.mp4"},
            {"id": 2, "clip_path": "clip2.mp4"},
            {"id": 1, "clip_path": "clip1.mp4"},
        ],
    })["scenes"]
    assert [s["id"] for s in merged] == [1, 2, 3, 4], merged
    assert [s["clip_path"] for s in merged] == [
        "clip1.mp4", "clip2.mp4", "clip3.mp4", "clip4.mp4"
    ], merged

    print("ok: dispatch groups cache-compatible scenes; merge preserves storyboard order")


def test_ltx_batch_orders_fallback_scenes():
    """node_generate_ltx_batch must group non-LTX_FACEID fallback_scenes for cache
    locality before fan-out, same as the old node_dispatch_generation did."""
    scenes = [
        {"id": 1, "mode": "STANDIN", "matched_image": "img_0.png", "image_role": "ref"},
        {"id": 2, "mode": "STANDIN", "matched_image": "img_0.png", "image_role": "ref"},
        {"id": 3, "mode": "SUBJECT_REF", "matched_image": "img_1.png", "image_role": "character_ref"},
        {"id": 4, "mode": "STANDIN", "matched_image": "img_0.png", "image_role": "ref"},
    ]
    call_order = []

    async def fake_generate_one_clip(payload):
        scene = payload["scene"]
        call_order.append(scene["id"])
        return {"clip_results": [{**scene, "clip_path": f"clip{scene['id']}.mp4"}]}

    orig = nodes.node_generate_one_clip
    nodes.node_generate_one_clip = fake_generate_one_clip
    try:
        result = asyncio.run(nodes.node_generate_ltx_batch({
            "job_id": "job",
            "scenes": scenes,
            "regen_target_ids": [],
        }))
    finally:
        nodes.node_generate_one_clip = orig

    assert call_order == [1, 2, 4, 3], call_order
    assert [s["id"] for s in result["scenes"]] == [1, 2, 3, 4], result["scenes"]

    print("ok: node_generate_ltx_batch groups fallback_scenes for cache locality")


if __name__ == "__main__":
    main()
    test_ltx_batch_orders_fallback_scenes()
