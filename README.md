# DaolVision

**오픈셸 자립형 생성 스튜디오** — 완전 오프라인·오픈소스 전용 환경에서 동작하는 생성 AI 스튜디오입니다.

anim 영상 에이전트(LangGraph)를 LocalAI 포크 UI와 결합한 시스템입니다. 시나리오 한 편을
입력하면 씬 분할, 사람의 승인, 씬별 클립 생성, 편집까지 한 번에 진행됩니다.

그동안 만들어 온 생성 경로는 하나도 삭제하지 않고 모두 남겨 두었습니다. 어느 한 경로가
정답이기 때문이 아니라 경로마다 트레이드오프가 다르기 때문이며, 구현 이력을 보존하는 것이
목적입니다.

## 무엇이 들어 있는가: 서로 독립적인 두 개의 축

"버전이 몇 개인가"라는 한 가지 기준만으로 세면 실제 구조를 잘못 파악하게 됩니다.
**입구**와 **생성 경로**는 서로 영향을 주지 않는 별개의 축이므로, 두 축을 조합해서
이해해야 합니다.

```
[입구]                                         [씬별 생성 경로 = mode]

localAI UI (:5199) ──┐                         ┌── T2V         인물 없음
                     ├──→ LangGraph :8700 ─────┼── STANDIN     인물 일관 · Wan
OWU 채팅 함수 ───────┘                         └── LTX_FACEID  인물 일관 · LTX
```

### 축 1: 입구 (프론트엔드)

두 입구 모두 같은 게이트웨이(:8700)로 요청을 보냅니다. 파이프라인은 하나이고 화면만
다르기 때문에, "OWU 버전"과 "localAI 버전"은 서로 다른 구현이 아닙니다.

| 입구 | 위치 | 상태 |
|---|---|---|
| localAI UI (:5199) | `localai-ui/` | 가동 |
| Open WebUI 채팅 함수 | `openwebui/openwebui_anim_function.py` | 가동 |

### 축 2: 생성 경로 (같은 파이프라인 안에서 씬마다 결정되는 `mode`)

| 경우 | UI 진입점 | 씬 mode | 모델 |
|---|---|---|---|
| 1. 인물 없이 영상 여러 개 | `시나리오만` | `T2V` | LTX-Video 0.9.8 13B distilled, 1280×704/24fps |
| 2a. 한 인물 일관 — **Wan** | `사진 첨부`·`이미지 설명` | `STANDIN` | Wan2.1-T2V-14B + Stand-In LoRA, 832×480/16fps |
| 2b. 한 인물 일관 — **LTX** | `사진 첨부`·`이미지 설명` | `LTX_FACEID` | LTX-2.3 22B GGUF + Best-FaceID LoRA, 1280×704/24fps |

경우 1은 UI에서 모드만 선택하면 되고, 2a와 2b 사이의 전환은 아래에 설명한 환경변수
하나로 이루어집니다.

### 두 축의 밖: 게이트웨이를 거치지 않는 독립 파이프라인

아래 파이프라인들은 게이트웨이를 통하지 않고 각자 자기 백엔드 서버를 직접 호출합니다.
위의 두 축과는 관련이 없는 별개 구현입니다.

| 파이프라인 | 위치 | 백엔드 | 현재 가동 여부 |
|---|---|---|---|
| OWU Wan director — 자체 플래너 LLM이 컷을 나누고 캐릭터록을 적용해 생성 | `openwebui/openwebui_function.py` | `:8500` 직접 호출 | **미가동**(서버 없음) |
| OWU Animate — 구동 영상으로 캐릭터를 애니메이트 | `openwebui/openwebui_animate_function.py` | `:8600` 직접 호출 | **미가동**(서버 없음) |
| Cosmos3-Nano 단발 T2V — 프롬프트 한 줄로 영상 하나 생성 | `t2v/cosmos3nano/` | `:8505` | 가동 |

미가동 상태인 두 파이프라인은 `video_generator/hunyuan_server/`의 서버를 실행하기만 하면
코드 수정 없이 그대로 다시 연결됩니다. 삭제하지 않은 이유와 되살리는 방법은
[openwebui/README.md](openwebui/README.md)에 정리해 두었습니다.

## 버전 전환: `AGENT_FACE_BACKEND`

**2a와 2b 사이의 전환에는 환경변수 하나만 사용합니다.** 게이트웨이(:8700)가 기동할 때
이 값을 읽으므로, 값을 바꾼 뒤에는 반드시 재시작해야 반영됩니다. 코드 수정이나 브랜치
전환은 필요하지 않습니다.

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

수동으로 기동할 때에는 명령 앞에 환경변수를 붙이면 됩니다.

```bash
cd langgraph && AGENT_FACE_BACKEND=standin ./run_agent.sh
```

전환이 제대로 적용되었는지는 job을 하나 실행한 뒤 게이트웨이 로그에 기록되는 라우팅
한 줄에서 확인합니다.

```
[route] 씬 mode: 1=STANDIN, 2=STANDIN, 3=STANDIN     # 2a
[route] 씬 mode: 1=LTX_FACEID, 2=PERSON_ASSEMBLY     # 2b
```

환경변수에 오타가 있는 값을 넣으면 기본값으로 조용히 대체하지 않고 기동 시점에 오류를
내며 종료합니다. 잘못된 백엔드로 몇 시간이 걸리는 job을 실행하는 것보다 즉시 실패하는
편이 낫기 때문입니다.

**어느 쪽을 선택할 것인가**: 인물이 여러 씬에 계속 등장하는 스토리라면 **2a**를 사용합니다.
2b는 22B GGUF 모델을 메모리에서 내렸다가 다시 올리는 과정에서 재양자화가 발생해 오래
지연되므로, Face-ID를 적용하는 씬을 기본 1개로 제한하고(`AGENT_FACEID_MAX_SCENES`)
나머지 씬은 조립 경로로 처리합니다. 따라서 2b는 인물이 등장하는 씬이 한두 개이고 화질이
더 중요할 때 사용합니다.

경로별 상세 설명과 보조 mode(`SUBJECT_REF`/`PRODUCT_OVERLAY`/`PERSON_ASSEMBLY`), 환경변수
전체 목록은 **[docs/pipelines.md](docs/pipelines.md)**에 있습니다.

## 시나리오

- **S1 — 우주비행사의 여정**: 텍스트 스토리 → 씬분할 → 캐릭터 일관 I2V(4씬) → Chatterbox CC0 한국어 나레이션 → mp4
- **S2 — 내 얼굴 → 그림체 변환**: 얼굴사진 → 애니/유화초상화/프로필/우주비행사 (Flux Kontext)
- **독립 TTS — 내 목소리**: 참조 WAV → Chatterbox Multilingual V3 한국어 음성 복제
- **독립 T2V — 프롬프트만으로 영상**: 사진 입력 없이 텍스트 프롬프트 → Cosmos3-Nano 단발샷 영상(identity가 필요 없는 용도)
- **연결**: S2에서 만든 우주비행사 캐릭터를 S1의 Face-ID 참조로 전달

## 스택

국적 열은 초기 설계 목표였던 비중국 스택 구성을 남긴 **기록**입니다. 지금은 경로를 고르는
기준이 아니라 각 모델이 어디에서 왔는지를 보여 주는 정보이며, Wan 경로(2a)도 의도적으로
유지하고 있습니다.

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

ComfyUI는 별도 로컬 HTTP 서비스로 격리합니다. GPL은 네트워크로 사용하는 것만으로는
DaolVision 전체에 전파되지 않지만, 제품 번들 형태로 배포할 때에는 각 구성요소의 소스
제공 의무와 고지 의무를 별도로 확인합니다. 위 내용은 기술적 검토이며 법률 자문이 아닙니다.

## 기동

기본 구성에서는 각 서버가 host의 systemd user 서비스로 기동합니다.

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

Ollama는 시스템 유닛으로 기동합니다(`sudo systemctl start ollama`, :11434).
Cosmos3-Nano T2V(:8505)는 아직 systemd 유닛이 없어서 수동으로 기동해야 하며,
자세한 내용은 [t2v/cosmos3nano/README.md](t2v/cosmos3nano/README.md)를 참고합니다.

## 오픈셸 GPU 샌드박스 격리 (선택)

Task 8.2.1에서는 위의 host 유닛 대신 모델 서버(ComfyUI/T2I/Kokoro/Chatterbox/Ollama)를
openshell GPU 샌드박스에서 기동하는 경로도 마련했습니다. 웨이트와 venv, 코드는 호스트에
그대로 두고 서버 프로세스만 격리합니다. 호스트 경로를 bind mount(대부분 읽기전용)로
샌드박스 내부의 **동일한 절대경로**에 연결하고 기존 localhost 포트로 forward하므로,
`langgraph/tools.py` 같은 호출부는 코드를 수정하지 않고 그대로 사용합니다.

host 유닛과 샌드박스는 같은 포트를 사용하므로 동시에 실행할 수 없습니다. 샌드박스로
전환하기 전에 해당 host 유닛을 `stop`하고 `disable` 해야 하며,
`scripts/start_studio.sh --check`를 실행하면 포트를 점유한 유닛과 그 유닛을 정지시키는
명령을 알려 줍니다.

```bash
./scripts/start_studio.sh --check          # 전제조건·포트 점유 점검
./scripts/start_studio.sh --up             # 5종 전체 샌드박스 기동
./scripts/start_studio.sh --up chatterbox  # 서비스 하나만
./scripts/start_studio.sh --down           # 정리
```

Cosmos3-Nano는 아직 이 스크립트의 서비스 목록에 없습니다. 샌드박스 격리 대상이 아니므로
host에서 직접 실행합니다.

구조와 마운트 규칙, ollama 관련 특이사항은
[docs/openshell-sandbox.md](docs/openshell-sandbox.md)에 상세히 정리해 두었습니다.

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

- `inference_server/` — FLUX.1-schnell(:8501) 서버 코드와 systemd deploy 유닛입니다(Task 3.7에서 video_generator의 hunyuan_server를 복제했으며 원본은 그대로 유지합니다). Animate(:8600)와 Wan2.2-TI2V-5B(:8500)는 사용하지 않는 코드였으므로 DaolVision에서는 삭제했습니다(Task 6.5).
- `langgraph/` — :8700 게이트웨이이며 S1 파이프라인을 오케스트레이션합니다(Task 4.1에서 복제했으며 원본은 그대로 유지합니다).
- `tts/chatterbox/` — Chatterbox Multilingual V3 서버(:8504)이며, 영상 나레이션(CC0 고정 화자)과 독립 음성 복제에 함께 사용합니다.
- `t2v/cosmos3nano/` — Cosmos3-Nano T2V 서버(:8505)이며, 프롬프트 하나로 단발샷 영상을 생성합니다(Task 7.6).
- `openwebui/` — Open WebUI Function 3종과 배포 스크립트입니다(video_generator에서 이관했습니다). 채팅에서 사용하던 경로를 보존하고 있으며, 현재는 `:8700` 에이전트 함수만 가동합니다. `:8500`과 `:8600`을 사용하는 나머지 둘은 서버가 없어서 참고용으로만 둡니다.

## 제약

- 오픈셸: 완전 오프라인·자립, External calls = 0 (실측 증명)
- GB10 119GB 통합메모리, OOM 예방 (전 모델 상주 우선, 실패하면 배치 언로드)
- 모델 국적은 기록용 정보이며 경로 선택 기준이 아닙니다(2a Wan 경로 유지)
