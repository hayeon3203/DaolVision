"""음료수 광고 스파이크 씬2 v3 — 제품을 v2(DaolFusion 로고 합성 캔)에서 가상
브랜드 패트병(bottle_canonical.png, Task assets_v2)으로 교체. 배경/카메라 구도는
v2에서 이미 체이닝 안정성 PASS + 인물 정면 접근으로 검증된 scene2_v2_bg.png를
그대로 재사용 — 바뀌는 건 합성되는 제품 픽셀뿐.

실행: cd langgraph && ./.venv/bin/python tests/probe_bev_ad_scene2_v3.py
결과: jobs/probe_bev_ad/clip2.mp4(덮어씀), assets/scene2_v3_first.png
"""
import asyncio
import shutil
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import tools  # noqa: E402

JOB_ID = "probe_bev_ad"
ASSETS = Path(__file__).resolve().parent.parent / "jobs" / JOB_ID / "assets"
SEED = 20260813  # scene2_v2_bg.png와 동일 배경 재사용이라 씬 자체는 같은 시드 유지

I2V_PROMPT = (
    "cinematic, the man runs from far in the distance straight toward the "
    "camera, growing larger and closer with each stride, camera stays low and "
    "steady near the bench where a clear plastic sports drink bottle stands, "
    "golden late-afternoon light"
)


def compose_first_frame(
    bg_path: Path,
    *,
    product_width_ratio: float = 0.052,
    product_center_x_ratio: float = 0.30,
    product_bottom_y_ratio: float = 0.80,
) -> Path:
    """정본 패트병 픽셀(bottle_canonical.png, 재생성 금지·매번 원본에서 새로
    리사이즈)을 v2와 같은 벤치 자리에 배치. 병이 캔보다 좁고 길쭉해서
    width_ratio를 캔(0.10)보다 낮춰 비슷한 높이감을 맞춘다(육안 확인 후 조정)."""
    bg = Image.open(bg_path).convert("RGBA")
    product = Image.open(ASSETS / "bottle_canonical.png").convert("RGBA")
    bw, bh = bg.size
    pw = int(bw * product_width_ratio)
    ph = int(product.height * (pw / product.width))
    product = product.resize((pw, ph), Image.LANCZOS)
    px = int(bw * product_center_x_ratio - pw / 2)
    py = int(bh * product_bottom_y_ratio - ph)
    bg.alpha_composite(product, (px, py))
    out = ASSETS / "scene2_v3_first.png"
    bg.convert("RGB").save(out, "PNG")
    return out


async def main() -> int:
    bg_path = ASSETS / "scene2_v2_bg.png"
    first = compose_first_frame(bg_path)
    print(f"조립 첫 프레임: {first}")
    shutil.copyfile(first, tools.refs_dir(JOB_ID) / "scene2_v3_first.png")
    clip = await tools.generate_i2v_fallback_clip(
        job_id=JOB_ID, scene_id=2, prompt=I2V_PROMPT,
        matched_image="scene2_v3_first.png", duration=3.0,
        seed=SEED, force_new=True,
    )
    print(f"scene 2 (v3) -> {clip}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
