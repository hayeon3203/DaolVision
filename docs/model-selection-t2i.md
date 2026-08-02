# T2I 모델 선택

## 현재 결정

장면별 정지 앵커 생성에는 독일 Black Forest Labs의
**FLUX.1-schnell**을 사용한다.

- 서비스: `:8501`
- 용도: S1의 각 장면을 I2V에 넘길 첫 이미지로 생성
- 설정: 1024×1024(서버 기본값, `/t2i` 단독 카테고리), 4 step
- Agent M2(`이미지 설명으로 생성`, `node_generate_image`)는 승인 시 `ref_images`로
  그대로 첨부되는 게 목적이라 16:9(`AGENT_T2I_WIDTH`/`AGENT_T2I_HEIGHT`, 기본
  1280×720)로 별도 지정 — 영상 프리셋 `WIDTH`/`HEIGHT`(LTX/Wan 32배수 제약용,
  1280×704)를 재사용하면 16:9가 아니게 되는 문제 수정 (Task 6.15 후속)
- GB10 실측 peak: 약 33.8GB
- 라이선스: Apache-2.0
- **콜드 로드 비용 주의**: `flux_server.py`는 매 요청마다 모델을 언로드한다
  (`FLUX_KEEP_RESIDENT=0` 기본값, Task 2.4 GB10 전 모델 상주 OOM 실측 후 채택).
  순수 추론은 웜 기준 ~7-12s지만, 콜드 로드+전송까지 포함하면 시스템 메모리
  압박 상태에서 실측 175s(로드 168s)까지 걸림(job a96857e4 ReadTimeout 재현,
  2026-08-02). `tools.py`의 read timeout을 120s→300s로 상향해 대응
  (Task 6.15 후속)

중국 원산 모델을 제외하면서 속도, 품질, 상업적 활용 가능성을 함께 만족하는
현재의 검증된 선택이다. FLUX와 I2V sampling은 동시에 실행하지 않고 LangGraph의
GPU-heavy queue에서 직렬화한다.

새 후보는 원산·라이선스를 확인한 뒤 동일 S1 프롬프트의 품질, warm latency와
peak 메모리로 비교한다.
