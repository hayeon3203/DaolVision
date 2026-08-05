# LTX Face-ID Anchor-Lock Removal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the Flux scene-anchor image-lock from the LTX Face-ID pipeline (Plans.md Task 5.2/5.3) and revert to Task 3.2's proven anchor-free Face-ID generation, restoring identity fidelity and fixing the face-size regression, without losing per-scene background variety (which was never anchor-driven).

**Architecture:** `node_generate_scene_anchors` (Flux call + classification) becomes `node_classify_faceid_scenes` (classification only, no Flux call). `_build_ltx_faceid_graph` stops injecting nodes 130/131 (`LoadImage` + `LTXVImgToVideo`) and stops overriding node 117/129 wiring, so the base `ltx_faceid_api.json` workflow's original wiring (node 100 `EmptyLTXVLatentVideo` → 117 → 129←83, identical to the 3.2 smoke test) takes effect untouched.

**Tech Stack:** Python 3.12, LangGraph, ComfyUI HTTP API, pytest-free `assert`-based smoke tests (repo convention — see existing `tests/test_scene_anchors.py`, `tests/test_ltx_faceid_batch.py`).

## Global Constraints

- No new dependencies. This is a revert-to-known-good plus cleanup, not new feature work.
- Task 5.2 (`node_generate_scene_anchors`, `tools.generate_scene_anchor`, `state.py` `anchor_image` field) was already committed at `35c81c4` — this plan edits already-committed code and will land in a new commit, not a `git revert` (avoids conflicting with the still-uncommitted Task 5.3 work in the same files).
- Task 5.3 (`_build_ltx_faceid_graph`, `_build_ltx_faceid_batch_graph`, `generate_ltx_faceid_batch`, the `node_generate_ltx_batch` graph wiring) is entirely uncommitted working-tree state — free to edit directly.
- `langgraph/comfyui_workflows/ltx_faceid_api.json` (untracked base workflow, 41 nodes, ids up to 129) is the source of truth for "no anchor" wiring: node 100 = `EmptyLTXVLatentVideo`, node 117 `video_latent` = `["100", 0]`, node 129 `positive`/`negative` = `["83", 0]`/`["83", 1]`. Confirmed via direct inspection — do not re-verify, just rely on this.
- Repo test convention: no pytest — test files are `assert`-based scripts with `if __name__ == "__main__":` blocks, run via `./.venv/bin/python tests/test_x.py`.
- Run all Python commands from `/home/admin/DaolVision/langgraph` using `./.venv/bin/python` (confirmed present).

---

### Task 1: Rewrite `test_ltx_faceid_batch.py` to assert anchor-free graph wiring

**Files:**
- Modify: `langgraph/tests/test_ltx_faceid_batch.py` (entire file, currently untracked/uncommitted — codex-authored for the buggy anchor design)

**Interfaces:**
- Consumes: `tools._build_ltx_faceid_graph(*, prompt, face_image, duration, seed, prefix)` — **note: `anchor_image` kwarg removed** (Task 2 will remove it from the function signature; this test is written against the target signature first, so it will fail until Task 2 lands).
- Consumes: `tools._build_ltx_faceid_batch_graph(scenes, uploaded)` — `uploaded` dict now only needs face-ref keys (no anchor path keys).
- Consumes: `nodes.node_generate_ltx_batch(state)` — unchanged signature.
- Produces: nothing new for later tasks — this is a leaf test file.

- [ ] **Step 1: Replace the whole file**

```python
"""Task 5.3: 네 Face-ID 씬을 단일 LTX batch 호출로 생성하는 계약 (2026-07-31 재설계:
Flux 앵커 lock 제거, 3.2와 동일한 base 워크플로 배선 사용)."""
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import nodes
import tools


def _scenes():
    return [
        {
            "id": i,
            "text": text,
            "prompt": f"astronaut scene {i}",
            "duration": 3.0,
            "mode": "LTX_FACEID",
            "face_id_ref": "astronaut.png",
            "matched_image": "astronaut.png",
            "image_role": "ref",
            "subject_type": "human",
        }
        for i, text in enumerate(("발사", "우주유영", "외계행성", "귀환"), 1)
    ]


async def _run():
    batch = AsyncMock(return_value={
        i: f"/jobs/s1/clip{i}.mp4" for i in range(1, 5)
    })
    with patch("tools.generate_ltx_faceid_batch", new=batch):
        result = await nodes.node_generate_ltx_batch({
            "job_id": "s1",
            "scenes": _scenes(),
            "regen_target_ids": [],
        })

    assert batch.await_count == 1, "씬별 호출로 회귀하면 모델을 반복 로드한다"
    payload = batch.await_args.args[1]
    assert len(payload) == 4
    assert all(scene["face_id_ref"] == "astronaut.png" for scene in payload)
    assert "anchor_image" not in payload[0], "앵커 필드는 더 이상 존재하면 안 됨"
    assert [scene["clip_path"] for scene in result["scenes"]] == [
        f"/jobs/s1/clip{i}.mp4" for i in range(1, 5)
    ]
    assert all(scene["mode"] == "LTX_FACEID" for scene in result["scenes"])
    assert all(scene["steps"] == tools.LTX_FACEID_STEPS for scene in result["scenes"])


if __name__ == "__main__":
    graph = tools._build_ltx_faceid_graph(
        prompt="wide astronaut shot",
        face_image="astronaut.png",
        duration=3.0,
        seed=123,
        prefix="job_ltx_1",
    )
    assert graph["100"]["inputs"]["width"] == 1024
    assert graph["100"]["inputs"]["height"] == 576
    assert graph["104"]["inputs"]["image"] == "astronaut.png"
    assert "130" not in graph, "Flux 앵커 LoadImage 노드는 더 이상 존재하면 안 됨"
    assert "131" not in graph, "LTXVImgToVideo 앵커 lock 노드는 더 이상 존재하면 안 됨"
    assert graph["117"]["inputs"]["video_latent"] == ["100", 0], (
        "117은 base 워크플로 원본 배선(EmptyLTXVLatentVideo)을 그대로 써야 한다"
    )
    assert graph["129"]["inputs"]["positive"] == ["83", 0]
    assert graph["129"]["inputs"]["negative"] == ["83", 1]
    assert graph["102"]["inputs"]["value"].startswith("ref_t2v:")
    assert graph["101"]["inputs"]["filename_prefix"] == "job_ltx_1"
    assert "audio" not in graph["56"]["inputs"]
    batch_graph, outputs = tools._build_ltx_faceid_batch_graph(
        [{**scene, "seed": scene["id"]} for scene in _scenes()],
        {"astronaut.png": "uploaded_astronaut.png"},
    )
    assert len([n for n in batch_graph.values() if n["class_type"] == "LoaderGGUF"]) == 1
    assert len([n for n in batch_graph.values() if n["class_type"] == "DualCLIPLoader"]) == 1
    assert len([
        n for n in batch_graph.values()
        if n["class_type"] == "LoraLoaderModelOnly"
    ]) == 2
    assert len([n for n in batch_graph.values() if n["class_type"] == "SamplerCustomAdvanced"]) == 4
    assert len([n for n in batch_graph.values() if n["class_type"] == "LTXVImgToVideo"]) == 0, (
        "앵커 lock 제거 후엔 이 노드 타입이 그래프에 전혀 없어야 한다"
    )
    assert len(outputs) == 4
    asyncio.run(_run())
    print("ok: four scenes use one anchor-free LTX Face-ID batch submission")
```

- [ ] **Step 2: Run it to verify it fails against current (uncommitted) tools.py**

Run: `cd /home/admin/DaolVision/langgraph && ./.venv/bin/python tests/test_ltx_faceid_batch.py`
Expected: `TypeError: _build_ltx_faceid_graph() missing 1 required keyword-only argument: 'anchor_image'` (current code still requires it) — this confirms the test targets the new behavior Task 2 will implement.

- [ ] **Step 3: Commit**

```bash
cd /home/admin/DaolVision
git add langgraph/tests/test_ltx_faceid_batch.py
git commit -m "test: assert anchor-free LTX Face-ID graph wiring (Task 5.3 redesign)"
```

---

### Task 2: Remove the Flux anchor image-lock from `tools.py`

**Files:**
- Modify: `langgraph/tools.py:655-700` (`_build_ltx_faceid_graph`)
- Modify: `langgraph/tools.py:722-748` (`_build_ltx_faceid_batch_graph` — one call-site line)
- Modify: `langgraph/tools.py:751-` (`generate_ltx_faceid_batch` — delete anchor upload block)
- Modify: `langgraph/tools.py:501-522` (delete `generate_scene_anchor` entirely)

**Interfaces:**
- Produces: `tools._build_ltx_faceid_graph(*, prompt: str, face_image: str, duration: float, seed: int, prefix: str) -> dict` (signature drops `anchor_image`).
- Produces: `tools.generate_ltx_faceid_batch(job_id: str, scenes: list[dict]) -> dict[int, str]` (scenes no longer need an `anchor_image` key).
- `tools.generate_scene_anchor` no longer exists — Task 4 removes its last caller (`nodes.py`) and Task 4 also removes the `driver.py` fake for it.

- [ ] **Step 1: Delete `generate_scene_anchor`**

In `langgraph/tools.py`, delete lines 501-522 (the full function, from `async def generate_scene_anchor(` through the blank line right before `async def generate_t2i_anchor(`). Leave exactly one blank line separating `generate_t2i_image` (ends line 498) from `generate_t2i_anchor` (starts at what is currently line 524).

- [ ] **Step 2: Strip the anchor lock out of `_build_ltx_faceid_graph`**

Replace (currently lines 655-700):

```python
def _build_ltx_faceid_graph(
    *, prompt: str, face_image: str, anchor_image: str, duration: float,
    seed: int, prefix: str,
) -> dict:
    """Flux 앵커를 첫 프레임으로 잠그고 Face-ID를 별도 참조로 주입한다."""
    graph = json.loads(LTX_FACEID_WORKFLOW.read_text())
    graph["31"]["inputs"]["value"] = duration
    graph["47"]["inputs"]["value"] = LTX_FACEID_FPS
    graph["50"]["inputs"]["noise_seed"] = seed
    graph["66"]["inputs"]["steps"] = LTX_FACEID_STEPS
    graph["98"]["inputs"]["preview_rate"] = LTX_FACEID_STEPS
    graph["100"]["inputs"].update(width=LTX_FACEID_WIDTH, height=LTX_FACEID_HEIGHT)
    graph["102"]["inputs"]["value"] = (
        prompt if prompt.lstrip().startswith("ref_t2v:") else f"ref_t2v: {prompt}"
    )
    graph["104"]["inputs"]["image"] = face_image
    graph["101"]["inputs"]["filename_prefix"] = prefix
    graph["130"] = {
        "inputs": {"image": anchor_image},
        "class_type": "LoadImage",
        "_meta": {"title": "Flux Scene Anchor"},
    }
    graph["131"] = {
        "inputs": {
            "positive": ["83", 0],
            "negative": ["83", 1],
            "vae": ["8", 0],
            "image": ["130", 0],
            "width": LTX_FACEID_WIDTH,
            "height": LTX_FACEID_HEIGHT,
            "length": ["5", 1],
            "batch_size": 1,
            "strength": 1.0,
        },
        "class_type": "LTXVImgToVideo",
        "_meta": {"title": "Flux Anchor I2V"},
    }
    # I2V가 만든 첫 프레임 latent/conditioning에 Face-ID reference tokens를
    # 추가한다. 이 연결이 없으면 anchor_image는 상태에만 있고 생성에는 쓰이지 않는다.
    graph["117"]["inputs"]["video_latent"] = ["131", 2]
    graph["129"]["inputs"]["positive"] = ["131", 0]
    graph["129"]["inputs"]["negative"] = ["131", 1]
    # S1 나레이션은 5.4에서 별도 TTS mux한다. 여기서 LTX 오디오를 디코드하면
    # 씬 사이 AudioVAE 로드가 대형 모델 offload와 스왑 스래싱을 유발한다.
    graph["56"]["inputs"].pop("audio", None)
    return graph
```

with:

```python
def _build_ltx_faceid_graph(
    *, prompt: str, face_image: str, duration: float, seed: int, prefix: str,
) -> dict:
    """3.2와 동일한 base 워크플로 배선(앵커 lock 없음) — Face-ID LoRA가 identity를
    전담한다. 2026-07-31: Flux 앵커로 첫 프레임을 강도 1.0으로 고정하던 버전은
    앵커 자체에 identity 정보가 없어(Flux가 얼굴 참조를 안 받음) 무작위 얼굴이
    나왔고, 그 강한 lock이 Face-ID Identity Transfer(node 129)를 무력화시켰다
    (실사용 재현 검증 완료, docs/superpowers/specs/2026-07-31-ltx-faceid-anchor-removal-design.md).
    """
    graph = json.loads(LTX_FACEID_WORKFLOW.read_text())
    graph["31"]["inputs"]["value"] = duration
    graph["47"]["inputs"]["value"] = LTX_FACEID_FPS
    graph["50"]["inputs"]["noise_seed"] = seed
    graph["66"]["inputs"]["steps"] = LTX_FACEID_STEPS
    graph["98"]["inputs"]["preview_rate"] = LTX_FACEID_STEPS
    graph["100"]["inputs"].update(width=LTX_FACEID_WIDTH, height=LTX_FACEID_HEIGHT)
    graph["102"]["inputs"]["value"] = (
        prompt if prompt.lstrip().startswith("ref_t2v:") else f"ref_t2v: {prompt}"
    )
    graph["104"]["inputs"]["image"] = face_image
    graph["101"]["inputs"]["filename_prefix"] = prefix
    # S1 나레이션은 5.4에서 별도 TTS mux한다. 여기서 LTX 오디오를 디코드하면
    # 씬 사이 AudioVAE 로드가 대형 모델 offload와 스왑 스래싱을 유발한다.
    graph["56"]["inputs"].pop("audio", None)
    return graph
```

- [ ] **Step 3: Drop the `anchor_image` call-site argument in `_build_ltx_faceid_batch_graph`**

In `langgraph/tools.py` inside `_build_ltx_faceid_batch_graph` (around line 730-737), change:

```python
        graph = _build_ltx_faceid_graph(
            prompt=scene["prompt"],
            face_image=uploaded[scene["face_id_ref"]],
            anchor_image=uploaded[scene["anchor_image"]],
            duration=float(scene.get("duration") or 3.0),
            seed=int(scene.get("seed") or 0),
            prefix=f"ltx_batch_scene_{scene_id}",
        )
```

to:

```python
        graph = _build_ltx_faceid_graph(
            prompt=scene["prompt"],
            face_image=uploaded[scene["face_id_ref"]],
            duration=float(scene.get("duration") or 3.0),
            seed=int(scene.get("seed") or 0),
            prefix=f"ltx_batch_scene_{scene_id}",
        )
```

- [ ] **Step 4: Delete the anchor upload block in `generate_ltx_faceid_batch`**

In `langgraph/tools.py` inside `generate_ltx_faceid_batch`, delete this whole block (currently lines 775-803, the loop that uploads `scene["anchor_image"]` to ComfyUI — starts right after the face-ref upload loop's closing, right before `graph, output_nodes = _build_ltx_faceid_batch_graph(...)`):

```python
        # 앵커는 씬마다 다르며 LTXVImgToVideo의 실제 첫 프레임 입력으로 들어간다.
        for scene in scenes:
            anchor_name = scene.get("anchor_image")
            if not anchor_name:
                raise ValueError(f"씬 {scene['id']}: LTX Face-ID I2V 앵커 이미지 없음")
            anchor_path = Path(anchor_name)
            if not anchor_path.is_file():
                raise FileNotFoundError(
                    f"씬 {scene['id']}: 앵커 이미지를 찾을 수 없음: {anchor_path}"
                )
            anchor_bytes = _prepare_reference_upload(anchor_path, subject_ref=False)
            response = await client.post(
                f"{COMFYUI_URL}/upload/image",
                files={
                    "image": (
                        f"ltx_anchor_{job_id}_{scene['id']}.png",
                        anchor_bytes,
                        "image/png",
                    )
                },
                data={"overwrite": "true"},
            )
            response.raise_for_status()
            data = response.json()
            uploaded[anchor_name] = (
                f"{data.get('subfolder')}/{data['name']}"
                if data.get("subfolder") else data["name"]
            )
```

Leave exactly one blank line, so the function reads directly from the face-ref upload loop into `graph, output_nodes = _build_ltx_faceid_batch_graph(scenes, uploaded)`.

- [ ] **Step 5: Run the Task 1 test to verify it now passes**

Run: `cd /home/admin/DaolVision/langgraph && ./.venv/bin/python tests/test_ltx_faceid_batch.py`
Expected: `ok: four scenes use one anchor-free LTX Face-ID batch submission`

- [ ] **Step 6: Byte-compile check and commit**

```bash
cd /home/admin/DaolVision
./langgraph/.venv/bin/python -m py_compile langgraph/tools.py
git add langgraph/tools.py
git commit -m "fix: remove Flux anchor image-lock from LTX Face-ID graph (Task 5.3)

Anchor carried no identity (Flux never received a face reference) and
LTXVImgToVideo strength=1.0 locked it as the first frame, overriding the
Face-ID Identity Transfer node entirely. Restores 3.2's proven wiring."
```

---

### Task 3: Rewrite `test_scene_anchors.py` to assert classification-only behavior

**Files:**
- Modify: `langgraph/tests/test_scene_anchors.py` (entire file, currently committed as part of Task 5.2's `35c83c4`)

**Interfaces:**
- Consumes: `nodes.node_classify_faceid_scenes(state: dict) -> dict` (new name — Task 4 introduces it; this test targets it first and will fail with `AttributeError` until Task 4 lands).

- [ ] **Step 1: Replace the whole file**

```python
"""Task 5.2 (2026-07-31 재설계): LTX_FACEID 모드 분류 계약.

원래 이 노드(`node_generate_scene_anchors`)는 Flux로 씬별 배경 앵커를
생성했으나, 앵커가 얼굴 참조를 받지 않아 identity가 무작위였고 그 앵커를
LTXVImgToVideo가 강도 1.0으로 고정해 Face-ID를 무력화시켰다(실사용 재현
검증, 2026-07-31). 배경 다양성은 3.2에서 이미 프롬프트 텍스트만으로
증명됐으므로 앵커를 완전히 제거하고, 이 노드는 사람 참조 유무로 씬의
`mode`/`face_id_ref`만 분류한다.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import nodes


def _run():
    scenes = [
        {
            "id": i,
            "text": text,
            "prompt": f"scene {i} prompt",
            "subject_type": "human",
            "matched_image": "astronaut.png",
            "image_role": "ref",
        }
        for i, text in enumerate(("발사", "우주유영", "외계행성", "귀환"), 1)
    ]
    result = nodes.node_classify_faceid_scenes({
        "job_id": "s1-astronaut",
        "scenes": scenes,
    })

    classified = result["scenes"]
    assert result["phase"] == "anchoring"
    assert len(classified) == 4
    assert all("anchor_image" not in scene for scene in classified), (
        "앵커 필드는 더 이상 생성되면 안 됨"
    )
    assert all(scene["face_id_ref"] == "astronaut.png" for scene in classified)
    assert all(scene["mode"] == "LTX_FACEID" for scene in classified)

    nonhuman = {
        **scenes[0],
        "subject_type": "nonhuman",
        "image_role": "character_ref",
    }
    guarded = nodes.node_classify_faceid_scenes({
        "job_id": "guard",
        "scenes": [nonhuman],
    })
    assert guarded["scenes"][0]["face_id_ref"] is None
    assert guarded["scenes"][0]["mode"] == "T2V"


if __name__ == "__main__":
    _run()
    print("ok: scenes classify into LTX_FACEID/T2V without a Flux anchor call")
```

(No `asyncio` needed anymore since the node is now synchronous — Task 4 makes `node_classify_faceid_scenes` a plain `def`, not `async def`. The `import asyncio` line is kept out entirely since nothing in this file awaits.)

- [ ] **Step 2: Run it to verify it fails against current nodes.py**

Run: `cd /home/admin/DaolVision/langgraph && ./.venv/bin/python tests/test_scene_anchors.py`
Expected: `AttributeError: module 'nodes' has no attribute 'node_classify_faceid_scenes'`

- [ ] **Step 3: Commit**

```bash
cd /home/admin/DaolVision
git add langgraph/tests/test_scene_anchors.py
git commit -m "test: assert LTX_FACEID classification without Flux anchor call (Task 5.2 redesign)"
```

---

### Task 4: Rename and strip the anchor node in `nodes.py`, rewire `graph.py`/`state.py`/`driver.py`

**Files:**
- Modify: `langgraph/nodes.py:669-702` (`node_generate_scene_anchors` → `node_classify_faceid_scenes`)
- Modify: `langgraph/graph.py:40` and `:74` (node registration + edge source name)
- Modify: `langgraph/state.py:23` (delete `anchor_image` field)
- Modify: `langgraph/driver.py:86-93,99` (delete `fake_scene_anchor` and its assignment)

**Interfaces:**
- Produces: `nodes.node_classify_faceid_scenes(state: GraphState) -> dict` — sync function, returns `{"scenes": [...], "phase": "anchoring"}`. Each scene dict gains `face_id_ref: str | None` and `mode` (unchanged from before), no longer gains `anchor_image`.
- Consumes: nothing new — same `Scene` state shape as before, minus `anchor_image`.

- [ ] **Step 1: Replace `node_generate_scene_anchors` in `nodes.py`**

Replace (currently lines 669-702):

```python
async def node_generate_scene_anchors(state: GraphState) -> dict:
    """2-3: 승인된 모든 씬의 Flux 앵커를 생성하고 Face-ID 참조를 별도 첨부한다.

    anchor_image는 장면 구도/배경의 첫 프레임 조건이고, face_id_ref는 사람 identity
    조건이다. 둘을 분리해야 5.3의 LTX I2V가 앵커 구도를 받으면서도 같은 얼굴을
    전 씬에 유지할 수 있다.
    """
    job_id = state["job_id"]
    scenes = state.get("scenes") or []

    async def generate(scene: Scene) -> Scene:
        anchor = await tools.generate_scene_anchor(
            job_id=job_id,
            scene_id=scene["id"],
            prompt=scene["prompt"],
            seed=scene_seed(job_id, scene["id"]),
        )
        matched = scene.get("matched_image")
        face_id_ref = (
            matched
            if matched
            and scene.get("subject_type") == "human"
            and scene.get("image_role") in ("start", "ref")
            else None
        )
        return {
            **scene,
            "anchor_image": anchor,
            "face_id_ref": face_id_ref,
            "mode": "LTX_FACEID" if face_id_ref else scene.get("mode", "T2V"),
        }

    anchored = await asyncio.gather(*(generate(scene) for scene in scenes))
    return {"scenes": list(anchored), "phase": "anchoring"}
```

with:

```python
def node_classify_faceid_scenes(state: GraphState) -> dict:
    """2-3: 사람 참조가 있는 씬을 LTX_FACEID 모드로 분류한다.

    2026-07-31 재설계: 원래 이 노드는 Flux로 씬별 배경 앵커를 생성해
    LTXVImgToVideo에 강도 1.0으로 고정했으나, 앵커 생성이 얼굴 참조를 전혀
    받지 않아 identity가 무작위였고 그 강한 lock이 뒤따르는 Face-ID Identity
    Transfer 노드를 무력화했다(참조 얼굴과 무관한 얼굴이 나옴, 실사용 재현
    검증 완료). 배경 다양성은 3.2에서 이미 증명됐듯 씬 프롬프트 텍스트만으로
    충분해 앵커가 불필요 — 순수 분류만 남긴다.
    """
    scenes = state.get("scenes") or []

    def classify(scene: Scene) -> Scene:
        matched = scene.get("matched_image")
        face_id_ref = (
            matched
            if matched
            and scene.get("subject_type") == "human"
            and scene.get("image_role") in ("start", "ref")
            else None
        )
        return {
            **scene,
            "face_id_ref": face_id_ref,
            "mode": "LTX_FACEID" if face_id_ref else scene.get("mode", "T2V"),
        }

    classified = [classify(scene) for scene in scenes]
    return {"scenes": classified, "phase": "anchoring"}
```

- [ ] **Step 2: Run the Task 3 test to verify it now passes**

Run: `cd /home/admin/DaolVision/langgraph && ./.venv/bin/python tests/test_scene_anchors.py`
Expected: `ok: scenes classify into LTX_FACEID/T2V without a Flux anchor call`

- [ ] **Step 3: Update `graph.py` node registration and edge**

In `langgraph/graph.py`, change line 40:

```python
    g.add_node("node_generate_scene_anchors", nodes.node_generate_scene_anchors)
```

to:

```python
    g.add_node("node_classify_faceid_scenes", nodes.node_classify_faceid_scenes)
```

Change line 74 (and the matching source-side of line 75, keep the target side `node_generate_ltx_batch` unchanged):

```python
    g.add_edge("node_generate_prompts", "node_generate_scene_anchors")
    g.add_edge("node_generate_scene_anchors", "node_generate_ltx_batch")
```

to:

```python
    g.add_edge("node_generate_prompts", "node_classify_faceid_scenes")
    g.add_edge("node_classify_faceid_scenes", "node_generate_ltx_batch")
```

Also update the Korean comment directly above (currently `# 씬별 Flux 앵커 + Face-ID 참조 첨부 후 Send API로 클립 생성을 fan-out한다.`, which is already stale relative to the uncommitted Task 5.3 rewiring) to:

```python
    # 사람 참조 씬을 LTX_FACEID로 분류한 뒤 배치 생성으로 넘긴다(앵커 없음, 3.2와 동일 배선).
```

- [ ] **Step 4: Delete the `anchor_image` field from `state.py`**

In `langgraph/state.py`, delete line 23:

```python
    anchor_image: str              # Phase 2.5 Flux가 생성한 씬별 I2V 첫 프레임 앵커
```

- [ ] **Step 5: Delete the Flux-anchor fake from `driver.py`**

In `langgraph/driver.py`, delete lines 86-93:

```python
    async def fake_scene_anchor(job_id, scene_id, prompt, seed=None):
        out = tools.job_dir(job_id) / f"anchor_scene_{scene_id}.png"
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i",
             f"color=c=navy:size={tools.WIDTH}x{tools.HEIGHT}", "-frames:v", "1", str(out)],
            check=True, capture_output=True,
        )
        return str(out)

```

and delete line 99 (now referring to a name that no longer exists on `tools`):

```python
    tools.generate_scene_anchor = fake_scene_anchor
```

- [ ] **Step 6: Regression — dry run and byte-compile**

Run: `cd /home/admin/DaolVision/langgraph && ./.venv/bin/python driver.py --dry`
Expected: dry run completes without raising (no `AttributeError`/`KeyError` from the removed `anchor_image` field or the renamed node).

Run: `./.venv/bin/python -m py_compile nodes.py graph.py state.py driver.py`
Expected: no output (success).

- [ ] **Step 7: Commit**

```bash
cd /home/admin/DaolVision
git add langgraph/nodes.py langgraph/graph.py langgraph/state.py langgraph/driver.py
git commit -m "refactor: rename node_generate_scene_anchors to node_classify_faceid_scenes

Drops the Flux anchor call entirely (Task 5.2 redesign) -- the node now
only classifies LTX_FACEID vs T2V mode. anchor_image field removed from
Scene state; no consumer needed it besides the now-removed anchor lock."
```

---

### Task 5: Fix the live probe script (face-size + drop anchor args)

**Files:**
- Modify: `langgraph/tests/probe_s1_ltx_batch_live.py` (entire file, currently untracked)

**Interfaces:**
- Consumes: `tools.generate_ltx_faceid_batch(job_id, scenes)` (unchanged signature; scenes no longer need `anchor_image`).
- No `tools.generate_scene_anchor` call anymore (function no longer exists).

**Context:** Live regen during design review showed the `"slow camera push-in"` phrasing in the scene prompts caused the subject to visibly grow across the 2-second clip (frame 0 → frame 24 comparison). Task 3.2's proven defaults are: wide/establishing shot, static camera, character small in frame relative to environment, expansive background — this task applies those defaults to all 4 scenes and drops the anchor plumbing.

- [ ] **Step 1: Replace the whole file**

```python
"""Task 5.3 live acceptance: LTX Face-ID clips 4개, 앵커 없이 3.2 배선 재사용."""
import asyncio
import argparse
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import nodes
import tools


JOB_ID = "task53-live-20260731"
FACE_SOURCE = Path(__file__).resolve().parents[2] / "건호군.jpg"
FACE_NAME = "astronaut_face.webp"

SCENES = [
    "A person astronaut with a transparent helmet visor, facing the camera, "
    "standing on a sunset launch pad, wide establishing shot, static camera, "
    "no camera movement, character small in frame relative to environment, "
    "expansive background.",
    "A person astronaut with a transparent helmet visor, facing the camera, "
    "floating above Earth during a spacewalk, wide cinematic shot, static "
    "camera, character small in frame relative to environment, stars and "
    "blue planet filling the expansive background.",
    "A person astronaut with a transparent helmet visor, facing the camera, "
    "standing on a rocky alien planet beneath two moons, wide establishing "
    "shot, static camera, character small in frame relative to environment, "
    "expansive violet landscape.",
    "A person astronaut with a transparent helmet visor, facing the camera, "
    "standing at the spacecraft hatch back on Earth, wide triumphant shot, "
    "static camera, character small in frame relative to environment, warm "
    "sunrise and recovery crew in the expansive background.",
]


async def main(scene_ids: set[int] | None = None):
    if not FACE_SOURCE.is_file():
        raise FileNotFoundError(FACE_SOURCE)
    ref_path = tools.refs_dir(JOB_ID) / FACE_NAME
    shutil.copyfile(FACE_SOURCE, ref_path)

    scenes = []
    print(f"[job] {JOB_ID}", flush=True)
    for scene_id, prompt in enumerate(SCENES, 1):
        if scene_ids and scene_id not in scene_ids:
            continue
        scenes.append({
            "id": scene_id,
            "text": prompt,
            "prompt": prompt,
            "duration": 2.0,
            "mode": "LTX_FACEID",
            "face_id_ref": FACE_NAME,
            "matched_image": FACE_NAME,
            "image_role": "ref",
            "subject_type": "human",
            "seed": nodes.scene_seed(JOB_ID, scene_id),
        })

    print("[ltx batch] submitting one graph with four sampler branches", flush=True)
    started = time.monotonic()
    clips = await tools.generate_ltx_faceid_batch(JOB_ID, scenes)
    print(f"[ltx batch] complete ({time.monotonic() - started:.1f}s)", flush=True)

    for scene in scenes:
        scene["clip_path"] = clips[scene["id"]]
    manifest = tools.job_dir(JOB_ID) / "manifest.json"
    manifest.write_text(json.dumps({
        "job_id": JOB_ID,
        "face_reference": str(ref_path),
        "scenes": scenes,
    }, ensure_ascii=False, indent=2))
    for scene in scenes:
        clip = Path(scene["clip_path"])
        if not clip.is_file() or clip.stat().st_size == 0:
            raise RuntimeError(f"missing clip: {clip}")
        print(f"[clip {scene['id']}/4] {clip} ({clip.stat().st_size} bytes)", flush=True)
    print(f"PASS manifest={manifest}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene-ids", default="")
    args = parser.parse_args()
    selected = {int(value) for value in args.scene_ids.split(",") if value}
    asyncio.run(main(scene_ids=selected or None))
```

- [ ] **Step 2: Byte-compile check**

Run: `cd /home/admin/DaolVision/langgraph && ./.venv/bin/python -m py_compile tests/probe_s1_ltx_batch_live.py`
Expected: no output (success).

- [ ] **Step 3: Commit**

```bash
cd /home/admin/DaolVision
git add langgraph/tests/probe_s1_ltx_batch_live.py
git commit -m "test: drop anchor plumbing and push-in framing from live LTX probe"
```

---

### Task 6: Update `Plans.md` and `.harness/STATE.md`

**Files:**
- Modify: `Plans.md:94-95` (rows 5.2, 5.3)
- Modify: `.harness/STATE.md` (append a correction entry; do not rewrite the already-committed 5.2 history bullet)

**Interfaces:** none — documentation only.

- [ ] **Step 1: Update `Plans.md` rows 94-95**

Replace:

```
| 5.2 | 앵커 생성 Flux + Face-ID 참조(우주비행사) 전달 | 씬별 앵커 생성 + 캐릭터 참조 첨부, driver --dry PASS | cd langgraph && ./.venv/bin/python driver.py --dry | 4.1, 5.1 | cc:완료 | - |
| 5.3 | I2V 클립 LTX+Face-ID 배치 생성 (로드1회 전씬) | 배치 로드로 4클립 생성, 씬별 재로드 없음, driver --dry PASS | cd langgraph && ./.venv/bin/python driver.py --dry | 3.2, 5.2 | cc:완료 | - |
```

with:

```
| 5.2 | LTX_FACEID 모드 분류 (사람 참조 씬만 식별, 앵커 없음) [재설계 2026-07-31] | 사람 start/ref 참조 씬만 LTX_FACEID로 분류, driver --dry PASS | cd langgraph && ./.venv/bin/python driver.py --dry | 4.1, 5.1 | cc:완료 | - |
| 5.3 | I2V 클립 LTX+Face-ID 배치 생성 (로드1회 전씬, 3.2와 동일 배선 — 앵커 lock 없음) | 배치 로드로 4클립 생성, 씬별 재로드 없음, 참조 얼굴과 육안 일치, driver --dry PASS | cd langgraph && ./.venv/bin/python driver.py --dry | 3.2, 5.2 | cc:완료 | - |
```

- [ ] **Step 2: Append a correction entry to `.harness/STATE.md`**

`.harness/STATE.md` is an append-only dated log (see the running bullets ending around line 606) — do not edit the existing 2026-07-31 Task 5.2/5.3 bullets in place. Append this new bullet immediately after the last existing line in that log section:

```markdown
- 2026-07-31, Task 5.2/5.3 재설계(정정). 위 Task 5.2/5.3 완료 기록은 Flux
  앵커(`node_generate_scene_anchors`)를 `LTXVImgToVideo strength=1.0`으로
  첫 프레임에 고정하는 설계였으나, 라이브 재생성 육안 검증(job
  `task53-live-20260731` 프레임 비교)에서 두 결함 확인:
  (1) Flux 앵커 생성이 얼굴 참조를 전혀 받지 않아 매번 무작위 얼굴 생성,
  (2) 그 무작위 얼굴을 강도 1.0으로 첫 프레임에 고정해 뒤따르는 Face-ID
  Identity Transfer(node 129)가 참조 얼굴로 override할 여지가 전혀 없었음
  — 최종 영상이 참조 얼굴과 무관한 사람으로 나옴(재현: 재검증 앵커가 완전히
  다른 여성 얼굴로 생성됨을 직접 확인). 씬 프롬프트의 "camera push-in" 문구도
  2초 클립 안에서 인물이 급격히 확대되는 별도 문제로 확인.
  **조치**: Flux 앵커 생성(`generate_scene_anchor`)과 앵커 lock 배선(node
  130/131, node 117/129 override)을 전부 제거하고 3.2가 검증한 순수 Face-ID
  배선(100 `EmptyLTXVLatentVideo` → 117 → 129←83)으로 복귀. 배경 다양성은
  3.2에서 이미 증명된 대로 씬 프롬프트 텍스트가 전담(앵커 불필요). 씬
  프롬프트는 push-in을 제거하고 3.2 기본값(wide/establishing shot, static
  camera, character small in frame)으로 통일. 설계 근거:
  `docs/superpowers/specs/2026-07-31-ltx-faceid-anchor-removal-design.md`.
  부가 효과: 씬당 ~177초였던 Flux 앵커 호출이 통째로 사라져 생성 시간도
  단축됨.
```

- [ ] **Step 3: Commit**

```bash
cd /home/admin/DaolVision
git add Plans.md .harness/STATE.md
git commit -m "docs: record Task 5.2/5.3 anchor-lock redesign in Plans.md/STATE.md"
```

---

### Task 7: Full regression + live visual re-verification

**Files:** none modified — verification only.

**Interfaces:** none.

- [ ] **Step 1: Re-run both unit tests together**

Run:
```bash
cd /home/admin/DaolVision/langgraph
./.venv/bin/python tests/test_scene_anchors.py
./.venv/bin/python tests/test_ltx_faceid_batch.py
```
Expected: both print their `ok: ...` lines, no assertion errors.

- [ ] **Step 2: Dry-run regression**

Run: `cd /home/admin/DaolVision/langgraph && ./.venv/bin/python driver.py --dry`
Expected: completes, prints a final job summary, no traceback.

- [ ] **Step 3: Byte-compile the whole package**

Run: `cd /home/admin/DaolVision/langgraph && ./.venv/bin/python -m py_compile tools.py nodes.py graph.py state.py driver.py tests/probe_s1_ltx_batch_live.py tests/test_scene_anchors.py tests/test_ltx_faceid_batch.py`
Expected: no output.

- [ ] **Step 4: Live single-scene re-verification (identity fix confirmation)**

Confirm `comfyui.service` and `flux.service` are active (`systemctl --user status comfyui.service flux.service`); start them if not (`systemctl --user start comfyui.service flux.service`, then poll `curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8188/system_stats` until `200`).

Run: `cd /home/admin/DaolVision/langgraph && ./.venv/bin/python tests/probe_s1_ltx_batch_live.py --scene-ids 1`
Expected: `PASS manifest=...` with a `clip1.mp4` written under `langgraph/jobs/task53-live-20260731/`.

Extract two frames and inspect them visually (Read tool supports images):
```bash
ffmpeg -y -i langgraph/jobs/task53-live-20260731/clip1.mp4 -vf "select=eq(n\,0)" -vframes 1 /tmp/verify_frame0.png -loglevel error
ffmpeg -y -i langgraph/jobs/task53-live-20260731/clip1.mp4 -vf "select=eq(n\,24)" -vframes 1 /tmp/verify_frame24.png -loglevel error
```
Expected: the face in both frames visibly matches `건호군.jpg` (same eyebrows/eyes/jawline), and the subject's on-screen size is stable between frame 0 and frame 24 (no push-in growth).

- [ ] **Step 5: Report result to the user**

Summarize pass/fail for each check above and give the exact frame/video file paths so the user can also open them directly.

---

## Plan Self-Review Notes

- **Spec coverage:** every file/change listed in the design spec's "컴포넌트별 변경" table has a corresponding task (tools.py → Tasks 1-2, nodes.py/graph.py/state.py/driver.py → Tasks 3-4, Plans.md/STATE.md → Task 6, prompt wording + probe script → Task 5, regression → Task 7).
- **Placeholder scan:** no TBD/TODO; every step has literal code or literal shell commands.
- **Type/name consistency:** `node_classify_faceid_scenes` used identically across Task 3 (test), Task 4 (implementation + graph.py registration). `_build_ltx_faceid_graph`'s new signature (`prompt, face_image, duration, seed, prefix` — no `anchor_image`) is used identically in Task 1's test and Task 2's implementation.
- **Scope:** single subsystem (LTX Face-ID pipeline), no decomposition needed — matches the approved design spec 1:1.
