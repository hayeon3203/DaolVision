"""Task 3.3 — LTX-2.3 Face-ID I2V 파이프라인 구간별(로드/샘플링/디코드) 소요시간 프로파일링.

ltx_faceid.json은 SetNode/GetNode(KJNodes 프론트엔드 전용 pseudo-node, /object_info에
없음)로 배선돼 /prompt API에 직접 못 보냄 — 3.2와 동일하게 헤드리스 브라우저로
window.app.graphToPrompt()를 호출해 실행용 API-format으로 변환한 뒤 제출한다.
브라우저는 이 실행 1회에만 쓰고, 실제 타이밍은 ComfyUI 웹소켓 실행 이벤트로 잰다.

실행 (전용 격리 venv, 프로덕션 ComfyUI venv는 건드리지 않음):
    /home/admin/comfyui-bench-venv/bin/python tests/probe_ltx_profile.py
"""
import json
import sys
import time
import uuid
import urllib.request
from pathlib import Path

import websocket
from playwright.sync_api import sync_playwright

COMFY_URL = "http://localhost:8188"
WORKFLOW = Path(__file__).resolve().parents[1] / "comfyui_workflows" / "ltx_faceid.json"
LOG_OUT = Path(__file__).resolve().parent / "_ltx_profile_log.json"

# 3.2에서 확정한 기본값(STATE.md) 그대로 재현 — 3.3은 병목 실측이지 파라미터
# 변경 실험이 아니다(그건 3.4).
OVERRIDES = {
    "100": {"width": 1024, "height": 576},          # EmptyLTXVLatentVideo, 16:9 기본값
    "104": {"image": "geonho_ref.jpg"},                # Face Reference — 사용자가 직접 지정한 테스트용
                                                        # 스톡 이미지(DaolVision/건호군.jpg)
    "40": {"text": (
        "wide establishing shot, astronaut walking toward a rocket at sunset launch pad, "
        "character small in frame relative to environment, expansive background, cinematic lighting"
    )},  # Automatic Prompt (Manual Prompt(12)는 미연결 dead branch, 안 건드림)
}


def graph_to_prompt():
    graph_json = json.loads(WORKFLOW.read_text())
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(COMFY_URL, wait_until="networkidle")
        page.wait_for_function("() => window.app && window.app.graph")
        page.evaluate("(g) => window.app.loadGraphData(g)", graph_json)
        result = page.evaluate("async () => { const r = await window.app.graphToPrompt(); return r.output; }")
        browser.close()
    return result


def apply_overrides(prompt):
    for node_id, fields in OVERRIDES.items():
        prompt[node_id]["inputs"].update(fields)
    return prompt


def run_and_capture(prompt, max_wait_s=1800):
    client_id = str(uuid.uuid4())
    ws = websocket.create_connection(f"ws://localhost:8188/ws?clientId={client_id}", timeout=30)

    body = json.dumps({"prompt": prompt, "client_id": client_id}).encode()
    req = urllib.request.Request(f"{COMFY_URL}/prompt", data=body, headers={"Content-Type": "application/json"})
    resp = json.loads(urllib.request.urlopen(req).read())
    if "error" in resp:
        raise RuntimeError(f"submit 거부: {resp}")
    prompt_id = resp["prompt_id"]
    print(f"submitted prompt_id={prompt_id}")

    t0 = time.time()
    events = []
    while time.time() - t0 < max_wait_s:
        try:
            msg = ws.recv()
        except websocket.WebSocketTimeoutException:
            # 30초 무이벤트는 정상(긴 로드/샘플링 구간) — history로 완료여부만 확인
            hist = json.loads(urllib.request.urlopen(f"{COMFY_URL}/history/{prompt_id}").read())
            if prompt_id in hist:
                events.append({"t": round(time.time() - t0, 3), "type": "history_poll_done", "data": None})
                break
            continue
        if isinstance(msg, (bytes, bytearray)):
            continue  # 프리뷰 프레임 바이너리, 타이밍과 무관
        data = json.loads(msg)
        events.append({"t": round(time.time() - t0, 3), "type": data.get("type"), "data": data.get("data")})
        d = data.get("data") or {}
        if data.get("type") == "executing" and d.get("node") is None and d.get("prompt_id") == prompt_id:
            break
        if data.get("type") == "execution_error" and d.get("prompt_id") == prompt_id:
            print("execution_error:", d)
            break
    ws.close()
    return events


def main():
    """3.4 파라미터 스윕용: argv[1]로 추가 override JSON 파일 경로를 받으면
    OVERRIDES 위에 덮어씀(예: {"99": {"strength_model": 0.75}}).
    argv[2]가 있으면 로그 출력 경로를 그걸로 바꿈(run별 로그 구분용)."""
    prompt = apply_overrides(graph_to_prompt())
    if len(sys.argv) > 1:
        extra = json.loads(Path(sys.argv[1]).read_text())
        for node_id, fields in extra.items():
            prompt[node_id]["inputs"].update(fields)
    class_map = {nid: nd["class_type"] for nid, nd in prompt.items()}
    events = run_and_capture(prompt)
    out_path = Path(sys.argv[2]) if len(sys.argv) > 2 else LOG_OUT
    out_path.write_text(json.dumps({"class_map": class_map, "events": events}, indent=2, ensure_ascii=False))
    print(f"raw log: {out_path}")


if __name__ == "__main__":
    main()
