"""ponytail: 1회성 수동 검증 스크립트. no-ref 모드(참조 이미지 없이 시나리오만)를
UI가 실제로 때리는 :8700 경로 그대로 돌려 속도와 산출물을 확인한다.

'스모크는 통과인데 UI는 품질 저하' 이슈 재발 방지가 목적이라, tools.py 함수를 직접
부르지 않고 GatewayAgent.jsx와 완전히 같은 계약으로만 통신한다:
  POST /jobs                {script_text, ref_images, image_request}
  GET  /jobs/{id}/status    폴링
  POST /jobs/{id}/resume    {payload: {approved: true}}          (checkpoint 1-4)
  POST /jobs/{id}/resume    {payload: {action: "approve_all"}}   (checkpoint 3-5)
서버는 반드시 run_agent.sh로 띄울 것 — AGENT_VIDEO_PRESET=fast(832x480),
AGENT_LTX13B_STEPS=8이 거기서 들어간다(tools.py 기본값과 동일).
"""
import json
import sys
import time

import requests

BASE = "http://127.0.0.1:8700"

# 인물이 등장하지만 참조 사진은 없는 시나리오 — no-ref 모드의 대표 입력.
SCRIPT = (
    "한 여성 모델이 도심 옥상에서 바람에 코트 자락을 날리며 카메라를 향해 걸어온다. "
    "엘리베이터를 타고 내려와 로비의 유리문을 밀고 거리로 나선다. "
    "횡단보도에서 신호를 기다리며 고개를 들어 하늘을 본다. "
    "해질 무렵 골목 카페 앞에 멈춰 서서 미소 짓는다."
)

t0 = time.time()
marks: list[tuple[float, str]] = []


def mark(label: str) -> None:
    elapsed = time.time() - t0
    marks.append((elapsed, label))
    print(f"[{elapsed:7.1f}s] {label}", flush=True)


resp = requests.post(f"{BASE}/jobs", json={
    "script_text": SCRIPT,
    "ref_images": [],      # no-ref: 참조 이미지 없음
    "image_request": "",   # 빈 문자열 → entry router가 M2 이미지 분기로 안 감
})
resp.raise_for_status()
job_id = resp.json()["job_id"]
mark(f"job 생성 job_id={job_id}")

last_phase = None
deadline = time.time() + 3600
while time.time() < deadline:
    st = requests.get(f"{BASE}/jobs/{job_id}/status").json()
    status, phase = st.get("status"), st.get("phase")
    if phase != last_phase:
        mark(f"phase={phase} status={status}")
        last_phase = phase

    if status == "waiting_for_approval":
        cp = st["checkpoint"]["checkpoint"]
        if cp.startswith("1-4"):
            payload = {"approved": True}                 # AgentScenePreview
        elif cp.startswith("3-5"):
            payload = {"action": "approve_all"}          # AgentClipPreview
        else:
            print(f"FAIL: no-ref 경로에 없어야 할 체크포인트 {cp}", flush=True)
            sys.exit(1)
        mark(f"승인 {cp} -> {payload}")
        requests.post(f"{BASE}/jobs/{job_id}/resume", json={"payload": payload})

    elif status == "done":
        mark(f"DONE {st.get('final_video_url')}")
        break
    elif status == "error":
        print(f"FAIL: {st.get('error')}", flush=True)
        sys.exit(1)
    time.sleep(5)
else:
    print("FAIL: timeout", flush=True)
    sys.exit(1)

# 품질 점검용: 씬별 mode/해상도 결정 요소와 실제 프롬프트를 그대로 덤프한다.
state = requests.get(f"{BASE}/jobs/{job_id}/state").json().get("values") or {}
scenes = state.get("scenes") or []
print("\n=== 씬별 산출 ===", flush=True)
for s in scenes:
    print(json.dumps({
        "id": s.get("id"), "mode": s.get("mode"), "duration": s.get("duration"),
        "matched_image": s.get("matched_image"), "subject_type": s.get("subject_type"),
        "clip_path": s.get("clip_path"),
        "prompt": s.get("prompt"),
    }, ensure_ascii=False, indent=2), flush=True)
print("\n=== style_bible ===\n" + str(state.get("style_bible")), flush=True)
print("\n=== 타임라인 ===", flush=True)
for elapsed, label in marks:
    print(f"  {elapsed:7.1f}s  {label}", flush=True)
print(f"\n총 {time.time() - t0:.1f}s / 씬 {len(scenes)}개", flush=True)
