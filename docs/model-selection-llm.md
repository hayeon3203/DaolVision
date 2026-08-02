# LLM·VLM 선택

## 현재 결정

- **씬 분할·참조 이미지 캡션:** gemma4:latest 단일 모델로 통일한다(2026-08-02).
  text+vision 겸용이라 두 역할이 같은 Ollama 상주 모델을 공유 — 추가 로드 0.
  **주의**: 같은 job으로 gemma4:latest 재현 시 `text` 필드 한글 오타 환각은
  사라졌지만, `matched_image`/`subject_type` 비결정성은 완화됐을 뿐 완전히
  해소되진 않음(3회 재현 중 matched_image 1~2회만 성공, subject_type 여전히
  human/nonhuman/none 왔다갔다) — 남은 문제로 별도 추적 필요, 참조 이미지가
  정확히 1장뿐이고 subject_type이 애매할 때는 LLM 판단에 맡기지 말고 코드에서
  결정론적으로 전 씬에 매칭시키는 방향을 다음 후보로 검토.
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
