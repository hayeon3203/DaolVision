# 5씬 E2E 인수인계 (2026-08-13 밤)

씬5 히어로컷 + clip2/clip4 수정을 넣고 E2E를 3회 시도했으나 **클립 완주는 못 했다**.
코드 수정은 전부 들어가 있고 씬 배정 단계까지 검증됐다. 다음 세션은 이 문서부터 읽는다.

## 1. 들어간 코드 수정 (커밋 안 됨, 워킹트리에 있음)

| 파일 | 변경 | 검증 |
|---|---|---|
| `langgraph/nodes.py:433` | `SCENE_COUNT`(env `AGENT_SCENE_COUNT`, 기본 4). 씬분할 프롬프트·개수검증·교정재요청·정규화가 공유 | ✅ 5씬 분할 확인 |
| `langgraph/nodes.py:818` | 제품 forward-fill 해제 — 인물 명사 있고 손동작 없는 씬은 상속 끊음 | ✅ 씬4 `role=ref matched=gen_0.png` |
| `langgraph/nodes.py:523` | `_PRODUCT_TEXT`에 `water` 추가(4B가 "음료수"를 "cool water"로 번역) | ✅ 테스트 |
| `langgraph/nodes.py:337` | 캡션 실패를 `[caption]` 로그로 노출(전엔 조용히 삼켜 배정이 무너짐) | ✅ |
| `langgraph/nodes.py` `_scene_prompt_system` | "인명을 지어내지 마라" 문구(환각 이름 `Elias` 대응) | 미검증 |
| `langgraph/tools.py:1474` | `_PRODUCT_PHRASE_RE` 확장 — 임의 형용사 3개까지+소유격. `a water bottle`/`the approaching bottle`이 안 지워져 배경에 병이 생기던 것 | ❌ 조립 씬까지 못 감 |
| `langgraph/tools.py` | `PRODUCT_HERO_FRAMING` + `PRODUCT_HERO_RATIOS(0.30,0.50,0.88)`, `face_ref is None`이면 히어로 분기 | ⚠️ 배정만 확인 |
| `langgraph/tools.py` `locate_grip` | clamp — 얼굴 bbox 기준 밴드로 좌표를 당김. 기각→고정픽셀 폴백을 없앰. `source=hand/clamped/estimated` 로그 | ❌ 미검증 |
| `langgraph/tools.py` `clean_llm_prompt` | 한글 제거(대응표가 출력에 섞여 wardrobe lock이 `a white 반팔 (short-sleeve) t-shirt`가 됨) | ✅ |
| `scripts/start_studio.sh:82` | comfyui `--highvram` 제거 | ✅ clip1 8:53→5:12 |
| `langgraph/run_agent.sh:54` | `AGENT_SCENE_COUNT=5` | ✅ |
| `langgraph/tests/test_hero_cut_and_product_release.py` | 신규 8케이스 | ✅ 통과 |
| `langgraph/tests/test_grip_clamp.py` | 신규 5케이스(합성 프레임) | ✅ 통과 |
| `langgraph/tests/probe_ui_full_flow_e2e.py` | 시나리오 5문장으로 교체 | — |

기존 테스트 3개(`test_scene_seed`, `test_scene_lighting`, `test_scene_context_fallback`)는
**이 작업 이전부터 실패** — 2026-08-13 베이스라인 변경(시드 상수화·조명 락)을 테스트가 안 따라간 것.

## 2. 막힌 지점 — LTX 2.3 22B GGUF 축출

Face-ID 씬이 **2개가 되는 순간** 터진다.

```
VAE 디코드가 메모리 요구 → ComfyUI free_memory → partially_unload
  → ComfyUI-GGUF ops.py _quantized_apply → convert   (파이썬 단일 스레드)
GPU-Util 1%, CPU 1코어 100%, 10~40분 정체
```
py-spy 스택으로 확정. 이미 문서화돼 있던 병목이다 — `docs/spikes/3.3-ltx-bottleneck-profile.md:40`
("GGUF dequant 스레드 단일스레드 99.9% CPU, 24분+"), `docs/spikes/3.4-ltx-lightweight-sweep.md:69`,
그리고 `langgraph/tools.py:2060` 도크스트링("1씬 6분 → 2씬 배치 40분+, job 865ee53a").

**원인 제공은 clip4 수정이다.** 씬4에서 제품을 떼자 `role=ref`가 되어 22B Face-ID 경로로 갔고,
베이스라인(씬1만 Face-ID)에 없던 조건이 만들어졌다.

fp8 교체는 불가 — `docs/spikes/3.1-ltx-faceid-compat.md:26` 기준 22B 배포판은 **bf16 46.1GB**와
**커뮤니티 GGUF Q6_K 17.8GB** 둘뿐이고, Q5_K_M은 3.4 스윕에서 얼굴 정합성 하락으로 미채택.
GGUF Q6_K + rank-111 distill LoRA가 Best-Face-ID LoRA 저자의 공식 검증 조합이기도 하다.

## 3. 사용자 결정 (2026-08-13)

**씬4도 조립 경로(LTX 13B fp8)로 보낸다.** 씬2·3에서 조립 경로 인물 품질이 충분하다고 판단.
22B Face-ID는 씬1 하나로 유지 → 베이스라인과 같은 프로파일로 복귀.

구현해야 할 것: 조립 경로에 **제품을 합성하지 않는 변형**이 필요하다. 현재
`generate_product_scene_clip`은 항상 제품 픽셀을 얹고 Kontext 재통합까지 한다.
씬4는 배경 생성(T2I + `person_appearance`) → I2V만 타야 한다.
`nodes.py` 2참조 분기에서 제품이 해제된 씬을 Face-ID가 아니라 이 경로로 라우팅한다.
얼굴 identity는 캡션·의상 lock 텍스트 수준으로만 유지된다(씬2·3과 동일한 수준).

## 4. 실행 전 환경 준비 (필수)

세션 종료 시점에 **전부 내려둔 상태**다.

```bash
# 1) 페이지 캐시 비우기 — CUDA 가시 여유가 여기서 결정된다 (sudo 필요)
sudo sh -c 'sync; echo 3 > /proc/sys/vm/drop_caches'

# 2) ComfyUI (--highvram 없이)
cd /home/admin/DaolVision && ./scripts/start_studio.sh --up comfyui

# 3) T2I FLUX :8501
cd /home/admin/DaolVision/inference_server && nohup ./run_flux.sh > flux.log 2>&1 &

# 4) 에이전트 :8700 (AGENT_SCENE_COUNT=5, 로그 실시간)
cd /home/admin/DaolVision/langgraph && PYTHONUNBUFFERED=1 nohup ./run_agent.sh > server_8700_scene5.log 2>&1 &

# 5) 비전 모델 워밍 — 콜드로드면 캡션이 실패하고 씬↔참조 결정론 배정이 통째로 꺼진다
#    (job f7c7b356 실측: 5씬 전부 face_id_ref 없이 제품 사진이 인물 씬 참조로 붙음)
curl -s http://127.0.0.1:11434/api/generate -d '{"model":"gemma4:latest","keep_alive":-1}'

# 6) E2E
cd /home/admin/DaolVision/langgraph && nohup ./.venv/bin/python -u tests/probe_ui_full_flow_e2e.py > probe_e2e_scene5.log 2>&1 &
```

확인 지표:
- `curl -s localhost:8188/system_stats` → `vram_free`가 **40GB 이상**이어야 안전
- `grep '\[caption\]' server_8700_scene5.log` → 비어 있어야 정상
- 씬 배정에 `face=gen_0.png`가 붙어야 정상
- 정체 판정: **GPU-Util 1% + ComfyUI CPU 1코어 100%가 10분 이상** → GGUF 축출 재발

## 4.5 조립 씬 라이브 검증 결과 (2026-08-14 새벽, 22B 없이)

`tests/probe_assembly_scenes_235.py`(씬2·3·5) + `tests/probe_scene4_no_product.py`(씬4)로
22B Face-ID를 건너뛰고 조립 경로만 돌렸다. 산출물: `jobs/probe_assembly_235/`.

| 씬 | 결과 | 판정 |
|---|---|---|
| 2 | 병이 벤치가 아닌 **코트 허공**에, 폭 95px(0.074)로 작음. 재생 시 **벤치와 병이 같이 흔들림** | ✗ |
| 3 | 그립 검출 성공(`source=hand`, center_x 0.641 — 스파이크 수동값 0.62와 근접). 다만 **병이 작게 시작해 커지는 현상 재발** | △ |
| 4 | 제품 없이 배경 T2I + I2V로 생성됨(22B 안 씀) | 사용자 확인 대기 |
| 5 | 히어로컷 폭 383px(0.30), 인물 없이 제품 단독 — **사용자 "딱 좋음"** | ✓ |

배경 T2I가 clip2에 병을 그리지 않은 것도 확인됐다(`_PRODUCT_PHRASE_RE` 확장이 실제
프롬프트 `a water bottle`/`the approaching bottle`을 지웠다).

**진단(공통 원인)**: 스파이크 한 장면에서 손으로 맞춘 **절대 좌표·절대 크기**를 배경이
매번 새로 생성되는 프로덕션에 그대로 옮긴 것. Plans 6.23이 "실제로 깨지는 걸 본 뒤에
검토"로 미뤄둔 지점에 도달했다.

**다음 세션 작업 계획(사용자 승인 대기)**
1. **clip3 — 얼굴 기준 크기**: `locate_grip`이 계산해두고 버리는 얼굴 bbox를 반환해
   `product_px = 0.50 × face_w`로 잡는다(스파이크 실측 139/276 = 0.504). 검출 실패 시
   현재 상수 0.10 폴백. `AGENT_PRODUCT_FACE_RATIO`로 노출
2. **clip2 A-1(즉효)**: `PRODUCT_PLACED_RATIOS` (0.075, 0.30, 0.80) → (0.15, 0.50, 0.97).
   실측상 T2I가 벤치를 하단 중앙(x 0.32~0.68, y 0.86~1.0)에 그린다
3. **clip2 B(모션)**: 벤치·병이 같이 흔들리는 건 배치 문제가 아니라 카메라 패닝 지시
   (`camera slowly tracks his movement horizontally`) + 전경의 거대한 벤치 시차 탓.
   놓인 씬 프롬프트에서 카메라 이동을 빼고 negative에 전경 이동 억제를 넣는다.
   **A-1/A-2로는 안 없어진다**
4. **clip2 A-2(구조)**: 배경 하단 1/3에서 놓일 면을 검출해 그 위에 배치. 1·2·3 결과를
   보고 판단
5. **씬4 프로덕션 이식**: 제품 합성을 건너뛰는 조립 분기 + `nodes.py` 라우팅

검증은 같은 프로브를 같은 시드로 재실행해 직접 비교한다. 측정 지표(병폭/프레임폭,
병폭/얼굴폭, 면 상단과의 어긋남, 첫↔끝 프레임 크기 변화율)를 스크립트가 찍게 한다.

## 4.6 UI (완료·푸시됨)

`08e273b feat(ui): Agent 입력을 "인물 생성 + 제품 첨부" / "시나리오만" 2개 모드로 정리`
— main에 머지·`origin/main` 푸시 완료. 워크트리 `/home/admin/DaolVision-ui-modes`
(브랜치 `ui-two-modes`)는 남아 있다. 확인용 서버는 빌드본을 `vite preview`로 :5199에
띄웠다(dev 서버로 띄우면 워크트리의 node_modules 심볼릭 링크가 Vite `server.fs.allow`에
걸려 **폰트만 403** → 아이콘이 전부 깨진다. dev로 볼 거면 워크트리에서 `npm install`을
따로 하거나 `server.fs.allow`를 열어야 한다).

## 5. 남은 검증 항목

조립 씬(2·3·5)에서만 확인 가능하다.

1. `assembly/scene2_bg.png`에 **병이 없어야** 한다 → clip2 페트병 2개 회귀 (정규식 수정)
2. `[assembly] 씬3 그립(hand|clamped|estimated)` 로그 → clip3 clamp 동작
3. `assembly/scene5_*.png` + `clip5.mp4` → 히어로컷이 인물 없이 제품 단독으로 나오는가
4. 씬2 프롬프트에 이동 궤적 어휘가 있는가(4B가 "달려간다"를 "멈춰 선다"로 바꾼 실측 있음 → Plans 6.24 근거)

## 6. 참고 job

- 베이스라인 완주본: `langgraph/jobs/3ded2f29-769b-4747-ba83-9d319c7effe3/` (4씬, 38분)
- 오늘 취소된 것: `d7599e09`(22B 로드 정지), `92a9a76b`(배정 정상, 씬1 디코드 정지),
  `f7c7b356`(캡션 실패로 배정 붕괴), `ff208b73`(clip1 5:12 성공, 씬4 22B에서 정지)
