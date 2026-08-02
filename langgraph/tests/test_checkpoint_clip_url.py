"""_checkpoint_for_client 회귀 테스트.

job 4265fba0에서 3-5_clip_approval 체크포인트가 각 씬의 clip_path를 호스트
절대경로 그대로 클라이언트에 넘겨 프론트가 <video src>로 재생할 방법이 없던
버그 실측. 이 변환이 사라지면 클립 리뷰 UI(AgentClipPreview)가 다시 빈
화면으로 돌아간다.

    cd langgraph && ./.venv/bin/python tests/test_checkpoint_clip_url.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import api


def test_adds_clip_url_from_clip_path():
    checkpoint = {
        "checkpoint": "3-5_clip_approval",
        "message": "x",
        "scenes": [{"id": 1, "clip_path": str(api.tools.JOBS_DIR / "jobX" / "clip1.mp4")}],
    }
    out = api._checkpoint_for_client(checkpoint)
    assert out["scenes"][0]["clip_url"] == "/files/jobX/clip1.mp4"


def test_scene_without_clip_path_untouched():
    checkpoint = {"checkpoint": "1-4_scene_split", "message": "x", "scenes": [{"id": 1, "text": "hi"}]}
    out = api._checkpoint_for_client(checkpoint)
    assert "clip_url" not in out["scenes"][0]


def test_checkpoint_without_scenes_passthrough():
    checkpoint = {"checkpoint": "2-3_x", "message": "x"}
    assert api._checkpoint_for_client(checkpoint) == checkpoint


if __name__ == "__main__":
    test_adds_clip_url_from_clip_path()
    test_scene_without_clip_path_untouched()
    test_checkpoint_without_scenes_passthrough()
    print("test_checkpoint_clip_url: all passed")
