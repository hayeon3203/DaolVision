"""6.22 E2E — "얼굴 생성 + 제품 첨부 + 시나리오" 조합을 실제 :8700으로 완주시킨다.

여기서 확인하려는 건 코드 배선이 아니라(그건 test_gen_plus_upload_refs.py가 커버)
**LLM이 참조 2장(생성 인물 + 첨부 제품)을 받았을 때 실제로 씬을 어떻게 나누고
무엇을 매칭하는지**다. 이게 6.23(제품 씬 조립 노드)의 입력 형태를 정한다.

씬분할 게이트(1-4)까지만 진행하고 그 결과를 덤프한 뒤 job을 취소한다 — 클립 생성은
비싸고 여기서 볼 게 없다.

전제: :8700(anim-agent)이 **수정된 코드로** 떠 있어야 한다. 구 코드면 라우터가
첨부 이미지를 보고 M2 분기를 스킵해 이 시나리오 자체가 성립하지 않는다.

    cd langgraph && ./.venv/bin/python tests/probe_gen_plus_upload_e2e.py
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
SCENARIO = (
    "한 남자가 농구장에서 땀 흘리며 드리블하고 점프슛을 쏜다. "
    "숨을 고르며 코트 한쪽 벤치에 놓인 음료수를 향해 달려간다. "
    "벤치 앞에 멈춰 음료수를 집어 든다. "
    "고개를 들고 시원하게 음료수를 들이켠다."
)

POLL_SECONDS = 3.0
TIMEOUT_SECONDS = 900


def wait_for_checkpoint(client: httpx.Client, job_id: str, want: str) -> dict:
    started = time.time()
    last = None
    while time.time() - started < TIMEOUT_SECONDS:
        status = client.get(f"{GATEWAY}/jobs/{job_id}/status").json()
        state = status.get("status")
        if state != last:
            print(f"  status={state} phase={status.get('phase')}")
            last = state
        if state == "waiting_for_approval":
            checkpoint = status.get("checkpoint") or {}
            name = checkpoint.get("checkpoint", "")
            if name.startswith(want):
                return checkpoint
            raise RuntimeError(f"예상과 다른 게이트: {name} (기대 {want})\n{json.dumps(checkpoint, ensure_ascii=False)[:600]}")
        if state in ("error", "cancelled"):
            raise RuntimeError(f"job {state}: {status.get('error')}")
        time.sleep(POLL_SECONDS)
    raise TimeoutError(f"{want} 게이트에 도달하지 못함")


def main() -> int:
    if not PRODUCT.exists():
        print(f"제품 이미지 없음: {PRODUCT}")
        return 1
    data_uri = "data:image/png;base64," + base64.b64encode(PRODUCT.read_bytes()).decode()

    with httpx.Client(timeout=60.0) as client:
        health = client.get(f"{GATEWAY}/health").json()
        print(f"gateway: {health}")

        start = client.post(f"{GATEWAY}/jobs", json={
            "script_text": "",
            "ref_images": [data_uri],      # 제품 첨부
            "image_request": IMAGE_REQUEST,  # 인물 생성
        })
        start.raise_for_status()
        job_id = start.json()["job_id"]
        print(f"job_id: {job_id}")

        print("\n[1] 이미지 승인 게이트(2-3) 대기")
        cp = wait_for_checkpoint(client, job_id, "2-3")
        print(f"  생성 이미지: {cp.get('gen_image_urls') or cp.get('gen_image_url')}")
        print(f"  생성 프롬프트: {cp.get('image_query')}")
        client.post(f"{GATEWAY}/jobs/{job_id}/resume", json={"payload": {"approved": True}}).raise_for_status()

        print("\n[2] 시나리오 입력 게이트(2-4) 대기")
        cp = wait_for_checkpoint(client, job_id, "2-4")
        print(f"  게이트가 보고한 ref_images: {cp.get('ref_images')}")
        refs = cp.get("ref_images") or []
        if len(refs) < 2:
            print("  !! 참조가 2장이 아니다 — 첨부분이 소실됐거나 병합이 안 됨")
        client.post(f"{GATEWAY}/jobs/{job_id}/resume",
                    json={"payload": {"script_text": SCENARIO}}).raise_for_status()

        print("\n[3] 씬분할 승인 게이트(1-4) 대기 (캡션 + LLM 씬분할, 수 분 소요)")
        cp = wait_for_checkpoint(client, job_id, "1-4")

        print("\n=== 씬분할 결과 ===")
        for scene in cp.get("scenes") or []:
            print(f"  씬{scene.get('id')}  subject={scene.get('subject_type'):9s} "
                  f"role={str(scene.get('image_role')):15s} matched={scene.get('matched_image')}")
            print(f"        text: {scene.get('text')}")

        state = client.get(f"{GATEWAY}/jobs/{job_id}/state").json()
        vals = state.get("values") or state
        print("\n=== 참조 캡션 ===")
        for name, caption in (vals.get("ref_captions") or {}).items():
            print(f"  {name}: {caption}")

        out = Path(__file__).resolve().parents[1] / "jobs" / job_id / "e2e_scene_split.json"
        out.write_text(json.dumps({
            "job_id": job_id,
            "ref_images": vals.get("ref_images"),
            "ref_captions": vals.get("ref_captions"),
            "scenes": cp.get("scenes"),
        }, ensure_ascii=False, indent=2))
        print(f"\n덤프: {out}")

        client.post(f"{GATEWAY}/jobs/{job_id}/cancel")
        print("job 취소함(클립 생성은 이 검증 범위 밖)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
