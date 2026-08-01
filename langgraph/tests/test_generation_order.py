"""Generation dispatch should group cache-compatible scenes without changing video order.

Success criteria:
- STANDIN scenes with the same reference image are dispatched consecutively, even if a
  different mode sits between them in storyboard order.
- Fan-in merge keeps the original scene order for final approval/editing.
- node_dispatch_generation filters out LTX_FACEID-mode scenes (those are already generated
  as one atomic batch by node_generate_ltx_batch — dispatching them again would duplicate
  generation) and still applies cache-locality ordering to the remaining scenes.
- node_dispatch_generation returns the literal string "node_checkpoint_clip_approval" when
  every scene is LTX_FACEID (nothing left to fan out) since Send-based conditional edges
  need a valid alternate destination when there's no fan-out to do.

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
    # regen must use a fresh random seed (seed=None) + force_new=True, not the
    # deterministic scene_seed() used for a first-pass generation.
    assert all(s.arg["seed"] is None and s.arg["force_new"] for s in regen_sends), regen_sends

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


def test_dispatch_excludes_ltx_faceid_scenes():
    """node_dispatch_generation must filter out LTX_FACEID-mode scenes (already generated
    by node_generate_ltx_batch's atomic batch submission) while still applying
    cache-locality ordering to the remaining non-LTX_FACEID scenes."""
    scenes = [
        {"id": 1, "mode": "STANDIN", "matched_image": "img_0.png", "image_role": "ref"},
        {"id": 2, "mode": "STANDIN", "matched_image": "img_0.png", "image_role": "ref"},
        {"id": 3, "mode": "SUBJECT_REF", "matched_image": "img_1.png", "image_role": "character_ref"},
        {"id": 4, "mode": "STANDIN", "matched_image": "img_0.png", "image_role": "ref"},
        {"id": 5, "mode": "LTX_FACEID", "matched_image": "img_2.png", "image_role": "start"},
    ]

    sends = nodes.node_dispatch_generation({"job_id": "job", "scenes": scenes})
    assert _ids(sends) == [1, 2, 4, 3], _ids(sends)

    print("ok: node_dispatch_generation excludes LTX_FACEID scenes, keeps cache-locality order")


def test_dispatch_all_ltx_faceid_routes_to_checkpoint():
    """When every scene is LTX_FACEID (nothing left to fan out), node_dispatch_generation
    must return the literal string destination, not an empty Send list."""
    scenes = [
        {"id": 1, "mode": "LTX_FACEID", "matched_image": "img_0.png", "image_role": "start"},
        {"id": 2, "mode": "LTX_FACEID", "matched_image": "img_0.png", "image_role": "start"},
    ]
    result = nodes.node_dispatch_generation({"job_id": "job", "scenes": scenes})
    assert result == "node_checkpoint_clip_approval", result

    print("ok: node_dispatch_generation routes straight to checkpoint when all scenes are LTX_FACEID")


if __name__ == "__main__":
    main()
    test_dispatch_excludes_ltx_faceid_scenes()
    test_dispatch_all_ltx_faceid_routes_to_checkpoint()
