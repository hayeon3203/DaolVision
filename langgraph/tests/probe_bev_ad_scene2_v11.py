"""음료수 광고 스파이크 씬2 v11 — 후처리 그라데이션 블러로 심도감 재현 (사용자
지시 2026-08-13, 검토안 2번). v8의 "자연스러움"이 사실 배경 전체 블러가 만든
심도 착시였다는 걸 확인한 뒤, 배경 디테일은 살리면서 심도 단서만 되살리는
방법을 찾는다: Kontext 세그멘테이션 모델(블랙박스)에 다시 기대는 대신, 이
카메라 앵글(저각·원경으로 뻗는 구도)에 맞춰 화면 y좌표 기준 수직 그라데이션
블러를 직접 만든다 — 벤치/병이 있는 하단은 선명, 인물·배경이 있는 상단은
점진적으로 블러.

diffusion 재호출 없음 — v10의 최종 영상(clip2.mp4, Kontext 배경블러 제거+검증된
I2V) 위에 순수 ffmpeg 후처리만 얹는다. 실패해도 되돌리기 쉽다.

실행: cd langgraph && ./.venv/bin/python tests/probe_bev_ad_scene2_v11.py
결과: jobs/probe_bev_ad/clip2.mp4(덮어씀), assets/scene2_v11_gradient_mask.png
"""
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
JOB_DIR = Path(__file__).resolve().parent.parent / "jobs" / "probe_bev_ad"
ASSETS = JOB_DIR / "assets"

FRAME_SIZE = (1280, 704)  # tools.WIDTH/HEIGHT(LTX quality 프리셋) — 720 아님, 실측 확인
# 벤치 상판이 화면에서 대략 y=420~480 부근에서 시작(v9/v10 합성 기준 실측) —
# 그 아래(병 포함)는 완전 선명, 그 위(인물·배경)는 점진적으로 블러 강도 100%까지.
SHARP_BELOW_Y = 470   # 이 y 밑은 마스크=0(완전 선명)
BLUR_ABOVE_Y = 250    # 이 y 위는 마스크=255(완전 블러)
BLUR_SIGMA = 12        # gblur 강도 — v8(radius 31, 과도)보다 훨씬 약하게


def make_gradient_mask() -> Path:
    w, h = FRAME_SIZE
    mask = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(mask)
    for y in range(h):
        if y >= SHARP_BELOW_Y:
            v = 0
        elif y <= BLUR_ABOVE_Y:
            v = 255
        else:
            t = (SHARP_BELOW_Y - y) / (SHARP_BELOW_Y - BLUR_ABOVE_Y)
            v = int(255 * t)
        draw.line([(0, y), (w, y)], fill=v)
    out = ASSETS / "scene2_v11_gradient_mask.png"
    mask.save(out, "PNG")
    return out


def apply_gradient_blur(video: Path, mask_png: Path, out: Path) -> Path:
    """ffmpeg -loop 1 스트리밍 방식이 실측에서 EOF를 못 잡고 폭주함(1.5초 클립에
    7분+ 분량을 뽑아내다 타임아웃 — -shortest도 안 먹힘, ffmpeg 6.1.1 filter_complex+
    loop 조합의 알려진 함정으로 추정). 프레임을 직접 추출→PIL로 픽셀 단위 블렌드
    →재조립하는 결정적 방식으로 대체 — 스트리밍 EOF 문제 자체가 성립 안 함."""
    mask = np.asarray(Image.open(mask_png).convert("L"), dtype=np.float32) / 255.0
    mask3 = mask[:, :, None]

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        frames_dir = tmp_path / "frames"
        frames_dir.mkdir()
        subprocess.run(["ffmpeg", "-y", "-i", str(video), str(frames_dir / "f_%04d.png")],
                       check=True, capture_output=True)
        frame_files = sorted(frames_dir.glob("f_*.png"))
        if not frame_files:
            raise RuntimeError(f"{video}에서 프레임을 못 뽑음")

        out_dir = tmp_path / "out"
        out_dir.mkdir()
        for f in frame_files:
            sharp = Image.open(f).convert("RGB")
            blurred = sharp.filter(ImageFilter.GaussianBlur(BLUR_SIGMA))
            sharp_arr = np.asarray(sharp, dtype=np.float32)
            blurred_arr = np.asarray(blurred, dtype=np.float32)
            blended = sharp_arr * (1 - mask3) + blurred_arr * mask3
            Image.fromarray(blended.astype(np.uint8), "RGB").save(out_dir / f.name)

        subprocess.run([
            "ffmpeg", "-y", "-r", "24", "-i", str(out_dir / "f_%04d.png"),
            "-pix_fmt", "yuv420p", str(out),
        ], check=True, capture_output=True)
    return out


def main() -> int:
    mask_png = make_gradient_mask()
    print(f"그라데이션 마스크: {mask_png}")
    # v10 결과(clip2.mp4, 이미 1.4s로 트림됨, 배경블러 없음+검증된 I2V)를 그대로
    # 소스로 쓴다 — 별도 백업 없이 in-place 트림했었어서 3초 원본은 안 남아있음.
    src = JOB_DIR / "clip2_v10_pre_blur.mp4"
    current = JOB_DIR / "clip2.mp4"
    if not src.exists():
        current.rename(src)
    out = apply_gradient_blur(src, mask_png, current)
    print(f"scene 2 (v11, 그라데이션 블러 후처리) -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
