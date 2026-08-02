# T2V 모델 선택 (Task 7.6)

[I2V 선택 문서](model-selection-i2v.md) 2026-07-31 갱신분에서 예고한 대로,
identity 불필요한 순수 T2V 단발샷 카테고리를 정리한다. LocalAI UI의 I2V
단발샷 카테고리(사진 1장 + 프롬프트, LTX-13B-distilled)를 대체 — 사진 입력
없이 프롬프트만으로 영상 1개(one-shot).

## 후보와 결정

- **Cosmos-Predict2-2B**: 7.3에서 이미 I2V 용도로 최종 제외됨(공식 모델
  카드에 identity 보존 언급 없음). 이번 T2V 스파이크에서도 **사용자 지시로
  비교 대상에서 제외** — Cosmos 3 Nano 단독 채택 여부만 확인.
- **Cosmos 3 Nano** (`nvidia/Cosmos3-Nano`, 16B = 8B reasoner + 8B
  generator, OpenMDW1.1 라이선스, 2026-06-01 출시): 실측 진행, 아래 채택.

## 하드웨어/환경

- NVIDIA GB10(DGX Spark), aarch64, Blackwell(compute capability 12.1/sm_121)
- driver 580.142, CUDA 13.0, torch 2.13.0+cu130(`.venv-cosmos3nano`,
  `--system-site-packages`로 만들었지만 diffusers/transformers 의존성이 더
  새 torch를 끌어와 별도 설치됨 — 결과적으로 문제 없이 동작)
- diffusers는 PyPI 릴리스(0.38.0 기준)에 `Cosmos3OmniPipeline`이 아직 없어
  git main 필요
- 계정(`hanna3203`)에 `nvidia/Cosmos3-Nano` 게이트 없음 — 라이선스 수락 절차
  없이 바로 다운로드됨(2026-08-02 확인, 35GB)
- 이전 2.4 스파이크에서 전 모델 상주 시 118GB/119GB까지 치솟아 OOM-kill난
  전례가 있어(`oom_orchestrator.py` 참고) 조심스럽게 접근 — 실측 시점에
  ComfyUI(20GB GPU 상주) + Ollama 등 다른 서비스가 이미 떠 있는 채로 진행

## 실측 (2026-08-02)

프롬프트: `"a paper airplane gliding through a sunlit office, slow motion"`,
640x480, 49프레임(24fps, ~2.04s), 20 steps, guidance_scale 6.0.
`enable_safety_checker=False`(로컬 전용 서버, 게이트된 별도 safety 모델
다운로드 없이 스킵 — 공개 배포 시엔 켜야 함).

| 구성 | cold(모델 로드 포함) | warm(재사용) | GPU 메모리 |
|---|---|---|---|
| `enable_sequential_cpu_offload()` 켬 | 259.3s | ~144s | 프로세스 상주 1.4GB(레이어별 스트리밍) |
| offload 끔(`.to("cuda")`) | 215.3s | **61.5s** | 프로세스 상주 30.8GB |

**offload는 GB10에서 순손해로 확인** — `enable_sequential_cpu_offload()`는
VRAM과 시스템 RAM이 분리된 디스크리트 GPU 박스를 전제로 설계된 기능인데,
GB10은 NVLink-C2C로 묶인 통합 메모리라 CPU/GPU가 물리적으로 같은 DRAM을
쓴다. 그래서 offload를 꺼도 피크 메모리 사용량은 동일(둘 다 같은 통합
메모리 풀 안)하면서 레이어별 CPU↔GPU 이동 오버헤드만 사라져 warm 생성이
**2.3배 빨라짐**(144s → 61.5s). `t2v/cosmos3nano/server.py`
`COSMOS3NANO_OFFLOAD` 기본값을 꺼짐으로 설정.

메모리 압박: 모델 로드 중 시스템 swap(15GB)이 완전히 소진되는 순간이
있었다(cold load, offload 켠 상태에서 관측 — RAM 75GB 사용/2.8GB 여유).
크래시로 이어지진 않았지만 2.4 스파이크가 경고한 상태와 유사한 신호라
`t2v/cosmos3nano` 서버는 job 파이프라인의 llm/t2i/i2v/tts와 같은
`oom_orchestrator.phase()` 배치 직렬화에 태웠다(`generate_t2v_cosmos3nano`,
동시 진입 방지만 — 별도 상주 프로세스라 언로드 훅은 없음, TTS 서버들과 동일
패턴).

품질(육안 확인, `t2v-frame.png` 프레임 캡처): 프롬프트와 일치하는 사무실
배경·창문 역광·종이비행기 형태를 뚜렷하게 재현. 디테일(비행기 접힌 선,
책상 위 소품)이 다소 뭉개지지만 단발샷 스파이크 기준으로는 충분한 품질.

## 채택

**Cosmos3-Nano 채택.** DoD상 요구된 "단발샷 생성 실측"을 충족(warm 61.5s,
비디오 640x480/2초, 유효 h264 mp4 출력 확인). Cosmos-Predict2-2B는 사용자
지시로 비교 생략 — 어차피 7.3에서 identity 보존 기능 부재로 I2V 제외된
전례가 있고, 이번 카테고리는 identity 무관 T2V라 재검토 여지는 있지만
이번 스파이크 범위 밖으로 둔다.

배선: LocalAI UI I2V 단발샷 카테고리(`GatewayI2V.jsx`, `POST /i2v`,
`generate_i2v_oneshot`)를 완전히 대체 — T2V 단발샷(`GatewayT2V.jsx`,
`POST /t2v`, `generate_t2v_cosmos3nano`, `t2v/cosmos3nano` 독립 서버 :8505).
job 파이프라인의 I2V 폴백 클립 생성(`_ltx13b_dims`, `_normalize_i2v_input`,
LTX-13B-distilled)은 이 카테고리와 무관하게 그대로 유지.

## 남은 캡션 (다음에 손볼 것)

- safety checker(cosmos-guardrail)는 게이트된 별도 HF 모델이 필요해 이번
  스파이크에서는 끄고 진행 — 로컬 단일사용자 데모 용도라 당장은 무방하나,
  공개/다중사용자로 넓힐 계획이 생기면 켜야 한다.
- 해상도/프레임수/steps를 키운 실측은 하지 않음(스파이크 범위 밖) — 실사용
  중 더 긴 영상이 필요해지면 warm 시간이 선형 이상으로 늘어날 가능성 확인
  필요.
