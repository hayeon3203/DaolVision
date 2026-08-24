# UI 풀 플로우 E2E 베이스라인 (2026-08-13)

job `3ded2f29-769b-4747-ba83-9d319c7effe3` — 프론트엔드와 동일한 `:8700` 경로로 4씬을
완주한 실행 중 **현재까지 가장 좋은 결과**. best 시나리오 후보로 이 설정·입력을 고정 기록한다.

산출물: `langgraph/jobs/3ded2f29-769b-4747-ba83-9d319c7effe3/`
소요: 38분 (15:38 시작 → 16:16 3-5 게이트 도달)

## 입력 (프론트에서 사람이 넣는 것과 동일)

**1. 이미지 생성 요청** (`image_request`)
```
20대 한국인 남자, 짧은 검은 머리, 흰 반팔 티셔츠, 정면 얼굴, 사실적인 사진
```

**2. 첨부 제품** (`ref_images`)
`langgraph/jobs/probe_bev_ad/assets/bottle_canonical_v3.png`
— 투명 배경 컷아웃 RGBA(투명 픽셀 190,793). **일반 사진(불투명)을 올리면 흰 배경째로
합성되므로 컷아웃이 전제다** — 프로덕션에 배경 제거 단계가 아직 없다.

**3. 시나리오** (`script_text`, 2-4 게이트)
```
한 남자가 농구장에서 땀 흘리며 공을 드리블하며 코트를 가로질러 달린다.
그는 농구 코트 한쪽 벤치에 놓인 음료수를 향해 달려간다.
벤치 앞에 멈춰 음료수를 집어 들고 시원하게 들이켠다.
다시 농구 코트로 돌아가 공을 잡고 힘차게 달려나간다.
```
- 4문장 = 4씬(씬분할 고정). 제품이 **2번째 문장부터** 등장해야 씬1이 순수 인물 경로를 탄다.
- 1번 문장은 점프슛 → 달리기로 바꾼 것. 점프는 도약·체공·착지가 한 컷에 섞여 불안정.
- 손동작 어휘("집어 들고")가 있는 씬만 `hand_held=True`(가장 취약한 경로)로 간다.

## 설정값

`langgraph/run_agent.sh`
```
AGENT_LLM_MODEL=gemma3:4b          # A/B 결과 채택. Nemotron 4B는 "코트"를 coat로 오역하고
                                   # setting을 환각, exaone3.5:32b는 21.6GB 상주가 FLUX를 압박
AGENT_LLM_KEEP_RESIDENT=1          # 3.3GB라 상주해도 안전
AGENT_VISION_MODEL=gemma4:latest   # 참조 캡션 전용
AGENT_VIDEO_PRESET=quality         # 1280x704. fast면 씬마다 해상도가 갈린다
AGENT_LTX13B_STEPS=8
```

`inference_server/run_flux.sh`
```
HF_HUB_OFFLINE=1        # 매 로드마다 HF 리비전 확인이 붙어 로드가 157s→646s로 늘었다
FLUX_KEEP_RESIDENT=0    # 1로 켜면 24GB가 잠겨 ComfyUI 모델 교체 여유가 사라진다
                        # (job 953eeea2: 스왑 15GB 전소, 여유 3GB, 20분+ 정체)
```

코드 상수 (1단계 결정론)
```
SCENE_DURATION_SECONDS      3.0     # 73프레임. 2.0초(49프레임)는 이동할 시간이 부족해
                                    # "슬로우모션"으로 보인다
SCENE_LIGHTING_LOCK         "warm golden late-afternoon backlight, bright clear exposure,
                             soft long shadows"   # mood 파생을 끊고 job 전체 1개로 고정
scene_seed 기반             "20260813" 상수 (job_id 무관) → 씬별 시드 1931120819 /
                            1283379657 / 2096494895 / 1098672158
LTX_FACEID_CAPTION_MAX_TOKENS  192  # 원본 1024. 4.0 tok/s라 씬당 4분+ 먹고 LTX 스왑 유발
PRODUCT_PLACED_RATIOS       (0.075, 0.30, 0.80)
PRODUCT_HELD_RATIOS         (0.10, 0.62, 0.87)
PRODUCT_TINT_STRENGTH       0.30    # 골든아워 전용. 조명 상수를 바꾸면 같이 조정할 것
FLUX_PRODUCT_BLUR           radius 10 / sigma 4
LTX_FACEID_STEPS            8
```

## 씬 배정 결과

```
씬1  role=ref            face=gen_0   드리블하며 달린다        → LTX_FACEID
씬2  role=character_ref  face=gen_0   물병 향해 달려간다        → PRODUCT_ASSEMBLY (hand_held=False)
씬3  role=character_ref  face=gen_0   물병 집어 들고 들이켠다   → PRODUCT_ASSEMBLY (hand_held=True)
씬4  role=character_ref  face=gen_0   코트로 돌아가 달려나간다  → PRODUCT_ASSEMBLY (hand_held=False)
```
4씬 전부 `face_id_ref`가 붙었다 — 인물 판정 forward-fill 반영 결과(이전 실행은 씬4가
주어 생략 때문에 `face=None` 히어로컷으로 오판됐다).

## 확보된 것

- 인물 일관성: 씬1·씬2가 같은 사람 (조립 경로에서 처음 성공)
- 의상: 흰 반팔 유지 (wardrobe lock을 이미지 생성 프롬프트에서 승격)
- 장소: 4씬 전부 실외 아스팔트 코트 (setting 영어화 전)
- 조명: 4씬 전부 골든아워 동일
- 움직임: 실제 이동 궤적이 생김 (슬로우모션 해소)
- 배경 군중 없음 (`empty` 명시)

## 남은 문제 (클립별)

| 클립 | 증상 | 추정 원인 |
|---|---|---|
| clip1 | 없음 — 인물 일관성·동작 양호 | |
| clip2 | **페트병 2개**. 배경 T2I가 자체 물병(무라벨)을 크게 그리고, **우리 광고 제품은 블러 처리**되고 다른 제품이 선명 | 배경 프롬프트에서 제품 명사구만 지웠을 뿐 "음료를 향해 달린다"는 맥락이 남아 T2I가 병을 생성. 우리 제품은 인물 마스크 밖이라 Kontext 배경 블러 대상 |
| clip3 | 인물 뒤에 **흰 그림자 같은 잔상**. 배경이 공원 도로(농구장 아님), 병이 손이 아닌 가슴 옆 | Kontext 인물 재렌더가 setting을 약하게 반영. 그립 검출이 폴백 좌표로 빠짐(clamp 미반영) |
| clip4 | 페트병이 **뜬금없이 합성 티가 남** | 놓일 면(벤치) 없이 고정 비율로 바닥에 배치 |

프롬프트 노이즈 2건도 관측: wardrobe lock에 한글이 섞임(`a white 반팔 (short-sleeve)
t-shirt` — 의상 오역 방지용 대응표를 LLM이 출력에 옮겨 적음), 씬3 프롬프트에 LLM이
지어낸 인물 이름(`Elias`)이 등장.

## 다음 단계

Plans 6.23(조립 노드 배치 자동화) / 6.24(few-shot + 검증기) / 6.25(인물 일관성 구조)
참조. 위 4개 증상이 그 세 태스크의 실측 근거다.
