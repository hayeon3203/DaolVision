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
| 2.3 | Nemotron-4B 한국어 씬분할 벤치 [tdd:skip:model-spike] | 한국어 스토리→씬 JSON 품질 눈판정, 미달시 Llama3.1 폴백 결정 STATE.md 기록 | - | 1.1 | cc:TODO | - |
| 2.3.5 | T2I 모델 확정 (Flux vs SDXL vs 대안) [tdd:skip:model-spike] | GB10 실측(로드시간·생성시간·peak VRAM) 비교로 :8501 자리에 쓸 T2I 모델 1개 확정, STATE.md 기록 | - | 1.1 | cc:완료 | - |
| 2.4 | 전 모델 상주 OOM 실측 (게이트) [tdd:skip:measure-spike] | 전 모델 동시로드 후 free 실측, 상주 가능여부·언로드 정책 STATE.md 기록 | - | 2.1, 2.2, 2.3, 2.3.5 | cc:TODO | - |

---

## Week 3 — Day2 LTX 캐릭터 일관성 스파이크 (게이트) [기준: docs/PRD.md R3]

| Task | 내용 | DoD | Acceptance | Depends | Status | GH |
|------|------|-----|------------|---------|--------|----|
| 3.1 | LTX distilled + BFS노드 + Face-ID LoRA 설치·호환·라이센스 확인 [tdd:skip:integration-spike] | ComfyUI에서 워크플로 로드 성공, LoRA↔distilled 호환·라이센스 STATE.md 기록 | test -f langgraph/comfyui_workflows/ltx_faceid.json | 2.4 | cc:TODO | - |
| 3.2 | Face-ID 얼굴+화풍 일관성 데모수준 검증 (게이트) [tdd:skip:quality-spike] | 참조얼굴로 4씬 생성, 얼굴+화풍 유지 눈판정, 미달시 Wan Stand-In 폴백 확정 STATE.md 기록 | - | 3.1 | cc:TODO | - |

---

## Week 4 — Day3 게이트웨이 :8700 확장 [기준: docs/Architecture.md]

| Task | 내용 | DoD | Acceptance | Depends | Status | GH |
|------|------|-----|------------|---------|--------|----|
| 4.1 | :8700 T2I 엔드포인트 (Flux/SDXL :8501 프록시) | POST /t2i가 앵커 이미지(base64/파일) 반환 | curl -sf -X POST http://localhost:8700/t2i -d '{"prompt":"test"}' | grep -qi image | 2.4 | cc:TODO | - |
| 4.2 | :8700 TTS 엔드포인트 (Kokoro 서버 프록시) | POST /tts가 한국어 wav 반환 | curl -sf -X POST http://localhost:8700/tts -d '{"text":"안녕"}' --output /tmp/t.wav && test -s /tmp/t.wav | 2.4 | cc:TODO | - |
| 4.3 | :8700 대시보드 엔드포인트 /dashboard/status | JSON에 trace·mem_used·external_calls 필드 포함 | curl -sf http://localhost:8700/dashboard/status | grep -q external_calls | 2.4 | cc:TODO | - |
| 4.4 | OOM 배치 오케스트레이터 (상주/언로드 정책, 로드순서 제어) [tdd:required] | 상주·배치 모드 전환 + 로드순서 직렬화, 유닛테스트 peak 검증 | cd langgraph && ./.venv/bin/python tests/test_oom_orchestrator.py | 2.4 | cc:TODO | - |
| 4.5 | 스타일 셀렉터 프롬프트 프리픽스 주입 (시네마틱/애니/픽셀/사이버펑크) [tdd:required] | style→프리픽스 매핑 함수, 유닛테스트 4종 검증 | cd langgraph && ./.venv/bin/python tests/test_style_prefix.py | - | cc:TODO | - |

---

## Week 5 — Day4 S1 파이프 (우주비행사 4씬) [기준: docs/PRD.md R2]

| Task | 내용 | DoD | Acceptance | Depends | Status | GH |
|------|------|-----|------------|---------|--------|----|
| 5.1 | 씬분할 LLM을 Nemotron-4B로 배선 (tools.call_llm) | LLM_MODEL 교체, 한국어 스토리→4씬 분할, driver --dry PASS | cd langgraph && ./.venv/bin/python driver.py --dry | 2.3, 4.4 | cc:TODO | - |
| 5.2 | 앵커 생성 Flux + Face-ID 참조(우주비행사) 전달 | 씬별 앵커 생성 + 캐릭터 참조 첨부, driver --dry PASS | cd langgraph && ./.venv/bin/python driver.py --dry | 4.1, 5.1 | cc:TODO | - |
| 5.3 | I2V 클립 LTX+Face-ID 배치 생성 (로드1회 전씬) | 배치 로드로 4클립 생성, 씬별 재로드 없음, driver --dry PASS | cd langgraph && ./.venv/bin/python driver.py --dry | 3.2, 5.2 | cc:TODO | - |
| 5.4 | TTS 나레이션 mux (경량, 나레이션>클립시 프레임홀드) [tdd:required] | 씬별 나레이션 concat+영상 mux, 홀드 로직 유닛테스트 | cd langgraph && ./.venv/bin/python tests/test_tts_mux.py | 4.2, 5.3 | cc:TODO | - |
| 5.5 | 승인 3게이트 챗 멀티턴 (마커패턴 이식) | 씬분할·클립·자막편집 3게이트 interrupt+챗 resume, 회귀 PASS | cd langgraph && ./.venv/bin/python tests/test_anim_function.py | 5.4 | cc:TODO | - |

---

## Week 6 — Day5 S2 + LocalAI 프론트 배선 [기준: docs/PRD.md R4·R5·R6]

| Task | 내용 | DoD | Acceptance | Depends | Status | GH |
|------|------|-----|------------|---------|--------|----|
| 6.1 | S2 Flux Kontext 4스타일 (애니/유화초상화/프로필/우주비행사) | 얼굴사진→4스타일 이미지 출력, :8700 /i2i 엔드포인트 | curl -sf -X POST http://localhost:8700/i2i -F style=astronaut -F image=@test.jpg | grep -qi image | 4.1 | cc:TODO | - |
| 6.2 | S2→S1 캐릭터 연결 (우주비행사 결과가 S1 Face-ID ref로 진입) | S2 출력이 S1 job ref_images로 전달, driver --dry PASS | cd langgraph && ./.venv/bin/python driver.py --dry | 6.1, 5.2 | cc:TODO | - |
| 6.3 | LocalAI 프론트 4카테고리 → :8700 배선 (API 콜 리라이트) [tdd:skip:frontend-wiring] | 4카테고리 요청이 :8700 도달, LocalAI 추론백엔드 미사용 | - | 2.1, 4.1, 4.2 | cc:TODO | - |
| 6.4 | Agent 노드 스텝퍼 컴포넌트 (phase→스텝 하이라이트) [tdd:skip:ui-component] | phase 값으로 5스텝 하이라이트 렌더, 챗 위 표시 | - | 6.3, 5.5 | cc:TODO | - |

---

## Week 7 — Day6 자립 대시보드 + 벤치 + 녹화 [기준: docs/PRD.md R9]

| Task | 내용 | DoD | Acceptance | Depends | Status | GH |
|------|------|-----|------------|---------|--------|----|
| 7.1 | 자립 대시보드 UI (배지 3종 + 실행트레이스 + 메모리게이지) [tdd:skip:ui-component] | 3위젯 렌더, /dashboard/status 폴링 표시 | - | 4.3, 6.3 | cc:TODO | - |
| 7.2 | External calls:0 실측 (ss 아웃바운드 폴링) [tdd:required] | 아웃바운드 카운터 함수, 유닛테스트(로컬only=0) | cd langgraph && ./.venv/bin/python tests/test_external_calls.py | 4.3 | cc:TODO | - |
| 7.3 | Cosmos-Predict2-2B 벤치 (비교기록) [tdd:skip:benchmark] | 같은 프롬프트 Cosmos I2V 샘플 생성, LTX와 비교 STATE.md 기록 | - | 3.2 | cc:TODO | - |
| 7.4 | TTS 4모델 한국어 샘플 생성 (자막편집 미리듣기용) [tdd:skip:asset-gen] | Kokoro/Zonos/CosyVoice2/Metis 샘플 wav 4종 생성 | ls langgraph/assets/tts_samples/*.wav | grep -q wav | 4.2 | cc:TODO | - |
| 7.5 | 시나리오 녹화 (S1·S2 백업본) [tdd:skip:asset-gen] | S1·S2 녹화 mp4 확보(라이브 실패 백업) | ls out/demo_*.mp4 | grep -q mp4 | 5.5, 6.2 | cc:TODO | - |

---

## Week 8 — Day7 마무리 (리허설·재현·문서) [기준: docs/PRD.md 성공기준]

| Task | 내용 | DoD | Acceptance | Depends | Status | GH |
|------|------|-----|------------|---------|--------|----|
| 8.1 | 라이브 리허설 + 폴백 사다리 점검 [tdd:skip:rehearsal] | 오프라인 E2E(S2→S1) 완주, 폴백 경로 각 1회 검증, STATE.md 기록 | - | 7.1, 7.5 | cc:TODO | - |
| 8.2 | 재현 스크립트 (클론→기동 한방) | scripts로 전 서비스 기동, 실행권한 | test -x scripts/start_studio.sh | 8.1 | cc:TODO | - |
| 8.3 | README 갱신 (오픈셸 구성·기동법·국적표) [tdd:skip:docs-only] | README에 스튜디오 구성·기동·모델국적표 반영 | grep -qi openshell README.md | 8.2 | cc:TODO | - |

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
