#!/usr/bin/env python3
"""S1 spike: exercise Nemotron-Labs-Diffusion-VLM-8B as text + caption model."""

import argparse
import json
import sys
import time
from pathlib import Path

import torch
from huggingface_hub import snapshot_download
from transformers import AutoModel, AutoTokenizer


MODEL_ID = "nvidia/Nemotron-Labs-Diffusion-VLM-8B"


def generate(model, tokenizer, process_messages, messages, max_new_tokens):
    batch = process_messages(
        tokenizer,
        messages,
        add_generation_prompt=True,
        enable_thinking=False,
        max_image_size=672,
    )
    prompt_ids = batch["input_ids"].to("cuda")
    kwargs = {}
    if "pixel_values" in batch:
        kwargs["pixel_values"] = batch["pixel_values"].to("cuda", dtype=torch.bfloat16)
        kwargs["image_sizes"] = batch["image_sizes"]
    torch.cuda.synchronize()
    started = time.perf_counter()
    with torch.inference_mode():
        out_ids, nfe = model.generate(
            prompt_ids,
            **kwargs,
            max_new_tokens=max_new_tokens,
            steps=max_new_tokens,
            block_length=32,
            shift_logits=False,
            threshold=0.9,
            eos_token_id=tokenizer.eos_token_id,
        )
    torch.cuda.synchronize()
    elapsed = time.perf_counter() - started
    text = tokenizer.batch_decode(
        out_ids[:, prompt_ids.shape[1] :], skip_special_tokens=True
    )[0].strip()
    return {"text": text, "seconds": round(elapsed, 2), "nfe": int(nfe)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--image",
        default="/home/admin/video_generator/assets/howtouse1.png",
    )
    args = parser.parse_args()

    snapshot = snapshot_download(MODEL_ID)
    sys.path.insert(0, snapshot)
    from image_processing import process_messages

    tokenizer = AutoTokenizer.from_pretrained(
        MODEL_ID, trust_remote_code=True, local_files_only=True
    )
    torch.cuda.reset_peak_memory_stats()
    load_started = time.perf_counter()
    model = (
        AutoModel.from_pretrained(
            MODEL_ID,
            trust_remote_code=True,
            dtype=torch.bfloat16,
            low_cpu_mem_usage=True,
            local_files_only=True,
        )
        .cuda()
        .eval()
    )
    load_seconds = time.perf_counter() - load_started

    scene_messages = [
        {
            "role": "system",
            "content": (
                "한국어 스토리를 정확히 4개 장면으로 나눠라. "
                '오직 JSON 배열만 출력: [{"id":1,"text":"...",'
                '"duration":3,"subject_type":"human"}]. '
                "id는 1~4, duration은 2 또는 3, 모든 장면은 human이다."
            ),
        },
        {
            "role": "user",
            "content": (
                "투명 바이저를 쓴 한 우주비행사가 로켓으로 발사되어 우주유영을 하고, "
                "신비로운 외계 행성을 탐사한 뒤 지구로 무사히 귀환한다."
            ),
        },
    ]
    scene = generate(model, tokenizer, process_messages, scene_messages, 256)

    image_path = str(Path(args.image).resolve())
    caption_messages = [
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": image_path}},
                {
                    "type": "text",
                    "text": (
                        "Describe the MAIN subject in ONE concise English phrase "
                        "for a video prompt. No preamble or quotes."
                    ),
                },
            ],
        }
    ]
    caption = generate(model, tokenizer, process_messages, caption_messages, 64)

    result = {
        "model": MODEL_ID,
        "environment": {
            "torch": torch.__version__,
            "load_seconds": round(load_seconds, 2),
            "peak_cuda_allocated_gib": round(
                torch.cuda.max_memory_allocated() / 1024**3, 2
            ),
            "peak_cuda_reserved_gib": round(
                torch.cuda.max_memory_reserved() / 1024**3, 2
            ),
        },
        "scene_split": scene,
        "caption": {"image": image_path, **caption},
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
