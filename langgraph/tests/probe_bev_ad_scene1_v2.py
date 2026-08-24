"""음료수 광고 스파이크 씬1 v2 — 사용자 피드백 2건 반영(2026-08-13):

1) 겨드랑이 털 노출(clip1_11.png, 점프슛 구간) 제거
2) 상의에 나이키 스우시 유사 로고 환각(clip1_12.png) 제거 — 가상 브랜드 광고라
   실제 브랜드 마크가 들어가면 안 됨

negative prompt로 안 가고 positive에 긍정형 서술을 넣은 이유: LTX Face-ID
워크플로의 negative는 ltx_faceid_api.json node 35에 하드코딩돼 있을 뿐 아니라,
node 81 CFGGuider가 cfg=1이라 classifier-free guidance가 꺼져 있어 negative
자체가 거의 무력하다. 반면 node 79(TextGenerate)의 STRICT EDITING RULE은 의상
묘사를 verbatim 보존하도록 강제돼 있어 positive에 넣은 의상 문구는 그대로 살아
캡션에 남는다.

시드는 clip1과 동일(20260812) — 모션/구도 품질이 좋았던 조건을 유지하고 의상
서술만 바꿔 차이를 격리한다.

실행: cd langgraph && ./.venv/bin/python tests/probe_bev_ad_scene1_v2.py
결과: jobs/probe_bev_ad/clip11.mp4 (clip1.mp4 덮어쓰지 않도록 scene_id=11)
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
SEED = 20260812      # clip1과 동일 — 의상 서술만 바꿔 차이를 격리
SCENE_ID = 11        # clip1.mp4 보존용(생성 파일은 clip11.mp4)

PROMPT = (
    "cinematic sports commercial, a young Korean man wearing a plain unbranded "
    "white sleeveless jersey with no logos and no text on it and black shorts, "
    "his underarms smooth and hairless, playing basketball alone on an outdoor "
    "court in golden late-afternoon light, dribbling fast then leaping for a "
    "jump shot, sweat glistening on his face, dynamic tracking camera, "
    "shallow depth of field"
)


async def main() -> int:
    ref_name = "face.png"
    shutil.copyfile(FACE_SRC, tools.refs_dir(JOB_ID) / ref_name)
    scenes = [{
        "id": SCENE_ID, "prompt": PROMPT, "duration": 3.0,
        "seed": SEED, "face_id_ref": ref_name,
    }]
    results = await tools.generate_ltx_faceid_batch(JOB_ID, scenes)
    for scene_id, path in results.items():
        print(f"scene {scene_id} -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
