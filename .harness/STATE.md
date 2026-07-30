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

Week 2 Day1 환경 스파이크(게이트) 완료(2.1~2.4). OOM 정책 = 배치 온디맨드
언로드로 확정. I2V/TTS 모델 확정 후 전 모델 상주 재실측 예정.

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

## Task 2.3 — Nemotron-4B 한국어 씬분할 벤치 (2026-07-30, cc:완료)

상세 근거·재현법은 [docs/spikes/2.3-scene-split-korean.md](../docs/spikes/2.3-scene-split-korean.md).

- **모델**: `ollama pull hf.co/nvidia/NVIDIA-Nemotron-3-Nano-4B-GGUF:Q4_K_M`
  (2.8GB) — 2.2에서 우려한 Mamba2-하이브리드 arch 미지원 없이 정상 로드/추론.
- **방법**: 프로덕션 system_prompt(`nodes.py::node_split_scenes`) 그대로, PRD S1
  시나리오(우주비행사 4씬)를 한국어로 입력해 3회 반복 실행. Llama3.1:8b로 동일
  프롬프트 2회 비교 실행.
- **Nemotron 3회**: JSON 파싱 3/3, 한국어 원문 보존 3/3, duration(2~3초) 스키마
  100% 준수, subject_type(human) 정확도 12/14씬. 결함: 1회 키릴문자 혼입
  (`гром음`), 1회 2/5씬 human→nonhuman 오분류. 둘 다 JSON 구조는 안 깨짐.
- **Llama3.1 2회 비교**: duration 위반 1건 추가, subject_type 정확도 3/11씬으로
  Nemotron보다 뚜렷이 나쁨(2회차는 5씬 전부 오분류).
- **결론: Nemotron-3-Nano-4B-GGUF 채택, 폴백(Llama3.1) 불필요**. 간헐적 결함은
  Llama3.1 대비 동등 이상이고 fallback 파싱 경로(`parse_json_lenient` +
  원문 text 폴백)로 안전. subject_type 오분류 완화는 6.x 배선 단계 과제로 이월.

## Task 2.2.1 — Diffusion VLM 텍스트+캡션 통합 스파이크 (2026-07-30, cc:완료)

상세 근거·재현법은
[docs/spikes/2.2.1-diffusion-vlm-unification.md](../docs/spikes/2.2.1-diffusion-vlm-unification.md).

- `nvidia/Nemotron-Labs-Diffusion-VLM-8B` BF16(17.9GB)을 GB10에서 네이티브 로드
  성공. load 88.53초, peak CUDA reserved 17.23GiB.
- 공식 문서의 `transformers>=5.0.0` 표기와 달리 5.0/5.12는 모델 코드 import 실패.
  체크포인트 제작 버전 4.57.1 전용 격리 venv에서 정상 작동.
- 캡션은 2.44초, 실제 인물 이미지 주 피사체를 정확히 영어로 설명해 **통과**.
- S1 한국어 4씬 분할은 6.92초지만 원문 전체 반복 + JSON 여는 `[` 누락으로
  **실패**. 현재 `parse_json_lenient`에도 들어갈 수 없음.
- 결정: Qwen 제거는 가능하되 단일 모델 통합은 보류. 텍스트는 이미 통과한
  Nemotron-3-Nano-4B-GGUF 유지, 캡션만 Diffusion VLM 후보로 채택. 실제 배선은
  Ollama 모델명 교체가 아니라 별도 Transformers 서버/호출 어댑터가 필요.

## Task 2.2.2 — vLLM + LTX 인코더 교체 검토 (2026-07-30, cc:완료)

상세 결과는
[docs/spikes/2.2.2-vllm-and-ltx-encoder.md](../docs/spikes/2.2.2-vllm-and-ltx-encoder.md).

- vLLM 0.26.0 aarch64 전용 venv 설치.
- Diffusion VLM-8B는 Transformers 5.12 import 충돌 및 vLLM 미지원 아키텍처로
  기동 실패. 전용 Transformers 4.57.1 서버 유지가 유일한 실증 경로.
- Nemotron 3 Nano 4B BF16은 vLLM 기동 성공(weight 7.47GiB). 하지만 S1에서
  thinking 출력 잘림, thinking off 시 4개 지시에 2개만 생성, JSON Schema 사용
  시 공백 토큰만 소진해 기존 Ollama Q4보다 품질 열세. 전환 보류.
- LTX Gemma 3 12B는 48층×3840 hidden 전체를 `3840*49` 전용 projection으로
  변환하는 학습된 conditioning encoder. 34층×4096 Diffusion VLM은 tokenizer,
  shape, embedding 공간이 모두 달라 drop-in 교체 불가. projection+cross-attention+
  Face-ID LoRA 재학습이 필요.
- 운영 조치: 미사용 `wan-animate.service` 중지(`:8600` 제거), FLUX :8501은
  S1 정지 앵커 생성용이라 유지. vLLM 스파이크 서버는 종료.

## Task 2.2.3 — Nemotron 12B VL 양자화 산정 (2026-07-30, cc:완료)

상세 결과는
[docs/spikes/2.2.3-nemotron-12b-vl-quant-sizing.md](../docs/spikes/2.2.3-nemotron-12b-vl-quant-sizing.md).

- BF16은 vLLM에서 `NemotronH_Nano_VL_V2`로 정상 인식, 24.57GiB weight
  load 성공. 사용자 지시로 inference/profile 전에 중단.
- 공식 FP8 저장 크기 14.35GiB → 예상 peak 16~20GiB로 예산 초과.
- 공식 NVFP4-QAD 저장 크기 9.89GiB → 예상 peak 12~14GiB. weight만으로
  10GiB에 근접해 전체 peak 8~10GB 보장은 불가.
- LTX Gemma FP8 12.30GiB + projection 2.15GiB = weights 14.45GiB. 이는
  LTX conditioning 필수 구성이라 Nemotron과 동시 상주시키지 않고 phase 단위
  unload/load해야 함.
- 결정: 8~10GB 엄격 예산이면 12B VL 전 계열 제외. 12~14GB를 허용할 때만
  NVFP4-QAD 실측 후보.

## Task 2.3.5 — T2I 모델 확정 (2026-07-29, cc:완료)

R10(전 모델 비중국/NVIDIA)에 따라 T2I 자리(video_generator `:8501` zimage 대체)에
NVIDIA 공식 모델을 우선 탐색·실측.

- **nvidia/Qwen-Image-Flash: 실측 기각**. transformer 20.43B + 전체 파이프라인
  28.85B 파라미터. GB10에서 `.to("cuda")`(CPU→GPU 가중치 이전) 도중 시스템 메모리
  114→118Gi(전체 119Gi)까지 치솟아 생성 시작 전에 강제종료. ComfyUI+anim-agent
  상주 상태 기준(video_generator에서 실측, 2026-07-29). 성능 비교 이전에 크기부터
  이 워크스테이션 동시 상주 조건에 안 맞음.
- **패턴**: NVIDIA 공식/NVIDIA 지원 T2I 모델 중 이 정도로 가볍고 GB10에서
  다른 서비스와 동시 상주 가능한 옵션을 아직 못 찾음.
- I2I(Flux Kontext)·I2V(Cosmos-Predict2-2B)는 **아직 미실측** — PRD상 I2I는
  NVIDIA 후보 시도 자체가 없고(처음부터 Flux Kontext), I2V의 Cosmos-Predict2-2B는
  "벤치 예정"(Phase 6)이라 여기 기록하지 않음. 실측 후 별도 판단.

**최종 확정: FLUX.1-schnell**(Black Forest Labs, 독일). GB10 실측 3종 비교:

| 모델 | 국적 | 파라미터 | load | gen | peak VRAM | 결과 |
|---|---|---|---|---|---|---|
| SDXL | 🇬🇧/🇺🇸 | 2.6B | 100s | 12.8s | 9.0GB | 가장 가벼움이지만 채택 안 함 |
| **FLUX.1-schnell** | 🇩🇪 | 12B | 448s(다운로드) | 11.7s | 33.8GB | **채택** |
| nvidia/Qwen-Image-Flash | 🇺🇸(원본 Qwen=🇨🇳) | 28.85B | — | — | OOM | 기각(위 항목) |

SDXL이 더 가볍지만(9GB) legacy UNet 구조라 diffusers의 새 attention dispatch
경로(`dispatch_attention_fn`, 향후 FA-4/Blackwell 최적화 적용 통로)를 못 탐 —
FLUX는 DiT 구조라 이 통로를 그대로 타서, video_generator의 Wan 영상 파이프라인과
같은 최적화 경로를 공유할 수 있음. 화질 실측은 `video_generator/hunyuan_server/
bench_out/{sdxl,flux-schnell}.png`로 눈 비교, 사용성 문제 없음 확인.

video_generator 쪽 구현: `hunyuan_server/zimage_server.py` → `flux_server.py`
교체, systemd `zimage.service` → `flux.service`, `langgraph/tools.py`
`ZIMAGE_URL` → `T2I_URL`(env `AGENT_T2I_URL`)로 정리. commit
video_generator@924a10c. `:8501`에서 실제 `/generate` 호출 검증 완료(임시 포트
18501, 1024×1024 png 10.3s).

**포트 충돌 해결됨 (2026-07-29)**: `:8501`을 다른 프로젝트(`daol-fascope`, 구
`wafer-fa`)의 Streamlit 대시보드가 쓰고 있어서 `flux.service` 기동이
`address already in use`로 실패했던 문제 — daol-fascope 쪽을 `:8502`로 옮겨서
해결. 참고: 그 프로세스는 `wafer-fa` 디렉토리가 `daol-fascope`로 rename된 뒤에도
구 경로(`/home/admin/wafer-fa/.venv/...`)를 그대로 물고 떠 있던 것(rename 후에도
이미 열린 파일은 유효 — Linux inode 특성), 재기동은 현재 경로
(`daol-fascope/.venv/bin/python3.12 -m streamlit run app.py --server.port 8502`)로
함. `flux.service`는 `:8501`에서 정상 기동·health 200 확인 완료.

## Task 2.4 — 전 모델 상주 OOM 실측 게이트 (2026-07-30, cc:완료)

상세 근거·타임라인은 [docs/spikes/2.4-oom-residency.md](../docs/spikes/2.4-oom-residency.md).

- **사전조치**: ollama systemd가 전역 `OLLAMA_MAX_LOADED_MODELS=1`이라 씬분할+
  캡션 동시 상주 자체가 불가했음 → `/etc/systemd/system/ollama.service.d/
  override.conf`로 `=2` 적용(사용자 승인, sudo 직접 실행). **override 유지 중**
  (재실측 때도 필요).
- **실측**: baseline(ComfyUI+anim-agent+무관 daol-fascope 상주, 36.4GB) +
  Nemotron-4B + gemma4 + FLUX.1-schnell 순차 로드 → 시스템 메모리
  82Gi→118Gi/119Gi까지 상승, 스왑 15Gi 완전 소진, thrashing. video_generator
  `server.py`(:8500, GPU 21.9GB 보유)가 압박 중 다운(로그 없어 OOM-kill 확정은
  못 했으나 정황상 유력) — 이후 재기동으로 복구 확인.
- **결론: 전 모델 상주(PRD 주력안) 기각, 폴백(배치 온디맨드 언로드) 채택.**
  I2V(LTX/Cosmos/Wan)·TTS 확정 전 3개 모델만으로도 이미 OOM 유발 — 강행 불가.
- **재실측 예정**: I2V·TTS 모델 확정 후, 확정 스택 전체로 상주 가능여부
  한 번 더 실측(이번 3-모델 결과가 최종 판단은 아님, daol-fascope처럼 무관한
  상시 점유 프로세스도 예산에 큰 비중이라 그 시점 상태로 재확인 필요).

## Task 0.2 — 기존 코드 파악 (파이프라인 4서브시스템) (2026-07-29, cc:완료)

`video_generator/CLAUDE.md`의 서브시스템 표(hunyuan_server :8500/:8600, langgraph
:8700, openwebui —, ComfyUI :8188)를 실제 코드·systemd 유닛과 대조. 검증: `systemctl
--user list-unit-files`, `ss -ltnp`, 각 run 스크립트의 포트 env, `langgraph/tools.py`
URL 상수, `langgraph/api.py` 라우트.

**일치 확인**: hunyuan_server(:8500/:8600), langgraph(:8700, `/jobs` 등 문서화된
라우트 전부 존재), ComfyUI(:8188, 현재 기동 중), openwebui Function 3종 — 문서와 실제
코드 일치.

**⚠️ 격차 발견 — CLAUDE.md 갱신 필요 (video_generator repo, DaolVision 아님)**:
1. **5번째 서브시스템 미문서화**: `hunyuan_server/zimage_server.py`(Z-Image-Turbo
   T2I, `:8501`, systemd `zimage.service` enabled)가 실존·기동 가능하지만
   CLAUDE.md 서브시스템 표·"네 서비스 systemd 유닛" 문장(4개로 명시)에 빠짐.
   `langgraph/nodes.py`(M2-2/M2-5)가 `tools.py`의 `ZIMAGE_URL`(:8501)로 정지
   이미지 앵커를 생성 — S1(우주비행사 여정) 씬 파이프라인에 실제로 관여하는
   경로라 DaolVision 대시보드 설계(6.x, 포트/데이터흐름 시각화) 시 반드시 포함
   필요.
2. **"미구현" 표기 stale**: CLAUDE.md "Not yet implemented (Phase C)"에 "cancel
   from the agent side"가 있으나, 실제로 `langgraph/api.py`에 `POST
   /jobs/{job_id}/cancel`이 동작 구현되어 있음(태스크 취소 + `.cancelled` 마커 +
   metrics 기록). 문서가 뒤처짐.

**DaolVision 영향**: 두 항목 다 video_generator repo의 CLAUDE.md를 갱신해야 할
사항이지만, 이 repo는 백엔드 코드를 수정하지 않는 원칙(repo 구성 참조)이라 여기서는
기록만 하고 실제 문서 수정은 video_generator 세션에서 별도 처리. DaolVision 쪽
대시보드/스텝퍼 설계 시 5개 엔드포인트(:8500/:8501/:8600/:8700/:8188) 기준으로
진행.

## Task 3.1 — LTX distilled + BFS노드 + Face-ID LoRA 설치·호환·라이센스 확인 (2026-07-30, cc:완료)

상세 근거는 [docs/spikes/3.1-ltx-faceid-compat.md](../docs/spikes/3.1-ltx-faceid-compat.md).

- **원래 가정 폐기**: "LTX distilled"(구 LTX-Video 13B) + 커뮤니티 Face-ID
  LoRA 조합은 버전 불일치로 애초에 안 맞음(LoRA는 LTX-2.3/22B 전용,
  `docs/model-selection.md`에 착수 전부터 리서치로 기록돼 있던 사항). "BFS"는
  미정의 상태였으나 `alisson-anjos/ComfyUI-BFSNodes`(Face-ID LoRA 공식
  컴패니언 노드)로 확인.
- **재정의 확정 스택**: LTX-2.3-22B-dev(GGUF Q6_K, `unsloth/LTX-2.3-GGUF`,
  17.8GB) + distill LoRA(rank-111 dynamic, `Kijai/LTX2.3_comfy`, 2.74GB) +
  Best-Face-ID LoRA(`Alissonerdx/LTX-Best-Face-ID`, 2.47GB) + BFS Nodes +
  KJNodes(video_generator/ComfyUI에 실치). 사용자 질문("더 가벼운 LTX 없냐")에
  대한 답: 공식 bf16(46GB)보다 GGUF Q6_K(17.8GB)가 실제 경량 경로이며, 이
  조합이 LoRA 저자가 직접 검증·배포한 조합(총 41.3GB, ArcFace projector는
  효과 미미해 스킵).
- **설치 중 부작용 2건 즉시 복구**: (1) numpy 2.x 승격이 기존 Wan
  파이프라인의 mediapipe(numpy<2 요구)를 깰 뻔함 → 1.26.4로 원복. (2)
  opencv-python-headless가 기존 opencv-contrib-python(4.11.0,
  `cv2.face` 등 contrib 모듈 보유)을 섀도잉할 뻔함 → contrib
  force-reinstall로 복구. 둘 다 기존 프로덕션 파이프라인 영향 없이 해결
  확인.
- **워크플로 로드 검증**(헤드리스, `/object_info` API 기준): 39개 노드 타입 +
  9개 모델 파일 참조 전부 FOUND. 이 ComfyUI 인스턴스는 community 표준
  `UnetLoaderGGUF` 대신 내장 `LoaderGGUF`를 씀 → 워크플로 JSON 노드타입
  교체, distill LoRA 위젯값의 원저작자 개인 폴더 접두어(`ltx-2/2.3/`)도
  제거해 우리 설치 경로와 맞춤. 산출물: `video_generator/langgraph/
  comfyui_workflows/ltx_faceid.json`(video_generator repo 자체 git에 커밋,
  ComfyUI 모델·커스텀노드 디렉터리는 gitignore 대상이라 추적 안 됨).
- **라이센스**: LTX-2 Community License(무료, 단 연매출 $10M+ 법인은 별도
  유료 계약 필요 — 이 프로젝트는 해당 없음), BFS Nodes는 GPL-3.0. 문제 없음.
- **실제 생성 품질 검증은 3.2로 이관**(참조얼굴 4씬 생성 눈판정).

## Task 3.2 — Face-ID 얼굴+화풍 일관성 데모수준 검증 (2026-07-30, cc:완료)

- **실행 경로**: `ltx_faceid.json`은 UI 저장 포맷(SetNode/GetNode/Reroute로
  변수 배선, `/object_info`에 등록 안 되는 프론트엔드 전용 pseudo-node)이라
  `/prompt` API에 직접 못 보냄. Playwright로 ComfyUI 프론트를 헤드리스
  로드 → `window.app.graphToPrompt()`로 실제 실행용 API-format으로 변환 →
  같은 세션 `fetch`로 `/prompt` 제출. Face-ID LoRA·distill LoRA·Best-Face-ID
  전부 3.1이 설치한 그대로, 노드 배선 수정 없음(참조 얼굴 파일과 씬별 프롬프트
  텍스트 위젯값만 교체).
- **설정**: 768×768(정사각, `Get_base_resolution` 하나가 width/height 동시
  공급이라 원래 정사각 고정), 5초/24fps(121프레임), distill LoRA 8-step,
  Best-Face-ID LoRA strength 1.0.
- **참조 얼굴**: 사용자 제공 개인 사진(비공인, 워터마크 없음). 최초 제시된
  케이팝 아이돌 언론사진(워터마크 있음, 실존 공인 얼굴)은 초상권/딥페이크
  리스크로 거절하고 교체받음 — 3.2류 얼굴합성 테스트는 매번 동의된 얼굴
  소스인지 먼저 확인 필요.
- **결과(4씬, 우주비행사 발사/우주유영/외계행성/귀환)**: 전부 success,
  node_errors 없음. 프레임 추출 눈판정 — s1/s2/s4(클로즈업)는 눈썹·눈·코·입
  모양이 참조 얼굴과 뚜렷이 일치, 씬 내부(0→110프레임) 흔들림 없음. s3(전신
  와이드샷)는 얼굴 비중이 작아 정합성 판정 신뢰도가 상대적으로 낮음. 화풍
  (라이팅·질감)은 4씬 전체 일관. **종합 PASS — Wan Stand-In 폴백 불필요.**
  씬당 생성 3~5분(최초 씬은 모델 로드 포함 ~5.5분, 이후 캐시로 ~3분대).
- **산출물**: `video_generator/ComfyUI/output/video/LTX_2.3_ia2v_0000{1..4}_.mp4`
  (얼굴 결과), `video_generator/ComfyUI/output/comparison_0000{1..4}-audio.mp4`
  (참조사진↔결과 비교).
- **후속 요구사항(스코프 아웃, 5.x 프로덕션 설정 단계로 이관)**:
  1. **16:9**: 현재 정사각은 `Get_base_resolution`이 width/height에 동일값을
     공급하는 배선 때문 — width/height를 분리해야 함. 같은 픽셀 예산으로
     화면비만 바꾸려면 1024×576(768²와 총 픽셀 동일, 속도 저하 없음).
  2. **더 먼 앵글/화려한 배경**: 워크플로 배선과 무관, 씬 프롬프트 문구
     문제("medium close-up" → "wide shot, expansive background" 식으로
     우리가 쓰는 캡션만 바꾸면 됨).
  3. **90초 영상**: 이 워크플로 duration 파라미터(node 31)를 90으로 올려
     한 번에 생성하는 건 아님 — `total_frames = ((duration*fps)//8)*8+1`이라
     90초/24fps는 2161프레임, LTX 단발 생성 실용 범위를 크게 초과(품질 붕괴/
     실패 위험). PRD 파이프 설계(씬분할→씬별 짧은 클립→TTS mux→최종 mp4,
     PRD.md 59행)대로 **여러 짧은 클립을 이어붙여 최종 90초를 만드는 것**이
     맞는 경로 — Week5 5.x(배치 클립 생성)에서 다룰 사안.

## 차단 요소

- 없음

## 최종 갱신

- 2026-07-30, Task 3.2 완료(Face-ID 4씬 눈판정 PASS, Wan 폴백 불필요. 16:9·
  와이드앵글·90초 후속 요구사항은 5.x로 스코프아웃).
