"""count_external_calls()가 ss ESTABLISHED 출력에서 loopback(127.0.0.1/::1/localhost)은
빼고 원격 주소만 세는지 검증 (Task 7.2, docs/PRD.md R9 "External calls:0 실측").

    ./.venv/bin/python tests/test_external_calls.py
"""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dashboard import count_external_calls

_HEADER = "State  Recv-Q Send-Q  Local Address:Port   Peer Address:Port"

_LOCAL_ONLY_SS = "\n".join([
    _HEADER,
    "ESTAB  0      0       127.0.0.1:51000      127.0.0.1:8700",
    "ESTAB  0      0           [::1]:52000          [::1]:8188",
    "ESTAB  0      0       127.0.0.1:53000       localhost:8501",
])

_MIXED_SS = "\n".join([
    _HEADER,
    "ESTAB  0      0       127.0.0.1:51000      127.0.0.1:8700",
    "ESTAB  0      0       10.0.0.5:44012      93.184.216.34:443",
    "ESTAB  0      0       10.0.0.5:44014       142.250.72.14:443",
])


def _fake_run(cmd, remote_output):
    class _Result:
        stdout = remote_output
    assert cmd[:2] == ["ss", "-tn"], f"예상치 못한 커맨드: {cmd}"
    return _Result()


def test_local_only_counts_zero():
    with patch("subprocess.run", lambda cmd, **kw: _fake_run(cmd, _LOCAL_ONLY_SS)):
        assert count_external_calls() == 0, "루프백만 있는데 0이 아님"
    print("ok: 로컬 전용 상태 → external_calls=0")


def test_remote_connections_counted():
    with patch("subprocess.run", lambda cmd, **kw: _fake_run(cmd, _MIXED_SS)):
        assert count_external_calls() == 2, "루프백 제외한 원격 커넥션 카운트 불일치"
    print("ok: 원격 커넥션만 정확히 카운트")


def main():
    test_local_only_counts_zero()
    test_remote_connections_counted()


if __name__ == "__main__":
    main()
