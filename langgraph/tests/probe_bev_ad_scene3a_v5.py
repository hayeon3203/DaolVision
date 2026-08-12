"""음료수 광고 스파이크 씬3a v5 — v2(자연스러운 픽업+그립+마시기, 최고 동작
품질)로 복귀(사용자 지시: v4 정지컷은 손-병 분리가 더 어색해서 기각) + negative
prompt로 와인병/유리병 방향 억제를 시도한다. generate_i2v_fallback_clip은 negative
prompt가 tools._build_ltx13b_graph에 하드코딩돼 있어 커스터마이즈 불가 — 이 그래프를
직접 복제해 negative만 바꾼 뒤 tools._generate_ltx_job_clip으로 제출한다(기존 재개
로직 재사용, 신규 모델/그래프 아님 — 노드 파라미터만 다름).

실행: cd langgraph && ./.venv/bin/python tests/probe_bev_ad_scene3a_v5.py
결과: jobs/probe_bev_ad/clip3.mp4(덮어씀), assets/scene3a_v5_first.png
"""
import asyncio
import shutil
import sys
from pathlib import Path

import httpx
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import tools  # noqa: E402

JOB_ID = "probe_bev_ad"
ASSETS = Path(__file__).resolve().parent.parent / "jobs" / JOB_ID / "assets"
SEED = 20260813  # v2와 동일 시드(모션 품질이 v2에서 가장 좋았던 조건 그대로 유지)

SCENE_PROMPT = (
    "cinematic medium-close shot of a young Korean man's face and upper "
    "chest on an outdoor basketball court, wearing a plain white sleeveless "
    "jersey, mouth closed, head tilted slightly down as if about to drink, "
    "empty space in front of his chest at hand height, warm golden backlight, "
    "shallow depth of field, photorealistic"
)
I2V_PROMPT = (
    "cinematic, he raises the clear plastic bottle from chest height up to "
    "his lips and tilts it back to drink, the bottle stays a clear plastic "
    "PET sports drink bottle with an orange cap throughout, natural "
    "continuous motion, golden light"
)
NEGATIVE_PROMPT = (
    "worst quality, blurry, jittery, distorted, low resolution, wine bottle, "
    "beer bottle, glass bottle, dark green glass, dark bottle, wine, alcohol, "
    "champagne, opaque bottle, different object, morphing shape"
)


def _build_ltx13b_graph_custom_negative(
    *, prompt: str, negative: str, image_name: str, width: int, height: int, seed: int,
) -> dict:
    """tools._build_ltx13b_graph 그대로 복제, negative(node 4)만 커스텀 텍스트로
    교체 — 나머지 노드 배선은 완전히 동일(신규 그래프 아님)."""
    return {
        "1": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": tools.LTX13B_CHECKPOINT}},
        "2": {"class_type": "CLIPLoader",
              "inputs": {"clip_name": tools.LTX13B_CLIP, "type": "ltxv"}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["2", 0]}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["2", 0]}},
        "5": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "6": {"class_type": "ModelSamplingLTXV",
              "inputs": {"model": ["1", 0], "max_shift": 2.05, "base_shift": 0.95}},
        "12": {"class_type": "LTXVConditioning", "inputs": {
            "positive": ["3", 0], "negative": ["4", 0], "frame_rate": float(tools.LTX13B_FPS),
        }},
        "7": {"class_type": "LTXVImgToVideo", "inputs": {
            "positive": ["12", 0], "negative": ["12", 1], "vae": ["1", 2],
            "image": ["5", 0], "width": width, "height": height,
            "length": tools.LTX13B_FRAMES, "batch_size": 1, "strength": 1.0,
        }},
        "8": {"class_type": "LTXVScheduler", "inputs": {
            "steps": tools.LTX13B_STEPS, "max_shift": 2.05, "base_shift": 0.95,
            "stretch": True, "terminal": 0.1,
        }},
        "9": {"class_type": "KSampler", "inputs": {
            "model": ["6", 0], "seed": seed, "steps": tools.LTX13B_STEPS, "cfg": 1.0,
            "sampler_name": "euler", "scheduler": "normal",
            "positive": ["7", 0], "negative": ["7", 1], "latent_image": ["7", 2],
            "denoise": 1.0,
        }},
        "10": {"class_type": "VAEDecode", "inputs": {"samples": ["9", 0], "vae": ["1", 2]}},
        "11": {"class_type": "SaveAnimatedWEBP", "inputs": {
            "images": ["10", 0], "filename_prefix": "i2v_oneshot", "fps": tools.LTX13B_FPS,
            "lossless": False, "quality": 90, "method": "default",
        }},
    }


def compose_first_frame(
    bg_path: Path,
    *,
    product_width_ratio: float = 0.035,
    product_center_x_ratio: float = 0.50,
    product_bottom_y_ratio: float = 0.92,
) -> Path:
    """v2와 동일 배치(가슴 높이 시작, 자연스러운 픽업 거리) — 모션은 그대로 두고
    negative prompt만 바꿔 비교한다. 항상 정본 원본에서 새로 리사이즈(재생성 금지)."""
    bg = Image.open(bg_path).convert("RGBA")
    product = Image.open(ASSETS / "bottle_canonical.png").convert("RGBA")
    bw, bh = bg.size
    pw = int(bw * product_width_ratio)
    ph = int(product.height * (pw / product.width))
    product = product.resize((pw, ph), Image.LANCZOS)
    px = int(bw * product_center_x_ratio - pw / 2)
    py = int(bh * product_bottom_y_ratio - ph)
    bg.alpha_composite(product, (px, py))
    out = ASSETS / "scene3a_v5_first.png"
    bg.convert("RGB").save(out, "PNG")
    return out


async def _upload_and_generate(ref_path: Path, prompt: str, negative: str,
                                duration: float, seed: int) -> str:
    async with (
        tools.oom.phase("i2v"),
        httpx.AsyncClient(timeout=httpx.Timeout(connect=10.0, read=60.0, write=60.0, pool=None)) as client,
    ):
        up = await client.post(
            f"{tools.COMFYUI_URL}/upload/image",
            files={"image": (f"scene3a_v5_{ref_path.name}", ref_path.read_bytes(), "image/png")},
            data={"overwrite": "true"},
        )
        up.raise_for_status()
        uj = up.json()
        image_name = f"{uj['subfolder']}/{uj['name']}" if uj.get("subfolder") else uj["name"]

    length = tools.to_ltx_len(duration * tools.LTX13B_FPS)
    graph = _build_ltx13b_graph_custom_negative(
        prompt=prompt, negative=negative, image_name=image_name,
        width=tools.WIDTH, height=tools.HEIGHT, seed=seed)
    graph["7"]["inputs"]["length"] = length
    request_key = f"scene3a_v5_{seed}_{duration}_{hash(prompt) % 10000}"
    return await tools._generate_ltx_job_clip(JOB_ID, 3, graph, request_key, True)


async def main() -> int:
    bg_path = ASSETS / "scene3a_v2_bg.png"
    first = compose_first_frame(bg_path)
    print(f"조립 첫 프레임: {first}")
    clip = await _upload_and_generate(first, I2V_PROMPT, NEGATIVE_PROMPT, 3.0, SEED)
    print(f"scene 3a (v5, negative prompt) -> {clip}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
