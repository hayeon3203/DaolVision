# LESSONS.md — 재발 방지 기록

> 에러·실수를 해결한 뒤 "다음에 같은 실수를 안 하려면"을 한 항목으로 남긴다.
> 최신 항목이 위. 세션 재개 시 최근 5개를 먼저 읽는다.

## 이 ollama 빌드(0.31.2, GB10)는 llama3.2-vision(mllama) 로드 불가 — 비전은 gemma
- `ollama pull llama3.2-vision`은 되지만 추론시 `500 unknown model architecture:
  'mllama'`. 이 빌드 llama.cpp가 mllama 미지원. Nemotron-Nano-VL도 RADIO 인코더라
  미지원(레지스트리에도 없음). transformers 네이티브도 버전 비호환으로 실패. (2026-07-28, 2.2)
- 규칙: VL/이미지캡션 필요하면 **gemma 계열**을 쓸 것(gemma4:latest 실측 200 OK).
  mllama·비표준 비전인코더 모델은 이 스택에서 배제. 새 ollama로 올리기 전엔
  llama3.2-vision 재시도 금지.

## trust_remote_code 커스텀 모델은 transformers 버전에 묶임 — 공유 venv에 함부로 X
- NVIDIA Nemotron-VL은 옛 transformers(≈4.4x)용 커스텀코드라 huyuan-env의 5.12에서
  `all_tied_weights_keys` 등으로 깨짐. 다운그레이드하면 그 venv 쓰는 :8500이 죽음.
- 규칙: 커스텀코드 모델은 **전용 venv**로 격리하거나, 유지비 크면 표준-arch 대안
  (gemma 등)으로 우회. 상주 서버 공유 venv의 핵심 라이브러리 버전을 건드리지 말 것. (2026-07-28)

## curl -d 로 base64 이미지 인라인 금지 — "Argument list too long"
- 이미지 base64를 `curl ... -d "{...$B64...}"`로 넣으면 ARG_MAX 초과로 즉사.
  페이로드를 파일에 쓰고 `curl -d @file`. -sf는 HTTP 500도 조용히 삼키니
  디버그시 -f 빼고 `-w '%{http_code}'`로 코드부터 볼 것. (2026-07-28)

## 포트 점유 확인 먼저 — Acceptance 오라클 오염 주의
- GB10엔 open-webui(8080)·waferscope(8090) 등 상주 서비스 많음. 새 서비스 띄우기
  전 `ss -ltn`으로 빈 포트 확인. `curl localhost:PORT`가 200이어도 **다른 서비스**일
  수 있음(2.1에서 8080=open-webui, 8090=waferscope에 오탐). 응답 body·title로
  실제 서비스 정체 확인 후 Acceptance 판정. (2026-07-28, 2.1)
