#!/usr/bin/env bash
# Start the FLUX.1-schnell text-to-image server on the host GPU.
set -euo pipefail

cd "$(dirname "$0")"
VENV="$HOME/huyuan-env"

export HYV_HOST="${HYV_HOST:-0.0.0.0}"
export HYV_PORT="${HYV_PORT:-8501}"
export FLUX_MODEL_PATH="${FLUX_MODEL_PATH:-black-forest-labs/FLUX.1-schnell}"
export FLUX_WIDTH="${FLUX_WIDTH:-1024}"
export FLUX_HEIGHT="${FLUX_HEIGHT:-1024}"
export FLUX_STEPS="${FLUX_STEPS:-4}"
# Avoid flash-attn (FA-2) on Blackwell; let diffusers use PyTorch SDPA.
export DIFFUSERS_ATTN_BACKEND="${DIFFUSERS_ATTN_BACKEND:-native}"
# Reduce CUDA allocator fragmentation (root cause behind past ~45GB fragmentation OOMs on GB10 unified memory).
export PYTORCH_CUDA_ALLOC_CONF="${PYTORCH_CUDA_ALLOC_CONF:-expandable_segments:True}"

exec "$VENV/bin/python" flux_server.py
