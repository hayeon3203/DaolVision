"""DaolFusion 로고 + NVIDIA 파트너 배지를 GB10 워크스테이션 사진에 오버레이해
subject_ref 참조 이미지를 만든다. AI 합성(Flux Kontext I2I) 대신 Pillow 결정론
오버레이를 쓴다 — 로고 픽셀이 프롬프트 해석에 좌우되지 않고 항상 원본 그대로
나오게 하기 위함(2026-08-12 설계문서 대비 구현 결정, 로고 정확도 보장이 원래
의도였으므로 방향은 동일).

실행: cd langgraph && ./.venv/bin/python tests/probe_logo_hw_compose.py
"""
from pathlib import Path

from PIL import Image

ASSETS = Path(__file__).resolve().parent.parent / "jobs" / "probe_logo_hw" / "assets"


def _find_device_photo() -> Path:
    for ext in ("jpg", "jpeg", "png"):
        p = ASSETS / f"device_gb10.{ext}"
        if p.exists():
            return p
    raise FileNotFoundError(
        f"{ASSETS}/device_gb10.{{jpg,png}} 없음 — GB10 워크스테이션 사진을 먼저 넣어라."
    )


def compose(
    device_path: Path,
    main_logo_path: Path,
    badge_logo_path: Path,
    out_path: Path,
    *,
    main_logo_width_ratio: float = 0.19,
    main_logo_center_x_ratio: float = 0.415,
    main_logo_center_y_ratio: float = 0.575,
    badge_width_ratio: float = 0.06,
    badge_center_x_ratio: float = 0.875,
    badge_center_y_ratio: float = 0.44,
) -> Path:
    """위치 기본값은 `nvidia-blackwell-products-gb10-update.png`(2500x2000,
    투명 배경 + 대각선 앵글의 박스 하나) 기준으로 실측 조정됨:
    - main_logo: 정면 그릴(허니콤) 패널 중앙 — 원래 있던 "DELL" 워드마크를
      DaolFusion 로고로 덮어서 가린다.
    - badge: 오른쪽 위로 기울어진 광택 측면 패널 위 — 캔버스 우하단 모서리가
      아니라(투명 여백이 넓어 거기 두면 장비에서 붕 뜬다) 장비 몸체 위의 좌표.
    다른 사진으로 바꾸면 이 네 값을 그 사진에 맞게 다시 잡아야 한다."""
    device = Image.open(device_path).convert("RGBA")
    dw, dh = device.size

    main_logo = Image.open(main_logo_path).convert("RGBA")
    main_w = int(dw * main_logo_width_ratio)
    main_h = int(main_logo.height * (main_w / main_logo.width))
    main_logo = main_logo.resize((main_w, main_h), Image.LANCZOS)
    main_x = int(dw * main_logo_center_x_ratio - main_w / 2)
    main_y = int(dh * main_logo_center_y_ratio - main_h / 2)
    device.alpha_composite(main_logo, (main_x, main_y))

    badge = Image.open(badge_logo_path).convert("RGBA")
    badge_w = int(dw * badge_width_ratio)
    badge_h = int(badge.height * (badge_w / badge.width))
    badge = badge.resize((badge_w, badge_h), Image.LANCZOS)
    badge_x = int(dw * badge_center_x_ratio - badge_w / 2)
    badge_y = int(dh * badge_center_y_ratio - badge_h / 2)
    device.alpha_composite(badge, (badge_x, badge_y))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    device.convert("RGB").save(out_path, "PNG")
    return out_path


def main() -> int:
    device_path = _find_device_photo()
    out = compose(
        device_path=device_path,
        main_logo_path=ASSETS / "logo_daolfusion.png",
        badge_logo_path=ASSETS / "logo_nvidia.png",
        out_path=ASSETS / "ref_composite.png",
    )
    print(f"합성 완료: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
