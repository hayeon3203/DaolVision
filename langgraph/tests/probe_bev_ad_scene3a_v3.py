"""음료수 광고 스파이크 씬3a v3 — v2에서 브랜드가 와인병으로 완전 변질된 문제
대응. LTXVImgToVideo의 strength가 이미 1.0(최대)이라 이미지 조건 강도로는 더
못 올림(tools.py:673 확인) — 남은 레버는 이동 거리·시간을 줄이는 것뿐이라
(1) 병 시작 위치를 가슴이 아니라 쇄골 바로 아래(입까지 거리 절반 이하)로,
(2) 클립 길이를 3.0s→2.0s로, (3) 시드 변경(붕괴가 시드 의존적인지 확인)
세 가지를 동시에 적용해 붕괴 억제 여부를 실측한다. 배경은 v2와 동일
(scene3a_v2_bg.png 재사용, 얼굴/구도 이미 검증됨).

실행: cd langgraph && ./.venv/bin/python tests/probe_bev_ad_scene3a_v3.py
결과: jobs/probe_bev_ad/clip3.mp4(덮어씀), assets/scene3a_v3_first.png
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
SEED = 20260816  # v2(20260813)에서 완전 붕괴 — 시드 의존성 확인 위해 변경

I2V_PROMPT = (
    "cinematic, the bottle lifts just slightly up to his lips and he drinks, "
    "small subtle motion, golden light"
)


def compose_first_frame(
    bg_path: Path,
    *,
    product_width_ratio: float = 0.035,
    product_center_x_ratio: float = 0.50,
    product_bottom_y_ratio: float = 0.78,
) -> Path:
    """v2(bottom_y_ratio=0.92, 가슴)보다 입에 훨씬 가깝게(0.78, 쇄골 바로 아래)
    배치 — 들어올릴 거리를 줄여 붕괴 전에 입에 닿게 한다. 항상 정본 원본에서
    새로 리사이즈(재생성 금지)."""
    bg = Image.open(bg_path).convert("RGBA")
    product = Image.open(ASSETS / "bottle_canonical.png").convert("RGBA")
    bw, bh = bg.size
    pw = int(bw * product_width_ratio)
    ph = int(product.height * (pw / product.width))
    product = product.resize((pw, ph), Image.LANCZOS)
    px = int(bw * product_center_x_ratio - pw / 2)
    py = int(bh * product_bottom_y_ratio - ph)
    bg.alpha_composite(product, (px, py))
    out = ASSETS / "scene3a_v3_first.png"
    bg.convert("RGB").save(out, "PNG")
    return out


async def main() -> int:
    bg_path = ASSETS / "scene3a_v2_bg.png"
    first = compose_first_frame(bg_path)
    print(f"조립 첫 프레임: {first}")
    ref_name = "scene3a_v3_first.png"
    shutil.copyfile(first, tools.refs_dir(JOB_ID) / ref_name)
    clip = await tools.generate_i2v_fallback_clip(
        job_id=JOB_ID, scene_id=3, prompt=I2V_PROMPT,
        matched_image=ref_name, duration=2.0, seed=SEED, force_new=True,
    )
    print(f"scene 3a (v3) -> {clip}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
