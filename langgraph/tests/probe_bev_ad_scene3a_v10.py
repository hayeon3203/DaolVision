"""음료수 광고 스파이크 씬3a v10 — 동작 폭 제한(2026-08-13 사용자 지적).

v9(clip18)는 채택 방향인데 2초대부터 무너진다: 병이 입을 지나 **눈 높이까지**
올라가고, 왼팔까지 올라와 양손이 얼굴을 감싸 손이 4개처럼 보이며, 고개가 과하게
젖혀진다(clip18_09/11.png). 라벨·캡은 끝까지 유지되므로 제품 쪽은 문제 없다.

바꾸는 건 I2V 프롬프트 하나뿐이다. 첫 프레임(scene3a_v9_recomposed.png)과 시드,
negative는 v9 그대로 — 사용자가 승인한 앞 구간을 보존하기 위해서다.

프롬프트 수정 방향(부정문 금지 — 씬1 v2에서 "no logos"가 오히려 로고를 만든 실측):
- 병이 닿는 지점을 명시한다("rim rests against his lower lip", "chin height")
- 한 손만 쓴다고 긍정으로 못박고 왼팔의 위치를 따로 지정한다
- 고개 젖힘을 "slightly"로 한정한다

실행: cd langgraph && ./.venv/bin/python tests/probe_bev_ad_scene3a_v10.py
결과: jobs/probe_bev_ad/clip19.mp4
"""
import asyncio
import sys
from pathlib import Path

import httpx

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))
sys.path.insert(0, str(_HERE))
import tools  # noqa: E402
from probe_bev_ad_scene3a_v5 import (  # noqa: E402
    NEGATIVE_PROMPT, _build_ltx13b_graph_custom_negative,
)
from probe_bev_ad_scene3a_v8 import I2V_SEED  # noqa: E402

JOB_ID = "probe_bev_ad"
ASSETS = _HERE.parent / "jobs" / JOB_ID / "assets"
SCENE_ID = 19

I2V_PROMPT = (
    "cinematic, he lifts the clear plastic bottle he is already holding a short "
    "distance up to his mouth and drinks, the bottle rim rests against his lower "
    "lip at chin height and stays there, only his right hand touches the bottle "
    "and his grip never changes, his left arm hangs relaxed at his side below "
    "the frame, his head tips back only slightly, the bottle stays a clear "
    "plastic PET sports drink bottle with an orange cap and a blue-to-orange "
    "gradient label throughout, natural continuous motion, golden light"
)


async def main() -> int:
    first = ASSETS / "scene3a_v9_recomposed.png"   # v9 확정 첫 프레임 재사용
    async with (
        tools.oom.phase("i2v"),
        httpx.AsyncClient(timeout=httpx.Timeout(connect=10.0, read=60.0, write=60.0, pool=None)) as client,
    ):
        up = await client.post(
            f"{tools.COMFYUI_URL}/upload/image",
            files={"image": (f"scene3a_v10_{first.name}", first.read_bytes(), "image/png")},
            data={"overwrite": "true"},
        )
        up.raise_for_status()
        uj = up.json()
        image_name = f"{uj['subfolder']}/{uj['name']}" if uj.get("subfolder") else uj["name"]

    graph = _build_ltx13b_graph_custom_negative(
        prompt=I2V_PROMPT, negative=NEGATIVE_PROMPT, image_name=image_name,
        width=tools.WIDTH, height=tools.HEIGHT, seed=I2V_SEED)
    graph["7"]["inputs"]["length"] = tools.to_ltx_len(3.0 * tools.LTX13B_FPS)
    clip = await tools._generate_ltx_job_clip(
        JOB_ID, SCENE_ID, graph, f"scene3a_v10_{I2V_SEED}", True)
    print(f"scene 3a (v10, 동작 폭 제한) -> {clip}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
