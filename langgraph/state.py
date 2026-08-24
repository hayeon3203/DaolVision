"""
State 스키마 정의
- Phase 1~5 전체를 관통하는 단일 State
- 씬 단위 데이터는 리스트[dict]로 관리 (Send API로 fan-out 시 이 리스트를 순회)
"""
from typing import TypedDict, Literal, Optional
import operator
from typing_extensions import Annotated


class Scene(TypedDict, total=False):
    id: int
    text: str                      # 원본 씬 텍스트
    duration: float                # 초 단위
    mood: str                      # 트랜지션/자막 톤 결정에 사용
    lighting: str                  # 이 씬의 mood를 구체적 조명/노출/그림자/색온도 언어로 번역한 재조명 큐(M3-7)
    matched_image: Optional[str]   # 이 씬에 피사체가 등장하는 ref 파일명 (없으면 T2V)
    image_role: Optional[Literal["start", "ref", "character_ref"]]
    # start=사진 구도로 시작 / ref=사람 얼굴 identity / character_ref=비인간 캐릭터·제품 전체 참조
    subject_type: Optional[Literal["human", "nonhuman", "none"]]  # 라우팅 진실원천(캡션 기반 보정)
    setting: str                   # 이 씬의 장소/배경. 추출 누락 시 해당 씬 원문으로 폴백
    prompt: str                    # Phase 2에서 생성된 최종 프롬프트
    negative_prompt: Optional[str] # I2V 폴백(mode=I2V) 전용 커스텀 negative — 없으면 tools의
                                    # 기본 negative(worst quality 등) 사용. 제품 identity 보호처럼
                                    # 씬별로 특정 방향(예: "wine bottle")을 밀어내야 할 때만 채움
                                    # (2026-08-12 음료 광고 스파이크, 씬3a 와인병 드리프트 대응).
    face_id_ref: Optional[str]     # LTX Face-ID에 별도 첨부할 사람 identity 참조 파일명
    mode: Literal["I2V", "T2V", "STANDIN", "SUBJECT_REF", "LTX_FACEID",
                  "PRODUCT_ASSEMBLY", "PERSON_ASSEMBLY"]
    # PRODUCT_ASSEMBLY: 제품 참조(character_ref)와 인물 참조(face_id_ref)가 함께 붙은 씬.
    # 배경 생성 → 제품 픽셀 Pillow 합성 → Kontext 재통합 → LTX I2V로 이어지는 A노선
    # (tools.generate_product_scene_clip). subject_ref(Wan)는 참조에 없는 새 요소를
    # 못 그려서 이 조합에 못 쓴다(2026-08-12 스파이크 결론).
    # PERSON_ASSEMBLY: 제품이 화면에 없는 인물 씬인데 Face-ID 정원(FACEID_MAX_SCENES)을
    # 넘겨 22B에서 내려온 씬. 같은 A노선을 제품 합성 없이 탄다(배경 T2I → LTX I2V).
    person_appearance: Optional[str]  # 조립 경로 배경 프롬프트에 박을 인물 외형(캡션+의상 lock)
    product_hand_held: Optional[bool]  # 인물이 제품을 손에 쥐는 씬인지(배경·배치가 달라짐)
    clip_path: Optional[str]       # Phase 3 생성 결과
    steps: int                     # 이 클립이 돌린 denoising step 수 (영상당 합산에 사용)
    quality_score: Optional[float]
    quality_flag: Literal["ok", "low_quality", "pending"]
    approved: bool


class GraphState(TypedDict, total=False):
    # Phase 1 입력
    job_id: str
    started_at: float              # 영상 제작 시작 시각(epoch). 완성 시 소요시간 계산에 사용
    script_text: str
    ref_images: list[str]
    ref_captions: dict[str, str]   # 파일명 → 비전모델 캡션 (씬 매칭 + 캐릭터록에 사용)
    wardrobe_locks: dict[str, str] # 사람 ref 파일명 → 사용자가 선언한 고정 의상 설명

    # M2 이미지 생성 분기 (참조 이미지 미첨부 + 이미지 생성 요청 시)
    image_request: str             # 사용자의 자연어 이미지 요청 (형식 강제 없음)
    image_query: str               # 하위호환: image_queries[0]
    image_queries: list[str]       # rewrite된 이미지 생성용 영어 프롬프트 (1개 고정, 리스트로 유지 — 하위호환)
    generated_ref_is_product: bool  # 생성 참조가 제품인가. _image_query_system이 제품 규칙을
                                   # 고른 시점에 확정한다 — 나중에 비전 캡션의 human/nonhuman
                                   # 판정으로 다시 묻지 않기 위해서다. 그 판정은 같은 시나리오를
                                   # 실행마다 다르게 갈랐다(2026-08-23: job dd16ef56은 nonhuman,
                                   # job c87912d8은 human으로 분류돼 노선이 통째로 바뀌었다).
    gen_image_path: str            # 하위호환: gen_image_paths[0]
    gen_image_paths: list[str]     # 생성된 이미지 png 경로들 (승인 게이트 대상)
    gen_image_history: list[str]   # 재생성 시도별 누적 경로. 사용자가 "1차/2차를 비교하고
                                   # 2번째로 결정"할 수 있어야 하는데, 예전엔 매 시도가
                                   # gen_img_0.png를 덮어써서 이전 결과가 물리적으로
                                   # 사라졌다(2026-08-13).

    # Phase 1~2 산출물
    scenes: list[Scene]
    style_bible: Optional[str]     # 전체 영상 공통 스타일 규격(팔레트/조명/톤). 모든 씬 프롬프트에 주입
    character_sheet: Optional[str] # 참조 이미지 없는 job의 주인공 외형 고정문(no-ref 모드).
                                   # 인물이 등장하는 T2V 씬에만 주입 — 참조가 있으면 빈 값

    # Phase 3 재생성 타겟 (사람이 "이 씬만 다시" 요청 시 채워짐)
    regen_target_ids: list[int]

    # Phase 3 결과 병합용 (Send API의 fan-out 결과를 이 키로 reduce)
    clip_results: Annotated[list[Scene], operator.add]

    # Phase 4 결과
    edited_preview_path: Optional[str]

    # Phase 5 결과
    final_video_path: Optional[str]

    # 파이프라인 진행 상태 (OpenWebUI 쪽에 노출용)
    phase: Literal[
        "planning", "prompting", "anchoring", "generating",
        "editing", "rendering", "done"
    ]
