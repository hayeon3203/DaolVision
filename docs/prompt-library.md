# 프롬프트 라이브러리 — 실측 검증된 T2I/T2V 프롬프트 기록

실제 A/B 렌더 테스트로 검증된 프롬프트만 모음. 코드/커밋에 흩어진 걸 참고용으로 한곳에 정리.
각 섹션에 원본 위치(커밋 해시 또는 파일 경로) 표기 — 실제 동작은 원본 코드가 SSOT, 여기는 참고 사본.

## 1. T2I 얼빡샷(face close-up) 방지 — FLUX.1-schnell

**원본:** `langgraph/nodes.py` `_IMG_QUERY_SYSTEM`, `_WIDE_SHOT_SIGNAL`, `_FACE_EMPHASIS_PHRASE` (commit `02dad27`, 2026-08-03)

**검증된 사실(A/B 렌더 테스트):**
- FLUX.1-schnell(4-step distilled)은 "wide shot", "face clearly visible" 같은 모호한 프레이밍 단어를 무시하고 기본적으로 극단적 얼굴 클로즈업을 만든다.
- 기술 용어 하나("24mm lens", "full-body shot")만으로도 부족 — 2026-08-03 A/B에서 head-and-shoulders medium shot으로 회귀 확인.
- 신뢰 가능한 wide shot을 얻으려면 scale cue를 최소 3중으로 중복 명시해야 함:
  1. 피사체가 프레임 안에서 작게(small within the frame)
  2. 카메라와의 구체적 거리(예: several meters from camera)
  3. 배경이 광활함(vast/tall/expansive, stretching far into background)
- **문장 형태가 중요.** 런온(구두점 없는 나열)은 실패, 완결된 문장/콤마절은 성공.
  - 실패 예 (2026-08-03 A/B): `"stands wide in the frame his head-to-boots he is small within the frame several meters from camera the background stretches far into the background"`
  - 성공 예: `"stands small within the frame, several meters from camera, entire body visible head-to-boots, inside a vast dim space stretching far into the background"`
- 얼굴/눈 언급은 wide shot에서 절대 금지 — "face clearly visible" 문구 하나만으로도 다시 클로즈업으로 끌림. 몸 전체가 나오면 얼굴은 자연히 보이는 것으로 취급.
- 클로즈업/포트레이트를 사용자가 명시적으로 요청한 경우에만 얼굴/눈 디테일 서술 허용, 이땐 wide-shot 문구 전부 생략.

**LLM이 그래도 지시를 무시할 때의 방어:** wide-shot 신호(`full-body`, `head-to-boots/toe/feet`, `wide-angle`, `wide shot`, `establishing shot`)가 감지되면 `_strip_face_emphasis_if_wide()`가 "face ... visible" 계열 문구를 정규식으로 결정적 제거.

## 2. LTX Face-ID 씬 프레이밍 기본값 (T2V)

**원본:** `docs/superpowers/plans/2026-07-31-ltx-faceid-anchor-removal.md` Task 5, `langgraph/tests/probe_s1_ltx_batch_live.py` (untracked)

**검증된 사실:** 라이브 재생성 육안 검증(frame 0 vs frame 24 비교)에서 씬 프롬프트에 `"slow camera push-in"` 문구가 있으면 2초 클립 안에서 피사체가 눈에 띄게 확대됨. 3.2에서 검증된 기본값(wide/establishing shot, static camera, character small in frame)으로 통일해야 함.

**검증된 4씬 템플릿 (우주비행사 시나리오, LTX_FACEID 모드):**

```
1. A person astronaut with a transparent helmet visor, facing the camera,
   standing on a sunset launch pad, wide establishing shot, static camera,
   no camera movement, character small in frame relative to environment,
   expansive background.

2. A person astronaut with a transparent helmet visor, facing the camera,
   floating above Earth during a spacewalk, wide cinematic shot, static
   camera, character small in frame relative to environment, stars and
   blue planet filling the expansive background.

3. A person astronaut with a transparent helmet visor, facing the camera,
   standing on a rocky alien planet beneath two moons, wide establishing
   shot, static camera, character small in frame relative to environment,
   expansive violet landscape.

4. A person astronaut with a transparent helmet visor, facing the camera,
   standing at the spacecraft hatch back on Earth, wide triumphant shot,
   static camera, character small in frame relative to environment, warm
   sunrise and recovery crew in the expansive background.
```

공통 요소: `wide/establishing/cinematic shot`, `static camera`(카메라 움직임 없음), `character small in frame relative to environment`, 배경은 항상 `expansive`.

## 3. 우주비행사 시나리오 스크립트 후보 5종 (한국어 story_text A/B)

**원본:** `langgraph/tests/_astronaut_prompt_search.py` (untracked, 1회성 실측)

driver의 `image_roundtrip` 패턴 재사용해 5개 job 순차 실행, 최종 영상 경로+소요시간 비교용.

```
1. 한 청년 우주비행사가 지구를 떠나 우주선을 타고 미지의 행성을 향해 나아간다.
2. 우주비행사가 우주선 창밖으로 지구를 바라보다가, 낯선 행성에 착륙해 첫 발을 내딛는다.
3. 한 우주비행사의 여정. 발사, 우주 비행, 행성 착륙, 그리고 첫 발걸음.
4. 우주비행사가 별들 사이를 항해하다 낯선 행성을 발견하고 조심스럽게 착륙선에서 내린다.
5. 지구를 떠난 한 우주비행사가 광활한 우주를 가로질러 마침내 새로운 세계에 도착한다.
```

앵커 이미지 요청(image_request)으로 쓰인 문구: `"우주비행사 헬멧을 쓴 젊은 남자, 얼굴이 잘 보이는 정면 클로즈업, 사실적인 사진 스타일"` — 앵커는 클로즈업 허용(T2V 씬과 달리 얼굴 참조 자체가 목적이므로 §1의 wide-shot 규칙과 무관).

수동 E2E용 4씬 한국어 스크립트(`langgraph/_manual_faceid_test.py`, untracked):

```
한 우주비행사가 노을 지는 발사대에서 로켓을 타고 이륙한다.
우주로 나가 무중력 상태에서 우주유영을 한다.
낯선 외계 행성에 착륙해 주변을 탐사한다.
임무를 마치고 지구로 귀환한다.
```

## 4. 해상도 A/B용 상세 프롬프트 (style bible 요소 포함 버전)

**원본:** `langgraph/tests/_faceid_resolution_ab.py` (untracked) — 768x768 `match_target` vs 1280x704 `match_target_letterbox` 비교용, 동일 face ref/seed(`440559665`).

```
A young male astronaut standing in the corner of a dark office, Earth looming
silently on the curved wall behind him, his posture leaning forward with one hand
outstretched palm upward toward the planet as if reaching across space, face
neutral expression eyes slightly narrowed gaze fixed on Earth, subtle breath
visible in cold air, camera slowly pulling back from wide establishing view
revealing vast empty office depth and distant desk lights fading into shadows,
composition emphasizing isolation against infinite void, Earth perfectly intact
in background not blurred or abstract, photorealistic cinematic live-action
rendering technique, natural lighting texture density high, surface materials
realistic metallic sheen and reflective visor, line edge treatment clean
non-drawn, shape language organic human form with slight compression from lens,
prop design language functional space suit, camera character wide-angle deep
focus anamorphic lens, color grading desaturated teal-orange palette low
saturation high contrast bleach bypass effect, emotional tone quiet awe Scene
lighting and atmosphere: low-key dim.
```

색보정/렌즈 스타일 문구(`color grading ...`, `camera character ... lens`)는 `b71700a`("fix(prompts): add color grading/lens style to bible")로 style bible에 편입된 패턴 — 씬 프롬프트 뒷부분에 고정 접미사로 붙이는 형태.

## 5. 22B Face-ID vs 13B 비교용 프롬프트

**원본:** `langgraph/tests/compare_22b_vs_13b.py`, `docs/model-selection-i2v.md` "2026-08-02 육안 비교" 절 (commit `379809b`)

```
a person taking photographs in a public garden, wide full-body shot,
bright natural daylight, colorful surroundings
```

seed `1234567890`, 같은 참조 사진(`건호군.jpg`)으로 양쪽 경로 비교. 결과: 22B Face-ID가 얼굴 일관성 확실히 우수 — [model-selection-i2v.md](model-selection-i2v.md) 채택 근거.

## 관련 문서

- [model-selection-i2v.md](model-selection-i2v.md) — I2V 모델 선택 근거, 22B vs 13B 표
- `docs/superpowers/plans/2026-07-31-ltx-faceid-anchor-removal.md` — Face-ID 앵커 제거 설계/근거 전문
