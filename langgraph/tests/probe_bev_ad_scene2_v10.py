"""음료수 광고 스파이크 씬2 v10 — v9의 성공한 절반만 취합한 최종 조합
(사용자 지시 2026-08-13). v9는 두 가지를 동시에 시도했다:
(A) Kontext 배경블러 제거 — 성공. 농구골대/코트 디테일 유지, 병 통합감 개선.
(B) 새 시드+"벤치 앞에서 멈춰선다" I2V 프롬프트로 풀 3초 자연 종료 — 실패.
    frame 9(1.3s)부터 이미 얼굴에 수염이 생기는 identity 드리프트, 마지막엔
    벤치에 손 짚고 쭈그려 앉는 기묘한 자세로 끝남.
v10은 (A)만 유지하고 (B)는 버린다 — I2V는 v5와 완전히 동일한 프롬프트/시드로
되돌리고(검증된 조합), 벤치 위 보행 구간은 자연 종료가 아니라 다시 1.4s 트림으로
처리한다("뚫고 지나가는" 문제의 최종 해법은 결국 트림).

실행: cd langgraph && ./.venv/bin/python tests/probe_bev_ad_scene2_v10.py
결과: jobs/probe_bev_ad/clip2.mp4(최종본), assets/scene2_v10_recomposed.png
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

RECOMPOSE_SEED = 20260813
I2V_SEED = 20260813  # v5와 동일 — 검증된 조합(다른 시드는 identity 드리프트 유발 확인됨)
TRIM_SECONDS = 1.4

WARM_TINT = (255, 220, 165)
TINT_STRENGTH = 0.30
PRODUCT_WIDTH_RATIO = 0.075
PRODUCT_CENTER_X_RATIO = 0.30
PRODUCT_BOTTOM_Y_RATIO = 0.80

I2V_PROMPT = (
    "cinematic, the man runs from far in the distance straight toward the "
    "camera, growing larger and closer with each stride, camera stays low and "
    "steady near the bench where a clear plastic sports drink bottle stands, "
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
    out = ASSETS / "scene2_v10_flat.png"
    bg.convert("RGB").save(out, "PNG")
    return out


def _build_kontext_graph_no_bg_blur(
    *, prompt: str, image_name: str, width: int, height: int, seed: int,
    controlnet_strength: float,
) -> dict:
    """tools._build_flux_kontext_graph 복제, 배경 세그멘테이션+블러(원본 노드
    19-22)만 제거 — 원본 이미지를 그대로 VAEEncode/Canny에 물려 배경 디테일 보존."""
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
            files={"image": ("scene2_v10_recompose_input.png", normalized, "image/png")},
            data={"overwrite": "true"},
        )
        up.raise_for_status()
        uj = up.json()
        image_name = f"{uj['subfolder']}/{uj['name']}" if uj.get("subfolder") else uj["name"]

        graph = _build_kontext_graph_no_bg_blur(
            prompt=RECOMPOSE_PROMPT, image_name=image_name, width=width, height=height,
            seed=RECOMPOSE_SEED, controlnet_strength=CONTROLNET_STRENGTH)
        resp = await client.post(f"{tools.COMFYUI_URL}/prompt", json={"prompt": graph})
        resp.raise_for_status()
        prompt_id = resp.json()["prompt_id"]

        started_at = time.time()
        history_item = None
        while history_item is None:
            if time.time() - started_at > tools.STANDIN_QUEUE_TIMEOUT:
                raise TimeoutError("씬2 v10 recompose가 제한 시간 내 완료되지 않음")
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

    out_path = ASSETS / "scene2_v10_recomposed.png"
    out_path.write_bytes(png.content)
    return out_path


def trim(src: Path, out: Path, seconds: float) -> Path:
    subprocess.run(["ffmpeg", "-y", "-i", str(src), "-t", str(seconds),
                     "-c", "copy", str(out)], check=True, capture_output=True)
    return out


async def main() -> int:
    bg = ASSETS / "scene2_v2_bg.png"  # 인물 원거리 시작 검증된 배경 재사용
    flat = compose_flat(bg)
    print(f"합성(정면 제품샷): {flat}")
    recomposed = await recompose(flat)
    print(f"Kontext 재통합(배경블러 없음): {recomposed}")

    ref_name = "scene2_v10_recomposed.png"
    shutil.copyfile(recomposed, tools.refs_dir(JOB_ID) / ref_name)
    clip = await tools.generate_i2v_fallback_clip(
        job_id=JOB_ID, scene_id=2, prompt=I2V_PROMPT,
        matched_image=ref_name, duration=3.0, seed=I2V_SEED, force_new=True,
    )
    full = JOB_DIR / "clip2_v10_full.mp4"
    Path(clip).replace(full)
    print(f"전체 클립(트림 전): {full}")
    final = trim(full, JOB_DIR / "clip2.mp4", TRIM_SECONDS)
    print(f"scene 2 (v10, 배경블러 제거 Kontext + 검증된 I2V + {TRIM_SECONDS}s 트림) -> {final}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
