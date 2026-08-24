# 제품만 첨부 + 다양한 사람 모드 (2026-08-14)

사용자 결정: **인물 일관성·배경 일관성·제품 일관성을 동시에 유지하는 건 접는다.** 대신
"다양한 사람이 제품을 쓰는" 광고로 간다. 인물 생성(M2)을 생략하고, 마지막 씬은 인물 없이
제품 히어로샷.

입력은 UI의 **"시나리오만" 모드**와 동일하다 — `image_request` 없이 `script_text` +
제품 사진 1장. `graph._entry_router`가 2-3(이미지 승인)·2-4(시나리오 입력) 게이트를
건너뛰고 곧장 1-4로 간다.

프로브: `langgraph/tests/probe_product_only_e2e.py`
테스트: `langgraph/tests/test_product_only_various_people.py`

## 1. 이 모드가 기존 코드에서 깨지던 곳

| # | 증상 | 원인 | 수정 |
|---|---|---|---|
| 1 | 사람이 나오는 씬이 `SUBJECT_REF`(Wan 참조 경로)로 감 → 참조에 없는 인물·손·동작을 못 그림 | 참조가 1장이면 전 씬 `subject_type`을 캡션값(nonhuman)으로 굳혔다 | `nodes.py` 단일참조 분기: 제품 1장 job은 씬별 인물 신호로 human/nonhuman을 가른다 |
| 2 | 조립 라우팅이 안 걸림 | 게이트가 `face_id_ref or job_has_human_ref`였다 — 인물 **참조**가 있어야만 조립 | `job_has_person_scene`(씬 중 하나라도 human) 추가. 사람이 한 씬도 없는 마스코트 job은 그대로 SUBJECT_REF |
| 3 | 전 씬이 히어로컷("no people")이 돼 사람이 통째로 사라짐 | 히어로 판정이 `face_ref is None`이었다. 이 모드는 **전 씬이** face_ref=None | `generate_product_scene_clip(hero=...)` 인자로 승격. nodes가 `subject_type != "human"`으로 넘긴다 |

## 2. 라이브에서 드러난 것 (job 8820932b, 씬1)

첫 실행은 씬 배정까지 정상이었는데 **첫 프레임이 깨졌다**. 두 원인 모두 코드베이스에
이미 문서화돼 있던 함정이었다.

![씬1 실패](../../langgraph/jobs/8820932b-e506-45c7-b583-134c4ace66cc/assembly/scene1_flat.png)

1. **빈 손이어야 할 그립에 T2I가 우유잔을 그렸다.** 인물 씬 배경에 씬 문장(동작 서술)을
   주입한 게 원인. Kontext 경로는 같은 이유로 **장소·의상·조명만** 넣는다
   (`tools.py` PRODUCT_HELD_BG_PROMPT 위 주석, 2026-08-13 실측). 제품 명사구를 지워도
   문장의 의미가 음료를 요구하면 diffusion은 음료를 그린다.
   → 인물 씬 T2I 배경도 동작을 빼고 **인물 외형 + 장소 + 조명**만 넣는다.
2. **병이 뺨에 붙었다**(`center_x=0.741`, 실제 손은 0.45 근처). `locate_grip`은 인물
   마스크 안 살색을 연결요소로 쪼개 "얼굴과 분리된 덩어리 = 팔·손"으로 보는데, T2I가
   그린 **V넥** 때문에 얼굴-목-가슴이 한 덩어리가 되면서 판정이 무너졌다. 베이스라인이
   멀쩡했던 건 인물 정본이 흰 크루넥 티였기 때문이다.
   → T2I 그립 프레이밍에 "plain high crew-neck, no exposed chest skin"을 못박는다.
3. 부수적으로 "체육관"이 **실외 농구코트**로 나왔다. 4B 번역 + 골든아워 조명 락이
   겹친 결과. 실내 씬이 섞인 시나리오에서는 `AGENT_SCENE_LIGHTING`을 장소 중립으로
   두어야 한다.

## 2.5 T2I 배경은 이 경로를 못 만든다 — 씬별 인물 정본으로 전환 (job 872beeee)

§2의 두 함정을 고친 뒤 다시 돌렸다. 결과: **2개는 해결, 포즈는 실패**.

| 항목 | 결과 |
|---|---|
| 빈 손에 음료 안 생기게 | ✅ 손이 비어서 나옴 |
| 실내 체육관 | ✅ 러닝머신·거울 있는 실내 |
| 쥐는 손 모양 | ❌ **손가락 5개를 활짝 폈다** |
| 병 위치 | ❌ `clamped`, center_x 0.809 — 어깨에 붙음(실제 손은 0.4 근처) |

프롬프트를 아무리 정교하게 써도 T2I는 "빈 원통형 그립"을 안 만든다. Kontext는 만든다 —
**이미 있는 사람을 다시 포즈시키는** 모델이라서다. 베이스라인이 성공한 이유가 그것이고,
정본 없이 그 자세를 요구한 게 설계 착오였다.

**전환(사용자 승인 2026-08-14)**: 씬마다 T2I로 포트레이트 1장을 뽑아 `face_ref`로 준다
(`nodes._ensure_scene_person_ref`). 그 뒤는 검증된 Kontext 경로 그대로다. 인물 일관성은
**씬 안에서만** 유지되고 씬끼리는 다른 사람 — 이 모드의 의도와 일치한다.

- 인물 설명은 `_make_scene_context`의 `person` 필드 재사용(LLM 추가 호출 없음)
- 시드는 `scene_seed()` — 재실행 시 같은 사람
- 포트레이트에 크루넥 강제. LLM이 "sports bra"라고 써도 하이넥으로 나왔다(실측)
- 생성 실패 시 기존 T2I 배경 경로로 폴백

## 2.6 메모리 — FLUX는 24GB가 아니라 35GB다

`FLUX_KEEP_RESIDENT=1`을 시도했다가 earlyoom에 두 번 죽었다. `nvidia-smi` 실측:

| 프로세스 | GPU 메모리 |
|---|---|
| FLUX.1-schnell (로드 상태) | **34.9GB** |
| ComfyUI (유휴, 모델 언로드 후에도) | 19.9~22.6GB |
| ollama gemma3:4b | 4.1GB |

베이스라인 문서의 "24GB"는 과소평가였다. FLUX 상주 + ComfyUI 20GB면 가용이 earlyoom
임계(`-m 15,5` = 18GB) 아래로 떨어지고, earlyoom이 badness 최고인 FLUX를 죽인다:

```
low memory! at or below SIGTERM limits: mem 15.00%
sending SIGTERM to process ... "python": badness 853, VmRSS 9853 MiB
```

**결론: 이 머신에서 FLUX 상주는 불가.** 호출당 150초 콜드로드를 감수한다.

부수 발견 2개:
- ComfyUI는 `POST /free`로 모델을 내려도 **RSS/GPU 메모리를 안 놓는다**(할당자 캐시).
  22.6GB를 회수하려면 `start_studio.sh --down/--up comfyui`로 재기동해야 한다.
  긴 세션 뒤 E2E를 걸기 전에는 이걸 먼저 한다.
- earlyoom이 FLUX를 죽이면 systemd가 5초 뒤 되살리는데, 그 창에 다음 호출이 물리면
  job이 `ConnectError: All connection attempts failed`로 죽는다. 에이전트에 connect 재시도가
  없다.

## 2.7 그립 검출은 "드러난 피부"에 통째로 의존한다 (probe_person_ref)

인물 정본 → Kontext 경로로 바꾸자 **자세는 한 번에 나왔다** — 빈 원통형 그립 손, 가슴
높이, 같은 사람. T2I가 두 번 실패한 그 포즈다. 남은 실패는 전부 `locate_grip` 쪽이었고,
증상은 달랐지만 원인은 하나다: **살색 픽셀이 예상 밖의 덩어리로 뭉친다.**

| 시도 | 증상 | 뭉친 것 | 조치 |
|---|---|---|---|
| 1 | 병이 뺨에 | V넥 가슴 살 + 얼굴 | (T2I 경로, 아래 2·3으로 이어짐) |
| 2 | 병이 어깨에 | 민소매 어깨 + 팔 | — |
| 3 | 병이 주먹 옆에 | 어깨가 "팔 상단 40%"에 포함 | 정본에 **긴팔** 강제 |
| 4 | 병이 주먹 아래 | 가슴 살 + 얼굴·목 → 얼굴 bbox 아래끝이 턱(300px)이 아니라 460px → 밴드가 통째로 아래로 밀림(515~970) | 인물 설명에서 **상의 묘사 금지** |

코드로 고친 것 2개(둘 다 회귀 테스트 있음, `test_grip_clamp.py`):

1. **따뜻한 색 옷이 피부로 판정됨** — `(r-b)>40 & r>90` 만 보던 판정에 `r>g>b`를 추가.
   핑크 rgb(247,122,172)는 g<b라 이제 걸러진다. 같은 파일 `_skin_mask`가 이미 쓰던 식이라
   두 곳의 기준이 갈라져 있던 것을 합친 것이다. 이걸 놓치면 살색이 프레임의 22%를 덮고
   얼굴 bbox가 8x0px 파편이 돼 제품 폭이 4px로 계산된다(= 병이 화면에서 사라짐).
2. **양팔이 보이면 크기로 못 가름** — 쥔 팔 2606px vs 늘어뜨린 팔 2607px, 1픽셀 차이로
   max()가 반대편을 골랐다. 배경 프롬프트의 "forearm angled up **across the body**"를
   기준으로 삼아, 얼굴 x범위와 겹치는 팔을 우선한다. 밴드도 좌우 대칭으로 고쳤다
   (-0.6/+1.2 → ±1.2 — 비대칭은 배경 한 장에 맞춘 값이었고 Kontext는 손을 반대편에도 그린다).

프롬프트로 고친 것 2개 — **의상은 미관 문제가 아니라 검출 문제다**:

- `PERSON_REF_PORTRAIT_PROMPT`: 긴팔 + 하이 크루넥 강제. 드러난 살색이 얼굴과 손뿐이면
  "얼굴과 분리된 덩어리 = 손"이라는 가정이 그대로 성립한다.
- `_LIGHTING_SYSTEM`의 person 필드: **상의를 묘사하지 마라**. "pink sports bra" 같은 값이
  같이 들어가면 diffusion이 크루넥 지시와 섞어 파인 목선을 그린다. 모자·안경은 허용
  (씬 정체성이고 피부 판정과 무관).

**정공법은 포즈 검출기다.** 이 머신에서 오늘은 불가:
- `SDPoseKeypointExtractor` — MODEL+VAE를 더 올려야 한다(§2.6의 메모리 여유 없음)
- `WanVideoUniAnimateDWPoseDetector` — 출력이 스켈레톤 **이미지**라 좌표를 못 준다.
  onnx 가중치도 없고 `HF_HUB_OFFLINE=1`이라 받을 수도 없다

손목 키포인트를 쓰면 의상·포즈 가정이 통째로 사라진다. 다음에 이 경로를 또 손대야 하면
색 휴리스틱을 더 깎지 말고 검출기부터 붙일 것.

## 3. 이 모드의 실행 설정

```bash
AGENT_SCENE_LIGHTING="soft warm key light, bright clear exposure, gentle natural shadows" \
AGENT_PRODUCT_TINT_STRENGTH=0.15 \
PYTHONUNBUFFERED=1 setsid nohup ./run_agent.sh > server_8700_product_only.log 2>&1 &
```

- 조명: 베이스라인의 골든아워 락(`warm golden late-afternoon backlight`)은 실내 씬을
  실외로 끌고 간다. 장소 중립으로 바꾼다.
- 틴트: `PRODUCT_TINT_STRENGTH=0.30`은 **골든아워 전용** 튜닝값이다. 조명을 바꾸면
  같이 낮춘다(안 낮추면 실내 씬에서 제품만 주황빛).
- `AGENT_SCENE_COUNT=5`는 `run_agent.sh` 기본값.
- 이 모드는 LTX 2.3 22B Face-ID를 **한 씬도 안 쓴다** → 22B GGUF 축출 벽
  (`2026-08-13-scene5-e2e-handoff.md` §2)이 원천적으로 안 생긴다.

## 4. 시나리오 작성 규칙

씬1~N-1(인물 씬): 인물 명사(`_HUMAN_TEXT`) + 손동작 어휘(`_HAND_ACTION_TEXT`)를 **둘 다**
넣는다. 인물 명사가 있어야 조립 경로로 가고, 손동작이 있어야 `hand_held=True`로 빈 그립
손 배경 경로를 탄다. 장소는 한국어로도 명시적으로("체육관" ❌ → "실내 체육관" ✅).

마지막 씬(히어로컷): 인물 명사도 손동작 어휘도 **넣으면 안 된다**. "사람 없는"처럼
부정문에 인물 명사를 써도 정규식이 걸어 인물 씬으로 잡힌다. 제품 명사만 남긴다.

## 5. 남은 것

- 클립 완주 결과(런2 job `fbb1e579`) 확인 — 특히 그립 위치와 씬별 인물 다양성
- `locate_grip`의 살색 연결요소 방식은 의상에 취약하다. 크루넥 지시는 회피책이지
  해결책이 아니다 — 사람 검출(포즈 키포인트)로 바꾸는 게 정공법
