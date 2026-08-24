#!/usr/bin/env bash
# Start the FLUX.1-schnell text-to-image server on the host GPU.
set -euo pipefail

cd "$(dirname "$0")"
VENV="$HOME/huyuan-env"

export HYV_HOST="${HYV_HOST:-0.0.0.0}"
export HYV_PORT="${HYV_PORT:-8501}"
export FLUX_MODEL_PATH="${FLUX_MODEL_PATH:-black-forest-labs/FLUX.1-schnell}"
# 로컬 캐시만 쓰고 Hugging Face로 나가지 않는다. 매 요청마다 모델을 다시 로드하는
# 정책(FLUX_KEEP_RESIDENT=0)이라 로드마다 리비전 확인 HTTP 호출이 붙었고, 그게 로드
# 시간을 157s → 646s로 밀어 :8700의 600s read timeout을 터뜨렸다(2026-08-13 job
# 37ec345a). PRD R9의 "External calls = 0" 요구사항 위반이기도 하다.
export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"
# 2026-08-13: 0 → 1. 요청마다 언로드하던 정책은 Task 2.4 전 모델 상주 OOM 실측에서
# 나온 것인데, 그 대가가 콜드 로드 157초다. job 하나가 T2I를 2~3회(인물 이미지 +
# 조립 배경) 호출하므로 5~8분이 순수 대기로 나간다. 현재 상주 총량이 17/119GB라
# 24GB를 더 물어도 여유가 있다고 보고 켠다 — OOM이 재발하면 되돌린다.
export FLUX_KEEP_RESIDENT="${FLUX_KEEP_RESIDENT:-0}"
# 2026-08-13 재원복: 1로 켰다가 되돌림. 콜드 로드 157초는 확실히 사라졌지만(job
# e9059c29 33분 완주) FLUX 24GB가 상시 잠기면서 ComfyUI가 LTX 22B → Kontext 스택으로
# 모델을 교체할 여유가 없어졌다. job 953eeea2에서 스왑 15GB가 전부 소진되고 여유
# 메모리 3GB만 남은 채 텍스트 인코더 로드에서 20분+ 정체(계산이 아니라 페이지 재배치).
# GB10은 CPU/GPU가 메모리를 공유하므로 상주 모델 하나가 전체 교체 여유를 갉아먹는다.
export TRANSFORMERS_OFFLINE="${TRANSFORMERS_OFFLINE:-1}"
export FLUX_WIDTH="${FLUX_WIDTH:-1024}"
export FLUX_HEIGHT="${FLUX_HEIGHT:-1024}"
export FLUX_STEPS="${FLUX_STEPS:-4}"
# Avoid flash-attn (FA-2) on Blackwell; let diffusers use PyTorch SDPA.
export DIFFUSERS_ATTN_BACKEND="${DIFFUSERS_ATTN_BACKEND:-native}"
# Reduce CUDA allocator fragmentation (root cause behind past ~45GB fragmentation OOMs on GB10 unified memory).
export PYTORCH_CUDA_ALLOC_CONF="${PYTORCH_CUDA_ALLOC_CONF:-expandable_segments:True}"

exec "$VENV/bin/python" flux_server.py
