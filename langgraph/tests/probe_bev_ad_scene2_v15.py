"""음료수 광고 스파이크 씬2 v15 — 병목 주황 링 없는 정본(v3)으로 재생성
(2026-08-13 사용자 지시).

v14(clip15)가 씬2 유력 후보로 확정됐고, 남은 지적은 병목의 주황 가로 링 하나뿐이다.
그 링은 Kontext가 만든 게 아니라 FLUX 생성 정본 자체에 있던 것이라
`probe_bev_ad_assets_v3.py`가 diffusion 없이 지워 `bottle_canonical_v3.png`를 만들었다.

바꾸는 건 합성에 쓰는 병 픽셀 하나뿐이다 — 배경(scene2_v14_bg.png), 배치 비율,
warm tint, Kontext 재통합 파라미터/시드, I2V 프롬프트/시드 전부 v14 그대로.

실행: cd langgraph && ./.venv/bin/python tests/probe_bev_ad_scene2_v15.py
결과: assets/scene2_v15_flat.png, scene2_v15_recomposed.png,
      jobs/probe_bev_ad/clip20.mp4
"""
import asyncio
import shutil
import sys
from pathlib import Path

from PIL import Image

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))
sys.path.insert(0, str(_HERE))
import tools  # noqa: E402
from probe_bev_ad_scene2_final import (  # noqa: E402
    PRODUCT_BOTTOM_Y_RATIO, PRODUCT_CENTER_X_RATIO, PRODUCT_WIDTH_RATIO,
    RECOMPOSE_PROMPT, RECOMPOSE_SEED, _apply_warm_tint,
)
from probe_bev_ad_scene2_final import CONTROLNET_STRENGTH  # noqa: E402
from probe_bev_ad_scene2_v13 import I2V_PROMPT, I2V_SEED  # noqa: E402
from probe_bev_ad_scene3a_v8 import _kontext  # noqa: E402

JOB_ID = "probe_bev_ad"
ASSETS = _HERE.parent / "jobs" / JOB_ID / "assets"
SCENE_ID = 20
BOTTLE = "bottle_canonical_v3.png"   # v14는 bottle_canonical.png(링 있음)


def compose_flat(bg_path: Path) -> Path:
    bg = Image.open(bg_path).convert("RGBA")
    product = _apply_warm_tint(Image.open(ASSETS / BOTTLE).convert("RGBA"))
    bw, bh = bg.size
    pw = int(bw * PRODUCT_WIDTH_RATIO)
    ph = int(product.height * (pw / product.width))
    product = product.resize((pw, ph), Image.LANCZOS)
    px = int(bw * PRODUCT_CENTER_X_RATIO - pw / 2)
    py = int(bh * PRODUCT_BOTTOM_Y_RATIO - ph)
    bg.alpha_composite(product, (px, py))
    out = ASSETS / "scene2_v15_flat.png"
    bg.convert("RGB").save(out, "PNG")
    print(f"병 합성: {pw}x{ph}px @ ({px},{py})")
    return out


async def main() -> int:
    flat = compose_flat(ASSETS / "scene2_v14_bg.png")
    print(f"합성: {flat}")
    recomposed = await _kontext(
        flat, RECOMPOSE_PROMPT, RECOMPOSE_SEED, CONTROLNET_STRENGTH,
        tools.FLUX_KONTEXT_GUIDANCE, "scene2_v15_recomposed.png",
        "scene2_v15_recompose_input.png", "씬2 v15 Kontext 재통합")
    print(f"Kontext 재통합: {recomposed}")

    ref_name = "scene2_v15_recomposed.png"
    shutil.copyfile(recomposed, tools.refs_dir(JOB_ID) / ref_name)
    clip = await tools.generate_i2v_fallback_clip(
        job_id=JOB_ID, scene_id=SCENE_ID, prompt=I2V_PROMPT,
        matched_image=ref_name, duration=3.0, seed=I2V_SEED, force_new=True,
    )
    print(f"scene 2 (v15, 링 없는 병) -> {clip}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
