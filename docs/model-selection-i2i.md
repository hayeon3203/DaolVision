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
