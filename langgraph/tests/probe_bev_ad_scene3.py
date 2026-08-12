"""음료수 광고 스파이크 씬3 (A노선) — 마시는 장면 2구도.
3a(scene_id=3): 캔+입술 타이트 클로즈업 — 손·입·제품 접촉 최소화 완화 구도.
3b(scene_id=4): 정면 미디엄 풀동작 — 대조군, 실패해도 기록 가치(설계문서).
둘 다 T2I 씬 + 정본 제품 픽셀 합성 → plain I2V.

실행: cd langgraph && ./.venv/bin/python tests/probe_bev_ad_scene3.py
결과: jobs/probe_bev_ad/clip3.mp4(3a), clip4.mp4(3b),
      assets/scene3a_first.png, assets/scene3b_first.png
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
T2I_URL = "http://127.0.0.1:8501"
SEED = 20260812

VARIANTS = {
    # name: (scene_id, T2I prompt, I2V prompt, 합성 파라미터)
    "scene3a": (
        3,
        "cinematic extreme close-up, lower half of a young Korean man's face, "
        "lips slightly parted, chin tilted up, sweat on his jawline, warm "
        "golden backlight, shallow depth of field, empty space in the lower "
        "third of the frame, photorealistic",
        "cinematic close-up, a silver aluminum can tilts up against his lips "
        "as he drinks, subtle swallowing motion, golden light",
        {"width_ratio": 0.30, "center_x_ratio": 0.50, "bottom_y_ratio": 1.02,
         "rotate_deg": -20},
    ),
    "scene3b": (
        4,
        "cinematic medium frontal shot, a young Korean man wearing a plain "
        "white sleeveless jersey and black shorts standing on an outdoor "
        "basketball court, his right arm bent holding his open hand at chest "
        "height, golden late-afternoon light, photorealistic",
        "cinematic, he raises the silver aluminum can to his mouth and drinks "
        "deeply, then lowers it with a satisfied breath",
        {"width_ratio": 0.065, "center_x_ratio": 0.46, "bottom_y_ratio": 0.57,
         "rotate_deg": 0},
    ),
}


def generate_bg(name: str, prompt: str) -> Path:
    out = ASSETS / f"{name}_bg.png"
    if out.exists():
        print(f"[skip] {out} 이미 존재")
        return out
    timeout = httpx.Timeout(connect=10.0, read=600.0, write=60.0, pool=None)
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(f"{T2I_URL}/generate", json={
            "prompt": prompt, "width": 1280, "height": 720, "seed": SEED})
        resp.raise_for_status()
        png = client.get(f"{T2I_URL}{resp.json()['image_url']}")
        png.raise_for_status()
    out.write_bytes(png.content)
    return out


def compose_first_frame(name: str, bg_path: Path, params: dict) -> Path:
    """정본 제품 픽셀 배치. 3a는 크게+기울여(입가 근처), 3b는 손 위치에 소형.
    비율/각도는 bg 육안 확인 후 조정(결정론 — 반복 조정 허용)."""
    bg = Image.open(bg_path).convert("RGBA")
    product = Image.open(ASSETS / "product_canonical.png").convert("RGBA")
    bw, bh = bg.size
    pw = int(bw * params["width_ratio"])
    ph = int(product.height * (pw / product.width))
    product = product.resize((pw, ph), Image.LANCZOS)
    if params["rotate_deg"]:
        product = product.rotate(params["rotate_deg"], expand=True,
                                 resample=Image.BICUBIC)
    px = int(bw * params["center_x_ratio"] - product.width / 2)
    py = int(bh * params["bottom_y_ratio"] - product.height)
    bg.alpha_composite(product, (px, py))
    out = ASSETS / f"{name}_first.png"
    bg.convert("RGB").save(out, "PNG")
    return out


async def main() -> int:
    for name, (scene_id, t2i_prompt, i2v_prompt, params) in VARIANTS.items():
        bg = generate_bg(name, t2i_prompt)
        first = compose_first_frame(name, bg, params)
        print(f"{name} 조립 첫 프레임: {first}")
        ref_name = f"{name}_first.png"
        shutil.copyfile(first, tools.refs_dir(JOB_ID) / ref_name)
        clip = await tools.generate_i2v_fallback_clip(
            job_id=JOB_ID, scene_id=scene_id, prompt=i2v_prompt,
            matched_image=ref_name, duration=3.0, seed=SEED, force_new=True,
        )
        print(f"{name} (scene_id={scene_id}) -> {clip}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
