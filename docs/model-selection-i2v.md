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

## Task 6.5 실측 (2026-08-01)

Wan2.2 T2V/I2V-폴백 제거 후 `:8700` job 파이프라인의 순수 T2V(참조 이미지
없는 씬)·I2V 폴백 경로를 LTX-Video-0.9.8-13B-distilled 단일 체크포인트로
통합, 실제 job으로 실측(`_generate_ltx_job_clip`, ComfyUI `:8188`).

- 4개 imageless(참조 이미지 없는 순수 T2V) 씬, 씬당 duration=3.0s →
  `to_ltx_len(3.0*24)=73` 프레임으로 정상 스냅(프레임 스냅 헬퍼가 실제
  ComfyUI 대상으로 정확히 동작함을 확인).
- 4씬 전체 클립 생성(제출→폴링→다운로드) **총 ~110초**, 평균 ~27s/클립 —
  단, 한 job 안에서 씬마다 순차 제출되는 구조라 엄밀한 "클립당" 값이 아니라
  4씬 배치 총합을 나눈 근사치(舊 LTX Face-ID 경로처럼 로더를 공유하는
  배치가 아님).
- 해상도 832x480("fast" 비디오 프리셋의 `WIDTH`/`HEIGHT` 전역값, Face-ID
  전용 해상도 아님).
- 다운스트림 `node_edit_concat`/`ffmpeg_concat`까지 포함한 전체 파이프라인
  검증: 최종 렌더 결과물이 12.17초 h264 mp4로 정상 생성, 씬 프롬프트와
  시각적으로 일치함을 육안 확인.
- 코히런스: 원 설계 문서의 미해결 리스크였던 "distilled 8-step 체크포인트가
  이미지 조건 없이도 코히런스를 유지하는지"는 이번 실측(3초 클립, 단순
  프롬프트)에서는 이상 없이 유지됨을 확인 — 다만 엄밀한 다중 시나리오
  품질 감사는 아니었다.
- 실측 도중 실제 버그 하나 발견·수정: ComfyUI `SaveAnimatedWEBP` 노드가
  ffmpeg 데뮤서가 파싱 못 하는 비표준 EXIF 메타데이터를 삽입해, 원본
  ComfyUI 출력 바이트를 파이프라인 ffmpeg concat 단계가 그대로 못 쓰는
  문제였음. `_generate_ltx_job_clip`에 실제 mp4로 재인코딩하는 단계를
  추가해 해결(커밋 `35d6019`/`fade045`), 이 문서 작성 시점엔 이미 해결된
  과거형 이슈.

## 2026-08-02 육안 비교 — 22B Face-ID vs 13B(비Face-ID)

같은 참조 사진(`건호군.jpg`), 같은 프롬프트, 같은 seed(1234567890)로 두
경로를 동일 조건 비교(`langgraph/tests/compare_22b_vs_13b.py`).

| | 13B(비Face-ID) | 22B Face-ID |
|---|---|---|
| 해상도 | 576x768(입력 종횡비 유지, `_ltx13b_dims`) | 768x768(고정) |
| steps | 8 | 8 |
| 길이 | 97프레임(24fps, ~4.0s) | 4.0s(24fps) |
| identity 조건 | 없음(원본 사진을 첫 프레임으로 조건부 입력만) | Face-ID LoRA + Identity Transfer(node 129) |

**결과(육안 확인): 22B가 얼굴 일관성 확실히 나음.** 13B는 Face-ID
conditioning이 없어 프레임이 진행될수록 identity가 흔들리는 반면, 22B는
동일 조건에서 원본 얼굴을 뚜렷하게 유지함 — [I2V 선택](model-selection-i2v.md)
상단의 "얼굴 일관 영상은 LTX-2.3 22B" 채택 근거를 재확인.

재현: `.venv/bin/python langgraph/tests/compare_22b_vs_13b.py` (ComfyUI
`:8188` 필요, 결과물은 `langgraph/tests/output_compare/`에 저장되며 git에는
커밋하지 않음).
