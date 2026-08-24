"""tools.compose_product_frame 회귀 테스트 (6.23 조립 단계).

음료 광고 스파이크가 5개 스크립트에 걸쳐 복제해 쓰던 "배경 + 제품 픽셀 합성"을
tools로 승격한 것. 이 합성은 diffusion을 안 거치는 게 핵심이라(제품 identity를
구조적으로 보존) 결정론적으로 검증 가능하다.

occlusion_box는 제품을 쥔 씬 전용이다 — 손가락이 제품 뒤에 남으면 첫 프레임이
물리적으로 틀린 상태가 되고, LTX가 그걸 맞추려 수렴하는 약 1초가 그대로 화면에
보인다(2026-08-13 clip17 실측).

    cd langgraph && ./.venv/bin/python tests/test_compose_product_frame.py
"""
import sys
import tempfile
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tools

SKIN = (200, 150, 110, 255)     # r>g>b, r-b=90 → _skin_mask 통과
PRODUCT = (0, 0, 255, 255)


def _fixtures(tmp: Path) -> tuple[Path, Path]:
    bg = Image.new("RGBA", (400, 200), (255, 255, 255, 255))
    for x in range(180, 260):
        for y in range(80, 160):
            bg.putpixel((x, y), SKIN)
    bg_path = tmp / "bg.png"
    bg.save(bg_path)

    product = Image.new("RGBA", (40, 80), PRODUCT)
    product_path = tmp / "product.png"
    product.save(product_path)
    return bg_path, product_path


def test_places_product_at_requested_ratios():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        bg_path, product_path = _fixtures(tmp)
        out = tmp / "flat.png"
        tools.compose_product_frame(
            bg_path, product_path, out,
            width_ratio=0.10, center_x_ratio=0.50, bottom_y_ratio=0.90,
            warm_tint=False)
        img = Image.open(out).convert("RGB")
        # 폭 40px(=400*0.10), 높이 80px, 중심 x=200, 바닥 y=180 → 상자 (180,100)-(220,180)
        assert img.getpixel((200, 140)) == PRODUCT[:3], "제품이 지정 위치에 없음"
        assert img.getpixel((200, 190)) != PRODUCT[:3], "제품이 bottom_y 아래로 넘침"
        assert img.getpixel((200, 95)) != PRODUCT[:3], "제품이 계산 높이보다 위로 넘침"


def test_warm_tint_darkens_toward_warm():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        bg_path, product_path = _fixtures(tmp)
        out = tmp / "flat.png"
        tools.compose_product_frame(
            bg_path, product_path, out,
            width_ratio=0.10, center_x_ratio=0.50, bottom_y_ratio=0.90,
            warm_tint=True)
        r, g, b = Image.open(out).convert("RGB").getpixel((200, 140))
        # 파란 제품에 warm tint를 곱하면 B가 눌린다(255,220,165 곱연산 30% 블렌드).
        assert b < 255, "warm tint가 적용되지 않음"
        assert b > 150, f"tint가 과도함: b={b}"


def test_occlusion_box_restores_skin_over_product():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        bg_path, product_path = _fixtures(tmp)
        # 제품을 살색 사각형 한가운데에 얹는다.
        common = dict(width_ratio=0.10, center_x_ratio=0.55, bottom_y_ratio=0.80,
                      warm_tint=False)
        plain = tmp / "plain.png"
        tools.compose_product_frame(bg_path, product_path, plain, **common)
        assert Image.open(plain).convert("RGB").getpixel((220, 120)) == PRODUCT[:3]

        occluded = tmp / "occluded.png"
        tools.compose_product_frame(bg_path, product_path, occluded,
                                    occlusion_box=(180, 80, 260, 160), **common)
        assert Image.open(occluded).convert("RGB").getpixel((220, 120)) == SKIN[:3], \
            "occlusion_box를 줬는데 살색 픽셀이 제품 위로 복원되지 않음"


def test_matches_spike_scene3a_output_if_present():
    """스파이크 산출물이 디스크에 있으면 바이트 단위로 같은지 확인(파이티 검증).
    jobs/는 gitignore 대상이라 CI에서는 조용히 건너뛴다."""
    assets = tools.JOBS_DIR / "probe_bev_ad" / "assets"
    bg = assets / "scene3a_v8_bg.png"
    product = assets / "bottle_canonical_v3.png"
    expected = assets / "scene3a_v11_flat.png"
    if not (bg.exists() and product.exists() and expected.exists()):
        print("  [skip] 스파이크 자산 없음 — 파리티 검증 생략")
        return
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "flat.png"
        tools.compose_product_frame(
            bg, product, out,
            width_ratio=0.075, center_x_ratio=0.62, bottom_y_ratio=0.87,
            warm_tint=True, occlusion_box=(790, 430, 905, 655))
        assert out.read_bytes() == expected.read_bytes(), \
            "tools 합성 결과가 스파이크 확정본과 다름"
        print("  파리티 OK: 스파이크 씬3a 첫 프레임과 바이트 일치")


if __name__ == "__main__":
    test_places_product_at_requested_ratios()
    test_warm_tint_darkens_toward_warm()
    test_occlusion_box_restores_skin_over_product()
    test_matches_spike_scene3a_output_if_present()
    print("test_compose_product_frame: all passed")
