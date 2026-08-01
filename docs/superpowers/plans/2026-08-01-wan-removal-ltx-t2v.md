# Wan2.2 백엔드 제거 → LTX-13B-distilled T2V/I2V 통합 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `tools.call_video()`(Wan2.2-TI2V-5B, :8500, 중국 원산)를 완전히 삭제하고, 씬 클립 생성의 T2V/I2V 폴백 경로를 이미 이 저장소에 있는 LTX-Video-0.9.8-13B-distilled(:8188 ComfyUI, Task 4.6이 이미 다운로드해둔 체크포인트)로 교체한다.

**Architecture:** `nodes.py:node_generate_one_clip`의 세 갈래 분기(SUBJECT_REF/STANDIN/그 외) 중 "그 외" 분기만 백엔드를 바꾼다. 새 함수 `generate_t2v_clip()`/`generate_i2v_fallback_clip()`이 `_generate_reference_clip()`(기존 STANDIN/SUBJECT_REF 경로)과 동일한 SQLite 기반 재개형(recoverable) ComfyUI job 추적 패턴을 공유 헬퍼 `_generate_ltx_job_clip()`로 재사용한다. 그래프 자체는 기존 `_build_ltx13b_graph()`(4.6, image-conditioned I2V)를 그대로 쓰거나(I2V 폴백), 그 형제 함수 `_build_ltx13b_t2v_graph()`(신규, 이미지 조건 없이 `EmptyLTXVLatentVideo`로 시작)를 쓴다(T2V). 신규 모델 다운로드 없음.

**Tech Stack:** Python 3.12 (langgraph/.venv), FastAPI, httpx, ComfyUI API-format 그래프(dict), SQLite(`comfy_prompts` 테이블, 기존 스키마 그대로), pytest 없이 `assert` 기반 self-check 스크립트(이 저장소 관례).

## Global Constraints

- 신규 모델 다운로드 금지 — LTX13B_CHECKPOINT/LTX13B_CLIP(Task 4.6 기존 상수) 그대로 재사용.
- `_generate_ltx_job_clip`은 `generate_i2v_oneshot`류 단순 폴링이 아니라 `_generate_reference_clip()`의 SQLite 재개형 패턴(큐/missing/exec 타임아웃, `_save_prompt`/`_recoverable_prompt`/`_update_prompt`)을 따른다 — `recoverable_comfy_jobs()`가 스캔하는 동일 `comfy_prompts` 테이블에 씀.
- `generate_t2v_clip`/`generate_i2v_fallback_clip`의 request_key 해시는 반드시 `prompt`를 포함한다 — 누락 시 씬 프롬프트 수정 후 재실행(`force_new=False`)에서 구프롬프트 캐시가 그대로 반환되는 stale-cache 버그가 남는다(스펙 self-review에서 이미 지적).
- `oom.phase("i2v")` 게이팅 그대로 유지 — Wan/STANDIN/SUBJECT_REF/오네샷이 이미 이 이름을 공유한다.
- `video_generator/`(별도 프로젝트 소유) 코드는 건드리지 않는다 — DaolVision이 그쪽을 호출하지 않게만 만든다. 단, **DaolVision 저장소 자체에 복제된 `inference_server/server.py` 등은 삭제 대상**이다 — 이건 별도 프로젝트가 아니라 이 저장소 안의 죽은 코드이고, `c4c36c4`(animate_server :8600 제거)가 이미 정확히 같은 상황에서 정확히 같은 조치를 한 전례가 있다.
- 출력 경로 컨벤션(`job_dir(job_id)/clip{scene_id}.mp4`) 불변 — ffmpeg concat/xfade 코드 무변경.
- 모든 GPU-프리 유닛테스트는 `./.venv/bin/python tests/<name>.py`로 단독 실행 가능해야 한다(이 저장소 관례, pytest 미사용).

---

### Task 1: LTX T2V 그래프 빌더 + 프레임 길이 헬퍼

**Files:**
- Modify: `langgraph/tools.py` (기존 `_build_ltx13b_graph()` 정의부, 약 593-635줄 바로 뒤에 추가)
- Test: `langgraph/tests/test_wan_removal.py` (신규)

**Interfaces:**
- Consumes: 기존 `LTX13B_CHECKPOINT`, `LTX13B_CLIP`, `LTX13B_STEPS`, `LTX13B_FPS`(모두 tools.py 상단에 이미 정의, 4.6) — import/신규 정의 불필요.
- Produces: `tools.to_ltx_len(frames: float) -> int`, `tools._build_ltx13b_t2v_graph(*, prompt: str, width: int, height: int, length: int, seed: int) -> dict` — Task 3이 이 둘을 그대로 호출.

- [ ] **Step 1: 실패하는 테스트 작성**

`langgraph/tests/test_wan_removal.py` 새로 생성:

```python
"""Wan2.2(:8500, 중국 원산) 백엔드 제거 검증 — docs/model-selection.md의
'비중국 원산' 원칙 위반 해소. T2V/I2V 폴백 씬을 LTX-Video-0.9.8-13B-distilled
(:8188 ComfyUI, Task 4.6이 이미 받아둔 체크포인트)로 통합.
ComfyUI 실호출 없이 GPU 없이 돈다 — 라이브 검증은 별도 수동 단계(플랜 Task 10).

    ./.venv/bin/python tests/test_wan_removal.py
"""
import asyncio
import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # langgraph/ 모듈 import용

import tools
import nodes


def test_to_ltx_len_snaps_to_8k_plus_1():
    assert tools.to_ltx_len(97) == 97       # 8*12+1, 이미 8k+1이면 그대로
    assert tools.to_ltx_len(1) == 25        # 최소 클램프
    assert tools.to_ltx_len(50) == 49       # 49(8*6+1, 차이1)가 57(8*7+1, 차이7)보다 가까움
    for n in (17, 33, 60, 100, 200):
        v = tools.to_ltx_len(n)
        assert (v - 1) % 8 == 0 and v >= 25, (n, v)
    print("ok: LTX length가 8k+1로 스냅되고 최소 25 유지")


def test_t2v_graph_has_no_image_nodes():
    graph = tools._build_ltx13b_t2v_graph(
        prompt="a robot waving", width=832, height=480, length=49, seed=7)
    assert not any(n["class_type"] in ("LoadImage", "LTXVImgToVideo")
                   for n in graph.values()), graph
    assert graph["7"]["class_type"] == "EmptyLTXVLatentVideo"
    assert graph["7"]["inputs"] == {
        "width": 832, "height": 480, "length": 49, "batch_size": 1}
    assert graph["9"]["inputs"]["positive"] == ["12", 0]
    assert graph["9"]["inputs"]["negative"] == ["12", 1]
    assert graph["9"]["inputs"]["latent_image"] == ["7", 0]
    assert graph["9"]["inputs"]["seed"] == 7
    assert graph["9"]["inputs"]["model"] == ["6", 0]
    assert graph["3"]["inputs"]["text"] == "a robot waving"
    assert graph["1"]["inputs"]["ckpt_name"] == tools.LTX13B_CHECKPOINT
    print("ok: T2V 그래프에 이미지 노드 없음, latent/조건 배선 정확")


def main():
    test_to_ltx_len_snaps_to_8k_plus_1()
    test_t2v_graph_has_no_image_nodes()


if __name__ == "__main__":
    main()
    sys.exit(0)
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd langgraph && ./.venv/bin/python tests/test_wan_removal.py`
Expected: `AttributeError: module 'tools' has no attribute 'to_ltx_len'`

- [ ] **Step 3: 구현**

`langgraph/tools.py`의 `_build_ltx13b_graph()` 함수(약 635줄) 바로 뒤, `generate_i2v_oneshot()` 정의 앞에 추가:

```python
def to_ltx_len(frames: float) -> int:
    """LTXV VAE 시공간 다운샘플 8 → length는 8k+1이어야 한다(LTX13B_FRAMES=97=8*12+1과
    동일 패턴, to_4k1의 LTX 8-배수 변형). 최소 25(≈1s@24fps)."""
    n = max(25, int(round(frames)))
    k = round((n - 1) / 8)
    return max(25, 8 * k + 1)


def _build_ltx13b_t2v_graph(
    *, prompt: str, width: int, height: int, length: int, seed: int,
) -> dict:
    """_build_ltx13b_graph(4.6, image-conditioned I2V)의 T2V 형제. LoadImage +
    LTXVImgToVideo 대신 EmptyLTXVLatentVideo로 순수 노이즈 latent에서 시작한다
    (이미지 조건 없음, Task 6.x Wan 제거 — docs/superpowers/specs/2026-08-01-
    wan-removal-ltx-t2v-design.md)."""
    return {
        "1": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": LTX13B_CHECKPOINT}},
        "2": {"class_type": "CLIPLoader",
              "inputs": {"clip_name": LTX13B_CLIP, "type": "ltxv"}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["2", 0]}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {
            "text": "worst quality, blurry, jittery, distorted, low resolution",
            "clip": ["2", 0],
        }},
        "6": {"class_type": "ModelSamplingLTXV",
              "inputs": {"model": ["1", 0], "max_shift": 2.05, "base_shift": 0.95}},
        "12": {"class_type": "LTXVConditioning", "inputs": {
            "positive": ["3", 0], "negative": ["4", 0], "frame_rate": float(LTX13B_FPS),
        }},
        "7": {"class_type": "EmptyLTXVLatentVideo", "inputs": {
            "width": width, "height": height, "length": length, "batch_size": 1,
        }},
        "8": {"class_type": "LTXVScheduler", "inputs": {
            "steps": LTX13B_STEPS, "max_shift": 2.05, "base_shift": 0.95,
            "stretch": True, "terminal": 0.1,
        }},
        "9": {"class_type": "KSampler", "inputs": {
            "model": ["6", 0], "seed": seed, "steps": LTX13B_STEPS, "cfg": 1.0,
            "sampler_name": "euler", "scheduler": "normal",
            "positive": ["12", 0], "negative": ["12", 1], "latent_image": ["7", 0],
            "denoise": 1.0,
        }},
        "10": {"class_type": "VAEDecode", "inputs": {"samples": ["9", 0], "vae": ["1", 2]}},
        "11": {"class_type": "SaveAnimatedWEBP", "inputs": {
            "images": ["10", 0], "filename_prefix": "t2v_job", "fps": LTX13B_FPS,
            "lossless": False, "quality": 90, "method": "default",
        }},
    }
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd langgraph && ./.venv/bin/python tests/test_wan_removal.py`
Expected: `ok: LTX length가 8k+1로 스냅되고 최소 25 유지` / `ok: T2V 그래프에 이미지 노드 없음, latent/조건 배선 정확` 둘 다 출력, exit 0.

- [ ] **Step 5: 커밋**

```bash
cd /home/admin/DaolVision
git add langgraph/tools.py langgraph/tests/test_wan_removal.py
git commit -m "feat: add LTX pure-T2V graph builder (Task 6.x Wan removal, 1/N)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 2: request_key 캐시 해시 순수 함수 2개

**Files:**
- Modify: `langgraph/tools.py`
- Test: `langgraph/tests/test_wan_removal.py`

**Interfaces:**
- Consumes: `hashlib`, `json`(이미 tools.py 상단에 import됨), Task 1의 `LTX13B_STEPS`/`LTX13B_FPS`, 기존 `WIDTH`/`HEIGHT`.
- Produces: `tools._t2v_request_key(scene_id, prompt, duration, seed) -> str`, `tools._i2v_fallback_request_key(scene_id, prompt, matched_image, duration, seed) -> str` — Task 3이 그대로 호출.

- [ ] **Step 1: 실패하는 테스트 작성**

`test_wan_removal.py`에 추가(`main()` 함수 앞):

```python
def test_t2v_request_key_changes_with_prompt_and_scene():
    k1 = tools._t2v_request_key(scene_id=3, prompt="a cat", duration=2.0, seed=None)
    k2 = tools._t2v_request_key(scene_id=3, prompt="a dog", duration=2.0, seed=None)
    k3 = tools._t2v_request_key(scene_id=4, prompt="a cat", duration=2.0, seed=None)
    assert len({k1, k2, k3}) == 3, "prompt 또는 scene_id 변화가 request_key에 반영 안 됨"
    print("ok: T2V request_key가 prompt/scene_id 변화를 반영(stale 캐시 방지)")


def test_i2v_fallback_request_key_changes_with_prompt_and_image():
    k1 = tools._i2v_fallback_request_key(
        scene_id=1, prompt="p1", matched_image="a.png", duration=2.0, seed=None)
    k2 = tools._i2v_fallback_request_key(
        scene_id=1, prompt="p2", matched_image="a.png", duration=2.0, seed=None)
    k3 = tools._i2v_fallback_request_key(
        scene_id=1, prompt="p1", matched_image="b.png", duration=2.0, seed=None)
    assert len({k1, k2, k3}) == 3, "prompt 또는 matched_image 변화가 request_key에 반영 안 됨"
    print("ok: I2V 폴백 request_key가 prompt/matched_image 변화를 반영")
```

`main()`을 아래로 교체:

```python
def main():
    test_to_ltx_len_snaps_to_8k_plus_1()
    test_t2v_graph_has_no_image_nodes()
    test_t2v_request_key_changes_with_prompt_and_scene()
    test_i2v_fallback_request_key_changes_with_prompt_and_image()
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd langgraph && ./.venv/bin/python tests/test_wan_removal.py`
Expected: `AttributeError: module 'tools' has no attribute '_t2v_request_key'`

- [ ] **Step 3: 구현**

`tools.py`의 `_build_ltx13b_t2v_graph()` 바로 뒤에 추가:

```python
def _t2v_request_key(scene_id: int, prompt: str, duration: float, seed: int | None) -> str:
    return hashlib.sha256(json.dumps({
        "scene_id": scene_id, "prompt": prompt, "duration": duration, "seed": seed,
        "steps": LTX13B_STEPS, "fps": LTX13B_FPS, "width": WIDTH, "height": HEIGHT,
        "workflow": "ltx13b_t2v_v1",  # 그래프 구조 바뀌면 캐시 무효화용 버전 문자열
    }, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _i2v_fallback_request_key(
    scene_id: int, prompt: str, matched_image: str, duration: float, seed: int | None,
) -> str:
    return hashlib.sha256(json.dumps({
        "scene_id": scene_id, "prompt": prompt, "matched_image": matched_image,
        "duration": duration, "seed": seed, "steps": LTX13B_STEPS, "fps": LTX13B_FPS,
        "width": WIDTH, "height": HEIGHT, "workflow": "ltx13b_i2v_fallback_v1",
    }, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd langgraph && ./.venv/bin/python tests/test_wan_removal.py`
Expected: 4개 테스트 전부 `ok:` 출력, exit 0.

- [ ] **Step 5: 커밋**

```bash
cd /home/admin/DaolVision
git add langgraph/tools.py langgraph/tests/test_wan_removal.py
git commit -m "feat: add request_key cache hashes for LTX T2V/I2V-fallback (2/N)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 3: 공유 ComfyUI job 헬퍼 + 두 wrapper + call_video/WAN_URL 삭제

**Files:**
- Modify: `langgraph/tools.py`
- Test: `langgraph/tests/test_wan_removal.py`

**Interfaces:**
- Consumes: Task 1(`to_ltx_len`, `_build_ltx13b_t2v_graph`, 기존 `_build_ltx13b_graph`), Task 2(두 request_key 함수), 기존 `COMFYUI_URL`, `STANDIN_QUEUE_TIMEOUT`, `STANDIN_MISSING_TIMEOUT`, `STANDIN_EXEC_TIMEOUT`, `_save_prompt`, `_recoverable_prompt`, `_update_prompt`, `job_dir`, `refs_dir`, `oom.phase`.
- Produces: `tools.generate_t2v_clip(job_id, scene_id, prompt, duration=2.0, seed=None, force_new=False) -> str`, `tools.generate_i2v_fallback_clip(job_id, scene_id, prompt, matched_image, duration=2.0, seed=None, force_new=False) -> str` — Task 4가 `nodes.py`에서 이 둘을 호출. `tools.call_video`/`tools.WAN_URL`은 이 태스크 이후 더 이상 존재하지 않는다.

- [ ] **Step 1: 실패하는 테스트 작성**

`test_wan_removal.py`에 `import inspect`(파일 상단에 이미 추가돼 있음, Step1에서 넣었음) 사용해 추가:

```python
def test_call_video_and_wan_url_removed():
    assert not hasattr(tools, "call_video"), "call_video가 남아있음 — Wan 배제 목적 위반"
    assert not hasattr(tools, "WAN_URL"), "WAN_URL이 남아있음"
    print("ok: call_video/WAN_URL 완전 제거")


def test_new_wrapper_signatures():
    t2v_params = list(inspect.signature(tools.generate_t2v_clip).parameters)
    assert t2v_params == ["job_id", "scene_id", "prompt", "duration", "seed", "force_new"], t2v_params
    i2v_params = list(inspect.signature(tools.generate_i2v_fallback_clip).parameters)
    assert i2v_params == [
        "job_id", "scene_id", "prompt", "matched_image", "duration", "seed", "force_new",
    ], i2v_params
    print("ok: generate_t2v_clip/generate_i2v_fallback_clip 시그니처 확정")
```

`main()`에 두 줄 추가:

```python
def main():
    test_to_ltx_len_snaps_to_8k_plus_1()
    test_t2v_graph_has_no_image_nodes()
    test_t2v_request_key_changes_with_prompt_and_scene()
    test_i2v_fallback_request_key_changes_with_prompt_and_image()
    test_call_video_and_wan_url_removed()
    test_new_wrapper_signatures()
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd langgraph && ./.venv/bin/python tests/test_wan_removal.py`
Expected: `AssertionError: call_video가 남아있음 — Wan 배제 목적 위반` (call_video가 아직 존재하므로)

- [ ] **Step 3: 구현 — 공유 헬퍼 + wrapper 추가**

`tools.py`의 `_i2v_fallback_request_key()` 바로 뒤에 추가:

```python
async def _generate_ltx_job_clip(
    job_id: str, scene_id: int, graph: dict, request_key: str, force_new: bool,
) -> str:
    """T2V/I2V 폴백 공용 — _generate_reference_clip(STANDIN/SUBJECT_REF)과 동일한
    SQLite 재개형 패턴(큐/missing/exec 타임아웃)을 그래프 dict만 바꿔 재사용한다."""
    async with (
        oom.phase("i2v"),
        httpx.AsyncClient(timeout=httpx.Timeout(connect=10.0, read=60.0, write=60.0, pool=None)) as client,
    ):
        existing = None if force_new else _recoverable_prompt(job_id, scene_id, request_key)
        if existing:
            prompt_id = existing["prompt_id"]
        else:
            resp = await client.post(f"{COMFYUI_URL}/prompt", json={"prompt": graph})
            resp.raise_for_status()
            prompt_id = resp.json()["prompt_id"]
            _save_prompt(prompt_id, job_id, scene_id, request_key)

        submitted_at = float(existing["submitted_at"]) if existing else time.time()
        execution_started_at = (float(existing["execution_started_at"])
                                if existing and existing["execution_started_at"] else None)
        missing_since = None
        media = None
        while True:
            await asyncio.sleep(2.0)
            h = (await client.get(f"{COMFYUI_URL}/history/{prompt_id}")).json()
            if prompt_id not in h:
                queue = (await client.get(f"{COMFYUI_URL}/queue")).json()
                running_ids = {item[1] for item in queue.get("queue_running", [])}
                pending_ids = {item[1] for item in queue.get("queue_pending", [])}
                if prompt_id in running_ids:
                    if execution_started_at is None:
                        execution_started_at = time.time()
                    _update_prompt(prompt_id, "running",
                                   execution_started_at=execution_started_at)
                elif prompt_id in pending_ids:
                    _update_prompt(prompt_id, "queued")
                elif time.time() - submitted_at > STANDIN_QUEUE_TIMEOUT:
                    msg = f"씬 {scene_id}: ComfyUI 큐에서 {STANDIN_QUEUE_TIMEOUT:.0f}s 내 시작되지 않음"
                    _update_prompt(prompt_id, "error", error=msg)
                    raise TimeoutError(msg)
                else:
                    missing_since = missing_since or time.time()
                    if time.time() - missing_since > STANDIN_MISSING_TIMEOUT:
                        msg = (f"씬 {scene_id}: ComfyUI prompt가 history/queue에서 사라짐 "
                               f"(prompt_id={prompt_id})")
                        _update_prompt(prompt_id, "error", error=msg)
                        raise TimeoutError(msg)
                if prompt_id in running_ids or prompt_id in pending_ids:
                    missing_since = None
                if execution_started_at and time.time() - execution_started_at > STANDIN_EXEC_TIMEOUT:
                    msg = (f"씬 {scene_id}: LTX 실행이 {STANDIN_EXEC_TIMEOUT:.0f}s를 초과함 "
                           f"(prompt_id={prompt_id})")
                    _update_prompt(prompt_id, "error", error=msg)
                    raise TimeoutError(msg)
                continue
            status = h[prompt_id]["status"]
            for kind, data in status.get("messages", []):
                if kind == "execution_start":
                    execution_started_at = data.get("timestamp", 0) / 1000 or time.time()
                    _update_prompt(prompt_id, "running",
                                   execution_started_at=execution_started_at)
            if status.get("status_str") == "error":
                msg = f"씬 {scene_id}: ComfyUI 실행 오류 {status.get('messages')}"
                _update_prompt(prompt_id, "error", error=msg)
                raise RuntimeError(msg)
            for node_out in h[prompt_id].get("outputs", {}).values():
                media = node_out.get("videos") or node_out.get("gifs") or node_out.get("images")
                if media:
                    break
            if media:
                _update_prompt(prompt_id, "completed", output_filename=media[0]["filename"])
                break
            if execution_started_at and time.time() - execution_started_at > STANDIN_EXEC_TIMEOUT:
                msg = (f"씬 {scene_id}: LTX 실행이 {STANDIN_EXEC_TIMEOUT:.0f}s를 초과함 "
                       f"(prompt_id={prompt_id})")
                _update_prompt(prompt_id, "error", error=msg)
                raise TimeoutError(msg)

        output = media[0]
        vid = await client.get(f"{COMFYUI_URL}/view", params={
            "filename": output["filename"], "subfolder": output.get("subfolder", ""),
            "type": output.get("type", "output"),
        })
        vid.raise_for_status()

    out = job_dir(job_id) / f"clip{scene_id}.mp4"
    out.write_bytes(vid.content)
    return str(out)


async def generate_t2v_clip(
    job_id: str, scene_id: int, prompt: str,
    duration: float = 2.0, seed: int | None = None, force_new: bool = False,
) -> str:
    """이미지 없는 씬(mode=T2V) — Wan call_video가 맡던 것 중 T2V 절반.
    같은 job 씬들이 같은 seed로 출발하면(호출부에서 payload.seed 그대로 넘김)
    그림체 흔들림이 줄어드는 건 기존 Wan 경로와 동일 관례."""
    resolved_seed = seed if seed is not None else int(time.time())
    length = to_ltx_len(duration * LTX13B_FPS)
    graph = _build_ltx13b_t2v_graph(
        prompt=prompt, width=WIDTH, height=HEIGHT, length=length, seed=resolved_seed)
    request_key = _t2v_request_key(scene_id, prompt, duration, seed)
    return await _generate_ltx_job_clip(job_id, scene_id, graph, request_key, force_new)


async def generate_i2v_fallback_clip(
    job_id: str, scene_id: int, prompt: str, matched_image: str,
    duration: float = 2.0, seed: int | None = None, force_new: bool = False,
) -> str:
    """USE_STANDIN=0일 때만 타는 드문 폴백(mode=I2V, 이미지 있음) — Wan call_video가
    맡던 것 중 I2V 절반. 기존 4.6 _build_ltx13b_graph(image-conditioned)를 그대로
    재사용, 신규 그래프 불필요."""
    resolved_seed = seed if seed is not None else int(time.time())
    timeout = httpx.Timeout(connect=10.0, read=60.0, write=60.0, pool=None)
    async with httpx.AsyncClient(timeout=timeout) as client:
        img_path = refs_dir(job_id) / matched_image
        up = await client.post(
            f"{COMFYUI_URL}/upload/image",
            files={"image": (f"i2v_fallback_{Path(matched_image).name}",
                             img_path.read_bytes(), "image/png")},
            data={"overwrite": "true"},
        )
        up.raise_for_status()
        uj = up.json()
        image_name = f"{uj['subfolder']}/{uj['name']}" if uj.get("subfolder") else uj["name"]

    length = to_ltx_len(duration * LTX13B_FPS)
    graph = _build_ltx13b_graph(
        prompt=prompt, image_name=image_name, width=WIDTH, height=HEIGHT, seed=resolved_seed)
    graph["7"]["inputs"]["length"] = length  # 4.6 오네샷은 LTX13B_FRAMES 고정, 여긴 씬 duration 반영
    request_key = _i2v_fallback_request_key(scene_id, prompt, matched_image, duration, seed)
    return await _generate_ltx_job_clip(job_id, scene_id, graph, request_key, force_new)
```

- [ ] **Step 4: `call_video`/`WAN_URL` 삭제**

`tools.py`에서 `WAN_URL = os.environ.get("AGENT_WAN_URL", "http://127.0.0.1:8500")` 줄(약 36줄) 삭제. `call_video()` 함수 전체(약 443-491줄, `async def call_video(...)` 부터 다음 함수 정의 전까지) 삭제.

- [ ] **Step 5: 테스트 통과 확인**

Run: `cd langgraph && ./.venv/bin/python tests/test_wan_removal.py`
Expected: 6개 테스트 전부 `ok:` 출력, exit 0.

- [ ] **Step 6: 커밋**

```bash
cd /home/admin/DaolVision
git add langgraph/tools.py langgraph/tests/test_wan_removal.py
git commit -m "feat: replace call_video (Wan) with LTX T2V/I2V-fallback wrappers (3/N)

call_video()/WAN_URL deleted. generate_t2v_clip and
generate_i2v_fallback_clip both route through the shared
_generate_ltx_job_clip helper, which copies _generate_reference_clip's
SQLite recoverable-job pattern so restarts still resume mid-generation
scenes the same way STANDIN/SUBJECT_REF already do.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 4: `nodes.py` 디스패치 교체

**Files:**
- Modify: `langgraph/nodes.py:870-906` (`node_generate_one_clip`)
- Test: `langgraph/tests/test_wan_removal.py`

**Interfaces:**
- Consumes: Task 3의 `tools.generate_t2v_clip`, `tools.generate_i2v_fallback_clip`.
- Produces: 없음(터미널 소비자) — 이후 Task는 `nodes.node_generate_one_clip`의 동작만 재검증.

- [ ] **Step 1: 실패하는 테스트 작성**

`test_wan_removal.py`에 추가:

```python
async def _async_test_dispatch_routes_to_new_functions():
    calls = []

    async def fake_t2v(**kw):
        calls.append(("t2v", kw))
        return "clipT.mp4"

    async def fake_i2v_fb(**kw):
        calls.append(("i2v_fb", kw))
        return "clipI.mp4"

    tools.generate_t2v_clip = fake_t2v
    tools.generate_i2v_fallback_clip = fake_i2v_fb

    t2v_scene = {"id": 1, "mode": "T2V", "prompt": "p", "matched_image": None,
                 "duration": 2.0, "mood": "neutral"}
    await nodes.node_generate_one_clip({"scene": t2v_scene, "job_id": "j", "seed": 1})
    assert calls[-1][0] == "t2v", calls
    assert calls[-1][1]["prompt"] == "p", calls

    i2v_scene = {"id": 2, "mode": "I2V", "prompt": "p", "matched_image": "ref.png",
                 "duration": 2.0, "mood": "neutral"}
    await nodes.node_generate_one_clip({"scene": i2v_scene, "job_id": "j", "seed": 1})
    assert calls[-1][0] == "i2v_fb", calls
    assert calls[-1][1]["matched_image"] == "ref.png", calls
    print("ok: mode=T2V/I2V가 각각 generate_t2v_clip/generate_i2v_fallback_clip로 라우팅")


def test_dispatch_routes_to_new_functions():
    asyncio.run(_async_test_dispatch_routes_to_new_functions())
```

`main()`에 한 줄 추가:

```python
def main():
    test_to_ltx_len_snaps_to_8k_plus_1()
    test_t2v_graph_has_no_image_nodes()
    test_t2v_request_key_changes_with_prompt_and_scene()
    test_i2v_fallback_request_key_changes_with_prompt_and_image()
    test_call_video_and_wan_url_removed()
    test_new_wrapper_signatures()
    test_dispatch_routes_to_new_functions()
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd langgraph && ./.venv/bin/python tests/test_wan_removal.py`
Expected: `AttributeError: module 'tools' has no attribute 'call_video'`(`nodes.py`가 아직 `tools.call_video`를 참조하므로 `node_generate_one_clip` 호출 시 에러)

- [ ] **Step 3: 구현**

`langgraph/nodes.py`의 892-901줄(`else: # T2V/I2V → Wan2.2-TI2V-5B (:8500)` 분기 전체)을 다음으로 교체:

```python
        else:                                # T2V/I2V 폴백 → LTX-13B-distilled (:8188)
            if scene["mode"] == "I2V":
                clip_path = await tools.generate_i2v_fallback_clip(
                    job_id=job_id,
                    scene_id=scene["id"],
                    prompt=scene["prompt"],
                    matched_image=scene["matched_image"],
                    duration=scene.get("duration", 2.0),
                    seed=payload.get("seed"),
                    force_new=payload.get("force_new", False),
                )
            else:                            # T2V
                clip_path = await tools.generate_t2v_clip(
                    job_id=job_id,
                    scene_id=scene["id"],
                    prompt=scene["prompt"],
                    duration=scene.get("duration", 2.0),
                    seed=payload.get("seed"),
                    force_new=payload.get("force_new", False),
                )
```

그 위 870-871줄 주석(":8500" 언급)도 갱신:

```python
    # 동시 실행 상한(_gen_semaphore): fan-out된 씬이 GPU를 동시에 물지 않게 게이팅.
    # 모든 백엔드가 이 단일 길목을 통과하므로 여기 하나만 걸면 :8188 합산 동시성이 잡힌다.
```

903-906줄(steps 결정 주석 + `tools.DEFAULT_STEPS`)도 교체:

```python
    # 클립당 step 수는 모드에 따라 결정적: LTX(T2V/I2V 폴백)=LTX13B_STEPS,
    # ComfyUI(STANDIN/SUBJECT_REF)=STANDIN_STEPS. 영상당 합산은 final_render에서.
    steps = (tools.STANDIN_STEPS if scene["mode"] in ("STANDIN", "SUBJECT_REF")
             else tools.LTX13B_STEPS)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd langgraph && ./.venv/bin/python tests/test_wan_removal.py`
Expected: 7개 테스트 전부 `ok:` 출력, exit 0.

- [ ] **Step 5: 커밋**

```bash
cd /home/admin/DaolVision
git add langgraph/nodes.py langgraph/tests/test_wan_removal.py
git commit -m "feat: route T2V/I2V-fallback scene dispatch to LTX (4/N)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 5: `run_agent.sh` 정리

**Files:**
- Modify: `langgraph/run_agent.sh:11`

**Interfaces:**
- Consumes: 없음.
- Produces: 없음 — 테스트 없음(환경변수 한 줄 삭제, 아무도 안 읽음. Task 4의 회귀 테스트로 실제 배선 동작은 이미 검증됨).

- [ ] **Step 1: 삭제**

`langgraph/run_agent.sh`의 11번째 줄:

```bash
export AGENT_WAN_URL="${AGENT_WAN_URL:-http://127.0.0.1:8500}"
```

이 줄을 통째로 삭제.

- [ ] **Step 2: grep으로 확인**

Run: `cd langgraph && grep -n AGENT_WAN_URL run_agent.sh`
Expected: 아무 출력 없음(exit 1, grep no-match).

- [ ] **Step 3: 커밋**

```bash
cd /home/admin/DaolVision
git add langgraph/run_agent.sh
git commit -m "chore: drop unused AGENT_WAN_URL export (5/N)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 6: `driver.py` `--dry` 페이크 교체

**Files:**
- Modify: `langgraph/driver.py:66-92` (`_install_fakes`)

**Interfaces:**
- Consumes: Task 3의 새 함수 시그니처(`generate_t2v_clip`, `generate_i2v_fallback_clip`).
- Produces: 없음 — `driver.py --dry`가 Task 9의 회귀 실행 대상.

- [ ] **Step 1: 구현**

`langgraph/driver.py`의 66-68줄:

```python
    async def fake_video(job_id, scene_id, prompt, mode, matched_image,
                         duration=2.0, seed=None, num_frames=None):
        return _fake_clip(job_id, scene_id)
```

를 다음으로 교체:

```python
    async def fake_t2v(job_id, scene_id, prompt, duration=2.0, seed=None, force_new=False):
        return _fake_clip(job_id, scene_id)

    async def fake_i2v_fallback(job_id, scene_id, prompt, matched_image,
                                duration=2.0, seed=None, force_new=False):
        return _fake_clip(job_id, scene_id)
```

92줄 `tools.call_video = fake_video`를 다음으로 교체:

```python
    tools.generate_t2v_clip = fake_t2v
    tools.generate_i2v_fallback_clip = fake_i2v_fallback
```

- [ ] **Step 2: 검증**

Run: `cd langgraph && ./.venv/bin/python driver.py --dry`
Expected: 마지막 줄이 정상 종료 메시지(예: 기존과 동일한 완주 출력, `Traceback`/`AttributeError` 없음). 실패 시 `tools.call_video` 잔여 참조가 없는지 `grep -n call_video driver.py`로 재확인.

- [ ] **Step 3: 커밋**

```bash
cd /home/admin/DaolVision
git add langgraph/driver.py
git commit -m "test: update driver.py --dry fakes for LTX T2V/I2V-fallback (6/N)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 7: `test_clip_concurrency.py` 갱신 + `test_anim15.py`(Wan 전용 수동 프로브) 삭제

**Files:**
- Modify: `langgraph/tests/test_clip_concurrency.py`
- Delete: `langgraph/tests/test_anim15.py`

**Interfaces:**
- Consumes: Task 3의 새 함수.
- Produces: 없음.

- [ ] **Step 1: `test_clip_concurrency.py` 수정**

`tools.call_video = fake_gen` 줄(29번째 줄 부근)을 다음으로 교체:

```python
    # 세 백엔드 경로를 모두 같은 fake로 대체 — 어느 모드든 단일 길목을 통과함을 확인.
    tools.generate_t2v_clip = fake_gen
    tools.generate_i2v_fallback_clip = fake_gen
    tools.generate_standin_clip = fake_gen
    tools.generate_subject_ref_clip = fake_gen
```

파일 상단 docstring의 "`:8500(Wan)+:8188(ComfyUI) 확산`" 문구를 갱신:

```
회귀 방지: 이 상한이 사라지면 씬 4개가 :8188(ComfyUI) 확산을 같은 순간에
피크로 몰아 GB10 통합메모리 OOM → ReadTimeout/정지. 참조: [[gb10-gpu-contention-comfyui-ollama]]
```

- [ ] **Step 2: 검증**

Run: `cd langgraph && ./.venv/bin/python tests/test_clip_concurrency.py`
Expected: `ok: limit=1 → peak 1(완전 순차) / limit=2 → peak 2 / 6씬 id 전부 보존`

- [ ] **Step 3: `test_anim15.py` 삭제**

이 파일은 ":8500만 사용"을 명시한 Wan 전용 수동 데모 스크립트(자동 회귀 스위트 아님) — Wan 제거로 전제 자체가 무효화된다. 대체물은 Task 10의 라이브 GPU 검증(`:8700` 파이프라인 전체 경로).

```bash
git rm langgraph/tests/test_anim15.py
```

- [ ] **Step 4: 커밋**

```bash
cd /home/admin/DaolVision
git add langgraph/tests/test_clip_concurrency.py
git commit -m "test: repoint concurrency gate test at LTX wrappers, drop Wan-only anim15 probe (7/N)

test_anim15.py was a manual :8500-only demo script, not part of the
automated suite -- its premise no longer holds once call_video is gone.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 8: `test_status_clips.py` 갱신

**Files:**
- Modify: `langgraph/tests/test_status_clips.py`

**Interfaces:**
- Consumes: `driver._install_fakes()`(Task 6에서 이미 새 함수로 교체됨).
- Produces: 없음.

- [ ] **Step 1: 구현**

23-31줄:

```python
_orig_video = tools.call_video


async def _staggered_video(job_id, scene_id, *a, **kw):
    await asyncio.sleep(0.3 if scene_id == 1 else 2.0)
    return await _orig_video(job_id, scene_id, *a, **kw)


tools.call_video = _staggered_video
```

를 다음으로 교체:

```python
_orig_t2v = tools.generate_t2v_clip
_orig_i2v_fallback = tools.generate_i2v_fallback_clip


async def _staggered_t2v(job_id, scene_id, *a, **kw):
    await asyncio.sleep(0.3 if scene_id == 1 else 2.0)
    return await _orig_t2v(job_id, scene_id, *a, **kw)


async def _staggered_i2v_fallback(job_id, scene_id, *a, **kw):
    await asyncio.sleep(0.3 if scene_id == 1 else 2.0)
    return await _orig_i2v_fallback(job_id, scene_id, *a, **kw)


tools.generate_t2v_clip = _staggered_t2v
tools.generate_i2v_fallback_clip = _staggered_i2v_fallback
```

- [ ] **Step 2: 검증**

Run: `cd langgraph && ./.venv/bin/python tests/test_status_clips.py`
Expected: `PASS: running 중 부분 완성 clips 노출 확인 — ...`

- [ ] **Step 3: 커밋**

```bash
cd /home/admin/DaolVision
git add langgraph/tests/test_status_clips.py
git commit -m "test: stagger LTX T2V/I2V-fallback wrappers instead of call_video (8/N)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 9: Plans.md 태스크 등록 + 전체 회귀 실행

**Files:**
- Modify: `Plans.md`(Week 6 섹션, 6.4 다음 줄에 6.5 추가)

**Interfaces:**
- Consumes: 없음.
- Produces: 없음.

- [ ] **Step 1: Plans.md에 6.5 추가**

`Plans.md`의 `| 6.4 | ... |` 줄 바로 뒤(Week 6 표 마지막 행)에 추가:

```
| 6.5 | Wan2.2(:8500, 중국원산) 백엔드 완전 제거 → T2V/I2V 폴백을 LTX-13B-distilled(:8188)로 통합 (docs/model-selection.md 비중국 원산 원칙 위반 해소, [[Duplicate, don't migrate]]) | call_video/WAN_URL 삭제, 신규 모델 다운로드 없음, driver --dry PASS, 유닛테스트 PASS, 라이브 job 1회 실측(이미지 없는 씬 포함) | cd langgraph && ./.venv/bin/python tests/test_wan_removal.py && ./.venv/bin/python driver.py --dry | 4.6 | cc:TODO | - |
```

**참고(태스크 본문에 넣지 않음, 실행자 인지용)**: Task 8.2.1(모델 서버 OpenShell 샌드박스 격리)이 "Wan:8500"을 6종 서비스 목록에 포함하고 있다 — 이 작업 완료 후 8.2.1 착수 시 그 목록에서 Wan을 빼야 한다(8.2.1은 아직 `cc:TODO`라 지금 당장 고칠 필요는 없음, 8.2.1 작업 시점에 자연히 드러남).

- [ ] **Step 2: 전체 회귀 스위트 실행**

Run:
```bash
cd /home/admin/DaolVision/langgraph
./.venv/bin/python tests/test_wan_removal.py
./.venv/bin/python tests/test_clip_concurrency.py
./.venv/bin/python tests/test_status_clips.py
./.venv/bin/python driver.py --dry
```

Expected: 넷 다 `ok:`/`PASS:`/정상 종료로 끝남, 어느 것도 `Traceback`/`AttributeError` 없음.

- [ ] **Step 3: `call_video`/`WAN_URL` 잔여 참조 없음을 grep으로 최종 확인**

Run: `cd /home/admin/DaolVision/langgraph && grep -rn "call_video\|WAN_URL\|AGENT_WAN_URL" . --include="*.py" --include="*.sh" | grep -v __pycache__`
Expected: 아무 출력 없음(exit 1).

- [ ] **Step 4: 커밋**

```bash
cd /home/admin/DaolVision
git add Plans.md
git commit -m "docs: register Task 6.5 (Wan removal) in Plans.md, all unit tests green (9/N)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 10: 라이브 GPU 검증 (사용자 명시 요청)

**Files:**
- 없음(검증 전용, 산출물은 실행 로그 + Task 11에서 문서에 기록).

**Interfaces:**
- Consumes: `:8700` 게이트웨이(재기동 필요 — Task 3/4의 코드 변경을 반영하려면 6.1 때와 동일하게 프로세스 재시작 필요), ComfyUI(:8188, 재기동 불요 — API 서버라 새 그래프 dict는 재시작 없이 즉시 반영됨).
- Produces: 문서화용 실측치(소요시간, 산출 clip 경로) — Task 11에 반영.

- [ ] **Step 1: GPU/메모리 상태 재점검(6.1과 동일 절차)**

```bash
nvidia-smi --query-compute-apps=pid,used_memory,process_name --format=csv
curl -sf -m 3 http://127.0.0.1:8188/system_stats | python3 -c "import json,sys; d=json.load(sys.stdin); dev=d['devices'][0]; print('vram_free_GB', round(dev['vram_free']/1e9,2))"
free -h
```

6.1 때 기준(vram_free 17GB 안팎에서 Kontext 1장 성공)과 비교해 여유가 있는지 확인. Wan 프로세스(pid는 그때그때 다름, `hunyuan_server/server.py`로 grep)가 계속 22GB를 쥐고 있다면 — 이 태스크 시점엔 아직 Task 12(Wan 프로세스 정지)를 안 했으므로 여전히 그 상태다. 여유 부족이 확인되면 여기서 멈추고 사용자에게 보고(6.1의 AskUserQuestion 패턴과 동일 판단 기준 — Wan 프로세스를 먼저 내릴지 여부는 이 태스크가 아니라 Task 12에서 다룬다. 다만 라이브 검증만 위해 순서를 앞당길지는 그 시점 판단).

- [ ] **Step 2: `:8700` 게이트웨이 재기동**

```bash
cd /home/admin/DaolVision/langgraph
ss -tlnp | grep 8700   # 현재 PID 확인
kill <PID>
sleep 2
nohup ./run_agent.sh >> server_8700.log 2>&1 &
disown
sleep 4
curl -sf -m 5 http://localhost:8700/health
```

Expected: `{"status":"ok","graph_loaded":true}`

- [ ] **Step 3: 이미지 없는 씬을 포함한 실제 job 실행**

`test.jpg`(6.1 때 썼던 얼굴사진, `/home/admin/DaolVision/건호군.jpg`)를 참조 이미지로 넣고, 짧은 시나리오로 job을 하나 돌린다 — `ref_images` 없이(순수 T2V만 나오게) 시작하는 편이 이 태스크의 검증 목적(이미지 없는 씬)에 더 직접적이다.

```bash
curl -sf -X POST http://localhost:8700/jobs \
  -H "Content-Type: application/json" \
  -d '{"script_text": "귀여운 로봇이 손을 흔들다가 신나게 달려간다.", "ref_images": []}' \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['job_id'])" > /tmp/wan_removal_job_id.txt
cat /tmp/wan_removal_job_id.txt
```

1-4(씬분할) 승인 게이트까지 진행되면 승인, 이후 3-5(클립 완료) 게이트까지 폴링:

```bash
JOB_ID=$(cat /tmp/wan_removal_job_id.txt)
curl -sf http://localhost:8700/jobs/$JOB_ID/status
# checkpoint가 "1-4"로 시작하면:
curl -sf -X POST http://localhost:8700/jobs/$JOB_ID/resume \
  -H "Content-Type: application/json" -d '{"payload": {"approved": true}}'
# 이후 진행상황을 몇 초 간격으로 재폴링(체크포인트가 "3-5"로 시작할 때까지)
curl -sf http://localhost:8700/jobs/$JOB_ID/status
```

- [ ] **Step 4: 산출물 확인**

```bash
JOB_ID=$(cat /tmp/wan_removal_job_id.txt)
ls -la /home/admin/DaolVision/langgraph/out/$JOB_ID/clip*.mp4
ffprobe -v error -show_entries stream=codec_name,width,height,duration -of default=noprint_wrappers=1 \
  /home/admin/DaolVision/langgraph/out/$JOB_ID/clip0.mp4
```

Expected: 유효한 mp4(코덱/해상도/길이가 합리적 — 8k+1 프레임수가 fps로 나눈 duration과 크게 어긋나지 않음). `server_8700.log`에서 해당 job의 에러 여부 확인:

```bash
grep -i "error\|traceback" /home/admin/DaolVision/langgraph/server_8700.log | tail -20
```

- [ ] **Step 5: 결과 기록**

소요시간(로그 타임스탬프로 계산), 해상도, 프레임수, 육안 코히런스 평가(이미지 조건 없이도 distilled 8-step이 자연스러운지 — 스펙의 "Out of scope" 리스크 항목)를 메모해 Task 11의 문서 갱신에 반영한다. 정리(test.jpg 등 임시 산출물 삭제)는 6.1 때와 동일하게 `/tmp` 쪽만.

**품질 붕괴 시(코히런스 심하게 깨짐, 아티팩트)**: 이 플랜을 완료 처리하지 않는다 — `LTX13B_STEPS`/가이던스 조정으로 1회 재시도하고, 그래도 안 되면 스펙의 "대안"(T2I 앵커 경유)으로 재브레인스토밍이 필요함을 사용자에게 보고한다.

---

### Task 11: 문서 갱신

**Files:**
- Modify: `docs/model-selection.md`, `docs/model-selection-i2v.md`, `docs/Architecture.md`, `docs/PRD.md`, `docs/external-dependencies.md`, `README.md`

**Interfaces:**
- Consumes: Task 10의 실측치.
- Produces: 없음.

- [ ] **Step 1: `docs/model-selection.md` 갱신**

`| I2V 얼굴 일관 영상 | LTX-2.3 22B Q6_K + Distill + Best Face-ID | 품질 통과, 속도 개선 필요 |` 행 다음에 추가:

```
| I2V(T2V/폴백, 舊 Wan2.2) | LTX-Video-0.9.8-13B-distilled | Task 6.5로 Wan2.2(중국원산) 교체, 실측 ~Ns/클립(Task 10 산출: server_8700.log 타임스탬프 차 또는 job status의 started_at/completed_at 차로 계산) |
```

Task 10에서 실제 측정한 초 단위 값을 `~Ns/클립` 자리에 그대로 채워 넣는다(예: `~42s/클립`) — 이 플랜 작성 시점엔 아직 실행 전이라 정확한 값을 알 수 없다.

`| I2V 단발샷(비Face-ID) | LTX-Video-0.9.8-13B-distilled | 채택, 30초/5초분량 실측... |` 행의 설명에 " · 6.5부터 job 파이프라인 T2V/I2V-폴백도 동일 체크포인트 공유"를 덧붙인다.

- [ ] **Step 2: `docs/model-selection-i2v.md`에 실측 절 추가**(파일 없으면 신설 — 지금까지 language 참조만 있고 실측 기록 파일이 비어있을 수 있음, 있으면 6.1의 `model-selection-i2i.md`와 동일한 형식으로 "## Task 6.5 실측 (날짜)" 절 추가)

Task 10에서 얻은 소요시간/해상도/코히런스 평가를 6.1의 `model-selection-i2i.md` 실측 절과 동일한 포맷으로 기록.

- [ ] **Step 3: `docs/Architecture.md` 갱신**

15줄: `| 영상 | ComfyUI(:8188): LTX distilled+Face-ID / Cosmos벤치 / Wan폴백 | 캐릭터+화풍 일관 I2V |`
→ `| 영상 | ComfyUI(:8188): LTX distilled+Face-ID / Cosmos벤치 (Wan 제거, Task 6.5) | 캐릭터+화풍 일관 I2V, T2V |`

28줄: `GW --> CF[ComfyUI :8188<br/>LTX+FaceID / Kontext / Wan]`
→ `GW --> CF[ComfyUI :8188<br/>LTX+FaceID / Kontext]`

42줄: `| ComfyUI(:8188) | I2V(캐릭터 일관) + I2I(Flux Kontext) | LTX+Face-ID LoRA·BFS노드·Wan(폴백) |`
→ `| ComfyUI(:8188) | I2V(캐릭터 일관 + T2V/폴백) + I2I(Flux Kontext) | LTX+Face-ID LoRA·BFS노드 |`

106줄: `- **국적**: 전 모델 비중국/NVIDIA(Wan 폴백 예외). 신규 도입시 국적·라이센스 확인`
→ `- **국적**: 전 모델 비중국/NVIDIA(Task 6.5로 Wan 예외 해소, 예외 없음). 신규 도입시 국적·라이센스 확인`

- [ ] **Step 4: `docs/PRD.md` 결정 로그에 추가**(기존 행 삭제 안 함 — 이 표는 append-only 이력)

"## 결정 로그" 표의 마지막 행 다음에 추가:

```
| 2026-08-01 | Wan2.1-14B Stand-In 폴백(R10 예외) 완전 제거, T2V/I2V 폴백을 LTX-13B-distilled로 통합 | 얼굴 일관성 폴백 역할은 이미 STANDIN(ComfyUI, 2026-07-31 재설계)으로 이관 완료 — Wan은 남은 역할(순수 T2V·희귀 I2V 폴백)뿐이라 국적 예외를 유지할 이유 소멸 | 유지(2026-07-28 결정대로 예외 존속) |
```

R10 행(163줄)에 각주 추가: `| R10 | 전 모델 비중국/NVIDIA (2026-08-01부터 예외 없음, Wan 제거됨). 신규 모델 도입시 국적 확인 | must |`

I2V(폴백) 모델표 행(111줄) 삭제하지 않고 갱신: `| I2V(폴백, 제거됨 2026-08-01) | ~~Wan2.1-14B Stand-In~~ | 🇨🇳 | Task 6.5로 제거 — 얼굴일관 폴백은 STANDIN(ComfyUI)이 대체 |`

- [ ] **Step 5: `docs/external-dependencies.md` 갱신**

Wan2.2-TI2V-5B 서비스 행(25줄)에 상태 갱신: `| Wan2.2-TI2V-5B (T2V/I2V) | :8500 | ~~inference_server/server.py~~(Task 6.5로 DaolVision에서 삭제, video_generator/hunyuan_server 원본은 유지) | ~~inference_server/deploy/wan.service~~ | Task 6.5로 DaolVision 사용 중단 |`

- [ ] **Step 6: `README.md` 갱신**

56줄: `- \`inference_server/\` — Wan2.2-TI2V-5B(:8500)·FLUX.1-schnell(:8501) 서버 코드 + systemd deploy unit(Task 3.7, video_generator hunyuan_server에서 복제 — 원본 유지). Animate(:8600)는 미사용 죽은 코드라 DaolVision에서 삭제`
→ `- \`inference_server/\` — FLUX.1-schnell(:8501) 서버 코드 + systemd deploy unit(Task 3.7, video_generator hunyuan_server에서 복제 — 원본 유지). Animate(:8600)·Wan2.2-TI2V-5B(:8500)는 미사용 죽은 코드라 DaolVision에서 삭제(Task 6.5)`

- [ ] **Step 7: 커밋**

```bash
cd /home/admin/DaolVision
git add docs/model-selection.md docs/model-selection-i2v.md docs/Architecture.md docs/PRD.md docs/external-dependencies.md README.md
git commit -m "docs: record Wan removal + LTX T2V/I2V-fallback measurement (Task 6.5)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 12: 저장소 내 Wan 서버 코드 삭제 + 실행 중 프로세스 정지 (c4c36c4 전례 그대로)

**Files:**
- Delete: `inference_server/server.py`, `inference_server/run.sh`, `inference_server/deploy/wan.service`

**Interfaces:**
- Consumes: Task 3-11 전부 완료(코드가 더 이상 :8500을 부르지 않음이 검증된 이후에만 실행 — 롤백 여지를 남기기 위한 순서).
- Produces: 없음.

- [ ] **Step 1: 삭제 — `c4c36c4`(animate_server :8600 제거)와 동일 패턴**

```bash
cd /home/admin/DaolVision
git rm inference_server/server.py inference_server/run.sh inference_server/deploy/wan.service
```

- [ ] **Step 2: 설치된 systemd user unit 제거**

```bash
systemctl --user list-unit-files | grep wan   # 현재 disabled임을 재확인(c4c36c4의 wan-animate와 동일 상태)
systemctl --user disable wan.service 2>&1 || true   # 이미 disabled라 no-op일 수 있음
rm -f ~/.config/systemd/user/wan.service
systemctl --user daemon-reload
```

- [ ] **Step 3: 수동 실행 중인 Wan 프로세스 정지**(video_generator 원본 프로세스 — 코드는 안 건드림, 프로세스만 정지)

```bash
pgrep -af "hunyuan_server/server.py"
# 위에서 나온 PID로:
kill <PID>
sleep 2
pgrep -af "hunyuan_server/server.py" || echo "stopped"
ss -tlnp | grep 8500 || echo ":8500 no longer listening"
```

이 프로세스는 `video_generator` 소유 코드를 실행하는 것이므로, 코드 자체는 그대로 두고 프로세스만 정지한다. 재기동이 필요하면 video_generator 쪽 자체 launcher로 다시 띄우면 된다(DaolVision은 더 이상 호출하지 않으므로 재기동 여부는 이 작업과 무관).

- [ ] **Step 4: 최종 확인**

```bash
cd /home/admin/DaolVision/langgraph
grep -rn "call_video\|WAN_URL\|:8500" . --include="*.py" --include="*.sh" | grep -v __pycache__
curl -sf -m 3 http://localhost:8700/health
./.venv/bin/python driver.py --dry
```

Expected: 첫 grep은 무출력(`:8500` 문자열 자체도 코드에서 완전히 사라짐), health 정상, `driver.py --dry` 정상 종료.

- [ ] **Step 5: 커밋**

```bash
cd /home/admin/DaolVision
git commit -m "refactor: remove dead Wan2.2 server code from DaolVision (12/N, Task 6.5)

LangGraph no longer calls :8500 as of Task 6.5's LTX T2V/I2V-fallback
migration. Dropped inference_server/server.py, run.sh, deploy/wan.service,
and the installed (already-disabled) systemd user unit, then stopped the
manually-running process. Scope is DaolVision only, per the same
precedent as c4c36c4 (animate_server :8600 removal) -- video_generator's
hunyuan_server/ keeps its own copy untouched.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

- [ ] **Step 6: Plans.md 6.5 완료 처리**

```bash
git log --oneline -1   # hash 확인
```

`Plans.md`의 `6.5` 행 Status를 `cc:완료 [<hash>]`로 갱신 후:

```bash
git add Plans.md
git commit -m "docs: mark Task 6.5 complete in Plans.md

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Self-Review 메모(작성자용, 실행자는 무시)

- **스펙 커버리지**: Architecture(Task 1-4) / Data flow(Task 1,3) / Error handling(Task 3) / Testing(Task 1-9) / 라이브 GPU 검증(Task 10) / Out of scope로 남겼던 `run_agent.sh`(Task 5)까지 전부 태스크로 존재. request_key 필드(스펙 self-review에서 지적된 갭)는 Task 2에서 정확히 스펙의 코드블록 그대로 반영.
- **플레이스홀더 스캔**: 없음 — 모든 스텝에 실행 가능한 실 코드/명령어.
- **타입/시그니처 일관성**: `generate_t2v_clip`/`generate_i2v_fallback_clip` 시그니처가 Task 3(정의) / Task 4(호출) / Task 6(driver 페이크) / Task 7,8(테스트 몽키패치)에서 전부 동일(`job_id, scene_id, prompt, [matched_image,] duration, seed, force_new`).
- **추가 발견 반영**: 브레인스토밍 스펙에는 없었지만 조사 중 발견한 두 가지를 플랜에 편입함 — (1) `driver.py`/`test_clip_concurrency.py`/`test_status_clips.py`/`test_anim15.py`가 전부 `call_video`를 직접 참조하고 있어 삭제 시 깨짐(Task 6-8), (2) DaolVision 저장소 자체에 복제된 `inference_server/server.py`(Wan 서버 코드)가 `c4c36c4`(animate_server :8600 제거)와 완전히 동일한 상황이라 같은 전례로 정리(Task 12).
