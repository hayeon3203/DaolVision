# LTX Face-ID 화질/일관성 회귀 조사 — job 8557e925

작성: 2026-08-01. 비교 대상:
- **기준(양호)**: `/home/admin/video_generator/ComfyUI/output/video/LTX_2.3_ia2v_00001_.mp4`(2026-07-30 생성, ComfyUI 수동 실행 추정)
- **회귀(불량)**: `/home/admin/DaolVision/langgraph/jobs/8557e925-6646-44a9-8877-2673c2a7e66d/clip{1-4}.mp4`(2026-08-01 12:49-13:07, `:8700` 파이프라인 실제 job)

## 요약

사용자 가설(생성 시간이 너무 길어서(클립당 체감 ~20분) 그게 화질 저하의 주원인)을 검증하려고 두 산출물을 직접 대조했다. **결론: 주원인은 생성 시간 자체가 아니라, 이 job이 이미 식별·수정된 두 버그(스타일 강제 누락 + 참조이미지 포맷 불일치)가 고쳐지기 약 2시간 전에 돌았기 때문으로 보인다.** 다만 해상도/길이가 기준 워크플로와 다르게 오버라이드돼 있는 지점은 이 조사로는 원인 여부가 미확정이고, 재검증이 필요하다.

## 증거

### 1. 그래프/샘플러 설정은 완전히 동일

기준 mp4에 ComfyUI가 임베드한 워크플로 메타데이터(`ffprobe -show_entries format_tags`)를 파이프라인의 `langgraph/comfyui_workflows/ltx_faceid_api.json`(`_build_ltx_faceid_graph()`가 로드하는 그 파일)과 노드별로 대조:

| 항목 | 기준 mp4 임베드 메타 | 파이프라인 JSON | 일치 |
|---|---|---|---|
| 체크포인트 | `ltx-2.3-22b-dev-Q6_K.gguf` | 동일 | ✅ |
| distill LoRA | `ltx-2.3-22b-distilled-1.1_lora-dynamic_fro09_avg_rank_111_bf16.safetensors`, strength 0.6 | 동일 | ✅ |
| Face-ID LoRA | `Best_FaceID_v1.0_LoRA.safetensors`, strength 1.0 | 동일 | ✅ |
| 샘플러/스케줄러 | `euler_ancestral_cfg_pp` / `bong_tangent`, 8 steps | 동일 | ✅ |
| sigma 커브 | `1.0, 0.99375, ..., 0.0`(9값) | 동일 | ✅ |
| Identity 노드 | `LTXIdentityOverlapConditioning`(node 129), `reference_guidance_scale=1.0` | 동일 | ✅ |

→ **모델·LoRA·샘플링 파라미터는 회귀의 원인이 아니다.** 두 산출물은 같은 워크플로 파일을 쓴다.

### 2. job이 최신 버그 수정 커밋보다 먼저 돌았다

```
job 8557e925 생성:  2026-08-01 12:49:49 ~ 13:07:04
커밋 07b083a:       2026-08-01 14:57:07  (job보다 약 1시간 50분 뒤)
```

`07b083a`("fix: LTX Face-ID concat 다운스케일 버그 수정 + style_bible photoreal 강제, 자막 노드 제거")가 고친 항목 중 이 job에서 실제로 재현되는 증상 2가지:

**(a) style_bible이 화풍을 photoreal로 강제하지 않음** — 회귀 산출물의 clip1(공원, 사실적 조명)과 clip4(공원, 플랫 카툰 배경)를 나란히 보면 같은 job 안에서 화풍이 씬마다 다르다. `07b083a`가 정확히 이 증상("LLM이 애니메이션·플랫벡터 화풍을 골라 배경만 그림체로 나오는 불일치")을 고쳤다 — 이 job은 그 수정 전.

**(b) 참조 이미지 포맷 불일치** — `refs/img_0.jpeg`를 `file`로 확인하면:
```
refs/img_0.jpeg: RIFF (little-endian) data, Web/P image, VP8 encoding, 856x1141
```
확장자는 `.jpeg`인데 실제 내용은 WebP다. `07b083a`가 정확히 이 케이스("확장자와 실제 포맷이 다른 참조 이미지가 비전 모델 디코드 실패로 조용히 T2V 강등되는 문제")를 고쳤다 — `caption_image()`가 원본 바이트를 그대로 Ollama 비전 모델에 넘기던 걸, PIL로 정규화 후 PNG 재인코딩하도록 바꿨다. 이 job은 그 수정 전이라 캡션 단계가 조용히 실패했을 가능성이 높다(캡션 실패 자체가 `matched_image`를 null로 만들진 않지만 — Face-ID 그래프에 주입되는 인물 묘사 텍스트가 비었을 수 있다).

### 3. 육안 비교

`ffmpeg`로 프레임을 뽑아 직접 비교(경로: `/tmp/frame_compare/`, 이 문서엔 첨부하지 않음, 재현 명령은 아래):

- 기준 mp4: 우주비행사 헬멧 안 얼굴이 참조 사진과 뚜렷이 일치.
- 회귀 clip1/clip2/clip4: 참조 사진과도, 서로 간에도 다른 얼굴 — Face-ID identity transfer가 사실상 작동하지 않았다.

```bash
ffmpeg -y -i <video> -vf "select=eq(n\,0)" -vsync 0 -vframes 1 -update 1 frame.png
```

### 4. 해상도/길이 — 원인 미확정, 기준과 다르게 오버라이드됨

| | 기준 | 회귀(job) |
|---|---|---|
| 해상도 | 768×768(정방형, 워크플로 자체 기본값) | 1024×576(와이드, `LTX_FACEID_WIDTH/HEIGHT` env로 하드 오버라이드) |
| 길이 | 5.0초(121프레임) | ~2.4초(57프레임, 씬별 duration) |

`_build_ltx_faceid_graph()`가 `graph["100"]["inputs"].update(width=LTX_FACEID_WIDTH, height=LTX_FACEID_HEIGHT)`(코드상 명시적 오버라이드)와 `graph["31"]["inputs"]["value"] = duration`으로 기준 워크플로의 검증된 기본값(768², 5초)을 씬 파이프라인용 값으로 덮어쓴다. `LTXIdentityOverlapConditioning`의 `ref_resize_mode: match_target`이 정방형 대신 와이드 타겟에서도 동일하게 잘 작동하는지는 이번 조사로 확인 못 했다 — **재검증 필요, 회귀의 추가 원인일 수 있음.**

### 5. 생성 시간

`generate_ltx_faceid_batch()`(4씬 배치 경로)는 `comfy_prompts` SQLite 테이블에 기록을 남기지 않는다(`_generate_reference_clip`류와 달리 `_save_prompt` 호출 없음) — 씬별 정확한 GPU 렌더 시간은 이번 조사로 못 얻었다. 참조이미지 업로드(12:49:49)부터 4클립+자막+최종렌더 완료(13:07:04)까지 **총 17분 15초**(LLM 씬분할+캡션 포함, 4씬 배치 전체) — "클립당 20분" 체감과 오더 자체는 맞지만, 정확히는 **배치 전체** 시간이지 클립 1개당은 아니다. 정밀한 원인 규명(체크포인트 22B 로드 vs 실제 샘플링 vs LLM 오버헤드 비중)을 하려면 `_generate_ltx_job_clip`류 SQLite 타이밍 계측을 이 배치 경로에도 붙이는 게 필요.

## 권장 후속 조치

1. **재검증 우선**: `07b083a` 반영된 현재 HEAD로 동일 시나리오(같은 참조사진)를 다시 돌려서 style/identity 문제가 실제로 해소됐는지 확인 — 이게 이 조사의 결론을 확정 짓는 가장 빠른 방법.
2. 참조이미지 포맷을 업로드 시점에 한 번 더 정규화(현재는 `caption_image`/`_prepare_reference_upload` 개별 호출부에서만 PIL 정규화 — 원본 파일 자체를 job 시작 시 정규화해두면 두 번 다시 안 터짐).
3. `generate_ltx_faceid_batch`에도 `comfy_prompts` 타이밍 계측을 붙여 씬별 실제 GPU 렌더 시간을 관측 가능하게(현재는 총 wall-clock만 알 수 있음).
4. 해상도(1024×576) 오버라이드가 identity transfer 신뢰도에 영향 있는지 A/B(768² vs 1024×576, 나머지 파라미터 고정)로 별도 확인.
