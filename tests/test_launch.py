"""웹 버튼이 띄우는 별도 프로세스."""

import subprocess
from pathlib import Path

from nara.web import launch


def test_launch_makes_the_child_write_utf8_even_to_a_null_device(monkeypatch):
    """분리된 자식의 표준 출력은 NUL이라 윈도우에서는 cp949가 된다. 그러면 요약 줄의
    '—' 한 글자에 UnicodeEncodeError가 나고, 단계 전체가 실패로 집계된다(2026-10-11 20:29)."""
    seen = {}

    def fake_popen(cmd, **kw):
        seen.update(kw, cmd=cmd)

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.delenv("PYTHONUTF8", raising=False)
    launch.launch(["run", "steps", "--step", "dept"], Path("x.db"))
    assert seen["env"]["PYTHONUTF8"] == "1"
    assert seen["stdout"] is subprocess.DEVNULL
    assert seen["cmd"][-4:] == ["--step", "dept", "--db", "x.db"]
