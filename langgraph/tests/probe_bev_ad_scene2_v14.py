"""음료수 광고 스파이크 씬2 v14 — 인물 상의를 반팔로 통일(2026-08-13 사용자 지시).

씬1이 v3에서 반팔로 확정됐는데(겨드랑이 털 제거) 씬2 배경 `scene2_v2_bg.png`의
인물은 민소매다. 트림 구간에서도 어깨가 식별될 만큼은 보인다(clip12_10.png,
1.25초 실측)이라 배경을 다시 만들어야 연속성이 맞는다.

씬1 v3에서 통한 방식 그대로 — **시드 고정 + 의상 명사 하나만 치환**.
`probe_bev_ad_scene2_v2.py`의 배경 프롬프트에서 `sleeveless jersey` →
`short-sleeve t-shirt`만 바꾸고 SEED(20260813)는 유지한다. 이후 체인
(합성 → Kontext 재통합 → I2V)은 확정본과 완전히 같은 파라미터·시드라
결정론적이다 — 소매 외의 변화는 배경 T2I가 시드 고정에도 구조를 얼마나
유지하느냐에만 달려 있다.

I2V 프롬프트/트림은 v13 결과(사용자 승인, 풀클립 3초 그대로)를 따른다.

실행: cd langgraph && ./.venv/bin/python tests/probe_bev_ad_scene2_v14.py
결과: assets/scene2_v14_bg.png, assets/scene2_v14_flat.png,
      assets/scene2_v14_recomposed.png, jobs/probe_bev_ad/clip15.mp4
"""
import asyncio
import shutil
import sys
import time
from pathlib import Path

import httpx
from PIL import Image

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))
sys.path.insert(0, str(_HERE))
import tools  # noqa: E402
from probe_bev_ad_scene2_final import (  # noqa: E402
    BLUR_RADIUS, BLUR_SIGMA, CONTROLNET_STRENGTH, PRODUCT_BOTTOM_Y_RATIO,
    PRODUCT_CENTER_X_RATIO, PRODUCT_WIDTH_RATIO, RECOMPOSE_PROMPT, RECOMPOSE_SEED,
    _apply_warm_tint, _build_kontext_graph_weak_blur,
)
from probe_bev_ad_scene2_v13 import I2V_PROMPT, I2V_SEED  # noqa: E402

JOB_ID = "probe_bev_ad"
ASSETS = _HERE.parent / "jobs" / JOB_ID / "assets"
T2I_URL = "http://127.0.0.1:8501"
BG_SEED = 20260813   # scene2_v2와 동일 — 의상 명사만 바꿔 차이를 격리
SCENE_ID = 15

# scene2_v2의 배경 프롬프트와 의상 명사 하나만 다름.
SCENE_PROMPT = (
    "cinematic sports commercial, low ground-level shot from right beside an "
    "empty wooden bench at the edge of an outdoor basketball court, the bench "
    "top is close to the camera and empty, in the far background a young "
    "Korean man wearing a plain white short-sleeve t-shirt and black shorts is "
    "running toward the camera, facing the camera with his face and chest "
    "visible, front view of a runner approaching the viewer, small distant "
    "figure far away on the court, deep perspective, court lines converging "
    "toward the camera, golden late-afternoon light, wide-angle lens, "
    "photorealistic"
)


def generate_scene_bg() -> Path:
    out = ASSETS / "scene2_v14_bg.png"
    if out.exists():
        print(f"[skip] {out} 이미 존재")
        return out
    timeout = httpx.Timeout(connect=10.0, read=600.0, write=60.0, pool=None)
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(f"{T2I_URL}/generate", json={
            "prompt": SCENE_PROMPT, "width": 1280, "height": 720, "seed": BG_SEED})
        resp.raise_for_status()
        png = client.get(f"{T2I_URL}{resp.json()['image_url']}")
        png.raise_for_status()
    out.write_bytes(png.content)
    return out


def compose_flat(bg_path: Path) -> Path:
    """확정본과 동일 배치·동일 warm tint. 항상 정본 원본에서 새로 리사이즈."""
    bg = Image.open(bg_path).convert("RGBA")
    product = _apply_warm_tint(Image.open(ASSETS / "bottle_canonical.png").convert("RGBA"))
    bw, bh = bg.size
    pw = int(bw * PRODUCT_WIDTH_RATIO)
    ph = int(product.height * (pw / product.width))
    product = product.resize((pw, ph), Image.LANCZOS)
    px = int(bw * PRODUCT_CENTER_X_RATIO - pw / 2)
    py = int(bh * PRODUCT_BOTTOM_Y_RATIO - ph)
    bg.alpha_composite(product, (px, py))
    out = ASSETS / "scene2_v14_flat.png"
    bg.convert("RGB").save(out, "PNG")
    return out


async def recompose(flat_path: Path) -> Path:
    normalized, img_width, img_height = tools._normalize_i2v_input(flat_path.read_bytes())
    width, height = tools._flux_kontext_dims(img_width, img_height)
    timeout = httpx.Timeout(connect=10.0, read=300.0, write=60.0, pool=None)
    async with tools.oom.phase("i2i"), httpx.AsyncClient(timeout=timeout) as client:
        up = await client.post(
            f"{tools.COMFYUI_URL}/upload/image",
            files={"image": ("scene2_v14_recompose_input.png", normalized, "image/png")},
            data={"overwrite": "true"},
        )
        up.raise_for_status()
        uj = up.json()
        image_name = f"{uj['subfolder']}/{uj['name']}" if uj.get("subfolder") else uj["name"]

        graph = _build_kontext_graph_weak_blur(
            prompt=RECOMPOSE_PROMPT, image_name=image_name, width=width, height=height,
            seed=RECOMPOSE_SEED, controlnet_strength=CONTROLNET_STRENGTH,
            blur_radius=BLUR_RADIUS, blur_sigma=BLUR_SIGMA)
        resp = await client.post(f"{tools.COMFYUI_URL}/prompt", json={"prompt": graph})
        resp.raise_for_status()
        prompt_id = resp.json()["prompt_id"]

        started_at = time.time()
        history_item = None
        while history_item is None:
            if time.time() - started_at > tools.STANDIN_QUEUE_TIMEOUT:
                raise TimeoutError("씬2 v14 recompose가 제한 시간 내 완료되지 않음")
            history = (await client.get(f"{tools.COMFYUI_URL}/history/{prompt_id}")).json()
            if prompt_id in history:
                history_item = history[prompt_id]
            else:
                await asyncio.sleep(2.0)
        if history_item.get("status", {}).get("status_str") == "error":
            raise RuntimeError(f"recompose 실행 오류 {history_item.get('status', {}).get('messages')}")

        media = None
        for node_out in history_item.get("outputs", {}).values():
            media = node_out.get("images")
            if media:
                break
        if not media:
            raise RuntimeError("recompose 출력 이미지 없음")
        output = media[0]
        png = await client.get(f"{tools.COMFYUI_URL}/view", params={
            "filename": output["filename"], "subfolder": output.get("subfolder", ""),
            "type": output.get("type", "output"),
        })
        png.raise_for_status()

    out_path = ASSETS / "scene2_v14_recomposed.png"
    out_path.write_bytes(png.content)
    return out_path


async def main() -> int:
    bg = generate_scene_bg()
    print(f"배경(반팔): {bg}")
    flat = compose_flat(bg)
    print(f"합성: {flat}")
    recomposed = await recompose(flat)
    print(f"Kontext 재통합(r{BLUR_RADIUS}/s{BLUR_SIGMA}): {recomposed}")

    ref_name = "scene2_v14_recomposed.png"
    shutil.copyfile(recomposed, tools.refs_dir(JOB_ID) / ref_name)
    clip = await tools.generate_i2v_fallback_clip(
        job_id=JOB_ID, scene_id=SCENE_ID, prompt=I2V_PROMPT,
        matched_image=ref_name, duration=3.0, seed=I2V_SEED, force_new=True,
    )
    print(f"scene 2 (v14, 반팔 풀클립) -> {clip}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
