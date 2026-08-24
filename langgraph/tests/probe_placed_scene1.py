"""접촉 없는 "놓인 구도"로 씬1을 만든다 (2026-08-14).

쥔 구도가 요구하는 세 가지(빈 그립 손 자세 생성 / 손 위치 검출 / 영상에서 손과 병이
함께 이동)를 전부 없애는 대안이다. 제품은 전경 평면에 크게 놓고 인물만 중경에서
움직인다. 카메라를 고정하면 병이 움직일 이유가 없어 **첫 프레임 수렴(0~1초 합성 티)도
발생하지 않는다** — 쥔 구도에서는 스파이크 씬2가 트림으로 회피했던 문제다.

프로덕션 함수(`tools.generate_product_scene_clip`)를 그대로 호출하되 상수 2개를 이
프로브에서만 덮어쓴다. 둘 다 농구 시나리오 한 장에 맞춰진 값이라 다른 장소에 못 쓴다 —
이 구도를 채택하면 프로덕션에서 파라미터화해야 한다:
  - PRODUCT_PLACED_BG_PROMPT: "벤치를 향해 카메라로 달려온다"가 박혀 있다
  - PRODUCT_PLACED_RATIOS: 폭 0.15 = 소품 크기. 여기서는 제품이 주인공이라 키운다

실행: cd langgraph && ./.venv/bin/python -u tests/probe_placed_scene1.py
산출: jobs/probe_placed/assembly/scene1_{bg,flat,recomposed}.png, clip1.mp4
"""
import asyncio
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import nodes  # noqa: E402
import tools  # noqa: E402

JOB_ID = "probe_placed"
ROOT = Path(__file__).resolve().parent.parent
PERSON_SRC = ROOT / "jobs" / "probe_person_ref" / "refs" / "person_1.png"
PRODUCT_SRC = ROOT / "jobs" / "probe_bev_ad" / "assets" / "bottle_canonical_v3.png"

SETTING = "an indoor gymnasium with mirrored walls and fitness equipment"
LIGHTING = "soft warm key light, bright clear exposure, gentle natural shadows"
PERSON = "a woman in her 20s who has just finished a workout"

# 인물 동작에는 **제품이 등장하지 않는다**. 문장의 의미가 음료를 요구하면 배경 T2I/Kontext가
# 자기 나름의 병을 그려 결과에 병이 둘이 된다(2026-08-13 실측). 접촉이 없으므로 동작에서
# 제품을 빼도 광고가 성립한다 — "마시는" 인상은 편집(제품 컷 + 반응 컷)이 만든다.
ACTION = ("she wipes her face with a small towel and walks a few steps forward, "
          "looking relaxed and satisfied after training")

# 놓인 구도 배경: 인물은 중경 오른쪽, 전경 왼쪽 아래에 **빈 평면**. 제품은 다음 단계에서
# 얹으므로 여기서 그리면 안 된다.
PLACED_BG = (
    f"{tools.PERSON_BG_IDENTITY}Re-render them as a cinematic wide commercial shot: "
    "the person stands several steps away in the mid-ground on the right side of the "
    f"frame, their whole upper body visible and in focus. {ACTION}. "
    "In the lower-left foreground, close to the camera, a bare empty flat surface — a "
    "bench top — juts into frame, completely empty with nothing resting on it, large "
    "and sharply lit. Photorealistic."
)
# 제품이 주인공이라 크게 놓는다. 폭 0.22 = 282x566px(프레임 높이의 80%), 왼쪽 1/3.
PLACED_RATIOS = (0.22, 0.30, 0.97)


async def main() -> int:
    refs = tools.refs_dir(JOB_ID)
    refs.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(PRODUCT_SRC, refs / "img_0.png")
    shutil.copyfile(PERSON_SRC, refs / "person_1.png")

    tools.PRODUCT_PLACED_BG_PROMPT = PLACED_BG
    tools.PRODUCT_PLACED_RATIOS = PLACED_RATIOS
    print(f"[놓인구도] 제품 폭 {PLACED_RATIOS[0]} "
          f"({PLACED_RATIOS[0]*1280:.0f}x{PLACED_RATIOS[0]*1280*2.01:.0f}px)", flush=True)

    clip = await tools.generate_product_scene_clip(
        JOB_ID, 1,
        # 배경 단계와 I2V 단계는 제품에 대한 요구가 **정반대**다.
        #   배경(Kontext): 제품을 언급하면 안 된다 — 자기 나름의 병을 그려 둘이 된다
        #   I2V: 제품을 언급해야 한다 — 안 하면 합성한 병을 지운다
        # 이 프롬프트는 I2V로만 간다(배경은 PRODUCT_PLACED_BG_PROMPT를 쓴다). 첫 실행에서
        # 제품 언급을 빼고 드리프트 억제 negative만 걸었더니 LTX가 12프레임 만에 병을
        # 통째로 지웠다 — negative는 "병 비슷한 건 지워라"인데 positive에 지킬 대상이
        # 없었기 때문이다. 프로덕션은 씬 문장에 제품이 들어 있어 이 문제가 안 생긴다.
        prompt=(f"A cinematic wide commercial shot in {SETTING}. In the foreground a "
                "clear plastic PET sports drink bottle with a blue-to-orange gradient "
                "label and an orange cap stands on the bench top, completely still and "
                f"unchanged, staying exactly where it is. Behind it, {ACTION}"),
        product_ref="img_0.png",
        face_ref="person_1.png",
        hero=False,
        hand_held=False,
        duration=3.0,
        seed=nodes.scene_seed(JOB_ID, 1),
        # 프로덕션과 같은 제품 드리프트 억제 negative(쥔 구도 프로브에서 빠뜨렸던 것).
        negative_prompt=nodes._negative_prompt_for_i2v_scene(
            'Plastic bottle containing liquid labeled "Urtage"'),
        scene_context=f"{SETTING}, {LIGHTING}",
        person_appearance=PERSON,
        force_new=True,
    )
    work = tools.job_dir(JOB_ID) / "assembly"
    print(f"완료: {clip}", flush=True)
    for name in ("scene1_bg.png", "scene1_flat.png", "scene1_recomposed.png"):
        if (work / name).exists():
            print(f"  {work / name}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
