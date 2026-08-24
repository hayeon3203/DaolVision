"""UI 풀 플로우 E2E — "시나리오만" 모드(제품만 첨부, 인물 생성 없음) (2026-08-14).

사용자 결정: 인물 일관성 + 배경 + 제품 일관성을 동시에 유지하는 건 접는다. 대신 **다양한
사람이 제품을 쓰는** 광고로 간다. 인물 생성이 없으므로 참조는 제품 1장뿐이고, 씬마다
다른 사람이 나오는 게 정상이다. 마지막 씬은 인물 없이 제품 히어로샷.

probe_ui_full_flow_e2e.py와 다른 점은 입력뿐이다 — image_request가 없어 2-3(이미지 승인)
· 2-4(시나리오 입력) 게이트를 안 타고 곧장 1-4로 간다(graph._entry_router).

실행: cd langgraph && ./.venv/bin/python -u tests/probe_product_only_e2e.py
"""
import base64
import json
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

GATEWAY = "http://127.0.0.1:8700"
PRODUCT = (Path(__file__).resolve().parents[1] / "jobs" / "probe_bev_ad"
           / "assets" / "bottle_canonical_v3.png")

# 5문장 = 5씬(AGENT_SCENE_COUNT=5).
#
# 씬1~4 작성 규칙 — 인물 명사(_HUMAN_TEXT) + 손동작 어휘(_HAND_ACTION_TEXT)를 **둘 다**
# 넣는다. 인물 명사가 있어야 subject_type=human이 돼 조립 경로로 가고, 손동작이 있어야
# hand_held=True로 빈 그립 손 배경 + 얼굴 기준 크기 경로를 탄다. 손동작이 없으면 "놓인
# 씬" 경로로 빠지는데 그쪽 배경 프레이밍은 농구 시나리오에 맞춰 튜닝돼 있다.
#
# 인물은 씬마다 **다른 사람**이다 — 나이·성별·장소를 명시해 갈라놓는다. 인물 참조가
# 없으므로 얼굴은 T2I가 매번 새로 그린다(그게 이 모드의 의도).
#
# 씬5(히어로컷) — 인물 명사도 손동작 어휘도 **넣으면 안 된다**. "사람 없는"처럼 부정문에
# 인물 명사를 써도 정규식이 걸어 인물 씬으로 잡힌다. 제품 명사만 남긴다.
#
# 장소는 한국어로도 **명시적으로** 쓴다 — "체육관"만 쓰면 4B가 outdoor basketball court로
# 옮긴다(2026-08-14 job 8820932b 씬1 실측, 골든아워 조명 락과 겹쳐 실외가 됐다).
SCENARIO = (
    "운동을 마친 20대 여자가 실내 체육관에서 음료수를 들고 시원하게 마신다. "
    "사무실 책상 앞에 앉은 30대 남자가 음료수를 집어 들어 한 모금 마신다. "
    "도서관에서 공부하던 20대 남자가 고개를 들고 음료수를 쥐고 천천히 마신다. "
    "공사장에서 안전모를 쓴 40대 남자가 음료수를 들고 크게 들이켠다. "
    "빈 카페 테이블 위에 놓인 제품에 카메라가 천천히 다가가며 멈춘다."
)

POLL_SECONDS = 5.0
GATE_TIMEOUT = 3600


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
        # image_request 없음 = "시나리오만" 모드. 시나리오를 job 생성 시점에 바로 넣는다.
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

        out = Path(__file__).resolve().parents[1] / "jobs" / job_id / "product_only_flow.json"
        out.write_text(json.dumps({"job_id": job_id, "scenes": scenes},
                                  ensure_ascii=False, indent=2))
        print(f"\n덤프: {out}")
        print(f"클립 디렉토리: {Path(__file__).resolve().parents[1] / 'jobs' / job_id}")
        print("승인 게이트에서 멈춰 있음 — 편집/최종 렌더는 진행하지 않는다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
