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
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from io import BytesIO

import httpx
from PIL import Image, ImageDraw, ImageFilter, ImageOps

import oom_orchestrator as oom
import style_presets

# ── 환경 설정 ────────────────────────────────────────────────
OLLAMA_URL = os.environ.get("AGENT_OLLAMA_URL", "http://127.0.0.1:11434/api/chat")
OLLAMA_GEN_URL = OLLAMA_URL.replace("/api/chat", "/api/generate")  # 비전 캡션용(images 지원)
LLM_MODEL = os.environ.get(
    "AGENT_LLM_MODEL",
    "hf.co/nvidia/NVIDIA-Nemotron-3-Nano-4B-GGUF:Q4_K_M",
)  # 2026-08-02: gemma4:latest로 잠깐 바꿨다가 롤백 — matched_image/subject_type을 LLM
  # 판단에 맡기지 않고 단일 참조 시 node_split_scenes가 결정론적으로 강제하도록 고쳐서
  # (nodes.py의 "단일 참조 결정론적 매칭" 분기) 씬분할 LLM 자체의 이 약점은 더는
  # 문제가 안 됨 — 원래 채택 근거(S1 JSON 파싱 검증)로 복귀.
VISION_MODEL = os.environ.get("AGENT_VISION_MODEL", "gemma4:latest")  # 참조 캡션 전용
# (단일 참조의 human/nonhuman 판정에 여전히 필요). qwen3.5:9b(중국원산) 교체 유지.
T2I_URL = os.environ.get("AGENT_T2I_URL", "http://127.0.0.1:8501")
KOKORO_URL = os.environ.get("AGENT_KOKORO_URL", "http://127.0.0.1:8503")
CHATTERBOX_URL = os.environ.get("AGENT_CHATTERBOX_URL", "http://127.0.0.1:8504")
COSMOS3NANO_URL = os.environ.get("AGENT_COSMOS3NANO_URL", "http://127.0.0.1:8505")
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
LLM_KEEP_RESIDENT = os.environ.get("AGENT_LLM_KEEP_RESIDENT", "1") == "1"

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
LTX_FACEID_WIDTH = int(os.environ.get("AGENT_LTX_FACEID_WIDTH", "1280"))
LTX_FACEID_HEIGHT = int(os.environ.get("AGENT_LTX_FACEID_HEIGHT", "704"))
# node 129(LTXIdentityOverlapConditioning)의 기본값 "match_target"은 참조 이미지를
# 출력 비율로 센터크롭 후 리사이즈한다 — 정사각 얼굴 참조를 와이드 타겟에 두면 위/
# 아래(이마·턱)가 잘려 identity 손실(0e76413의 원인). "match_target_letterbox"는
# 크롭 없이 레터박스로 맞춰 잘리는 픽셀이 없다 — 이 모드라야 16:9(1280x704)에서도
# identity가 유지된다(2026-08-03 A/B 프레임 비교로 실측 확인).
LTX_FACEID_REF_RESIZE_MODE = os.environ.get(
    "AGENT_LTX_FACEID_REF_RESIZE_MODE", "match_target_letterbox")
LTX_FACEID_FPS = int(os.environ.get("AGENT_LTX_FACEID_FPS", "24"))
LTX_FACEID_STEPS = int(os.environ.get("AGENT_LTX_FACEID_STEPS", "8"))
# node 129(LTXIdentityOverlapConditioning)의 identity 강도 노브. 기본값 1.0은 워크플로
# JSON 원본값 그대로 — 얼굴 일관성이 아쉬우면 1.2~1.5로 올려본다(배경/포즈 자유도와 trade-off).
LTX_FACEID_GUIDANCE = float(os.environ.get("AGENT_LTX_FACEID_GUIDANCE", "1.0"))
# 워크플로 내장 Gemma 캡션 재작성(node 79 TextGenerate)의 토큰 상한. 원본 JSON은 1024.
LTX_FACEID_CAPTION_MAX_TOKENS = int(
    os.environ.get("AGENT_LTX_FACEID_CAPTION_MAX_TOKENS", "192"))
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
# M2 T2I 앵커(generate_t2i_image) 전용 해상도. WIDTH/HEIGHT(1280x704)는 LTX/Wan의
# 32배수 제약에 맞춘 영상 프리셋이라 16:9가 아니다(704*16/9=1251.5) — 이 값을 그대로
# 재사용하면 승인 후 ref_images로 첨부되는 기본 생성 이미지가 정확한 16:9가 아니게 된다.
# FLUX는 16배수만 맞으면 되므로 정확한 16:9로 별도 지정.
T2I_WIDTH = int(os.environ.get("AGENT_T2I_WIDTH", "1280"))
T2I_HEIGHT = int(os.environ.get("AGENT_T2I_HEIGHT", "720"))


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
    """비전 모델은 전환 시 내리되, 작은 씬분할 Nemotron은 선택적으로 상주시킨다.

    전체 resident 모드는 여전히 사용하지 않는다. 과거 OOM의 큰 축인 비전 모델은
    계속 내리고 LLM_KEEP_RESIDENT=1인 경우 LLM_MODEL 하나만 예외로 남긴다.
    """
    models = {VISION_MODEL}
    if not LLM_KEEP_RESIDENT:
        models.add(LLM_MODEL)
    async with httpx.AsyncClient(timeout=30) as client:
        for model in models:
            try:
                await client.post(OLLAMA_GEN_URL, json={"model": model, "keep_alive": 0})
            except httpx.HTTPError:
                pass  # 이미 언로드됐거나 서버 일시 불가 — 다음 로드가 알아서 재적재


oom.register_unload("llm", _unload_llm_backend)


async def _unload_i2v_backend() -> None:
    """ComfyUI(--highvram)는 체크포인트를 알아서 안 내리므로 명시적으로 unload+free
    호출(Task 4.4와 동일 문제 — 13B↔22B GGUF 전환 시 이중 상주 OOM 방지)."""
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            await client.post(
                f"{COMFYUI_URL}/free", json={"unload_models": True, "free_memory": True})
        except httpx.HTTPError:
            pass  # 다음 /prompt 제출이 알아서 재적재


oom.register_unload("i2v", _unload_i2v_backend)
# t2i(Flux)는 oom hook을 쓰지 않는다. oom_orchestrator는 backend '전환'만 알지 그
# i2v 안에서 어떤 모델이 뜨는지는 모르는데, 여기서 필요한 건 정확히 그 모델별 분기라
# 층이 다르다. FLUX_KEEP_RESIDENT=0(기본)이면 flux_server가 매 요청 자체 언로드하므로
# 애초에 hook이 불필요하고, =1이면 아래 _release_t2i()를 무거운 경로에서만 부른다.


async def _release_t2i() -> None:
    """무거운 ComfyUI 경로 진입 전에 FLUX(:8501) 상주분을 비운다.

    GB10 실측(2026-08-04, FLUX_KEEP_RESIDENT=1):
      - FLUX 상주 + LTX-13B T2V  → peak 77.8GiB, 여유 41GiB, 정상 속도(1클립 149s)
      - FLUX 상주 + LTX-22B FaceID → peak 93GiB+, free 2.1GiB, ComfyUI가 lowvram으로
        강등(로그 "lowvram patches: 1244")되어 씬마다 부분 언로드/재로드 → 2씬 70분+
    즉 13B는 공존 가능하고 22B는 불가능하다. 그래서 '전부 상주/전부 온디맨드'가 아니라
    무거운 경로만 자리를 비우게 한다 — 13B 경로(generate_t2v_clip 등)는 이 함수를
    부르지 않으므로 상주 이득(콜드로드 ~176s 회피)을 그대로 가져간다.

    best-effort: 비우기는 성능 최적화지 정합성 조건이 아니다. :8501이 없거나 실패해도
    호출부는 그대로 진행한다(그 경우 예전처럼 메모리가 빡빡할 뿐 결과는 같다)."""
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            await client.post(f"{T2I_URL}/unload")
    except httpx.HTTPError:
        pass  # 서버 부재/실패 — 다음 /generate가 알아서 재적재한다


# ── LLM ─────────────────────────────────────────────────────
async def call_llm(system_prompt: str, user_prompt: str) -> str:
    async with oom.phase("llm"), httpx.AsyncClient(timeout=180) as client:
        resp = await client.post(
            OLLAMA_URL,
            json={
                "model": LLM_MODEL,
                "stream": False,
                "keep_alive": -1 if LLM_KEEP_RESIDENT else "5m",
                # Ollama 모델별 지원 여부와 무관하게 비사고 모드로 고정한다.
                # JSON-only 씬 분할에 숨은 CoT가 섞이거나 지연되는 것을 방지한다.
                "think": False,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                # num_ctx 미지정 시 모델 기본 컨텍스트(Nemotron 1,048,576 / qwen3.5:9b
                # 262,144 토큰)로 KV캐시를 잡아 콜당 수십 초 오버헤드가 남 — 씬 프롬프트는
                # 몇백 토큰이면 충분(2026-08-02, job 003cb843 anchoring 5분31초 실측 디버깅).
                "options": {"num_ctx": 8192},
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
            "options": {"num_ctx": 8192},
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
    # 5) 한글 잔재 제거. 이 함수를 통과한 문자열은 전부 FLUX T5 / LTX로 가는데 둘 다
    #    영어만 읽는다 — 한글 토큰은 순수 노이즈고, 의상 lock에 섞이면 전 씬 프롬프트로
    #    복제된다(2026-08-13 job 3ded2f29: 오역 방지용 대응표 "Korean 반팔 means
    #    short-sleeve"를 4B가 출력에 옮겨 적어 wardrobe lock이 `a white 반팔
    #    (short-sleeve) t-shirt`가 됐다). 괄호 안 영문 주석이 붙어 있으면 그걸 살린다.
    text = re.sub(r"[가-힣]+\s*\(([^)]*)\)", r"\1", text)
    text = re.sub(r"[가-힣]+", " ", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", re.sub(r"\s{2,}", " ", text)).strip()
    return text


# ── 프레임 길이 헬퍼 + 정지 이미지 앵커 (FLUX.1-schnell) ──────────
def to_4k1(frames: float) -> int:
    """Wan VAE temporal factor 4 → num_frames 는 4k+1 이어야 함. 최소 17."""
    n = max(17, int(round(frames)))
    k = round((n - 1) / 4)
    return max(17, 4 * k + 1)


async def generate_t2i_image(job_id: str, prompt: str, seed: int | None = None, index: int = 0) -> str:
    """정지 이미지 앵커 생성 (FLUX.1-schnell, :8501). 이전엔 :8500 Wan 영상 파이프라인을
    num_frames=1로 돌려썼는데(~120s), 전용 T2I 모델로 교체. 순수 추론은 웜 상태 기준
    ~7-12s지만, flux_server.py가 매 요청마다 모델을 언로드하는 정책(FLUX_KEEP_RESIDENT=0
    기본값 — Task 2.4 GB10 전 모델 상주 OOM 실측 후 채택)이라 매 콜마다 콜드 로드 비용이
    붙는다. job a96857e4 ReadTimeout 재현 실측: 콜드 전체 175s(로드 168s+생성 7.5s,
    시스템 메모리 압박 상태). 이후 job 937f1da6도 동일 원인으로 재발(당시 서버
    프로세스가 재시작 전이라 옛 120s 코드로 떠 있었음) — 메모리 압박이 더 심하면
    175s도 못 버틸 수 있다고 보고 generate_t2v_clip/generate_chatterbox_clone과
    같은 600s(온디맨드 콜드로드 있는 다른 backend들의 기존 전례)로 여유있게 상향.
    return: 로컬 png 경로. index: 한 배치에서 여러 장 생성 시 파일명 구분용
    (gen_img_0.png, gen_img_1.png, ...). T2I_WIDTH/HEIGHT(16:9)는 영상 WIDTH/HEIGHT
    프리셋과 별개 — 승인 후 이 이미지가 그대로 ref_images로 첨부되는 기본 캐릭터
    이미지가 된다(node_checkpoint_image_approval)."""
    body = {"prompt": prompt, "width": T2I_WIDTH, "height": T2I_HEIGHT}
    if seed is not None:
        body["seed"] = seed
    timeout = httpx.Timeout(connect=10.0, read=900.0, write=60.0, pool=None)
    async with oom.phase("t2i"), httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(f"{T2I_URL}/generate", json=body)
        resp.raise_for_status()
        image_url = resp.json()["image_url"]
        png = await client.get(f"{T2I_URL}{image_url}")
        png.raise_for_status()

    out = job_dir(job_id) / f"gen_img_{index}.png"
    out.write_bytes(png.content)
    return str(out)


_ASCII_ONLY_RE = re.compile(r"^[\x00-\x7F]*$")


async def _ensure_english_prompt(prompt: str) -> str:
    """FLUX.1-schnell 텍스트 인코더(CLIP-L 위주)는 영어 학습이 압도적이라 비영어 프롬프트를
    사실상 OOV로 처리한다 — 무관한 장면 + 의미없는 가짜 글자 간판으로 환각하는 실패 패턴을
    2026-08-05 T2I 카테고리에서 실측(한국어 프롬프트 입력 → 일본 상점가+가짜 한자 간판 출력).
    ASCII 프롬프트는 그대로 통과, 비ASCII만 LLM(call_llm, Ollama)로 영어 번역."""
    if _ASCII_ONLY_RE.match(prompt):
        return prompt
    translated = await call_llm(
        "Translate the user's text into natural, concise English for use as a text-to-image "
        "generation prompt. Output ONLY the translated English text, nothing else — no quotes, "
        "no explanation.",
        prompt,
    )
    return translated.strip()


async def generate_t2i_anchor(
    prompt: str,
    width: int | None = None,
    height: int | None = None,
    seed: int | None = None,
) -> dict:
    """:8700 /t2i 게이트웨이 엔드포인트용 T2I 프록시(FLUX.1-schnell, :8501). job_id 스코프
    파일이 필요없는 단발 호출(대시보드 미리보기 등)이라 job_dir에 안 쓰고 base64로 바로 반환.
    read timeout은 generate_t2i_image와 동일한 콜드 로드 비용을 겪으므로 같이 600s로
    맞춘다(둘 다 같은 :8501 FLUX 서버, 같은 매콜 언로드 정책)."""
    prompt = await _ensure_english_prompt(prompt)
    body = {"prompt": prompt}
    if width is not None:
        body["width"] = width
    if height is not None:
        body["height"] = height
    if seed is not None:
        body["seed"] = seed
    timeout = httpx.Timeout(connect=10.0, read=900.0, write=60.0, pool=None)
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
# generate_ltx_faceid_batch도 이제 oom.phase("i2v")로 게이팅된다(Task 6.15 대비,
# 이전엔 이 함수만 빠져 있어 llm/t2i 전환과 겹칠 수 있었음).
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


LTX13B_DEFAULT_NEGATIVE = "worst quality, blurry, jittery, distorted, low resolution"


def _build_ltx13b_graph(
    *, prompt: str, image_name: str, width: int, height: int, seed: int,
    negative: str = LTX13B_DEFAULT_NEGATIVE,
) -> dict:
    """docs/spikes/3.8 산출물(tests/probe_ltx13b_i2v.py)과 동일한 API-format 그래프.
    LTX-2.3 Face-ID 워크플로와 달리 SetNode/GetNode pseudo-node가 없어 UI 변환 없이
    직접 구성한다. ComfyUI 코어 내장 LTX 노드만 사용, Face-ID LoRA 없음.
    negative: 기본값은 화질 전용. 씬별로 특정 오브젝트 드리프트를 밀어내야 하면
    (예: 2026-08-12 음료 광고 스파이크의 "wine bottle" 드리프트) 호출부가 커스텀
    negative를 넘긴다 — 기본 화질 negative에 이어붙이지 않고 완전히 교체(호출부가
    필요하면 직접 이어붙여서 넘긴다)."""
    return {
        "1": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": LTX13B_CHECKPOINT}},
        "2": {"class_type": "CLIPLoader",
              "inputs": {"clip_name": LTX13B_CLIP, "type": "ltxv"}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["2", 0]}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {
            "text": negative,
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
    negative: str = LTX13B_DEFAULT_NEGATIVE,
) -> str:
    return hashlib.sha256(json.dumps({
        "scene_id": scene_id, "prompt": prompt, "matched_image": matched_image,
        "duration": duration, "seed": seed, "steps": LTX13B_STEPS, "fps": LTX13B_FPS,
        "width": WIDTH, "height": HEIGHT, "negative": negative,
        "workflow": "ltx13b_i2v_fallback_v1",
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
    negative_prompt: str | None = None,
) -> str:
    """USE_STANDIN=0일 때만 타는 드문 폴백(mode=I2V, 이미지 있음) — Wan call_video가
    맡던 것 중 I2V 절반. 기존 4.6 _build_ltx13b_graph(image-conditioned)를 그대로
    재사용, 신규 그래프 불필요.
    negative_prompt: None이면 기본 화질 negative(LTX13B_DEFAULT_NEGATIVE). 씬이
    특정 방향의 identity 드리프트를 밀어내야 하면(2026-08-12 음료 광고 스파이크,
    씬3a "wine bottle" 드리프트) 호출부(Scene.negative_prompt)가 채워 넘긴다."""
    resolved_seed = seed if seed is not None else int(time.time())
    negative = negative_prompt if negative_prompt is not None else LTX13B_DEFAULT_NEGATIVE
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
        prompt=prompt, image_name=image_name, width=WIDTH, height=HEIGHT,
        seed=resolved_seed, negative=negative)
    graph["7"]["inputs"]["length"] = length  # 4.6 오네샷은 LTX13B_FRAMES 고정, 여긴 씬 duration 반영
    request_key = _i2v_fallback_request_key(scene_id, prompt, matched_image, duration, seed, negative)
    return await _generate_ltx_job_clip(job_id, scene_id, graph, request_key, force_new)


# Cosmos3-Nano는 31GB GPU 상주라 ComfyUI 등과 상시 동거가 안 됨(VRAM 부족) —
# systemd 상시 서비스 대신 첫 /t2v 요청이 직접 프로세스를 띄우고, 유휴 시
# server.py 자체 워치독(COSMOS3NANO_IDLE_TIMEOUT)이 스스로 종료해 VRAM을 반납한다.
COSMOS3NANO_BOOT_TIMEOUT = float(os.environ.get("AGENT_COSMOS3NANO_BOOT_TIMEOUT", "60"))
_cosmos3nano_launch_lock = asyncio.Lock()


async def _ensure_cosmos3nano_running(client: httpx.AsyncClient) -> None:
    async def _healthy() -> bool:
        try:
            r = await client.get(f"{COSMOS3NANO_URL}/health", timeout=2.0)
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    if await _healthy():
        return

    async with _cosmos3nano_launch_lock:
        if await _healthy():  # 락 대기 중 다른 요청이 이미 띄웠을 수 있음
            return
        repo_root = Path(__file__).resolve().parents[1]
        python = repo_root / ".venv-cosmos3nano" / "bin" / "python"
        script = repo_root / "t2v" / "cosmos3nano" / "server.py"
        log_path = repo_root / "t2v" / "cosmos3nano" / "server.log"
        with open(log_path, "ab") as log:
            subprocess.Popen(
                [str(python), str(script)],
                stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                cwd=str(repo_root), start_new_session=True,  # langgraph 재시작에 안 딸려 죽게
            )
        deadline = time.monotonic() + COSMOS3NANO_BOOT_TIMEOUT
        while time.monotonic() < deadline:
            if await _healthy():
                return
            await asyncio.sleep(1.0)
        raise TimeoutError("Cosmos3-Nano 서버가 제한 시간 내 기동하지 않음")


async def generate_t2v_cosmos3nano(
    prompt: str,
    seed: int | None = None,
    width: int = 640,
    height: int = 480,
    num_frames: int = 49,
) -> dict:
    """:8700 /t2v 단발샷 (Cosmos3-Nano, t2v/cosmos3nano 독립 서버 프록시, Task 7.6).
    job과 무관한 단발 호출 — 이미지 입력 없이 프롬프트만으로 영상 1개, base64 mp4로
    바로 반환. 서버가 안 떠 있으면 여기서 직접 기동(온디맨드, VRAM 부족으로 상시
    서비스 불가 — server.py 쪽 유휴 워치독과 짝). ComfyUI와 GPU 메모리를 나눠 쓰므로
    llm/t2i/i2v/tts와 같은 batch 직렬화에도 태운다(oom_orchestrator 참고)."""
    if seed is None:
        seed = int(time.time())

    timeout = httpx.Timeout(connect=10.0, read=600.0, write=60.0, pool=None)
    async with oom.phase("t2v"), httpx.AsyncClient(timeout=timeout) as client:
        await _ensure_cosmos3nano_running(client)
        resp = await client.post(
            f"{COSMOS3NANO_URL}/generate",
            json={
                "prompt": prompt,
                "seed": seed,
                "width": width,
                "height": height,
                "num_frames": num_frames,
            },
        )
        resp.raise_for_status()
        video_bytes = resp.content

    return {
        "video_base64": base64.b64encode(video_bytes).decode(),
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

# ── ControlNet(canny) 구도 고정 — Kontext 텍스트 앵커만으론 줌인 드리프트("왕대갈") 못 잡아서
# 추가. Shakker-Labs Union Pro는 canny/depth/pose 등 여러 타입을 한 체크포인트로 지원 —
# 신규 depth 추정기 없이 core 내장 Canny 전처리만으로 구도(엣지) 고정한다.
FLUX_CONTROLNET_UNION = os.environ.get(
    "AGENT_FLUX_CONTROLNET_UNION", "flux1-dev-controlnet-union-pro-2.0.safetensors")
FLUX_CONTROLNET_STRENGTH = float(os.environ.get("AGENT_FLUX_CONTROLNET_STRENGTH", "0.6"))

# 스타일별 오버라이드 — clay/watercolor류(구도 유지가 스타일 본질)는 기본값(0.6/2.5) 그대로
# 두고, cinematic/cyberpunk처럼 조명·분위기 자체가 스타일인 애들만 낮춘 strength로
# ControlNet lock을 풀어준다(실측: 0.6에선 조명/재질이 거의 안 바뀜, 0.35에서 확 좋아짐).
# 목록에 없는 스타일은 FLUX_CONTROLNET_STRENGTH/FLUX_KONTEXT_GUIDANCE 기본값을 그대로 씀.
STYLE_CONTROLNET_STRENGTH: dict[str, float] = {"cinematic": 0.35, "cyberpunk": 0.35}
STYLE_KONTEXT_GUIDANCE: dict[str, float] = {"cinematic": 4.0}

# 배경 세그멘테이션 — ControlNet(canny)+ReferenceLatent가 원본 사진 전체(배경 포함)를
# 그대로 조건으로 걸어서, 웹캠 배경의 warm 조명색이 클레이 스타일(원래 warm/terracotta
# 편향)과 겹쳐 배경이 과하게 붉게 나오는 문제가 있었다(건호군.jpg는 우연히 중성 회색
# 배경이라 안 보임). 1차 수정(EmptyImage 단색 합성)은 과교정 — 배경 edge/색 정보가
# 아예 0이 되니 Kontext가 참조할 게 없어서 실측(웹캠 사무실 사진)에서 배경이 통짜
# 주황색으로 날아감. 단색 대신 원본 배경을 강하게 블러(ImageBlur)한 걸 합성 —
# 색/톤(사무실 창문·조명의 대략적인 색감)은 남기고 디테일 edge만 죽여서 ControlNet이
# 잔가지 구조까지 고정 안 하게 하면서도 KSampler가 완전 무근거로 배경색을 굴리지
# 않게 한다.
FLUX_BG_REMOVAL_MODEL = os.environ.get("AGENT_FLUX_BG_REMOVAL_MODEL", "birefnet.safetensors")
FLUX_BG_BLUR_RADIUS = 31   # ComfyUI ImageBlur 최댓값 — 얼굴 클로즈업(I2I 스타일 변환) 기본값
FLUX_BG_BLUR_SIGMA = 10.0
# 제품 합성 프레임 재통합용 약한 블러. 31/10.0을 그대로 쓰면 배경(농구골대·코트 마크)이
# 다 뭉개지고(2026-08-12 씬2 v8), 반대로 블러를 아예 빼면 심도 단서가 사라져 합성한
# 제품이 다시 "스티커"처럼 뜬다(v9/v10) — 약화가 정답이었다(v12, 사용자 승인).
FLUX_PRODUCT_BLUR_RADIUS = int(os.environ.get("AGENT_FLUX_PRODUCT_BLUR_RADIUS", "10"))
FLUX_PRODUCT_BLUR_SIGMA = float(os.environ.get("AGENT_FLUX_PRODUCT_BLUR_SIGMA", "4"))

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


# ── 제품 픽셀 합성 (A노선) ─────────────────────────────────────────────
# 2026-08-12~13 음료 광고 스파이크에서 확정된 조립 방식. 제품 참조 이미지를 diffusion에
# 통과시키지 않고 Pillow로 씬 배경에 직접 얹는다 — subject_ref(i2v_14b)가 "참조에 없는
# 새 요소"를 못 그리는 약점을 우회하고, 제품 identity 붕괴를 구조적으로 차단한다.
PRODUCT_WARM_TINT = (255, 220, 165)   # 골든아워 씬 톤 매칭(30% 곱연산)
# 0으로 두면 tint를 끈다. 이 값은 골든아워 전용으로 튜닝된 것이라 씬 조명이 차갑거나
# 실내면 제품만 주황빛이 돼 오히려 합성 티가 난다(2026-08-13 job e9059c29 씬3: 회색
# 스튜디오 배경에 주황 제품). 조명을 SCENE_LIGHTING_LOCK으로 골든아워에 고정하는 한
# 켜두는 게 맞고, 조명 상수를 바꾸면 이 값도 같이 조정해야 한다.
PRODUCT_TINT_STRENGTH = float(os.environ.get("AGENT_PRODUCT_TINT_STRENGTH", "0.30"))


def _apply_warm_tint(product: Image.Image, tint: tuple = PRODUCT_WARM_TINT,
                     strength: float | None = None) -> Image.Image:
    if strength is None:
        strength = PRODUCT_TINT_STRENGTH
    if strength <= 0:
        return product
    """제품 픽셀을 씬 조명 톤에 맞춘다. 스튜디오 흰조명 제품샷을 골든아워 배경에
    그대로 얹으면 색온도가 튀어 합성 티가 난다."""
    from PIL import ImageChops
    rgb = product.convert("RGB")
    multiplied = ImageChops.multiply(rgb, Image.new("RGB", rgb.size, tint))
    out = Image.blend(rgb, multiplied, strength).convert("RGBA")
    out.putalpha(product.split()[-1])
    return out


def _skin_mask(img: Image.Image, box: tuple[int, int, int, int]):
    """box 안의 살색 픽셀 마스크. 제품을 쥔 손 씬에서 손가락을 제품 위로 되돌려
    occlusion을 복원하는 데 쓴다 — 손가락이 제품 뒤에 있으면 첫 프레임이 물리적으로
    틀린 상태가 되고, LTX가 그걸 맞추려 수렴하는 1초가 그대로 화면에 보인다."""
    import numpy as np
    arr = np.array(img.convert("RGB")).astype(np.int16)
    r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
    skin = (r > g) & (g > b) & ((r - b) > 25) & (r > 110)
    mask = np.zeros(skin.shape, dtype=bool)
    x0, y0, x1, y1 = box
    mask[y0:y1, x0:x1] = skin[y0:y1, x0:x1]
    return mask


def compose_product_frame(
    bg_path: str | Path, product_path: str | Path, out_path: str | Path, *,
    width_ratio: float, center_x_ratio: float, bottom_y_ratio: float,
    warm_tint: bool = True, occlusion_box: tuple[int, int, int, int] | None = None,
) -> str:
    """씬 배경에 제품 픽셀을 얹어 I2V 첫 프레임을 만든다(diffusion 없음).

    비율은 배경 크기에 대한 상대값이다. occlusion_box를 주면 그 영역의 살색 픽셀을
    합성 뒤에 다시 얹어 손가락이 제품 앞을 가로지르게 한다(제품을 쥔 씬 전용).
    """
    import numpy as np
    bg = Image.open(bg_path).convert("RGBA")
    product = Image.open(product_path).convert("RGBA")
    if warm_tint:
        product = _apply_warm_tint(product)
    bw, bh = bg.size
    pw = max(1, int(bw * width_ratio))
    ph = max(1, int(product.height * (pw / product.width)))
    product = product.resize((pw, ph), Image.LANCZOS)
    px = int(bw * center_x_ratio - pw / 2)
    py = int(bh * bottom_y_ratio - ph)

    composed = bg.copy()
    composed.alpha_composite(product, (px, py))
    if occlusion_box:
        mask = _skin_mask(bg, occlusion_box)
        arr, bg_arr = np.array(composed), np.array(bg)
        arr[mask] = bg_arr[mask]
        composed = Image.fromarray(arr, "RGBA")

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    composed.convert("RGB").save(out_path, "PNG")
    return str(out_path)
async def release_comfyui_gpu(*, interrupt: bool = True) -> None:
    """ComfyUI가 물고 있는 GPU를 놓게 한다 — job 취소 경로에서 부른다.

    job을 취소해도 ComfyUI는 (1) 실행 중인 프롬프트를 끝까지 계산하고 (2) 로드한
    체크포인트를 그대로 들고 있는다. 2026-08-23 실측: 취소한 job의 모델이 21.4GB를
    잡고 있어서 다음 job의 FLUX 콜드로드가 `NVRM: Out of memory [NV_ERR_NO_MEMORY]`로
    죽었고(flux.service restart counter 1), 그 job이 `ConnectError: All connection
    attempts failed`로 통째로 실패했다. E2E 한 번을 그렇게 날렸다.

    AGENT_MAX_CONCURRENT_CLIPS=1이라 실행 중 프롬프트는 취소된 그 job의 것이다.
    실패는 조용히 삼킨다 — 취소 자체가 실패하면 안 된다.
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        for path, payload in (
            ("/interrupt", {}) if interrupt else (None, None),
            ("/free", {"unload_models": True, "free_memory": True}),
        ):
            if path is None:
                continue
            try:
                await client.post(f"{COMFYUI_URL}{path}", json=payload)
            except Exception as exc:                  # ComfyUI가 내려 있어도 취소는 성공해야 한다
                print(f"[cancel] ComfyUI {path} 실패({type(exc).__name__}: {exc}) — 무시")


# ── 제품 오버레이 (T2V 클립 위에 얹기, 조립+I2V 대체) ─────────────────
# 조립 첫 프레임을 I2V에 넣는 경로는 제품을 못 지킨다: LTX는 조건 이미지를 **첫 latent
# 하나(=8프레임)** 에만 쓰고 나머지는 denoise=1.0으로 새로 그린다(job dd16ef56 실측 —
# clip1 루마가 f0~f6 30.4로 고정이다가 f7 52, f8 107, f10 157로 붕괴). negative로 막을
# 수도 없다: KSampler cfg=1.0이면 ComfyUI가 uncond를 통째로 건너뛴다(comfy/samplers.py
# `if math.isclose(cond_scale, 1.0) ... uncond_ = None`).
#
# 그래서 순서를 뒤집는다. T2V로 사람 장면을 **먼저 끝내고** 제품을 그 위에 얹으면
# 제품을 지울 주체가 없다. 드리프트가 고쳐지는 게 아니라 발생할 자리가 사라진다.
# 전제 두 가지 — 카메라 고정, 제품 자체가 안 움직임(놓인 무드등 등). 둘 중 하나라도
# 깨지면 정적 오버레이는 물리적으로 틀리므로 이 경로를 쓰면 안 된다.
#
# 비율 의미는 compose_product_frame과 같다(폭/가로중심/바닥). 기본값은 "전경 오른쪽
# 아래" — 인물 동선 밖이라 사람이 제품 앞을 가로지를 확률이 가장 낮은 자리다.
# 크기는 **높이 기준**으로 잡는다. 세워둔 물건의 화면 존재감은 폭이 아니라 높이가
# 결정하는데, 폭 고정비를 쓰면 제품 종횡비에 따라 결과가 제멋대로다 — 2026-08-23 실측,
# 같은 width=0.16이 종횡비 0.62 램프에는 화면높이 47%, 0.57에는 51%, 0.40에는 **72%**가
# 됐다(job 8402186d에서 제품이 화면 오른쪽을 통째로 지배한 원인).
# WIDTH_RATIO는 이제 **상한**이다 — 넓적한 제품이 화면을 가로지르지 않게 막는 용도.
PRODUCT_OVERLAY_HEIGHT_RATIO = float(os.environ.get("AGENT_PRODUCT_OVERLAY_HEIGHT", "0.34"))
PRODUCT_OVERLAY_WIDTH_RATIO = float(os.environ.get("AGENT_PRODUCT_OVERLAY_WIDTH", "0.16"))
PRODUCT_OVERLAY_CENTER_X = float(os.environ.get("AGENT_PRODUCT_OVERLAY_CENTER_X", "0.80"))
# 2026-08-23 job 239b1d15: 램프 바닥을 화면 맨 아래(0.94)에 두니 받치는 면이 프레임
# 밖으로 잘려 램프가 "떠 있는" 느낌이었다(사용자 지적). 위로 올려(0.84) 램프 앞·아래로
# 전경 상판이 보이게 하면 그 위에 놓인 걸로 읽힌다 — 씬5 히어로컷이 이래서 얹혀 보였다.
PRODUCT_OVERLAY_BOTTOM_Y = float(os.environ.get("AGENT_PRODUCT_OVERLAY_BOTTOM_Y", "0.84"))
# 접지 그림자 세기. 0이면 끈다 — 유리/발광체는 옅게, 무거운 제품은 진하게.
PRODUCT_OVERLAY_SHADOW_ALPHA = int(os.environ.get("AGENT_PRODUCT_OVERLAY_SHADOW_ALPHA", "150"))


def _probe_dims(path: str) -> tuple[int, int]:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", str(path)],
        check=True, capture_output=True, text=True,
    )
    w, h = r.stdout.strip().split("x")[:2]
    return int(w), int(h)


def bake_product_layer(
    product_path: str | Path, out_path: str | Path, *, width: int, height: int,
    width_ratio: float = PRODUCT_OVERLAY_WIDTH_RATIO,
    height_ratio: float | None = PRODUCT_OVERLAY_HEIGHT_RATIO,
    center_x_ratio: float = PRODUCT_OVERLAY_CENTER_X,
    bottom_y_ratio: float = PRODUCT_OVERLAY_BOTTOM_Y,
    warm_tint: bool = True, shadow_alpha: int = PRODUCT_OVERLAY_SHADOW_ALPHA,
) -> str:
    """제품 컷아웃을 영상과 같은 크기의 **투명 PNG 한 장**으로 굽는다.

    프레임마다 다시 합성하지 않고 이 한 장을 ffmpeg overlay로 전 프레임에 얹는다 —
    카메라가 고정이므로 좌표가 변할 이유가 없고, 정지 레이어라 프레임 간 떨림도 없다.
    제품 밑에는 눌린 타원 그림자를 같이 굽는다. 없으면 제품이 바닥에서 붕 떠 보인다.
    """
    product = Image.open(product_path).convert("RGBA")
    if product.getchannel("A").getextrema()[0] == 255:
        raise ValueError(
            f"{Path(product_path).name}에 투명 배경이 없다 — _ensure_product_cutout을 먼저 태워라")
    if warm_tint:
        product = _apply_warm_tint(product)
    if height_ratio:
        # 높이로 잡고, 폭이 상한을 넘으면 폭에 맞춰 다시 줄인다(넓적한 제품 방어).
        ph = max(1, int(height * height_ratio))
        pw = max(1, int(product.width * (ph / product.height)))
        cap = max(1, int(width * width_ratio))
        if pw > cap:
            pw, ph = cap, max(1, int(product.height * (cap / product.width)))
    else:                                   # height_ratio=None → 옛 폭 고정비(프로브 호환)
        pw = max(1, int(width * width_ratio))
        ph = max(1, int(product.height * (pw / product.width)))
    product = product.resize((pw, ph), Image.LANCZOS)
    px = int(width * center_x_ratio - pw / 2)
    py = int(height * bottom_y_ratio - ph)

    layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    if shadow_alpha > 0:
        shadow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        rx, ry = pw * 0.62, max(3.0, ph * 0.055)
        cx, cy = px + pw / 2, py + ph
        ImageDraw.Draw(shadow).ellipse(
            [cx - rx, cy - ry, cx + rx, cy + ry], fill=(0, 0, 0, shadow_alpha))
        layer = Image.alpha_composite(
            layer, shadow.filter(ImageFilter.GaussianBlur(max(2.0, ry))))
    layer.alpha_composite(product, (px, py))
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    layer.save(out_path)
    return str(out_path)


def overlay_product_on_clip(
    clip_path: str | Path, product_path: str | Path, out_path: str | Path, *,
    width_ratio: float = PRODUCT_OVERLAY_WIDTH_RATIO,
    height_ratio: float | None = PRODUCT_OVERLAY_HEIGHT_RATIO,
    center_x_ratio: float = PRODUCT_OVERLAY_CENTER_X,
    bottom_y_ratio: float = PRODUCT_OVERLAY_BOTTOM_Y,
    warm_tint: bool = True, shadow_alpha: int = PRODUCT_OVERLAY_SHADOW_ALPHA,
    layer_path: str | Path | None = None,
) -> str:
    """T2V 클립 전 프레임에 제품을 같은 좌표로 얹는다(diffusion 없음, 제품 픽셀 무손실).

    레이어 크기는 클립에서 직접 읽는다 — 호출부가 WIDTH/HEIGHT를 잘못 넘겨 어긋나는
    사고를 막는다(I2V 경로는 1392x752 조립 프레임을 1280x704로 넣고 있었다).
    layer_path를 주면 구운 레이어를 남긴다(디버깅용).
    """
    width, height = _probe_dims(clip_path)
    with tempfile.TemporaryDirectory() as td:
        layer = Path(layer_path) if layer_path else Path(td) / "product_layer.png"
        bake_product_layer(
            product_path, layer, width=width, height=height,
            width_ratio=width_ratio, height_ratio=height_ratio,
            center_x_ratio=center_x_ratio,
            bottom_y_ratio=bottom_y_ratio, warm_tint=warm_tint, shadow_alpha=shadow_alpha)
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(clip_path), "-i", str(layer),
             "-filter_complex", "[0:v][1:v]overlay=0:0:format=auto[v]",
             "-map", "[v]", "-map", "0:a?", "-c:a", "copy",
             "-pix_fmt", "yuv420p", str(out_path)],
            check=True, capture_output=True)
    return str(out_path)



def _build_flux_kontext_graph(
    *, prompt: str, image_name: str, width: int, height: int, seed: int,
    lock_bg_color: bool, guidance: float, controlnet_strength: float,
    blur_radius: int = FLUX_BG_BLUR_RADIUS, blur_sigma: float = FLUX_BG_BLUR_SIGMA,
) -> dict:
    """docs.comfy.org/tutorials/flux/flux-1-kontext-dev 공식 워크플로와 동일한
    API-format 그래프(LoadImage→FluxKontextImageScale→VAEEncode→ReferenceLatent로
    입력 얼굴사진을 조건으로 건 뒤 EmptySD3LatentImage에서 새로 샘플링).

    lock_bg_color=True(claymation 전용)면 노드23/24로 배경을 원본 톤에 강제 매칭한다 —
    clay는 조명이 안 바뀌는 스타일이라 이게 warm 편향 배경버그를 잡아주는데, cinematic/
    cyberpunk처럼 조명·분위기 자체가 스타일 본질인 애들한텐 그 강제가 스타일을 눌러버려서
    "그냥 어두워지기만 함" 부작용이 남(실측 확인). 그래서 clay만 켠다."""
    graph = {
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
        # 배경 세그멘테이션 — 인물만 선명하게 두고 배경은 강하게 블러한 합성본(노드22)을
        # VAEEncode/Canny 양쪽에 물려서, 원본 배경의 세밀한 구조/색은 조건에서 빠지되
        # 대략적인 톤(사무실 조명·창문 색감 등)은 남는다. 최종 출력은 어차피
        # EmptySD3LatentImage(노드11, 순수 노이즈)에서 새로 샘플링되므로 배경도 그대로
        # 클레이 스타일로 그려짐 — 원본 구조 강제만 빠진다.
        "19": {"class_type": "LoadBackgroundRemovalModel",
               "inputs": {"bg_removal_name": FLUX_BG_REMOVAL_MODEL}},
        "20": {"class_type": "RemoveBackground",
               "inputs": {"bg_removal_model": ["19", 0], "image": ["7", 0]}},
        "21": {"class_type": "ImageBlur", "inputs": {
            "image": ["7", 0], "blur_radius": blur_radius, "sigma": blur_sigma,
        }},
        "22": {"class_type": "ImageCompositeMasked", "inputs": {
            "destination": ["21", 0], "source": ["7", 0], "x": 0, "y": 0,
            "resize_source": False, "mask": ["20", 0],
        }},
        "8": {"class_type": "VAEEncode", "inputs": {"pixels": ["22", 0], "vae": ["3", 0]}},
        "9": {"class_type": "ReferenceLatent",
              "inputs": {"conditioning": ["4", 0], "latent": ["8", 0]}},
        "10": {"class_type": "FluxGuidance",
               "inputs": {"conditioning": ["9", 0], "guidance": guidance}},
        "11": {"class_type": "EmptySD3LatentImage",
               "inputs": {"width": width, "height": height, "batch_size": 1}},
        # ControlNet(canny) 구도 고정 — 배경-제거 합성본(노드22)에서 엣지 뽑아 KSampler
        # conditioning에 얹는다. Kontext 텍스트 앵커만으론 줌인 드리프트 못 잡아서 추가.
        "15": {"class_type": "Canny",
               "inputs": {"image": ["22", 0], "low_threshold": 0.4, "high_threshold": 0.8}},
        "16": {"class_type": "ControlNetLoader",
               "inputs": {"control_net_name": FLUX_CONTROLNET_UNION}},
        "17": {"class_type": "SetShakkerLabsUnionControlNetType",
               "inputs": {"control_net": ["16", 0], "type": "canny"}},
        "18": {"class_type": "ControlNetApplyAdvanced", "inputs": {
            "positive": ["10", 0], "negative": ["5", 0], "control_net": ["17", 0],
            "image": ["15", 0], "vae": ["3", 0], "strength": controlnet_strength,
            "start_percent": 0.0, "end_percent": 1.0,
        }},
        "12": {"class_type": "KSampler", "inputs": {
            "model": ["1", 0], "seed": seed, "steps": FLUX_KONTEXT_STEPS, "cfg": 1.0,
            "sampler_name": "euler", "scheduler": "simple",
            "positive": ["18", 0], "negative": ["18", 1], "latent_image": ["11", 0],
            "denoise": 1.0,
        }},
        "13": {"class_type": "VAEDecode", "inputs": {"samples": ["12", 0], "vae": ["3", 0]}},
    }
    if lock_bg_color:
        # 배경 색 고정(clay 전용) — ControlNet은 edge만 잠그고 색은 안 건드려서 clay
        # 스타일의 warm/테라코타 편향이 배경 조명색까지 밀어붙이는 문제(실측: 사무실 흰
        # 형광등이 주황으로 뜸)가 있었다. KSampler 출력 전체를 블러 배경(노드21, 원본
        # 톤)에 Reinhard LAB color-match(KJNodes ColorMatchV2, 이미 설치돼있음)로 맞춘 뒤,
        # 인물 부분만 보정 전 원본 생성물(노드13)로 다시 덮어써서 얼굴/피부 clay 톤은
        # 안 건드린다.
        graph["23"] = {"class_type": "ColorMatchV2", "inputs": {
            "image_target": ["13", 0], "image_ref": ["21", 0],
            "method": "reinhard_lab_gpu", "strength": 1.0, "multithread": True,
        }}
        graph["24"] = {"class_type": "ImageCompositeMasked", "inputs": {
            "destination": ["23", 0], "source": ["13", 0], "x": 0, "y": 0,
            "resize_source": False, "mask": ["20", 0],
        }}
        final_image = ["24", 0]
    else:
        final_image = ["13", 0]
    graph["14"] = {"class_type": "SaveImage",
                   "inputs": {"images": final_image, "filename_prefix": "i2i_style"}}
    return graph


async def _submit_and_fetch_image(client: httpx.AsyncClient, graph: dict, what: str) -> bytes:
    """ComfyUI에 그래프를 제출하고 첫 출력 이미지 바이트를 받아온다."""
    resp = await client.post(f"{COMFYUI_URL}/prompt", json={"prompt": graph})
    resp.raise_for_status()
    prompt_id = resp.json()["prompt_id"]
    started_at = time.time()
    history_item = None
    while history_item is None:
        if time.time() - started_at > STANDIN_QUEUE_TIMEOUT:
            raise TimeoutError(f"{what}이(가) 제한 시간 내 완료되지 않음")
        history = (await client.get(f"{COMFYUI_URL}/history/{prompt_id}")).json()
        if prompt_id in history:
            history_item = history[prompt_id]
        else:
            await asyncio.sleep(2.0)
    if history_item.get("status", {}).get("status_str") == "error":
        raise RuntimeError(f"{what} 실행 오류 {history_item.get('status', {}).get('messages')}")
    media = None
    for node_out in history_item.get("outputs", {}).values():
        media = node_out.get("images")
        if media:
            break
    if not media:
        raise RuntimeError(f"{what} 출력 이미지 없음")
    output = media[0]
    png = await client.get(f"{COMFYUI_URL}/view", params={
        "filename": output["filename"], "subfolder": output.get("subfolder", ""),
        "type": output.get("type", "output"),
    })
    png.raise_for_status()
    return png.content


async def run_flux_kontext(
    image_bytes: bytes, *, prompt: str, seed: int, upload_name: str, what: str,
    guidance: float = FLUX_KONTEXT_GUIDANCE,
    controlnet_strength: float = FLUX_CONTROLNET_STRENGTH,
    blur_radius: int = FLUX_BG_BLUR_RADIUS, blur_sigma: float = FLUX_BG_BLUR_SIGMA,
) -> bytes:
    """Flux Kontext 단발 실행(입력 이미지 → 재렌더된 이미지 바이트)."""
    normalized, img_width, img_height = _normalize_i2v_input(image_bytes)
    width, height = _flux_kontext_dims(img_width, img_height)
    timeout = httpx.Timeout(connect=10.0, read=300.0, write=60.0, pool=None)
    async with oom.phase("i2i"), httpx.AsyncClient(timeout=timeout) as client:
        up = await client.post(
            f"{COMFYUI_URL}/upload/image",
            files={"image": (upload_name, normalized, "image/png")},
            data={"overwrite": "true"},
        )
        up.raise_for_status()
        uj = up.json()
        image_name = f"{uj['subfolder']}/{uj['name']}" if uj.get("subfolder") else uj["name"]
        graph = _build_flux_kontext_graph(
            prompt=prompt, image_name=image_name, width=width, height=height, seed=seed,
            lock_bg_color=False, guidance=guidance,
            controlnet_strength=controlnet_strength,
            blur_radius=blur_radius, blur_sigma=blur_sigma)
        return await _submit_and_fetch_image(client, graph, what)


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
            prompt=prompt, image_name=image_name, width=width, height=height, seed=seed,
            lock_bg_color=(style == "claymation"),
            guidance=STYLE_KONTEXT_GUIDANCE.get(style, FLUX_KONTEXT_GUIDANCE),
            controlnet_strength=STYLE_CONTROLNET_STRENGTH.get(style, FLUX_CONTROLNET_STRENGTH))
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


# ── 제품 씬 조립 경로 (A노선, 6.23) ──────────────────────────────────
# 2026-08-12~13 음료 광고 스파이크에서 확정된 파이프라인을 그대로 옮긴 것.
# subject_ref(Wan i2v_14b)는 참조에 **있는** 대상 identity 유지는 강하지만 참조에
# **없는** 새 요소(사람·손·스토리)를 못 그린다. 그래서 제품 픽셀은 diffusion을 거치지
# 않고 Pillow로 첫 프레임에 직접 얹고, I2V에는 "움직임만" 시킨다.
#
# 비율·시드·프롬프트는 스파이크 best-case를 기본값으로 고정한다(Plans 6.23 결정).
# 배경이 바뀌면 비율이 깨지는 게 실측돼 있으나(씬2에서 의상 단어 하나 바꾸자 벤치
# 구조가 통째로 변함, 씬3a는 center_x 6% 이동만으로 붕괴) 이 시나리오 재현이 목적이라
# 조정 UI는 붙이지 않는다.

# 제품이 놓여 있는 씬(씬2형): 벤치·바닥 등 전경에 큼직하게.
# 2026-08-14 라이브 재검증에서 옛값 (0.075, 0.30, 0.80)이 병을 벤치가 아닌 **코트 허공**에
# 폭 95px(0.074)로 붙였다. 그 값은 스파이크 배경 한 장에서 손으로 맞춘 절대 좌표였고,
# 프로덕션은 배경을 매번 새로 그린다. PRODUCT_PLACED_BG_PROMPT가 지시하는 구도에서 배경이
# 실제로 놓을 면을 그리는 위치(x 0.32~0.68, y 0.86~1.0)의 중앙·하단으로 옮긴다.
PRODUCT_PLACED_RATIOS = (0.15, 0.50, 0.97)
# 인물이 손에 쥔 씬(씬3a형): 그립 위치. 폭은 이제 얼굴 기준으로 계산하므로(아래
# PRODUCT_FACE_RATIO) 이 0.10은 얼굴 검출이 실패했을 때의 폴백값이다.
PRODUCT_HELD_RATIOS = (0.10, 0.62, 0.87)
# 쥔 제품의 폭 = 얼굴 폭 × 이 비율. 스파이크 실측(병폭 139px / 얼굴폭 276px = 0.504).
# 프레임 폭 고정비로 두면 배경마다 인물 크기가 달라 어긋나고, 작게 시작하면 LTX가 재생
# 중에 "저 얼굴 옆에 있을 크기"로 키우는 과정이 화면에 보인다(clip19/21, 2026-08-14 씬3 재현).
PRODUCT_FACE_RATIO = float(os.environ.get("AGENT_PRODUCT_FACE_RATIO", "0.50"))
# 손가락을 제품 위로 되돌릴 영역. 배경(그립 손)의 좌표에 종속된 값이다.
PRODUCT_HELD_OCCLUSION_BOX = (790, 430, 905, 655)
PRODUCT_RECOMPOSE_CONTROLNET = float(os.environ.get("AGENT_PRODUCT_RECOMPOSE_CN", "0.45"))
PRODUCT_BG_CONTROLNET = 0.35   # cinematic 프리셋값 — 0.6은 조명/재질이 거의 안 바뀜
PRODUCT_BG_GUIDANCE = 4.0

# 인물이 제품을 쥐는 씬의 배경. **빈 그립 손을 미리 그려두는 게 핵심** — 첫 프레임에
# 그립이 없으면 LTX가 손과 제품을 같이 발명하면서 라벨·캡이 통째로 날아간다(clip13/16).
PRODUCT_HELD_BG_PROMPT = (
    "Keep this exact same person — same face, same facial features, same hairstyle, "
    "same age — do not change their identity. Re-render them as a cinematic "
    "medium-close commercial shot: their face and upper chest fill the frame, their "
    "expression is calm and relaxed with a smooth untroubled brow and a faint "
    "satisfied smile, eyes open and looking down toward their own hand. Their right "
    "hand is raised in front of their chest at collarbone height, forearm angled up "
    "across the body, fingers curled into a firm cylindrical grip as if holding a "
    "drink bottle, but the hand is empty with an open gap between the curled fingers "
    "and the thumb. Shallow depth of field with the background softly out of focus, "
    "photorealistic."
)
PRODUCT_HELD_EMPTY_HAND = (
    "The hand is empty at this moment — nothing is in it yet, no bottle, no cup, no "
    "can. They have not started drinking."
)
# 인물 정본이 없는 job("시나리오만" 모드)의 쥔 씬 배경. Kontext 재렌더가 아니라 T2I로
# 처음부터 그리므로 위 두 상수를 그대로 못 쓴다 — 둘 다 제품 명사를 **부정문으로** 쓰는데
# (`as if holding a drink bottle, but the hand is empty`, `no bottle, no cup, no can`)
# Kontext는 원본 픽셀이 있어 버티지만 T2I는 부정을 못 읽고 그 병을 그린다(_strip_product_
# phrases 주석의 실측과 같은 함정). 그래서 제품 명사를 아예 쓰지 않고 손 모양만 서술한다.
PRODUCT_HELD_T2I_FRAMING = (
    "a cinematic medium-close commercial shot: their face and upper chest fill the "
    "frame, their expression is calm and relaxed with a faint satisfied smile, eyes "
    "open and looking down toward their own hand. Their right hand is raised in front "
    "of their chest at collarbone height, forearm angled up across the body, fingers "
    "curled into a firm cylindrical grip closed around empty air, an open gap between "
    "the curled fingers and the thumb, the grip clearly empty. They wear a plain "
    "high crew-neck top that fully covers the chest and shoulders, no V-neck, no "
    "exposed chest or collarbone skin. Shallow depth of field with the background "
    "softly out of focus, photorealistic"
)
# 크루넥 지시는 미관이 아니라 locate_grip 때문이다. 그립 검출은 인물 마스크 안의 살색을
# 연결요소로 쪼개 "얼굴과 분리된 덩어리 = 팔·손"으로 본다. V넥으로 가슴 살이 보이면
# 얼굴-목-가슴이 한 덩어리로 이어지면서 팔 요소 판정이 무너져 병이 뺨에 붙는다
# (2026-08-14 job 8820932b 씬1 실측: center_x 0.741, 손은 0.45 근처였다). 베이스라인이
# 멀쩡했던 건 인물 정본이 흰 크루넥 티였기 때문이다.
# 합성한 제품을 씬 조명에 녹인다. "재설계하지 마라"를 반복 명시하지 않으면 Kontext가
# 라벨을 새로 그려버린다.
PRODUCT_RECOMPOSE_PROMPT_HELD = (
    "The exact same product from the reference image, unchanged shape, unchanged "
    "label, unchanged colors, unchanged cap — do not redesign it. Re-light and "
    "re-render only the product so it looks physically held in this person's hand in "
    "this exact scene: the curled fingers wrap around the product body with matching "
    "rim light and natural contact shadows where the fingers meet it, natural "
    "photographic grain, shallow depth of field."
)
# 마무리 히어로컷(제품 단독 클로즈업). 인물 씬 프레이밍을 그대로 쓰면 "인물이 카메라로
# 다가온다"가 박혀 있어 제품만 나와야 할 컷에 사람이 생긴다. 무인(無人)을 명시한다.
PRODUCT_SURFACE_FRAMING = (
    "shot from a low angle close to a bare empty surface in the foreground, that "
    "surface large and sharply in focus filling the lower half of the frame, the "
    "background far behind and softly out of focus, cinematic product commercial "
    "lighting"
)
PRODUCT_HERO_FRAMING = (
    "no people, nobody in frame, empty scene with no person visible, "
    "the image bleeding all the way to every edge of the frame with no border, "
    f"{PRODUCT_SURFACE_FRAMING}"
)
# 히어로컷은 제품이 주인공이라 크게 놓는다(놓인 씬의 0.075는 소품 크기다).
PRODUCT_HERO_RATIOS = (0.30, 0.50, 0.88)

# 제품 없는 인물 씬(씬4형)의 배경 = I2V 첫 프레임. 씬 문장을 그대로 주면 T2I가 문장의
# **마지막 동작**을 그린다 — 2026-08-14 job 1559ee49 씬4 실측: "코트 안쪽으로 달려
# 들어가 골대를 향해 슛을 쏜다"에서 이미 슛을 쏘는 정지 자세가 나왔고, 그 자세에서
# 시작하니 클립 내내 팔만 올라갔다(달리기 없음, 움직임 느림). 첫 프레임은 동작 **직전·
# 도중**이어야 한다 — hand_held 배경이 "빈 그립 손"을 요구하는 것과 같은 처방이다.
# 인물 정본을 Kontext로 재렌더할 때 항상 앞에 붙는 identity lock. 이 문구가 없으면
# Kontext가 얼굴을 새로 그린다.
PERSON_BG_IDENTITY = (
    "Keep this exact same person — same face, same facial features, same hairstyle, "
    "same age, no added facial hair, no added beard or moustache — do not change their "
    "identity. "
)
# 놓인 제품 씬(씬2형) 배경. 스파이크 씬2 배경이 그랬듯 **놓일 면을 비워둔 채** 만든다 —
# 제품 픽셀은 다음 단계에서 얹으므로 여기서 병을 그리면 결과에 병이 둘이 된다.
# 인물은 카메라 쪽으로 다가오되, 카메라에 달려들어 상체가 화면을 채우면 안 된다
# (2026-08-14 job 1559ee49 씬2: 저각+접근 지시가 겹쳐 허리를 세우고 렌즈로 돌진).
# 인물 동작과 "놓일 면"은 시나리오마다 다르다 — 농구는 벤치로 달려오지만 실내 무드등
# 광고는 협탁 앞에 서 있다. 기본값은 베이스라인 job 3ded2f29 재현값이라 그대로 둔다.
PLACED_BG_PERSON_ACTION = os.environ.get(
    "AGENT_PLACED_BG_ACTION",
    "running toward the camera with a natural upright running form")
PLACED_BG_SURFACE = os.environ.get("AGENT_PLACED_BG_SURFACE", "a bench top")
PRODUCT_PLACED_BG_PROMPT = (
    f"{PERSON_BG_IDENTITY}Re-render them as a cinematic wide commercial shot: the "
    f"person is several steps away in the mid-ground, small in the frame, "
    f"{PLACED_BG_PERSON_ACTION}, their whole body visible. "
    f"In front of them, close to the camera, a bare empty flat surface — "
    f"{PLACED_BG_SURFACE} — fills the lower foreground across the bottom third of the "
    "frame, completely empty with nothing resting on it, large and sharply in focus. "
    "Photorealistic."
)
# 제품이 화면에 없는 인물 씬(씬4형) 배경. 여기서는 씬 동작을 주입해야 그림이 된다.
PERSON_SCENE_ACTION_BG_PROMPT = (
    f"{PERSON_BG_IDENTITY}Re-render them full-body in the scene described below, "
    "keeping the whole person visible in a cinematic wide shot. Photorealistic."
)
PERSON_SCENE_FIRST_FRAME = (
    "this is the very first frame of a moving shot: the person is at the START of the "
    "described action and has not finished it yet, caught mid-motion with their weight "
    "already shifting and a natural motion blur on the moving limbs, never a posed "
    "static end-of-action pose"
)

# 배경 프롬프트에서 제품을 가리키는 구절을 지운다. 제품 픽셀은 다음 단계에서 얹으므로
# 배경에 제품이 그려지면 결과에 제품이 둘이 된다(2026-08-13 히어로컷 실측: T2I가 콜라색
# 대형 병을 그리고 그 앞에 우리 제품이 작게 합성됐고, Kontext 재통합이 둘을 하나로 합침).
#
# "no bottle, no can" 같은 **부정문으로는 못 막는다** — FLUX는 부정을 못 읽고 오히려 그
# 개념을 그린다(같은 날 씬1에서 "no logos and no text"가 로고를 2개 만든 실측). 그래서
# 금지 대신 해당 명사구를 문장에서 제거한다.
# 명사구만 지우고 뒤따르는 배경 서술("on the wooden bench at the edge of the court")은
# 남긴다 — 그건 배경 생성에 그대로 필요한 정보다.
# 수식어를 열거하면 반드시 샌다 — 2026-08-13 UI E2E job 3ded2f29 씬2가 그렇게 뚫렸다
# (`reaching towards a water bottle`, `focused on the approaching bottle` 둘 다 안 걸려
# T2I가 무라벨 병을 그렸고 결과에 병이 둘). 한정사 뒤 형용사는 개수·종류를 모르므로
# 열거 대신 최대 3개까지 임의 단어를 허용하고, 소유격 한정사도 받는다.
_PRODUCT_PHRASE_RE = re.compile(
    r"\b(?:the|a|an|his|her|their|its|this|that)\s+(?:\w+\s+){0,3}"
    r"(?:bottle|bottles|can|cans|cup|cups|beverage|beverages|"
    # 조명 제품 광고. 히어로컷 배경은 씬 문장을 그대로 쓰므로 여기 없으면 T2I가
    # 자기 나름의 램프를 그리고 그 앞에 우리 제품이 또 합성된다(램프 2개).
    r"lamp|lamps|lantern|lanterns|product|products)\b", re.I)
# 제품이 문장의 주어일 때 남는 조각("stands alone on the bench" 같은 서술어)은 그대로
# 둔다 — 문법이 어색해도 배경 정보는 보존된다.


def _strip_product_phrases(text: str) -> str:
    cleaned = _PRODUCT_PHRASE_RE.sub("", text or "")
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    cleaned = re.sub(r"(,\s*){2,}", ", ", cleaned).strip(" ,")
    return cleaned

# 놓인 제품 씬의 카메라 고정. 2026-08-14 라이브에서 clip2는 **벤치와 병이 같이 흔들렸다** —
# 배치 문제가 아니다. 씬 프롬프트에 "the camera slowly tracks his movement horizontally"가
# 들어 있고, 놓인 씬 배경은 놓일 면을 카메라 코앞 전경에 두므로
# 시차가 최대가 된다. 합성 제품은 배경 픽셀에 박혀 있어 그 면과 함께 통째로 움직인다.
# 배치 비율(A-1)로는 안 없어진다 — 카메라 지시 자체를 빼야 한다.
_CAMERA_CLAUSE_RE = re.compile(r"\bcamera\b", re.I)
# 카메라 절을 지우면 뒤따르는 분사구("following his arc through the space...")가 주어를
# 잃고 인물 동작으로 읽힌다. 이어지는 절도 같이 뗀다.
_CAMERA_CONT_RE = re.compile(
    r"^\s*(?:following|tracking|panning|moving|drifting|circling|sweeping|gliding)\b", re.I)
STATIC_CAMERA_CLAUSE = ("the camera is locked off on a tripod, completely static framing "
                        "with no pan, no tilt, no dolly and no zoom")
PRODUCT_PLACED_NEGATIVE_EXTRA = (
    "camera pan, camera tracking shot, camera shake, moving foreground, "
    "sliding bench, sliding product, product drifting, wobbling objects")


def _lock_camera(prompt: str) -> str:
    """씬 프롬프트에서 카메라 이동 지시를 빼고 고정 카메라를 못박는다(놓인 제품 씬 전용)."""
    kept, drop_next = [], False
    for clause in re.split(r"(?<=[;,])\s*", prompt or ""):
        if _CAMERA_CLAUSE_RE.search(clause):
            drop_next = True
            continue
        if drop_next and _CAMERA_CONT_RE.match(clause):
            continue
        drop_next = False
        kept.append(clause)
    cleaned = re.sub(r"[;,\s]+$", "", " ".join(kept).strip())
    return f"{cleaned}; {STATIC_CAMERA_CLAUSE}"


PRODUCT_RECOMPOSE_PROMPT_PLACED = (
    "The exact same product from the reference image, unchanged shape, unchanged "
    "label, unchanged colors, unchanged cap — do not redesign it. Re-light and "
    "re-render only the product so it looks physically photographed standing in this "
    "exact scene: matching key light direction, matching soft contact shadow on the "
    "surface it rests on, natural photographic grain, shallow depth of field with the "
    "background softly out of focus but still recognizable, not abstract blur."
)


def _pad_to_wide(img: Image.Image, target_aspect: float) -> Image.Image:
    """세로 인물 정본을 와이드 캔버스로 확장. 여백은 배경 코너색으로 채워 이음매를
    만들지 않는다 — 하드 엣지가 남으면 Kontext의 canny가 그 액자선까지 구도로 잠근다."""
    rgb = img.convert("RGB")
    w, h = rgb.size
    new_w = int(round(h * target_aspect))
    if new_w <= w:
        return rgb
    corners = [rgb.getpixel(p) for p in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1))]
    fill = tuple(sum(c[i] for c in corners) // len(corners) for i in range(3))
    canvas = Image.new("RGB", (new_w, h), fill)
    canvas.paste(rgb, ((new_w - w) // 2, 0))
    return canvas


async def person_mask(image_bytes: bytes, upload_name: str = "person_mask_input.png"):
    """birefnet(ComfyUI 내장 RemoveBackground)으로 인물 실루엣 마스크를 뽑는다.

    색만으로는 피부를 못 가른다 — 골든아워 코트 바닥이 피부와 색공간에서 겹친다
    (실측: 손등 rgb(195,101,32) vs 코트 rgb(213,134,80)). 배경을 먼저 지워야
    피부 검출이 의미를 갖는다. Kontext 그래프가 이미 쓰는 노드라 신규 모델 없음.
    """
    import numpy as np
    graph = {
        "1": {"class_type": "LoadImage", "inputs": {"image": upload_name}},
        "2": {"class_type": "LoadBackgroundRemovalModel",
              "inputs": {"bg_removal_name": FLUX_BG_REMOVAL_MODEL}},
        "3": {"class_type": "RemoveBackground",
              "inputs": {"bg_removal_model": ["2", 0], "image": ["1", 0]}},
        "4": {"class_type": "MaskToImage", "inputs": {"mask": ["3", 0]}},
        "5": {"class_type": "SaveImage",
              "inputs": {"images": ["4", 0], "filename_prefix": "person_mask"}},
    }
    timeout = httpx.Timeout(connect=10.0, read=300.0, write=60.0, pool=None)
    async with oom.phase("i2i"), httpx.AsyncClient(timeout=timeout) as client:
        up = await client.post(
            f"{COMFYUI_URL}/upload/image",
            files={"image": (upload_name, image_bytes, "image/png")},
            data={"overwrite": "true"},
        )
        up.raise_for_status()
        uj = up.json()
        graph["1"]["inputs"]["image"] = (
            f"{uj['subfolder']}/{uj['name']}" if uj.get("subfolder") else uj["name"])
        png = await _submit_and_fetch_image(client, graph, "인물 마스크")
    gray = np.array(Image.open(BytesIO(png)).convert("L"))
    return gray > 128


GRIP_LABEL_SCALE = 4   # 연결요소 라벨링 축소 배율. bbox만 필요하므로 1/4로 충분하고,
                       # 원본 해상도(1392x752≈105만 px)를 순수 파이썬 BFS로 도는 것보다
                       # 16배 빠르다(scipy.ndimage.label을 쓰려고 의존성을 늘리지 않는다).


def locate_grip(bg_bytes: bytes, mask) -> dict | None:
    """배경에서 '들어올린 손' 영역을 찾아 제품 배치 좌표를 산출한다.

    인물 마스크 안에서 무채색(흰 티셔츠, r≈g≈b)을 뺀 나머지가 피부(얼굴·목·팔·손)다.
    팔을 들고 있으면 팔·손이 얼굴과 분리된 연결요소로 잡히고, 그 요소의 **위쪽 끝**이
    손가락이다(팔은 아래에서 올라오고 손이 가장 높다).

    반환: {"occlusion_box", "center_x_ratio", "bottom_y_ratio", "hand_box"}
    손을 못 찾으면 None — 호출부가 고정 기본값으로 폴백한다.
    """
    import numpy as np
    from collections import deque

    arr = np.array(Image.open(BytesIO(bg_bytes)).convert("RGB")).astype(np.int16)
    full_h, full_w = arr.shape[:2]
    r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
    # 피부 판정. r > g > b 순서를 **반드시** 함께 본다 — `(r-b)>40` 만으로는 따뜻한 색
    # 옷이 전부 피부로 걸린다(2026-08-14 job probe_person_ref 씬1 실측: 핑크 상의
    # rgb(247,122,172)가 r-b=75로 통과해 얼굴·팔·배·상의가 한 덩어리가 됐고, 살색이
    # 프레임의 22%를 덮으면서 연결요소 분리가 무너져 face_box가 8x0px 파편으로 잡혔다.
    # 그 결과 제품 폭이 얼굴폭×0.5 = 4px로 계산돼 병이 사실상 사라졌다).
    # 핑크는 g < b라 이 조건에서 걸러진다. 같은 파일의 _skin_mask가 쓰는 판정식과 맞춘 것 —
    # 두 곳이 다른 기준을 쓸 이유가 없었다.
    skin_full = mask & (r > g) & (g > b) & ((r - b) > 40) & (r > 90)
    if skin_full.sum() < 500:
        return None

    s = GRIP_LABEL_SCALE
    skin = skin_full[::s, ::s]
    h, w = skin.shape
    labels = np.zeros(skin.shape, np.int32)
    comps = []          # (픽셀수, x0, y0, x1, y1, label)
    current = 0
    for y in range(h):
        for x in range(w):
            if skin[y, x] and labels[y, x] == 0:
                current += 1
                queue = deque([(y, x)])
                labels[y, x] = current
                count = 0
                x0 = x1 = x
                y0 = y1 = y
                while queue:
                    cy, cx = queue.popleft()
                    count += 1
                    x0, x1 = min(x0, cx), max(x1, cx)
                    y0, y1 = min(y0, cy), max(y1, cy)
                    for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        ny, nx = cy + dy, cx + dx
                        if 0 <= ny < h and 0 <= nx < w and skin[ny, nx] and labels[ny, nx] == 0:
                            labels[ny, nx] = current
                            queue.append((ny, nx))
                comps.append((count, x0, y0, x1, y1, current))
    if not comps:
        return None                       # 피사체 자체가 없다 — 호출부가 폴백
    comps.sort(reverse=True)
    # 상위 3개를 그냥 쓰면 안 된다 — 성분 수가 적으면 **파편이 후보에 낀다**. 그 파편이
    # 프레임 맨 위에 있으면 "가장 위에서 시작하는 것 = 얼굴" 규칙이 그걸 얼굴로 고른다
    # (2026-08-14 probe_person_ref 씬1 실측: 얼굴 2662px·손 1709px 사이에 정수리 파편
    # 65px이 끼어 face_w가 0.046으로 잡혔고, 제품 폭이 얼굴폭×0.5 = 32px이 됐다).
    # 최대 덩어리의 1/4 미만은 사람의 부위가 아니라 노이즈로 본다.
    floor = comps[0][0] * 0.25
    big = [c for c in comps[:3] if c[0] >= floor] or comps[:1]
    # 얼굴은 가장 위에서 시작하는 큰 덩어리. 팔·손은 그보다 아래에서 올라온다.
    face = min(big, key=lambda c: c[2])
    fx0, fy0, fx1, fy1 = face[1] * s, face[2] * s, face[3] * s, face[4] * s
    face_w = max(1, fx1 - fx0)
    face_h = max(1, fy1 - fy0)

    # ── 허용 밴드(clamp) ────────────────────────────────────────────────
    # 검출값을 그대로 믿지 않는다. 그립은 해부학적으로 **턱 아래 가슴 높이**,
    # **얼굴 폭 기준 좌우 한 뼘 안쪽**에 있다. 검출이 그 밖을 짚으면(마시는 자세
    # 배경에서 손이 입가로 올라가 귀 옆을 가리킨 실측, 2026-08-13 5컷 라이브)
    # 기각 대신 밴드 경계로 끌어당긴다 — 기각하면 스파이크 배경 좌표계에서 뽑은
    # 고정 픽셀값으로 떨어져 새 배경에서는 병이 가슴 한복판이나 허공에 붙는다.
    y_lo, y_hi = fy1 + 0.15 * face_h, fy1 + 1.40 * face_h
    # 좌우 대칭으로 잡는다. 예전 값(-0.60/+1.20)은 손이 화면 오른쪽에 오는 배경 한 장에
    # 맞춘 비대칭이었는데, Kontext는 같은 프롬프트로도 손을 화면 **왼쪽**에 그린다
    # (2026-08-14 probe_person_ref 씬1). 한쪽만 좁혀둘 근거가 없다.
    x_lo, x_hi = fx0 - 1.20 * face_w, fx1 + 1.20 * face_w

    def _clamp(v, lo, hi):
        return max(lo, min(hi, v))

    arms = [c for c in big if c[5] != face[5]]
    # 팔 후보가 둘이면(민소매·반팔이라 양팔이 다 드러난 경우) **크기로는 못 가른다** —
    # 2026-08-14 probe_person_ref 씬1에서 쥔 팔 2606px, 늘어뜨린 팔 2607px로 1픽셀 차이가
    # 났고 max()가 늘어뜨린 쪽을 골라 병이 반대편 어깨에 붙었다.
    # 구분 신호는 배경 프롬프트에 이미 있다 — "forearm angled up across the body".
    # 쥔 팔은 몸을 가로질러 오므로 얼굴 x범위와 겹치고, 늘어뜨린 팔은 몸 바깥에 있다.
    # 겹치는 후보가 없으면(정면 단독 팔) 기존대로 최대 크기로 폴백한다.
    across = [c for c in arms if c[1] * s <= fx1 and c[3] * s >= fx0]
    arms = across or arms
    hand_box = None
    if arms:
        arm = max(arms, key=lambda c: c[0])
        _, _, ay0, _, ay1, arm_label = arm
        # 팔 요소의 상단 40% = 손. 그 아래는 팔뚝이라 제품이 놓일 자리가 아니다.
        hand_y1 = ay0 + max(1, int((ay1 - ay0) * 0.40))
        band = labels[ay0:hand_y1 + 1, :] == arm_label
        ys, xs = np.where(band)
        if len(xs):
            hx0, hx1 = int(xs.min()) * s, int(xs.max()) * s
            hand_box = (hx0, ay0 * s, hx1, hand_y1 * s)

    if hand_box:
        hx0, hy0, hx1, hy1 = hand_box
        hand_w = max(1, hx1 - hx0)
        # 그립 입구는 손가락 끝 쪽(바깥 모서리)이다. 스파이크 수동 튜닝값(center_x
        # 0.62 = 863px)이 손 bbox 우측 끝과 거의 같았다 — 병이 손 안쪽이 아니라
        # 손가락이 감싸는 바깥 모서리에 걸친다.
        center_x = _clamp(hx1, x_lo, x_hi)
        center_y = _clamp((hy0 + hy1) / 2, y_lo, y_hi)
        # occlusion은 손 bbox 전체가 아니라 **오른쪽 절반(손가락 쪽)**만 쓴다. 전체를
        # 쓰면 손등까지 제품 앞으로 복원돼 병이 손 뒤로 숨는다(v9 실패 방향).
        # 단, 손 bbox가 밴드 밖이라 좌표가 실제로 당겨졌으면 이 상자는 더 이상 손을
        # 가리키지 않으므로 버린다(엉뚱한 살색 픽셀을 제품 위로 복원하게 된다).
        moved = abs(center_x - hx1) > 0.05 * face_w or abs(center_y - (hy0 + hy1) / 2) > 0.05 * face_h
        occlusion = None if moved else (hx0 + hand_w // 2, hy0, hx1, hy1)
        source = "clamped" if moved else "hand"
    else:
        # 손을 못 찾았다(팔이 몸통과 붙어 한 덩어리이거나 소매에 가림). 얼굴 기준
        # 기하 추정 — PRODUCT_HELD_BG_PROMPT가 지시하는 자세("가슴 앞 쇄골 높이,
        # 팔은 몸을 가로질러 위로")의 좌표다. 고정 픽셀 폴백과 달리 배경이 바뀌어도
        # 얼굴을 따라간다.
        center_x = _clamp(fx1 + 0.35 * face_w, x_lo, x_hi)
        center_y = _clamp(fy1 + 0.70 * face_h, y_lo, y_hi)
        # 손 위치를 모르는 상태에서 occlusion 상자를 그리면 가슴·목의 살색이 제품
        # 위로 복원돼 병이 뭉개진다. 손가락 복원을 포기하는 쪽이 손해가 작다.
        occlusion = None
        hand_box = (int(center_x - 0.4 * face_w), int(center_y - 0.5 * face_h),
                    int(center_x + 0.4 * face_w), int(center_y + 0.5 * face_h))
        source = "estimated"

    return {
        "hand_box": hand_box,
        "occlusion_box": occlusion,
        "source": source,
        # 제품 크기를 얼굴 기준으로 잡기 위해 호출부에 넘긴다(PRODUCT_FACE_RATIO).
        "face_box": (fx0, fy0, fx1, fy1),
        "face_w_ratio": face_w / full_w,
        "center_x_ratio": center_x / full_w,
        # compose_product_frame은 제품 '바닥' 기준이라 호출부가 제품 높이를 알아야
        # 변환할 수 있다. 여기서는 손 중심만 넘긴다.
        "center_y_ratio": center_y / full_h,
    }
# ── 제품 오버레이 씬 경로 (B노선, 2026-08-23) ─────────────────────────
# A노선(조립+I2V)은 제품을 첫 프레임에 박고 LTX에 넘긴다. LTX는 조건 이미지를 첫 latent
# 하나(=8프레임)에만 쓰고 나머지는 denoise=1.0으로 새로 그리므로 제품이 지워진다
# (job dd16ef56 실측: clip1 루마 f0~f6 30.4 고정 → f10 157). negative로도 못 막는다 —
# KSampler cfg=1.0이면 ComfyUI가 uncond를 통째로 건너뛴다(comfy/samplers.py의
# `if math.isclose(cond_scale, 1.0) ... uncond_ = None`).
#
# B노선은 순서를 뒤집는다. T2V로 사람 장면을 **먼저 끝내고** 제품을 그 위에 얹는다.
# 제품이 diffusion을 아예 안 거치므로 지워질 자리가 없다. 전제는 두 가지 —
# 카메라 고정, 제품이 스스로 안 움직임. 손에 쥔 씬은 둘 다 깨지므로 A노선에 남긴다.
#
# 부수 효과: 제품 위치·크기 튜닝에 GPU가 필요없다(ffmpeg만). A노선은 비율 하나 바꿀
# 때마다 클립을 통째로 다시 뽑아야 했다.
PRODUCT_OVERLAY_ENABLED = os.environ.get("AGENT_PRODUCT_OVERLAY", "1") not in ("0", "false", "")

# 제품이 얹힐 자리. 하단 전폭을 덮게 해야 고정 비율이 표면을 빗나가지 않는다 —
# "lower-right side table"로 좁게 지시하면 그 협탁이 x 0.72에서 끝나 제품이 러그 위에
# 떴다(프로브 v3 실측).
# 2026-08-23 job 8402186d: "하단 전폭"으로 지시했더니 화면 아래 절반을 덮는 거대한
# 책상 슬래브가 생겨 원룸 씬이 사무실처럼 보였고 노트북까지 딸려 나왔다. 제품이 놓일
# 자리만 필요하므로 오른쪽 아래 구석으로 좁힌다. 대신 "그 구석을 채운다"고 못박아
# v3에서처럼 표면이 x 0.72에서 끝나 제품이 허공에 뜨는 것도 막는다.
# 히어로컷(PRODUCT_SURFACE_FRAMING)이 얹혀 보이는 비결을 인물 씬에도 준다: 나무 상판의
# **윗면**이 카메라를 향해 보이고 화면 아래쪽으로 깔려야, 그 위에 놓인 램프 앞으로 나무가
# 보여 "얹힘"으로 읽힌다. "협탁 구석" 서술만으로는 상판 윗면이 안 보였다(job 239b1d15).
PRODUCT_OVERLAY_SURFACE = (
    "a polished wooden tabletop fills the lower-right foreground, its flat top surface "
    "clearly visible and angled slightly toward the camera so we look down onto it, the "
    "near edge of the tabletop crossing the lower part of the frame, its surface bare and "
    "empty with nothing on it, ready for an object to stand on it")
# 인물은 제품 반대쪽(왼쪽 중경)에 둔다 — 사람이 제품 앞을 가로지르면 정적 오버레이가
# 사람 위에 뜬다. 동선을 미리 갈라놓는 게 유일한 대책이다(오클루전 계산은 안 한다).
# 의상 지시가 없으면 "기지개를 켠다" 같은 동작에서 상반신 탈의가 나온다(job 8402186d
# 씬2 실측). full-bleed 지시는 액자 테두리 아티팩트 방어다 — 같은 job 씬4에서 둥근
# 모서리 흰 테두리가 화면 안에 생겼다. 둘 다 positive로만 쓴다(cfg=1.0에서 부정문은
# 소환문이 된다).
PRODUCT_OVERLAY_PERSON_FRAMING = (
    "a cinematic commercial shot with the people in the mid-ground on the left half of "
    "the frame, relaxed and naturally in motion, everyone fully dressed in ordinary "
    "everyday indoor clothing that covers the torso and shoulders, the image bleeding "
    "all the way to every edge of the frame with no border and no inset panel")
# 조명 — B방식. 광원의 **이유를 창밖에 준다**. 프로브 3라운드 실측:
#   v1 "warm light spills from the lower-right foreground" → LTX가 그 광원을 실제로
#      그렸다(씬마다 조명기구 2개 생성).
#   v2 "with no lamps and no light fixtures anywhere" → 여전히 그렸다. cfg=1.0이라
#      부정어가 죽고 "lamp"라는 명사만 조건에 남는다. 부정문이 소환문이 된다.
#   v3 광원을 아예 언급 안 함 → 2개에서 1개로 줄었지만 남았다. 이유를 안 주면 발명한다.
# 창은 조명기구가 아니므로 램프를 부르지 않으면서 따뜻한 톤의 근거가 된다.
# 화풍 — B노선은 job별 style_bible을 **안 쓴다**. bible은 LLM이 제품 이미지에서 뽑는
# "디자인 사양서" 문체라 영상 화풍으로는 정반대로 작용한다. 2026-08-23 job 032e1827
# 실측 bible: "Rendering Technique: Photorealism, Flat Lighting, Studio Shot. Line/Edge
# Treatment: Sharp, Precise, Clean. Shape Language: Geometric, Minimalist. Texture
# Density: Low, Uniform. Environmental Detail Level: None, Seamless Background." —
# 맨 앞 Photorealism 하나를 나머지가 전부 눌러 결과가 3D 만화로 나왔다.
# 부정문은 쓰지 않는다(cfg=1.0에서 부정문은 소환문이 된다 — 프롬프트 v2 실패 참고).
# 원하는 것만 적극적으로 서술한다.
PRODUCT_OVERLAY_STYLE = os.environ.get(
    "AGENT_PRODUCT_OVERLAY_STYLE",
    "photorealistic live-action footage filmed on a full-frame cinema camera with a 35mm "
    "lens, real human skin with visible pores and fine facial detail, real fabric weave "
    "and worn surface texture, natural light falloff and soft contact shadows, fine film "
    "grain, shallow depth of field, documentary realism")
PRODUCT_OVERLAY_LIGHT = os.environ.get(
    "AGENT_PRODUCT_OVERLAY_LIGHT",
    "soft moonlight and distant city glow fall into the room through a large window, "
    "washing the walls and furniture in a gentle warm amber evening tone with deep soft "
    "shadows in the corners, faces still clearly visible")

# 히어로컷(사람 없는 제품 단독 컷)은 제품을 크게 놓는다.
PRODUCT_OVERLAY_HERO_HEIGHT_RATIO = float(
    os.environ.get("AGENT_PRODUCT_OVERLAY_HERO_HEIGHT", "0.62"))
PRODUCT_OVERLAY_HERO_RATIOS = (
    float(os.environ.get("AGENT_PRODUCT_OVERLAY_HERO_WIDTH", "0.34")),
    float(os.environ.get("AGENT_PRODUCT_OVERLAY_HERO_CENTER_X", "0.52")),
    float(os.environ.get("AGENT_PRODUCT_OVERLAY_HERO_BOTTOM_Y", "0.92")),
)

# 조명 큐는 node_prompt_scenes가 프롬프트 **끝에** 한 문장으로 붙인다. B노선은 그 문장을
# 통째로 갈아끼운다 — 서버 전역 AGENT_SCENE_LIGHTING에 "soft amber lamp glow"가 들어
# 있으면(무드등 시나리오 기본값이 그렇다) 그 단어가 T2V에 램프를 소환한다.
_SCENE_LIGHTING_TAIL_RE = re.compile(r"\s*Scene lighting and atmosphere:.*$", re.I | re.S)
# 이 경로의 T2V는 제품을 **알 필요가 아예 없다** — 제품은 영상이 끝난 뒤 픽셀로 얹힌다.
# 그래서 _strip_product_phrases(한정사 필요)보다 세게, 맨몸 명사까지 지운다. 다른
# 경로에 쓰면 문장이 망가지지만 여기서는 지우는 게 정확하다.
# 재작성 LLM이 해부학적 노출 표현을 쓰면 그게 의상 지시를 이긴다. 2026-08-23 job
# 1fd34d0a 씬2: 프레이밍에 "everyone fully dressed ... covers the torso"를 넣었는데도
# 재작성문이 "a relaxed gesture **opening his chest**", "lingering slightly on his
# **open chest**"라고 두 번 써서 상반신 탈의 남자가 나왔다. 더 구체적이고 반복된 쪽이
# 이긴다. cfg=1.0이라 negative로 못 막으므로 프롬프트에서 뺀다.
_BODY_EXPOSURE_RE = re.compile(
    r"\b(?:(?:his|her|their|the)\s+)?(?:open|bare|exposed|naked|toned|muscular)\s+"
    r"(?:chest|torso|upper body|abs|shoulders)\b"
    r"|\bshirtless\b|\bopening (?:his|her|their) chest\b|\btopless\b", re.I)
_BARE_PRODUCT_NOUN_RE = re.compile(
    r"\b(?:lamp|lamps|lantern|lanterns|lighting fixture|lighting fixtures|light fixture|"
    r"light fixtures|bottle|bottles|can|cans|cup|cups|beverage|beverages)\b", re.I)


def _overlay_t2v_prompt(prompt: str, *, hero: bool, scene_context: str = "") -> str:
    """B노선 T2V 프롬프트 — 사람 장면만 서술하고 제품은 한 글자도 넣지 않는다.

    scene_context(씬의 장소)를 앞쪽에 직접 박는다. LLM 재작성문 하나에만 장소를
    맡기면 환각이 그대로 영상이 된다(job 8402186d 씬2: 서재 시나리오가 체육관으로).
    """
    body = _SCENE_LIGHTING_TAIL_RE.sub("", prompt or "")
    body = _BARE_PRODUCT_NOUN_RE.sub("", _strip_product_phrases(body))
    body = _BODY_EXPOSURE_RE.sub("", body)
    body = re.sub(r"\s{2,}", " ", body)
    body = re.sub(r"(,\s*){2,}", ", ", body).strip(" ,.")
    body = _lock_camera(body)
    framing = PRODUCT_HERO_FRAMING if hero else PRODUCT_OVERLAY_PERSON_FRAMING
    # 우리 지시를 **앞**에 둔다. 씬 프롬프트 꼬리에는 style_bible이 통째로 붙어 있는데
    # ("Rendering Technique: ... Flat Lighting, Studio Shot", "Environmental Detail
    # Level: None, Seamless Background") 그게 우리가 요구한 "창밖 달빛 드는 방"과
    # 정면으로 싸운다. 게다가 T5 토큰 한도에 걸리면 잘리는 건 뒤쪽이라, 뒤에 두면
    # 빈 표면·광원·카메라 고정이 가장 먼저 희생된다(2026-08-23 job 032e1827 실측:
    # 프롬프트가 style_bible 덤프 포함 1900자를 넘었고 결과가 3D 만화로 나왔다).
    parts = [PRODUCT_OVERLAY_STYLE, framing]
    if scene_context and scene_context.strip():
        parts.append(f"the location is {scene_context.strip()}")
    if not hero:                       # 히어로컷 프레이밍은 빈 표면 서술을 이미 갖고 있다
        parts.append(PRODUCT_OVERLAY_SURFACE)
    parts += [PRODUCT_OVERLAY_LIGHT, STATIC_CAMERA_CLAUSE, body]
    return ". ".join(p.strip(" ,.") for p in parts if p and p.strip()) + "."


async def generate_product_overlay_clip(
    job_id: str, scene_id: int, *, prompt: str, product_ref: str | None,
    hero: bool = False, duration: float = 3.0, seed: int | None = None,
    force_new: bool = False, scene_context: str = "",
) -> str:
    """B노선 — T2V로 사람 장면을 만들고 제품 컷아웃을 전 프레임에 정적 오버레이한다.

    산출물: clip<N>_t2v.mp4(제품 없는 원본), layer<N>.png(구운 제품 레이어),
    clip<N>.mp4(최종). 원본과 레이어를 남기는 이유는 비율만 바꿔 다시 얹을 때
    T2V를 재생성하지 않기 위해서다.
    """
    job = job_dir(job_id)
    t2v_prompt = _overlay_t2v_prompt(prompt, hero=hero, scene_context=scene_context)
    print(f"[overlay] 씬{scene_id} T2V 프롬프트: {t2v_prompt}")
    generated = await generate_t2v_clip(
        job_id, scene_id, t2v_prompt, duration=duration, seed=seed, force_new=force_new)
    base = job / f"clip{scene_id}_t2v.mp4"
    shutil.copyfile(generated, base)          # generate_t2v_clip은 clip<N>.mp4에 쓴다
    if not product_ref:
        # 제품이 화면에 없는 인물 씬 — 얹을 게 없으니 T2V 결과가 곧 최종이다.
        return str(generated)
    nonce = f"{int(time.time() * 1000)}"
    product = await _ensure_product_cutout(refs_dir(job_id) / product_ref, nonce)
    ratios = PRODUCT_OVERLAY_HERO_RATIOS if hero else (
        PRODUCT_OVERLAY_WIDTH_RATIO, PRODUCT_OVERLAY_CENTER_X, PRODUCT_OVERLAY_BOTTOM_Y)
    h_ratio = PRODUCT_OVERLAY_HERO_HEIGHT_RATIO if hero else PRODUCT_OVERLAY_HEIGHT_RATIO
    out = job / f"clip{scene_id}.mp4"
    overlay_product_on_clip(
        base, product, out, width_ratio=ratios[0], height_ratio=h_ratio,
        center_x_ratio=ratios[1], bottom_y_ratio=ratios[2],
        layer_path=job / f"layer{scene_id}.png")
    print(f"[overlay] 씬{scene_id} 제품 오버레이: {out} "
          f"(높이 {h_ratio}, 폭상한 {ratios[0]}, x {ratios[1]}, y {ratios[2]})")
    return str(out)



async def generate_product_scene_clip(
    job_id: str, scene_id: int, *, prompt: str, product_ref: str | None,
    face_ref: str | None = None, hero: bool | None = None, hand_held: bool = False,
    duration: float = 3.0, seed: int | None = None, negative_prompt: str | None = None,
    scene_context: str = "", person_appearance: str = "", force_new: bool = False,
) -> str:
    """제품이 등장하는 씬을 A노선(첫 프레임 조립)으로 생성한다.

    1) 배경 — 손에 쥔 씬이면 인물 참조를 Kontext로 재렌더해 **빈 그립 손**까지 그린다.
       놓인 씬이면 씬 프롬프트로 T2I 배경을 뽑는다.
    2) 제품 픽셀을 Pillow로 합성(diffusion 없음).
    3) Kontext로 약한 블러(10/4)와 함께 재통합 — 제품만 씬 조명에 녹인다. 블러를
       빼면 심도 단서가 사라져 제품이 스티커처럼 뜨고, 기본값 31을 쓰면 배경이 다
       뭉개진다.
    4) LTX I2V로 움직임만 입힌다(negative로 제품 드리프트 억제).

    `hero=True`면 사람이 안 나오는 제품 단독 컷이다. 배경을 T2I로 새로 그리고 제품을
    크게 놓는다. `face_ref`도 `hero`도 없는 씬 = **인물 정본이 없는 인물 씬**(제품만
    첨부하는 "시나리오만" 모드)이라 배경을 T2I로 그린다 — 씬마다 다른 사람이 나오는 게
    그 모드의 의도다. `hero=None`은 옛 추론(`face_ref is None`)으로 폴백한다(프로브 호환).

    `product_ref=None`이면 **제품이 화면에 없는 인물 씬**(씬4형)이다. 2·3단계를 건너뛰고
    배경 T2I → I2V만 탄다. 이 씬들은 원래 LTX 2.3 22B Face-ID로 갔는데, Face-ID 씬이 2개가
    되는 순간 GGUF 축출로 10~40분 정체가 난다(docs/spikes/2026-08-13-scene5-e2e-handoff.md).
    얼굴 identity는 씬2·3과 같은 수준(캡션·의상 lock 텍스트)으로만 유지된다 —
    사용자 결정(2026-08-14).

    중간 산출물은 jobs/<job_id>/assembly/에 남긴다 — 노드별 결과를 눈으로 검증해야
    하기 때문이다.
    """
    resolved_seed = seed if seed is not None else int(time.time())
    if hero is None:
        hero = face_ref is None
    work = job_dir(job_id) / "assembly"
    work.mkdir(parents=True, exist_ok=True)
    product_path = refs_dir(job_id) / product_ref if product_ref else None
    # ComfyUI는 동일 그래프+동일 입력 파일명을 캐시 히트로 처리하는데, 그때 history의
    # outputs가 비어 돌아와 "출력 이미지 없음"으로 죽는다(재생성 시 재현). 업로드
    # 파일명에 nonce를 넣어 매 호출을 새 그래프로 만든다.
    nonce = f"{int(time.time() * 1000)}"

    # 1) 배경
    grip = None
    if face_ref:
        # 인물이 나오는 씬은 **전부** 인물 정본을 Kontext로 재렌더해 배경을 만든다.
        # T2I로 새로 그리면 얼굴 identity를 잡아둔 게 아무것도 없어 매번 다른 사람이
        # 나온다(2026-08-14 job 1559ee49 씬2: 정본은 수염 없는 20대 초반인데 배경 인물은
        # 수염 + 나이 위). 캡션 텍스트는 사람을 특정하지 못한다. 사용자 결정 2026-08-14.
        padded = _pad_to_wide(Image.open(refs_dir(job_id) / face_ref), WIDTH / HEIGHT)
        buf = BytesIO()
        padded.save(buf, "PNG")
        setting = ", ".join(v for v in (scene_context, person_appearance) if v and v.strip())
        if hand_held:
            # 쥔 씬의 배경에는 **장소·의상·조명만** 주입한다. 씬 프롬프트(동작 서술)를
            # 통째로 넣으면 Kontext가 그 동작을 그려버린다 — 2026-08-13 라이브 검증에서
            # "he lifts the bottle and drinks"를 주입했더니 이미 유리병을 들고 마시는
            # 자세가 나왔고, 손이 입가로 가버려 그립 검출이 귀 옆을 짚었다. 첫 프레임은
            # 동작 **직전** 상태여야 한다.
            body = f"{PRODUCT_HELD_BG_PROMPT} {PRODUCT_HELD_EMPTY_HAND}"
            what = f"씬{scene_id} 제품 조립 배경(그립 손)"
        elif product_path is not None:
            # 놓인 제품 씬: 씬 문장을 넣지 않는다. 명사구를 지워도 문장의 의미가 제품을
            # 요구하면 diffusion은 자기 나름의 병을 그린다(같은 job 씬2: 정규식 확장
            # 뒤에도 배경에 무라벨 생수병). 자리는 비워두고 제품은 다음 단계에서 얹는다.
            body = PRODUCT_PLACED_BG_PROMPT
            what = f"씬{scene_id} 제품 조립 배경(놓임)"
        else:
            # 제품 없는 인물 씬: 여기서는 씬 동작이 곧 그림이라 주입한다. 대신 완료
            # 자세로 굳지 않게 "동작 도중"을 못박는다.
            body = (f"{PERSON_SCENE_ACTION_BG_PROMPT} The action in this shot: "
                    f"{_strip_product_phrases(prompt)}. {PERSON_SCENE_FIRST_FRAME}.")
            what = f"씬{scene_id} 인물 씬 배경"
        bg_prompt = body + (f" Setting, wardrobe and lighting: {setting}." if setting else "")
        bg_bytes = await run_flux_kontext(
            buf.getvalue(), prompt=bg_prompt, seed=resolved_seed,
            upload_name=f"assembly_bg_{job_id}_{scene_id}_{nonce}.png", what=what,
            guidance=PRODUCT_BG_GUIDANCE, controlnet_strength=PRODUCT_BG_CONTROLNET)
        bg_path = work / f"scene{scene_id}_bg.png"
        bg_path.write_bytes(bg_bytes)
    else:
        # 인물 정본이 없는 씬 → T2I로 배경을 새로 그린다("시나리오만" 모드 또는 히어로컷).
        if hero:
            # 히어로컷: 사람을 지우고 씬 문장을 그대로 쓴다(제품 명사만 제거). 프롬프트가
            # 제품을 주인공으로 서술하면 T2I가 자기 나름의 병을 그려 결과에 병이 둘이
            # 된다(2026-08-13 5컷 라이브: 콜라색 대형 병 뒤에 우리 제품이 작게 합성됨).
            bg_prompt = f"{_strip_product_phrases(prompt)}, {PRODUCT_HERO_FRAMING}"
        else:
            # 인물 씬: 씬 문장(동작 서술)을 **넣지 않는다**. Kontext 경로가 같은 이유로
            # 장소·의상·조명만 주입하는 것과 같다 — 동작을 넣으면 T2I가 그 동작을 그려
            # 첫 프레임이 동작 '직후'가 되고, 마시는 씬에서는 비어 있어야 할 그립 손에
            # 제 나름의 음료를 그려 넣는다(2026-08-14 job 8820932b 씬1 실측: 빈 손 대신
            # 우유잔, 그 위에 우리 병이 겹쳐 합성됨). 제품 명사구를 지워도 문장의 의미가
            # 음료를 요구하면 diffusion은 음료를 그린다.
            framing = (PRODUCT_HELD_T2I_FRAMING if hand_held else
                       f"a cinematic commercial shot with one person in the mid-ground, "
                       f"{PRODUCT_SURFACE_FRAMING}")
            who = ", ".join(v for v in (person_appearance, scene_context) if v and v.strip())
            bg_prompt = framing + (f". Person, setting and lighting: {who}." if who else "")
        bg_path = Path(await generate_t2i_image(job_id, bg_prompt, seed=resolved_seed,
                                                index=1000 + scene_id))
        shutil.copyfile(bg_path, work / f"scene{scene_id}_bg.png")
        bg_path = work / f"scene{scene_id}_bg.png"
        bg_bytes = bg_path.read_bytes()

    # 그립 좌표는 배경마다 다르다 — 하드코딩하면 새로 뽑은 배경에서 병이 가슴 한복판에
    # 붙는다(라이브 검증에서 실제로 발생). 인물 마스크로 손을 찾아 산출하고, 못 찾으면
    # 스파이크 기본값으로 폴백한다.
    if hand_held and not hero:
        try:
            grip = locate_grip(bg_bytes, await person_mask(
                bg_bytes, upload_name=f"assembly_mask_{job_id}_{scene_id}_{nonce}.png"))
        except Exception as exc:                      # 검출 실패가 생성 전체를 막지 않게
            print(f"[assembly] 씬{scene_id} 그립 검출 실패({exc}) — 기본값 사용")

    if product_path is None:
        # 2)·3) 없음 — 얹을 제품이 없으니 배경이 곧 첫 프레임이다.
        recomposed = bg_path
    else:
        recomposed = await _compose_and_recompose_product(
            job_id, scene_id, work, bg_path, product_path, grip,
            hand_held=hand_held, hero=hero, seed=resolved_seed, nonce=nonce)

    # 4) I2V — 조립된 첫 프레임에 움직임만
    ref_name = f"assembled_scene{scene_id}.png"
    shutil.copyfile(recomposed, refs_dir(job_id) / ref_name)
    # 놓인 제품 씬은 카메라를 고정한다 — 합성 제품이 배경 픽셀에 박혀 있어 카메라가
    # 움직이면 놓인 면과 함께 통째로 흔들린다(2026-08-14 clip2 실측).
    placed = not hand_held and not hero and product_path is not None
    if placed:
        prompt = _lock_camera(prompt)
        negative_prompt = (f"{negative_prompt or LTX13B_DEFAULT_NEGATIVE}, "
                           f"{PRODUCT_PLACED_NEGATIVE_EXTRA}")
    return await generate_i2v_fallback_clip(
        job_id=job_id, scene_id=scene_id, prompt=prompt, matched_image=ref_name,
        duration=duration, seed=resolved_seed, force_new=force_new,
        negative_prompt=negative_prompt)


async def _ensure_product_cutout(product_path: Path, nonce: str) -> Path:
    """제품 참조에 투명 배경이 없으면 배경을 지우고 알파 bbox로 잘라 캐시한다.

    이게 없으면 `compose_product_frame`의 alpha_composite가 **배경 사각형째** 붙인다
    (불투명 이미지는 알파가 전부 255다). 컷아웃이 필요한 입력은 두 가지다:
      - 프론트 describe 모드가 M2로 생성한 제품 이미지 — FLUX는 RGB만 출력한다
        (실측: 1280x720 RGB, 알파 extrema (255,255)).
      - 사용자가 올린 일반 제품 사진.
    제품 이미지 프롬프트(_IMG_QUERY_PRODUCT_SYSTEM)는 원래부터 "cut out 해서 합성한다"를
    전제로 흰 배경 스튜디오컷을 요구하고 있었는데, 그 컷아웃 단계만 없었다.

    `person_mask`(이름과 달리 ComfyUI 내장 birefnet RemoveBackground 그래프다)를 그대로
    쓴다 — 신규 모델·의존성 없음. 결과는 job의 refs 옆에 캐시해 씬마다 다시 안 돌린다.
    실패하면 원본을 그대로 돌려준다 — 배경이 붙는 게 제품이 통째로 사라지는 것보다 낫다.
    """
    cached = product_path.with_name(product_path.stem + ".cutout.png")
    if cached.exists():
        return cached
    img = Image.open(product_path)
    if img.mode in ("RGBA", "LA") and img.convert("RGBA").getchannel("A").getextrema()[0] < 255:
        return product_path                       # 이미 투명 배경 컷아웃
    try:
        mask = await person_mask(product_path.read_bytes(),
                                 upload_name=f"product_cutout_{nonce}.png")
        rgba = img.convert("RGBA")
        if mask.shape != (rgba.height, rgba.width):
            raise ValueError(f"마스크 크기 불일치 {mask.shape} vs {(rgba.height, rgba.width)}")
        rgba.putalpha(Image.fromarray((mask * 255).astype("uint8"), mode="L"))
        box = rgba.split()[-1].getbbox()
        if box is None:
            raise ValueError("배경 제거가 피사체를 통째로 지웠다")
        rgba.crop(box).save(cached)
    except Exception as exc:                      # 컷아웃 실패가 생성 전체를 막지 않게
        print(f"[assembly] 제품 컷아웃 실패({exc}) — 원본 사용")
        return product_path
    print(f"[assembly] 제품 컷아웃: {product_path.name} → {cached.name} {Image.open(cached).size}")
    return cached


async def _compose_and_recompose_product(
    job_id: str, scene_id: int, work: Path, bg_path: Path, product_path: Path,
    grip: dict | None, *, hand_held: bool, hero: bool, seed: int, nonce: str,
) -> Path:
    """조립 2)·3)단계 — 제품 픽셀을 첫 프레임에 얹고 Kontext로 씬 조명에 녹인다."""
    product_path = await _ensure_product_cutout(product_path, nonce)
    # 2) 제품 픽셀 합성
    if hand_held:
        width_ratio, center_x, bottom_y = PRODUCT_HELD_RATIOS
    elif hero:                                  # 히어로컷 — 제품이 화면의 주인공
        width_ratio, center_x, bottom_y = PRODUCT_HERO_RATIOS
    else:
        width_ratio, center_x, bottom_y = PRODUCT_PLACED_RATIOS
    occlusion_box = PRODUCT_HELD_OCCLUSION_BOX if hand_held else None
    if grip:
        bg_w, bg_h = Image.open(bg_path).size
        # 제품 폭은 프레임이 아니라 **얼굴**을 기준으로 잡는다 — 배경이 매번 새로
        # 생성돼 인물 크기가 달라지므로 고정비는 맞을 이유가 없다(2026-08-14 씬3:
        # 병이 작게 시작해 재생 중에 커짐).
        width_ratio = PRODUCT_FACE_RATIO * grip["face_w_ratio"]
        product_h_ratio = width_ratio * (bg_w / bg_h) * (
            Image.open(product_path).height / Image.open(product_path).width)
        # 손 중심에 제품 세로 중심을 맞춘다 → 바닥 기준 비율로 변환.
        center_x = grip["center_x_ratio"]
        bottom_y = min(0.99, grip["center_y_ratio"] + product_h_ratio / 2)
        occlusion_box = grip["occlusion_box"]
        print(f"[assembly] 씬{scene_id} 그립({grip['source']}): hand={grip['hand_box']} "
              f"face_w={grip['face_w_ratio']:.3f} width={width_ratio:.3f} "
              f"center_x={center_x:.3f} bottom_y={bottom_y:.3f} occl={occlusion_box}")
    flat = compose_product_frame(
        bg_path, product_path, work / f"scene{scene_id}_flat.png",
        width_ratio=width_ratio, center_x_ratio=center_x, bottom_y_ratio=bottom_y,
        warm_tint=True, occlusion_box=occlusion_box)

    # 3) Kontext 재통합
    recomposed_bytes = await run_flux_kontext(
        Path(flat).read_bytes(),
        prompt=(PRODUCT_RECOMPOSE_PROMPT_HELD if hand_held
                else PRODUCT_RECOMPOSE_PROMPT_PLACED),
        seed=seed,
        upload_name=f"assembly_recompose_{job_id}_{scene_id}_{nonce}.png",
        what=f"씬{scene_id} 제품 재통합",
        controlnet_strength=PRODUCT_RECOMPOSE_CONTROLNET,
        blur_radius=FLUX_PRODUCT_BLUR_RADIUS, blur_sigma=FLUX_PRODUCT_BLUR_SIGMA)
    recomposed = work / f"scene{scene_id}_recomposed.png"
    recomposed.write_bytes(recomposed_bytes)
    return recomposed


## ── TTS 온디맨드 기동 ─────────────────────────────────────────
# Kokoro/Chatterbox는 systemd user 유닛으로만 존재하고 기본 비활성 상태다(상시 상주하면
# LocalAI의 다른 카테고리와 GPU 메모리를 다툼). 요청이 올 때만 `systemctl --user start`로
# 띄우고, 일정 시간 아무도 안 쓰면 자동으로 내린다. ponytail: 유휴 감시는 단일 asyncio
# 태스크 + dict 하나로 — 프로세스 매니저나 systemd timer 신규 도입 안 함.
TTS_IDLE_TIMEOUT = float(os.environ.get("AGENT_TTS_IDLE_TIMEOUT", "180"))
_tts_last_used: dict[str, float] = {}
_tts_watchdog_task: asyncio.Task | None = None


async def _tts_idle_watchdog() -> None:
    while True:
        await asyncio.sleep(30.0)
        now = time.time()
        for unit, last in list(_tts_last_used.items()):
            if now - last > TTS_IDLE_TIMEOUT:
                subprocess.run(["systemctl", "--user", "stop", unit], check=False)
                _tts_last_used.pop(unit, None)


async def _ensure_tts_service(unit: str, base_url: str) -> None:
    """unit이 안 떠있으면 systemctl --user start로 기동하고 /health가 응답할 때까지 기다린다."""
    global _tts_watchdog_task
    _tts_last_used[unit] = time.time()
    if _tts_watchdog_task is None:
        _tts_watchdog_task = asyncio.create_task(_tts_idle_watchdog())
    async with httpx.AsyncClient(timeout=3.0) as client:
        try:
            if (await client.get(f"{base_url}/health")).status_code < 500:
                return
        except httpx.HTTPError:
            pass
    subprocess.run(["systemctl", "--user", "start", unit], check=True)
    deadline = time.time() + 110.0  # TimeoutStartSec=120 여유
    async with httpx.AsyncClient(timeout=3.0) as client:
        while time.time() < deadline:
            try:
                if (await client.get(f"{base_url}/health")).status_code < 500:
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(2.0)
    raise TimeoutError(f"{unit}가 기동 후 {deadline:.0f}s 내 healthy 상태가 되지 않음")


async def generate_kokoro_narration(text: str, speed: float = 1.0) -> bytes:
    """Generate Korean narration through the dedicated Kokoro backend.

    The backend may return WAV bytes directly or an ``audio_url`` JSON object.
    Supporting both keeps this gateway independent from a particular Kokoro
    server wrapper without weakening the model boundary.
    """
    # 첫 요청에는 Kokoro 프로세스 자체를 기동하는 시간이 포함될 수 있다(온디맨드).
    await _ensure_tts_service("kokoro.service", KOKORO_URL)
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
    await _ensure_tts_service("chatterbox.service", CHATTERBOX_URL)
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
    # 워크플로 내장 Gemma 캡션 재작성(node 79)의 토큰 상한. 원본 1024는 과하다 —
    # 결과는 한 문장짜리 ref_t2v 캡션인데 4.0 tok/s로 생성되므로 상한만큼 돌면 씬당
    # 4분 넘게 먹고, 그 사이 LTX 22B가 언로드됐다 다시 로드되는 스왑까지 유발한다
    # (2026-08-13 job 865ee53a 로그 실측: "Generating tokens 294/1024 [01:13]",
    # "Unloaded partially: 14785 MB freed"). 캡션 한 문장엔 192면 충분하다.
    graph["79"]["inputs"]["max_length"] = LTX_FACEID_CAPTION_MAX_TOKENS
    graph["101"]["inputs"]["filename_prefix"] = prefix
    graph["129"]["inputs"]["reference_guidance_scale"] = LTX_FACEID_GUIDANCE
    graph["129"]["inputs"]["ref_resize_mode"] = LTX_FACEID_REF_RESIZE_MODE
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
    """Face-ID 씬들을 생성한다. 씬마다 **별도 prompt로 제출**한다.

    원래는 로더를 공유하는 단일 prompt로 묶어 "LTX/Gemma/LoRA를 정확히 한 번 로드"하려
    했는데, 실측 결과 그 이득이 없다(2026-08-13 job 865ee53a 로그): 씬마다 워크플로
    내장 Gemma가 캡션을 다시 쓰고 그 사이 LTX 22B(17GB)가 언로드됐다 재로드된다
    ("Unloaded partially: 14785 MB freed"). 로더를 공유해도 실제 가중치는 왕복하므로
    묶을수록 스왑만 늘었다 — 1씬 6분(스파이크 clip11→clip14 실측)이 2씬 배치에서
    40분+로 늘어난 주원인.

    씬별 제출은 총 시간이 비슷하거나 짧고, 부분 실패가 그 씬에만 갇히며, 진행 상황이
    씬 단위로 드러난다(부분 완성 클립 노출, SC1).
    """
    if not scenes:
        return {}
    if len(scenes) > 1:
        results: dict[int, str] = {}
        for scene in scenes:
            results.update(await generate_ltx_faceid_batch(job_id, [scene]))
        return results
    timeout = httpx.Timeout(connect=10.0, read=60.0, write=60.0, pool=None)
    async with oom.phase("i2v"), httpx.AsyncClient(timeout=timeout) as client:
        # 22B는 상주 FLUX와 공존 못 한다(_release_t2i 도크스트링의 실측). 업로드보다
        # 먼저 비워야 ComfyUI가 첫 로드부터 lowvram으로 안 떨어진다.
        await _release_t2i()
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
        # ponytail: Wan(i2v_14b/standin_t2v) 경로의 FLUX 동시 peak은 미실측이다. 22B가
        # 무너진 걸 봤으니 안전쪽(비우고 시작)에 둔다 — 실측해서 13B처럼 여유가
        # 확인되면 이 줄만 빼면 상주 이득을 이 경로에도 돌려줄 수 있다.
        await _release_t2i()
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
    잡은 호출부(node_edit_concat)가 LTX_FACEID_WIDTH/HEIGHT(1280x704)를 넘겨써야
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
    # job 3ded2f29: 오역 방지 대응표가 출력에 섞여 wardrobe lock에 한글이 박혔다.
    d = clean_llm_prompt("A man wearing a white 반팔 (short-sleeve) t-shirt runs.")
    assert d == "A man wearing a white short-sleeve t-shirt runs.", d
    e = clean_llm_prompt("a white 반팔 t-shirt, golden hour")
    assert e == "a white t-shirt, golden hour", e
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

    # overlay_product_on_clip 자체점검: 비율 좌표가 맞는 자리에 제품을 얹는지
    # (합성 클립 + 단색 PNG, GPU 불필요). 회귀 대상 — 비율 수학이 틀어지면 제품이
    # 화면 밖이나 인물 한복판에 붙는다.
    with tempfile.TemporaryDirectory() as td:
        vw, vh = 320, 240
        clip = f"{td}/blue.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c=blue:s={vw}x{vh}:r=24:d=1",
             "-pix_fmt", "yuv420p", clip], check=True, capture_output=True)
        prod = Image.new("RGBA", (100, 200), (255, 0, 0, 255))
        prod.putalpha(Image.new("L", (100, 200), 255))
        prod.putpixel((0, 0), (255, 0, 0, 0))     # 투명 픽셀 1개 = 컷아웃으로 인정
        prod_path = f"{td}/prod.png"
        prod.save(prod_path)
        out = overlay_product_on_clip(
            clip, prod_path, f"{td}/out.mp4",
            width_ratio=0.2, height_ratio=None, center_x_ratio=0.8, bottom_y_ratio=0.9,
            warm_tint=False, shadow_alpha=0)
        assert _probe_dims(out) == (vw, vh), _probe_dims(out)
        frame = f"{td}/f.png"
        subprocess.run(["ffmpeg", "-y", "-i", out, "-vframes", "1", frame],
                       check=True, capture_output=True)
        got = Image.open(frame).convert("RGB")
        # pw=64, ph=128 → x 224..288, y 88..216. 그 한복판은 빨강이어야 한다.
        r, g, b = got.getpixel((256, 150))
        assert r > 180 and g < 80 and b < 80, f"제품 자리가 빨강이 아님: {(r, g, b)}"
        r, g, b = got.getpixel((10, 10))
        assert b > 180 and r < 80, f"제품 밖이 배경(파랑)이 아님: {(r, g, b)}"
        # 높이 기준 산정: 종횡비가 달라도 화면 높이 점유가 같아야 한다. 폭 고정비를
        # 쓰면 세로로 긴 제품이 화면을 세로로 지배한다(job 8402186d: 화면높이 72%).
        for pw0, ph0 in ((100, 200), (60, 400)):        # 종횡비 0.50 / 0.15
            tall = Image.new("RGBA", (pw0, ph0), (255, 0, 0, 255))
            tall.putpixel((0, 0), (255, 0, 0, 0))
            tp = f"{td}/tall_{pw0}.png"
            tall.save(tp)
            lp = f"{td}/tall_{pw0}_layer.png"
            bake_product_layer(tp, lp, width=vw, height=vh, height_ratio=0.30,
                               width_ratio=1.0, warm_tint=False, shadow_alpha=0)
            box = Image.open(lp).getchannel("A").getbbox()
            got_h = (box[3] - box[1]) / vh
            assert abs(got_h - 0.30) < 0.02, f"종횡비 {pw0}x{ph0}에서 높이 {got_h:.3f} != 0.30"
        # 넓적한 제품은 폭 상한에 걸려 더 작아져야 한다(화면을 가로지르면 안 됨)
        wide = Image.new("RGBA", (800, 100), (255, 0, 0, 255))
        wide.putpixel((0, 0), (255, 0, 0, 0))
        wp, wl = f"{td}/wide.png", f"{td}/wide_layer.png"
        wide.save(wp)
        bake_product_layer(wp, wl, width=vw, height=vh, height_ratio=0.30,
                           width_ratio=0.25, warm_tint=False, shadow_alpha=0)
        box = Image.open(wl).getchannel("A").getbbox()
        assert (box[2] - box[0]) <= int(vw * 0.25) + 1, f"폭 상한이 안 걸림: {box}"

        # 불투명 입력은 컷아웃 없이 사각형째 붙으므로 거부해야 한다
        opaque = f"{td}/opaque.png"
        Image.new("RGB", (50, 50), (0, 255, 0)).save(opaque)
        try:
            bake_product_layer(opaque, f"{td}/l.png", width=vw, height=vh)
            raise AssertionError("불투명 제품 입력을 거부하지 않았다")
        except ValueError:
            pass
    print("overlay_product_on_clip self-check ok")
