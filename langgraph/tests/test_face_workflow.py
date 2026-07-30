"""M3-9 얼굴 전용 Stand-In T2V 경로 라우팅 검증.

face(사람) 참조는 standin_t2v.json(배경 프롬프트 100%)로, subject_ref(비인간)는
i2v_14b.json(참조 전체 첫프레임)로 가는지, relight 노브가 face 그래프에 새지 않는지 확인.

    ./.venv/bin/python tests/test_face_workflow.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tools


def _build(subject_ref, relight):
    return tools._build_reference_graph(
        prompt="a woman startled by monitor light in a dark office",
        num_frames=33, seed=7, prefix="job_2", subject_ref=subject_ref, relight=relight)


def test_face_uses_standin_no_relight():
    graph, nodes = _build(subject_ref=False, relight=True)
    assert nodes is tools._SI_FACE, "face 경로가 face 노드맵을 안 씀"
    assert nodes["embeds"] == "103", "face dims 노드가 103(EmptyEmbeds)이 아님"
    dims = graph["103"]["inputs"]
    assert dims["num_frames"] == 33, "num_frames 미주입"
    # relight override(node 105 전용)는 face 그래프에 절대 없어야 한다.
    assert "start_latent_strength" not in dims, "relight가 face(빈 embeds)에 샜음"
    assert graph["16"]["inputs"]["positive_prompt"].startswith("a woman"), "프롬프트 미주입"
    assert graph["74"]["inputs"]["filename_prefix"] == "job_2", "prefix 미주입"
    assert graph["27"]["inputs"]["seed"] == 7, "seed 미주입"
    # standin_t2v 고유 노드(얼굴 추출/identity 주입) 존재 확인
    classes = {n.get("class_type") for n in graph.values()}
    assert "ApplyFaceProcessor" in classes and "WanVideoAddStandInLatent" in classes, "Stand-In 노드 없음"
    print("ok: face→standin_t2v, 배경 프롬프트, relight 미주입")


def test_face_lora_strength_injected():
    """M3-10: face 경로에 identity/distill LoRA strength 노브가 주입되는지."""
    graph, _ = _build(subject_ref=False, relight=False)
    assert graph["69"]["inputs"]["strength"] == tools.STANDIN_FACE_LORA_STRENGTH, "identity LoRA strength 미주입"
    assert graph["71"]["inputs"]["strength"] == tools.STANDIN_DISTILL_LORA_STRENGTH, "distill LoRA strength 미주입"
    print("ok: face LoRA strength 노브 주입")


def test_subject_uses_i2v_with_relight():
    graph, nodes = _build(subject_ref=True, relight=True)
    assert nodes is tools._SI, "subject 경로가 i2v 노드맵을 안 씀"
    assert nodes["embeds"] == "105", "subject dims 노드가 105가 아님"
    enc = graph["105"]["inputs"]
    assert enc["num_frames"] == 33, "num_frames 미주입"
    assert enc["start_latent_strength"] < 1.0, "subject relight override 미적용"
    print("ok: subject→i2v_14b, relight 적용")


def test_subject_no_relight_keeps_lock():
    graph, _ = _build(subject_ref=True, relight=False)
    assert graph["105"]["inputs"]["start_latent_strength"] == 1.0, "relight off인데 잠금 완화됨"
    print("ok: subject relight off면 첫프레임 잠금 1.0 유지")


def test_workflow_files_exist():
    for wf in (tools.I2V_WORKFLOW, tools.FACE_WORKFLOW):
        assert wf.exists(), f"워크플로 파일 없음: {wf}"
    print("ok: 두 워크플로 파일 존재")


def main():
    test_workflow_files_exist()
    test_face_uses_standin_no_relight()
    test_face_lora_strength_injected()
    test_subject_uses_i2v_with_relight()
    test_subject_no_relight_keeps_lock()
    print("\nall M3-9 face-workflow tests passed")


if __name__ == "__main__":
    main()
