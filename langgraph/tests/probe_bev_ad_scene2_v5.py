"""음료수 광고 스파이크 씬2 v5 — 씬3a v5와 동일한 커스텀 그래프(negative prompt
커스터마이즈)로 재생성 + 벤치 위를 걸어가는 부자연스러운 구간을 트림으로 제거
(사용자 지시: "패트병으로 다가오는데까지만 끊으면 됨"). v4(크기+톤 매칭)의
합성은 그대로 유지, 생성 그래프만 씬3a v5와 통일한다.

실행: cd langgraph && ./.venv/bin/python tests/probe_bev_ad_scene2_v5.py
결과: jobs/probe_bev_ad/clip2.mp4(트림된 최종본, 덮어씀),
      jobs/probe_bev_ad/clip2_full.mp4(트림 전 원본, 대조용)
"""
import asyncio
import subprocess
import sys
from pathlib import Path

import httpx
from PIL import Image, ImageChops

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import tools  # noqa: E402
from probe_bev_ad_scene3a_v5 import _build_ltx13b_graph_custom_negative  # noqa: E402

JOB_ID = "probe_bev_ad"
ASSETS = Path(__file__).resolve().parent.parent / "jobs" / JOB_ID / "assets"
JOB_DIR = Path(__file__).resolve().parent.parent / "jobs" / JOB_ID
SEED = 20260813

I2V_PROMPT = (
    "cinematic, the man runs from far in the distance straight toward the "
    "camera, growing larger and closer with each stride, camera stays low and "
    "steady near the bench where a clear plastic sports drink bottle stands, "
    "golden late-afternoon light"
)
# 씬3a v5와 동일한 negative — 이 씬엔 와인병 위험은 없지만(제품이 정적) 그래프
# 자체를 통일해달라는 사용자 요청 반영, 손대지 않고 그대로 재사용.
NEGATIVE_PROMPT = (
    "worst quality, blurry, jittery, distorted, low resolution, wine bottle, "
    "beer bottle, glass bottle, dark green glass, dark bottle, wine, alcohol, "
    "champagne, opaque bottle, different object, morphing shape"
)

# v4와 동일 톤/크기 파라미터
WARM_TINT = (255, 220, 165)
TINT_STRENGTH = 0.30
PRODUCT_WIDTH_RATIO = 0.075
PRODUCT_CENTER_X_RATIO = 0.30
PRODUCT_BOTTOM_Y_RATIO = 0.80

# 사용자 관찰: 인물이 벤치 위를 걸어 지나감 — 발이 벤치에 닿기 직전까지만 남긴다.
# clip2v4fine_11(t=1.25s)까진 코트 바닥, clip2v4fine_13(t=1.5s)에 발이 벤치 앞
# 모서리에 닿음 — 그 중간인 1.4s를 트림 컷 지점으로 잡는다.
TRIM_SECONDS = 1.4


def _apply_warm_tint(product: Image.Image) -> Image.Image:
    rgb = product.convert("RGB")
    tint_layer = Image.new("RGB", rgb.size, WARM_TINT)
    multiplied = ImageChops.multiply(rgb, tint_layer)
    blended = Image.blend(rgb, multiplied, TINT_STRENGTH)
    out = blended.convert("RGBA")
    out.putalpha(product.split()[-1])
    return out


def compose_first_frame(bg_path: Path) -> Path:
    bg = Image.open(bg_path).convert("RGBA")
    product = Image.open(ASSETS / "bottle_canonical.png").convert("RGBA")
    product = _apply_warm_tint(product)
    bw, bh = bg.size
    pw = int(bw * PRODUCT_WIDTH_RATIO)
    ph = int(product.height * (pw / product.width))
    product = product.resize((pw, ph), Image.LANCZOS)
    px = int(bw * PRODUCT_CENTER_X_RATIO - pw / 2)
    py = int(bh * PRODUCT_BOTTOM_Y_RATIO - ph)
    bg.alpha_composite(product, (px, py))
    out = ASSETS / "scene2_v5_first.png"
    bg.convert("RGB").save(out, "PNG")
    return out


async def _upload_and_generate(ref_path: Path, prompt: str, negative: str,
                                duration: float, seed: int) -> str:
    async with (
        tools.oom.phase("i2v"),
        httpx.AsyncClient(timeout=httpx.Timeout(connect=10.0, read=60.0, write=60.0, pool=None)) as client,
    ):
        up = await client.post(
            f"{tools.COMFYUI_URL}/upload/image",
            files={"image": (f"scene2_v5_{ref_path.name}", ref_path.read_bytes(), "image/png")},
            data={"overwrite": "true"},
        )
        up.raise_for_status()
        uj = up.json()
        image_name = f"{uj['subfolder']}/{uj['name']}" if uj.get("subfolder") else uj["name"]

    length = tools.to_ltx_len(duration * tools.LTX13B_FPS)
    graph = _build_ltx13b_graph_custom_negative(
        prompt=prompt, negative=negative, image_name=image_name,
        width=tools.WIDTH, height=tools.HEIGHT, seed=seed)
    graph["7"]["inputs"]["length"] = length
    request_key = f"scene2_v5_{seed}_{duration}_{hash(prompt) % 10000}"
    return await tools._generate_ltx_job_clip(JOB_ID, 2, graph, request_key, True)


def trim(src: Path, out: Path, seconds: float) -> Path:
    """붕괴/재생성 없는 순수 편집 컷 — 벤치 위를 걷는 어색한 구간만 잘라낸다."""
    subprocess.run([
        "ffmpeg", "-y", "-i", str(src), "-t", str(seconds),
        "-c", "copy", str(out),
    ], check=True, capture_output=True)
    return out


async def main() -> int:
    bg_path = ASSETS / "scene2_v2_bg.png"
    first = compose_first_frame(bg_path)
    print(f"조립 첫 프레임: {first}")
    clip = await _upload_and_generate(first, I2V_PROMPT, NEGATIVE_PROMPT, 3.0, SEED)
    full = JOB_DIR / "clip2_full.mp4"
    Path(clip).replace(full)
    print(f"전체 클립(트림 전): {full}")
    trimmed = trim(full, JOB_DIR / "clip2.mp4", TRIM_SECONDS)
    print(f"scene 2 (v5, {TRIM_SECONDS}s 트림) -> {trimmed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
