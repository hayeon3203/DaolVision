"""그립 좌표 clamp 회귀 테스트 (clip3 재현성).

이전 동작: 손 검출이 조금이라도 어긋나면(마시는 자세라 손이 입가로 올라감, 팔이 몸통과
붙어 한 덩어리) locate_grip이 None을 돌려주고 호출부가 **스파이크 배경 좌표계의 고정
픽셀값**으로 폴백했다. 배경이 새로 생성되는 프로덕션에서는 그 좌표가 맞을 이유가 없어
병이 가슴 한복판·허공에 붙었다(job 3ded2f29 clip3: 병이 손이 아닌 가슴 옆).

지금 동작: 좌표를 얼굴 기준 해부학 밴드(턱 아래 가슴 높이, 얼굴 폭 좌우 한 뼘)로
clamp하고, 손을 아예 못 찾으면 얼굴에서 기하 추정한다. 최고값은 아니어도 최악이 없다.

    cd langgraph && ./.venv/bin/python tests/test_grip_clamp.py
"""
import sys
from io import BytesIO
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tools

W, H = 1392, 752
SKIN = (200, 140, 90)      # r-b=110 > 40, r=200 > 90 → 피부로 검출됨
SHIRT = (235, 235, 235)    # 무채색 → 피부 아님
BG = (120, 120, 120)
FACE_BOX = (600, 100, 750, 300)      # x0, y0, x1, y1 — face_w=150, face_h=200


def _frame(*skin_boxes: tuple[int, int, int, int]):
    """인물(마스크) 안에 피부 덩어리들을 배치한 합성 프레임을 만든다."""
    arr = np.full((H, W, 3), BG, np.uint8)
    mask = np.zeros((H, W), bool)
    # 인물 실루엣: 얼굴~허리를 덮는 큰 사각형(옷은 무채색이라 피부로 안 잡힌다)
    arr[80:700, 520:960] = SHIRT
    mask[80:700, 520:960] = True
    for x0, y0, x1, y1 in skin_boxes:
        arr[y0:y1, x0:x1] = SKIN
        mask[y0:y1, x0:x1] = True
    buf = BytesIO()
    Image.fromarray(arr).save(buf, "PNG")
    return buf.getvalue(), mask


def test_detected_hand_inside_band_is_used_as_is():
    """정상 검출(가슴 높이에 든 손)은 그대로 쓰고 손가락 복원 상자도 유지한다."""
    png, mask = _frame(FACE_BOX, (800, 400, 900, 650))
    grip = tools.locate_grip(png, mask)
    assert grip and grip["source"] == "hand", grip
    assert grip["occlusion_box"] is not None, "정상 검출인데 손가락 복원을 버렸다"
    # 그립 입구 = 손 bbox 우측 끝(≈900px), 손 상단 40% 중심(≈450px)
    assert 0.60 < grip["center_x_ratio"] < 0.68, grip["center_x_ratio"]
    assert 0.55 < grip["center_y_ratio"] < 0.65, grip["center_y_ratio"]


def test_hand_at_mouth_is_clamped_not_rejected():
    """마시는 자세 배경 — 손이 턱 옆으로 올라간 경우. 예전엔 None(고정값 폴백)이었다."""
    png, mask = _frame(FACE_BOX, (760, 120, 850, 320))
    grip = tools.locate_grip(png, mask)
    assert grip is not None, "기각돼 고정 픽셀 폴백으로 떨어졌다"
    assert grip["source"] == "clamped", grip["source"]
    # 턱(y=300) 아래로 끌려와야 한다 — 귀·입가에 병이 붙는 게 이전 실패 모드였다.
    assert grip["center_y_ratio"] * H >= 300, grip["center_y_ratio"] * H
    assert grip["occlusion_box"] is None, "당겨진 좌표의 손 상자를 그대로 쓰면 안 된다"


def test_no_arm_component_falls_back_to_face_geometry():
    """팔이 몸통과 붙어 한 덩어리 — 얼굴 기준 추정. 고정 픽셀값을 쓰면 안 된다."""
    png, mask = _frame(FACE_BOX)
    grip = tools.locate_grip(png, mask)
    assert grip and grip["source"] == "estimated", grip
    assert grip["occlusion_box"] is None
    cx, cy = grip["center_x_ratio"] * W, grip["center_y_ratio"] * H
    fx1, fy1 = FACE_BOX[2], FACE_BOX[3]
    assert fx1 <= cx <= fx1 + 180, f"추정 x가 얼굴에서 너무 멀다: {cx}"
    assert fy1 < cy < fy1 + 280, f"추정 y가 가슴 높이가 아니다: {cy}"


def test_coordinates_follow_the_face_not_the_spike_frame():
    """clamp의 요지 — 배경이 바뀌어 인물이 이동하면 좌표도 같이 움직여야 한다."""
    shifted = tuple(v + (300 if i % 2 == 0 else 0) for i, v in enumerate(FACE_BOX))
    a = tools.locate_grip(*_frame(FACE_BOX))
    b = tools.locate_grip(*_frame(shifted))
    assert b["center_x_ratio"] - a["center_x_ratio"] > 0.18, (a, b)


def test_no_person_returns_none():
    """피부가 아예 없으면 호출부의 고정 기본값으로 넘긴다(옛 동작 유지)."""
    png, mask = _frame()
    assert tools.locate_grip(png, mask) is None


def test_warm_coloured_garment_is_not_skin():
    """따뜻한 색 옷이 피부로 걸리면 안 된다.

    2026-08-14 probe_person_ref 씬1: 핑크 상의 rgb(247,122,172)가 `(r-b)>40` 만 보던
    옛 판정을 통과해 얼굴·팔·배·상의가 한 덩어리가 됐다. 살색이 프레임의 22%를 덮으면서
    연결요소 분리가 무너져 face_box가 8x0px 파편으로 잡혔고, 제품 폭이 얼굴폭×0.5 = 4px로
    계산돼 병이 화면에서 사라졌다. 핑크는 g < b라 r>g>b 조건에서 걸러진다.
    """
    png, mask = _frame(FACE_BOX, (800, 400, 900, 650))
    arr = np.array(Image.open(BytesIO(png)).convert("RGB"))
    arr[350:700, 560:780] = (247, 122, 172)      # 핑크 상의로 몸통만 덮는다(팔 x800~900은 남김)
    buf = BytesIO()
    Image.fromarray(arr).save(buf, "PNG")
    grip = tools.locate_grip(buf.getvalue(), mask)
    assert grip and grip["source"] == "hand", grip
    # 얼굴이 파편이 아니라 실제 얼굴로 잡혀야 한다(FACE_BOX 폭 150 / W)
    assert grip["face_w_ratio"] > 0.08, f"상의가 피부로 걸려 얼굴 검출이 깨졌다: {grip}"


def test_tiny_fragment_above_the_face_is_not_mistaken_for_it():
    """프레임 맨 위의 살색 파편이 얼굴로 뽑히면 안 된다.

    2026-08-14 probe_person_ref 씬1: 얼굴 2662px·손 1709px 사이에 정수리 파편 65px이
    상위 3개 후보에 끼었고, "가장 위에서 시작하는 것 = 얼굴" 규칙이 그 파편을 골랐다.
    face_w가 0.046(64px)으로 잡히면서 제품 폭이 얼굴폭×0.5 = 32px이 됐다.
    """
    fragment = (700, 20, 740, 40)               # 얼굴보다 위에 있는 작은 파편
    png, mask = _frame(FACE_BOX, (800, 400, 900, 650), fragment)
    grip = tools.locate_grip(png, mask)
    assert grip, "검출 자체가 실패했다"
    fw = grip["face_w_ratio"] * W
    assert fw > 100, f"파편을 얼굴로 골랐다: face_box={grip['face_box']} 폭={fw:.0f}"
    assert grip["face_box"][1] >= FACE_BOX[1] - 20, grip["face_box"]


def test_hand_across_the_body_wins_over_bigger_hanging_arm():
    """양팔이 다 드러난 경우 크기로 고르면 안 된다.

    같은 job 실측: 쥔 팔 2606px, 늘어뜨린 팔 2607px로 1픽셀 차이가 나서 max()가
    늘어뜨린 쪽을 골랐고 병이 반대편 어깨에 붙었다. 배경 프롬프트가 지시하는
    "forearm angled up across the body"를 기준으로 삼는다 — 쥔 팔은 얼굴 x범위와 겹친다.
    """
    hanging = (980, 380, 1090, 700)             # 몸 바깥, 더 큼(110x320)
    across = (560, 380, 690, 640)               # 얼굴 x범위(600~750)와 겹침, 더 작음(130x260)
    assert (hanging[2] - hanging[0]) * (hanging[3] - hanging[1]) > \
           (across[2] - across[0]) * (across[3] - across[1])
    png, mask = _frame(FACE_BOX, hanging, across)
    grip = tools.locate_grip(png, mask)
    assert grip and grip["source"] == "hand", grip
    hx1 = grip["hand_box"][2]
    assert hx1 <= 760, f"몸 바깥 팔을 골랐다: hand_box={grip['hand_box']}"


def main() -> None:
    test_detected_hand_inside_band_is_used_as_is()
    test_hand_at_mouth_is_clamped_not_rejected()
    test_no_arm_component_falls_back_to_face_geometry()
    test_coordinates_follow_the_face_not_the_spike_frame()
    test_no_person_returns_none()
    test_warm_coloured_garment_is_not_skin()
    test_tiny_fragment_above_the_face_is_not_mistaken_for_it()
    test_hand_across_the_body_wins_over_bigger_hanging_arm()
    print("test_grip_clamp: all passed")


if __name__ == "__main__":
    main()
