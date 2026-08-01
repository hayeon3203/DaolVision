"""Task 6.2 검증: S2 /i2i 출력(base64 PNG)이 그대로 S1 /jobs의 ref_images로 전달돼
_save_ref_images가 유효한 Face-ID 참조 파일로 저장하는지 확인 (S2→S1 연결, PRD R5).
ComfyUI 실호출 없이 tools.generate_i2i_style을 가짜로 교체해 GPU 없이 돈다.

    ./.venv/bin/python tests/test_s2_s1_connection.py
"""
import asyncio
import base64
import os
import sys
import tempfile
from pathlib import Path

os.environ["AGENT_JOBS_DIR"] = tempfile.mkdtemp(prefix="anim_test_jobs_")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # langgraph/ 모듈 import용

import api
import tools


class _FakeUpload:
    def __init__(self, data: bytes):
        self._data = data

    async def read(self) -> bytes:
        return self._data


async def _async_main():
    # ComfyUI가 실제로 만들 astronaut PNG를 흉내낸다 — 바이트 내용 자체가 중요한 게
    # 아니라 "i2i가 반환한 base64가 왜곡 없이 ref 파일로 저장되는지"가 검증 대상.
    fake_astronaut_png = b"\x89PNG\r\n\x1a\n" + b"fake-astronaut-bytes"

    async def fake_i2i(image_bytes, style, seed=None):
        assert style == "cinematic"
        return {
            "image_base64": base64.b64encode(fake_astronaut_png).decode(),
            "width": 1024, "height": 1024,
        }

    tools.generate_i2i_style = fake_i2i

    i2i_result = await api.i2i_style(
        style="cinematic", image=_FakeUpload(b"face-photo-bytes"), seed=None)

    # S2 응답을 그대로 (변환 없이) S1 /jobs의 ref_images 입력으로 사용.
    ref_names = api._save_ref_images("s2s1-connect-job", [i2i_result["image_base64"]])

    assert len(ref_names) == 1, ref_names
    saved = tools.refs_dir("s2s1-connect-job") / ref_names[0]
    assert saved.exists(), "S2 출력이 S1 ref 파일로 저장되지 않음"
    assert saved.read_bytes() == fake_astronaut_png, "저장된 바이트가 S2 출력과 다름"
    print("PASS: S2 /i2i 출력이 S1 ref_images로 손실 없이 전달됨")


def main():
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()
    sys.exit(0)
