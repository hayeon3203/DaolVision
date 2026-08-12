"""음료수 광고 스파이크 씬2 v2 (A노선, 사용자 피드백 반영) — 구도 반전.
v1(probe_bev_ad_scene2.py)은 카메라가 인물 뒤에서 따라가고 제품이 화면 저 멀리
작게(벤치 위) 나오는 구도였음. 사용자 피드백: "음료가 가까이 있고 멀리서
주인공이 달려오는" 구도를 원함 — 카메라를 제품 근처(전경)에 두고, 인물이
코트 저 멀리서 카메라 쪽으로 달려오게 함.

1) FLUX T2I로 "벤치 옆 지상 시점, 코트 저 멀리서 다가오는 인물" 씬 생성(제품 없음)
2) 정본 제품 픽셀을 벤치 위(전경, 카메라와 가까움)에 크게 Pillow 합성
3) 조립된 첫 프레임을 plain I2V(LTX-13B, generate_i2v_fallback_clip)에 투입
핵심 관찰: (a) v1에서 PASS였던 체이닝 안정성 재현 여부, (b) 제품이 커진 만큼
identity 유지가 더 엄격한 기준을 통과하는지, (c) 인물 얼굴이 보이는 정면
접근 구도인지.

실행: cd langgraph && ./.venv/bin/python tests/probe_bev_ad_scene2_v2.py
결과: jobs/probe_bev_ad/clip2.mp4(덮어씀), assets/scene2_v2_bg.png, assets/scene2_v2_first.png
"""
import asyncio
import shutil
import sys
from pathlib import Path

import httpx
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import tools  # noqa: E402

JOB_ID = "probe_bev_ad"
ASSETS = Path(__file__).resolve().parent.parent / "jobs" / JOB_ID / "assets"
T2I_URL = "http://127.0.0.1:8501"
SEED = 20260813  # v2 1차 시도(20260812)는 인물이 뒷모습으로 카메라에서 멀어지는
# 구도가 나와 시드 변경 + 프롬프트에 "facing the camera/front view" 명시 추가.

# 카메라가 벤치(제품이 놓일 자리) 옆 지상 시점에서 코트 저 멀리를 바라봄 —
# 인물은 배경에 작게 시작해 카메라 쪽으로 다가오는 구도(정면, 얼굴 보임).
# 의상은 씬1(clip1)과 동일.
SCENE_PROMPT = (
    "cinematic sports commercial, low ground-level shot from right beside an "
    "empty wooden bench at the edge of an outdoor basketball court, the bench "
    "top is close to the camera and empty, in the far background a young "
    "Korean man wearing a plain white sleeveless jersey and black shorts is "
    "running toward the camera, facing the camera with his face and chest "
    "visible, front view of a runner approaching the viewer, small distant "
    "figure far away on the court, deep perspective, court lines converging "
    "toward the camera, golden late-afternoon light, wide-angle lens, "
    "photorealistic"
)
I2V_PROMPT = (
    "cinematic, the man runs from far in the distance straight toward the "
    "camera, growing larger and closer with each stride, camera stays low and "
    "steady near the bench where a silver aluminum can stands, golden "
    "late-afternoon light"
)


def generate_scene_bg() -> Path:
    out = ASSETS / "scene2_v2_bg.png"
    if out.exists():
        print(f"[skip] {out} 이미 존재")
        return out
    timeout = httpx.Timeout(connect=10.0, read=600.0, write=60.0, pool=None)
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(f"{T2I_URL}/generate", json={
            "prompt": SCENE_PROMPT, "width": 1280, "height": 720, "seed": SEED})
        resp.raise_for_status()
        png = client.get(f"{T2I_URL}{resp.json()['image_url']}")
        png.raise_for_status()
    out.write_bytes(png.content)
    return out


def compose_first_frame(
    bg_path: Path,
    *,
    product_width_ratio: float = 0.10,
    product_center_x_ratio: float = 0.32,
    product_bottom_y_ratio: float = 0.78,
) -> Path:
    """정본 제품 픽셀을 전경 벤치 위(카메라와 가까움)에 대형 배치. v1(0.025)의
    반대 극단 — 비율은 scene2_v2_bg.png의 벤치 위치를 육안으로 보고 조정한다
    (결정론 — 반복 조정 허용). 항상 정본 원본에서 새로 리사이즈(재생성 금지,
    중간 손실 누적 방지)."""
    bg = Image.open(bg_path).convert("RGBA")
    product = Image.open(ASSETS / "product_canonical.png").convert("RGBA")
    bw, bh = bg.size
    pw = int(bw * product_width_ratio)
    ph = int(product.height * (pw / product.width))
    product = product.resize((pw, ph), Image.LANCZOS)
    px = int(bw * product_center_x_ratio - pw / 2)
    py = int(bh * product_bottom_y_ratio - ph)
    bg.alpha_composite(product, (px, py))
    out = ASSETS / "scene2_v2_first.png"
    bg.convert("RGB").save(out, "PNG")
    return out


async def main() -> int:
    bg = generate_scene_bg()
    first = compose_first_frame(bg)
    print(f"조립 첫 프레임: {first}")
    shutil.copyfile(first, tools.refs_dir(JOB_ID) / "scene2_v2_first.png")
    clip = await tools.generate_i2v_fallback_clip(
        job_id=JOB_ID, scene_id=2, prompt=I2V_PROMPT,
        matched_image="scene2_v2_first.png", duration=3.0,
        seed=SEED, force_new=True,
    )
    print(f"scene 2 (v2) -> {clip}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
