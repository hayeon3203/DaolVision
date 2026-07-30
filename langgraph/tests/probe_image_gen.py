"""M2-0 이미지 모델 실측 — FLUX.1-schnell :8501 /generate 로 png 3장을 뽑는다.
사용자 눈 판정용 실험 스크립트(그래프 무관).

실행: cd langgraph && ./.venv/bin/python tests/probe_image_gen.py
결과: langgraph/jobs/probe_image/probe_{person,background,mascot}.png
"""
import sys
from pathlib import Path

import httpx

# 서버 설정은 tools.py 한 곳에서 재사용(포트/해상도 표류 방지)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools import T2I_URL, WIDTH, HEIGHT, JOBS_DIR  # noqa: E402

OUT_DIR = JOBS_DIR / "probe_image"

# 인물 / 배경 / 마스코트 — PRD R4 실측 샘플
PROMPTS = {
    "person": "A young woman with short black hair smiling warmly, upper body portrait, "
              "soft studio lighting, photorealistic, sharp focus",
    "background": "An empty cozy coffee shop interior in the morning, wooden tables, "
                  "large windows with sunlight, warm tones, wide shot, photorealistic",
    "mascot": "A cute round orange cat mascot character, big eyes, simple flat "
              "illustration style, white background, centered",
}


def probe_one(name: str, prompt: str) -> Path:
    """/generate 로 정지 이미지 요청 → png 저장."""
    body = {"prompt": prompt, "width": WIDTH, "height": HEIGHT}
    timeout = httpx.Timeout(connect=10.0, read=120.0, write=60.0, pool=None)
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(f"{T2I_URL}/generate", json=body)
        resp.raise_for_status()
        image_url = resp.json()["image_url"]
        png_resp = client.get(f"{T2I_URL}{image_url}")
        png_resp.raise_for_status()

    png = OUT_DIR / f"probe_{name}.png"
    png.write_bytes(png_resp.content)
    return png


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    results = []
    for name, prompt in PROMPTS.items():
        print(f"[probe] {name} … ", end="", flush=True)
        try:
            png = probe_one(name, prompt)
            ok = png.exists() and png.stat().st_size > 0
            print("OK" if ok else "EMPTY", "→", png)
            results.append(ok)
        except Exception as e:  # noqa: BLE001
            print("FAIL:", e)
            results.append(False)

    n_ok = sum(results)
    print(f"\n{n_ok}/{len(PROMPTS)} png 생성. 저장 위치: {OUT_DIR}")
    print("→ 사용자 눈 판정 후 PLAN.md M2-0 '판정 결과'에 기입.")
    return 0 if n_ok == len(PROMPTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
