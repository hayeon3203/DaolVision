"""음료수 광고 스파이크 제품 정본 v3 — 병목 주황 링 제거(2026-08-13 사용자 지시).

`bottle_canonical.png`(FLUX 생성분)에는 캡 아래 어깨 부분에 얇은 주황 가로 링이
있다. 영상에서 이게 계속 눈에 띈다는 지적(clip15).

정본 픽셀 실측: 주황 픽셀 밴드가 y 146~150(두께 5px), x 54~151에 있고 캡(y 3~61)·
번개 로고(y 378~512)·라벨 그라디언트(y 589~723)와 완전히 분리돼 있다. 그래서 링
밴드만 정확히 지울 수 있다.

제거 방식은 **diffusion 없이** 링 위/아래 행을 세로로 선형 보간해 덮는다(A노선
원칙: 제품 픽셀은 diffusion을 통과시키지 않는다). 병 재생성은 하지 않는다 —
재생성하면 라벨·형태가 통째로 바뀌어 지금까지 승인된 씬들과 어긋난다.

실행: cd langgraph && ./.venv/bin/python tests/probe_bev_ad_assets_v3.py
결과: assets/bottle_canonical_v3.png (+ 육안확인용 bottle_flat_v3.png)
"""
from pathlib import Path

import numpy as np
from PIL import Image

ASSETS = Path(__file__).resolve().parent.parent / "jobs" / "probe_bev_ad" / "assets"

# 실측값. 강한 주황 임계(r>190,g<180,b<120)로는 y146~150만 잡히지만, 느슨한 warm
# 임계((r-b)>18)로 보면 헤일로가 y144~152까지 번져 있다(각 행 76~102px). 좁게 잡으면
# 옅은 살구색 잔상이 그대로 남는다 — 헤일로 전체 + 여유 2px을 덮는다.
RING_Y0, RING_Y1 = 142, 154
RING_X0, RING_X1 = 45, 160


def remove_neck_ring(src: Path, out: Path) -> Path:
    img = Image.open(src).convert("RGBA")
    arr = np.array(img).astype(np.float64)
    above = arr[RING_Y0 - 1, RING_X0:RING_X1 + 1]     # 링 바로 위 행
    below = arr[RING_Y1 + 1, RING_X0:RING_X1 + 1]     # 링 바로 아래 행
    span = RING_Y1 - RING_Y0 + 2
    for i, y in enumerate(range(RING_Y0, RING_Y1 + 1), start=1):
        t = i / span
        arr[y, RING_X0:RING_X1 + 1] = above * (1 - t) + below * t
    Image.fromarray(arr.round().astype(np.uint8), "RGBA").save(out, "PNG")
    return out


def main() -> int:
    out = remove_neck_ring(ASSETS / "bottle_canonical.png",
                           ASSETS / "bottle_canonical_v3.png")
    bottle = Image.open(out).convert("RGBA")
    flat = Image.new("RGBA", bottle.size, (255, 255, 255, 255))
    flat.alpha_composite(bottle)
    flat_path = ASSETS / "bottle_flat_v3.png"
    flat.convert("RGB").save(flat_path, "PNG")
    print(f"정본(v3, 링 제거): {out}")
    print(f"육안확인용: {flat_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
