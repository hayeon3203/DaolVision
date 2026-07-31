"""Task 3.5 — SageAttention3(sm_121a) 적용 전/후 스텝당 소요시간 비교.

KJNodes의 PathchSageAttentionKJ를 그래프에 삽입해 sageattn3_blackwell로 model을
패치한다. 삽입 지점: node 99(Face-ID LoRA) 출력 -> node 98
(LTX2SamplingPreviewOverride)의 model 입력 사이(다른 model 소비 노드 없음,
`prompt_preview.json` 역참조로 확인).

실행: /home/admin/comfyui-bench-venv/bin/python tests/probe_ltx_sageattn.py [baseline|sage3]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from probe_ltx_profile import graph_to_prompt, apply_overrides, run_and_capture, LOG_OUT  # noqa: E402

MODE = sys.argv[1] if len(sys.argv) > 1 else "sage3"
OUT = Path(__file__).resolve().parent / f"_ltx_sage_{MODE}_log.json"

NEW_NODE_ID = "200"


def main():
    prompt = apply_overrides(graph_to_prompt())

    if MODE == "sage3":
        prompt[NEW_NODE_ID] = {
            "inputs": {
                "model": ["99", 0],
                "sage_attention": "sageattn3",
                "allow_compile": False,
            },
            "class_type": "PathchSageAttentionKJ",
        }
        prompt["98"]["inputs"]["model"] = [NEW_NODE_ID, 0]

    class_map = {nid: nd["class_type"] for nid, nd in prompt.items()}
    events = run_and_capture(prompt)
    OUT.write_text(__import__("json").dumps({"mode": MODE, "class_map": class_map, "events": events}, indent=2, ensure_ascii=False))
    print(f"mode={MODE} raw log: {OUT}")


if __name__ == "__main__":
    main()
