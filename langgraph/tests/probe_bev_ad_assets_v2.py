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


def cutout(src: Path, flood_thresh: int = 12, border_step: int = 20) -> Image.Image:
    """흰 배경을 제거해 RGBA 컷아웃 반환. 패트병처럼 투명한 소재는 병 내부의
    밝은 하이라이트 줄무늬가 배경색과 색상 거리가 가까워(실측 9~27, 배경 자체
    변동폭 최대 14와 겹침) 모서리 4점 + 관대한 threshold(60) 조합은 floodfill이
    병 안쪽까지 새어 들어가 구멍을 남긴다(사용자 발견, clip2v3_12에서 패트
    부분이 어색하게 비치는 현상의 원인 — 실측: red 배경에 합성해 확인하니 실제
    투명 구멍이었음, 모폴로지 closing으로도 안 메워질 만큼 큼).
    해결: threshold를 배경 내부 변동폭보다 약간 낮게(12) 잡아 하이라이트로
    새는 걸 원천 차단하고, 시드를 모서리 4점 대신 테두리 전체(20px 간격)에서
    출발시켜 배경의 국소적 색 변동(그림자/바닥 반사)도 짧은 경로로 모두
    커버한다 — 물체를 갉아먹지 않으면서 배경은 깨끗이 지워짐(실측 확인됨)."""
    img = Image.open(src).convert("RGBA")
    w, h = img.size
    marker = (255, 0, 255, 255)
    seeds = set()
    for x in range(0, w, border_step):
        seeds.add((x, 0))
        seeds.add((x, h - 1))
    for y in range(0, h, border_step):
        seeds.add((0, y))
        seeds.add((w - 1, y))
    px = img.load()
    for sx, sy in seeds:
        if px[sx, sy] != marker:
            ImageDraw.floodfill(img, (sx, sy), marker, thresh=flood_thresh)
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
