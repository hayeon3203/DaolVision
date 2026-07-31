"""Task 5.2: 씬별 Flux 앵커와 사람 Face-ID 참조 전달 계약."""
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import nodes


async def _run():
    scenes = [
        {
            "id": i,
            "text": text,
            "prompt": f"scene {i} prompt",
            "subject_type": "human",
            "matched_image": "astronaut.png",
            "image_role": "ref",
        }
        for i, text in enumerate(("발사", "우주유영", "외계행성", "귀환"), 1)
    ]
    generate = AsyncMock(
        side_effect=lambda job_id, scene_id, prompt, seed=None:
        f"/jobs/{job_id}/anchor_scene_{scene_id}.png"
    )
    with patch("tools.generate_scene_anchor", new=generate):
        result = await nodes.node_generate_scene_anchors({
            "job_id": "s1-astronaut",
            "scenes": scenes,
        })

    anchored = result["scenes"]
    assert result["phase"] == "anchoring"
    assert len(anchored) == 4
    assert generate.await_count == 4
    assert [scene["anchor_image"] for scene in anchored] == [
        f"/jobs/s1-astronaut/anchor_scene_{i}.png" for i in range(1, 5)
    ]
    assert all(scene["face_id_ref"] == "astronaut.png" for scene in anchored)
    assert [call.kwargs["prompt"] for call in generate.await_args_list] == [
        f"scene {i} prompt" for i in range(1, 5)
    ]

    nonhuman = {
        **scenes[0],
        "subject_type": "nonhuman",
        "image_role": "character_ref",
    }
    with patch("tools.generate_scene_anchor", new=AsyncMock(return_value="/tmp/anchor.png")):
        guarded = await nodes.node_generate_scene_anchors({
            "job_id": "guard",
            "scenes": [nonhuman],
        })
    assert guarded["scenes"][0]["face_id_ref"] is None


if __name__ == "__main__":
    asyncio.run(_run())
    print("ok: four Flux anchors carry the astronaut Face-ID reference separately")
