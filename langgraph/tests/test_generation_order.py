"""Generation dispatch should group cache-compatible scenes without changing video order.

Success criteria:
- STANDIN scenes with the same reference image are dispatched consecutively, even if a
  different mode sits between them in storyboard order.
- Fan-in merge keeps the original scene order for final approval/editing.

Run:
  ./.venv/bin/python tests/test_generation_order.py
"""
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


if __name__ == "__main__":
    main()
