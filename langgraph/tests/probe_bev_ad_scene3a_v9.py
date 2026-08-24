"""음료수 광고 스파이크 씬3a v9 — 첫 프레임의 손-병 occlusion을 결정론적으로 고친다
(2026-08-13 사용자 지적: clip17은 0~1초 동안 병이 합성한 것처럼 떠 있다가 서서히
손이 잡는 모양으로 모핑됨).

## 원인 (v8 프레임 실측)

clip17_01.png(0.25초)에서 병이 손가락 **앞에** 떠 있고 손가락은 전부 뒤에 있다.
`LTXVImgToVideo.strength=1.0`이라 첫 프레임이 그대로 고정되므로, 물리적으로 틀린
그 상태에서 시작해 diffusion이 맞는 상태로 수렴하는 과정이 그대로 화면에 보인다
(clip17_03.png에서 수렴 완료). Kontext 재통합도 못 고쳤다 — ControlNet canny
0.45가 "손가락 위에 얹힌 병" 실루엣을 그대로 잠그기 때문.

scene3a_v8_bg.png 확대 실측으로 기하 오류도 하나 더 나왔다: 손등이 카메라를
향하고 손가락은 오른쪽으로 말려 있어서 병이 들어갈 자리는 **손가락 말린 안쪽
(x≈830~900)**인데, v8은 병을 x 727~831 즉 손등 위에 얹었다.

## v9가 바꾸는 것 2가지 (둘 다 diffusion 없음 — 결정론적)

1. 병을 그립 안쪽으로 이동: center_x 0.56 → 0.62
2. **손가락 픽셀 복원**: 배경에서 손가락 영역(FINGER_BOX)의 살색 픽셀만 마스크로
   뽑아 병 위에 다시 얹는다. 손가락이 병 앞을 가로지르는 정상 occlusion이 된다.
   제품 픽셀은 여전히 diffusion을 안 거친다(A노선 원칙 유지).

실행: cd langgraph && ./.venv/bin/python tests/probe_bev_ad_scene3a_v9.py
결과: assets/scene3a_v9_flat.png, scene3a_v9_recomposed.png,
      jobs/probe_bev_ad/clip18.mp4
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
    I2V_PROMPT, I2V_SEED, RECOMPOSE_CN_STRENGTH, RECOMPOSE_PROMPT, RECOMPOSE_SEED,
    _kontext,
)

JOB_ID = "probe_bev_ad"
ASSETS = _HERE.parent / "jobs" / JOB_ID / "assets"
SCENE_ID = 18   # v8의 generate_clip을 그대로 쓰면 SCENE_ID=17이라 clip17을 덮어쓴다

GRIP_WIDTH_RATIO = 0.075
GRIP_CENTER_X_RATIO = 0.62    # v8은 0.56(손등 위) — 손가락 말린 안쪽으로 이동
GRIP_BOTTOM_Y_RATIO = 0.87

# scene3a_v8_bg.png(1392x752) 확대 실측: 손가락 끝 무리가 x 820~870, y 465~615에
# 있다. 여유를 둬서 잡되 손등(x<790)과 팔뚝(y>660)은 제외 — 그쪽까지 앞으로 얹으면
# 병이 손 전체 뒤로 들어가 "손 뒤에 숨은 병"이 된다.
FINGER_BOX = (790, 430, 905, 655)


def _skin_mask(img: Image.Image, box: tuple[int, int, int, int]) -> np.ndarray:
    """box 안에서 살색 픽셀만 True. box 안에는 흰 티셔츠(R≈G≈B)와 손밖에 없어서
    'R>G>B이고 R-B가 충분히 크다'는 단순 조건으로 분리된다(골든아워 조명이라
    손은 확실히 warm)."""
    arr = np.array(img.convert("RGB")).astype(np.int16)
    r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
    skin = (r > g) & (g > b) & ((r - b) > 25) & (r > 110)
    mask = np.zeros(skin.shape, dtype=bool)
    x0, y0, x1, y1 = box
    mask[y0:y1, x0:x1] = skin[y0:y1, x0:x1]
    return mask


def compose_flat(bg_path: Path) -> Path:
    bg = Image.open(bg_path).convert("RGBA")
    product = _apply_warm_tint(Image.open(ASSETS / "bottle_canonical.png").convert("RGBA"))
    bw, bh = bg.size
    pw = int(bw * GRIP_WIDTH_RATIO)
    ph = int(product.height * (pw / product.width))
    product = product.resize((pw, ph), Image.LANCZOS)
    px = int(bw * GRIP_CENTER_X_RATIO - pw / 2)
    py = int(bh * GRIP_BOTTOM_Y_RATIO - ph)

    composed = bg.copy()
    composed.alpha_composite(product, (px, py))

    # 손가락 복원 — 배경 원본 픽셀을 마스크로 다시 얹는다.
    mask = _skin_mask(bg, FINGER_BOX)
    comp_arr = np.array(composed)
    bg_arr = np.array(bg)
    comp_arr[mask] = bg_arr[mask]
    out_img = Image.fromarray(comp_arr, "RGBA")

    out = ASSETS / "scene3a_v9_flat.png"
    out_img.convert("RGB").save(out, "PNG")
    print(f"병 합성: {pw}x{ph}px @ ({px},{py})  |  손가락 복원 픽셀 {int(mask.sum())}개")
    return out


async def generate_clip(first: Path) -> str:
    """v8과 동일 배선 — SCENE_ID(18)와 request_key만 다르다."""
    async with (
        tools.oom.phase("i2v"),
        httpx.AsyncClient(timeout=httpx.Timeout(connect=10.0, read=60.0, write=60.0, pool=None)) as client,
    ):
        up = await client.post(
            f"{tools.COMFYUI_URL}/upload/image",
            files={"image": (f"scene3a_v9_{first.name}", first.read_bytes(), "image/png")},
            data={"overwrite": "true"},
        )
        up.raise_for_status()
        uj = up.json()
        image_name = f"{uj['subfolder']}/{uj['name']}" if uj.get("subfolder") else uj["name"]

    graph = _build_ltx13b_graph_custom_negative(
        prompt=I2V_PROMPT, negative=NEGATIVE_PROMPT, image_name=image_name,
        width=tools.WIDTH, height=tools.HEIGHT, seed=I2V_SEED)
    graph["7"]["inputs"]["length"] = tools.to_ltx_len(3.0 * tools.LTX13B_FPS)
    return await tools._generate_ltx_job_clip(
        JOB_ID, SCENE_ID, graph, f"scene3a_v9_{I2V_SEED}", True)


async def main() -> int:
    bg = ASSETS / "scene3a_v8_bg.png"
    flat = compose_flat(bg)
    print(f"합성(occlusion 복원): {flat}")
    recomposed = await _kontext(
        flat, RECOMPOSE_PROMPT, RECOMPOSE_SEED, RECOMPOSE_CN_STRENGTH,
        tools.FLUX_KONTEXT_GUIDANCE, "scene3a_v9_recomposed.png",
        "scene3a_v9_recompose_input.png", "씬3a v9 Kontext 재통합")
    print(f"Kontext 재통합: {recomposed}")
    clip = await generate_clip(recomposed)
    print(f"scene 3a (v9) -> {clip}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
