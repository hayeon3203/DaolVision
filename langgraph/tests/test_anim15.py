"""백엔드 단독 테스트: 15초 4씬 애니메이션, 캐릭터+톤 일관성 검증.

이미지 미제공 → 레퍼런스 1장 자동생성 → 씬1·2·4 I2V 앵커, 씬3(박스)은 T2V.
모든 씬 공통 STYLE 접두사 + 동일 SEED, 마지막에 컬러그레이딩 통일 패스.
Ollama/graph 안 씀 (프롬프트는 여기서 직접 작성). :8500만 사용.

    ./.venv/bin/python test_anim15.py
"""
import asyncio
import subprocess
import time
from pathlib import Path

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # langgraph/ 모듈 import용

import tools

JOB = "test15"
SEED = 42
DUR = 3.7  # 초/씬 × 4 ≈ 15s

# 4씬 공통 — 그림체/색감/조명/렌더를 고정해 씬 간 이질감을 줄인다.
STYLE = ("2D anime style, clean cel shading, cinematic, moody cool color grade, "
         "teal and amber lighting, soft film grain, consistent art style, highly detailed")

REF = f"portrait of a young East Asian woman office worker, late 20s, shoulder-length black hair, upper body facing camera, neutral thoughtful expression, {STYLE}"

SCENES = [  # (id, mode, prompt, 자막)
    (1, "I2V", f"she sits at a desk late at night, glowing monitor, mountains of stacked documents around her, resting chin on hand, slightly frowning, deep in thought, dim office, {STYLE}",
     "어두운 밤, 서류 산더미 속에서 고민하는 그녀"),
    (2, "I2V", f"a bright light suddenly bursts from the monitor illuminating her face, she looks up startled and surprised, wide eyes, {STYLE}",
     "모니터에서 새어나온 밝은 빛, 놀라는 그녀"),
    (3, "T2V", f"small cardboard boxes moving along a conveyor belt, boxes neatly aligning into tidy rows, clean automated factory, {STYLE}",
     "컨베이어 벨트 위 박스들이 착착 정리된다"),
    (4, "I2V", f"the same woman in a bright meeting room finishing a presentation, colleagues applauding, she smiles confidently with a slight smirk, {STYLE}",
     "회의실, 박수 속에 발표를 마치며 미소"),
]


def _fmt_ts(sec: float) -> str:
    h, r = divmod(int(sec), 3600); m, s = divmod(r, 60)
    return f"{h:02}:{m:02}:{s:02},{int((sec-int(sec))*1000):03}"


async def _make_ref():
    """레퍼런스 클립(짧게) 생성 후 선명한 중간 프레임을 refs/ref.png 로 뽑는다."""
    clip = await tools.call_video(JOB, 0, REF, "T2V", None, duration=1.2, seed=SEED)
    ref_png = tools.refs_dir(JOB) / "ref.png"
    subprocess.run(["ffmpeg", "-y", "-ss", "0.6", "-i", clip, "-vframes", "1", str(ref_png)],
                   check=True, capture_output=True)
    print(f"[ref] {ref_png}", flush=True)
    return "ref.png"


def _grade(inp: str, out: str):
    """4개 클립을 하나로 이은 뒤 동일 그레이딩을 얹어 팔레트를 강제 통일."""
    subprocess.run(
        ["ffmpeg", "-y", "-i", inp, "-vf",
         "eq=contrast=1.06:saturation=1.08:gamma=0.98,"
         "colorbalance=rs=-0.03:gs=-0.01:bs=0.04:bm=-0.02",
         "-pix_fmt", "yuv420p", out],
        check=True, capture_output=True)


async def main():
    tools.job_dir(JOB); tools.refs_dir(JOB)
    t0 = time.time()
    ref = await _make_ref()

    paths = []
    for sid, mode, prompt, _ in SCENES:
        img = ref if mode == "I2V" else None
        print(f"[씬 {sid}] {mode} 생성 시작 (+{time.time()-t0:.0f}s)", flush=True)
        p = await tools.call_video(JOB, sid, prompt, mode, img, duration=DUR, seed=SEED)
        print(f"[씬 {sid}] 완료 → {p}", flush=True)
        paths.append(p)

    d = tools.job_dir(JOB)
    concat = str(d / "concat.mp4")
    graded = str(d / "graded.mp4")
    final = str(d / "final15.mp4")

    tools.ffmpeg_concat(paths, ["crossfade"] * (len(paths) - 1), concat)
    _grade(concat, graded)

    # 자막(실패해도 graded 는 남김)
    try:
        durs = [tools._probe_duration(p) for p in paths]
        srt = d / "subs.srt"
        with open(srt, "w", encoding="utf-8") as f:
            t = 0.0
            for i, ((_, _, _, cap), dur) in enumerate(zip(SCENES, durs), 1):
                f.write(f"{i}\n{_fmt_ts(t)} --> {_fmt_ts(t+dur)}\n{cap}\n\n"); t += dur
        tools.burn_subtitles(graded, str(srt), final)
    except Exception as e:
        print(f"[자막 스킵] {e}", flush=True)
        final = graded

    print(f"\n✅ 완료 (+{time.time()-t0:.0f}s): {final}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
