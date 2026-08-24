"""씬분할·프롬프트 생성 LLM A/B — 모델만 바꿔 같은 시나리오를 돌린다(2026-08-13).

UI E2E job 1a0d85b1에서 Nemotron 3 Nano 4B가 원문을 심하게 변형했다:
  농구장 → soccer field / football pitch
  코트(court) → "one side of the coat"  (외투로 오역)
  음료수 → a glass of water
배경과 피사체가 씬마다 튀는 직접 원인이라 더 큰 한국어 모델과 비교한다.

영상은 만들지 않는다 — 씬 텍스트와 최종 영어 프롬프트만 뽑아 원문 보존 여부를 본다.

실행: cd langgraph && ./.venv/bin/python tests/probe_llm_ab_scene_split.py [모델...]
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import nodes  # noqa: E402
import tools  # noqa: E402

DEFAULT_MODELS = ["hf.co/nvidia/NVIDIA-Nemotron-3-Nano-4B-GGUF:Q4_K_M", "exaone3.5:32b"]

SCENARIO = (
    "한 남자가 농구장에서 땀 흘리며 드리블하고 점프슛을 쏜다. "
    "그는 농구 코트 한쪽 벤치에 놓인 음료수를 향해 달려간다. "
    "벤치 앞에 멈춰 음료수를 집어 들고 시원하게 들이켠다. "
    "다시 농구 코트로 돌아가 공을 잡고 힘차게 달려나간다."
)
CAPTIONS = {
    "img_0.png": ('Clear plastic bottle with orange cap containing liquid labeled '
                  '"Urtape" featuring a blue to orange gradient and yellow lightning bolt logo'),
    "gen_0.png": "Young Asian man wearing white t-shirt",
}
# 원문 보존을 기계적으로 채점할 신호. 있으면 좋은 것 / 있으면 나쁜 것.
GOOD = ["basketball", "court", "bottle", "bench"]
BAD = ["soccer", "football", "pitch", "coat", "glass of water", "wine"]


async def run_model(model: str) -> dict:
    tools.LLM_MODEL = model
    state = {
        "job_id": f"probe_llm_ab", "script_text": SCENARIO,
        "ref_images": list(CAPTIONS), "ref_captions": CAPTIONS,
    }
    split = await nodes.node_split_scenes(state)
    state.update(split)
    prompts = await nodes.node_generate_prompts(state)
    return prompts


def score(scenes: list[dict]) -> tuple[int, int]:
    blob = " ".join((s.get("prompt") or "").lower() for s in scenes)
    return (sum(1 for g in GOOD if g in blob), sum(1 for b in BAD if b in blob))


async def main() -> int:
    models = sys.argv[1:] or DEFAULT_MODELS
    results = {}
    for model in models:
        print(f"\n{'=' * 78}\n모델: {model}\n{'=' * 78}")
        try:
            out = await run_model(model)
        except Exception as exc:
            print(f"  실패: {exc}")
            continue
        scenes = out["scenes"]
        print(f"style_bible: {(out.get('style_bible') or '')[:150]}\n")
        for s in scenes:
            print(f"씬{s['id']} mode={s.get('mode')} role={s.get('image_role')} "
                  f"matched={s.get('matched_image')} face={s.get('face_id_ref')}")
            print(f"  text  : {s.get('text')}")
            print(f"  set/lit: {s.get('setting')} / {s.get('lighting')}")
            print(f"  prompt: {(s.get('prompt') or '')[:280]}\n")
        good, bad = score(scenes)
        results[model] = (good, bad)
        print(f"원문 보존 신호 {good}/{len(GOOD)} · 변형 신호 {bad}/{len(BAD)}")

    print(f"\n{'=' * 78}\n요약 (보존↑ 변형↓ 이 좋음)")
    for model, (good, bad) in results.items():
        print(f"  {model:52s} 보존 {good}/{len(GOOD)}  변형 {bad}/{len(BAD)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
