"""씬4를 제품 없이 조립 경로로 만들어 본다 (2026-08-14).

씬4는 제품이 손을 떠난 뒤의 컷이라 제품이 화면에 없어야 한다. 지금 프로덕션은 그런
씬을 `role=ref`로 판정해 LTX 2.3 22B Face-ID로 보내는데, Face-ID 씬이 2개가 되면
GGUF 축출로 10~40분 정체가 난다(docs/spikes/2026-08-13-scene5-e2e-handoff.md).

사용자 결정(2026-08-14): 씬2·3·5의 조립 경로 인물 품질이면 충분하니 씬4도 같은 경로로
보낸다. 여기서는 그 경로를 코드 수정 전에 **먼저 눈으로 확인**한다 — 조립 경로에서
제품 합성 단계(2·3단계)만 건너뛴 형태다:

    배경 T2I(씬 프롬프트 + 인물 외형) → LTX 13B I2V

`generate_product_scene_clip`은 제품을 항상 얹으므로 여기서는 두 단계를 직접 호출한다.
프로덕션 이식은 이 결과를 보고 결정한다.

실행: cd langgraph && ./.venv/bin/python -u tests/probe_scene4_no_product.py
산출: jobs/probe_assembly_235/scene4_bg.png, clip4.mp4
"""
import asyncio
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import tools  # noqa: E402

JOB_ID = "probe_assembly_235"          # 씬2·3·5와 같은 job에 넣어 나란히 비교한다
SCENE_ID = 4
SEED = 1098672158                      # 베이스라인 3ded2f29 씬4 시드
APPEARANCE = ("Young adult East Asian man wearing a white crewneck t-shirt, "
              "wearing a white short-sleeve t-shirt")
# 베이스라인 job 3ded2f29의 씬4 프롬프트(제품이 등장하지 않는 컷).
PROMPT = (
    "A wide shot, low angle capturing the momentum, shows a young man returning to "
    "the empty outdoor asphalt basketball court bathed in warm golden late-afternoon "
    "backlight, creating soft long shadows. He is powerfully sprinting forward, his "
    "arms outstretched as he grabs the worn basketball from the center of the court "
    "with an excited gesture - a rapid reaching motion, fingertips brushing against "
    "the textured surface. The camera moves dynamically alongside him"
)


async def main() -> int:
    work = tools.job_dir(JOB_ID) / "assembly"
    work.mkdir(parents=True, exist_ok=True)

    # 1) 배경 — 제품이 없으므로 놓일 면을 전경에 잡는 PRODUCT_PLACED_FRAMING도 쓰지 않는다.
    #    인물 외형만 주입해 Face-ID 씬과 같은 사람으로 보이게 한다.
    bg_prompt = f"{PROMPT}, the person looks like: {APPEARANCE}"
    print(f"[씬4] 배경 T2I seed={SEED}\n  {bg_prompt[:160]}...", flush=True)
    bg = Path(await tools.generate_t2i_image(JOB_ID, bg_prompt, seed=SEED,
                                             index=1000 + SCENE_ID))
    shutil.copyfile(bg, work / f"scene{SCENE_ID}_bg.png")
    print(f"[씬4] 배경: {work / f'scene{SCENE_ID}_bg.png'}", flush=True)

    # 2) I2V — 제품 합성(Pillow)·재통합(Kontext) 없이 바로 움직임만 입힌다.
    ref_name = f"assembled_scene{SCENE_ID}.png"
    shutil.copyfile(work / f"scene{SCENE_ID}_bg.png", tools.refs_dir(JOB_ID) / ref_name)
    clip = await tools.generate_i2v_fallback_clip(
        job_id=JOB_ID, scene_id=SCENE_ID, prompt=PROMPT, matched_image=ref_name,
        duration=3.0, seed=SEED, force_new=True)
    print(f"[씬4] 완료: {clip}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
