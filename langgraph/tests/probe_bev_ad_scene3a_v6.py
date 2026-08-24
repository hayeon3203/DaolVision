"""음료수 광고 스파이크 씬3a v6 — 얼굴 identity 통일(사용자 피드백 2026-08-13:
"clip4/clip3의 얼굴이 clip1과 다르다").

## 왜 Face-ID를 못 쓰는가

씬3a는 A노선(제품 픽셀을 합성한 첫 프레임을 I2V에 먹임)이라 첫 프레임 lock이
필수인데, LTX Face-ID 경로(`tools._build_ltx_faceid_graph`)에는 첫 프레임 입력
자체가 없다 — 노드 104의 image는 identity 참조(노드 129)로만 들어간다. 첫 프레임을
넣던 노드 130/131(LoadImage+LTXVImgToVideo)은 2026-07-31에 제거됐다: strength 1.0
앵커 lock이 Face-ID Identity Transfer를 무력화시켜 오히려 무작위 얼굴이 나왔기
때문(docs/superpowers/specs/2026-07-31-ltx-faceid-anchor-removal-design.md).
즉 "제품 픽셀 고정 + Face-ID"는 이미 실패로 판정돼 뜯어낸 조합이다.

## 대신 쓰는 방법 — 얼굴을 영상이 아니라 정지 이미지 단계에서 고정

씬 배경을 T2I로 새로 뽑는 대신(그러면 매번 새 얼굴이 나온다), 인물 정본
`person_canonical.png`를 Flux Kontext에 넣어 **같은 얼굴 그대로** 씬3a 구도로
재렌더한다. 씬2 recompose에서 이미 쓴 배선(`tools._build_flux_kontext_graph`
+ ControlNet union canny) 그대로 — 신규 모델/그래프 0.

인물 정본은 768x1024 세로인데 씬은 와이드라, 좌우를 배경 코너색으로 채워
와이드 캔버스로 만든 뒤 넣는다(배경이 평평한 회색이라 이음매가 안 생긴다 —
하드 엣지가 남으면 canny가 그 사각 테두리까지 구도로 잠가버린다).
ControlNet strength는 cinematic 프리셋값 0.35 — 0.6은 조명/재질이 거의 안 바뀌어
실내 포트레이트 톤이 그대로 남는다(6.19 실측).

실행: cd langgraph && ./.venv/bin/python tests/probe_bev_ad_scene3a_v6.py
결과: assets/scene3a_v6_kontext_input.png (와이드 패딩본)
      assets/scene3a_v6_bg.png            (Kontext 재렌더 배경)
      assets/scene3a_v6_first.png         (병 합성 첫 프레임)
      jobs/probe_bev_ad/clip13.mp4        (clip3.mp4 보존용 scene_id=13)
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
from probe_bev_ad_scene3a_v5 import (  # noqa: E402
    I2V_PROMPT, NEGATIVE_PROMPT, _build_ltx13b_graph_custom_negative,
)

JOB_ID = "probe_bev_ad"
ASSETS = _HERE.parent / "jobs" / JOB_ID / "assets"
SCENE_ID = 13                 # clip3.mp4 보존용(생성 파일은 clip13.mp4)
KONTEXT_SEED = 20260813
I2V_SEED = 20260813           # v5와 동일 — 모션 품질이 확인된 조건 유지

# cinematic 프리셋값(tools.STYLE_CONTROLNET_STRENGTH/STYLE_KONTEXT_GUIDANCE)
CONTROLNET_STRENGTH = 0.35
GUIDANCE = 4.0

# v5의 배치 그대로 — 가슴 높이에서 시작해 입까지 들어올릴 거리를 확보한다.
PRODUCT_WIDTH_RATIO = 0.035
PRODUCT_CENTER_X_RATIO = 0.50
PRODUCT_BOTTOM_Y_RATIO = 0.92

KONTEXT_PROMPT = (
    "Keep this exact same man — same face, same facial features, same hairstyle, "
    "same age — do not change his identity. Re-render him as a cinematic "
    "medium-close commercial shot on an outdoor basketball court in warm golden "
    "late-afternoon backlight: he wears a plain white short-sleeve t-shirt, his "
    "face and upper chest fill the frame, his mouth is closed and his head is "
    "tilted slightly down with his eyes closed as if about to drink, both hands "
    "down out of frame, empty space in front of his chest at hand height, "
    "shallow depth of field with the court and hoop softly out of focus behind "
    "him, photorealistic."
)


def pad_to_wide(src: Path, out: Path, target_aspect: float = 1280 / 704) -> Path:
    """세로 인물 정본을 와이드 캔버스로 확장. 여백은 원본 배경 코너색으로 채워
    이음매(하드 엣지)를 만들지 않는다 — canny가 그 테두리를 구도로 잠그면
    출력에 액자 같은 선이 남는다."""
    img = Image.open(src).convert("RGB")
    w, h = img.size
    corners = [img.getpixel(p) for p in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1))]
    fill = tuple(sum(c[i] for c in corners) // len(corners) for i in range(3))
    new_w = int(round(h * target_aspect))
    if new_w <= w:
        img.save(out, "PNG")
        return out
    canvas = Image.new("RGB", (new_w, h), fill)
    canvas.paste(img, ((new_w - w) // 2, 0))
    canvas.save(out, "PNG")
    return out


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


async def kontext_scene_bg(padded: Path) -> Path:
    image_bytes = padded.read_bytes()
    normalized, img_width, img_height = tools._normalize_i2v_input(image_bytes)
    width, height = tools._flux_kontext_dims(img_width, img_height)
    timeout = httpx.Timeout(connect=10.0, read=300.0, write=60.0, pool=None)
    async with tools.oom.phase("i2i"), httpx.AsyncClient(timeout=timeout) as client:
        up = await client.post(
            f"{tools.COMFYUI_URL}/upload/image",
            files={"image": ("scene3a_v6_kontext_input.png", normalized, "image/png")},
            data={"overwrite": "true"},
        )
        up.raise_for_status()
        uj = up.json()
        image_name = f"{uj['subfolder']}/{uj['name']}" if uj.get("subfolder") else uj["name"]
        graph = tools._build_flux_kontext_graph(
            prompt=KONTEXT_PROMPT, image_name=image_name, width=width, height=height,
            seed=KONTEXT_SEED, lock_bg_color=False, guidance=GUIDANCE,
            controlnet_strength=CONTROLNET_STRENGTH)
        png = await _run_comfy_graph(client, graph, "씬3a v6 Kontext 재렌더")
    out = ASSETS / "scene3a_v6_bg.png"
    out.write_bytes(png)
    return out


def compose_first_frame(bg_path: Path) -> Path:
    """v5와 동일 배치. 항상 정본 원본에서 새로 리사이즈(중간 손실 누적 방지)."""
    bg = Image.open(bg_path).convert("RGBA")
    product = Image.open(ASSETS / "bottle_canonical.png").convert("RGBA")
    bw, bh = bg.size
    pw = int(bw * PRODUCT_WIDTH_RATIO)
    ph = int(product.height * (pw / product.width))
    product = product.resize((pw, ph), Image.LANCZOS)
    px = int(bw * PRODUCT_CENTER_X_RATIO - pw / 2)
    py = int(bh * PRODUCT_BOTTOM_Y_RATIO - ph)
    bg.alpha_composite(product, (px, py))
    out = ASSETS / "scene3a_v6_first.png"
    bg.convert("RGB").save(out, "PNG")
    return out


async def generate_clip(first: Path) -> str:
    async with (
        tools.oom.phase("i2v"),
        httpx.AsyncClient(timeout=httpx.Timeout(connect=10.0, read=60.0, write=60.0, pool=None)) as client,
    ):
        up = await client.post(
            f"{tools.COMFYUI_URL}/upload/image",
            files={"image": (f"scene3a_v6_{first.name}", first.read_bytes(), "image/png")},
            data={"overwrite": "true"},
        )
        up.raise_for_status()
        uj = up.json()
        image_name = f"{uj['subfolder']}/{uj['name']}" if uj.get("subfolder") else uj["name"]

    graph = _build_ltx13b_graph_custom_negative(
        prompt=I2V_PROMPT, negative=NEGATIVE_PROMPT, image_name=image_name,
        width=tools.WIDTH, height=tools.HEIGHT, seed=I2V_SEED)
    graph["7"]["inputs"]["length"] = tools.to_ltx_len(3.0 * tools.LTX13B_FPS)
    request_key = f"scene3a_v6_{I2V_SEED}"
    return await tools._generate_ltx_job_clip(JOB_ID, SCENE_ID, graph, request_key, True)


async def main() -> int:
    padded = pad_to_wide(ASSETS / "person_canonical.png",
                         ASSETS / "scene3a_v6_kontext_input.png")
    print(f"Kontext 입력(와이드 패딩): {padded}")
    bg = await kontext_scene_bg(padded)
    print(f"Kontext 재렌더 배경: {bg}")
    first = compose_first_frame(bg)
    print(f"조립 첫 프레임: {first}")
    clip = await generate_clip(first)
    print(f"scene 3a (v6, 얼굴 통일) -> {clip}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
