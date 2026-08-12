"""음료수 광고 스파이크 씬2 v4 — 사용자 피드백 2건 반영:
(1) 패트병이 너무 작아 부자연스러움 → width_ratio 확대.
(2) 합성 티(주변 골든아워 톤과 안 어우러짐) → 병 픽셀에 씬의 따뜻한 색조를
    약하게 곱연산으로 입혀 톤을 맞춘다(배경/구도는 v3와 동일, scene2_v2_bg.png
    재사용 — 이미 체이닝 PASS 검증된 배경).

실행: cd langgraph && ./.venv/bin/python tests/probe_bev_ad_scene2_v4.py
결과: jobs/probe_bev_ad/clip2.mp4(덮어씀), assets/scene2_v4_first.png
"""
import asyncio
import shutil
import sys
from pathlib import Path

from PIL import Image, ImageChops

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import tools  # noqa: E402

JOB_ID = "probe_bev_ad"
ASSETS = Path(__file__).resolve().parent.parent / "jobs" / JOB_ID / "assets"
SEED = 20260813

I2V_PROMPT = (
    "cinematic, the man runs from far in the distance straight toward the "
    "camera, growing larger and closer with each stride, camera stays low and "
    "steady near the bench where a clear plastic sports drink bottle stands, "
    "golden late-afternoon light"
)

# 골든아워 톤(주황빛 저녁 햇살) — scene2_v2_bg.png 하이라이트 영역 육안 샘플로
# 잡은 근사값. 병 픽셀에 약하게(30%) 곱연산해 스튜디오 중립광 느낌을 줄인다.
WARM_TINT = (255, 220, 165)
TINT_STRENGTH = 0.30


def _apply_warm_tint(product: Image.Image) -> Image.Image:
    rgb = product.convert("RGB")
    tint_layer = Image.new("RGB", rgb.size, WARM_TINT)
    multiplied = ImageChops.multiply(rgb, tint_layer)
    blended = Image.blend(rgb, multiplied, TINT_STRENGTH)
    out = blended.convert("RGBA")
    out.putalpha(product.split()[-1])
    return out


def compose_first_frame(
    bg_path: Path,
    *,
    product_width_ratio: float = 0.075,
    product_center_x_ratio: float = 0.30,
    product_bottom_y_ratio: float = 0.80,
) -> Path:
    """v3(0.052) 대비 병을 눈에 띄게 키운다(0.075) + 골든아워 톤 매칭.
    항상 정본 원본에서 새로 리사이즈(재생성 금지)."""
    bg = Image.open(bg_path).convert("RGBA")
    product = Image.open(ASSETS / "bottle_canonical.png").convert("RGBA")
    product = _apply_warm_tint(product)
    bw, bh = bg.size
    pw = int(bw * product_width_ratio)
    ph = int(product.height * (pw / product.width))
    product = product.resize((pw, ph), Image.LANCZOS)
    px = int(bw * product_center_x_ratio - pw / 2)
    py = int(bh * product_bottom_y_ratio - ph)
    bg.alpha_composite(product, (px, py))
    out = ASSETS / "scene2_v4_first.png"
    bg.convert("RGB").save(out, "PNG")
    return out


async def main() -> int:
    bg_path = ASSETS / "scene2_v2_bg.png"
    first = compose_first_frame(bg_path)
    print(f"조립 첫 프레임: {first}")
    ref_name = "scene2_v4_first.png"
    shutil.copyfile(first, tools.refs_dir(JOB_ID) / ref_name)
    clip = await tools.generate_i2v_fallback_clip(
        job_id=JOB_ID, scene_id=2, prompt=I2V_PROMPT,
        matched_image=ref_name, duration=3.0, seed=SEED, force_new=True,
    )
    print(f"scene 2 (v4) -> {clip}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
