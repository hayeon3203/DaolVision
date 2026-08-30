# DaolVision

**오픈셸 자립형 생성 스튜디오** — 완전 오프라인·오픈소스 전용 환경에서 도는 생성 AI 스튜디오.

anim 영상 에이전트(LangGraph)를 LocalAI 포크 UI 위에 얹은 것. 시나리오 한 편을 넣으면
씬 분할 → 사람 승인 → 씬별 클립 생성 → 편집까지 한 번에 나온다.

그동안 만든 생성 경로를 지우지 않고 전부 남겨 뒀다. 어느 쪽이 정답이라서가 아니라
트레이드오프가 달라서다 — 구현 히스토리 보존이 목적이다.

## 무엇이 들어 있나 — 축이 두 개다

"버전이 몇 개냐"를 한 줄로 세면 틀린다. **입구**와 **생성 경로**는 서로 직교한다.

```
[입구]                                         [씬별 생성 경로 = mode]

localAI UI (:5199) ──┐                         ┌── T2V         인물 없음
                     ├──→ LangGraph :8700 ─────┼── STANDIN     인물 일관 · Wan
OWU 채팅 함수 ───────┘                         └── LTX_FACEID  인물 일관 · LTX
```

### 축 1 — 입구 (프론트엔드)

둘 다 **같은 게이트웨이(:8700)를 친다.** 파이프라인은 하나고 화면만 다르다.
"OWU 버전"과 "localAI 버전"은 서로 다른 구현이 아니다.

| 입구 | 위치 | 상태 |
|---|---|---|
| localAI UI (:5199) | `localai-ui/` | 가동 |
| Open WebUI 채팅 함수 | `openwebui/openwebui_anim_function.py` | 가동 |

### 축 2 — 생성 경로 (그 파이프라인 안의 씬 `mode`)

| 경우 | UI 진입점 | 씬 mode | 모델 |
|---|---|---|---|
| 1. 인물 없이 영상 여러 개 | `시나리오만` | `T2V` | LTX-Video 0.9.8 13B distilled, 1280×704/24fps |
| 2a. 한 인물 일관 — **Wan** | `사진 첨부`·`이미지 설명` | `STANDIN` | Wan2.1-T2V-14B + Stand-In LoRA, 832×480/16fps |
| 2b. 한 인물 일관 — **LTX** | `사진 첨부`·`이미지 설명` | `LTX_FACEID` | LTX-2.3 22B GGUF + Best-FaceID LoRA, 1280×704/24fps |

경우 1은 UI에서 모드만 고르면 되고, 2a ↔ 2b는 환경변수로 갈아 끼운다(아래).

### 축 밖 — 게이트웨이를 안 거치는 독립 파이프라인

각자 자기 백엔드를 직접 친다. 위 두 축과 무관한 별개 구현이다.

| 뭐 | 위치 | 백엔드 | 지금 도나 |
|---|---|---|---|
| OWU Wan director — 자체 플래너 LLM이 컷 나누고 캐릭터록 걸어 생성 | `openwebui/openwebui_function.py` | `:8500` 직통 | **아니오** — 서버 없음 |
| OWU Animate — 구동 영상으로 캐릭터 애니메이트 | `openwebui/openwebui_animate_function.py` | `:8600` 직통 | **아니오** — 서버 없음 |
| Cosmos3-Nano 단발 T2V — 프롬프트 한 줄 → 영상 하나 | `t2v/cosmos3nano/` | `:8505` | 가동 |

안 도는 둘은 `video_generator/hunyuan_server/`의 서버만 띄우면 그대로 붙는다.
지우지 않은 이유·살리는 법: [openwebui/README.md](openwebui/README.md)

## 버전 전환 — `AGENT_FACE_BACKEND`

**2a ↔ 2b 전환은 환경변수 하나.** 게이트웨이(:8700)가 기동할 때 읽으므로 바꾼 뒤
재시작해야 반영된다. 코드 수정도 브랜치 전환도 필요 없다.

```bash
# 2b — LTX Face-ID (기본값, 아무것도 안 해도 이 경로)
systemctl --user restart anim-agent

# 2a — Wan Stand-In
systemctl --user set-environment AGENT_FACE_BACKEND=standin
systemctl --user restart anim-agent

# 기본값으로 되돌리기
systemctl --user unset-environment AGENT_FACE_BACKEND
systemctl --user restart anim-agent
```

수동 기동이면 앞에 붙이기만 하면 된다 — `cd langgraph && AGENT_FACE_BACKEND=standin ./run_agent.sh`

제대로 갈렸는지는 job 하나 돌린 뒤 게이트웨이 로그의 라우팅 한 줄로 확인한다:

```
[route] 씬 mode: 1=STANDIN, 2=STANDIN, 3=STANDIN     # 2a
[route] 씬 mode: 1=LTX_FACEID, 2=PERSON_ASSEMBLY     # 2b
```

오타난 값은 조용히 기본값으로 폴백하지 않고 기동 시점에 죽는다 — 잘못된 백엔드로 몇
시간짜리 job을 돌리는 것보다 낫다.

**어느 쪽을 고를까**: 인물이 여러 씬에 계속 나오는 스토리면 **2a**. 2b는 22B GGUF 축출
정체 때문에 Face-ID 씬을 기본 1개로 제한하고(`AGENT_FACEID_MAX_SCENES`) 나머지는 조립
경로로 강등하므로, 인물 씬이 한두 개이고 화질이 우선일 때 쓴다.

경로별 상세·곁가지 mode(`SUBJECT_REF`/`PRODUCT_OVERLAY`/`PERSON_ASSEMBLY`)·env 전체 목록:
**[docs/pipelines.md](docs/pipelines.md)**

## 시나리오

- **S1 — 우주비행사의 여정**: 텍스트 스토리 → 씬분할 → 캐릭터 일관 I2V(4씬) → Chatterbox CC0 한국어 나레이션 → mp4
- **S2 — 내 얼굴 → 그림체 변환**: 얼굴사진 → 애니/유화초상화/프로필/우주비행사 (Flux Kontext)
- **독립 TTS — 내 목소리**: 참조 WAV → Chatterbox Multilingual V3 한국어 음성 복제
- **독립 T2V — 프롬프트만으로 영상**: 사진 입력 없이 텍스트 프롬프트 → Cosmos3-Nano 단발샷 영상(identity 불필요 용도)
- **연결**: S2 우주비행사 캐릭터 → S1 Face-ID 참조로

## 스택

국적 열은 초기 설계 목표(비중국 스택 구성)의 **기록**이다 — 지금은 선택 기준이 아니라
어느 모델이 어디서 왔는지 남긴 것이고, Wan 경로(2a)는 의도적으로 살려 두었다.

| 역할 | 모델 | 국적 |
|---|---|---|
| 씬분할 | Nemotron-4B | 🇺🇸 NVIDIA |
| 캡션 | gemma4:latest | 🇺🇸 Google |
| T2I | Flux.1-schnell | 🇩🇪 |
| I2I | Flux.1 Kontext | 🇩🇪 |
| I2V | LTX-Video distilled + Face-ID | 🇮🇱 |
| T2V 단발샷 | Cosmos3-Nano | 🇺🇸 NVIDIA |
| 영상 나레이션 TTS | Chatterbox Multilingual V3 + CC0 한국어 화자 | 🇨🇦 |
| 독립 사용자 음성 TTS | Chatterbox Multilingual V3 | 🇨🇦 |

## 라이선스 핵심

| 구성요소 | 라이선스 | 상업 사용·배포 영향 |
|---|---|---|
| ComfyUI · BFS Nodes · KJNodes · VideoHelperSuite | GPL-3.0 | 상업적 실행 가능. 수정본이나 결합 배포 시 GPL 소스 제공·고지 의무 검토 |
| WanVideoWrapper | Apache-2.0 | 상업 사용·수정·배포 가능, 저작권·라이선스 고지 유지 |
| ComfyUI GGUF 로더 | MIT | 상업 사용·수정·배포 가능, 저작권·라이선스 고지 유지 |
| LTX-2.3 및 파생 GGUF/LoRA | LTX-2 Community License | 상업 사용 가능. 연매출 미화 1천만 달러 이상 법인은 별도 상업 계약 필요 |
| LTX Best-Face-ID LoRA | 별도 라이선스 불명확 | 상업 배포 전 저작권자 조건 재확인 필요 |
| FLUX.1-schnell | Apache-2.0 | 상업 사용 가능 |
| FLUX.1 Kontext [dev] | FLUX.1 Dev Non-Commercial License | 상업 서비스에는 사용 불가하므로 상용 라이선스 또는 대체 모델 필요 |
| Cosmos3-Nano | OpenMDW1.1 | 상업 사용 조건 미검토, 배포 전 라이선스 원문 재확인 필요 |
| Chatterbox Multilingual V3 | MIT | 상업 사용 가능. 사용자 참조 음성은 별도 권리·동의 필요 |
| 고정 한국어 나레이션 참조 음성 | CC0-1.0 | 상업적 복제·수정·배포 가능 |

ComfyUI는 별도 로컬 HTTP 서비스로 격리한다. GPL은 네트워크 사용만으로
DaolVision 전체에 전파되지 않지만, 제품 번들로 배포할 때는 각 구성요소의 소스
제공 및 고지 의무를 별도로 확인한다. 위 내용은 기술적 검토이며 법률 자문이 아니다.

## 기동

기본은 host systemd user 서비스로 뜬다:

| 서비스 | 포트 | 유닛 |
|---|---|---|
| ComfyUI (LTX/Flux Kontext) | 8188 | `comfyui.service` |
| Flux.1-schnell T2I | 8501 | `flux.service` |
| LangGraph 게이트웨이 | 8700 | `anim-agent.service` |
| Chatterbox TTS | 8504 | `chatterbox.service` |
| 프로덕션 웹 UI | 5199 | `daolvision-ui.service` |

```bash
systemctl --user start comfyui flux anim-agent chatterbox daolvision-ui
```

Ollama는 시스템 유닛(`sudo systemctl start ollama`, :11434). Cosmos3-Nano
T2V(:8505)는 아직 systemd 유닛이 없어 수동 기동 —
[t2v/cosmos3nano/README.md](t2v/cosmos3nano/README.md) 참고.

## 오픈셸 GPU 샌드박스 격리 (선택)

Task 8.2.1: 위 host 유닛 대신 모델 서버(ComfyUI/T2I/Kokoro/Chatterbox/Ollama)를
openshell GPU 샌드박스에서 띄우는 경로도 있다. 웨이트·venv·코드는 호스트에
그대로 두고 서버 프로세스만 격리한다 — bind mount(대부분 읽기전용)로 호스트
경로를 샌드박스 내부 **동일 절대경로**에 연결하고, 기존 localhost 포트로
forward해 `langgraph/tools.py` 등 호출부는 코드 변경 없이 그대로 쓴다.

host 유닛과 샌드박스는 같은 포트를 두고 배타적이다 — 전환 전에 해당 host
유닛을 `stop`·`disable` 해야 한다(`scripts/start_studio.sh --check`가 점유
유닛과 내릴 명령을 알려준다).

```bash
./scripts/start_studio.sh --check          # 전제조건·포트 점유 점검
./scripts/start_studio.sh --up             # 5종 전체 샌드박스 기동
./scripts/start_studio.sh --up chatterbox  # 서비스 하나만
./scripts/start_studio.sh --down           # 정리
```

Cosmos3-Nano는 아직 이 스크립트의 서비스 테이블에 없다 — 샌드박스 격리 대상
밖, host에서 직접 실행.

구조·마운트 규칙·ollama 특이사항 상세: [docs/openshell-sandbox.md](docs/openshell-sandbox.md)

## 기획 문서

- [docs/PRD.md](docs/PRD.md) — 제품 요구사항 (product contract)
- [docs/UserFlow.md](docs/UserFlow.md) — 사용자 플로우
- [docs/Architecture.md](docs/Architecture.md) — 아키텍처
- [Plans.md](Plans.md) — 실행 task 원장 (7일 스프린트)
- [tts/chatterbox/README.md](tts/chatterbox/README.md) — 한국어 사용자 음성 테스트
- [docs/external-dependencies.md](docs/external-dependencies.md) — ComfyUI/HF캐시 등 git 비추적 외부 의존성
- [docs/model-selection.md](docs/model-selection.md) — 역할별 모델 채택 현황 총괄
- [docs/model-selection-t2v.md](docs/model-selection-t2v.md) — T2V 모델 선택 근거 (Cosmos3-Nano 채택, Task 7.6)

## 백엔드

- `inference_server/` — FLUX.1-schnell(:8501) 서버 코드 + systemd deploy unit(Task 3.7, video_generator hunyuan_server에서 복제 — 원본 유지). Animate(:8600)·Wan2.2-TI2V-5B(:8500)는 미사용 죽은 코드라 DaolVision에서 삭제(Task 6.5)
- `langgraph/` — :8700 게이트웨이(S1 파이프 오케스트레이션, Task 4.1에서 복제 — 원본 유지)
- `tts/chatterbox/` — Chatterbox Multilingual V3 서버(:8504), 영상 나레이션(CC0 고정 화자)·독립 음성 복제 겸용
- `t2v/cosmos3nano/` — Cosmos3-Nano T2V 서버(:8505), 프롬프트 단발샷 영상 생성 (Task 7.6)
- `openwebui/` — Open WebUI Function 3종 + 배포 스크립트(video_generator에서 이관). 채팅에서 쓰던 경로 보존 — `:8700` 에이전트 함수만 현재 가동, `:8500`·`:8600`용 둘은 서버가 없어 참고용

## 제약

- 오픈셸: 완전 오프라인·자립, External calls = 0 (실측 증명)
- GB10 119GB 통합메모리, OOM 예방 (전 모델 상주 우선 → 실패시 배치 언로드)
- 모델 국적은 기록용 정보 — 경로 선택 기준이 아니다(2a Wan 경로 유지)
