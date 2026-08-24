"""LTX distilled(cfg=1.0)에서 NAG로 negative prompt를 되살릴 수 있는지 A/B (2026-08-23).

문제: `_build_ltx13b_t2v_graph`/`_build_ltx13b_graph`의 KSampler는 cfg=1.0인데,
ComfyUI는 그때 uncond를 통째로 건너뛴다(comfy/samplers.py:609
`if math.isclose(cond_scale, 1.0) ... uncond_ = None`). 그래서 negative_prompt가
계산만 되고 샘플러에 도달하지 않는다. 이 프로젝트에서 지금까지 negative로 뭔가를
밀어내려던 시도가 전부 실패한 근본 원인이다(무드등 광고: T2V가 자기 램프를 씬마다
1~2개씩 그림 / 음료 광고: wine bottle 드리프트).

NAG(Normalized Attention Guidance)는 cfg를 못 쓰는 distilled 모델용으로, guidance를
attention 공간에서 건다. ComfyUI-KJNodes의 `LTX2_NAG`가 설치돼 있다(출력 MODEL).
이름이 LTX2_인데 우리 체크포인트는 ltxv-13b-0.9.8-distilled라 **동작 보장이 없다** —
그걸 확인하는 게 이 프로브의 전부다.

A/B: 같은 프롬프트·같은 시드로
  씬1 = baseline (NAG 없음)
  씬2 = NAG (negative = 조명기구 명사들)
결과에서 램프 개수가 줄면 성공.

실행: cd langgraph && ./.venv/bin/python -u tests/probe_ltx_nag_negative.py
산출: jobs/probe_nag/clip1.mp4(baseline), clip2.mp4(NAG)
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import tools  # noqa: E402

JOB_ID = "probe_nag"
SEED = 20260823
DURATION = 3.0

# 램프를 확실히 소환하는 장면 — baseline이 램프를 안 그리면 A/B가 성립 안 한다.
PROMPT = ". ".join([
    tools.PRODUCT_OVERLAY_STYLE,
    tools.PRODUCT_OVERLAY_PERSON_FRAMING,
    tools.PRODUCT_OVERLAY_SURFACE,
    tools.PRODUCT_OVERLAY_LIGHT,
    tools.STATIC_CAMERA_CLAUSE,
    "a man in his 30s sits on a living room sofa at night reading a book, turning a page",
]) + "."

# 밀어낼 것 — 조명기구만. 화질 negative는 섞지 않는다(효과 귀속을 흐린다).
NEGATIVE = ("table lamp, floor lamp, desk lamp, lamp shade, light fixture, chandelier, "
            "pendant light, wall sconce, standing lamp")

# KJNodes 기본값. 되면 이 값들을 튜닝 대상으로 넘긴다.
NAG_SCALE = float(sys.argv[1]) if len(sys.argv) > 1 else 11.0
NAG_ALPHA = 0.25
NAG_TAU = 2.5


def build_graph(*, with_nag: bool) -> dict:
    g = tools._build_ltx13b_t2v_graph(
        prompt=PROMPT, width=tools.WIDTH, height=tools.HEIGHT,
        length=tools.to_ltx_len(DURATION * tools.LTX13B_FPS), seed=SEED)
    # 노드4는 화질 negative가 하드코딩돼 있다 — 조명기구 negative로 바꾼다.
    g["4"]["inputs"]["text"] = NEGATIVE
    if with_nag:
        # ModelSamplingLTXV(6) → LTX2_NAG(13) → KSampler(9)
        g["13"] = {"class_type": "LTX2_NAG", "inputs": {
            "model": ["6", 0], "nag_scale": NAG_SCALE, "nag_alpha": NAG_ALPHA,
            "nag_tau": NAG_TAU, "nag_cond_video": ["4", 0],
        }}
        g["9"]["inputs"]["model"] = ["13", 0]
    return g


async def main() -> None:
    print(f"프롬프트:\n{PROMPT}\n")
    print(f"negative: {NEGATIVE}")
    print(f"NAG: scale={NAG_SCALE} alpha={NAG_ALPHA} tau={NAG_TAU}\n")
    # NAG가 이 체크포인트에서 죽었으므로(LTX2 전용) cfg 상향이 유일하게 남은 레버다.
    # distilled는 cfg=1.0 전제로 학습돼 있어 올리면 화질이 무너질 수 있다 — 그걸 잰다.
    variants = [(1, "baseline", None), (2, "NAG", "nag"), (3, "cfg2.0", 2.0),
                (4, "cfg3.0", 3.0)]
    for scene_id, label, mode in variants:
        graph = build_graph(with_nag=(mode == "nag"))
        if isinstance(mode, float):
            graph["9"]["inputs"]["cfg"] = mode
        key = f"nag_ab_{label}_{SEED}_{NAG_SCALE}"
        try:
            clip = await tools._generate_ltx_job_clip(JOB_ID, scene_id, graph, key, True)
        except Exception as exc:
            print(f"[{label}] 실패: {type(exc).__name__}: {exc}")
            continue
        print(f"[{label}] {clip}")
    print(f"\n산출: {tools.job_dir(JOB_ID)}")


if __name__ == "__main__":
    asyncio.run(main())
