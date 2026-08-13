"""음료수 광고 스파이크 씬2 v12 — 검토안 1번: Kontext 배경블러를 완전히 빼는 대신
강도만 낮춘다(FLUX_BG_BLUR_RADIUS=31은 ComfyUI 최댓값 하드코딩, 원래 얼굴클로즈업용
세팅 — v8이 이 값을 그대로 써서 배경이 과도하게 뭉개짐). 세그멘테이션+블러 노드
(원본 19-22)는 유지하되 blur_radius/sigma만 낮춘 값 2개를 실측 비교한다.

실행: cd langgraph && ./.venv/bin/python tests/probe_bev_ad_scene2_v12.py <radius> <sigma>
예: ./.venv/bin/python tests/probe_bev_ad_scene2_v12.py 10 4
결과: jobs/probe_bev_ad/assets/scene2_v12_r{radius}_s{sigma}.png
"""
import asyncio
import sys
import time
from pathlib import Path

import httpx
from PIL import Image, ImageChops

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import tools  # noqa: E402

ASSETS = Path(__file__).resolve().parent.parent / "jobs" / "probe_bev_ad" / "assets"
RECOMPOSE_SEED = 20260813

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
    "matching soft contact shadow on the wooden bench, natural photographic "
    "grain, shallow depth of field with the background softly out of focus but "
    "still recognizable (basketball hoop and court lines still visible, not "
    "abstract blur)."
)
CONTROLNET_STRENGTH = 0.45


def _apply_warm_tint(product: Image.Image) -> Image.Image:
    rgb = product.convert("RGB")
    tint_layer = Image.new("RGB", rgb.size, WARM_TINT)
    multiplied = ImageChops.multiply(rgb, tint_layer)
    blended = Image.blend(rgb, multiplied, TINT_STRENGTH)
    out = blended.convert("RGBA")
    out.putalpha(product.split()[-1])
    return out


def compose_flat(bg_path: Path) -> Path:
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
    out = ASSETS / "scene2_v12_flat.png"
    bg.convert("RGB").save(out, "PNG")
    return out


def _build_kontext_graph_weak_blur(
    *, prompt: str, image_name: str, width: int, height: int, seed: int,
    controlnet_strength: float, blur_radius: int, blur_sigma: float,
) -> dict:
    """tools._build_flux_kontext_graph 그대로 복제, blur_radius/sigma만 파라미터화
    (원본은 FLUX_BG_BLUR_RADIUS=31 하드코딩 + sigma=10.0 하드코딩)."""
    return {
        "1": {"class_type": "UNETLoader",
              "inputs": {"unet_name": tools.FLUX_KONTEXT_UNET, "weight_dtype": "default"}},
        "2": {"class_type": "DualCLIPLoader", "inputs": {
            "clip_name1": tools.FLUX_KONTEXT_CLIP_L, "clip_name2": tools.FLUX_KONTEXT_T5,
            "type": "flux",
        }},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": tools.FLUX_KONTEXT_VAE}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["2", 0]}},
        "5": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["4", 0]}},
        "6": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "7": {"class_type": "FluxKontextImageScale", "inputs": {"image": ["6", 0]}},
        "19": {"class_type": "LoadBackgroundRemovalModel",
               "inputs": {"bg_removal_name": tools.FLUX_BG_REMOVAL_MODEL}},
        "20": {"class_type": "RemoveBackground",
               "inputs": {"bg_removal_model": ["19", 0], "image": ["7", 0]}},
        "21": {"class_type": "ImageBlur", "inputs": {
            "image": ["7", 0], "blur_radius": blur_radius, "sigma": blur_sigma,
        }},
        "22": {"class_type": "ImageCompositeMasked", "inputs": {
            "destination": ["21", 0], "source": ["7", 0], "x": 0, "y": 0,
            "resize_source": False, "mask": ["20", 0],
        }},
        "8": {"class_type": "VAEEncode", "inputs": {"pixels": ["22", 0], "vae": ["3", 0]}},
        "9": {"class_type": "ReferenceLatent",
              "inputs": {"conditioning": ["4", 0], "latent": ["8", 0]}},
        "10": {"class_type": "FluxGuidance",
               "inputs": {"conditioning": ["9", 0], "guidance": tools.FLUX_KONTEXT_GUIDANCE}},
        "11": {"class_type": "EmptySD3LatentImage",
               "inputs": {"width": width, "height": height, "batch_size": 1}},
        "15": {"class_type": "Canny",
               "inputs": {"image": ["22", 0], "low_threshold": 0.4, "high_threshold": 0.8}},
        "16": {"class_type": "ControlNetLoader",
               "inputs": {"control_net_name": tools.FLUX_CONTROLNET_UNION}},
        "17": {"class_type": "SetShakkerLabsUnionControlNetType",
               "inputs": {"control_net": ["16", 0], "type": "canny"}},
        "18": {"class_type": "ControlNetApplyAdvanced", "inputs": {
            "positive": ["10", 0], "negative": ["5", 0], "control_net": ["17", 0],
            "image": ["15", 0], "vae": ["3", 0], "strength": controlnet_strength,
            "start_percent": 0.0, "end_percent": 1.0,
        }},
        "12": {"class_type": "KSampler", "inputs": {
            "model": ["1", 0], "seed": seed, "steps": tools.FLUX_KONTEXT_STEPS, "cfg": 1.0,
            "sampler_name": "euler", "scheduler": "simple",
            "positive": ["18", 0], "negative": ["18", 1], "latent_image": ["11", 0],
            "denoise": 1.0,
        }},
        "13": {"class_type": "VAEDecode", "inputs": {"samples": ["12", 0], "vae": ["3", 0]}},
        "14": {"class_type": "SaveImage", "inputs": {"images": ["13", 0], "filename_prefix": "i2i_style"}},
    }


async def recompose(flat_path: Path, blur_radius: int, blur_sigma: float) -> Path:
    image_bytes = flat_path.read_bytes()
    normalized, img_width, img_height = tools._normalize_i2v_input(image_bytes)
    width, height = tools._flux_kontext_dims(img_width, img_height)

    timeout = httpx.Timeout(connect=10.0, read=180.0, write=60.0, pool=None)
    async with tools.oom.phase("i2i"), httpx.AsyncClient(timeout=timeout) as client:
        up = await client.post(
            f"{tools.COMFYUI_URL}/upload/image",
            files={"image": (f"scene2_v12_r{blur_radius}_input.png", normalized, "image/png")},
            data={"overwrite": "true"},
        )
        up.raise_for_status()
        uj = up.json()
        image_name = f"{uj['subfolder']}/{uj['name']}" if uj.get("subfolder") else uj["name"]

        graph = _build_kontext_graph_weak_blur(
            prompt=RECOMPOSE_PROMPT, image_name=image_name, width=width, height=height,
            seed=RECOMPOSE_SEED, controlnet_strength=CONTROLNET_STRENGTH,
            blur_radius=blur_radius, blur_sigma=blur_sigma)
        resp = await client.post(f"{tools.COMFYUI_URL}/prompt", json={"prompt": graph})
        resp.raise_for_status()
        prompt_id = resp.json()["prompt_id"]

        started_at = time.time()
        history_item = None
        while history_item is None:
            if time.time() - started_at > tools.STANDIN_QUEUE_TIMEOUT:
                raise TimeoutError("씬2 v12 recompose가 제한 시간 내 완료되지 않음")
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

    out_path = ASSETS / f"scene2_v12_r{blur_radius}_s{blur_sigma}.png"
    out_path.write_bytes(png.content)
    return out_path


async def main() -> int:
    blur_radius = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    blur_sigma = float(sys.argv[2]) if len(sys.argv) > 2 else 4.0
    flat = compose_flat(ASSETS / "scene2_v2_bg.png")
    print(f"합성(정면 제품샷): {flat}")
    recomposed = await recompose(flat, blur_radius, blur_sigma)
    print(f"scene 2 (v12, blur_radius={blur_radius}, sigma={blur_sigma}) -> {recomposed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
