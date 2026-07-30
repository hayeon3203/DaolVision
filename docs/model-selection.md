# DaolVision 모델 선택 기준과 검증 현황

작성일: 2026-07-30
상태: LLM/VLM 재선정 중. T2I와 I2V 구성은 별도 스파이크 결과를 따름.

이 문서는 모델을 확정했다고 선언하는 목록이 아니다. DaolVision이 한 장비에서
여러 추론 서비스를 운영하면서 S1 영상 파이프라인을 안정적으로 실행하기 위해,
어떤 조건으로 모델을 비교했고 무엇을 확인했으며 다음에 무엇을 검증할지 기록한다.

## 1. 먼저 지켜야 할 운영 조건

### 하드웨어

- NVIDIA GB10 Grace Blackwell, 119GiB unified memory
- ARM64 CPU 20코어
- 현재 검증 환경: Torch 2.12.1+cu130, Transformers 5.12.1. 모델별 전용
  Transformers 환경은 별도 venv로 격리한다.
- CPU와 GPU가 같은 메모리를 공유하므로 `VRAM`과 시스템 RAM을 독립된 예산처럼
  계산하면 안 된다.
- 생성 중 순간 peak가 체크포인트 크기나 모델 로드 직후 사용량보다 훨씬 크다.
  기존 동시 상주 테스트에서는 FLUX 생성 순간 전체 사용량이 118/119GiB까지
  상승하고 swap 15GiB가 소진되어 다른 GPU 서비스가 종료됐다.

따라서 DaolVision은 여러 모델과 서비스를 동시에 띄워야 하고 FLUX와 LTX 같은
무거운 비전 모델도 실행해야 하므로, **경량 모델과 FP8·NVFP4·INT4·GGUF 같은
양자화 체크포인트를 최우선**으로 선택한다. BF16은 호환성 확인용이 아니면
기본 배포 후보로 삼지 않는다.

품질과 호환성이 같은 후보 사이에서는 NVIDIA 자체 모델을 우선하고, 그다음
비중국 모델, 마지막으로 NVIDIA가 최적화했지만 원 가중치는 중국 계열인 모델을
검토한다. 배포 주체와 원 학습 주체를 따로 기록한다. FlashAttention 4 같은
Blackwell 최적화는 품질 회귀와 실제 peak를 확인한 뒤 켠다. 얼굴 유지 I2V와
테마별 I2I는 검증된 Hugging Face·ComfyUI workflow를 재사용하는 방향을 우선한다.

### 가능한 실행 프레임워크

| 프레임워크 | 주 용도 | 이 프로젝트에서의 원칙 |
|---|---|---|
| vLLM | 표준 Causal LLM 및 지원되는 멀티모달 LLM의 상시 API 서빙 | OpenAI 호환 API가 필요하고 아키텍처가 네이티브 지원될 때 우선 검토 |
| SGLang | 지원되는 LLM/VLM의 고성능 서빙 대안 | vLLM보다 호환성이나 메모리 결과가 명확히 좋을 때 비교 |
| Transformers | 실험적·커스텀 아키텍처 검증 | vLLM/SGLang 미지원 모델의 격리 서버에만 사용. 버전 고정 필수 |
| Ollama/llama.cpp | GGUF INT4 계열 경량 LLM/VLM | 현재처럼 작은 모델의 품질과 메모리가 더 좋으면 유지 |
| ComfyUI | FLUX, LTX, VAE, LoRA 및 학습된 conditioning graph | 확산 모델과 LTX 텍스트 인코더는 이 경로를 유지 |

프레임워크를 하나로 통일하는 것 자체가 목표는 아니다. 모델이 요구하는 출력
형식과 학습된 연결을 보존하면서, 상주 메모리와 초기화 시간을 줄이는 조합이
목표다.

### NVIDIA 생태계 모델 도입이 어려운 이유

GB10은 NVIDIA 모델을 실행하기 좋은 Blackwell 장비지만, NVIDIA가 공개한 모델을
고르면 바로 경량 로컬 파이프라인이 완성되는 것은 아니다. 이번 검토에서는
다음과 같은 간극이 확인됐다.

1. **distilled 경량 오픈소스 체크포인트가 부족하다.** 공개 가중치는 BF16이나
   FP8 중심인 경우가 많고, 3~4B급 VLM 또는 품질 검증된 INT4·NVFP4 배포본은
   선택지가 좁다. Distillation이 제공되더라도 생성 step이나 지연만 줄이고 전체
   가중치와 생성 peak는 크게 줄이지 않는 경우가 있다.
2. **양자화 형식만으로 운영 메모리가 해결되지 않는다.** Nemotron Nano 12B VL
   NVFP4-QAD도 checkpoint가 9.89GiB여서 vision activation, KV/cache, CUDA
   workspace를 더하면 예상 peak가 12~14GiB다. 양자화 파일 크기와 실제 상주
   peak를 따로 측정해야 한다.
3. **GB10에서 실행 가능한 것과 서빙 엔진이 지원하는 것은 다르다.** GB10의
   CUDA와 연산 정밀도가 모델을 수용하더라도 vLLM·SGLang이 해당 VLM
   architecture, vision tower, custom remote code를 지원하지 않을 수 있다.
   Diffusion VLM 8B는 Transformers 버전을 고정하면 실행됐지만 vLLM에는
   `NemotronLabsDiffusionVLMModel` 구현이 없었다. 반면 Nemotron Nano 12B v2
   VL의 C-RADIO 경로는 현재 vLLM 0.26.0에서 네이티브 인식됐다. 따라서
   “NVIDIA VLM 전체가 미지원”이 아니라 **모델 revision과 엔진 버전별 확인**이
   필요하다.
4. **ARM64와 최신 CUDA 조합의 패키지 격차가 있다.** x86 서버를 우선 지원하는
   wheel, custom CUDA op, FlashAttention 또는 ComfyUI node는 GB10 ARM64에서
   그대로 설치되지 않을 수 있다. 한 모델을 위해 Transformers를 내리면 다른
   서비스와 충돌하므로 모델별 venv와 서버 격리가 필요하다.
5. **NVIDIA 최적화와 현재 생성 workflow 사이에 연결 간극이 있다.** FLUX와
   LTX의 ComfyUI graph, Gemma projection, BFS Nodes, Face-ID LoRA는 각자
   학습된 tensor 형식과 loader를 요구한다. NVIDIA VLM을 선택해도 이 구성요소를
   대체할 수 없으며, vLLM API로 통일하려면 custom node와 conditioning adapter
   개발 또는 재학습이 필요하다.
6. **비중국·NVIDIA 우선 조건이 후보를 더 줄인다.** NVIDIA가 배포하거나
   양자화한 모델이라도 원 가중치와 text encoder가 Qwen/Wan 계열일 수 있다.
   배포 조직, 원 학습 주체, 하위 encoder의 원산을 각각 확인해야 한다.

따라서 NVIDIA 생태계 사용 여부는 브랜드나 모델 카드만으로 결정하지 않는다.
`GB10/ARM64 설치 → 엔진 기동 → 양자화 runtime peak → 실제 S1 품질 →
기존 ComfyUI·LangGraph 연결 비용`을 하나의 채택 게이트로 다룬다.

### 코드 구조상 유지할 아키텍처

```text
UI
 └─ :8700 FastAPI/LangGraph gateway
     ├─ LLM endpoint      씬 분할·프롬프트·승인 의도
     ├─ VLM endpoint      사용자 참조 이미지 캡션
     ├─ :8501 FLUX        S1 T2I 앵커
     ├─ :8188 ComfyUI     LTX I2V + Gemma encoder + projection + Face-ID
     └─ TTS
```

다음 규칙은 모델을 바꾸더라도 유지한다.

1. UI는 개별 모델 서버가 아니라 `:8700`만 호출한다.
2. LangGraph의 `call_llm`과 `caption_image`는 역할을 분리한다. 같은 모델로
   합칠 수는 있지만 모델명 하나를 바꾸는 방식이 아니라 backend adapter를
   통해 Ollama/OpenAI 호환 API 차이를 흡수한다.
3. 서비스 프로세스는 가능하면 계속 실행하고, **작은 양자 LLM/VLM은 상주**시켜
   요청마다 모델을 올리고 내리는 지연을 없앤다.
4. 모델 상주와 작업 동시 실행은 분리해서 생각한다. FLUX와 LTX 서비스를
   유지하더라도 두 확산 작업의 sampling peak가 겹치지 않도록 gateway에서
   GPU-heavy queue/semaphore로 직렬화한다.
5. unload/reload는 정상 실행 절차가 아니라 메모리 압박 시 최후의 fallback이다.
   채택 전 실제 동시 상주 peak를 측정하여 정상 경로에서 eviction이 필요 없는
   조합을 선정한다.
6. LTX의 Gemma encoder, LTX projection, transformer, Face-ID LoRA는 하나의
   학습된 conditioning 스택이다. 독립적인 일반 LLM처럼 교체하지 않는다.
7. 모델 선택은 체크포인트 크기가 아니라 `서비스 상주 + 실제 생성 peak`로
   결정한다. 품질 테스트도 실제 S1 프롬프트와 JSON 파서로 반복한다.

## 2. 역할별 현재 판단

| 역할 | 현재 후보/구성 | 상태 | 이유 |
|---|---|---|---|
| 씬 분할 LLM | NVIDIA Nemotron 3 Nano 4B GGUF Q4_K_M | 잠정 유지 | 기존 Ollama 경로에서 S1 JSON 파싱 3/3 성공. 약 2.84GB 파일, 예상 runtime 4~6GB |
| 참조 이미지 캡션 VLM | 미확정 | 재선정 | 기존 문서의 `gemma4:latest` 확정 표기를 철회. 8~10GB급 양자 모델을 우선 탐색 |
| T2I 앵커 | FLUX.1-schnell | 유지 | `:8501`, 1024² 4-step peak 33.8GB 실측. S1의 장면별 정지 앵커 생성 |
| I2V | LTX-2.3 22B GGUF Q6_K + distill LoRA + BFS Nodes + Face-ID LoRA | 호환 구성 확인, peak 실측 필요 | Face-ID LoRA가 LTX-Video 13B가 아니라 LTX-2.3용임을 확인 |
| LTX conditioning | Gemma 3 12B FP8 + LTX projection BF16 | 유지 필요 | LTX와 Face-ID가 이 embedding/projection 공간을 전제로 학습됨 |
| I2I | FLUX.1 Kontext | 검증 대기 | S2의 얼굴 스타일 변환용이며 FLUX.1-schnell과 역할이 다름 |
| TTS | Kokoro 82M | 유지 | 작고 CPU 실행도 가능해 GPU 상주 예산에 미치는 영향이 작음 |

`wan-animate`는 사용하지 않으므로 서비스와 포트 `:8600`을 내렸다.
FLUX 서비스는 S1 T2I 앵커에 필요하므로 유지한다.

## 3. LLM/VLM 스파이크 결과

### 3.1 Nemotron Labs Diffusion VLM 8B

`nvidia/Nemotron-Labs-Diffusion-VLM-8B` 하나로 텍스트 씬 분할과 이미지 캡션을
통합할 수 있는지 확인했다.

- Transformers 4.57.1에서 이미지 캡션은 2.44초, 의미 품질 통과
- S1 텍스트 씬 분할은 배열 시작 문자가 빠지고 모든 장면이 원문 전체를
  반복하여 JSON/의미 분리 실패
- vLLM 0.26.0은 `NemotronLabsDiffusionVLMModel` 아키텍처를 지원하지 않음
- Transformers 5.x와 모델 원격 코드의 import도 충돌
- BF16 peak reserved 17.23GiB

따라서 캡션 가능성은 있지만, 현재 상태에서는 단일 LLM/VLM이나 상시 경량
서비스로 채택하지 않는다. 상세 결과는
[Spike 2.2.1](spikes/2.2.1-diffusion-vlm-unification.md)에 있다.

### 3.2 Nemotron 3 Nano 4B의 vLLM 전환

BF16 모델은 vLLM 0.26.0에서 정상 기동했지만 실제 S1 테스트에서는 다음 문제가
있었다.

- thinking 사용 시 reasoning이 출력 토큰을 소비해 JSON이 잘림
- thinking 해제 시 4개 지시에도 2개 장면만 반환
- JSON Schema 강제 시 공백 생성 반복

기존 Ollama Q4는 같은 역할에서 JSON 파싱 3/3을 통과했다. 프레임워크 통일보다
현재의 양자화·품질·상주 메모리 이점이 크므로 LLM은 Ollama Q4를 잠정 유지한다.

### 3.3 NVIDIA Nemotron Nano 12B v2 VL

BF16은 vLLM이 `NemotronH_Nano_VL_V2`로 정상 인식하고 24.57GiB weight
load까지 성공했으나, 양자 모델 우선 방침에 따라 inference/profile 전에
중단하고 캐시도 삭제했다.

| 양자화 | 체크포인트 크기 | 예상 runtime peak | 판정 |
|---|---:|---:|---|
| FP8 | 14.35GiB | 16~20GiB | 8~10GB 목표 초과 |
| NVFP4-QAD | 9.89GiB | 12~14GiB | 가장 가깝지만 목표 초과 예상 |

NVFP4는 기능 후보로 남길 수 있지만 작은 LLM/VLM을 계속 상주시키려는 운영
조건에는 여전히 무겁다. 채택하려면 `--enforce-eager`, context 4096, 이미지
1장 제한으로 실제 peak와 S1 캡션 품질을 먼저 측정해야 한다. 상세 산정은
[Spike 2.2.3](spikes/2.2.3-nemotron-12b-vl-quant-sizing.md)에 있다.

## 4. Gemma를 vLLM으로 띄울 수 있는가

결론은 **일반 Gemma 생성 모델은 vLLM으로 서빙할 수 있지만, 현재 LTX용
Gemma를 vLLM API 서버로 옮기는 것은 실익이 없고 drop-in도 아니다.**

현재 로컬 LTX 구성은 다음 파일을 ComfyUI graph 안에서 직접 사용한다.

| 구성 | 실제 파일 크기 |
|---|---:|
| Gemma 3 12B FP8 encoder | 12.30GiB |
| LTX text projection BF16 | 2.15GiB |
| 합계 weights | 14.45GiB |
| 예상 실행 peak | 15.5~18GiB |

LTX는 Gemma의 최종 문장만 받는 것이 아니라 토큰별 다중 layer hidden state를
가져와 `3840 × 49` 입력의 전용 projection으로 video/audio conditioning을
만든다. BFS identity 경로와 Face-ID LoRA도 같은 embedding 공간을 전제로 한다.

반면 일반적인 vLLM OpenAI API는 생성 텍스트나 표준 embedding을 반환한다.
ComfyUI의 `CLIP`/conditioning 객체와 LTX가 요구하는 모든 hidden state tensor를
원격 전달하지 않는다. 이를 vLLM 서비스로 분리하려면 다음이 필요하다.

1. LTX 전용 hidden-state 반환 API와 serializer 구현
2. ComfyUI custom node 및 원격 tensor 전송 구현
3. projection 실행 위치와 캐시 수명 관리
4. 기존 encoder와 수치·품질 동등성 및 Face-ID 회귀 테스트

더구나 vLLM 프로세스에 14GB 이상을 상주시킨 뒤 ComfyUI가 같은 encoder를 다시
로드하면 가중치가 중복된다. ComfyUI 로더를 완전히 대체해도 네트워크/직렬화
비용과 별도 KV/workspace가 생긴다. 따라서 **Gemma는 vLLM 서비스로 만들지 않고
LTX 전용 ComfyUI conditioning 구성요소로 유지**한다.

로딩 지연을 줄이는 해법은 Gemma를 일반 LLM 서버로 분리하는 것이 아니라,
LTX 작업이 연속되는 동안 ComfyUI model cache에 Gemma와 projection을 유지하고
S1의 4개 장면을 한 batch/session으로 처리하는 것이다. 이 상태에서 경량
LLM/VLM과 FLUX/LTX 서비스는 계속 살아 있되, FLUX와 LTX sampling만 겹치지
않게 한다.

## 5. 메모리 운영 방향

이전의 “매 단계마다 대형 모델 unload → 다음 모델 load” 방식은 OOM은 피하지만
초기화 지연이 너무 크다. 앞으로는 아래 순서로 설계한다.

1. gateway, 경량 Q4 LLM, 경량 양자 VLM, TTS는 상시 상주
2. FLUX와 ComfyUI 서비스도 상시 실행
3. ComfyUI는 같은 작업의 4개 LTX 장면 동안 Gemma/LTX graph cache 유지
4. GPU-heavy generation은 전역 semaphore로 직렬 실행
5. 실제 전체 peak가 안전 한도를 넘을 때만 가장 큰 idle 모델을 eviction

119GiB 전체를 모델에 할당하지 않는다. OS, 페이지 캐시, tensor 복사, CUDA
workspace와 순간 activation을 위한 안전 여유를 남겨야 한다. 최종 상주 조합은
idle 사용량과 FLUX/LTX 각각의 생성 peak를 같은 조건에서 측정한 뒤 확정한다.

## 6. 후보 카탈로그

아래 표는 후보를 버리지 않고 후속 비교를 이어가기 위한 카탈로그다. 2026-07-30
웹 리서치와 기존 스파이크를 바탕으로 하며, `미확인` 또는 커뮤니티 수치는 GB10
실측값이 아니다. 과거 문서의 `확정` 표현은 현재 재선정 상태에 맞게 제거했다.

### I2I 후보

| 모델 | 국적 | 파라미터 | 디스크/양자화 | Load VRAM | Peak VRAM | 비고 |
|---|---|---|---|---|---|---|
| **FLUX.1 Kontext [dev]** | 🇩🇪 Black Forest Labs | 12B | BF16 23.8GB / 커뮤니티 FP8 약 11.9GB / GGUF Q4 약 7GB | 약 24GB(BF16) / 12GB(FP8) / 7GB(Q4) | 약 31.5GB(BF16, offload 없음, RTX 5090) / 20GB(FP8+offload) | S2 현재 후보. 비상업 라이선스, ComfyUI·Diffusers·GGUF 지원 |

### I2V 및 얼굴 일관성 후보

| 모델 | 국적 | 파라미터 | 디스크/양자화 | Load VRAM | Peak VRAM | 비고 |
|---|---|---|---|---|---|---|
| LTX-Video distilled 구버전 | 🇮🇱 Lightricks | 13B, 경량 2B 변형 | BF16 28.6GB / FP8 15.7GB | 최소 6GB(offload+512², clean-load 미확인) | 6~32GB 커뮤니티 보고 | Face-ID LoRA가 LTX-2.3용이라 현재 구성에서는 제외 |
| LTX Best-Face-ID LoRA | 커뮤니티 Alissonerdx | 애드온 | LoRA 2.47GB + ArcFace projector 69.3MB | — | — | LTX-2.3 22B 및 `ComfyUI-BFSNodes` 필요 |
| LTX-2.3-22B-dev GGUF Q6_K | 🇮🇱 Lightricks 원본 / unsloth 양자화 | 22B | GGUF Q6_K 17.8GB, distill LoRA 2.74GB | 실측 예정 | 실측 예정 | 현재 Face-ID 호환 구성. 공식 BF16 46.1GB보다 경량 |
| NVIDIA Cosmos-Predict2-2B-Video2World | 🇺🇸 NVIDIA | 2B | BF16 `.pt` 3.91GB | Load/peak 분리 안 됨 | 32.54GB 공식 수치, 720p/16fps | 후속 Cosmos-Predict2.5 존재 |
| Wan2.1-T2V-14B + Stand-In | 🇨🇳 Alibaba / WeChatCV | 14B + 153M | 약 57GB + VAE 508MB + T5 11.4GB | 40~48GB, 480p FP8+offload | 65~80GB, 720p | 현재 사용하지 않음. 기존 실제 배선은 Wan2.2-Animate였으며 서비스 종료 |
| LTX-2 / LTX-2.3 공식 | 🇮🇱 Lightricks | 19B / 22B | FP8 distilled 27GB/29.5GB, LTX-2 BF16 43GB | FP8 distilled 16GB 구동 보고 | 약 24GB가 쾌적하다는 커뮤니티 보고 | 오디오 동기화, Face-ID LoRA 대상 |
| Stable Video Diffusion img2vid | 🇬🇧/🇺🇸 Stability AI | 약 2B | 미확인 | 미확인 | 미확인 | 호스팅 API 종료 후 사실상 레거시 |
| NVIDIA Cosmos 의료 특화 계열 | 🇺🇸 NVIDIA | — | — | — | — | 수술 로봇 등 특화 목적이라 일반 애니메이션에는 부적합 |

### T2I 후보

![T2I GenEval vs Inference Time vs Peak GPU Memory](img/t2i-genEval-vs-inference-vs-peak-vram.webp)

다음 차트 값은 사용자 제공 자료에서 옮긴 것으로 원 논문과 실행 조건을 아직
검증하지 않았다. 서로 다른 출처의 load/peak 수치와 직접 비교하지 않는다.

| 모델 | Peak GPU Memory(차트) | GenEval | 비고 |
|---|---:|---:|---|
| Mage-Flow-Turbo | 17.68GB | 0.88 | 차트상 가장 가볍고 빠름 |
| Mage-Flow | 18.10GB | 0.90 | 차트상 최고 품질. 가중치·라이선스·ComfyUI 지원 확인 필요 |
| Mage-Flow-Base | 18.10GB | 0.79 | 검증 필요 |
| FLUX.2-Klein-4B | 19.76GB | 0.83 | PRD 범위 밖 후보 |
| FLUX.2-Klein-Base-4B | 19.76GB | 0.78 | PRD 범위 밖 후보 |
| Z-Image-Turbo | 24.46GB | 0.82 | 검증 필요 |
| Z-Image-Base | 25.28GB | 0.84 | 검증 필요 |
| SD3.5-Large | 30.88GB | 0.70 | 미사용 후보 |
| LongCat-Image | 32.12GB | 0.87 | 검증 필요 |
| FLUX.2-Klein-9B | 37.36GB | 0.86 | PRD 범위 밖 후보 |
| FLUX.2-Klein-Base-9B | 37.36GB | 0.83 | PRD 범위 밖 후보 |
| FLUX.1-dev / FLUX.1-Krea | 36.06GB | 0.65 / 0.72 | 현재 FLUX.1-schnell과 다른 모델 |
| Lens 계열 | 51.58GB | 0.70~0.85 | 무거움 |
| Qwen-Image | 58.80GB | 0.87 | 계열상 중국 원산, 메모리도 큼 |
| HiDream-I1-Full | 65.47GB | 0.83 | 차트상 가장 무거움 |

추가 조사 후보:

| 모델 | 국적/원산 | 파라미터 | 양자화·메모리 | 비고 |
|---|---|---:|---|---|
| FLUX.1-dev | 🇩🇪 BFL | 12B | BF16 23.8GB / FP8 약 11.9GB / GGUF Q4 6~8GB | 비상업 라이선스 |
| Krea-2-Turbo | 🇺🇸 Krea AI | 12~13B, 출처 불일치 | BF16 약 24.5GB / FP8·NVFP4 약 10~12GB / INT4 약 7GB | gated, Krea 2 Community License |
| Ideogram 4 FP8 | 🇨🇦 Ideogram, 텍스트 인코더는 🇨🇳 Qwen3-VL | DiT 9.3B + encoder 8B | DiT FP8 9.29GB, 전체 미확인 | 비중국 정책상 텍스트 인코더 원산 주의 |
| NVIDIA Qwen-Image-Flash | 원본 🇨🇳 Alibaba/Qwen | 파이프라인 약 28.85B | BF16 약 57.7GB | GB10 기존 실측 OOM. 적은 step은 peak memory를 줄이지 않음 |

### LLM·멀티모달 후보

| 모델 | 실제 원산 | 파라미터 | 디스크/양자화 | Load/Peak | 비고 |
|---|---|---|---|---|---|
| Nemotron 3 Nano 4B GGUF | 🇺🇸 NVIDIA | 3.97B | Q4_K_M 2.84GB | 현재 약 4~6GB 예상 | 씬 분할 잠정 유지 |
| Nemotron Labs Diffusion VLM 8B | 🇺🇸 NVIDIA | 8B | BF16 17.9GB | peak reserved 17.23GiB 실측 | 캡션 통과, 씬 분할·vLLM 실패 |
| Nemotron Nano 12B v2 VL FP8 | 🇺🇸 NVIDIA | 약 13B | 14.35GiB | 예상 16~20GiB | 8~10GB 목표 초과 |
| Nemotron Nano 12B v2 VL NVFP4-QAD | 🇺🇸 NVIDIA | 약 13B | 9.89GiB | 예상 12~14GiB | 작은 VLM 실패 시 후순위 실측 |
| Nemotron-3-Nano-30B-A3B NVFP4 | 🇺🇸 NVIDIA | 30B total / 활성 약 3.5B | 19.4GB | peak 보고 편차 큼 | 베이스는 텍스트 전용 |
| Qwen3.6-35B-A3B-NVFP4 | 🇨🇳 Alibaba, NVIDIA 양자화 | 35B / 활성 3B | 23.5GB | load 약 22GB 커뮤니티 보고 | 원산 정책과 메모리 목표 불일치 |
| Gemma 4 26B-A4B NVFP4 | 🇺🇸 Google DeepMind | 25.2B / 활성 3.8B | 18.8GB | load 16.5GB 보고 | 현재 목표보다 무거움 |
| DiffusionGemma 26B-A4B NVFP4 | 🇺🇸 Google DeepMind | 26B급 MoE | 18.9GB | 약 18GB 보고 | 서버 통합 성숙도 확인 필요 |
| `gemma4:latest` / `gemma4:e4b` | 🇺🇸 Google | raw 8B, effective 약 4B 표기 | QAT 9.6GB | 과거 nvidia-smi 7.3GB | 과거 캡션 후보. 확정 철회 후 재비교 |
| Llama 비전 계열 | 🇺🇸 Meta | 모델별 상이 | 미확인 | 미확인 | Ollama·vLLM 지원과 소형 양자판 재조사 가능 |

### TTS 후보

| 모델 | 국적 | 파라미터 | 디스크/양자화 | 메모리 | 비고 |
|---|---|---:|---|---|---|
| Kokoro-82M | 🇺🇸 hexgrad | 82M | FP32/BF16 약 326MB, JS Q4 86MB | 1~2GB 이하 보고 | 현재 선택, CPU 실행 가능 |
| Zonos-v0.1 | 🇺🇸 Zyphra | 1.6B | BF16 3.25GB | 공식 최소 6GB+ | Linux 중심 |
| CosyVoice2-0.5B | 🇨🇳 FunAudioLLM/Alibaba | 0.5B | Q4 1GB 미만 보고 | FP 약 4GB 권장 | 원산 정책 불일치 |
| Metis | 🇨🇳 CUHK-Shenzhen | 학습 파라미터 20M 미만 | 전용 checkpoint 미공개 | 미확인 | 연구 도구 성격이 강함 |

카탈로그를 해석할 때는 모델 배포자가 NVIDIA인지뿐 아니라 원 가중치의 학습
주체도 분리해 기록한다. 특히 Qwen 계열, Ideogram의 Qwen text encoder,
CosyVoice 계열은 비중국 정책 검토 대상이다.

## 7. 다음 테스트

LLM과 캡션 모델은 아직 최종 확정하지 않는다. 다음 순서로 결정한다.

1. 현재 `wan-animate` 제거 후의 clean baseline과 상주 서비스 메모리 재측정
2. 3~4B급 INT4/GGUF 멀티모달 후보를 우선 조사
3. 후보별 실제 참조 이미지 캡션 정확도·한국어 지시 준수·지연을 3회 측정
4. 경량 LLM + VLM + FLUX + ComfyUI/LTX cache 동시 상주 상태에서 peak 측정
5. FLUX와 LTX 작업 직렬화 시 재로딩 없이 S1 4씬이 완주되는지 확인
6. 작은 VLM이 품질 게이트를 통과하지 못할 때만 Nemotron 12B VL NVFP4를
   12~14GiB 예산 후보로 실측

최종 선택 게이트는 다음과 같다.

- 씬 분할: S1 4씬 JSON parse 3/3, 장면 의미와 순서 보존
- 캡션: 주 피사체·외형·의상·구도 보존, 근거 없는 속성 추가 금지
- 상주성: 정상 S1 실행에서 모델 재로딩 없음
- 안정성: swap 고갈, 서비스 종료, CUDA OOM 없음
- 메모리: LLM/VLM은 개별 peak 8~10GB 우선, 전체 파이프라인에는 안전 여유 확보
- 구조: `:8700` 단일 gateway와 LangGraph checkpoint 흐름 유지

관련 실측:

- [캡션 모델 비교](spikes/2.2-vl-caption-models.md)
- [한국어 씬 분할 비교](spikes/2.3-scene-split-korean.md)
- [동시 상주 OOM](spikes/2.4-oom-residency.md)
- [vLLM 및 LTX encoder 검토](spikes/2.2.2-vllm-and-ltx-encoder.md)
- [LTX-2.3 Face-ID 호환성](spikes/3.1-ltx-faceid-compat.md)
