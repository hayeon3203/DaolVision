"""음료수 광고 스파이크 씬2 v9 — v8(Kontext 재통합, 사용자 호평)의 병 표현은
유지하되 배경 블러 문제를 고친다 + 3초 풀클립에서 인물이 병을 "뚫고" 지나가지
않는 자연스러운 접근 동작으로 재작업 (사용자 지시 2026-08-13).

(1) tools._build_flux_kontext_graph는 인물 얼굴 클로즈업용으로 설계돼 배경을
    강하게 블러하는 세그멘테이션(노드19-22)을 내장하고 있다 — 이 씬(광각
    제품+원거리 인물)엔 안 맞아 농구골대/코트 마크가 다 뭉개졌다. 그 노드들을
    건너뛰고 원본 배경 그대로 VAEEncode/Canny에 물리는 커스텀 그래프를 쓴다
    (신규 그래프 아님 — 기존 그래프에서 노드만 제거, 나머지 배선 동일).
(2) v3~v8은 전부 "카메라 정면으로 곧장 달려온다"였는데, 3초 내내 달리면 결국
    벤치(병 자리)에 도달해 밟고 지나간다. 이번엔 T2I 배경 자체를 인물이 더
    멀리서 출발하도록 다시 만들고, I2V 프롬프트에 "벤치 앞에서 속도를 줄이며
    멈춰선다"를 명시해 3초 끝에 벤치 앞에 자연스럽게 도착·정지하도록 한다
    (트림 불필요 — 동작 자체가 끝에서 멈춤).

실행: cd langgraph && ./.venv/bin/python tests/probe_bev_ad_scene2_v9.py
결과: jobs/probe_bev_ad/assets/scene2_v9_{bg,flat,recomposed}.png,
      jobs/probe_bev_ad/clip2.mp4 (3초 풀클립, 트림 없음)
"""
import asyncio
import shutil
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
T2I_URL = "http://127.0.0.1:8501"
SEED = 20260818  # 인물이 더 멀리서 출발하는 새 배경이라 시드 새로 시도

WARM_TINT = (255, 220, 165)
TINT_STRENGTH = 0.30
PRODUCT_WIDTH_RATIO = 0.075
PRODUCT_CENTER_X_RATIO = 0.30
PRODUCT_BOTTOM_Y_RATIO = 0.80

# 인물을 v2 대비 더 작게/멀리 시작시켜, 3초 동안 달려도 벤치 바로 앞에서
# 자연스럽게 도착하는 정도로 거리를 벌린다.
SCENE_PROMPT = (
    "cinematic sports commercial, low ground-level shot from right beside an "
    "empty wooden bench at the edge of an outdoor basketball court, the bench "
    "top is close to the camera and empty, very far in the background a young "
    "Korean man wearing a plain white sleeveless jersey and black shorts is "
    "running toward the camera, facing the camera with his face and chest "
    "visible, front view of a runner approaching the viewer, tiny distant "
    "figure far away near the far end of the court, deep perspective, court "
    "lines converging toward the camera, golden late-afternoon light, "
    "wide-angle lens, photorealistic"
)
I2V_PROMPT = (
    "cinematic, the man runs from far in the distance straight toward the "
    "camera, growing larger and closer with each stride, then slows down and "
    "comes to a stop right in front of the bench without stepping onto it, "
    "golden late-afternoon light"
)

RECOMPOSE_PROMPT = (
    "The exact same clear plastic sports drink bottle from the reference image, "
    "unchanged shape, unchanged blue and orange gradient label, unchanged "
    "lightning-bolt logo, unchanged orange cap — do not redesign it. Re-light "
    "and re-render only the bottle so it looks physically photographed in this "
    "exact golden late-afternoon outdoor scene: matching warm backlit rim light, "
    "matching soft contact shadow on the wooden bench, natural photographic "
    "grain. Everything else in the frame (the bench, the court, the runner, "
    "the background, its sharpness) stays exactly as it is — do not blur or "
    "change the background."
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


def generate_scene_bg() -> Path:
    out = ASSETS / "scene2_v9_bg.png"
    if out.exists():
        print(f"[skip] {out} 이미 존재")
        return out
    timeout = httpx.Timeout(connect=10.0, read=600.0, write=60.0, pool=None)
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(f"{T2I_URL}/generate", json={
            "prompt": SCENE_PROMPT, "width": 1280, "height": 720, "seed": SEED})
        resp.raise_for_status()
        png = client.get(f"{T2I_URL}{resp.json()['image_url']}")
        png.raise_for_status()
    out.write_bytes(png.content)
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
    out = ASSETS / "scene2_v9_flat.png"
    bg.convert("RGB").save(out, "PNG")
    return out


def _build_kontext_graph_no_bg_blur(
    *, prompt: str, image_name: str, width: int, height: int, seed: int,
    controlnet_strength: float,
) -> dict:
    """tools._build_flux_kontext_graph 그대로 복제하되 배경 세그멘테이션+블러
    (원본 노드 19/20/21/22)를 빼고, 원본 이미지(노드 7)를 그대로 VAEEncode/Canny에
    물린다 — 병만 재조명되고 배경 디테일(농구골대·코트 마크)은 원본 유지."""
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
        "8": {"class_type": "VAEEncode", "inputs": {"pixels": ["7", 0], "vae": ["3", 0]}},
        "9": {"class_type": "ReferenceLatent",
              "inputs": {"conditioning": ["4", 0], "latent": ["8", 0]}},
        "10": {"class_type": "FluxGuidance",
               "inputs": {"conditioning": ["9", 0], "guidance": tools.FLUX_KONTEXT_GUIDANCE}},
        "11": {"class_type": "EmptySD3LatentImage",
               "inputs": {"width": width, "height": height, "batch_size": 1}},
        "15": {"class_type": "Canny",
               "inputs": {"image": ["7", 0], "low_threshold": 0.4, "high_threshold": 0.8}},
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


async def recompose(flat_path: Path) -> Path:
    image_bytes = flat_path.read_bytes()
    normalized, img_width, img_height = tools._normalize_i2v_input(image_bytes)
    width, height = tools._flux_kontext_dims(img_width, img_height)

    timeout = httpx.Timeout(connect=10.0, read=180.0, write=60.0, pool=None)
    async with tools.oom.phase("i2i"), httpx.AsyncClient(timeout=timeout) as client:
        up = await client.post(
            f"{tools.COMFYUI_URL}/upload/image",
            files={"image": ("scene2_v9_recompose_input.png", normalized, "image/png")},
            data={"overwrite": "true"},
        )
        up.raise_for_status()
        uj = up.json()
        image_name = f"{uj['subfolder']}/{uj['name']}" if uj.get("subfolder") else uj["name"]

        graph = _build_kontext_graph_no_bg_blur(
            prompt=RECOMPOSE_PROMPT, image_name=image_name, width=width, height=height,
            seed=SEED, controlnet_strength=CONTROLNET_STRENGTH)
        resp = await client.post(f"{tools.COMFYUI_URL}/prompt", json={"prompt": graph})
        resp.raise_for_status()
        prompt_id = resp.json()["prompt_id"]

        started_at = time.time()
        history_item = None
        while history_item is None:
            if time.time() - started_at > tools.STANDIN_QUEUE_TIMEOUT:
                raise TimeoutError("씬2 v9 recompose가 제한 시간 내 완료되지 않음")
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

    out_path = ASSETS / "scene2_v9_recomposed.png"
    out_path.write_bytes(png.content)
    return out_path


async def main() -> int:
    # v9 1차 시도(새 배경, SEED 20260818)는 인물이 오히려 더 가깝게 나와 기각 —
    # 이미 검증된 v2 배경(인물 원거리 시작)을 그대로 재사용하고 I2V 프롬프트의
    # "멈춰선다" 지시만으로 해결한다.
    bg = ASSETS / "scene2_v2_bg.png"
    print(f"배경(v2 재사용, 인물 원거리 시작 검증됨): {bg}")
    flat = compose_flat(bg)
    print(f"합성(정면 제품샷): {flat}")
    recomposed = await recompose(flat)
    print(f"Kontext 재통합(배경블러 없음): {recomposed}")

    ref_name = "scene2_v9_recomposed.png"
    shutil.copyfile(recomposed, tools.refs_dir(JOB_ID) / ref_name)
    clip = await tools.generate_i2v_fallback_clip(
        job_id=JOB_ID, scene_id=2, prompt=I2V_PROMPT,
        matched_image=ref_name, duration=3.0, seed=SEED, force_new=True,
    )
    print(f"scene 2 (v9, 배경블러 제거 + 벤치 앞 정지 동작, 3초) -> {clip}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
