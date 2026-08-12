# 음료수 광고 3씬 스파이크 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 첫 프레임 조립(A: T2I 씬 + 실제 제품 픽셀 Pillow 합성 → plain I2V)과 씬 역할 분리(B: 참조 lock 없는 순수 인물 생성)로 subject_ref의 구조적 약점(참조에 없는 새 요소 발명 불가)을 우회할 수 있는지, 농구→갈증→음료 3씬 광고 시나리오로 실측한다. A+B 조합 편집본과 A 단독 편집본 둘 다 산출·비교한다.

**Architecture:** 신규 모델/그래프/의존성 없음. (1) FLUX-schnell(:8501) 캔 제품샷 + DaolFusion 로고 Pillow 합성 + 흰배경 컷아웃으로 정본 제품 자산 1개 생성 — 이후 모든 씬은 이 픽셀 재사용만(재생성 금지). 인물도 FLUX T2I로 새로 생성한 가상 인물 정본(`person_canonical.png`) 1장을 만들어 전 씬 얼굴 참조로 쓴다(사용자 변경 지시 2026-08-12: `건호군.jpg` 대신 신규 생성 인물 — 설계문서 자산 절보다 이 plan이 우선). (2) 씬1(B)은 기존 LTX Face-ID 배치 경로(`tools.generate_ltx_faceid_batch`)로 순수 생성. (3) 씬2/3a/3b(A)는 FLUX T2I 씬 이미지 + 제품 픽셀 Pillow 합성으로 첫 프레임을 만들고 `tools.generate_i2v_fallback_clip`(plain I2V, LTX-13B distilled)으로 움직임만 입힌다. (4) `tools.ffmpeg_concat`으로 편집본 2개 산출, 결과는 설계문서 `## 결과` 섹션 + Plans.md에 기록.

**Tech Stack:** Python 3(`langgraph/.venv`), Pillow, httpx, FLUX.1-schnell(:8501), ComfyUI(:8188, LTX-13B distilled + LTX Face-ID), ffmpeg.

**설계문서:** `docs/superpowers/specs/2026-08-12-beverage-ad-3scene-spike-design.md` — 시나리오·리스크 판정·성공 기준의 원본.

## Global Constraints

- 새 모델·새 ComfyUI 그래프·새 의존성 도입 금지 (설계문서 "범위 밖"). 영상 생성은 기존 `tools.py` 함수(`generate_ltx_faceid_batch`/`generate_i2v_fallback_clip`)와 `_build_flux_kontext_graph` 직호출만 사용. 단, 단독 T2I(:8501 FLUX)는 프로브 스크립트에서 httpx 직접 호출 허용 — `generate_t2i_anchor` 경유 시 LLM 백엔드 의존(`_ensure_english_prompt`)이 추가돼 프로브 격리성이 깨지고, FLUX 서버는 매 요청 언로드 정책이라 oom 게이팅 실익 없음(Task 1 리뷰 판정, 기존 probe HTTP 직호출 관례와 동일 — `probe_logo_hw_recompose.py`의 ComfyUI 폴링도 직호출).
- 실행은 전부 `cd /home/admin/DaolVision/langgraph && ./.venv/bin/python ...` 기준.
- 시작 전 서비스 확인: `curl -sf http://127.0.0.1:8188/system_stats`(ComfyUI), `curl -sf http://127.0.0.1:8501/health`(FLUX). FLUX가 죽어 있으면 `systemctl --user restart flux.service`.
- job_id는 전 태스크 공통 `probe_bev_ad` — 산출물은 `langgraph/jobs/probe_bev_ad/`(gitignored, 스크립트만 커밋).
- 정본 제품 자산(`product_canonical.png`)은 Task 1 이후 **절대 재생성 금지** — 씬 합성은 픽셀 재사용(리사이즈/회전은 매번 정본 원본에서 새로, 중간 결과물 재리사이즈 금지).
- 생성 파일 경로는 전부 실행 로그/기록 표에 남긴다 (feedback: always share generated paths).
- 인물 시드/의상 텍스트 lock: 시드 `20260812` 고정, 의상은 "plain white sleeveless jersey and black shorts"를 씬1·2·3b 프롬프트에 동일하게 명시(씬간 identity 비교 변수 축소).
- 생성 프롬프트는 영어로 스크립트에 직접 작성(FLUX/LTX 모두 영어 프롬프트 경로, `node_generate_prompts` 미사용 — 격리 프로브라 파이프라인 LLM 개입 배제).
- 육안 검증 단계는 기계 Acceptance 불가 — 프레임 캡처 png를 남기고 기록 표에 판정을 적는 것으로 대신한다(Plans.md 규칙: `|| echo skip`류 금지).

---

### Task 1: 정본 자산 — FLUX 캔+로고 합성 컷아웃, FLUX 신규 인물 참조

**Files:**
- Create: `langgraph/tests/probe_bev_ad_assets.py`
- Test: 스크립트 실행 자체가 검증 (산출 이미지 육안 확인)

**Interfaces:**
- Consumes: `/home/admin/DaolVision/DaolFusion_세로_tree.png` (로고 원본, 리사이즈 없이 유지)
- Produces: `langgraph/jobs/probe_bev_ad/assets/product_canonical.png` (RGBA 투명배경 컷아웃, 로고 합성 완료) — Task 3/4가 이 픽셀만 재사용. `assets/person_canonical.png` (FLUX 생성 가상 인물 정본, 정면 상반신) — Task 2 face_id_ref·Task 3 폴백 참조. `can_raw.png`(생성 원본), `product_flat.png`(흰배경 육안확인용)도 함께 산출.

- [ ] **Step 1: 스크립트 작성**

```python
"""음료수 광고 스파이크 — 정본 제품 자산 생성 (2026-08-12 설계문서 Task 1).
1) FLUX-schnell(:8501)로 무지(라벨 없는) 알루미늄 캔 제품샷 생성 — 흰 배경
2) 흰 배경 floodfill 제거로 투명 컷아웃
3) DaolFusion 로고를 Pillow로 캔 몸통에 결정론 합성 (diffusion 무경유)
이 합성본(product_canonical.png)이 정본 — 이후 모든 씬은 픽셀 재사용만.

실행: cd langgraph && ./.venv/bin/python tests/probe_bev_ad_assets.py
결과: jobs/probe_bev_ad/assets/{can_raw.png, product_canonical.png, product_flat.png}
"""
from pathlib import Path

import httpx
from PIL import Image, ImageDraw

ASSETS = Path(__file__).resolve().parent.parent / "jobs" / "probe_bev_ad" / "assets"
T2I_URL = "http://127.0.0.1:8501"
LOGO = Path("/home/admin/DaolVision/DaolFusion_세로_tree.png")
SEED = 20260812

CAN_PROMPT = (
    "studio product photograph of a single sleek aluminum beverage can, "
    "plain blank brushed silver aluminum surface with no label and no text, "
    "standing upright, centered, pure white seamless background, "
    "soft even studio lighting, photorealistic"
)
PERSON_PROMPT = (
    "portrait photograph of a young Korean man in his early twenties, short "
    "black hair, clear frontal face looking at the camera, neutral friendly "
    "expression, head and shoulders, plain light gray background, natural "
    "soft lighting, photorealistic"
)


def _t2i(prompt: str, out: Path, *, width: int, height: int) -> Path:
    if out.exists():
        print(f"[skip] {out} 이미 존재 — 재생성 금지(정본 고정)")
        return out
    timeout = httpx.Timeout(connect=10.0, read=600.0, write=60.0, pool=None)
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(f"{T2I_URL}/generate", json={
            "prompt": prompt, "width": width, "height": height, "seed": SEED})
        resp.raise_for_status()
        png = client.get(f"{T2I_URL}{resp.json()['image_url']}")
        png.raise_for_status()
    ASSETS.mkdir(parents=True, exist_ok=True)
    out.write_bytes(png.content)
    return out


def generate_can() -> Path:
    return _t2i(CAN_PROMPT, ASSETS / "can_raw.png", width=768, height=1024)


def generate_person() -> Path:
    """신규 가상 인물 정본 (사용자 지시: 건호군.jpg 대신 T2I 생성 인물 사용).
    Face-ID 참조로 쓰므로 정면·선명 얼굴이 필수 — 육안 확인 후 불량이면
    SEED 변경 재생성(정본 확정 전에만 허용)."""
    return _t2i(PERSON_PROMPT, ASSETS / "person_canonical.png",
                width=768, height=1024)


def cutout(src: Path, flood_thresh: int = 60) -> Image.Image:
    """흰 배경을 네 모서리 floodfill로 제거해 RGBA 컷아웃 반환.
    ponytail: floodfill 임계 방식 — 캔 내부 흰 하이라이트는 보존됨(경계에서만 침투).
    배경이 안 지워지거나 캔이 침식되면 flood_thresh 조정."""
    img = Image.open(src).convert("RGBA")
    w, h = img.size
    marker = (255, 0, 255, 255)
    for corner in [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]:
        ImageDraw.floodfill(img, corner, marker, thresh=flood_thresh)
    px = img.load()
    for y in range(h):
        for x in range(w):
            if px[x, y] == marker:
                px[x, y] = (0, 0, 0, 0)
    return img.crop(img.getbbox())


def composite_logo(
    can: Image.Image,
    *,
    logo_width_ratio: float = 0.62,
    logo_center_x_ratio: float = 0.50,
    logo_center_y_ratio: float = 0.52,
) -> Image.Image:
    """로고를 캔 몸통 중앙에 합성. 원본 로고를 매번 새로 리사이즈(누적 손실 방지).
    비율 기본값은 육안 확인 후 조정 가능(결정론 — 같은 값이면 항상 같은 결과)."""
    logo = Image.open(LOGO).convert("RGBA")
    cw, ch = can.size
    lw = int(cw * logo_width_ratio)
    lh = int(logo.height * (lw / logo.width))
    logo = logo.resize((lw, lh), Image.LANCZOS)
    lx = int(cw * logo_center_x_ratio - lw / 2)
    ly = int(ch * logo_center_y_ratio - lh / 2)
    out = can.copy()
    out.alpha_composite(logo, (lx, ly))
    return out


def main() -> int:
    raw = generate_can()
    can = cutout(raw)
    canonical = composite_logo(can)
    out = ASSETS / "product_canonical.png"
    canonical.save(out, "PNG")
    flat = Image.new("RGBA", canonical.size, (255, 255, 255, 255))
    flat.alpha_composite(canonical)
    flat_path = ASSETS / "product_flat.png"
    flat.convert("RGB").save(flat_path, "PNG")
    person = generate_person()
    print(f"제품 정본: {out}")
    print(f"육안확인용: {flat_path}")
    print(f"인물 정본: {person}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: 실행 + 육안 확인**

Run: `cd /home/admin/DaolVision/langgraph && ./.venv/bin/python tests/probe_bev_ad_assets.py`
Expected: `정본: .../product_canonical.png` 출력.

`product_flat.png`를 Read 도구로 열어 확인: (1) 캔이 하나만, 온전한 형태로 생성됐는지 — 아니면 `SEED`를 바꿔 `can_raw.png` 지우고 재생성(정본 확정 전이므로 이때만 허용). (2) 컷아웃 경계가 캔을 침식하지 않았는지 — 침식이면 `flood_thresh` 하향. (3) DaolFusion 로고가 캔 몸통 안에 온전히 들어가고 실루엣·색이 원본 그대로인지 — 아니면 `logo_*_ratio` 조정 후 재실행.

`person_canonical.png`도 Read 도구로 확인: 정면·선명한 얼굴 1인, 해부구조 파탄(눈/치아 아티팩트) 없음 — 불량이면 SEED 변경 재생성(인물 확정 전에만 허용, 확정 후 재생성 금지). 이 인물이 이후 모든 씬의 얼굴 참조다.

- [ ] **Step 3: 커밋**

```bash
cd /home/admin/DaolVision
git add langgraph/tests/probe_bev_ad_assets.py
git commit -m "test: 음료 광고 스파이크 정본 제품 자산 생성 프로브"
```

---

### Task 2: 씬1 (B노선) — 농구 운동, LTX Face-ID 순수 생성

**Files:**
- Create: `langgraph/tests/probe_bev_ad_scene1.py`
- Test: 스크립트 실행 자체가 검증 (clip1.mp4 + 프레임 캡처 육안)

**Interfaces:**
- Consumes: `langgraph/jobs/probe_bev_ad/assets/person_canonical.png` (Task 1 인물 정본)
- Produces: `langgraph/jobs/probe_bev_ad/clip1.mp4` — Task 5 편집본(A+B)의 첫 클립. 씬2 identity 비교 기준 프레임 `clip1_*.png`.

- [ ] **Step 1: 스크립트 작성**

```python
"""음료수 광고 스파이크 씬1 (B노선) — 참조 lock 없는 순수 인물 생성.
LTX Face-ID 경로(generate_ltx_faceid_batch)로 얼굴 identity만 걸고
농구 운동 씬을 자유 생성한다. 핵심 관찰: 빠른 스포츠 동작의 팔다리 해부구조.

실행: cd langgraph && ./.venv/bin/python tests/probe_bev_ad_scene1.py
결과: jobs/probe_bev_ad/clip1.mp4
"""
import asyncio
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import tools  # noqa: E402

JOB_ID = "probe_bev_ad"
FACE_SRC = (Path(__file__).resolve().parent.parent / "jobs" / JOB_ID
            / "assets" / "person_canonical.png")
SEED = 20260812

PROMPT = (
    "cinematic sports commercial, a young Korean man wearing a plain white "
    "sleeveless jersey and black shorts playing basketball alone on an outdoor "
    "court in golden late-afternoon light, dribbling fast then leaping for a "
    "jump shot, sweat glistening on his face, dynamic tracking camera, "
    "shallow depth of field"
)


async def main() -> int:
    ref_name = "face.png"
    shutil.copyfile(FACE_SRC, tools.refs_dir(JOB_ID) / ref_name)
    scenes = [{
        "id": 1, "prompt": PROMPT, "duration": 3.0,
        "seed": SEED, "face_id_ref": ref_name,
    }]
    results = await tools.generate_ltx_faceid_batch(JOB_ID, scenes)
    for scene_id, path in results.items():
        print(f"scene {scene_id} -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
```

- [ ] **Step 2: 실행**

Run: `cd /home/admin/DaolVision/langgraph && ./.venv/bin/python tests/probe_bev_ad_scene1.py`
Expected: `scene 1 -> .../jobs/probe_bev_ad/clip1.mp4` 출력, 파일 생성.

- [ ] **Step 3: 프레임 캡처 + 육안 기록**

Run: `cd /home/admin/DaolVision/langgraph/jobs/probe_bev_ad && ffmpeg -y -i clip1.mp4 -vf fps=1 clip1_%02d.png`

캡처 프레임을 Read 도구로 열어 기록: (1) 팔다리 해부구조 정상 여부(손가락/팔 개수), (2) 얼굴이 `person_canonical.png` 인물로 식별되는지, (3) 농구 동작(드리블/슛)이 실제로 렌더됐는지(내용 탈락 없음). 판정을 실행 기록에 표로 남긴다 — Task 5 결과표의 씬1 행.

- [ ] **Step 4: 커밋**

```bash
cd /home/admin/DaolVision
git add langgraph/tests/probe_bev_ad_scene1.py
git commit -m "test: 음료 광고 스파이크 씬1 Face-ID 순수 생성 프로브"
```

---

### Task 3: 씬2 (A노선) — 음료수를 향해 달리기, 첫 프레임 조립 → plain I2V

**Files:**
- Create: `langgraph/tests/probe_bev_ad_scene2.py`
- Test: 스크립트 실행 자체가 검증 (clip2.mp4 + 프레임 캡처 육안)

**Interfaces:**
- Consumes: `langgraph/jobs/probe_bev_ad/assets/product_canonical.png` (Task 1 정본), Task 2의 의상 lock 텍스트(동일 문자열)
- Produces: `langgraph/jobs/probe_bev_ad/clip2.mp4`, 조립 첫 프레임 `assets/scene2_first.png` — Task 5 편집본 두 개 모두의 클립. **최우선 관찰(설계문서 관찰 2): T2I 생성 이미지를 plain I2V 첫 프레임으로 먹일 때 체이닝 불안정 재발 여부.**

- [ ] **Step 1: 스크립트 작성**

```python
"""음료수 광고 스파이크 씬2 (A노선) — 첫 프레임 조립 → plain I2V.
1) FLUX T2I로 "코트 옆 벤치를 향해 달리는 인물" 씬 생성 (제품 없음)
2) 정본 제품 픽셀을 벤치 위에 Pillow 합성 (diffusion 무경유)
3) 조립된 첫 프레임을 plain I2V(LTX-13B, generate_i2v_fallback_clip)에 투입
핵심 관찰: 생성 이미지 → I2V 체이닝 불안정 재발 여부 (재발 시 A 노선 전제 붕괴).

실행: cd langgraph && ./.venv/bin/python tests/probe_bev_ad_scene2.py
결과: jobs/probe_bev_ad/clip2.mp4, assets/scene2_first.png
"""
import asyncio
import shutil
import sys
from pathlib import Path

import httpx
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import tools  # noqa: E402

JOB_ID = "probe_bev_ad"
ASSETS = Path(__file__).resolve().parent.parent / "jobs" / JOB_ID / "assets"
T2I_URL = "http://127.0.0.1:8501"
SEED = 20260812

SCENE_PROMPT = (
    "cinematic sports commercial, a young Korean man wearing a plain white "
    "sleeveless jersey and black shorts running across an outdoor basketball "
    "court toward a wooden bench at the side of the court, the bench top is "
    "empty, golden late-afternoon light, wide shot, photorealistic"
)
I2V_PROMPT = (
    "cinematic, the man runs toward the bench where a silver aluminum can "
    "stands, camera follows him smoothly, golden late-afternoon light"
)


def generate_scene_bg() -> Path:
    out = ASSETS / "scene2_bg.png"
    if out.exists():
        print(f"[skip] {out} 이미 존재")
        return out
    timeout = httpx.Timeout(connect=10.0, read=600.0, write=60.0, pool=None)
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(f"{T2I_URL}/generate", json={
            "prompt": SCENE_PROMPT, "width": 1280, "height": 720, "seed": SEED})
        resp.raise_for_status()
        png = client.get(f"{T2I_URL}{resp.json()['image_url']}")
        png.raise_for_status()
    out.write_bytes(png.content)
    return out


def compose_first_frame(
    bg_path: Path,
    *,
    product_width_ratio: float = 0.055,
    product_center_x_ratio: float = 0.80,
    product_bottom_y_ratio: float = 0.72,
) -> Path:
    """정본 제품 픽셀을 벤치 위에 소형 배치. 비율은 scene2_bg.png의 벤치 위치를
    육안으로 보고 조정한다(결정론 — 반복 조정 허용). 항상 정본 원본에서 새로
    리사이즈(중간 손실 누적 방지)."""
    bg = Image.open(bg_path).convert("RGBA")
    product = Image.open(ASSETS / "product_canonical.png").convert("RGBA")
    bw, bh = bg.size
    pw = int(bw * product_width_ratio)
    ph = int(product.height * (pw / product.width))
    product = product.resize((pw, ph), Image.LANCZOS)
    px = int(bw * product_center_x_ratio - pw / 2)
    py = int(bh * product_bottom_y_ratio - ph)
    bg.alpha_composite(product, (px, py))
    out = ASSETS / "scene2_first.png"
    bg.convert("RGB").save(out, "PNG")
    return out


async def main() -> int:
    bg = generate_scene_bg()
    first = compose_first_frame(bg)
    print(f"조립 첫 프레임: {first}")
    shutil.copyfile(first, tools.refs_dir(JOB_ID) / "scene2_first.png")
    clip = await tools.generate_i2v_fallback_clip(
        job_id=JOB_ID, scene_id=2, prompt=I2V_PROMPT,
        matched_image="scene2_first.png", duration=3.0,
        seed=SEED, force_new=True,
    )
    print(f"scene 2 -> {clip}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
```

- [ ] **Step 2: T2I 씬 생성 + 합성 위치 조정**

Run: `cd /home/admin/DaolVision/langgraph && ./.venv/bin/python tests/probe_bev_ad_scene2.py`

첫 실행 후 `assets/scene2_first.png`를 Read 도구로 열어 확인: (1) 벤치가 실제로 프레임에 있고 제품이 벤치 위에 얹혀 보이는지 — 아니면 `product_*_ratio`를 bg의 실제 벤치 위치에 맞춰 조정, `scene2_first.png`만 재생성(`scene2_bg.png`는 skip 로직으로 고정됨). (2) 씬 인물의 의상이 씬1과 같은 흰 저지·검은 반바지인지, (3) 제품 크기가 "화면에서 작게" 수준인지. 벤치가 아예 없으면 `SCENE_PROMPT` 수정 후 `scene2_bg.png` 삭제하고 재생성(이때 시드 변경 허용, 변경값 기록).

- [ ] **Step 3: 체이닝 안정성 + identity 육안 기록**

Run: `cd /home/admin/DaolVision/langgraph/jobs/probe_bev_ad && ffmpeg -y -i clip2.mp4 -vf fps=1 clip2_%02d.png`

기록 (Task 5 결과표 씬2 행): (1) **체이닝 안정성** — I2V가 조립 첫 프레임의 인물/배경/제품을 유지하는지, 선행 스파이크식 identity 붕괴(다른 물체로 변함/환각)가 재발하는지. (2) 제품(로고 포함)이 영상 내내 원본 실루엣·색으로 식별되는지. (3) 합성부 위화감(조명/그림자/원근)이 정지 프레임과 영상에서 각각 어느 정도인지. (4) 씬1 캡처(clip1_*.png)와 나란히 놓고 인물이 육안상 같은 사람인지.

- [ ] **Step 4 (조건부): identity 불일치 시 Flux Kontext 얼굴 참조 폴백**

Step 3에서 씬1↔2 인물이 명백히 다른 사람이면 — 설계문서 관찰 1의 "구현 시 실측 결정" 지점 — `tests/probe_logo_hw_recompose.py`의 `recompose()` 패턴(`tools._build_flux_kontext_graph` 직호출, `controlnet_strength=0.45`)을 복사해 `assets/person_canonical.png`를 입력으로 "The exact same young man from the reference photo, unchanged face — now wearing a plain white sleeveless jersey and black shorts, full body, running across an outdoor basketball court toward a wooden bench, golden late-afternoon light, wide shot" 프롬프트로 씬 이미지를 재구성하고, 그 결과를 `scene2_bg.png` 대신 써서 Step 1~3을 반복한다. 두 결과(순수 T2I vs Kontext 얼굴 참조)의 identity 판정을 모두 기록 — 어느 쪽이든 한 번의 폴백 시도로 종료(스파이크, 무한 튜닝 금지).

- [ ] **Step 5: 커밋**

```bash
cd /home/admin/DaolVision
git add langgraph/tests/probe_bev_ad_scene2.py
git commit -m "test: 음료 광고 스파이크 씬2 첫프레임 조립 I2V 프로브"
```

---

### Task 4: 씬3a/3b (A노선) — 마시는 장면, 완화 구도 vs 풀동작 대조군

**Files:**
- Create: `langgraph/tests/probe_bev_ad_scene3.py`
- Test: 스크립트 실행 자체가 검증 (clip3.mp4=3a, clip4.mp4=3b + 프레임 캡처)

**Interfaces:**
- Consumes: `assets/product_canonical.png` (Task 1 정본), 의상 lock 텍스트(3b)
- Produces: `langgraph/jobs/probe_bev_ad/clip3.mp4`(**3a**, 편집본에 들어감), `clip4.mp4`(**3b** 대조군, 기록용 — 편집본 제외). scene_id↔구도 매핑(3=3a, 4=3b)을 기록에 명시.

- [ ] **Step 1: 스크립트 작성**

```python
"""음료수 광고 스파이크 씬3 (A노선) — 마시는 장면 2구도.
3a(scene_id=3): 캔+입술 타이트 클로즈업 — 손·입·제품 접촉 최소화 완화 구도.
3b(scene_id=4): 정면 미디엄 풀동작 — 대조군, 실패해도 기록 가치(설계문서).
둘 다 T2I 씬 + 정본 제품 픽셀 합성 → plain I2V.

실행: cd langgraph && ./.venv/bin/python tests/probe_bev_ad_scene3.py
결과: jobs/probe_bev_ad/clip3.mp4(3a), clip4.mp4(3b),
      assets/scene3a_first.png, assets/scene3b_first.png
"""
import asyncio
import shutil
import sys
from pathlib import Path

import httpx
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import tools  # noqa: E402

JOB_ID = "probe_bev_ad"
ASSETS = Path(__file__).resolve().parent.parent / "jobs" / JOB_ID / "assets"
T2I_URL = "http://127.0.0.1:8501"
SEED = 20260812

VARIANTS = {
    # name: (scene_id, T2I prompt, I2V prompt, 합성 파라미터)
    "scene3a": (
        3,
        "cinematic extreme close-up, lower half of a young Korean man's face, "
        "lips slightly parted, chin tilted up, sweat on his jawline, warm "
        "golden backlight, shallow depth of field, empty space in the lower "
        "third of the frame, photorealistic",
        "cinematic close-up, a silver aluminum can tilts up against his lips "
        "as he drinks, subtle swallowing motion, golden light",
        {"width_ratio": 0.30, "center_x_ratio": 0.50, "bottom_y_ratio": 1.02,
         "rotate_deg": -20},
    ),
    "scene3b": (
        4,
        "cinematic medium frontal shot, a young Korean man wearing a plain "
        "white sleeveless jersey and black shorts standing on an outdoor "
        "basketball court, his right arm bent holding his open hand at chest "
        "height, golden late-afternoon light, photorealistic",
        "cinematic, he raises the silver aluminum can to his mouth and drinks "
        "deeply, then lowers it with a satisfied breath",
        {"width_ratio": 0.07, "center_x_ratio": 0.58, "bottom_y_ratio": 0.55,
         "rotate_deg": 0},
    ),
}


def generate_bg(name: str, prompt: str) -> Path:
    out = ASSETS / f"{name}_bg.png"
    if out.exists():
        print(f"[skip] {out} 이미 존재")
        return out
    timeout = httpx.Timeout(connect=10.0, read=600.0, write=60.0, pool=None)
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(f"{T2I_URL}/generate", json={
            "prompt": prompt, "width": 1280, "height": 720, "seed": SEED})
        resp.raise_for_status()
        png = client.get(f"{T2I_URL}{resp.json()['image_url']}")
        png.raise_for_status()
    out.write_bytes(png.content)
    return out


def compose_first_frame(name: str, bg_path: Path, params: dict) -> Path:
    """정본 제품 픽셀 배치. 3a는 크게+기울여(입가 근처), 3b는 손 위치에 소형.
    비율/각도는 bg 육안 확인 후 조정(결정론 — 반복 조정 허용)."""
    bg = Image.open(bg_path).convert("RGBA")
    product = Image.open(ASSETS / "product_canonical.png").convert("RGBA")
    bw, bh = bg.size
    pw = int(bw * params["width_ratio"])
    ph = int(product.height * (pw / product.width))
    product = product.resize((pw, ph), Image.LANCZOS)
    if params["rotate_deg"]:
        product = product.rotate(params["rotate_deg"], expand=True,
                                 resample=Image.BICUBIC)
    px = int(bw * params["center_x_ratio"] - product.width / 2)
    py = int(bh * params["bottom_y_ratio"] - product.height)
    bg.alpha_composite(product, (px, py))
    out = ASSETS / f"{name}_first.png"
    bg.convert("RGB").save(out, "PNG")
    return out


async def main() -> int:
    for name, (scene_id, t2i_prompt, i2v_prompt, params) in VARIANTS.items():
        bg = generate_bg(name, t2i_prompt)
        first = compose_first_frame(name, bg, params)
        print(f"{name} 조립 첫 프레임: {first}")
        ref_name = f"{name}_first.png"
        shutil.copyfile(first, tools.refs_dir(JOB_ID) / ref_name)
        clip = await tools.generate_i2v_fallback_clip(
            job_id=JOB_ID, scene_id=scene_id, prompt=i2v_prompt,
            matched_image=ref_name, duration=3.0, seed=SEED, force_new=True,
        )
        print(f"{name} (scene_id={scene_id}) -> {clip}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
```

- [ ] **Step 2: 실행 + 합성 위치 조정**

Run: `cd /home/admin/DaolVision/langgraph && ./.venv/bin/python tests/probe_bev_ad_scene3.py`

`scene3a_first.png`/`scene3b_first.png`를 Read 도구로 열어 확인: 3a는 캔이 입가 근처(접촉 직전)에, 3b는 캔이 손 위치에 놓였는지. 안 맞으면 `VARIANTS`의 합성 파라미터를 bg의 실제 입/손 위치에 맞춰 조정 후 재실행(bg는 skip 로직으로 고정). bg 자체가 구도 불량(입/손이 프레임 밖)이면 프롬프트 수정 + 해당 `*_bg.png` 삭제 후 재생성(변경 기록).

- [ ] **Step 3: 육안 기록**

Run: `cd /home/admin/DaolVision/langgraph/jobs/probe_bev_ad && ffmpeg -y -i clip3.mp4 -vf fps=1 clip3_%02d.png && ffmpeg -y -i clip4.mp4 -vf fps=1 clip4_%02d.png`

기록 (Task 5 결과표 씬3a/3b 행): (1) 3a — 손·입·제품 접촉 최소화 구도가 실제로 마시는 동작으로 렌더됐는지, 해부구조(입/손) 파탄 여부, 제품 로고 유지 여부. (2) 3b — 실패 양상 구체 기록(어디서 어떻게 깨지는지; 성공 기대 안 함, 실패도 기록 가치로 성공 취급). (3) 두 구도의 체이닝 안정성 비교.

- [ ] **Step 4: 커밋**

```bash
cd /home/admin/DaolVision
git add langgraph/tests/probe_bev_ad_scene3.py
git commit -m "test: 음료 광고 스파이크 씬3 마시기 2구도 프로브"
```

---

### Task 5: 편집본 2개 + 결과 기록 (설계문서·Plans.md)

**Files:**
- Create: `langgraph/tests/probe_bev_ad_edit.py`
- Modify: `docs/superpowers/specs/2026-08-12-beverage-ad-3scene-spike-design.md` (`## 결과` 섹션 추가)
- Modify: `Plans.md` (Week 6 표에 새 태스크 행 추가)

**Interfaces:**
- Consumes: `clip1.mp4`(Task 2), `clip2.mp4`(Task 3), `clip3.mp4`(Task 4의 3a), Task 2~4의 육안 기록 표
- Produces: `langgraph/jobs/probe_bev_ad/ad_combined.mp4`(A+B: 씬1+2+3a), `ad_a_only.mp4`(A 단독: 씬2+3a). 문서 최종화(이후 소비자 없음).

- [ ] **Step 1: 편집 스크립트 작성**

```python
"""음료수 광고 스파이크 — 편집본 2개 산출 (설계문서: A+B 조합본과 A 단독본 비교).
ad_combined.mp4 = 씬1(B) + 씬2(A) + 씬3a(A), ad_a_only.mp4 = 씬2 + 씬3a.
3b(clip4)는 대조군이라 편집본에서 제외. 해상도는 Face-ID 클립(1280x704) 기준으로
통일해 clip1 화질 손실 방지(ffmpeg_concat 독스트링 규칙).

실행: cd langgraph && ./.venv/bin/python tests/probe_bev_ad_edit.py
결과: jobs/probe_bev_ad/ad_combined.mp4, ad_a_only.mp4
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import tools  # noqa: E402

JOB = Path(__file__).resolve().parent.parent / "jobs" / "probe_bev_ad"


def main() -> int:
    c1, c2, c3 = (str(JOB / f"clip{i}.mp4") for i in (1, 2, 3))
    combined = tools.ffmpeg_concat(
        [c1, c2, c3], ["cut", "cut"], str(JOB / "ad_combined.mp4"),
        width=tools.LTX_FACEID_WIDTH, height=tools.LTX_FACEID_HEIGHT)
    a_only = tools.ffmpeg_concat(
        [c2, c3], ["cut"], str(JOB / "ad_a_only.mp4"),
        width=tools.LTX_FACEID_WIDTH, height=tools.LTX_FACEID_HEIGHT)
    print(f"A+B 조합본: {combined}")
    print(f"A 단독본: {a_only}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: 실행 + 비교 시청 기록**

Run: `cd /home/admin/DaolVision/langgraph && ./.venv/bin/python tests/probe_bev_ad_edit.py`
Expected: 두 mp4 경로 출력. 두 편집본의 차이(씬1 유무가 광고 흐름/identity 인상에 주는 영향)를 육안 기록.

- [ ] **Step 3: 설계문서에 `## 결과` 섹션 추가**

`docs/superpowers/specs/2026-08-12-beverage-ad-3scene-spike-design.md` 끝에 추가 — 선행 스파이크(`2026-08-12-agent-logo-hardware-consistency-design.md`)와 동일 형식:

- 씬별 결과표: 씬 / 경로(A·B) / 내용 렌더 여부 / 해부구조 / 제품·로고 상태 / 체이닝 안정성 / 비고.
- 설계문서 "관찰 포인트" 1~3 각각의 실측 답 (특히 관찰 2: 생성 이미지 → plain I2V 체이닝 불안정 재발 여부 — A 노선 전제 판정).
- 성공 기준 6개 항목별 판정.
- 생성 파일 전체 경로 목록 (클립·첫프레임·정본 자산·편집본 — feedback: always share generated paths).
- 후속 권고 (합성 위화감 보정 필요 여부, 정식 기능화 가치).

- [ ] **Step 4: Plans.md에 태스크 행 추가**

Week 6 표에서 6.19 형식(실측 스파이크, 발견/조치/미해결 인라인)을 따라 새 행 추가. **번호는 6.21 사용** — 6.20은 선행 로고+GB10 스파이크 plan Task 5가 예약(Phase 2b 대기로 아직 미기입). Acceptance 컬럼은 육안 검증이라 "-", DoD는 "설계문서 결과 섹션에 A노선 체이닝 판정 + A+B/A단독 비교 기록됨", Status `cc:완료`.

- [ ] **Step 5: 커밋**

```bash
cd /home/admin/DaolVision
git add langgraph/tests/probe_bev_ad_edit.py Plans.md \
  docs/superpowers/specs/2026-08-12-beverage-ad-3scene-spike-design.md
git commit -m "docs+test: 음료 광고 3씬 스파이크 편집본 산출 + 결과 기록"
```
