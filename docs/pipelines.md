# 파이프라인 지도 — 어떤 경우에 무엇이 도는가

이 저장소에는 **영상 생성 경로가 하나가 아니다.** 시나리오만 주는 경우, 인물 한 명을
씬마다 일관되게 유지하는 경우, 그 인물 일관성을 서로 다른 모델로 푸는 두 가지 구현이
전부 살아 있고, 모두 같은 LangGraph 게이트웨이(:8700) 안에서 씬별 `mode` 값으로 갈린다.

경로를 지우지 않고 남긴 이유는 그동안의 구현 히스토리를 보존하기 위해서다. 어느 쪽이
"정답"이라서가 아니라 **트레이드오프가 달라서** 둘 다 쓸모가 있다.

## 세 가지 경우

| 경우 | UI 진입점 | 씬 `mode` | 백엔드 |
|---|---|---|---|
| **1. 인물 없이 영상 여러 개** | `시나리오만` | `T2V` | LTX-Video 0.9.8 **13B** distilled fp8 (ComfyUI :8188), 1280×704 / 24fps |
| **2a. 한 인물 일관 — Wan** | `사진 첨부` 또는 `이미지 설명` | `STANDIN` | Wan2.1-T2V-**14B** fp8 + Stand-In LoRA + lightx2v distill LoRA (ComfyUI :8188), 832×480 / 16fps |
| **2b. 한 인물 일관 — LTX** | `사진 첨부` 또는 `이미지 설명` | `LTX_FACEID` | LTX-2.3 **22B** GGUF Q6_K + Best-FaceID LoRA (ComfyUI :8188), 1280×704 / 24fps |

2a와 2b는 **같은 입력, 같은 UI, 같은 승인 흐름**을 쓴다. `AGENT_FACE_BACKEND` 하나로만
갈린다 — 아래 "버전 전환" 참고.

### 곁가지 경로 (같은 그래프 안, 자동 라우팅)

| `mode` | 언제 | 백엔드 |
|---|---|---|
| `SUBJECT_REF` | 참조가 **사람이 아닐 때**(제품·마스코트) | Wan2.1-I2V-14B-480P fp8 + lightx2v LoRA (`i2v_14b.json`) |
| `PRODUCT_OVERLAY` | 제품 참조가 있고 그 제품이 손에 안 들린 씬 | 배경 T2I + 제품 픽셀 합성 |
| `PERSON_ASSEMBLY` | 인물 씬인데 Face-ID 정원(`AGENT_FACEID_MAX_SCENES`, 기본 1) 초과 | 배경 재생성 + 의상/외형 텍스트 lock |
| `I2V` / (`T2V` + 캐릭터록 텍스트) | `AGENT_USE_STANDIN=0`으로 참조 경로를 통째로 끈 경우의 폴백 | LTX 13B |

**단발 T2V (에이전트 미경유)**: Cosmos3-Nano 서버(:8505, `t2v/cosmos3nano/`)는 프롬프트
한 줄 → 영상 하나. 씬 분할도 승인도 없다. 경우 1과 목적이 겹치지만 별개 서비스다.

## 버전 전환 (env)

전환은 **환경변수 하나**다. 코드 수정도, 브랜치 전환도, 재설치도 필요 없다.
게이트웨이(:8700) 프로세스가 기동할 때 읽으므로 **바꾼 뒤 재시작해야 반영된다.**

| 변수 | 값 | 뜻 |
|---|---|---|
| `AGENT_FACE_BACKEND` | `ltx_faceid` *(기본)* | 2b — 인물 씬을 LTX 22B Face-ID로 |
| | `standin` | 2a — 인물 씬을 Wan2.1-14B Stand-In으로 |

```bash
# 2b (기본) — LTX Face-ID
systemctl --user restart anim-agent

# 2a — Wan Stand-In
systemctl --user set-environment AGENT_FACE_BACKEND=standin
systemctl --user restart anim-agent

# 되돌리기
systemctl --user unset-environment AGENT_FACE_BACKEND
systemctl --user restart anim-agent
```

수동 기동이면 그냥 앞에 붙인다:

```bash
cd langgraph && AGENT_FACE_BACKEND=standin ./run_agent.sh
```

`run_agent.sh`에 고정하고 싶으면 파일 안 `export` 줄 옆에 같이 적으면 된다.

**확인법**: job을 하나 돌리면 게이트웨이 로그에 씬별 라우팅이 한 줄로 찍힌다.

```
[route] 씬 mode: 1=STANDIN, 2=STANDIN, 3=STANDIN     # 2a
[route] 씬 mode: 1=LTX_FACEID, 2=PERSON_ASSEMBLY     # 2b (정원 1)
```

오타를 내면 조용히 기본값으로 폴백하지 않고 **기동 시점에 죽는다** — 잘못된 백엔드로
몇 시간짜리 job을 돌리는 것보다 낫다.

### 두 백엔드 비교

| | 2a `standin` | 2b `ltx_faceid` |
|---|---|---|
| 해상도/fps | 832×480 / 16fps | 1280×704 / 24fps |
| 스텝 | 4 (distill LoRA) | 8 |
| 인물 씬 개수 제한 | 없음 | 기본 **1개** (`AGENT_FACEID_MAX_SCENES`) — 초과분은 `PERSON_ASSEMBLY`로 강등 |
| 얼굴이 고정하는 것 | 얼굴 identity만. 의상은 안 잠금 → 프롬프트로 별도 lock | 얼굴 identity |
| 알려진 약점 | 정면 바이어스(측면·로우앵글 프롬프트가 잘 안 먹음) | 22B GGUF 축출 정체 — 씬 2개 이상이면 재양자화로 10~40분 정체(그래서 정원 1) |

정원 제약이 없다는 점 때문에 **인물이 여러 씬에 계속 나오는 스토리는 2a가 실질적으로 더
잘 돈다.** 화질이 우선이고 인물 씬이 한두 개면 2b.

## 관련 env (자주 만지는 것만)

| 변수 | 기본 | 뜻 |
|---|---|---|
| `AGENT_FACE_BACKEND` | `ltx_faceid` | 위 참고 |
| `AGENT_USE_STANDIN` | `1` | 참조 이미지 경로 전체 on/off. `0`이면 참조가 있어도 Stand-In/Subject-Ref를 안 쓰고 I2V/T2V 폴백. `AGENT_FACE_BACKEND=standin`이면 이 값과 무관하게 켜진다 |
| `AGENT_FACEID_MAX_SCENES` | `1` | 2b 전용 Face-ID 씬 정원 |
| `AGENT_STANDIN_STEPS` | `4` | 2a 스텝 수 (4~8) |
| `AGENT_STANDIN_WIDTH` / `_HEIGHT` | `832` / `480` | 2a 해상도. I2V-14B 체크포인트가 480P 전용이라 올리면 느려진다 |
| `AGENT_STANDIN_FACE_LORA_STRENGTH` | `1.0` | 2a 얼굴 유지 강도 ↑ = 배경 자유도 ↓ |
| `AGENT_LTX_FACEID_STEPS` | `8` | 2b 스텝 수 |
| `AGENT_MAX_CONCURRENT_CLIPS` | `1` | 동시 클립 생성 상한. GB10 통합메모리 OOM 방지용이라 함부로 올리지 말 것 |

전체 목록은 `langgraph/tools.py` 상단.

## 히스토리 — 코드가 어디서 왔나

| 저장소 | 역할 |
|---|---|
| **DaolVision** (이 저장소) | 현재 본선. 위 경로 전부 여기 있다 |
| `video_generator` | 부모 저장소. Wan2.2-TI2V-5B(:8500) / Wan2.2-Animate-14B(:8600) 서버와 Open WebUI Function 3종의 원본. `inference_server/`·`langgraph/`가 여기서 복제됐다(Task 3.7/4.1) |
| `langgraph_videogenerator` | 에이전트만 떼어낸 옛 공개용 스냅샷 |
| `hunyuanvideo-pipeline` | 그 이전 |

`video_generator`에만 있고 여기 없는 것: Wan2.2-TI2V-5B diffusers 서버(:8500, Task 6.5에서
DaolVision에선 삭제), Wan2.2-Animate-14B(:8600),
`ComfyUI/batch_scenes.py`(에이전트 없이 Stand-In만 배치로 돌리는 스크립트판 2a).

Open WebUI Function 3종은 `openwebui/`로 **이관 완료** — 소유자는 이 저장소다.
`:8500`·`:8600`을 쓰는 두 함수는 서버가 없어 지금 안 돌지만, 히스토리 보존을 위해
지우지 않고 둔다. 상세: [openwebui/README.md](../openwebui/README.md)

## 검증

```bash
cd langgraph && ./.venv/bin/python tests/test_face_backend_routing.py
```

두 백엔드가 실제로 다른 `mode`로 갈리는지, 잘못된 값이 조용히 통과하지 않는지 확인한다.
GPU도 LLM도 안 쓴다.
