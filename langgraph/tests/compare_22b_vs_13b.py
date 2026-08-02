"""LTX Face-ID 22B(GGUF) vs LTX-13B distilled 육안 비교(같은 이미지+프롬프트+seed).
결과 기록: docs/model-selection-i2v.md의 "2026-08-02 육안 비교" 절.

실행: /home/admin/DaolVision/langgraph/.venv/bin/python tests/compare_22b_vs_13b.py
(ComfyUI :8188 필요, 결과물은 tests/output_compare/에 저장·git 미추적)
"""
import base64
import json
import time
from io import BytesIO
from pathlib import Path

import httpx
from PIL import Image, ImageOps

COMFY_URL = "http://127.0.0.1:8188"
IMG_PATH = Path("/home/admin/DaolVision/건호군.jpg")
OUT_DIR = Path(__file__).resolve().parent / "output_compare"
WORKFLOW_DIR = Path(__file__).resolve().parent.parent / "comfyui_workflows"

PROMPT = (
    "a person taking photographs in a public garden, wide full-body shot, "
    "bright natural daylight, colorful surroundings"
)
SEED = 1234567890
TIMEOUT = httpx.Timeout(connect=10.0, read=60.0, write=60.0, pool=None)
QUEUE_TIMEOUT = 1800.0


def normalize_image(path: Path) -> tuple[bytes, int, int]:
    with Image.open(path) as opened:
        image = ImageOps.exif_transpose(opened).copy()
    if "A" in image.getbands():
        rgba = image.convert("RGBA")
        bg = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        image = Image.alpha_composite(bg, rgba).convert("RGB")
    else:
        image = image.convert("RGB")
    out = BytesIO()
    image.save(out, format="PNG", optimize=True)
    return out.getvalue(), image.width, image.height


def ltx13b_dims(img_width: int, img_height: int, max_dim: int = 768) -> tuple[int, int]:
    if img_width >= img_height:
        width = max_dim
        height = max(32, round(max_dim * img_height / img_width / 32) * 32)
    else:
        height = max_dim
        width = max(32, round(max_dim * img_width / img_height / 32) * 32)
    return width, height


def upload_image(client: httpx.Client, image_bytes: bytes, name: str) -> str:
    resp = client.post(
        f"{COMFY_URL}/upload/image",
        files={"image": (name, image_bytes, "image/png")},
        data={"overwrite": "true"},
    )
    resp.raise_for_status()
    data = resp.json()
    return f"{data['subfolder']}/{data['name']}" if data.get("subfolder") else data["name"]


def submit_and_wait(client: httpx.Client, graph: dict) -> dict:
    resp = client.post(f"{COMFY_URL}/prompt", json={"prompt": graph})
    resp.raise_for_status()
    prompt_id = resp.json()["prompt_id"]
    print(f"  submitted prompt_id={prompt_id}")

    started = time.time()
    while True:
        if time.time() - started > QUEUE_TIMEOUT:
            raise TimeoutError("timed out waiting for ComfyUI history")
        history = client.get(f"{COMFY_URL}/history/{prompt_id}").json()
        if prompt_id in history:
            item = history[prompt_id]
            if item.get("status", {}).get("status_str") == "error":
                raise RuntimeError(json.dumps(item["status"]["messages"], indent=2))
            return item
        time.sleep(3.0)


def fetch_output(client: httpx.Client, history_item: dict) -> tuple[bytes, str]:
    for node_out in history_item.get("outputs", {}).values():
        media = node_out.get("videos") or node_out.get("gifs") or node_out.get("images")
        if media:
            output = media[0]
            resp = client.get(f"{COMFY_URL}/view", params={
                "filename": output["filename"],
                "subfolder": output.get("subfolder", ""),
                "type": output.get("type", "output"),
            })
            resp.raise_for_status()
            return resp.content, output["filename"]
    raise RuntimeError("no video/image output found in history")


def build_13b_graph(image_name: str, width: int, height: int) -> dict:
    return {
        "1": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": "ltxv-13b-0.9.8-distilled-fp8.safetensors"}},
        "2": {"class_type": "CLIPLoader",
              "inputs": {"clip_name": "t5xxl_fp8_e4m3fn_scaled.safetensors", "type": "ltxv"}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": PROMPT, "clip": ["2", 0]}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {
            "text": "worst quality, blurry, jittery, distorted, low resolution",
            "clip": ["2", 0]}},
        "5": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "6": {"class_type": "ModelSamplingLTXV",
              "inputs": {"model": ["1", 0], "max_shift": 2.05, "base_shift": 0.95}},
        "12": {"class_type": "LTXVConditioning", "inputs": {
            "positive": ["3", 0], "negative": ["4", 0], "frame_rate": 24.0}},
        "7": {"class_type": "LTXVImgToVideo", "inputs": {
            "positive": ["12", 0], "negative": ["12", 1], "vae": ["1", 2],
            "image": ["5", 0], "width": width, "height": height,
            "length": 97, "batch_size": 1, "strength": 1.0}},
        "8": {"class_type": "LTXVScheduler", "inputs": {
            "steps": 8, "max_shift": 2.05, "base_shift": 0.95,
            "stretch": True, "terminal": 0.1}},
        "9": {"class_type": "KSampler", "inputs": {
            "model": ["6", 0], "seed": SEED, "steps": 8, "cfg": 1.0,
            "sampler_name": "euler", "scheduler": "normal",
            "positive": ["7", 0], "negative": ["7", 1], "latent_image": ["7", 2],
            "denoise": 1.0}},
        "10": {"class_type": "VAEDecode", "inputs": {"samples": ["9", 0], "vae": ["1", 2]}},
        "11": {"class_type": "SaveAnimatedWEBP", "inputs": {
            "images": ["10", 0], "filename_prefix": "compare_13b", "fps": 24,
            "lossless": False, "quality": 90, "method": "default"}},
    }


def build_22b_graph(face_image_name: str) -> dict:
    graph = json.loads((WORKFLOW_DIR / "ltx_faceid_api.json").read_text())
    graph["31"]["inputs"]["value"] = 4.0  # duration(s) ~= 13B's 97 frames @24fps
    graph["47"]["inputs"]["value"] = 24
    graph["50"]["inputs"]["noise_seed"] = SEED
    graph["66"]["inputs"]["steps"] = 8
    graph["98"]["inputs"]["preview_rate"] = 8
    graph["100"]["inputs"].update(width=768, height=768)
    graph["102"]["inputs"]["value"] = f"ref_t2v: {PROMPT}"
    graph["104"]["inputs"]["image"] = face_image_name
    graph["101"]["inputs"]["filename_prefix"] = "compare/LTX22B_compare"
    graph["129"]["inputs"]["reference_guidance_scale"] = 1.0
    graph["56"]["inputs"].pop("audio", None)
    return graph


def main():
    OUT_DIR.mkdir(exist_ok=True)
    raw = IMG_PATH.read_bytes()
    normalized, img_w, img_h = normalize_image(IMG_PATH)
    print(f"input image: {img_w}x{img_h}")

    with httpx.Client(timeout=TIMEOUT) as client:
        print("[13B] uploading + submitting...")
        width, height = ltx13b_dims(img_w, img_h)
        name_13b = upload_image(client, normalized, "compare_input_13b.png")
        item_13b = submit_and_wait(client, build_13b_graph(name_13b, width, height))
        content_13b, fname_13b = fetch_output(client, item_13b)
        (OUT_DIR / "13b.webp").write_bytes(content_13b)
        print(f"[13B] done -> {OUT_DIR / '13b.webp'} (orig: {fname_13b}, {width}x{height})")

        print("[22B Face-ID] uploading + submitting...")
        name_22b = upload_image(client, normalized, "compare_input_22b.png")
        item_22b = submit_and_wait(client, build_22b_graph(name_22b))
        content_22b, fname_22b = fetch_output(client, item_22b)
        (OUT_DIR / "22b.mp4").write_bytes(content_22b)
        print(f"[22B Face-ID] done -> {OUT_DIR / '22b.mp4'} (orig: {fname_22b}, 768x768)")

    print("\nDONE. compare:")
    print(f"  13B (no Face-ID): {OUT_DIR / '13b.webp'}")
    print(f"  22B (Face-ID):    {OUT_DIR / '22b.mp4'}")


if __name__ == "__main__":
    main()
