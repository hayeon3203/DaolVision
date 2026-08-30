# 파이프라인 지도: 어떤 경우에 무엇이 동작하는가

이 저장소에는 **영상 생성 경로가 하나만 있는 것이 아닙니다.** 시나리오만 입력하는 경우,
인물 한 명을 씬마다 일관되게 유지하는 경우, 그리고 그 인물 일관성을 서로 다른 모델로
해결하는 두 가지 구현이 모두 살아 있습니다. 이 경로들은 전부 같은 LangGraph
게이트웨이(:8700) 안에서 씬별 `mode` 값에 따라 나뉩니다.

경로를 삭제하지 않고 남긴 이유는 그동안의 구현 이력을 보존하기 위해서입니다. 어느 한쪽이
"정답"이기 때문이 아니라 **트레이드오프가 서로 다르기 때문에** 둘 다 쓸모가 있습니다.

## 세 가지 경우

| 경우 | UI 진입점 | 씬 `mode` | 백엔드 |
|---|---|---|---|
| **1. 인물 없이 영상 여러 개** | `시나리오만` | `T2V` | LTX-Video 0.9.8 **13B** distilled fp8 (ComfyUI :8188), 1280×704 / 24fps |
| **2a. 한 인물 일관 — Wan** | `사진 첨부` 또는 `이미지 설명` | `STANDIN` | Wan2.1-T2V-**14B** fp8 + Stand-In LoRA + lightx2v distill LoRA (ComfyUI :8188), 832×480 / 16fps |
| **2b. 한 인물 일관 — LTX** | `사진 첨부` 또는 `이미지 설명` | `LTX_FACEID` | LTX-2.3 **22B** GGUF Q6_K + Best-FaceID LoRA (ComfyUI :8188), 1280×704 / 24fps |

2a와 2b는 **같은 입력과 같은 UI, 같은 승인 흐름**을 사용합니다. 두 경로는 오직
`AGENT_FACE_BACKEND` 하나에 따라 나뉘며, 자세한 내용은 아래 "버전 전환"에 있습니다.

### 보조 경로 (같은 그래프 안에서 자동으로 라우팅됩니다)

| `mode` | 적용 조건 | 백엔드 |
|---|---|---|
| `SUBJECT_REF` | 참조 대상이 **사람이 아닌 경우**(제품·마스코트) | Wan2.1-I2V-14B-480P fp8 + lightx2v LoRA (`i2v_14b.json`) |
| `PRODUCT_OVERLAY` | 제품 참조가 있지만 그 제품을 손에 들고 있지 않은 씬 | 배경 T2I + 제품 픽셀 합성 |
| `PERSON_ASSEMBLY` | 인물이 등장하는 씬이지만 Face-ID 허용 개수(`AGENT_FACEID_MAX_SCENES`, 기본 1)를 초과한 경우 | 배경 재생성 + 의상·외형 텍스트 lock |
| `I2V` / (`T2V` + 캐릭터록 텍스트) | `AGENT_USE_STANDIN=0`으로 참조 경로 전체를 끈 경우의 폴백 | LTX 13B |

**단발 T2V (에이전트를 거치지 않습니다)**: Cosmos3-Nano 서버(:8505, `t2v/cosmos3nano/`)는
프롬프트 한 줄로 영상 하나를 생성합니다. 씬 분할도 승인 절차도 없습니다. 경우 1과 목적이
겹치지만 별개의 서비스입니다.

## 버전 전환 (환경변수)

전환에는 **환경변수 하나만 사용합니다.** 코드 수정도, 브랜치 전환도, 재설치도 필요하지
않습니다. 게이트웨이(:8700) 프로세스가 기동할 때 이 값을 읽으므로, **값을 바꾼 뒤에는
반드시 재시작해야 반영됩니다.**

| 변수 | 값 | 의미 |
|---|---|---|
| `AGENT_FACE_BACKEND` | `ltx_faceid` *(기본)* | 2b — 인물 씬을 LTX 22B Face-ID로 생성 |
| | `standin` | 2a — 인물 씬을 Wan2.1-14B Stand-In으로 생성 |

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

수동으로 기동할 때에는 명령 앞에 환경변수를 붙이면 됩니다.

```bash
cd langgraph && AGENT_FACE_BACKEND=standin ./run_agent.sh
```

`run_agent.sh`에 값을 고정하고 싶다면 파일 안의 `export` 줄 옆에 함께 적으면 됩니다.

**확인 방법**: job을 하나 실행하면 게이트웨이 로그에 씬별 라우팅 결과가 한 줄로 기록됩니다.

```
[route] 씬 mode: 1=STANDIN, 2=STANDIN, 3=STANDIN     # 2a
[route] 씬 mode: 1=LTX_FACEID, 2=PERSON_ASSEMBLY     # 2b (허용 개수 1)
```

값에 오타가 있으면 기본값으로 조용히 대체하지 않고 **기동 시점에 오류를 내며 종료합니다.**
잘못된 백엔드로 몇 시간이 걸리는 job을 실행하는 것보다 즉시 실패하는 편이 낫기 때문입니다.

### 두 백엔드 비교

| | 2a `standin` | 2b `ltx_faceid` |
|---|---|---|
| 해상도/fps | 832×480 / 16fps | 1280×704 / 24fps |
| 스텝 | 4 (distill LoRA) | 8 |
| 인물 씬 개수 제한 | 없음 | 기본 **1개** (`AGENT_FACEID_MAX_SCENES`). 초과한 씬은 `PERSON_ASSEMBLY`로 처리 |
| 얼굴에 대해 고정되는 범위 | 얼굴 identity만 고정하며 의상은 고정하지 않으므로 프롬프트로 따로 lock을 걸어야 함 | 얼굴 identity |
| 알려진 약점 | 정면 바이어스가 있어서 측면·로우앵글 프롬프트가 잘 반영되지 않음 | 22B GGUF 모델을 메모리에서 내렸다가 다시 올릴 때 재양자화가 일어나므로, 씬이 2개 이상이면 10~40분 동안 지연됨(그래서 허용 개수를 1로 둠) |

씬 개수 제약이 없다는 점 때문에, **인물이 여러 씬에 계속 등장하는 스토리에서는 2a가
실질적으로 더 잘 동작합니다.** 화질이 더 중요하고 인물이 등장하는 씬이 한두 개라면 2b를
사용합니다.

## 관련 환경변수 (자주 수정하는 것만 정리했습니다)

| 변수 | 기본 | 의미 |
|---|---|---|
| `AGENT_FACE_BACKEND` | `ltx_faceid` | 위 설명 참고 |
| `AGENT_USE_STANDIN` | `1` | 참조 이미지 경로 전체를 켜고 끕니다. `0`이면 참조 이미지가 있어도 Stand-In이나 Subject-Ref를 사용하지 않고 I2V/T2V로 폴백합니다. 단 `AGENT_FACE_BACKEND=standin`이면 이 값과 무관하게 켜집니다 |
| `AGENT_FACEID_MAX_SCENES` | `1` | 2b 전용으로, Face-ID를 적용할 씬의 최대 개수입니다 |
| `AGENT_STANDIN_STEPS` | `4` | 2a의 스텝 수입니다 (4~8) |
| `AGENT_STANDIN_WIDTH` / `_HEIGHT` | `832` / `480` | 2a의 해상도입니다. I2V-14B 체크포인트가 480P 전용이라서 값을 올리면 느려집니다 |
| `AGENT_STANDIN_FACE_LORA_STRENGTH` | `1.0` | 2a의 얼굴 유지 강도이며, 값을 올리면 배경 자유도가 낮아집니다 |
| `AGENT_LTX_FACEID_STEPS` | `8` | 2b의 스텝 수입니다 |
| `AGENT_MAX_CONCURRENT_CLIPS` | `1` | 동시에 생성할 클립의 상한입니다. GB10 통합메모리의 OOM을 방지하기 위한 값이므로 함부로 올리지 않습니다 |

전체 목록은 `langgraph/tools.py` 상단에 있습니다.

## 이력: 코드가 어디에서 왔는가

| 저장소 | 역할 |
|---|---|
| **DaolVision** (이 저장소) | 현재 본선이며, 위의 경로가 전부 여기에 있습니다 |
| `video_generator` | 부모 저장소입니다. Wan2.2-TI2V-5B(:8500)와 Wan2.2-Animate-14B(:8600) 서버, Open WebUI Function 3종의 원본이 있으며, `inference_server/`와 `langgraph/`를 여기에서 복제했습니다(Task 3.7/4.1) |
| `langgraph_videogenerator` | 에이전트만 분리해 두었던 옛 공개용 스냅샷입니다 |
| `hunyuanvideo-pipeline` | 그보다 앞선 저장소입니다 |

`video_generator`에만 있고 이 저장소에는 없는 것은 다음과 같습니다. Wan2.2-TI2V-5B
diffusers 서버(:8500, Task 6.5에서 DaolVision에서는 삭제했습니다), Wan2.2-Animate-14B(:8600),
그리고 `ComfyUI/batch_scenes.py`(에이전트 없이 Stand-In만 배치로 실행하는 스크립트 형태의
2a)입니다.

Open WebUI Function 3종은 `openwebui/`로 **이관을 완료했으며** 소유자는 이 저장소입니다.
`:8500`과 `:8600`을 사용하는 두 함수는 서버가 없어서 현재 동작하지 않지만, 구현 이력을
보존하기 위해 삭제하지 않고 둡니다. 상세한 내용은
[openwebui/README.md](../openwebui/README.md)에 있습니다.

## 검증

```bash
cd langgraph && ./.venv/bin/python tests/test_face_backend_routing.py
```

두 백엔드가 실제로 서로 다른 `mode`로 라우팅되는지, 그리고 잘못된 값이 조용히 통과하지는
않는지 확인합니다. GPU와 LLM은 사용하지 않습니다.
