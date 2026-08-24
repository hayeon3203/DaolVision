"""B노선(제품 오버레이) 라우팅과 T2V 프롬프트 정제 회귀 테스트.

A노선(조립+I2V)은 제품을 첫 프레임에 박아 LTX에 넘기는데, LTX는 조건 이미지를 첫
latent 하나(=8프레임)에만 쓰고 나머지를 denoise=1.0으로 새로 그린다 — job dd16ef56
실측에서 clip1 루마가 f0~f6 30.4로 고정이다가 f10에 157로 붕괴했고 제품이 사라졌다.
B노선은 T2V로 사람 장면을 먼저 끝내고 제품을 픽셀로 얹어 그 문제를 없앤다.

여기서 지키는 것 세 가지:
  1) 놓인 제품 씬은 B노선으로 간다.
  2) 손에 쥔 씬은 A노선에 남는다 — 제품이 손과 함께 움직여야 하므로 정적 오버레이가
     물리적으로 틀리다.
  3) B노선 T2V 프롬프트에 제품 명사가 한 글자도 남지 않는다. 남으면 T2V가 자기 나름의
     제품을 그리고 그 위에 우리 제품이 또 얹혀 화면에 둘이 된다(프로브 v1~v3 실측:
     조명 문구가 광원을 요구하자 씬마다 램프를 2개씩 그렸다). cfg=1.0이라 negative로
     지울 수 없으므로 프롬프트에서 빼는 게 유일한 수단이다.

    cd langgraph && ./.venv/bin/python tests/test_product_overlay_routing.py
"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import nodes
import tools

PRODUCT = "img_0.png"


def _scene(**over) -> dict:
    base = {
        "id": 1, "mode": "PRODUCT_ASSEMBLY", "prompt": "a woman sits on a sofa",
        "matched_image": PRODUCT, "subject_type": "human", "duration": 3.0,
        "product_hand_held": False,
    }
    base.update(over)
    return base


async def _dispatch(scene: dict):
    """node_generate_one_clip이 어느 생성 함수를 부르는지만 본다."""
    with (
        patch("tools.generate_product_overlay_clip",
              new=AsyncMock(return_value="/x/clip1.mp4")) as overlay,
        patch("tools.generate_product_scene_clip",
              new=AsyncMock(return_value="/x/clip1.mp4")) as assembly,
    ):
        await nodes.node_generate_one_clip({"scene": scene, "job_id": "t", "seed": 7})
    return overlay, assembly


async def test_placed_product_scene_takes_overlay_route():
    overlay, assembly = await _dispatch(_scene())
    assert overlay.await_count == 1, "놓인 제품 씬이 B노선으로 안 감"
    assert assembly.await_count == 0, "A노선이 같이 불렸다"
    kwargs = overlay.await_args.kwargs
    assert kwargs["product_ref"] == PRODUCT and kwargs["hero"] is False, kwargs


async def test_hero_cut_takes_overlay_route_as_hero():
    overlay, _ = await _dispatch(_scene(id=5, subject_type="product"))
    assert overlay.await_args.kwargs["hero"] is True, "히어로컷이 hero로 안 넘어감"


async def test_hand_held_scene_stays_on_assembly_route():
    overlay, assembly = await _dispatch(_scene(product_hand_held=True))
    assert assembly.await_count == 1, "쥔 씬이 A노선에 안 남음"
    assert overlay.await_count == 0, "쥔 씬이 B노선으로 샜다"


async def test_kill_switch_returns_everything_to_assembly():
    with patch.object(tools, "PRODUCT_OVERLAY_ENABLED", False):
        overlay, assembly = await _dispatch(_scene())
    assert assembly.await_count == 1 and overlay.await_count == 0, "킬스위치가 안 먹음"


def test_t2v_prompt_drops_every_product_noun():
    # node_generate_prompts가 붙이는 조명 큐를 그대로 재현한다. 서버 전역
    # AGENT_SCENE_LIGHTING 기본값에 "soft amber lamp glow"가 들어 있어(무드등 시나리오)
    # 이 문장을 안 떼면 T2V가 램프를 그린다.
    prompt = ("A woman relaxes on the sofa beside the warm glass lamp, holding a cup. "
              "Scene lighting and atmosphere: dim warm indoor evening light, soft amber "
              "lamp glow, deep soft shadows.")
    out = tools._overlay_t2v_prompt(prompt, hero=False)
    for noun in ("lamp", "cup", "bottle", "Scene lighting and atmosphere"):
        assert noun.lower() not in out.lower(), f"{noun!r}가 T2V 프롬프트에 남았다: {out}"
    assert "woman relaxes on the sofa" in out, f"인물 동작이 통째로 날아갔다: {out}"
    assert tools.PRODUCT_OVERLAY_SURFACE in out, "제품 얹을 빈 표면 지시가 없다"
    assert tools.PRODUCT_OVERLAY_LIGHT in out, "창밖 광원 지시가 없다"
    assert tools.STATIC_CAMERA_CLAUSE in out, "카메라 고정 지시가 없다"


def test_hero_prompt_forbids_people():
    out = tools._overlay_t2v_prompt("The lamp glows alone on the table.", hero=True)
    assert "no people" in out and "lamp" not in out.lower(), out


def test_camera_move_is_stripped():
    out = tools._overlay_t2v_prompt(
        "A man types, the camera slowly pushes in toward him, tracking his hands.",
        hero=False)
    assert "pushes in" not in out, f"카메라 이동이 안 지워짐: {out}"
    assert tools.STATIC_CAMERA_CLAUSE in out


# ── classify 단계 (실제로 깨졌던 곳) ────────────────────────────────
# 2026-08-23 job c87912d8: 램프 참조가 비전 캡션에서 human으로 분류돼 image_role이
# character_ref가 아닌 ref로 떨어졌고, 그래서 node_generate_prompts가 mode를
# PRODUCT_ASSEMBLY로 안 찍었다. 그 결과 node_classify_faceid_scenes가 씬1을
# LTX_FACEID로, 나머지를 PERSON_ASSEMBLY로 보내 B노선이 한 번도 안 탔다.
# 같은 시나리오가 전날(job dd16ef56)엔 nonhuman으로 분류돼 조립으로 갔었다 —
# 라우팅이 흔들리는 판정에 매달려 있었다는 뜻이다.

def _classify_state(**over) -> dict:
    st = {
        "job_id": "t",
        "ref_images": ["gen_0.png"],
        "ref_captions": {"gen_0.png": "A young woman smiling"},   # 램프를 사람으로 오분류
        "generated_ref_is_product": True,
        "scenes": [
            {"id": 1, "text": "여자가 어두운 방으로 걸어 들어온다.", "subject_type": "human",
             "matched_image": "gen_0.png", "image_role": "ref"},
            {"id": 2, "text": "남자가 책상 앞에 앉아 창밖을 본다.", "subject_type": "human",
             "matched_image": "gen_0.png", "image_role": "ref"},
            {"id": 5, "text": "빈 협탁 위에 놓인 제품에 카메라가 다가간다.",
             "subject_type": "nonhuman", "matched_image": "gen_0.png", "image_role": "ref"},
        ],
    }
    st.update(over)
    return st


def test_caption_misclassification_still_routes_to_overlay():
    out = nodes.node_classify_faceid_scenes(_classify_state())
    modes = {s["id"]: s["mode"] for s in out["scenes"]}
    assert modes == {1: "PRODUCT_OVERLAY", 2: "PRODUCT_OVERLAY", 5: "PRODUCT_OVERLAY"}, modes
    assert all(s["matched_image"] == "gen_0.png" for s in out["scenes"])


def test_no_faceid_promotion_when_overlay_active():
    out = nodes.node_classify_faceid_scenes(_classify_state())
    assert not any(s["mode"] == "LTX_FACEID" for s in out["scenes"]), \
        "Face-ID 승격이 살아 있다 — 22B GGUF 축출 정체를 다시 부른다"


def test_hand_held_scene_excluded_at_classify():
    st = _classify_state()
    st["scenes"][0]["text"] = "여자가 제품을 집어 들고 바라본다."
    out = nodes.node_classify_faceid_scenes(st)
    modes = {s["id"]: s["mode"] for s in out["scenes"]}
    assert modes[1] != "PRODUCT_OVERLAY", f"쥔 씬이 B노선으로 샜다: {modes}"
    assert modes[2] == "PRODUCT_OVERLAY", modes


def test_upload_path_falls_back_to_caption():
    # 업로드 참조에는 generated_ref_is_product가 없다 — 캡션 nonhuman 판정으로 폴백.
    st = _classify_state(generated_ref_is_product=False,
                         ref_captions={"gen_0.png": "A glass ball table lamp"})
    out = nodes.node_classify_faceid_scenes(st)
    assert all(s["mode"] == "PRODUCT_OVERLAY" for s in out["scenes"]), \
        [s["mode"] for s in out["scenes"]]


def test_person_only_job_untouched():
    # 제품 참조가 없는 job(인물 사진만)은 B노선을 타면 안 된다 — 사람 컷아웃을
    # 영상 위에 얹는 짓이 된다.
    st = _classify_state(generated_ref_is_product=False,
                         ref_captions={"gen_0.png": "A young woman smiling"})
    out = nodes.node_classify_faceid_scenes(st)
    assert not any(s["mode"] == "PRODUCT_OVERLAY" for s in out["scenes"]), \
        [s["mode"] for s in out["scenes"]]


# ── A노선 전용 준비작업을 B노선 씬에서 건너뛰는지 ──────────────────
# 2026-08-23 job 032e1827: 씬별 인물 정본(person_1~4.png) 4장을 12:23~12:35, **12분**
# 들여 뽑고 전부 버렸다. 그 정본은 A노선이 Kontext로 배경을 재렌더할 때만 쓰이는데
# B노선은 배경을 T2V가 통째로 그린다. job 전체 시간의 약 40%가 순수 낭비였다.

async def test_person_ref_t2i_skipped_on_overlay_route():
    state = {
        "job_id": "t",
        "ref_images": ["gen_0.png"],
        "ref_captions": {"gen_0.png": "A glass ball table lamp"},
        "generated_ref_is_product": True,
        "style_bible": "cinematic",
        "character_sheet": "",
        "scenes": [
            {"id": 1, "text": "여자가 어두운 방으로 걸어 들어온다.", "mood": "neutral",
             "duration": 3.0, "matched_image": "gen_0.png", "image_role": "character_ref",
             "subject_type": "human", "setting": "원룸", "lighting": "dim"},
        ],
    }
    with (
        patch("tools.call_llm", new=AsyncMock(return_value="a woman enters a dark room")),
        patch("tools.generate_t2i_image",
              new=AsyncMock(return_value="/x/gen_img_2001.png")) as t2i,
    ):
        await nodes.node_generate_prompts(state)
    assert t2i.await_count == 0, (
        f"B노선 씬인데 인물 정본 T2I를 {t2i.await_count}번 뽑았다 — 씬당 약 3분 낭비")


def test_style_is_pinned_and_leads_the_prompt():
    out = tools._overlay_t2v_prompt("A woman walks into a room.", hero=False)
    assert out.startswith(tools.PRODUCT_OVERLAY_STYLE), \
        f"고정 화풍이 맨 앞이 아니다 — T5 토큰 한도에 걸리면 뒤부터 잘린다: {out[:120]}"


async def test_style_bible_never_reaches_overlay_prompt():
    """job별 style_bible이 B노선 프롬프트에 섞이면 화풍이 3D 만화로 무너진다."""
    bible = ("Rendering Technique: Photorealism, Flat Lighting, Studio Shot. "
             "Texture Density: Low, Uniform. Environmental Detail Level: None.")
    state = {
        "job_id": "t", "ref_images": ["gen_0.png"],
        "ref_captions": {"gen_0.png": "A glass ball table lamp"},
        "generated_ref_is_product": True, "style_bible": bible, "character_sheet": "",
        "scenes": [{"id": 1, "text": "여자가 방에 들어온다.", "mood": "neutral",
                    "duration": 3.0, "matched_image": "gen_0.png",
                    "image_role": "character_ref", "subject_type": "human",
                    "setting": "원룸", "lighting": "dim"}],
    }
    with (
        patch("tools.call_llm", new=AsyncMock(return_value="a woman walks in")),
        patch("tools.generate_t2i_image", new=AsyncMock(return_value="/x/a.png")),
    ):
        out = await nodes.node_generate_prompts(state)
    prompt = out["scenes"][0]["prompt"]
    for bad in ("Flat Lighting", "Texture Density", "Environmental Detail Level",
                "Scene lighting and atmosphere"):
        assert bad not in prompt, f"{bad!r}가 B노선 프롬프트에 남았다: {prompt}"


async def test_cancel_releases_comfyui_gpu():
    """취소가 ComfyUI 모델을 안 내리면 다음 job의 FLUX가 GPU OOM으로 죽는다
    (2026-08-23 실측: 21.4GB 잔류 → NVRM Out of memory → job 통째로 실패)."""
    import api
    with (
        patch("tools.release_comfyui_gpu", new=AsyncMock()) as rel,
        patch("metrics.video_finished", new=lambda **k: None),
    ):
        res = await api.cancel_job("t-cancel")
    assert res["status"] == "cancelled"
    assert rel.await_count == 1, "취소가 ComfyUI GPU를 안 놓는다"


async def test_release_comfyui_gpu_survives_dead_comfyui():
    """ComfyUI가 내려 있어도 취소 자체는 성공해야 한다."""
    orig = tools.COMFYUI_URL
    tools.COMFYUI_URL = "http://127.0.0.1:9"      # discard 포트 — 연결 실패
    try:
        await tools.release_comfyui_gpu()          # 예외가 새면 실패
    finally:
        tools.COMFYUI_URL = orig


def test_person_scene_without_product_stays_off_overlay_route():
    """인물+제품 2참조 job에서 **제품이 화면에 없는 인물 씬**은 B노선을 타면 안 된다.

    타면 그 씬에 제품을 억지로 얹게 되고(농구 씬에 음료병) 인물 경로가 쓰던 의상
    lock도 날아간다. 2026-08-23 test_generated_wardrobe_lock 회귀로 잡혔다.
    """
    st = _classify_state(
        generated_ref_is_product=False,
        ref_images=["person.png", "bottle.png"],
        ref_captions={"person.png": "A young man", "bottle.png": "Plastic bottle"},
        scenes=[
            {"id": 1, "text": "남자가 농구장에서 달린다.", "subject_type": "human",
             "matched_image": "person.png", "image_role": "ref"},
            {"id": 2, "text": "벤치 위에 놓인 제품을 비춘다.", "subject_type": "nonhuman",
             "matched_image": "bottle.png", "image_role": "character_ref"},
        ],
    )
    modes = {sc["id"]: sc["mode"] for sc in nodes.node_classify_faceid_scenes(st)["scenes"]}
    assert modes[1] != "PRODUCT_OVERLAY", f"제품 없는 인물 씬이 B노선으로 샜다: {modes}"
    assert modes[2] == "PRODUCT_OVERLAY", f"제품 씬이 B노선을 안 탔다: {modes}"


def test_hero_detected_from_scene_text_not_subject_type():
    """히어로컷 판정이 씬분할 LLM의 subject_type에 매달리면 안 된다.

    2026-08-23: 같은 시나리오 5번째 문장이 job 032e1827에서는 nonhuman,
    job 8402186d에서는 human으로 찍혔다. 후자에서는 히어로 비율도 무인 강제도 안 걸려
    마무리 제품컷이 인물 씬과 똑같은 크기로 나왔다(레이어 파일이 바이트까지 동일).
    """
    st = _classify_state(scenes=[
        {"id": 1, "text": "여자가 어두운 방으로 걸어 들어온다.", "subject_type": "human",
         "matched_image": "gen_0.png", "image_role": "ref"},
        # LLM이 human으로 **잘못** 찍은 히어로컷 — 문장엔 사람이 없다.
        {"id": 5, "text": "빈 침실 협탁 위에 놓인 제품에 카메라가 천천히 다가간다.",
         "subject_type": "human", "matched_image": "gen_0.png", "image_role": "ref"},
    ])
    out = {sc["id"]: sc for sc in nodes.node_classify_faceid_scenes(st)["scenes"]}
    assert out[5]["product_hero"] is True, "히어로컷을 인물 씬으로 봤다"
    assert out[1]["product_hero"] is False, "인물 씬을 히어로컷으로 봤다"


async def test_hero_flag_reaches_generator():
    scene = _scene(id=5, product_hero=True, subject_type="human")
    overlay, _ = await _dispatch(scene)
    assert overlay.await_args.kwargs["hero"] is True, "product_hero가 생성기까지 안 감"


# ── 프롬프트 결함 3종 회귀 (job 8402186d에서 눈으로 잡힌 것들) ──────

def test_scene_location_is_pinned_into_prompt():
    """장소를 LLM 재작성문 하나에만 맡기면 환각이 그대로 영상이 된다.

    job 8402186d 씬2: 원문 "어두운 서재 책상 앞에 앉은 20대 남자가 노트북을 덮고"가
    setting='an indoor basketball court'로 환각돼 체육관 컷이 나왔다.
    """
    out = tools._overlay_t2v_prompt(
        "a man closes a laptop", hero=False, scene_context="a home study with a desk")
    assert "the location is a home study with a desk" in out, out


def test_setting_prefers_scene_text_over_llm():
    assert "home study" in nodes._setting_from_text("어두운 서재 책상 앞에 앉은 남자")
    assert "living room" in nodes._setting_from_text("거실 소파에 앉아 책을 넘긴다")
    assert "child" in nodes._setting_from_text("어두운 아이 방에서 이불을 여며 준다")
    # 장소 단어가 없으면 LLM 값을 건드리지 않는다
    assert nodes._setting_from_text("천천히 걸어가며 미소짓는다") is None


def test_wardrobe_and_fullbleed_clauses_present():
    """의상 지시가 없으면 '기지개' 동작에서 상반신 탈의가 나오고(씬2), full-bleed
    지시가 없으면 액자 테두리가 화면 안에 생긴다(씬4)."""
    out = tools._overlay_t2v_prompt("a man stretches his arms", hero=False)
    assert "fully dressed" in out and "covers the torso" in out, out
    assert "no border" in out, out
    hero = tools._overlay_t2v_prompt("the product sits on a table", hero=True)
    assert "no border" in hero, hero


def test_surface_is_a_foreground_tabletop_not_full_width_slab():
    """하단 전폭 슬래브는 원룸 씬을 사무실처럼 만들었고(job 8402186d 씬1), 반대로 램프를
    맨 아래에 박으면 받침 면이 안 보여 떠 보였다(job 239b1d15). 전경 상판 윗면이 보여야
    한다."""
    surf = tools.PRODUCT_OVERLAY_SURFACE
    assert "lower-right foreground" in surf and "top surface" in surf
    assert "full width" not in surf


def test_lamp_raised_off_frame_bottom():
    """램프 바닥이 프레임 맨 아래(>0.9)면 받치는 면이 잘려 떠 보인다."""
    assert tools.PRODUCT_OVERLAY_BOTTOM_Y <= 0.88


def test_body_exposure_phrases_are_stripped():
    """재작성 LLM의 노출 표현이 의상 지시를 이긴다 — 프롬프트에서 빼야 한다.

    job 1fd34d0a 씬2: "everyone fully dressed ... covers the torso"를 넣었는데도
    재작성문이 "opening his chest" / "his open chest"를 두 번 써서 상반신 탈의가 나왔다.
    """
    out = tools._overlay_t2v_prompt(
        "he stretches, a relaxed gesture opening his chest, lingering on his open chest "
        "and focused eyes", hero=False)
    for bad in ("open chest", "opening his chest", "shirtless", "bare chest"):
        assert bad not in out.lower(), f"{bad!r}가 남았다: {out}"
    assert "fully dressed" in out and "stretches" in out, out


def test_location_recovered_from_original_script_sentence():
    """씬분할이 장소 수식구를 잘라내도 사용자 원문에서 되찾아야 한다.

    job 1fd34d0a: 사용자 원문 "어두운 서재 책상 앞에 앉은 20대 남자가 노트북을 덮고
    기지개를 켜며 창밖을 본다"에서 씬분할이 "어두운 서재 책상 앞에 앉은"을 잘라냈고,
    setting LLM의 농구장 환각이 그대로 영상이 됐다.
    """
    state = {
        "script_text": ("여자가 원룸으로 걸어 들어온다. "
                        "어두운 서재 책상 앞에 앉은 남자가 노트북을 덮는다."),
        "scenes": [{"id": 1, "text": "여자가 걸어 들어온다."},
                   {"id": 2, "text": "남자가 노트북을 덮는다."}],   # 장소가 잘려나감
    }
    assert nodes._script_sentence_for_scene(state, 1).startswith("어두운 서재"), \
        nodes._script_sentence_for_scene(state, 1)
    assert "home study" in nodes._setting_from_text(
        nodes._script_sentence_for_scene(state, 1))
    # 문장 수와 씬 수가 다르면 짝이 틀릴 수 있으므로 포기한다
    state["scenes"] = state["scenes"][:1]
    assert nodes._script_sentence_for_scene(state, 0) == ""


def test_placed_product_ignores_unrelated_hand_action():
    """놓는 제품(램프) job에서 무관한 손동작('노트북을 들고')이 씬을 A노선으로 튕기면
    안 된다. 2026-08-23 job f967a473: 씬분할이 "노트북을 들고"를 지어냈고 그게
    _HAND_ACTION_TEXT에 걸려 가족 소파 씬이 옛 조립 경로로 갔다.
    """
    st = _classify_state(
        generated_ref_is_product=True,
        image_request="따뜻한 앰버빛 유리구 무드등, 월넛 받침",
        scenes=[
            {"id": 1, "text": "20대 남자가 노트북을 들고 서재 책상에 앉아 있다.",
             "subject_type": "human", "matched_image": "gen_0.png", "image_role": "ref"},
        ],
    )
    out = nodes.node_classify_faceid_scenes(st)["scenes"]
    assert out[0]["mode"] == "PRODUCT_OVERLAY", f"놓는 제품인데 손동작에 튕김: {out[0]['mode']}"


def test_holding_the_product_still_routes_to_assembly():
    """제품 자체를 드는 씬은 A노선에 남는다(정적 오버레이가 물리적으로 틀림)."""
    st = _classify_state(
        generated_ref_is_product=True,
        image_request="시원한 탄산음료 캔",
        scenes=[
            {"id": 1, "text": "남자가 음료를 집어 든다.", "subject_type": "human",
             "matched_image": "gen_0.png", "image_role": "ref"},
        ],
    )
    out = nodes.node_classify_faceid_scenes(st)["scenes"]
    assert out[0]["mode"] != "PRODUCT_OVERLAY", "제품 쥔 씬이 오버레이로 샜다"


def test_holds_product_object_detection():
    hp = nodes._scene_holds_product
    # 놓는 제품(beverage=False): 제품 목적어일 때만 든 것.
    assert hp("여자가 제품을 들고 바라본다") is True
    assert hp("남자가 노트북을 들고 책상에 앉아 있다") is False   # 노트북 = 제품 아님
    assert hp("여자가 책을 읽으며 넘긴다") is False
    assert hp("가족이 소파에 앉아 쉰다") is False
    # 음료 제품(beverage=True): 아무 손동작이나 제품 듦. 영어 "holds it"도 포함.
    assert hp("남자가 음료수를 집어 든다", beverage=True) is True
    assert hp("A woman holds it and takes a slow sip.", beverage=True) is True
    assert hp("남자가 노트북을 들고 앉아 있다", beverage=True) is True  # 음료 job이면 손동작=듦


def test_product_beverage_detection():
    assert nodes._product_is_beverage({"image_request": "시원한 콜라 병"}) is True
    assert nodes._product_is_beverage({"image_request": "유리구 무드등, 월넛 받침"}) is False
    assert nodes._product_is_beverage({"ref_captions": {"x": "A soda can"}}) is True


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            asyncio.run(fn()) if asyncio.iscoroutinefunction(fn) else fn()
            print(f"  ok {name}")
    print("test_product_overlay_routing ok")
