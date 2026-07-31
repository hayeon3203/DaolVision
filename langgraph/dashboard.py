"""
:8700 게이트웨이 자립 대시보드 지표 (Task 4.3, docs/PRD.md R9).

- trace: 파이프 각 스텝의 백엔드 URL/모델/vendor/license. vendor·license는 실제 설정된
  모델명에서 동적 판별한다(정적 하드코딩 금지) — LLM_MODEL/VISION_MODEL은 Task 5.1 전까지
  qwen3.5:9b(Alibaba)가 기본값이고, Nemotron-4B 배선 후엔 자동으로 nvidia로 바뀐다.
- gpu: GB10은 unified memory라 `nvidia-smi`의 FB Memory 필드가 N/A → `free` 커맨드로 대체.
  power_limit_w는 이 드라이버(580.142) 기준 GPU 모듈 레벨 자체가 미노출이라 필드 없음.
- external_calls: `ss` ESTABLISHED 커넥션 중 loopback이 아닌 원격 주소 수(실측, PRD Q23-b).
"""
import re
import subprocess

from pydantic import BaseModel

import tools

MODEL_VENDORS = [
    (re.compile(r"nemotron", re.I), "nvidia", "nvidia-open-model-license"),
    (re.compile(r"qwen", re.I), "alibaba", "apache-2.0"),
    (re.compile(r"llama", re.I), "meta", "llama3-community"),
    (re.compile(r"gemma", re.I), "google", "gemma"),
]


def classify_model(model: str) -> tuple[str, str]:
    for pattern, vendor, license_ in MODEL_VENDORS:
        if pattern.search(model):
            return vendor, license_
    return "unknown", "unknown"


class TraceStep(BaseModel):
    step: str
    url: str
    model: str
    vendor: str
    license: str
    vram_gb: float | None = None


class GpuStatus(BaseModel):
    used_gb: float
    total_gb: float
    free_gb: float
    util_percent: float
    temp_c: float
    power_draw_w: float


class DashboardStatus(BaseModel):
    offline: bool
    trace: list[TraceStep]
    gpu: GpuStatus
    external_calls: int


def gpu_mem() -> dict:
    out = subprocess.run(["free", "-b"], capture_output=True, text=True, check=True).stdout
    _, total_b, used_b, free_b = out.splitlines()[1].split()[:4]
    return {"used_gb": int(used_b) / 1e9, "total_gb": int(total_b) / 1e9, "free_gb": int(free_b) / 1e9}


def gpu_status() -> GpuStatus:
    row = subprocess.run(
        ["nvidia-smi", "--query-gpu=utilization.gpu,temperature.gpu,power.draw",
         "--format=csv,noheader,nounits"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    util, temp, power = (float(x) for x in row.split(", "))
    return GpuStatus(**gpu_mem(), util_percent=util, temp_c=temp, power_draw_w=power)


def count_external_calls() -> int:
    """ss ESTABLISHED 아웃바운드 중 127.0.0.1/::1 아닌 원격 주소 수."""
    out = subprocess.run(
        ["ss", "-tn", "state", "established"], capture_output=True, text=True, check=True,
    ).stdout
    count = 0
    for line in out.splitlines()[1:]:
        cols = line.split()
        if len(cols) < 5:
            continue
        host = cols[4].rsplit(":", 1)[0].strip("[]")
        if host not in ("127.0.0.1", "::1", "localhost"):
            count += 1
    return count


def _ollama_step(step: str, url: str, model: str) -> TraceStep:
    vendor, license_ = classify_model(model)
    return TraceStep(step=step, url=url, model=model, vendor=vendor, license=license_)


def build_trace() -> list[TraceStep]:
    return [
        _ollama_step("scene_split", tools.OLLAMA_URL, tools.LLM_MODEL),
        _ollama_step("caption", tools.OLLAMA_GEN_URL, tools.VISION_MODEL),
        TraceStep(step="t2i_anchor", url=tools.T2I_URL, model="flux-schnell",
                   vendor="black-forest-labs", license="apache-2.0"),
        TraceStep(step="i2v_clip", url=tools.COMFYUI_URL, model="LTX-13B-distilled",
                   vendor="lightricks", license="openrail-m"),
        TraceStep(step="tts_narration", url=tools.CHATTERBOX_URL, model="chatterbox-multilingual-v3",
                   vendor="resemble-ai", license="mit"),
    ]


def dashboard_status() -> DashboardStatus:
    external_calls = count_external_calls()
    return DashboardStatus(
        offline=external_calls == 0,
        trace=build_trace(),
        gpu=gpu_status(),
        external_calls=external_calls,
    )


if __name__ == "__main__":  # 자체 점검
    assert classify_model("hf.co/nvidia/NVIDIA-Nemotron-3-Nano-4B-GGUF:Q4_K_M") == ("nvidia", "nvidia-open-model-license")
    assert classify_model("qwen3.5:9b") == ("alibaba", "apache-2.0")
    assert classify_model("mystery-model") == ("unknown", "unknown")
    status = dashboard_status()
    assert status.external_calls >= 0
    assert 0 <= status.gpu.util_percent <= 100
    assert status.gpu.total_gb > 0
    assert len(status.trace) == 5
    print("dashboard self-check ok:", status.model_dump_json())
