"""음료수 광고 스파이크 — 정본 제품 자산 생성 (2026-08-12 설계문서 Task 1).
1) FLUX-schnell(:8501)로 무지(라벨 없는) 알루미늄 캔 제품샷 생성 — 흰 배경
2) 흰 배경 floodfill 제거로 투명 컷아웃
3) DaolFusion 로고를 Pillow로 캔 몸통에 결정론 합성 (diffusion 무경유)
이 합성본(product_canonical.png)이 정본 — 이후 모든 씬은 픽셀 재사용만.

실행: cd langgraph && ./.venv/bin/python tests/probe_bev_ad_assets.py
결과: jobs/probe_bev_ad/assets/{can_raw.png, product_canonical.png, product_flat.png}
"""
from pathlib import Path

import httpx
from PIL import Image, ImageDraw

ASSETS = Path(__file__).resolve().parent.parent / "jobs" / "probe_bev_ad" / "assets"
T2I_URL = "http://127.0.0.1:8501"
LOGO = Path("/home/admin/DaolVision/DaolFusion_세로_tree.png")
SEED = 20260812

CAN_PROMPT = (
    "studio product photograph of a single sleek aluminum beverage can, "
    "plain blank brushed silver aluminum surface with no label and no text, "
    "standing upright, centered, pure white seamless background, "
    "soft even studio lighting, photorealistic"
)
PERSON_PROMPT = (
    "portrait photograph of a young Korean man in his early twenties, short "
    "black hair, clear frontal face looking at the camera, neutral friendly "
    "expression, head and shoulders, plain light gray background, natural "
    "soft lighting, photorealistic"
)


def _t2i(prompt: str, out: Path, *, width: int, height: int) -> Path:
    if out.exists():
        print(f"[skip] {out} 이미 존재 — 재생성 금지(정본 고정)")
        return out
    timeout = httpx.Timeout(connect=10.0, read=600.0, write=60.0, pool=None)
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(f"{T2I_URL}/generate", json={
            "prompt": prompt, "width": width, "height": height, "seed": SEED})
        resp.raise_for_status()
        png = client.get(f"{T2I_URL}{resp.json()['image_url']}")
        png.raise_for_status()
    ASSETS.mkdir(parents=True, exist_ok=True)
    out.write_bytes(png.content)
    return out


def generate_can() -> Path:
    return _t2i(CAN_PROMPT, ASSETS / "can_raw.png", width=768, height=1024)


def generate_person() -> Path:
    """신규 가상 인물 정본 (사용자 지시: 건호군.jpg 대신 T2I 생성 인물 사용).
    Face-ID 참조로 쓰므로 정면·선명 얼굴이 필수 — 육안 확인 후 불량이면
    SEED 변경 재생성(정본 확정 전에만 허용)."""
    return _t2i(PERSON_PROMPT, ASSETS / "person_canonical.png",
                width=768, height=1024)


def cutout(src: Path, flood_thresh: int = 60) -> Image.Image:
    """흰 배경을 네 모서리 floodfill로 제거해 RGBA 컷아웃 반환.
    ponytail: floodfill 임계 방식 — 캔 내부 흰 하이라이트는 보존됨(경계에서만 침투).
    배경이 안 지워지거나 캔이 침식되면 flood_thresh 조정."""
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


def composite_logo(
    can: Image.Image,
    *,
    logo_width_ratio: float = 0.62,
    logo_center_x_ratio: float = 0.50,
    logo_center_y_ratio: float = 0.52,
) -> Image.Image:
    """로고를 캔 몸통 중앙에 합성. 원본 로고를 매번 새로 리사이즈(누적 손실 방지).
    비율 기본값은 육안 확인 후 조정 가능(결정론 — 같은 값이면 항상 같은 결과)."""
    logo = Image.open(LOGO).convert("RGBA")
    cw, ch = can.size
    lw = int(cw * logo_width_ratio)
    lh = int(logo.height * (lw / logo.width))
    logo = logo.resize((lw, lh), Image.LANCZOS)
    lx = int(cw * logo_center_x_ratio - lw / 2)
    ly = int(ch * logo_center_y_ratio - lh / 2)
    out = can.copy()
    out.alpha_composite(logo, (lx, ly))
    return out


def main() -> int:
    raw = generate_can()
    can = cutout(raw)
    canonical = composite_logo(can)
    out = ASSETS / "product_canonical.png"
    canonical.save(out, "PNG")
    flat = Image.new("RGBA", canonical.size, (255, 255, 255, 255))
    flat.alpha_composite(canonical)
    flat_path = ASSETS / "product_flat.png"
    flat.convert("RGB").save(flat_path, "PNG")
    person = generate_person()
    print(f"제품 정본: {out}")
    print(f"육안확인용: {flat_path}")
    print(f"인물 정본: {person}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
