"""음료수 광고 스파이크 씬3a v7 — 첫 프레임의 병을 키운다(2026-08-13 사용자 지시).

v6 실측: 배경 1392x752에 병이 `width_ratio=0.035` = **48px 폭**으로 합성됐는데
(assets/scene3a_v6_first.png — 손도 없이 가슴 앞에 떠 있는 아주 작은 병), 정작
마시는 프레임에서는 병이 340px대로 커진다. 스케일 점프가 7배라 LTX가 병을
"재발명"할 수밖에 없고, 그 결과 주황 캡·그라디언트 라벨이 다 날아가 무명
생수병으로 드리프트했다(clip13_05/08.png).

v7은 **병 크기 하나만** 바꾼다: 0.035 → 0.09(1392px 기준 48px → 125px).
배경·시드·negative·I2V 프롬프트는 v6과 완전히 동일하다.

찡그린 표정은 배경 자체(scene3a_v6_bg.png)에 박혀 있어 여기서 못 고친다 —
고치려면 Kontext 배경을 다시 만들어야 하는데 그러면 화각까지 바뀌어 이번
실험(병 크기)의 변수가 섞인다. 별도 시도로 분리한다.

실행: cd langgraph && ./.venv/bin/python tests/probe_bev_ad_scene3a_v7.py
결과: assets/scene3a_v7_first.png, jobs/probe_bev_ad/clip16.mp4
"""
import asyncio
import sys
from pathlib import Path

import httpx
from PIL import Image

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))
sys.path.insert(0, str(_HERE))
import tools  # noqa: E402
from probe_bev_ad_scene3a_v5 import (  # noqa: E402
    I2V_PROMPT, NEGATIVE_PROMPT, _build_ltx13b_graph_custom_negative,
)
from probe_bev_ad_scene3a_v6 import I2V_SEED  # noqa: E402

JOB_ID = "probe_bev_ad"
ASSETS = _HERE.parent / "jobs" / JOB_ID / "assets"
SCENE_ID = 16

PRODUCT_WIDTH_RATIO = 0.09     # v6은 0.035 — 이 값 하나만 바뀜
PRODUCT_CENTER_X_RATIO = 0.50
PRODUCT_BOTTOM_Y_RATIO = 0.92


def compose_first_frame(bg_path: Path) -> Path:
    bg = Image.open(bg_path).convert("RGBA")
    product = Image.open(ASSETS / "bottle_canonical.png").convert("RGBA")
    bw, bh = bg.size
    pw = int(bw * PRODUCT_WIDTH_RATIO)
    ph = int(product.height * (pw / product.width))
    product = product.resize((pw, ph), Image.LANCZOS)
    px = int(bw * PRODUCT_CENTER_X_RATIO - pw / 2)
    py = int(bh * PRODUCT_BOTTOM_Y_RATIO - ph)
    bg.alpha_composite(product, (px, py))
    out = ASSETS / "scene3a_v7_first.png"
    bg.convert("RGB").save(out, "PNG")
    print(f"병 합성 크기: {pw}x{ph}px (캔버스 {bw}x{bh})")
    return out


async def generate_clip(first: Path) -> str:
    """v6의 generate_clip과 동일 배선 — SCENE_ID(16)와 request_key만 다르다.
    v6 함수를 그대로 임포트하면 그쪽 SCENE_ID=13으로 clip13.mp4를 덮어쓴다."""
    async with (
        tools.oom.phase("i2v"),
        httpx.AsyncClient(timeout=httpx.Timeout(connect=10.0, read=60.0, write=60.0, pool=None)) as client,
    ):
        up = await client.post(
            f"{tools.COMFYUI_URL}/upload/image",
            files={"image": (f"scene3a_v7_{first.name}", first.read_bytes(), "image/png")},
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
        JOB_ID, SCENE_ID, graph, f"scene3a_v7_{I2V_SEED}", True)


async def main() -> int:
    first = compose_first_frame(ASSETS / "scene3a_v6_bg.png")
    print(f"조립 첫 프레임: {first}")
    clip = await generate_clip(first)   # v6과 동일 배선(negative/시드/프롬프트 그대로)
    print(f"scene 3a (v7, 병 확대) -> {clip}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
