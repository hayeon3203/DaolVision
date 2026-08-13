"""음료수 광고 스파이크 씬2 v7 — 원근/그림자 보정 (사용자 지시, "여전히 어색함"
대응 1번 시도). v6(오버레이)와 정확히 같은 무-드리프트 오버레이 방식을 쓰되,
병 이미지에 두 가지를 추가한다:
1) 미세 원근 기울임(shear) — 벤치가 카메라 쪽에서 뒤로(오른쪽 위) 뻗어나가는
   각도라, 정면 제품샷을 그대로 붙이면 "스티커" 느낌이 남는다. 상단을 살짝
   오른쪽으로 기울여 그 각도에 얹힌 것처럼 보이게 한다.
2) 접지 그림자 — 병 밑동에 부드러운 타원 그림자를 깔아 벤치에 닿아있다는
   물리적 신호를 준다. 씬의 광원이 배경 상단(역광)에 있어 그림자는 카메라
   쪽(전경/왼쪽 아래)으로 떨어지게 배치.
diffusion 미경유(오버레이) 자체는 그대로 유지 — 드리프트 리스크 없음.

실행: cd langgraph && ./.venv/bin/python tests/probe_bev_ad_scene2_v7.py
결과: jobs/probe_bev_ad/clip2.mp4(덮어씀), assets/scene2_v7_overlay.png
"""
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
JOB_DIR = Path(__file__).resolve().parent.parent / "jobs" / "probe_bev_ad"
ASSETS = JOB_DIR / "assets"

WARM_TINT = (255, 220, 165)
TINT_STRENGTH = 0.30
PRODUCT_WIDTH_RATIO = 0.075
PRODUCT_CENTER_X_RATIO = 0.30
PRODUCT_BOTTOM_Y_RATIO = 0.80
BG_SIZE = (1280, 720)  # scene2_v2_bg.png와 동일

SHEAR_RATIO = 0.10       # 병 높이 대비 상단 이동폭 — 벤치 원근에 맞춘 기울임
SHADOW_OFFSET = (14, 6)  # 그림자 중심을 병 밑동에서 (오른쪽, 아래)로 미는 픽셀
SHADOW_SIZE_RATIO = 1.35  # 그림자 타원 폭 = 병 폭 * 이 값
SHADOW_BLUR = 6
SHADOW_ALPHA = 110        # 0-255


def _apply_warm_tint(product: Image.Image) -> Image.Image:
    rgb = product.convert("RGB")
    tint_layer = Image.new("RGB", rgb.size, WARM_TINT)
    multiplied = ImageChops.multiply(rgb, tint_layer)
    blended = Image.blend(rgb, multiplied, TINT_STRENGTH)
    out = blended.convert("RGBA")
    out.putalpha(product.split()[-1])
    return out


def _shear_top_right(img: Image.Image, shear_ratio: float) -> Image.Image:
    """상단을 오른쪽으로 shear_ratio*height 픽셀만큼 기울인다. 캔버스를 이동폭만큼
    넓혀서 잘림 없이 담는다."""
    w, h = img.size
    shift = int(h * shear_ratio)
    new_w = w + shift
    # PIL AFFINE은 출력→입력 역방향 매핑. 출력 (x,y)의 입력좌표 = (x - shift*(1 - y/h), y)
    # y=0(상단)일 때 input_x = x - shift → 오른쪽으로 shift만큼 당겨와 상단이 오른쪽으로 밀림.
    coeffs = (1, shift / h, -shift, 0, 1, 0)
    return img.transform((new_w, h), Image.AFFINE, coeffs, resample=Image.BICUBIC)


def _make_shadow(product_size: tuple[int, int]) -> Image.Image:
    pw, ph = product_size
    sw = int(pw * SHADOW_SIZE_RATIO)
    sh = max(6, int(sw * 0.22))
    pad = SHADOW_BLUR * 3
    canvas = Image.new("RGBA", (sw + pad * 2, sh + pad * 2), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    draw.ellipse([pad, pad, pad + sw, pad + sh], fill=(20, 15, 10, SHADOW_ALPHA))
    return canvas.filter(ImageFilter.GaussianBlur(SHADOW_BLUR))


def compose_overlay(bg_size: tuple[int, int] = BG_SIZE) -> tuple[Path, int, int]:
    product = Image.open(ASSETS / "bottle_canonical.png").convert("RGBA")
    product = _apply_warm_tint(product)
    bw, bh = bg_size
    pw = int(bw * PRODUCT_WIDTH_RATIO)
    ph = int(product.height * (pw / product.width))
    product = product.resize((pw, ph), Image.LANCZOS)
    sheared = _shear_top_right(product, SHEAR_RATIO)

    shadow = _make_shadow((pw, ph))
    canvas_w = max(sheared.width, shadow.width) + 40
    canvas_h = sheared.height + shadow.height
    canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))

    bottle_x = 20
    bottle_y = 0
    shadow_x = bottle_x + (sheared.width - shadow.width) // 2 + SHADOW_OFFSET[0]
    shadow_y = bottle_y + sheared.height - shadow.height // 2 + SHADOW_OFFSET[1]
    canvas.alpha_composite(shadow, (shadow_x, shadow_y))
    canvas.alpha_composite(sheared, (bottle_x, bottle_y))

    out = ASSETS / "scene2_v7_overlay.png"
    canvas.save(out, "PNG")

    # 배치 좌표: v6과 동일 기준점(병 밑동 중심)을 캔버스 offset 감안해 역산.
    base_center_x = int(bw * PRODUCT_CENTER_X_RATIO)
    base_bottom_y = int(bh * PRODUCT_BOTTOM_Y_RATIO)
    px = base_center_x - bottle_x - sheared.width // 2
    py = base_bottom_y - (bottle_y + sheared.height)
    return out, px, py


def overlay_and_trim(video: Path, overlay_png: Path, px: int, py: int,
                      out: Path, seconds: float = 1.4) -> Path:
    subprocess.run([
        "ffmpeg", "-y", "-i", str(video), "-i", str(overlay_png),
        "-filter_complex", f"[0][1]overlay={px}:{py}",
        "-t", str(seconds), "-pix_fmt", "yuv420p", str(out),
    ], check=True, capture_output=True)
    return out


def main() -> int:
    overlay_png, px, py = compose_overlay()
    print(f"보정된 오버레이 PNG: {overlay_png} @ ({px},{py})")
    no_overlay = JOB_DIR / "clip2_v6_no_overlay.mp4"  # v6에서 생성된 병-없는 원본 재사용
    if not no_overlay.exists():
        raise FileNotFoundError(f"{no_overlay} 없음 — 먼저 probe_bev_ad_scene2_v6.py 실행 필요")
    final = overlay_and_trim(no_overlay, overlay_png, px, py, JOB_DIR / "clip2.mp4")
    print(f"scene 2 (v7, 원근+그림자 보정) -> {final}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
