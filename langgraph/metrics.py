"""
LangGraph 영상 에이전트(:8700)의 Prometheus 지표.

hunyuan_server(:8500)의 metrics.py는 '클립 한 개'를 렌더하는 GPU 서버 관점의 지표다.
여기서는 사람이 실제로 받는 '완성 영상 한 편(=job)' 관점의 지표를 수집한다:
  - 시작/완성한 영상 수, 영상당 씬 수, 제작 소요시간(시나리오→최종본)
  - 씬 클립을 어떤 모드(T2V/I2V/STANDIN/SUBJECT_REF)로 생성했는지
  - 사람이 승인 게이트에서 요청한 재생성 횟수

프로세스가 재시작되면 카운터가 0으로 초기화된다. Prometheus는 counter reset을
자동 보정하므로 rate/increase 쿼리는 안전하다. (누적 절대값이 필요하면 이후 영속화)
"""
from prometheus_client import Counter, Gauge, Histogram, generate_latest, CONTENT_TYPE_LATEST

VIDEOS_STARTED = Counter("anim_videos_started_total", "started video jobs")
VIDEOS_FINISHED = Counter("anim_videos_total", "finished video jobs", ["status"])
VIDEO_LAST_DURATION = Gauge("anim_video_last_duration_seconds", "wall time of the last finished video")
VIDEO_DURATION = Histogram(
    "anim_video_duration_seconds", "video job wall time (scenario→final)",
    buckets=(60, 180, 300, 600, 900, 1800, 3600, 7200),
)
SCENES_PER_VIDEO = Histogram(
    "anim_scenes_per_video", "scenes per finished video",
    buckets=(1, 2, 3, 4, 5, 6, 8, 10, 15),
)
CLIPS_GENERATED = Counter("anim_clips_generated_total", "scene clips generated", ["mode"])
REGENERATIONS = Counter("anim_regenerations_total", "human-requested scene regenerations")

# ---- denoising step 집계 (기존 :8500 서버의 step 지표를 영상(job) 단위로 모음) ----
# 클립당 step 수는 요청 시 결정적이다(:8500 T2V/I2V=DEFAULT_STEPS, ComfyUI Stand-In/Subject
# =STANDIN_STEPS) → :8500을 폴링할 필요 없이 정확히 합산한다.
CLIP_STEPS = Counter("anim_clip_steps_total", "denoising steps executed by scene clips", ["mode"])
VIDEO_STEPS = Histogram(
    "anim_video_steps", "total denoising steps per finished video",
    buckets=(4, 8, 20, 40, 60, 80, 120, 200, 400),
)
VIDEO_LAST_STEPS = Gauge("anim_video_last_steps", "total denoising steps of the last finished video")


def video_started():
    VIDEOS_STARTED.inc()


def clip_generated(mode: str):
    CLIPS_GENERATED.labels(mode=mode).inc()


def clip_steps(mode: str, steps: int):
    """클립 한 개가 돌린 denoising step 수를 모드별로 누적."""
    if steps > 0:
        CLIP_STEPS.labels(mode=mode).inc(steps)


def regeneration(count: int):
    if count > 0:
        REGENERATIONS.inc(count)


def video_finished(scenes: int, duration: float | None, steps: int = 0, status: str = "done"):
    VIDEOS_FINISHED.labels(status=status).inc()
    if status == "done":
        SCENES_PER_VIDEO.observe(scenes)
        if duration is not None:
            VIDEO_LAST_DURATION.set(duration)
            VIDEO_DURATION.observe(duration)
        if steps > 0:
            VIDEO_LAST_STEPS.set(steps)
            VIDEO_STEPS.observe(steps)


def render():
    """Prometheus 노출 텍스트 + content type."""
    return generate_latest(), CONTENT_TYPE_LATEST


if __name__ == "__main__":  # 자체 점검: 한 편 만들면 지표가 올바르게 오르는지
    video_started()
    clip_generated("T2V"); clip_steps("T2V", 20)
    clip_generated("STANDIN"); clip_steps("STANDIN", 4)
    regeneration(2)
    video_finished(scenes=2, duration=300.0, steps=24)
    text = generate_latest().decode()
    assert 'anim_videos_started_total 1.0' in text
    assert 'anim_videos_total{status="done"} 1.0' in text
    assert 'anim_clips_generated_total{mode="T2V"} 1.0' in text
    assert 'anim_clip_steps_total{mode="T2V"} 20.0' in text
    assert 'anim_regenerations_total 2.0' in text
    assert 'anim_video_last_duration_seconds 300.0' in text
    assert 'anim_video_last_steps 24.0' in text
    print("metrics self-check ok")
