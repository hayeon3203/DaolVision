# STATE.md — DaolVision 현재 상태 스냅샷

> 세션이 언제 끊겨도 이 파일 하나로 "지금 어디까지 왔는지"를 복원한다.
> 작업 시작 전·작업 단위 종료 후마다 갱신. Task 상태의 단일 출처는 Plans.md.

## repo 구성 (필독)

- **DaolVision**(이 repo, github.com/hayeon3203/DaolVision, private) = 오픈셸 자립형
  생성 스튜디오. 기획·문서 + **:8700 게이트웨이 앱 전체**(`langgraph/` —
  api.py/tools.py/nodes.py/graph.py/state.py/metrics.py/driver.py, 프로덕션이
  런타임에 로드하는 `comfyui_workflows/i2v_14b.json`·`standin_t2v.json`, 자체
  `.venv`) + 앞으로 붙일 신규 코드(LocalAI 포크 프론트, 스텝퍼/대시보드) +
  스파이크 기록의 집.
- **GPU 상주 미디어 서버만 `video_generator`에 남음**: hunyuan_server(:8501
  Flux T2I), ComfyUI(:8188, Stand-In·LTX Face-ID·LTX T2V/I2V 폴백 스파이크).
  DaolVision의 langgraph 게이트웨이는 이들을 **HTTP로만 소비**(URL은
  `AGENT_T2I_URL`/`AGENT_COMFYUI_URL` env, 전부 127.0.0.1).
  **2026-08-01 Task 12(Wan 제거) 이후**: 기존 hunyuan_server(:8500 Wan
  T2V/I2V, 중국 원산)를 부르던 `AGENT_WAN_URL`/`call_video`가 삭제되고
  T2V/I2V 폴백 경로가 전부 LTX-Video-0.9.8-13B-distilled(:8188 ComfyUI)로
  통합됨 — `c4c36c4`(animate_server :8600 제거)와 동일 전례.
  **2026-07-30 Task 4.1 직후 이전**: 게이트웨이 코드가 물리적으로도
  video_generator에 있어 원칙과 어긋나던 걸 바로잡음(커밋: video_generator
  `59e5462`(삭제) / DaolVision 이번 커밋(추가), 히스토리 보존 없이 새 커밋).
  `video_generator/langgraph/comfyui_workflows/ltx_faceid.json`과
  `tests/probe_ltx_watch.py`·`probe_ltx_profile.py`(둘 다 untracked)는
  **Task 3.3 진행 중이라 일부러 남김** — 3.3 종료 후 별도 정리.
- 스파이크용 LocalAI 클론은 `/home/admin/LocalAI`(untracked).

## 현재 목표

Week 2 Day1 환경 스파이크(게이트) 완료(2.1~2.4). OOM 정책 = 배치 온디맨드
언로드로 확정. TTS는 S1 영상=Kokoro, 독립 사용자 음성=Chatterbox
Multilingual V3로 역할 분리 확정. I2V 포함 전체 모델 상주 재실측 예정.

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
- **16:9 와이드샷 재검증 (2026-07-30, 같은 세션)**: node 100(`EmptyLTXVLatentVideo`)의
  width/height 링크(94/95, 둘 다 `Get_base_resolution`)를 API 제출 직전에
  `graphToPrompt()` 결과 JSON에서 리터럴 `1024×576`으로 덮어써 정사각 배선을
  우회. 프롬프트도 "wide establishing shot ... character small in frame
  relative to environment" 식으로 교체(발사 씬, 노을 발사대). 제출→완료
  3분29초 — 768² 대비 총 픽셀 동일이라 **속도 저하 없음**(모델 캐시 유지시
  s2~s4와 동일 페이스). 결과: 배경(노을·구름·발사탑) 화려하게 살아남, 얼굴은
  클로즈업보다 작지만 눈썹·헤어스타일 참조와 일치 유지. 산출물:
  `video_generator/ComfyUI/output/video/LTX_2.3_ia2v_00005_.mp4`.
- **새 기본값 확정(3.2 이후 모든 LTX Face-ID 씬 생성에 적용)**:
  - 해상도: **1024×576**(16:9, 768² 동일 픽셀 예산 — width/height를
    `graphToPrompt()` 후 API 프롬프트 JSON에서 리터럴로 덮어써야 함, UI
    그래프 자체는 여전히 정사각 배선이라 매 제출마다 override 필요.
    영구 배선 분리는 하지 않음, override 방식 유지가 더 단순).
  - 씬 프롬프트 톤: 인물 축소·배경 확장 지향("wide/establishing shot",
    "expansive background", "character small in frame") — 클로즈업
    문구("medium close-up") 지양.
  - 나머지(5초/24fps/8-step distill/Face-ID LoRA strength 1.0)는 3.2 원래
    설정 유지.
  - **90초 영상은 이 기본값과 별개**: duration 파라미터(node 31)를 90으로
    올려 한 번에 생성하는 게 아님 — `total_frames = ((duration*fps)//8)*8+1`
    이라 90초/24fps는 2161프레임, LTX 단발 생성 실용 범위를 크게 초과(품질
    붕괴/실패 위험). PRD 파이프 설계(씬분할→씬별 짧은 클립→TTS mux→최종
    mp4, PRD.md 59행)대로 **여러 짧은 클립을 이어붙여 최종 90초를 만드는
    것**이 맞는 경로 — Week5 5.x(배치 클립 생성)에서 다룰 사안, 아직 미착수.

## Task 4.1 — :8700 T2I 엔드포인트 (Flux/SDXL :8501 프록시) (2026-07-30, cc:완료)

- **3.3과의 충돌 여부 사전 검토**: 3.3(cc:WIP)은 :8188 ComfyUI LTX-2.3 Face-ID
  워크플로 구간별 프로파일링 — 전용 격리 venv(`comfyui-bench-venv`)로 돌고
  "프로덕션 ComfyUI venv는 건드리지 않음"이 원칙, 신규 untracked 파일
  `video_generator/langgraph/tests/probe_ltx_profile.py` 하나만 추가. 4.1은
  `video_generator/langgraph/api.py`(:8700 게이트웨이)·`tools.py`에 :8501
  Flux 프록시 코드를 추가 — 파일·포트·프로세스 겹침 없음(3.3=8188/ComfyUI,
  4.1=8501/Flux 경유 8700 게이트웨이). 두 작업 간 상호 영향 없음을 확인 후 구현.
- **구현**: `tools.generate_t2i_anchor(prompt, width?, height?, seed?)` 신설
  (job_id 불필요한 단발 프록시, 기존 job 스코프 `generate_t2i_image`와 별도) —
  FLUX.1-schnell(:8501) `/generate` 호출 후 PNG를 base64로 반환. `api.py`에
  `POST /t2i` 라우트 추가, 빈 prompt는 400, 백엔드 장애(httpx.HTTPError)는 502.
- **검증**: `tests/test_t2i_endpoint.py` 신설(GPU/Flux 실호출 없이
  `tools.generate_t2i_anchor`를 가짜로 교체) — base64 반환·빈 prompt 400·
  백엔드 장애 502 3종 PASS. 기존 회귀 `test_status_clips.py`도 재실행 PASS
  (게이트웨이 다른 엔드포인트 영향 없음 확인).
- **커밋**: video_generator repo `6548985`(DaolVision은 백엔드 코드를 갖지
  않으므로 커밋도 video_generator repo 자체 git에 있음 — 3.1/3.2와 동일 관례).

## Task 3.3 — LTX I2V 파이프라인 병목 프로파일링 (2026-07-30, cc:완료)

상세 근거는 [docs/spikes/3.3-ltx-bottleneck-profile.md](../docs/spikes/3.3-ltx-bottleneck-profile.md).

- **클린 측정 총 소요: 523.44초(8분43초)** — 모델로드 189.9초(36.3%) / 8-step
  샘플링 232.9초(44.5%, 스텝당 ~29.1초) / 디코드+후처리 100.6초(19.2%, 이 중
  텍스트인코더 불필요 재로드 26.4초 포함).
- **1차 시도는 측정 실패**: 사용자가 별도로 띄운 `flux_server.py`(T2I)와
  ComfyUI GGUF 로드가 GB10 통합메모리를 동시 경합 → 스왑 스래싱으로 GGUF
  dequant 스레드가 24분+ 사실상 정지(disk read 거의 0). 시스템 mem free
  1.7Gi/swap free 630Mi까지 하락, earlyoom SIGKILL 문턱 근접. `flux_server.py`
  kill -9로 해소, ComfyUI는 `/interrupt`가 안 먹혀(노드 내부 C-level 루프)
  `systemctl --user restart comfyui.service`로 재기동 후 재측정.
- **4.4(OOM 오케스트레이터)에 주는 시사점**: 동시 상주 경합은 "느려짐"이 아니라
  "사실상 정지"(동일 작업 92초 vs 24분+, 40배 이상 차) — 설계 목표를 "감내"가
  아니라 "정지 방지"로 잡아야 함.
- **3.4/3.5 baseline 확정**: 샘플링(44.5%)이 최대 병목 → step 수·attention
  backend가 최우선 레버. 모델로드(36.3%)의 GGUF dequant는 정상 조건에서
  92초로 자체는 과도하지 않음(1차 시도의 이상 지연은 경합 탓).
- **산출물**: `video_generator/langgraph/tests/probe_ltx_profile.py`(변환+제출,
  3.4/3.5 재사용 예정), `tests/probe_ltx_watch.py`(재제출 없이 관찰 재개용),
  격리 venv `/home/admin/comfyui-bench-venv`(Playwright — 프로덕션 ComfyUI
  venv `/home/admin/.venv`와 분리 유지, 3.1의 numpy/opencv 오염 전례 반복
  방지).

## Task 7.4 — Chatterbox V3 사용자 음성 E2E 청취 검증 (2026-07-31, cc:완료)

- **결정**: 영상 생성 파이프의 나레이션은 Kokoro로 고정하고, LocalAI의 독립
  TTS 카테고리에서만 Chatterbox Multilingual V3 사용자 음성 복제를 제공한다.
- **라우팅 계약**: Agent 내부 `POST /tts/narration` → Kokoro, 독립 TTS
  `POST /tts/clone` → Chatterbox V3. 두 엔진 사이 자동 폴백 없음.
- **참조 입력**: `private/tts/voices/my_voice/reference.wav`(35.43초, PCM
  16-bit, 48kHz stereo)와 `reference.txt`. `private/`와 출력 `out/`은 Git 제외.
- **환경**: `.venv-chatterbox` Python 3.11, ARM64 CUDA 13용
  torch/torchaudio 2.11.0+cu130. V3 GPU 로드 약 3.0GiB 실측.
- **검증**: 같은 한국어 문장과 seed로 참조 조건 clone 및 기본 음성 대조군을
  생성해 음량 정규화 후 청취. 사용자가 `clone_test_listen.wav`는 본인 음성과
  매우 유사하다고 판정했고 기본 음성은 말투가 급해 부적합하다고 판정.
- **산출물**: `out/tts/chatterbox/my_voice/clone_test_listen.wav`,
  `default_voice_control_listen.wav`, `reference_listen.wav`.
- **남은 구현**: 게이트웨이 `/tts/narration`, `/tts/clone` 및 LocalAI TTS
  화면 배선은 Plans 4.2/4.2.1/6.3에서 구현한다. 현재는 로컬 CLI와 모델 검증 완료.

## Task 4.2 — :8700 Kokoro 영상 나레이션 엔드포인트 (2026-07-31, cc:완료)

- **구현**: `POST /tts/narration`을 추가해 `text`와 `speed(0.5~2.0)`를
  localhost `:8503/generate`로 전달하고, 결과를 `audio/wav`로 반환한다.
  빈 텍스트는 400, 백엔드 연결 실패·비정상 WAV는 502로 처리한다.
- **엔진 경계**: 이 경로는 영상 나레이션 전용 Kokoro로 고정하며 Chatterbox로
  자동 폴백하지 않는다. 사용자 복제 음성은 후속 Task 4.2.1 `/tts/clone`에서
  별도로 구현한다.
- **Kokoro 서비스**: `tts/kokoro/`에 PyKokoro 한국어 백엔드, 격리
  `.venv-kokoro`, systemd 유닛을 추가했다. 기본 화자는 `af_heart`, 출력은
  24kHz mono PCM 16-bit WAV이며 최초 모델 적재를 고려해 게이트웨이 read
  timeout은 300초다.
- **검증**: 계약 테스트(정상 WAV·빈 입력 400·백엔드 장애 502)와 기존 T2I
  회귀 테스트 PASS. 실서비스 `POST :8700/tts/narration` 호출도 200
  (`X-TTS-Engine: kokoro`), 24kHz mono PCM, 6.4초/307,244바이트로 통과.
  청취용 결과는 `out/tts/kokoro_narration_api.wav`.

## Task 3.4 — LTX I2V 경량화 파라미터 스윕 (2026-07-31, cc:완료)

상세 근거는 [docs/spikes/3.4-ltx-lightweight-sweep.md](../docs/spikes/3.4-ltx-lightweight-sweep.md).

- **채택: baseline 유지**(8-step, GGUF Q6_K, Face-ID LoRA strength 1.0). 테스트한
  경량화 레버 중 순이익 나는 조합 없음.
- **step 8→6: 기각**. twin 아티팩트(주인공 옆에 동일 인물이 프레임 내내 하나
  더 붙음, 저스텝 diffusion의 전형적 identity 미수렴 결함) + 얼굴 정합성 저하.
- **Face-ID strength 0.75: 미결**. 시드를 baseline과 정확히 동일하게 고정해도
  (`/history`로 실제 반영 확인) 카메라 구도가 매번 달라짐 — GPU 병렬연산
  부동소수점 비결정성이 8-step 누적되며 증폭되는 것으로 추정, 이 파이프라인은
  시드 고정만으론 완전 재현 안 됨. 3회 제출 전부 얼굴이 프레임에 안 잡혀
  정합성 판정 불가, 속도 영향 없음만 확인.
- **GGUF Q6_K→Q5_K_M: 트레이드오프로 미채택**. 가중치 15.6GB(Q6_K 17.2GB 대비
  작음)는 확실하나, 얼굴 정합성이 눈에 띄게 하락(턱선·헤어 파팅 불일치)하고
  속도는 두 실행 간 46% 편차(20.28 vs 28.27초/step)로 신뢰 불가.
- **UVM(통합메모리) 스톨 반복 재현 — 4.4/3.6에 근거로 남김**: 시스템 메모리가
  1~2GB대로 빠듯할 때마다 GPU-매핑 페이지 회수 압박으로 `UVM GPU1 BH` 커널
  스레드가 계속 개입, ComfyUI 스레드는 CPU 99%인데 disk read_bytes·로그
  진행이 15~24분+ 완전히 멈추는 현상이 이번 스윕에서 최소 2회 재현됨(GGUF
  로드 단계·VAE 디코드 단계 각각). `/interrupt` 무효, `systemctl --user
  restart comfyui.service`로만 회복. 일반 스왑 스래싱과 달리 GPU-매핑
  메모리가 스왑 압박 받을 때 특유의 오버헤드(CUDA managed-memory
  oversubscription의 알려진 함정) — 4.4는 "메모리 부족 감내"가 아니라
  "GPU-매핑 페이지가 회수 후보로 안 잡히게 여유 유지"를 목표로 잡아야 함.
- **Wan2.2-TI2V-5B 대비 참고**: `journalctl -u wan.service`에서 LTX와 동일
  프레임수(121) 조건 실측 2건 발견 — 45.68~93.08초/step(1280×704, 20-step).
  LTX baseline 27.6초/step(1024×576, 8-step) 대비 Wan(5B, 파라미터 훨씬 작음)이
  오히려 1.7~3.4배 느림 — 3.2의 "Wan Stand-In 폴백 불필요" 판정이 속도 면에서도
  방향이 맞았음을 보강.

## Task 3.5 — SageAttention3 스파이크 (2026-07-31, cc:완료)

`/home/admin/SageAttention/sageattention3_blackwell`을 GB10 sm_121a
타겟으로 소스 빌드해 ComfyUI 운영 venv(`/home/admin/.venv`)에 설치
(`MAX_JOBS=2`로 OOM 방지, 설치 전후 numpy/opencv/torch 버전 스냅샷 비교로
오염 없음 확인). KJNodes `PathchSageAttentionKJ` 노드로 LTX 그래프의
Face-ID LoRA 출력~샘플러 사이에 패치 삽입.

**결과: 순이익 없음.** 같은 세션 조건에서 baseline 25.36초/step vs sage3
27.02초/step — 오히려 근소하게 느림(둘 다 이 세션 특유의 UVM 스톨 노이즈
영향권). 3.4와 같은 결론: 테스트한 가속 레버 중 확실한 순이익 내는 조합
없음. 채택 안 함.

## Task 3.8 — LTX-13B-distilled 단발샷 I2V (2026-07-31, cc:완료)

상세 근거는 [docs/spikes/3.8-ltx13b-oneshot-i2v.md](../docs/spikes/3.8-ltx13b-oneshot-i2v.md).

- **LTX-2.3-22B Face-ID 파이프라인(523초/5초분량)의 대안으로 LTX-Video-0.9.8-
  13B-distilled(fp8) 채택 — 8-step 30.22초, 17배 빠름.** Face-ID LoRA 없이
  원본 사진이 첫 프레임으로 직접 조건부 입력 — 단일 클립 내 identity는
  자연 유지된다는 가설 확인(눈판정 통과, twin/드리프트 없음).
- **막힌 지점 4개 순차 해결**: (1) `curl | tail` 파이프가 curl 실패를
  가려서 safetensors 파일 손상 → `curl -fL --retry` 재다운로드. (2)
  `LTXBaseModel.forward()`가 `attention_mask` 필수인자인데 클래식 0.9.x
  경로는 안 채움(2.3/AV 리팩터 회귀 추정) → `comfy/model_base.py`의
  `LTXV.extra_conds()` 1줄 패치(`None`이어도 `CONDConstant(None)`으로 명시
  채움, 기존 2.3 파이프라인 동작 불변). (3) `LTXAVTextEncoderLoader`는
  AV(2.3) 전용이라 이 체크포인트엔 안 맞음 → 일반 `CLIPLoader`로 원복.
  (4) 로컬 `umt5-xxl-enc-bf16.safetensors`가 Wan 전용 키 스킴이라 로더가
  못 알아봄(77×768 CLIP-L로 오인식) → LTX 0.9.x는 실제로 표준 T5-XXL을
  씀, `comfyanonymous/flux_text_encoders`의
  `t5xxl_fp8_e4m3fn_scaled.safetensors`로 교체.
- **NVIDIA Cosmos 계열 I2V 용도 최종 제외**: Cosmos-Predict2-2B는 identity
  보존 기능 없음(공식 카드 확인), Cosmos3-Super-Image2Video(64B)는
  8×H200급 멀티GPU 전제라 GB10 1노드 불가. Cosmos는 identity 불필요한
  순수 T2V 단발샷 용도로 재검토 예정(사용자 요청, 아직 미착수).
- **알려진 후속 버그**: 테스트 스크립트가 세로 사진(856×1141)에 가로
  해상도(768×512) 하드코딩해 얼굴 상단이 크롭됨 — 모델 결함 아님, 다음
  실행은 512×704(세로 비율)로 재검증 필요.
- **UI 카테고리 개편**: 사이드바 독립 T2I 카테고리 폐지(Agent 내부 단계로만
  존재), 신규 "I2V 단발샷" 카테고리 추가 — `[Agent(T2I→I2V)] [I2V 단발샷]
  [I2I] [TTS]`. docs/PRD.md 갱신 완료, `:8700 /i2v` 게이트웨이 엔드포인트는
  아직 미구현(Plans.md 신규 태스크로 추가).

## Task 3.6 — ComfyUI 모델 로딩 스파이크 완화 플래그 조사 (2026-07-31, cc:완료)

상세 근거는 [docs/spikes/3.6-comfyui-loading-memory-flags.md](../docs/spikes/3.6-comfyui-loading-memory-flags.md).

- **채택 없음**: `--cache-classic` 제거(기본 `--cache-ram` 복귀) 전/후로
  production 모델(3.8, LTX-13B-distilled) 단발샷 I2V 재측정 — 가용메모리
  ±130MB·스왑 변화 없음·소요시간 차이 노이즈 범위, 측정 가능한 이득 없음.
  `comfyui.service`는 원래 플래그(`--cache-classic --highvram`)로 원복.
- **원인 재확인**: 3.3에서 관측된 진짜 위험 스파이크(가용메모리 1.7GiB,
  24분+ 정지)는 ComfyUI 자체 로딩이 아니라 별도 프로세스(`flux_server.py`)와의
  동시 대형 모델 로드 경합이 원인 — 단일 서비스 CLI 플래그로 해결 불가.
  단독 실행 시 최저 가용메모리 51GiB로 여유 충분(위험 상황 재현 안 됨).
- **후속**: 진짜 완화책은 Task 4.4(OOM 오케스트레이터, 프로세스 간 동시
  대형 로드 직렬화/차단) 몫 — 3.6은 조사 완료로 종료, 추가 액션 없음.

## Task 3.7 — video_generator 백엔드 이전 (2026-07-31, cc:완료)

상세 근거는 [docs/external-dependencies.md](../docs/external-dependencies.md).

- **코드 복제**(이전 아님, 사용자 지시로 정정): `inference_server/`(Wan :8500·Flux
  :8501·Animate :8600 서버·deploy unit·모니터링·editing 스크립트, git 추적분
  전량)를 video_generator에서 DaolVision으로 복제(commit `56672a0`).
  video_generator에 있던 uncommitted 수정(`run.sh`/`run_animate.sh`의
  `PYTORCH_CUDA_ALLOC_CONF` 추가)도 함께 반영해 유실 없음. 처음엔 video_generator
  쪽 원본을 삭제했으나(commit `dca401a`/`17dc548`) "이전 말고 복제"로 정정 지시받아
  즉시 `revert`(`afa5baf`/`8dce4ec`) — video_generator에도 동일 코드가 원본
  그대로 남아 있다. SSOT는 DaolVision, video_generator는 구 위치 사본.
- **외부 의존성으로 명시적 문서화** (물리 이전 안 함): ComfyUI(:8188, ~150GB,
  GPL-3.0 vendored, `comfyui.service`로 상시 가동 중이라 무중단 이전 불가),
  Wan2.2-Animate 저장소, HuggingFace 캐시(~315GB). 셋 다 원래도 `.gitignore`
  대상이었다 — 경로·크기·재배치 방법을 `docs/external-dependencies.md`에 표로 기록.
  `inference_server/weights/Z-Image-Turbo`(31GB)는 폐기된 선대 모델이라 제외.
- **systemd**: repo 내 `deploy/*.service` 템플릿과 설치본
  (`~/.config/systemd/user/{wan,flux,wan-animate}.service`) 모두 새 경로로
  갱신. 셋 다 이전부터 `disabled`/`inactive`(현재 Wan/Flux는 수동 프로세스로
  실행 중)라 `daemon-reload`·`enable`·`restart`는 하지 않음 — 라이브 서비스
  무중단 원칙 유지. `comfyui.service`(유일하게 `Restart=always`로 상시
  가동)는 경로 변경 없이 그대로 둠.
- **충돌 재확인**: 3.3~3.6은 전부 cc:완료, 건드린 파일은 `docs/spikes/*.md`·
  `langgraph/comfyui_workflows/`뿐 — `inference_server/`와 경로·포트 겹침 없음.
- **DoD 대비 남은 갭**: "DaolVision 클론만으로 전 서비스 기동"은 코드 기준
  참(clone 즉시 `inference_server/run*.sh` 실행 가능) — 단 ComfyUI 앱/모델과
  HF 캐시는 별도로 문서 경로에 배치해야 실제 기동됨(문서화 완료, 자동화 스크립트는
  범위 밖).
- **폴더명 정정**(2026-07-31): `hunyuan_server` → `inference_server`로 개명
  (사용자 지시 — HunyuanVideo는 진작 Wan2.2-TI2V-5B로 교체됐고 이제 안 씀,
  이름만 관성으로 남아 있었음). DaolVision 쪽 코드·deploy unit·설치된 systemd
  unit·문서를 전부 새 이름으로 갱신. video_generator 원본 디렉터리명은
  그대로 `hunyuan_server`(건드리지 않음 — 복제본과 원본은 독립적으로 관리).
- **animate_server.py(:8600) 삭제**(2026-07-31, 사용자 지시): LangGraph가
  :8600을 호출한 적 없고(Task 2.2.2부터 `wan-animate.service` 중지 상태) 죽은
  코드로 확인돼 DaolVision `inference_server/`에서 제거
  (`animate_server.py`·`run_animate.sh`·`deploy/wan-animate.service`).
  설치된 `~/.config/systemd/user/wan-animate.service`도 disable 후 삭제
  (원래도 inactive/disabled). 삭제 범위는 DaolVision만 — video_generator
  `hunyuan_server/` 원본은 안 건드림(사용자가 명시적으로 DaolVision만 선택).

## 차단 요소

- 없음

## Task 4.2.1 — :8700 Chatterbox V3 사용자 음성 엔드포인트 (2026-07-31, cc:완료)

- **구현**: `POST /tts/clone`이 multipart `text`와 필수 `reference` WAV를
  받아 Chatterbox 전용 `:8504/generate`로 전달한다.
- **출력 계약**: Chatterbox 서비스가 결과를 24kHz mono PCM 16-bit WAV로
  정규화한다. 빈 텍스트는 400, 참조 누락은 422, WAV가 아닌 입력은 415,
  백엔드 장애·비정상 WAV는 502다.
- **엔진 경계**: clone 경로는 Chatterbox V3만 호출하며 Kokoro 자동 폴백이
  없다. `/tts/narration`의 Kokoro 고정 경로도 그대로 유지한다.
- **검증**: `tests/test_tts_routing.py`, 기존 Kokoro narration 및 T2I 계약
  테스트와 Python 컴파일 검증 PASS.

## 최종 갱신

- 2026-07-31, S1 나레이션 엔진을 Kokoro에서 Chatterbox V3 + 고정 CC0
  한국어 화자로 교체. Kokoro `af_heart`는 한국어 G2P만 가능하고 한국어
  네이티브 화자가 없어 실청취에서 외국인 억양으로 기각했다. Lingua Libre
  화자 `CHK2605`의 Wikimedia Commons CC0 녹음 10개를 8.79초/24kHz mono
  참조로 구성했으며, `/tts/narration` 실호출 200·24kHz mono WAV를 확인했다.
  Kokoro 서비스는 미사용으로 중지·비활성화했다.
- 2026-07-31, Task 4.2.1 완료(:8700 `POST /tts/clone` → Chatterbox V3
  :8504, 필수 참조 WAV, 24kHz mono 출력, Kokoro 폴백 없음).
- 2026-07-31, Task 4.2 완료(:8700 `POST /tts/narration` → Kokoro :8503,
  한국어 24kHz mono WAV 실호출 통과). 영상 나레이션은 Kokoro 고정,
  사용자 음성은 후속 4.2.1 Chatterbox 경로로 계속 분리.
- 2026-07-31, TTS 역할 분리 확정(S1 영상=Kokoro, 독립 사용자 음성=Chatterbox
  V3). 실제 참조 음성 clone 청취 통과, 기본 음성 대조군은 기각. 게이트웨이/UI
  배선은 후속 Task 4.2/4.2.1/6.3.
- 2026-07-30, Task 4.1 완료(:8700 POST /t2i, Flux :8501 프록시, base64 반환) —
  3.3(ComfyUI :8188 프로파일링, cc:WIP)과 파일/포트 겹침 없음 확인 후 구현.
- 2026-07-30, Task 3.2 완료(Face-ID 4씬 눈판정 PASS, Wan 폴백 불필요) +
  16:9(1024×576)·와이드샷 프롬프트 톤을 새 기본값으로 확정. 90초 최종영상은
  5.x 배치 클립 이어붙이기로 스코프아웃(미착수).
- 2026-07-31, Task 5.1 완료. `tools.call_llm` 기본값을 Ollama
  `hf.co/nvidia/NVIDIA-Nemotron-3-Nano-4B-GGUF:Q4_K_M`으로 교체하고
  `run_agent.sh` 기본값도 통일했다. 씬분할은 정확히 4씬을 요구하며, Nemotron의
  간헐적 3/5씬 출력을 1회 교정 재시도 후 순서 보존 정규화한다. 실제 한국어
  우주비행사 시나리오 4씬, 회귀 테스트, `driver.py --dry` 모두 PASS.
- 2026-07-31, Task 5.2 완료. `node_generate_scene_anchors`를 씬 프롬프트와
  클립 fan-out 사이에 추가해 Flux(:8501)로 `anchor_scene_<id>.png`를 씬별
  생성한다. 각 씬은 구도/배경 조건인 `anchor_image`와 LTX Face-ID identity
  조건인 `face_id_ref`를 별도 필드로 보존한다. 사람의 `start/ref`만 Face-ID
  참조가 전달되며 비인간 참조는 제외한다. 4씬 앵커 계약 테스트, 기존 생성 순서·
  스타일 회귀, Python 컴파일, `driver.py --dry` 모두 PASS.
- 2026-07-31, Task 5.3 완료. 3.2에서 품질 통과한 LTX-2.3-22B Q6_K +
  distill LoRA + Best-Face-ID 워크플로를 UI 변환이 필요 없는
  `ltx_faceid_api.json`으로 고정했다. 4씬은 개별 `/prompt`가 아니라 하나의
  ComfyUI prompt 안에서 모델/Gemma/VAE/LoRA 로더를 공유하고 샘플러 가지
  4개만 분리한다. 따라서 배치당 GGUF/Gemma 로더 각 1개, LoRA 로더 2개로
  씬별 재로드를 구조적으로 방지한다. Face-ID 참조도 동일 파일이면 한 번만
  업로드한다. ComfyUI 41개 노드 타입 호환 확인, 단일 배치 계약 테스트,
  Python 컴파일, `driver.py --dry` PASS.
  - **라이브 Acceptance 추가**: job `task53-live-20260731`에서 동의된 사용자
    얼굴 참조(`건호군.jpg`)로 발사·우주유영·외계행성·귀환 클립 4개 실제 생성.
    전부 1024×576, 24fps, 2.041667초 H.264 MP4이며
    `langgraph/jobs/task53-live-20260731/clip{1..4}.mp4`에 보존했다.
    중간 프레임 contact sheet 눈판정에서 장면별 배경 구분은 확인됐으나, 동일
    인물 여부는 이후 재검증에서 뒤집힘 — 아래 재설계(정정) 항목 참고.
  - 원본 워크플로의 LTX 오디오 디코드가 씬 2 후 AudioVAE 로드 중 스왑
    스래싱을 일으켜 첫 배치를 중단했다. S1 오디오는 5.4 TTS mux가 담당하므로
    `CreateVideo.audio` 연결을 제거해 영상 전용으로 재실행했고 나머지 3씬 완주.
    ComfyUI 0.25 `SaveVideo`가 MP4를 `outputs.images + animated=true`로
    보고하는 형식도 production downloader에 반영했다.
- 2026-07-31, Task 5.2/5.3 재설계(정정). 위 Task 5.2/5.3 완료 기록은 Flux
  앵커(`node_generate_scene_anchors`)를 `LTXVImgToVideo strength=1.0`으로
  첫 프레임에 고정하는 설계였으나, 라이브 재생성 육안 검증(job
  `task53-live-20260731` 프레임 비교)에서 두 결함 확인:
  (1) Flux 앵커 생성이 얼굴 참조를 전혀 받지 않아 매번 무작위 얼굴 생성,
  (2) 그 무작위 얼굴을 강도 1.0으로 첫 프레임에 고정해 뒤따르는 Face-ID
  Identity Transfer(node 129)가 참조 얼굴로 override할 여지가 전혀 없었음
  — 최종 영상이 참조 얼굴과 무관한 사람으로 나옴(재현: 재검증 앵커가 완전히
  다른 여성 얼굴로 생성됨을 직접 확인). 씬 프롬프트의 "camera push-in" 문구도
  2초 클립 안에서 인물이 급격히 확대되는 별도 문제로 확인.
  **조치**: Flux 앵커 생성(`generate_scene_anchor`)과 앵커 lock 배선(node
  130/131, node 117/129 override)을 전부 제거하고 3.2가 검증한 순수 Face-ID
  배선(100 `EmptyLTXVLatentVideo` → 117 → 129←83)으로 복귀. 배경 다양성은
  3.2에서 이미 증명된 대로 씬 프롬프트 텍스트가 전담(앵커 불필요). 씬
  프롬프트는 push-in을 제거하고 3.2 기본값(wide/establishing shot, static
  camera, character small in frame)으로 통일. 설계 근거:
  `docs/superpowers/specs/2026-07-31-ltx-faceid-anchor-removal-design.md`.
  부가 효과: 씬당 ~177초였던 Flux 앵커 호출이 통째로 사라져 생성 시간도
  단축됨.
