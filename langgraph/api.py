"""
OpenWebUI ↔ LangGraph 연동 레이어.
- thread_id = job_id 로 매핑하여 checkpointer가 상태를 들고 있게 함
- interrupt()가 발생하면 그래프 실행이 멈추고 __interrupt__ 값을 반환 → 그걸 OpenWebUI에 그대로 프리뷰로 전달
- 사람이 승인/수정하면 /jobs/{job_id}/resume 으로 Command(resume=...) 호출
- 생성 파일은 /files/<job_id>/... 로 다운로드 (OWU 컨테이너가 호스트 IP로 접근)
"""
import asyncio
import base64
import os
import uuid
from pathlib import Path

import httpx
from fastapi import FastAPI, File, Form, HTTPException, Response, UploadFile
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from langgraph.types import Command

import tools
import metrics
import dashboard
import style_presets
from graph import compile_graph

app = FastAPI(title="anim_video_agent")
app.mount("/files", StaticFiles(directory=str(tools.JOBS_DIR)), name="files")
app.mount("/static", StaticFiles(directory=str(Path(__file__).resolve().parent / "static")), name="static")

graph = None  # startup에서 초기화

# 클립 생성은 수 분 걸린다. ainvoke를 요청 안에서 await하면 HTTP가 그동안 블로킹돼
# OWU가 무한 로딩으로 보인다. → 백그라운드 태스크로 돌리고 /status 폴링으로 진행상황 노출.
RUNNING: dict[str, asyncio.Task] = {}   # job_id → 실행 중 태스크
ERRORS: dict[str, str] = {}             # job_id → 마지막 실패 메시지


def _launch(job_id: str, coro) -> None:
    """graph 실행을 백그라운드로 던지고 즉시 리턴. 상태는 checkpointer(SQLite)에 저장됨."""
    async def runner():
        try:
            await coro
        except Exception as e:  # 생성 실패를 /status가 surface 할 수 있게 보관
            ERRORS[job_id] = f"{type(e).__name__}: {e}"
        finally:
            RUNNING.pop(job_id, None)
    ERRORS.pop(job_id, None)
    RUNNING[job_id] = asyncio.create_task(runner())


@app.on_event("startup")
async def startup():
    global graph
    graph = await compile_graph(str(tools.JOBS_DIR / "checkpoints.db"))
    # 제출/생성 중 프로세스가 종료된 작업은 기존 prompt_id로 이어서 회수한다.
    # 사람 승인 interrupt에 멈춘 작업은 자동으로 resume하지 않는다.
    for job_id in tools.recoverable_comfy_jobs():
        config = {"configurable": {"thread_id": job_id}}
        snapshot = await graph.aget_state(config)
        interrupts = [i for task in snapshot.tasks
                      for i in (getattr(task, "interrupts", ()) or ())]
        if snapshot.next and not interrupts:
            _launch(job_id, graph.ainvoke(None, config=config))


class StartJobRequest(BaseModel):
    script_text: str
    ref_images: list[str] = []   # base64 또는 data-URI 문자열
    image_request: str = ""      # M2: 참조 미첨부 + 이미지 생성 요청 시 자연어 텍스트


class ResumeRequest(BaseModel):
    payload: dict


class ReviseRequest(BaseModel):
    instruction: str
    scenes: list[dict] | None = None


class ApprovalIntentRequest(BaseModel):
    checkpoint: str
    text: str


class T2IRequest(BaseModel):
    prompt: str
    width: int | None = None
    height: int | None = None
    seed: int | None = None


class TTSNarrationRequest(BaseModel):
    text: str
    speed: float = Field(default=1.0, ge=0.5, le=2.0)


def _save_ref_images(job_id: str, images: list[str]) -> list[str]:
    """base64/data-URI 이미지들을 jobs/<job_id>/refs/ 에 저장하고 파일명 리스트 반환."""
    names = []
    for i, raw in enumerate(images):
        ext = "png"
        payload = raw
        if raw.startswith("data:"):
            header, _, payload = raw.partition(",")
            if "/" in header and ";" in header:
                ext = header.split("/")[1].split(";")[0] or "png"
        name = f"img_{i}.{ext}"
        (tools.refs_dir(job_id) / name).write_bytes(base64.b64decode(payload))
        names.append(name)
    return names


@app.post("/jobs")
async def start_job(req: StartJobRequest):
    job_id = str(uuid.uuid4())
    ref_names = _save_ref_images(job_id, req.ref_images)
    config = {"configurable": {"thread_id": job_id}}
    _launch(job_id, graph.ainvoke(
        {
            "job_id": job_id,
            "script_text": req.script_text,
            "ref_images": ref_names,
            "image_request": req.image_request,  # 있으면 entry router가 이미지 분기로
            "scenes": [],
            "clip_results": [],
            "regen_target_ids": [],
        },
        config=config,
    ))
    return {"job_id": job_id, "status": "running"}


@app.post("/jobs/{job_id}/resume")
async def resume_job(job_id: str, req: ResumeRequest):
    config = {"configurable": {"thread_id": job_id}}
    _launch(job_id, graph.ainvoke(Command(resume=req.payload), config=config))
    return {"job_id": job_id, "status": "running"}


@app.post("/jobs/{job_id}/recover")
async def recover_job(job_id: str):
    """Re-launch an orphaned graph run that has pending next nodes but no task.

    This is for cases where the API process died or the in-memory RUNNING task was lost
    after an approval, before node_generate_one_clip posted work to :8188 (ComfyUI).
    """
    if (tools.job_dir(job_id) / ".cancelled").exists():
        return {"job_id": job_id, "status": "cancelled"}
    task = RUNNING.get(job_id)
    if task and not task.done():
        return {"job_id": job_id, "status": "running"}

    config = {"configurable": {"thread_id": job_id}}
    snapshot = await graph.aget_state(config)
    interrupts = [i.value for t in snapshot.tasks for i in (getattr(t, "interrupts", ()) or ())]
    if interrupts:
        return {"job_id": job_id, "status": "waiting_for_approval", "checkpoint": interrupts[0]}
    if not snapshot.next:
        vals = snapshot.values or {}
        return {"job_id": job_id, "status": "done" if vals.get("phase") == "done" else "idle",
                "phase": vals.get("phase"),
                "final_video_url": _to_url(vals.get("final_video_path"))}

    _launch(job_id, graph.ainvoke(None, config=config))
    return {"job_id": job_id, "status": "running", "recovered": True,
            "next": list(snapshot.next)}


@app.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str):
    """Persistently mark a job cancelled and stop its in-process graph task."""
    task = RUNNING.get(job_id)
    if task and not task.done():
        task.cancel()
    (tools.job_dir(job_id) / ".cancelled").write_text("user_cancelled\n")
    ERRORS.pop(job_id, None)
    metrics.video_finished(scenes=0, duration=None, status="cancelled")
    return {"job_id": job_id, "status": "cancelled"}


@app.get("/jobs/{job_id}/status")
async def job_status(job_id: str):
    """폴링용. running(진행중) | waiting_for_approval(승인대기) | done | error 를 반환.
    상태는 checkpointer에서 읽으므로 서버 재시작에도 유효. (aiosqlite 단일 커넥션이
    읽기/쓰기를 직렬화 → 폴링 중 잠깐 stale할 수 있으나 진행표시엔 무해)"""
    if (tools.job_dir(job_id) / ".cancelled").exists():
        return {"job_id": job_id, "status": "cancelled"}
    config = {"configurable": {"thread_id": job_id}}
    snapshot = await graph.aget_state(config)
    task = RUNNING.get(job_id)
    resuming = task is not None and not task.done()
    interrupts = [i.value for t in snapshot.tasks for i in (getattr(t, "interrupts", ()) or ())]
    vals = snapshot.values or {}
    if job_id in ERRORS:
        return {"job_id": job_id, "status": "error", "error": ERRORS[job_id],
                "phase": vals.get("phase"),
                "comfyui": tools.comfy_job_progress(job_id)}
    # resume 직후엔 그래프가 인터럽트를 지나기 전까지 체크포인터에 구 인터럽트가
    # 잠깐 남는다 — 실행 중 태스크가 있으면 그 인터럽트는 stale이므로 running으로 취급.
    if interrupts and not resuming:  # 사람 승인 대기 (interrupt 발생)
        return {"job_id": job_id, "status": "waiting_for_approval", "checkpoint": interrupts[0]}
    if resuming:
        scenes = vals.get("scenes") or []
        results = vals.get("clip_results") or []
        # 완성된 클립은 즉시 URL로 노출 → OWU가 전체 완료를 기다리지 않고 인라인 표시
        clips = [{"scene_id": s.get("id"), "url": _to_url(s.get("clip_path"))}
                 for s in results if s.get("clip_path")]
        return {"job_id": job_id, "status": "running", "phase": vals.get("phase"),
                "clips_done": len(results), "clips_total": len(scenes),
                "clips": clips,
                "comfyui": tools.comfy_job_progress(job_id)}
    if snapshot.next:
        # 다음 노드가 남아 있는데 현재 프로세스에 실행 태스크가 없으면 실제로는 진행 중이 아니다.
        # 예: 1-4 승인 직후 node_generate_prompts/node_generate_one_clip로 넘어가기 전 태스크가
        # 죽거나 서버가 재시작된 경우. running으로 숨기면 OWU가 영원히 polling한다.
        return {"job_id": job_id, "status": "error",
                "error": f"job stalled with pending graph nodes: {list(snapshot.next)}",
                "phase": vals.get("phase"),
                "next": list(snapshot.next),
                "comfyui": tools.comfy_job_progress(job_id)}
    # 돌 게 없고 interrupt도 없음 → 종료
    return {"job_id": job_id, "status": "done" if vals.get("phase") == "done" else "idle",
            "phase": vals.get("phase"),
            "final_video_url": _to_url(vals.get("final_video_path"))}


@app.post("/jobs/{job_id}/revise")
async def revise_job_scenes(job_id: str, req: ReviseRequest):
    """1-4 게이트: 자연어 수정 지시 → 현재 씬 구조를 반영한 전체 scenes를 반환.
    그래프를 resume하지 않는다. OWU가 이 결과를 {"approved": True, "scenes": ...}로 다시 보낸다."""
    config = {"configurable": {"thread_id": job_id}}
    snapshot = await graph.aget_state(config)
    vals = snapshot.values or {}
    scenes = req.scenes or vals.get("scenes") or []
    if not scenes:
        raise HTTPException(status_code=400, detail="수정할 씬이 없습니다")
    captions = vals.get("ref_captions") or {}
    ref_info = [{"file": fn, "shows": captions.get(fn, "")}
                for fn in (vals.get("ref_images") or [])]
    return {"scenes": await tools.revise_scenes(scenes, ref_info, req.instruction)}


@app.post("/t2i")
async def t2i(req: T2IRequest):
    """앵커 이미지 생성 (FLUX/SDXL :8501 프록시). job과 무관한 단발 호출 — base64 PNG 반환."""
    if not req.prompt or not req.prompt.strip():
        raise HTTPException(status_code=400, detail="prompt is required")
    try:
        return await tools.generate_t2i_anchor(req.prompt, req.width, req.height, req.seed)
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"T2I backend unreachable: {e}")


@app.post("/i2v")
async def i2v_oneshot(
    prompt: str = Form(...),
    image: UploadFile = File(...),
    seed: int | None = Form(None),
):
    """단발샷 I2V (LTX-Video-13B-distilled, ComfyUI :8188 프록시). job과 무관 —
    이미지+프롬프트 한 번 받아 base64 영상(webp) 반환."""
    prompt = prompt.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt is required")
    image_bytes = await image.read()
    if not image_bytes:
        raise HTTPException(status_code=422, detail="image is required")
    try:
        return await tools.generate_i2v_oneshot(image_bytes, prompt, seed)
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"I2V backend unreachable: {e}")
    except (ValueError, RuntimeError, TimeoutError) as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.post("/i2i")
async def i2i_style(
    style: str = Form(...),
    image: UploadFile = File(...),
    seed: int | None = Form(None),
):
    """S2 Flux Kontext 스타일 변환 (Task 6.1). style_presets.py(4.5)의 6종 프리픽스를
    style_prefix() 그대로 재사용 — 신규 스타일 정의 없음. job과 무관 — base64 PNG 반환."""
    style = style.strip()
    if style not in style_presets.STYLE_PREFIXES:
        raise HTTPException(status_code=400, detail=f"unsupported style: {style}")
    image_bytes = await image.read()
    if not image_bytes:
        raise HTTPException(status_code=422, detail="image is required")
    try:
        return await tools.generate_i2i_style(image_bytes, style, seed)
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"I2I backend unreachable: {e}")
    except (ValueError, RuntimeError, TimeoutError) as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.post("/tts/narration")
async def tts_narration(req: TTSNarrationRequest):
    """S1 video narration using the fixed CC0 Chatterbox narrator voice."""
    text = req.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required")
    try:
        wav = await tools.generate_chatterbox_narration(text, req.speed)
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Chatterbox narrator backend unavailable or invalid: {exc}",
        ) from exc
    return Response(
        content=wav,
        media_type="audio/wav",
        headers={
            "Content-Disposition": 'attachment; filename="narration.wav"',
            "X-TTS-Engine": "chatterbox-v3",
        },
    )


@app.post("/tts/clone")
async def tts_clone(
    text: str = Form(...),
    reference: UploadFile | None = File(None),
):
    """Independent user-voice TTS. This route never falls back to Kokoro."""
    text = text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required")
    if reference is None or not reference.filename:
        raise HTTPException(status_code=422, detail="reference WAV is required")
    if not reference.filename.lower().endswith(".wav"):
        raise HTTPException(status_code=415, detail="reference must be a WAV file")

    reference_wav = await reference.read()
    if (
        len(reference_wav) < 12
        or reference_wav[:4] != b"RIFF"
        or reference_wav[8:12] != b"WAVE"
    ):
        raise HTTPException(status_code=415, detail="reference is not a valid WAV file")

    try:
        wav = await tools.generate_chatterbox_clone(
            text, reference_wav, reference.filename
        )
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Chatterbox backend unavailable or invalid: {exc}",
        ) from exc
    return Response(
        content=wav,
        media_type="audio/wav",
        headers={
            "Content-Disposition": 'attachment; filename="clone.wav"',
            "X-TTS-Engine": "chatterbox-v3",
        },
    )


@app.post("/approval-intent")
async def approval_intent(req: ApprovalIntentRequest):
    """OWU 승인 턴을 LLM으로 분류한다. 그래프 상태는 변경하지 않는다."""
    supported = ("2-3", "1-4", "3-5")
    if not req.checkpoint.startswith(supported):
        raise HTTPException(status_code=400, detail="지원하지 않는 승인 게이트입니다")
    return await tools.classify_approval_intent(req.checkpoint, req.text)


@app.get("/jobs/{job_id}/state")
async def get_state(job_id: str):
    config = {"configurable": {"thread_id": job_id}}
    snapshot = await graph.aget_state(config)
    return {"values": snapshot.values, "next": snapshot.next}


@app.get("/metrics")
def metrics_endpoint():
    """Prometheus 스크레이프용. 영상(job) 관점 지표를 노출한다."""
    data, ctype = metrics.render()
    return Response(content=data, media_type=ctype)


@app.get("/health")
async def health():
    return {"status": "ok", "graph_loaded": graph is not None}


@app.get("/dashboard/status")
def dashboard_status():
    """자립 대시보드 폴링 엔드포인트 (docs/PRD.md R9). trace/gpu/external_calls 실측."""
    return dashboard.dashboard_status()


def _to_url(path: str | None) -> str | None:
    """로컬 파일 경로 → /files/... 상대 URL."""
    if not path:
        return None
    try:
        rel = os.path.relpath(path, tools.JOBS_DIR)
    except ValueError:
        return None
    return f"/files/{rel}"


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host=os.environ.get("AGENT_API_HOST", "0.0.0.0"),
        port=int(os.environ.get("AGENT_API_PORT", "8700")),
    )
