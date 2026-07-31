"""
OOM 배치 오케스트레이터 (Task 4.4, docs/spikes/2.4-oom-residency.md 결정 반영).

Task 2.4 게이트 실측: 전 모델(Ollama 2종+FLUX) 상주 시 118GB/119GB까지 치솟아
프로세스 크래시(OOM-kill 추정)가 났다. 정상상태 크기 합산(85.7GB 추정)보다 실측이
32GB 더 높았던 원인은 백엔드 전환 구간의 동시 이중 상주 — 예: Ollama 모델이 아직
언로드되기 전에 FLUX가 `.to("cuda")` 전환을 시작하는 겹침 — 로 추정됐다.

채택 정책(배치 온디맨드 언로드): 파이프라인은 backend를 llm → t2i → i2v → tts
순서로 사용한다. 이 phase()가 그 전환 지점마다 "직전 backend가 다 비워질 때까지
다음 backend 진입을 미룬다"를 강제해 겹침을 없앤다. 같은 backend 안에서의
동시성(예: 씬 클립 fan-out, tools._gen_semaphore)은 막지 않는다 — 막는 건 오직
서로 다른 backend 사이의 겹침이다.

AGENT_OOM_MODE=resident로 이 게이팅을 끌 수 있다(2.4 실측상 이 GB10에서는
크래시가 재현됐으므로 기본값은 batch).
"""
import asyncio
import os

MODE = os.environ.get("AGENT_OOM_MODE", "batch")  # "batch" | "resident"

LOAD_ORDER = ("llm", "t2i", "i2v", "tts")  # 문서화 목적 — phase()는 순서를 강제하지 않고 겹침만 막는다

_cond = asyncio.Condition()
_active_backend: str | None = None
_inflight = 0
_unload_hooks: dict[str, object] = {}


def register_unload(backend: str, hook) -> None:
    """backend가 다른 backend로 교체될 때 호출할 언로드 콜백 등록(동기/코루틴 둘 다 허용)."""
    _unload_hooks[backend] = hook


def reset(mode: str | None = None) -> None:
    """테스트 전용: 전역 상태 초기화."""
    global MODE, _active_backend, _inflight, _unload_hooks
    if mode is not None:
        MODE = mode
    _active_backend = None
    _inflight = 0
    _unload_hooks = {}


class _Phase:
    def __init__(self, backend: str):
        self.backend = backend

    async def __aenter__(self):
        if MODE == "resident":
            return self
        global _active_backend, _inflight
        async with _cond:
            while _active_backend is not None and _active_backend != self.backend and _inflight > 0:
                await _cond.wait()
            if _active_backend != self.backend:
                hook = _unload_hooks.get(_active_backend) if _active_backend else None
                if hook is not None:
                    result = hook()
                    if asyncio.iscoroutine(result):
                        await result
                _active_backend = self.backend
            _inflight += 1
        return self

    async def __aexit__(self, *exc):
        if MODE == "resident":
            return False
        global _inflight
        async with _cond:
            _inflight -= 1
            _cond.notify_all()
        return False


def phase(backend: str) -> _Phase:
    """이 backend의 로드~사용 구간을 표시. batch 모드에선 직전 backend가 비워질 때까지
    진입을 막고(로드순서 직렬화), 같은 backend끼리는 동시 진입을 허용한다."""
    return _Phase(backend)


if __name__ == "__main__":  # 자체 점검
    async def _demo():
        reset("batch")
        events = []

        async def slow(backend, label, delay=0.02):
            async with phase(backend):
                events.append(f"{label}-start")
                await asyncio.sleep(delay)
                events.append(f"{label}-end")

        unloaded = []
        register_unload("llm", lambda: unloaded.append("llm"))
        await asyncio.gather(slow("llm", "a"), slow("t2i", "b"))
        assert events == ["a-start", "a-end", "b-start", "b-end"], events
        assert unloaded == ["llm"], unloaded
    asyncio.run(_demo())
    print("oom_orchestrator self-check ok")
