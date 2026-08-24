"""음료수 광고 스파이크 씬3a v11 — 병목 주황 링 없는 정본(v3)으로 재생성
(2026-08-13 사용자 지시).

씬3a는 v10(clip19)에서 확정됐다. 바꾸는 건 합성에 쓰는 병 픽셀 하나뿐 —
`bottle_canonical.png` → `bottle_canonical_v3.png`(링 제거본).

나머지는 확정 체인 그대로:
- 배경: scene3a_v8_bg.png (빈 그립 손 + 편안한 표정)
- 합성: v9 배치(center_x 0.62, width 0.075, bottom_y 0.87) + 손가락 픽셀 복원
- Kontext 재통합: v8/v9와 동일 프롬프트·시드
- I2V: v10 프롬프트(한 손 유지·입 높이 제한) + 동일 negative/시드

실행: cd langgraph && ./.venv/bin/python tests/probe_bev_ad_scene3a_v11.py
결과: assets/scene3a_v11_flat.png, scene3a_v11_recomposed.png,
      jobs/probe_bev_ad/clip21.mp4
"""
import asyncio
import sys
from pathlib import Path

import httpx
import numpy as np
from PIL import Image

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))
sys.path.insert(0, str(_HERE))
import tools  # noqa: E402
from probe_bev_ad_scene2_final import _apply_warm_tint  # noqa: E402
from probe_bev_ad_scene3a_v5 import (  # noqa: E402
    NEGATIVE_PROMPT, _build_ltx13b_graph_custom_negative,
)
from probe_bev_ad_scene3a_v8 import (  # noqa: E402
    I2V_SEED, RECOMPOSE_CN_STRENGTH, RECOMPOSE_PROMPT, RECOMPOSE_SEED, _kontext,
)
from probe_bev_ad_scene3a_v9 import (  # noqa: E402
    FINGER_BOX, GRIP_BOTTOM_Y_RATIO, GRIP_CENTER_X_RATIO, GRIP_WIDTH_RATIO, _skin_mask,
)
from probe_bev_ad_scene3a_v10 import I2V_PROMPT  # noqa: E402

JOB_ID = "probe_bev_ad"
ASSETS = _HERE.parent / "jobs" / JOB_ID / "assets"
SCENE_ID = 21
BOTTLE = "bottle_canonical_v3.png"


def compose_flat(bg_path: Path) -> Path:
    """v9와 동일 — 병 픽셀만 링 제거본으로 바뀐다."""
    bg = Image.open(bg_path).convert("RGBA")
    product = _apply_warm_tint(Image.open(ASSETS / BOTTLE).convert("RGBA"))
    bw, bh = bg.size
    pw = int(bw * GRIP_WIDTH_RATIO)
    ph = int(product.height * (pw / product.width))
    product = product.resize((pw, ph), Image.LANCZOS)
    px = int(bw * GRIP_CENTER_X_RATIO - pw / 2)
    py = int(bh * GRIP_BOTTOM_Y_RATIO - ph)

    composed = bg.copy()
    composed.alpha_composite(product, (px, py))
    mask = _skin_mask(bg, FINGER_BOX)
    comp_arr, bg_arr = np.array(composed), np.array(bg)
    comp_arr[mask] = bg_arr[mask]

    out = ASSETS / "scene3a_v11_flat.png"
    Image.fromarray(comp_arr, "RGBA").convert("RGB").save(out, "PNG")
    print(f"병 합성: {pw}x{ph}px @ ({px},{py})  |  손가락 복원 {int(mask.sum())}px")
    return out


async def main() -> int:
    flat = compose_flat(ASSETS / "scene3a_v8_bg.png")
    print(f"합성: {flat}")
    recomposed = await _kontext(
        flat, RECOMPOSE_PROMPT, RECOMPOSE_SEED, RECOMPOSE_CN_STRENGTH,
        tools.FLUX_KONTEXT_GUIDANCE, "scene3a_v11_recomposed.png",
        "scene3a_v11_recompose_input.png", "씬3a v11 Kontext 재통합")
    print(f"Kontext 재통합: {recomposed}")

    async with (
        tools.oom.phase("i2v"),
        httpx.AsyncClient(timeout=httpx.Timeout(connect=10.0, read=60.0, write=60.0, pool=None)) as client,
    ):
        up = await client.post(
            f"{tools.COMFYUI_URL}/upload/image",
            files={"image": (f"scene3a_v11_{recomposed.name}", recomposed.read_bytes(), "image/png")},
            data={"overwrite": "true"},
        )
        up.raise_for_status()
        uj = up.json()
        image_name = f"{uj['subfolder']}/{uj['name']}" if uj.get("subfolder") else uj["name"]

    graph = _build_ltx13b_graph_custom_negative(
        prompt=I2V_PROMPT, negative=NEGATIVE_PROMPT, image_name=image_name,
        width=tools.WIDTH, height=tools.HEIGHT, seed=I2V_SEED)
    graph["7"]["inputs"]["length"] = tools.to_ltx_len(3.0 * tools.LTX13B_FPS)
    clip = await tools._generate_ltx_job_clip(
        JOB_ID, SCENE_ID, graph, f"scene3a_v11_{I2V_SEED}", True)
    print(f"scene 3a (v11, 링 없는 병) -> {clip}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
