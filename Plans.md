# Plans.md — video_generator

작성일: 2026-07-07
기준 문서: CLAUDE.md (오토메모리 anim-video-agent-langgraph.md, hunyuan-video-project.md)

---

## Week 0 — harness 도입 + 기존 코드 파악

| Task | 내용 | DoD | Acceptance | Depends | Status | GH |
|------|------|-----|------------|---------|--------|----|
| 0.1 | Harness 도입 (기존 프로젝트) | harness.toml·Plans.md·.harness/·agents/·agent-memory 존재, git 초기화됨 | test -f harness.toml && test -f Plans.md && test -d .harness && git rev-parse --git-dir | - | cc:완료 | - |
| 0.2 | 기존 코드 파악 (파이프라인 4서브시스템) | 각 서브시스템 진입점·포트·데이터흐름을 CLAUDE.md와 대조 확인, 격차 있으면 STATE.md에 기록 | - | 0.1 | cc:완료 [41d912d] | - |

---

## Week 0.5 — repo 통합 대청소 (설계: docs/superpowers/specs/2026-07-07-repo-consolidation-design.md)

| Task | 내용 | DoD | Acceptance | Depends | Status | GH |
|------|------|-----|------------|---------|--------|----|
| 0.5.1 | 하위 repo 백업 push (langgraph 5커밋, hunyuan 코드만) | 두 GitHub repo에 로컬 전체 반영, 가중치 미포함 | - | - | cc:완료 | - |
| 0.5.2 | 하위 .git 제거 → 최상위 monorepo 흡수 | git ls-files에 hunyuan_server/·langgraph/ 포함, 하위 .git 없음 | test ! -d langgraph/.git && git ls-files langgraph | grep -q graph.py | 0.5.1 | cc:완료 | - |
| 0.5.3 | 쓰레기 삭제 (venv 5.8GB·orchestrator×2·로그) | venv/·orchestrator/ 부재, 라이브 로그만 잔존 | test ! -d venv && test ! -d orchestrator | 0.5.2 | cc:완료 | - |
| 0.5.4 | openwebui/ 단일 원본화 + deploy_anim_function.sh 신설·배포 | Function 3종+스크립트 3종 존재, langgraph 복사본 삭제, OWU DB v0.2.0 반영 | test -x openwebui/deploy_anim_function.sh && test ! -f langgraph/openwebui_anim_function.py | 0.5.2 | cc:완료 | - |
| 0.5.5 | langgraph tests/·docs/·deploy/ 정리 + 회귀 검증 | 테스트 5종 tests/로 이동(sys.path 보정), driver --dry PASS | cd langgraph && ./.venv/bin/python driver.py --dry | 0.5.2 | cc:완료 | - |
| 0.5.6 | 문서 갱신 (README 신설, CLAUDE.md 경로 정정, 메모리) | 루트 README.md 존재, CLAUDE.md에 orchestrator·구경로 참조 없음 | test -f README.md | 0.5.5 | cc:완료 | - |
| 0.5.7 | OWU 배포본 기준 라이브 E2E + 발견 버그 2건 수정 | deploy 스크립트 -i 누락(DB 미주입)·/status resume 경합 수정, 4턴 멀티턴 완주+final.mp4 검증 | cd langgraph && ./.venv/bin/python tests/test_anim_function.py | 0.5.4 | cc:완료 | - |

---

## Week 1 — 안정화 (GPU 메모리 압박)

| Task | 내용 | DoD | Acceptance | Depends | Status | GH |
|------|------|-----|------------|---------|--------|----|
| 1.1 | 클립 생성 동시 실행 상한 (fan-out OOM 방지) | tools._gen_semaphore(AGENT_MAX_CONCURRENT_CLIPS, 기본1)로 node_generate_one_clip 게이팅, 유닛테스트 peak≤상한 검증, driver --dry·live PASS | cd langgraph && ./.venv/bin/python tests/test_clip_concurrency.py | 0.5.7 | cc:완료 | - |

---

## Week 2 — Day1 환경 스파이크 (게이트) [기준: docs/PRD.md]

| Task | 내용 | DoD | Acceptance | Depends | Status | GH |
|------|------|-----|------------|---------|--------|----|
| 2.1 | LocalAI 포크 클론·빌드·기동 (GB10 aarch64) [tdd:skip:build-spike] | 포크 빌드 성공, WebUI가 HTTP 응답, .harness/STATE.md에 포트·빌드법 기록 | curl -sf http://localhost:8094/ >/dev/null | 1.1 | cc:완료 [c094265] | - |
| 2.2 | Nemotron-VL-8B Ollama 서빙 가능여부 검증 [tdd:skip:model-spike] | ollama 로드+이미지 캡션 응답 성공 or Llama3.2-Vision 폴백 확정, STATE.md 기록 | - | 1.1 | cc:완료 [c094265] | - |
| 2.2.1 | Nemotron-Labs-Diffusion-VLM-8B 텍스트+캡션 단일모델 스파이크 [tdd:skip:model-spike] | GB10 네이티브 로드·S1 한국어 씬분할·이미지 캡션 실측, 역할별 채택 여부 기록 | - | 2.2, 2.3 | cc:완료 | - |
| 2.2.2 | LLM/VLM vLLM 서빙 + LTX Gemma 인코더 대체 스파이크 [tdd:skip:model-spike] | 두 Nemotron vLLM 기동·S1 출력 검증, LTX conditioning 호환성 판정 기록 | - | 2.2.1 | cc:완료 | - |
| 2.2.3 | Nemotron Nano 12B v2 VL 양자화 메모리 산정 [tdd:skip:model-spike] | BF16/FP8/NVFP4 크기·예상 피크 비교, 8~10GB 예산 적합성 판정 | - | 2.2.2 | cc:완료 | - |
| 2.3 | Nemotron-4B 한국어 씬분할 벤치 [tdd:skip:model-spike] | 한국어 스토리→씬 JSON 품질 눈판정, 미달시 Llama3.1 폴백 결정 STATE.md 기록 | - | 1.1 | cc:완료 [b8c8cd0] | - |
| 2.3.5 | T2I 모델 확정 (Flux vs SDXL vs 대안) [tdd:skip:model-spike] | GB10 실측(로드시간·생성시간·peak VRAM) 비교로 :8501 자리에 쓸 T2I 모델 1개 확정, STATE.md 기록 | - | 1.1 | cc:완료 [ad8ae4a] | - |
| 2.4 | 전 모델 상주 OOM 실측 (게이트) [tdd:skip:measure-spike] | 전 모델 동시로드 후 free 실측, 상주 가능여부·언로드 정책 STATE.md 기록 | - | 2.1, 2.2, 2.3, 2.3.5 | cc:완료 [7174bf9] | - |

---

## Week 3 — Day2 LTX 캐릭터 일관성 스파이크 (게이트) [기준: docs/PRD.md R3]

| Task | 내용 | DoD | Acceptance | Depends | Status | GH |
|------|------|-----|------------|---------|--------|----|
| 3.1 | LTX distilled + BFS노드 + Face-ID LoRA 설치·호환·라이센스 확인 [tdd:skip:integration-spike] | ComfyUI에서 워크플로 로드 성공, LoRA↔distilled 호환·라이센스 STATE.md 기록 | test -f langgraph/comfyui_workflows/ltx_faceid.json | 2.4 | cc:완료 [755b317] | - |
| 3.2 | Face-ID 얼굴+화풍 일관성 데모수준 검증 (게이트) [tdd:skip:quality-spike] | 참조얼굴로 4씬 생성, 얼굴+화풍 유지 눈판정, 미달시 Wan Stand-In 폴백 확정 STATE.md 기록 | - | 3.1 | cc:완료 [41f63ac] | - |

---

## Week 3.5 — LTX I2V 병목 프로파일링 + 경량화 (4.1과 독립 병렬 가능, 게이트 아님)

| Task | 내용 | DoD | Acceptance | Depends | Status | GH |
|------|------|-----|------------|---------|--------|----|
| 3.3 | LTX I2V 파이프라인 병목 프로파일링 (모델로드/스텝/VAE디코드 구간별 실측) [tdd:skip:benchmark] | 워크플로 1회 실행, 구간별(로드·샘플링·디코드) 소요시간 표로 STATE.md 기록 | - | 3.2 | cc:완료 [2afa3cb] | - |
| 3.4 | 경량화 파라미터 스윕 (distill LoRA weight, step 10→8, Face-ID LoRA strength 1.0→0.7~0.8, GGUF Q6_K→Q5_K_M) [tdd:skip:quality-spike] | 조합별 생성시간 실측 + 얼굴/화풍 유지 눈판정, 최소 4~5초 분량 유지, 채택 조합·기각 사유 STATE.md 기록 | - | 3.3 | cc:완료 [e4387bb] | - |
| 3.5 | Attention backend 교체 스파이크 (SageAttention3 vs 기본 PyTorch attention) [tdd:skip:benchmark] | ComfyUI 내장 sageattn3_blackwell 적용 전/후 스텝당 소요시간 비교 + 품질 동일성 눈판정 STATE.md 기록. flash-attn-4는 top-level flash_attn_func 미제공으로 ComfyUI attention.py와 드롭인 비호환 확인됨(패치 없인 채택 불가) — 이번 스파이크 대상에서 제외 | - | 3.3 | cc:완료 [8eb3ceb] | - |
| 3.6 | ComfyUI 모델 로딩 스파이크 완화 플래그 조사 (추후, 낮은 우선순위) [tdd:skip:research] | 로딩 구간 시스템메모리 스파이크 완화 CLI 플래그/옵션 조사 후 적용 전/후 재측정 STATE.md 기록 | - | 3.3 | cc:완료 [fd3321c] | - |
| 3.7 | video_generator 백엔드 완전 이전 (hunyuan_server+ComfyUI → DaolVision, 독립 repo화) [tdd:skip:repo-migration] | hunyuan_server(Wan :8500·Flux :8501·Animate)와 ComfyUI(:8188)를 DaolVision으로 이전(또는 외부 의존성으로 명시적 문서화), video_generator 코드 참조 제거, DaolVision 클론만으로 전 서비스 기동 가능. 4.1처럼 이전 전 활성 스파이크(3.3~3.6) 파일과 충돌 여부 재확인 필요 | - | 3.6 | cc:완료 [56672a0] | - |
| 3.8 | LTX-13B-distilled 단발샷 I2V (Face-ID 없이, 사진+텍스트→영상) [tdd:skip:integration-spike] | 8-step 30초대 생성 성공(4개 core/노드 호환성 블로커 해결), 눈판정 구조 정상(twin 없음). 종횡비 버그·측면/가림 구도 검증은 후속 | - | 3.3 | cc:완료 [8eb3ceb] | - |

---

## Week 4 — Day3 게이트웨이 :8700 확장 [기준: docs/Architecture.md]

| Task | 내용 | DoD | Acceptance | Depends | Status | GH |
|------|------|-----|------------|---------|--------|----|
| 4.1 | :8700 T2I 엔드포인트 (Flux/SDXL :8501 프록시) | POST /t2i가 앵커 이미지(base64/파일) 반환 | curl -sf -X POST http://localhost:8700/t2i -d '{"prompt":"test"}' | grep -qi image | 2.4 | cc:완료 [6548985] | - |
| 4.2 | :8700 영상 나레이션 TTS 엔드포인트 (Chatterbox V3 CC0 화자) | POST /tts/narration이 고정 CC0 한국어 화자로 24kHz mono WAV 반환, S1은 이 경로만 사용 | curl -sf -X POST http://localhost:8700/tts/narration -H 'Content-Type: application/json' -d '{"text":"안녕"}' --output /tmp/t.wav && test -s /tmp/t.wav | 2.4 | cc:완료 [0b5e63f] | - |
| 4.2.1 | :8700 사용자 음성 TTS 엔드포인트 (Chatterbox V3) [tdd:required] | POST /tts/clone이 text+reference WAV로 24kHz mono WAV 반환, 참조 누락시 4xx, 다른 화자 자동 폴백 없음 | cd langgraph && ./.venv/bin/python tests/test_tts_routing.py | 4.2 | cc:완료 | - |
| 4.3 | :8700 대시보드 엔드포인트 /dashboard/status | JSON에 trace·mem_used·external_calls 필드 포함 | curl -sf http://localhost:8700/dashboard/status | grep -q external_calls | 2.4 | cc:완료 [f4dad69] | - |
| 4.4 | OOM 배치 오케스트레이터 (상주/언로드 정책, 로드순서 제어) [tdd:required] | 상주·배치 모드 전환 + 로드순서 직렬화, 유닛테스트 peak 검증 | cd langgraph && ./.venv/bin/python tests/test_oom_orchestrator.py | 2.4 | cc:완료 [3c97a1d] | - |
| 4.5 | 스타일 셀렉터 프롬프트 프리픽스 주입 (시네마틱/애니/사이버펑크/로우폴리3D/클레이메이션/수채화) [tdd:required] | style→프리픽스 매핑 함수, 유닛테스트 6종 검증 | cd langgraph && ./.venv/bin/python tests/test_style_prefix.py | - | cc:완료 [b164a1f] | - |
| 4.6 | :8700 I2V 단발샷 엔드포인트 (LTX-13B-distilled, ComfyUI 프록시) | POST /i2v가 이미지+프롬프트로 영상(webp/mp4) 반환, 3.8 종횡비 버그 수정(입력 비율에 맞춰 32배수 해상도 산정) 반영 | curl -sf -X POST http://localhost:8700/i2v -F prompt=test -F image=@test.jpg | grep -qi video | 2.4, 3.8 | cc:완료 [58ebde6] | - |
---

## Week 5 — Day4 S1 파이프 (우주비행사 4씬) [기준: docs/PRD.md R2]

| Task | 내용 | DoD | Acceptance | Depends | Status | GH |
|------|------|-----|------------|---------|--------|----|
| 5.1 | 씬분할 LLM을 Nemotron-4B로 배선 (tools.call_llm) | LLM_MODEL 교체, 한국어 스토리→4씬 분할, driver --dry PASS | cd langgraph && ./.venv/bin/python driver.py --dry | 2.3, 4.4 | cc:완료 | - |
| 5.2 | LTX_FACEID 모드 분류 (사람 참조 씬만 식별, 앵커 없음) [재설계 2026-07-31] | 사람 start/ref 참조 씬만 LTX_FACEID로 분류, driver --dry PASS | cd langgraph && ./.venv/bin/python driver.py --dry && ./.venv/bin/python tests/test_ltx_faceid_batch.py | 4.1, 5.1 | cc:완료 | - |
| 5.3 | I2V 클립 LTX+Face-ID 배치 생성 (로드1회 전씬, 3.2와 동일 배선 — 앵커 lock 없음) | 배치 로드로 4클립 생성, 씬별 재로드 없음, 참조 얼굴과 육안 일치, driver --dry PASS | cd langgraph && ./.venv/bin/python driver.py --dry && ./.venv/bin/python tests/test_ltx_faceid_batch.py | 3.2, 5.2 | cc:완료 | - |
| 5.4 | TTS 나레이션 mux (경량, 나레이션>클립시 프레임홀드) [tdd:required] [skip: 5.5 선행, 5.4는 후순위] | 씬별 나레이션 concat+영상 mux, 홀드 로직 유닛테스트 | cd langgraph && ./.venv/bin/python tests/test_tts_mux.py | 4.2, 5.3 | cc:TODO | - |
| 5.5 | 승인 2게이트 챗 멀티턴 (마커패턴 이식, 자막편집 게이트 제외) | 씬분할·클립 2게이트 interrupt+챗 resume, 회귀 PASS | cd langgraph && ./.venv/bin/python tests/test_anim_function.py | 5.3 | cc:완료 [63abf1c] | - |

---

## Week 6 — Day5 S2 + LocalAI 프론트 배선 [기준: docs/PRD.md R4·R5·R6]

| Task | 내용 | DoD | Acceptance | Depends | Status | GH |
|------|------|-----|------------|---------|--------|----|
| 6.1 | S2 Flux Kontext 6스타일 (4.5 style_presets.py 재사용: cinematic/anime/cyberpunk/lowpoly/claymation/watercolor, 신규 정의 안 함) | 얼굴사진→6스타일 이미지 출력, :8700 /i2i 엔드포인트가 style_prefix() 그대로 호출 | curl -sf -X POST http://localhost:8700/i2i -F style=cinematic -F image=@test.jpg | grep -qi image | 4.1, 4.5 | cc:완료 [a6e5e3b] | - |
| 6.2 | S2→S1 캐릭터 연결 (우주비행사 결과가 S1 Face-ID ref로 진입) | S2 출력이 S1 job ref_images로 전달, driver --dry PASS | cd langgraph && ./.venv/bin/python driver.py --dry | 6.1, 5.2 | cc:완료 [920befb] | - |
| 6.3 | LocalAI 프론트 5카테고리(Agent/I2V 단발샷/I2I/TTS/T2I) → :8700 배선 (API 콜 리라이트. 2026-08-01 사용자 지시로 독립 T2I 카테고리 재추가 — 2026-07-31 폐지 결정을 뒤집음) [tdd:skip:frontend-wiring] | Agent의 영상 나레이션은 /tts/narration, 독립 TTS 카테고리는 /tts/clone, I2V 단발샷 카테고리는 /i2v, I2I는 /i2i, T2I는 /t2i에 도달하고 LocalAI 추론백엔드 미사용 | - | 2.1, 4.1, 4.2, 4.2.1, 4.6 | cc:완료 [818cb9d] | - |
| 6.4 | Agent 노드 스텝퍼 컴포넌트 (phase→스텝 하이라이트) [tdd:skip:ui-component] | phase 값으로 5스텝 하이라이트 렌더, 챗 위 표시 | - | 6.3, 5.5 | cc:완료 [5766929] | - |
| 6.5 | Wan2.2(:8500, 중국원산) 백엔드 완전 제거 → T2V/I2V 폴백을 LTX-13B-distilled(:8188)로 통합 (docs/model-selection.md 비중국 원산 원칙 위반 해소, [[Duplicate, don't migrate]]) | call_video/WAN_URL 삭제, 신규 모델 다운로드 없음, driver --dry PASS, 유닛테스트 PASS, 라이브 job 1회 실측(이미지 없는 씬 포함) | cd langgraph && ./.venv/bin/python tests/test_wan_removal.py && ./.venv/bin/python driver.py --dry | 4.6 | cc:완료 [f6ac142] | - |
| 6.6 | Agent 씬분할 승인 게이트(1-4) 리뷰 UI (job 78cb492c 확인 중 원클릭 블라인드 승인만 있고 씬 내용 미표시 발견) [tdd:skip:ui-component] | checkpoint.scenes 렌더(텍스트/mood/duration/피사체타입/매칭이미지), 승인 또는 스토리 수정 후 재분할(revised_script_text) 지원 | - | 6.3 | cc:완료 [286f603] | - |
| 6.7 | 씬 프롬프트 LLM의 style_bible 중복 에코 버그 수정 (job 78cb492c 영상 퀄리티 저하 원인 — 최종 프롬프트 절반이 스타일 문구 중복) [tdd:skip:post-hoc-diagnostic-fix — 실 LLM 호출로 버그 재현·수정 확인 후 회귀테스트 작성, red-first 아님] | _scene_prompt_system에 반복금지 지시 추가 + _strip_echoed_bible()로 중복 제거, 유닛테스트 3종 PASS | cd langgraph && ./.venv/bin/python tests/test_strip_echoed_bible.py | 5.1 | cc:완료 [b3ae916] | - |
| 6.8 | Agent 클립승인 게이트(3-5) clip_url 노출 + 리뷰 UI (job 4265fba0 확인 중 발견 — checkpoint.scenes가 호스트 절대경로 clip_path만 줘서 프론트가 클립을 아예 못 보여주고 원클릭 approve_all만 있었음) [tdd:skip:ui-component] | api.py `_checkpoint_for_client()`가 clip_url(/files/...) 보강, AgentClipPreview가 클립 재생+quality_flag 표시+씬별 재생성(action:regenerate) 지원 | cd langgraph && ./.venv/bin/python tests/test_checkpoint_clip_url.py | 6.6 | cc:완료 [c160795, 44b816c] | - |
| 6.9 | 씬 프롬프트의 인물 환각 + 화풍 표류 버그 수정 (job 4265fba0 — subject_type=nonhuman(인물 없는 씬)인데도 "a lone figure" 등 임의 인물 생성, 앵커·Face-ID 둘 다 없는 순수 T2V job은 style_bible이 flat vector/2D로 표류) [tdd:skip:post-hoc-diagnostic-fix — 실 LLM 호출로 재현·수정 확인, red-first 아님] | has_human_subject=False면 인물 묘사 지시를 금지 지시로 반전, 앵커/Face-ID 둘 다 없으면 style_bible이 photoreal cinematic 기본값 채택. 유닛테스트 3종 PASS, 실 LLM 호출로 두 버그 각각 재현·수정 확인 | cd langgraph && ./.venv/bin/python tests/test_scene_prompt_subject.py | 6.7 | cc:완료 [c160795] | - |
| 6.10 | Agent 완료/재시작 버튼 (완료 후 dead-end, 진행 중 job 포기 수단 없음 발견) [tdd:skip:ui-component] | job_id 옆 상시 "새로 시작"(진행중이면 cancelJob) 버튼, status==done시 "새 영상 만들기" CTA | - | 6.8 | cc:완료 [39f99ba] | - |
| 6.11 | VIDEO_PRESETS steps 죽은코드 발견 + AGENT_LTX13B_STEPS 노출 (quality/fast 프리셋이 steps:10/20을 정의하지만 tools.py 어디서도 안 읽음 — 실제 step 수는 별도 AGENT_LTX13B_STEPS, 기본 8, run_agent.sh에 노출 안 돼 있었음) [tdd:skip:config-tuning] | run_agent.sh에 AGENT_LTX13B_STEPS export 추가(8→12 테스트), 오해 소지 있던 프리셋 주석 정정 | - | 6.9 | cc:완료 [4bd7048] | - |
| 6.12 | LTX Face-ID 해상도 오버라이드(1024x576)가 identity 붕괴 원인으로 확정 (job 0c0e972b/003cb843 vs baseline LTX_2.3_ia2v_0000{1-4} 프레임 비교 + node 129 `match_target` 소스 분석 — 정사각 참조를 와이드 타겟에 크롭하며 얼굴 손실. 같은 프롬프트·시드로 768x768 재현 스크립트 돌려 identity 복구 확인) [tdd:skip:post-hoc-diagnostic-fix] | LTX_FACEID_WIDTH/HEIGHT 기본값 1024x576→768x768(baseline과 동일), ffmpeg_concat 주석 정정 | - | 6.9 | cc:완료 | - |
| 6.13 | Ollama LLM 콜 num_ctx 미지정으로 콜당 수십초 오버헤드 (call_llm/caption_image가 options 없이 호출 → 모델 기본 컨텍스트(Nemotron 1,048,576 / qwen3.5:9b 262,144 토큰) 기준 KV캐시 할당. job 003cb843 anchoring 단계 7콜 순차 실행에 5분31초, 콜당 평균 47초 실측) [tdd:skip:config-tuning] | 두 호출 모두 `options: {num_ctx: 8192}` 추가 | - | 6.11 | cc:완료 | - |
| 6.14 | VISION_MODEL qwen3.5:9b(중국·Alibaba 원산) → gemma4:latest 교체 (model-selection.md "비중국 원산" 원칙 위반 발견, [[Wan2.2 removed from DaolVision]]과 동일 사유) [tdd:skip:model-swap] | 같은 참조사진 caption_image A/B 실측(qwen3.5:9b/gemma4:latest/gemma3:4b/exaone3.5:7.8b — exaone은 vision capability 없어 탈락) 근거로 gemma4:latest 채택(qwen 대비 품질 대등·속도 우위), run_agent.sh 기본값 교체 | - | 6.13 | cc:완료 | - |
| 6.15 | Agent UI에 M2(이미지 설명으로 생성) 입력 분기 없음 + 2-3 체크포인트 자동승인이라 생성 이미지 리뷰 불가 (GatewayAgent.jsx — script_text/ref_images 파일첨부만 있고 image_request 미배선, `autoDecisionFor`가 `2-3` 체크포인트 무조건 자동승인) [tdd:skip:ui-component] | "사진 첨부" vs "이미지 설명으로 생성" 입력 분기 UI + 2-3용 AgentScenePreview류 프리뷰 컴포넌트(생성 이미지 확인 후 승인/재생성) | - | 6.6, 6.8 | cc:TODO | - |
| 6.16 | 씬분할 LLM(Nemotron 3 Nano 4B)이 matched_image/subject_type을 비결정적으로 오판 (job 67c45bcb-44e2-47d1-b8a9-0aa436289918 — 동일 입력 3회 재현 시 matched_image 대부분 null, 동일 씬 텍스트인데 subject_type이 human/nonhuman/none으로 매 콜 달라짐, text 필드 한글 오타 환각까지 확인) [tdd:skip:model-swap] | LLM_MODEL을 VISION_MODEL과 동일한 gemma4:latest로 통일(text+vision 겸용, 추가 로드 0), Nemotron 4B는 씬분할 용도로 폐기, model-selection-llm.md에 재현 증거 기록 | - | 6.14 | cc:완료 | - |
| 6.17 | 6.16의 gemma4:latest 교체 후에도 matched_image/subject_type 비결정성 재현(완화만 됨, 미해소) — 근본 원인이 모델 용량이 아니라 "LLM이 씬↔참조이미지 매칭을 판단"하는 구조 자체임을 확인 [tdd:required] | `node_split_scenes`에 단일 참조 결정론적 매칭 추가(참조 1장이면 LLM 판단 무시하고 전 씬에 강제 매칭 + 캡션 기반 human/nonhuman 1회 판정), LLM_MODEL은 Nemotron 3 Nano 4B로 롤백(더는 이 약점이 문제 안 됨), 기존 유닛테스트 전부 PASS 확인 | cd langgraph && ./.venv/bin/python tests/test_nemotron_scene_split.py && ./.venv/bin/python tests/test_scene_anchors.py | 6.16 | cc:완료 | - |

---

## Week 7 — Day6 자립 대시보드 + 벤치 + 녹화 [기준: docs/PRD.md R9]

| Task | 내용 | DoD | Acceptance | Depends | Status | GH |
|------|------|-----|------------|---------|--------|----|
| 7.1 | 자립 대시보드 UI (배지 3종 + 실행트레이스 + 메모리게이지) [tdd:skip:ui-component] | 3위젯 렌더, /dashboard/status 폴링 표시 | - | 4.3, 6.3 | cc:완료 [e528f2b] | - |
| 7.2 | External calls:0 실측 (ss 아웃바운드 폴링) [tdd:required] | 아웃바운드 카운터 함수, 유닛테스트(로컬only=0) | cd langgraph && ./.venv/bin/python tests/test_external_calls.py | 4.3 | cc:완료 [e5d1206] | - |
| 7.3 | Cosmos-Predict2-2B I2V 벤치 [tdd:skip:benchmark] | (2026-07-31 판정: 공식 모델카드 확인 결과 identity 보존 기능 없어 I2V 용도 최종 제외, docs/spikes/3.8 참고 — 이 태스크는 채택 불가로 종료) | - | 3.2 | cc:완료 [8eb3ceb] | - |
| 7.6 | T2V 단발샷 카테고리 스파이크 (Cosmos-Predict2-2B/Cosmos 3 Nano, 추후·낮은 우선순위) [tdd:skip:benchmark] | Cosmos-Predict2-2B(2B)와 Cosmos 3 Nano(16B, 2026-06-01 출시, 8B dense 트랜스포머 기반. bf16 weight만 ~32GB로 GB10 119GB엔 수치상 들어가나 ARM64+Blackwell 커널 호환 미검증. Qwen3-VL 8B 아키텍처 기반이라 R10 국적 배점 계보상 애매하지만 identity 불필요한 순수 T2V 용도라 무방) 둘 다 단발샷 생성 실측·비교, model-selection-t2v.md 신설·기록 | - | 3.8 | cc:TODO | - |
| 7.4 | Chatterbox V3 사용자 음성 E2E 청취 검증 [tdd:skip:asset-gen] | 업로드 참조 음성으로 생성한 한국어 clone이 기본 음성 대조군보다 화자 유사도가 높고 출력 WAV 보존 | test -s out/tts/chatterbox/my_voice/clone_test_listen.wav | 4.2.1 | cc:완료 | - |
| 7.5 | 시나리오 녹화 (S1·S2 백업본) [tdd:skip:asset-gen] | S1·S2 녹화 mp4 확보(라이브 실패 백업) | ls out/demo_*.mp4 | grep -q mp4 | 5.5, 6.2 | cc:TODO | - |

---

## Week 8 — Day7 마무리 (리허설·재현·문서) [기준: docs/PRD.md 성공기준]

| Task | 내용 | DoD | Acceptance | Depends | Status | GH |
|------|------|-----|------------|---------|--------|----|
| 8.1 | 라이브 리허설 + 폴백 사다리 점검 [tdd:skip:rehearsal] | 오프라인 E2E(S2→S1) 완주, 폴백 경로 각 1회 검증, STATE.md 기록 | - | 7.1, 7.5 | cc:TODO | - |
| 8.2 | 재현 스크립트 (클론→기동 한방) | scripts로 전 서비스 기동, 실행권한 | test -x scripts/start_studio.sh | 8.1 | cc:TODO | - |
| 8.2.1 | 모델 서버 OpenShell 샌드박스 격리 (Ollama/ComfyUI:8188/T2I:8501/Kokoro:8503/Chatterbox:8504 각 `--gpu` 샌드박스 + `forward`로 기존 localhost 포트 유지, tools.py 코드 변경 없음) | 5종 서비스 전부 openshell sandbox에서 기동, 기존 AGENT_*_URL localhost:PORT로 그대로 응답, driver.py --dry PASS | openshell sandbox list \| grep -c Ready \| grep -q 5 && cd langgraph && ./.venv/bin/python driver.py --dry | 8.2 | cc:TODO | - |
| 8.3 | README 갱신 (오픈셸 구성·기동법·국적표) [tdd:skip:docs-only] | README에 스튜디오 구성·기동·모델국적표 반영 | grep -qi openshell README.md | 8.2.1 | cc:TODO | - |

---

<!--
Task Status 마커:
  cc:TODO   — 미시작
  cc:WIP    — 진행 중 (harness가 자동 설정)
  cc:완료   — 완료 (harness가 자동 설정)

GH 컬럼:
  -         — GitHub 미연동 또는 이슈 미생성
  #N        — 연결된 GitHub Issue 번호 (harness-plan이 자동 기입)

Acceptance 컬럼:
  -         — 기계 검증 없음 (skip). "|| echo skip"처럼 항상 성공하는
              패턴은 oracle을 무력화하므로 금지 — 검증 안 할 거면 "-"로 명시.
  명령어     — PR 오픈 시 plans-guard CI가 실행, 실패하면 PR 차단.
              CI checkout 범위 밖 경로(예: ../다른-repo/)는 실행 불가 — 금지.
  예시: pytest tests/test_auth.py -k login
  예시: curl -sf http://localhost/health | grep '"status":"ok"'
  패턴별 예시:
    파일 존재: test -f src/main.py
    명령 성공: npm run build 2>&1 | grep -v error
    HTTP 응답: curl -sf http://localhost:3000/health | grep ok
    테스트 통과: pytest tests/ -x -q
    출력 포함: go test ./... | grep -v SKIP
  escaped pipe(예: grep 'a\|b')는 Acceptance 컬럼에서만 사용 — DoD 등 다른
  컬럼에 쓰면 파서가 열 개수를 오인식한다.
  * 스택 설치(npm ci 등)는 .github/workflows/plans-guard.yml 상단 주석 해제

DoD (Definition of Done) 작성 원칙:
  - 검증 가능한 파일·명령·출력으로 기술
  - "존재한다", "성공한다", "에러 0"처럼 객관적 기준
  - "잘 작성된다", "좋다"처럼 주관적 기준 금지
-->
