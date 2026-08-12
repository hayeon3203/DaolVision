# Phase 2(b) 수동 실행 기록 — LocalAI UI GatewayAgent

날짜: ____ · 실행자: ____

---

## 절차

1. **localai-ui 개발 서버 기동 확인**
   - 터미널에서 `cd /home/admin/DaolVision/localai-ui && npm run dev` 실행 (또는 이미 실행 중이면 `http://localhost:5173`이 응답하는지 확인).
   - GatewayAgent 엔드포인트 확인: `curl http://localhost:8700/health` → `{"status":"ok","graph_loaded":true}` 응답 수신.

2. **로컬 브라우저에서 GatewayAgent 대화 창 이동**
   - `http://localhost:5173/app/gw-agent` 접속 (또는 localai-ui 홈에서 GatewayAgent 채팅 메뉴 클릭).

3. **참조 이미지 첨부**
   - 채팅창 하단 이미지 업로드 버튼을 클릭해 다음 파일 첨부:
     ```
     /home/admin/DaolVision/langgraph/jobs/probe_logo_hw/assets/ref_composite.png
     ```
   - 첨부 확인: UI에 파란 클라우드/나무 로고(DaolFusion) + 초록 배지(NVIDIA)가 있는 워크스테이션 합성 이미지가 표시됨.

4. **시나리오 원문 입력**
   - 채팅창에 다음 텍스트를 그대로 입력하고 전송:
     ```
     시네마틱한 아침 햇살 아래, 사람이 출근 준비를 하는 동안 책상 위 DaolFusion 
     GB10 워크스테이션이 이미 조용히 켜져 데이터를 정리하고 있다. 낮, 사무실에서 사람은 회의와 창작에 
     몰입하고 워크스테이션은 화면에 진행률을 띄운 채 반복 작업을 대신 처리한다. 
     저녁, 사람이 가족과 식탁에 둘러앉아 웃는 동안 워크스테이션은 거실 한쪽에서 
     여전히 조용히 켜져 있다. 밤, 다들 잠든 집 안에서 워크스테이션의 로고만 
     은은히 빛나며 여전히 작동하고 있다.
     ```

5. **체크포인트 1-4 (씬분할 리뷰)**
   - UI가 4개 씬을 분할한 뒤 "승인" 버튼을 표시할 때까지 기다림.
   - 각 씬의 다음 정보를 기록:
     - **UI에 표시된 `subject_type`** (예: human, nonhuman, character 등)
     - **UI에 표시된 `matched_image`** (예: img_0.png)
   - 아래 "기록표" 섹션의 씬별 행에 입력.

6. **체크포인트 2-3 (이미지 리뷰, 해당할 경우)**
   - 만약 UI가 이 단계에서 멈춘다면(M2 분기), 참조 이미지 재확인 후 진행.
   - 표시되는 참조 이미지가 위 Step 3의 `ref_composite.png`와 동일한지 육안 확인.

7. **체크포인트 3-5 (클립 리뷰)**
   - 4개 클립을 순서대로 재생. 각 씬별로:
     - **로고 상태(육안)**를 아래 표에 기록 (예: "파란 로고 선명함", "로고 희미", "로고 소실" 등).
   - 모든 클립 검토 후 "모두 승인(approve_all)" 버튼 클릭.

8. **완료**
   - 최종 영상이 다운로드되거나 경로가 표시될 때까지 기다림.
   - 아래 "최종 영상 경로" 섹션에 기록.

---

## 기록표

| 씬 | UI에 표시된 subject_type | UI에 표시된 matched_image | 로고 상태 (육안) | 비고 |
|---|---|---|---|---|
| 1 | | | | |
| 2 | | | | |
| 3 | | | | |
| 4 | | | | |

---

## 최종 영상 경로

```
____
```

---

## 비교 기준 (참고: Phase 2a 스크립트/API 직호출 기준선)

Task 3(Phase 2a) 실행 결과 요약:
- **subject_type**: 4/4 씬 모두 `nonhuman` (픽스 후, 리스크 1 해결)
- **DaolFusion 로고**: 4/4 씬 우수하게 유지, 완전 소실 없음
- **NVIDIA 배지**: 아이콘 형태 4/4 씬 유지, 워드마크 텍스트는 2/4 씬(1,3)에서 또렷이 판독, 2/4 씬(2,4)에서 흐릿
- **워크스테이션(피사체)**: 4/4 씬 모두 프레임 내내 유지 (Task 2 저녁 씬 완전 소실과 대조)

---

## Phase 2(a)와 다른 점 (있다면)

```
(이 섹션은 실행 후 작성)
예: 로고 유지도 개선/악화, 체크포인트 수 차이, 최종 영상 길이 차이, 기타 시각적 차이 등
```

---

## 기록 작성 완료 후

1. 이 파일을 저장.
2. 필요시 아래 커밋:
   ```bash
   cd /home/admin/DaolVision
   git add langgraph/jobs/probe_logo_hw/phase2b_manual_record.md
   git commit -m "record: Phase 2b 수동 UI 실행 기록 (실행자: ____)"
   ```
