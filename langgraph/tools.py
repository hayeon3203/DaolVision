"""
실제 인프라 호출부 (GB10 실서버 배선).

- LLM: Ollama 네이티브 chat API (`/api/chat`), NVIDIA Nemotron 3 Nano 4B GGUF
- 비디오: LTX-Video-0.9.8-13B-distilled via ComfyUI (:8188) — T2V/I2V 폴백, Stand-In(참조-얼굴)
- ffmpeg: concat + xfade + 자막 번인

nodes.py는 이 파일의 함수 시그니처에만 의존한다. 엔드포인트/모델이 바뀌면 여기만 교체.
"""
import asyncio
import base64
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from io import BytesIO

import httpx
from PIL import Image, ImageOps

import oom_orchestrator as oom
import style_presets

# ── 환경 설정 ────────────────────────────────────────────────
OLLAMA_URL = os.environ.get("AGENT_OLLAMA_URL", "http://127.0.0.1:11434/api/chat")
OLLAMA_GEN_URL = OLLAMA_URL.replace("/api/chat", "/api/generate")  # 비전 캡션용(images 지원)
LLM_MODEL = os.environ.get(
    "AGENT_LLM_MODEL",
    "hf.co/nvidia/NVIDIA-Nemotron-3-Nano-4B-GGUF:Q4_K_M",
)
VISION_MODEL = os.environ.get("AGENT_VISION_MODEL", "qwen3.5:9b")  # qwen3.5:9b = text+vision 겸용. qwen2.5:7b+gemma3:4b 대체. run_agent.sh와 동일 기본값
T2I_URL = os.environ.get("AGENT_T2I_URL", "http://127.0.0.1:8501")
KOKORO_URL = os.environ.get("AGENT_KOKORO_URL", "http://127.0.0.1:8503")
CHATTERBOX_URL = os.environ.get("AGENT_CHATTERBOX_URL", "http://127.0.0.1:8504")
CHATTERBOX_NARRATION_REFERENCE = Path(
    os.environ.get(
        "AGENT_CHATTERBOX_NARRATION_REFERENCE",
        str(
            Path(__file__).resolve().parents[1]
            / "private"
            / "tts"
            / "voices"
            / "narrator_cc0"
            / "reference.wav"
        ),
    )
)

# ── ComfyUI Stand-In (참조-이미지 씬의 얼굴 일관성 경로) ──────────
COMFYUI_URL = os.environ.get("AGENT_COMFYUI_URL", "http://127.0.0.1:8188")
# 참조 이미지가 있는 씬을 Stand-In(ComfyUI)으로 보낼지 스위치. off면 전부
# generate_t2v_clip/generate_i2v_fallback_clip(둘 다 ComfyUI :8188)로.
USE_STANDIN = os.environ.get("AGENT_USE_STANDIN", "1").lower() not in ("0", "false", "no", "")
# 0이면 참조 이미지 캡션(gemma vision) 생략 → 이미지↔씬은 사람이 지정. gemma 미로드로 GPU 압박↓.
CAPTION_REFS = os.environ.get("AGENT_CAPTION_REFS", "1").lower() not in ("0", "false", "no", "")
STANDIN_STEPS = int(os.environ.get("AGENT_STANDIN_STEPS", "4"))     # lightx2v distill: 4~8
# Stand-In 기반 Wan2.1 14B의 네이티브 fps=16. 24fps 생성은 프레임 50% 낭비(스텝시간이
# 프레임 수에 초선형). 편집 단계에서 DEFAULT_FPS로 정규화하므로 다른 클립과 섞여도 안전.
STANDIN_FPS = int(os.environ.get("AGENT_STANDIN_FPS", "16"))
# I2V-14B 체크포인트가 480P 전용(이름 그대로) — LTX T2V 경로의 WIDTH/HEIGHT(quality
# 프리셋 기본 1280x704)를 그대로 쓰면 해상도 초과로 100초 목표를 못 맞춤(실측 65s→159s).
# 이 경로만 별도로 832x480 고정.
STANDIN_WIDTH = int(os.environ.get("AGENT_STANDIN_WIDTH", "832"))
STANDIN_HEIGHT = int(os.environ.get("AGENT_STANDIN_HEIGHT", "480"))
# M3-8 relight 노브: 참조 첫프레임 latent가 조명/노출/배경을 잠그는 강도. 씬 mood가 참조와
# 크게 다른 씬만(호출부 nodes.py가 판단) 낮춰 프롬프트대로 재조명되게 한다 — 1.0이면
# 밝은 참조가 어두운 씬도 밝게 굳히고 참조 배경(흐릿한 portrait bg)까지 전파됨. identity와
# trade-off라 실측 튜닝값. ref: standin-identity-only-not-style, PLAN M3-8.
STANDIN_RELIGHT_STRENGTH = float(os.environ.get("AGENT_STANDIN_RELIGHT_STRENGTH", "0.55"))
STANDIN_RELIGHT_NOISE_AUG = float(os.environ.get("AGENT_STANDIN_RELIGHT_NOISE_AUG", "0.02"))
# M3-10: face(standin_t2v) 경로 튜닝 노브. identity LoRA(node69)↑면 얼굴 유지↑·배경 자유↓,
# distill LoRA(node71)는 저스텝 품질. 코드 자동결정 말고 실측 A/B로 조정. PLAN M3-10.
STANDIN_FACE_LORA_STRENGTH = float(os.environ.get("AGENT_STANDIN_FACE_LORA_STRENGTH", "1.0"))
STANDIN_DISTILL_LORA_STRENGTH = float(os.environ.get("AGENT_STANDIN_DISTILL_LORA_STRENGTH", "0.6"))
# face 경로 LoRA 노드(standin_t2v.json 전용): 69=Stand-In identity, 71=lightx2v distill.
_SI_FACE_LORA = {"identity": "69", "distill": "71"}


def _relight_embed_overrides(relight: bool) -> dict:
    """M3-8: relight 씬이면 WanVideoImageToVideoEncode의 latent 잠금을 완화하는 override.
    미적용(참조와 mood 유사) 씬은 빈 dict = 기존 1.0 동작 유지."""
    if not relight:
        return {}
    return {
        "start_latent_strength": STANDIN_RELIGHT_STRENGTH,
        "end_latent_strength": STANDIN_RELIGHT_STRENGTH,
        "noise_aug_strength": STANDIN_RELIGHT_NOISE_AUG,
    }
STANDIN_EXEC_TIMEOUT = float(os.environ.get("AGENT_STANDIN_EXEC_TIMEOUT",
                                             os.environ.get("AGENT_STANDIN_TIMEOUT", "1800")))
STANDIN_QUEUE_TIMEOUT = float(os.environ.get("AGENT_STANDIN_QUEUE_TIMEOUT", "86400"))
STANDIN_MISSING_TIMEOUT = float(os.environ.get("AGENT_STANDIN_MISSING_TIMEOUT", "30"))
# 클립 생성 동시 실행 상한. Send fan-out은 씬들을 한 이벤트 루프에서 동시에 돌리므로
# 상한이 없으면 LTX T2V/I2V 폴백 + Stand-In/Subject-Ref(둘 다 :8188 ComfyUI) 확산이
# 같은 순간 피크를 쳐 GB10 통합메모리 OOM.
# 1=완전 직렬(기본), 2=백엔드당 하나. ref: gb10-gpu-contention-comfyui-ollama.
MAX_CONCURRENT_CLIPS = int(os.environ.get("AGENT_MAX_CONCURRENT_CLIPS", "1"))
_gen_semaphore = asyncio.Semaphore(MAX_CONCURRENT_CLIPS)  # 실행 루프는 await 시점에 바인딩(py3.10+)
_WORKFLOW_DIR = Path(__file__).resolve().parent / "comfyui_workflows"
# subject_ref(비인간/제품): 참조 전체를 첫프레임 latent로 → 실루엣·화풍 보존, 배경 잠금.
I2V_WORKFLOW = _WORKFLOW_DIR / "i2v_14b.json"
# face(사람): 얼굴 identity만 주입(Stand-In), 배경은 프롬프트 100%(빈 embeds). M3-9.
FACE_WORKFLOW = _WORKFLOW_DIR / "standin_t2v.json"
LTX_FACEID_WORKFLOW = _WORKFLOW_DIR / "ltx_faceid_api.json"
LTX_FACEID_WIDTH = int(os.environ.get("AGENT_LTX_FACEID_WIDTH", "1024"))
LTX_FACEID_HEIGHT = int(os.environ.get("AGENT_LTX_FACEID_HEIGHT", "576"))
LTX_FACEID_FPS = int(os.environ.get("AGENT_LTX_FACEID_FPS", "24"))
LTX_FACEID_STEPS = int(os.environ.get("AGENT_LTX_FACEID_STEPS", "8"))
# node 129(LTXIdentityOverlapConditioning)의 identity 강도 노브. 기본값 1.0은 워크플로
# JSON 원본값 그대로 — 얼굴 일관성이 아쉬우면 1.2~1.5로 올려본다(배경/포즈 자유도와 trade-off).
LTX_FACEID_GUIDANCE = float(os.environ.get("AGENT_LTX_FACEID_GUIDANCE", "1.0"))
# 호환 alias (구 이름) — 기본 경로는 i2v.
STANDIN_WORKFLOW = I2V_WORKFLOW
# API 그래프 주입 노드 ID (comfyui_workflows/README.md 표 참조). 두 워크플로는 dims 노드만
# 다르다: i2v=105(WanVideoImageToVideoEncode), face=103(WanVideoEmptyEmbeds).
_SI = {
    "image": "58", "prompt": "16", "embeds": "105", "sampler": "27", "output": "74",
}
_SI_FACE = {
    "image": "58", "prompt": "16", "embeds": "103", "sampler": "27", "output": "74",
}

JOBS_DIR = Path(os.environ.get("AGENT_JOBS_DIR",
                               str(Path(__file__).resolve().parent / "jobs")))
JOBS_DIR.mkdir(parents=True, exist_ok=True)
COMFY_PROMPTS_DB = JOBS_DIR / "comfy_prompts.db"
_PROMPT_DB_LOCK = threading.Lock()

VIDEO_PRESETS = {
    "quality": {"width": 1280, "height": 704, "steps": 20},
    "fast": {"width": 832, "height": 480, "steps": 10},
}
VIDEO_PRESET = os.environ.get("AGENT_VIDEO_PRESET", "quality").lower()
if VIDEO_PRESET not in VIDEO_PRESETS:
    raise ValueError(f"unknown AGENT_VIDEO_PRESET={VIDEO_PRESET!r}; choose quality or fast")
_PRESET = VIDEO_PRESETS[VIDEO_PRESET]
DEFAULT_FPS = int(os.environ.get("AGENT_FPS", "24"))
WIDTH = int(os.environ.get("AGENT_WIDTH", str(_PRESET["width"])))
HEIGHT = int(os.environ.get("AGENT_HEIGHT", str(_PRESET["height"])))


def _prompt_db() -> sqlite3.Connection:
    """ComfyUI 제출 상태를 LangGraph 노드와 독립적으로 즉시 영속화한다."""
    conn = sqlite3.connect(COMFY_PROMPTS_DB, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS comfy_prompts (
            prompt_id TEXT PRIMARY KEY, job_id TEXT NOT NULL,
            scene_id INTEGER NOT NULL, request_key TEXT NOT NULL,
            status TEXT NOT NULL, output_filename TEXT, error TEXT,
            submitted_at REAL NOT NULL, execution_started_at REAL,
            completed_at REAL, updated_at REAL NOT NULL
        )
    """)
    conn.execute("""CREATE INDEX IF NOT EXISTS idx_comfy_prompts_recovery
                    ON comfy_prompts(job_id, scene_id, request_key, submitted_at DESC)""")
    return conn


def _save_prompt(prompt_id: str, job_id: str, scene_id: int, request_key: str) -> None:
    now = time.time()
    with _PROMPT_DB_LOCK, _prompt_db() as conn:
        conn.execute("""INSERT OR REPLACE INTO comfy_prompts
            (prompt_id, job_id, scene_id, request_key, status, submitted_at, updated_at)
            VALUES (?, ?, ?, ?, 'queued', ?, ?)""",
            (prompt_id, job_id, scene_id, request_key, now, now))


def _update_prompt(prompt_id: str, status: str, *, output_filename: str | None = None,
                   error: str | None = None, execution_started_at: float | None = None) -> None:
    completed = time.time() if status in ("completed", "error") else None
    with _PROMPT_DB_LOCK, _prompt_db() as conn:
        conn.execute("""UPDATE comfy_prompts SET status=?,
            output_filename=COALESCE(?, output_filename), error=?,
            execution_started_at=COALESCE(?, execution_started_at),
            completed_at=COALESCE(?, completed_at), updated_at=? WHERE prompt_id=?""",
            (status, output_filename, error, execution_started_at, completed, time.time(), prompt_id))


def _recoverable_prompt(job_id: str, scene_id: int, request_key: str):
    with _PROMPT_DB_LOCK, _prompt_db() as conn:
        return conn.execute("""SELECT * FROM comfy_prompts
            WHERE job_id=? AND scene_id=? AND request_key=? AND status != 'error'
            ORDER BY submitted_at DESC LIMIT 1""", (job_id, scene_id, request_key)).fetchone()


def recoverable_comfy_jobs() -> list[str]:
    with _PROMPT_DB_LOCK, _prompt_db() as conn:
        rows = conn.execute("""SELECT DISTINCT job_id FROM comfy_prompts
            WHERE status IN ('queued', 'running', 'completed')""").fetchall()
    return [row[0] for row in rows]


def comfy_job_progress(job_id: str) -> dict:
    with _PROMPT_DB_LOCK, _prompt_db() as conn:
        rows = conn.execute("""SELECT scene_id, prompt_id, status, error
            FROM comfy_prompts WHERE job_id=? ORDER BY submitted_at""", (job_id,)).fetchall()
    latest = {}
    for row in rows:
        latest[row["scene_id"]] = dict(row)
    return {"scenes": list(latest.values())}


def job_dir(job_id: str) -> Path:
    d = JOBS_DIR / job_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def refs_dir(job_id: str) -> Path:
    d = job_dir(job_id) / "refs"
    d.mkdir(parents=True, exist_ok=True)
    return d


async def _unload_llm_backend() -> None:
    """씬분할/캡션 두 Ollama 모델을 명시적으로 언로드(keep_alive=0). Task 4.4 —
    2.4 실측상 이 언로드 없이 다음 backend(T2I 등)로 전환하면 이중 상주로 OOM."""
    async with httpx.AsyncClient(timeout=30) as client:
        for model in {LLM_MODEL, VISION_MODEL}:
            try:
                await client.post(OLLAMA_GEN_URL, json={"model": model, "keep_alive": 0})
            except httpx.HTTPError:
                pass  # 이미 언로드됐거나 서버 일시 불가 — 다음 로드가 알아서 재적재


oom.register_unload("llm", _unload_llm_backend)


# ── LLM ─────────────────────────────────────────────────────
async def call_llm(system_prompt: str, user_prompt: str) -> str:
    async with oom.phase("llm"), httpx.AsyncClient(timeout=180) as client:
        resp = await client.post(
            OLLAMA_URL,
            json={
                "model": LLM_MODEL,
                "stream": False,
                # Ollama 모델별 지원 여부와 무관하게 비사고 모드로 고정한다.
                # JSON-only 씬 분할에 숨은 CoT가 섞이거나 지연되는 것을 방지한다.
                "think": False,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            },
        )
        resp.raise_for_status()
        return resp.json()["message"]["content"]


_APPROVAL_INTENTS = {"approve", "revise", "reject", "ambiguous"}
_EXPLICIT_APPROVE = re.compile(
    r"\s*(?:approve[d]?|승인|확정|ok(?:ay)?|yes)(?:해|해줘|합니다|요)?[.!?\s]*",
    re.I,
)
_EXPLICIT_REGEN = re.compile(r"(?:regen(?:erate)?|재생성|다시)", re.I)
_EXPLICIT_REVISE = re.compile(
    r"(?:revise|edit|change|replace|remove|add|수정|변경|바꿔|바꾸|교체|삭제|추가|"
    r"더\s*.{0,20}(?:해|만들))",
    re.I,
)
_EXPLICIT_REJECT = re.compile(r"\s*(?:reject|cancel|취소|거절|중단)(?:해|해줘|합니다|요)?[.!?\s]*", re.I)


def approval_intent_fallback(checkpoint: str, text: str) -> str:
    """LLM 장애 시 명시적인 명령만 판정한다. 애매하면 절대 승인하지 않는다."""
    value = text.strip()
    if _EXPLICIT_APPROVE.fullmatch(value):
        return "approve"
    if _EXPLICIT_REJECT.fullmatch(value):
        return "reject"
    if _EXPLICIT_REGEN.search(value) or _EXPLICIT_REVISE.search(value):
        return "revise"
    return "ambiguous"


async def classify_approval_intent(checkpoint: str, text: str) -> dict:
    """승인 게이트 응답을 구조화한다. 실패·비정상 출력은 보수적 폴백으로 처리한다."""
    system_prompt = (
        "You classify a user's response at a human approval gate in an animation workflow. "
        "Return ONLY JSON: {\"intent\": \"approve|revise|reject|ambiguous\"}. "
        "approve means accept the current result and continue (including natural phrases such as "
        "'좋아', '이대로 진행해', '괜찮네 다음으로', or 'looks good, continue'). "
        "revise means change, edit, or regenerate the current result. "
        "reject means explicitly cancel, stop, or refuse it. "
        "ambiguous means the intent is unclear. Never infer approval from a neutral or unclear reply."
    )
    user_prompt = json.dumps({"checkpoint": checkpoint, "response": text}, ensure_ascii=False)
    try:
        parsed = parse_json_lenient(await call_llm(system_prompt, user_prompt))
        intent = parsed.get("intent") if isinstance(parsed, dict) else None
        if intent not in _APPROVAL_INTENTS:
            raise ValueError(f"invalid approval intent: {intent!r}")
        return {"intent": intent, "source": "llm"}
    except Exception:
        return {"intent": approval_intent_fallback(checkpoint, text), "source": "fallback"}


async def caption_image(image_path: str) -> str:
    """비전 모델로 이미지의 주요 피사체를 영어 한 구절로 캡션.
    씬↔이미지 내용 매칭 + 캐릭터록(인물 묘사 텍스트) 주입에 쓰인다.

    _prepare_reference_upload와 동일하게 PIL로 정규화 후 PNG로 재인코딩한다 — 원본
    파일이 확장자와 실제 포맷이 다른 경우(예: .jpg로 저장된 WebP) 원본 바이트를 그대로
    보내면 Ollama 비전 모델이 디코드 못 해 "No visual content provided" 식으로 침묵
    실패하고, 그 결과 matched_image가 전 씬에서 null이 되어 T2V로 조용히 강등된다."""
    with Image.open(image_path) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
    buf = BytesIO()
    image.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    async with oom.phase("llm"), httpx.AsyncClient(timeout=180) as client:
        resp = await client.post(OLLAMA_GEN_URL, json={
            "model": VISION_MODEL,
            "prompt": (
                "Describe the MAIN subject of this image in ONE concise English phrase "
                "for a video prompt. If a person: age range, gender, ethnicity, clothing. "
                "If an object: what it is and its setting. No preamble, no quotes."
            ),
            "images": [b64],
            "stream": False,
        })
        resp.raise_for_status()
        return resp.json().get("response", "").strip()


_SUBTITLE_SYSTEM = (
    "너는 영상 자막 작가다. 각 장면의 시각 묘사(scene)를 받아, 장면 흐름에 맞는 "
    "자연스러운 스토리텔링 자막을 한 장면당 한 줄씩 새로 쓴다. 시각 묘사를 그대로 옮기지 말고 "
    "장면이 이어지는 내레이션처럼 매끄럽게 연결한다. 각 자막은 짧은 한 문장(화면에 겹치지 않게), "
    "입력 장면과 정확히 같은 개수를 같은 순서로. 오직 JSON 문자열 배열로만 출력한다. "
    "예: [\"첫 장면 자막\", \"둘째 장면 자막\"]"
)


async def generate_subtitle_lines(scenes: list[dict]) -> list[str]:
    """장면 시각묘사를 LLM이 자연스러운 스토리텔링 자막으로 재작성한다 (M3-11).
    LLM 실패·개수 불일치 시 원문 text로 폴백 — 자막이 비는 일은 없다."""
    ordered = sorted(scenes, key=lambda x: x["id"])
    fallback = [str(s.get("text", "")).strip() for s in ordered]
    user_prompt = json.dumps(
        [{"id": s["id"], "scene": s.get("text", ""), "mood": s.get("mood", "neutral")}
         for s in ordered], ensure_ascii=False)
    try:
        parsed = parse_json_lenient(await call_llm(_SUBTITLE_SYSTEM, user_prompt))
        lines = [str(x).strip() for x in parsed] if isinstance(parsed, list) else []
        if len(lines) == len(ordered) and all(lines):
            return lines
    except Exception:
        pass
    return fallback


def parse_json_lenient(text: str):
    """qwen이 ```json 펜스나 잡설을 붙여도 첫 JSON 배열/객체를 뽑아 파싱."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 첫 [ ... ] 또는 { ... } 블록 추출
    for open_c, close_c in (("[", "]"), ("{", "}")):
        i, j = text.find(open_c), text.rfind(close_c)
        if i != -1 and j > i:
            try:
                return json.loads(text[i:j + 1])
            except json.JSONDecodeError:
                continue  # 이 블록도 문법이 깨졌으면 다음 후보(중괄호)로 넘어간다 —
                          # 여기서 raw JSONDecodeError를 그대로 흘리면 호출부가 예외
                          # 타입 하나(ValueError)만 잡아 재시도하는 계약이 깨진다.
    raise ValueError(f"LLM 응답에서 JSON 파싱 실패: {text[:200]}")


_REVISE_KEYS = ("id", "text", "duration", "mood", "matched_image", "image_role")


async def revise_scenes(current_scenes: list[dict], ref_images: list[dict],
                        instruction: str) -> list[dict]:
    """1-4 게이트에서 사람의 자연어 수정 지시를 '현재 씬 구조'에 반영해 전체 씬 배열을 재구조화한다.
    revised_script_text(처음부터 재분할) 경로와 달리 기존 씬을 보존·편집하는 것이 목적.
    matched_image/image_role의 유효성 가드는 호출측(node_checkpoint_scene_approval)이 재수행한다."""
    view = [{k: s.get(k) for k in _REVISE_KEYS} for s in current_scenes]
    system_prompt = (
        "너는 애니메이션 스토리보드 편집자다. 아래 현재 씬 목록(JSON)과 사용자의 수정 지시를 받아 "
        "지시를 반영한 '전체' 씬 목록을 다시 만들어라. 지시가 건드리지 않은 씬과 필드는 그대로 유지한다. "
        "각 씬 객체 키: id(정수), text(씬 설명), duration(초, 숫자), mood(무드), "
        "matched_image(ref_images의 file 중 하나 또는 null), "
        "image_role(\"start\"|\"ref\"|\"character_ref\"|null). "
        "씬을 추가·삭제·재배열해도 되지만 id는 1부터 순서대로 다시 매겨라. "
        "JSON 배열로만 반환하고 다른 텍스트는 절대 포함하지 마라."
    )
    user_prompt = json.dumps({
        "current_scenes": view,
        "ref_images": ref_images,
        "instruction": instruction,
    }, ensure_ascii=False)
    scenes = parse_json_lenient(await call_llm(system_prompt, user_prompt))
    # 일부 로컬 LLM은 요청 객체 형태를 따라 배열을 current_scenes/scenes 키로 감싼다.
    if isinstance(scenes, dict):
        scenes = scenes.get("scenes") or scenes.get("current_scenes")
    if not isinstance(scenes, list) or not scenes:
        raise ValueError(f"revise_scenes: LLM이 유효한 씬 배열을 반환하지 않음: {scenes!r}")
    return scenes


_PROMPT_PREAMBLE = re.compile(
    r"^(sure[,!.]?|certainly[,!.]?|here('?s| is)|okay[,!.]?|of course)\b.*?:\s*",
    re.I | re.S,
)
_PROMPT_MARKER = re.compile(r"(?:english\s+prompt|prompt)\s*:\s*", re.I)


def clean_llm_prompt(text: str) -> str:
    """qwen이 붙이는 서문("Sure, here's a prompt...")·따옴표·후기 문장을 걷어내고 실제 프롬프트만 남긴다."""
    text = text.strip()
    # 1) 따옴표로 감싼 본문이 있으면 가장 긴 인용 블록 = 실제 프롬프트
    quotes = re.findall(r'"([^"]{20,})"', text)
    if quotes:
        return max(quotes, key=len).strip()
    # 2) 'English Prompt:' / 'Prompt:' 마커 뒤를 채택 (여러 개면 마지막 것)
    markers = list(_PROMPT_MARKER.finditer(text))
    if markers:
        text = text[markers[-1].end():].strip()
    # 3) 남은 서문 한 줄 제거
    text = _PROMPT_PREAMBLE.sub("", text).strip()
    # 4) 후기성 마지막 문장 제거 ("This prompt/description ...")
    text = re.sub(r"\s*This (prompt|description)\b.*$", "", text, flags=re.I | re.S).strip()
    return text


# ── 프레임 길이 헬퍼 + 정지 이미지 앵커 (FLUX.1-schnell) ──────────
def to_4k1(frames: float) -> int:
    """Wan VAE temporal factor 4 → num_frames 는 4k+1 이어야 함. 최소 17."""
    n = max(17, int(round(frames)))
    k = round((n - 1) / 4)
    return max(17, 4 * k + 1)


async def generate_t2i_image(job_id: str, prompt: str, seed: int | None = None, index: int = 0) -> str:
    """정지 이미지 앵커 생성 (FLUX.1-schnell, :8501). 이전엔 :8500 Wan 영상 파이프라인을
    num_frames=1로 돌려썼는데(~120s), 전용 T2I 모델로 교체(~10-15s). return: 로컬 png 경로.
    index: 한 배치에서 여러 장 생성 시 파일명 구분용(gen_img_0.png, gen_img_1.png, ...)."""
    body = {"prompt": prompt, "width": WIDTH, "height": HEIGHT}
    if seed is not None:
        body["seed"] = seed
    timeout = httpx.Timeout(connect=10.0, read=120.0, write=60.0, pool=None)
    async with oom.phase("t2i"), httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(f"{T2I_URL}/generate", json=body)
        resp.raise_for_status()
        image_url = resp.json()["image_url"]
        png = await client.get(f"{T2I_URL}{image_url}")
        png.raise_for_status()

    out = job_dir(job_id) / f"gen_img_{index}.png"
    out.write_bytes(png.content)
    return str(out)


async def generate_t2i_anchor(
    prompt: str,
    width: int | None = None,
    height: int | None = None,
    seed: int | None = None,
) -> dict:
    """:8700 /t2i 게이트웨이 엔드포인트용 T2I 프록시(FLUX.1-schnell, :8501). job_id 스코프
    파일이 필요없는 단발 호출(대시보드 미리보기 등)이라 job_dir에 안 쓰고 base64로 바로 반환."""
    body = {"prompt": prompt}
    if width is not None:
        body["width"] = width
    if height is not None:
        body["height"] = height
    if seed is not None:
        body["seed"] = seed
    timeout = httpx.Timeout(connect=10.0, read=120.0, write=60.0, pool=None)
    async with oom.phase("t2i"), httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(f"{T2I_URL}/generate", json=body)
        resp.raise_for_status()
        data = resp.json()
        png = await client.get(f"{T2I_URL}{data['image_url']}")
        png.raise_for_status()
    return {
        "image_base64": base64.b64encode(png.content).decode(),
        "seconds": data.get("seconds"),
    }


# ── I2V 단발샷 (LTX-Video-13B-distilled, docs/spikes/3.8) ──────
# 5.2/5.3(LTX Face-ID 22B GGUF)도 같은 ComfyUI(:8188, --highvram)를 공유한다.
# --highvram은 체크포인트를 적극적으로 CPU로 내리지 않으므로, 이 경로와 5.x LTX
# Face-ID 배치가 겹치면 두 체크포인트가 동시에 VRAM에 상주해 OOM 위험이 있다.
# generate_ltx_faceid_batch는 별도 게이팅이 없어(5.2/5.3 재설계 계획에서 그 함수를
# 직접 건드리는 중이라 여기서 손대지 않음) oom.phase만으로 완전한 상호배제는 아니다
# — Wan/Stand-In i2v 경로와는 겹침을 막지만, 운영 시 이 엔드포인트와 5.x 파이프라인
# job을 동시에 돌리지 않는 편이 안전하다.
LTX13B_CHECKPOINT = os.environ.get(
    "AGENT_LTX13B_CHECKPOINT", "ltxv-13b-0.9.8-distilled-fp8.safetensors")
LTX13B_CLIP = os.environ.get("AGENT_LTX13B_CLIP", "t5xxl_fp8_e4m3fn_scaled.safetensors")
LTX13B_STEPS = int(os.environ.get("AGENT_LTX13B_STEPS", "8"))
LTX13B_FRAMES = int(os.environ.get("AGENT_LTX13B_FRAMES", "97"))
LTX13B_FPS = int(os.environ.get("AGENT_LTX13B_FPS", "24"))
# 긴 변 기준 캡(32배수). 3.8이 8-step/20초를 측정한 768x512와 같은 화소수 대역을
# 유지하면서, 짧은 변은 입력 비율에 맞춰 32배수로 산정한다(아래 _ltx13b_dims).
LTX13B_MAX_DIM = int(os.environ.get("AGENT_LTX13B_MAX_DIM", "768"))


def _ltx13b_dims(img_width: int, img_height: int) -> tuple[int, int]:
    """3.8 후속 버그 수정: 하드코딩 768x512(가로 고정) 대신 입력 사진의 실제 비율에
    맞춰 긴 변=LTX13B_MAX_DIM, 짧은 변=비율 맞춤 32배수로 해상도를 산정한다.
    세로 사진에 가로 고정값을 쓰면 얼굴 상단(이마)이 크롭되던 문제(3.8 산출물 기록)를
    막는다. LTX latent는 VAE 시공간 다운샘플 때문에 32배수 제약이 있다."""
    if img_width <= 0 or img_height <= 0:
        raise ValueError(f"invalid image dimensions: {img_width}x{img_height}")
    long_edge = LTX13B_MAX_DIM
    if img_width >= img_height:
        width = long_edge
        height = max(32, round(long_edge * img_height / img_width / 32) * 32)
    else:
        height = long_edge
        width = max(32, round(long_edge * img_width / img_height / 32) * 32)
    return width, height


def _normalize_i2v_input(image_bytes: bytes) -> tuple[bytes, int, int]:
    """업로드된 원본 이미지를 EXIF 회전 반영 + RGB PNG로 정규화. 폭/높이는 회전 반영 후
    값이어야 종횡비 산정(_ltx13b_dims)이 맞다."""
    with Image.open(BytesIO(image_bytes)) as opened:
        image = ImageOps.exif_transpose(opened).copy()
    if "A" in image.getbands():
        rgba = image.convert("RGBA")
        background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        image = Image.alpha_composite(background, rgba).convert("RGB")
    else:
        image = image.convert("RGB")
    out = BytesIO()
    image.save(out, format="PNG", optimize=True)
    return out.getvalue(), image.width, image.height


def _build_ltx13b_graph(
    *, prompt: str, image_name: str, width: int, height: int, seed: int,
) -> dict:
    """docs/spikes/3.8 산출물(tests/probe_ltx13b_i2v.py)과 동일한 API-format 그래프.
    LTX-2.3 Face-ID 워크플로와 달리 SetNode/GetNode pseudo-node가 없어 UI 변환 없이
    직접 구성한다. ComfyUI 코어 내장 LTX 노드만 사용, Face-ID LoRA 없음."""
    return {
        "1": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": LTX13B_CHECKPOINT}},
        "2": {"class_type": "CLIPLoader",
              "inputs": {"clip_name": LTX13B_CLIP, "type": "ltxv"}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["2", 0]}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {
            "text": "worst quality, blurry, jittery, distorted, low resolution",
            "clip": ["2", 0],
        }},
        "5": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "6": {"class_type": "ModelSamplingLTXV",
              "inputs": {"model": ["1", 0], "max_shift": 2.05, "base_shift": 0.95}},
        "12": {"class_type": "LTXVConditioning", "inputs": {
            "positive": ["3", 0], "negative": ["4", 0], "frame_rate": float(LTX13B_FPS),
        }},
        "7": {"class_type": "LTXVImgToVideo", "inputs": {
            "positive": ["12", 0], "negative": ["12", 1], "vae": ["1", 2],
            "image": ["5", 0], "width": width, "height": height,
            "length": LTX13B_FRAMES, "batch_size": 1, "strength": 1.0,
        }},
        "8": {"class_type": "LTXVScheduler", "inputs": {
            "steps": LTX13B_STEPS, "max_shift": 2.05, "base_shift": 0.95,
            "stretch": True, "terminal": 0.1,
        }},
        "9": {"class_type": "KSampler", "inputs": {
            "model": ["6", 0], "seed": seed, "steps": LTX13B_STEPS, "cfg": 1.0,
            "sampler_name": "euler", "scheduler": "normal",
            "positive": ["7", 0], "negative": ["7", 1], "latent_image": ["7", 2],
            "denoise": 1.0,
        }},
        "10": {"class_type": "VAEDecode", "inputs": {"samples": ["9", 0], "vae": ["1", 2]}},
        "11": {"class_type": "SaveAnimatedWEBP", "inputs": {
            "images": ["10", 0], "filename_prefix": "i2v_oneshot", "fps": LTX13B_FPS,
            "lossless": False, "quality": 90, "method": "default",
        }},
    }


def to_ltx_len(frames: float) -> int:
    """LTXV VAE 시공간 다운샘플 8 → length는 8k+1이어야 한다(LTX13B_FRAMES=97=8*12+1과
    동일 패턴, to_4k1의 LTX 8-배수 변형). 최소 25(≈1s@24fps)."""
    n = max(25, int(round(frames)))
    k = round((n - 1) / 8)
    return max(25, 8 * k + 1)


def _build_ltx13b_t2v_graph(
    *, prompt: str, width: int, height: int, length: int, seed: int,
) -> dict:
    """_build_ltx13b_graph(4.6, image-conditioned I2V)의 T2V 형제. LoadImage +
    LTXVImgToVideo 대신 EmptyLTXVLatentVideo로 순수 노이즈 latent에서 시작한다
    (이미지 조건 없음, Task 6.x Wan 제거 — docs/superpowers/specs/2026-08-01-
    wan-removal-ltx-t2v-design.md)."""
    return {
        "1": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": LTX13B_CHECKPOINT}},
        "2": {"class_type": "CLIPLoader",
              "inputs": {"clip_name": LTX13B_CLIP, "type": "ltxv"}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["2", 0]}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {
            "text": "worst quality, blurry, jittery, distorted, low resolution",
            "clip": ["2", 0],
        }},
        "6": {"class_type": "ModelSamplingLTXV",
              "inputs": {"model": ["1", 0], "max_shift": 2.05, "base_shift": 0.95}},
        "12": {"class_type": "LTXVConditioning", "inputs": {
            "positive": ["3", 0], "negative": ["4", 0], "frame_rate": float(LTX13B_FPS),
        }},
        "7": {"class_type": "EmptyLTXVLatentVideo", "inputs": {
            "width": width, "height": height, "length": length, "batch_size": 1,
        }},
        "8": {"class_type": "LTXVScheduler", "inputs": {
            "steps": LTX13B_STEPS, "max_shift": 2.05, "base_shift": 0.95,
            "stretch": True, "terminal": 0.1,
        }},
        "9": {"class_type": "KSampler", "inputs": {
            "model": ["6", 0], "seed": seed, "steps": LTX13B_STEPS, "cfg": 1.0,
            "sampler_name": "euler", "scheduler": "normal",
            "positive": ["12", 0], "negative": ["12", 1], "latent_image": ["7", 0],
            "denoise": 1.0,
        }},
        "10": {"class_type": "VAEDecode", "inputs": {"samples": ["9", 0], "vae": ["1", 2]}},
        "11": {"class_type": "SaveAnimatedWEBP", "inputs": {
            "images": ["10", 0], "filename_prefix": "t2v_job", "fps": LTX13B_FPS,
            "lossless": False, "quality": 90, "method": "default",
        }},
    }


def _t2v_request_key(scene_id: int, prompt: str, duration: float, seed: int | None) -> str:
    return hashlib.sha256(json.dumps({
        "scene_id": scene_id, "prompt": prompt, "duration": duration, "seed": seed,
        "steps": LTX13B_STEPS, "fps": LTX13B_FPS, "width": WIDTH, "height": HEIGHT,
        "workflow": "ltx13b_t2v_v1",  # 그래프 구조 바뀌면 캐시 무효화용 버전 문자열
    }, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _i2v_fallback_request_key(
    scene_id: int, prompt: str, matched_image: str, duration: float, seed: int | None,
) -> str:
    return hashlib.sha256(json.dumps({
        "scene_id": scene_id, "prompt": prompt, "matched_image": matched_image,
        "duration": duration, "seed": seed, "steps": LTX13B_STEPS, "fps": LTX13B_FPS,
        "width": WIDTH, "height": HEIGHT, "workflow": "ltx13b_i2v_fallback_v1",
    }, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _webp_bytes_to_mp4(webp_bytes: bytes, fps: int) -> bytes:
    """SaveAnimatedWEBP가 ComfyUI 표준 관례로 EXIF에 워크플로 메타데이터를 심는데,
    ffmpeg의 webp 디먹서가 이 비표준 EXIF를 못 읽고 전체 디코드를 포기한다(PIL은
    문제없이 읽음). 다운스트림 node_edit_concat/ffmpeg_concat이 ffmpeg로 이 파일을
    그대로 열기 때문에, PIL로 프레임을 뽑아 ffmpeg image2pipe로 진짜 mp4 재인코딩한다."""
    with Image.open(BytesIO(webp_bytes)) as im:
        n_frames = getattr(im, "n_frames", 1)
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp_path = tmp.name
        proc = None
        try:
            proc = subprocess.Popen(
                ["ffmpeg", "-y", "-f", "image2pipe", "-framerate", str(fps), "-i", "-",
                 "-pix_fmt", "yuv420p", tmp_path],
                stdin=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            for i in range(n_frames):
                im.seek(i)
                buf = BytesIO()
                im.convert("RGB").save(buf, format="PNG")
                proc.stdin.write(buf.getvalue())
            _, stderr = proc.communicate(timeout=60)  # stdin close도 communicate가 처리
            if proc.returncode != 0:
                raise RuntimeError(
                    f"webp→mp4 재인코딩 실패: {stderr.decode(errors='replace')[-500:]}")
            return Path(tmp_path).read_bytes()
        except Exception:
            # 프레임 루프/write/communicate 타임아웃 등 도중 실패 시 ffmpeg 좀비 방지
            # (communicate가 정상 완료된 뒤라면 이미 reap된 상태라 poll()이 None이 아님)
            if proc is not None and proc.poll() is None:
                proc.kill()
                proc.wait()
            raise
        finally:
            Path(tmp_path).unlink(missing_ok=True)


async def _generate_ltx_job_clip(
    job_id: str, scene_id: int, graph: dict, request_key: str, force_new: bool,
) -> str:
    """T2V/I2V 폴백 공용 — _generate_reference_clip(STANDIN/SUBJECT_REF)과 동일한
    SQLite 재개형 패턴(큐/missing/exec 타임아웃)을 그래프 dict만 바꿔 재사용한다."""
    async with (
        oom.phase("i2v"),
        httpx.AsyncClient(timeout=httpx.Timeout(connect=10.0, read=60.0, write=60.0, pool=None)) as client,
    ):
        existing = None if force_new else _recoverable_prompt(job_id, scene_id, request_key)
        if existing:
            prompt_id = existing["prompt_id"]
        else:
            resp = await client.post(f"{COMFYUI_URL}/prompt", json={"prompt": graph})
            resp.raise_for_status()
            prompt_id = resp.json()["prompt_id"]
            _save_prompt(prompt_id, job_id, scene_id, request_key)

        submitted_at = float(existing["submitted_at"]) if existing else time.time()
        execution_started_at = (float(existing["execution_started_at"])
                                if existing and existing["execution_started_at"] else None)
        missing_since = None
        media = None
        while True:
            await asyncio.sleep(2.0)
            h = (await client.get(f"{COMFYUI_URL}/history/{prompt_id}")).json()
            if prompt_id not in h:
                queue = (await client.get(f"{COMFYUI_URL}/queue")).json()
                running_ids = {item[1] for item in queue.get("queue_running", [])}
                pending_ids = {item[1] for item in queue.get("queue_pending", [])}
                if prompt_id in running_ids:
                    if execution_started_at is None:
                        execution_started_at = time.time()
                    _update_prompt(prompt_id, "running",
                                   execution_started_at=execution_started_at)
                elif prompt_id in pending_ids:
                    _update_prompt(prompt_id, "queued")
                elif time.time() - submitted_at > STANDIN_QUEUE_TIMEOUT:
                    msg = f"씬 {scene_id}: ComfyUI 큐에서 {STANDIN_QUEUE_TIMEOUT:.0f}s 내 시작되지 않음"
                    _update_prompt(prompt_id, "error", error=msg)
                    raise TimeoutError(msg)
                else:
                    missing_since = missing_since or time.time()
                    if time.time() - missing_since > STANDIN_MISSING_TIMEOUT:
                        msg = (f"씬 {scene_id}: ComfyUI prompt가 history/queue에서 사라짐 "
                               f"(prompt_id={prompt_id})")
                        _update_prompt(prompt_id, "error", error=msg)
                        raise TimeoutError(msg)
                if prompt_id in running_ids or prompt_id in pending_ids:
                    missing_since = None
                if execution_started_at and time.time() - execution_started_at > STANDIN_EXEC_TIMEOUT:
                    msg = (f"씬 {scene_id}: LTX 실행이 {STANDIN_EXEC_TIMEOUT:.0f}s를 초과함 "
                           f"(prompt_id={prompt_id})")
                    _update_prompt(prompt_id, "error", error=msg)
                    raise TimeoutError(msg)
                continue
            status = h[prompt_id]["status"]
            for kind, data in status.get("messages", []):
                if kind == "execution_start":
                    execution_started_at = data.get("timestamp", 0) / 1000 or time.time()
                    _update_prompt(prompt_id, "running",
                                   execution_started_at=execution_started_at)
            if status.get("status_str") == "error":
                msg = f"씬 {scene_id}: ComfyUI 실행 오류 {status.get('messages')}"
                _update_prompt(prompt_id, "error", error=msg)
                raise RuntimeError(msg)
            for node_out in h[prompt_id].get("outputs", {}).values():
                # Both graphs this helper serves (T2V/I2V-fallback) terminate in SaveAnimatedWEBP,
                # which only ever emits "images" -- no "videos"/"gifs" key to fall back to.
                media = node_out.get("images")
                if media:
                    break
            if media:
                _update_prompt(prompt_id, "completed", output_filename=media[0]["filename"])
                break
            if execution_started_at and time.time() - execution_started_at > STANDIN_EXEC_TIMEOUT:
                msg = (f"씬 {scene_id}: LTX 실행이 {STANDIN_EXEC_TIMEOUT:.0f}s를 초과함 "
                       f"(prompt_id={prompt_id})")
                _update_prompt(prompt_id, "error", error=msg)
                raise TimeoutError(msg)

        output = media[0]
        vid = await client.get(f"{COMFYUI_URL}/view", params={
            "filename": output["filename"], "subfolder": output.get("subfolder", ""),
            "type": output.get("type", "output"),
        })
        vid.raise_for_status()

    out = job_dir(job_id) / f"clip{scene_id}.mp4"
    mp4_bytes = await asyncio.to_thread(_webp_bytes_to_mp4, vid.content, LTX13B_FPS)
    out.write_bytes(mp4_bytes)
    return str(out)


async def generate_t2v_clip(
    job_id: str, scene_id: int, prompt: str,
    duration: float = 2.0, seed: int | None = None, force_new: bool = False,
) -> str:
    """이미지 없는 씬(mode=T2V) — Wan call_video가 맡던 것 중 T2V 절반.
    같은 job 씬들이 같은 seed로 출발하면(호출부에서 payload.seed 그대로 넘김)
    그림체 흔들림이 줄어드는 건 기존 Wan 경로와 동일 관례."""
    resolved_seed = seed if seed is not None else int(time.time())
    length = to_ltx_len(duration * LTX13B_FPS)
    graph = _build_ltx13b_t2v_graph(
        prompt=prompt, width=WIDTH, height=HEIGHT, length=length, seed=resolved_seed)
    request_key = _t2v_request_key(scene_id, prompt, duration, seed)
    return await _generate_ltx_job_clip(job_id, scene_id, graph, request_key, force_new)


async def generate_i2v_fallback_clip(
    job_id: str, scene_id: int, prompt: str, matched_image: str,
    duration: float = 2.0, seed: int | None = None, force_new: bool = False,
) -> str:
    """USE_STANDIN=0일 때만 타는 드문 폴백(mode=I2V, 이미지 있음) — Wan call_video가
    맡던 것 중 I2V 절반. 기존 4.6 _build_ltx13b_graph(image-conditioned)를 그대로
    재사용, 신규 그래프 불필요."""
    resolved_seed = seed if seed is not None else int(time.time())
    async with (
        oom.phase("i2v"),
        httpx.AsyncClient(timeout=httpx.Timeout(connect=10.0, read=60.0, write=60.0, pool=None)) as client,
    ):
        img_path = refs_dir(job_id) / matched_image
        up = await client.post(
            f"{COMFYUI_URL}/upload/image",
            files={"image": (f"i2v_fallback_{Path(matched_image).name}",
                             img_path.read_bytes(), "image/png")},
            data={"overwrite": "true"},
        )
        up.raise_for_status()
        uj = up.json()
        image_name = f"{uj['subfolder']}/{uj['name']}" if uj.get("subfolder") else uj["name"]

    length = to_ltx_len(duration * LTX13B_FPS)
    graph = _build_ltx13b_graph(
        prompt=prompt, image_name=image_name, width=WIDTH, height=HEIGHT, seed=resolved_seed)
    graph["7"]["inputs"]["length"] = length  # 4.6 오네샷은 LTX13B_FRAMES 고정, 여긴 씬 duration 반영
    request_key = _i2v_fallback_request_key(scene_id, prompt, matched_image, duration, seed)
    return await _generate_ltx_job_clip(job_id, scene_id, graph, request_key, force_new)


async def generate_i2v_oneshot(image_bytes: bytes, prompt: str, seed: int | None = None) -> dict:
    """:8700 /i2v 단발샷 (LTX-Video-13B-distilled, ComfyUI :8188 프록시).
    job과 무관한 단발 호출 — base64 webp로 바로 반환."""
    normalized, img_width, img_height = _normalize_i2v_input(image_bytes)
    width, height = _ltx13b_dims(img_width, img_height)
    if seed is None:
        seed = int(time.time())

    timeout = httpx.Timeout(connect=10.0, read=180.0, write=60.0, pool=None)
    async with oom.phase("i2v"), httpx.AsyncClient(timeout=timeout) as client:
        up = await client.post(
            f"{COMFYUI_URL}/upload/image",
            files={"image": ("i2v_oneshot_input.png", normalized, "image/png")},
            data={"overwrite": "true"},
        )
        up.raise_for_status()
        uj = up.json()
        image_name = f"{uj['subfolder']}/{uj['name']}" if uj.get("subfolder") else uj["name"]

        graph = _build_ltx13b_graph(
            prompt=prompt, image_name=image_name, width=width, height=height, seed=seed)
        resp = await client.post(f"{COMFYUI_URL}/prompt", json={"prompt": graph})
        resp.raise_for_status()
        prompt_id = resp.json()["prompt_id"]

        started_at = time.time()
        history_item = None
        while history_item is None:
            if time.time() - started_at > STANDIN_QUEUE_TIMEOUT:
                raise TimeoutError("I2V 단발샷이 제한 시간 내 완료되지 않음")
            history = (await client.get(f"{COMFYUI_URL}/history/{prompt_id}")).json()
            if prompt_id in history:
                history_item = history[prompt_id]
            else:
                await asyncio.sleep(2.0)

        if history_item.get("status", {}).get("status_str") == "error":
            raise RuntimeError(
                f"I2V 단발샷 실행 오류 {history_item.get('status', {}).get('messages')}"
            )

        media = None
        for node_out in history_item.get("outputs", {}).values():
            media = node_out.get("videos") or node_out.get("gifs") or node_out.get("images")
            if media:
                break
        if not media:
            raise RuntimeError("I2V 단발샷 출력 영상 없음")
        output = media[0]
        video = await client.get(f"{COMFYUI_URL}/view", params={
            "filename": output["filename"],
            "subfolder": output.get("subfolder", ""),
            "type": output.get("type", "output"),
        })
        video.raise_for_status()

    return {
        "video_base64": base64.b64encode(video.content).decode(),
        "width": width,
        "height": height,
    }


# ── I2I 스타일 변환 (Flux Kontext dev, docs/model-selection-i2i.md, Task 6.1) ──
# style_presets.py(4.5)의 6종 프리픽스를 그대로 재사용한다 — 신규 스타일 정의 없음.
FLUX_KONTEXT_UNET = os.environ.get(
    "AGENT_FLUX_KONTEXT_UNET", "flux1-dev-kontext_fp8_scaled.safetensors")
FLUX_KONTEXT_CLIP_L = os.environ.get("AGENT_FLUX_KONTEXT_CLIP_L", "clip_l.safetensors")
FLUX_KONTEXT_T5 = os.environ.get(
    "AGENT_FLUX_KONTEXT_T5", "t5xxl_fp8_e4m3fn_scaled.safetensors")  # 5.x LTX와 공유
FLUX_KONTEXT_VAE = os.environ.get("AGENT_FLUX_KONTEXT_VAE", "ae.safetensors")
FLUX_KONTEXT_STEPS = int(os.environ.get("AGENT_FLUX_KONTEXT_STEPS", "20"))
FLUX_KONTEXT_GUIDANCE = float(os.environ.get("AGENT_FLUX_KONTEXT_GUIDANCE", "2.5"))

# ComfyUI comfy_extras/nodes_flux.py의 FluxKontextImageScale이 내부적으로 고르는
# 해상도 버킷과 동일 목록 — EmptySD3LatentImage에 같은 width/height를 넣어야 latent
# 크기가 어긋나지 않는다(그래프 실행 전 파이썬에서 미리 같은 알고리즘으로 계산).
FLUX_KONTEXT_RESOLUTIONS = [
    (672, 1568), (688, 1504), (720, 1456), (752, 1392), (800, 1328),
    (832, 1248), (880, 1184), (944, 1104), (1024, 1024), (1104, 944),
    (1184, 880), (1248, 832), (1328, 800), (1392, 752), (1456, 720),
    (1504, 688), (1568, 672),
]


def _flux_kontext_dims(img_width: int, img_height: int) -> tuple[int, int]:
    """FluxKontextImageScale과 동일한 최근접 종횡비 버킷 산정(ComfyUI 소스 미러)."""
    if img_width <= 0 or img_height <= 0:
        raise ValueError(f"invalid image dimensions: {img_width}x{img_height}")
    aspect = img_width / img_height
    _, width, height = min(
        (abs(aspect - w / h), w, h) for w, h in FLUX_KONTEXT_RESOLUTIONS)
    return width, height


def _build_flux_kontext_graph(
    *, prompt: str, image_name: str, width: int, height: int, seed: int,
) -> dict:
    """docs.comfy.org/tutorials/flux/flux-1-kontext-dev 공식 워크플로와 동일한
    API-format 그래프(LoadImage→FluxKontextImageScale→VAEEncode→ReferenceLatent로
    입력 얼굴사진을 조건으로 건 뒤 EmptySD3LatentImage에서 새로 샘플링)."""
    return {
        "1": {"class_type": "UNETLoader",
              "inputs": {"unet_name": FLUX_KONTEXT_UNET, "weight_dtype": "default"}},
        "2": {"class_type": "DualCLIPLoader", "inputs": {
            "clip_name1": FLUX_KONTEXT_CLIP_L, "clip_name2": FLUX_KONTEXT_T5, "type": "flux",
        }},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": FLUX_KONTEXT_VAE}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["2", 0]}},
        "5": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["4", 0]}},
        "6": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "7": {"class_type": "FluxKontextImageScale", "inputs": {"image": ["6", 0]}},
        "8": {"class_type": "VAEEncode", "inputs": {"pixels": ["7", 0], "vae": ["3", 0]}},
        "9": {"class_type": "ReferenceLatent",
              "inputs": {"conditioning": ["4", 0], "latent": ["8", 0]}},
        "10": {"class_type": "FluxGuidance",
               "inputs": {"conditioning": ["9", 0], "guidance": FLUX_KONTEXT_GUIDANCE}},
        "11": {"class_type": "EmptySD3LatentImage",
               "inputs": {"width": width, "height": height, "batch_size": 1}},
        "12": {"class_type": "KSampler", "inputs": {
            "model": ["1", 0], "seed": seed, "steps": FLUX_KONTEXT_STEPS, "cfg": 1.0,
            "sampler_name": "euler", "scheduler": "simple",
            "positive": ["10", 0], "negative": ["5", 0], "latent_image": ["11", 0],
            "denoise": 1.0,
        }},
        "13": {"class_type": "VAEDecode", "inputs": {"samples": ["12", 0], "vae": ["3", 0]}},
        "14": {"class_type": "SaveImage",
               "inputs": {"images": ["13", 0], "filename_prefix": "i2i_style"}},
    }


async def generate_i2i_style(image_bytes: bytes, style: str, seed: int | None = None) -> dict:
    """:8700 /i2i 얼굴사진→스타일 변환 (Flux Kontext dev, ComfyUI :8188 프록시).
    job과 무관한 단발 호출 — base64 PNG로 바로 반환. style은 style_presets.py의
    6종 키 중 하나여야 한다(신규 스타일 정의 없음, 미지원 키는 여기서 거부)."""
    if style not in style_presets.STYLE_PREFIXES:
        raise ValueError(f"unsupported style: {style}")
    prompt = (
        f"Change the style of the photo to: {style_presets.style_prefix(style)}. "
        "Keep the same facial features, pose, and composition."
    )
    normalized, img_width, img_height = _normalize_i2v_input(image_bytes)
    width, height = _flux_kontext_dims(img_width, img_height)
    if seed is None:
        seed = int(time.time())

    timeout = httpx.Timeout(connect=10.0, read=180.0, write=60.0, pool=None)
    async with oom.phase("i2i"), httpx.AsyncClient(timeout=timeout) as client:
        up = await client.post(
            f"{COMFYUI_URL}/upload/image",
            files={"image": ("i2i_style_input.png", normalized, "image/png")},
            data={"overwrite": "true"},
        )
        up.raise_for_status()
        uj = up.json()
        image_name = f"{uj['subfolder']}/{uj['name']}" if uj.get("subfolder") else uj["name"]

        graph = _build_flux_kontext_graph(
            prompt=prompt, image_name=image_name, width=width, height=height, seed=seed)
        resp = await client.post(f"{COMFYUI_URL}/prompt", json={"prompt": graph})
        resp.raise_for_status()
        prompt_id = resp.json()["prompt_id"]

        started_at = time.time()
        history_item = None
        while history_item is None:
            if time.time() - started_at > STANDIN_QUEUE_TIMEOUT:
                raise TimeoutError("I2I 스타일 변환이 제한 시간 내 완료되지 않음")
            history = (await client.get(f"{COMFYUI_URL}/history/{prompt_id}")).json()
            if prompt_id in history:
                history_item = history[prompt_id]
            else:
                await asyncio.sleep(2.0)

        if history_item.get("status", {}).get("status_str") == "error":
            raise RuntimeError(
                f"I2I 스타일 변환 실행 오류 {history_item.get('status', {}).get('messages')}"
            )

        media = None
        for node_out in history_item.get("outputs", {}).values():
            media = node_out.get("images")
            if media:
                break
        if not media:
            raise RuntimeError("I2I 스타일 변환 출력 이미지 없음")
        output = media[0]
        png = await client.get(f"{COMFYUI_URL}/view", params={
            "filename": output["filename"],
            "subfolder": output.get("subfolder", ""),
            "type": output.get("type", "output"),
        })
        png.raise_for_status()

    return {
        "image_base64": base64.b64encode(png.content).decode(),
        "width": width,
        "height": height,
    }


async def generate_kokoro_narration(text: str, speed: float = 1.0) -> bytes:
    """Generate Korean narration through the dedicated Kokoro backend.

    The backend may return WAV bytes directly or an ``audio_url`` JSON object.
    Supporting both keeps this gateway independent from a particular Kokoro
    server wrapper without weakening the model boundary.
    """
    # 첫 요청에는 Kokoro 모델의 메모리 적재 시간이 포함될 수 있다.
    timeout = httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=None)
    async with oom.phase("tts"), httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            f"{KOKORO_URL}/generate",
            json={"text": text, "language": "ko", "speed": speed},
        )
        response.raise_for_status()
        content_type = response.headers.get("content-type", "").lower()
        if "audio/wav" in content_type or "audio/x-wav" in content_type:
            wav = response.content
        else:
            audio_url = response.json().get("audio_url")
            if not audio_url:
                raise ValueError("Kokoro backend response has no audio_url")
            audio_response = await client.get(f"{KOKORO_URL}{audio_url}")
            audio_response.raise_for_status()
            wav = audio_response.content

    if len(wav) < 12 or wav[:4] != b"RIFF" or wav[8:12] != b"WAVE":
        raise ValueError("Kokoro backend returned invalid WAV data")
    return wav


async def generate_chatterbox_clone(
    text: str,
    reference_wav: bytes,
    filename: str = "reference.wav",
) -> bytes:
    """Generate cloned Korean speech using only the Chatterbox V3 backend."""
    timeout = httpx.Timeout(connect=10.0, read=600.0, write=60.0, pool=None)
    async with oom.phase("tts"), httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            f"{CHATTERBOX_URL}/generate",
            data={"text": text},
            files={"reference": (filename, reference_wav, "audio/wav")},
        )
        response.raise_for_status()
        wav = response.content

    if len(wav) < 12 or wav[:4] != b"RIFF" or wav[8:12] != b"WAVE":
        raise ValueError("Chatterbox backend returned invalid WAV data")
    return wav


async def generate_chatterbox_narration(text: str, speed: float = 1.0) -> bytes:
    """Generate video narration with the fixed, commercially usable CC0 voice."""
    if not CHATTERBOX_NARRATION_REFERENCE.is_file():
        raise ValueError(
            f"Chatterbox narration reference is missing: "
            f"{CHATTERBOX_NARRATION_REFERENCE}"
        )
    # Chatterbox V3 has no native speaking-rate control. Keep ``speed`` in the
    # gateway contract for compatibility; natural model timing is used.
    return await generate_chatterbox_clone(
        text,
        CHATTERBOX_NARRATION_REFERENCE.read_bytes(),
        CHATTERBOX_NARRATION_REFERENCE.name,
    )


async def generate_standin_clip(
    job_id: str,
    scene_id: int,
    prompt: str,
    ref_image: str,
    duration: float = 2.0,
    seed: int | None = None,
    force_new: bool = False,
    relight: bool = False,
) -> str:
    """참조 얼굴 1장 + 프롬프트로 I2V-14B 클립 생성 (ComfyUI :8188).
    참조 이미지 전체를 첫 프레임 latent로 인코딩 → 얼굴+화풍+분위기가 통째로 이어짐.
    return: 로컬 클립 경로.

    해상도는 체크포인트 네이티브인 STANDIN_WIDTH/HEIGHT(832x480)로 고정 — T2V 경로의
    WIDTH/HEIGHT(quality 프리셋 1280x704)를 그대로 쓰면 100초 목표를 못 맞춘다(실측
    65s→159s). fps는 STANDIN_FPS(네이티브 16)로 생성하고 편집 단계(ffmpeg_concat)가
    모든 입력을 DEFAULT_FPS로 정규화한다.
    """
    return await _generate_reference_clip(
        job_id, scene_id, prompt, ref_image, duration, seed, force_new,
        subject_ref=False, relight=relight)


async def generate_subject_ref_clip(
    job_id: str, scene_id: int, prompt: str, ref_image: str,
    duration: float = 2.0, seed: int | None = None, force_new: bool = False,
    relight: bool = False,
) -> str:
    """비인간 캐릭터/제품 전체 이미지를 identity 조건으로 쓰는 경로."""
    return await _generate_reference_clip(
        job_id, scene_id, prompt, ref_image, duration, seed, force_new,
        subject_ref=True, relight=relight)


def _build_ltx_faceid_graph(
    *, prompt: str, face_image: str, duration: float, seed: int, prefix: str,
) -> dict:
    """3.2와 동일한 base 워크플로 배선(앵커 lock 없음) — Face-ID LoRA가 identity를
    전담한다. 2026-07-31: Flux 앵커로 첫 프레임을 강도 1.0으로 고정하던 버전은
    앵커 자체에 identity 정보가 없어(Flux가 얼굴 참조를 안 받음) 무작위 얼굴이
    나왔고, 그 강한 lock이 Face-ID Identity Transfer(node 129)를 무력화시켰다
    (실사용 재현 검증 완료, docs/superpowers/specs/2026-07-31-ltx-faceid-anchor-removal-design.md).
    """
    graph = json.loads(LTX_FACEID_WORKFLOW.read_text())
    graph["31"]["inputs"]["value"] = duration
    graph["47"]["inputs"]["value"] = LTX_FACEID_FPS
    graph["50"]["inputs"]["noise_seed"] = seed
    graph["66"]["inputs"]["steps"] = LTX_FACEID_STEPS
    graph["98"]["inputs"]["preview_rate"] = LTX_FACEID_STEPS
    graph["100"]["inputs"].update(width=LTX_FACEID_WIDTH, height=LTX_FACEID_HEIGHT)
    graph["102"]["inputs"]["value"] = (
        prompt if prompt.lstrip().startswith("ref_t2v:") else f"ref_t2v: {prompt}"
    )
    graph["104"]["inputs"]["image"] = face_image
    graph["101"]["inputs"]["filename_prefix"] = prefix
    graph["129"]["inputs"]["reference_guidance_scale"] = LTX_FACEID_GUIDANCE
    # S1 나레이션은 5.4에서 별도 TTS mux한다. 여기서 LTX 오디오를 디코드하면
    # 씬 사이 AudioVAE 로드가 대형 모델 offload와 스왑 스래싱을 유발한다.
    graph["56"]["inputs"].pop("audio", None)
    return graph


_LTX_SHARED_NODES = {
    # 네 씬이 아래 로더/고정 conditioning을 같은 그래프 노드로 참조한다.
    "8", "26", "27", "35", "41", "43", "47", "58", "67", "68", "78", "98", "99",
}


def _remap_graph_links(value, mapping: dict[str, str]):
    if (
        isinstance(value, list) and len(value) == 2
        and isinstance(value[0], str) and value[0] in mapping
    ):
        return [mapping[value[0]], value[1]]
    if isinstance(value, dict):
        return {key: _remap_graph_links(item, mapping) for key, item in value.items()}
    if isinstance(value, list):
        return [_remap_graph_links(item, mapping) for item in value]
    return value


def _build_ltx_faceid_batch_graph(
    scenes: list[dict], uploaded: dict[str, str],
) -> tuple[dict, dict[int, str]]:
    """씬별 샘플러 가지를 합치되 무거운 로더 노드는 한 벌만 둔다."""
    batch: dict = {}
    output_nodes: dict[int, str] = {}
    for scene in scenes:
        scene_id = scene["id"]
        graph = _build_ltx_faceid_graph(
            prompt=scene["prompt"],
            face_image=uploaded[scene["face_id_ref"]],
            duration=float(scene.get("duration") or 3.0),
            seed=int(scene.get("seed") or 0),
            prefix=f"ltx_batch_scene_{scene_id}",
        )
        mapping = {
            node_id: node_id if node_id in _LTX_SHARED_NODES else f"s{scene_id}_{node_id}"
            for node_id in graph
        }
        for node_id, node in graph.items():
            mapped_id = mapping[node_id]
            if mapped_id in batch:
                continue
            batch[mapped_id] = _remap_graph_links(node, mapping)
        output_nodes[scene_id] = mapping["101"]
    return batch, output_nodes


async def generate_ltx_faceid_batch(job_id: str, scenes: list[dict]) -> dict[int, str]:
    """단일 ComfyUI prompt에서 로더를 공유해 LTX/Gemma/LoRA를 정확히 한 번 로드한다."""
    if not scenes:
        return {}
    timeout = httpx.Timeout(connect=10.0, read=60.0, write=60.0, pool=None)
    async with httpx.AsyncClient(timeout=timeout) as client:
        uploaded: dict[str, str] = {}
        # 동일 캐릭터 참조는 배치 전체에서 한 번만 업로드한다.
        for scene in scenes:
            ref_name = scene["face_id_ref"]
            if ref_name not in uploaded:
                image_path = refs_dir(job_id) / ref_name
                image_bytes = _prepare_reference_upload(image_path, subject_ref=False)
                response = await client.post(
                    f"{COMFYUI_URL}/upload/image",
                    files={"image": (f"ltx_face_{image_path.stem}.png", image_bytes, "image/png")},
                    data={"overwrite": "true"},
                )
                response.raise_for_status()
                data = response.json()
                uploaded[ref_name] = (
                    f"{data.get('subfolder')}/{data['name']}"
                    if data.get("subfolder") else data["name"]
                )

        graph, output_nodes = _build_ltx_faceid_batch_graph(scenes, uploaded)
        response = await client.post(f"{COMFYUI_URL}/prompt", json={"prompt": graph})
        response.raise_for_status()
        prompt_id = response.json()["prompt_id"]

        started_at = time.time()
        history_item = None
        while history_item is None:
            if time.time() - started_at > STANDIN_QUEUE_TIMEOUT:
                raise TimeoutError("LTX Face-ID batch가 제한 시간 내 완료되지 않음")
            history = (await client.get(f"{COMFYUI_URL}/history/{prompt_id}")).json()
            if prompt_id in history:
                history_item = history[prompt_id]
            else:
                await asyncio.sleep(2.0)

        if history_item.get("status", {}).get("status_str") == "error":
            raise RuntimeError(
                f"LTX Face-ID batch 실행 오류 "
                f"{history_item.get('status', {}).get('messages')}"
            )

        results: dict[int, str] = {}
        for scene_id, output_node in output_nodes.items():
            node_output = history_item.get("outputs", {}).get(output_node, {})
            # SaveVideo는 ComfyUI 버전에 따라 MP4도 images+animated로 보고한다.
            media = (
                node_output.get("videos")
                or node_output.get("gifs")
                or node_output.get("images")
            )
            if not media:
                raise RuntimeError(f"씬 {scene_id}: LTX Face-ID 출력 영상 없음")
            output = media[0]
            video = await client.get(f"{COMFYUI_URL}/view", params={
                "filename": output["filename"],
                "subfolder": output.get("subfolder", ""),
                "type": output.get("type", "output"),
            })
            video.raise_for_status()
            path = job_dir(job_id) / f"clip{scene_id}.mp4"
            path.write_bytes(video.content)
            results[scene_id] = str(path)
        return results


REFERENCE_PREPROCESS_VERSION = 2


def _prepare_reference_upload(image_path: Path, *, subject_ref: bool) -> bytes:
    """Normalize EXIF/alpha while preserving pixels needed by the identity encoder.

    The I2V encode uses the whole image as-is for both ref kinds (no face-crop step).
    Subject refs additionally crop transparent margins so a mascot/product occupies the
    frame without its empty canvas; face refs keep their original framing untouched.
    """
    with Image.open(image_path) as opened:
        image = ImageOps.exif_transpose(opened).copy()
    if subject_ref and "A" in image.getbands():
        alpha = image.getchannel("A")
        bbox = alpha.getbbox()
        if bbox:
            image = image.crop(bbox)
    if "A" in image.getbands():
        rgba = image.convert("RGBA")
        background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        image = Image.alpha_composite(background, rgba).convert("RGB")
    else:
        image = image.convert("RGB")
    out = BytesIO()
    image.save(out, format="PNG", optimize=True)
    return out.getvalue()


def _build_reference_graph(
    *, prompt: str, num_frames: int, seed: int | None, prefix: str, subject_ref: bool,
    relight: bool,
) -> tuple[dict, dict]:
    """M3-9: ref-kind별 ComfyUI 그래프 빌드.
    - subject_ref(비인간): i2v_14b — 참조 전체가 첫프레임 latent(실루엣·화풍 보존).
      M3-8 relight 노브(node 105 첫프레임 lock 완화)는 이 경로에만 유효.
    - face(사람): standin_t2v — 얼굴 identity만 주입, 배경은 프롬프트(빈 embeds). relight 무의미(no-op).
    반환: (graph, 노드맵)."""
    workflow, nodes = (I2V_WORKFLOW, _SI) if subject_ref else (FACE_WORKFLOW, _SI_FACE)
    graph = json.loads(workflow.read_text())
    graph[nodes["prompt"]]["inputs"]["positive_prompt"] = prompt
    graph[nodes["embeds"]]["inputs"].update(
        width=STANDIN_WIDTH, height=STANDIN_HEIGHT, num_frames=num_frames)
    if subject_ref:  # relight는 i2v 첫프레임 lock 전용 — face(빈 embeds)엔 넣지 않는다.
        graph[nodes["embeds"]]["inputs"].update(_relight_embed_overrides(relight))
    else:  # M3-10: face 경로 LoRA strength 튜닝 노브(identity 유지 vs 배경 자유 A/B).
        graph[_SI_FACE_LORA["identity"]]["inputs"]["strength"] = STANDIN_FACE_LORA_STRENGTH
        graph[_SI_FACE_LORA["distill"]]["inputs"]["strength"] = STANDIN_DISTILL_LORA_STRENGTH
    graph[nodes["sampler"]]["inputs"]["steps"] = STANDIN_STEPS
    if seed is not None:
        graph[nodes["sampler"]]["inputs"]["seed"] = seed
    graph[nodes["output"]]["inputs"]["filename_prefix"] = prefix
    graph[nodes["output"]]["inputs"]["frame_rate"] = STANDIN_FPS  # 실시간 재생속도; 편집에서 24로 정규화
    return graph, nodes


async def _generate_reference_clip(
    job_id: str, scene_id: int, prompt: str, ref_image: str, duration: float,
    seed: int | None, force_new: bool, *, subject_ref: bool, relight: bool = False,
) -> str:
    graph, nodes = _build_reference_graph(
        prompt=prompt, num_frames=to_4k1(duration * STANDIN_FPS), seed=seed,
        prefix=f"{job_id}_{scene_id}", subject_ref=subject_ref, relight=relight)

    request_key = hashlib.sha256(json.dumps({
        "scene_id": scene_id, "prompt": prompt, "ref_image": ref_image,
        "duration": duration, "seed": seed, "steps": STANDIN_STEPS,
        "fps": STANDIN_FPS,  # fps가 바뀌면 num_frames가 달라짐 → 이전 캐시 재사용 방지
        "reference_mode": "subject" if subject_ref else "face",
        "preprocess_version": REFERENCE_PREPROCESS_VERSION,
        "width": WIDTH, "height": HEIGHT,
        "workflow": (I2V_WORKFLOW if subject_ref else FACE_WORKFLOW).name,  # M3-9: 경로 전환 시 캐시 무효화
        # relight는 subject_ref(i2v)에만 유효 — face는 항상 {}로 고정(캐시 안정).
        "relight": _relight_embed_overrides(relight) if subject_ref else {},
        # M3-10: face LoRA strength 바뀌면 캐시 무효화(A/B 튜닝 반영).
        "face_lora": None if subject_ref else [STANDIN_FACE_LORA_STRENGTH, STANDIN_DISTILL_LORA_STRENGTH],
    }, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    async with (
        oom.phase("i2v"),
        httpx.AsyncClient(timeout=httpx.Timeout(connect=10.0, read=60.0, write=60.0, pool=None)) as client,
    ):
        # 1) 참조 이미지 업로드 → ComfyUI input/ 에 올려 LoadImage가 파일명으로 참조
        img_path = refs_dir(job_id) / ref_image
        upload_name = f"{'subject' if subject_ref else 'face'}_v{REFERENCE_PREPROCESS_VERSION}_{img_path.stem}.png"
        upload_bytes = _prepare_reference_upload(img_path, subject_ref=subject_ref)
        up = await client.post(
            f"{COMFYUI_URL}/upload/image",
            files={"image": (upload_name, upload_bytes, "image/png")},
            data={"overwrite": "true"},
        )
        up.raise_for_status()
        uj = up.json()
        sub = uj.get("subfolder", "")
        graph[nodes["image"]]["inputs"]["image"] = f"{sub}/{uj['name']}" if sub else uj["name"]

        # 2) 제출 직후 별도 SQLite에 커밋. 재실행 시 기존 prompt를 재사용한다.
        existing = None if force_new else _recoverable_prompt(job_id, scene_id, request_key)
        if existing:
            prompt_id = existing["prompt_id"]
        else:
            sub_resp = await client.post(f"{COMFYUI_URL}/prompt", json={"prompt": graph})
            sub_resp.raise_for_status()
            prompt_id = sub_resp.json()["prompt_id"]
            _save_prompt(prompt_id, job_id, scene_id, request_key)

        # 3) 큐 대기와 실제 실행 시간을 분리한다. execution_start 전 대기는
        # 실행 제한시간에 포함하지 않는다.
        submitted_at = float(existing["submitted_at"]) if existing else time.time()
        execution_started_at = (float(existing["execution_started_at"])
                                if existing and existing["execution_started_at"] else None)
        missing_since = None
        gif = None
        while True:
            await asyncio.sleep(2.0)
            h = (await client.get(f"{COMFYUI_URL}/history/{prompt_id}")).json()
            if prompt_id not in h:
                queue = (await client.get(f"{COMFYUI_URL}/queue")).json()
                running_ids = {item[1] for item in queue.get("queue_running", [])}
                pending_ids = {item[1] for item in queue.get("queue_pending", [])}
                if prompt_id in running_ids:
                    if execution_started_at is None:
                        execution_started_at = time.time()
                    _update_prompt(prompt_id, "running",
                                   execution_started_at=execution_started_at)
                elif prompt_id in pending_ids:
                    _update_prompt(prompt_id, "queued")
                elif time.time() - submitted_at > STANDIN_QUEUE_TIMEOUT:
                    msg = f"씬 {scene_id}: ComfyUI 큐에서 {STANDIN_QUEUE_TIMEOUT:.0f}s 내 시작되지 않음"
                    _update_prompt(prompt_id, "error", error=msg)
                    raise TimeoutError(msg)
                else:
                    missing_since = missing_since or time.time()
                    if time.time() - missing_since > STANDIN_MISSING_TIMEOUT:
                        msg = (f"씬 {scene_id}: ComfyUI prompt가 history/queue에서 사라짐 "
                               f"(prompt_id={prompt_id})")
                        _update_prompt(prompt_id, "error", error=msg)
                        raise TimeoutError(msg)
                if prompt_id in running_ids or prompt_id in pending_ids:
                    missing_since = None
                if execution_started_at and time.time() - execution_started_at > STANDIN_EXEC_TIMEOUT:
                    label = "Subject Ref" if subject_ref else "Stand-In"
                    msg = (f"씬 {scene_id}: {label} 실행이 {STANDIN_EXEC_TIMEOUT:.0f}s를 초과함 "
                           f"(prompt_id={prompt_id})")
                    _update_prompt(prompt_id, "error", error=msg)
                    raise TimeoutError(msg)
                continue
            status = h[prompt_id]["status"]
            for kind, data in status.get("messages", []):
                if kind == "execution_start":
                    execution_started_at = data.get("timestamp", 0) / 1000 or time.time()
                    _update_prompt(prompt_id, "running",
                                   execution_started_at=execution_started_at)
            if status.get("status_str") == "error":
                msg = f"씬 {scene_id}: ComfyUI 실행 오류 {status.get('messages')}"
                _update_prompt(prompt_id, "error", error=msg)
                raise RuntimeError(msg)
            for node_out in h[prompt_id].get("outputs", {}).values():
                if node_out.get("gifs"):
                    gif = node_out["gifs"][0]
                    break
            if gif:
                _update_prompt(prompt_id, "completed", output_filename=gif["filename"])
                break
            if execution_started_at and time.time() - execution_started_at > STANDIN_EXEC_TIMEOUT:
                label = "Subject Ref" if subject_ref else "Stand-In"
                msg = (f"씬 {scene_id}: {label} 실행이 {STANDIN_EXEC_TIMEOUT:.0f}s를 초과함 "
                       f"(prompt_id={prompt_id})")
                _update_prompt(prompt_id, "error", error=msg)
                raise TimeoutError(msg)

        # 4) 결과 mp4 다운로드 (/view — 파일시스템 경로 의존 없음)
        vid = await client.get(f"{COMFYUI_URL}/view", params={
            "filename": gif["filename"], "subfolder": gif.get("subfolder", ""),
            "type": gif.get("type", "output"),
        })
        vid.raise_for_status()

    out = job_dir(job_id) / f"clip{scene_id}.mp4"
    out.write_bytes(vid.content)
    return str(out)


# ── ffmpeg ──────────────────────────────────────────────────
def _probe_duration(path: str) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        check=True, capture_output=True, text=True,
    )
    return float(r.stdout.strip())


def ffmpeg_concat(clip_paths: list[str], transitions: list[str], out_path: str,
                   width: int = WIDTH, height: int = HEIGHT) -> str:
    """트랜지션 포함 이어붙이기. transitions[i] = clip i→i+1 사이 ('crossfade'|'cut').
    width/height 기본값은 T2V fast/quality 프리셋(832x480 등) — LTX_FACEID 씬이 섞인
    잡은 호출부(node_edit_concat)가 LTX_FACEID_WIDTH/HEIGHT(1024x576)를 넘겨써야
    LTX 클립이 이 프리셋으로 다운스케일되지 않는다(Face-ID 화질 손실 방지)."""
    if len(clip_paths) == 1:
        subprocess.run(["ffmpeg", "-y", "-i", clip_paths[0], "-c", "copy", out_path],
                       check=True, capture_output=True)
        return out_path
    filter_complex, last = build_concat_filter(clip_paths, transitions, width, height)
    inputs = []
    for p in clip_paths:
        inputs += ["-i", p]
    subprocess.run(
        ["ffmpeg", "-y", *inputs, "-filter_complex", filter_complex,
         "-map", f"[{last}]", "-pix_fmt", "yuv420p", out_path],
        check=True, capture_output=True,
    )
    return out_path


def build_concat_filter(clip_paths: list[str], transitions: list[str],
                         width: int = WIDTH, height: int = HEIGHT):
    """
    cut → concat 필터, crossfade → xfade(0.5s).

    ⚠️ 예전 구현은 cut도 xfade(duration=0.001)로 흉내 냈는데, 0.001s는 1프레임(1/24s)보다
    짧아 ffmpeg가 전환 프레임 0개로 계산 → 두 번째 입력이 통째로 탈락하고 체인 전체가
    연쇄 붕괴했다(클립 4개 18.2s → 6.1s). cut은 반드시 concat으로 붙인다.

    모든 입력을 fps/해상도/SAR/PTS 정규화해서 fps가 다른 클립(예: 16fps Stand-In)이
    섞여도 concat/xfade가 안전하다.
    return: (filter_complex_str, 최종_출력_라벨)
    """
    XFADE = 0.5
    durations = [_probe_duration(p) for p in clip_paths]
    # settb=AVTB: concat 출력(1/1000000)과 fps 필터 출력(1/24)의 timebase가 달라
    # xfade가 "timebase do not match"로 실패한다 → 모든 입력을 AVTB로 통일.
    parts = [
        f"[{i}:v]fps={DEFAULT_FPS},scale={width}:{height},setsar=1,"
        f"setpts=PTS-STARTPTS,settb=AVTB[n{i}]"
        for i in range(len(clip_paths))
    ]

    # cut으로 이어지는 연속 구간을 세그먼트 하나로 concat
    segments: list[tuple[list[int], float]] = []   # ([클립 인덱스...], 구간 길이)
    run, run_dur = [0], durations[0]
    for i in range(1, len(clip_paths)):
        if transitions[i - 1] == "crossfade":
            segments.append((run, run_dur))
            run, run_dur = [], 0.0
        run.append(i)
        run_dur += durations[i]
    segments.append((run, run_dur))

    seg_labels: list[tuple[str, float]] = []
    for k, (idxs, dur) in enumerate(segments):
        if len(idxs) == 1:
            seg_labels.append((f"n{idxs[0]}", dur))
        else:
            ins = "".join(f"[n{i}]" for i in idxs)
            parts.append(f"{ins}concat=n={len(idxs)}:v=1:a=0[s{k}]")
            seg_labels.append((f"s{k}", dur))

    # 세그먼트 사이만 진짜 crossfade
    prev, offset = seg_labels[0]
    for k in range(1, len(seg_labels)):
        label, dur = seg_labels[k]
        off = max(0.0, offset - XFADE)
        parts.append(f"[{prev}][{label}]xfade=transition=fade:"
                     f"duration={XFADE:.3f}:offset={off:.3f}[x{k}]")
        prev = f"x{k}"
        offset = off + dur
    return ";".join(parts), prev


def burn_subtitles(video_path: str, srt_path: str, out_path: str) -> str:
    subprocess.run(
        ["ffmpeg", "-y", "-i", video_path, "-vf", f"subtitles={srt_path}",
         "-pix_fmt", "yuv420p", out_path],
        check=True, capture_output=True,
    )
    return out_path


if __name__ == "__main__":  # clean_llm_prompt 자체점검: python tools.py
    # 실제로 이번 job에서 qwen이 뱉었던 3가지 패턴
    a = clean_llm_prompt(
        'Sure, here is the prompt in English:\n\n"A dimly lit room where an Asian '
        'woman sits at a cluttered desk, chin on clasped hands, troubled expression."'
        '\n\nThis prompt includes both the scene description and camera work.'
    )
    assert a.startswith("A dimly lit room") and "Sure" not in a and "This prompt" not in a, a
    b = clean_llm_prompt(
        "A bright light is shining...\n\nEnglish Prompt:\nA bright light emanating from "
        "a monitor startles an Asian woman, her eyes widen in surprise."
    )
    assert b.startswith("A bright light emanating") and "English Prompt" not in b, b
    c = clean_llm_prompt("A clean prompt with no preamble at all, anime scene.")
    assert c.startswith("A clean prompt"), c
    print("clean_llm_prompt self-check ok")

    # revise_scenes 자체점검 (LLM 응답을 가짜로 주입 — 파싱/재구조화만 검증)
    async def _fake_llm(_s, _u):
        return ('```json\n[{"id":1,"text":"밝은 방","duration":3,"mood":"bright",'
                '"matched_image":null,"image_role":null}]\n```')
    _orig = call_llm
    globals()["call_llm"] = _fake_llm
    try:
        revised = asyncio.run(revise_scenes(
            [{"id": 1, "text": "어두운 방", "duration": 3, "mood": "dark"}], [], "더 밝게"))
        assert len(revised) == 1 and revised[0]["mood"] == "bright", revised
    finally:
        globals()["call_llm"] = _orig
    print("revise_scenes self-check ok")

    # ffmpeg_concat 자체점검: cut이 클립을 떨어뜨리지 않는지 (합성 클립, GPU 불필요)
    # 회귀 대상: xfade duration=0.001(<1프레임) 버그 — 클립 4개 18.2s가 6.1s로 붕괴했었다.
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        clips = []
        for i, (color, d) in enumerate([("red", 2), ("green", 1), ("blue", 1), ("yellow", 2)]):
            p = f"{td}/c{i}.mp4"
            subprocess.run(
                ["ffmpeg", "-y", "-f", "lavfi", "-i",
                 f"color=c={color}:s={WIDTH}x{HEIGHT}:r={DEFAULT_FPS}:d={d}",
                 "-pix_fmt", "yuv420p", p], check=True, capture_output=True)
            clips.append(p)
        out_cut = f"{td}/out_cut.mp4"
        ffmpeg_concat(clips, ["cut", "cut", "cut"], out_cut)
        got = _probe_duration(out_cut)
        assert abs(got - 6.0) < 0.15, f"cut concat 길이 {got} != ~6.0"
        out_x = f"{td}/out_x.mp4"
        ffmpeg_concat(clips, ["cut", "crossfade", "cut"], out_x)
        got = _probe_duration(out_x)
        assert abs(got - 5.5) < 0.15, f"crossfade concat 길이 {got} != ~5.5"
        # 16fps 클립이 섞여도 정규화로 안전한지
        p16 = f"{td}/c16.mp4"
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i",
                        f"color=c=white:s={WIDTH}x{HEIGHT}:r=16:d=2",
                        "-pix_fmt", "yuv420p", p16], check=True, capture_output=True)
        out_mix = f"{td}/out_mix.mp4"
        ffmpeg_concat([clips[0], p16], ["cut"], out_mix)
        got = _probe_duration(out_mix)
        assert abs(got - 4.0) < 0.15, f"fps 혼합 concat 길이 {got} != ~4.0"
    print("ffmpeg_concat self-check ok")
