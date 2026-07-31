"""Task 5.2 (2026-07-31 재설계): LTX_FACEID 모드 분류 계약.

원래 이 노드(`node_generate_scene_anchors`)는 Flux로 씬별 배경 앵커를
생성했으나, 앵커가 얼굴 참조를 받지 않아 identity가 무작위였고 그 앵커를
LTXVImgToVideo가 강도 1.0으로 고정해 Face-ID를 무력화시켰다(실사용 재현
검증, 2026-07-31). 배경 다양성은 3.2에서 이미 프롬프트 텍스트만으로
증명됐으므로 앵커를 완전히 제거하고, 이 노드는 사람 참조 유무로 씬의
`mode`/`face_id_ref`만 분류한다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import nodes


def _run():
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
    result = nodes.node_classify_faceid_scenes({
        "job_id": "s1-astronaut",
        "scenes": scenes,
    })

    classified = result["scenes"]
    assert result["phase"] == "anchoring"
    assert len(classified) == 4
    assert all("anchor_image" not in scene for scene in classified), (
        "앵커 필드는 더 이상 생성되면 안 됨"
    )
    assert all(scene["face_id_ref"] == "astronaut.png" for scene in classified)
    assert all(scene["mode"] == "LTX_FACEID" for scene in classified)

    nonhuman = {
        **scenes[0],
        "subject_type": "nonhuman",
        "image_role": "character_ref",
    }
    guarded = nodes.node_classify_faceid_scenes({
        "job_id": "guard",
        "scenes": [nonhuman],
    })
    assert guarded["scenes"][0]["face_id_ref"] is None
    assert guarded["scenes"][0]["mode"] == "T2V"


if __name__ == "__main__":
    _run()
    print("ok: scenes classify into LTX_FACEID/T2V without a Flux anchor call")
