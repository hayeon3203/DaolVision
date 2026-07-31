"""LTX-Video-0.9.8-13B-distilled I2V 단발샷 테스트 (Face-ID 없음, LoRA 없음).

LTX-2.3 Face-ID 그래프와 달리 SetNode/GetNode pseudo-node가 없어 UI-format
변환(Playwright) 없이 API-format을 직접 구성해 제출한다. ComfyUI 코어 내장
LTX 노드(comfy_extras/nodes_lt.py)만 사용 — 커스텀 확장 불필요.

실행: /home/admin/comfyui-bench-venv/bin/python tests/probe_ltx13b_i2v.py <이미지경로> "<프롬프트>"
"""
import json
import sys
import time
import uuid
import base64
import urllib.request
from pathlib import Path

import websocket

COMFY_URL = "http://localhost:8188"
IMAGE_PATH = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/home/admin/video_generator/ComfyUI/input/geonho_ref.jpg")
PROMPT_TEXT = sys.argv[2] if len(sys.argv) > 2 else (
    "a person waving hello and smiling at the camera, natural lighting, realistic motion"
)
LOG_OUT = Path(__file__).resolve().parent / "_ltx13b_i2v_log.json"


def upload_image():
    with open(IMAGE_PATH, "rb") as f:
        data = f.read()
    boundary = "----ltx13bupload"
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{IMAGE_PATH.name}\"\r\n"
        f"Content-Type: application/octet-stream\r\n\r\n"
    ).encode() + data + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        f"{COMFY_URL}/upload/image", data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    resp = json.loads(urllib.request.urlopen(req).read())
    return resp["name"]


def build_prompt(image_name):
    return {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "ltxv-13b-0.9.8-distilled-fp8.safetensors"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "t5xxl_fp8_e4m3fn_scaled.safetensors", "type": "ltxv"}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": PROMPT_TEXT, "clip": ["2", 0]}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": "worst quality, blurry, jittery, distorted, low resolution", "clip": ["2", 0]}},
        "5": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "6": {"class_type": "ModelSamplingLTXV", "inputs": {"model": ["1", 0], "max_shift": 2.05, "base_shift": 0.95}},
        "12": {"class_type": "LTXVConditioning", "inputs": {"positive": ["3", 0], "negative": ["4", 0], "frame_rate": 24.0}},
        "7": {"class_type": "LTXVImgToVideo", "inputs": {
            "positive": ["12", 0], "negative": ["12", 1], "vae": ["1", 2],
            "image": ["5", 0], "width": 768, "height": 512, "length": 97, "batch_size": 1, "strength": 1.0,
        }},
        "8": {"class_type": "LTXVScheduler", "inputs": {"steps": 8, "max_shift": 2.05, "base_shift": 0.95, "stretch": True, "terminal": 0.1}},
        "9": {"class_type": "KSampler", "inputs": {
            "model": ["6", 0], "seed": 1234567890, "steps": 8, "cfg": 1.0,
            "sampler_name": "euler", "scheduler": "normal",
            "positive": ["7", 0], "negative": ["7", 1], "latent_image": ["7", 2], "denoise": 1.0,
        }},
        "10": {"class_type": "VAEDecode", "inputs": {"samples": ["9", 0], "vae": ["1", 2]}},
        "11": {"class_type": "SaveAnimatedWEBP", "inputs": {"images": ["10", 0], "filename_prefix": "ltx13b_i2v", "fps": 24, "lossless": False, "quality": 90, "method": "default"}},
    }


def run_and_capture(prompt, max_wait_s=1800):
    client_id = str(uuid.uuid4())
    ws = websocket.create_connection(f"ws://localhost:8188/ws?clientId={client_id}", timeout=30)
    body = json.dumps({"prompt": prompt, "client_id": client_id}).encode()
    req = urllib.request.Request(f"{COMFY_URL}/prompt", data=body, headers={"Content-Type": "application/json"})
    resp = json.loads(urllib.request.urlopen(req).read())
    if "error" in resp:
        raise RuntimeError(f"submit 거부: {json.dumps(resp, indent=2)}")
    prompt_id = resp["prompt_id"]
    print(f"submitted prompt_id={prompt_id}")

    t0 = time.time()
    events = []
    while time.time() - t0 < max_wait_s:
        try:
            msg = ws.recv()
        except websocket.WebSocketTimeoutException:
            hist = json.loads(urllib.request.urlopen(f"{COMFY_URL}/history/{prompt_id}").read())
            if prompt_id in hist:
                events.append({"t": round(time.time() - t0, 3), "type": "history_poll_done", "data": None})
                break
            continue
        if isinstance(msg, (bytes, bytearray)):
            continue
        data = json.loads(msg)
        events.append({"t": round(time.time() - t0, 3), "type": data.get("type"), "data": data.get("data")})
        d = data.get("data") or {}
        if data.get("type") == "executing" and d.get("node") is None and d.get("prompt_id") == prompt_id:
            break
        if data.get("type") == "execution_error" and d.get("prompt_id") == prompt_id:
            print("execution_error:", json.dumps(d, indent=2))
            break
    ws.close()
    return events, prompt_id


def main():
    image_name = upload_image()
    print(f"uploaded: {image_name}")
    prompt = build_prompt(image_name)
    events, prompt_id = run_and_capture(prompt)
    LOG_OUT.write_text(json.dumps({"prompt_id": prompt_id, "events": events}, indent=2, ensure_ascii=False))
    print(f"raw log: {LOG_OUT}")


if __name__ == "__main__":
    main()
