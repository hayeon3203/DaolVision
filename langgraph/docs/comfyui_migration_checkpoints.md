# ComfyUI 전환 체크포인트 — Stand-In 얼굴 일관성 경로 (개정판)

최초작성: 2026-07-05. **개정: 2026-07-05 — Animate 2패스 계획을 폐기하고 Stand-In 1패스로 전환.**
목적: 영상의 **얼굴 identity 일관성**을 높인다. (속도는 별개 레버 — 아래 Phase 0 참고)

---

## 0'. 왜 Animate → Stand-In 으로 바꿨나 (전환 근거, 반드시 먼저 읽을 것)

이전 개정판은 identity 경로로 **Wan2.2-Animate 14B 2패스**(draft T2V → pose/mask 추출 → animate)를 잡았다. **이는 이 파이프라인에 대해 잘못된 전제였다.**

| | **Stand-In (채택)** | **Wan Animate (폐기)** |
|---|---|---|
| 입력 | 참조 얼굴 1장 + 텍스트 프롬프트 | **구동 영상(driving video)** + 참조 이미지 |
| 하는 일 | 얼굴 identity를 latent로 주입해 자유 생성 영상에 고정 | 구동 영상의 포즈·동작을 참조 인물에게 이식 |
| 패스 | **1패스 (T2V)** | 2패스 (14B ×2) + 전처리 |
| 전처리 | 없음 | vitpose 포즈 + SAM2 마스크 추출 |
| 속도 | 빠름 (lightx2v distill) | 느림 |
| 적합 상황 | "이 얼굴로 이 장면을 만들어" | "이 실제 연기를 이 캐릭터가 하게" |

**핵심:** Animate는 *따라 할 구동 영상*이 있어야 의미가 있다. 그런데 이 LangGraph 파이프라인은 **텍스트 프롬프트에서 장면을 발명**한다 — 따라 할 원본 연기 영상이 없다. Animate를 쓰려면 구동 영상을 얻으려고 14B T2V를 먼저 돌리고(draft), 거기서 포즈를 뽑아 두 번째 14B Animate 패스를 돌려야 한다. Stand-In이 1패스로 하는 identity 고정을 2배 연산으로 하는 셈이고, 이 용도에선 이득도 거의 없다.

**Stand-In이 현재 :8500 I2V보다도 나은 이유:** 지금은 참조 이미지가 있는 씬을 I2V(이미지를 첫 프레임으로)로 보낸다. 첫 프레임 조건은 영상이 진행되며 얼굴이 흐려지고, 참조가 "얼굴"이 아니라 "전체 장면 프레임"이어야 한다. Stand-In은 얼굴 identity를 **클립 전체 + 여러 씬에 걸쳐** 고정 → 캐릭터 일관성이라는 진짜 목표에 정확히 맞는다.

**Animate가 나중에 값어치 하는 경우(지금은 아님):** 실제 구동 영상에서 정확한 동작/립싱크를 이식하거나, 얼굴을 넘어 전신+의상까지 완전 고정해야 할 때.

### 전환에 따른 정리 (2026-07-05 완료)
- [x] Animate 자산(~21GB) 삭제: Animate 14B fp8 / clip_vision_h / sam2 / lightx2v_I2V / WanAnimate_relight LoRA. 공유 캐시(`Kijai/WanVideo_comfy`의 umt5·Wan2.1 VAE·lightx2v_**T2V**·Wan2.1-T2V-14B)는 보존.
- [x] 다운로드 스캐폴딩(`ComfyUI/download_animate_models.*`) 제거.

---

## A. 이미 보유한 Stand-In 자산 (추가 다운로드 0)

| 자산 | 경로 | 상태 |
|---|---|---|
| 기반 모델 Wan2.1-T2V-14B fp8 | `ComfyUI/models/diffusion_models/Wan2_1-T2V-14B_fp8_e4m3fn.safetensors` | ✅ |
| VAE Wan2.1 bf16 | `models/vae/Wan2_1_VAE_bf16.safetensors` | ✅ |
| Text encoder umt5-xxl-enc | `models/text_encoders/umt5-xxl-enc-bf16.safetensors` | ✅ |
| Stand-In LoRA | `models/loras/Stand-In_wan2.1_T2V_14B.ckpt` (strength 1.0) | ✅ |
| lightx2v **T2V** distill LoRA | `models/loras/lightx2v_T2V_14B_cfg_step_distill_v2_lora_rank64_bf16.safetensors` | ✅ |
| Kijai WanVideoWrapper | `custom_nodes/ComfyUI-WanVideoWrapper` (`WanVideoAddStandInLatent` 등) | ✅ |
| Stand-In Preprocessor 노드 | `custom_nodes/Stand-In_Preprocessor_ComfyUI` | ✅ |
| 예제 워크플로우 | `.../example_workflows/wanvideo_2_1_14B_Stand-In_reference_example_01.json` | ✅ 출발점 |
| 검증된 출력 스펙 | 832×480, 81프레임 (사용자 확인: 빠르고 퀄리티 좋음) | ✅ |

→ **Phase 1(다운로드)은 사실상 완료.** 남은 건 워크플로우 export와 코드 연결.

---

## B. 코드 현실 (전 개정판 확인 결과, 유효)

- `tools.py`의 비디오 함수는 **`call_video`** 하나. `matched_image` 있으면 :8500 **/generate_i2v**, 없으면 **/generate**(T2V). (`tools.py:136`, WAN_URL=`AGENT_WAN_URL`, 기본 :8500)
- `nodes.py:224` `node_generate_one_clip`이 `tools.call_video(..., matched_image=scene.get("matched_image"))` 호출. quality_flag는 `"pending"`으로만 둠 — 퀄리티 체크 로직 미구현.
- 씬 라우팅: `matched_image`(그 인물이 등장하는 참조 파일명) 유무로 갈림. `image_role`("start"/그외)은 **Stand-In에선 무의미** (첫 프레임 조건이 아니라 identity 주입이므로) — 무시 처리.
- :8500 서버는 상주형(재시작 없인 콜드로드 없음). ComfyUI는 :8188 상주.

---

## Phase 0 — 병목 진단 ✅ 완료 (2026-07-05 실측, 유효)

- 병목은 콜드로드가 아니라 **추론 자체**. 에이전트 설정(20 step·1280×704·49f)으로 :8500 직접 호출 시 클립당 184~233초. 가벼운 설정(6 step·832×480·33f)은 25초.
- **속도 레버 (identity와 별개, 마이그레이션 불필요):** 스텝 축소(20→6~8, 가장 큰 레버)·해상도 축소·distill LoRA. Stand-In 경로는 lightx2v_T2V distill을 이미 포함하므로 속도도 자연히 유리.

---

## Phase 1 — 준비물 ✅ 사실상 완료

- [x] **1-1.** Stand-In 모델/노드 전부 보유 (위 A표). 추가 다운로드 없음.
- [x] **1-2.** ComfyUI(:8188)에서 로드/실행 확인. **주의:** WanVideoWrapper 배포 예제(`wanvideo_2_1_14B_Stand-In_reference_example_01.json`)는 얼굴 전처리를 MediaPipe FaceMesh + essentials REMBG + KJNodes crop 12노드 체인으로 하는데 **이 노드들은 설치돼 있지 않다.** 대신 설치된 전용 노드 `Stand-In_Preprocessor_ComfyUI`(`FaceProcessorLoader`→`ApplyFaceProcessor`)가 그 전처리를 1~2노드로 대체 → 그쪽 example(`.../Stand-In_Preprocessor_ComfyUI/example/wanvideo_Stand-In_reference_example.json`)이 현재 설치 상태로 도는 올바른 출발점. 핵심 Wan 노드(ModelLoader/Sampler/AddStandInLatent/Decode/VideoCombine/LoraSelect)는 전부 설치됨. **이미 07-03에 이 워크플로우로 성공 실행 이력 11건 존재**(`/history`).
- [ ] **1-3.** 메모리 계획: 검증 기간엔 :8500 상주(fallback) + ComfyUI(14B Stand-In) 동시. GB10 통합 119GB 중 현재 ~75GB 사용. Stand-In은 단일 14B라 Animate 2패스보다 여유. 부족하면 **미사용 :8600(구 Animate 서버) 먼저 내림** — LangGraph가 안 씀.

---

## Phase 2 — Stand-In 워크플로우 제작/export ✅ 완료 (2026-07-05)

**핵심 지름길:** 밑바닥부터 만들 필요가 없었다. ComfyUI `/history`에 07-03 성공 실행 그래프가 **이미 API 포맷**으로 남아 있었고(모델 파일명 로컬 교정·죽은 CLIP 경로 제거·VideoCombine을 Decode에 직결·save_output=True 전부 반영된 상태), 그걸 그대로 캡처했다. UI→API 위젯 매핑을 손으로 하지 않음(→ Sampler의 control_after_generate 숨은 위젯 등 오매핑 리스크 회피).

- [x] **2-1.** 경로 확인: `LoadImage(58) → ApplyFaceProcessor(128) → WanVideoEncode(104) → WanVideoAddStandInLatent(102) → WanVideoSampler(27) → WanVideoDecode(28) → VHS_VideoCombine(74)`. 출력 832×480·81f, Stand-In LoRA(69)+lightx2v_T2V distill(71), **steps=4**. 단독 실행 검증(아래 2-1 결과) 완료.
- [x] **2-2.** 얼굴 추출은 설치된 전용 노드 `FaceProcessorLoader(130)→ApplyFaceProcessor(128)`가 담당(얼굴 크롭+중립 배경). → **matched_image가 얼굴 크롭이 아닌 전체 장면이어도 OK.** 배포 예제의 12노드 REMBG/FaceMesh 체인은 불필요(미설치).
- [x] **2-3.** API 포맷 export 완료 → `langgraph/comfyui_workflows/standin_t2v.json` (19노드, PreviewImage 제거). 치환 노드 ID는 `comfyui_workflows/README.md` 표에 기록:
  - 프롬프트: **node 16** `WanVideoTextEncode.positive_prompt` (CLIP 경로 아님 — 그건 죽은 노드였음)
  - 참조 이미지: **node 58** `LoadImage.image` (먼저 `/upload/image`로 올린 뒤 파일명 주입)
  - 해상도/프레임: **node 103** `width/height/num_frames`, 시드: **node 27** `seed`
  - 출력: **node 74** `VHS_VideoCombine.filename_prefix` (`save_output=true` 이미 설정)
- [x] **2-4.** 결정: **참조 없는 씬은 :8500 T2V 그대로, 참조 있는 씬만 Stand-In으로.** (게으른 기본값 채택 — 변경 표면 최소, ComfyUI 단일 큐 순차 부담도 완화) → Phase 3-2 분기에 반영.

**2-1 실측:** `standin_validate` 단독 제출 → `/prompt` 정상 접수(템플릿 round-trip OK) → `standin_validate_00001.mp4` 성공 생성. execution_start→success **282초**. 단, 이번이 세션 첫 Stand-In 실행이라 **14B 모델+LoRA 콜드로드 포함** — 웜 상태 후속 실행은 더 짧을 것(steps=4 distill). Phase 3 poll timeout는 콜드로드 대비 넉넉히(예: 600s)로 잡고, 웜 실측 나오면 조정.

---

## Phase 3 — 코드 수정 (langgraph) ✅ 완료 (2026-07-05)

- [x] **3-1.** `tools.py` `generate_standin_clip(job_id, scene_id, prompt, ref_image, duration, seed)`:
  `standin_t2v.json` 로드 → `/upload/image`로 참조 얼굴 업로드 → 노드 16(프롬프트)/103(w·h·num_frames)/27(steps·seed)/74(prefix·frame_rate)에 주입 → `/prompt` POST → `/history/{id}` 폴링 → `/view`로 mp4 다운로드 → `jobs/<job_id>/clip<id>.mp4` 저장. env: `AGENT_COMFYUI_URL`·`AGENT_USE_STANDIN`·`AGENT_STANDIN_STEPS`(4)·`AGENT_STANDIN_TIMEOUT`(600) 모두 run_agent.sh에 추가.
  - ⚠️ **해상도/fps는 T2V 경로와 동일하게 강제**(WIDTH/HEIGHT/DEFAULT_FPS 주입). ffmpeg `xfade`는 입력 클립 해상도가 다르면 실패 → 한 job의 모든 클립이 같은 규격이어야 concat됨. Stand-In 템플릿 기본은 832×480이지만 코드가 매 호출 override.
- [x] **3-2.** `node_generate_one_clip` 분기: `mode=="STANDIN"` → `generate_standin_clip`, 그 외 → 기존 `call_video`. quality_flag는 `"pending"` 유지.
- [x] **3-3.** env 스위치 `AGENT_USE_STANDIN`(기본 on). off면 참조 씬도 기존 T2V/I2V 경로. `call_video` 그대로 fallback 유지. 라우팅은 `node_generate_prompts`에서 `mode` 결정: 참조 있음+스위치 on → `"STANDIN"`.
- [x] **3-4.** `driver.py --dry`: `tools.generate_standin_clip`도 fake로 패치. dry e2e 통과(3 게이트 자동승인 → final.mp4).

### 3-α. 프롬프트 품질 개선 (사용자 요청: 이전 예제의 무표정·고정자세 해결)
문제: Stand-In은 얼굴 일관성은 좋지만 **표정/자세/구도가 참조 사진처럼 고정**돼 어색했음.
근본원인: (1) 프롬프트가 표정·감정을 명시 안 함 → diffusion이 무표정으로 수렴, (2) 기존 코드가
ref 씬에 **외모 캡션(캐릭터록)을 프롬프트에 주입** → identity가 이미 latent로 들어오는 Stand-In에선
표정까지 정지 강화. 조치:
- `_scene_prompt_system(standin)`: shot/각도(씬마다 변주)·자세·**표정과 감정(mood 반영)**·카메라 무빙을
  요구하고 "static·stiff·frozen·blank face 피하라" 명시.
- Stand-In 씬: system에 "얼굴/외모/나이/의상 묘사 금지 — 오직 행동·감정·표정·구도만" 지시 + **외모 캡션 주입 제거**.
  → 정체성은 이미지, 표정·동작은 프롬프트가 자유롭게 몰아줌.

**3 실측:** `generate_standin_clip` 라이브 단독 호출(웜) → 832×480@16fps·2.06s 클립 정상 생성, **90초**.
업로드→주입→submit→폴링→view→저장 전 경로 확인. (콜드 첫 실행은 Phase 2-1의 282초 참고.)

---

## Phase 4 — 테스트 및 전환 확정

- [ ] **4-1.** e2e: matched_image **없는** 씬 1개(T2V) / **있는** 씬 1개(Stand-In) 각각 `driver.py`로 실행.
- [ ] **4-2.** 같은 인물이 나오는 **여러 씬**에서 얼굴이 일관된지 **육안 비교** (이게 진짜 목표). 기존 I2V 결과와 대조. 배치 총 소요시간도 기록.
- [ ] **4-3.** 확정 시: fallback 유지 여부 결정, 미사용 :8600 프로세스 정리(run.sh 프로세스 kill, 재부팅 자동시작 없음 확인).
- [ ] **4-4.** `video_generator/CLAUDE.md`·`README.md` 아키텍처 섹션에 "참조-이미지 씬 = ComfyUI Stand-In T2V" 반영. Open WebUI function의 AGENT_URL 영향 없음 확인.

---

## C. 미해결 리스크

- **ComfyUI 단일 큐** → LangGraph의 Send fan-out 병렬이 ComfyUI에선 사실상 순차. (참조 있는 씬만 Stand-In으로 보내면 순차 부담 완화)
- **Stand-In 전제**: 참조 이미지에 **식별 가능한 정면 얼굴**이 있어야 identity 주입이 잘 됨. 얼굴이 작거나 옆모습/뒷모습 위주 참조면 효과 약함 → Phase 2-2의 얼굴 추출 품질이 관건.
- 병목이 추론 속도(Phase 0 확인)인 점은 유효 — 속도가 문제면 스텝/해상도/distill 레버로 별도 대응(마이그레이션과 무관).
