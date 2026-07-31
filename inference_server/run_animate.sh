#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
export WAN_ANIMATE_MODEL_ID="${WAN_ANIMATE_MODEL_ID:-Wan-AI/Wan2.2-Animate-14B-Diffusers}"
export WAN_ANIMATE_REPO="${WAN_ANIMATE_REPO:-/home/admin/video_generator/Wan2.2-Animate}"
export WAN_ANIMATE_PROCESS_CKPT="${WAN_ANIMATE_PROCESS_CKPT:-$PWD/process_checkpoint}"
export WAN_ANIMATE_HOST="${WAN_ANIMATE_HOST:-0.0.0.0}"
export WAN_ANIMATE_PORT="${WAN_ANIMATE_PORT:-8600}"
export WAN_ANIMATE_WIDTH="${WAN_ANIMATE_WIDTH:-832}"
export WAN_ANIMATE_HEIGHT="${WAN_ANIMATE_HEIGHT:-480}"
export WAN_ANIMATE_MAX_SECONDS="${WAN_ANIMATE_MAX_SECONDS:-5}"
export DIFFUSERS_ATTENTION_BACKEND="${DIFFUSERS_ATTENTION_BACKEND:-native}"
# Reduce CUDA allocator fragmentation (root cause behind past ~45GB fragmentation OOMs on GB10 unified memory).
export PYTORCH_CUDA_ALLOC_CONF="${PYTORCH_CUDA_ALLOC_CONF:-expandable_segments:True}"

exec /home/admin/huyuan-env/bin/python animate_server.py
