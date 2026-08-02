# LLM·VLM 선택

## 현재 결정

- **씬 분할 LLM:** NVIDIA Nemotron 3 Nano 4B GGUF Q4_K_M으로 롤백한다(2026-08-02,
  같은 날 두 번째 결정). gemma4:latest로 잠깐 바꿔봤지만 `matched_image`/
  `subject_type` 비결정성이 완화될 뿐 안 없어짐(아래 근거 참고) — 근본 원인이
  "LLM이 씬↔참조이미지 매칭을 판단"하는 구조 자체였으므로, 모델 교체 대신
  `node_split_scenes`가 **참조 이미지가 정확히 1장이면 LLM 판단을 무시하고
  전 씬에 결정론적으로 강제 매칭**하도록 코드를 고쳤다(nodes.py "단일 참조
  결정론적 매칭" 분기). 이걸로 씬분할 LLM 자체의 이 약점은 더는 문제가 안 돼
  원래 채택 근거(S1 JSON 파싱 3/3 통과)로 복귀.
- **참조 이미지 캡션:** gemma4:latest 유지. 단일 참조의 human/nonhuman 판정에만
  쓰인다(matched_image 판단에는 더 이상 안 쓰임) — qwen3.5:9b(중국원산) 대체
  근거는 그대로 유효.
- **LTX의 Gemma 3 12B:** 일반 LLM이 아니라 LTX conditioning 구성요소다.
  LTX projection 및 Face-ID와 묶여 있으므로 별도 LLM 서버로 교체하지 않는다.

## 제외·보류 근거

- **NVIDIA Nemotron 3 Nano 4B GGUF Q4_K_M(씬 분할, 2026-08-02 폐기)** — 기존
  S1 JSON 파싱 3/3 통과 기록으로 잠정 채택했었으나, job `67c45bcb-44e2-47d1-
  b8a9-0aa436289918`에서 matched_image/subject_type을 실전 규모(4씬+참조이미지
  1장, 동시에 여러 제약)에서 동시 판단하지 못함을 확인. 같은 입력으로 씬분할
  LLM 콜만 3회 재현:
  - `matched_image`가 거의 항상 null(유일한 참조 이미지인데도 어떤 씬에도
    안 붙임) — 3회 중 전부/1개/2개 매칭으로 결과 자체가 실행마다 다름.
  - 완전히 동일한 씬 텍스트("낯선 외계 행성에 착륙해 주변을 탐사한다")의
    `subject_type`이 human/nonhuman/none으로 실행마다 바뀜 — 의미 판단이
    아니라 사실상 랜덤.
  - `text` 필드(원문 그대로 보존해야 하는 필드)에 한글 오타 환각 발생
    ("낯선" → "나이신"/"이상한"/"이익한").
  - 참조 이미지 캡션 자체는 정상("Handsome East Asian teenage boy in a grey
    graphic t-shirt")이었으므로 캡션 품질 문제가 아니라 4B 모델이 다중 제약
    구조화 출력(원문 보존 + 이미지 매칭 + 분류)을 동시에 못 지키는 용량 한계.
  - 단순 3/3 JSON 파싱 테스트로는 이 실패가 안 드러난다 — 향후 LLM 채택
    게이트는 다중 씬·참조이미지 동시 판단 실측을 포함해야 한다.
- Nemotron Labs Diffusion VLM 8B는 캡션은 통과했지만 씬 분할 JSON과 vLLM
  호환성에서 실패했고 약 17.23GiB peak를 기록했다.
- Nemotron Nano 12B v2 VL의 NVFP4 체크포인트도 runtime peak가 약
  12~14GiB로 예상되어 상시 경량 VLM 목표보다 무겁다.
- 엔진 통일보다 한국어 지시 준수, 구조화 출력, 상주 메모리를 우선한다.

관련 기록: [캡션 모델 비교](spikes/2.2-vl-caption-models.md),
[한국어 씬 분할](spikes/2.3-scene-split-korean.md),
[vLLM 검토](spikes/2.2.2-vllm-and-ltx-encoder.md)
