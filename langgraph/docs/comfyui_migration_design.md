# LangGraph 생성 백엔드: FastAPI(Wan) → ComfyUI 전환 설계

## 0. 배경 / 문제

- 현재 `tools.py`의 `call_hunyuan_video` / `call_quality_check`가 FastAPI :8500(TI2V-5B), :8600(Animate-14B)을 호출.
- 클립 4~5개 생성에 30분 소요 — 콜드로드/재로드 가능성이 높음 (검증 필요, 1번 항목 참조).
- 과거 ComfyUI + 정적 이미지 face-lock 방식은 "배경만 살짝 바뀜 + 표정 굳음" 문제가 있었음
  → 원인 추정: identity 고정용 신호만 있고 motion/expression을 주는 driving video가 없었기 때문.
  → 이번 설계는 draft(자유 구도) → animate replace(identity lock, motion-driven) 2단계로 이 문제를 회피.

---

## 1. [CLI 선행 작업] 로딩 지연 원인 진단 (설계 변경 전 필수)

목적: ComfyUI 전환이 실제로 병목을 해결하는지 확인. 아래 두 가지를 로그로 남길 것.

```
# 현재 FastAPI 백엔드 기준
- 서버 기동 후 첫 번째 clip 생성 소요 시간 (콜드 스타트 포함)
- 같은 서버에 두 번째 clip 생성 소요 시간 (워밍업 후)
```

- 두 값이 비슷하다 → 추론 자체가 느린 것 → ComfyUI 전환으로 해결 안 됨. 배치 크기/해상도/스텝 수 조정이 우선.
- 두 번째가 첫 번째보다 현저히 짧다 → 콜드로드가 문제 → ComfyUI 전환(모델 상주)으로 해결 가능. 아래 설계 진행.

---

## 2. 목표 아키텍처

```
node_generate_one_clip (LangGraph)
        │
        ▼
[Stage 1] ComfyUI workflow: draft_t2v.json
   - Wan2.1/2.2 T2V, 프롬프트만 사용, identity 무시
   - 자유 구도/카메라워크 확보
        │
        ▼ (scene.matched_image 존재?)
        │
   ┌────┴────┐
   │ No       │ Yes
   ▼          ▼
 draft = final   [Stage 2] ComfyUI workflow: animate_replace.json
                    - 입력: draft 비디오(motion) + matched_image(identity)
                    - 내부에서 DWPose 추출 + SAM2 마스킹 + Wan2.2-Animate-14B 실행
                    - 출력: identity 고정 + 동작 보존된 최종 클립
```

핵심 원칙: **ComfyUI 프로세스 1개만 상주.** draft/animate 워크플로우 모두 같은 ComfyUI 서버(:8188)에 큐잉하며, 체크포인트 로더 노드가 동일 파일을 참조하면 ComfyUI가 자체 캐시로 재로드를 회피함. FastAPI 8500/8600 프로세스는 폐기(또는 fallback으로만 유지).

---

## 3. 필요한 ComfyUI 워크플로우 (API 포맷 export)

ComfyUI UI에서 "Save (API Format)"으로 export하여 리포에 저장:

| 파일명 | 내용 |
|---|---|
| `comfyui_workflows/draft_t2v.json` | 프롬프트 → 자유 구도 draft 클립 (기존 T2V 워크플로우 재사용 가능) |
| `comfyui_workflows/animate_replace.json` | driving video + reference image → identity 고정 클립. 참고 그래프 구성: `LoadVideo → GetVideoComponents → Sam2Segmentation(character mask) → DWPreprocessor(pose) → CLIPVisionEncode(reference image) → WanAnimateToVideo → SaveVideo` |

주의: `WanAnimateToVideo` 노드는 width/height가 16의 배수여야 함 (`PixelPerfectResolution` 노드로 보정).

---

## 4. 코드 변경 지점

### 4-1. `tools.py` — ComfyUI 클라이언트 추가

```python
import httpx
import json
import uuid
import asyncio

COMFYUI_ENDPOINT = "http://172.16.4.228:8188"  # 실제 주소로 교체

async def submit_comfyui_workflow(workflow_path: str, param_overrides: dict) -> str:
    """
    workflow_path: comfyui_workflows/*.json
    param_overrides: {"<node_id>.inputs.<field>": value} 형태로 특정 노드 입력값 덮어쓰기
    return: prompt_id
    """
    with open(workflow_path) as f:
        workflow = json.load(f)

    for dotted_key, value in param_overrides.items():
        node_id, _, field = dotted_key.partition(".inputs.")
        workflow[node_id]["inputs"][field] = value

    client_id = str(uuid.uuid4())
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{COMFYUI_ENDPOINT}/prompt",
            json={"prompt": workflow, "client_id": client_id},
        )
        resp.raise_for_status()
        return resp.json()["prompt_id"]


async def poll_comfyui_result(prompt_id: str, timeout_sec: int = 300) -> str:
    """완료까지 폴링 후 출력 파일 경로(ComfyUI output 디렉토리 기준) 반환"""
    async with httpx.AsyncClient(timeout=30) as client:
        for _ in range(timeout_sec // 2):
            resp = await client.get(f"{COMFYUI_ENDPOINT}/history/{prompt_id}")
            history = resp.json()
            if prompt_id in history:
                outputs = history[prompt_id]["outputs"]
                for node_output in outputs.values():
                    if "gifs" in node_output or "videos" in node_output:
                        key = "videos" if "videos" in node_output else "gifs"
                        return node_output[key][0]["filename"]
            await asyncio.sleep(2)
    raise TimeoutError(f"ComfyUI job {prompt_id} timed out")


async def generate_draft_clip(prompt: str) -> str:
    param_overrides = {"<PROMPT_NODE_ID>.inputs.text": prompt}  # 실제 노드 ID로 교체
    prompt_id = await submit_comfyui_workflow(
        "comfyui_workflows/draft_t2v.json", param_overrides
    )
    return await poll_comfyui_result(prompt_id)


async def generate_animate_replace(draft_video_path: str, ref_image_path: str) -> str:
    param_overrides = {
        "<VIDEO_LOADER_NODE_ID>.inputs.video": draft_video_path,
        "<REF_IMAGE_NODE_ID>.inputs.image": ref_image_path,
    }
    prompt_id = await submit_comfyui_workflow(
        "comfyui_workflows/animate_replace.json", param_overrides
    )
    return await poll_comfyui_result(prompt_id)
```

`<PROMPT_NODE_ID>` 등은 실제 export된 JSON을 열어서 해당 노드의 id로 치환 필요 — CLI가 워크플로우 export 후 직접 확인.

### 4-2. `nodes.py` — `node_generate_one_clip` 교체

```python
async def node_generate_one_clip(payload: dict) -> dict:
    scene: Scene = payload["scene"]

    draft_path = await tools.generate_draft_clip(prompt=scene["prompt"])

    if scene.get("matched_image"):
        clip_path = await tools.generate_animate_replace(
            draft_video_path=draft_path,
            ref_image_path=scene["matched_image"],
        )
    else:
        clip_path = draft_path

    quality = await tools.call_quality_check(clip_path, scene.get("matched_image"))
    score = quality["score"]
    flag = "ok" if score >= 0.75 else "low_quality"

    updated_scene: Scene = {
        **scene, "clip_path": clip_path,
        "quality_score": score, "quality_flag": flag,
    }
    return {"clip_results": [updated_scene]}
```

`call_quality_check`는 기존 로직 유지 가능 (별도 경량 서버 or 로컬 CLIP 스코어링으로 대체 가능, ComfyUI와 무관).

### 4-3. `state.py` — 변경 없음 (Scene 스키마 그대로 사용)

### 4-4. 정리 대상

- `tools.py`의 `LLM_ENDPOINT` 이외 `VIDEO_ENDPOINT`, `QUALITY_CHECK_ENDPOINT` (8500/8600) 하드코딩 제거 또는 fallback 플래그로 격리
- FastAPI :8500/:8600 서비스 — systemd 유닛 disable (완전 삭제는 fallback 필요성 확정 후)

---

## 5. 마이그레이션 순서 (CLI 실행 체크리스트)

1. [ ] 1번 항목의 로딩 지연 진단 로그 확보 → 콜드로드 문제 확인
2. [ ] ComfyUI에서 draft_t2v, animate_replace 워크플로우 수동 구성 후 API 포맷 export
3. [ ] `tools.py`에 `submit_comfyui_workflow`/`poll_comfyui_result`/`generate_draft_clip`/`generate_animate_replace` 추가, 노드 ID 실제 값으로 치환
4. [ ] `nodes.py`의 `node_generate_one_clip` 교체
5. [ ] 테스트: 씬 1개(matched_image 없음), 씬 1개(matched_image 있음) 각각 end-to-end 실행
6. [ ] 클립 4~5개 배치 실행 후 총 소요시간 재측정 — 30분 대비 개선 여부 확인
7. [ ] 개선 확인되면 FastAPI 8500/8600 systemd 서비스 disable
8. [ ] `README.md`의 아키텍처 섹션, "실행 전 교체가 필요한 부분" 표 갱신

---

## 6. 미해결 리스크

- ComfyUI 동시 요청 처리: 기본은 단일 큐라 씬별 fan-out(Send API)을 병렬로 던져도 ComfyUI 내부에서는 순차 처리됨 — Phase 3 전체 소요시간이 "씬 개수 × (draft+replace 시간)"으로 선형 증가. 진짜 병렬 처리가 필요하면 ComfyUI 멀티 인스턴스(포트 분리) 검토 필요.
- `animate_replace` 워크플로우는 단일 인물, 안정적 동작, 좋은 조명 전제에서 품질이 가장 좋음 — 씬 프롬프트 작성 시 이 조건을 벗어나지 않도록 가이드 필요.
