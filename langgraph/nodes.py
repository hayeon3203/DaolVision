"""
Phase 1~5 노드 구현
- interrupt(): 사람 승인이 필요한 2개 체크포인트 (1-4, 3-5). 4-5 자막편집 게이트는 제외.
- Send: 씬별 클립 생성을 fan-out으로 병렬 처리
- Command(goto=...): 사람이 승인/재생성/반려를 선택한 뒤 그래프 흐름을 분기
"""
import asyncio
import hashlib
import json
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
    raw = await tools.call_llm(_IMG_QUERY_SYSTEM, request)
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
        q = _strip_face_emphasis_if_wide(q)
        if q:
            queries.append(q)
    queries = queries[:1]
    if not queries:
        raise ValueError("이미지 생성 요청을 이해하지 못했습니다. 표현을 조금 바꿔서 다시 시도해주세요.")
    # M2 전용 phase — 기존 5단계 스테퍼(planning/prompting/anchoring/generating/done)
    # 앞에 오는 별도 단계라 AgentPhaseStepper가 image_gen_used일 때만 조건부로 그린다.
    return {"image_queries": queries, "image_query": queries[0] if queries else "", "phase": "image_generating"}


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
    paths = await asyncio.gather(*[
        tools.generate_t2i_image(job_id, q, seed=seed, index=i)
        for i, q in enumerate(queries)
    ])
    paths = list(paths)
    return {"gen_image_paths": paths, "gen_image_path": paths[0], "phase": "image_generating"}


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
    })
    # decision 예시: {"approved": True} / {"feedback": "더 파랗게"}
    if decision.get("approved"):
        # 승인 이미지들을 참조 이미지로 주입 → 기존 caption_image·스마트 라우팅이 그대로 받음.
        # ref_captions에 생성 시 쓴 프롬프트를 그대로 채워 넣어 — 별도 vision 캡션 호출 없이 —
        # node_split_scenes가 어떤 이미지가 어떤 씬에 어울리는지 내용 기반으로 매칭하게 한다.
        job_id = state["job_id"]
        ref_names, ref_captions = [], {}
        for i, p in enumerate(paths):
            name = f"img_{i}.png"
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
        mentions = re.findall(r"img[_\s]?(\d+)(?:\.[a-z0-9]+)?", line, re.I)
        if mentions:
            candidate = f"img_{int(mentions[-1])}.png"
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
            except Exception:
                captions[fn] = ""   # 캡션 실패해도 파일명 기반으로 계속 진행
        out["ref_captions"] = captions
    return out


# mood는 트랜지션 규칙(node_edit_concat: calm/sad → crossfade)과 영어로 비교된다.
# LLM이 중국어/한국어 mood를 뱉으면 규칙이 영원히 미발동 → 영어 enum으로 강제 + 가드.
MOODS = ("calm", "sad", "neutral", "happy", "tense", "excited", "surprised")

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


def _normalise_scene_count(items: list, target: int = 4) -> list:
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
_NONHUMAN_HINTS = re.compile(
    r"\b(mascot|robot|android|product|logo|animal|creature|monster|toy|plush|doll|figurine|"
    r"cartoon|cartoonish|emoji|blob|gadget|device|bottle|package|parcel|box|carton|"
    r"food|snack|fruit|plant|flower|vehicle|car|truck|drone|cat|dog|bird|fish|dragon)\b|"
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


# 씬 텍스트(한/영)에서 피사체 종류 판정 — 캡션(gemma) 불필요. M3-6 이전 결정론적 경로 복원.
# 비인간 명사가 있으면 nonhuman을 우선(마스코트/로봇/제품 씬), 아니면 사람 명사로 human.
_NONHUMAN_TEXT = re.compile(
    r"마스코트|캐릭터|로봇|안드로이드|제품|상품|인형|로고|동물|고양이|강아지|개구리|곰|토끼|새|물고기|"
    r"드론|자동차|기계|사물|음식|과일|식물|꽃|"
    r"\b(mascot|robot|android|product|logo|animal|creature|toy|doll|drone|vehicle|plant|character)\b", re.I)
_HUMAN_TEXT = re.compile(
    r"여성|남성|여자|남자|사람|인물|직원|회사원|아이|소년|소녀|남녀|그녀|그는|인간|"
    r"\b(woman|man|person|people|boy|girl|worker|human|lady|male|female)\b", re.I)


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
        "너는 애니메이션 스토리보드 작가다. 주어진 시나리오를 정확히 4개 씬으로 분할하라. "
        "반드시 4개의 객체만 반환하고, 시나리오의 시작부터 끝까지 시간 순서대로 고르게 배분하라. "
        "text는 반드시 입력 시나리오와 '같은 언어'로 써라 — 다른 언어(특히 중국어/영어)로 "
        "번역하지 마라. 시나리오 문장을 임의로 요약·창작하지 말고 원문의 내용과 순서를 보존하라. "
        "한 문장(주어+목적어+동사)을 문법 단위 중간에서 두 씬으로 쪼개지 마라. "
        "나쁜 예: 원문 '우주선이 지구를 향해 천천히 다가간다.' → 씬A text='우주선이 지구를', "
        "씬B text='향해 천천히 다가간다.' (틀림 — 목적어 '지구'와 동사가 분리돼 두 씬 다 "
        "무슨 장면인지 알 수 없다). 좋은 예: 씬 text='우주선이 지구를 향해 천천히 다가간다.' "
        "그대로 한 씬에 담고, 부족한 씬 개수는 다른 씬에서 다른 각도·디테일로 채운다. "
        "각 씬의 text는 그 자체로 '누가/무엇이 무엇을 하는지' 완결되게 읽혀야 한다. 문장 수가 "
        "4개보다 적으면 한 문장을 다른 각도·디테일로 확장해 채우고, 많으면 의미가 이어지는 "
        "문장끼리 묶어서 4개로 만들어라 — 절대 문장을 반으로 자르지 마라. "
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
    if scenes_raw is None or not isinstance(scenes_raw, list) or len(scenes_raw) != 4 or fractured:
        if scenes_raw is None:
            instruction = (
                "이전 응답은 문법이 깨진 JSON이었다(배열이나 객체의 괄호가 안 맞았다). "
                "같은 내용을 반복해서 출력하지 말고, 배열은 반드시 '['로 열어 ']'로 정확히 "
                "닫고 각 객체도 '{'...'}' 한 쌍으로 정확히 닫아라. 정확히 4개 씬으로 나누고 "
                "JSON 배열 외에는 아무것도 출력하지 마라."
            )
        elif fractured:
            instruction = (
                "이전 결과는 원문의 한 문장(주어+목적어+동사)을 씬 경계에서 중간에 잘랐다 "
                "— 예: '우주선이 지구를' / '향해 다가간다'처럼 목적어와 동사가 다른 씬으로 "
                "분리됐다. 문장을 자르지 말고 각 씬 text가 완결된 문장(또는 완결된 절)이 "
                "되도록 다시 나눠라. 내용과 시간 순서는 보존하되, 문장 수가 4개보다 적으면 "
                "같은 문장을 다른 각도·디테일로 확장해 채워라. JSON 배열 외에는 아무것도 "
                "출력하지 마라."
            )
        else:
            instruction = (
                "이전 결과의 내용과 시간 순서를 보존하면서 정확히 4개 씬으로 다시 나눠라. "
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
        # subject_type 진실원천: 씬 텍스트 키워드(캡션 불필요, M3-6 이전 동작) > 캡션 > LLM.
        # 7b가 subject_type을 자주 누락(→None)해 마스코트가 얼굴(STANDIN) 경로로 새던 회귀를 막는다.
        cap_type = _subject_type_from_caption(captions.get(matched, "")) if matched else None
        derived = _subject_type_from_text(s.get("text", "")) or cap_type
        if derived:
            subject_type = derived
        role = _normalise_image_role(matched, s.get("image_role"), subject_type)
        # duration clamp: 스텝시간이 프레임 수에 초선형이라 긴 씬이 속도를 지배한다.
        # LLM 출력만 제한하고, 사람이 1-4 게이트에서 고친 값은 그대로 존중한다.
        try:
            dur = float(s.get("duration") or 3.0)
        except (TypeError, ValueError):
            dur = 3.0
        scenes.append({
            "id": i + 1,
            "text": s["text"],
            "duration": min(max(dur, 2.0), 3.0),
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
        for sc in scenes:
            sc["matched_image"] = only_ref
            sc["subject_type"] = st
            sc["image_role"] = role
    elif len(ref_set) > 1:
        # 매칭 누락 결정론적 보정: 9b가 씬↔이미지 matched_image를 랜덤 누락(여자 씬이 None으로
        # 새 사람 생성 → 얼굴 일관성 붕괴)하던 문제를 캡션 기반 per-ref 종류로 메운다. 씬의
        # subject_type과 같은 종류의 참조가 정확히 하나면 그 참조로 매칭한다(모호하면 건드리지 않음).
        ref_types = {fn: _subject_type_from_caption(captions.get(fn, "")) for fn in ref_set}
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


async def _make_style_bible(state: GraphState) -> str:
    """전체 시나리오 기준 공통 스타일 규격 1개 생성. 실패 시 기존 토큰으로 폴백.
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
          "saturation, contrast character — e.g. desaturated teal-orange, warm film "
          "stock, bleach-bypass), and LENS STYLE (focal length feel, depth-of-field "
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

          "Do not standardize character identity, anatomy, clothing, or appearance. "
          "Output only a compact comma-separated English style specification "
          "under 130 words. No preamble, quotes, or markdown."
    )
    user_prompt = json.dumps({
        "script": state["script_text"],
        "scenes": [s["text"] for s in state["scenes"]],
        "characters": state.get("ref_captions") or {},
        **({"image_anchor_prompt": image_query} if image_query else {}),
    }, ensure_ascii=False)
    try:
        bible = tools.clean_llm_prompt(await tools.call_llm(system_prompt, user_prompt))
        return bible if bible else STYLE_LOCK_TOKEN
    except Exception:
        return STYLE_LOCK_TOKEN


_LIGHTING_SYSTEM = (
    "You are a cinematographer + continuity supervisor for a short video. The art style (화풍) is "
    "FIXED across scenes — you do NOT touch it. For EACH scene output two things: "
    "(1) lighting — one short English clause: exposure/brightness, key-light quality, shadow depth, "
    "contrast, color temperature, translating the scene's MOOD. A dark/sad/tense beat MUST be low-key "
    "and genuinely dim; a joyful beat bright and high-key. Never inherit a bright reference image's "
    "brightness. No character appearance/clothing/pose — lighting only. "
    "(2) setting — the scene's physical LOCATION/background in the script's own language. If this "
    "scene continues in the SAME place as the previous scene, output an empty string \"\" for setting "
    "(it inherits the previous location). Only fill setting when the location changes. When in doubt, "
    "fill it in rather than leaving it empty — scenes that name a different physical environment "
    "(e.g. a launch pad vs. open space vs. an alien planet's surface vs. re-entry through the "
    "atmosphere) are almost always DIFFERENT settings, even if no location word is repeated. "
    'Output ONLY a JSON object mapping each scene id (string) to {"lighting": "...", "setting": "..."}, '
    'e.g. {"1": {"lighting": "low-key dim, deep shadows, cool cast", "setting": "어두운 사무실"}, '
    '"2": {"lighting": "sudden bright key light", "setting": ""}}. No preamble, no markdown.'
)


async def _make_scene_context(state: GraphState) -> tuple[dict[int, str], dict[int, str]]:
    """M3-7 + 배경 연속성: 씬별 재조명 큐 + 장소(setting)를 한 번의 focused LLM 호출로 생성.
    bible(불변 화풍)과 분리. setting은 빈값이면 직전 씬 장소를 forward-fill(연속성).
    이전엔 setting을 giant split 호출에 얹었는데 9b가 run마다 누락 → focused 호출로 이관해 안정화.
    반환: (lighting_map, setting_map). 실패/누락 씬은 호출부에서 폴백."""
    scenes = state.get("scenes") or []
    user_prompt = json.dumps({
        "script": state.get("script_text", ""),
        "scenes": [{"id": s.get("id"), "text": s.get("text", ""), "mood": s.get("mood", "neutral")}
                   for s in scenes],
    }, ensure_ascii=False)
    lighting: dict[int, str] = {}
    setting: dict[int, str] = {}
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
        for k, v in (raw or {}).items():
            if isinstance(v, dict):
                lit = (v.get("lighting") or "").strip() if isinstance(v.get("lighting"), str) else ""
                setg = (v.get("setting") or "").strip() if isinstance(v.get("setting"), str) else ""
            else:  # 구형/축약 응답: 문자열이면 lighting으로만 취급
                lit, setg = ((v or "").strip() if isinstance(v, str) else ""), ""
            if lit:
                lit_map[int(k)] = lit
            if setg:
                set_map[int(k)] = setg
        lighting = lighting or lit_map   # 첫 시도의 조명은 보존
        setting = set_map
        if len(setting) >= min_filled:    # 최소 절반 이상 장소를 얻으면 종료
            break
    # 장소 forward-fill: 빈(=이어지는) 씬은 직전 씬 장소 상속. 씬 순서대로.
    prev = ""
    for s in scenes:
        sid = s.get("id")
        if setting.get(sid):
            prev = setting[sid]
        elif prev:
            setting[sid] = prev
    return lighting, setting


async def node_generate_prompts(state: GraphState) -> dict:
    """2-1, 2-2: 프롬프트 생성 + 스타일 고정 + 이미지 스마트 라우팅 (AI).
    - 스타일 바이블: job당 1회 생성, 모든 씬 프롬프트 끝에 주입 → 분위기/톤 통일.
    - image_role=start/ref → Stand-In 얼굴 크롭으로 사람 identity 유지.
    - image_role=ref → Stand-In으로 사람 얼굴 identity 유지.
    - image_role=character_ref → Subject Ref로 마스코트/제품 전체 identity 유지.
    - 이미지 없음      → T2V.
    """
    captions = state.get("ref_captions") or {}
    wardrobe_locks = state.get("wardrobe_locks") or {}
    bible = state.get("style_bible") or await _make_style_bible(state)

    # M3-7 재조명 + 배경 연속성: 씬별 조명 큐 + 장소(setting)를 한 번의 focused 호출로 생성
    # (추가 LLM 호출 없음 — 기존 조명 호출에 fold). 이미 둘 다 있으면(재생성) 재호출 생략.
    have_ctx = all(s.get("lighting") and s.get("setting") for s in state["scenes"])
    lighting_map, setting_map = (({}, {}) if have_ctx else await _make_scene_context(state))

    updated_scenes = []
    for scene in state["scenes"]:
        # 이 씬의 장소를 주입(빈값이면 기존/직전 상속값 유지) → _scene_prompt_user가 배경으로 씀.
        scene = {**scene, "setting": setting_map.get(scene.get("id")) or scene.get("setting", "")}
        img = scene.get("matched_image")
        role = scene.get("image_role")
        subject_ref = bool(img) and role == "character_ref" and tools.USE_STANDIN
        standin = bool(img) and role in ("start", "ref") and tools.USE_STANDIN
        wardrobe = wardrobe_locks.get(img, "") if standin else ""
        # 보존(identity·화풍)과 분리된 '적응' 축: 이 씬의 재조명 큐.
        cue = (lighting_map.get(scene.get("id"))
               or scene.get("lighting")
               or _mood_to_lighting(scene.get("mood", "neutral")))

        has_human_subject = bool(standin or subject_ref or scene.get("subject_type") == "human")
        raw_prompt = _strip_echoed_bible(tools.clean_llm_prompt(
            await tools.call_llm(_scene_prompt_system(standin or subject_ref, bool(wardrobe), has_human_subject),
                                 _scene_prompt_user(scene, bible, wardrobe, cue))), bible)

        if subject_ref:
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
        elif img and role == "start":        # Stand-In off일 때만 I2V 폴백
            mode = "I2V"
            full_prompt = f"{raw_prompt}, {bible}"
        elif img:                           # ref이지만 Stand-In off → T2V + 캐릭터록 텍스트
            mode = "T2V"
            desc = captions.get(img, "")
            lock = f" The main character: {desc}." if desc else ""
            full_prompt = f"{raw_prompt}.{lock} {bible}"
        else:                               # 이미지 없음
            mode = "T2V"
            full_prompt = f"{raw_prompt}, {bible}"

        # M3-7: 씬 재조명 큐를 결정적으로 프롬프트 끝에 못박는다 — rewrite LLM이 조명을
        # 약하게 반영해도 어두운 씬은 실제로 저조도 지시가 남는다(참조 밝기 상속 방지).
        full_prompt = f"{full_prompt} Scene lighting and atmosphere: {cue}."
        updated_scenes.append({**scene, "prompt": full_prompt, "mode": mode, "lighting": cue})

    return {"scenes": updated_scenes, "style_bible": bible, "phase": "prompting"}


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
        return {
            **scene,
            "face_id_ref": face_id_ref,
            "mode": "LTX_FACEID" if face_id_ref else scene.get("mode", "T2V"),
        }

    classified = [classify(scene) for scene in scenes]
    return {"scenes": classified, "phase": "anchoring"}


def _scene_prompt_system(standin: bool, has_wardrobe: bool = False, has_human_subject: bool = True) -> str:
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
            # Task 3.2 눈판정으로 확정된 기본값(STATE.md Task 3.2/5.2 재설계): 클로즈업은
            # identity 전이 신뢰도와 배경 퀄리티 둘 다 떨어뜨린다 — wide shot으로 고정.
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
    f1be24f6-aaf7-4e39-bc0c-49ac3ca64e5c — 씬 1/2 프레임이 사실상 동일)."""
    return int(hashlib.sha1(f"{job_id}:{scene_id}".encode()).hexdigest()[:8], 16) % (2 ** 31)


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
        if scene["mode"] == "SUBJECT_REF":
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
