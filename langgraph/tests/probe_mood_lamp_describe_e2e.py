"""프론트 describe 모드 그대로 재현 — 이미지 생성 → 시나리오 → 영상 (2026-08-23).

프론트 GatewayAgent "인물 생성 + 제품 첨부"(describe) 모드가 첨부를 비우고 제출하는
경로를 그대로 친다:
  POST /jobs {script_text:'', ref_images:[], image_request:'<제품 설명>'}
  → 2-3 이미지 승인({approved:true})
  → 2-4 시나리오 입력({script_text:'<5문장>'})
  → 1-4 씬 승인({approved:true})
  → 3-5 클립 완료 게이트에서 멈춤

payload는 전부 프론트 컴포넌트가 보내는 것과 동일하다(AgentImagePreview/
AgentScenePreview/GatewayAgent.jsx 확인). env 노브(조명·놓인배경·틴트)는 서버 기동 시
주입돼 있어야 한다.

실행: cd langgraph && ./.venv/bin/python -u tests/probe_mood_lamp_describe_e2e.py
"""
import json
import sys
import time
from pathlib import Path

import httpx

GATEWAY = "http://127.0.0.1:8700"

# 프론트 이미지 요청란에 사람이 치는 것과 같은 자연어. _image_query_system이 _PRODUCT_TEXT
# (무드등/램프)로 제품 규칙을 골라 흰 배경 스튜디오컷을 뽑는다.
IMAGE_REQUEST = "따뜻한 앰버빛으로 은은하게 빛나는 유리구 무드등, 짙은 월넛 원통 받침"

# 인물 씬(1~4): 손동작 어휘 금지(집어/들고/쥐고/마시/들이켜) — 걸리면 그립 경로로 감.
# 제품 명사 금지 — 배경이 램프를 또 그림. 마지막 씬만 제품 명사 + 인물 명사 없이.
SCENARIO = (
    "퇴근한 30대 여자가 어두운 원룸으로 천천히 걸어 들어와 협탁 쪽으로 고개를 돌린다. "
    "어두운 서재 책상 앞에 앉은 20대 남자가 노트북을 덮고 기지개를 켜며 창밖을 본다. "
    "은은한 주황빛이 감도는 거실 소파에 앉은 40대 남자가 책장을 천천히 넘긴다. "
    "어두운 아이 방에서 30대 여자가 침대 가장자리에 앉아 이불을 여며 준다. "
    "빈 침실 협탁 위에 놓인 제품에 카메라가 천천히 다가가며 멈춘다."
)

POLL = 5.0
TIMEOUT = 7200


def wait_for(client, job_id, want):
    started, last = time.time(), None
    while time.time() - started < TIMEOUT:
        try:
            st = client.get(f"{GATEWAY}/jobs/{job_id}/status").json()
        except httpx.HTTPError as e:
            print(f"  [{time.strftime('%H:%M:%S')}] 응답없음({type(e).__name__})")
            time.sleep(POLL); continue
        state = st.get("status")
        stamp = f"{state} phase={st.get('phase')}"
        ct = st.get("clips_total")
        if ct is not None:
            stamp += f" clips={st.get('clips_done')}/{ct}"
        if stamp != last:
            print(f"  [{time.strftime('%H:%M:%S')}] {stamp}"); last = stamp
        if state == "waiting_for_approval":
            cp = st.get("checkpoint") or {}
            name = cp.get("checkpoint", "")
            if name.startswith(want):
                return cp
            raise RuntimeError(f"예상 밖 게이트 {name} (기대 {want})")
        if state in ("error", "cancelled"):
            raise RuntimeError(f"job {state}: {st.get('error')}")
        time.sleep(POLL)
    raise TimeoutError(f"{want} 도달 실패")


def main():
    with httpx.Client(timeout=120.0) as c:
        print(f"gateway: {c.get(f'{GATEWAY}/health').json()}")
        # describe 모드: image_request만, ref_images/script_text 없음
        job_id = c.post(f"{GATEWAY}/jobs", json={
            "script_text": "", "ref_images": [], "image_request": IMAGE_REQUEST,
        }).json()["job_id"]
        print(f"job_id: {job_id}\n")

        print("[2-3] 제품 이미지 생성 → 승인 게이트")
        cp = wait_for(c, job_id, "2-3")
        for u in cp.get("gen_image_urls") or []:
            print(f"  생성이미지: {u}")
        print(f"  프롬프트: {(cp.get('image_queries') or [''])[0]}")
        c.post(f"{GATEWAY}/jobs/{job_id}/resume", json={"payload": {"approved": True}})

        print("\n[2-4] 시나리오 입력 게이트")
        wait_for(c, job_id, "2-4")
        c.post(f"{GATEWAY}/jobs/{job_id}/resume", json={"payload": {"script_text": SCENARIO}})

        print("\n[1-4] 씬분할 승인 게이트")
        cp = wait_for(c, job_id, "1-4")
        for s in cp.get("scenes") or []:
            print(f"  씬{s.get('id')} subject={s.get('subject_type')} role={s.get('image_role')} "
                  f"matched={s.get('matched_image')} face={s.get('face_id_ref')}")
            print(f"        {s.get('text')}")
        c.post(f"{GATEWAY}/jobs/{job_id}/resume", json={"payload": {"approved": True}})

        print("\n[3-5] 클립 생성 대기 (수십 분)")
        cp = wait_for(c, job_id, "3-5")
        scenes = cp.get("scenes") or []
        held = [s.get("id") for s in scenes if s.get("product_hand_held")]
        for s in scenes:
            print(f"  씬{s.get('id')} mode={s.get('mode')} hand_held={s.get('product_hand_held')} "
                  f"clip={s.get('clip_url')}")
        out = Path(__file__).resolve().parents[1] / "jobs" / job_id / "describe_flow.json"
        out.write_text(json.dumps({"job_id": job_id, "scenes": scenes}, ensure_ascii=False, indent=2))
        print(f"\n덤프: {out}")
        if held:
            print(f"경고: 손에 쥐는 씬 발생 {held}")
        print(f"클립 디렉토리: {out.parent}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
