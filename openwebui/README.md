# Open WebUI Function 3종

Open WebUI 채팅창에서 이 스택을 사용하던 경로입니다. `video_generator/openwebui/`에서
이관했습니다(원본 커밋 `6686a89`). **이 디렉터리가 유일한 소유자입니다.** video_generator
쪽은 아카이브 상태로 동결했으므로 그곳의 파일을 수정하거나 배포하지 않습니다.

## 함수

| 파일 | OWU 표시 이름 | `FN_ID` | 백엔드 | DaolVision에서 동작 여부 |
|---|---|---|---|---|
| `openwebui_anim_function.py` | Animation Video Agent | `animation_video_agent` | 게이트웨이 `:8700` | **동작함**(서비스 있음) |
| `openwebui_function.py` | Wan2.2 TI2V-5B | `hunyuanvideo_1_5` | Wan diffusers `:8500` | 동작하지 않음(서버 없음) |
| `openwebui_animate_function.py` | Wan2.2 Animate 14B | `wan2_2_animate_14b` | Animate `:8600` | 동작하지 않음(서버 없음) |

`FN_ID`는 OWU DB에 이미 존재하는 행의 id이므로, 이 값을 바꾸면 배포가 실패합니다.
`hunyuanvideo_1_5`라는 이름은 HunyuanVideo를 사용하던 시절에 붙인 것이며 실제 백엔드는
Wan2.2-TI2V-5B입니다. 즉 이름만 예전 것으로 남아 있습니다.

### 동작하지 않는 두 함수를 다시 사용하려면

`:8500`과 `:8600` diffusers 서버는 Task 6.5에서 사용하지 않는다고 판단해 DaolVision에서
삭제했습니다. 원본이 `video_generator/hunyuan_server/`에 그대로 있으므로 거기에서 서버를
기동하면 이 함수들이 다시 연결됩니다. 모델 가중치는
`Wan-AI/Wan2.2-TI2V-5B-Diffusers`(약 23GB)와 `Wan-AI/Wan2.2-Animate-14B-Diffusers`(약 28GB)입니다.

`openwebui_function.py`가 수행하던 동작은 다음과 같습니다. 플래너 LLM이 단발 컷인지
멀티 컷인지 결정하고, 컷마다 캐릭터록을 적용한 시네마틱 프롬프트로 다시 작성한 뒤 Wan
`:8500`으로 생성하고, 결과를 이어 붙여 채팅에 인라인으로 렌더링합니다. 캐릭터록의 경우
참조 이미지(`woman_infront.png`)의 3D 애니메이션 화풍에 맞추는 문구가 프롬프트에
하드코딩되어 있습니다(`openwebui_function.py:123,138`). 이 화풍 고정 기능을 localAI UI
쪽으로 옮기는 작업은 아직 하지 않았습니다. `langgraph/style_presets.py`의 프리픽스 6종이
S1 파이프라인에 아직 연결되어 있지 않으므로, 그것을 연결하는 것이 실제로 해야 할 작업입니다.

## 배포

**OWU Function은 파일이 아니라 OWU의 sqlite DB(`function` 테이블)에 저장되어 있습니다.**
따라서 파일만 수정하면 아무 변화도 일어나지 않습니다. 각 함수에 대응하는 스크립트가 DB의
`content` 값을 갱신하고 컨테이너를 재시작해서 다시 컴파일하게 만듭니다.

```bash
./deploy_anim_function.sh       # Animation Video Agent
./deploy_function.sh            # Wan2.2 TI2V-5B
./deploy_animate_function.sh    # Wan2.2 Animate 14B
```

스크립트가 수행하는 작업은 문법 검증, `webui.db`의 타임스탬프 백업, `content` UPDATE,
`docker restart open-webui`, `/health` 대기 순서입니다. 대상 행이 없으면 실패하고 중단합니다.

경로는 **스크립트 자기 위치를 기준으로** 계산합니다(`BASH_SOURCE`). 이관하기 전에는
절대경로가 하드코딩되어 있어서, 복사본에서 실행해도 video_generator의 파일이 배포되는
문제가 있었습니다.

## Valves (OWU Admin → Functions → 톱니)

기본값이 `172.16.4.228`인 것은 이 값이 **컨테이너에서 바라본 호스트 IP**이기 때문입니다.
OWU가 도커 안에서 실행되므로 `127.0.0.1`을 쓰면 컨테이너 자기 자신을 가리키게 되어 연결에
실패합니다. 호스트 IP가 바뀌면 이 값을 수정합니다.

| 함수 | Valve | 기본값 |
|---|---|---|
| anim | `AGENT_URL` / `BROWSER_URL` | `http://172.16.4.228:8700` |
| ti2v | `SERVER_URL` / `VIDEO_BASE_URL` | `http://172.16.4.228:8500` |
| ti2v | `OLLAMA_URL` | `http://172.16.4.228:11434/api/chat` |
| animate | `SERVER_URL` / `VIDEO_BASE_URL` | `http://172.16.4.228:8600` |

## 검증

```bash
cd ../langgraph && ./.venv/bin/python tests/test_anim_function.py
```

OWU UI 없이 멀티턴 승인 대화를 시뮬레이션합니다. 이 디렉터리의
`openwebui_anim_function.py`를 직접 로드하므로, 파일을 수정했다면 배포하기 전에 이
테스트에서 먼저 문제를 발견할 수 있습니다.

## 관리 규칙

- 수정할 때에는 **이 디렉터리의 파일을 수정하고 배포 스크립트를 실행합니다.** OWU Admin
  UI에서 직접 편집하면 다음 배포 때 조용히 덮어써집니다.
- `FN_ID`는 수정하지 않습니다.
- 백엔드가 없는 함수(`:8500`/`:8600`)도 삭제하지 않고 둡니다. 구현 이력을 보존하는 것이
  목적이며, 서버만 다시 기동하면 그대로 동작하기 때문입니다.
