"""음료수 광고 스파이크 씬3a v4 — 정지컷 편집 (사용자 지시, v3 "이동거리/시간/시드"
레버가 전부 실패한 뒤의 대안). LTX가 손으로 병을 들어올리는 동작 자체에 강하게
와인병 쪽으로 끌리는 구조적 한계(strength 이미 최대, 거리/시간/시드로도 못 막음)를
diffusion을 안 거치는 정지 컷으로 우회한다:

1) 정지 샷 — 병이 쇄골 아래(v3와 동일 합성, diffusion 없음, 브랜드 100% 보존)
   "마시기 직전" 정지 프레임을 짧게 유지(freeze).
2) 컷 — 병이 이미 입가에 도착한 새 합성 프레임에서 아주 짧고 미세한 틸트
   동작만 I2V로 생성(들어올리는 큰 이동 없음 → 붕괴 유발 요인 최소화).
3) 편집 — 정지 구간 + 짧은 동작 클립을 컷 트랜지션으로 이어붙인다.

실행: cd langgraph && ./.venv/bin/python tests/probe_bev_ad_scene3a_v4.py
결과: jobs/probe_bev_ad/clip3.mp4(최종 편집본, 덮어씀),
      assets/scene3a_v4_atlips_first.png, jobs/probe_bev_ad/clip3_sip_only.mp4
"""
import asyncio
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import tools  # noqa: E402

JOB_ID = "probe_bev_ad"
ASSETS = Path(__file__).resolve().parent.parent / "jobs" / JOB_ID / "assets"
JOB_DIR = Path(__file__).resolve().parent.parent / "jobs" / JOB_ID
SEED = 20260817

FREEZE_SECONDS = 0.8
SIP_DURATION = 1.5  # 짧을수록 붕괴 전에 끝날 확률 높음(v1 관찰: ~1초까지 유지)

I2V_PROMPT = (
    "cinematic, he tilts the bottle back very slightly and takes a small sip, "
    "minimal subtle motion, mostly still, golden light"
)


def compose_at_lips(
    bg_path: Path,
    *,
    product_width_ratio: float = 0.09,
    mouth_x_ratio: float = 0.485,
    mouth_y_ratio: float = 0.385,
    rotate_deg: float = -15,
) -> Path:
    """병 목(입 닿는 지점=리사이즈 전 상단중앙)이 입술 위치(mouth_x/y_ratio)에
    오도록 배치 — 회전은 top-center 기준점을 유지한 채로 적용해(회전으로 생긴
    여백만큼 보정) 병 목이 회전 후에도 계속 같은 목표 좌표를 가리키게 한다.
    I2V는 미세한 틸트만 그리면 되므로 붕괴 유발 요인(큰 이동)이 구조적으로
    사라진다. 항상 정본 원본에서 새로 리사이즈(재생성 금지)."""
    bg = Image.open(bg_path).convert("RGBA")
    product = Image.open(ASSETS / "bottle_canonical.png").convert("RGBA")
    bw, bh = bg.size
    pw = int(bw * product_width_ratio)
    ph = int(product.height * (pw / product.width))
    product = product.resize((pw, ph), Image.LANCZOS)
    top_center_pre = (pw / 2, 0.0)
    if rotate_deg:
        product = product.rotate(rotate_deg, expand=True, resample=Image.BICUBIC)
        pad_x = (product.width - pw) / 2
        top_center = (top_center_pre[0] + pad_x, 0.0)
    else:
        top_center = top_center_pre
    target_x = bw * mouth_x_ratio
    target_y = bh * mouth_y_ratio
    px = int(target_x - top_center[0])
    py = int(target_y - top_center[1])
    bg.alpha_composite(product, (px, py))
    out = ASSETS / "scene3a_v4_atlips_first.png"
    bg.convert("RGB").save(out, "PNG")
    return out


def make_freeze_clip(still_path: Path, out_path: Path, seconds: float) -> Path:
    """정지 이미지를 짧게 유지하는 무음 mp4로 변환 (diffusion 없음, 브랜드 100% 보존).
    씬2/3 클립과 동일한 24fps로 맞춰 편집 시 프레임레이트 불일치가 안 생기게 한다."""
    subprocess.run([
        "ffmpeg", "-y", "-loop", "1", "-i", str(still_path),
        "-t", str(seconds), "-r", "24", "-pix_fmt", "yuv420p", str(out_path),
    ], check=True, capture_output=True)
    return out_path


async def main() -> int:
    bg_path = ASSETS / "scene3a_v2_bg.png"

    # 1) 정지 샷 (v3 합성 재사용 — 이미 존재, diffusion 없음)
    freeze_source = ASSETS / "scene3a_v3_first.png"
    freeze_clip = JOB_DIR / "clip3_freeze.mp4"
    make_freeze_clip(freeze_source, freeze_clip, FREEZE_SECONDS)
    print(f"정지 클립: {freeze_clip}")

    # 2) 입가 도착 합성 + 짧은 틸트 I2V
    at_lips = compose_at_lips(bg_path)
    print(f"입가 합성 첫프레임: {at_lips}")
    ref_name = "scene3a_v4_atlips_first.png"
    shutil.copyfile(at_lips, tools.refs_dir(JOB_ID) / ref_name)
    sip_clip_path = await tools.generate_i2v_fallback_clip(
        job_id=JOB_ID, scene_id=3, prompt=I2V_PROMPT,
        matched_image=ref_name, duration=SIP_DURATION, seed=SEED, force_new=True,
    )
    print(f"틸트 클립: {sip_clip_path}")
    sip_only = JOB_DIR / "clip3_sip_only.mp4"
    shutil.copyfile(sip_clip_path, sip_only)

    # 3) 정지 + 틸트 컷 편집
    final = tools.ffmpeg_concat(
        [str(freeze_clip), str(sip_only)], ["cut"], str(JOB_DIR / "clip3.mp4"),
        width=tools.LTX_FACEID_WIDTH, height=tools.LTX_FACEID_HEIGHT)
    print(f"scene 3a (v4, 정지컷 편집) -> {final}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
