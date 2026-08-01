# Wan2.2 백엔드 제거 → LTX-13B-distilled T2V/I2V 통합

작성: 2026-08-01 · 관련: docs/model-selection.md, Plans.md 6.1(Flux Kontext)의
후속 대화에서 발견된 별도 작업. Plans.md에 태스크 번호 미부여 — writing-plans
단계에서 부여.

## 배경 / 문제

`nodes.py:893`(`node_generate_clip`)는 씬 모드에 따라 세 백엔드로 분기한다:

- `SUBJECT_REF` → `tools.generate_subject_ref_clip()` (ComfyUI :8188)
- `STANDIN` → `tools.generate_standin_clip()` (ComfyUI :8188)
- 그 외(T2V, USE_STANDIN=0일 때의 I2V 폴백) → `tools.call_video()` (Wan2.2
  :8500, `video_generator/hunyuan_server`)

`docs/model-selection.md`의 공통 원칙("모델은 **비중국 원산**")과 달리
Wan2.2-TI2V-5B는 알리바바(중국) 원산이다. 지금까지 이 원칙 위반이 방치돼
있었다 — 이번 대화에서 발견.

Wan2.2 서버(:8500, `huyuan-env/bin/python server.py`)는 상시 리소스로
~22GB VRAM을 항상 점유한다. 이 프로세스 자체(및 `video_generator/` 코드)는
DaolVision이 아니라 별도 프로젝트 소유이므로 삭제하지 않는다 — DaolVision
쪽에서 호출만 끊는다([[Duplicate, don't migrate]] 컨벤션과 동일 원리:
video_generator 원본은 건드리지 않음).

## 결정된 방향

`tools.call_video()`를 삭제하고, 이미 이 저장소에 있는
LTX-Video-0.9.8-13B-distilled(Task 4.6, `/i2v` 원샷 엔드포인트가 쓰는 그
체크포인트 — `flux1-dev-kontext_fp8_scaled.safetensors`처럼 신규 다운로드
아님)로 T2V/I2V 폴백 두 경로 모두 통합한다. 신규 모델 다운로드 없음.

대안으로 "이미지 없는 씬은 FLUX.1-schnell T2I 앵커를 먼저 만들고 기존 I2V
그래프로 넘긴다"(신규 그래프 0줄, 100% 기존 코드 재사용)도 검토했으나,
사용자가 LTX 순수 T2V 그래프 신규 구축을 선택함 — 앵커 경유 없이 텍스트만으로
직접 생성하는 편이 Wan이 원래 하던 일과 더 가깝다는 판단.

## 컴포넌트

### 1. `_build_ltx13b_t2v_graph()` (신규, `tools.py`)

기존 `_build_ltx13b_graph()`(4.6, `_build_ltx13b_graph` 그대로 유지)의
형제 함수. 차이는 딱 두 노드:

- `LoadImage`(5번) + `LTXVImgToVideo`(7번) 제거
- `EmptyLTXVLatentVideo`(width, height, length, batch_size=1)로 대체 —
  ComfyUI `comfy_extras/nodes_lt.py`에 기본 내장된 노드, 이미지 조건 없이
  순수 노이즈 latent를 만듦.

나머지(`CheckpointLoaderSimple`, `CLIPLoader`, `CLIPTextEncode`,
`ModelSamplingLTXV`, `LTXVConditioning`, `LTXVScheduler`, `KSampler`,
`VAEDecode`, `SaveAnimatedWEBP`)는 `_build_ltx13b_graph()`와 동일 배선.
`LTX13B_CHECKPOINT`/`LTX13B_CLIP`/`LTX13B_STEPS`/`LTX13B_FPS` 상수 그대로
재사용.

### 2. `_generate_ltx_job_clip()` (신규 공유 헬퍼, `tools.py`)

`generate_i2v_oneshot`류 단순 폴링이 **아니라** `_generate_reference_clip()`
(STANDIN/SUBJECT_REF가 쓰는 패턴)을 그대로 따른다:

- SQLite prompt 추적(`_save_prompt`/`_recoverable_prompt`/`_update_prompt`) —
  같은 `comfy_prompts` 테이블에 씀. `recoverable_comfy_jobs()`는 이 테이블을
  일반적으로 스캔하므로(모드 무관) 추가 배선 없이 자동으로 재시작 복구 대상에
  편입됨.
- 큐 타임아웃(`STANDIN_QUEUE_TIMEOUT`) / missing-prompt 타임아웃
  (`STANDIN_MISSING_TIMEOUT`) / 실행 타임아웃(`STANDIN_EXEC_TIMEOUT`) 동일 적용.
- 출력: `job_dir(job_id)/clip{scene_id}.mp4` — 기존 관례 그대로, ffmpeg
  concat/xfade 쪽 무변경.
- `force_new`로 캐시 재사용/강제 재생성 스위치(형제 함수들과 동일 시그니처).

이미지 업로드 단계(`_generate_reference_clip`의 1번 스텝)만 T2V 경로에서
생략된다. I2V 폴백 경로는 이미지 업로드를 유지하되 `_build_ltx13b_graph()`를
그대로 재사용한다(신규 그래프 불필요, 4.6 그래프가 이미 image-conditioned).

**request_key 해시 필드(명시)**: `_generate_reference_clip`을 그대로
베껴 쓰면 안 되는 지점 — `ref_image`/`reference_mode`/`relight`/`face_lora`
필드는 T2V에 해당 없음. 두 경로 모두 `prompt`를 반드시 해시에 포함해야
한다(누락 시 씬 프롬프트를 수정하고 `force_new=False`로 재실행해도
구프롬프트로 만든 캐시 클립을 그대로 반환하는 버그가 생김 — `scene_id`가
DB 조회 WHERE절에 별도 컬럼으로 있어도 request_key 자체가 프롬프트 변경을
반영 못 하면 stale 캐시를 못 걸러냄).

```python
# generate_t2v_clip 쪽 request_key 페이로드
{
    "scene_id": scene_id, "prompt": prompt, "duration": duration, "seed": seed,
    "steps": LTX13B_STEPS, "fps": LTX13B_FPS, "width": WIDTH, "height": HEIGHT,
    "workflow": "ltx13b_t2v_v1",  # 그래프 구조 바뀌면 캐시 무효화용 버전 문자열
}
# generate_i2v_fallback_clip 쪽은 위에 matched_image까지 추가
{
    "scene_id": scene_id, "prompt": prompt, "matched_image": matched_image,
    "duration": duration, "seed": seed, "steps": LTX13B_STEPS, "fps": LTX13B_FPS,
    "width": WIDTH, "height": HEIGHT, "workflow": "ltx13b_i2v_fallback_v1",
}
```

### 3. 얇은 wrapper 2개 (`tools.py`, `call_video` 호출부 대체)

```python
async def generate_t2v_clip(
    job_id: str, scene_id: int, prompt: str,
    duration: float = 2.0, seed: int | None = None, force_new: bool = False,
) -> str:
    ...  # _build_ltx13b_t2v_graph + _generate_ltx_job_clip

async def generate_i2v_fallback_clip(
    job_id: str, scene_id: int, prompt: str, matched_image: str,
    duration: float = 2.0, seed: int | None = None, force_new: bool = False,
) -> str:
    ...  # _build_ltx13b_graph(기존, 4.6) + _generate_ltx_job_clip
```

### 4. `nodes.py:893` 디스패치 변경

```python
else:  # T2V/I2V(Wan 폴백) → LTX(:8188)
    if scene["mode"] == "I2V":
        clip_path = await tools.generate_i2v_fallback_clip(
            job_id=job_id, scene_id=scene["id"], prompt=scene["prompt"],
            matched_image=scene["matched_image"],
            duration=scene.get("duration", 2.0), seed=payload.get("seed"),
            force_new=payload.get("force_new", False),
        )
    else:  # T2V
        clip_path = await tools.generate_t2v_clip(
            job_id=job_id, scene_id=scene["id"], prompt=scene["prompt"],
            duration=scene.get("duration", 2.0), seed=payload.get("seed"),
            force_new=payload.get("force_new", False),
        )
```

### 5. 삭제 대상

- `tools.call_video()` 함수 전체
- `WAN_URL` 상수 및 그 사용부
- `run_agent.sh`의 `AGENT_WAN_URL` export (더 이상 아무도 안 읽음)

`video_generator/hunyuan_server/server.py` 자체는 삭제하지 않는다(별도
프로젝트 소유). 프로세스를 계속 띄워둘지/내릴지는 이 작업과 무관한 별도 결정
— DaolVision 쪽에서 부르지 않게 되는 것으로 이 스펙의 목적은 달성됨.

## Data flow

`to_4k1(duration * LTX13B_FPS)` 프레임 변환 — Wan이 쓰던
`to_4k1(duration * DEFAULT_FPS)`와 동일 헬퍼, fps 상수만 LTX13B_FPS(24,
Wan의 DEFAULT_FPS와 우연히 동일)로 정렬. width/height는 `_ltx13b_dims()`
대신 job 파이프라인 기존 `WIDTH`/`HEIGHT` 전역(비디오 프리셋 시스템,
Wan이 쓰던 것과 동일) 사용 — T2V/I2V 폴백 모두 입력 이미지 종횡비가 없거나
이미 정해진 씬 해상도를 쓰므로 Kontext류 종횡비 버킷 계산 불필요.
seed는 씬 간 노이즈 일관성을 위해 그대로 passthrough.

## Error handling / recovery

`_generate_reference_clip`의 기존 타임아웃 사다리 + SQLite 재개를 그대로
상속 — Wan 경로(재개 불가, `call_video` 자체 주석에 "연결 끊겨도 생성을
취소 안 하므로 read 타임아웃을 없앤다"고 명시돼 있어 프로세스 재시작 시
해당 씬은 유실됐음)보다 오히려 신뢰성이 올라간다.
`oom.phase("i2v")` 게이팅은 그대로 유지 — LTX는 이미 5.x Face-ID/오네샷
엔드포인트와 이 phase 이름을 공유한다.

## Testing

- 단위 테스트(`tests/test_wan_removal.py`, 신규): ComfyUI HTTP 콜을
  monkeypatch해 그래프 노드 배선 검증(T2V 그래프엔 `LoadImage`/`image` 관련
  노드 없음, I2V 폴백 그래프는 기존 `_build_ltx13b_graph`와 노드 집합 동일),
  duration→프레임 수 계산 검증, `nodes.py`가 더 이상 `tools.call_video`를
  참조하지 않는지 grep 검증. `test_i2v_oneshot.py`/`test_i2i_style.py`
  컨벤션 그대로 — GPU 없이 돈다.
- **라이브 GPU 검증(사용자 명시 요청)**: 위 유닛테스트와 별도로, 구현 완료
  후 실제 job을 하나 돌려(이미지 없는 씬 최소 1개 포함) `:8700` 파이프라인
  전체 경로로 clip이 실제로 생성되는지 확인. 6.1에서 했던 방식과 동일하게
  진행 전 GPU/메모리 상태 재점검(현재 ComfyUI 자체 캐시가 유동적이므로 그
  시점 재확인 필요) 후 실행, 산출물(clip 파일 경로) 및 소요시간 기록.
  distilled 8-step 체크포인트가 이미지 조건 없이도 코히런스를 유지하는지는
  이 라이브 검증에서 실측 확인 — 실패 시(품질 붕괴) steps/guidance 조정
  또는 T2I-앵커 경유안(위 "대안" 절)으로 재검토.

## Out of scope

- `hunyuan_server` 프로세스를 지금 내릴지 여부 — 이 스펙 구현과 별개 결정.
- Wan이 서비스하던 다른 프로젝트(video_generator 자체의 T2V 기능) — 안 건드림.
