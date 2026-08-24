"""UI 풀 플로우 E2E — :8700만 호출해 영상 생성까지 완주시킨다(2026-08-13).

지금까지의 검증은 전부 "Scene dict를 직접 구성해 노드에 넣는" 방식이었다. 여기서만
확인되는 것은 **LLM이 실제로 쓴 씬 프롬프트로도 같은 품질이 나오는가**다 — 오늘
하루 유일하게 손대지 않은 변수이고, 스파이크와 UI 결과가 다르다는 우려의 원인이다.

프론트가 하는 것과 동일한 순서로 게이트를 통과한다:
  1) 인물 생성 요청 + 제품 사진 첨부로 job 시작
  2) 2-3 이미지 승인
  3) 2-4 시나리오 입력
  4) 1-4 씬분할 승인(분할 결과와 라우팅을 덤프)
  5) 3-5 클립 승인 게이트까지 대기 → 클립 URL과 씬별 mode 덤프

실행: cd langgraph && ./.venv/bin/python tests/probe_ui_full_flow_e2e.py
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

IMAGE_REQUEST = "20대 한국인 남자, 짧은 검은 머리, 흰 반팔 티셔츠, 정면 얼굴, 사실적인 사진"
# AGENT_SCENE_COUNT=5이라 5문장. 제품은 2번째 문장부터 등장(씬1은 순수 인물 생성 경로).
SCENARIO = (
    # 점프슛 → 달리기(사용자 지시 2026-08-13). 점프는 도약·체공·착지가 한 컷에 섞여
    # 동작이 복잡한 반면 달리기는 이동 궤적이 단순해 LTX가 안정적으로 그린다
    # (스파이크 씬2도 달리기였고 1발에 성공했다).
    "한 남자가 농구장에서 땀 흘리며 공을 드리블하며 코트를 가로질러 달린다. "
    "그는 농구 코트 한쪽 벤치에 놓인 음료수를 향해 달려간다. "
    "벤치 앞에 멈춰 음료수를 집어 들고 시원하게 들이켠다. "
    # 씬4. 원래 "다시 코트로 돌아가 공을 잡고 힘차게 달려나간다"였는데 씬1(정면에서
    # 드리블하며 달림)과 동작·구도가 겹쳐 clip4가 clip1의 재탕이 됐다(2026-08-14
    # probe_assembly_235 씬4 확인). 뒷모습 + 슛으로 갈라놓는다. 씬4는 이제 조립
    # 경로(PERSON_ASSEMBLY)라 정면 강제 문구(PRODUCT_PLACED_FRAMING)를 안 붙이므로
    # "등을 보이며"가 실제로 배경에 반영된다.
    # "음료수"를 이 문장에 쓰면 안 된다 — 제품 forward-fill(_PRODUCT_TEXT)이 다시 켜져
    # 씬4에 병이 합성된다. 마신 건 씬3에서 이미 끝났으므로 "벤치를 뒤로 하고"로만
    # 이어 붙인다(벤치는 제품 명사가 아니라 상속이 안 켜진다).
    # 동작은 **하나만** 넣는다. "달려 들어가 + 슛을 쏜다"처럼 둘을 넣으면 T2I가 마지막
    # 동작(슛)만 그리고, 그게 I2V 첫 프레임이 돼 달리기가 통째로 사라진다
    # (2026-08-14 job 1559ee49 씬4 실측 — 제자리에서 팔만 올림).
    "남자는 벤치를 뒤로 하고 카메라에 등을 보이며 다시 코트 안쪽으로 힘차게 달려 들어간다. "
    # 마무리 히어로컷. 인물 명사·손동작 어휘가 들어가면 인물 상속이 켜져 얼굴 참조가
    # 붙고 배경에 사람이 그려진다 — 제품 명사만 남긴다.
    "빈 농구 코트를 배경으로 벤치 위 제품에 카메라가 천천히 다가가며 멈춘다."
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
            # 게이트웨이가 잠깐 끊겨도(재기동 등) 폴링이 죽지 않게 한다. 체크포인터가
            # SQLite라 job 상태는 프로세스 재시작에도 남는다.
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
            "script_text": "", "ref_images": [data_uri], "image_request": IMAGE_REQUEST,
        }).json()["job_id"]
        print(f"job_id: {job_id}\n")

        print("[1] 이미지 승인 게이트(2-3)")
        cp = wait_for(client, job_id, "2-3")
        print(f"  생성 이미지: {cp.get('gen_image_urls')}")
        print(f"  프롬프트: {cp.get('image_query')}")
        client.post(f"{GATEWAY}/jobs/{job_id}/resume", json={"payload": {"approved": True}})

        print("\n[2] 시나리오 입력 게이트(2-4)")
        cp = wait_for(client, job_id, "2-4")
        print(f"  참조: {cp.get('ref_images')}")
        client.post(f"{GATEWAY}/jobs/{job_id}/resume",
                    json={"payload": {"script_text": SCENARIO}})

        print("\n[3] 씬분할 승인 게이트(1-4)")
        cp = wait_for(client, job_id, "1-4")
        for s in cp.get("scenes") or []:
            print(f"  씬{s.get('id')} subject={s.get('subject_type')} "
                  f"role={s.get('image_role')} matched={s.get('matched_image')} "
                  f"face={s.get('face_id_ref')}")
            print(f"        {s.get('text')}")
        client.post(f"{GATEWAY}/jobs/{job_id}/resume", json={"payload": {"approved": True}})

        print("\n[4] 클립 생성 → 승인 게이트(3-5) 대기 (수십 분)")
        cp = wait_for(client, job_id, "3-5")

        print("\n=== 씬별 생성 결과 ===")
        scenes = cp.get("scenes") or []
        for s in scenes:
            print(f"  씬{s.get('id')} mode={s.get('mode')} "
                  f"hand_held={s.get('product_hand_held')} clip={s.get('clip_url')}")
            print(f"        prompt: {(s.get('prompt') or '')[:160]}")

        out = Path(__file__).resolve().parents[1] / "jobs" / job_id / "ui_full_flow.json"
        out.write_text(json.dumps({"job_id": job_id, "scenes": scenes},
                                  ensure_ascii=False, indent=2))
        print(f"\n덤프: {out}")
        print(f"클립 디렉토리: {Path(__file__).resolve().parents[1] / 'jobs' / job_id}")
        print("승인 게이트에서 멈춰 있음 — 편집/최종 렌더는 진행하지 않는다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
