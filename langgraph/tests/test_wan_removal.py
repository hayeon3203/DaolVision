"""Wan2.2(:8500, 중국 원산) 백엔드 제거 검증 — docs/model-selection.md의
'비중국 원산' 원칙 위반 해소. T2V/I2V 폴백 씬을 LTX-Video-0.9.8-13B-distilled
(:8188 ComfyUI, Task 4.6이 이미 받아둔 체크포인트)로 통합.
ComfyUI 실호출 없이 GPU 없이 돈다 — 라이브 검증은 별도 수동 단계(플랜 Task 10).

    ./.venv/bin/python tests/test_wan_removal.py
"""
import asyncio
import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # langgraph/ 모듈 import용

import tools
import nodes


def test_to_ltx_len_snaps_to_8k_plus_1():
    assert tools.to_ltx_len(97) == 97       # 8*12+1, 이미 8k+1이면 그대로
    assert tools.to_ltx_len(1) == 25        # 최소 클램프
    assert tools.to_ltx_len(50) == 49       # 49(8*6+1, 차이1)가 57(8*7+1, 차이7)보다 가까움
    for n in (17, 33, 60, 100, 200):
        v = tools.to_ltx_len(n)
        assert (v - 1) % 8 == 0 and v >= 25, (n, v)
    print("ok: LTX length가 8k+1로 스냅되고 최소 25 유지")


def test_t2v_graph_has_no_image_nodes():
    graph = tools._build_ltx13b_t2v_graph(
        prompt="a robot waving", width=832, height=480, length=49, seed=7)
    assert not any(n["class_type"] in ("LoadImage", "LTXVImgToVideo")
                   for n in graph.values()), graph
    assert graph["7"]["class_type"] == "EmptyLTXVLatentVideo"
    assert graph["7"]["inputs"] == {
        "width": 832, "height": 480, "length": 49, "batch_size": 1}
    assert graph["9"]["inputs"]["positive"] == ["12", 0]
    assert graph["9"]["inputs"]["negative"] == ["12", 1]
    assert graph["9"]["inputs"]["latent_image"] == ["7", 0]
    assert graph["9"]["inputs"]["seed"] == 7
    assert graph["9"]["inputs"]["model"] == ["6", 0]
    assert graph["3"]["inputs"]["text"] == "a robot waving"
    assert graph["1"]["inputs"]["ckpt_name"] == tools.LTX13B_CHECKPOINT
    print("ok: T2V 그래프에 이미지 노드 없음, latent/조건 배선 정확")


def test_t2v_request_key_changes_with_prompt_and_scene():
    k1 = tools._t2v_request_key(scene_id=3, prompt="a cat", duration=2.0, seed=None)
    k2 = tools._t2v_request_key(scene_id=3, prompt="a dog", duration=2.0, seed=None)
    k3 = tools._t2v_request_key(scene_id=4, prompt="a cat", duration=2.0, seed=None)
    assert len({k1, k2, k3}) == 3, "prompt 또는 scene_id 변화가 request_key에 반영 안 됨"
    print("ok: T2V request_key가 prompt/scene_id 변화를 반영(stale 캐시 방지)")


def test_i2v_fallback_request_key_changes_with_prompt_and_image():
    k1 = tools._i2v_fallback_request_key(
        scene_id=1, prompt="p1", matched_image="a.png", duration=2.0, seed=None)
    k2 = tools._i2v_fallback_request_key(
        scene_id=1, prompt="p2", matched_image="a.png", duration=2.0, seed=None)
    k3 = tools._i2v_fallback_request_key(
        scene_id=1, prompt="p1", matched_image="b.png", duration=2.0, seed=None)
    assert len({k1, k2, k3}) == 3, "prompt 또는 matched_image 변화가 request_key에 반영 안 됨"
    print("ok: I2V 폴백 request_key가 prompt/matched_image 변화를 반영")


def test_call_video_and_wan_url_removed():
    assert not hasattr(tools, "call_video"), "call_video가 남아있음 — Wan 배제 목적 위반"
    assert not hasattr(tools, "WAN_URL"), "WAN_URL이 남아있음"
    print("ok: call_video/WAN_URL 완전 제거")


def test_new_wrapper_signatures():
    t2v_params = list(inspect.signature(tools.generate_t2v_clip).parameters)
    assert t2v_params == ["job_id", "scene_id", "prompt", "duration", "seed", "force_new"], t2v_params
    i2v_params = list(inspect.signature(tools.generate_i2v_fallback_clip).parameters)
    assert i2v_params == [
        "job_id", "scene_id", "prompt", "matched_image", "duration", "seed", "force_new",
        "negative_prompt",
    ], i2v_params
    print("ok: generate_t2v_clip/generate_i2v_fallback_clip 시그니처 확정")


async def _async_test_dispatch_routes_to_new_functions():
    calls = []

    async def fake_t2v(**kw):
        calls.append(("t2v", kw))
        return "clipT.mp4"

    async def fake_i2v_fb(**kw):
        calls.append(("i2v_fb", kw))
        return "clipI.mp4"

    tools.generate_t2v_clip = fake_t2v
    tools.generate_i2v_fallback_clip = fake_i2v_fb

    t2v_scene = {"id": 1, "mode": "T2V", "prompt": "p", "matched_image": None,
                 "duration": 2.0, "mood": "neutral"}
    await nodes.node_generate_one_clip({"scene": t2v_scene, "job_id": "j", "seed": 1})
    assert calls[-1][0] == "t2v", calls
    assert calls[-1][1]["prompt"] == "p", calls

    i2v_scene = {"id": 2, "mode": "I2V", "prompt": "p", "matched_image": "ref.png",
                 "duration": 2.0, "mood": "neutral"}
    await nodes.node_generate_one_clip({"scene": i2v_scene, "job_id": "j", "seed": 1})
    assert calls[-1][0] == "i2v_fb", calls
    assert calls[-1][1]["matched_image"] == "ref.png", calls
    print("ok: mode=T2V/I2V가 각각 generate_t2v_clip/generate_i2v_fallback_clip로 라우팅")


def test_dispatch_routes_to_new_functions():
    asyncio.run(_async_test_dispatch_routes_to_new_functions())


def test_webp_bytes_to_mp4_produces_real_mp4():
    import io
    from PIL import Image as PILImage
    frames = []
    for i in range(3):
        img = PILImage.new("RGB", (64, 64), color=(i * 80, 100, 150))
        frames.append(img)
    buf = io.BytesIO()
    frames[0].save(buf, format="WEBP", save_all=True, append_images=frames[1:],
                    duration=100, loop=0)
    webp_bytes = buf.getvalue()

    mp4_bytes = tools._webp_bytes_to_mp4(webp_bytes, fps=10)
    assert mp4_bytes[:4] != b"RIFF", "여전히 WebP 컨테이너 — mp4 재인코딩 안 됨"
    assert len(mp4_bytes) > 0

    import tempfile, subprocess as sp
    with tempfile.NamedTemporaryFile(suffix=".mp4") as f:
        f.write(mp4_bytes)
        f.flush()
        probe = sp.run(
            ["ffprobe", "-v", "error", "-show_entries", "stream=codec_name,nb_frames",
             "-of", "default=noprint_wrappers=1", f.name],
            capture_output=True, text=True, check=True,
        )
    assert "codec_name=h264" in probe.stdout, probe.stdout
    assert "nb_frames=3" in probe.stdout, probe.stdout
    print("ok: webp 바이트가 ffprobe로 검증 가능한 진짜 h264 mp4로 재인코딩됨")


def test_webp_bytes_to_mp4_reaps_ffmpeg_on_mid_loop_failure():
    """리뷰 지적: 프레임 루프/write/communicate 도중 예외가 나면 ffmpeg proc이 reap 안
    되고 좀비/행 상태로 남는다. 두 번째 프레임에서 강제로 예외를 터뜨려(ffmpeg는 나머지
    입력을 기다리며 살아있는 상태) except 경로가 proc.kill()+wait()로 실제 회수하는지
    검증한다."""
    import io
    from unittest import mock
    from PIL import Image as PILImage

    frames = [PILImage.new("RGB", (64, 64), color=(i * 40, 100, 150)) for i in range(5)]
    buf = io.BytesIO()
    frames[0].save(buf, format="WEBP", save_all=True, append_images=frames[1:],
                    duration=100, loop=0)
    webp_bytes = buf.getvalue()

    real_popen = tools.subprocess.Popen
    created = []

    def spy_popen(*a, **kw):
        p = real_popen(*a, **kw)
        created.append(p)
        return p

    call_count = {"n": 0}
    orig_convert = PILImage.Image.convert

    def flaky_convert(self, *a, **kw):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise RuntimeError("simulated mid-loop failure")
        return orig_convert(self, *a, **kw)

    with mock.patch("tools.subprocess.Popen", side_effect=spy_popen), \
         mock.patch.object(PILImage.Image, "convert", flaky_convert):
        try:
            tools._webp_bytes_to_mp4(webp_bytes, fps=10)
            raised = False
        except RuntimeError:
            raised = True

    assert raised, "프레임 루프 중 예외가 삼켜짐"
    assert created, "Popen이 호출되지 않음"
    proc = created[0]
    try:
        proc.wait(timeout=5)
    except tools.subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        raise AssertionError("except 경로가 ffmpeg를 kill하지 않음 — 좀비/행 프로세스")
    assert proc.returncode is not None
    print("ok: 프레임 루프 도중 실패해도 ffmpeg proc이 kill/wait로 reap됨(좀비 방지)")


def main():
    test_to_ltx_len_snaps_to_8k_plus_1()
    test_t2v_graph_has_no_image_nodes()
    test_t2v_request_key_changes_with_prompt_and_scene()
    test_i2v_fallback_request_key_changes_with_prompt_and_image()
    test_call_video_and_wan_url_removed()
    test_new_wrapper_signatures()
    test_dispatch_routes_to_new_functions()
    test_webp_bytes_to_mp4_produces_real_mp4()
    test_webp_bytes_to_mp4_reaps_ffmpeg_on_mid_loop_failure()


if __name__ == "__main__":
    main()
    sys.exit(0)
