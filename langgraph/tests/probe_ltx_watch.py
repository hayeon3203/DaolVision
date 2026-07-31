"""이미 큐에서 실행 중인 prompt_id에 새 웹소켓으로 붙어 완료까지 이벤트를 잡는다.
probe_ltx_profile.py의 최초 recv() 타임아웃(600s)이 로딩 구간보다 짧아서 죽은 뒤,
같은 job을 재제출하지 않고(이중 로드 OOM 위험) 관찰만 재개하기 위한 보조 스크립트.
"""
import json
import sys
import time
import uuid
import urllib.request

import websocket

COMFY_URL = "http://localhost:8188"
PROMPT_ID = sys.argv[1]
LOG_OUT = sys.argv[2]
MAX_WAIT_S = 1800  # 30분 상한

client_id = str(uuid.uuid4())
ws = websocket.create_connection(f"ws://localhost:8188/ws?clientId={client_id}", timeout=30)

t0 = time.time()
events = []
while time.time() - t0 < MAX_WAIT_S:
    try:
        msg = ws.recv()
    except websocket.WebSocketTimeoutException:
        # 30초 무이벤트는 정상(긴 로드/샘플링 구간) — history로 완료여부만 확인하고 계속
        hist = json.loads(urllib.request.urlopen(f"{COMFY_URL}/history/{PROMPT_ID}").read())
        if PROMPT_ID in hist:
            events.append({"t": round(time.time() - t0, 3), "type": "history_poll_done", "data": None})
            break
        continue
    if isinstance(msg, (bytes, bytearray)):
        continue
    data = json.loads(msg)
    events.append({"t": round(time.time() - t0, 3), "type": data.get("type"), "data": data.get("data")})
    d = data.get("data") or {}
    if data.get("type") == "executing" and d.get("node") is None and d.get("prompt_id") == PROMPT_ID:
        break
    if data.get("type") == "execution_error" and d.get("prompt_id") == PROMPT_ID:
        print("execution_error:", d)
        break
ws.close()

with open(LOG_OUT, "w") as f:
    json.dump({"prompt_id": PROMPT_ID, "events": events, "note": "load 구간 초반부는 최초 스크립트 크래시로 유실, 재접속 이후만 기록"}, f, indent=2, ensure_ascii=False)
print(f"watch done, {len(events)} events -> {LOG_OUT}")
