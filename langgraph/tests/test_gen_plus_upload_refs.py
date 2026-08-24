"""6.22 — "얼굴 생성 + 제품 첨부" 동시 입력 회귀 테스트.

기존에는 둘이 배타였다: `graph._entry_router`가 `image_request and not ref_images`
조건이라 제품 이미지를 첨부하는 순간 M2 이미지 생성 분기가 통째로 스킵됐고,
설령 진입해도 `node_checkpoint_image_approval`이 승인 시 `ref_images`를 생성분
리스트로 **덮어써서** 첨부한 제품이 소멸했다. 파일명도 업로드분(api._save_ref_images)과
생성분이 똑같이 `img_{i}.png`라 디스크에서 서로 덮어쓴다.

이 3가지가 다시 깨지면 "얼굴은 생성하고 제품은 첨부" 시나리오가 조용히
단일 참조 job으로 퇴화한다(씬↔이미지 결정론 매칭도 같이 무력화됨).

    cd langgraph && ./.venv/bin/python tests/test_gen_plus_upload_refs.py
"""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import graph
import nodes
import tools


def test_router_enters_image_branch_even_with_uploaded_refs():
    state = {"image_request": "농구하는 남자", "ref_images": ["img_0.png"]}
    assert graph._entry_router(state) == "node_rewrite_image_query"


def test_router_image_request_only():
    assert graph._entry_router({"image_request": "x"}) == "node_rewrite_image_query"


def test_router_uploaded_refs_only():
    state = {"ref_images": ["img_0.png"], "script_text": "x"}
    assert graph._entry_router(state) == "node_parse_input"


def _approve(job_id: str, gen_src: Path, uploaded: list[str]) -> dict:
    state = {
        "job_id": job_id,
        "gen_image_paths": [str(gen_src)],
        "image_queries": ["a young korean man"],
        "ref_images": list(uploaded),
        "ref_captions": {uploaded[0]: "a plastic bottle"} if uploaded else {},
    }
    with patch.object(nodes, "interrupt", return_value={"approved": True}):
        return nodes.node_checkpoint_image_approval(state)


def test_approval_merges_generated_into_uploaded_refs():
    job_id = "test_gen_plus_upload"
    refs = tools.refs_dir(job_id)
    uploaded = refs / "img_0.png"
    uploaded.write_bytes(b"UPLOADED-PRODUCT")
    gen_src = refs.parent / "gen_src.png"
    gen_src.write_bytes(b"GENERATED-FACE")

    command = _approve(job_id, gen_src, ["img_0.png"])
    update = command.update

    assert "img_0.png" in update["ref_images"], "첨부한 제품 참조가 사라짐"
    assert len(update["ref_images"]) == 2, f"참조 2장이어야 함: {update['ref_images']}"
    generated = [n for n in update["ref_images"] if n != "img_0.png"][0]
    assert generated.startswith("gen_"), f"생성분 파일명이 업로드분과 충돌: {generated}"

    # 디스크에서도 서로 안 덮어썼는지 — 이름만 바꾸고 실제로 같은 파일을 쓰면 의미 없다.
    assert uploaded.read_bytes() == b"UPLOADED-PRODUCT", "업로드 파일이 덮어써짐"
    assert (refs / generated).read_bytes() == b"GENERATED-FACE"

    # 캡션도 병합 — 업로드분 캡션이 날아가면 nonhuman 판정이 무너진다.
    assert update["ref_captions"]["img_0.png"] == "a plastic bottle"
    assert update["ref_captions"][generated] == "a young korean man"


def test_approval_without_uploaded_refs_still_works():
    job_id = "test_gen_only"
    gen_src = tools.refs_dir(job_id).parent / "gen_src.png"
    gen_src.write_bytes(b"GENERATED-FACE")

    update = _approve(job_id, gen_src, []).update
    assert len(update["ref_images"]) == 1
    assert update["ref_images"][0].startswith("gen_")


def test_wardrobe_lock_addresses_both_prefixes():
    """생성분이 gen_N으로 바뀌었어도 사용자가 이름으로 의상 락을 걸 수 있어야 한다."""
    script = "gen_0 의상: 흰 반팔 티셔츠\nimg_0 의상: 파란 라벨 패트병"
    locks = nodes.extract_wardrobe_locks(script, ["gen_0.png", "img_0.png"])
    assert locks["gen_0.png"] == "흰 반팔 티셔츠"
    assert locks["img_0.png"] == "파란 라벨 패트병"


if __name__ == "__main__":
    test_router_enters_image_branch_even_with_uploaded_refs()
    test_router_image_request_only()
    test_router_uploaded_refs_only()
    test_approval_merges_generated_into_uploaded_refs()
    test_approval_without_uploaded_refs_still_works()
    test_wardrobe_lock_addresses_both_prefixes()
    print("test_gen_plus_upload_refs: all passed")
