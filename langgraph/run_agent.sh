#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
export AGENT_API_HOST="${AGENT_API_HOST:-0.0.0.0}"
export AGENT_API_PORT="${AGENT_API_PORT:-8700}"
export AGENT_OLLAMA_URL="${AGENT_OLLAMA_URL:-http://127.0.0.1:11434/api/chat}"
export AGENT_LLM_MODEL="${AGENT_LLM_MODEL:-qwen3.5:9b}"
export AGENT_VISION_MODEL="${AGENT_VISION_MODEL:-qwen3.5:9b}"  # qwen3.5:9b = text+vision 겸용. qwen2.5:7b+gemma3:4b 대체(단일 모델 로드)
export AGENT_CAPTION_REFS="${AGENT_CAPTION_REFS:-1}"          # 1=참조 캡션 ON. VISION_MODEL=qwen3.5:9b가 텍스트용으로 이미 상주 → 추가 모델 로드 0(옛 gemma 18.5GB 우려 소멸). shows 기반 씬↔이미지 매칭 정확도↑
export AGENT_WAN_URL="${AGENT_WAN_URL:-http://127.0.0.1:8500}"
export AGENT_T2I_URL="${AGENT_T2I_URL:-http://127.0.0.1:8501}"  # 정지 이미지 앵커(M2) 전용, FLUX.1-schnell
export AGENT_KOKORO_URL="${AGENT_KOKORO_URL:-http://127.0.0.1:8503}"  # S1 나레이션 전용 Kokoro
export AGENT_CHATTERBOX_URL="${AGENT_CHATTERBOX_URL:-http://127.0.0.1:8504}"  # 사용자 음성 복제 전용 Chatterbox V3
export AGENT_CHATTERBOX_NARRATION_REFERENCE="${AGENT_CHATTERBOX_NARRATION_REFERENCE:-../private/tts/voices/narrator_cc0/reference.wav}"
export AGENT_COMFYUI_URL="${AGENT_COMFYUI_URL:-http://127.0.0.1:8188}"   # Stand-In(참조-얼굴 씬)
export AGENT_USE_STANDIN="${AGENT_USE_STANDIN:-1}"     # job bfb193ba 재현: 참조 씬을 14B Stand-In(ComfyUI)으로. 0이면 :8500 5B로만.
export AGENT_STANDIN_STEPS="${AGENT_STANDIN_STEPS:-4}" # lightx2v distill 4~8 (bfb193ba 당시 값은 기록에 없어 기본 4 유지)
export AGENT_STANDIN_FPS="${AGENT_STANDIN_FPS:-16}"    # Wan2.1 네이티브 16fps. 24는 프레임 +50% → 클립당 ~40% 느림 + 모션 1.5x 빨라 보임(편집이 24fps로 정규화).
export AGENT_STANDIN_EXEC_TIMEOUT="${AGENT_STANDIN_EXEC_TIMEOUT:-1800}"
export AGENT_STANDIN_QUEUE_TIMEOUT="${AGENT_STANDIN_QUEUE_TIMEOUT:-86400}"
export AGENT_MAX_CONCURRENT_CLIPS="${AGENT_MAX_CONCURRENT_CLIPS:-1}"  # 씬 클립 동시 생성 상한. 1=순차(OOM안전), 2=백엔드당 하나
# fast=832x480/10 steps, quality=1280x704/20 steps. 개별 AGENT_* 값으로 덮어쓸 수 있다.
export AGENT_VIDEO_PRESET="${AGENT_VIDEO_PRESET:-fast}"
export AGENT_FPS="${AGENT_FPS:-24}"          # Wan2.2-TI2V-5B 네이티브 24fps

exec ./.venv/bin/python api.py
