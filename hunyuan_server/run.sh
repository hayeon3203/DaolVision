#!/usr/bin/env bash
# Start the Wan2.2-TI2V-5B inference server on the host GPU.
set -euo pipefail

cd "$(dirname "$0")"
VENV="$HOME/huyuan-env"

export HYV_HOST="${HYV_HOST:-0.0.0.0}"
export HYV_PORT="${HYV_PORT:-8500}"
# One checkpoint serves both T2V and I2V (~23GB shared), so both fit comfortably
# on the 119GB GB10 with no swap / single-residency juggling.
export WAN_MODEL_ID="${WAN_MODEL_ID:-Wan-AI/Wan2.2-TI2V-5B-Diffusers}"
export WAN_WIDTH="${WAN_WIDTH:-832}"
export WAN_HEIGHT="${WAN_HEIGHT:-480}"
# Avoid flash-attn on Blackwell; let diffusers use PyTorch SDPA.
export DIFFUSERS_ATTENTION_BACKEND="${DIFFUSERS_ATTENTION_BACKEND:-native}"
# Reduce CUDA allocator fragmentation (root cause behind past ~45GB fragmentation OOMs on GB10 unified memory).
export PYTORCH_CUDA_ALLOC_CONF="${PYTORCH_CUDA_ALLOC_CONF:-expandable_segments:True}"
# Brand logo overlay off by default (set WAN_LOGO_OVERLAY=1 to re-enable).
export WAN_LOGO_OVERLAY="${WAN_LOGO_OVERLAY:-0}"

exec "$VENV/bin/python" server.py
