"""Task 5.3 live acceptance: LTX Face-ID clips 4개, 앵커 없이 3.2 배선 재사용."""
import asyncio
import argparse
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import nodes
import tools


JOB_ID = "task53-live-20260731"
FACE_SOURCE = Path(__file__).resolve().parents[2] / "건호군.jpg"
FACE_NAME = "astronaut_face.webp"

SCENES = [
    "A person astronaut with a transparent helmet visor, facing the camera, "
    "standing on a sunset launch pad, wide establishing shot, static camera, "
    "no camera movement, character small in frame relative to environment, "
    "expansive background.",
    "A person astronaut with a transparent helmet visor, facing the camera, "
    "floating above Earth during a spacewalk, wide cinematic shot, static "
    "camera, character small in frame relative to environment, stars and "
    "blue planet filling the expansive background.",
    "A person astronaut with a transparent helmet visor, facing the camera, "
    "standing on a rocky alien planet beneath two moons, wide establishing "
    "shot, static camera, character small in frame relative to environment, "
    "expansive violet landscape.",
    "A person astronaut with a transparent helmet visor, facing the camera, "
    "standing at the spacecraft hatch back on Earth, wide triumphant shot, "
    "static camera, character small in frame relative to environment, warm "
    "sunrise and recovery crew in the expansive background.",
]


async def main(scene_ids: set[int] | None = None):
    if not FACE_SOURCE.is_file():
        raise FileNotFoundError(FACE_SOURCE)
    ref_path = tools.refs_dir(JOB_ID) / FACE_NAME
    shutil.copyfile(FACE_SOURCE, ref_path)

    scenes = []
    print(f"[job] {JOB_ID}", flush=True)
    for scene_id, prompt in enumerate(SCENES, 1):
        if scene_ids and scene_id not in scene_ids:
            continue
        scenes.append({
            "id": scene_id,
            "text": prompt,
            "prompt": prompt,
            "duration": 2.0,
            "mode": "LTX_FACEID",
            "face_id_ref": FACE_NAME,
            "matched_image": FACE_NAME,
            "image_role": "ref",
            "subject_type": "human",
            "seed": nodes.scene_seed(JOB_ID, scene_id),
        })

    print("[ltx batch] submitting one graph with four sampler branches", flush=True)
    started = time.monotonic()
    clips = await tools.generate_ltx_faceid_batch(JOB_ID, scenes)
    print(f"[ltx batch] complete ({time.monotonic() - started:.1f}s)", flush=True)

    for scene in scenes:
        scene["clip_path"] = clips[scene["id"]]
    manifest = tools.job_dir(JOB_ID) / "manifest.json"
    manifest.write_text(json.dumps({
        "job_id": JOB_ID,
        "face_reference": str(ref_path),
        "scenes": scenes,
    }, ensure_ascii=False, indent=2))
    for scene in scenes:
        clip = Path(scene["clip_path"])
        if not clip.is_file() or clip.stat().st_size == 0:
            raise RuntimeError(f"missing clip: {clip}")
        print(f"[clip {scene['id']}/4] {clip} ({clip.stat().st_size} bytes)", flush=True)
    print(f"PASS manifest={manifest}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene-ids", default="")
    args = parser.parse_args()
    selected = {int(value) for value in args.scene_ids.split(",") if value}
    asyncio.run(main(scene_ids=selected or None))
