"""음료수 광고 스파이크 씬1 (B노선) — 참조 lock 없는 순수 인물 생성.
LTX Face-ID 경로(generate_ltx_faceid_batch)로 얼굴 identity만 걸고
농구 운동 씬을 자유 생성한다. 핵심 관찰: 빠른 스포츠 동작의 팔다리 해부구조.

실행: cd langgraph && ./.venv/bin/python tests/probe_bev_ad_scene1.py
결과: jobs/probe_bev_ad/clip1.mp4
"""
import asyncio
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import tools  # noqa: E402

JOB_ID = "probe_bev_ad"
FACE_SRC = (Path(__file__).resolve().parent.parent / "jobs" / JOB_ID
            / "assets" / "person_canonical.png")
SEED = 20260812

PROMPT = (
    "cinematic sports commercial, a young Korean man wearing a plain white "
    "sleeveless jersey and black shorts playing basketball alone on an outdoor "
    "court in golden late-afternoon light, dribbling fast then leaping for a "
    "jump shot, sweat glistening on his face, dynamic tracking camera, "
    "shallow depth of field"
)


async def main() -> int:
    ref_name = "face.png"
    shutil.copyfile(FACE_SRC, tools.refs_dir(JOB_ID) / ref_name)
    scenes = [{
        "id": 1, "prompt": PROMPT, "duration": 3.0,
        "seed": SEED, "face_id_ref": ref_name,
    }]
    results = await tools.generate_ltx_faceid_batch(JOB_ID, scenes)
    for scene_id, path in results.items():
        print(f"scene {scene_id} -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
