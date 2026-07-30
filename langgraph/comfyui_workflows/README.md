# comfyui_workflows

langgraph agent용 ComfyUI API-format 워크플로우 템플릿 (`comfyui_migration_checkpoints.md`의 Phase 2).

## `i2v_14b.json` — I2V-14B 전체이미지 identity+화풍 (M3-9~: **subject_ref(비인간/제품) 경로 전용**)

참조 이미지(얼굴 또는 피사체, 1장) + 텍스트 프롬프트 → 832×480×45프레임(2.8초@16fps) 영상.
참조 이미지를 `WanVideoImageToVideoEncode`로 첫 프레임 latent 전체를 인코딩하기 때문에,
identity**뿐 아니라 화풍/분위기까지** 그대로 이어짐 — 아래 `standin_t2v.json`과 다른 점.
`standin_t2v.json`의 Stand-In 어댑터는 얼굴 임베딩만 주입하고, T2V-14B 체크포인트 자체의
(실사 위주) 화풍이 그대로 지배함. 체크포인트: `Wan2_1-I2V-14B-480P_fp8_e4m3fn` +
`lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16` LoRA(병합 안 함, strength 0.6).
얼굴 크롭 단계 없음 — 얼굴 참조와 피사체/마스코트 참조가 완전히 같은 그래프를 씀.

파이프라인: `LoadImage(58) → WanVideoImageToVideoEncode(105) → WanVideoSampler(27) →
WanVideoDecode(28) → VHS_VideoCombine(74)`.

아래 시간 측정값의 전제 조건: ComfyUI(`comfyui.service`)를 `--cache-classic --highvram`으로
실행해야 함 — `--highvram` 없으면 프롬프트마다 transformer/T5가 재로드됨(실측 +50~80초).
노드 16(T5)과 노드 105(이미지 인코딩) 둘 다 `force_offload`는 `false`.

### 주입 지점(Injection points)

| 노드 ID | class_type | 필드 | 템플릿 값 | 실제로 채울 값 |
|---|---|---|---|---|
| `58` | LoadImage | `image` | `__REF_IMAGE__` | 업로드된 참조 이미지 파일명 (먼저 `POST /upload/image`) |
| `16` | WanVideoTextEncode | `positive_prompt` | `__PROMPT__` | 씬 프롬프트 (negative_prompt는 그대로 둠) |
| `74` | VHS_VideoCombine | `filename_prefix` | `__PREFIX__` | 예: `<job_id>_<scene_id>`; 결과물은 `ComfyUI/output/<prefix>_00001.mp4`에 생성 |
| `27` | WanVideoSampler | `seed` | `0` | 실행마다 다른 seed |
| `105` | WanVideoImageToVideoEncode | `width/height/num_frames` | `832/480/45` | `tools.py`가 `WIDTH/HEIGHT`+길이로 설정 |

실측(`:8188` 실제 실행, 45프레임, steps=4, 모델 상주 상태): 총 **~65~72초**. 81프레임(5초 클립)은
~148초 측정 — 목표치 100초 초과라서 기본값을 45프레임으로 잡음.

### 결과물 가져오기
`GET /history/{prompt_id}`를 폴링. mp4는 `outputs[<74>].gifs[0].filename`에 있음
(subfolder `""`, type `output`) → `ComfyUI/output/<filename>`에서 읽어 `jobs/<job_id>/`로 복사.

## `standin_t2v.json` — Stand-In 얼굴 일관성 T2V (M3-9~: **face(사람) 경로 전용**, 배경 프롬프트 100%)

참조 얼굴(1장) + 텍스트 프롬프트 → 832×480×81프레임 영상, 클립 전체에 걸쳐 그 얼굴의
identity가 주입됨. 베이스: WanVideoWrapper의 Stand-In 예제이지만, **실제로 성공한 ComfyUI
실행 기록**(history `287811ee`)에서 캡처해왔기 때문에 모델 파일명이 전부 로컬 실제 파일명이고,
죽은 CLIP 텍스트 경로/미리보기/나란히 붙이기(side-by-side concat) 같은 안 쓰는 노드는 이미
제거된 상태.

파이프라인: `LoadImage(58) → ApplyFaceProcessor(128) → WanVideoEncode(104) →
WanVideoAddStandInLatent(102) → WanVideoSampler(27) → WanVideoDecode(28) → VHS_VideoCombine(74)`.
얼굴 추출(얼굴을 무배경으로 크롭)은 설치된 `FaceProcessorLoader(130) → ApplyFaceProcessor(128)`
노드가 담당 — 그래서 `matched_image`가 얼굴 크롭이 아니라 **전체 씬 이미지여도 문제없음**
(Phase 2-2에서 이미 처리됨). LoRA 두 개 다 적용: Stand-In(69) + lightx2v_T2V distill(71).

### 주요 노드

- **`22` WanVideoModelLoader**: `Wan2_1-T2V-14B_fp8_e4m3fn.safetensors`, fp8 양자화, `sageattn` 어텐션
- **`69`/`71` WanVideoLoraSelect**: Stand-In LoRA(strength 1.0) + lightx2v 4-step distill LoRA(strength 0.6) — 두 개 겹쳐 씀
- **`27` WanVideoSampler**: steps=4, cfg=1.0, shift=9.0, scheduler=dpm++_sde — distill LoRA 쓰니까 4스텝만
- **`130`/`128` FaceProcessorLoader / ApplyFaceProcessor**: `face_crop_scale=2.5`, `resize_to=512` — 커밋 `b91154d`에서 1.5→2.5로 인물 머리 과대 문제를 완화한 값
- **`102` WanVideoAddStandInLatent**: `freq_offset=25` — 커밋 `8a82b6c`에서 1→25로 얼굴 사각 누수를 제거한 값
- **`39` WanVideoBlockSwap**: `blocks_to_swap=0` — 메모리 참사 방지를 위해 오프로드를 꺼둠 (참고: `comfyui-8188-standin-resident` 메모리)
- **`16` WanVideoTextEncode**: positive는 `__PROMPT__` 플레이스홀더(agent가 채움), negative는 고정 중국어 품질 프롬프트

### 노드 상호작용 흐름

```
[58 이미지 로드] → [130+128 얼굴 검출/크롭] → [104 얼굴 인코딩] ─┐
                                                              ├→ [102 identity 주입] ─┐
                              [103 빈 캔버스 embeds] ──────────┘                      │
                                                                                      ├→ [27 샘플러] → [28 디코드] → [74 영상 합치기]
[11+16 프롬프트 텍스트 인코딩] ───────────────────────────────────────────────────────┤
                                                                                      │
[22 기본모델+Stand-In LoRA] → [70 blockswap설정] → [79 lightx2v LoRA 추가] ──────────┘
```

1. **얼굴 준비** (58→130→128→104): 참조 이미지를 넣으면 YOLO로 얼굴만 찾아 잘라냄(crop).
   `face_crop_scale=2.5`는 "얼굴 주변을 원래 얼굴 크기의 2.5배 넓이로 잘라라"는 뜻 —
   이 값이 낮으면 머리가 화면에서 이상하게 크게 나옴(과거 버그, 이미 고침). 잘라낸 얼굴
   이미지를 VAE로 "압축된 숫자 표현"(latent)으로 바꿈.
2. **identity 주입** (103+104→102): 텅 빈 영상 캔버스(103)에 방금 압축한 얼굴 정보(104)를
   끼워넣는 게 102번 노드. `freq_offset=25`는 "얼굴 정보를 영상 프레임의 어느 위치/주파수
   대역에 심을지" 조절값 — 너무 낮으면(과거 1) 얼굴 경계가 뭉개져서 사각형 티가 남(과거
   버그, 이미 고침).
3. **프롬프트 준비** (11+16): 사용자가 입력한 텍스트를 모델이 이해하는 숫자 벡터로 변환.
   positive(원하는 것) + negative(피할 것, 손가락 기형 같은 흔한 실패 패턴들을 미리 차단).
4. **모델 준비** (22→70→79): 기본 Wan2.1-14B 모델 위에 LoRA 두 장을 겹쳐 씀 — LoRA는
   "원본 모델은 안 건드리고 얇은 보정판을 덧씌우는" 방식.
   - Stand-In LoRA(69): 얼굴을 원본이랑 닮게 유지하는 역할
   - lightx2v distill LoRA(71, strength 0.6): 원래 20스텝 걸릴 걸 4스텝만에 끝내주는 속성 학습 LoRA
   - blockswap(39, `blocks_to_swap=0`)은 "모델 일부를 CPU로 빼서 VRAM을 아낄지" 설정 —
     지금은 0이라 안 뺌(다 GPU에 상주, 메모리가 넉넉해서)
5. **실제 그리기** (27 샘플러): 얼굴 identity(102) + 프롬프트(16) + 준비된 모델(79) 셋을
   받아서 4번 반복(steps=4) 노이즈 제거하며 영상 latent를 만듦. `cfg=1.0`은 프롬프트
   강제성이 거의 없다는 뜻(distill 모델 특성상 낮게 씀), `shift=9.0`은 노이즈 스케줄 튜닝값.
6. **완성** (28→74): latent를 다시 실제 픽셀 영상으로 복원(디코드)한 뒤 프레임들을 mp4로 합침.

핵심 한 줄: 얼굴 identity 경로(58→130→128→104→102)와 모델+프롬프트 경로(22→70→79,
11→16)가 27번 샘플러에서 합쳐져서 "이 프롬프트대로, 이 얼굴을 유지한 채" 영상을 생성하는 구조.

### 주입 지점 (Phase 3이 채움)

| 노드 ID | class_type | 필드 | 템플릿 값 | 실제로 채울 값 |
|---|---|---|---|---|
| `58` | LoadImage | `image` | `__REF_IMAGE__` | 업로드된 참조 이미지 파일명 (먼저 `POST /upload/image`) |
| `16` | WanVideoTextEncode | `positive_prompt` | `__PROMPT__` | 씬 프롬프트 (negative_prompt는 그대로 둠) |
| `74` | VHS_VideoCombine | `filename_prefix` | `__PREFIX__` | 예: `<job_id>_<scene_id>`; 결과물은 `ComfyUI/output/<prefix>_00001.mp4`에 생성 |
| `27` | WanVideoSampler | `seed` | `0` | 실행마다 다른 seed |

기타 조절값(실행마다가 아니라 JSON 자체에서 변경): `27.steps`(=4, 문서상 4~8 허용),
`103.width/height/num_frames`(=832/480/81). `save_output`은 이미 `true`(노드 74).

### 결과물 가져오기
`GET /history/{prompt_id}`를 폴링. mp4는 `outputs[<74>].gifs[0].filename`에 있음
(subfolder `""`, type `output`) → `ComfyUI/output/<filename>`에서 읽어 `jobs/<job_id>/`로 복사.
