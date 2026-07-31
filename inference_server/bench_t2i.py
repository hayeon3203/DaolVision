"""One-shot T2I benchmark for the :8501 zimage slot candidates.

Loads one pipeline, generates one image with a fixed prompt/seed, reports
load time / generate time / peak GPU memory, then frees the model.

Usage:
  python bench_t2i.py sdxl
  python bench_t2i.py flux-schnell
  python bench_t2i.py qwen-image-flash
"""
import os
import sys
import gc
import time

os.environ.setdefault("DIFFUSERS_ATTENTION_BACKEND", "native")  # flash-attn broken on GB10/Blackwell

import torch

PROMPT = "a red fox in a snowy pine forest, golden hour, cinematic still frame"
SEED = 42
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bench_out")
os.makedirs(OUT_DIR, exist_ok=True)

MODELS = {
    "sdxl": dict(
        repo="stabilityai/stable-diffusion-xl-base-1.0",
        pipeline_cls="StableDiffusionXLPipeline",
        steps=30,
        extra={},
    ),
    "flux-schnell": dict(
        repo="black-forest-labs/FLUX.1-schnell",
        pipeline_cls="FluxPipeline",
        steps=4,
        extra=dict(guidance_scale=0.0),
    ),
    "qwen-image-flash": dict(
        repo="nvidia/Qwen-Image-Flash",
        pipeline_cls="QwenImagePipeline",
        steps=4,
        extra=dict(true_cfg_scale=1.0),
    ),
}


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in MODELS:
        print(f"usage: python bench_t2i.py [{'|'.join(MODELS)}]")
        sys.exit(1)
    name = sys.argv[1]
    cfg = MODELS[name]

    import diffusers
    pipeline_cls = getattr(diffusers, cfg["pipeline_cls"])

    torch.cuda.reset_peak_memory_stats()
    t0 = time.time()
    pipe = pipeline_cls.from_pretrained(cfg["repo"], torch_dtype=torch.bfloat16)
    pipe = pipe.to("cuda")
    load_s = time.time() - t0

    t1 = time.time()
    image = pipe(
        prompt=PROMPT,
        width=1024,
        height=1024,
        num_inference_steps=cfg["steps"],
        generator=torch.Generator(device="cuda").manual_seed(SEED),
        **cfg["extra"],
    ).images[0]
    gen_s = time.time() - t1

    peak_gb = torch.cuda.max_memory_allocated() / (1024 ** 3)
    out_path = os.path.join(OUT_DIR, f"{name}.png")
    image.save(out_path)

    print(f"RESULT model={name} load_s={load_s:.1f} gen_s={gen_s:.1f} peak_vram_gb={peak_gb:.1f} out={out_path}")

    del pipe
    gc.collect()
    torch.cuda.empty_cache()


if __name__ == "__main__":
    main()
