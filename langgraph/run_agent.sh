#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
export AGENT_API_HOST="${AGENT_API_HOST:-0.0.0.0}"
export AGENT_API_PORT="${AGENT_API_PORT:-8700}"
export AGENT_OLLAMA_URL="${AGENT_OLLAMA_URL:-http://127.0.0.1:11434/api/chat}"
export AGENT_LLM_MODEL="${AGENT_LLM_MODEL:-hf.co/nvidia/NVIDIA-Nemotron-3-Nano-4B-GGUF:Q4_K_M}"
  # 2026-08-02: gemma4:latest로 잠깐 바꿨다가 롤백 — matched_image/subject_type을
  # LLM 판단에 맡기지 않고 단일 참조 시 node_split_scenes가 결정론적으로 강제하도록
  # 고쳐서(nodes.py "단일 참조 결정론적 매칭") 씬분할 LLM 자체의 이 약점은 더는 문제 아님.
export AGENT_VISION_MODEL="${AGENT_VISION_MODEL:-gemma4:latest}"  # 참조 캡션 전용(단일 참조의
  # human/nonhuman 판정에 여전히 필요). qwen3.5:9b(중국/Alibaba) 교체 유지 —
  # 같은 참조사진 A/B 캡션 실측(qwen3.5:9b/gemma4:latest/gemma3:4b) 근거, gemma4가
  # qwen과 품질 대등하고 속도 우위.
export AGENT_CAPTION_REFS="${AGENT_CAPTION_REFS:-1}"          # 1=참조 캡션 ON. shows 기반 씬↔이미지 매칭 정확도↑
export AGENT_T2I_URL="${AGENT_T2I_URL:-http://127.0.0.1:8501}"  # 정지 이미지 앵커(M2) 전용, FLUX.1-schnell
export AGENT_KOKORO_URL="${AGENT_KOKORO_URL:-http://127.0.0.1:8503}"  # S1 나레이션 전용 Kokoro
export AGENT_CHATTERBOX_URL="${AGENT_CHATTERBOX_URL:-http://127.0.0.1:8504}"  # 사용자 음성 복제 전용 Chatterbox V3
export AGENT_CHATTERBOX_NARRATION_REFERENCE="${AGENT_CHATTERBOX_NARRATION_REFERENCE:-../private/tts/voices/narrator_cc0/reference.wav}"
export AGENT_COMFYUI_URL="${AGENT_COMFYUI_URL:-http://127.0.0.1:8188}"   # Stand-In(참조-얼굴 씬)
export AGENT_USE_STANDIN="${AGENT_USE_STANDIN:-1}"     # job bfb193ba 재현: 참조 씬을 14B Stand-In(ComfyUI)으로. 0이면 generate_i2v_fallback_clip(LTX-13B-distilled, :8188)로.
export AGENT_STANDIN_STEPS="${AGENT_STANDIN_STEPS:-4}" # lightx2v distill 4~8 (bfb193ba 당시 값은 기록에 없어 기본 4 유지)
export AGENT_STANDIN_FPS="${AGENT_STANDIN_FPS:-16}"    # Wan2.1 네이티브 16fps. 24는 프레임 +50% → 클립당 ~40% 느림 + 모션 1.5x 빨라 보임(편집이 24fps로 정규화).
export AGENT_STANDIN_EXEC_TIMEOUT="${AGENT_STANDIN_EXEC_TIMEOUT:-1800}"
export AGENT_STANDIN_QUEUE_TIMEOUT="${AGENT_STANDIN_QUEUE_TIMEOUT:-86400}"
export AGENT_MAX_CONCURRENT_CLIPS="${AGENT_MAX_CONCURRENT_CLIPS:-1}"  # 씬 클립 동시 생성 상한. 1=순차(OOM안전), 2=백엔드당 하나
# fast=832x480, quality=1280x704 (해상도만 바뀜 — VIDEO_PRESETS의 steps 필드는 죽은 코드,
# tools.py 어디서도 안 읽힘). AGENT_WIDTH/AGENT_HEIGHT로 개별 덮어쓰기 가능.
export AGENT_VIDEO_PRESET="${AGENT_VIDEO_PRESET:-fast}"
export AGENT_FPS="${AGENT_FPS:-24}"          # Wan2.2-TI2V-5B 네이티브 24fps
# T2V/I2V-폴백/I2V-단발샷(전부 LTX-13B-distilled)의 실제 diffusion step 수 — 프리셋과
# 무관한 별도 변수. distilled 체크포인트라 4~8이 원 학습 레짐, job 78cb492c/4265fba0
# 퀄리티 저하 디버깅 중 12로 상향 테스트(2026-08-02).
export AGENT_LTX13B_STEPS="${AGENT_LTX13B_STEPS:-12}"

exec ./.venv/bin/python api.py
