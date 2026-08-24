"""1-4 승인 게이트가 제품 씬 라우팅을 뒤집지 않는지 회귀 테스트.

2026-08-13 UI E2E job 1a0d85b1 실측: 씬분할 시점에는 배정이 정확했는데
(씬2·3 = subject_type:human / role:character_ref / face_id_ref:인물), 승인 게이트를
통과하면서 `_normalise_image_role`이 "human이면 role은 ref"라는 옛 규약으로
character_ref를 ref로 되돌렸다. 그 결과 node_classify_faceid_scenes가
**제품 사진을 얼굴 참조로** 잡아 Face-ID가 매 씬 다른 사람(양복 입은 남자)을 그렸다.

인물+제품 광고의 제품 씬은 subject_type=human(주인공은 사람) + role=character_ref
(참조는 제품)라는 조합을 쓴다. 이 조합이 승인 게이트를 무사히 통과해야 한다.

    cd langgraph && ./.venv/bin/python tests/test_scene_approval_preserves_routing.py
"""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import nodes

PERSON, PRODUCT = "gen_0.png", "img_0.png"


def _approved_scenes(scenes: list[dict]) -> list[dict]:
    state = {"scenes": scenes, "ref_images": [PERSON, PRODUCT]}
    with patch.object(nodes, "interrupt", return_value={"approved": True}):
        return nodes.node_checkpoint_scene_approval(state).update["scenes"]


def test_product_scene_role_survives_approval():
    scenes = [{
        "id": 2, "text": "그는 음료수를 향해 달려간다.", "matched_image": PRODUCT,
        "image_role": "character_ref", "subject_type": "human", "face_id_ref": PERSON,
    }]
    out = _approved_scenes(scenes)
    assert out[0]["image_role"] == "character_ref", \
        f"승인 게이트가 제품 씬 role을 뒤집음: {out[0]['image_role']}"
    assert out[0]["face_id_ref"] == PERSON


def test_classify_after_approval_keeps_person_as_face_ref():
    """승인 게이트 → classify 순서로 흘려도 제품 사진이 얼굴 참조가 되면 안 된다."""
    scenes = [{
        "id": 2, "text": "그는 음료수를 향해 달려간다.", "matched_image": PRODUCT,
        "image_role": "character_ref", "subject_type": "human", "face_id_ref": PERSON,
        "mode": "PRODUCT_ASSEMBLY",
    }]
    approved = _approved_scenes(scenes)
    classified = nodes.node_classify_faceid_scenes({"scenes": approved})["scenes"]
    assert classified[0]["face_id_ref"] == PERSON, \
        f"제품 사진이 얼굴 참조로 잡힘: {classified[0]['face_id_ref']}"
    assert classified[0]["mode"] != "LTX_FACEID", "제품 씬이 Face-ID 배치로 샜다"


def test_plain_person_scene_still_normalises_to_ref():
    """인물 참조가 붙은 일반 씬은 기존대로 ref로 정규화돼야 한다(회귀 방지)."""
    scenes = [{
        "id": 1, "text": "한 남자가 농구를 한다.", "matched_image": PERSON,
        "image_role": None, "subject_type": "human",
    }]
    assert _approved_scenes(scenes)[0]["image_role"] == "ref"


def test_missing_reference_downgrades_to_t2v():
    scenes = [{
        "id": 1, "text": "x", "matched_image": "nope.png",
        "image_role": "ref", "subject_type": "human",
    }]
    out = _approved_scenes(scenes)
    assert out[0]["matched_image"] is None and out[0]["image_role"] is None


if __name__ == "__main__":
    test_product_scene_role_survives_approval()
    test_classify_after_approval_keeps_person_as_face_ref()
    test_plain_person_scene_still_normalises_to_ref()
    test_missing_reference_downgrades_to_t2v()
    print("test_scene_approval_preserves_routing: all passed")
