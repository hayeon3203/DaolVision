"""씬별 다른 구도 참조 이미지 스파이크 — subject_ref가 매 씬 같은 사진을 첫프레임으로
써서 구도가 고정되는 문제(2026-08-12 사용자 관찰) 완화 시도. Flux Kontext I2I로
ref_composite.png를 씬 의도에 맞게 재구성(로고/제품 정체성은 유지, 구도만 변경)한
참조 이미지를 씬별로 따로 만든다. generate_i2i_style()은 6종 스타일 프리셋 전용이라
자유 프롬프트가 안 되므로, 그 내부가 쓰는 _build_flux_kontext_graph를 직접 호출한다.
controlnet_strength를 낮게(0.15) 줘서 — 6.19 스파이크의 ControlNet 용도(구도 고정)와
반대로, 이번엔 구도 변경 자유도를 주는 쪽으로 씀.

실행: cd langgraph && ./.venv/bin/python tests/probe_logo_hw_recompose.py
결과: jobs/probe_logo_hw/assets/ref_scene1.png, ref_scene3.png
"""
import asyncio
import base64
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import httpx  # noqa: E402
import tools  # noqa: E402

ASSETS = Path(__file__).resolve().parent.parent / "jobs" / "probe_logo_hw" / "assets"
SRC_IMAGE = ASSETS / "device_gb10.png"  # 순수 장비 사진, 로고 없음(합성 전 원본)

SCENARIOS = {
    "scene1_dell_s45": (
        "The exact same product from the reference image, unchanged shape, materials, "
        "proportions and the exact wordmark/logo visible on its front panel — do not "
        "redesign or remove it. Recompose only: close-up hero shot on a wooden office "
        "desk in soft morning light, camera at a slightly lower angle than the "
        "reference, product fills most of the frame."
    ),
    "scene3_dell_s45": (
        "The exact same product from the reference image, unchanged shape, materials, "
        "proportions and the exact wordmark/logo visible on its front panel — do not "
        "redesign or remove it. Recompose only: the product now sits small and distant "
        "on a side table in the corner of a warmly lit living room at dusk, wide shot "
        "from across the room, product occupies a small portion of the frame."
    ),
}

LOW_CONTROLNET_STRENGTH = 0.45  # 1차 시도 0.15에서 제품 identity가 I2V 단계까지
# 못 버티고 붕괴(다른 물건으로 변함/환각 캐릭터)해서 상향 — 6.19 기본값(0.6, 구도
# 완전 고정)과 1차 시도(0.15, 구도 완전 자유) 중간, identity 안정성 우선 재시도


async def recompose(name: str, prompt: str) -> Path:
    image_bytes = SRC_IMAGE.read_bytes()
    normalized, img_width, img_height = tools._normalize_i2v_input(image_bytes)
    width, height = tools._flux_kontext_dims(img_width, img_height)
    seed = int(time.time()) + hash(name) % 1000

    timeout = httpx.Timeout(connect=10.0, read=180.0, write=60.0, pool=None)
    async with tools.oom.phase("i2i"), httpx.AsyncClient(timeout=timeout) as client:
        up = await client.post(
            f"{tools.COMFYUI_URL}/upload/image",
            files={"image": (f"recompose_{name}_input.png", normalized, "image/png")},
            data={"overwrite": "true"},
        )
        up.raise_for_status()
        uj = up.json()
        image_name = f"{uj['subfolder']}/{uj['name']}" if uj.get("subfolder") else uj["name"]

        graph = tools._build_flux_kontext_graph(
            prompt=prompt, image_name=image_name, width=width, height=height, seed=seed,
            lock_bg_color=False, guidance=tools.FLUX_KONTEXT_GUIDANCE,
            controlnet_strength=LOW_CONTROLNET_STRENGTH)
        resp = await client.post(f"{tools.COMFYUI_URL}/prompt", json={"prompt": graph})
        resp.raise_for_status()
        prompt_id = resp.json()["prompt_id"]

        started_at = time.time()
        history_item = None
        while history_item is None:
            if time.time() - started_at > tools.STANDIN_QUEUE_TIMEOUT:
                raise TimeoutError(f"{name}: I2I 재구성이 제한 시간 내 완료되지 않음")
            history = (await client.get(f"{tools.COMFYUI_URL}/history/{prompt_id}")).json()
            if prompt_id in history:
                history_item = history[prompt_id]
            else:
                await asyncio.sleep(2.0)

        if history_item.get("status", {}).get("status_str") == "error":
            raise RuntimeError(f"{name}: I2I 재구성 실행 오류 {history_item.get('status', {}).get('messages')}")

        media = None
        for node_out in history_item.get("outputs", {}).values():
            media = node_out.get("images")
            if media:
                break
        if not media:
            raise RuntimeError(f"{name}: I2I 재구성 출력 이미지 없음")
        output = media[0]
        png = await client.get(f"{tools.COMFYUI_URL}/view", params={
            "filename": output["filename"],
            "subfolder": output.get("subfolder", ""),
            "type": output.get("type", "output"),
        })
        png.raise_for_status()

    out_path = ASSETS / f"ref_{name}.png"
    out_path.write_bytes(png.content)
    return out_path


async def main() -> int:
    for name, prompt in SCENARIOS.items():
        print(f"[{name}] 재구성 중...")
        out = await recompose(name, prompt)
        print(f"  -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
