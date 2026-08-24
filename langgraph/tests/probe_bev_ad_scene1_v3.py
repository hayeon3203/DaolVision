"""음료수 광고 스파이크 씬1 v3 — 겨드랑이 털 제거를 의상 교체로 해결(2026-08-13).

v2(positive 프롬프트에 "underarms smooth and hairless" + "no logos and no text"
추가)는 3중 실패로 기각:
- 겨드랑이 털 그대로 남음(clip11_11.png)
- 로고는 오히려 가슴에 2개 생김 — 부정문("no logos")을 diffusion이 부정으로 못
  읽고 오히려 해당 개념을 그려낸다(clip11_05/11/12.png 실측)
- 시드가 같은데도 프롬프트가 길어지면서 프레이밍이 밀려 머리가 잘림(clip11_05.png)

v3는 그래서 변수를 하나로 줄인다: clip1 확정 프롬프트에서 의상 명사만
`sleeveless jersey` → `short-sleeve t-shirt`로 치환. 겨드랑이가 아예 안 보이므로
털 서술 자체가 필요 없고, 로고 관련 문구는 넣지 않는다(부정문 역효과 실측).
프롬프트 길이/구조가 원본과 거의 같아 구도 회귀 위험도 낮다.

연속성 주의: 씬3a(clip3)도 상의가 보이므로 같이 반팔로 맞춰야 한다. 씬2(clip2)는
인물이 원거리 + 아웃포커스라 소매 유무가 식별되지 않아 배경 재생성 불필요
(clip2_final_full_05/07.png 육안 확인).

실행: cd langgraph && ./.venv/bin/python tests/probe_bev_ad_scene1_v3.py
결과: jobs/probe_bev_ad/clip14.mp4 (clip1.mp4 보존, v2 clip11.mp4와도 분리)
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
SEED = 20260812      # clip1과 동일 — 의상 명사만 바꿔 차이를 격리
SCENE_ID = 14

# clip1 확정 프롬프트와 의상 명사 하나만 다름.
PROMPT = (
    "cinematic sports commercial, a young Korean man wearing a plain white "
    "short-sleeve t-shirt and black shorts playing basketball alone on an "
    "outdoor court in golden late-afternoon light, dribbling fast then leaping "
    "for a jump shot, sweat glistening on his face, dynamic tracking camera, "
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
