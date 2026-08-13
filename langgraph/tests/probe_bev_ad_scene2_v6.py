"""음료수 광고 스파이크 씬2 v6 — 후처리 오버레이 방식 (사용자 지시 2026-08-13,
A노선의 3번째 변형). A노선(첫프레임 조립→I2V가 전 프레임을 diffusion으로
재생성)과 다르게, 이번엔 병을 diffusion에 아예 노출시키지 않는다:

1) 배경(scene2_v2_bg.png, 병 없음)을 그대로 I2V 첫 프레임으로 사용 — 인물
   달리기 동작만 생성, 병은 diffusion이 한 번도 못 본다.
2) 생성된 영상 위에 실제 병 픽셀(정본 원본에서 매번 새로 리사이즈+톤매칭)을
   고정 좌표로 매 프레임 오버레이 — 병이 벤치 위에 가만히 있고 카메라도
   고정이라 화면상 위치가 클립 내내 안 변하므로 고정좌표 오버레이가 가능
   (씬3a처럼 손에 들려 움직이는 경우엔 위치 추적이 필요해 불가능, 별개 사안).
   diffusion을 아예 안 거치므로 identity 드리프트가 구조적으로 0.
3) 벤치 위 보행 구간은 v5와 동일하게 1.4s에서 트림.

실행: cd langgraph && ./.venv/bin/python tests/probe_bev_ad_scene2_v6.py
결과: jobs/probe_bev_ad/clip2.mp4(오버레이+트림 최종본, 덮어씀),
      jobs/probe_bev_ad/clip2_v6_no_overlay.mp4(오버레이 전 원본 영상, 대조용)
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
    "camera, growing larger and closer with each stride, golden late-afternoon "
    "light, empty wooden bench in the foreground"
)
NEGATIVE_PROMPT = tools.LTX13B_DEFAULT_NEGATIVE  # 병이 diffusion에 없으니 병 관련 억제 불필요

# v4/v5와 동일 톤/크기(오버레이도 같은 값으로 배치해야 이전 버전들과 비교 가능)
WARM_TINT = (255, 220, 165)
TINT_STRENGTH = 0.30
PRODUCT_WIDTH_RATIO = 0.075
PRODUCT_CENTER_X_RATIO = 0.30
PRODUCT_BOTTOM_Y_RATIO = 0.80
TRIM_SECONDS = 1.4


def _apply_warm_tint(product: Image.Image) -> Image.Image:
    rgb = product.convert("RGB")
    tint_layer = Image.new("RGB", rgb.size, WARM_TINT)
    multiplied = ImageChops.multiply(rgb, tint_layer)
    blended = Image.blend(rgb, multiplied, TINT_STRENGTH)
    out = blended.convert("RGBA")
    out.putalpha(product.split()[-1])
    return out


def make_overlay_png(bg_size: tuple[int, int]) -> tuple[Path, int, int]:
    """오버레이용 병 PNG(리사이즈+톤매칭 완료)와 배치 좌표(px, py)를 반환.
    항상 정본 원본에서 새로 리사이즈(재생성 금지)."""
    product = Image.open(ASSETS / "bottle_canonical.png").convert("RGBA")
    product = _apply_warm_tint(product)
    bw, bh = bg_size
    pw = int(bw * PRODUCT_WIDTH_RATIO)
    ph = int(product.height * (pw / product.width))
    product = product.resize((pw, ph), Image.LANCZOS)
    out = ASSETS / "scene2_v6_overlay.png"
    product.save(out, "PNG")
    px = int(bw * PRODUCT_CENTER_X_RATIO - pw / 2)
    py = int(bh * PRODUCT_BOTTOM_Y_RATIO - ph)
    return out, px, py


async def _upload_and_generate(ref_path: Path, prompt: str, negative: str,
                                duration: float, seed: int) -> str:
    async with (
        tools.oom.phase("i2v"),
        httpx.AsyncClient(timeout=httpx.Timeout(connect=10.0, read=60.0, write=60.0, pool=None)) as client,
    ):
        up = await client.post(
            f"{tools.COMFYUI_URL}/upload/image",
            files={"image": (f"scene2_v6_{ref_path.name}", ref_path.read_bytes(), "image/png")},
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
    request_key = f"scene2_v6_{seed}_{duration}_{hash(prompt) % 10000}"
    return await tools._generate_ltx_job_clip(JOB_ID, 2, graph, request_key, True)


def overlay_and_trim(video: Path, overlay_png: Path, px: int, py: int,
                      out: Path, seconds: float) -> Path:
    """diffusion 없는 순수 합성 — 병 픽셀을 고정좌표로 매 프레임 오버레이하고
    벤치 위 보행 구간(v5와 동일 지점) 트림."""
    subprocess.run([
        "ffmpeg", "-y", "-i", str(video), "-i", str(overlay_png),
        "-filter_complex", f"[0][1]overlay={px}:{py}",
        "-t", str(seconds), "-pix_fmt", "yuv420p", str(out),
    ], check=True, capture_output=True)
    return out


async def main() -> int:
    bg_path = ASSETS / "scene2_v2_bg.png"  # 병 없는 순수 배경
    bg_size = Image.open(bg_path).size
    overlay_png, px, py = make_overlay_png(bg_size)
    print(f"오버레이 PNG: {overlay_png} @ ({px},{py})")

    clip = await _upload_and_generate(bg_path, I2V_PROMPT, NEGATIVE_PROMPT, 3.0, SEED)
    no_overlay = JOB_DIR / "clip2_v6_no_overlay.mp4"
    Path(clip).replace(no_overlay)
    print(f"오버레이 전 원본(병 없음): {no_overlay}")

    final = overlay_and_trim(no_overlay, overlay_png, px, py, JOB_DIR / "clip2.mp4", TRIM_SECONDS)
    print(f"scene 2 (v6, 오버레이+{TRIM_SECONDS}s 트림) -> {final}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
