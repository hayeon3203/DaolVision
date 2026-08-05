"""ponytail: 1회성 수동 검증 스크립트. 실 사진으로 LTX_FACEID E2E를 :8700 API로 돌려
눈으로 확인하기 위함 — 자동화 테스트 아님, 완료 후 삭제 예정."""
import base64
import sys
import time

import requests

BASE = "http://127.0.0.1:8700"
IMG = "/home/admin/DaolVision/건호군.jpg"

with open(IMG, "rb") as f:
    b64 = base64.b64encode(f.read()).decode()

resp = requests.post(f"{BASE}/jobs", json={
    # 3.2 스파이크와 동일한 4개의 뚜렷이 구별되는 사건 — node_split_scenes가 내용을
    # 창작하지 않고 그대로 4씬에 매핑하므로(원문 보존 규칙), 사건 수가 부족한 한 문장
    # 스크립트처럼 같은 순간이 반복되는 문제가 안 생긴다.
    "script_text": (
        "한 우주비행사가 노을 지는 발사대에서 로켓을 타고 이륙한다. "
        "우주로 나가 무중력 상태에서 우주유영을 한다. "
        "낯선 외계 행성에 착륙해 주변을 탐사한다. "
        "임무를 마치고 지구로 귀환한다."
    ),
    "ref_images": [f"data:image/jpeg;base64,{b64}"],
})
resp.raise_for_status()
job_id = resp.json()["job_id"]
print(f"job_id={job_id}", flush=True)

deadline = time.time() + 1800
while time.time() < deadline:
    st = requests.get(f"{BASE}/jobs/{job_id}/status").json()
    status = st.get("status")
    print(f"[{time.strftime('%H:%M:%S')}] status={status} phase={st.get('phase')}", flush=True)
    if status == "waiting_for_approval":
        cp = st["checkpoint"]["checkpoint"]
        if cp.startswith("1-4"):
            payload = {"approved": True}
        elif cp.startswith("3-5"):
            payload = {"action": "approve_all"}
        else:
            print(f"FAIL: 알 수 없는 체크포인트 {cp}")
            sys.exit(1)
        print(f"  approve {cp} -> {payload}", flush=True)
        requests.post(f"{BASE}/jobs/{job_id}/resume", json={"payload": payload})
    elif status == "done":
        print(f"DONE: {st.get('final_video_url')}", flush=True)
        sys.exit(0)
    elif status == "error":
        print(f"FAIL: {st.get('error')}", flush=True)
        sys.exit(1)
    time.sleep(5)

print("FAIL: timeout", flush=True)
sys.exit(1)
