"""Face-ID 정원 + 놓인 씬 카메라 고정 회귀 테스트 (2026-08-14).

배경: LTX 2.3 22B(GGUF Q6_K)는 Face-ID 씬이 2개가 되는 순간 재양자화로 10~40분
정체한다. 그래서 첫 씬만 22B에 남기고 나머지 인물 씬은 조립 경로(PERSON_ASSEMBLY)로
내린다. 그리고 놓인 제품 씬은 카메라를 고정해야 한다 — 합성 제품이 배경 픽셀에 박혀
있어 카메라가 움직이면 놓인 면과 함께 통째로 흔들렸다(clip2 실측).

    cd langgraph && ./.venv/bin/python tests/test_faceid_cap_and_camera_lock.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import nodes
import tools

SCENE2_CAMERA = (
    "A wide shot, low angle captures a young man sprinting across the court; "
    "his hands outstretched, he gestures with an open palm; the camera slowly "
    "tracks his movement horizontally, following his arc through the space with "
    "smooth, natural motion"
)


def _person_scene(sid: int) -> dict:
    """인물 참조가 붙은 씬 — 분류기가 LTX_FACEID로 올리는 형태."""
    return {"id": sid, "matched_image": "gen_0.png", "subject_type": "human",
            "image_role": "ref", "mode": "STANDIN"}


def test_first_person_scene_keeps_faceid_rest_demoted():
    scenes = [_person_scene(1), _person_scene(4), _person_scene(6)]
    out = nodes.node_classify_faceid_scenes({"scenes": scenes})["scenes"]
    assert [s["mode"] for s in out] == ["LTX_FACEID", "PERSON_ASSEMBLY", "PERSON_ASSEMBLY"]
    # 내려간 씬도 얼굴 참조는 그대로 들고 간다 — 조립 배경 프롬프트가 캡션을 쓴다.
    assert all(s["face_id_ref"] == "gen_0.png" for s in out)


def test_product_assembly_scenes_are_not_counted_or_touched():
    """제품 씬은 22B를 안 쓴다 — 정원에 들어가서도, 강등돼서도 안 된다."""
    scenes = [
        {"id": 2, "matched_image": "img_0.png", "subject_type": "human",
         "image_role": "character_ref", "mode": "PRODUCT_ASSEMBLY", "face_id_ref": "gen_0.png"},
        _person_scene(4),
    ]
    out = nodes.node_classify_faceid_scenes({"scenes": scenes})["scenes"]
    assert out[0]["mode"] == "PRODUCT_ASSEMBLY"
    assert out[1]["mode"] == "LTX_FACEID", "제품 씬이 정원을 잡아먹었다"


def test_camera_motion_clause_removed_and_locked():
    locked = tools._lock_camera(SCENE2_CAMERA)
    assert "camera slowly tracks" not in locked
    assert "following his arc" not in locked, "카메라 절의 이어지는 분사구가 남았다"
    assert tools.STATIC_CAMERA_CLAUSE in locked
    # 인물 동작은 살아 있어야 한다 — 카메라만 빼는 것이지 씬을 정지시키는 게 아니다.
    assert "sprinting across the court" in locked
    assert "open palm" in locked


def test_camera_lock_is_noop_on_prompt_without_camera():
    plain = "A young man drinks from the bottle and smiles"
    locked = tools._lock_camera(plain)
    assert locked.startswith(plain)
    assert tools.STATIC_CAMERA_CLAUSE in locked


def test_placed_ratios_sit_on_the_lower_center_surface():
    """T2I가 놓일 면을 그리는 실측 영역(x 0.32~0.68, y 0.86~1.0) 안에 있어야 한다."""
    width, center_x, bottom_y = tools.PRODUCT_PLACED_RATIOS
    assert 0.32 < center_x < 0.68, center_x
    assert bottom_y >= 0.95, bottom_y
    assert width > 0.10, "0.075는 폭 95px짜리 소품이었다"


def test_held_product_width_follows_face():
    """쥔 제품 폭 = 얼굴 폭 × 0.50(스파이크 실측 139/276)."""
    assert 0.4 < tools.PRODUCT_FACE_RATIO < 0.6
    face_w_ratio = 276 / 1392
    assert abs(tools.PRODUCT_FACE_RATIO * face_w_ratio - 139 / 1392) < 0.01


def _run_assembly(job_id, scene_id, **kwargs):
    """조립 경로를 GPU 없이 돌린다 — 배경(Kontext/T2I)과 I2V만 가짜로 바꾼다."""
    import asyncio
    from io import BytesIO

    from PIL import Image

    seen = {}

    def _png():
        buf = BytesIO()
        Image.new("RGB", (128, 72), (10, 20, 30)).save(buf, "PNG")
        return buf.getvalue()

    async def fake_kontext(image_bytes, *, prompt, **kw):
        seen["bg_prompt"] = prompt
        seen["bg_via"] = "kontext"
        return _png()

    async def fake_t2i(jid, prompt, seed=None, index=0):
        seen["bg_prompt"] = prompt
        seen["bg_via"] = "t2i"
        path = tools.job_dir(jid) / f"t2i_{index}.png"
        path.write_bytes(_png())
        return str(path)

    async def fake_i2v(**kw):
        seen["i2v"] = kw
        return f"clip{scene_id}.mp4"

    def boom(*a, **k):
        raise AssertionError("제품이 없는 씬인데 제품 합성이 호출됐다")

    orig = (tools.run_flux_kontext, tools.generate_t2i_image,
            tools.generate_i2v_fallback_clip, tools.compose_product_frame)
    tools.run_flux_kontext, tools.generate_t2i_image = fake_kontext, fake_t2i
    tools.generate_i2v_fallback_clip, tools.compose_product_frame = fake_i2v, boom
    try:
        seen["clip"] = asyncio.run(
            tools.generate_product_scene_clip(job_id, scene_id, **kwargs))
    finally:
        (tools.run_flux_kontext, tools.generate_t2i_image,
         tools.generate_i2v_fallback_clip, tools.compose_product_frame) = orig
    return seen


def test_person_scene_uses_kontext_rerender_not_t2i():
    """인물 씬 배경은 인물 정본 Kontext 재렌더 — T2I로 새로 그리면 매번 다른 얼굴이 된다."""
    job_id = "test_person_assembly"
    refs = tools.refs_dir(job_id)
    from PIL import Image
    Image.new("RGB", (512, 512), (200, 180, 160)).save(refs / "gen_0.png")

    seen = _run_assembly(
        job_id, 4, prompt="he sprints back into the court, seen from behind",
        product_ref=None, face_ref="gen_0.png",
        scene_context="an outdoor asphalt basketball court, golden hour",
        person_appearance="Young adult East Asian man in a white t-shirt")

    assert seen["clip"] == "clip4.mp4"
    assert seen["bg_via"] == "kontext", "인물 씬인데 T2I로 배경을 새로 그렸다"
    assert tools.PERSON_BG_IDENTITY in seen["bg_prompt"], "identity lock이 빠졌다"
    # 동작은 넣되 완료 자세로 굳지 않게 "동작 도중"을 못박아야 한다.
    assert "sprints back into the court" in seen["bg_prompt"]
    assert tools.PERSON_SCENE_FIRST_FRAME in seen["bg_prompt"]
    assert "white t-shirt" in seen["bg_prompt"], "인물 외형이 배경 프롬프트에서 빠졌다"
    # 제품이 없으면 카메라 고정도 걸지 않는다 — 인물 씬은 카메라가 움직여도 된다.
    assert tools.STATIC_CAMERA_CLAUSE not in seen["i2v"]["prompt"]
    assert (refs / "assembled_scene4.png").exists()


def test_hero_cut_still_uses_t2i():
    """히어로컷은 재렌더할 인물이 없다 — 유일하게 T2I로 배경을 그리는 경로."""
    seen = _run_assembly(
        "test_hero_assembly", 5,
        prompt="a slow push-in on the bottle standing on the bench",
        product_ref=None, face_ref=None)
    assert seen["bg_via"] == "t2i"
    assert tools.PRODUCT_HERO_FRAMING in seen["bg_prompt"]
    # 제품 명사는 지워야 한다 — 배경에 병이 그려지면 결과에 병이 둘이 된다.
    assert "bottle" not in seen["bg_prompt"].lower()


def main() -> None:
    test_first_person_scene_keeps_faceid_rest_demoted()
    test_product_assembly_scenes_are_not_counted_or_touched()
    test_camera_motion_clause_removed_and_locked()
    test_camera_lock_is_noop_on_prompt_without_camera()
    test_placed_ratios_sit_on_the_lower_center_surface()
    test_held_product_width_follows_face()
    test_person_scene_uses_kontext_rerender_not_t2i()
    test_hero_cut_still_uses_t2i()
    print("test_faceid_cap_and_camera_lock: all passed")


if __name__ == "__main__":
    main()
