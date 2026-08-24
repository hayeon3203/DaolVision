"""UI 풀 플로우 E2E — 무드등 광고("얼굴과 제품이 붙지 않는" 시나리오) (2026-08-23).

**왜 이 시나리오인가**: 얼굴·배경·제품 일관성을 동시에 잡기 어려운 원인 중 가장 취약한
고리가 `locate_grip`(살색 연결요소로 손을 찾는 휴리스틱)이다. 그건 인물이 제품을 **손에
쥐는** 씬에서만 돈다. 제품을 협탁 위에 놓아 인물과 떼어놓으면 그 경로 자체를 안 탄다 —
`hand_held=False`(놓인 씬) + 마무리 히어로컷만 남는다.

입력은 probe_product_only_e2e.py와 같은 "시나리오만" 모드다(`image_request` 없이
script_text + 제품 1장). 제품은 tests/make_mood_lamp_asset.py가 뽑은 투명 배경 컷아웃.

실행: cd langgraph && ./.venv/bin/python -u tests/probe_mood_lamp_e2e.py
"""
import base64
import json
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

GATEWAY = "http://127.0.0.1:8700"
PRODUCT = (Path(__file__).resolve().parents[1] / "jobs" / "probe_mood_lamp"
           / "assets" / "lamp_canonical.png")

# 5문장 = 5씬(AGENT_SCENE_COUNT=5).
#
# 씬1~4 — 인물 명사는 넣고 **손동작 어휘(_HAND_ACTION_TEXT)는 절대 넣지 않는다**.
# 손동작이 걸리면 hand_held=True로 그립 경로를 타고, 그게 바로 피하려는 경로다.
# 금지 어휘: 집어/들고/쥐고/든/마시/들이켜/한 모금/입에 대…
#
# 씬 문장에 **제품 명사를 넣지 않는다**. 놓인 씬 배경(Kontext)에는 씬 문장이 아니라
# LLM이 뽑은 setting·lighting만 들어가는데, 거기에 "무드등이 켜진 방"이 실리면 배경이
# 자기 나름의 램프를 그리고 그 앞에 우리 제품이 또 합성된다(램프 2개). 방의 분위기는
# 빛으로만 서술한다.
#
# 씬5(히어로컷) — 인물 명사도 손동작도 없이 제품 명사만. "제품"은 _PRODUCT_TEXT와
# _NONHUMAN_TEXT에 둘 다 있어 인물 상속이 끊기고 subject_type=nonhuman이 된다.
#
# 장소는 한국어로도 명시적으로 쓴다(4B가 모호한 장소를 환각·오역한다).
SCENARIO = (
    "퇴근한 30대 여자가 어두운 원룸으로 천천히 걸어 들어와 협탁 쪽으로 고개를 돌린다. "
    "어두운 서재 책상 앞에 앉은 20대 남자가 노트북을 덮고 기지개를 켜며 창밖을 본다. "
    "은은한 주황빛이 감도는 거실 소파에 앉은 40대 남자가 책장을 천천히 넘긴다. "
    "어두운 아이 방에서 30대 여자가 침대 가장자리에 앉아 이불을 여며 준다. "
    "빈 침실 협탁 위에 놓인 제품에 카메라가 천천히 다가가며 멈춘다."
)

POLL_SECONDS = 5.0
GATE_TIMEOUT = 7200


def wait_for(client: httpx.Client, job_id: str, want: str) -> dict:
    started = time.time()
    last = None
    while time.time() - started < GATE_TIMEOUT:
        try:
            status = client.get(f"{GATEWAY}/jobs/{job_id}/status").json()
        except httpx.HTTPError as exc:
            print(f"  [{time.strftime('%H:%M:%S')}] 게이트웨이 응답 없음({type(exc).__name__}) — 재시도")
            time.sleep(POLL_SECONDS)
            continue
        state = status.get("status")
        stamp = f"{state} phase={status.get('phase')}"
        clips = status.get("clips_total")
        if clips is not None:
            stamp += f" clips={status.get('clips_done')}/{clips}"
        if stamp != last:
            print(f"  [{time.strftime('%H:%M:%S')}] {stamp}")
            last = stamp
        if state == "waiting_for_approval":
            checkpoint = status.get("checkpoint") or {}
            name = checkpoint.get("checkpoint", "")
            if name.startswith(want):
                return checkpoint
            raise RuntimeError(f"예상과 다른 게이트: {name} (기대 {want})")
        if state in ("error", "cancelled"):
            raise RuntimeError(f"job {state}: {status.get('error')}")
        time.sleep(POLL_SECONDS)
    raise TimeoutError(f"{want} 게이트 도달 실패")


def main() -> int:
    data_uri = "data:image/png;base64," + base64.b64encode(PRODUCT.read_bytes()).decode()
    with httpx.Client(timeout=120.0) as client:
        print(f"gateway: {client.get(f'{GATEWAY}/health').json()}")
        job_id = client.post(f"{GATEWAY}/jobs", json={
            "script_text": SCENARIO, "ref_images": [data_uri],
        }).json()["job_id"]
        print(f"job_id: {job_id}\n")

        print("[1] 씬분할 승인 게이트(1-4)")
        cp = wait_for(client, job_id, "1-4")
        for s in cp.get("scenes") or []:
            print(f"  씬{s.get('id')} subject={s.get('subject_type')} "
                  f"role={s.get('image_role')} matched={s.get('matched_image')} "
                  f"face={s.get('face_id_ref')}")
            print(f"        {s.get('text')}")
        client.post(f"{GATEWAY}/jobs/{job_id}/resume", json={"payload": {"approved": True}})

        print("\n[2] 클립 생성 → 승인 게이트(3-5) 대기 (수십 분)")
        cp = wait_for(client, job_id, "3-5")

        print("\n=== 씬별 생성 결과 ===")
        scenes = cp.get("scenes") or []
        for s in scenes:
            print(f"  씬{s.get('id')} mode={s.get('mode')} "
                  f"hand_held={s.get('product_hand_held')} clip={s.get('clip_url')}")
            print(f"        prompt: {(s.get('prompt') or '')[:160]}")

        # 이 프로브의 존재 이유 — 그립 경로를 한 씬도 안 타야 한다.
        held = [s.get("id") for s in scenes if s.get("product_hand_held")]
        assert not held, f"손에 쥐는 씬이 생겼다(씬 {held}) — 시나리오에 손동작 어휘가 섞였다"

        out = Path(__file__).resolve().parents[1] / "jobs" / job_id / "mood_lamp_flow.json"
        out.write_text(json.dumps({"job_id": job_id, "scenes": scenes},
                                  ensure_ascii=False, indent=2))
        print(f"\n덤프: {out}")
        print(f"클립 디렉토리: {Path(__file__).resolve().parents[1] / 'jobs' / job_id}")
        print("승인 게이트에서 멈춰 있음 — 편집/최종 렌더는 진행하지 않는다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
