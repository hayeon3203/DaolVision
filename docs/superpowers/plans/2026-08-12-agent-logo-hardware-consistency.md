# 가상 기업 로고 + 하드웨어 장비 영상 일관성 스파이크 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** DaolFusion 로고 + NVIDIA 파트너 배지가 붙은 GB10 워크스테이션 참조 이미지 1장을 만들고, `langgraph/` agent 파이프라인(`:8700`)의 기존 nonhuman `subject_ref`(`character_ref`) 경로로 4씬 "하루 몽타주" 영상에 로고를 일관되게 태울 수 있는지 실측한다. 스크립트/API 직호출 결과와 실제 LocalAI UI(GatewayAgent 채팅+승인게이트) 결과를 나란히 비교해, 과거(Task 6.16/6.12) 재발했던 "테스트는 통과했는데 프론트에서 다르다" 문제가 이번에도 나타나는지 확인한다.

**Architecture:** 신규 모델/그래프 없음. (1) Pillow로 로고 2개를 GB10 사진에 결정론적으로 오버레이해 참조 이미지 생성 (AI 합성이 아님 — 로고 픽셀 정확도를 보장하기 위해 `tools.py`의 기존 Flux Kontext I2I 대신 선택, 설계문서 대비 구현 결정 사항). (2) `tests/probe_*.py` 패턴으로 `tools.generate_subject_ref_clip`을 씬분할 없이 직접 호출하는 Phase 1 격리 프로브. (3) `driver.py` 패턴(자동승인 payload + `graph.ainvoke`)으로 전체 파이프라인을 직접 호출하는 Phase 2(a). (4) 동일 시나리오를 실제 LocalAI UI로 수동 실행하는 Phase 2(b) — 이건 사람이 브라우저에서 직접 밟는다. (5) 다섯 결과물(Phase1 클립, 2a 로그, 2a 클립, 2b 기록, 2b 클립)을 한 표로 비교하고 Plans.md/설계문서에 결과를 남긴다.

**Tech Stack:** Python 3(`langgraph/.venv`), Pillow, LangGraph(`graph.py`/`driver.py` 패턴), ComfyUI(`:8188`, Flux-schnell/LTX-Video), LocalAI UI(`localai-ui/`, GatewayAgent).

## Global Constraints

- 새 모델·새 ComfyUI 그래프·새 의존성 도입 금지 (설계문서 "범위 밖"). Pillow는 이미 `langgraph/.venv`에 있는지 Task 1에서 확인만 하고, 없으면 그 venv에만 추가한다(신규 서비스 아님).
- 실행은 전부 `cd /home/admin/DaolVision/langgraph && ./.venv/bin/python ...` 기준.
- `:8188`(ComfyUI), `:8700`(agent API) 이 이미 떠 있어야 Phase 1/2(a)가 동작한다 — 안 떠 있으면 태스크 시작 전에 기동 상태를 `curl -sf http://127.0.0.1:8188/system_stats`, `curl -sf http://127.0.0.1:8700/health`로 확인.
- Acceptance 컬럼에 `|| echo skip`류 항상-성공 패턴 금지(Plans.md 규칙). 육안 검증만 가능한 단계는 "-"로 명시하고 결과를 파일로 남긴다.
- 로고 원본 파일은 절대 리사이즈 없이 원본 그대로 저장소에 유지 — 합성 스크립트는 항상 원본을 읽어 매번 새로 리사이즈한다(중간 손실 누적 방지).

---

### Task 1: 듀얼 로고 참조 이미지 합성 스크립트

**Files:**
- Create: `langgraph/tests/probe_logo_hw_compose.py`
- Create (디렉토리만, 파일은 사용자가 채움): `langgraph/jobs/probe_logo_hw/assets/`
- Test: 스크립트 자체가 검증 대상 (별도 pytest 없음 — 산출 이미지 육안 확인)

**Interfaces:**
- Consumes: 없음(신규)
- Produces: `langgraph/jobs/probe_logo_hw/assets/ref_composite.png` — Task 2/3/4가 이 파일 경로를 참조 이미지로 사용.

- [ ] **Step 1: 에셋 디렉토리 준비 + 사용자 입력 대기**

```bash
mkdir -p /home/admin/DaolVision/langgraph/jobs/probe_logo_hw/assets
cp "/home/admin/DaolVision/DaolFusion_세로_tree.png" \
   /home/admin/DaolVision/langgraph/jobs/probe_logo_hw/assets/logo_daolfusion.png
cp /home/admin/DaolVision/NVIDIA.png \
   /home/admin/DaolVision/langgraph/jobs/probe_logo_hw/assets/logo_nvidia.png
```

사용자가 GB10 워크스테이션 사진을
`langgraph/jobs/probe_logo_hw/assets/device_gb10.jpg`(또는 `.png`)로 넣을 때까지
대기한다 — 이 파일 없이는 다음 스텝 실행 불가.

- [ ] **Step 2: 합성 스크립트 작성**

```python
"""DaolFusion 로고 + NVIDIA 파트너 배지를 GB10 워크스테이션 사진에 오버레이해
subject_ref 참조 이미지를 만든다. AI 합성(Flux Kontext I2I) 대신 Pillow 결정론
오버레이를 쓴다 — 로고 픽셀이 프롬프트 해석에 좌우되지 않고 항상 원본 그대로
나오게 하기 위함(2026-08-12 설계문서 대비 구현 결정, 로고 정확도 보장이 원래
의도였으므로 방향은 동일).

실행: cd langgraph && ./.venv/bin/python tests/probe_logo_hw_compose.py
"""
from pathlib import Path

from PIL import Image

ASSETS = Path(__file__).resolve().parent.parent / "jobs" / "probe_logo_hw" / "assets"


def _find_device_photo() -> Path:
    for ext in ("jpg", "jpeg", "png"):
        p = ASSETS / f"device_gb10.{ext}"
        if p.exists():
            return p
    raise FileNotFoundError(
        f"{ASSETS}/device_gb10.{{jpg,png}} 없음 — GB10 워크스테이션 사진을 먼저 넣어라."
    )


def compose(
    device_path: Path,
    main_logo_path: Path,
    badge_logo_path: Path,
    out_path: Path,
    *,
    main_logo_width_ratio: float = 0.14,
    main_logo_center_x_ratio: float = 0.43,
    main_logo_center_y_ratio: float = 0.60,
    badge_width_ratio: float = 0.06,
    badge_center_x_ratio: float = 0.875,
    badge_center_y_ratio: float = 0.44,
) -> Path:
    """위치 기본값은 `nvidia-blackwell-products-gb10-update.png`(2500x2000,
    투명 배경 + 대각선 앵글의 박스 하나) 기준으로 실측 조정됨:
    - main_logo: 정면 그릴(허니콤) 패널 중앙 — 원래 있던 "DELL" 워드마크를
      DaolFusion 로고로 덮어서 가린다.
    - badge: 오른쪽 위로 기울어진 광택 측면 패널 위 — 캔버스 우하단 모서리가
      아니라(투명 여백이 넓어 거기 두면 장비에서 붕 뜬다) 장비 몸체 위의 좌표.
    다른 사진으로 바꾸면 이 네 값을 그 사진에 맞게 다시 잡아야 한다."""
    device = Image.open(device_path).convert("RGBA")
    dw, dh = device.size

    main_logo = Image.open(main_logo_path).convert("RGBA")
    main_w = int(dw * main_logo_width_ratio)
    main_h = int(main_logo.height * (main_w / main_logo.width))
    main_logo = main_logo.resize((main_w, main_h), Image.LANCZOS)
    main_x = int(dw * main_logo_center_x_ratio - main_w / 2)
    main_y = int(dh * main_logo_center_y_ratio - main_h / 2)
    device.alpha_composite(main_logo, (main_x, main_y))

    badge = Image.open(badge_logo_path).convert("RGBA")
    badge_w = int(dw * badge_width_ratio)
    badge_h = int(badge.height * (badge_w / badge.width))
    badge = badge.resize((badge_w, badge_h), Image.LANCZOS)
    badge_x = int(dw * badge_center_x_ratio - badge_w / 2)
    badge_y = int(dh * badge_center_y_ratio - badge_h / 2)
    device.alpha_composite(badge, (badge_x, badge_y))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    device.convert("RGB").save(out_path, "PNG")
    return out_path


def main() -> int:
    device_path = _find_device_photo()
    out = compose(
        device_path=device_path,
        main_logo_path=ASSETS / "logo_daolfusion.png",
        badge_logo_path=ASSETS / "logo_nvidia.png",
        out_path=ASSETS / "ref_composite.png",
    )
    print(f"합성 완료: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 3: 실행 + 육안 확인**

Run: `cd /home/admin/DaolVision/langgraph && ./.venv/bin/python tests/probe_logo_hw_compose.py`
Expected: `합성 완료: .../ref_composite.png` 출력, 파일 생성됨.

`ref_composite.png`를 Read 도구로 열어 확인: (1) 원본 사진의 "DELL" 워드마크가
DaolFusion 로고에 완전히 가려졌는지 — 글자 일부라도 로고 밖으로 삐져나오면
`main_logo_width_ratio`를 키우거나 `main_logo_center_*_ratio`를 그릴 중앙(글자
있던 자리)에 더 정확히 맞춘다. (2) NVIDIA 배지가 장비 몸체(오른쪽 광택 패널) 위에
자연스럽게 얹혀 있고 캔버스 여백(검정/투명 영역)에 붕 떠 있지 않은지. 안 맞으면
Step 2의 `*_ratio` 파라미터를 조정하고 재실행(결정론적이라 같은 파라미터면 항상
같은 결과 — 반복 조정 허용).

- [ ] **Step 4: 커밋**

```bash
cd /home/admin/DaolVision
git add langgraph/tests/probe_logo_hw_compose.py
git commit -m "test: 듀얼 로고 GB10 워크스테이션 합성 프로브 스크립트 추가"
```

`langgraph/jobs/`는 저장소 `.gitignore`에 이미 잡혀 있다(job 산출물 전반이
비커밋 대상) — `assets/*.png`(로고 원본·합성 참조 이미지)도 자동으로 이 규칙을
따르므로 강제 추가하지 않는다. 스크립트만 커밋하고, 에셋은 로컬에 그대로 둔다.

---

### Task 2: Phase 1 격리 프로브 — subject_ref 모델 자체 능력 확인

**Files:**
- Create: `langgraph/tests/probe_logo_hw_phase1.py`
- Test: 스크립트 실행 자체가 검증 (4개 mp4 산출물 육안 비교)

**Interfaces:**
- Consumes: `langgraph/jobs/probe_logo_hw/assets/ref_composite.png` (Task 1 산출물)
- Produces: `langgraph/jobs/probe_logo_hw/clip1.mp4` ~ `clip4.mp4` — Task 5 비교 표에서
  "Phase 1" 행으로 사용.

- [ ] **Step 1: 프로브 스크립트 작성**

`tests/probe_subject_ref_camera.py` 패턴을 그대로 따른다(4씬 하루 몽타주로 확장).

```python
"""로고+GB10 합성 이미지로 4씬 subject_ref 클립을 씬분할/승인게이트 없이 직접
생성 — 파이프라인 배선 문제와 모델 자체의 로고 유지 능력을 분리해서 본다.

실행: cd langgraph && ./.venv/bin/python tests/probe_logo_hw_phase1.py
결과: langgraph/jobs/probe_logo_hw/clip1.mp4 ~ clip4.mp4
"""
import asyncio
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import tools  # noqa: E402
from nodes import node_generate_prompts, scene_seed  # noqa: E402

JOB_ID = "probe_logo_hw"
SRC_IMAGE = (
    Path(__file__).resolve().parent.parent
    / "jobs" / "probe_logo_hw" / "assets" / "ref_composite.png"
)

SCENES_TEXT = [
    ("시네마틱한 아침 햇살 아래, 사람이 출근 준비를 하는 동안 책상 위 DaolFusion "
     "GB10 워크스테이션이 이미 조용히 켜져 데이터를 정리하고 있다.", "calm"),
    ("낮, 사무실에서 사람은 회의와 창작에 몰입하고 워크스테이션은 화면에 진행률을 "
     "띄운 채 반복 작업을 대신 처리한다.", "neutral"),
    ("저녁, 사람이 가족과 식탁에 둘러앉아 웃는 동안 워크스테이션은 거실 한쪽에서 "
     "여전히 조용히 켜져 있다.", "happy"),
    ("밤, 다들 잠든 집 안에서 워크스테이션의 로고만 은은히 빛나며 여전히 "
     "작동하고 있다.", "calm"),
]


async def main() -> int:
    ref_name = "img_0.png"
    shutil.copyfile(SRC_IMAGE, str(tools.refs_dir(JOB_ID) / ref_name))

    scenes = [
        {
            "id": i + 1,
            "text": text,
            "duration": 3.0,
            "mood": mood,
            "matched_image": ref_name,
            "image_role": "character_ref",   # 강제 SUBJECT_REF — Task 6.17 단일참조 경로와 동일
            "quality_flag": "pending",
            "approved": False,
        }
        for i, (text, mood) in enumerate(SCENES_TEXT)
    ]
    state = {
        "job_id": JOB_ID,
        "script_text": " ".join(t for t, _ in SCENES_TEXT),
        "ref_captions": {},
        "wardrobe_locks": {},
        "image_query": "",
        "scenes": scenes,
    }

    print("[1/2] style_bible + 씬 프롬프트 생성 중 (cinematic)…")
    state.update(await node_generate_prompts(state))

    for scene in state["scenes"]:
        assert scene["mode"] == "SUBJECT_REF", f"scene {scene['id']}: mode={scene['mode']}"
        print(f"scene {scene['id']} prompt: {scene['prompt']}")

    print("[2/2] SUBJECT_REF 클립 4개 생성 중 (ComfyUI :8188)…")
    for scene in state["scenes"]:
        clip_path = await tools.generate_subject_ref_clip(
            job_id=JOB_ID, scene_id=scene["id"], prompt=scene["prompt"],
            ref_image=ref_name, duration=scene["duration"],
            seed=scene_seed(JOB_ID, scene["id"]), force_new=True,
        )
        print(f"  scene {scene['id']} -> {clip_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
```

- [ ] **Step 2: 실행**

Run: `cd /home/admin/DaolVision/langgraph && ./.venv/bin/python tests/probe_logo_hw_phase1.py`
Expected: 에러 없이 종료, `scene N -> .../clipN.mp4` 4줄 출력, 각 mp4가
`langgraph/jobs/probe_logo_hw/`에 생성됨. (`node_generate_prompts`/`_make_style_bible`
에는 스타일을 강제 지정하는 입력 필드가 없다 — `nodes.py:659` 확인 결과 style_bible은
전적으로 script_text/씬 텍스트에서 LLM이 유추한다. 그래서 cinematic 톤을 유도하려면
씬 텍스트 자체에 "시네마틱한" 같은 표현을 넣는다 — 위 `SCENES_TEXT`에 이미 반영됨.
새 style 파라미터를 코드에 추가하지 않는다, Global Constraints의 "새 기능 도입 금지"
위반.)

- [ ] **Step 3: 육안 기록**

4개 mp4를 각 프레임 캡처해(`ffmpeg -i clipN.mp4 -vf fps=1 clipN_%02d.png`) 로고가
매 씬 원본과 같은 실루엣/색으로 유지되는지, NVIDIA 배지가 뭉개지거나 사라지지
않는지 표로 기록한다 (씬 번호 / DaolFusion 로고 상태 / NVIDIA 배지 상태 /
비고). 이 표는 Task 5의 최종 비교표 왼쪽 열이 된다.

- [ ] **Step 4: 커밋**

```bash
cd /home/admin/DaolVision
git add langgraph/tests/probe_logo_hw_phase1.py
git commit -m "test: 로고+GB10 subject_ref Phase 1 격리 프로브 추가"
```

(mp4 산출물 자체는 용량이 크면 커밋하지 않고 기록 표에 경로만 남긴다.)

---

### Task 3: Phase 2(a) — 스크립트/API 직호출 전체 파이프라인

**Files:**
- Create: `langgraph/tests/probe_logo_hw_phase2a.py`
- Test: 실행 자체가 검증 (최종 mp4 + 비교 지점 JSON 로그)

**Interfaces:**
- Consumes: `langgraph/jobs/probe_logo_hw/assets/ref_composite.png` (Task 1)
- Produces: `langgraph/jobs/probe_logo_hw/phase2a_log.json` (씬별
  `matched_image`/`subject_type`/`mode`/`prompt`/seed), 최종 합본 mp4 경로 —
  Task 5가 이 JSON과 Task 4의 수동 기록을 나란히 비교.

- [ ] **Step 1: 스크립트 작성**

`driver.py`의 `_auto_decision`/`graph.ainvoke` 패턴을 그대로 쓰되 `--dry` 패치
(`_install_fakes`)는 적용하지 않는다(실서버 호출).

```python
"""로고+GB10 하루 몽타주 시나리오를 그래프 직호출(HTTP API 아님, driver.py와
동일하게 graph.ainvoke 직접 호출)로 끝까지 실행 — 승인게이트는 자동승인.
Phase 2(b)의 실제 UI 실행과 같은 입력으로 비교하기 위한 스크립트/API측 기준선.

실행: cd langgraph && ./.venv/bin/python tests/probe_logo_hw_phase2a.py
결과: jobs/<job_id>/final_video.mp4, jobs/probe_logo_hw/phase2a_log.json
"""
import asyncio
import base64
import json
import uuid
from pathlib import Path

from langgraph.types import Command

import tools
from graph import compile_graph

REF_IMAGE = (
    Path(__file__).resolve().parent.parent
    / "jobs" / "probe_logo_hw" / "assets" / "ref_composite.png"
)
LOG_PATH = (
    Path(__file__).resolve().parent.parent
    / "jobs" / "probe_logo_hw" / "phase2a_log.json"
)

SCRIPT_TEXT = (
    "시네마틱한 아침 햇살 아래, 사람이 출근 준비를 하는 동안 책상 위 DaolFusion "
    "GB10 워크스테이션이 이미 조용히 켜져 데이터를 정리하고 있다. 낮, 사무실에서 사람은 회의와 창작에 "
    "몰입하고 워크스테이션은 화면에 진행률을 띄운 채 반복 작업을 대신 처리한다. "
    "저녁, 사람이 가족과 식탁에 둘러앉아 웃는 동안 워크스테이션은 거실 한쪽에서 "
    "여전히 조용히 켜져 있다. 밤, 다들 잠든 집 안에서 워크스테이션의 로고만 "
    "은은히 빛나며 여전히 작동하고 있다."
)


def _auto_decision(cp: dict) -> dict:
    name = cp.get("checkpoint", "")
    if name.startswith("1-4"):
        return {"approved": True}
    if name.startswith("2-3"):
        return {"approved": True}
    if name.startswith("3-5"):
        return {"action": "approve_all"}
    if name.startswith("4-5"):
        return {"approved": True}
    raise RuntimeError(f"알 수 없는 체크포인트: {cp}")


async def main() -> int:
    job_id = f"logohw2a-{uuid.uuid4().hex[:8]}"
    graph = await compile_graph(str(tools.JOBS_DIR / f"checkpoints_{job_id}.db"))
    config = {"configurable": {"thread_id": job_id}}

    ref_b64 = base64.b64encode(REF_IMAGE.read_bytes()).decode()
    print(f"[job {job_id}] 시작", flush=True)
    result = await graph.ainvoke(
        {
            "job_id": job_id,
            "script_text": SCRIPT_TEXT,
            "ref_images": [f"data:image/png;base64,{ref_b64}"],
            "scenes": [],
            "clip_results": [],
            "regen_target_ids": [],
        },
        config=config,
    )
    while True:
        snapshot = await graph.aget_state(config)
        interrupts = [i for t in snapshot.tasks for i in (getattr(t, "interrupts", ()) or ())]
        if not interrupts:
            break
        cp = interrupts[0].value
        decision = _auto_decision(cp)
        print(f"  checkpoint {cp.get('checkpoint')} -> {decision}", flush=True)
        result = await graph.ainvoke(Command(resume=decision), config=config)

    final_state = (await graph.aget_state(config)).values
    log = {
        "job_id": job_id,
        "final_video_path": final_state.get("final_video_path"),
        "scenes": [
            {
                "id": s.get("id"),
                "matched_image": s.get("matched_image"),
                "subject_type": s.get("subject_type"),
                "image_role": s.get("image_role"),
                "mode": s.get("mode"),
                "prompt": s.get("prompt"),
                "mood": s.get("mood"),
            }
            for s in final_state.get("scenes", [])
        ],
    }
    LOG_PATH.write_text(json.dumps(log, ensure_ascii=False, indent=2))
    print(f"\n최종 영상: {final_state.get('final_video_path')}")
    print(f"로그: {LOG_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
```

- [ ] **Step 2: 실행**

Run: `cd /home/admin/DaolVision/langgraph && ./.venv/bin/python tests/probe_logo_hw_phase2a.py`
Expected: 각 checkpoint 자동승인 로그 출력 후 "최종 영상: ..." 경로 출력,
`phase2a_log.json` 생성됨. `subject_type`이 4씬 모두 `"nonhuman"`, `image_role`이
모두 `"character_ref"`인지 `cat jobs/probe_logo_hw/phase2a_log.json`으로 확인 —
아니면 Task 5에서 원인 조사 대상으로 기록(리스크 1 재현 사례).

- [ ] **Step 3: 커밋**

```bash
cd /home/admin/DaolVision
git add langgraph/tests/probe_logo_hw_phase2a.py
git commit -m "test: 로고+GB10 Phase 2a 스크립트 직호출 프로브 추가"
```

---

### Task 4: Phase 2(b) — 실제 LocalAI UI 수동 실행 절차

**Files:**
- Create: `langgraph/jobs/probe_logo_hw/phase2b_manual_record.md`

**Interfaces:**
- Consumes: `langgraph/jobs/probe_logo_hw/assets/ref_composite.png` (Task 1),
  Task 3의 `SCRIPT_TEXT`(동일 시나리오 원문을 그대로 붙여넣는다)
- Produces: 채워진 `phase2b_manual_record.md` — Task 5 비교표 오른쪽 열.

이 태스크는 자동화하지 않는다 — 검증 대상 자체가 "실제 사람이 브라우저에서
UI를 조작했을 때의 결과"이므로 사람이 직접 진행한다.

- [ ] **Step 1: 기록 템플릿 작성**

```markdown
# Phase 2(b) 수동 실행 기록 — LocalAI UI GatewayAgent

날짜: ____ · 실행자: ____

## 절차
1. `localai-ui` 개발 서버 기동 확인, `/app/gw-agent`로 이동.
2. 채팅창에 `langgraph/jobs/probe_logo_hw/assets/ref_composite.png` 첨부.
3. 시나리오 원문(Task 3의 SCRIPT_TEXT와 동일 문자열) 그대로 입력.
4. 체크포인트 1-4(씬분할 리뷰) — 각 씬 subject_type/matched_image 표시값 기록.
5. 체크포인트 2-3(이미지 리뷰) — 있다면 표시된 참조 이미지가 ref_composite.png와
   동일한지 확인.
6. 체크포인트 3-5(클립 리뷰) — 각 클립의 로고 상태 육안 기록, approve_all.
7. 완료 후 최종 영상 다운로드.

## 기록표

| 씬 | UI에 표시된 subject_type | UI에 표시된 matched_image | 로고 상태(육안) | 비고 |
|---|---|---|---|---|
| 1 | | | | |
| 2 | | | | |
| 3 | | | | |
| 4 | | | | |

## 최종 영상 경로
____

## Phase 2(a)와 다른 점(있다면)
____
```

- [ ] **Step 2: 사용자가 절차대로 실행하고 표를 채운다**

(agentic worker가 대신 실행할 수 없는 단계 — 사용자 실행 대기.)

- [ ] **Step 3: 커밋**

```bash
cd /home/admin/DaolVision
git add langgraph/jobs/probe_logo_hw/phase2b_manual_record.md
git commit -m "docs: 로고+GB10 Phase 2b 수동 UI 실행 기록"
```

---

### Task 5: 결과 비교 정리 + Plans.md/설계문서 반영

**Files:**
- Modify: `Plans.md` (Week 6 표에 Task 6.20 추가)
- Modify: `docs/superpowers/specs/2026-08-12-agent-logo-hardware-consistency-design.md`
  ("검증" 섹션 뒤에 "결과" 섹션 추가)

**Interfaces:**
- Consumes: Task 2 육안 기록, Task 3 `phase2a_log.json`, Task 4
  `phase2b_manual_record.md`
- Produces: 없음(문서 최종화, 이후 태스크가 이 결과를 소비할 일 없음)

- [ ] **Step 1: 비교표 작성**

Task 2/3/4 산출물을 하나의 표로 합친다 — 설계문서의 "비교 지점" 5가지
(matched_image/subject_type, 최종 프롬프트, seed, 그래프 파라미터, 로고 육안
비교) 각각에 대해 Phase 1 / 2(a) / 2(b) 값을 나열하고 일치 여부 표시.

- [ ] **Step 2: 설계문서에 결과 섹션 추가**

`docs/superpowers/specs/2026-08-12-agent-logo-hardware-consistency-design.md`
끝에 `## 결과` 섹션을 추가해 Step 1 표 + 결론(로고 일관성 성공/실패, 스크립트-UI
일치 여부, 발견된 리스크 요인 1~5 중 실제로 재현된 것) + 후속 권고(정식
기능화할지, 추가 스파이크가 필요한지)를 기록한다.

- [ ] **Step 3: Plans.md에 Task 6.20 추가**

`| 6.20 | ... |` 행을 6.19 다음에 추가 — 기존 6.19 형식(실측 스파이크, 발견/조치/
미해결 항목 인라인 기술)을 따른다. Acceptance 컬럼은 기계 검증 불가 항목이므로
"-", DoD는 "결과 섹션에 로고 일관성 판정 + 스크립트-UI 일치 여부 기록됨"으로
작성. Status는 실행 완료 후 `cc:완료`로 갱신.

- [ ] **Step 4: 커밋**

```bash
cd /home/admin/DaolVision
git add Plans.md docs/superpowers/specs/2026-08-12-agent-logo-hardware-consistency-design.md
git commit -m "docs: 로고+GB10 일관성 스파이크 결과 정리, Plans.md Task 6.20 추가"
```
