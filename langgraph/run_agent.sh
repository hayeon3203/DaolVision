#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
export AGENT_API_HOST="${AGENT_API_HOST:-0.0.0.0}"
export AGENT_API_PORT="${AGENT_API_PORT:-8700}"
export AGENT_OLLAMA_URL="${AGENT_OLLAMA_URL:-http://127.0.0.1:11434/api/chat}"
export AGENT_LLM_MODEL="${AGENT_LLM_MODEL:-gemma3:4b}"
  # 2026-08-13 최종: gemma3:4b(Google, 3.3GB, 비중국 원산).
  # A/B(tests/probe_llm_ab_scene_split.py) 실측 — 같은 시나리오 4씬 기준:
  #   Nemotron 4B  : setting 1/4만 추출, 나머지는 "어두운 사무실"·"버스 스테이션" 환각.
  #                  "코트"를 coat(외투)로 오역, 농구장→soccer field/football pitch.
  #   exaone3.5:32b: 오역 없음, setting은 씬1만 추출(나머지 폴백). 전체 소요 수 분 +
  #                  21.6GB 상주가 FLUX 콜드로드를 압박해 T2I 서버가 내려감(job a817cfc4).
  #   gemma4:latest: setting 4/4 전부 빈 값, 장소가 실내 체육관·공원으로 표류.
  #   gemma3:4b    : setting 4/4 추출 성공, 오역 없음, 전체 71초. 채택.
  # 아래는 교체 이력(참고):
  # 2026-08-13: Nemotron 3 Nano 4B → exaone3.5:32b(LG AI, 한국어 특화, 비중국 원산).
  # 4B가 한국어 원문을 지키지 못하는 게 배경 불일치의 직접 원인이었다(UI E2E job
  # 1a0d85b1 실측): "코트"를 coat(외투)로 오역해 "one side of the coat"를 쓰고,
  # 농구장을 soccer field/football pitch로 바꾸고, 음료수를 a glass of water로 바꿨다.
  # 장소 추출은 더 나빠서 시나리오에 없는 "어두운 사무실"·"버스 스테이션"을 환각했다.
  # exaone은 같은 시나리오에서 4씬 전부 setting=농구장을 뽑았고 오역이 없었다
  # (tests/probe_llm_ab_scene_split.py A/B). 19.3GB로 ComfyUI와 동거 가능.
export AGENT_LLM_KEEP_RESIDENT="${AGENT_LLM_KEEP_RESIDENT:-1}"
  # gemma3:4b는 3.3GB라 상주해도 FLUX/ComfyUI를 압박하지 않는다(원래 이 정책이 전제한
  # 크기). 상주를 켜면 LLM 호출 7~8회의 재로드 비용이 사라진다. 아래는 32B를 쓰던
  # 동안 껐던 이력(참고):
  # 2026-08-13: 1 → 0. 상주 정책은 씬분할 LLM이 Nemotron 4B(2.8GB)일 때 세운 것인데
  # exaone3.5:32b는 21.6GB를 영구 점유한다(ollama /api/ps 실측). 그 상태에서 FLUX
  # 콜드 로드가 157초까지 늘어졌고 응답 직후 T2I 서버가 내려가 다음 호출이 연결
  # 거부를 맞았다(job a817cfc4, flux.service restart counter 2). LLM은 씬분할·프롬프트
  # 단계에서만 쓰이고 그 뒤로는 이미지·영상 생성이 이어지므로 상주 이득보다 점유
  # 손해가 크다. 대신 LLM 호출마다 재로드 비용이 붙는다.
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
# 씬 개수. 씬분할 LLM 프롬프트·교정 재요청·정규화가 모두 이 값을 공유한다.
# 5 = 인물 4씬 + 마무리 히어로컷(제품 단독) 1씬. 클립당 8~10분이라 job 시간이 그만큼 는다.
export AGENT_SCENE_COUNT="${AGENT_SCENE_COUNT:-5}"
# fast=832x480, quality=1280x704 (해상도만 바뀜 — VIDEO_PRESETS의 steps 필드는 죽은 코드,
# tools.py 어디서도 안 읽힘). AGENT_WIDTH/AGENT_HEIGHT로 개별 덮어쓰기 가능.
export AGENT_VIDEO_PRESET="${AGENT_VIDEO_PRESET:-quality}"
  # 2026-08-13: fast(832x480) → quality(1280x704). Face-ID 경로는 자체 상수
  # (LTX_FACEID_WIDTH/HEIGHT=1280x704)를 쓰는데 조립·I2V 경로만 이 프리셋을 따르므로,
  # fast로 두면 한 광고 안에서 씬마다 해상도가 달라진다(UI E2E job 00a21ee8 실측:
  # clip1=1280x704, clip2=832x480). 스파이크 확정본도 전부 quality로 만들었다.
export AGENT_FPS="${AGENT_FPS:-24}"          # Wan2.2-TI2V-5B 네이티브 24fps
# T2V/I2V-폴백/I2V-단발샷(전부 LTX-13B-distilled)의 실제 diffusion step 수 — 프리셋과
# 무관한 별도 변수. distilled 체크포인트의 원 학습 레짐(4~8) 상단인
# 8 steps를 기본으로 사용한다.
export AGENT_LTX13B_STEPS="${AGENT_LTX13B_STEPS:-8}"

# 사용자 첫 요청 전에 Nemotron을 Ollama에 적재한다. call_llm도 keep_alive=-1을
# 반복해서 보내며, tools.py의 backend 전환 훅은 이 모델을 언로드하지 않는다.
# 전체 resident 모드를 켜는 것이 아니라 작은 씬분할 LLM 하나만 상주시켜 기존
# LLM→I2V/TTS 직렬화와 대형 모델 언로드 정책은 그대로 유지한다.
if [ "$AGENT_LLM_KEEP_RESIDENT" = "1" ]; then
  ollama_base="${AGENT_OLLAMA_URL%/api/chat}"
  warmup_body="$(printf '{"model":"%s","keep_alive":-1,"options":{"num_ctx":8192}}' "$AGENT_LLM_MODEL")"
  curl -fsS --max-time 300 \
    -H 'Content-Type: application/json' \
    --data-binary "$warmup_body" \
    "$ollama_base/api/generate" >/dev/null
fi

exec ./.venv/bin/python api.py
