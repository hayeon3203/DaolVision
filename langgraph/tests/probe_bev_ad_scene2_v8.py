"""음료수 광고 스파이크 씬2 v8 — Flux Kontext I2I로 병을 장면에 자연스럽게 통합
(사용자 지시: "병이 여전히 스튜디오 사진처럼 보임" → 2번 방법 시도).
v6/v7의 "정면 제품샷을 그대로 오버레이"는 원근/그림자를 추가해도 이질감이
안 없어졌다 — 근본 원인은 병 픽셀 자체가 스튜디오 조명으로 찍혀서 씬의 골든아워
역광과 재질감이 안 맞는 것. Kontext I2I로 "이 정지 이미지 한 장"을 씬 조명에
맞게 다시 그리게 시킨다(GB10 스파이크에서 검증된 recompose 패턴,
tests/probe_logo_hw_recompose.py와 동일 그래프 직호출).

정지 이미지 1장만 재생성하는 거라 씬3a급 identity 리스크는 없음(픽셀이 매 프레임
다시 그려지는 게 아니라 이 한 장만 한 번 그려짐 — 그 뒤엔 diffusion 없음,
v6과 동일하게 이 결과물을 그대로 I2V 첫 프레임으로 먹인다).

실행: cd langgraph && ./.venv/bin/python tests/probe_bev_ad_scene2_v8.py
결과: jobs/probe_bev_ad/assets/scene2_v8_recomposed.png (재통합된 정지 프레임),
      jobs/probe_bev_ad/clip2.mp4 (I2V까지 돌린 최종본)
"""
import asyncio
import shutil
import subprocess
import sys
import time
from pathlib import Path

import httpx
from PIL import Image, ImageChops

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import tools  # noqa: E402

JOB_ID = "probe_bev_ad"
ASSETS = Path(__file__).resolve().parent.parent / "jobs" / JOB_ID / "assets"
JOB_DIR = Path(__file__).resolve().parent.parent / "jobs" / JOB_ID
SEED = 20260813

WARM_TINT = (255, 220, 165)
TINT_STRENGTH = 0.30
PRODUCT_WIDTH_RATIO = 0.075
PRODUCT_CENTER_X_RATIO = 0.30
PRODUCT_BOTTOM_Y_RATIO = 0.80

RECOMPOSE_PROMPT = (
    "The exact same clear plastic sports drink bottle from the reference image, "
    "unchanged shape, unchanged blue and orange gradient label, unchanged "
    "lightning-bolt logo, unchanged orange cap — do not redesign it. Re-light "
    "and re-render only the bottle so it looks physically photographed in this "
    "exact golden late-afternoon outdoor scene: matching warm backlit rim light, "
    "matching soft contact shadow on the wooden bench, matching shallow depth of "
    "field sharpness falloff, natural photographic grain. Everything else in the "
    "frame (the bench, the court, the runner, the background) stays exactly "
    "as it is."
)
CONTROLNET_STRENGTH = 0.45  # GB10 스파이크 실측값 — identity 안정성과 재구성 자유의 중간


def _apply_warm_tint(product: Image.Image) -> Image.Image:
    rgb = product.convert("RGB")
    tint_layer = Image.new("RGB", rgb.size, WARM_TINT)
    multiplied = ImageChops.multiply(rgb, tint_layer)
    blended = Image.blend(rgb, multiplied, TINT_STRENGTH)
    out = blended.convert("RGBA")
    out.putalpha(product.split()[-1])
    return out


def compose_flat(bg_path: Path) -> Path:
    """v4와 동일한 '정면 제품샷 그대로 붙이기' 합성 — 이걸 Kontext 입력으로 쓴다."""
    bg = Image.open(bg_path).convert("RGBA")
    product = Image.open(ASSETS / "bottle_canonical.png").convert("RGBA")
    product = _apply_warm_tint(product)
    bw, bh = bg.size
    pw = int(bw * PRODUCT_WIDTH_RATIO)
    ph = int(product.height * (pw / product.width))
    product = product.resize((pw, ph), Image.LANCZOS)
    px = int(bw * PRODUCT_CENTER_X_RATIO - pw / 2)
    py = int(bh * PRODUCT_BOTTOM_Y_RATIO - ph)
    bg.alpha_composite(product, (px, py))
    out = ASSETS / "scene2_v8_flat.png"
    bg.convert("RGB").save(out, "PNG")
    return out


async def recompose(flat_path: Path) -> Path:
    image_bytes = flat_path.read_bytes()
    normalized, img_width, img_height = tools._normalize_i2v_input(image_bytes)
    width, height = tools._flux_kontext_dims(img_width, img_height)
    seed = SEED

    timeout = httpx.Timeout(connect=10.0, read=180.0, write=60.0, pool=None)
    async with tools.oom.phase("i2i"), httpx.AsyncClient(timeout=timeout) as client:
        up = await client.post(
            f"{tools.COMFYUI_URL}/upload/image",
            files={"image": ("scene2_v8_recompose_input.png", normalized, "image/png")},
            data={"overwrite": "true"},
        )
        up.raise_for_status()
        uj = up.json()
        image_name = f"{uj['subfolder']}/{uj['name']}" if uj.get("subfolder") else uj["name"]

        graph = tools._build_flux_kontext_graph(
            prompt=RECOMPOSE_PROMPT, image_name=image_name, width=width, height=height,
            seed=seed, lock_bg_color=False, guidance=tools.FLUX_KONTEXT_GUIDANCE,
            controlnet_strength=CONTROLNET_STRENGTH)
        resp = await client.post(f"{tools.COMFYUI_URL}/prompt", json={"prompt": graph})
        resp.raise_for_status()
        prompt_id = resp.json()["prompt_id"]

        started_at = time.time()
        history_item = None
        while history_item is None:
            if time.time() - started_at > tools.STANDIN_QUEUE_TIMEOUT:
                raise TimeoutError("씬2 v8 recompose가 제한 시간 내 완료되지 않음")
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

    out_path = ASSETS / "scene2_v8_recomposed.png"
    out_path.write_bytes(png.content)
    return out_path


async def main() -> int:
    flat = compose_flat(ASSETS / "scene2_v2_bg.png")
    print(f"합성(정면 제품샷 그대로): {flat}")
    recomposed = await recompose(flat)
    print(f"Kontext 재통합 완료: {recomposed}")

    ref_name = "scene2_v8_recomposed.png"
    shutil.copyfile(recomposed, tools.refs_dir(JOB_ID) / ref_name)
    i2v_prompt = (
        "cinematic, the man runs from far in the distance straight toward the "
        "camera, growing larger and closer with each stride, golden late-afternoon "
        "light, the bottle on the bench stays exactly as shown"
    )
    clip = await tools.generate_i2v_fallback_clip(
        job_id=JOB_ID, scene_id=2, prompt=i2v_prompt,
        matched_image=ref_name, duration=3.0, seed=SEED, force_new=True,
    )
    full = JOB_DIR / "clip2_v8_full.mp4"
    Path(clip).replace(full)
    print(f"전체 클립(트림 전): {full}")
    trimmed = JOB_DIR / "clip2.mp4"
    subprocess.run(["ffmpeg", "-y", "-i", str(full), "-t", "1.4",
                     "-c", "copy", str(trimmed)], check=True, capture_output=True)
    print(f"scene 2 (v8, Kontext 재통합 + I2V + 1.4s 트림) -> {trimmed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
