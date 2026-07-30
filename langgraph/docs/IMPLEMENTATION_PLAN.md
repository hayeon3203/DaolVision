# 구현 계획 — anim_video_agent 스캐폴드 → 실동작 (A+B)

스캐폴드(`state/graph/nodes/api.py`)의 아키텍처는 유지. `tools.py`의 가짜 엔드포인트·미구현부를
실제 GB10 인프라에 배선하고, OWU 연동까지. **자동 품질체크(3-2)는 제거.**

## 확정된 실측 사실
- LLM: Ollama `127.0.0.1:11434/api/chat`, `qwen2.5:7b` (네이티브 chat API, `.message.content`)
- 비디오: Wan2.2-TI2V-5B `127.0.0.1:8500` — `/generate`(T2V), `/generate_i2v`(base64 `image`), `num_frames`=4k+1, 응답 `{video_url}` (상대경로, GET으로 mp4 다운로드)
- `httpx` 설치됨 / `langgraph` 미설치
- OWU 연동 기존 방식 = Function 추정(`booth_game_pipeline.py`만 pipelines에 존재) → Phase B에서 확정

## Phase A — 헤드리스 end-to-end 동작

### A0. 의존성
`~/huyuan-env/bin/pip install langgraph langgraph-checkpoint-sqlite` (httpx 있음).
설치 후 `interrupt/Command/Send/AsyncSqliteSaver` import 되는 버전 확인.

### A1. `tools.py` 재작성 (nodes.py는 최소 수정 원칙)
- `call_llm(system, user)` → Ollama `/api/chat`, model=`qwen2.5:7b`, `stream:false`. 반환 `.message.content`.
  scene-split은 JSON-only 요구인데 qwen이 ```json 펜스를 붙일 수 있으니 방어 파싱 헬퍼 추가.
- `call_video(prompt, mode, ref_image_b64)` (구 `call_hunyuan_video`):
  - T2V → POST `/generate` `{prompt, num_frames, num_inference_steps, width, height}`
  - I2V → POST `/generate_i2v` + `{image: ref_image_b64}`
  - `num_frames = to_4k1(round(duration*fps))` 헬퍼 (기본 fps 16, 최소 17)
  - 응답 `video_url` → GET으로 mp4 받아 `OUT/jobs/<job_id>/clipN.mp4` 저장, 그 경로 반환
- `call_quality_check` **삭제** (호출부도 제거).
- `build_xfade_filter(clip_paths, transitions)` 구현: `ffprobe`로 각 클립 duration 읽어
  누적 offset으로 xfade 체인 구성. transition=="cut"이면 xfade 대신 단순 concat 세그먼트.
- `ffmpeg_concat`, `burn_subtitles`는 유지(경로만 확인).

### A2. `nodes.py` 최소 수정
- `node_generate_one_clip`: `call_quality_check` 호출 제거 → `quality_flag="pending"`, `quality_score=None`.
  `call_video` 새 시그니처에 맞춰 ref 이미지 base64 전달.
- ref 이미지 해결: job 시작 시 `ref_images`(base64/data-URI)를 `OUT/jobs/<job_id>/refs/`에 저장,
  `matched_image`는 그 파일명. tools가 읽어 base64 인코딩. (nodes에 작은 헬퍼 or api에서 선처리)
- 출력 경로 `/tmp/...`, `/mnt/user-data/outputs/...` → `OUT/jobs/<job_id>/`.

### A3. `api.py` 수정
- `AsyncSqliteSaver` 경로를 `OUT/checkpoints.db`로. `@app.on_event`는 유지(동작함) 또는 lifespan로.
- job 시작 시 refs 디스크 저장 선처리.
- bind `0.0.0.0`, port env(기본 8700).

### A4. 헤드리스 검증 (필수 게이트)
`driver.py`: `/jobs` 시작 → `__interrupt__` 오면 자동 승인 payload로 `/resume` ×3 → 최종 mp4 확인.
3개 체크포인트(1-4 승인, 3-5 approve_all, 4-5 승인) 통과 + `final_video_path` 재생 가능하면 A 완료.

## Phase B — OWU 연동
### B0. 기존 연동 방식 확정
OWU가 영상 서버를 Function으로 부르는지 pipeline으로 부르는지 실제 확인
(`openwebui_function.py` vs pipelines 컨테이너). 같은 메커니즘 재사용.

### B1. OWU 플러그인 (start-or-resume 매핑)
- 대화별로 job_id 보관(첫 메시지=`/jobs` 시작, 이후=`/resume`).
- 서버 응답의 `checkpoint`(interrupt payload)를 마크다운으로 렌더:
  - 1-4: 씬 목록 표(id/텍스트/mood/mode) + "승인하려면 `approve`, 수정은 ..." 안내
  - 3-5: 씬별 클립 **영상 링크**(OWU `<video>` sanitize 우회 = 마크다운 링크, 기존 방식 재사용) + `approve_all`/`regenerate 2,4`
  - 4-5: 프리뷰 링크 + `approve`
- 사용자 메시지 텍스트를 resume payload로 파싱(approve / regenerate 2,4 등).
- 완료 시 `final_video_path` 링크.

### B2. 실동작 검증
OWU 채팅창에서 스크립트 입력 → 3개 승인 → 최종 영상 링크까지 실제 통과.

## 범위 밖 (Phase C, 이번 제외)
5-1 실제 고해상도 재렌더(현재 프리뷰 copy), xfade 미세 정확도, 취소, Send 실제 병렬화(서버 단일 GPU라 무의미).
