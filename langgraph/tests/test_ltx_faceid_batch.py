"""Task 5.3: 네 Face-ID 씬을 단일 LTX batch 호출로 생성하는 계약 (2026-07-31 재설계:
Flux 앵커 lock 제거, 3.2와 동일한 base 워크플로 배선 사용)."""
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import nodes
import tools


def _scenes():
    return [
        {
            "id": i,
            "text": text,
            "prompt": f"astronaut scene {i}",
            "duration": 3.0,
            "mode": "LTX_FACEID",
            "face_id_ref": "astronaut.png",
            "matched_image": "astronaut.png",
            "image_role": "ref",
            "subject_type": "human",
        }
        for i, text in enumerate(("발사", "우주유영", "외계행성", "귀환"), 1)
    ]


async def _run():
    batch = AsyncMock(return_value={
        i: f"/jobs/s1/clip{i}.mp4" for i in range(1, 5)
    })
    with patch("tools.generate_ltx_faceid_batch", new=batch):
        result = await nodes.node_generate_ltx_batch({
            "job_id": "s1",
            "scenes": _scenes(),
            "regen_target_ids": [],
        })

    assert batch.await_count == 1, "씬별 호출로 회귀하면 모델을 반복 로드한다"
    payload = batch.await_args.args[1]
    assert len(payload) == 4
    assert all(scene["face_id_ref"] == "astronaut.png" for scene in payload)
    assert "anchor_image" not in payload[0], "앵커 필드는 더 이상 존재하면 안 됨"
    assert [scene["clip_path"] for scene in result["scenes"]] == [
        f"/jobs/s1/clip{i}.mp4" for i in range(1, 5)
    ]
    assert all(scene["mode"] == "LTX_FACEID" for scene in result["scenes"])
    assert all(scene["steps"] == tools.LTX_FACEID_STEPS for scene in result["scenes"])


if __name__ == "__main__":
    graph = tools._build_ltx_faceid_graph(
        prompt="wide astronaut shot",
        face_image="astronaut.png",
        duration=3.0,
        seed=123,
        prefix="job_ltx_1",
    )
    assert graph["100"]["inputs"]["width"] == 1024
    assert graph["100"]["inputs"]["height"] == 576
    assert graph["104"]["inputs"]["image"] == "astronaut.png"
    assert "130" not in graph, "Flux 앵커 LoadImage 노드는 더 이상 존재하면 안 됨"
    assert "131" not in graph, "LTXVImgToVideo 앵커 lock 노드는 더 이상 존재하면 안 됨"
    assert graph["117"]["inputs"]["video_latent"] == ["100", 0], (
        "117은 base 워크플로 원본 배선(EmptyLTXVLatentVideo)을 그대로 써야 한다"
    )
    assert graph["129"]["inputs"]["positive"] == ["83", 0]
    assert graph["129"]["inputs"]["negative"] == ["83", 1]
    assert graph["102"]["inputs"]["value"].startswith("ref_t2v:")
    assert graph["101"]["inputs"]["filename_prefix"] == "job_ltx_1"
    assert "audio" not in graph["56"]["inputs"]
    batch_graph, outputs = tools._build_ltx_faceid_batch_graph(
        [{**scene, "seed": scene["id"]} for scene in _scenes()],
        {"astronaut.png": "uploaded_astronaut.png"},
    )
    assert len([n for n in batch_graph.values() if n["class_type"] == "LoaderGGUF"]) == 1
    assert len([n for n in batch_graph.values() if n["class_type"] == "DualCLIPLoader"]) == 1
    assert len([
        n for n in batch_graph.values()
        if n["class_type"] == "LoraLoaderModelOnly"
    ]) == 2
    assert len([n for n in batch_graph.values() if n["class_type"] == "SamplerCustomAdvanced"]) == 4
    assert len([n for n in batch_graph.values() if n["class_type"] == "LTXVImgToVideo"]) == 0, (
        "앵커 lock 제거 후엔 이 노드 타입이 그래프에 전혀 없어야 한다"
    )
    assert len(outputs) == 4
    asyncio.run(_run())
    print("ok: four scenes use one anchor-free LTX Face-ID batch submission")
