"""Send fan-out된 씬 클립 생성이 _gen_semaphore 상한을 절대 넘지 않는지 검증.

회귀 방지: 이 상한이 사라지면 씬 4개가 :8500(Wan)+:8188(ComfyUI) 확산을 같은 순간에
피크로 몰아 GB10 통합메모리 OOM → ReadTimeout/정지. 참조: [[gb10-gpu-contention-comfyui-ollama]]

    ./.venv/bin/python tests/test_clip_concurrency.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # langgraph/ 모듈 import용

import tools
import nodes


async def _run(limit: int, n_scenes: int = 6):
    """limit 상한으로 n_scenes개를 동시 fan-out → (관측 peak, 반환된 id 집합) 반환."""
    tools._gen_semaphore = asyncio.Semaphore(limit)
    live = {"cur": 0, "peak": 0}

    async def fake_gen(**_kw):
        live["cur"] += 1
        live["peak"] = max(live["peak"], live["cur"])
        await asyncio.sleep(0.02)          # 실제 GPU 점유 구간을 흉내
        live["cur"] -= 1
        return "clip.mp4"

    # 세 백엔드 경로를 모두 같은 fake로 대체 — 어느 모드든 단일 길목을 통과함을 확인.
    tools.call_video = fake_gen
    tools.generate_standin_clip = fake_gen
    tools.generate_subject_ref_clip = fake_gen

    # 모드를 섞어 :8500/:8188 양쪽 경로가 하나의 세마포어로 합산 게이팅되는지 본다.
    modes = ["T2V", "STANDIN", "SUBJECT_REF", "I2V", "STANDIN", "T2V"][:n_scenes]
    scenes = [{"id": i, "mode": m, "prompt": "p", "matched_image": "r.png", "duration": 2.0}
              for i, m in enumerate(modes)]

    results = await asyncio.gather(*[
        nodes.node_generate_one_clip({"scene": s, "job_id": "t", "seed": 1}) for s in scenes
    ])
    got_ids = {r["clip_results"][0]["id"] for r in results}
    return live["peak"], got_ids


def main():
    expected_ids = set(range(6))

    peak1, ids1 = asyncio.run(_run(1))
    assert peak1 == 1, f"limit=1 인데 동시 실행 peak={peak1}"
    assert ids1 == expected_ids, f"씬 유실/중복: {ids1}"

    peak2, ids2 = asyncio.run(_run(2))
    assert peak2 == 2, f"limit=2 인데 peak={peak2} (게이팅이 과하거나 동시성이 안 남)"
    assert ids2 == expected_ids, f"씬 유실/중복: {ids2}"

    print("ok: limit=1 → peak 1(완전 순차) / limit=2 → peak 2 / 6씬 id 전부 보존")


if __name__ == "__main__":
    main()
