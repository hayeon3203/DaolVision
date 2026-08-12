"""음료수 광고 스파이크 씬2 (A노선) — 첫 프레임 조립 → plain I2V.
1) FLUX T2I로 "코트 옆 벤치를 향해 달리는 인물" 씬 생성 (제품 없음)
2) 정본 제품 픽셀을 벤치 위에 Pillow 합성 (diffusion 무경유)
3) 조립된 첫 프레임을 plain I2V(LTX-13B, generate_i2v_fallback_clip)에 투입
핵심 관찰: 생성 이미지 → I2V 체이닝 불안정 재발 여부 (재발 시 A 노선 전제 붕괴).

실행: cd langgraph && ./.venv/bin/python tests/probe_bev_ad_scene2.py
결과: jobs/probe_bev_ad/clip2.mp4, assets/scene2_first.png
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

SCENE_PROMPT = (
    "cinematic sports commercial, a young Korean man wearing a plain white "
    "sleeveless jersey and black shorts running across an outdoor basketball "
    "court toward a wooden bench at the side of the court, the bench top is "
    "empty, golden late-afternoon light, wide shot, photorealistic"
)
I2V_PROMPT = (
    "cinematic, the man runs toward the bench where a silver aluminum can "
    "stands, camera follows him smoothly, golden late-afternoon light"
)


def generate_scene_bg() -> Path:
    out = ASSETS / "scene2_bg.png"
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
    product_width_ratio: float = 0.025,
    product_center_x_ratio: float = 0.83,
    product_bottom_y_ratio: float = 0.64,
) -> Path:
    """정본 제품 픽셀을 벤치 위에 소형 배치. 비율은 scene2_bg.png의 벤치 위치를
    육안으로 보고 조정한다(결정론 — 반복 조정 허용). 항상 정본 원본에서 새로
    리사이즈(중간 손실 누적 방지)."""
    bg = Image.open(bg_path).convert("RGBA")
    product = Image.open(ASSETS / "product_canonical.png").convert("RGBA")
    bw, bh = bg.size
    pw = int(bw * product_width_ratio)
    ph = int(product.height * (pw / product.width))
    product = product.resize((pw, ph), Image.LANCZOS)
    px = int(bw * product_center_x_ratio - pw / 2)
    py = int(bh * product_bottom_y_ratio - ph)
    bg.alpha_composite(product, (px, py))
    out = ASSETS / "scene2_first.png"
    bg.convert("RGB").save(out, "PNG")
    return out


async def main() -> int:
    bg = generate_scene_bg()
    first = compose_first_frame(bg)
    print(f"조립 첫 프레임: {first}")
    shutil.copyfile(first, tools.refs_dir(JOB_ID) / "scene2_first.png")
    clip = await tools.generate_i2v_fallback_clip(
        job_id=JOB_ID, scene_id=2, prompt=I2V_PROMPT,
        matched_image="scene2_first.png", duration=3.0,
        seed=SEED, force_new=True,
    )
    print(f"scene 2 -> {clip}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
