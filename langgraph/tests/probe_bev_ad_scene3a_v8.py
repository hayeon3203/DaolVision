"""음료수 광고 스파이크 씬3a v8 — 첫 프레임에 그립을 만들어 준다(2026-08-13).

## v6/v7이 왜 실패했나

둘 다 병이 손 없이 가슴 앞 공중에 떠 있는 첫 프레임이었다. LTX는 마시는 동작을
만들려면 손·그립을 새로 발명해야 했고, 그 과정에서 병 자체까지 재발명해 주황
캡과 그라디언트 라벨이 날아갔다(clip13/clip16). v7에서 병을 48px→125px로
키운 건 이 원인과 무관해서 효과가 없었다(오히려 병목이 기형이 됨).

## v8이 바꾸는 것 2가지

1. **빈 그립 손을 배경에 미리 그린다** — Kontext 프롬프트로 "가슴 앞에 손을 들어
   병을 쥔 모양(단, 손은 비어 있음)"을 만들고, 그 손 위치에 병을 합성한다.
   LTX는 그립을 발명할 필요 없이 "이미 쥔 병을 입으로 올리는" 동작만 하면 된다.
2. **Kontext 재통합 단계 추가** — v5/v6/v7은 합성 직후 바로 I2V였다. 씬2 확정본
   (probe_bev_ad_scene2_final.py)은 합성 → Kontext 재통합 → I2V였고, 그 단계가
   제품을 씬 조명에 녹여 "스티커처럼 떠 있는" 느낌을 없앤 게 확인돼 있다.
   씬3a에도 같은 A노선 전체 레시피를 적용한다.

찡그린 표정(v6/v7 배경에서 사용자 지적)도 여기서 같이 잡는다. 단 부정문
("no frown")은 쓰지 않는다 — 씬1 v2에서 "no logos and no text"가 오히려 로고를
2개 만든 게 실측됐다. 긍정 서술로만 기술한다.

## 실행 (2단계 — 손 위치를 눈으로 보고 합성 비율을 정해야 함)

  cd langgraph && ./.venv/bin/python tests/probe_bev_ad_scene3a_v8.py --bg-only
  # assets/scene3a_v8_bg.png 확인 후 아래 GRIP_* 상수 조정
  cd langgraph && ./.venv/bin/python tests/probe_bev_ad_scene3a_v8.py

결과: assets/scene3a_v8_bg.png, scene3a_v8_flat.png, scene3a_v8_recomposed.png,
      jobs/probe_bev_ad/clip17.mp4
"""
import asyncio
import sys
import time
from pathlib import Path

import httpx
from PIL import Image

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))
sys.path.insert(0, str(_HERE))
import tools  # noqa: E402
from probe_bev_ad_scene2_final import (  # noqa: E402
    BLUR_RADIUS, BLUR_SIGMA, CONTROLNET_STRENGTH as RECOMPOSE_CN_STRENGTH,
    _apply_warm_tint, _build_kontext_graph_weak_blur,
)
from probe_bev_ad_scene3a_v5 import (  # noqa: E402
    NEGATIVE_PROMPT, _build_ltx13b_graph_custom_negative,
)

JOB_ID = "probe_bev_ad"
ASSETS = _HERE.parent / "jobs" / JOB_ID / "assets"
SCENE_ID = 17
KONTEXT_SEED = 20260813
RECOMPOSE_SEED = 20260813
I2V_SEED = 20260813

# v6과 동일(cinematic 프리셋) — 배경 재렌더용
BG_CONTROLNET_STRENGTH = 0.35
BG_GUIDANCE = 4.0

# 손 위치에 맞춰 조정하는 값 — --bg-only로 배경 확인 후 수정한다.
# scene3a_v8_bg.png 실측(캔버스 1392x752): 그립 손가락이 x 700~860, y 480~620에
# 있고 중심은 x≈780(=0.56). 병 폭 104px(0.075)이 그립 안쪽 폭과 맞고, bottom_y
# 0.87이면 병 몸통 중간(438~647px)을 손가락이 잡는 위치가 된다.
GRIP_WIDTH_RATIO = 0.075
GRIP_CENTER_X_RATIO = 0.56
GRIP_BOTTOM_Y_RATIO = 0.87

BG_PROMPT = (
    "Keep this exact same man — same face, same facial features, same hairstyle, "
    "same age — do not change his identity. Re-render him as a cinematic "
    "medium-close commercial shot on an outdoor basketball court in warm golden "
    "late-afternoon backlight: he wears a plain white short-sleeve t-shirt, his "
    "face and upper chest fill the frame, his expression is calm and relaxed "
    "with a smooth untroubled brow and a faint satisfied smile, eyes open and "
    "looking down toward his own hand. His right hand is raised in front of his "
    "chest at collarbone height, forearm angled up across his body, fingers "
    "curled into a firm cylindrical grip as if holding a drink bottle, but the "
    "hand is empty with an open gap between the curled fingers and the thumb. "
    "Shallow depth of field with the court and hoop softly out of focus behind "
    "him, photorealistic."
)

RECOMPOSE_PROMPT = (
    "The exact same clear plastic sports drink bottle from the reference image, "
    "unchanged shape, unchanged blue and orange gradient label, unchanged "
    "lightning-bolt logo, unchanged orange cap — do not redesign it. Re-light "
    "and re-render only the bottle so it looks physically held in this man's "
    "hand in this exact golden late-afternoon outdoor scene: his curled fingers "
    "wrap around the bottle body with matching warm backlit rim light and "
    "natural contact shadows where the fingers meet the plastic, natural "
    "photographic grain, shallow depth of field with the background softly out "
    "of focus but still recognizable."
)

I2V_PROMPT = (
    "cinematic, he raises the clear plastic bottle he is already holding from "
    "chest height up to his lips and tilts it back to drink, his grip on the "
    "bottle never changes, the bottle stays a clear plastic PET sports drink "
    "bottle with an orange cap and a blue-to-orange gradient label throughout, "
    "natural continuous motion, golden light"
)


async def _run_comfy_graph(client: httpx.AsyncClient, graph: dict, what: str) -> bytes:
    resp = await client.post(f"{tools.COMFYUI_URL}/prompt", json={"prompt": graph})
    resp.raise_for_status()
    prompt_id = resp.json()["prompt_id"]
    started_at = time.time()
    history_item = None
    while history_item is None:
        if time.time() - started_at > tools.STANDIN_QUEUE_TIMEOUT:
            raise TimeoutError(f"{what}이(가) 제한 시간 내 완료되지 않음")
        history = (await client.get(f"{tools.COMFYUI_URL}/history/{prompt_id}")).json()
        if prompt_id in history:
            history_item = history[prompt_id]
        else:
            await asyncio.sleep(2.0)
    if history_item.get("status", {}).get("status_str") == "error":
        raise RuntimeError(f"{what} 실행 오류 {history_item.get('status', {}).get('messages')}")
    media = None
    for node_out in history_item.get("outputs", {}).values():
        media = node_out.get("images")
        if media:
            break
    if not media:
        raise RuntimeError(f"{what} 출력 이미지 없음")
    output = media[0]
    png = await client.get(f"{tools.COMFYUI_URL}/view", params={
        "filename": output["filename"], "subfolder": output.get("subfolder", ""),
        "type": output.get("type", "output"),
    })
    png.raise_for_status()
    return png.content


async def _kontext(input_path: Path, prompt: str, seed: int, controlnet_strength: float,
                   guidance: float, out_name: str, upload_name: str, what: str) -> Path:
    normalized, img_width, img_height = tools._normalize_i2v_input(input_path.read_bytes())
    width, height = tools._flux_kontext_dims(img_width, img_height)
    timeout = httpx.Timeout(connect=10.0, read=300.0, write=60.0, pool=None)
    async with tools.oom.phase("i2i"), httpx.AsyncClient(timeout=timeout) as client:
        up = await client.post(
            f"{tools.COMFYUI_URL}/upload/image",
            files={"image": (upload_name, normalized, "image/png")},
            data={"overwrite": "true"},
        )
        up.raise_for_status()
        uj = up.json()
        image_name = f"{uj['subfolder']}/{uj['name']}" if uj.get("subfolder") else uj["name"]
        graph = _build_kontext_graph_weak_blur(
            prompt=prompt, image_name=image_name, width=width, height=height,
            seed=seed, controlnet_strength=controlnet_strength,
            blur_radius=BLUR_RADIUS, blur_sigma=BLUR_SIGMA)
        # 배경 재렌더는 guidance를 cinematic 값으로 올린다(재통합은 씬2 확정값 유지).
        graph["10"]["inputs"]["guidance"] = guidance
        png = await _run_comfy_graph(client, graph, what)
    out = ASSETS / out_name
    out.write_bytes(png)
    return out


async def make_bg() -> Path:
    out = ASSETS / "scene3a_v8_bg.png"
    if out.exists():
        print(f"[skip] {out} 이미 존재 — 재생성하려면 파일을 지운다")
        return out
    padded = ASSETS / "scene3a_v6_kontext_input.png"   # v6이 만든 와이드 패딩 인물 정본
    return await _kontext(
        padded, BG_PROMPT, KONTEXT_SEED, BG_CONTROLNET_STRENGTH, BG_GUIDANCE,
        "scene3a_v8_bg.png", "scene3a_v8_bg_input.png", "씬3a v8 배경 재렌더")


def compose_flat(bg_path: Path) -> Path:
    """그립 손 위치에 병을 얹는다. 씬2 확정본과 같이 골든아워 warm tint를 입힌다."""
    bg = Image.open(bg_path).convert("RGBA")
    product = _apply_warm_tint(Image.open(ASSETS / "bottle_canonical.png").convert("RGBA"))
    bw, bh = bg.size
    pw = int(bw * GRIP_WIDTH_RATIO)
    ph = int(product.height * (pw / product.width))
    product = product.resize((pw, ph), Image.LANCZOS)
    px = int(bw * GRIP_CENTER_X_RATIO - pw / 2)
    py = int(bh * GRIP_BOTTOM_Y_RATIO - ph)
    bg.alpha_composite(product, (px, py))
    out = ASSETS / "scene3a_v8_flat.png"
    bg.convert("RGB").save(out, "PNG")
    print(f"병 합성: {pw}x{ph}px @ ({px},{py}), 캔버스 {bw}x{bh}")
    return out


async def generate_clip(first: Path) -> str:
    async with (
        tools.oom.phase("i2v"),
        httpx.AsyncClient(timeout=httpx.Timeout(connect=10.0, read=60.0, write=60.0, pool=None)) as client,
    ):
        up = await client.post(
            f"{tools.COMFYUI_URL}/upload/image",
            files={"image": (f"scene3a_v8_{first.name}", first.read_bytes(), "image/png")},
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
        JOB_ID, SCENE_ID, graph, f"scene3a_v8_{I2V_SEED}", True)


async def main() -> int:
    bg = await make_bg()
    print(f"배경(빈 그립 손): {bg}")
    if "--bg-only" in sys.argv:
        print("--bg-only: 손 위치 확인 후 GRIP_* 상수 조정하고 다시 실행")
        return 0
    flat = compose_flat(bg)
    print(f"합성: {flat}")
    recomposed = await _kontext(
        flat, RECOMPOSE_PROMPT, RECOMPOSE_SEED, RECOMPOSE_CN_STRENGTH,
        tools.FLUX_KONTEXT_GUIDANCE, "scene3a_v8_recomposed.png",
        "scene3a_v8_recompose_input.png", "씬3a v8 Kontext 재통합")
    print(f"Kontext 재통합: {recomposed}")
    clip = await generate_clip(recomposed)
    print(f"scene 3a (v8, 그립+재통합) -> {clip}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
