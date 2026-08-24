"""불투명 제품 참조가 합성 전에 컷아웃되는지 회귀 테스트.

이전 동작: 제품 참조를 그대로 alpha_composite 했다. 프론트 describe 모드가 M2로 생성한
제품 이미지는 FLUX가 RGB로만 내주므로(실측: 1280x720 RGB, 알파 extrema (255,255)) 알파가
전부 255고, 흰 배경 사각형이 씬에 통째로 붙었다. 사용자가 올린 일반 제품 사진도 같다.

지금 동작: `_compose_and_recompose_product`가 합성 직전에 `_ensure_product_cutout`을 태운다.
알파가 이미 있으면 건드리지 않고, 없으면 birefnet으로 배경을 지운 뒤 알파 bbox로 자른다.
실패하면 원본으로 폴백한다(배경이 붙는 게 제품이 사라지는 것보다 낫다).

    cd langgraph && ./.venv/bin/python tests/test_product_cutout.py
"""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

os.environ["AGENT_JOBS_DIR"] = tempfile.mkdtemp(prefix="anim_test_jobs_")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tools        # noqa: E402

W, H = 200, 120
BOX = (60, 30, 140, 100)        # 흰 배경 위의 제품 영역


def _opaque_product(path: Path) -> None:
    """M2/T2I 출력을 흉내낸다 — RGB(알파 없음), 흰 배경, 가운데에 제품."""
    img = Image.new("RGB", (W, H), (255, 255, 255))
    img.paste(Image.new("RGB", (BOX[2] - BOX[0], BOX[3] - BOX[1]), (200, 90, 20)), BOX[:2])
    img.save(path)


def _mask_of_box():
    mask = np.zeros((H, W), dtype=bool)
    mask[BOX[1]:BOX[3], BOX[0]:BOX[2]] = True
    return mask


async def main() -> None:
    work = Path(tempfile.mkdtemp(prefix="cutout_"))
    calls = []

    async def fake_person_mask(image_bytes, upload_name="x.png"):
        calls.append(upload_name)
        return _mask_of_box()

    tools.person_mask = fake_person_mask

    # 1) 불투명 입력 → 배경 제거 + bbox 크롭
    src = work / "gen_0.png"
    _opaque_product(src)
    out = await tools._ensure_product_cutout(src, "n1")
    assert out != src, "불투명 제품이 컷아웃되지 않았다"
    cut = Image.open(out)
    assert cut.mode == "RGBA" and cut.size == (BOX[2] - BOX[0], BOX[3] - BOX[1]), (cut.mode, cut.size)
    assert cut.getchannel("A").getextrema() == (255, 255), "제품 영역은 불투명해야 한다"

    # 2) 같은 파일 재호출 → 캐시 재사용(birefnet 재호출 없음)
    again = await tools._ensure_product_cutout(src, "n2")
    assert again == out and len(calls) == 1, f"컷아웃이 캐시되지 않았다: {calls}"

    # 3) 이미 투명한 컷아웃은 건드리지 않는다
    already = work / "canonical.png"
    rgba = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
    rgba.paste(Image.new("RGBA", (20, 20), (255, 0, 0, 255)), (10, 10))
    rgba.save(already)
    assert await tools._ensure_product_cutout(already, "n3") == already
    assert len(calls) == 1, "투명 입력에 birefnet을 또 돌렸다"

    # 4) 배경 제거가 전부 지우면 원본으로 폴백한다
    async def empty_mask(image_bytes, upload_name="x.png"):
        return np.zeros((H, W), dtype=bool)

    tools.person_mask = empty_mask
    blank = work / "blank.png"
    _opaque_product(blank)
    assert await tools._ensure_product_cutout(blank, "n4") == blank, "실패 시 원본 폴백이 안 됐다"

    print("OK: 불투명 제품만 컷아웃, 캐시 재사용, 실패 시 원본 폴백")


if __name__ == "__main__":
    asyncio.run(main())
