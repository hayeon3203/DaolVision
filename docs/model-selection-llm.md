# LLM·VLM 선택

## 현재 결정

- **씬 분할:** NVIDIA Nemotron 3 Nano 4B GGUF Q4_K_M을 잠정 유지한다.
  기존 Ollama 경로에서 S1 JSON 파싱을 3/3 통과했고 파일 크기는 약 2.84GB다.
- **참조 이미지 캡션:** 아직 확정하지 않았다. 3~4B급 INT4/GGUF 비중국
  멀티모달 모델을 우선 재검토한다.
- **LTX의 Gemma 3 12B:** 일반 LLM이 아니라 LTX conditioning 구성요소다.
  LTX projection 및 Face-ID와 묶여 있으므로 별도 LLM 서버로 교체하지 않는다.

## 제외·보류 근거

- Nemotron Labs Diffusion VLM 8B는 캡션은 통과했지만 씬 분할 JSON과 vLLM
  호환성에서 실패했고 약 17.23GiB peak를 기록했다.
- Nemotron Nano 12B v2 VL의 NVFP4 체크포인트도 runtime peak가 약
  12~14GiB로 예상되어 상시 경량 VLM 목표보다 무겁다.
- 엔진 통일보다 한국어 지시 준수, 구조화 출력, 상주 메모리를 우선한다.

관련 기록: [캡션 모델 비교](spikes/2.2-vl-caption-models.md),
[한국어 씬 분할](spikes/2.3-scene-split-korean.md),
[vLLM 검토](spikes/2.2.2-vllm-and-ltx-encoder.md)
