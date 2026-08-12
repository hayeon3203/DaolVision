"""음료수 광고 스파이크 정본 제품 자산 v2 — 실제 로고 합성(DaolFusion PNG) 대신
가상의 브랜드가 통째로 녹아든 패트병 음료를 FLUX-schnell T2I로 직접 생성한다
(사용자 지시 2026-08-12: "우리 png 로고 파일 활용하는게 아니라, 아예 그냥 가상의
브랜드의 패트병으로 된 음료수로 하고 싶어"). Task 1의 캔+Pillow 로고 합성 자산
(product_canonical.png)을 대체하는 v2 정본 — 이후 씬2/3 재작업은 이 픽셀만 재사용.

실행: cd langgraph && ./.venv/bin/python tests/probe_bev_ad_assets_v2.py
결과: jobs/probe_bev_ad/assets/{bottle_raw.png, bottle_canonical.png, bottle_flat.png}
"""
from pathlib import Path

import httpx
from PIL import Image, ImageDraw

ASSETS = Path(__file__).resolve().parent.parent / "jobs" / "probe_bev_ad" / "assets"
T2I_URL = "http://127.0.0.1:8501"
SEED = 20260815  # 1차 시도(20260814)는 조명 이슈 확인 위해 균일조명 명시 추가하며 재시도

BOTTLE_PROMPT = (
    "studio product photograph of a single clear plastic PET bottle of a "
    "fictional sports beverage brand, vibrant blue and orange gradient label "
    "wrapped around the bottle with a bold abstract lightning-bolt logo mark "
    "and a short invented brand name, bright orange bottle cap, standing "
    "upright, centered, pure white seamless background, flat even omnidirectional "
    "studio lighting with no single directional key light, no strong highlight "
    "or shadow favoring either side of the bottle, both left and right sides "
    "equally bright, photorealistic, no real world brand names or logos"
)


def generate_bottle() -> Path:
    out = ASSETS / "bottle_raw.png"
    if out.exists():
        print(f"[skip] {out} 이미 존재 — 재생성 금지(정본 고정)")
        return out
    timeout = httpx.Timeout(connect=10.0, read=600.0, write=60.0, pool=None)
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(f"{T2I_URL}/generate", json={
            "prompt": BOTTLE_PROMPT, "width": 768, "height": 1024, "seed": SEED})
        resp.raise_for_status()
        png = client.get(f"{T2I_URL}{resp.json()['image_url']}")
        png.raise_for_status()
    ASSETS.mkdir(parents=True, exist_ok=True)
    out.write_bytes(png.content)
    return out


def cutout(src: Path, flood_thresh: int = 60) -> Image.Image:
    """흰 배경을 네 모서리 floodfill로 제거해 RGBA 컷아웃 반환 (Task 1
    product_canonical 컷아웃과 동일 로직 재사용)."""
    img = Image.open(src).convert("RGBA")
    w, h = img.size
    marker = (255, 0, 255, 255)
    for corner in [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]:
        ImageDraw.floodfill(img, corner, marker, thresh=flood_thresh)
    px = img.load()
    for y in range(h):
        for x in range(w):
            if px[x, y] == marker:
                px[x, y] = (0, 0, 0, 0)
    return img.crop(img.getbbox())


def main() -> int:
    raw = generate_bottle()
    bottle = cutout(raw)
    out = ASSETS / "bottle_canonical.png"
    bottle.save(out, "PNG")
    flat = Image.new("RGBA", bottle.size, (255, 255, 255, 255))
    flat.alpha_composite(bottle)
    flat_path = ASSETS / "bottle_flat.png"
    flat.convert("RGB").save(flat_path, "PNG")
    print(f"정본(v2, 패트병): {out}")
    print(f"육안확인용: {flat_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
