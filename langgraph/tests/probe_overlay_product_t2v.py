"""T2V 사람 장면 + 제품 정적 오버레이 (2026-08-23).

조립 첫 프레임 → I2V 경로를 뒤집는 안의 1단계 프로브. 지금 경로는 제품을 먼저 박고
LTX에 넘기는데, LTX는 조건 이미지를 첫 latent 하나(=8프레임)에만 쓰고 나머지는
denoise=1.0으로 새로 그린다(job dd16ef56 실측: clip1 루마 f0~f6 30.4 고정 → f10 157).
negative로도 못 막는다 — KSampler cfg=1.0이면 ComfyUI가 uncond를 건너뛴다.

그래서 순서를 뒤집는다:
  1) T2V로 **사람 장면만** 만든다. 카메라 고정 + 전경 오른쪽 아래에 빈 표면 +
     제품이 만들 빛만 미리(제품 없이).
  2) 제품 컷아웃을 영상 크기 투명 PNG 한 장으로 굽고 ffmpeg overlay로 전 프레임에 얹는다.
제품을 영상모델이 만지지 않으므로 드리프트할 자리가 없다.

인물 일관성은 요구하지 않는다(씬마다 다른 사람이어도 됨) — 그래서 인물 참조도,
조립도, I2V도 필요없다.

실행: cd langgraph && ./.venv/bin/python -u tests/probe_overlay_product_t2v.py
산출: jobs/probe_overlay/clip{1,2}.mp4(T2V 원본), clip{1,2}_final.mp4(오버레이),
      layer{1,2}.png(구운 제품 레이어)
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import tools  # noqa: E402

# 프롬프트를 고칠 때마다 올린다 — 이전 라운드 산출물을 덮어쓰지 않고 비교하려고.
VARIANT = "v3"
JOB_ID = f"probe_overlay_{VARIANT}"
ROOT = Path(__file__).resolve().parent.parent
PRODUCT = ROOT / "jobs" / "probe_mood_lamp" / "assets" / "lamp_canonical.png"
SEED = 20260823
DURATION = 3.0

# 카메라 고정이 이 경로의 전제다. 카메라가 움직이면 정지 레이어가 배경과 어긋난다.
CAMERA = ("the camera is locked off on a tripod, completely static framing with no pan, "
          "no tilt, no dolly and no zoom")

# 제품이 놓일 자리. 제품 명사를 쓰지 않는다 — 쓰면 T2V가 자기 나름의 램프를 그려
# 오버레이한 제품과 둘이 된다(2026-08-13 히어로컷 실측과 같은 함정). negative로
# 지울 수도 없다(cfg=1.0). 그래서 "비어 있다"를 positive로만 말한다.
EMPTY_SPOT = ("a bare wooden tabletop spans the full width of the near foreground along the "
              "bottom edge of the frame, seen slightly from above, its surface completely "
              "empty and clear with nothing resting on it")

# 조명 문구 3라운드 기록 (전부 cfg=1.0 때문 — negative가 죽어 있어 positive 문장만이
# 유일한 레버다):
#   v1 "warm amber light spills outward from that lower-right foreground" → LTX가 그
#      광원을 실제로 그렸다. 씬마다 램프 2개 생성, 무드등 광고에 램프 3개.
#   v2 "with no lamps and no light fixtures anywhere in the shot" → **여전히 그렸다**.
#      부정어가 안 먹고 "lamp"라는 명사만 조건에 남는다. 부정문이 소환문이 된다.
#   v3 광원을 아예 언급하지 않는다. 방의 톤만 말하고 빛의 출처를 묻지 않는다 —
#      오버레이한 무드등이 그 방의 유일한 조명기구가 된다.
GLOW = ("the room is bathed in a soft warm amber evening tone with deep gentle shadows in the "
        "corners, faces still clearly visible, calm and intimate")

SCENES = [
    {
        "id": 1,
        # 전경 오른쪽 아래를 제품에 내주므로 사람은 중경 왼쪽~중앙에 둔다(동선 분리).
        "action": ("a family of four sits together on a large fabric sofa in the mid-ground "
                   "on the left, the parents talking quietly while the two children lean "
                   "against them, everyone relaxed and smiling, gentle natural movement"),
        # 와이드 거실샷 — 램프는 소품 크기.
        "ratios": {"width_ratio": 0.14, "center_x_ratio": 0.66, "bottom_y_ratio": 0.82},
    },
    {
        "id": 2,
        "action": ("a man in his 30s works late at his own office desk in the mid-ground on "
                   "the left, typing on a laptop, then leaning back in his chair and "
                   "rolling his shoulders, calm and focused"),
        # 책상 옆은 카메라에 더 가까움 — 조금 크게.
        "ratios": {"width_ratio": 0.20, "center_x_ratio": 0.80, "bottom_y_ratio": 0.97},
    },
]


def build_prompt(action: str) -> str:
    return (f"A cinematic commercial shot. {action}. {EMPTY_SPOT}. {GLOW}. {CAMERA}.")


async def main(overlay_only: bool = False, tag: str = "") -> None:
    """overlay_only=True면 이미 만든 T2V 클립을 그대로 쓰고 오버레이만 다시 한다.

    제품 위치·크기 튜닝에 GPU가 전혀 필요없다는 뜻이다 — 제품은 영상 생성과 완전히
    분리돼 있으므로 ratios만 바꿔 몇 초 만에 다시 얹으면 된다. 조립+I2V 경로에서는
    비율 하나 바꿀 때마다 클립을 통째로 다시 뽑아야 했다.
    """
    job = tools.job_dir(JOB_ID)
    print(f"job dir: {job}")
    print(f"제품: {PRODUCT} {'(있음)' if PRODUCT.exists() else '(없음!)'}")
    for scene in SCENES:
        sid = scene["id"]
        clip = job / f"clip{sid}.mp4"
        if overlay_only:
            if not clip.exists():
                raise SystemExit(f"{clip} 없음 — overlay-only는 T2V를 먼저 돌린 뒤에만 쓴다")
            print(f"씬{sid} 기존 T2V 클립 재사용: {clip}")
        else:
            prompt = build_prompt(scene["action"])
            print(f"\n── 씬{sid} T2V ──\n{prompt}\n")
            clip = await tools.generate_t2v_clip(
                JOB_ID, sid, prompt, duration=DURATION, seed=SEED, force_new=True)
            print(f"씬{sid} T2V 클립: {clip}")
        final = job / f"clip{sid}_final{tag}.mp4"
        tools.overlay_product_on_clip(
            clip, PRODUCT, final, layer_path=job / f"layer{sid}{tag}.png", **scene["ratios"])
        print(f"씬{sid} 오버레이 완료: {final}")
    print("\n산출물:")
    for p in sorted(job.glob("*.mp4")) + sorted(job.glob("*.png")):
        print(f"  {p}")


if __name__ == "__main__":
    # --overlay-only [태그]: T2V 건너뛰고 오버레이만 다시(위치·크기 튜닝용, GPU 불필요)
    _only = "--overlay-only" in sys.argv
    _tag = next((a for a in sys.argv[1:] if not a.startswith("-")), "")
    asyncio.run(main(overlay_only=_only, tag=_tag))
