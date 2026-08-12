"""음료수 광고 스파이크 씬3a v2 — 두 가지 변경 동시 반영(사용자 지시 2026-08-12):
(1) 제품을 가상 브랜드 패트병(bottle_canonical.png)으로 교체.
(2) v1은 조립 첫 프레임이 이미 "병이 입가에 도착한" 최종 자세라 픽업(들어올리는)
동작 자체가 렌더되지 않았음(0~1초 정지 상태로 확인됨) — 이번엔 병을 가슴 높이에
composite해 입까지 들어올리는 이동 동작이 실제로 필요하도록 프레임을 다시 짠다.
Task 4 결론(근접·능동 동작일수록 identity 붕괴 위험 큼)을 감안해 손-제품 접촉은
최소화(손에 쥔 모습 대신 가슴 앞 허공에 위치 — 기존 성공 패턴 유지).

실행: cd langgraph && ./.venv/bin/python tests/probe_bev_ad_scene3a_v2.py
결과: jobs/probe_bev_ad/clip3.mp4(덮어씀), assets/scene3a_v2_bg.png, assets/scene3a_v2_first.png
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
SEED = 20260813

SCENE_PROMPT = (
    "cinematic medium-close shot of a young Korean man's face and upper "
    "chest on an outdoor basketball court, wearing a plain white sleeveless "
    "jersey, mouth closed, head tilted slightly down as if about to drink, "
    "empty space in front of his chest at hand height, warm golden backlight, "
    "shallow depth of field, photorealistic"
)
I2V_PROMPT = (
    "cinematic, the bottle rises smoothly from chest height up to his lips "
    "and tilts back as he drinks, natural continuous motion, golden light"
)


def generate_scene_bg() -> Path:
    out = ASSETS / "scene3a_v2_bg.png"
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


def compose_first_frame(
    bg_path: Path,
    *,
    product_width_ratio: float = 0.035,
    product_center_x_ratio: float = 0.50,
    product_bottom_y_ratio: float = 0.92,
    rotate_deg: float = 0,
) -> Path:
    """정본 패트병 픽셀(bottle_canonical.png, 재생성 금지)을 가슴 높이(입가보다
    아래)에 배치 — v1(입가에 이미 도착)과 달리 I2V가 들어올리는 이동을
    실제로 그려야 한다. 비율은 scene3a_v2_bg.png 육안 확인 후 조정."""
    bg = Image.open(bg_path).convert("RGBA")
    product = Image.open(ASSETS / "bottle_canonical.png").convert("RGBA")
    bw, bh = bg.size
    pw = int(bw * product_width_ratio)
    ph = int(product.height * (pw / product.width))
    product = product.resize((pw, ph), Image.LANCZOS)
    if rotate_deg:
        product = product.rotate(rotate_deg, expand=True, resample=Image.BICUBIC)
    px = int(bw * product_center_x_ratio - product.width / 2)
    py = int(bh * product_bottom_y_ratio - product.height)
    bg.alpha_composite(product, (px, py))
    out = ASSETS / "scene3a_v2_first.png"
    bg.convert("RGB").save(out, "PNG")
    return out


async def main() -> int:
    bg = generate_scene_bg()
    first = compose_first_frame(bg)
    print(f"조립 첫 프레임: {first}")
    ref_name = "scene3a_v2_first.png"
    shutil.copyfile(first, tools.refs_dir(JOB_ID) / ref_name)
    clip = await tools.generate_i2v_fallback_clip(
        job_id=JOB_ID, scene_id=3, prompt=I2V_PROMPT,
        matched_image=ref_name, duration=3.0, seed=SEED, force_new=True,
    )
    print(f"scene 3a (v2) -> {clip}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
