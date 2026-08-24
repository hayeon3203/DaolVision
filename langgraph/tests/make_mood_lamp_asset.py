"""무드등 제품 정본(투명 배경 컷아웃) 생성 (2026-08-23).

프로덕션에는 배경 제거 단계가 없다 — 참조 제품은 **투명 배경 RGBA 컷아웃**이어야 한다
(docs/spikes/2026-08-13-ui-e2e-baseline.md). 음료 스파이크의 bottle_canonical_v3.png가
그렇듯 알파 bbox에 딱 맞게 잘라 둔다.

FLUX(:8501)로 무드등 1장을 뽑고, ComfyUI birefnet(`tools.person_mask`가 이미 쓰는
RemoveBackground 노드)으로 알파를 딴다. 신규 모델·의존성 없음.

실행: cd langgraph && ./.venv/bin/python -u tests/make_mood_lamp_asset.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image                                    # noqa: E402

import tools                                             # noqa: E402

JOB = "probe_mood_lamp"
SEED = 20260823
OUT = Path(__file__).resolve().parents[1] / "jobs" / JOB / "assets" / "lamp_canonical.png"

# 배경을 **단색**으로 못박는다. birefnet은 살릴 피사체를 하나로 잡아야 하는데 방 배경이
# 있으면 협탁·벽까지 물고 들어온다. 켜진 상태로 뽑는 이유는 이 광고의 주인공이 빛이라
# 꺼진 램프를 합성하면 씬 조명과 따로 논다.
# 흰 원통은 화병처럼 보이고(첫 시도 실측) 밝은 배경에서 사라진다. 구(球) 형태 +
# 어두운 베이스 + 진한 앰버 발광으로 실루엣과 대비를 둘 다 준다 — 프레임 폭 15%로
# 축소돼도 램프로 읽혀야 한다.
PROMPT = (
    "product photograph of a single modern mood lamp: a frosted glass sphere glowing "
    "with intense warm amber orange light, switched on and clearly emitting light, "
    "sitting on a short dark walnut wood cylindrical base, standing upright and "
    "centered, isolated on a plain flat pure white seamless background, no table, "
    "no props, no text, no logo, studio product lighting, sharp focus, full object "
    "visible with margin around it"
)


async def main() -> int:
    path = await tools.generate_t2i_image(JOB, PROMPT, seed=SEED, index=0)
    print(f"T2I: {path}")
    raw = Path(path).read_bytes()

    mask = await tools.person_mask(raw, upload_name=f"lamp_cutout_{SEED}.png")
    img = Image.open(path).convert("RGBA")
    if mask.shape != (img.height, img.width):            # 마스크는 원본 해상도로 돌아온다
        raise SystemExit(f"마스크 크기 불일치: {mask.shape} vs {(img.height, img.width)}")

    alpha = Image.fromarray((mask * 255).astype("uint8"), mode="L")
    img.putalpha(alpha)
    box = img.split()[-1].getbbox()
    if box is None:
        raise SystemExit("컷아웃이 비었다 — 배경 제거가 피사체를 통째로 지웠다")
    cut = img.crop(box)

    # 알파가 프레임의 5% 미만이면 램프가 아니라 파편을 잡은 것이다(배경 제거 실패).
    ratio = (cut.width * cut.height) / (img.width * img.height)
    print(f"알파 bbox {box} → {cut.size} (프레임의 {ratio:.1%})")
    if ratio < 0.05:
        raise SystemExit("컷아웃이 너무 작다 — 프롬프트/시드를 바꿔 다시 뽑을 것")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    cut.save(OUT)
    print(f"제품 정본: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
