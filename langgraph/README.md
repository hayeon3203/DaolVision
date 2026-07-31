# langgraph_videogenerator

## 프로젝트 소개

**"이야기 한 편을 넣으면 편집까지 끝난 영상 한 편이 나오는" 로컬 영상 제작 에이전트**입니다.

스토리(텍스트) 또는 참조 이미지를 입력하면 **씬 분할 → 씬별 영상 생성 → 편집·자막 → 최종 렌더**까지
LangGraph 상태 기계가 자동으로 수행합니다. 다만 완전 자동은 아닙니다 — 영상 생성은 GPU 비용이 커서
잘못된 방향으로 오래 달리면 손해가 크기 때문에, 사람이 중간 결과를 확인하고 승인/수정/재생성을
지시하는 **휴먼 승인 게이트 3곳**을 일부러 남겨둔 "사람이 감독하는 자동화"입니다.

특징:

- **완전 로컬**: LLM(Ollama), 영상 생성(Wan2.2/Wan2.1), 편집(ffmpeg) 전부 한 대에서. 외부 API 의존 없음.
- **멈췄다 재개**: 상태가 SQLite 체크포인트로 저장되어, 몇 시간 뒤 승인해도 멈춘 지점부터 이어집니다.
- **얼굴 일관성**: 참조 이미지를 주면 해당 인물 씬은 Stand-In(14B) 경로로 라우팅되어 얼굴이 유지됩니다.
- **채팅으로 조작**: Open WebUI에서 자연어로 지시합니다 (예: `승인`, `재생성 2,4`, `씬3에 2번째 사진 넣어줘`).

## 전제 조건

| 구분 | 요구 사항 |
|---|---|
| GPU/메모리 | 두 모델 상주 기준 GPU 메모리 **~40GB+** (Wan2.2-5B ~22GB + Wan2.1-14B fp8 ~17GB). 개발 환경은 GB10(NVIDIA DGX Spark, 119GB 통합메모리, sm_121) |
| OS | Linux (개발 환경: Ubuntu 24.04, CUDA 13.0) |
| Python | 3.12 |
| 시스템 도구 | `ffmpeg` 6.x 이상 (크로스페이드·자막·최종 렌더) |

## 필요 구성 요소

이 에이전트는 **지휘자**이고, 실제 연주는 아래 서비스들이 합니다. 넷 다 떠 있어야 전체 파이프라인이 돕니다.

| 구성 요소 | 역할 | 준비물 |
|---|---|---|
| [Ollama](https://ollama.com) | 씬 분할·프롬프트 생성 LLM | `ollama pull qwen2.5:7b` (+선택: 이미지 캡션용 `gemma3:4b`) |
| Wan 추론 서버 (`:8500`) | 일반 씬 T2V/I2V 생성 | `Wan-AI/Wan2.2-TI2V-5B-Diffusers` (HuggingFace, diffusers 서버로 서빙) |
| [ComfyUI](https://github.com/comfyanonymous/ComfyUI) (`:8188`) | 참조 얼굴 씬(Stand-In) 생성 | [WanVideoWrapper](https://github.com/kijai/ComfyUI-WanVideoWrapper)·VideoHelperSuite 커스텀 노드 + 모델 파일: `Wan2_1-T2V-14B_fp8_e4m3fn`, Stand-In LoRA, lightx2v distill LoRA, `Wan2_1_VAE`, `umt5-xxl` |
| [SageAttention](https://github.com/thu-ml/SageAttention) | 어텐션 가속 (클립당 202s→142s) | ComfyUI의 venv에 소스 빌드 설치 (2.2, `sageattn3` 포함) |
| Python 라이브러리 | 에이전트 본체 | `requirements.txt` (langgraph, fastapi, httpx 등) |

## 시작하기

```bash
# 1. 클론 + 가상환경
git clone https://github.com/hayeon3203/langgraph_videogenerator.git
cd langgraph_videogenerator
python3.12 -m venv .venv && ./.venv/bin/pip install -r requirements.txt

# 2. LLM 준비
ollama pull qwen2.5:7b

# 3. 생성 백엔드 확인 (별도 기동, systemd 상주 권장)
curl http://127.0.0.1:8500/health      # Wan T2V/I2V 서버
curl http://127.0.0.1:8188/system_stats  # ComfyUI (+WanVideoWrapper)
curl http://127.0.0.1:8503/health      # Kokoro 한국어 나레이션

# 4. GPU 없이 파이프라인 검증 (가짜 클립으로 전체 흐름 확인)
./.venv/bin/python driver.py --dry

# 5. 에이전트 기동 (:8700)
./run_agent.sh

# 6. (선택) Open WebUI 관리자 패널에 openwebui_anim_function.py 등록 → 채팅으로 조작
```

포트·모델·스텝 수 등 모든 튜너블은 `run_agent.sh`의 env var로 바꿉니다 — 소스 수정이 필요 없습니다.

---

## 아키텍처

```
사용자 (Open WebUI 채팅)
  └─ openwebui_anim_function.py  ← 멀티턴 승인 UI (자연어 명령 해석)
       └─ :8700  api.py (FastAPI)
            └─ LangGraph 상태 기계 (graph.py / nodes.py, SQLite 체크포인트)
                 ├─ LLM: Ollama qwen2.5:7b        ← 씬 분할·프롬프트 생성 (로컬)
                 ├─ T2V/I2V: :8500 Wan2.2-TI2V-5B  ← 일반 씬 (FastAPI 서버)
                 ├─ Stand-In: :8188 ComfyUI Wan2.1-14B ← 참조 얼굴 일관성 씬
                 └─ ffmpeg                          ← 크로스페이드·자막·최종 렌더
```

파이프라인 (5단계):

```
START → 입력 파싱 → 씬 분할
      → [승인 게이트 1] 씬 구성 승인 / 자연어 수정
      → 씬별 프롬프트 생성 (+ style bible 주입)
      → 클립 병렬 생성 (T2V ↔ Stand-In 자동 라우팅, Send fan-out)
      → [승인 게이트 2] 클립 승인 / 특정 씬 재생성
      → 편집 (크로스페이드·자막)
      → [승인 게이트 3] 최종 확인
      → 최종 렌더 → DONE
```

- 상태는 SQLite에 체크포인트로 저장됩니다(`thread_id = job_id`). 몇 시간 뒤에 승인해도 멈춘 지점부터 정확히 재개됩니다.
- 재생성은 **항상 사람이 결정**합니다. AI가 스스로 재생성 루프를 돌지 않습니다(GPU 무한 소모 방지).
- 게이트는 3곳으로 고정 — 더 많으면 승인 피로, 더 적으면 재작업 비용이 커집니다.

## 파일 구조

```
langgraph_videogenerator/
├── state.py      # GraphState, Scene 타입 정의
├── tools.py      # 모든 외부 호출 (Ollama, :8500, ComfyUI :8188, ffmpeg) — 인프라 교체 시 이 파일만 수정
├── nodes.py      # 5단계 노드 로직 + 승인 게이트 3곳 + style bible
├── graph.py      # 노드 배선 + SQLite 체크포인터
├── api.py        # :8700 FastAPI (/jobs, /resume, /revise, /cancel, /metrics)
├── metrics.py    # 운영 지표
├── openwebui_anim_function.py  # Open WebUI 멀티턴 Function (Open WebUI 관리자 패널에 등록)
├── comfyui_workflows/
│   └── standin_t2v.json        # Stand-In 워크플로우 (GB10 최적화 반영)
├── driver.py     # E2E 드라이버 (--dry: GPU 없이 검증)
└── test_*.py     # 단위/통합 테스트
```

## API 요약 (:8700)

| 엔드포인트 | 역할 |
|---|---|
| `POST /jobs` | 새 job 시작 (스토리 + 참조 이미지) |
| `POST /jobs/{id}/resume` | 승인 게이트 재개 (`approve_all`, `regenerate [2,4]` 등) |
| `POST /jobs/{id}/revise` | **자연어 수정 지시**를 씬 구조에 반영 (게이트 1) |
| `POST /jobs/{id}/cancel` | job 취소 |
| `POST /tts/narration` | Kokoro 한국어 영상 나레이션 WAV 생성 |
| `GET /jobs/{id}/state` | 현재 상태 조회 (`__interrupt__` 포함 = 승인 대기) |
| `GET /metrics` | 운영 지표 |

응답에 `__interrupt__`가 있으면 **사람 승인 대기**, `phase: "done"`이면 완료입니다.

## 품질 장치

- **Style bible (분위기 통일)**: job당 1회 LLM이 전체 스토리로부터 시각 스타일 명세를 만들어
  모든 씬 프롬프트에 주입 → 씬 간 화풍/톤이 통일됩니다. 의상 잠금(wardrobe lock)도 추출해 인물 의상이 씬마다 바뀌는 것을 방지합니다.
- **Stand-In 얼굴 일관성**: 참조 이미지가 지정된 씬은 ComfyUI의 Wan2.1-14B + Stand-In LoRA로 라우팅되어
  등장인물 얼굴이 유지됩니다. 제출 이력은 `comfy_prompts.db`에 즉시 영속화되어 에이전트가 재시작해도 복구됩니다.
- **LLM 환각 방어**: 씬 분할 LLM이 존재하지 않는 참조 이미지 파일명을 지어내면 자동으로 T2V로 강등합니다.

## GB10 최적화 (성능 튜닝 이력)

GB10은 CPU/GPU가 119GB 통합메모리를 공유합니다. VRAM 절약용 오프로드 기법이
같은 DRAM 안의 복사만 반복하는 순수 낭비가 되므로 전부 제거하고 모델을 상주시켰습니다.

`comfyui_workflows/standin_t2v.json` 기준:

| 항목 | 변경 | 효과 |
|---|---|---|
| `blocks_to_swap` | 15 → **0** | 매 스텝 모델 조각 CPU↔GPU 왕복 제거 |
| 모델 로더 `load_device` | offload_device → **main_device** | 14B를 GPU에 상주 |
| 샘플러 `force_offload` | true → **false** | 생성 후에도 모델을 내리지 않음 |
| `attention_mode` | sdpa → **sageattn** (SageAttention 2.2, 소스 빌드) | 어텐션 가속 |
| lightx2v LoRA / shift | strength **0.6** / shift **9.0** | 모션 튜닝 |

실측(832×480, 81프레임, 4스텝, 상주 상태): **클립당 202초 → 142초**.
모델 로딩(~2분/회)은 상주화 + ComfyUI systemd 서비스화로 0이 됨.

⚠️ 이 스택에서 확인된 금지 조합:
- `sageattn_3`(fp4): GB10에서 커널 dtype 에러
- `fp8_e4m3fn_fast`: 비병합 LoRA(SetLoRAs) 구조와 비호환
- **sageattn + torch.compile**: 매 실행 재컴파일 폭주(30분+ 멈춤) → compile 제거 필수

## 기술 결정: 왜 OpenShell이 아니라 LangGraph인가

초기 프로토타입(`orchestrator/`)은 OpenShell 기반이었으나 다음 이유로 부적합 판정, LangGraph로 전환했습니다:

| 기준 | OpenShell | LangGraph (채택) |
|---|---|---|
| 사람 승인 흐름 | 순차 실행만 가능, 중간 개입 불가 | `interrupt()` 네이티브 지원 (게이트 3곳) |
| 상태 재개 | DB+복원 로직 직접 구현 필요 | SQLite 체크포인트로 멈춘 지점부터 재개 |
| 씬 메타데이터 공유 | 인스턴스 간 공유 어려움 (별도 DB 필요) | 중앙 state dict에 일원화 |
| 병렬 클립 생성 | 인스턴스 N개 수동 관리 | `Send` fan-out 내장 |
| 운영 | 단순 실험용 | 실서비스 수준 (API + 체크포인트 + 복구) |

요약: OpenShell은 "일꾼"만 제공하지만, 이 파이프라인의 본질은 **멈췄다 재개하는 승인 워크플로우와 상태 관리**이며
그것은 LangGraph가 프레임워크 차원에서 제공합니다. 상세 비교는 `BRIEFING.md` 참조.

## Open WebUI 연동

`openwebui_anim_function.py`를 Open WebUI Function으로 등록하면 채팅에서 전 과정을 조작할 수 있습니다.
승인이 멀티턴이므로 job/체크포인트를 어시스턴트 메시지 말미의 HTML 주석 마커로 유지합니다.
자연어 명령 예: `승인` / `approve` / `재생성 2,4` / `씬1에 첫번째 사진` / 자유 문장 수정 지시(게이트 1).
