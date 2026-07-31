# Task 5.2/5.3 재설계 — Flux 앵커 lock 제거, 3.2 순수 Face-ID 생성 복귀

작성: 2026-07-31 · 관련 Task: Plans.md 5.2, 5.3 (codex 구현분 재작업)

## 배경 / 문제

codex가 구현한 5.2(씬별 Flux 앵커 생성)+5.3(LTX Face-ID 배치 생성)을 실제
생성해 육안 검증한 결과 두 가지 결함 발견:

1. **얼굴 크기 급변**: 씬 프롬프트의 "slow camera push-in" 문구 때문에
   2초 클립 안에서 인물이 화면을 급격히 채움.
2. **얼굴 정체성 미반영(핵심 버그)**: 최종 영상의 얼굴이 참조 얼굴(건호군.jpg)과
   전혀 다른 사람으로 나옴. 재현 테스트에서 원인 확정:
   - `generate_scene_anchor()`(tools.py:501)는 Flux에 텍스트 프롬프트만 보내고
     얼굴 참조 이미지를 전혀 넘기지 않음 → 앵커 자체가 완전히 랜덤한 얼굴
     (재검증 테스트에서 전혀 다른 여성 얼굴 생성 확인, 스크린샷 근거 있음).
   - `_build_ltx_faceid_graph()`(tools.py:655-700)가 이 랜덤 얼굴 앵커를
     `LTXVImgToVideo strength=1.0`으로 첫 프레임 latent에 완전히 못박고
     (`graph["117"]["video_latent"] = ["131", 2]`), Face-ID Identity Transfer
     노드(129, `LTXIdentityOverlapConditioning`)가 뒤늦게 identity를
     주입하려 해도 이미 고정된 구조라 override 불가.
   - 결과: 최종 영상이 참조 얼굴이 아니라 앵커의 랜덤 얼굴을 그대로 반영.

원래 설계 의도(`nodes.py:672` 주석)는 "anchor_image=구도/배경 조건,
face_id_ref=identity 조건, 둘을 분리"였음 — 즉 애초에 앵커가 identity를
담당하는 설계가 아니었고, 이 분리를 실제로 구현한 image-lock 강도(1.0)가
identity 주입을 막아버린 것이 버그.

**대조군**: Task 3.2(Flux 앵커 없이 Face-ID LoRA 단독 생성)는 4씬 전부
참조 얼굴과 뚜렷이 일치(STATE.md 기록) — 배경도 발사대/우주유영/외계행성/귀환
전부 다르게 나옴(프롬프트 텍스트만으로).

## 결정된 방향

**Flux 앵커 image-lock을 완전히 제거하고 3.2의 검증된 순수 Face-ID 생성
방식으로 복귀한다.**

- 배경 다양성은 앵커가 아니라 씬 프롬프트 텍스트가 담당했음이 3.2로 이미
  증명됨 — 앵커 제거해도 배경 다양성 손실 없음.
- 앵커는 애초에 identity 정보가 없었음 — 제거해도 identity 손실 없음
  (오히려 identity 주입을 막던 lock이 없어져 정상화됨).
- 부가 이득: Flux 앵커 생성 호출(씬당 실측 ~177초)이 통째로 사라져
  "생성이 너무 오래 걸린다"는 불만도 같이 해결됨.

## 아키텍처 변경

```
Before: node_generate_prompts → node_generate_scene_anchors(Flux 호출) → node_generate_ltx_batch(앵커 lock)
After:  node_generate_prompts → node_classify_faceid_scenes(Flux 호출 없음, 분류만) → node_generate_ltx_batch(3.2 원본 배선)
```

graph.py의 엣지 구조(선형 3단)는 그대로 유지 — 노드 내용만 교체, 재배선 없음.

## 컴포넌트별 변경

| 파일 | 변경 |
|---|---|
| `langgraph/tools.py:655-700` `_build_ltx_faceid_graph` | node 130(`LoadImage` 앵커)/131(`LTXVImgToVideo`) 추가 코드 삭제. `graph["117"]["video_latent"]` / `graph["129"]["positive"/"negative"]`를 `131`로 덮어쓰던 5줄 삭제 → base 워크플로(`ltx_faceid_api.json`) 원본 배선(100 `EmptyLTXVLatentVideo` → 117 → 129←83, 3.2와 동일)이 그대로 유효해짐. `anchor_image` 파라미터 제거. |
| `langgraph/tools.py:751-` `generate_ltx_faceid_batch` | 앵커 이미지 업로드 블록 삭제 — face_id_ref 업로드만 남김. |
| `langgraph/tools.py:501` `generate_scene_anchor` | 함수 삭제 (다른 소비처 없음, grep으로 확인 완료 — state.py의 `anchor_image` 필드가 유일한 소비처였고 그마저 5.3 배치 경로 전용). |
| `langgraph/nodes.py:669` `node_generate_scene_anchors` | Flux 호출 제거, `face_id_ref`/`mode` 분류 로직만 남김. 함수명을 `node_classify_faceid_scenes`로 개명(더 이상 앵커를 생성하지 않으므로). |
| `langgraph/graph.py` | 노드 등록/엣지에서 함수 참조만 개명된 이름으로 교체 (엣지 구조 자체는 불변). |
| `langgraph/state.py:23` `anchor_image` 필드 | 삭제. |
| `Plans.md` 5.2/5.3 행 | "앵커 생성" 문구를 "LTX_FACEID 모드 분류"로 정정, DoD를 새 아키텍처 기준으로 갱신. |
| `.harness/STATE.md` | Task 5.2/5.3 섹션에 재설계 사유(오늘 프레임 비교 증거, 3.2 대조)와 근거 기록. |

## 데이터 플로우

scene dict에서 `anchor_image` 키가 완전히 사라짐. `face_id_ref`/`mode` 계산
로직은 이동만 하고 동작은 동일(입력 face reference가 human/start·ref 역할일
때 LTX_FACEID로 분류하는 기존 조건 그대로 유지).

## 에러 처리

기존 `anchor_path.is_file()` 등 앵커 관련 에러 경로 전부 삭제 대상(더는
존재하지 않는 파일을 참조하던 코드). 새로 추가되는 에러 케이스 없음 —
실패 지점이 하나(Flux 앵커 호출) 줄어드는 효과.

## 씬 프롬프트 문구 수정 (얼굴 크기 문제 해결)

`node_generate_prompts` 또는 씬 프롬프트 생성 시 "camera push-in"류
문구를 피하고 3.2가 확정한 기본값을 유지: "wide/establishing shot",
"expansive background", "character small in frame relative to
environment", 정적 카메라 선호. (재현 테스트로 이미 검증 완료 — push-in
제거만으로 프레임 전체에서 인물 크기 안정적으로 유지됨.)

## 테스트

- `langgraph/tests/test_ltx_faceid_batch.py`(untracked, codex 작성분) —
  앵커 관련 mock/assert 있으면 제거.
- `langgraph/tests/probe_s1_ltx_batch_live.py` — `anchor_image`/
  `skip_anchors` 인자 제거, 단순화.
- `cd langgraph && ./.venv/bin/python driver.py --dry` 회귀 확인.
- 가능하면 라이브 재생성 1씬으로 참조 얼굴과의 일치 여부 육안 재확인.

## 범위 밖 (Non-goals)

- Flux 단에 IP-Adapter/face-ref 조건을 새로 붙여서 앵커+identity를 동시에
  살리는 절충안 — 이번엔 채택 안 함(사용자가 정체성 우선으로 확정, 배경
  다양성은 어차피 텍스트가 담당하므로 앵커 자체가 불필요).
- 90초 전체 영상 조립(TTS mux, 5.4) — 별도 태스크.
