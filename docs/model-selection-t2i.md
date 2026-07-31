# T2I 모델 선택

## 현재 결정

장면별 정지 앵커 생성에는 독일 Black Forest Labs의
**FLUX.1-schnell**을 사용한다.

- 서비스: `:8501`
- 용도: S1의 각 장면을 I2V에 넘길 첫 이미지로 생성
- 설정: 1024×1024, 4 step
- GB10 실측 peak: 약 33.8GB
- 라이선스: Apache-2.0

중국 원산 모델을 제외하면서 속도, 품질, 상업적 활용 가능성을 함께 만족하는
현재의 검증된 선택이다. FLUX와 I2V sampling은 동시에 실행하지 않고 LangGraph의
GPU-heavy queue에서 직렬화한다.

새 후보는 원산·라이선스를 확인한 뒤 동일 S1 프롬프트의 품질, warm latency와
peak 메모리로 비교한다.
