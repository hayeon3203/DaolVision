# 영상 분위기 일관성 관련 설정

핵심 원인은 프롬프트 내용보다 상위에서 **“실사 시네마틱”을 기본 화풍으로 강제하는 설정**입니다. 특히 “시나리오만”은 참조 이미지가 없으므로 이 기본값이 매번 적용됩니다.

## “시나리오만”에 직접 적용되는 설정

### 1. 기본 화풍 강제

참조 이미지가 없으면 다음 방향으로 고정됩니다.

- photorealistic
- cinematic live-action
- real-world materials
- natural lighting
- photographic texture
- 동일한 플랫폼 시각 정체성

사용자가 `anime`, `watercolor`, `cartoon`, `comic`, `flat vector`처럼 다른 매체를 **시나리오에 명시적으로 작성한 경우에만** 이 기본값을 벗어나도록 되어 있습니다.

위치: [`nodes.py`](../langgraph/nodes.py#L690)

이 설정이 서로 전혀 다른 시나리오도 비슷한 실사 영화 톤으로 나오는 가장 큰 원인입니다.

### 2. 전역 스타일 바이블

작업마다 Nemotron이 스타일 바이블을 하나 만들고 네 장면 모두에 똑같이 삽입합니다. 고정 대상으로 요구하는 항목은 다음과 같습니다.

- 렌더링 기법
- 선과 경계 표현
- 형태 언어
- 재질과 표면
- 텍스처 밀도
- 환경 디테일 수준
- 소품 디자인 언어
- 카메라 성격
- 컬러 그레이딩
- 렌즈 스타일과 초점 심도
- 전체 작품의 정서적 분위기

또한 네 클립을 “같은 카메라·렌즈 패키지로 촬영하고 같은 후반 색보정을 거친 단편영화”처럼 만들라고 명시합니다.

위치: [`nodes.py`](../langgraph/nodes.py#L641)

### 3. 스타일 바이블의 결정적 재삽입

Nemotron이 장면 프롬프트를 만들 때 스타일을 약하게 반영하는 정도가 아닙니다. 코드에서 모든 장면 프롬프트 뒤에 동일한 `bible` 문자열을 직접 붙입니다.

```text
<장면 프롬프트>. <캐릭터 설정> <전역 스타일 바이블>
Scene lighting and atmosphere: <조명 설정>.
```

따라서 장면별 내용이 크게 달라도 렌더링·렌즈·색감·전체 정서는 계속 같습니다.

위치: [`nodes.py`](../langgraph/nodes.py#L919)

### 4. 스타일 생성 실패 시에도 일관성 강제

스타일 바이블 생성이 실패하거나 빈 응답이면 `STYLE_LOCK_TOKEN`으로 대체됩니다. 이 폴백 역시 다음 항목을 네 장면에서 동일하게 유지하도록 강제합니다.

- 렌더링 기법
- 재료와 텍스처
- 소품 디자인
- 색보정 방식
- 그림자 성격
- 시네마틱 콘트라스트
- 카메라 성격

즉, LLM이 실패해도 화풍 고정은 풀리지 않습니다.

위치: [`nodes.py`](../langgraph/nodes.py#L631)

### 5. 작품 전체의 단일 정서

스타일 바이블에 장면별 감정과 별개로 작품 전체를 관통하는 하나의 정서를 만들도록 되어 있습니다.

예:

- quiet awe
- tense urgency
- warm nostalgia

이 정서는 네 장면 모두에 유지됩니다. 서로 다른 입력에서도 Nemotron이 비슷한 “cinematic/quiet/warm” 조합을 자주 선택하면 결과가 더욱 비슷해질 수 있습니다.

2026-08-05 변경: 스타일 바이블 생성 프롬프트의 컬러 그레이딩 예시에서
`desaturated teal-orange`, `warm film stock`, `bleach-bypass`를 제거했습니다.
컬러 그레이딩 자체는 여전히 작업별 바이블에 포함되지만, 특정 저채도 영화 색감으로
유도하지 않습니다.

### 6. 장면별 조명도 제한된 규칙 사용

장면의 `mood`는 다음 7개로 제한됩니다.

```text
calm, sad, neutral, happy, tense, excited, surprised
```

LLM 조명 생성이 실패하면 고정된 조명 프리셋으로 대체됩니다.

| Mood | 고정되는 경향 |
|---|---|
| sad | 어둡고 차가운 저채도 |
| tense | 저조도·고대비·차가운 색감 |
| calm | 부드러운 조명·따뜻한 중성 색감 |
| neutral | 자연광·중간 콘트라스트 |
| happy | 밝은 하이키·따뜻한 고채도 |
| excited | 밝고 선명한 색·강한 하이라이트 |
| surprised | 갑작스러운 키라이트·선명한 대비 |

위치: [`nodes.py`](../langgraph/nodes.py#L247)

장면별 조명은 달라질 수 있지만, 선택지가 제한적이어서 여러 영상에서 익숙한 조명 패턴이 반복됩니다.

2026-08-05 변경: 조명 생성기는 `sad`와 `tense`만 저조도로 선택하도록 제한하고,
`calm`은 정상 노출의 부드럽고 균일한 조명으로 지시합니다. 또한 LLM이 잘못해서
`happy` 또는 `neutral` 장면에 `low-key`, `dim`, `deep shadows`, `low exposure` 등의
큐를 반환하면 코드가 각각의 밝은/균형 노출 폴백으로 교체합니다. 따라서 이 두 mood의
최소 노출은 프롬프트 권고가 아니라 코드 수준에서 보장됩니다.

### 7. 조명 문구도 프롬프트 끝에 강제 삽입

조명은 Nemotron의 장면 프롬프트 작성에 참고로만 전달되는 게 아니라, 최종 프롬프트 끝에 다시 직접 붙습니다.

```text
Scene lighting and atmosphere: ...
```

따라서 모델이 조명 지시를 생략하거나 약하게 쓰더라도 반드시 남습니다.

위치: [`nodes.py`](../langgraph/nodes.py#L948)

### 8. 장면 프롬프트의 영화 문법

모든 장면에 다음 조건이 공통 적용됩니다.

- 구체적인 숏 크기와 카메라 각도
- 카메라 움직임
- 자연스럽고 동적인 움직임
- 하나의 연속된 무편집 숏
- 하나의 지배적인 행동
- 이전 장면에서 이어지는 단편영화의 다음 순간

이 때문에 입력 소재는 달라도 영상 문법이 계속 “영화적 단일 숏”으로 수렴합니다.

위치: [`nodes.py`](../langgraph/nodes.py#L986)

### 9. 장소 연속성

장소가 빈 장면은 이전 장면의 장소를 이어받습니다. 이후 다음 문구로 배경에 강제 적용됩니다.

```text
Setting/location (render this exact place as the background)
```

같은 영상 내부의 연속성을 높이지만, 장면 사이의 시각적 변화 폭은 줄어들 수 있습니다.

위치: [`nodes.py`](../langgraph/nodes.py#L793), [`nodes.py`](../langgraph/nodes.py#L1061)

### 10. 인물이 나오면 캐릭터 시트도 반복 삽입

“시나리오만”에 사람이 등장하면 Nemotron이 다음 내용을 포함한 캐릭터 시트를 한 개 생성합니다.

- 성별과 대략적인 나이
- 체격
- 머리 색·길이·스타일
- 피부색
- 특징
- 기본 의상

이 시트가 모든 인물 장면에 반복 삽입됩니다. 인물 일관성이 필요 없더라도 현재는 자동 적용됩니다.

위치: [`nodes.py`](../langgraph/nodes.py#L656), [`nodes.py`](../langgraph/nodes.py#L935)

## 모델·샘플링 측 고정 설정

“시나리오만”은 LTX-13B T2V 경로를 사용합니다.

- 체크포인트: `ltxv-13b-0.9.8-distilled-fp8.safetensors`
- 텍스트 인코더: `t5xxl_fp8_e4m3fn_scaled.safetensors`
- 실제 실행 스텝: `12`
- FPS: `24`
- sampler: `euler`
- scheduler: `normal`
- CFG: `1.0`
- denoise: `1.0`
- max shift: `2.05`
- base shift: `0.95`
- 공통 negative prompt:

```text
worst quality, blurry, jittery, distorted, low resolution
```

위치: [`tools.py`](../langgraph/tools.py#L584), [`tools.py`](../langgraph/tools.py#L670), [`run_agent.sh`](../langgraph/run_agent.sh#L36)

같은 모델·샘플러·스케줄러·낮은 CFG를 계속 사용하므로 모델 고유의 색감과 움직임도 반복됩니다.

시드는 장면마다 `job_id + scene_id`로 다르게 계산됩니다. 따라서 같은 시드가 분위기 반복의 원인은 아닙니다.

위치: [`nodes.py`](../langgraph/nodes.py#L1077)

## 다른 입력 모드에만 적용되는 설정

참조 이미지 모드에서는 추가로 다음 고정값이 있습니다. “시나리오만”에는 직접 적용되지 않습니다.

- Stand-In 해상도: `832×480`
- Stand-In 스텝: `4`
- FPS: `16`
- Face identity LoRA: `1.0`
- Distill LoRA: `0.6`
- 어두운 장면 relight latent strength: `0.55`
- noise augmentation: `0.02`
- 사람 참조 장면은 항상 wide/establishing shot
- 인물을 배경 속에서 작게 배치
- 카메라는 정적 또는 느린 팬
- close-up과 medium close-up 금지

위치: [`tools.py`](../langgraph/tools.py#L65), [`nodes.py`](../langgraph/nodes.py#L1027)

따라서 참조 이미지 모드라면 분위기뿐 아니라 구도까지 반복되는 경향이 더 강합니다.

## 가장 영향이 큰 설정 순서

현재 증상의 원인은 대략 다음 순서입니다.

1. 참조 없는 모든 영상에 `photorealistic cinematic live-action` 강제
2. 네 장면에 동일한 스타일 바이블 직접 삽입
3. 작품 전체에 단일 감정 톤 요구
4. 제한된 mood→조명 프리셋
5. 동일한 LTX 모델·샘플러·CFG 설정
6. 장면을 항상 하나의 연속된 영화 숏으로 작성

특히 1번 때문에 “어떤 프롬프트를 넣어도 비슷하다”는 느낌이 생길 가능성이 큽니다.

## 남아 있는 기존 FLUX 변경

현재 `langgraph/tools.py`에 커밋되지 않고 남아 있는 FLUX 관련 변경은 세 부분입니다.

### 1. `_release_t2i()` 함수 추가

FLUX 서버 `:8501`에 `POST /unload`를 보내 상주 중인 FLUX 가중치를 명시적으로 내립니다.

목적:

- FLUX + LTX-13B는 동시 상주 가능
- FLUX + LTX-22B Face-ID는 메모리가 부족
- ComfyUI가 low-VRAM 모드로 떨어져 2개 장면 생성에 70분 이상 걸린 사례 방지

### 2. LTX Face-ID 배치 직전 FLUX 언로드

`generate_ltx_faceid_batch()`가 22B Face-ID 모델을 올리기 전에 `_release_t2i()`를 호출합니다.

즉, 얼굴 참조 영상 생성 전에 FLUX가 차지한 메모리를 먼저 반환합니다.

### 3. Stand-In/Subject Reference 직전 FLUX 언로드

`_generate_reference_clip()`에서도 `_release_t2i()`를 호출합니다.

이 경로는 Wan 14B 기반 참조 영상 경로의 FLUX 동시 상주 메모리가 충분히 검증되지 않았기 때문에 안전하게 먼저 FLUX를 내리도록 되어 있습니다.

이 변경이 동작하려면 함께 남아 있는 다음 미커밋 변경이 필요합니다.

- [`flux_server.py`](../inference_server/flux_server.py#L116): `POST /unload` 엔드포인트 추가
- [`start_studio.sh`](../scripts/start_studio.sh#L78): Ollama 모델 경로를 샌드박스에 추가한 변경

`start_studio.sh` 변경은 FLUX 언로드 자체와 직접 관계되기보다는 Ollama 샌드박스에서 기존 모델 저장소를 정상적으로 찾기 위한 수정입니다.

정리하면 `tools.py`의 기존 FLUX 변경은 **화풍이나 분위기를 조정하는 설정이 아니라, 대형 영상 모델 진입 전에 FLUX를 내려 메모리 부족과 저속 low-VRAM 전환을 막는 운영 최적화**입니다.
