"""Regression tests for /status not masking stopped jobs as running.

Run:
  ./.venv/bin/python tests/test_status_stalled.py
"""
import asyncio
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

os.environ["AGENT_JOBS_DIR"] = tempfile.mkdtemp(prefix="anim_test_jobs_")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import api


class _FakeGraph:
    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.invoked = False

    async def aget_state(self, config):
        return self.snapshot

    async def ainvoke(self, payload, config):
        self.invoked = True


def _snapshot(*, next=(), values=None, interrupts=()):
    task = SimpleNamespace(
        interrupts=[SimpleNamespace(value=i) for i in interrupts]
    )
    return SimpleNamespace(
        next=next,
        values=values or {},
        tasks=[task] if interrupts else [],
    )


async def main():
    api.RUNNING.clear()
    api.ERRORS.clear()

    api.graph = _FakeGraph(_snapshot(
        next=("node_generate_prompts",),
        values={"phase": "planning", "scenes": [{"id": 1}]},
    ))
    stalled = await api.job_status("stalled-job")
    assert stalled["status"] == "error", stalled
    assert "stalled" in stalled["error"], stalled
    assert stalled["next"] == ["node_generate_prompts"], stalled

    recovered = await api.recover_job("stalled-job")
    assert recovered["status"] == "running", recovered
    assert recovered["recovered"] is True, recovered
    assert recovered["next"] == ["node_generate_prompts"], recovered
    await api.RUNNING["stalled-job"]
    assert api.graph.invoked is True
    api.RUNNING.clear()

    api.ERRORS["failed-job"] = "RuntimeError: prompt generation failed"
    api.graph = _FakeGraph(_snapshot(
        values={"phase": "planning"},
        interrupts=[{"checkpoint": "1-4_scene_split"}],
    ))
    failed = await api.job_status("failed-job")
    assert failed["status"] == "error", failed
    assert failed["error"] == "RuntimeError: prompt generation failed", failed

    print("PASS: /status reports stopped jobs as error, not running/stale approval")


if __name__ == "__main__":
    asyncio.run(main())
