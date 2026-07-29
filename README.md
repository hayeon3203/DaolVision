# DaolVision

**오픈셸 자립형 생성 스튜디오** — 완전 오프라인·오픈소스 전용 환경에서 도는 생성 AI 스튜디오.

기존 anim 영상 에이전트(LangGraph T2I→I2V)를 LocalAI 포크 UI 위에 얹고, **전 모델을 비중국/NVIDIA 오픈소스**로 구성한다. 국적·오프라인·GB10 메모리를 대시보드로 시각 증명하는 것이 핵심 차별점.

## 시나리오

- **S1 — 우주비행사의 여정**: 텍스트 스토리 → 씬분할 → 캐릭터 일관 I2V(4씬) → TTS 나레이션 → mp4
- **S2 — 내 얼굴 → 그림체 변환**: 얼굴사진 → 애니/유화초상화/프로필/우주비행사 (Flux Kontext)
- **연결**: S2 우주비행사 캐릭터 → S1 Face-ID 참조로

## 스택 (전부 비중국/NVIDIA 오픈소스)

| 역할 | 모델 | 국적 |
|---|---|---|
| 씬분할 | Nemotron-4B | 🇺🇸 NVIDIA |
| 캡션 | Nemotron-VL-8B | 🇺🇸 NVIDIA |
| T2I | Flux.1-schnell | 🇩🇪 |
| I2I | Flux.1 Kontext | 🇩🇪 |
| I2V | LTX-Video distilled + Face-ID | 🇮🇱 |
| I2V 벤치 | Cosmos-Predict2-2B | 🇺🇸 NVIDIA |
| TTS | Kokoro | 🇺🇸 |

## 기획 문서

- [docs/PRD.md](docs/PRD.md) — 제품 요구사항 (product contract)
- [docs/UserFlow.md](docs/UserFlow.md) — 사용자 플로우
- [docs/Architecture.md](docs/Architecture.md) — 아키텍처
- [Plans.md](Plans.md) — 실행 task 원장 (7일 스프린트)

## 제약

- 오픈셸: 완전 오프라인·자립, External calls = 0 (실측 증명)
- GB10 119GB 통합메모리, OOM 예방 (전 모델 상주 우선 → 실패시 배치 언로드)
- 비중국 우선 + 품질 예외 허용
