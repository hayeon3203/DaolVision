"""음료수 광고 스파이크 씬3a v12 — 첫 프레임 병 크기를 물리적으로 맞춘다
(2026-08-13 사용자 지적: clip19/clip21에서 병이 처음에 아주 작다가 점점 커짐).

## 실측

라벨 파랑 bbox 폭을 프레임 폭 대비로 재면 첫 프레임 3.5% → 2.25초 6.6%로 **약 1.9배**
커진다. 원인은 합성한 병이 물리적으로 너무 작다는 것 — LTX가 "저 얼굴 옆에 있을
병 크기"로 보정하는 과정이 화면에 보인다.

배경(scene3a_v8_bg.png) 얼굴 폭이 y=260(광대 높이)에서 276px다. 실제 얼굴 폭
15cm 기준 18.4px/cm이므로 PET 병 지름 7cm는 약 129px, 손이 얼굴보다 카메라에
가까우니 135~145px가 맞다. v11의 104px는 30% 작다.

## 바꾸는 것

`width_ratio` 0.075 → 0.10 (104px → 139px) **하나만**. 그립 span이 180px이라
139px 병은 손 안에 들어간다. 배경·배치 좌표·손가락 복원·Kontext·I2V 프롬프트·
시드 전부 v11 그대로.

실행: cd langgraph && ./.venv/bin/python tests/probe_bev_ad_scene3a_v12.py
결과: assets/scene3a_v12_flat.png, scene3a_v12_recomposed.png,
      jobs/probe_bev_ad/clip22.mp4
"""
import asyncio
import sys
from pathlib import Path

import httpx

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))
sys.path.insert(0, str(_HERE))
import tools  # noqa: E402
from probe_bev_ad_scene3a_v5 import (  # noqa: E402
    NEGATIVE_PROMPT, _build_ltx13b_graph_custom_negative,
)
from probe_bev_ad_scene3a_v8 import (  # noqa: E402
    I2V_SEED, RECOMPOSE_CN_STRENGTH, RECOMPOSE_PROMPT, RECOMPOSE_SEED, _kontext,
)
from probe_bev_ad_scene3a_v9 import (  # noqa: E402
    FINGER_BOX, GRIP_BOTTOM_Y_RATIO, GRIP_CENTER_X_RATIO,
)
from probe_bev_ad_scene3a_v10 import I2V_PROMPT  # noqa: E402

JOB_ID = "probe_bev_ad"
ASSETS = _HERE.parent / "jobs" / JOB_ID / "assets"
SCENE_ID = 22
GRIP_WIDTH_RATIO = 0.10   # v11은 0.075(104px) — 물리 계산상 30% 작았다


async def main() -> int:
    # 6.23으로 tools에 승격된 합성 헬퍼를 그대로 쓴다(스파이크 복제본 아님).
    flat = tools.compose_product_frame(
        ASSETS / "scene3a_v8_bg.png", ASSETS / "bottle_canonical_v3.png",
        ASSETS / "scene3a_v12_flat.png",
        width_ratio=GRIP_WIDTH_RATIO, center_x_ratio=GRIP_CENTER_X_RATIO,
        bottom_y_ratio=GRIP_BOTTOM_Y_RATIO, warm_tint=True,
        occlusion_box=FINGER_BOX)
    print(f"합성: {flat}")

    recomposed = await _kontext(
        Path(flat), RECOMPOSE_PROMPT, RECOMPOSE_SEED, RECOMPOSE_CN_STRENGTH,
        tools.FLUX_KONTEXT_GUIDANCE, "scene3a_v12_recomposed.png",
        "scene3a_v12_recompose_input.png", "씬3a v12 Kontext 재통합")
    print(f"Kontext 재통합: {recomposed}")

    async with (
        tools.oom.phase("i2v"),
        httpx.AsyncClient(timeout=httpx.Timeout(connect=10.0, read=60.0, write=60.0, pool=None)) as client,
    ):
        up = await client.post(
            f"{tools.COMFYUI_URL}/upload/image",
            files={"image": (f"scene3a_v12_{recomposed.name}", recomposed.read_bytes(), "image/png")},
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
        JOB_ID, SCENE_ID, graph, f"scene3a_v12_{I2V_SEED}", True)
    print(f"scene 3a (v12, 병 크기 물리 보정) -> {clip}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
