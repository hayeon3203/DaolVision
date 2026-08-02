"""_checkpoint_for_client 회귀 테스트 — 2-3_image_approval 분기.

Task 6.15: 2-3 체크포인트가 gen_image_paths(호스트 절대경로)를 그대로 클라이언트에
넘기면 AgentImagePreview가 <img src>로 렌더링할 방법이 없다. clip_url과 같은 패턴으로
gen_image_urls/gen_image_url을 보강해야 한다.

    cd langgraph && ./.venv/bin/python tests/test_checkpoint_image_url.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import api


def test_adds_gen_image_urls_from_paths():
    checkpoint = {
        "checkpoint": "2-3_image_approval",
        "message": "x",
        "gen_image_paths": [
            str(api.tools.JOBS_DIR / "jobX" / "gen_img_0.png"),
            str(api.tools.JOBS_DIR / "jobX" / "gen_img_1.png"),
        ],
    }
    out = api._checkpoint_for_client(checkpoint)
    assert out["gen_image_urls"] == ["/files/jobX/gen_img_0.png", "/files/jobX/gen_img_1.png"]
    assert out["gen_image_url"] == "/files/jobX/gen_img_0.png"


def test_checkpoint_without_gen_image_paths_untouched():
    checkpoint = {"checkpoint": "1-4_scene_split", "message": "x", "scenes": [{"id": 1, "text": "hi"}]}
    out = api._checkpoint_for_client(checkpoint)
    assert "gen_image_urls" not in out
    assert "gen_image_url" not in out


if __name__ == "__main__":
    test_adds_gen_image_urls_from_paths()
    test_checkpoint_without_gen_image_paths_untouched()
    print("test_checkpoint_image_url: all passed")
