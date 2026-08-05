"""
1회성 검증 스크립트 — LTX Face-ID ref_resize_mode A/B 비교.
768x768(match_target, 현재 기본값) vs 1280x704(match_target_letterbox, 크롭 없음)
동일 얼굴 ref + 동일 prompt/seed로 두 클립을 생성해 identity 손실 여부를 프레임으로 비교.
커밋 대상 아님(_ 프리픽스).

    ./.venv/bin/python tests/_faceid_resolution_ab.py
"""
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

import tools

JOB_ID = "astro1-9044f4"          # 기존 실제 run의 얼굴 ref 재사용
FACE_REF = "img_0.png"
PROMPT = (
    "A young male astronaut standing in the corner of a dark office, Earth looming "
    "silently on the curved wall behind him, his posture leaning forward with one hand "
    "outstretched palm upward toward the planet as if reaching across space, face "
    "neutral expression eyes slightly narrowed gaze fixed on Earth, subtle breath "
    "visible in cold air, camera slowly pulling back from wide establishing view "
    "revealing vast empty office depth and distant desk lights fading into shadows, "
    "composition emphasizing isolation against infinite void, Earth perfectly intact "
    "in background not blurred or abstract, photorealistic cinematic live-action "
    "rendering technique, natural lighting texture density high, surface materials "
    "realistic metallic sheen and reflective visor, line edge treatment clean "
    "non-drawn, shape language organic human form with slight compression from lens, "
    "prop design language functional space suit, camera character wide-angle deep "
    "focus anamorphic lens, color grading desaturated teal-orange palette low "
    "saturation high contrast bleach bypass effect, emotional tone quiet awe Scene "
    "lighting and atmosphere: low-key dim."
)
SEED = 440559665
DURATION = 3.0

# astro 5-run 비교 스크립트가 같은 ComfyUI 큐를 물고 있어 우리 job이 몇 분~십수 분
# 대기할 수 있다 — 넉넉히 잡는다.
HISTORY_TIMEOUT_S = 3600.0


async def _upload_ref(client: httpx.AsyncClient) -> str:
    image_path = tools.refs_dir(JOB_ID) / FACE_REF
    image_bytes = tools._prepare_reference_upload(image_path, subject_ref=False)
    resp = await client.post(
        f"{tools.COMFYUI_URL}/upload/image",
        files={"image": ("faceid_ab_ref.png", image_bytes, "image/png")},
        data={"overwrite": "true"},
    )
    resp.raise_for_status()
    data = resp.json()
    return f"{data.get('subfolder')}/{data['name']}" if data.get("subfolder") else data["name"]


def _build_graph(*, width: int, height: int, ref_resize_mode: str, prefix: str,
                  face_image: str) -> dict:
    graph = tools._build_ltx_faceid_graph(
        prompt=PROMPT, face_image=face_image, duration=DURATION, seed=SEED, prefix=prefix,
    )
    graph["100"]["inputs"].update(width=width, height=height)
    graph["129"]["inputs"]["ref_resize_mode"] = ref_resize_mode
    return graph


async def _wait_history(client: httpx.AsyncClient, prompt_id: str) -> dict:
    t0 = time.time()
    while True:
        if time.time() - t0 > HISTORY_TIMEOUT_S:
            raise TimeoutError(f"ComfyUI history timeout for {prompt_id}")
        history = (await client.get(f"{tools.COMFYUI_URL}/history/{prompt_id}")).json()
        if prompt_id in history:
            return history[prompt_id]
        await asyncio.sleep(5.0)


async def _run_and_download(client: httpx.AsyncClient, graph: dict, out_path: Path) -> None:
    resp = await client.post(f"{tools.COMFYUI_URL}/prompt", json={"prompt": graph})
    resp.raise_for_status()
    prompt_id = resp.json()["prompt_id"]
    print(f"  queued prompt_id={prompt_id}", flush=True)

    t0 = time.time()
    history_item = await _wait_history(client, prompt_id)

    if history_item.get("status", {}).get("status_str") == "error":
        raise RuntimeError(f"ComfyUI error: {history_item.get('status', {}).get('messages')}")

    outputs = history_item.get("outputs", {})
    node_101 = outputs.get("101", {})
    media = node_101.get("videos") or node_101.get("gifs") or node_101.get("images") or []
    if not media:
        raise RuntimeError(f"no media output: {json.dumps(outputs)[:500]}")
    m = media[0]
    params = {"filename": m["filename"], "type": m.get("type", "output")}
    if m.get("subfolder"):
        params["subfolder"] = m["subfolder"]
    dl = await client.get(f"{tools.COMFYUI_URL}/view", params=params)
    dl.raise_for_status()
    out_path.write_bytes(dl.content)
    dt = time.time() - t0
    print(f"  downloaded -> {out_path} ({dt:.1f}s)", flush=True)


async def main():
    out_dir = tools.JOBS_DIR.parent / "tests" / "output_compare" / "faceid_ab"
    out_dir.mkdir(parents=True, exist_ok=True)

    timeout = httpx.Timeout(connect=10.0, read=60.0, write=60.0, pool=None)
    async with httpx.AsyncClient(timeout=timeout) as client:
        face_image = await _upload_ref(client)

        print("[A] baseline 768x768 match_target", flush=True)
        graph_a = _build_graph(width=768, height=768, ref_resize_mode="match_target",
                                prefix="faceid_ab_baseline", face_image=face_image)
        await _run_and_download(client, graph_a, out_dir / "A_768x768_match_target.mp4")

        print("[B] candidate 1280x704 match_target_letterbox", flush=True)
        graph_b = _build_graph(width=1280, height=704, ref_resize_mode="match_target_letterbox",
                                prefix="faceid_ab_letterbox", face_image=face_image)
        await _run_and_download(client, graph_b, out_dir / "B_1280x704_letterbox.mp4")

    print("DONE", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
