"""
Phase 1~5 노드 구현
- interrupt(): 사람 승인이 필요한 2개 체크포인트 (1-4, 3-5). 4-5 자막편집 게이트는 제외.
- Send: 씬별 클립 생성을 fan-out으로 병렬 처리
- Command(goto=...): 사람이 승인/재생성/반려를 선택한 뒤 그래프 흐름을 분기
"""
import asyncio
import hashlib
import json
import os
import re
import shutil
import time
import uuid

from langgraph.types import interrupt, Command, Send, Overwrite
from langgraph.graph import END

from state import GraphState, Scene
import tools
import metrics


# ══════════════════════════════════════════════════════════
# Phase 1. 입력 수집 & 스토리 기획
# ══════════════════════════════════════════════════════════

_IMG_QUERY_SYSTEM = (
    "You rewrite a user's free-form image request (any language) into a single prompt for a "
    "text-to-image generator. Even if the user describes multiple things, distill it into one "
    "image request that captures the main subject, composition, and lighting. "
    "The target model (FLUX.1-schnell, 4-step distilled) follows vague framing words like "
    "'wide shot' or 'face clearly visible' poorly and defaults to an extreme close-up — a single "
    "technical term like '24mm lens' or 'full-body shot' is NOT enough on its own (verified by "
    "A/B render test, 2026-08-03: it still produced a head-and-shoulders medium shot). It only "
    "reliably goes wide when the scale is stated redundantly, in plain descriptive terms, at "
    "least three ways: (1) the subject 'stands/is small within the frame', (2) a concrete camera "
    "distance like 'several meters from camera', and (3) the background described as vast/tall/ "
    "expansive 'stretching far into the background'. So whenever the user's request implies "
    "anything other than a tight close-up (e.g. wide, full-body, standing, from a distance, "
    "establishing shot), include all three of those redundant scale cues plus the body being "
    "fully visible head-to-toe/head-to-boots and a named wide-angle lens. Never mention the face, "
    "eyes, or 'head to shoulders' at all in a wide/full-body shot, even if the user asked for "
    "the face to be visible — any face-emphasis or shoulders-up wording biases the model back "
    "toward a close-up and contradicts the full-body framing. State only that the subject faces "
    "the camera; the face will read as visible once the whole body is in frame. Only describe "
    "the face/eyes in detail if the user explicitly asks for a close-up or portrait, in which "
    "case skip all the wide-shot phrasing above entirely. "
    "Write ONE well-formed, properly punctuated sentence (or comma-joined clauses) — never a "
    "bare run-on list of phrases with no commas or periods. A run-on with the scale cues just "
    "mashed together (verified by A/B test, 2026-08-03: 'stands wide in the frame his "
    "head-to-boots he is small within the frame several meters from camera the background "
    "stretches far into the background') reliably fails and regresses to a close-up, while the "
    "same content as a clean punctuated sentence ('stands small within the frame, several "
    "meters from camera, entire body visible head-to-boots, inside a vast dim space stretching "
    "far into the background') reliably produces the correct wide shot. Match the second style. "
    "Output a JSON array with exactly one object: [{\"query\": \"<prompt>\"}]. "
    "If the subject is a person or character, default to a photorealistic, cinematic "
    "live-action style unless the user explicitly asks for an anime, illustrated, or "
    "stylized look. "
    "Output only the JSON array — no preamble, quotes, or markdown."
)


# 인물/제품 전용 규칙 — 이 파이프라인에서 생성 이미지의 용도는 사실상 둘뿐이고, 둘 다
# 위의 범용(와이드샷 강조) 규칙과 정면으로 충돌한다.
#
# 실측(2026-08-13 E2E job f11798c7): "20대 한국인 남자, 짧은 검은 머리, 흰 반팔 티셔츠,
# 정면 얼굴" 요청에 범용 규칙이 걸려 "standing small within the frame several meters
# from camera ... vast dim space stretching far into the background"가 나왔다. 캡션이
# "dark indoor corridor"였고 얼굴은 Face-ID 참조로 못 쓸 크기였다. "흰 반팔 티셔츠"가
# 상반신을 암시해 "tight close-up이 아니다"로 분류되고, 그 다음 _strip_face_emphasis_if_wide가
# 설계대로 "정면 얼굴" 요구를 지운 결과다.
#
# 두 프롬프트는 음료 광고 스파이크에서 실제로 쓸 만한 자산을 만들어낸 문구를 옮긴 것이다
# (tests/probe_bev_ad_assets.py PERSON_PROMPT, assets_v2.py BOTTLE_PROMPT).
_IMG_QUERY_PERSON_SYSTEM = (
    "You rewrite a user's free-form request for an image of a PERSON (any language) into a "
    "single prompt for a text-to-image generator (FLUX.1-schnell). The resulting image is used "
    "as a face identity reference for video generation, so it must be a portrait: head and "
    "shoulders, the face large and sharp in the frame, subject facing the camera directly, "
    "neutral friendly expression, plain uncluttered background, natural soft even lighting, "
    "photorealistic. Keep every appearance detail the user gave (age, gender, hair, clothing). "
    # 2026-08-13 실측: "흰 반팔 티셔츠"(short-sleeve)를 "white sleeveless T-shirt"로 뒤집어
    # 번역했다. 소매 길이는 이후 전 씬의 의상 일관성 기준이 되므로 한 번 틀리면 광고
    # 전체가 어긋난다. 대표적인 오역 쌍을 직접 못박는다.
    "Translate garment terms literally and exactly: Korean 반팔 means short-sleeve (it does "
    "NOT mean sleeveless), 긴팔 means long-sleeve, 민소매/나시 means sleeveless. Keep the "
    "sleeve length the user asked for. "
    "Never place the subject far from the camera, never describe a full-body or wide shot, and "
    "never describe an elaborate environment — those shrink the face until it is useless as an "
    "identity reference. Write ONE well-formed, properly punctuated sentence. "
    "Output a JSON array with exactly one object: [{\"query\": \"<prompt>\"}]. "
    "Output only the JSON array — no preamble, quotes, or markdown."
)
_IMG_QUERY_PRODUCT_SYSTEM = (
    "You rewrite a user's free-form request for an image of an OBJECT or PRODUCT (any language) "
    "into a single prompt for a text-to-image generator (FLUX.1-schnell). The resulting image is "
    "cut out and composited into video frames, so it must be a studio product photograph: one "
    "single object, standing upright, centered, filling most of the frame, on a pure white "
    "seamless background, flat even omnidirectional studio lighting with no strong directional "
    "key light and no heavy highlight or shadow favouring either side, photorealistic. "
    "Keep every design detail the user gave (colors, shape, label, material). Invent a brand name "
    "and mark if the user asks for one, but never reproduce a real-world brand name or logo. "
    "Never describe a scene, an environment, hands holding the object, or people. "
    "Write ONE well-formed, properly punctuated sentence. "
    "Output a JSON array with exactly one object: [{\"query\": \"<prompt>\"}]. "
    "Output only the JSON array — no preamble, quotes, or markdown."
)


_WIDE_SHOT_SIGNAL = re.compile(
    r"\b(full[- ]body|head[- ]to[- ](boots|toe|feet)|wide[- ]angle|wide shot|establishing shot)\b",
    re.I,
)
_FACE_EMPHASIS_PHRASE = re.compile(
    r",?\s*\b(with\s+)?(his\s+|her\s+|their\s+|its\s+|the\s+)?face[s]?\s+(is\s+|are\s+)?(clearly\s+|fully\s+)?visible"
    r"(\s+from\s+[a-z][a-z\- ]*?(?=[,.]|$))?",
    re.I,
)


def _strip_face_emphasis_if_wide(text: str) -> str:
    """FLUX.1-schnell 실측(2026-08-03): LLM에게 'wide shot에는 얼굴 강조 문구 넣지 마라'고
    시스템 프롬프트로 지시해도 소형 로컬 LLM이 곧잘 무시하고 'face clearly visible'을
    끼워 넣는다 — 이 문구 하나만으로 full-body 지시가 있어도 결과 이미지가 다시
    얼빡샷(face close-up)으로 회귀함을 확인(t2i_test1 vs t2i_test2 A/B). 프롬프트
    지시만으로는 신뢰할 수 없어 wide-shot 신호가 있으면 얼굴 강조 문구를 결정적으로
    제거한다."""
    if _WIDE_SHOT_SIGNAL.search(text):
        text = _FACE_EMPHASIS_PHRASE.sub("", text)
        text = re.sub(r"\s{2,}", " ", text).strip(" ,")
    return text


# 생성 이미지 프롬프트에서 의상 구절만 뽑는다. 비전 캡션은 소매 길이 같은 세부를
# 흘린다("white sleeveless T-shirt" → 캡션은 "wearing a white t-shirt") — 그 캡션만
# 조립 배경에 넘기면 씬마다 소매가 제각각이 된다(2026-08-13 사용자 지적).
_WEARING_RE = re.compile(r"\bwearing\s+([^,.;]+)", re.I)


def _wardrobe_from_query(image_query: str) -> str:
    match = _WEARING_RE.search(image_query or "")
    return match.group(1).strip() if match else ""


def _image_query_system(request: str) -> tuple[str, bool]:
    """요청 텍스트로 생성 이미지의 역할을 가려 규칙을 고른다(LLM 호출 없음).
    반환: (system 프롬프트, 와이드샷 얼굴강조 제거를 적용할지).

    비인간을 먼저 본다 — _subject_type_from_text와 같은 우선순위다. "마스코트 캐릭터"
    처럼 사람 단어가 섞여도 제품/캐릭터 규칙이 이겨야 한다.
    """
    text = request or ""
    if _NONHUMAN_TEXT.search(text) or _PRODUCT_TEXT.search(text):
        return _IMG_QUERY_PRODUCT_SYSTEM, False
    if _HUMAN_TEXT.search(text):
        return _IMG_QUERY_PERSON_SYSTEM, False
    # 둘 다 아니면 기존 범용 규칙 — 와이드샷 강조와 얼굴강조 제거가 여기서만 유효하다.
    return _IMG_QUERY_SYSTEM, True


async def node_rewrite_image_query(state: GraphState) -> dict:
    """M2-1: 사용자 자연어 이미지 요청 → 이미지 생성용 영어 프롬프트 1개.
    node_generate_prompts와 동일한 call_llm + clean_llm_prompt 패턴 재사용.
    사용자가 명시적으로 요청한 것이므로, 파싱 실패로 조용히 빈 결과를 주는 대신
    /status의 error 필드로 재시도 안내를 노출한다(app.py except Exception → ERRORS[job_id]).
    1장 고정(이전엔 최대 3장 동시 생성 허용 — flux_server.py 동시요청 레이스(job 78f91567)
    + 콜드로드 비용이 장수만큼 배로 늘어 UX 나쁨, 1장 시나리오로 확정)."""
    request = (state.get("image_request") or "").strip()
    if not request:
        return {"image_queries": [], "image_query": ""}
    system_prompt, strip_face_emphasis = _image_query_system(request)
    raw = await tools.call_llm(system_prompt, request)
    try:
        items = tools.parse_json_lenient(raw)
    except ValueError:
        items = []
    if isinstance(items, dict):
        items = items.get("queries") or items.get("items") or []
    queries = []
    for item in items if isinstance(items, list) else []:
        q = item.get("query") if isinstance(item, dict) else item if isinstance(item, str) else None
        q = tools.clean_llm_prompt(q or "")
        if strip_face_emphasis:
            # 인물 규칙에서는 절대 적용하면 안 된다 — 얼굴 강조를 지우는 게 목적인 함수라
            # Face-ID 참조로 쓸 포트레이트에서 정확히 필요한 문구를 없앤다.
            q = _strip_face_emphasis_if_wide(q)
        if q:
            queries.append(q)
    queries = queries[:1]
    if not queries:
        raise ValueError("이미지 생성 요청을 이해하지 못했습니다. 표현을 조금 바꿔서 다시 시도해주세요.")
    # M2 전용 phase — 기존 5단계 스테퍼(planning/prompting/anchoring/generating/done)
    # 앞에 오는 별도 단계라 AgentPhaseStepper가 image_gen_used일 때만 조건부로 그린다.
    return {"image_queries": queries, "image_query": queries[0] if queries else "",
            # 제품 규칙이 선택됐다 = 이 생성 이미지는 제품이다. 라우팅이 이걸 쓴다.
            "generated_ref_is_product": system_prompt is _IMG_QUERY_PRODUCT_SYSTEM,
            "phase": "image_generating"}


async def node_generate_image(state: GraphState) -> dict:
    """M2-2/M2-5: image_queries(1개 고정) → FLUX.1-schnell(:8501)로 정지 이미지 앵커 생성.
    이전엔 Wan2.2-TI2V-5B(:8500, 이후 제거됨) 영상 파이프라인을 num_frames=1로 돌려썼는데(1장 뽑는 데 ~120s),
    전용 T2I 모델로 교체. 산출: jobs/<job_id>/gen_img_0.png.
    node_rewrite_image_query가 이미 1개로 자르지만, 방어적으로 여기서도 1개로 자른다
    (동시 다중요청이던 예전엔 flux_server.py 언로드/락 레이스로 job 78f91567 500 재현됨)."""
    queries = (state.get("image_queries") or [])[:1]
    if not queries:
        return {"gen_image_paths": [], "gen_image_path": ""}
    job_id = state["job_id"]
    seed = int(hashlib.sha1(job_id.encode()).hexdigest()[:8], 16) % (2 ** 31)
    # index를 시도 횟수로 쓴다 — 0 고정이면 재생성이 gen_img_0.png를 덮어써서 이전
    # 시도가 사라지고, 승인 게이트에서 "1차와 2차를 비교"할 수가 없다.
    history = list(state.get("gen_image_history") or [])
    attempt = len(history)
    paths = await asyncio.gather(*[
        tools.generate_t2i_image(job_id, q, seed=seed, index=attempt + i)
        for i, q in enumerate(queries)
    ])
    paths = list(paths)
    return {"gen_image_paths": paths, "gen_image_path": paths[0],
            "gen_image_history": history + paths, "phase": "image_generating"}


def node_checkpoint_image_approval(state: GraphState) -> Command:
    """checkpoint 2-3 (M2, 선택 분기): 생성 이미지(들) 승인 게이트.
    기존 2게이트(1-4/3-5) interrupt/Command 패턴 그대로 복제.
    approve → 다음 단계(기존 파이프라인 진입). 자연어 수정 → M2-1(rewrite)부터 재실행(전체 재생성)."""
    paths = state.get("gen_image_paths") or []
    queries = state.get("image_queries") or []
    decision = interrupt({
        "checkpoint": "2-3_image_approval",
        "message": "생성된 이미지를 확인하고 승인하거나 수정 요청을 입력해주세요.",
        "gen_image_paths": paths,
        "gen_image_path": paths[0] if paths else None,
        "image_queries": queries,
        "image_query": queries[0] if queries else None,
        # 이전 시도까지 함께 넘겨 프론트가 1차/2차를 나란히 비교하게 한다.
        "gen_image_history": state.get("gen_image_history") or paths,
    })
    # decision 예시: {"approved": True} / {"feedback": "더 파랗게"}
    if decision.get("approved"):
        # 승인 이미지들을 참조 이미지로 주입 → 기존 caption_image·스마트 라우팅이 그대로 받음.
        # ref_captions에 생성 시 쓴 프롬프트를 그대로 채워 넣어 — 별도 vision 캡션 호출 없이 —
        # node_split_scenes가 어떤 이미지가 어떤 씬에 어울리는지 내용 기반으로 매칭하게 한다.
        #
        # 2026-08-13(6.22): 기존 ref_images를 덮어쓰지 않고 **병합**한다. 사용자가
        # 제품 사진을 첨부하고 얼굴만 생성하는 조합에서, 덮어쓰면 첨부한 제품이 조용히
        # 사라져 단일 참조 job으로 퇴화했다. 파일명도 `img_{i}.png`에서 `gen_{i}.png`로
        # 바꾼다 — 업로드분을 api._save_ref_images가 같은 `img_{i}.png`로 저장하므로
        # 그대로 두면 디스크에서 제품 파일을 덮어쓴다.
        job_id = state["job_id"]
        ref_names = list(state.get("ref_images") or [])
        ref_captions = dict(state.get("ref_captions") or {})
        for i, p in enumerate(paths):
            name = f"gen_{i}.png"
            shutil.copyfile(p, str(tools.refs_dir(job_id) / name))
            ref_names.append(name)
            if i < len(queries):
                ref_captions[name] = queries[i]
        return Command(
            goto="node_checkpoint_scenario_input",
            update={"ref_images": ref_names, "ref_captions": ref_captions},
        )
    # 자연어 수정 텍스트를 원본 요청에 누적 → rewrite부터 재실행(N장 전체 재생성).
    # 덮어쓰면 원본 의도("잔디밭 뛰어노는")가 소실돼 프롬프트가 피드백만 따라감.
    feedback = (decision.get("feedback") or decision.get("revised_request") or "").strip()
    base = (state.get("image_request") or "").strip()
    combined = f"{base}\n추가 요청: {feedback}" if base and feedback else (feedback or base)
    return Command(
        goto="node_rewrite_image_query",
        update={"image_request": combined},
    )


def node_checkpoint_scenario_input(state: GraphState) -> Command:
    """checkpoint 2-4 (M3-1): 이미지 승인 후 시나리오 입력 게이트.
    이전엔 image_request 텍스트가 script_text로 그대로 흘러 '그 사진에 대한 시나리오'가
    자동으로 만들어졌다. 이제 승인 후 사용자가 직접 입력한 시나리오로 씬을 분할한다."""
    decision = interrupt({
        "checkpoint": "2-4_scenario_input",
        "message": "이미지가 승인되었습니다. 이 이미지로 만들 영상의 시나리오를 입력해주세요.",
        "ref_images": state.get("ref_images"),
    })
    script = (decision.get("script_text") or "").strip()
    if not script:  # 빈 입력 방어 — 같은 게이트로 되돌아가 다시 묻는다
        return Command(goto="node_checkpoint_scenario_input")
    return Command(goto="node_parse_input", update={"script_text": script})


WARDROBE_LOCK_TEMPLATE = """WARDROBE CONTINUITY LOCK:
The character must wear exactly the following outfit in every scene and frame:
{wardrobe_description}
Preserve the same garments, layers, colors, patterns, materials, fit, footwear,
and accessories. Do not change, remove, replace, or add any clothing or accessories.
Maintain wardrobe continuity across different poses, locations, lighting conditions,
camera angles, and shot sizes.
""".strip()


def extract_wardrobe_locks(script_text: str, ref_images: list[str]) -> dict[str, str]:
    """사용자가 선언한 의상만 이미지별로 추출하며 이미지 내용은 추측하지 않는다."""
    valid, current_ref, locks = set(ref_images), None, {}
    for raw_line in script_text.splitlines():
        line = raw_line.strip()
        # 업로드분은 img_N(api._save_ref_images), 생성분은 gen_N
        # (node_checkpoint_image_approval, 6.22) — 둘 다 이름으로 지목할 수 있어야 한다.
        mentions = re.findall(r"\b(img|gen)[_\s]?(\d+)(?:\.[a-z0-9]+)?", line, re.I)
        if mentions:
            prefix, number = mentions[-1]
            candidate = f"{prefix.lower()}_{int(number)}.png"
            if candidate in valid:
                current_ref = candidate
        match = re.search(
            r"(?:의상|옷)(?:은|는)?\s*[:=]?\s*(.+)$|(?:wardrobe|outfit)\s*[:=]\s*(.+)$",
            line, re.I)
        if current_ref and match:
            value = (match.group(1) or match.group(2)).strip().strip(". ")
            if value:
                locks[current_ref] = value
    return locks


async def node_parse_input(state: GraphState) -> dict:
    """1-2: 입력 파싱 + 참조 이미지 캡셔닝 (AI).
    각 이미지를 비전 모델로 캡션해 두면 씬 분할이 '파일명 추측'이 아니라 '내용'으로
    이미지를 배치할 수 있고, 인물 묘사를 프롬프트에 주입(캐릭터록)할 수 있다."""
    out: dict = {"script_text": state["script_text"].strip()}
    # 이 노드는 job당 한 번(START 직후)만 실행된다 → 영상 '시작'으로 집계.
    metrics.video_started()
    out["started_at"] = time.time()
    refs = state.get("ref_images") or []
    out["wardrobe_locks"] = extract_wardrobe_locks(out["script_text"], refs)
    if refs and tools.CAPTION_REFS:  # 캡션 OFF면 gemma 미로드; 이미지↔씬은 사람이 승인 게이트에서 지정
        captions = {}
        for fn in refs:
            try:
                captions[fn] = await tools.caption_image(str(tools.refs_dir(state["job_id"]) / fn))
            except Exception as exc:
                captions[fn] = ""   # 캡션 실패해도 파일명 기반으로 계속 진행
                # 조용히 삼키면 안 된다 — 캡션이 비는 순간 node_split_scenes의 결정론
                # 배정(인물 1장 + 제품 1장)이 통째로 탈락하고 LLM 매칭으로 강등돼
                # 전 씬에서 face_id_ref가 사라진다(2026-08-13 job f7c7b356 실측:
                # 5씬 전부 얼굴 참조 없이 제품 사진이 인물 씬 참조로 붙었다).
                # 로그가 없으면 결과물을 눈으로 보기 전까지 알 방법이 없다.
                print(f"[caption] {fn} 캡션 실패({type(exc).__name__}: {exc}) — "
                      f"씬↔참조 결정론 배정이 꺼진다")
        out["ref_captions"] = captions
    return out


# mood는 트랜지션 규칙(node_edit_concat: calm/sad → crossfade)과 영어로 비교된다.
# LLM이 중국어/한국어 mood를 뱉으면 규칙이 영원히 미발동 → 영어 enum으로 강제 + 가드.
MOODS = ("calm", "sad", "neutral", "happy", "tense", "excited", "surprised")

# ── 1단계 결정론 상수 (2026-08-13) ────────────────────────────────────────
# 스파이크가 확정한 그림은 프롬프트·시드·길이·조명이 전부 상수였기 때문에 나온 것이다.
# 프로덕션은 이것들을 LLM/job_id에 넘겨서 매번 다른 결과를 냈다. 스파이크 값을 기본으로
# 되돌린다(환경변수로 실험 가능).
#
# duration: LLM이 2~3초 사이를 씬마다 다르게 정했다. 2.0초는 49프레임(24fps)이라 인물이
# 이동할 시간 자체가 부족해 "슬로우모션"으로 보인다(job e9059c29 씬2·4 실측).
# 스파이크는 전 씬 3.0초(73프레임)였다.
SCENE_DURATION_SECONDS = float(os.environ.get("AGENT_SCENE_DURATION", "3.0"))

# 조명: 기존엔 mood에서 파생돼 씬마다 톤이 튀었다(excited→high-key/deep shadows,
# happy→cool cast, neutral→dusk). 한 광고의 조명은 하나여야 한다. 빈 문자열로 두면
# 기존 mood 파생 경로를 그대로 쓴다.
SCENE_LIGHTING_LOCK = os.environ.get(
    "AGENT_SCENE_LIGHTING",
    "warm golden late-afternoon backlight, bright clear exposure, soft long shadows")

# M3-7 재조명 폴백: LLM 씬별 조명 큐 생성 실패/누락 시 mood만으로 구체적 조명 언어를 준다.
# 핵심 목적 — 어두운 mood(sad/tense)는 참조 이미지 밝기를 상속하지 않고 실제로 저조도로 간다.
_MOOD_LIGHTING = {
    "sad":       "low-key dim lighting, deep soft shadows, cool desaturated color grade, low exposure",
    "tense":     "hard low-key lighting, high contrast, sharp deep shadows, cold color cast",
    "calm":      "soft even lighting, gentle shadows, warm neutral color grade",
    "neutral":   "balanced natural lighting, moderate contrast, neutral color temperature",
    "happy":     "bright high-key lighting, light airy shadows, warm saturated color grade",
    "excited":   "bright vivid lighting, punchy saturated color, dynamic highlights",
    "surprised": "bright sudden key light, crisp highlights, alert high contrast",
}


def _mood_to_lighting(mood: str) -> str:
    return _MOOD_LIGHTING.get((mood or "neutral").strip().lower(), _MOOD_LIGHTING["neutral"])


# LLM이 neutral/happy 장면에도 "low-key dim"을 반복 선택하는 경향을 결정론적으로
# 차단한다. 프롬프트 지시만으로는 실제 job에서 해질녘의 happy 장면까지 deep shadows로
# 내려간 사례가 있었으므로, 이 두 mood는 최소 노출을 코드 레벨에서 보장한다.
_DARK_LIGHTING_RE = re.compile(
    r"\b(low[- ]key|dim(?:ly)?|underexpos(?:ed|ure)|low exposure|deep shadows?|"
    r"near[- ]black|poorly lit|dark lighting)\b", re.I)


def _enforce_mood_exposure(mood: str, cue: str) -> str:
    normalized = (mood or "neutral").strip().lower()
    cleaned = (cue or "").strip()
    if normalized in {"happy", "neutral"} and (
        not cleaned or _DARK_LIGHTING_RE.search(cleaned)
    ):
        return _MOOD_LIGHTING[normalized]
    return cleaned or _mood_to_lighting(normalized)


# M3-8: 참조 사진은 대개 밝은/중립 조명이라, 저조도·강대비 mood가 참조와 가장 크게
# 괴리된다 → 이런 씬만 서버측 relight 노브를 켜 첫프레임 latent 잠금을 완화한다. 밝은/
# 중립 mood는 참조와 유사해 노브 미적용(기존 동작 유지).
# ponytail: mood 화이트리스트 휴리스틱. 참조 실제 밝기 측정으로 업그레이드는 필요 시.
RELIGHT_MOODS = {"sad", "tense"}


def _needs_relight(mood: str) -> bool:
    return (mood or "neutral").strip().lower() in RELIGHT_MOODS

SUBJECT_TYPES = ("human", "nonhuman", "none")


def _split_scene_text_safely(text: str) -> tuple:
    """절 중간(주어+목적어+동사)을 끊지 않고 텍스트를 둘로 나눈다. 문장종결 부호(./!/?)나
    쉼표가 끝이 아닌 중간에 있으면 그 지점에서 나누고, 나눌 안전한 지점이 없으면(완결된
    절 하나뿐) 같은 text를 그대로 복제해 두 씬으로 만든다(각도·디테일 차이는 하류 영어
    재작성 단계가 담당) — 단어 수로 무작정 반토막 내던 예전 방식이 '우주선이 지구를'/
    '향해 다가간다'처럼 목적어와 동사를 갈라놓는 버그의 원인이었다."""
    body = text.rstrip()
    if len(body) <= 1:
        return None, None
    matches = list(re.finditer(r"[.!?,]", body[:-1]))  # 끝 문장부호는 분할 지점에서 제외
    if matches:
        cut = matches[-1].end()
        first, second = body[:cut].strip(), body[cut:].strip()
        if first and second:
            return first, second
    return text, text


# 씬 개수. 4가 기본이지만 광고 마무리 히어로컷(제품 단독)을 붙이려면 5가 필요하다.
# LLM 프롬프트·교정 재요청·정규화가 전부 이 값을 공유해야 한다 — 한 곳만 바꾸면
# "정확히 4개로 나눠라"를 받은 LLM 출력이 정규화 단계에서 억지로 쪼개지거나 합쳐진다.
SCENE_COUNT = int(os.environ.get("AGENT_SCENE_COUNT", "4"))

# 한 job에서 LTX 2.3 22B Face-ID를 태울 수 있는 씬 수 상한. 2개부터 GGUF 재양자화
# 정체가 난다(node_classify_faceid_scenes 주석). 22B가 여유로운 장비로 옮기면 올린다.
FACEID_MAX_SCENES = int(os.environ.get("AGENT_FACEID_MAX_SCENES", "1"))


def _normalise_scene_count(items: list, target: int = SCENE_COUNT) -> list:
    """LLM의 3/5씬 변동을 원문 순서를 유지한 채 목표 개수로 정규화한다."""
    scenes = [dict(item) for item in items if isinstance(item, dict) and item.get("text")]
    while len(scenes) > target:
        tail = scenes.pop()
        scenes[-1]["text"] = f'{scenes[-1]["text"]} {tail["text"]}'.strip()
        scenes[-1]["duration"] = min(
            float(scenes[-1].get("duration") or 3),
            float(tail.get("duration") or 3),
        )
    while scenes and len(scenes) < target:
        index = max(range(len(scenes)), key=lambda i: len(str(scenes[i].get("text", ""))))
        source = scenes[index]
        first, second = _split_scene_text_safely(str(source["text"]))
        if first is None:
            break
        scenes[index:index + 1] = [
            {**source, "text": first},
            {**source, "text": second},
        ]
    return scenes


# 캡션(gemma 영어)에서 사람/비인간을 결정론적으로 판정한다. qwen2.5:7b가 씬 분할 시
# subject_type 필드를 자주 누락(→ None)해 마스코트·제품이 얼굴(STANDIN) 경로로 오라우팅되던
# 문제(job 1fddc76: 4씬 전부 subject_type None)를 캡션 진실원천으로 막는다.
# 컴퓨팅 하드웨어 어휘 중 computer/server/workstation/machine/equipment는 "a man at
# his computer"류 사람 캡션에도 흔히 걸려 human을 nonhuman으로 오분류한다(실측:
# tests/test_subject_caption_classification.py가 회귀로 잡음). hardware/appliance/
# accelerator/processor/electronics/computing은 사람 캡션의 주어로 잘 안 쓰여
# 충돌 리스크가 낮다 — 그 쪽만 남긴다.
_NONHUMAN_HINTS = re.compile(
    r"\b(mascot|robot|android|product|logo|animal|creature|monster|toy|plush|doll|figurine|"
    r"cartoon|cartoonish|emoji|blob|gadget|device|bottle|package|parcel|box|carton|"
    # lamp/light: 조명 제품 광고. 없으면 캡션이 nonhuman으로 안 잡혀 단일참조 job이
    # 전 씬 human으로 굳고 마무리 히어로컷에 사람이 그려진다.
    r"lamp|lantern|luminaire|"
    r"food|snack|fruit|plant|flower|vehicle|car|truck|drone|cat|dog|bird|fish|dragon|"
    r"hardware|appliance|accelerator|processor|electronics|computing)\b|"
    r"(animated|cartoon|stylized|cute|character)\s+character|character\s+illustration", re.I)
_HUMAN_HINTS = re.compile(
    r"\b(man|woman|men|women|person|people|boy|girl|lady|guy|male|female|worker|portrait|human|"
    r"businessman|businesswoman|gentleman|model|child|kid|adult|he|she)\b", re.I)


def _subject_type_from_caption(caption: str) -> str | None:
    """캡션 키워드로 human/nonhuman 판정. 애매하면 None(폴백).
    비인간 힌트를 먼저 본다 — 'cute mascot ... character'처럼 사람 단어가 섞여도 마스코트 우선."""
    cap = caption or ""
    if _NONHUMAN_HINTS.search(cap):
        return "nonhuman"
    if _HUMAN_HINTS.search(cap):
        return "human"
    return None


# 2026-08-12 음료 광고 스파이크 실측: 병 제품을 손으로 들어 마시는 동작을 I2V에
# 시키면 LTX가 와인병/유리병 쪽으로 강하게 드리프트(강도=1.0 최대여도 발생, 스파이크
# probe_bev_ad_scene3a_v5.py에서 negative prompt로 억제 성공). "지금 이 시나리오"
# 한정 대응 — 캡션에 bottle이 잡히는 I2V 씬에만 결정적으로 적용, 다른 제품군
# 일반화는 하지 않는다(요청 범위 밖).
_BOTTLE_CAPTION_RE = re.compile(r"\bbottle\b", re.I)
_BOTTLE_DRIFT_NEGATIVE = (
    tools.LTX13B_DEFAULT_NEGATIVE + ", wine bottle, beer bottle, glass bottle, "
    "dark green glass, dark bottle, wine, alcohol, champagne, opaque bottle, "
    "different object, morphing shape"
)


def _negative_prompt_for_i2v_scene(caption: str) -> str | None:
    """I2V 씬의 ref 캡션에 병이 잡히면 와인병 드리프트 억제용 negative를 채운다.
    안 잡히면 None(호출부가 tools 기본 negative로 폴백)."""
    if _BOTTLE_CAPTION_RE.search(caption or ""):
        return _BOTTLE_DRIFT_NEGATIVE
    return None


# 씬 텍스트(한/영)에서 피사체 종류 판정 — 캡션(gemma) 불필요. M3-6 이전 결정론적 경로 복원.
# 비인간 명사가 있으면 nonhuman을 우선(마스코트/로봇/제품 씬), 아니면 사람 명사로 human.
_NONHUMAN_TEXT = re.compile(
    r"마스코트|캐릭터|로봇|안드로이드|제품|상품|인형|로고|동물|고양이|강아지|개구리|곰|토끼|새|물고기|"
    r"드론|자동차|기계|사물|음식|과일|식물|꽃|"
    r"\b(mascot|robot|android|product|logo|animal|creature|toy|doll|drone|vehicle|plant|character)\b", re.I)
_HUMAN_TEXT = re.compile(
    r"여성|남성|여자|남자|사람|인물|직원|회사원|아이|소년|소녀|남녀|그녀|그는|인간|"
    r"\b(woman|man|person|people|boy|girl|worker|human|lady|male|female)\b", re.I)


# 씬 텍스트에 제품이 등장하는지 — 인물 참조와 제품 참조가 함께 있는 job에서 어느 씬이
# 제품 조립 경로를 타야 하는지 결정론적으로 가른다. LLM의 씬↔이미지 매칭은 신뢰하지
# 않는다(2026-08-13 E2E job f11798c7 실측: 4씬 중 2씬을 틀리게 매칭 — "고개를 들고
# 들이켰다" 씬에 제품 사진을 사람 얼굴 참조(role=ref)로 붙여 Face-ID에 병 사진이
# 들어갈 뻔했다. 6.17에서 단일 참조에 내린 결론 — "씬↔참조 매칭을 LLM이 판단하는
# 구조 자체가 문제" — 가 2참조에서도 그대로 재현됨).
# _NONHUMAN_TEXT와 분리한 이유: 그쪽은 "이 씬의 주인공이 비인간인가"를 묻는 반면
# 여기는 "인물이 다루는 소품으로 제품이 등장하는가"라 주인공 판정과 독립이다.
# `water`가 목록에 있는 이유: 4B가 "음료수"를 "cool water"로 번역해 뱉는 게 실측돼 있고
# (job 911ebd9c), 그때 bottle/drink 어느 것도 안 걸린다. 광고 시나리오 문맥에서 water는
# 사실상 항상 제품이라 오탐보다 미탐 비용이 크다.
_PRODUCT_TEXT = re.compile(
    r"음료수|음료|드링크|생수|물병|페트|패트|병|캔|제품|상품|무드등|무드 ?램프|램프|"
    r"\b(bottle|drink|beverage|can|product|soda|juice|water|lamp|lamps)\b", re.I)


# 인물이 제품을 **손에 쥐는** 씬인지 — 조립 경로에서 배경 전략과 배치 비율이 갈린다.
# 쥐는 씬은 배경에 빈 그립 손을 미리 그려야 하고(안 그리면 LTX가 손과 제품을 같이
# 발명하며 라벨이 날아간다, clip13/16 실측), 제품이 가슴 높이에 크게 놓인다.
# 놓인 씬은 벤치·바닥 전경에 작게 놓이고 인물은 배경에 멀리 있다.
_HAND_ACTION_TEXT = re.compile(
    r"집어|집는|들어\s*올|들고|쥐고|쥔|마시|들이켜|들이키|한\s*모금|입에\s*대|"
    r"\b(pick(s|ing)?\s*up|grab(s|bing)?|hold(s|ing)?|drink(s|ing)?|sip(s|ping)?|"
    r"raise(s|d)?\s+the|lifts?)\b", re.I)


# 인물 참조가 없는 job("시나리오만" 모드)에서 씬마다 뽑는 인물 정본 포트레이트.
#
# 의상 지시 두 개는 미관이 아니라 **locate_grip 때문**이다. 그립 검출은 인물 마스크 안의
# 살색을 연결요소로 쪼개 "얼굴과 분리된 덩어리 = 팔·손"으로 보는데, 노출이 늘어날수록
# 그 가정이 깨진다(2026-08-14 probe_person_ref 씬1 연속 실측):
#   - V넥/가슴 노출 → 얼굴·목·가슴이 한 덩어리 → 얼굴 bbox가 파편으로 잡힘
#   - 민소매 → 팔·어깨가 한 덩어리 → "팔 상단 40% = 손"이 어깨까지 먹어 병이 주먹 옆에 뜸
# 긴팔 + 하이 크루넥이면 드러난 살색이 **얼굴과 손뿐**이라 그 가정이 그대로 성립한다.
# 포즈 검출기(SDPoseKeypointExtractor 등)로 바꾸는 게 정공법이지만 MODEL+VAE를 더 올려야
# 해서 이 머신의 메모리 여유가 없다(docs/spikes/2026-08-14-product-only-various-people.md §2.6).
PERSON_REF_PORTRAIT_PROMPT = (
    "A photorealistic head-and-shoulders portrait photograph of {description}, "
    "facing the camera, calm neutral expression, plain uncluttered background, "
    "soft even lighting, sharp focus. They wear a plain high crew-neck long-sleeve "
    "top that fully covers the chest, shoulders and both arms down to the wrists, "
    "no V-neck, no exposed chest, no bare shoulders, no bare forearms"
)


def _person_on_screen_flags(scenes: list[Scene]) -> list[bool]:
    """씬별 "사람이 화면에 있는가". 인물 참조가 붙은 job과 제품만 첨부한 job이 공유한다.

    인물 명사만 보면 안 된다 — 한국어는 주어를 생략한다("벤치 앞에 멈춰 음료수를 집어
    든다"에는 사람 단어가 하나도 없다). 손동작 신호를 같이 보면 그런 문장도 인물 씬으로
    잡히고, 실제 히어로컷 문장("제품이 벤치 위에 놓여 빛난다")은 둘 다 없어 구분된다.

    신호가 아예 없으면 **직전 씬에서 물려받는다**(forward-fill). 동사 목록을 늘리는 건
    한국어에서 끝이 없고, 광고 한 편에서 주인공은 중간에 사라지지 않는다. 다만 제품이
    문장의 주인공인 씬(제품 명사만 있고 인물 신호가 전혀 없음)은 상속을 끊어 히어로컷으로
    인정한다 — 안 그러면 마무리 히어로컷에 사람이 그려진다.
    """
    flags, carried = [], False
    for sc in scenes:
        text = sc.get("text") or ""
        explicit = bool(_HUMAN_TEXT.search(text) or _HAND_ACTION_TEXT.search(text))
        if explicit:
            carried = True
        elif _PRODUCT_TEXT.search(text):     # 제품만 있는 씬 = 히어로컷 → 상속 끊음
            carried = False
        flags.append(explicit or carried)
    return flags


def _subject_type_from_text(text: str) -> str | None:
    """씬 텍스트 키워드로 human/nonhuman 판정. 애매하면 None."""
    t = text or ""
    if _NONHUMAN_TEXT.search(t):
        return "nonhuman"
    if _HUMAN_TEXT.search(t):
        return "human"
    return None


def _is_nonhuman_subject(text: str) -> bool:
    """구 테스트용 호환 shim. image_role 결정 경로에서는 사용하지 않는다."""
    return any(term in (text or "") for term in ("고양이", "로봇", "마스코트"))


def _normalise_image_role(matched: str | None, role: str | None,
                          subject_type: str | None) -> str | None:
    """LLM이 판단한 피사체 종류를 image_role의 진실의 원천으로 사용한다."""
    if not matched:
        return None
    if subject_type == "nonhuman":
        return "character_ref"
    if subject_type == "human":
        # 이미 character_ref면 뒤집지 않는다. 인물+제품 광고에서 제품 씬은
        # subject_type=human(주인공은 사람) + role=character_ref(참조는 제품)라는
        # 조합을 쓴다(6.23 결정론 배정). 여기서 role을 ref로 되돌리면
        # node_classify_faceid_scenes가 **제품 사진을 얼굴 참조로** 잡아 Face-ID가
        # 무작위 인물을 그린다 — 2026-08-13 UI E2E job 1a0d85b1에서 실제로 발생했다
        # (씬2·3이 양복 입은 다른 사람으로 나옴). 승인 게이트를 통과할 때만 재정규화가
        # 돌아서 split 단독 테스트로는 안 잡혔다.
        if role == "character_ref":
            return role
        return role if role in ("start", "ref") else "ref"
    return role if role in ("start", "ref", "character_ref") else None


_SENTENCE_TERMINALS = (".", "!", "?", "다", "요", "까", "네", ",")


def _scenes_look_fractured(scenes_raw: list, script_text: str) -> bool:
    """인접 두 씬의 text가 원문 한 문장을 절 중간에서 자른 조각인지 감지한다.
    두 조각을 이어붙인 문자열이 원문의 연속 부분문자열이면서, 앞 조각이 문장종결
    표지(./!/?/다/요/까/네/,) 없이 끝나면 — 목적어/동사 같은 문법 단위가 씬 경계에서
    잘렸다고 본다(예: '우주선이 지구를' / '향해 다가간다')."""
    compact_script = re.sub(r"\s+", "", script_text)
    for i in range(len(scenes_raw) - 1):
        a = scenes_raw[i] if isinstance(scenes_raw[i], dict) else {}
        b = scenes_raw[i + 1] if isinstance(scenes_raw[i + 1], dict) else {}
        a_text, b_text = str(a.get("text", "")), str(b.get("text", ""))
        a_stripped = a_text.rstrip()
        if not a_stripped or a_stripped[-1] in _SENTENCE_TERMINALS:
            continue
        combined = re.sub(r"\s+", "", a_text + b_text)
        if combined and combined in compact_script:
            return True
    return False


async def node_split_scenes(state: GraphState) -> dict:
    """1-3: 씬 분할 (AI)"""
    captions = state.get("ref_captions") or {}
    # 파일명뿐 아니라 '무엇을 담고 있는지(shows)'를 함께 넘겨 내용 기반 매칭이 되게 한다.
    ref_info = [{"file": fn, "shows": captions.get(fn, "")} for fn in (state.get("ref_images") or [])]

    system_prompt = (
        f"너는 애니메이션 스토리보드 작가다. 주어진 시나리오를 정확히 {SCENE_COUNT}개 씬으로 분할하라. "
        f"반드시 {SCENE_COUNT}개의 객체만 반환하고, 시나리오의 시작부터 끝까지 시간 순서대로 고르게 배분하라. "
        "text는 반드시 입력 시나리오와 '같은 언어'로 써라 — 다른 언어(특히 중국어/영어)로 "
        "번역하지 마라. 시나리오 문장을 임의로 요약·창작하지 말고 원문의 내용과 순서를 보존하라. "
        "한 문장(주어+목적어+동사)을 문법 단위 중간에서 두 씬으로 쪼개지 마라. "
        # 예시는 도메인 중립이어야 한다. 전엔 '우주선이 지구를…'을 썼는데, 4B 모델이
        # 묘사할 피사체가 없는 씬에서 이 예시를 그대로 주워다 썼다(job 14a61492 실측:
        # "Earth hangs above the skyline", "abandoned earth space station", "ISS at
        # 400 km altitude"). 교훈(문장 중간 절단 금지)은 어떤 문장으로도 전달된다.
        "나쁜 예: 원문 '학생이 책을 책상에 내려놓는다.' → 씬A text='학생이 책을', "
        "씬B text='책상에 내려놓는다.' (틀림 — 목적어 '책'과 동사가 분리돼 두 씬 다 "
        "무슨 장면인지 알 수 없다). 좋은 예: 씬 text='학생이 책을 책상에 내려놓는다.' "
        "그대로 한 씬에 담고, 부족한 씬 개수는 다른 씬에서 다른 각도·디테일로 채운다. "
        "각 씬의 text는 그 자체로 '누가/무엇이 무엇을 하는지' 완결되게 읽혀야 한다. 문장 수가 "
        f"{SCENE_COUNT}개보다 적으면 한 문장을 다른 각도·디테일로 확장해 채우고, 많으면 의미가 이어지는 "
        f"문장끼리 묶어서 {SCENE_COUNT}개로 만들어라 — 절대 문장을 반으로 자르지 마라. "
        "각 씬은 다음 키를 가진 객체다: text(씬 설명, 입력과 동일 언어), "
        "duration(초, 숫자, 2~3 사이 — 3초를 넘기지 마라, 긴 장면은 여러 씬으로 쪼개라), "
        f"mood(반드시 다음 영어 단어 중 하나: {', '.join(MOODS)}), "
        "matched_image(ref_images 중 이 씬에 그 피사체가 등장하는 파일명 하나 — 반드시 shows 설명을 "
        "보고 '내용'으로 판단, 없으면 null). script_text와 shows의 언어가 달라도 번역된 의미가 같으면 "
        "동일 피사체로 매칭하고, shows의 주요 피사체가 씬에 등장하면 구도·행동이 달라도 반드시 매칭하라, "
        f"subject_type(씬 텍스트와 shows를 함께 보고, 참조할 주요 피사체가 사람이면 \"human\", "
        f"동물·식물·사물·제품·로봇·가상 캐릭터면 \"nonhuman\", 피사체가 없으면 \"none\"; "
        f"반드시 {', '.join(SUBJECT_TYPES)} 중 하나), "
        "image_role(matched_image가 있을 때만: 이 씬이 그 사진과 똑같은 장면/포즈로 '시작'하면 \"start\", "
        "사람의 얼굴 identity만 유지하면 \"ref\", 마스코트·로봇·제품·비인간 캐릭터의 전체 "
        "실루엣·색상·로고를 유지하면 \"character_ref\", 그 외 null). "
        "중요: 같은 인물/사물이 여러 씬에 나오면 그 인물이 등장하는 '모든' 씬에 matched_image를 붙여라 "
        "(그래야 인물이 일관되게 유지된다). subject_type을 먼저 의미적으로 판단한 뒤 role을 정하라. "
        "nonhuman은 종류나 명칭에 관계없이 항상 \"character_ref\"를 사용하고, human만 사진과 동일 "
        "구도로 시작하면 \"start\", 그 외에는 \"ref\"를 사용하라. "
        "JSON 배열로만 반환하고 다른 텍스트는 절대 포함하지 마라."
    )
    user_prompt = json.dumps({
        "script_text": state["script_text"],
        "ref_images": ref_info,
    }, ensure_ascii=False)

    raw = await tools.call_llm(system_prompt, user_prompt)
    try:
        scenes_raw = tools.parse_json_lenient(raw)
    except ValueError:
        # Nemotron Q4가 문법이 깨진 JSON을 낼 때가 실측 확인됨(배열 close 누락, 반복 생성
        # 등, 2026-08-01). 그대로 두면 job 전체가 크래시한다 — 개수 오류와 동일한 교정
        # 재시도 경로로 흡수한다.
        scenes_raw = None
    # Nemotron Q4는 같은 프롬프트에서도 간헐적으로 3/5씬을 반환한다(Spike 2.3).
    # 잘못된 결과를 그대로 승인 게이트에 보내지 말고, 결과를 보존한 교정 요청을 한 번 수행한다.
    # 개수 오류·JSON 파싱 실패뿐 아니라 문장 중간 절단(목적어/동사 분리)도 같은 경로를 탄다.
    fractured = isinstance(scenes_raw, list) and _scenes_look_fractured(scenes_raw, state["script_text"])
    if (scenes_raw is None or not isinstance(scenes_raw, list)
            or len(scenes_raw) != SCENE_COUNT or fractured):
        if scenes_raw is None:
            instruction = (
                "이전 응답은 문법이 깨진 JSON이었다(배열이나 객체의 괄호가 안 맞았다). "
                "같은 내용을 반복해서 출력하지 말고, 배열은 반드시 '['로 열어 ']'로 정확히 "
                "닫고 각 객체도 '{'...'}' 한 쌍으로 정확히 닫아라. 정확히 "
                f"{SCENE_COUNT}개 씬으로 나누고 "
                "JSON 배열 외에는 아무것도 출력하지 마라."
            )
        elif fractured:
            instruction = (
                "이전 결과는 원문의 한 문장(주어+목적어+동사)을 씬 경계에서 중간에 잘랐다 "
                "— 예: '학생이 책을' / '책상에 내려놓는다'처럼 목적어와 동사가 다른 씬으로 "
                "분리됐다. 문장을 자르지 말고 각 씬 text가 완결된 문장(또는 완결된 절)이 "
                "되도록 다시 나눠라. 내용과 시간 순서는 보존하되, 문장 수가 "
                f"{SCENE_COUNT}개보다 적으면 "
                "같은 문장을 다른 각도·디테일로 확장해 채워라. JSON 배열 외에는 아무것도 "
                "출력하지 마라."
            )
        else:
            instruction = (
                "이전 결과의 내용과 시간 순서를 보존하면서 정확히 "
                f"{SCENE_COUNT}개 씬으로 다시 나눠라. "
                "JSON 배열 외에는 아무것도 출력하지 마라."
            )
        correction_prompt = json.dumps({
            "instruction": instruction,
            "script_text": state["script_text"],
            "ref_images": ref_info,
            "previous_result": scenes_raw if scenes_raw is not None else raw[:500],
        }, ensure_ascii=False)
        raw = await tools.call_llm(system_prompt, correction_prompt)
        try:
            scenes_raw = tools.parse_json_lenient(raw)
        except ValueError:
            scenes_raw = None
    if not isinstance(scenes_raw, list):
        scenes_raw = []
    scenes_raw = _normalise_scene_count(scenes_raw)

    ref_set = set(state.get("ref_images") or [])
    scenes: list[Scene] = []
    # 한국어는 첫 문장 뒤로 주어를 생략한다(pro-drop). "한 여성 모델이 옥상에서 걸어온다 /
    # 엘리베이터를 타고 내려온다 / 횡단보도에서 하늘을 본다"는 전부 같은 인물인데
    # _subject_type_from_text가 씬을 개별로 보므로 2번째 씬부터 None→"none"이 된다.
    # "none"이면 _scene_prompt_system(has_human_subject=False)가 "사람을 만들지 마라"를
    # 걸어 주인공을 지워버린다(job 14a61492 실측: 4씬 중 3씬에서 인물이 사라지고 트램·
    # 우주정거장이 대신 등장). 참조 이미지가 있으면 캡션이 빈자리를 메워 가려지므로
    # 참조 없는 job에서만 드러난다. setting이 이미 쓰는 forward-fill을 여기도 적용한다.
    carried_subject_type: str | None = None
    for i, s in enumerate(scenes_raw):
        if isinstance(s, str):        # qwen이 씬을 객체 대신 문자열로 뱉을 때 방어 → 그 문자열을 씬 텍스트로
            s = {"text": s}
        if not isinstance(s, dict) or not s.get("text"):  # 형태 깨진 항목은 건너뜀
            continue
        matched = s.get("matched_image")
        subject_type = s.get("subject_type")
        if subject_type not in SUBJECT_TYPES:
            subject_type = "none"
        if matched not in ref_set:  # LLM이 없는 파일명을 환각하면 T2V로 강등
            matched = None
        # subject_type 진실원천: 씬 텍스트 키워드 > 캡션 > 직전 씬 물려받기 > LLM.
        # 7b가 subject_type을 자주 누락(→None)해 마스코트가 얼굴(STANDIN) 경로로 새던 회귀를 막는다.
        #
        # 물려받기가 LLM보다 위인 이유: 이 4B는 subject_type을 누락만 하는 게 아니라
        # 틀리게도 답한다(job 74ea0e1a 실측 — "횡단보도에서 신호를 기다리며 고개를 들어
        # 하늘을 본다"를 nonhuman으로 분류, 텍스트엔 비인간 키워드가 하나도 없다). 그
        # 결과 _scene_prompt_system이 "사람을 만들지 마라"를 걸어 주인공 대신 신호등이
        # 주인공이 됐다. 텍스트·캡션이라는 실제 증거가 없을 때는 LLM의 씬별 추측보다
        # "이야기의 피사체는 이어진다"는 연속성이 더 신뢰할 만하다.
        cap_type = _subject_type_from_caption(captions.get(matched, "")) if matched else None
        derived = _subject_type_from_text(s.get("text", "")) or cap_type
        if derived:
            subject_type = derived
        elif carried_subject_type:
            # ponytail: 첫 씬은 물려받을 게 없어 LLM 값이 그대로 선다 — 거기서 틀리면
            # 전 씬이 같이 틀린다. 풍경 전용 씬이 인물을 물려받는 과포함도 감수한다
            # (주인공이 삭제되는 쪽보다 피해가 작다). 무인물 씬을 정확히 표현해야 하면
            # 그때 씬 텍스트의 무인물 신호를 _NONHUMAN_TEXT에 추가한다.
            subject_type = carried_subject_type
        if subject_type in ("human", "nonhuman"):
            carried_subject_type = subject_type
        role = _normalise_image_role(matched, s.get("image_role"), subject_type)
        # duration은 LLM 값을 쓰지 않고 상수로 고정한다(SCENE_DURATION_SECONDS).
        # 씬마다 2~3초를 오가면 프레임 수가 49~73으로 흔들리는데, 49프레임 씬은 인물이
        # 이동할 시간이 부족해 움직임이 거의 없는 컷이 된다(job e9059c29 씬2·4 실측).
        # 사람이 1-4 게이트에서 고친 값은 그대로 존중된다(이 노드는 재분할 때만 돈다).
        scenes.append({
            "id": i + 1,
            "text": s["text"],
            "duration": SCENE_DURATION_SECONDS,
            "mood": s.get("mood") if s.get("mood") in MOODS else "neutral",
            "matched_image": matched,
            "image_role": role,
            "subject_type": subject_type,
            "quality_flag": "pending",
            "approved": False,
        })

    if len(ref_set) == 1:
        # 단일 참조 결정론적 매칭: 참조가 1장뿐이면 "어느 씬에 매칭할지" 판단 자체가
        # 불필요하다(항상 그 하나). LLM의 씬별 matched_image/subject_type 판단을
        # 신뢰하지 않고 전 씬에 강제 부착한다 — Nemotron/gemma4 둘 다 이 판단에서
        # 비결정적으로 실패함을 실측 확인(job 67c45bcb-44e2, [[docs/model-selection-llm.md]]:
        # 동일 입력 재실행마다 matched_image가 null/부분매칭을 오갔다). subject_type은
        # 캡션이 있으면 캡션 기반, 없으면 human 기본값(단일 참조 대부분이 인물 사진).
        only_ref = next(iter(ref_set))
        st = _subject_type_from_caption(captions.get(only_ref, "")) or "human"
        role = "character_ref" if st == "nonhuman" else "ref"
        # 참조가 제품 1장뿐인 job = "인물 생성 없이 제품만 첨부"(UI 시나리오만 모드).
        # subject_type을 전 씬 nonhuman으로 굳히면 안 된다 — 그러면 사람이 제품을 쓰는
        # 씬도 무인물 씬으로 취급돼 SUBJECT_REF(Wan 참조 경로)로 가고, 참조에 없는
        # 인물·손·동작을 못 그린다. 씬 텍스트의 인물 신호로 씬별로 가른다: 사람이 나오는
        # 씬은 human(→ 제품 조립 경로), 제품 단독 씬은 nonhuman(→ 히어로컷).
        # 인물 사진 1장짜리 job(st="human")은 기존대로 전 씬 동일하다.
        person_flags = (_person_on_screen_flags(scenes) if st == "nonhuman"
                        else [True] * len(scenes))
        for sc, has_person in zip(scenes, person_flags):
            sc["matched_image"] = only_ref
            sc["subject_type"] = "human" if (st == "human" or has_person) else "nonhuman"
            sc["image_role"] = role
    elif len(ref_set) > 1:
        ref_types = {fn: _subject_type_from_caption(captions.get(fn, "")) for fn in ref_set}
        humans = [fn for fn, t in ref_types.items() if t == "human"]
        nonhumans = [fn for fn, t in ref_types.items() if t == "nonhuman"]
        if len(ref_set) == 2 and len(humans) == 1 and len(nonhumans) == 1:
            # 인물 1장 + 제품 1장 결정론적 배정 — "얼굴 생성 + 제품 첨부" 조합(6.22)의
            # 표준 형태다. 단일 참조에서와 같은 이유로 LLM 매칭을 통째로 무시한다:
            # 어느 씬에 무엇이 필요한지가 참조 종류만으로 이미 정해져 있기 때문이다.
            #   - 주인공(인물)은 전 씬에 등장하므로 face_id_ref로 항상 붙인다.
            #   - 제품이 텍스트에 등장하는 씬만 matched_image=제품(character_ref)으로 둔다.
            #     그 씬도 subject_type은 human이다 — 제품은 인물이 다루는 소품이지
            #     주인공이 아니다. nonhuman으로 두면 _scene_prompt_system이 "사람을
            #     만들지 마라"를 걸어 주인공이 지워진다(6.9에서 잡았던 버그).
            #
            # 제품 등장 판정은 씬별 키워드 매칭이 아니라 **등장 이후 forward-fill**이다.
            # 광고 시나리오에서 제품은 한 번 나오면 끝까지 남는다. 씬별로 키워드를 찾으면
            # 씬분할 LLM이 문장을 영어로 번역해버리는 순간 놓친다(2026-08-13 E2E job
            # 911ebd9c 실측: "고개를 들고 시원하게 음료수를 들이켰다"를 "heads up, he
            # takes a sip of cool water"로 번역해 "음료수"도 bottle/drink도 안 걸렸다.
            # 씬분할 시스템 프롬프트가 "입력과 같은 언어로 써라"를 명시하는데도 4B가
            # 무시하는 기존 비결정성). setting·subject_type이 이미 쓰는 forward-fill과
            # 같은 처방이다 — 첫 등장 지점만 맞히면 되므로 번역에 훨씬 덜 취약하다.
            human_ref, product_ref = humans[0], nonhumans[0]
            product_on_screen = False
            # 인물 신호가 없는 제품 씬 = 히어로컷(제품 단독 클로즈업). 이런 씬에 얼굴
            # 참조를 붙이면 조립 경로가 인물 배경을 그려 제품 단독 컷이 안 된다.
            # 판정 규칙은 _person_on_screen_flags 참조(제품 단독 job과 공유).
            for sc, has_person in zip(scenes, _person_on_screen_flags(scenes)):
                text = sc.get("text") or ""
                sc["face_id_ref"] = human_ref if has_person else None
                sc["subject_type"] = "human" if has_person else "nonhuman"
                # 제품도 인물처럼 **끊긴다**. 무한 forward-fill이면 제품이 손을 떠난
                # 뒤의 씬까지 조립 경로로 가서 병이 뜬금없이 합성된다(2026-08-13 UI E2E
                # job 3ded2f29 씬4 실측: "다시 코트로 돌아가 공을 잡고 달려나간다"에
                # 페트병이 바닥에 붙어 나옴). 인물 명사가 있고 손동작이 없는 씬 =
                # 제품이 화면 밖이므로 상속을 끊는다. 손동작이 있으면(번역돼 제품 명사가
                # 사라진 "takes a sip" 같은 문장) 그대로 유지한다.
                if _PRODUCT_TEXT.search(text):
                    product_on_screen = True
                elif _HUMAN_TEXT.search(text) and not _HAND_ACTION_TEXT.search(text):
                    product_on_screen = False
                if product_on_screen:
                    sc["matched_image"] = product_ref
                    sc["image_role"] = "character_ref"
                else:
                    sc["matched_image"] = human_ref
                    sc["image_role"] = "ref"
            return {"scenes": scenes, "phase": "planning"}
        # 매칭 누락 결정론적 보정: 9b가 씬↔이미지 matched_image를 랜덤 누락(여자 씬이 None으로
        # 새 사람 생성 → 얼굴 일관성 붕괴)하던 문제를 캡션 기반 per-ref 종류로 메운다. 씬의
        # subject_type과 같은 종류의 참조가 정확히 하나면 그 참조로 매칭한다(모호하면 건드리지 않음).
        for sc in scenes:
            if sc.get("matched_image"):
                continue
            st = sc.get("subject_type")
            if st in ("human", "nonhuman"):
                cands = [fn for fn, t in ref_types.items() if t == st]
                if len(cands) == 1:
                    sc["matched_image"] = cands[0]
                    sc["image_role"] = _normalise_image_role(cands[0], sc.get("image_role"), st)

    return {"scenes": scenes, "phase": "planning"}


def node_checkpoint_scene_approval(state: GraphState) -> Command:
    """
    checkpoint 1-4 (필수): 씬 분할 결과를 사람이 검토.
    OpenWebUI 쪽에서는 이 interrupt payload를 받아 씬 리스트를 프리뷰로 렌더링하고,
    사용자가 수정한 scenes(있다면)와 approve 여부를 resume 값으로 되돌려준다.
    """
    decision = interrupt({
        "checkpoint": "1-4_scene_split",
        "message": "씬 분할 결과를 확인하고 승인하거나 수정해주세요.",
        "scenes": state["scenes"],
    })
    # decision 예시: {"approved": True, "scenes": [...수정된 씬...]}
    if decision.get("approved"):
        updated_scenes = decision.get("scenes", state["scenes"])
        # 사람이 게이트에서 지정한 이미지 가드: 없는 파일이면 T2V 강등, 역할 비었으면 I2V(start)
        ref_set = set(state.get("ref_images") or [])
        guarded = []
        for s in updated_scenes:
            img, role = s.get("matched_image"), s.get("image_role")
            if img not in ref_set:
                img, role = None, None
            else:
                role = _normalise_image_role(img, role, s.get("subject_type"))
            guarded.append({**s, "matched_image": img, "image_role": role})
        return Command(goto="node_generate_prompts", update={"scenes": guarded})
    else:
        # 반려 시 씬 분할 재시도 (사람이 텍스트 자체를 수정했을 수도 있음)
        return Command(
            goto="node_split_scenes",
            update={"script_text": decision.get("revised_script_text", state["script_text"])},
        )


# ══════════════════════════════════════════════════════════
# Phase 2. 씬별 프롬프트 엔지니어링
# ══════════════════════════════════════════════════════════
# style bible: job당 1회 생성, 모든 씬 프롬프트 끝에 주입 → 분위기/톤 통일
STYLE_LOCK_TOKEN = """  Maintain one cohesive visual world across every scene. Keep the rendering technique,
  line and edge treatment, shape language, surface materials, texture density,
  environmental detail level, prop design language, color-grading method,
  shadow characteristics, cinematic contrast, and camera character consistent.
  Every location, subject, and object must appear designed by the same art department.
  Allow scene-specific changes in location, time of day, weather, emotion, lighting
  intensity, and accent colors when required by the narrative, without changing the
  underlying visual style."""


async def _make_style_bible(state: GraphState) -> tuple[str, str]:
    """전체 시나리오 기준 공통 스타일 규격 1개 생성. 실패 시 기존 토큰으로 폴백.
    반환: (style_bible, character_sheet). character_sheet는 참조 이미지가 없고 사람이
    등장하는 job에서만 채워지며(needs_character_sheet), 그 외에는 빈 문자열이다 —
    LLM 호출은 여전히 1회다(같은 응답에서 두 줄로 받아 쪼갠다).
    image_query(있으면)가 정지 이미지 앵커의 화풍을 정의하므로, 영상 스타일이 그와
    독립적으로 결정되면 이미지·영상 그림체가 어긋난다 → image_query를 앵커로 넘겨
    같은 렌더링 기법을 따르도록 강제한다."""
    image_query = (state.get("image_query") or "").strip()
    # 실제 인물 사진(Face-ID) 참조 씬이 있으면 화풍을 photoreal로 강제한다 — 안 그러면
    # LLM이 애니메이션/플랫벡터 화풍을 골라도 막을 게 없어서, Face-ID LoRA가 얼굴만
    # 실사로 박아넣는 동안 배경·소품은 그림체로 렌더링되는 불일치가 생긴다.
    has_face_ref = any(
        s.get("subject_type") == "human" and s.get("image_role") in ("start", "ref")
        for s in (state.get("scenes") or [])
    )
    # 참조 이미지가 하나도 없는데 사람이 등장하는 job(= no-ref 모드)에서만 캐릭터 시트를
    # 함께 뽑는다. 참조가 있으면 Stand-In/Face-ID latent나 캡션이 이미 identity를 쥐고
    # 있어 텍스트로 또 고정하면 표정·자세까지 굳는다(node_generate_prompts의 standin 주석).
    needs_character_sheet = (
        not (state.get("ref_images") or [])
        and any(s.get("subject_type") == "human" for s in (state.get("scenes") or []))
    )
    system_prompt = (
          "You are an art director for a short video. "
          "Create ONE global style bible from the complete story and scene list. "

          + (
              "A reference image was already generated from the anchor prompt given "
              "below (see 'image_anchor_prompt'). The video MUST match that image's "
              "rendering technique, line/edge treatment, and shape language exactly — "
              "do not invent a different art style (e.g. do not switch between anime, "
              "3D render, or photoreal). Extract the rendering style from the anchor "
              "prompt and carry it through unchanged. "
              if image_query else ""
          )

          + (
              "A real person's face will be identity-locked into this video from a real "
              "photo (Face-ID). The style MUST be photorealistic, cinematic live-action — "
              "real-world materials, natural lighting, photographic texture and detail "
              "density. Do NOT choose anime, flat vector, illustration, 3D-cartoon, or any "
              "other stylized/non-photoreal rendering technique — a stylized background "
              "would clash with the photoreal locked face. "
              if has_face_ref else ""
          )

          # 앵커 이미지도 Face-ID도 없는 순수 T2V job(예: job 4265fba0)은 이 스타일을
          # 고정할 게 아무것도 없어 "flat vector linework... characterless" 같은 2D
          # 화풍으로 표류한다 — 이 플랫폼의 기본 정체성(photoreal cinematic)을 명시적
          # 기본값으로 못박는다.
          + (
              "No reference image constrains this style. Default to photorealistic, "
              "cinematic live-action rendering — real-world materials, natural lighting, "
              "photographic texture and detail density — matching this platform's "
              "established visual identity. Only depart from photoreal if the story text "
              "itself explicitly names an illustrated, animated, or stylized medium (e.g. "
              "anime, cartoon, watercolor, comic, flat vector). "
              if not image_query and not has_face_ref else ""
          )

          + "Define ONLY the invariant visual rules that stay IDENTICAL across every "
          "scene (the art style / 화풍): rendering technique, line and edge treatment, "
          "shape language, surface materials, texture density, environmental detail "
          "level, prop design language, camera character, COLOR GRADING (palette bias, "
          "saturation, and contrast character), and LENS STYLE (focal length feel, depth-of-field "
          "character, any distortion — e.g. wide-angle deep focus, anamorphic shallow "
          "DOF, telephoto compression). Think of all four clips as connected shots from "
          "the same short film shot on the same camera/lens package and graded in the "
          "same pass. "

          # M3-7: per-scene mood/lighting는 여기서 정의하지 않는다(_make_scene_lighting가
          # 씬별로 담당). bible은 씬 간 불변 화풍만 담아 모든 씬에 동일하게 주입된다.
          "Do NOT bake in any single scene's brightness, exposure, time of day, or "
          "lighting state — those change per scene and are specified separately. "

          "Also define ONE overarching emotional tone/atmosphere for the whole piece "
          "(e.g. quiet awe, tense urgency, warm nostalgia) that stays constant as the "
          "story's emotional register throughout — this is the film's constant "
          "undertone, NOT the same thing as each scene's specific mood, which still "
          "swings with the narrative beat (tense, calm, joyful) and is specified "
          "separately per scene. "

          # 참조 이미지가 있으면 identity는 이미지 latent(Stand-In/Face-ID)나 캡션이
          # 담당하므로 bible이 외모를 정하면 안 된다. 참조가 없으면 그 반대다 — 아무도
          # 인물을 고정하지 않아 씬마다 새 사람이 나온다(job 1a0b199d 실측: 1씬 "a woman
          # model"이 4씬에서 "beside him"으로 성별까지 바뀜).
          + ("Do not standardize character identity, anatomy, clothing, or appearance. "
             if not needs_character_sheet else
             "No reference photo exists for the people in this story, so nothing else "
             "pins their appearance down — you must. ")

          + ("Output only a compact comma-separated English style specification "
             "under 130 words. No preamble, quotes, or markdown."
             if not needs_character_sheet else
             "Output exactly two lines, no preamble, quotes, or markdown:\n"
             "STYLE: <compact comma-separated English style specification, under 130 words>\n"
             "CHARACTER: <the single main character's fixed physical appearance in one "
             "sentence — approximate age, build, hair colour/length/style, skin tone, "
             "distinctive features, and default outfit. State the gender explicitly. Be "
             "concrete enough that a different artist would draw the same person twice. "
             "Describe appearance ONLY — no pose, expression, action, location, or "
             "lighting. If the story genuinely has no person in it, output CHARACTER: none>")
    )
    user_prompt = json.dumps({
        "script": state["script_text"],
        "scenes": [s["text"] for s in state["scenes"]],
        "characters": state.get("ref_captions") or {},
        **({"image_anchor_prompt": image_query} if image_query else {}),
    }, ensure_ascii=False)
    try:
        raw = tools.clean_llm_prompt(await tools.call_llm(system_prompt, user_prompt))
        bible, sheet = _split_style_and_character(raw) if needs_character_sheet else (raw, "")
        return (bible or STYLE_LOCK_TOKEN), sheet
    except Exception:
        return STYLE_LOCK_TOKEN, ""


def _split_style_and_character(raw: str) -> tuple[str, str]:
    """needs_character_sheet일 때의 "STYLE: ... / CHARACTER: ..." 2줄 응답을 쪼갠다.

    LLM이 형식을 안 지키면(라벨 누락) 전체를 style bible로 보고 시트는 비운다 — 시트가
    비면 호출부가 주입을 건너뛸 뿐이라 기존 동작으로 안전하게 되돌아간다. 라벨을 못
    떼면 "CHARACTER: ..."가 모든 씬 프롬프트 꼬리에 그대로 붙어버리므로 여기서 반드시
    떼어내야 한다.
    """
    style_parts: list[str] = []
    sheet = ""
    current = None
    for line in (raw or "").splitlines():
        stripped = line.strip()
        low = stripped.lower()
        if low.startswith("style:"):
            current = "style"
            stripped = stripped[len("style:"):].strip()
        elif low.startswith("character:"):
            current = "character"
            stripped = stripped[len("character:"):].strip()
        if not stripped:
            continue
        if current == "character":
            sheet = f"{sheet} {stripped}".strip()
        elif current == "style":
            style_parts.append(stripped)
    if not style_parts:          # 라벨을 아예 안 지킴 → 전체를 bible로, 시트는 포기
        return (raw or "").strip(), ""
    if sheet.lower().rstrip(". ") == "none":   # 인물 없는 이야기
        sheet = ""
    return " ".join(style_parts), sheet


_LIGHTING_SYSTEM = (
    "You are a cinematographer + continuity supervisor for a short video. The art style (화풍) is "
    "FIXED across scenes — you do NOT touch it. For EACH scene output two things: "
    "(1) lighting — one short English clause: exposure/brightness, key-light quality, shadow depth, "
    "contrast, color temperature, translating the scene's MOOD. ONLY sad or tense beats should be "
    "low-key or genuinely dim. Happy scenes MUST be bright/high-key with clear subject exposure; "
    "neutral scenes MUST have balanced natural exposure with readable midtones and no deep shadows; "
    "calm scenes should use soft even light at normal exposure, not default to dimness. Never inherit "
    "a bright reference image's brightness. No character appearance/clothing/pose — lighting only. "
    # setting은 반드시 영어. 조립 경로가 이 값을 Flux Kontext/T2I 배경 프롬프트에 그대로
    # 넣는데, 한국어면 영어 전용 모델에 노이즈로 들어가 장소 지시가 통째로 증발한다
    # (2026-08-13 job e9059c29 실측: setting="코트 한쪽 벤치" → 배경이 인물 정본의 회색
    # 스튜디오 그대로 나옴). 씬 텍스트는 원문 언어를 유지하되 setting만 영어로 뽑는다.
    "(2) setting — the scene's physical LOCATION/background, ALWAYS written in English "
    "regardless of the script's language, concrete and photographable "
    "(e.g. 'an outdoor asphalt basketball court', not '농구장'). If this "
    "scene continues in the SAME place as the previous scene, output an empty string \"\" for setting "
    "(it inherits the previous location). Only fill setting when the location changes. When in doubt, "
    "fill it in rather than leaving it empty — scenes that name a different physical environment "
    # 도메인 중립 예시 — 위 split 프롬프트와 같은 이유로 우주 소재를 걷어냈다.
    "(e.g. a hotel lobby vs. a rooftop terrace vs. a subway platform vs. a riverside path) "
    "are almost always DIFFERENT settings, even if no location word is repeated. "
    # person은 인물 참조가 없는 job(제품만 첨부하는 "시나리오만" 모드)에서만 쓰인다.
    # 그 모드의 조립 배경은 T2I로 사람을 처음부터 그리는데, 씬 문장을 그대로 넣으면
    # 동작까지 그려져 첫 프레임이 망가진다(빈 손이어야 할 자리에 T2I가 우유잔을 그린
    # 실측, 2026-08-14 job 8820932b 씬1). 그래서 동작을 뺀 **외형만** 여기서 뽑는다.
    "(3) person — who is visible in this scene, as a short English noun phrase: approximate age, "
    "gender, and role or context (e.g. 'a woman in her 20s who has just finished a workout', "
    "'a construction worker in his 40s wearing a yellow hard hat'). NO action, NO pose, NO "
    "location, NO objects they hold. "
    # 상의를 묘사하면 안 되는 이유는 미관이 아니라 그립 검출이다 — 인물 정본 프롬프트가
    # 긴팔·하이 크루넥을 강제하는데(PERSON_REF_PORTRAIT_PROMPT), 여기서 "pink sports bra"
    # 같은 걸 같이 넣으면 diffusion이 둘을 섞어 파인 목선을 그린다. 그러면 가슴 살이
    # 얼굴·목과 한 덩어리가 돼 얼굴 bbox 아래끝이 턱이 아니라 가슴이 되고, 그 값에서
    # 파생되는 그립 밴드가 통째로 아래로 밀려 병이 손 아래에 붙는다(2026-08-14
    # probe_person_ref 씬1 실측: 턱 300px인데 얼굴 bbox가 460px까지, 밴드 515~970).
    "Do NOT describe the top, shirt, dress or any torso garment — wardrobe is fixed elsewhere. "
    "Hats, glasses and other head/face accessories are fine. "
    "Empty string \"\" if no person appears in the scene. "
    "Different scenes may show different people — describe each scene's own person, do not copy. "
    'Output ONLY a JSON object mapping each scene id (string) to '
    '{"lighting": "...", "setting": "...", "person": "..."}, '
    'e.g. {"1": {"lighting": "low-key dim, deep shadows, cool cast", "setting": "a dim open-plan office", '
    '"person": "a man in his 30s in a navy shirt"}, '
    '"2": {"lighting": "sudden bright key light", "setting": "", "person": ""}}. No preamble, no markdown.'
)


# 씬 텍스트에 장소가 **명시돼 있으면** LLM 추출값보다 우선한다.
# _make_scene_context의 focused LLM(gemma3:4b)이 장소를 환각한다: 2026-08-23 job
# 8402186d 씬2는 원문이 "어두운 서재 책상 앞에 앉은 20대 남자가 노트북을 덮고
# 기지개를 켜며 창밖을 본다"인데 setting을 'an indoor basketball court with a large
# window'로 뱉었고, 결과 영상이 체육관에서 상반신 탈의 남자가 만세하는 컷이 됐다
# (프롬프트에 "the player"까지 박혔다). 같은 job 씬3은 "은은한 주황빛이 감도는
# 거실"이 'bright and airy living room'으로 뒤집혀 어두운 무드와 정면 충돌했다.
# 원문에 장소 단어가 있는 씬만 덮어쓴다 — 없으면 LLM 값을 그대로 둔다.
_SETTING_KEYWORDS = (
    ("서재", "a home study with a wooden desk and bookshelves"),
    ("사무실", "a quiet office interior with a desk"),
    ("책상", "an indoor room with a wooden desk"),
    ("거실", "a home living room with a sofa"),
    ("소파", "a home living room with a sofa"),
    ("아이 방", "a child's bedroom"),
    ("아이방", "a child's bedroom"),
    ("침실", "a bedroom with a bed and a bedside table"),
    ("침대", "a bedroom with a bed and a bedside table"),
    ("원룸", "a small one-room apartment interior"),
    ("주방", "a home kitchen"),
    ("부엌", "a home kitchen"),
    ("욕실", "a home bathroom"),
    ("현관", "an apartment entryway"),
    ("카페", "a cafe interior"),
    ("농구장", "an outdoor basketball court"),
    ("코트", "an outdoor basketball court"),
    ("체육관", "an indoor gymnasium"),
)


def _script_sentence_for_scene(state: GraphState, index: int) -> str:
    """씬분할 LLM이 잘라낸 사용자 원문 문장을 되찾는다.

    2026-08-23 job 1fd34d0a 실측: 사용자가 친 "어두운 서재 책상 앞에 앉은 20대 남자가
    노트북을 덮고 기지개를 켜며 창밖을 본다"에서 씬분할이 **"어두운 서재 책상 앞에
    앉은"을 통째로 잘라냈다**. 장소 단어가 사라지니 _setting_from_text가 볼 게 없었고
    setting LLM의 농구장 환각이 그대로 영상이 됐다.

    문장 수와 씬 수가 같을 때만 index로 짝짓는다 — 다르면 짝이 틀릴 수 있어 포기한다.
    """
    sentences = [x.strip() for x in re.split(r"(?<=[.!?。])\s+|\n+",
                                             state.get("script_text") or "") if x.strip()]
    if len(sentences) == len(state.get("scenes") or []) and 0 <= index < len(sentences):
        return sentences[index]
    return ""


def _setting_from_text(text: str) -> str | None:
    """씬 원문에서 장소를 직접 읽는다. 못 찾으면 None(= LLM 값 유지)."""
    t = text or ""
    for keyword, place in _SETTING_KEYWORDS:
        if keyword in t:
            return place
    return None


async def _make_scene_context(
    state: GraphState,
) -> tuple[dict[int, str], dict[int, str], dict[int, str]]:
    """M3-7 + 배경 연속성: 씬별 재조명 큐 + 장소(setting) + 인물 외형(person)을 한 번의
    focused LLM 호출로 생성. bible(불변 화풍)과 분리. setting 추출이 비었거나 실패하면
    직전 씬을 추측해 상속하지 않고 해당 씬 원문으로 폴백해 사용자 내용을 보존한다.
    이전엔 setting을 giant split 호출에 얹었는데 9b가 run마다 누락 → focused 호출로 이관해 안정화.
    반환: (lighting_map, setting_map, person_map). 실패/누락 씬은 호출부에서 폴백.
    person은 인물 참조가 없는 job에서만 쓰이므로 누락돼도 폴백 없이 빈 값으로 둔다."""
    scenes = state.get("scenes") or []
    user_prompt = json.dumps({
        "script": state.get("script_text", ""),
        "scenes": [{"id": s.get("id"), "text": s.get("text", ""), "mood": s.get("mood", "neutral")}
                   for s in scenes],
    }, ensure_ascii=False)
    lighting: dict[int, str] = {}
    setting: dict[int, str] = {}
    person: dict[int, str] = {}
    # 9b는 setting 필드를 run마다 통째로 누락하기도 한다(3런 중 1런). 또한 값을 일부만
    # 채우고 나머지를 전부 ""(=이어짐)로 반환하는 경우도 실측됨(job fbd7c4a5, 4씬 스토리에서
    # 씬1만 채우고 2~4가 전부 이전 장소를 계속 상속 — 명백히 다른 장소인데도). "하나라도 얻으면
    # 종료"는 이 절반-누락 케이스를 못 걸러내므로, 최소 절반 이상 채워야 통과로 인정한다.
    min_filled = max(1, len(scenes) // 2)
    for _attempt in range(2):
        try:
            raw = tools.parse_json_lenient(await tools.call_llm(_LIGHTING_SYSTEM, user_prompt))
        except Exception:
            break
        lit_map: dict[int, str] = {}
        set_map: dict[int, str] = {}
        person_map: dict[int, str] = {}
        for k, v in (raw or {}).items():
            if isinstance(v, dict):
                lit = (v.get("lighting") or "").strip() if isinstance(v.get("lighting"), str) else ""
                setg = (v.get("setting") or "").strip() if isinstance(v.get("setting"), str) else ""
                per = (v.get("person") or "").strip() if isinstance(v.get("person"), str) else ""
            else:  # 구형/축약 응답: 문자열이면 lighting으로만 취급
                lit, setg, per = ((v or "").strip() if isinstance(v, str) else ""), "", ""
            if lit:
                lit_map[int(k)] = lit
            if setg:
                set_map[int(k)] = setg
            if per:
                person_map[int(k)] = per
        lighting = lighting or lit_map   # 첫 시도의 조명은 보존
        person = person or person_map
        setting = set_map
        if len(setting) >= min_filled:    # 최소 절반 이상 장소를 얻으면 종료
            break
    # 누락 씬은 **가장 가까운 유효 장소를 상속**한다(forward-fill, 선두 공백은 첫 유효값).
    #
    # 이전에는 해당 씬의 한국어 원문을 폴백으로 넣었다. 사용자 내용을 보존한다는
    # 취지였지만 실측 결과 정반대로 작동했다(2026-08-13 A/B, Nemotron 4B·exaone 32b
    # 공통): 4씬 중 씬1만 장소 추출에 성공하고 2~4는 "그는 코트 한쪽 벤치에 있는
    # 음료수 병을 향해 달려간다." 같은 원문이 setting에 그대로 들어갔다. 장소 정보가
    # 사실상 없으니 프롬프트 LLM이 장소를 자유 창작해 같은 광고 안에서 농구장이
    # 광장·공원·테니스장으로 튀었다(테니스 라켓까지 등장).
    #
    # 광고 한 편의 장소는 하나이거나 몇 개뿐이라 상속이 훨씬 안전하다. "첫 씬 배경이
    # 전체를 덮는다"는 원래 우려는 실재하지만, 장소가 통째로 사라지는 쪽이 확실히 더
    # 나쁘다는 게 확인됐다. 장소가 실제로 바뀌는 스토리는 LLM이 그 씬의 setting을
    # 채우면 그 지점부터 새 장소로 갈아탄다.
    ordered = [s.get("id") for s in scenes]
    first_valid = next((setting[sid] for sid in ordered if setting.get(sid)), "")
    carried = first_valid
    for sid in ordered:
        if setting.get(sid):
            carried = setting[sid]
        else:
            setting[sid] = carried
    return lighting, setting, person


async def node_generate_prompts(state: GraphState) -> dict:
    """2-1, 2-2: 프롬프트 생성 + 스타일 고정 + 이미지 스마트 라우팅 (AI).
    - 스타일 바이블: job당 1회 생성, 모든 씬 프롬프트 끝에 주입 → 분위기/톤 통일.
    - image_role=start/ref → Stand-In 얼굴 크롭으로 사람 identity 유지.
    - image_role=ref → Stand-In으로 사람 얼굴 identity 유지.
    - image_role=character_ref → Subject Ref로 마스코트/제품 전체 identity 유지.
    - 이미지 없음      → T2V.
    """
    captions = state.get("ref_captions") or {}
    wardrobe_locks = dict(state.get("wardrobe_locks") or {})
    # 생성 인물의 의상을 전 씬 wardrobe lock으로 승격한다.
    #
    # 지금까지 wardrobe_locks는 사용자가 시나리오에 "img_0 의상: ..."처럼 **직접 선언**한
    # 경우에만 채워졌다. 그래서 이미지를 생성해 쓰는 M2 플로우에서는 Face-ID 씬에 의상
    # 지시가 하나도 없었고, `_scene_prompt_system`의 standin 분기는 "의상을 지어내지
    # 마라"만 걸어서 모델이 매 씬 아무거나 입혔다(2026-08-13 job 953eeea2 clip1: 인물
    # 정본은 흰 반팔인데 검은 바시티 재킷이 나옴).
    #
    # 이미지 생성 프롬프트에는 사용자가 요구한 의상이 그대로 들어 있으므로(`wearing
    # white short-sleeve t-shirt`) 그걸 뽑아 인물 참조의 lock으로 쓴다. 사용자가 직접
    # 선언한 값이 있으면 그쪽이 우선이다(setdefault).
    generated_wardrobe = _wardrobe_from_query(state.get("image_query") or "")
    if generated_wardrobe:
        for ref_name, caption in captions.items():
            if _subject_type_from_caption(caption) == "human":
                wardrobe_locks.setdefault(ref_name, generated_wardrobe)
    # 재생성(regen)이면 이미 state에 있는 값을 그대로 쓴다 — 씬만 다시 만들 때 인물이
    # 바뀌면 안 되므로 시트도 bible과 같이 보존한다.
    if state.get("style_bible"):
        bible, character_sheet = state["style_bible"], (state.get("character_sheet") or "")
    else:
        bible, character_sheet = await _make_style_bible(state)

    # M3-7 재조명 + 배경 연속성: 씬별 조명 큐 + 장소(setting)를 한 번의 focused 호출로 생성
    # (추가 LLM 호출 없음 — 기존 조명 호출에 fold). 이미 둘 다 있으면(재생성) 재호출 생략.
    have_ctx = all(s.get("lighting") and s.get("setting") for s in state["scenes"])
    lighting_map, setting_map, person_map = (
        ({}, {}, {}) if have_ctx else await _make_scene_context(state))

    # job에 인물 참조가 함께 있으면(=인물+제품 광고) 제품 씬은 전부 조립 경로로 보낸다.
    # 히어로컷(제품 단독 클로즈업)은 face_id_ref가 없지만 여전히 조립이 맞다 — 제품 픽셀을
    # diffusion에 통과시키지 않는 게 이 경로의 요지다. 캡션만 보면 되므로 루프 밖에서 1회 계산.
    job_has_human_ref = any(
        _subject_type_from_caption(cap) == "human" for cap in captions.values())
    # 인물 참조가 없어도 **씬에 사람이 나오면** 조립 경로다(제품만 첨부하는 "시나리오만"
    # 모드). SUBJECT_REF(Wan 참조 경로)는 참조에 없는 인물·손·동작을 못 그리므로 사람이
    # 제품을 쓰는 광고에는 못 쓴다. 사람이 한 씬도 안 나오는 job(마스코트·제품 단독
    # 영상)은 그대로 SUBJECT_REF로 남는다.
    job_has_person_scene = any(s.get("subject_type") == "human" for s in state["scenes"])
    job_wants_assembly = job_has_human_ref or job_has_person_scene

    query_wardrobe = _wardrobe_from_query(state.get("image_query") or "")

    async def _ensure_scene_person_ref(scene: Scene, description: str) -> str | None:
        """인물 참조가 없는 job("시나리오만" 모드)의 인물 씬에 **씬 전용 인물 정본**을 만든다.

        조립 경로의 쥔 씬 배경은 인물 정본을 Kontext로 재렌더해 만드는데, 그 재렌더가
        "빈 원통형 그립 손"이라는 까다로운 포즈를 실제로 그려내는 유일한 경로다. 정본
        없이 T2I로 처음부터 그리면 손이 활짝 펴진 채 나오고(2026-08-14 job 872beeee 씬1
        실측: 손가락 5개를 편 손에 병이 합성됨), 살색 연결요소가 뭉쳐 그립 검출도
        `clamped`로 빠져 병이 어깨에 붙는다.

        그래서 씬마다 포트레이트 1장을 뽑아 face_ref로 준다 — 그 뒤는 베이스라인이
        검증한 Kontext 경로 그대로다. 인물 일관성은 **씬 안에서만** 유지되고 씬끼리는
        다른 사람이 나온다(이 모드의 의도).
        """
        name = f"person_{scene.get('id')}.png"
        dest = tools.refs_dir(state["job_id"]) / name
        if dest.exists():                      # 재생성 시 같은 사람을 유지
            return name
        query = PERSON_REF_PORTRAIT_PROMPT.format(description=description)
        try:
            path = await tools.generate_t2i_image(
                state["job_id"], query, seed=scene_seed(state["job_id"], scene.get("id") or 0),
                index=2000 + (scene.get("id") or 0))
        except Exception as exc:               # 실패해도 생성 전체를 막지 않는다
            print(f"[person_ref] 씬{scene.get('id')} 인물 정본 생성 실패({exc}) — T2I 배경 경로 사용")
            return None
        shutil.copyfile(path, dest)
        print(f"[person_ref] 씬{scene.get('id')} 인물 정본 {name}: {description}")
        return name

    def _person_appearance(scene: Scene) -> str:
        """조립 경로 배경(T2I/Kontext)에 넣을 인물 외형. 배경을 새로 그리므로 지시가
        없으면 의상이 자유롭게 나와 Face-ID 씬과 어긋난다(job 00a21ee8: 인물 정본은
        흰 티인데 베이지 티+청바지).

        인물 참조가 없는 job("시나리오만" 모드)은 물려받을 캡션이 없다 — 그 씬의 인물
        외형을 _make_scene_context가 뽑아둔 값으로 대신한다. 이게 없으면 배경 T2I에
        사람 정보가 하나도 안 들어가 씬마다 아무나 나온다."""
        appearance = (captions.get(scene.get("face_id_ref") or "", "")
                      or person_map.get(scene.get("id"), ""))
        if query_wardrobe:
            return (f"{appearance}, wearing {query_wardrobe}" if appearance
                    else f"wearing {query_wardrobe}")
        return appearance

    updated_scenes = []
    for scene_index, scene in enumerate(state["scenes"]):
        # 이 씬의 장소를 주입(빈값이면 기존/직전 상속값 유지) → _scene_prompt_user가 배경으로 씀.
        # 원문에 장소가 있으면 그걸 쓴다(_setting_from_text 주석의 환각 실측 참고).
        # 씬 텍스트에 없으면 사용자 원문 문장까지 되짚는다 — 씬분할이 장소 수식구를
        # 잘라내는 실측 사례가 있다(_script_sentence_for_scene 주석 참고).
        scene = {**scene, "setting": (
            _setting_from_text(scene.get("text", ""))
            or _setting_from_text(_script_sentence_for_scene(state, scene_index))
            or setting_map.get(scene.get("id"))
            or scene.get("setting", ""))}
        img = scene.get("matched_image")
        role = scene.get("image_role")
        subject_ref = bool(img) and role == "character_ref" and tools.USE_STANDIN
        standin = bool(img) and role in ("start", "ref") and tools.USE_STANDIN
        wardrobe = wardrobe_locks.get(img, "") if standin else ""
        # 보존(identity·화풍)과 분리된 '적응' 축: 이 씬의 재조명 큐.
        # 조명은 job 전체에 하나로 고정한다. mood 파생 경로를 쓰면 한 광고 안에서
        # 씬마다 톤이 바뀐다(excited→deep shadows, happy→cool cast, neutral→dusk가
        # 한 시나리오에서 동시에 나온 실측: job e9059c29). SCENE_LIGHTING_LOCK을 빈
        # 문자열로 두면 기존 mood 파생 경로로 돌아간다.
        cue = SCENE_LIGHTING_LOCK or _enforce_mood_exposure(
            scene.get("mood", "neutral"),
            (lighting_map.get(scene.get("id"))
             or scene.get("lighting")
             or _mood_to_lighting(scene.get("mood", "neutral"))),
        )

        has_human_subject = bool(standin or subject_ref or scene.get("subject_type") == "human")
        # 와이드샷 강제는 Stand-In(Wan) 경로 전용이다. 이 씬이 LTX Face-ID나 제품 조립으로
        # 갈 예정이면 끈다 — 그 경로들엔 정반대로 작용해 인물이 늘 멀리 잡힌다.
        will_be_faceid = bool(img) and scene.get("subject_type") == "human" and role in ("start", "ref")
        will_be_assembly = bool(subject_ref and (scene.get("face_id_ref") or job_wants_assembly))
        # 인물 참조가 없는 인물 씬 → 씬 전용 인물 정본을 만들어 Kontext 경로로 보낸다.
        # B노선으로 갈 씬은 **건너뛴다**. 이 정본은 A노선이 Kontext 배경을 재렌더할 때만
        # 쓰이는데 B노선은 배경을 T2V가 통째로 그리므로 한 장도 안 본다. 2026-08-23
        # job 032e1827 실측: 씬 4개분(person_1~4.png) 생성에 12:23~12:35, **12분**을
        # 쓰고 전부 버렸다 — job 전체 시간의 약 40%다.
        if (will_be_assembly and not job_has_human_ref and not scene.get("face_id_ref")
                and scene.get("subject_type") == "human"
                and not _scene_takes_overlay_route(state, scene)):
            desc = (person_map.get(scene.get("id")) or "").strip()
            ref = await _ensure_scene_person_ref(scene, desc) if desc else None
            if ref:
                scene = {**scene, "face_id_ref": ref}
        raw_prompt = _strip_echoed_bible(tools.clean_llm_prompt(
            await tools.call_llm(_scene_prompt_system(standin or subject_ref, bool(wardrobe),
                                                      has_human_subject,
                                                      force_wide=not (will_be_faceid or will_be_assembly)),
                                 _scene_prompt_user(scene, bible, wardrobe, cue))), bible)

        negative_prompt = None  # I2V 씬만 채움(984행) — 다른 모드는 이 필드를 안 씀
        if will_be_assembly:
            # 제품 참조가 붙은 씬 → A노선 조립(6.23).
            # subject_ref(Wan i2v_14b)로 보내면 참조에 없는 인물·손·동작을 못 그린다.
            mode = "PRODUCT_ASSEMBLY"
            negative_prompt = _negative_prompt_for_i2v_scene(captions.get(img, ""))
            full_prompt = f"{raw_prompt}, {bible}"
            # 조립 씬 배경은 T2I/Kontext가 새로 그리므로 인물 외형을 명시하지 않으면
            # 의상이 자유롭게 나와 Face-ID 씬과 어긋난다. 인물 참조 캡션을 그대로 넘긴다.
            scene = {**scene,
                     # 제품을 드는 씬만 hand_held(음료는 아무 손동작, 놓는 제품은
                     # 목적어가 제품일 때만 — "노트북을 들고"는 제외).
                     "product_hand_held": _scene_holds_product(
                         scene.get("text") or "", beverage=_product_is_beverage(state)),
                     "person_appearance": _person_appearance(scene)}
        elif subject_ref:
            mode = "SUBJECT_REF"
            desc = captions.get(img, "")
            desc_suffix = f" ({desc})" if desc else ""
            # "Preserve its complete silhouette" 문구를 첫 문장에 두면 diffusion이 이를
            # "프레임 안 배치까지 고정"으로 과하게 해석해 카메라가 피사체를 안 따라가는
            # 사례 실측(2026-07-10, job f1be24f6 — 배경·구도가 전 프레임 고정). identity
            # lock을 피사체 외형에만 명시적으로 한정하고, 카메라/구도는 이 lock과
            # 무관하다고 못박아 raw_prompt의 카메라 지시가 눌리지 않게 한다.
            identity = (f"The main subject's appearance is the exact non-human character or "
                        f"product from the reference image{desc_suffix}: same shape, colors, "
                        "distinctive features and visible logo — do not replace it with a human "
                        "or redesign its appearance. This constraint covers ONLY the subject's "
                        "own appearance; it does NOT fix the camera, framing, composition or "
                        "background — those follow the shot/camera-movement instructions below. ")
            full_prompt = f"{identity}{raw_prompt}, {bible}"
        elif standin:
            # Stand-In: 얼굴 identity는 이미지 latent로 주입된다. 프롬프트에 외모/캐릭터록을
            # 다시 넣으면 표정·자세까지 참조 사진처럼 '고정'돼 어색해진다 → 넣지 않는다.
            # 프롬프트는 오직 그 씬의 표정·감정·동작·구도만 밀어붙인다.
            mode = "STANDIN"
            wardrobe_lock = (WARDROBE_LOCK_TEMPLATE.format(
                wardrobe_description=wardrobe) if wardrobe else "")
            full_prompt = f"{wardrobe_lock}\n{raw_prompt}, {bible}" if wardrobe_lock else f"{raw_prompt}, {bible}"
            # 이 씬은 뒤에서 LTX_FACEID로 올라가고, Face-ID 정원(FACEID_MAX_SCENES)을
            # 넘으면 PERSON_ASSEMBLY로 내려간다(node_classify_faceid_scenes). 그 경로도
            # 배경을 새로 그리므로 인물 외형을 미리 실어둔다.
            scene = {**scene, "person_appearance": _person_appearance(scene)}
        elif img and role == "start":        # Stand-In off일 때만 I2V 폴백
            mode = "I2V"
            negative_prompt = _negative_prompt_for_i2v_scene(captions.get(img, ""))
            full_prompt = f"{raw_prompt}, {bible}"
        elif img:                           # ref이지만 Stand-In off → T2V + 캐릭터록 텍스트
            mode = "T2V"
            desc = captions.get(img, "")
            lock = f" The main character: {desc}." if desc else ""
            full_prompt = f"{raw_prompt}.{lock} {bible}"
        else:                               # 이미지 없음
            mode = "T2V"
            # no-ref 인물 씬: 참조가 없어 identity를 쥔 게 아무것도 없다. 캐릭터 시트를
            # 위 캡션록(928행)과 같은 문구로 붙여 씬마다 새 사람이 나오는 걸 막는다.
            # 무인물 씬에는 붙이지 않는다 — _scene_prompt_system이 그 씬엔 "사람을
            # 만들지 마라"를 걸고 있어 정면으로 충돌한다.
            lock = (f" The main character: {character_sheet}."
                    if character_sheet and has_human_subject else "")
            full_prompt = f"{raw_prompt}.{lock} {bible}"

        # B노선(제품 오버레이)은 style_bible도 조명 큐도 붙이지 않는다.
        #  - bible: 제품 이미지에서 뽑은 디자인 사양서라 영상 화풍을 3D 만화로 만든다
        #    (job 032e1827 실측, tools.PRODUCT_OVERLAY_STYLE 주석 참고). 대신 고정
        #    실사 화풍을 tools 쪽에서 프롬프트 맨 앞에 붙인다.
        #  - 조명 큐: 서버 전역 AGENT_SCENE_LIGHTING에 "soft amber lamp glow"가 들어
        #    있어 그 단어가 T2V에 램프를 소환한다. B노선은 창밖 광원으로 대체한다.
        if _scene_takes_overlay_route(state, scene):
            full_prompt = raw_prompt
        else:
            # M3-7: 씬 재조명 큐를 결정적으로 프롬프트 끝에 못박는다 — rewrite LLM이 조명을
            # 약하게 반영해도 어두운 씬은 실제로 저조도 지시가 남는다(참조 밝기 상속 방지).
            full_prompt = f"{full_prompt} Scene lighting and atmosphere: {cue}."
        updated_scenes.append({
            **scene, "prompt": full_prompt, "mode": mode, "lighting": cue,
            "negative_prompt": negative_prompt,
        })

    return {"scenes": updated_scenes, "style_bible": bible,
            "character_sheet": character_sheet, "phase": "prompting"}


# 손동작이 **제품을 대상으로** 하는가. hand_held 배제는 "이 씬에서 제품이 손에 들려
# 함께 움직이는가"를 물어야 하는데, _HAND_ACTION_TEXT는 목적어를 안 봐서 "노트북을
# 들고"(2026-08-23 job f967a473 씬분할이 지어낸 문장)에도 걸려 놓는 제품 씬을 옛 조립
# 경로로 튕겼다. 손동작 동사 앞 목적어가 제품 지시어면 제품을 든 것, 다른 물건
# (노트북·책·가방)이면 제품은 그대로 놓여 있는 것이다.
_PRODUCT_REF_WORDS = ("제품", "그것", "이것", "음료", "병", "캔", "컵", "잔",
                      "무드등", "램프", "product", "lamp", "bottle", "can", "cup", "drink")
_PRODUCT_HELD_RE = re.compile(
    r"(?:" + "|".join(_PRODUCT_REF_WORDS) + r")\s*(?:을|를|its|the)?\s*"
    r"[^.]{0,8}?(?:집어|집는|들어|들고|쥐고|쥔|마시|들이켜|들이키|한\s*모금|입에\s*대|"
    r"pick|grab|hold|drink|sip|lift|rais)", re.I)


# 이 job의 제품이 손에 드는 유형(음료 등)인가. 음료는 씬 자체가 "그걸 마시는" 이야기라
# 손동작=제품 듦이 맞다("holds it", "음료수를 마신다"). 놓는 제품(램프)은 반대로 손동작이
# 다른 물건("노트북을 들고")을 향하는 게 보통이라 목적어가 제품일 때만 든 것으로 본다.
_BEVERAGE_PRODUCT_RE = re.compile(
    r"음료|보틀|beverage|bottle|soda|juice|coffee|tea|콜라|주스|커피|" 
    r"\b(?:can|cup|drink)\b|캔|컵|잔|병", re.I)


def _product_is_beverage(state: GraphState) -> bool:
    text = state.get("image_request") or ""
    if not text:
        text = " ".join((state.get("ref_captions") or {}).values())
    return bool(_BEVERAGE_PRODUCT_RE.search(text))


def _scene_holds_product(text: str, *, beverage: bool = False) -> bool:
    """이 씬에서 **제품이** 손에 들리는가.
    beverage=True(음료 제품): 아무 손동작이나 제품 듦으로 본다(씬이 그걸 마시는 이야기다).
    beverage=False(놓는 제품): 손동작 목적어가 제품일 때만. "노트북을 들고"는 제외.
    """
    if beverage:
        return bool(_HAND_ACTION_TEXT.search(text or ""))
    return bool(_PRODUCT_HELD_RE.search(text or ""))


def _product_overlay_ref(state: GraphState) -> str | None:
    """오버레이할 제품 참조를 고른다. 없으면 None(= B노선 안 탐).

    생성 참조(describe 모드)는 `generated_ref_is_product`를 **먼저** 본다. 비전 캡션의
    human/nonhuman 판정은 같은 시나리오를 실행마다 다르게 갈랐다 — 2026-08-23 무드등
    E2E에서 job dd16ef56은 램프를 nonhuman(→character_ref→조립)으로, job c87912d8은
    human(→ref→Face-ID)으로 분류해 노선이 통째로 바뀌었다. 이미지 요청 시점의 규칙
    선택은 흔들리지 않으므로 그걸 우선한다. 업로드 참조는 캡션 판정으로 폴백한다.
    """
    refs = state.get("ref_images") or []
    if not refs:
        return None
    if state.get("generated_ref_is_product"):
        return refs[0]                      # describe 모드는 생성 이미지 1장 고정
    caps = state.get("ref_captions") or {}
    for ref in refs:
        if _subject_type_from_caption(caps.get(ref, "")) == "nonhuman":
            return ref
    return None


def _scene_takes_overlay_route(state: GraphState, scene: Scene) -> bool:
    """이 씬이 B노선(제품 오버레이)으로 갈 예정인가.

    node_classify_faceid_scenes의 판정과 **같은 규칙**이어야 한다. 여기서만 쓰이는
    목적은 A노선 전용 준비작업(씬별 인물 정본 T2I)을 미리 건너뛰는 것이다.
    """
    overlay_ref = _product_overlay_ref(state) if tools.PRODUCT_OVERLAY_ENABLED else None
    # 제품이 화면에 없는 인물 씬(matched_image가 인물 참조)까지 B노선으로 끌고 가면 그
    # 씬에 제품을 억지로 얹게 되고 의상 lock도 날아간다(test_generated_wardrobe_lock).
    if not overlay_ref or scene.get("matched_image") != overlay_ref:
        return False
    # 제품 **자체를** 드는 씬만 A노선에 남긴다. 무관한 손동작("노트북을 들고")은 제품이
    # 그대로 놓여 있으니 오버레이 유지.
    return not (scene.get("product_hand_held")
                or _scene_holds_product(scene.get("text") or "",
                                        beverage=_product_is_beverage(state)))


def node_classify_faceid_scenes(state: GraphState) -> dict:
    """2-3: 사람 참조가 있는 씬을 LTX_FACEID 모드로 분류한다.

    2026-07-31 재설계: 원래 이 노드는 Flux로 씬별 배경 앵커를 생성해
    LTXVImgToVideo에 강도 1.0으로 고정했으나, 앵커 생성이 얼굴 참조를 전혀
    받지 않아 identity가 무작위였고 그 강한 lock이 뒤따르는 Face-ID Identity
    Transfer 노드를 무력화했다(참조 얼굴과 무관한 얼굴이 나옴, 실사용 재현
    검증 완료). 배경 다양성은 3.2에서 이미 증명됐듯 씬 프롬프트 텍스트만으로
    충분해 앵커가 불필요 — 순수 분류만 남긴다.
    """
    scenes = state.get("scenes") or []

    def classify(scene: Scene) -> Scene:
        matched = scene.get("matched_image")
        face_id_ref = (
            matched
            if matched
            and scene.get("subject_type") == "human"
            and scene.get("image_role") in ("start", "ref")
            else None
        )
        # 인물+제품 2참조 job(node_split_scenes의 결정론 배정)에서는 제품 씬도 주인공
        # 얼굴을 유지해야 하므로 face_id_ref가 미리 채워져 있다. matched_image는 제품을
        # 가리키므로 위 식은 None을 내놓는데, 그걸 그대로 쓰면 주인공 identity가 날아간다.
        # 미리 설정된 값은 보존한다. 다만 mode는 LTX_FACEID로 올리지 않는다 — 그 씬은
        # 제품 픽셀 조립 경로(6.23)가 담당하고, Face-ID 배치는 제품이 없는 씬 전용이다.
        preset_face_ref = scene.get("face_id_ref")
        if face_id_ref is None and preset_face_ref:
            return {**scene, "face_id_ref": preset_face_ref,
                    "mode": scene.get("mode", "T2V")}
        # AGENT_FACE_BACKEND=standin이면 승격하지 않는다 — node_generate_prompts가 이미
        # 찍어둔 mode="STANDIN"(Wan2.1-14B + Stand-In LoRA, :8188)을 그대로 살린다.
        # 정원(FACEID_MAX_SCENES)은 LTX 22B GGUF 축출 정체 때문에 있는 제약이라
        # Stand-In 경로엔 해당 없음 — 아래 루프가 mode=="LTX_FACEID"만 세므로 자동으로 빠진다.
        promote = bool(face_id_ref) and tools.FACE_BACKEND == "ltx_faceid"
        return {
            **scene,
            "face_id_ref": face_id_ref,
            "mode": "LTX_FACEID" if promote else scene.get("mode", "T2V"),
        }

    # LTX 2.3 22B(GGUF Q6_K) Face-ID 씬은 **최대 FACEID_MAX_SCENES개**로 자른다.
    # 2개가 되는 순간 VAE 디코드가 free_memory를 부르고 ComfyUI-GGUF가 파이썬 단일
    # 스레드로 재양자화하면서 GPU 1%·CPU 1코어 100%로 10~40분 정체한다(py-spy로 확정,
    # docs/spikes/2026-08-13-scene5-e2e-handoff.md §2, 3.3-ltx-bottleneck-profile.md).
    # fp8 교체는 불가(22B 배포판은 bf16 46GB / GGUF Q6_K 17.8GB뿐).
    # 넘치는 씬은 조립 경로(제품 없는 변형)로 내린다 — 얼굴 identity는 씬2·3과 같은
    # 캡션·의상 lock 텍스트 수준으로만 유지된다. 사용자 결정(2026-08-14).
    # B노선(제품 오버레이)이 켜져 있고 이 job에 제품 참조가 있으면 Face-ID 승격을
    # **하지 않는다**. Face-ID는 씬 사이 얼굴 identity를 지키려고 존재하는데, 이 모드는
    # 인물 일관성을 요구하지 않는다(사용자 결정 2026-08-23) — 씬마다 다른 사람이어도
    # 된다. 대신 22B GGUF 축출 정체(10~40분)와 Kontext 조립을 통째로 건너뛴다.
    overlay_ref = _product_overlay_ref(state) if tools.PRODUCT_OVERLAY_ENABLED else None
    _bev = _product_is_beverage(state)
    # 히어로컷(사람 없는 제품 단독 컷) 판정은 씬 텍스트로 **결정론적으로** 한다.
    # subject_type은 씬분할 LLM이 붙이는 값이라 흔들린다 — 같은 시나리오 5번째 문장
    # ("빈 침실 협탁 위에 놓인 제품에 카메라가 다가간다")이 job 032e1827에서는
    # nonhuman, job 8402186d에서는 human으로 찍혔다. 후자에서는 히어로 비율도 무인
    # 강제도 안 걸려 마무리 컷이 인물 씬과 똑같은 크기로 나왔다.
    on_screen = _person_on_screen_flags(scenes)

    classified = []
    faceid_used = 0
    for idx, scene in enumerate(classify(s) for s in scenes):
        # 손에 쥔 씬은 제품이 손과 함께 움직여야 하므로 정적 오버레이가 물리적으로
        # 틀리다 — A노선에 남긴다. product_hand_held는 node_generate_prompts가
        # 조립 씬에만 채우므로 여기서 씬 텍스트로 직접 판정한다.
        # 제품을 드는 씬만 hand_held(음료=아무 손동작, 놓는 제품=제품 목적어일 때만).
        hand_held = bool(scene.get("product_hand_held")
                         or _scene_holds_product(scene.get("text") or "", beverage=_bev))

        if (overlay_ref and not hand_held
                and scene.get("matched_image") == overlay_ref):
            classified.append({**scene, "mode": "PRODUCT_OVERLAY",
                               "product_hand_held": False,
                               "product_hero": not on_screen[idx]})
            continue
        if scene.get("mode") == "LTX_FACEID":
            faceid_used += 1
            if faceid_used > FACEID_MAX_SCENES:
                scene = {**scene, "mode": "PERSON_ASSEMBLY"}
        classified.append(scene)
    print("[route] 씬 mode: " + ", ".join(
        f"{s.get('id')}={s.get('mode')}" for s in classified))
    return {"scenes": classified, "phase": "anchoring"}


def _scene_prompt_system(standin: bool, has_wardrobe: bool = False, has_human_subject: bool = True,
                         force_wide: bool = True) -> str:
    """씬 프롬프트 생성용 system 프롬프트. 구도/자세/표정/카메라를 '맥락에 맞게' 요구.

    핵심: 표정(facial expression)과 감정, 그리고 '정적이지 않은' 동적 동작을 명시적으로
    요구한다 — 이게 없으면 diffusion(특히 Stand-In)이 무표정·부동자세로 수렴한다.

    has_human_subject=False(씬 subject_type != "human")면 인물 묘사 지시를 아예 빼고
    "사람을 지어내지 마라"로 뒤집는다 — 안 그러면 "인물 하나 없이" 같은 무인물 씬에서도
    LLM이 항상 (2)(3) 지시를 채우려고 "a lone figure", "a figure hunched over" 같은
    임의의 사람을 만들어낸다(job 4265fba0 실측 — subject_type 전부 nonhuman인데
    4씬 전부 사람이 등장).
    """
    subject_clause = (
        "(2) the character's specific body pose, gesture and action; (3) the character's FACIAL "
        "EXPRESSION and emotional state matching the mood; "
        if has_human_subject else
        "(2)-(3) this scene has NO human character — do NOT invent a person, figure, silhouette, "
        "bystander, or any human presence anywhere in the shot; describe only the environment, "
        "objects, machinery, weather, and any named non-human subject (animal, mascot, robot, "
        "vehicle) performing its own action; "
    )
    base = (
        "You are a prompt engineer for a video diffusion model. "
        "Rewrite the scene into ONE vivid English prompt that specifies, all fitting the "
        "scene's context and mood: (1) shot size and camera angle (e.g. close-up, wide, low "
        "angle) — vary it per scene, do not default to a frontal medium shot; "
        + subject_clause +
        "(4) camera movement. "
        + ("Favor natural, dynamic motion and a lively expression — avoid static, stiff or "
           "frozen poses and blank faces. " if has_human_subject else
           "Favor natural, dynamic motion in the environment/subject — avoid static, frozen shots. ")
        + "This is ONE continuous, uncut shot — no jump cuts, no scene changes, no camera "
        "cuts inside the clip; describe a single unfolding moment, one dominant action, "
        "not several competing events. This scene is part of one continuous short film — "
        "write it as the next moment following on from the previous scene, not an "
        "isolated standalone image. "
        # 광고 컷에 군중이 끼면 주인공이 묻힌다. LLM이 스스로 "players casually milling
        # about", "a moderately busy court"를 넣던 실측(job 00a21ee8) 대응. 부정문("no
        # spectators")으로 쓰게 두면 그 문구가 diffusion 프롬프트에 그대로 들어가 오히려
        # 사람을 그리므로, 긍정 서술로 쓰라고 못박는다.
        # 지어낸 인명은 T5 텍스트 인코더에 인종·외모 편향을 태운다. 조립 씬 배경은 T2I가
        # 인물을 새로 그리므로 그 편향이 그대로 화면에 남는다(2026-08-13 job 3ded2f29
        # 씬3 프롬프트에 없던 이름 `Elias`가 등장).
        + "Never invent or use a personal name for anyone; refer to people only by generic "
        "noun phrases such as 'the man', 'the woman', 'the player'. "
        + "The location holds only the main subject: describe it as quiet and deserted, with "
        "no crowd, spectators, bystanders or other players present. Phrase this positively in "
        "your prompt (e.g. 'an empty court in the late afternoon'), never as a negation. "
        + "CRITICAL: keep every specific named subject, object, or place mentioned in the "
        "scene text explicit in your English prompt — if the scene names something concrete "
        "(e.g. Earth, a spaceship, a specific landmark), your prompt must name that exact "
        "thing too, not a vague substitute or generic background detail. Never drop it. "
        "The 'Global style' line you are given below is appended to your output automatically "
        "after you write it — do NOT copy, restate, or paraphrase any part of it (rendering "
        "technique, texture/material wording, lens, edge treatment, prop design language). "
        "Write ONLY this scene's shot, pose, expression, action and camera movement. "
    )
    if standin:
        base += (
            "IMPORTANT: the character's face and identity come from a separate reference "
            "image, so do NOT invent their appearance, age, gender, ethnicity or hair. "
            + ("A user-provided WARDROBE LOCK follows. Translate it faithfully into English, state the exact garments and colors, and keep them unchanged. " if has_wardrobe else "Do not invent or describe clothing. ")
            + "Describe what they DO and FEEL — expression, gaze, gesture, movement — and the shot composition. "
        )
        if force_wide:
            # Task 3.2 눈판정으로 확정된 기본값(STATE.md Task 3.2/5.2 재설계): Stand-In(Wan)
            # 경로에서는 클로즈업이 identity 전이 신뢰도와 배경 퀄리티를 둘 다 떨어뜨린다.
            #
            # 2026-08-13: LTX Face-ID와 제품 조립 경로에는 적용하지 않는다. 그 두 경로에는
            # 이 규칙이 정반대로 작용해 4씬 전부 "character small within this frame"이 나왔고
            # 인물이 멀어 얼굴이 뭉개졌다(job 00a21ee8, 사용자 지적). 스파이크 확정본은
            # medium-close(clip22)로 성공했다.
            base += (
                "OVERRIDE the shot-size instruction above for this character: ALWAYS use a wide "
                "or establishing shot with the character small within an expansive, detailed "
                "background — never a close-up or medium close-up. Keep the camera static or "
                "slow-panning, not pushing in. "
            )
    return base + "Output ONLY the prompt text — no preamble, no quotes, no explanation, no markdown."


def _strip_echoed_bible(raw_prompt: str, bible: str) -> str:
    """씬 프롬프트 LLM이 system 프롬프트의 '베끼지 마라' 지시를 무시하고 user 프롬프트에
    준 'Global style: {bible}' 컨텍스트를 그대로 따라 쓰는 사례 실측(로컬 소형모델,
    job 78cb492c) — code가 bible을 뒤에 다시 붙이므로 중복+토큰낭비. 마커 이후 텍스트와
    bible 원문 그대로 등장한 부분을 제거해 최종 프롬프트에서 스타일 문구가 한 번만
    남게 한다."""
    marker_idx = raw_prompt.find("Global style:")
    if marker_idx != -1:
        raw_prompt = raw_prompt[:marker_idx].rstrip()
    if bible and bible in raw_prompt:
        raw_prompt = raw_prompt.replace(bible, "").strip(" ,.")
    return raw_prompt


def _scene_prompt_user(scene: Scene, bible: str, wardrobe: str = "", lighting: str = "") -> str:
    lock = f"\nWARDROBE LOCK (mandatory, translate faithfully): {wardrobe}" if wardrobe else ""
    # M3-7: 씬 재조명 큐를 rewrite LLM에 넘겨 조명/노출/그림자를 프롬프트에 녹이게 한다.
    # 참조 이미지 밝기 상속 금지 — mood대로 재조명. (결정적 append는 호출부에서 별도 수행)
    relight = (f"\nScene lighting (translate faithfully, do NOT inherit the reference image's "
               f"brightness): {lighting}") if lighting else ""
    # 배경 연속성: 이 씬의 장소를 프롬프트에 명시적으로 실어 STANDIN/T2V(배경=프롬프트) 씬이
    # 직전 씬과 같은 장소를 유지하게 한다. forward-fill된 setting이 여기로 들어온다.
    place = f"\nSetting/location (render this exact place as the background): {scene.get('setting')}" if scene.get("setting") else ""
    return f"Scene: {scene['text']}\nMood: {scene.get('mood', 'neutral')}{lock}{relight}{place}\nGlobal style: {bible}"


# ══════════════════════════════════════════════════════════
# Phase 3. 클립 생성 (fan-out/fan-in)
# ══════════════════════════════════════════════════════════

def scene_seed(job_id: str, scene_id: int) -> int:
    """씬별로 다른 초기 노이즈를 준다. job_seed 하나를 전 씬이 공유하면(과거 설계
    의도: 그림체 흔들림 방지) 참조 이미지 전체를 첫 프레임 latent로 쓰는 STANDIN_STEPS=4
    같은 저스텝 조합에서 프롬프트 차이가 트레젝토리를 거의 못 갈라놓아 씬마다 다른
    텍스트를 줘도 모션이 수렴해버리는 사례 실측(2026-07-10, job
    f1be24f6-aaf7-4e39-bc0c-49ac3ca64e5c — 씬 1/2 프레임이 사실상 동일).

    2026-08-13: 시드 기반을 job_id에서 **고정 상수**로 바꿨다. job마다 UUID가 달라
    같은 입력이 매번 다른 추첨을 받았고, 스파이크가 확정한 그림을 재현할 방법이
    없었다(스파이크는 전 단계 seed=20260813 고정). 씬별 변화는 scene_id로 유지한다.
    AGENT_SCENE_SEED_BASE로 덮어쓰면 다른 추첨을 시도할 수 있다.
    """
    base = os.environ.get("AGENT_SCENE_SEED_BASE", "20260813").strip() or "20260813"
    return int(hashlib.sha1(f"{base}:{scene_id}".encode()).hexdigest()[:8], 16) % (2 ** 31)


def _generation_cache_key(scene: Scene) -> tuple:
    return (
        scene.get("mode") or "",
        scene.get("matched_image") or "",
        scene.get("image_role") or "",
    )


def _order_scenes_for_generation(scenes: list[Scene]) -> list[tuple[int, Scene]]:
    """Backend/cache locality only. Final video order is restored by scene id later."""
    return sorted(enumerate(scenes), key=lambda item: (_generation_cache_key(item[1]), item[0]))


def node_dispatch_generation(state: GraphState) -> list[Send] | str:
    """
    3-1: Send API로 비-LTX_FACEID 씬만 병렬 fan-out (LTX_FACEID는 node_generate_ltx_batch가
    이미 배치로 생성·병합했으므로 제외 — 다시 보내면 중복 생성됨).
    regen_target_ids가 있으면 해당 씬만, 없으면 전체 비-LTX_FACEID 씬 대상.
    실제 생성 순서는 같은 mode/ref끼리 묶어 ComfyUI 캐시 재사용률을 높인다.
    폴백 씬이 하나도 없으면(전부 LTX_FACEID) node_merge_clip_results를 거치지 않고
    곧장 checkpoint로 라우팅한다 — 빈 Send 리스트는 어떤 후속 노드도 스케줄하지 않아
    fan-in이 트리거되지 않는 정도가 아니라 그래프 실행이 아예 멈춘다(잡이 조용히
    idle로 정지) — 반드시 별도 처리해야 한다.
    """
    target_ids = state.get("regen_target_ids")
    scenes_to_run = (
        [s for s in state["scenes"] if s["id"] in target_ids]
        if target_ids else state["scenes"]
    )
    scenes_to_run = [s for s in scenes_to_run if s.get("mode") != "LTX_FACEID"]
    if not scenes_to_run:
        return "node_checkpoint_clip_approval"
    scenes_to_run = [s for _, s in _order_scenes_for_generation(scenes_to_run)]
    job_id = state["job_id"]
    return [Send("node_generate_one_clip", {
                "scene": s,
                "job_id": job_id,
                "seed": None if target_ids else scene_seed(job_id, s["id"]),
                "force_new": bool(target_ids),
            })
            for s in scenes_to_run]


async def node_generate_ltx_batch(state: GraphState) -> dict:
    """3-1: Face-ID 씬만 한 큐 배치로 제출해 LTX 모델 로드는 작업당 한 번만 수행한다.
    비-LTX_FACEID 폴백 씬은 이 노드가 직접 처리하지 않고, 뒤따르는 conditional edge
    (node_dispatch_generation → Send fan-out)로 넘긴다 — 씬별로 독립된 그래프 태스크로
    유지해야 /status가 배치 전체가 끝나기 전에 완료된 클립을 부분적으로 노출할 수 있다
    (SC1, langgraph/tests/test_status_clips.py). regen_target_ids는 여기서 지우지
    않는다 — node_dispatch_generation이 같은 값을 읽어서 regen 대상만 필터링해야 하기
    때문(node_merge_clip_results가 최종적으로 지운다 — 단, 전부 LTX_FACEID면 이 경로를
    건너뛰어 stale하게 남는다. 다음 regen이 Command(update=...)로 덮어쓰므로 무해하다)."""
    target_ids = set(state.get("regen_target_ids") or [])
    targets = [
        scene for scene in state["scenes"]
        if not target_ids or scene["id"] in target_ids
    ]
    face_scenes = [scene for scene in targets if scene.get("mode") == "LTX_FACEID"]

    batch_payload = [
        {
            **scene,
            "seed": scene_seed(state["job_id"], scene["id"])
            if not target_ids else int(time.time_ns() % (2 ** 31)),
        }
        for scene in face_scenes
    ]
    paths = await tools.generate_ltx_faceid_batch(state["job_id"], batch_payload)
    generated: list[Scene] = []
    for scene in face_scenes:
        metrics.clip_generated("LTX_FACEID")
        metrics.clip_steps("LTX_FACEID", tools.LTX_FACEID_STEPS)
        generated.append({
            **scene,
            "clip_path": paths[scene["id"]],
            "steps": tools.LTX_FACEID_STEPS,
            "quality_score": None,
            "quality_flag": "pending",
        })

    by_id = {scene["id"]: scene for scene in generated}
    merged = [by_id.get(scene["id"], scene) for scene in state["scenes"]]
    # clip_results는 Annotated[list, operator.add]라 그냥 []를 쓰면 existing + [] (no-op)이
    # 되어 리셋되지 않는다 — Overwrite로 감싸야 실제로 비워진다.
    return {
        "scenes": merged,
        "clip_results": Overwrite([]),
        "phase": "generating",
    }


async def node_generate_one_clip(payload: dict) -> dict:
    """3-1: 개별 씬 클립 생성 (AI). 자동 품질체크(3-2)는 제거 — 사람이 3-5에서 판단."""
    scene: Scene = payload["scene"]
    job_id: str = payload["job_id"]

    # 동시 실행 상한(_gen_semaphore): fan-out된 씬이 GPU를 동시에 물지 않게 게이팅.
    # 모든 백엔드가 이 단일 길목을 통과하므로 여기 하나만 걸면 :8188 합산 동시성이 잡힌다.
    relight = _needs_relight(scene.get("mood", "neutral"))  # M3-8: mood 괴리 씬만 재조명 노브
    async with tools._gen_semaphore:
        # PERSON_ASSEMBLY = 제품이 화면에 없는 인물 씬. 같은 조립 경로를 제품 없이
        # 탄다(배경 T2I → I2V). Face-ID 정원을 넘겨 22B에서 내려온 씬이다.
        # B노선(제품 오버레이): T2V로 사람 장면을 먼저 끝내고 제품을 그 위에 얹는다.
        # A노선(조립+I2V)은 제품을 첫 프레임에 박아 LTX에 넘기는데, LTX가 조건 이미지를
        # 첫 8프레임에만 쓰고 나머지를 새로 그려 제품을 지운다(job dd16ef56 실측).
        # 손에 쥔 씬은 제품이 손과 같이 움직여야 하므로 정적 오버레이가 물리적으로
        # 틀리다 — A노선에 남긴다. AGENT_PRODUCT_OVERLAY=0으로 전체를 A노선에 되돌린다
        # (음료 광고 baseline은 A노선에서 확정된 값이라 그때 필요하다).
        _hand_held = bool(scene.get("product_hand_held"))
        if scene["mode"] == "PRODUCT_OVERLAY" or (
                tools.PRODUCT_OVERLAY_ENABLED
                and scene["mode"] == "PRODUCT_ASSEMBLY" and not _hand_held):
            clip_path = await tools.generate_product_overlay_clip(
                job_id=job_id, scene_id=scene["id"], prompt=scene["prompt"],
                product_ref=scene["matched_image"],
                # product_hero는 classify가 씬 텍스트로 결정론적으로 채운다.
                # subject_type 폴백은 A노선에서 넘어온 씬(PRODUCT_ASSEMBLY)용이다.
                hero=bool(scene.get("product_hero",
                                    scene.get("subject_type") != "human")),
                duration=scene.get("duration", 2.0), seed=payload.get("seed"),
                force_new=payload.get("force_new", False),
                scene_context=scene.get("setting") or "",
            )
        elif scene["mode"] in ("PRODUCT_ASSEMBLY", "PERSON_ASSEMBLY"):
            clip_path = await tools.generate_product_scene_clip(
                job_id=job_id, scene_id=scene["id"], prompt=scene["prompt"],
                product_ref=(scene["matched_image"]
                             if scene["mode"] == "PRODUCT_ASSEMBLY" else None),
                face_ref=scene.get("face_id_ref"),
                # 히어로컷 = 사람이 안 나오는 제품 씬. face_ref 유무로 추론하면 안 된다 —
                # 인물 참조가 없는 job("시나리오만" 모드)은 전 씬이 face_ref=None이라
                # 사람이 나오는 씬까지 히어로컷으로 처리된다.
                hero=(scene.get("subject_type") != "human"),
                hand_held=bool(scene.get("product_hand_held")),
                duration=scene.get("duration", 2.0), seed=payload.get("seed"),
                negative_prompt=scene.get("negative_prompt"),
                # 배경에는 장소·조명만 넘긴다(동작 서술을 넣으면 Kontext가 그 동작을
                # 그려버려 첫 프레임이 '동작 직전'이 아니게 된다).
                scene_context=", ".join(
                    v for v in (scene.get("setting"), scene.get("lighting")) if v),
                person_appearance=scene.get("person_appearance") or "",
                force_new=payload.get("force_new", False),
            )
        elif scene["mode"] == "SUBJECT_REF":
            clip_path = await tools.generate_subject_ref_clip(
                job_id=job_id, scene_id=scene["id"], prompt=scene["prompt"],
                ref_image=scene["matched_image"], duration=scene.get("duration", 2.0),
                seed=payload.get("seed"), force_new=payload.get("force_new", False),
                relight=relight,
            )
        elif scene["mode"] == "STANDIN":       # 참조-얼굴 씬 → ComfyUI Stand-In (:8188)
            clip_path = await tools.generate_standin_clip(
                job_id=job_id,
                scene_id=scene["id"],
                prompt=scene["prompt"],
                ref_image=scene["matched_image"],
                duration=scene.get("duration", 2.0),
                seed=payload.get("seed"),
                force_new=payload.get("force_new", False),
                relight=relight,
            )
        else:                                # T2V/I2V 폴백 → LTX-13B-distilled (:8188)
            if scene["mode"] == "I2V":
                clip_path = await tools.generate_i2v_fallback_clip(
                    job_id=job_id,
                    scene_id=scene["id"],
                    prompt=scene["prompt"],
                    matched_image=scene["matched_image"],
                    duration=scene.get("duration", 2.0),
                    seed=payload.get("seed"),
                    force_new=payload.get("force_new", False),
                    negative_prompt=scene.get("negative_prompt"),
                )
            else:                            # T2V
                clip_path = await tools.generate_t2v_clip(
                    job_id=job_id,
                    scene_id=scene["id"],
                    prompt=scene["prompt"],
                    duration=scene.get("duration", 2.0),
                    seed=payload.get("seed"),
                    force_new=payload.get("force_new", False),
                )

    # 클립당 step 수는 모드에 따라 결정적: LTX(T2V/I2V 폴백)=LTX13B_STEPS,
    # ComfyUI(STANDIN/SUBJECT_REF)=STANDIN_STEPS. 영상당 합산은 final_render에서.
    steps = (tools.STANDIN_STEPS if scene["mode"] in ("STANDIN", "SUBJECT_REF")
             else tools.LTX13B_STEPS)
    metrics.clip_generated(scene["mode"])
    metrics.clip_steps(scene["mode"], steps)
    updated_scene: Scene = {
        **scene,
        "clip_path": clip_path,
        "steps": steps,
        "quality_score": None,
        "quality_flag": "pending",
    }
    # clip_results는 Annotated[list, operator.add] 이므로 fan-in 시 자동 병합됨
    return {"clip_results": [updated_scene]}


def node_merge_clip_results(state: GraphState) -> dict:
    """fan-in 이후 scenes를 최신 clip_results로 갱신 (재생성된 씬만 덮어쓰기)
    clip_results는 Annotated[list, operator.add]라 []를 그대로 반환하면 existing + []
    (no-op)이라 실제로 비워지지 않는다 — 다음 생성 사이클(regen)에서 이전 사이클 항목이
    남아 /status의 clips_done/clips가 부풀거나 중복 URL을 노출한다. Overwrite로 감싸
    실제 리셋을 강제한다."""
    result_by_id = {s["id"]: s for s in state["clip_results"]}
    merged = [result_by_id.get(s["id"], s) for s in state["scenes"]]
    return {"scenes": merged, "clip_results": Overwrite([]), "regen_target_ids": [], "phase": "generating"}


def node_checkpoint_clip_approval(state: GraphState) -> Command:
    """
    checkpoint 3-5 (필수): 클립별 승인.
    - 3-3 원칙 반영: 재생성은 AI가 자동으로 하지 않고, 사람이 regen 대상을 지정해야만 루프 진입.
    """
    decision = interrupt({
        "checkpoint": "3-5_clip_approval",
        "message": "각 씬 클립을 확인해주세요. low_quality로 표시된 씬은 재확인 권장.",
        "scenes": state["scenes"],
    })
    # decision 예시:
    # {"action": "approve_all"}
    # {"action": "regenerate", "scene_ids": [2, 4]}
    action = decision.get("action")

    if action == "approve_all":
        approved_scenes = [{**s, "approved": True} for s in state["scenes"]]
        return Command(goto="node_edit_concat", update={"scenes": approved_scenes})

    elif action == "regenerate":
        target_ids = decision["scene_ids"]
        metrics.regeneration(len(target_ids))
        return Command(
            goto="node_generate_ltx_batch",
            update={"regen_target_ids": target_ids},
        )

    else:
        # 승인 대기 상태 유지 (잘못된 입력 등) — 같은 체크포인트 재진입
        return Command(goto="node_checkpoint_clip_approval")


# ══════════════════════════════════════════════════════════
# Phase 4. 편집 & 연결
# ══════════════════════════════════════════════════════════

async def node_edit_concat(state: GraphState) -> dict:
    """4-1, 4-2, 4-4: 순서 배치 + 트랜지션 + concat 프리뷰 (AI)"""
    scenes = sorted(state["scenes"], key=lambda s: s["id"])
    clip_paths = [s["clip_path"] for s in scenes]

    # 무드 기반 트랜지션 결정 (간단 규칙 예시)
    transitions = [
        "crossfade" if s["mood"] in ("calm", "sad") else "cut"
        for s in scenes[1:]
    ]

    preview_path = str(tools.job_dir(state["job_id"]) / "preview_low.mp4")
    # LTX_FACEID 씬이 하나라도 있으면 concat 타겟 해상도를 그 네이티브 해상도(1024x576)로
    # 올린다 — 기본 WIDTH/HEIGHT(T2V fast/quality 프리셋, 예: 832x480)로 그대로 스케일하면
    # 이미 더 좋은 화질로 뽑힌 LTX 클립이 합치기 단계에서 다운스케일돼 얼굴 디테일이
    # 뭉개진다(Face-ID 화질 손실 원인, .harness/STATE.md 참고).
    if any(s.get("mode") == "LTX_FACEID" for s in scenes):
        width, height = tools.LTX_FACEID_WIDTH, tools.LTX_FACEID_HEIGHT
    else:
        width, height = tools.WIDTH, tools.HEIGHT
    # ffmpeg는 동기 subprocess → 스레드로 오프로드해 이벤트루프(모든 :8700 엔드포인트가
    # 공유)를 막지 않는다. 안 그러면 인코딩 중 /status·/jobs가 응답 못해 OWU가 ReadTimeout.
    await asyncio.to_thread(tools.ffmpeg_concat, clip_paths, transitions, preview_path, width, height)

    return {"edited_preview_path": preview_path}


# ══════════════════════════════════════════════════════════
# Phase 5. 최종 출력
# ══════════════════════════════════════════════════════════

async def node_final_render(state: GraphState) -> dict:
    """5-1, 5-2: 고해상도 렌더링 + 포맷 변환 (AI, 사람 개입 없음)"""
    final_path = str(tools.job_dir(state["job_id"]) / "final.mp4")
    # Phase C에서 원본 클립 풀퀄 재인코딩 예정. 지금은 편집 프리뷰를 최종본으로 확정.
    import shutil
    shutil.copy(state["edited_preview_path"], final_path)
    started = state.get("started_at")
    duration = time.time() - started if started else None
    scenes = state.get("scenes") or []
    total_steps = sum(s.get("steps", 0) for s in scenes)
    metrics.video_finished(scenes=len(scenes), duration=duration, steps=total_steps)
    return {"final_video_path": final_path, "phase": "done"}
