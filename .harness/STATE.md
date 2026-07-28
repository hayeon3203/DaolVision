# STATE.md — DaolVision 현재 상태 스냅샷

> 세션이 언제 끊겨도 이 파일 하나로 "지금 어디까지 왔는지"를 복원한다.
> 작업 시작 전·작업 단위 종료 후마다 갱신. Task 상태의 단일 출처는 Plans.md.

## repo 구성 (필독)

- **DaolVision**(이 repo, github.com/hayeon3203/DaolVision, private) = 오픈셸 자립형
  생성 스튜디오. 기획·문서·**신규 코드**(LocalAI 포크 프론트, 스텝퍼/대시보드,
  게이트웨이 확장) + 스파이크 기록의 집.
- **백엔드 코드는 별도 repo `video_generator`**(hunyuan_server :8500, langgraph :8700,
  ComfyUI :8188 등)에 있고 **그대로 유지**. DaolVision은 이를 **HTTP로 소비**
  (Architecture "기존 LangGraph API 확장" 원칙). 코드 이전 안 함.
- 스파이크용 LocalAI 클론은 `/home/admin/LocalAI`(untracked).

## 현재 목표

Week 2 Day1 환경 스파이크(게이트) 진행 중. 2.1·2.2 완료, 2.3 다음.

## Task 2.1 — LocalAI 스파이크 (2026-07-28, cc:완료)

**목표**: LocalAI 포크가 GB10(aarch64)에서 빌드·기동되는지 게이트 검증. 포크는
프론트 껍데기만 사용(추론 백엔드 미사용) — PRD 결정 2026-07-28.

- **포트: 8094** (LocalAI 기본 8080은 open-webui 컨테이너 상주, 8090은
  waferscope-nginx 상주 — 둘 다 이미 점유. 8094가 첫 빈 포트).
- **클론**: `git clone --depth1 mudler/LocalAI` → `/home/admin/LocalAI`
  (commit c4d0c06, 72M).
- **프론트 빌드법** (우리가 실제 포크할 대상): React SPA.
  `cd LocalAI/core/http/react-ui && npm install && npm run build` → `dist/` 4.6M,
  vite build 284ms **성공**(node 24, aarch64). Go 바이너리는 `dist/`를
  `go:embed react-ui/dist/*`로 임베드(app.go:47).
- **런타임 기동법**: 소스 Go 빌드는 Go 1.26+protoc 필요(미설치)라, 껍데기 스파이크
  범위상 공식 GB10-네이티브 이미지로 기동:
  `docker run -d --name localai-spike -p 8094:8080 localai/localai:master-nvidia-l4t-arm64`
  (nvidia-l4t-arm64 = Grace-Blackwell/Tegra arm64용 태그).
- **검증**: `curl -sf http://localhost:8094/` → 301 `/app`(React SPA,
  `<title>LocalAI</title>`), `/readyz` 200, `/v1/models` → `{"data":[]}`. 컨테이너
  healthy. **Acceptance PASS**.
- **사이드바 카테고리 추가/제거 지점**(6.3용):
  `LocalAI/core/http/react-ui/src/components/console/consoleConfig.js` 항목 배열
  편집 후 `npm run build`.

**⚠️ 게이트 발견 — PRD/Architecture 전제 갱신 필요**:
1. **UI 스택이 바뀜**: PRD/Architecture는 "Go템플릿+Alpine"이라 적혔으나 현 LocalAI는
   **React SPA**(vite, `core/http/react-ui/`, `go:embed`). → 6.3(4카테고리
   :8700 배선)·6.4(노드 스텝퍼 주입)은 Alpine이 아니라 **React 컴포넌트 수정**
   작업. docs/PRD.md·docs/Architecture.md 갱신 필요.
2. **8080 포트 충돌**: open-webui가 8080 상주 → LocalAI는 8094 사용. Plans.md
   2.1 Acceptance를 `:8080`→`:8094`로 정정함.
3. 추론 백엔드는 기동 안 함(모델 0개) — 껍데기 프론트만 확인. GPU 미사용.

**정리(상시 상주 여부 미정)**: `docker rm -f localai-spike`로 내림. 재기동은 위 한 줄.

## Task 2.2 — 이미지 캡션 VL 모델 검증 (2026-07-28, cc:완료)

상세 근거·재현법·실패이유는 [docs/spikes/2.2-vl-caption-models.md](../docs/spikes/2.2-vl-caption-models.md).

- **Nemotron-VL-8B: 최종 배제**. ollama는 RADIO 비전인코더 미지원(레지스트리에도
  없음). transformers 네이티브도 5.12 vs 모델 커스텀코드(옛 4.4x) 비호환
  (`all_tied_weights_keys`). 다운그레이드는 :8500 깨져 불가. 17GB 캐시 rm.
- **llama3.2-vision:11b(계획 폴백): 로드 실패** — ollama가 `mllama` arch 미지원(500). rm.
- **최종 확정: gemma4:latest**(9.6GB, ollama). 실증 HTTP 200, gemma3:4b보다 상세.
  gemma3:4b는 경량 폴백 유지. 5.x 배선시 캡션 = gemma4:latest.
- **NVIDIA는 텍스트 레이어에만 깔끔**: Nemotron-3-Nano-4B-GGUF(2.84GB, GGUF)는
  ollama 직행 가능 → **2.3 씬분할 후보**로 이월(ollama의 Mamba2-하이브리드 arch
  지원 재확인 필요).

## 차단 요소

- 없음

## 최종 갱신

- 2026-07-28, 2.1·2.2 스파이크 완료 후 DaolVision으로 기록 이관.
