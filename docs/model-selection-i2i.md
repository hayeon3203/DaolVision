# I2I 모델 선택

## 현재 후보

S2 얼굴 스타일 변환에는 독일 Black Forest Labs의
**FLUX.1 Kontext [dev]**를 검증한다. FLUX.1-schnell은 T2I 앵커 모델이며,
Kontext는 입력 이미지의 인물과 구조를 유지하며 편집하는 별도 역할이다.

## 채택 전 확인 사항

- 애니메이션·유화·프로필·우주비행사 스타일에서 얼굴 유사도
- GB10의 load/warm latency와 peak 메모리
- LangGraph 및 ComfyUI/Diffusers 연결 비용
- **FLUX.1 Dev Non-Commercial License:** 현재 dev 가중치는 상업 서비스에
  그대로 사용할 수 없다. 상용 라이선스를 확보하거나 상업 이용 가능한
  비중국 대체 모델을 선택해야 한다.

따라서 기술 후보이지만 상업 배포 모델로는 아직 확정하지 않는다.

## Task 6.1 1차 실측 (2026-08-01)

`:8700 /i2i` 엔드포인트 배선 완료(`langgraph/tools.py::generate_i2i_style`,
`_build_flux_kontext_graph`), ComfyUI 공식 워크플로(LoadImage →
FluxKontextImageScale → VAEEncode → ReferenceLatent → FluxGuidance → KSampler)
그대로 이식. 가중치는 Comfy-Org 리패키지 비게이트 미러에서 받음
(`diffusion_models/flux1-dev-kontext_fp8_scaled.safetensors` ~11.9GB,
`text_encoders/clip_l.safetensors` ~0.25GB, `vae/ae.safetensors` ~0.34GB —
t5xxl은 5.x LTX와 공유).

- cinematic 스타일 1장(880x1184) 실측: **~113초**, HTTP 200, 얼굴 정체성 유지.
- ComfyUI(`--highvram`)는 새 그래프 로드 시 이전 세션의 상주 체크포인트(32GB)를
  자체적으로 이관(evict)하고 Kontext만 남아 17GB 수준으로 내려감 — `--highvram`이
  막는 건 "현재 사용 중인 모델"의 즉시 언로드이지, 새 요청이 들어왔을 때의 캐시
  교체 자체를 막지 않는다. 5.x LTX Face-ID와 동시에 큐가 겹치지 않는 한 이 경로는
  상시 자원 상주 서버(Wan :8500, ~22GB)와 공존 가능.
- 6종 스타일 전체 순회, 배치/동시성, GB10 peak 메모리 세부 곡선은 별도 실측 필요.
