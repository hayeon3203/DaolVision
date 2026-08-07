# DaolVision

**오픈셸 자립형 생성 스튜디오** — 완전 오프라인·오픈소스 전용 환경에서 도는 생성 AI 스튜디오.

기존 anim 영상 에이전트(LangGraph T2I→I2V)를 LocalAI 포크 UI 위에 얹고, **전 모델을 비중국/NVIDIA 오픈소스**로 구성한다. 국적·오프라인·GB10 메모리를 대시보드로 시각 증명하는 것이 핵심 차별점.

## 시나리오

- **S1 — 우주비행사의 여정**: 텍스트 스토리 → 씬분할 → 캐릭터 일관 I2V(4씬) → Chatterbox CC0 한국어 나레이션 → mp4
- **S2 — 내 얼굴 → 그림체 변환**: 얼굴사진 → 애니/유화초상화/프로필/우주비행사 (Flux Kontext)
- **독립 TTS — 내 목소리**: 참조 WAV → Chatterbox Multilingual V3 한국어 음성 복제
- **독립 T2V — 프롬프트만으로 영상**: 사진 입력 없이 텍스트 프롬프트 → Cosmos3-Nano 단발샷 영상(identity 불필요 용도)
- **연결**: S2 우주비행사 캐릭터 → S1 Face-ID 참조로

## 스택 (전부 비중국/NVIDIA 오픈소스)

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

## 제약

- 오픈셸: 완전 오프라인·자립, External calls = 0 (실측 증명)
- GB10 119GB 통합메모리, OOM 예방 (전 모델 상주 우선 → 실패시 배치 언로드)
- 비중국 우선 + 품질 예외 허용
