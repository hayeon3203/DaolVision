# 모델 선택 개요

작성일: 2026-07-31

DaolVision은 NVIDIA GB10(119GiB 통합 메모리) 한 대에서 LangGraph 파이프라인을
실행한다. 모델은 **비중국 원산**, 로컬 실행, 라이선스, 실제 품질과 생성 시간을
함께 보고 선택한다. 체크포인트가 작아도 activation·CUDA workspace·모델 전환
비용 때문에 전체 파이프라인이 빨라진다고 가정하지 않는다.

## 현재 선택 현황

| 역할 | 현재 선택 | 상태 |
|---|---|---|
| 씬 분할 LLM | NVIDIA Nemotron 3 Nano 4B GGUF Q4_K_M | 잠정 유지 |
| 참조 이미지 캡션 VLM | 미확정 | 재선정 중 |
| TTS | Chatterbox Multilingual V3 | 채택 |
| T2I 앵커 | FLUX.1-schnell | 채택 |
| I2I 얼굴 변환 | FLUX.1 Kontext [dev] | 배선·1차 실측 완료(Task 6.1), 상업 라이선스 미확정 |
| I2V 얼굴 일관 영상 | LTX-2.3 22B Q6_K + Distill + Best Face-ID | 품질 통과, 속도 개선 필요 |
| I2V 단발샷(비Face-ID) | LTX-Video-0.9.8-13B-distilled | 채택, 30초/5초분량 실측. 해상도 종횡비 버그 수정 후 재검증 필요 |

역할별 근거와 제약은 다음 문서에 분리한다.

- [LLM·VLM 선택](model-selection-llm.md)
- [TTS 선택](model-selection-tts.md)
- [T2I 선택](model-selection-t2i.md)
- [I2I 선택](model-selection-i2i.md)
- [I2V 선택과 LangGraph 속도 제약](model-selection-i2v.md)

## 공통 운영 원칙

- UI는 개별 모델 서버 대신 `:8700` LangGraph gateway만 호출한다.
- 경량 LLM은 가능하면 상주시키되 FLUX·LTX 같은 GPU-heavy 작업은 직렬화한다.
- 모델 로드와 씬 생성을 매번 반복하지 않고 같은 작업의 여러 씬을 묶어 처리한다.
- 국적은 배포자뿐 아니라 원 가중치와 핵심 encoder의 학습 주체까지 확인한다.
- 최종 채택은 모델 크기가 아니라 GB10의 cold/warm 시간, peak 메모리, 실제
  한국어·얼굴 일관성 품질로 결정한다.

상세 실측 기록은 [`docs/spikes`](spikes/)에 보존한다.
