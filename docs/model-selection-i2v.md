# I2V 모델 선택과 LangGraph 속도 제약

## 현재 구성과 문제

얼굴 일관성을 위해 다음 조합을 사용한다.

- LTX-2.3 22B GGUF Q6_K
- Distill LoRA
- LTX Best Face-ID LoRA와 BFS Nodes
- Gemma 3 12B FP8 encoder 및 LTX projection

품질은 통과했지만 5초 영상에 약 6분이 걸린다. 별도 프로파일에서는 모델 로드
약 190초, 8-step sampling 약 221초, 전체 523초가 측정됐다. 6 step은 twin
아티팩트와 얼굴 정합성 저하가 발생했고 Q5는 확실한 가속 없이 얼굴 품질이
낮아져 채택하지 않았다.

## 비중국 경량 모델 선택이 어려운 이유

1. 빠른 오픈 I2V 모델 다수가 중국 원산이라 프로젝트 정책에서 제외된다.
2. 비중국 2B급 모델은 빨라도 대부분 첫 프레임 I2V일 뿐, Face-ID 전용
   conditioning이나 얼굴 유사도 학습이 없다.
3. 현재 Best Face-ID는 LTX-2 22B 전용이라 경량 LTX-Video 2B에 이식할 수 없다.
4. step·양자화를 더 줄이면 속도보다 먼저 인물 중복과 얼굴 드리프트가 발생한다.
5. LangGraph에서는 T2I→I2V 모델 전환, encoder·VAE 로드, 여러 씬 반복 비용까지
   포함되므로 단일 모델 벤치마크보다 실제 시간이 길다.
6. GB10은 ARM64·통합 메모리 환경이라 공개된 x86/Hopper 벤치마크와 최적화
   커널 성능을 그대로 기대할 수 없다.

## 검토 후보

| 후보 | 장점 | 한계 | 판단 |
|---|---|---|---|
| LTX-Video 2B Distilled | 비중국, 8 step 이하, 2분 이내 가능성 | Best Face-ID 호환 불가 | 1순위 속도 스파이크 |
| NVIDIA Cosmos Predict2 2B | 비중국, 단일 이미지 Video2World | 얼굴 ID 전용 모델이 아님 | 2순위 비교 |
| Stable Video Diffusion XT | 경량·빠름 | 짧은 길이, 제어와 얼굴 유지가 약함 | 제외 |
| 현재 LTX-2.3 22B Face-ID | 얼굴 일관성이 가장 좋음 | 목표 시간 초과 | 고품질 기준선 유지 |

따라서 현재로서는 **5초·2분 이내·비중국·강한 얼굴 일관성**을 모두 검증한
대체 모델이 없다. LTX-Video 2B를 같은 장면별 얼굴 앵커로 먼저 실측하되,
통과하지 못하면 일반 장면은 2B, 얼굴 중요 장면은 기존 22B로 나누는 방식을
검토한다.

채택 게이트는 warm 생성 120초 이내, 5초 분량, 정면·측면·가림 장면의 얼굴
일관성, CUDA OOM 없음이다. cold load 시간은 별도로 기록하고 여러 씬을 한
세션에서 처리해 LangGraph의 반복 로드를 피한다.

관련 기록: [Face-ID 호환성](spikes/3.1-ltx-faceid-compat.md),
[병목 프로파일](spikes/3.3-ltx-bottleneck-profile.md),
[경량화 스윕](spikes/3.4-ltx-lightweight-sweep.md),
[단발샷 실측](spikes/3.8-ltx13b-oneshot-i2v.md)

## 2026-07-31 갱신 — LTX-13B-distilled 단발샷 채택

1순위 후보였던 LTX-Video distilled 계열을 13B-distilled(fp8, 15.7GB)로
실측: **8-step 30.22초, 채택 게이트(warm 120초 이내)를 여유 있게 통과**.
`Lightricks/LTX-Video`의 `ltxv-13b-0.9.8-distilled-fp8.safetensors` +
`comfyanonymous/flux_text_encoders`의 `t5xxl_fp8_e4m3fn_scaled.safetensors`
조합, Face-ID LoRA 없이 원본 사진 자체를 첫 프레임으로 조건부 입력 — 단일
짧은 클립 내에서는 identity가 자연히 유지된다는 가설 확인(눈판정 통과,
twin/드리프트 없음).

**Cosmos-Predict2-2B는 I2V identity 용도로 최종 제외** — 공식 모델 카드에
identity 보존 관련 언급 없고 "입력을 정확히 안 따라갈 수 있음" 명시.
Cosmos3-Super-Image2Video(64B)는 8×H200급 멀티GPU 전제라 GB10 1노드로는
애초에 불가. Cosmos는 identity 불필요한 순수 T2V 용도로 재검토 예정(별도
카테고리, `model-selection-t2v.md` 신설 시 정리 — 아직 미착수).

**남은 검증**: 종횡비 버그(테스트 스크립트가 세로 사진에 가로 해상도
하드코딩해 얼굴 상단 크롭됨, 모델 결함 아님) 수정 후 재검증, 정면 외
측면·가림 구도 채택 게이트 항목 미완료. 상세는
[3.8 스파이크](spikes/3.8-ltx13b-oneshot-i2v.md) 참고.
