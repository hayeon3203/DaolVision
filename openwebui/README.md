# Open WebUI Function 3종

Open WebUI 채팅창에서 이 스택을 쓰던 경로. `video_generator/openwebui/`에서 이관했다
(원본 커밋 `6686a89`). **이 디렉터리가 유일한 소유자다** — video_generator 쪽은 아카이브라
동결이니 거기 파일을 고치거나 배포하지 마라.

## 함수

| 파일 | OWU 표시 이름 | `FN_ID` | 백엔드 | DaolVision에서 도는가 |
|---|---|---|---|---|
| `openwebui_anim_function.py` | Animation Video Agent | `animation_video_agent` | 게이트웨이 `:8700` | **예** — 서비스 있음 |
| `openwebui_function.py` | Wan2.2 TI2V-5B | `hunyuanvideo_1_5` | Wan diffusers `:8500` | 아니오 — 서버 없음 |
| `openwebui_animate_function.py` | Wan2.2 Animate 14B | `wan2_2_animate_14b` | Animate `:8600` | 아니오 — 서버 없음 |

`FN_ID`는 OWU DB의 기존 행 id라 바꾸면 배포가 깨진다. `hunyuanvideo_1_5`는 HunyuanVideo를
쓰던 시절의 잔재고 실제 백엔드는 Wan2.2-TI2V-5B다 — 이름만 옛것.

### 안 도는 둘을 살리려면

`:8500`·`:8600` diffusers 서버는 Task 6.5에서 DaolVision에선 지웠다(그때 미사용 판정).
`video_generator/hunyuan_server/`에 원본이 그대로 있으니 거기서 기동하면 이 함수들이 붙는다.
모델 가중치는 `Wan-AI/Wan2.2-TI2V-5B-Diffusers`(~23GB), `Wan-AI/Wan2.2-Animate-14B-Diffusers`(~28GB).

`openwebui_function.py`가 하던 것 — 플래너 LLM이 단발/멀티컷을 정하고, 컷마다 캐릭터록을
건 시네마틱 프롬프트로 재작성해서 Wan `:8500`으로 돌리고 이어붙여 채팅에 인라인 렌더.
캐릭터록은 참조 이미지(`woman_infront.png`)의 3D 애니메이션 화풍에 맞추는 문구가 프롬프트에
하드코딩돼 있다(`openwebui_function.py:123,138`). 이 화풍 고정을 localAI UI 쪽으로 옮기는
작업은 아직 안 했다 — `langgraph/style_presets.py`의 프리픽스 6종이 S1 파이프에 미배선이라
거기 배선하는 게 실제 할 일이다.

## 배포

**OWU Function은 파일이 아니라 OWU의 sqlite DB(`function` 테이블)에 산다.** 파일만 고치면
아무 일도 안 일어난다. 짝이 되는 스크립트가 DB `content`를 갱신하고 컨테이너를 재시작해
재컴파일시킨다.

```bash
./deploy_anim_function.sh       # Animation Video Agent
./deploy_function.sh            # Wan2.2 TI2V-5B
./deploy_animate_function.sh    # Wan2.2 Animate 14B
```

스크립트가 하는 일: 문법 검증 → `webui.db` 타임스탬프 백업 → `content` UPDATE →
`docker restart open-webui` → `/health` 대기. 대상 행이 없으면 실패하고 멈춘다.

경로는 **스크립트 자기 위치 기준**이다(`BASH_SOURCE`). 이관 전에는 절대경로가 박혀 있어서,
복사본에서 실행해도 video_generator 파일이 올라가는 함정이 있었다.

## Valves (OWU Admin → Functions → 톱니)

기본값이 `172.16.4.228`인 건 **컨테이너에서 본 호스트 IP**다 — OWU가 도커 안에서 돌기
때문에 `127.0.0.1`을 쓰면 컨테이너 자신을 가리켜 붙지 않는다. 호스트 IP가 바뀌면 여기를
고친다.

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

OWU UI 없이 멀티턴 승인 대화를 시뮬레이션한다. 이 디렉터리의
`openwebui_anim_function.py`를 직접 로드하므로, 파일을 고치면 배포 전에 여기서 먼저 걸린다.

## 관리 규칙

- 고칠 땐 **이 파일을 고치고 배포 스크립트를 돌린다.** OWU Admin UI에서 직접 편집하면 다음
  배포 때 조용히 덮어써진다.
- `FN_ID`는 건드리지 않는다.
- 백엔드가 없는 함수(`:8500`/`:8600`)도 지우지 않고 둔다 — 구현 히스토리 보존이 목적이고,
  서버만 다시 띄우면 그대로 돈다.
